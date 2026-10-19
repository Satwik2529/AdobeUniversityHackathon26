"""The hybrid NLP engine: normalization + regex/pattern rules + the
controlled taxonomy in vocabulary.py. No external model, no API call —
every extraction here is deterministic and traceable to an explicit rule,
so a result can always be explained by pointing at the rule that fired.

Hard rule (see requirement_validator.py for the next stage): a word in
the query is NEVER simply dropped because it didn't match a pattern.
Anything not consumed by entity/price/attribute/audience/use-case/
qualifier extraction is surfaced as an explicit `unrecognized_term`
requirement instead of vanishing — that is what stops a query like
"laptop with wheels" from silently degrading into just "laptop" and
scoring as if "wheels" had never been asked about.
"""
import hashlib
import re

from . import domain_vocabulary, normalizer, vocabulary
from .versions import NLP_ENGINE_VERSION

_PRICE_MAX_CUES = ["under", "below", "less than", "cheaper than", "within", "up to"]
_PRICE_MIN_CUES = ["over", "above", "more than", "starting from", "at least"]
_PRICE_APPROX_CUES = ["around", "about", "roughly", "approximately", "near"]

# unit -> attribute keys it could plausibly belong to, most specific first.
_UNIT_ATTRIBUTE_HINTS = {
    "gb": ["ram", "storage"],
    "tb": ["storage"],
    "mb": ["ram", "storage"],
    "mp": ["camera"],
    "mah": ["battery"],
    "inch": ["display"],
    "ghz": ["processor"],
    "hz": ["display"],
    "kg": ["weight"],
    "g": ["weight"],
}


class _Consumption:
    """Tracks which character ranges of `normalized_query` have already
    been claimed by some extracted requirement, so the final leftover-word
    pass (see `_unrecognized_terms`) knows what's genuinely unaccounted
    for rather than re-flagging words that were already understood."""

    def __init__(self, text):
        self.text = text
        self.spans = []

    def mark(self, needle):
        if not needle:
            return
        start = 0
        while True:
            match = normalizer.find_phrase(self.text, needle, start)
            if match is None:
                return
            self.spans.append(match.span())
            start = match.end()

    def covers(self, start, end):
        return any(s <= start and end <= e for s, e in self.spans)


def _requirement_id(category, key):
    digest = hashlib.sha256(("%s:%s" % (category, key)).encode("utf-8")).hexdigest()[:8]
    return "R-%s-%s" % (category[:3].upper(), digest)


def _detect_intent(normalized_query):
    if any(normalizer.contains_phrase(normalized_query, m.strip()) for m in vocabulary.INTENT_MARKERS["comparison"]):
        return "comparison"
    if any(normalizer.contains_phrase(normalized_query, m.strip()) for m in vocabulary.INTENT_MARKERS["availability"]):
        return "availability"
    if any(normalizer.contains_phrase(normalized_query, m.strip()) for m in vocabulary.INTENT_MARKERS["specification"]):
        return "specification"
    if any(normalizer.contains_phrase(normalized_query, m.strip()) for m in vocabulary.INTENT_MARKERS["recommendation"]):
        return "recommendation"
    return "general"


def _detect_entity(normalized_query, profile):
    candidates = [(e["text"], e.get("confidence", "low")) for e in (profile or {}).get("entities", [])]
    candidates.sort(key=lambda tc: -len(tc[0]))
    for text, confidence in candidates:
        needle = normalizer.normalize_text(text)
        if normalizer.contains_phrase(normalized_query, needle):
            return {"text": text, "source": "profile", "confidence": confidence}
    return None


def _detect_comparison_entity(normalized_query, profile, primary_entity, intent):
    """"Laptop vs Keyboard", "Computer Science vs Business Administration"
    -- a comparison query names a SECOND entity, which used to have no
    representation at all: _detect_entity only ever returns one match, so
    the second name's words fell through to unrecognized_term one at a
    time ("computer": unrecognized, "science": unrecognized) instead of
    being understood as "the other thing being compared". Only searched
    for when intent is already "comparison" (an explicit " vs "/" versus
    "/"compare" marker fired) and a primary entity was found, so this
    never fires on an ordinary single-entity query."""
    if intent != "comparison" or primary_entity is None:
        return None
    candidates = [(e["text"], e.get("confidence", "low")) for e in (profile or {}).get("entities", [])]
    candidates.sort(key=lambda tc: -len(tc[0]))
    for text, confidence in candidates:
        if text == primary_entity["text"]:
            continue
        needle = normalizer.normalize_text(text)
        if normalizer.contains_phrase(normalized_query, needle):
            return {"text": text, "source": "profile", "confidence": confidence}
    return None


def _price_constraint_type(normalized_query, match_span):
    window = normalized_query[max(0, match_span[0] - 20):match_span[0]]
    if any(normalizer.contains_phrase(window, cue) for cue in _PRICE_MAX_CUES):
        return "price_max"
    if any(normalizer.contains_phrase(window, cue) for cue in _PRICE_MIN_CUES):
        return "price_min"
    if any(normalizer.contains_phrase(window, cue) for cue in _PRICE_APPROX_CUES):
        return "price_approx"
    return "price_mentioned"


def _extract_price_constraints(normalized_query, consumption):
    out = []
    seen_spans = set()
    for m, value, currency in normalizer.iter_money_matches(normalized_query):
        if m.span() in seen_spans:
            continue
        seen_spans.add(m.span())
        consumption.mark(m.group(0))
        out.append({
            "type": _price_constraint_type(normalized_query, m.span()),
            "value": value,
            "currency": currency,
            "raw": m.group(0).strip(),
        })
    return out


def _resolve_attribute_for_unit(unit, normalized_query, span, concepts):
    hints = _UNIT_ATTRIBUTE_HINTS.get(unit, [])
    if len(hints) == 1:
        return hints[0], "high"
    window = normalized_query[max(0, span[0] - 15):min(len(normalized_query), span[1] + 15)]
    for attr in hints:
        synonyms = concepts["attributes"].get(attr, [])
        if any(normalizer.contains_phrase(window, s) for s in synonyms):
            return attr, "high"
    if hints:
        return hints[0], "low"
    return None, "low"


def _extract_valued_attributes(normalized_query, consumption, concepts):
    """"16GB RAM", "108MP camera" -- an explicit number+unit. These units
    (GB, MP, mAh...) are inherently electronics/shopping concepts, so this
    naturally contributes little outside that domain -- other domains'
    numeric facts (tuition, duration) are handled as price_constraint or
    bare attributes instead, see module docstring."""
    out = []
    for m, value, unit in normalizer.iter_unit_matches(normalized_query):
        attr, confidence = _resolve_attribute_for_unit(unit, normalized_query, m.span(), concepts)
        if attr is None:
            continue
        consumption.mark(m.group(0))
        out.append({
            "attribute": attr,
            "value": value,
            "unit": unit,
            "raw": m.group(0).strip(),
            "confidence": confidence,
            "kind": "valued",
        })
    return out


def _extract_bare_attributes(normalized_query, consumption, already_covered_attrs, concepts):
    """"laptop with RAM", "keyboard with backlighting" -- an attribute
    named without a value. This used to be silently dropped entirely
    (rule: never drop a term); it is now a first-class, presence-only
    requirement -- "does the site even discuss this attribute for this
    entity", resolved later against the entity's own schema."""
    out = []
    for key, synonyms in concepts["attributes"].items():
        for syn in sorted(synonyms, key=len, reverse=True):
            needle = normalizer.normalize_text(syn)
            match = normalizer.find_phrase(normalized_query, needle)
            if match is None:
                continue
            if consumption.covers(match.start(), match.end()):
                continue
            # Already have a valued match for this attribute (e.g. "16GB"
            # for "ram") -- the word itself ("RAM") still needs to be
            # marked consumed so it isn't flagged as unrecognized, but no
            # second, duplicate bare requirement is created for it.
            consumption.mark(needle)
            if key not in already_covered_attrs:
                out.append({"attribute": key, "value": None, "unit": None, "raw": syn,
                            "confidence": "n/a", "kind": "bare"})
            break
    return out


def _extract_terms(normalized_query, term_map, consumption):
    hits = []
    for key, synonyms in term_map.items():
        if not synonyms:
            continue
        for syn in sorted(synonyms, key=len, reverse=True):
            needle = normalizer.normalize_text(syn)
            if normalizer.contains_phrase(normalized_query, needle):
                consumption.mark(needle)
                hits.append({"key": key, "raw": syn})
                break
    return hits


def _extract_qualifiers(normalized_query, consumption):
    hits = []
    seen_keys = set()
    for key, synonyms in vocabulary.QUALIFIER_SYNONYMS.items():
        for syn in synonyms:
            m = re.search(r"\b%s\b" % re.escape(syn), normalized_query)
            if m:
                consumption.mark(m.group(0))
                if key not in seen_keys:
                    seen_keys.add(key)
                    hits.append({"key": key, "raw": syn,
                                "verifiable": vocabulary.QUALITY_QUALIFIERS.get(key) is not None})
                break
    return hits


def _unrecognized_terms(normalized_query, consumption, entities):
    """Everything left over after every other extractor has had a chance
    -- surfaced, never dropped. Intent-marker words are also consumed so
    "best"/"compare"/"buy" don't double up as unrecognized noise on top of
    already explaining the query's intent."""
    for markers in vocabulary.INTENT_MARKERS.values():
        for m in markers:
            consumption.mark(m.strip())
    for e in entities:
        if e:
            consumption.mark(normalizer.normalize_text(e["text"]))

    leftover = []
    seen = set()
    for token, start, end in normalizer.tokenize_with_spans(normalized_query):
        if token in vocabulary.STOPWORDS or len(token) <= 2:
            continue
        if token.isdigit():
            continue
        if consumption.covers(start, end):
            continue
        if token in seen:
            continue
        seen.add(token)
        leftover.append({"text": token})
    return leftover


def analyze_query(query_text, profile=None):
    profile = profile or {}
    # The ONE resolution point where domain enters the engine: everything
    # below is identical code for every domain, it just gets handed a
    # different concept dictionary (see domain_vocabulary.py).
    concepts = domain_vocabulary.get_vocabulary(profile.get("domain_type"))
    normalized_query = normalizer.normalize_text(query_text)
    consumption = _Consumption(normalized_query)

    intent = _detect_intent(normalized_query)
    entity = _detect_entity(normalized_query, profile)
    comparison_entity = _detect_comparison_entity(normalized_query, profile, entity, intent)

    price_constraints = _extract_price_constraints(normalized_query, consumption)
    valued_attrs = _extract_valued_attributes(normalized_query, consumption, concepts)
    bare_attrs = _extract_bare_attributes(
        normalized_query, consumption, already_covered_attrs={a["attribute"] for a in valued_attrs},
        concepts=concepts,
    )
    attribute_hits = valued_attrs + bare_attrs
    audience_hits = _extract_terms(normalized_query, concepts["audiences"], consumption)
    use_case_hits = _extract_terms(normalized_query, concepts["use_cases"], consumption)
    qualifier_hits = _extract_qualifiers(normalized_query, consumption)
    unrecognized = _unrecognized_terms(normalized_query, consumption, [entity, comparison_entity])

    requirements = []
    if entity:
        requirements.append({
            "id": _requirement_id("entity", entity["text"]),
            "category": "entity",
            "key": entity["text"],
            "raw": entity["text"],
            "detail": {"confidence": entity["confidence"]},
        })
    if comparison_entity:
        requirements.append({
            "id": _requirement_id("entity", comparison_entity["text"]),
            "category": "entity",
            "key": comparison_entity["text"],
            "raw": comparison_entity["text"],
            "detail": {"confidence": comparison_entity["confidence"], "comparison_target": True},
        })
    for pc in price_constraints:
        requirements.append({
            "id": _requirement_id("price_constraint", pc["raw"]),
            "category": "price_constraint",
            "key": pc["type"],
            "raw": pc["raw"],
            "detail": pc,
        })
    seen_attrs = set()
    for a in attribute_hits:
        dedupe_key = (a["attribute"], a["value"], a["unit"])
        if dedupe_key in seen_attrs:
            continue
        seen_attrs.add(dedupe_key)
        requirements.append({
            "id": _requirement_id("attribute", "%s-%s%s" % (a["attribute"], a["value"], a["unit"])),
            "category": "attribute",
            "key": a["attribute"],
            "raw": a["raw"],
            "detail": a,
        })
    for aud in audience_hits:
        requirements.append({
            "id": _requirement_id("audience", aud["key"]),
            "category": "audience",
            "key": aud["key"],
            "raw": aud["raw"],
            "detail": {},
        })
    for uc in use_case_hits:
        requirements.append({
            "id": _requirement_id("use_case", uc["key"]),
            "category": "use_case",
            "key": uc["key"],
            "raw": uc["raw"],
            "detail": {},
        })
    for q in qualifier_hits:
        requirements.append({
            "id": _requirement_id("quality_qualifier", q["key"]),
            "category": "quality_qualifier",
            "key": q["key"],
            "raw": q["raw"],
            "detail": {"verifiable": q["verifiable"]},
        })
    for term in unrecognized:
        requirements.append({
            "id": _requirement_id("unrecognized_term", term["text"]),
            "category": "unrecognized_term",
            "key": term["text"],
            "raw": term["text"],
            "detail": {},
        })

    return {
        "nlp_engine_version": NLP_ENGINE_VERSION,
        "raw_query": query_text,
        "normalized_query": normalized_query,
        "intent": intent,
        "entity": entity,
        "audience": audience_hits,
        "use_case": use_case_hits,
        "attributes": attribute_hits,
        "constraints": price_constraints,
        "qualifiers": qualifier_hits,
        "unrecognized_terms": unrecognized,
        "requirements": requirements,
    }
