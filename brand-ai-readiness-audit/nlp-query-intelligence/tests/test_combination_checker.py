import os
import unittest

import _pathfix  # noqa: F401
from lib import combination_checker, domain_profiler, schema, snapshot_adapter

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _supported(category, key, url, raw=None):
    return {"id": "R-%s" % key, "category": category, "key": key, "raw": raw or key,
            "evidence": {"status": "SUPPORTED", "url": url}}


class CombinationCheckerUnitTest(unittest.TestCase):
    def test_no_check_with_fewer_than_two_combinable_requirements(self):
        self.assertIsNone(combination_checker.check_combination([_supported("entity", "laptop", "u1")]))
        self.assertIsNone(combination_checker.check_combination(
            [_supported("attribute", "ram", "u1")]))

    def test_same_product_satisfying_all_is_supported(self):
        result = combination_checker.check_combination([
            _supported("price_constraint", "price_max", "https://x/p1"),
            _supported("attribute", "ram", "https://x/p1"),
        ])
        self.assertEqual(result["evidence"]["status"], "SUPPORTED")
        self.assertEqual(result["evidence"]["url"], "https://x/p1")

    def test_different_products_satisfying_each_is_not_found(self):
        result = combination_checker.check_combination([
            _supported("price_constraint", "price_max", "https://x/p1"),
            _supported("attribute", "ram", "https://x/p2"),
        ])
        self.assertEqual(result["evidence"]["status"], "NOT_FOUND")

    def test_three_requirements_two_matching_is_partially_supported(self):
        result = combination_checker.check_combination([
            _supported("price_constraint", "price_max", "https://x/p1"),
            _supported("audience", "students", "https://x/p1"),
            _supported("attribute", "ram", "https://x/p2"),
        ])
        self.assertEqual(result["evidence"]["status"], "PARTIALLY_SUPPORTED")

    def test_entity_and_qualifier_are_never_combined(self):
        # Entity identity and subjective qualifiers aren't per-product facts
        # to reconcile the way price/attribute/audience/use_case are.
        result = combination_checker.check_combination([
            _supported("entity", "laptop", "https://x/p1"),
            _supported("quality_qualifier", "premium", "https://x/p2"),
        ])
        self.assertIsNone(result)


class CombinationCheckerIntegrationTest(unittest.TestCase):
    def test_real_fixture_gap_is_caught(self):
        # Verified by hand against the fixture: "students" + "under
        # ₹60,000" evidence both point to Value Laptop (₹45k/8GB), while
        # "16GB RAM" evidence points to Pro Laptop (₹95k) -- no single
        # product satisfies all three. This is the exact bug the query-
        # generation quality review found.
        snap, digest = snapshot_adapter.load_snapshot(os.path.join(FIXTURES, "shopping-site", "snapshot.json"))
        profile = domain_profiler.build_profile(snap, digest)
        result = schema.build_query_result(
            "laptop for students under ₹60,000 with 16GB RAM", snap, digest, profile)
        combo = next((r for r in result["requirements"] if r["category"] == "combination"), None)
        self.assertIsNotNone(combo)
        self.assertIn(combo["evidence"]["status"], ("NOT_FOUND", "PARTIALLY_SUPPORTED"))
        # And it must show up as a real, actionable coverage gap -- not be
        # silently excluded the way NOT_ASSESSABLE requirements are.
        self.assertLess(result["scoring"]["evidence_coverage"], 100)


if __name__ == "__main__":
    unittest.main()
