import json
import logging
import os
import re
import sqlite3
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, abort, jsonify, request, send_from_directory
from googleapiclient.errors import HttpError

sys.path.insert(0, str(Path(__file__).parent / "backend"))
import sync as gmail_sync  # noqa: E402
from analyse import SAMPLES, connect  # noqa: E402
from gmail import (block_sender, get_service, list_blocks, trash_message,  # noqa: E402
                   unblock_sender, untrash_message)
from parse import parse_eml  # noqa: E402
from score import (DOMAIN_IN_TEXT, FREE_HOSTING, TRACKERS, auth_result,  # noqa: E402
                   reg_domain, same_org)

SYNC_MINUTES = float(os.environ.get("SYNC_MINUTES", 5))  # 0 disables background sync
log = logging.getLogger("email_analyser")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
app = Flask(__name__, static_folder="static", static_url_path="/static")

_sync_lock = threading.Lock()
sync_status = {"last_sync": None, "last_new": 0, "last_error": None, "running": False,
               "interval_minutes": SYNC_MINUTES}


def db():
    con = connect()
    con.row_factory = sqlite3.Row
    return con


def run_sync():
    """Run one sync unless one is already running. Returns False if skipped."""
    if not _sync_lock.acquire(blocking=False):
        return False
    sync_status["running"] = True
    try:
        # fresh client per run: googleapiclient objects aren't thread-safe
        result = gmail_sync.sync(get_service())
        sync_status.update(last_new=result["new"], last_error=None)
        if result["new"] or result["removed"]:
            log.info("sync: %d new, %d removed in Gmail", result["new"], result["removed"])
    except Exception as err:
        log.exception("sync failed")
        sync_status["last_error"] = str(err)
    finally:
        sync_status.update(last_sync=datetime.now(timezone.utc).isoformat(), running=False)
        _sync_lock.release()
    return True


def sync_loop():
    while True:
        run_sync()
        time.sleep(SYNC_MINUTES * 60)


@app.before_request
def same_origin_only():
    """Block other websites from triggering actions on this local server."""
    if request.method == "POST":
        origin = request.headers.get("Origin")
        if origin and urlparse(origin).netloc != request.host:
            abort(403)
        if not request.is_json:
            abort(415)


@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.get("/api/emails")
def emails():
    with db() as con:
        rows = con.execute(
            "SELECT r.msg_id, source, subject, sender, from_name, date, score, flagged, reasons, "
            "l.label FROM results r LEFT JOIN labels l USING (msg_id) "
            "WHERE r.msg_id NOT IN (SELECT msg_id FROM actions) ORDER BY score DESC"
        ).fetchall()
    return jsonify([{**dict(r), "reasons": json.loads(r["reasons"])} for r in rows])


def describe_link(link, from_dom):
    """Where a link really goes, and why it might be misleading."""
    host = (urlparse(link.href).hostname or "") if "://" in link.href else ""
    dom = reg_domain(link.href) or host
    warning = None
    shown = DOMAIN_IN_TEXT.search(link.text or "")
    shown_dom = reg_domain(shown.group(1)) if shown else ""
    if host and FREE_HOSTING.search(host):
        warning = "free file hosting"
    elif host and re.fullmatch(r"[\d.]+|\[[\da-f:]+\]", host):
        warning = "raw IP address"
    elif shown_dom and dom and not same_org(shown_dom, dom) and dom not in TRACKERS:
        warning = f"text says {shown_dom}"
    elif dom and dom not in TRACKERS and not (from_dom and same_org(dom, from_dom)):
        warning = "different site from sender"
    return {"text": (link.text or "")[:200], "href": link.href[:500], "host": host or link.href[:60],
            "warning": warning}


@app.get("/api/emails/<msg_id>/detail")
def detail(msg_id):
    with db() as con:
        row = con.execute("SELECT source FROM results WHERE msg_id = ?", (msg_id,)).fetchone()
    if not row:
        abort(404)
    path = (SAMPLES / row["source"] / f"{msg_id}.eml").resolve()
    if SAMPLES.resolve() not in path.parents or not path.exists():
        abort(404)
    e = parse_eml(path)
    from_dom = reg_domain(e.from_addr)
    links, seen = [], set()
    for link in e.links:
        if link.href in seen or not link.href.lower().startswith(("http://", "https://")):
            continue
        seen.add(link.href)
        links.append(describe_link(link, from_dom))
    auth = ({k: auth_result(e.auth_results, k) for k in ("spf", "dkim", "dmarc")}
            if e.auth_results else None)
    return jsonify(body=e.body, links=links[:100], link_count=len(links), auth=auth,
                   reply_to=e.reply_to, return_path=e.return_path, attachments=e.attachments)


@app.get("/api/status")
def status():
    return jsonify(sync_status)


@app.post("/api/sync")
def sync_now():
    if not run_sync():
        return jsonify(sync_status), 409  # already running
    return jsonify(sync_status), 200 if not sync_status["last_error"] else 502


@app.post("/api/emails/<msg_id>/label")
def set_label(msg_id):
    """Your verdict on an email: "safe", "scam", or null to clear it."""
    label = request.get_json(silent=True, force=True).get("label")
    if label not in ("safe", "scam", None):
        abort(400)
    with db() as con:
        if not con.execute("SELECT 1 FROM results WHERE msg_id = ?", (msg_id,)).fetchone():
            abort(404)
        if label:
            con.execute("INSERT OR REPLACE INTO labels VALUES (?, ?, datetime('now'))", (msg_id, label))
        else:
            con.execute("DELETE FROM labels WHERE msg_id = ?", (msg_id,))
    return jsonify(ok=True, label=label)


@app.post("/api/emails/<msg_id>/trash")
def trash(msg_id):
    block = bool(request.get_json(silent=True, force=True).get("block"))
    with db() as con:
        row = con.execute("SELECT sender FROM results WHERE msg_id = ?", (msg_id,)).fetchone()
        if not row:
            abort(404)
        try:
            svc = get_service()
            trash_message(svc, msg_id)
            if block:
                block_sender(svc, row["sender"])
        except HttpError as err:
            return jsonify(error=f"Gmail error: {err.reason}"), 502
        except Exception as err:  # e.g. sign-in failed or missing permissions
            return jsonify(error=str(err)), 500
        con.execute(
            "INSERT OR REPLACE INTO actions VALUES (?, ?, datetime('now'))",
            (msg_id, "blocked" if block else "trashed"),
        )
    return jsonify(ok=True, sender=row["sender"], blocked=block)



def gmail_errors(fn):
    """Run a Gmail call; turn failures into a JSON error response."""
    try:
        return fn(), None
    except HttpError as err:
        return None, (jsonify(error=f"Gmail error: {err.reason}"), 502)
    except Exception as err:  # e.g. sign-in failed or missing permissions
        return None, (jsonify(error=str(err)), 500)


@app.get("/api/history")
def history():
    """Everything you (or Gmail) removed, newest first."""
    with db() as con:
        rows = con.execute(
            "SELECT a.msg_id, a.action, a.at, r.subject, r.sender, r.from_name, r.score "
            "FROM actions a LEFT JOIN results r USING (msg_id) ORDER BY a.at DESC LIMIT 300"
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/emails/<msg_id>/undo")
def undo(msg_id):
    """Restore a trashed email; if it was blocked, remove the block too."""
    with db() as con:
        row = con.execute(
            "SELECT a.action, r.sender FROM actions a LEFT JOIN results r USING (msg_id) "
            "WHERE a.msg_id = ?", (msg_id,)).fetchone()
    if not row:
        abort(404)

    def restore():
        svc = get_service()
        try:
            untrash_message(svc, msg_id)
        except HttpError as err:
            if err.resp.status == 404:
                raise RuntimeError("This email was permanently deleted, so it can't be restored.")
            raise
        return unblock_sender(svc, row["sender"]) if row["action"] == "blocked" and row["sender"] else 0

    unblocked, error = gmail_errors(restore)
    if error:
        return error
    with db() as con:
        con.execute("DELETE FROM actions WHERE msg_id = ?", (msg_id,))
    return jsonify(ok=True, unblocked=bool(unblocked), sender=row["sender"])


@app.get("/api/blocked")
def blocked():
    blocks, error = gmail_errors(lambda: list_blocks(get_service()))
    return error or jsonify(sorted({b["sender"] for b in blocks}, key=str.lower))


@app.post("/api/blocked/unblock")
def unblock():
    sender = str(request.get_json(silent=True, force=True).get("sender") or "").strip()
    if not sender:
        abort(400)
    removed, error = gmail_errors(lambda: unblock_sender(get_service(), sender))
    return error or jsonify(ok=True, removed=removed)


if __name__ == "__main__":
    if SYNC_MINUTES > 0:
        threading.Thread(target=sync_loop, daemon=True, name="gmail-sync").start()
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 8000)), debug=False)
