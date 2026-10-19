"""Requirement -> evidence matching. This is where the negative controls
live (see tests/test_negative_controls.py): evidence is always scoped to
pages that actually mention the query's entity first, so an unrelated
"premium subscription" blurb on a page that never mentions "laptop" can
never support a "premium laptop" qualifier. Every result carries the exact
{url, field, observed_value, evidence_type, confidence} it was decided from.
"""
from . import domain_vocabulary, normalizer, requirement_validator, vocabulary

SUPPORTED = "SUPPORTED"
PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
NOT_FOUND = "NOT_FOUND"
CONTRADICTED = "CONTRADICTED"
NOT_ASSESSABLE = "NOT_ASSESSABLE"
INVALID_REQUIREMENT = "INVALID_REQUIREMENT"

# Guards against a qualifier word matching an unrelated upsell/plan mention
# on the same page as the entity (e.g. "premium" describing a subscription
# tier, not the product itself).
_QUALIFIER_FALSE_CONTEXT = ["subscription", "membership", "plan", "newsletter"]


def _evidence(status, url=None, field=None, observed_value=None, evidence_type=None,
              confidence=None, note=None, **extra):
    result = {
        "status": status,
        "url": url,
        "field": field,
        "observed_value": observed_value,
        "evidence_type": evidence_type,
        "confidence": confidence,
        "note": note,
    }
    result.update(extra)
    return result


def entity_pages_for(requirement, index):
    if requirement is None:
        return []
    return index.pages_mentioning(requirement["key"])


def match_entity(requirement, index):
    pages = index.pages_mentioning(requirement["key"])
    if not pages:
        return _evidence(NOT_FOUND, note="No page mentions %r." % requirement["key"])
    page = pages[0]
    return _evidence(SUPPORTED, url=page["url"], field="page_text",
                      observed_value=requirement["key"], evidence_type="visible_text",
                      confidence=0.9 if len(pages) > 1 else 0.7)


def _observed_prices(pages):
    out = []
    for page in pages:
        for offer in page["offers"]:
            price = offer.get("price")
            try:
                if price is not None:
                    out.append({"value": float(price), "url": page["url"],
                                "field": "structured_data.offers.price",
                                "evidence_type": "structured_data"})
            except (TypeError, ValueError):
                continue
        for m, value, currency in normalizer.iter_money_matches(page["blob"]):
            out.append({"value": value, "url": page["url"], "field": "page_text",
                        "evidence_type": "visible_text"})
    return out


def match_price_constraint(requirement, entity_pages):
    if not entity_pages:
        return _evidence(NOT_ASSESSABLE, note="No page identifies the requested product, so price cannot be checked.")
    observed = _observed_prices(entity_pages)
    if not observed:
        return _evidence(NOT_FOUND, note="No price was found on the pages that mention this product.")

    ctype = requirement["detail"]["type"]
    target = requirement["detail"]["value"]

    if ctype in ("price_mentioned", "price_approx"):
        if ctype == "price_approx":
            close = [o for o in observed if abs(o["value"] - target) / max(target, 1) <= 0.15]
            if close:
                best = close[0]
                return _evidence(SUPPORTED, url=best["url"], field=best["field"],
                                  observed_value=best["value"], evidence_type=best["evidence_type"], confidence=0.7)
            return _evidence(NOT_FOUND, note="No observed price is close to %s." % target)
        best = observed[0]
        return _evidence(SUPPORTED, url=best["url"], field=best["field"],
                          observed_value=best["value"], evidence_type=best["evidence_type"], confidence=0.6)

    # Grouped per page rather than per price mention: a shopping site
    # legitimately carries several products across a price range, so one
    # other, pricier product existing elsewhere must not read as
    # "contradicted" — only a single product whose OWN observed prices
    # disagree with each other counts as genuinely mixed evidence.
    by_page = {}
    for o in observed:
        by_page.setdefault(o["url"], []).append(o)

    def _split(prices):
        if ctype == "price_max":
            return [p for p in prices if p["value"] <= target], [p for p in prices if p["value"] > target]
        return [p for p in prices if p["value"] >= target], [p for p in prices if p["value"] < target]

    qualifying_pages, mixed_pages, violating_pages = [], [], []
    for url, prices in by_page.items():
        qualifying, violating = _split(prices)
        if qualifying and not violating:
            qualifying_pages.append(qualifying[0])
        elif qualifying and violating:
            mixed_pages.append(qualifying[0])
        elif violating:
            violating_pages.append(violating[0])

    # Selectivity: what fraction of the distinct products found would this
    # constraint actually exclude? A ceiling so high nothing is ever
    # filtered is technically satisfied but tells a user almost nothing —
    # see query_quality.py's realism factor, which reads this back.
    total_pages = len(by_page)
    selectivity = round(len(violating_pages) / total_pages, 2) if total_pages else None
    all_values = [o["value"] for o in observed]
    realism = _price_realism(ctype, target, all_values)

    if qualifying_pages:
        best = qualifying_pages[0]
        note = None
        if realism == "unrealistic_high":
            note = ("This threshold is far above every observed price, so it is technically satisfied but "
                    "filters out essentially nothing.")
        elif realism == "unrealistic_low":
            note = ("This threshold is far below every observed price, so it is technically satisfied but "
                    "filters out essentially nothing.")
        return _evidence(SUPPORTED, url=best["url"], field=best["field"],
                          observed_value=best["value"], evidence_type=best["evidence_type"], confidence=0.8,
                          note=note, selectivity=selectivity, constraint_realism=realism)
    if mixed_pages:
        best = mixed_pages[0]
        return _evidence(PARTIALLY_SUPPORTED, url=best["url"], field=best["field"],
                          observed_value=best["value"], evidence_type=best["evidence_type"], confidence=0.5,
                          note="This product's own page shows conflicting prices relative to this constraint.",
                          selectivity=selectivity, constraint_realism=realism)
    worst = violating_pages[0]
    return _evidence(CONTRADICTED, url=worst["url"], field=worst["field"],
                      observed_value=worst["value"], evidence_type=worst["evidence_type"], confidence=0.7,
                      note="Every product found violates this constraint.",
                      selectivity=selectivity, constraint_realism=realism)


def _price_realism(ctype, target, observed_values):
    """"Technically satisfied" and "meaningfully selective" are different
    claims — this flags the gap between them (e.g. "laptop under
    $10,000,000") without touching whether the constraint was satisfied."""
    if not observed_values or target <= 0:
        return None
    obs_max, obs_min = max(observed_values), min(observed_values)
    if ctype == "price_max" and obs_max and target >= obs_max * 3:
        return "unrealistic_high"
    if ctype == "price_min" and obs_min and target <= obs_min / 3:
        return "unrealistic_low"
    return "realistic"


def match_bare_attribute(requirement, entity_pages, index, concepts):
    """"laptop with RAM" -- the attribute is named but no value was given.
    This asks only "does the site discuss this attribute for this
    entity at all" -- a presence check, not a value match. Requires the
    synonym to appear in an entity page's title/heading/body (any tier is
    acceptable here since there's no value to be wrong about); structured
    data or title placement earns higher confidence."""
    if not entity_pages:
        return _evidence(NOT_ASSESSABLE, note="No page identifies the requested product, so this attribute cannot be checked.")
    attr = requirement["key"]
    synonyms = concepts["attributes"].get(attr, [])
    for page in entity_pages:
        for syn in sorted(synonyms, key=len, reverse=True):
            tier = index.locate(page, syn)
            if tier is None:
                continue
            confidence = {"structured_data": 0.85, "title": 0.8, "heading": 0.7, "body": 0.5}[tier]
            return _evidence(SUPPORTED, url=page["url"], field="page_text", observed_value=syn,
                              evidence_type=tier, confidence=confidence,
                              note="This attribute is discussed for this product, but no specific value was "
                                   "requested to verify.")
    return _evidence(NOT_FOUND, note="This attribute is not mentioned on the pages that identify this product.")


def match_attribute(requirement, entity_pages, index, concepts):
    if requirement["detail"].get("value") is None:
        return match_bare_attribute(requirement, entity_pages, index, concepts)
    if not entity_pages:
        return _evidence(NOT_ASSESSABLE, note="No page identifies the requested product, so this attribute cannot be checked.")
    attr = requirement["key"]
    wanted_unit = requirement["detail"]["unit"]
    wanted_value = requirement["detail"]["value"]
    synonyms = concepts["attributes"].get(attr, [])

    matches, other_values, attribute_mentioned = [], [], False
    for page in entity_pages:
        for m, value, unit in normalizer.iter_unit_matches(page["blob"]):
            if unit != wanted_unit:
                continue
            window = page["blob"][max(0, m.start() - 20):m.end() + 20]
            if not any(normalizer.contains_phrase(window, s) for s in synonyms):
                continue
            attribute_mentioned = True
            if value == wanted_value:
                matches.append({"url": page["url"], "value": value})
            else:
                other_values.append({"url": page["url"], "value": value})

    if matches:
        best = matches[0]
        return _evidence(SUPPORTED, url=best["url"], field="page_text",
                          observed_value="%s%s" % (best["value"], wanted_unit),
                          evidence_type="visible_text", confidence=0.8)
    if other_values:
        worst = other_values[0]
        return _evidence(CONTRADICTED, url=worst["url"], field="page_text",
                          observed_value="%s%s" % (worst["value"], wanted_unit),
                          evidence_type="visible_text", confidence=0.6,
                          note="A different value for this attribute was found.")
    if attribute_mentioned or any(any(normalizer.contains_phrase(p["blob"], s) for s in synonyms) for p in entity_pages):
        return _evidence(PARTIALLY_SUPPORTED, evidence_type="visible_text", confidence=0.4,
                          note="This attribute is discussed but the specific value could not be confirmed.")
    return _evidence(NOT_FOUND, note="This attribute is not mentioned on the pages that identify this product.")


def _lexically_assessable_pages(pages):
    """Pages whose language is either unknown or explicitly supported by the
    English-only vocabulary — see vocabulary.SUPPORTED_LEXICAL_LANGUAGES."""
    return [p for p in pages if p["lang"] is None or p["lang"] in vocabulary.SUPPORTED_LEXICAL_LANGUAGES]


def _phrase_hits_with_context(pages, synonyms, index, false_context_terms):
    supported, false_context_only = [], []
    for page in pages:
        for syn in synonyms:
            needle = normalizer.normalize_text(syn)
            if not normalizer.contains_phrase(page["blob"], needle):
                continue
            window = index.context_window(page, syn)
            if false_context_terms and any(normalizer.contains_phrase(window, bad) for bad in false_context_terms):
                false_context_only.append((page, syn))
            else:
                supported.append((page, syn))
    return supported, false_context_only


def match_audience(requirement, entity_pages, index, concepts):
    if not entity_pages:
        return _evidence(NOT_ASSESSABLE, note="No page identifies the requested product, so audience fit cannot be checked.")
    assessable_pages = _lexically_assessable_pages(entity_pages)
    if not assessable_pages:
        return _evidence(NOT_ASSESSABLE, note="The pages for this product are not in a supported language for this check.")
    synonyms = concepts["audiences"].get(requirement["key"], [])
    supported, false_context_only = _phrase_hits_with_context(
        assessable_pages, synonyms, index, vocabulary.AUDIENCE_FALSE_CONTEXT)
    if supported:
        page, syn = supported[0]
        return _evidence(SUPPORTED, url=page["url"], field="page_text", observed_value=syn,
                          evidence_type="visible_text", confidence=0.7)
    if false_context_only:
        return _evidence(PARTIALLY_SUPPORTED, evidence_type="visible_text", confidence=0.2,
                          note="This audience is mentioned only in an unrelated context (e.g. a discount banner), "
                               "not as suitability evidence.")
    return _evidence(NOT_FOUND, note="No evidence this product is positioned for this audience.")


def match_use_case(requirement, entity_pages, index, concepts):
    if not entity_pages:
        return _evidence(NOT_ASSESSABLE, note="No page identifies the requested product, so use-case fit cannot be checked.")
    assessable_pages = _lexically_assessable_pages(entity_pages)
    if not assessable_pages:
        return _evidence(NOT_ASSESSABLE, note="The pages for this product are not in a supported language for this check.")
    synonyms = concepts["use_cases"].get(requirement["key"], [])
    supported, _ = _phrase_hits_with_context(assessable_pages, synonyms, index, None)
    if supported:
        page, syn = supported[0]
        return _evidence(SUPPORTED, url=page["url"], field="page_text", observed_value=syn,
                          evidence_type="visible_text", confidence=0.7)
    return _evidence(NOT_FOUND, note="No evidence this product is positioned for this use case.")


def match_qualifier(requirement, entity_pages, index):
    key = requirement["key"]
    phrases = vocabulary.QUALITY_QUALIFIERS.get(key)
    if phrases is None:
        return _evidence(
            NOT_ASSESSABLE,
            note='"%s" is a subjective claim a single site\'s own content cannot verify — '
                 "shown for completeness, not scored as pass or fail." % key,
        )
    if not entity_pages:
        return _evidence(NOT_ASSESSABLE, note="No page identifies the requested product, so this claim cannot be checked.")
    assessable_pages = _lexically_assessable_pages(entity_pages)
    if not assessable_pages:
        return _evidence(NOT_ASSESSABLE, note="The pages for this product are not in a supported language for this check.")
    supported, false_context_only = _phrase_hits_with_context(
        assessable_pages, phrases, index, _QUALIFIER_FALSE_CONTEXT)
    if supported:
        page, syn = supported[0]
        return _evidence(SUPPORTED, url=page["url"], field="page_text", observed_value=syn,
                          evidence_type="visible_text", confidence=0.6)
    return _evidence(NOT_FOUND, note="No %s-quality evidence found for this product." % key)


def match_requirement(requirement, index, entity_requirement, concepts):
    entity_pages = entity_pages_for(entity_requirement, index)
    category = requirement["category"]
    if category == "entity":
        return match_entity(requirement, index)
    if category == "price_constraint":
        return match_price_constraint(requirement, entity_pages)
    if category == "attribute":
        return match_attribute(requirement, entity_pages, index, concepts)
    if category == "audience":
        return match_audience(requirement, entity_pages, index, concepts)
    if category == "use_case":
        return match_use_case(requirement, entity_pages, index, concepts)
    if category == "quality_qualifier":
        return match_qualifier(requirement, entity_pages, index)
    return _evidence(NOT_ASSESSABLE, note="Unrecognized requirement category.")


def evaluate_requirements(nlp_result, index, entity_schemas=None, domain_type=None):
    """requirement_validator.py runs FIRST: anything it can already
    resolve (no entity to scope by, an unrecognized term, or a concept
    with no evidenced relationship to this entity) never reaches the
    matchers below — those only ever see requirements with a validated
    domain relationship left to actually check.

    `domain_type` resolves the same concept dictionary nlp_engine.py used
    to extract these requirements in the first place (see
    domain_vocabulary.py) — the evidence side must look up a bare
    attribute's synonyms from the identical bundle the query side used to
    name it, or a domain mismatch here would silently fail to find
    evidence that genuinely exists."""
    concepts = domain_vocabulary.get_vocabulary(domain_type)
    entity_requirement = next((r for r in nlp_result["requirements"] if r["category"] == "entity"), None)
    partitioned = requirement_validator.validate(
        nlp_result["requirements"], entity_requirement, entity_schemas or {})

    evaluated = []
    for requirement, outcome, resolved_evidence in partitioned:
        if outcome == requirement_validator.RESOLVED:
            evidence = resolved_evidence
        else:
            evidence = match_requirement(requirement, index, entity_requirement, concepts)
        evaluated.append({**requirement, "evidence": evidence})
    return evaluated
