"""The public demo's sample emails should keep scoring the way the demo describes."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from parse import parse_eml  # noqa: E402
from score import FLAG_AT, score  # noqa: E402

SAMPLES = Path(__file__).resolve().parent.parent / "demo" / "samples"
KNOWN_MISS = {"demo-missed-gift-cards"}  # shown in the demo as a scam rules can't catch


class DemoSamples(unittest.TestCase):
    def test_scams_flagged(self):
        for path in sorted((SAMPLES / "spam").glob("*.eml")):
            with self.subTest(path.stem):
                r = score(parse_eml(path))
                if path.stem in KNOWN_MISS:
                    self.assertLess(r.score, FLAG_AT, r.reasons)
                else:
                    self.assertGreaterEqual(r.score, FLAG_AT, r.reasons)

    def test_legit_not_flagged(self):
        for path in sorted((SAMPLES / "inbox").glob("*.eml")):
            with self.subTest(path.stem):
                r = score(parse_eml(path))
                self.assertLess(r.score, FLAG_AT, r.reasons)


if __name__ == "__main__":
    unittest.main()
