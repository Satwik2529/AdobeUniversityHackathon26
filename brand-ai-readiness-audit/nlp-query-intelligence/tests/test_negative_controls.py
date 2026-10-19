"""The negative controls the master spec calls out by name: evidence
matching must not be fooled by an unrelated use of the same word.
"""
import os
import unittest

import _pathfix  # noqa: F401
from lib import domain_profiler, schema, snapshot_adapter

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _analyze(query):
    snap, digest = snapshot_adapter.load_snapshot(os.path.join(FIXTURES, "shopping-site", "snapshot.json"))
    profile = domain_profiler.build_profile(snap, digest)
    return schema.build_query_result(query, snap, digest, profile)


def _requirement(result, category):
    return next(r for r in result["requirements"] if r["category"] == category)


class NegativeControlsTest(unittest.TestCase):
    def test_premium_laptop_matches_the_product_page_not_the_subscription_page(self):
        result = _analyze("premium laptop")
        qualifier = _requirement(result, "quality_qualifier")
        self.assertEqual(qualifier["evidence"]["status"], "SUPPORTED")
        self.assertNotIn("subscription", (qualifier["evidence"]["url"] or ""))
        self.assertIn("pro-laptop", qualifier["evidence"]["url"])

    def test_premium_alone_does_not_pull_in_the_subscription_page(self):
        # No entity in this query at all, so nothing should be scoped to the
        # unrelated subscription page — the qualifier must come back
        # NOT_ASSESSABLE, never a false SUPPORTED off subscription copy.
        result = _analyze("premium subscription plan")
        self.assertIsNone(result["nlp"]["entity"])
        qualifier = _requirement(result, "quality_qualifier")
        self.assertEqual(qualifier["evidence"]["status"], "NOT_ASSESSABLE")

    def test_student_laptop_matches_genuine_suitability_language(self):
        result = _analyze("student laptop")
        audience = _requirement(result, "audience")
        self.assertEqual(audience["evidence"]["status"], "SUPPORTED")
        self.assertIn("value-laptop", audience["evidence"]["url"])

    def test_student_discount_page_alone_does_not_satisfy_audience_relevance(self):
        # If the ONLY audience-word evidence anywhere were the discount page,
        # the false-context guard must still refuse to call it SUPPORTED.
        # Verified directly against evidence_matcher rather than requiring a
        # fixture with no genuine match, to keep the assertion precise.
        from lib import domain_vocabulary, evidence_index, evidence_matcher
        snap, _ = snapshot_adapter.load_snapshot(os.path.join(FIXTURES, "shopping-site", "snapshot.json"))
        index = evidence_index.EvidenceIndex(snap)
        discount_page = next(p for p in index.pages if "student-discount" in p["url"])
        entity_pages = [discount_page]
        requirement = {"id": "R-TEST", "category": "audience", "key": "students", "raw": "students"}
        concepts = domain_vocabulary.get_vocabulary("shopping")
        evidence = evidence_matcher.match_audience(requirement, entity_pages, index, concepts)
        self.assertNotEqual(evidence["status"], "SUPPORTED")

    def test_cheap_laptop_does_not_invent_a_price_threshold(self):
        result = _analyze("cheap laptop")
        categories = [r["category"] for r in result["requirements"]]
        self.assertNotIn("price_constraint", categories)
        qualifier = _requirement(result, "quality_qualifier")
        self.assertEqual(qualifier["key"], "budget")

    def test_absurd_price_ceiling_is_technically_satisfied_but_flagged_unrealistic(self):
        # "Satisfied" and "meaningfully selective" are different claims --
        # this must not silently read the same as a genuinely tight,
        # realistic constraint like "under ₹60,000".
        absurd = _analyze("laptop under $10,000,000")
        realistic = _analyze("laptop under ₹60,000")
        absurd_price = _requirement(absurd, "price_constraint")
        realistic_price = _requirement(realistic, "price_constraint")
        self.assertEqual(absurd_price["evidence"]["status"], "SUPPORTED")
        self.assertEqual(absurd_price["evidence"]["constraint_realism"], "unrealistic_high")
        self.assertEqual(realistic_price["evidence"]["constraint_realism"], "realistic")
        self.assertLess(absurd["query_quality"]["overall"], realistic["query_quality"]["overall"])

    def test_ram_inside_the_word_programmers_is_not_a_false_match(self):
        # Regression for a real bug caught during the rework: naive
        # substring matching let "ram" match inside "programmers"/
        # "programming". Every phrase check must be word-boundary aware.
        # (The wireless-keyboard page mentions "programmers" but never the
        # standalone word "RAM" anywhere in its own text.)
        from lib import evidence_index, normalizer
        snap, _ = snapshot_adapter.load_snapshot(os.path.join(FIXTURES, "mixed-category-site", "snapshot.json"))
        index = evidence_index.EvidenceIndex(snap)
        page = next(p for p in index.pages if "wireless-keyboard" in p["url"])
        self.assertTrue(normalizer.contains_phrase(page["blob"], "programmers"))
        self.assertFalse(normalizer.contains_phrase(page["blob"], "ram"))


if __name__ == "__main__":
    unittest.main()
