"""Score every sample and report how well flags match the folder it came from.

Usage (from the project root): python backend/evaluate.py [--show inbox|spam]
"""
import sys
from pathlib import Path

from parse import parse_eml
from score import FLAG_AT, score

show = sys.argv[sys.argv.index("--show") + 1] if "--show" in sys.argv else None
for folder in sorted(p for p in Path("samples").iterdir() if p.is_dir()):
    rows = sorted(((score(e), e) for e in map(parse_eml, folder.glob("*.eml"))),
                  key=lambda x: -x[0].score)
    flagged = [x for x in rows if x[0].score >= FLAG_AT]
    print(f"{folder.name:>6}: {len(flagged):>3}/{len(rows)} flagged")
    if show == folder.name:
        for r, e in rows:
            mark = "FLAG" if r.score >= FLAG_AT else "    "
            print(f"   {mark} {r.score:>3}  {e.from_addr[:35]:35} {e.subject[:45]!r}")
            for reason in r.reasons:
                print(f"              {reason}")
