import json
import logging
import os
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
from analyse import connect  # noqa: E402
from gmail import block_sender, get_service, trash_message  # noqa: E402

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
            "SELECT msg_id, source, subject, sender, from_name, date, score, flagged, reasons "
            "FROM results WHERE msg_id NOT IN (SELECT msg_id FROM actions) ORDER BY score DESC"
        ).fetchall()
    return jsonify([{**dict(r), "reasons": json.loads(r["reasons"])} for r in rows])


@app.get("/api/status")
def status():
    return jsonify(sync_status)


@app.post("/api/sync")
def sync_now():
    if not run_sync():
        return jsonify(sync_status), 409  # already running
    return jsonify(sync_status), 200 if not sync_status["last_error"] else 502


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


if __name__ == "__main__":
    if SYNC_MINUTES > 0:
        threading.Thread(target=sync_loop, daemon=True, name="gmail-sync").start()
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 8000)), debug=False)
