import json
import sqlite3
from pathlib import Path

from parse import parse_eml
from score import FLAG_AT, score

con = sqlite3.connect("analyser.db")
con.execute("""CREATE TABLE IF NOT EXISTS results (
    msg_id TEXT PRIMARY KEY, source TEXT, subject TEXT, sender TEXT,
    from_name TEXT, date TEXT, score INTEGER, flagged INTEGER, reasons TEXT)""")

for folder in Path("samples").iterdir():
    if not folder.is_dir():
        continue
    for p in folder.glob("*.eml"):
        e, r = (e := parse_eml(p)), score(e)
        con.execute(
            "INSERT OR REPLACE INTO results VALUES (?,?,?,?,?,?,?,?,?)",
            (e.msg_id, folder.name, e.subject, e.from_addr, e.from_name,
             e.date, r.score, int(r.score >= FLAG_AT), json.dumps(r.reasons)),
        )
con.commit()
print(con.execute("SELECT source, COUNT(*), SUM(flagged) FROM results GROUP BY source").fetchall())