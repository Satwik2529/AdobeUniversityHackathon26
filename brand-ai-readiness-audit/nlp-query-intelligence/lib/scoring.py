"""Multi-dimensional, documented scoring. Nothing here is a single blended
percentage standing in for "how good is this query" — evidence_coverage,
answerability and confidence are computed independently (query_quality.py
and opportunity.py add two more), so a query can score high on one and low
on another instead of collapsing into one number that hides the reason.

evidence_coverage: of the requirements with a DEFINITE verdict (i.e. not
  NOT_ASSESSABLE), how well are they supported. INVALID_REQUIREMENT
  requirements are included here and scored as unsupported (multiplier
  0.0) — a query about a property that has no evidenced relationship to
  the entity is not "excused" the way a genuinely unassessable one is;
  it is a real coverage gap. This is the load-bearing fix for a query
  never reaching 100% just because everything past the entity was
  silently dropped or waved through.

answerability: of EVERYTHING the query asked about (including terms the
  taxonomy doesn't recognize at all), what fraction could be given a
  definite verdict at all. A query half-full of unrecognized vocabulary
  can have perfect evidence_coverage on the half that WAS checked and
  still show degraded answerability — the two dimensions are kept apart
  on purpose (see requirement_validator.py's docstring for why coverage
  alone can't carry this).

confidence: the requirement-weighted average of each definite verdict's
  own evidence confidence (structured data / title placement scores
  higher than a bare body-text mention) — how much to trust the
  evidence_coverage number, not a restatement of it.
"""
from .versions import SCORING_VERSION

REQUIREMENT_WEIGHTS = {
    "entity": 25,
    "price_constraint": 20,
    "attribute": 20,
    "audience": 15,
    "use_case": 15,
    "quality_qualifier": 5,
    # Whether the OTHER supported requirements above were actually true of
    # the same product at once (see combination_checker.py) — weighted
    # comparably to a single fact because a "Frankenstein" answer built
    # from several individually-true-but-never-jointly-true facts is a
    # more serious defect than any one weak requirement.
    "combination": 20,
}
_DEFAULT_WEIGHT = 10

STATUS_MULTIPLIER = {
    "SUPPORTED": 1.0,
    "PARTIALLY_SUPPORTED": 0.5,
    "NOT_FOUND": 0.0,
    "CONTRADICTED": -0.25,
    "INVALID_REQUIREMENT": 0.0,
}

# Requirements in this state carry no verdict about the site at all (no
# entity to scope by, unrecognized vocabulary, unsupported language) —
# excluded from evidence_coverage's denominator, but they still count
# against answerability, which measures exactly this gap.
_UNASSESSABLE_STATUS = "NOT_ASSESSABLE"


def _evidence_coverage(evaluated_requirements):
    scored = [r for r in evaluated_requirements if r["evidence"]["status"] != _UNASSESSABLE_STATUS]
    total_weight = sum(REQUIREMENT_WEIGHTS.get(r["category"], _DEFAULT_WEIGHT) for r in scored)

    breakdown = []
    earned = 0.0
    for r in scored:
        weight = REQUIREMENT_WEIGHTS.get(r["category"], _DEFAULT_WEIGHT)
        max_points = (weight / total_weight * 100) if total_weight else 0
        multiplier = STATUS_MULTIPLIER.get(r["evidence"]["status"], 0.0)
        points = max(0.0, max_points * multiplier)
        earned += points
        breakdown.append({
            "requirement_id": r["id"],
            "category": r["category"],
            "key": r["key"],
            "raw": r.get("raw"),
            "status": r["evidence"]["status"],
            "max_points": round(max_points, 1),
            "points_earned": round(points, 1),
        })
    score = round(max(0.0, min(100.0, earned))) if scored else None
    return score, breakdown


def _answerability(evaluated_requirements):
    total = len(evaluated_requirements)
    if not total:
        return None
    definite = sum(1 for r in evaluated_requirements if r["evidence"]["status"] != _UNASSESSABLE_STATUS)
    return round(100 * definite / total)


def _confidence(evaluated_requirements):
    weighted_sum, weight_total = 0.0, 0.0
    for r in evaluated_requirements:
        c = r["evidence"].get("confidence")
        if c is None:
            continue
        w = REQUIREMENT_WEIGHTS.get(r["category"], _DEFAULT_WEIGHT)
        weighted_sum += c * w
        weight_total += w
    if weight_total == 0:
        return None
    return round(100 * weighted_sum / weight_total)


def score_requirements(evaluated_requirements):
    coverage, breakdown = _evidence_coverage(evaluated_requirements)
    answerability = _answerability(evaluated_requirements)
    confidence = _confidence(evaluated_requirements)
    not_assessable = [r for r in evaluated_requirements if r["evidence"]["status"] == _UNASSESSABLE_STATUS]

    return {
        "scoring_version": SCORING_VERSION,
        # Kept for compact display contexts (the generated-query list,
        # comparison tables) — a documented blend, never the only number
        # shown for a single query's own analysis page. None of its inputs
        # are query_quality/opportunity, which live in their own modules
        # and are merged in by schema.py so this module has no knowledge
        # of the query-text-level heuristics those compute.
        "overall_score": coverage if coverage is not None else 0,
        "evidence_coverage": coverage,
        "answerability": answerability,
        "confidence": confidence,
        "breakdown": breakdown,
        "not_assessable": [
            {"requirement_id": r["id"], "category": r["category"], "key": r["key"],
             "note": r["evidence"].get("note")}
            for r in not_assessable
        ],
    }
