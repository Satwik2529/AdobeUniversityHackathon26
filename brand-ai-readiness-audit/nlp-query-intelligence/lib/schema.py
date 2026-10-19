"""Output shape builders + a small pre-write validator, mirroring the
existing entrypoint's "evidence-or-silence" discipline: an output that
doesn't validate is never written to disk.
"""
import hashlib
import time

from . import (
    combination_checker,
    difficulty,
    differential,
    evidence_index,
    evidence_matcher,
    finding_correlator,
    nlp_engine,
    opportunity,
    query_quality,
    recommendations,
    scoring,
)
from .versions import PIPELINE_VERSION

_VALID_STATUSES = (
    "SUPPORTED", "PARTIALLY_SUPPORTED", "NOT_FOUND", "CONTRADICTED",
    "NOT_ASSESSABLE", "INVALID_REQUIREMENT",
)


class SchemaError(Exception):
    pass


def _require(obj, keys, where):
    for key in keys:
        if key not in obj:
            raise SchemaError("%s missing required field %r" % (where, key))


def validate_query_result(result):
    _require(result, ["query_id", "pipeline_version", "generated_at", "snapshot_hash",
                       "nlp", "requirements", "scoring", "query_quality", "assessable"], "query-result")
    _require(result["scoring"], ["overall_score", "evidence_coverage", "answerability",
                                  "confidence", "breakdown"], "query-result.scoring")
    _require(result["query_quality"], ["overall", "factors"], "query-result.query_quality")
    for req in result["requirements"]:
        _require(req, ["id", "category", "key", "evidence"], "query-result.requirements[]")
        _require(req["evidence"], ["status"], "query-result.requirements[].evidence")
        if req["evidence"]["status"] not in _VALID_STATUSES:
            raise SchemaError("invalid evidence status %r" % req["evidence"]["status"])
    return result


def _query_result_id(query_text, snapshot_hash):
    return "QR-" + hashlib.sha256((query_text + "|" + snapshot_hash).encode("utf-8")).hexdigest()[:12]


def _overall_query_health(coverage, answerability, quality_overall):
    """The one headline number, IF a single number is needed (a compact
    list row, a comparison column) — documented blend of the three
    independent dimensions above it, never presented as the only
    explanation for a query's result (see the UI's "why this score"
    breakdown, which always shows the three inputs separately).

    Weighted toward the two dimensions that measure actual site evidence
    (coverage, answerability) rather than query_quality, which is close
    to a constant ~100 for any well-formed query — generator output is
    well-formed by construction, so giving it equal footing with real
    evidence would mask genuine coverage gaps behind a quality bonus that
    isn't telling you anything about THIS site. 10% keeps quality
    meaningful for the cases it does catch (unrealistic constraints,
    heavy unrecognized-term noise) without letting it prop up a weak
    evidence result."""
    if coverage is None or answerability is None:
        return None
    return round(0.6 * coverage + 0.3 * answerability + 0.1 * quality_overall)


def _reasoning_trace(nlp_result, evaluated, scored, quality, opportunity_score):
    understood = []
    if nlp_result["entity"]:
        understood.append("entity: %s" % nlp_result["entity"]["text"])
    understood += ["%s: %s" % (c["type"], c["raw"]) for c in nlp_result["constraints"]]
    understood += ["%s: %s" % (a["attribute"], a["raw"]) for a in nlp_result["attributes"]]
    understood += ["audience: %s" % a["raw"] for a in nlp_result["audience"]]
    understood += ["use case: %s" % u["raw"] for u in nlp_result["use_case"]]
    understood += ["qualifier: %s" % q["raw"] for q in nlp_result["qualifiers"]]
    if nlp_result["unrecognized_terms"]:
        understood += ["unrecognized: %s" % t["text"] for t in nlp_result["unrecognized_terms"]]

    by_status = {}
    for r in evaluated:
        by_status.setdefault(r["evidence"]["status"], []).append(r["key"])

    return {
        "understand": {"intent": nlp_result["intent"], "terms": understood},
        "require": [{"category": r["category"], "key": r["key"]} for r in evaluated],
        "retrieve_verify": {status: keys for status, keys in by_status.items()},
        "score": {
            "evidence_coverage": scored["evidence_coverage"],
            "answerability": scored["answerability"],
            "confidence": scored["confidence"],
            "query_quality": quality["overall"],
            "opportunity": opportunity_score,
        },
    }


def build_query_result(query_text, snapshot, snapshot_hash, profile, report=None, index=None):
    """The single place `test` assembles a full result: NLP -> requirement
    validation -> evidence -> multi-dimensional scoring -> quality ->
    opportunity -> recommendations -> (optional) finding correlation."""
    index = index or evidence_index.EvidenceIndex(snapshot)
    entity_schemas = (profile or {}).get("entity_schemas", {})

    nlp_result = nlp_engine.analyze_query(query_text, profile)
    entity_requirement = next((r for r in nlp_result["requirements"] if r["category"] == "entity"), None)

    evaluated = evidence_matcher.evaluate_requirements(
        nlp_result, index, entity_schemas, domain_type=(profile or {}).get("domain_type"))
    combination = combination_checker.check_combination(evaluated)
    if combination is not None:
        evaluated = evaluated + [combination]
    scored = scoring.score_requirements(evaluated)
    quality = query_quality.compute_query_quality(nlp_result, evaluated, entity_requirement)
    gap_points = (
        opportunity.actionable_gap_points(scored["breakdown"])
        if scored["evidence_coverage"] is not None else None
    )
    opportunity_score = opportunity.compute_opportunity(quality["overall"], gap_points, scored["answerability"])
    diff = difficulty.classify_difficulty(evaluated)
    recs = recommendations.build_recommendations(evaluated)
    correlations = finding_correlator.correlate(evaluated, report)

    assessable = entity_requirement is not None
    not_assessable_reason = None if assessable else (
        "No product or category recognized in this site's evidence was found in this query, so nothing could "
        "be scoped for evidence checking."
    )

    result = {
        "query_id": _query_result_id(query_text, snapshot_hash),
        "pipeline_version": PIPELINE_VERSION,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "snapshot_hash": snapshot_hash,
        "site": snapshot.get("site"),
        "assessable": assessable,
        "not_assessable_reason": not_assessable_reason,
        "nlp": nlp_result,
        "requirements": evaluated,
        "scoring": scored,
        "query_quality": quality,
        "opportunity_score": opportunity_score,
        "overall_query_health": _overall_query_health(
            scored["evidence_coverage"], scored["answerability"], quality["overall"]),
        "difficulty": diff,
        "reasoning_trace": _reasoning_trace(nlp_result, evaluated, scored, quality, opportunity_score),
        "recommendations": recs,
        "related_findings": correlations,
        "report_available": report is not None,
    }
    return validate_query_result(result)
