"""Dashboard actions that change Gmail: trash, block, restore. Gmail is faked."""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))
os.environ.pop("DEMO", None)

import analyse  # noqa: E402
import app  # noqa: E402
from parse import Link  # noqa: E402

LOCAL = {"Host": "localhost:8000"}


class Actions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._saved = analyse.DB, analyse.SAMPLES
        analyse.DB = str(Path(self.tmp.name) / "test.db")
        analyse.SAMPLES = Path(self.tmp.name) / "samples"
        (analyse.SAMPLES / "inbox").mkdir(parents=True)
        path = analyse.SAMPLES / "inbox" / "m1.eml"
        shutil.copy(ROOT / "tests" / "fixtures" / "legit_paypal.eml", path)
        with analyse.connect() as con:
            analyse.store(con, path, "inbox")

        self.calls = []
        patches = {
            "get_service": lambda: "svc",
            "block_sender": lambda svc, s: self.calls.append(("block", s)),
            "trash_message": lambda svc, m: self.calls.append(("trash", m)),
            "untrash_message": lambda svc, m: self.calls.append(("untrash", m)),
            "unblock_sender": lambda svc, s: self.calls.append(("unblock", s)) or 1,
        }
        self._real = {k: getattr(app, k) for k in patches}
        for k, v in patches.items():
            setattr(app, k, v)
        self.client = app.app.test_client()

    def tearDown(self):
        for k, v in self._real.items():
            setattr(app, k, v)
        analyse.DB, analyse.SAMPLES = self._saved
        self.tmp.cleanup()

    def post(self, url, body):
        return self.client.post(url, json=body, headers=LOCAL)

    def actions(self):
        return analyse.connect().execute("SELECT msg_id, action FROM actions").fetchall()

    def test_block_then_trash_then_undo(self):
        r = self.post("/api/emails/m1/trash", {"block": True})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.calls, [("block", "service@paypal.com"), ("trash", "m1")])
        self.assertEqual(self.actions(), [("m1", "blocked")])
        self.assertEqual(self.client.get("/api/emails", headers=LOCAL).json, [])

        r = self.post("/api/emails/m1/undo", {})
        self.assertTrue(r.json["unblocked"])
        self.assertEqual(self.calls[2:], [("untrash", "m1"), ("unblock", "service@paypal.com")])
        self.assertEqual(self.actions(), [])

    def test_failed_block_trashes_nothing(self):
        def fail(svc, sender):
            raise RuntimeError("missing permission")
        app.block_sender = fail
        r = self.post("/api/emails/m1/trash", {"block": True})
        self.assertEqual(r.status_code, 500)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.actions(), [])

    def test_unknown_email_404(self):
        self.assertEqual(self.post("/api/emails/nope/trash", {}).status_code, 404)


class LinkWarnings(unittest.TestCase):
    def test_lookalike_link_warned_even_from_same_site(self):
        w = app.describe_link(Link("https://paypa1.com/login", "Log in"), "paypa1.com")["warning"]
        self.assertEqual(w, "lookalike of paypal")

    def test_ipv6_link_is_raw_ip(self):
        self.assertEqual(app.describe_link(Link("http://[::1]/x", "x"), "a.com")["warning"],
                         "raw IP address")


if __name__ == "__main__":
    unittest.main()
