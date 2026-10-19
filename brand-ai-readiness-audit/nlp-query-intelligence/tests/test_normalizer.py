import unittest

import _pathfix  # noqa: F401
from lib import normalizer


class NormalizerTest(unittest.TestCase):
    def test_normalize_text_collapses_and_lowercases(self):
        self.assertEqual(normalizer.normalize_text("  Best   LAPTOP  "), "best laptop")

    def test_find_money_symbol_before(self):
        hits = normalizer.find_money("Priced at ₹60,000 today")
        self.assertEqual(hits, [{"value": 60000.0, "currency": "inr", "raw": "₹60,000"}])

    def test_find_money_symbol_after(self):
        hits = normalizer.find_money("It costs 599 USD")
        self.assertEqual(hits[0]["value"], 599.0)
        self.assertEqual(hits[0]["currency"], "usd")

    def test_find_money_magnitude_k(self):
        hits = normalizer.find_money("under $60k")
        self.assertEqual(hits[0]["value"], 60000.0)

    def test_find_units(self):
        hits = normalizer.find_units("comes with 16GB RAM and 512GB storage")
        units = [(h["value"], h["unit"]) for h in hits]
        self.assertIn((16.0, "gb"), units)
        self.assertIn((512.0, "gb"), units)

    def test_tokenize_strips_punctuation(self):
        self.assertEqual(normalizer.tokenize("Best laptop, under $60k!"),
                          ["best", "laptop", "under", "60k"])


if __name__ == "__main__":
    unittest.main()
