import os
import unittest

import _pathfix  # noqa: F401
from lib import domain_profiler, evidence_index, nlp_engine, schema, snapshot_adapter

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


class RequirementValidatorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap, cls.digest = snapshot_adapter.load_snapshot(
            os.path.join(FIXTURES, "mixed-category-site", "snapshot.json"))
        cls.profile = domain_profiler.build_profile(cls.snap, cls.digest)

    def _requirements(self, query):
        return schema.build_query_result(query, self.snap, self.digest, self.profile)["requirements"]

    def _status(self, requirements, category):
        return next(r for r in requirements if r["category"] == category)["evidence"]["status"]

    def test_keyboard_with_ram_is_invalid_requirement_not_a_false_pass(self):
        reqs = self._requirements("Keyboard with RAM")
        self.assertEqual(self._status(reqs, "attribute"), "INVALID_REQUIREMENT")

    def test_laptop_with_ram_is_genuinely_supported(self):
        reqs = self._requirements("Laptop with RAM")
        self.assertEqual(self._status(reqs, "attribute"), "SUPPORTED")

    def test_keyboard_with_backlighting_is_genuinely_supported(self):
        reqs = self._requirements("Keyboard with backlighting")
        self.assertEqual(self._status(reqs, "attribute"), "SUPPORTED")

    def test_invalid_requirement_still_counts_toward_coverage_denominator(self):
        # The load-bearing fix: a schema-mismatched requirement must not be
        # excluded the way NOT_ASSESSABLE is -- otherwise the query would
        # trivially reduce back to a 100% "entity-only" score.
        result = schema.build_query_result("Keyboard with RAM", self.snap, self.digest, self.profile)
        self.assertLess(result["scoring"]["evidence_coverage"], 100)

    def test_no_term_is_ever_silently_dropped(self):
        nlp_result = nlp_engine.analyze_query("Laptop with wheels", self.profile)
        keys = [r["key"] for r in nlp_result["requirements"]]
        self.assertIn("wheels", keys)

    def test_unrecognized_term_resolves_not_assessable_not_a_false_pass(self):
        reqs = self._requirements("Laptop with wheels")
        self.assertEqual(self._status(reqs, "unrecognized_term"), "NOT_ASSESSABLE")


if __name__ == "__main__":
    unittest.main()
