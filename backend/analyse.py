import json
import sqlite3
from pathlib import Path

from parse import parse_eml
from score import FLAG_AT, score

DB = "analyser.db"
SAMPLES = Path("samples")


def connect():
    con = sqlite3.connect(DB, timeout=30)
    con.execute("""CREATE TABLE IF NOT EXISTS results (
        msg_id TEXT PRIMARY KEY, source TEXT, subject TEXT, sender TEXT,
        from_name TEXT, date TEXT, score INTEGER, flagged INTEGER, reasons TEXT)""")
    con.execute("CREATE TABLE IF NOT EXISTS actions (msg_id TEXT PRIMARY KEY, action TEXT, at TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS sync_state (key TEXT PRIMARY KEY, value TEXT)")
    return con


def store(con, path, source):
    """Parse and score one .eml file and save the result."""
    e = parse_eml(path)
    r = score(e)
    con.execute(
        "INSERT OR REPLACE INTO results VALUES (?,?,?,?,?,?,?,?,?)",
        (e.msg_id, source, e.subject, e.from_addr, e.from_name,
         e.date, r.score, int(r.score >= FLAG_AT), json.dumps(r.reasons)),
    )
    return r


if __name__ == "__main__":
    con = connect()
    for folder in SAMPLES.iterdir():
        if folder.is_dir():
            for p in folder.glob("*.eml"):
                store(con, p, folder.name)
    con.commit()
    print(con.execute("SELECT source, COUNT(*), SUM(flagged) FROM results GROUP BY source").fetchall())
