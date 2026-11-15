import json
import re
import sqlite3

import pandas as pd
import streamlit as st
from googleapiclient.errors import HttpError

from backend.gmail import block_sender, get_service, trash_message


def esc(s):
    """Email fields are attacker-controlled; stop them rendering as markdown/links."""
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|<>~])", r"\\\1", str(s))


@st.cache_resource
def gmail():
    return get_service()


def trash(con, row, block):
    try:
        svc = gmail()
        trash_message(svc, row.msg_id)
        if block:
            block_sender(svc, row.sender)
    except HttpError as err:
        st.error(f"Gmail error: {err}")
        return
    con.execute(
        "INSERT OR REPLACE INTO actions VALUES (?, ?, datetime('now'))",
        (row.msg_id, "blocked" if block else "trashed"),
    )
    con.commit()
    st.session_state.toast = f"Moved to trash{' and blocked ' + row.sender if block else ''}"
    st.rerun()


st.set_page_config(page_title="Email Analyser", layout="wide")
if msg := st.session_state.pop("toast", None):
    st.toast(msg)

con = sqlite3.connect("analyser.db")
con.execute("CREATE TABLE IF NOT EXISTS actions (msg_id TEXT PRIMARY KEY, action TEXT, at TEXT)")
df = pd.read_sql(
    "SELECT * FROM results WHERE msg_id NOT IN (SELECT msg_id FROM actions)", con
)
df["date"] = pd.to_datetime(df["date"], errors="coerce", utc=True)
df["reasons"] = df["reasons"].apply(json.loads)

st.title("Email Analyser")
c1, c2, c3 = st.columns(3)
c1.metric("Analysed", len(df))
c2.metric("Flagged", int(df.flagged.sum()))
c3.metric("Avg score", round(df.score.mean(), 1) if len(df) else 0)

st.subheader("Score by date")
st.scatter_chart(df.dropna(subset=["date"]), x="date", y="score", color="source")

sources = sorted(df.source.unique())
picked = st.multiselect("Source", sources, default=sources)
only_flagged = st.toggle("Flagged only", value=True)
view = df[df.source.isin(picked)]
if only_flagged:
    view = view[view.flagged == 1]

st.subheader(f"Emails ({len(view)})")
for _, row in view.sort_values("score", ascending=False).iterrows():
    with st.expander(f"{row.score:>3} · {esc(row.subject[:80])} · {esc(row.sender)}"):
        st.text(f"From: {row.from_name} <{row.sender}>\nDate: {row.date}\nSource: {row.source}")
        st.text("\n".join(row.reasons))
        b1, b2, _ = st.columns([1, 1, 4])
        if b1.button("Move to trash", key=f"trash-{row.msg_id}"):
            trash(con, row, block=False)
        if b2.button("Block sender & trash", key=f"block-{row.msg_id}", type="primary"):
            trash(con, row, block=True)
