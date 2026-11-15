"""Incremental Gmail sync: download and score new INBOX/SPAM mail since the last run.

Uses Gmail's history API, so after the first run each sync only fetches what changed.
Usage (from the project root): python backend/sync.py
"""
import base64

from googleapiclient.errors import HttpError

from analyse import SAMPLES, connect, store
from gmail import get_service

LABELS = ("SPAM", "INBOX")  # SPAM first: if a message somehow has both, treat it as spam
FIRST_SYNC_MAX = 100  # per label, on the first run or after history expires


def _get_state(con, key):
    row = con.execute("SELECT value FROM sync_state WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def _set_state(con, key, value):
    con.execute("INSERT OR REPLACE INTO sync_state VALUES (?, ?)", (key, str(value)))


def _label_of(label_ids):
    return next((l for l in LABELS if l in label_ids), None)


def _recent(svc):
    """Latest messages per label, for a full (re)sync."""
    found = {}
    for label in LABELS:
        resp = svc.users().messages().list(
            userId="me", labelIds=[label], maxResults=FIRST_SYNC_MAX).execute()
        for m in resp.get("messages", []):
            found.setdefault(m["id"], label)
    return found


def _changes_since(svc, start):
    """Messages added to INBOX/SPAM, and messages trashed or deleted, since `start`."""
    added, removed, latest = {}, set(), start
    history = svc.users().history()
    req = history.list(userId="me", startHistoryId=start,
                       historyTypes=["messageAdded", "labelAdded", "messageDeleted"])
    while req is not None:
        resp = req.execute()
        latest = resp.get("historyId", latest)
        for h in resp.get("history", []):
            for item in h.get("messagesAdded", []):
                m = item["message"]
                if label := _label_of(m.get("labelIds", [])):
                    added[m["id"]] = label
            for item in h.get("labelsAdded", []):
                if "TRASH" in item.get("labelIds", []):
                    removed.add(item["message"]["id"])
            for item in h.get("messagesDeleted", []):
                removed.add(item["message"]["id"])
        req = history.list_next(req, resp)
    return added, removed, latest


def sync(svc=None):
    """Returns {"new": n, "removed": n}. Raises on Gmail/auth errors."""
    svc = svc or get_service()
    con = connect()
    try:
        start = _get_state(con, "history_id")
        added, removed = {}, set()
        if start:
            try:
                added, removed, latest = _changes_since(svc, start)
            except HttpError as err:
                if err.resp.status != 404:
                    raise
                start = None  # history ids expire after about a week: do a full sync
        if not start:
            # read the history id *before* listing so nothing arriving meanwhile is missed
            latest = svc.users().getProfile(userId="me").execute()["historyId"]
            added = _recent(svc)

        known = {r[0] for r in con.execute("SELECT msg_id FROM results")}
        new = 0
        for msg_id, label in added.items():
            if msg_id in known or msg_id in removed:
                continue
            try:
                raw = svc.users().messages().get(userId="me", id=msg_id, format="raw").execute()["raw"]
            except HttpError as err:
                if err.resp.status == 404:  # deleted before we got to it
                    continue
                raise
            folder = SAMPLES / label.lower()
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{msg_id}.eml"
            path.write_bytes(base64.urlsafe_b64decode(raw))
            store(con, path, folder.name)
            new += 1

        # hide emails you trashed or deleted in Gmail itself
        gone = removed & known
        con.executemany(
            "INSERT OR IGNORE INTO actions VALUES (?, 'removed_in_gmail', datetime('now'))",
            [(m,) for m in gone])
        _set_state(con, "history_id", latest)
        con.commit()
        return {"new": new, "removed": len(gone)}
    finally:
        con.close()


if __name__ == "__main__":
    print(sync())
