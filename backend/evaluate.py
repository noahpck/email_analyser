"""Measure the scorer against your labels.

Ground truth is the label you gave an email in the dashboard (Safe / Scam). Emails you
haven't labelled fall back to their folder: samples/spam -> scam, anything else -> safe.

Usage (from the project root):
    python backend/evaluate.py              # summary + the emails it gets wrong
    python backend/evaluate.py --all        # also list every email with its reasons
    python backend/evaluate.py --labelled   # only count emails you've labelled
"""
import sys

from analyse import SAMPLES, connect
from parse import parse_eml
from score import FLAG_AT, score

show_all = "--all" in sys.argv
labelled_only = "--labelled" in sys.argv

with connect() as con:
    labels = dict(con.execute("SELECT msg_id, label FROM labels"))

rows = []  # (truth, from_label, result, email)
for folder in sorted(p for p in SAMPLES.iterdir() if p.is_dir()):
    for path in folder.glob("*.eml"):
        e = parse_eml(path)
        if e.msg_id in labels:
            truth, from_label = labels[e.msg_id], True
        elif labelled_only:
            continue
        else:
            truth, from_label = ("scam" if folder.name == "spam" else "safe"), False
        rows.append((truth, from_label, score(e), e))

caught = [x for x in rows if x[0] == "scam" and x[2].score >= FLAG_AT]
missed = [x for x in rows if x[0] == "scam" and x[2].score < FLAG_AT]
false_alarms = [x for x in rows if x[0] == "safe" and x[2].score >= FLAG_AT]
safe_ok = [x for x in rows if x[0] == "safe" and x[2].score < FLAG_AT]
n_scam, n_safe = len(caught) + len(missed), len(false_alarms) + len(safe_ok)

print(f"{len(rows)} emails ({sum(x[1] for x in rows)} labelled by you, "
      f"the rest guessed from their folder)\n")
print(f"  Scams caught:        {len(caught):>4} / {n_scam:<4}"
      f"  ({len(caught) / n_scam:.0%} recall)" if n_scam else "  Scams caught:        no scams")
print(f"  Safe wrongly flagged:{len(false_alarms):>4} / {n_safe:<4}"
      f"  ({len(false_alarms) / n_safe:.1%} false-alarm rate)" if n_safe else "")
if caught or false_alarms:
    print(f"  Precision:           {len(caught) / (len(caught) + len(false_alarms)):.0%}"
          "  (of flagged emails, how many were really scams)")


def show(title, items):
    if not items:
        return
    print(f"\n{title}:")
    for truth, from_label, r, e in sorted(items, key=lambda x: -x[2].score):
        tag = "you said " + truth if from_label else "folder"
        print(f"  {r.score:>3}  [{tag:13}] {e.from_addr[:32]:32} {e.subject[:45]!r}")
        for reason in r.reasons:
            print(f"         {reason}")


show("Missed scams (scored under %d)" % FLAG_AT, missed)
show("False alarms (safe but flagged)", false_alarms)
if show_all:
    show("Caught scams", caught)
    show("Correctly not flagged", safe_ok)
