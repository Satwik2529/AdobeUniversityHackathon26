"""Opportunity — kept separate from evidence_coverage on purpose (a low
score alone is not an "opportunity": a garbage query scoring 0 because it
is nonsense is not something a site owner can act on; a realistic query
scoring 0 because the site genuinely lacks that evidence is).

Formula (documented, not tuned to produce a particular-looking number):

    actionable_gap = sum of (max_points - points_earned) for requirements
                      whose status is NOT_FOUND, PARTIALLY_SUPPORTED or
                      CONTRADICTED -- i.e. requirements where the site
                      COULD, in principle, add or fix content to close
                      the gap.
    opportunity = quality/100 * actionable_gap * (answerability/100)

INVALID_REQUIREMENT is deliberately excluded from the gap: "Keyboard
with RAM" scoring low is not an opportunity, because there is nothing to
add — keyboards do not have RAM. Recommending otherwise would be exactly
the kind of fabricated, non-evidence-backed suggestion the rest of this
subsystem refuses to make (see recommendations.py). Only a genuine
content gap the site could plausibly address counts.

- quality gates it: below a floor, nothing scores as an opportunity no
  matter how large the gap (see _MIN_QUALITY_FOR_OPPORTUNITY).
- answerability discounts opportunities that are mostly unanswerable
  (unrecognized vocabulary) rather than genuinely uncovered.
"""
_MIN_QUALITY_FOR_OPPORTUNITY = 40
_ACTIONABLE_STATUSES = {"NOT_FOUND", "PARTIALLY_SUPPORTED", "CONTRADICTED"}


def actionable_gap_points(scoring_breakdown):
    return sum(
        b["max_points"] - b["points_earned"]
        for b in scoring_breakdown
        if b["status"] in _ACTIONABLE_STATUSES
    )


def compute_opportunity(query_quality_overall, gap_points, answerability):
    if gap_points is None or answerability is None:
        return None
    if query_quality_overall < _MIN_QUALITY_FOR_OPPORTUNITY:
        return 0
    raw = (query_quality_overall / 100) * max(0, gap_points) * (answerability / 100)
    return round(min(100, raw))
