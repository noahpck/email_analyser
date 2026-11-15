import json
import re
import sqlite3

import pandas as pd
import streamlit as st


def esc(s):
    """Email fields are attacker-controlled; stop them rendering as markdown/links."""
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|<>~])", r"\\\1", str(s))


st.set_page_config(page_title="Email Analyser", layout="wide")
df = pd.read_sql("SELECT * FROM results", sqlite3.connect("analyser.db"))
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