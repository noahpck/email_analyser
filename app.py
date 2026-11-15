import json
import sqlite3
from urllib.parse import urlparse

from flask import Flask, abort, jsonify, request, send_from_directory
from googleapiclient.errors import HttpError

from backend.gmail import block_sender, get_service, trash_message

DB = "analyser.db"
app = Flask(__name__, static_folder="static", static_url_path="/static")
_gmail = None


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE IF NOT EXISTS actions (msg_id TEXT PRIMARY KEY, action TEXT, at TEXT)")
    return con


def gmail():
    global _gmail
    if _gmail is None:
        _gmail = get_service()
    return _gmail


@app.before_request
def same_origin_only():
    """Block other websites from triggering trash/block on this local server."""
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


@app.post("/api/emails/<msg_id>/trash")
def trash(msg_id):
    block = bool(request.get_json(silent=True, force=True).get("block"))
    with db() as con:
        row = con.execute("SELECT sender FROM results WHERE msg_id = ?", (msg_id,)).fetchone()
        if not row:
            abort(404)
        try:
            svc = gmail()
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
    app.run(host="127.0.0.1", port=8000, debug=False)
