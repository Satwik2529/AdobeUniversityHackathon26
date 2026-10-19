import unittest

import _pathfix  # noqa: F401
from lib import query_quality


def _req(category, status, **evidence_extra):
    return {"category": category, "evidence": {"status": status, **evidence_extra}}


ENTITY = {"key": "laptop", "text": "laptop"}


class QueryQualityTest(unittest.TestCase):
    def test_query_with_no_entity_has_zero_testability(self):
        result = query_quality.compute_query_quality(
            {"intent": "general"}, [_req("unrecognized_term", "NOT_ASSESSABLE")], entity_requirement=None)
        self.assertEqual(result["factors"]["testability"], 0)

    def test_query_with_entity_has_full_testability(self):
        result = query_quality.compute_query_quality(
            {"intent": "recommendation"}, [_req("entity", "SUPPORTED")], entity_requirement=ENTITY)
        self.assertEqual(result["factors"]["testability"], 100)

    def test_unrecognized_terms_reduce_domain_relevance(self):
        clean = query_quality.compute_query_quality(
            {"intent": "general"}, [_req("entity", "SUPPORTED")], entity_requirement=ENTITY)
        noisy = query_quality.compute_query_quality(
            {"intent": "general"},
            [_req("entity", "SUPPORTED"), _req("unrecognized_term", "NOT_ASSESSABLE")],
            entity_requirement=ENTITY,
        )
        self.assertLess(noisy["factors"]["domain_relevance"], clean["factors"]["domain_relevance"])

    def test_unrealistic_price_constraint_reduces_realism(self):
        realistic = query_quality.compute_query_quality(
            {"intent": "general"},
            [_req("entity", "SUPPORTED"), _req("price_constraint", "SUPPORTED", constraint_realism="realistic")],
            entity_requirement=ENTITY,
        )
        unrealistic = query_quality.compute_query_quality(
            {"intent": "general"},
            [_req("entity", "SUPPORTED"),
             _req("price_constraint", "SUPPORTED", constraint_realism="unrealistic_high")],
            entity_requirement=ENTITY,
        )
        self.assertLess(unrealistic["factors"]["realism"], realistic["factors"]["realism"])
        self.assertLess(unrealistic["overall"], realistic["overall"])

    def test_overall_is_the_documented_weighted_sum(self):
        result = query_quality.compute_query_quality(
            {"intent": "recommendation"}, [_req("entity", "SUPPORTED")], entity_requirement=ENTITY)
        expected = round(sum(result["factors"][k] * result["weights"][k] for k in result["weights"]))
        self.assertEqual(result["overall"], expected)


if __name__ == "__main__":
    unittest.main()
