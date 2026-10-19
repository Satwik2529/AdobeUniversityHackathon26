import unittest

import _pathfix  # noqa: F401
from lib import opportunity


def _breakdown_entry(status, max_points=50, points_earned=None):
    if points_earned is None:
        points_earned = max_points if status == "SUPPORTED" else 0
    return {"status": status, "max_points": max_points, "points_earned": points_earned}


class OpportunityTest(unittest.TestCase):
    def test_low_quality_query_is_never_an_opportunity(self):
        gap = opportunity.actionable_gap_points([_breakdown_entry("NOT_FOUND")])
        self.assertEqual(opportunity.compute_opportunity(query_quality_overall=10, gap_points=gap,
                                                          answerability=100), 0)

    def test_full_coverage_has_no_opportunity_left(self):
        gap = opportunity.actionable_gap_points([_breakdown_entry("SUPPORTED")])
        self.assertEqual(opportunity.compute_opportunity(query_quality_overall=100, gap_points=gap,
                                                          answerability=100), 0)

    def test_realistic_query_with_a_real_gap_scores_high(self):
        gap = opportunity.actionable_gap_points([_breakdown_entry("NOT_FOUND", max_points=60)])
        score = opportunity.compute_opportunity(query_quality_overall=90, gap_points=gap, answerability=100)
        self.assertGreater(score, 40)

    def test_invalid_requirement_gap_is_not_an_opportunity(self):
        # The load-bearing fix: a schema-mismatched requirement ("keyboard
        # with RAM") is not something a site owner can act on -- there is
        # nothing to add, so it must not be flagged as an opportunity.
        gap = opportunity.actionable_gap_points([
            _breakdown_entry("SUPPORTED", max_points=60),
            _breakdown_entry("INVALID_REQUIREMENT", max_points=40),
        ])
        self.assertEqual(gap, 0)
        self.assertEqual(opportunity.compute_opportunity(query_quality_overall=90, gap_points=gap,
                                                          answerability=100), 0)

    def test_gap_driven_by_unanswerable_content_is_discounted(self):
        gap = opportunity.actionable_gap_points([_breakdown_entry("NOT_FOUND", max_points=60)])
        answerable_gap = opportunity.compute_opportunity(query_quality_overall=90, gap_points=gap, answerability=100)
        unanswerable_gap = opportunity.compute_opportunity(query_quality_overall=90, gap_points=gap, answerability=50)
        self.assertLess(unanswerable_gap, answerable_gap)

    def test_missing_dimensions_return_none_not_a_fabricated_number(self):
        self.assertIsNone(opportunity.compute_opportunity(query_quality_overall=90, gap_points=None,
                                                           answerability=None))


if __name__ == "__main__":
    unittest.main()
