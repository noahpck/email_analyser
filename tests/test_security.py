"""Security guards in the server and Gmail helpers."""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))
os.environ.pop("DEMO", None)

from gmail import SAFE_ADDRESS, block_sender  # noqa: E402


class SafeAddress(unittest.TestCase):
    def test_plain_addresses_allowed(self):
        for a in ("bob@example.com", "a.b+tag@mail.example.co.nz", "x_y-z@sub.domain.io"):
            self.assertTrue(SAFE_ADDRESS.fullmatch(a), a)

    def test_search_syntax_rejected(self):
        for a in ('"x or from:*"@evil.com', '"a b"@evil.com', "a@b.com OR c@d.com",
                  "{a@b.com c@d.com}", "*@evil.com", "", "no-at-sign"):
            self.assertFalse(SAFE_ADDRESS.fullmatch(a), a)

    def test_block_sender_refuses_before_calling_gmail(self):
        with self.assertRaises(ValueError):
            block_sender(None, '"x or from:*"@evil.com')  # svc=None: would crash if reached


class LocalServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app
        cls.client = app.app.test_client()

    def test_rebinding_host_rejected(self):
        r = self.client.get("/api/config", headers={"Host": "evil.example:8000"})
        self.assertEqual(r.status_code, 403)

    def test_localhost_allowed(self):
        r = self.client.get("/api/config", headers={"Host": "localhost:8000"})
        self.assertEqual(r.status_code, 200)

    def test_cross_origin_post_rejected(self):
        r = self.client.post("/api/sync", json={}, headers={
            "Host": "localhost:8000", "Origin": "https://evil.example"})
        self.assertEqual(r.status_code, 403)

    def test_form_post_rejected(self):
        r = self.client.post("/api/sync", data={"a": "1"}, headers={"Host": "localhost:8000"})
        self.assertEqual(r.status_code, 415)

    def test_security_headers(self):
        r = self.client.get("/", headers={"Host": "localhost:8000"})
        self.assertIn("default-src 'self'", r.headers["Content-Security-Policy"])
        self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")


if __name__ == "__main__":
    unittest.main()
