"""Scorer tests. Run from the project root: python -m unittest -v"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from parse import parse_eml  # noqa: E402
from score import (FLAG_AT, claimed_brand, looks_random, reg_domain,  # noqa: E402
                   same_org, score)

FIXTURES = Path(__file__).parent / "fixtures"


def run(name):
    e = parse_eml(FIXTURES / name)
    return e, score(e)


class ScoreFixtures(unittest.TestCase):
    def assertReason(self, result, text):
        self.assertTrue(any(text in r for r in result.reasons),
                        f"no reason containing {text!r} in {result.reasons}")

    def assertNoReason(self, result, text):
        self.assertFalse(any(text in r for r in result.reasons),
                         f"unexpected reason containing {text!r} in {result.reasons}")

    def test_lookalike_phish_is_flagged(self):
        _, r = run("phish_lookalike.eml")
        self.assertGreaterEqual(r.score, FLAG_AT)
        self.assertReason(r, "DMARC failed")
        self.assertReason(r, "resembles paypal")
        self.assertReason(r, "display name claims 'paypal'")
        self.assertReason(r, "raw IP address")
        self.assertReason(r, "link text shows paypal.com")

    def test_real_paypal_is_clean(self):
        _, r = run("legit_paypal.eml")
        self.assertEqual(r.score, 0, r.reasons)

    def test_storage_scam_is_flagged(self):
        _, r = run("storage_scam.eml")
        self.assertGreaterEqual(r.score, FLAG_AT)
        self.assertReason(r, "no real top-level domain")
        self.assertReason(r, "free file hosting")
        self.assertReason(r, "username 'alex.doe'")
        self.assertReason(r, "aren't in To/Cc")
        self.assertReason(r, "Message-ID uses fake domain")
        self.assertReason(r, "scam phrasing")

    def test_marketing_newsletter_is_not_flagged(self):
        # tracker links, ESP Return-Path, helpdesk Reply-To, "free"/"limited", fake "Re:"
        _, r = run("newsletter.eml")
        self.assertLess(r.score, FLAG_AT, r.reasons)
        self.assertNoReason(r, "no SPF/DKIM pass aligned")  # second DKIM signature aligns
        self.assertNoReason(r, "link text shows")
        self.assertNoReason(r, "scam phrasing")
        self.assertNoReason(r, "Message-ID")

    def test_draft_without_auth_headers_is_clean(self):
        _, r = run("draft_no_auth.eml")
        self.assertEqual(r.score, 0, r.reasons)

    def test_forged_lower_auth_header_is_ignored(self):
        e, r = run("forged_auth.eml")
        self.assertNotIn("dmarc=pass", e.auth_results)
        self.assertReason(r, "DMARC failed")
        self.assertReason(r, "SPF fail")

    def test_double_extension_attachment(self):
        e, r = run("attachment.eml")
        self.assertEqual(e.attachments, ["invoice.pdf.exe"])
        self.assertReason(r, "+40 risky attachment invoice.pdf.exe")


class Helpers(unittest.TestCase):
    def test_reg_domain(self):
        self.assertEqual(reg_domain("x@mail.paypal.com"), "paypal.com")
        self.assertEqual(reg_domain("https://a.b.example.co.nz/path"), "example.co.nz")
        self.assertEqual(reg_domain("alert@vneeu.csi"), "")

    def test_looks_random(self):
        for label in ("ylwfrqnox", "cwlgprvkr", "pf0ux39xpf0ux39x", "yxjkx"):
            self.assertTrue(looks_random(label), label)
        for label in ("crunchyroll", "woolworths", "eventbrite", "mcdonalds", "higgsfield", "mail154"):
            self.assertFalse(looks_random(label), label)

    def test_same_org(self):
        self.assertTrue(same_org("seek.com", "seek.co.nz"))
        self.assertFalse(same_org("paypal.com", "paypal.xyz"))
        self.assertFalse(same_org("paypal.com", "paypa1.com"))

    def test_claimed_brand(self):
        self.assertEqual(claimed_brand("Lowe's-Rewards"), "lowes")
        self.assertEqual(claimed_brand("UPS Delivery"), "ups")
        self.assertIsNone(claimed_brand("Python Groups"))  # 'ups' inside a word
        self.assertIsNone(claimed_brand("Alex Doe"))


if __name__ == "__main__":
    unittest.main()
