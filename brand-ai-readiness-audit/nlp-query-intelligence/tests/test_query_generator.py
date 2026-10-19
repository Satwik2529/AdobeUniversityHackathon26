import os
import re
import unittest

import _pathfix  # noqa: F401
from lib import domain_profiler, query_generator, snapshot_adapter

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


class QueryGeneratorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap, cls.digest = snapshot_adapter.load_snapshot(os.path.join(FIXTURES, "shopping-site", "snapshot.json"))
        cls.profile = domain_profiler.build_profile(cls.snap, cls.digest)

    def _generate(self):
        return query_generator.generate_queries(self.profile, self.snap, self.digest)

    def test_generates_at_least_one_query_per_populated_family(self):
        result = self._generate()
        families = {q["family"] for q in result["queries"]}
        self.assertIn("entity", families)
        self.assertIn("price", families)
        self.assertIn("attribute", families)
        self.assertIn("audience", families)

    def test_queries_are_unique(self):
        result = self._generate()
        texts = [q["text"] for q in result["queries"]]
        self.assertEqual(len(texts), len(set(texts)))

    def test_generation_is_deterministic(self):
        r1 = self._generate()
        r2 = self._generate()
        self.assertEqual([q["id"] for q in r1["queries"]], [q["id"] for q in r2["queries"]])
        self.assertEqual([q["text"] for q in r1["queries"]], [q["text"] for q in r2["queries"]])

    def test_query_id_is_stable_hash_of_text(self):
        result = self._generate()
        for q in result["queries"]:
            self.assertEqual(q["id"], query_generator._query_id(q["text"]))

    def test_every_generated_query_carries_its_own_precomputed_score(self):
        result = self._generate()
        for q in result["queries"]:
            self.assertIn("evidence_coverage", q)
            self.assertIn("query_quality", q)
            self.assertIn("opportunity_score", q)
            self.assertIn("difficulty", q)

    def test_ranked_by_opportunity_descending(self):
        result = self._generate()
        scores = [q["opportunity_score"] or -1 for q in result["queries"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_sparse_profile_yields_few_or_no_queries_not_an_error(self):
        snap, digest = snapshot_adapter.load_snapshot(os.path.join(FIXTURES, "sparse-site", "snapshot.json"))
        profile = domain_profiler.build_profile(snap, digest)
        result = query_generator.generate_queries(profile, snap, digest)
        self.assertIsInstance(result["queries"], list)  # no exception, honest empty/small result

    def test_mixed_site_never_generates_a_cross_entity_attribute_query(self):
        # No template should ever pair "keyboard" with "ram" -- the
        # per-entity schema makes the invalid combination unreachable at
        # generation time, not just caught after the fact.
        snap, digest = snapshot_adapter.load_snapshot(
            os.path.join(FIXTURES, "mixed-category-site", "snapshot.json"))
        profile = domain_profiler.build_profile(snap, digest)
        result = query_generator.generate_queries(profile, snap, digest)
        for q in result["queries"]:
            text = q["text"].lower()
            if re.search(r"\bkeyboard\b", text):
                self.assertIsNone(re.search(r"\bram\b", text), text)


if __name__ == "__main__":
    unittest.main()
