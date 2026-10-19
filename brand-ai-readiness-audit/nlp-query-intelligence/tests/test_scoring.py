import unittest

import _pathfix  # noqa: F401
from lib import scoring


def _req(category, key, status):
    return {"id": "R-%s" % key, "category": category, "key": key, "raw": key,
            "evidence": {"status": status}}


class ScoringTest(unittest.TestCase):
    def test_all_supported_scores_100(self):
        result = scoring.score_requirements([
            _req("entity", "laptop", "SUPPORTED"),
            _req("price_constraint", "price_max", "SUPPORTED"),
        ])
        self.assertEqual(result["overall_score"], 100)

    def test_all_not_found_scores_0(self):
        result = scoring.score_requirements([
            _req("entity", "laptop", "NOT_FOUND"),
        ])
        self.assertEqual(result["overall_score"], 0)

    def test_contradicted_cannot_push_score_below_zero(self):
        result = scoring.score_requirements([
            _req("entity", "laptop", "CONTRADICTED"),
        ])
        self.assertEqual(result["overall_score"], 0)

    def test_not_assessable_excluded_from_denominator(self):
        with_only_assessable = scoring.score_requirements([
            _req("entity", "laptop", "SUPPORTED"),
        ])
        with_extra_not_assessable = scoring.score_requirements([
            _req("entity", "laptop", "SUPPORTED"),
            _req("quality_qualifier", "best", "NOT_ASSESSABLE"),
        ])
        self.assertEqual(with_only_assessable["overall_score"], with_extra_not_assessable["overall_score"])
        self.assertEqual(len(with_extra_not_assessable["not_assessable"]), 1)

    def test_query_with_no_requirements_never_errors(self):
        result = scoring.score_requirements([])
        self.assertEqual(result["overall_score"], 0)
        self.assertEqual(result["breakdown"], [])

    def test_partial_support_scores_between_zero_and_full(self):
        full = scoring.score_requirements([_req("entity", "laptop", "SUPPORTED")])
        partial = scoring.score_requirements([_req("entity", "laptop", "PARTIALLY_SUPPORTED")])
        self.assertLess(partial["overall_score"], full["overall_score"])
        self.assertGreater(partial["overall_score"], 0)

    def test_invalid_requirement_is_NOT_excluded_like_not_assessable(self):
        # This is the exact bug the rework fixes: an entity-only query must
        # not read as 100% just because everything else was waved through.
        entity_only = scoring.score_requirements([_req("entity", "laptop", "SUPPORTED")])
        with_invalid = scoring.score_requirements([
            _req("entity", "laptop", "SUPPORTED"),
            _req("attribute", "ram", "INVALID_REQUIREMENT"),
        ])
        self.assertEqual(entity_only["overall_score"], 100)
        self.assertLess(with_invalid["overall_score"], 100)

    def test_answerability_drops_when_terms_are_unrecognized_even_if_coverage_is_perfect(self):
        result = scoring.score_requirements([
            _req("entity", "laptop", "SUPPORTED"),
            {**_req("unrecognized_term", "wheels", "NOT_ASSESSABLE")},
        ])
        self.assertEqual(result["evidence_coverage"], 100)
        self.assertLess(result["answerability"], 100)

    def test_coverage_and_answerability_are_independent_dimensions(self):
        # A query where the ONE checkable thing is perfectly supported, but
        # half the query was unrecognized: high coverage, degraded
        # answerability -- never collapsed into a single number.
        result = scoring.score_requirements([
            _req("entity", "laptop", "SUPPORTED"),
            {**_req("unrecognized_term", "wheels", "NOT_ASSESSABLE")},
        ])
        self.assertNotEqual(result["evidence_coverage"], result["answerability"])

    def test_confidence_reflects_evidence_quality_not_status(self):
        low_conf = {**_req("entity", "laptop", "SUPPORTED"), "evidence": {"status": "SUPPORTED", "confidence": 0.3}}
        high_conf = {**_req("entity", "laptop", "SUPPORTED"), "evidence": {"status": "SUPPORTED", "confidence": 0.9}}
        self.assertLess(scoring.score_requirements([low_conf])["confidence"],
                         scoring.score_requirements([high_conf])["confidence"])


if __name__ == "__main__":
    unittest.main()
