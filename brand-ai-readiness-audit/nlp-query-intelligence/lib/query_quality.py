"""Query quality — deliberately independent of evidence_coverage (see
scoring.py's docstring for why the two must never collapse into one
number). This asks "is this a legitimate, testable, realistic question
about this site's domain", not "does the site answer it well". A
nonsensical or unrealistic query should score low here even if, by
accident, the one thing it does ask about happens to be fully supported.

Every factor is a simple, documented, deterministic rule over data
already computed by nlp_engine.py / evidence_matcher.py — no invented
"AI understanding" claim, matching the project's no-fake-semantic-AI
principle.
"""
from .versions import PIPELINE_VERSION

_WEIGHTS = {
    "semantic_coherence": 0.15,
    "domain_relevance": 0.35,
    "testability": 0.25,
    "clarity": 0.10,
    "realism": 0.15,
}


def _semantic_coherence(evaluated_requirements):
    """At least one requirement resolved to something other than pure
    unrecognized noise."""
    meaningful = [r for r in evaluated_requirements if r["category"] != "unrecognized_term"]
    return 100 if meaningful else 0


def _domain_relevance(evaluated_requirements):
    """What fraction of everything asked actually connects to this
    site's domain (not unrecognized, not INVALID_REQUIREMENT)."""
    total = len(evaluated_requirements)
    if not total:
        return 0
    relevant = sum(
        1 for r in evaluated_requirements
        if r["category"] != "unrecognized_term" and r["evidence"]["status"] != "INVALID_REQUIREMENT"
    )
    return round(100 * relevant / total)


def _testability(entity_requirement):
    """Without an identified entity there is nothing to scope evidence
    by, so nothing downstream can be genuinely tested."""
    return 100 if entity_requirement else 0


def _clarity(nlp_result, entity_requirement):
    """A crude but honest signal: a query with no identifiable entity AND
    no clear intent marker is genuinely ambiguous about what it's even
    asking; anything else is treated as clear (this is not sentence-level
    disambiguation, just a floor against the emptiest queries)."""
    if entity_requirement or nlp_result["intent"] != "general":
        return 100
    return 40


def _realism(evaluated_requirements):
    """Reads the constraint_realism flag evidence_matcher.py's price
    matcher already computed — an absurd ceiling/floor is technically
    satisfied but not a realistic constraint (see evidence_matcher.py:
    _price_realism)."""
    for r in evaluated_requirements:
        if r["category"] == "price_constraint":
            if r["evidence"].get("constraint_realism") in ("unrealistic_high", "unrealistic_low"):
                return 25
    return 100


def compute_query_quality(nlp_result, evaluated_requirements, entity_requirement):
    factors = {
        "semantic_coherence": _semantic_coherence(evaluated_requirements),
        "domain_relevance": _domain_relevance(evaluated_requirements),
        "testability": _testability(entity_requirement),
        "clarity": _clarity(nlp_result, entity_requirement),
        "realism": _realism(evaluated_requirements),
    }
    overall = round(sum(factors[k] * _WEIGHTS[k] for k in _WEIGHTS))
    return {
        "pipeline_version": PIPELINE_VERSION,
        "overall": overall,
        "factors": factors,
        "weights": dict(_WEIGHTS),
    }
