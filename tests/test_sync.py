"""Sync against a fake Gmail: which emails get imported and which get hidden."""
import base64
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import analyse  # noqa: E402
import sync  # noqa: E402

RAW = (ROOT / "tests" / "fixtures" / "legit_paypal.eml").read_bytes()


class Req:
    def __init__(self, resp):
        self.resp = resp

    def execute(self):
        return self.resp


class FakeGmail:
    """Just enough of the Gmail API for sync.py."""

    def __init__(self, history=(), inbox=()):
        self._history, self._inbox = list(history), list(inbox)

    def users(self):
        return self

    def history(self):
        return self

    def messages(self):
        return self

    def getProfile(self, userId):
        return Req({"historyId": "100"})

    def list(self, userId, labelIds=None, startHistoryId=None, **kw):
        if startHistoryId:  # history().list
            return Req({"historyId": "200", "history": self._history})
        ids = self._inbox if labelIds == ["INBOX"] else []
        return Req({"messages": [{"id": i} for i in ids]})

    def list_next(self, req, resp):
        return None

    def get(self, userId, id, format):
        return Req({"raw": base64.urlsafe_b64encode(RAW).decode()})


def trash(mid, removed=False):
    key = "labelsRemoved" if removed else "labelsAdded"
    return {key: [{"message": {"id": mid}, "labelIds": ["TRASH"]}]}


class ChangesSince(unittest.TestCase):
    def removed(self, *events):
        return sync._changes_since(FakeGmail(history=events), "1")[1]

    def restored(self, *events):
        return sync._changes_since(FakeGmail(history=events), "1")[2]

    def test_trash_hides(self):
        self.assertEqual(self.removed(trash("m1")), {"m1"})

    def test_trash_then_restore_does_not_hide(self):
        self.assertEqual(self.removed(trash("m1"), trash("m1", removed=True)), set())

    def test_restore_then_trash_hides(self):
        self.assertEqual(self.removed(trash("m1", removed=True), trash("m1")), {"m1"})

    def test_restore_is_reported(self):
        self.assertEqual(self.restored(trash("m1"), trash("m1", removed=True)), {"m1"})
        self.assertEqual(self.restored(trash("m1", removed=True), trash("m1")), set())

    def test_permanent_delete_hides(self):
        self.assertEqual(self.removed({"messagesDeleted": [{"message": {"id": "m2"}}]}), {"m2"})

    def test_new_inbox_message_is_added(self):
        added = sync._changes_since(FakeGmail(history=[
            {"messagesAdded": [{"message": {"id": "m3", "labelIds": ["INBOX", "UNREAD"]}}]},
            {"messagesAdded": [{"message": {"id": "m4", "labelIds": ["SENT"]}}]},
        ]), "1")[0]
        self.assertEqual(added, {"m3": "INBOX"})


class FullSync(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._saved = analyse.DB, sync.SAMPLES
        analyse.DB = str(Path(self.tmp.name) / "test.db")
        sync.SAMPLES = Path(self.tmp.name) / "samples"

    def tearDown(self):
        analyse.DB, sync.SAMPLES = self._saved
        self.tmp.cleanup()

    def test_first_sync_imports_and_saves_bookmark(self):
        self.assertEqual(sync.sync(FakeGmail(inbox=["a1", "a2"])), {"new": 2, "removed": 0})
        con = analyse.connect()
        self.assertEqual(con.execute("SELECT COUNT(*) FROM results").fetchone()[0], 2)
        self.assertEqual(con.execute("SELECT value FROM sync_state").fetchone()[0], "100")

    def test_one_bad_email_does_not_block_the_rest(self):
        real_store = sync.store

        def flaky_store(con, path, source):
            if path.stem == "bad":
                raise ValueError("unparseable")
            return real_store(con, path, source)

        sync.store = flaky_store
        try:
            result = sync.sync(FakeGmail(inbox=["bad", "good"]))
        finally:
            sync.store = real_store
        self.assertEqual(result["new"], 1)
        # bookmark still saved, so the next sync moves on instead of retrying forever
        self.assertEqual(analyse.connect().execute("SELECT value FROM sync_state").fetchone()[0], "100")
        # and its file is gone, so analyse.py / evaluate.py don't crash on it later
        self.assertEqual([p.stem for p in sync.SAMPLES.glob("*/*.eml")], ["good"])

    def test_restored_in_gmail_shows_again(self):
        sync.sync(FakeGmail(inbox=["a1"]))
        sync.sync(FakeGmail(history=[trash("a1")]))
        con = analyse.connect()
        self.assertEqual(con.execute("SELECT action FROM actions").fetchall(), [("removed_in_gmail",)])
        sync.sync(FakeGmail(history=[trash("a1", removed=True)]))
        self.assertEqual(con.execute("SELECT COUNT(*) FROM actions").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
