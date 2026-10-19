"""Deterministic, evidence-aware query generation: profile + per-entity
templates -> each candidate run through the SAME full analysis pipeline
(nlp_engine -> requirement_validator -> evidence_matcher -> scoring ->
query_quality -> opportunity) real user queries go through, so a
generated query's score is never a separate, cheaper approximation.
Candidates below a minimum query_quality are dropped rather than shipped
as "realistic" test queries; survivors are ranked by opportunity so the
most actionable gaps surface first.

Determinism contract (verified by tests/test_query_generator.py, NL3):
the same profile + snapshot, serialized identically, always yields the
same ordered list of query ids and texts.
"""
import hashlib

from . import query_templates, schema
from .versions import GENERATOR_VERSION

_MIN_QUALITY_TO_KEEP = 35


def _query_id(text):
    return "Q-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]


def _candidate_texts(profile):
    entity_schemas = profile.get("entity_schemas", {})
    entity_texts = [e["text"] for e in profile.get("entities", [])]
    out = []
    for entity_text in entity_texts:
        entity_schema = entity_schemas.get(entity_text, {})
        for family_fn in query_templates.PER_ENTITY_FAMILIES:
            out.extend(family_fn(entity_text, entity_schema))
    out.extend(query_templates.comparison_family_cross_entity(entity_texts))
    return out


def generate_queries(profile, snapshot, snapshot_hash, index=None, report=None):
    seen_texts = set()
    candidates = []
    for family, text in _candidate_texts(profile):
        if text in seen_texts:
            continue
        seen_texts.add(text)
        candidates.append((family, text))

    queries = []
    for family, text in candidates:
        result = schema.build_query_result(text, snapshot, snapshot_hash, profile, report=report, index=index)
        if result["query_quality"]["overall"] < _MIN_QUALITY_TO_KEEP:
            continue
        queries.append({
            "id": _query_id(text),
            "text": text,
            "family": family,
            "difficulty": result["difficulty"],
            "assessable": result["assessable"],
            "evidence_coverage": result["scoring"]["evidence_coverage"],
            "answerability": result["scoring"]["answerability"],
            "query_quality": result["query_quality"]["overall"],
            "opportunity_score": result["opportunity_score"],
            "overall_query_health": result["overall_query_health"],
        })

    # Highest opportunity first (None treated as lowest) -- the point of
    # generation is to surface actionable gaps, not just list everything.
    queries.sort(key=lambda q: (-(q["opportunity_score"] or -1), q["text"]))

    return {
        "generator_version": GENERATOR_VERSION,
        "profile_snapshot_hash": profile.get("snapshot_hash"),
        "site": profile.get("site"),
        "count": len(queries),
        "discarded_low_quality": len(candidates) - len(queries),
        "queries": queries,
    }
