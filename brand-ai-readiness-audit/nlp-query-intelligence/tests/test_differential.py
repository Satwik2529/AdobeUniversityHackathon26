import os
import unittest

import _pathfix  # noqa: F401
from lib import differential, domain_profiler, schema, snapshot_adapter

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _analyze(query):
    snap, digest = snapshot_adapter.load_snapshot(os.path.join(FIXTURES, "shopping-site", "snapshot.json"))
    profile = domain_profiler.build_profile(snap, digest)
    return schema.build_query_result(query, snap, digest, profile)


class DifferentialTest(unittest.TestCase):
    def test_adding_a_requirement_is_reported_as_added(self):
        a = _analyze("laptop")
        b = _analyze("laptop with 16gb ram")
        cmp = differential.compare_two(a, b)
        added_categories = [r["category"] for r in cmp["added_requirements"]]
        self.assertIn("attribute", added_categories)

    def test_score_delta_matches_scoring_difference(self):
        a = _analyze("laptop")
        b = _analyze("laptop with 16gb ram")
        cmp = differential.compare_two(a, b)
        self.assertEqual(cmp["score_delta"], b["scoring"]["overall_score"] - a["scoring"]["overall_score"])

    def test_compare_many_returns_a_flat_table(self):
        results = [_analyze("laptop"), _analyze("premium laptop"), _analyze("student laptop")]
        table = differential.compare_many(results)
        self.assertEqual(len(table["queries"]), 3)


if __name__ == "__main__":
    unittest.main()
