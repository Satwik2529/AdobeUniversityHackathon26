"""Deterministic query-text templates, one function per family — now
entity-schema-aware: every template is generated PER ENTITY using that
entity's own discovered attributes/audiences/use-cases
(profile["entity_schemas"][entity]), never the old site-wide union. This
is what stops "keyboard with RAM" from ever being generated on a site
that also sells laptops — RAM was never observed in keyboard's own
schema, so it is never a candidate for a keyboard query in the first
place (a stronger guarantee than catching it after generation).
"""


def _currency_symbol(price_signals):
    currency = (price_signals or {}).get("currency") or "inr"
    return {"inr": "₹", "usd": "$", "eur": "€", "gbp": "£"}.get(currency, "₹")


def entity_family(entity_text, entity_schema):
    return [("entity", "Best %s" % entity_text)]


def price_family(entity_text, entity_schema):
    price = entity_schema.get("price_signals")
    if not price or not price.get("max") or price.get("sample_size", 0) < 3:
        return []
    sym = _currency_symbol(price)
    # The median observed price, not 80% of the max -- a threshold that
    # only the priciest listings would ever fail is technically a
    # constraint but tests nothing (see evidence_matcher.py's own
    # selectivity/realism flag on the same idea). The median genuinely
    # splits the catalog and is still a realistic, observed data point,
    # not an arbitrary number.
    threshold = int(price["median"])
    return [("price", "%s under %s%s" % (entity_text.capitalize(), sym, "{:,}".format(threshold)))]


def attribute_family(entity_text, entity_schema, limit=3):
    return [("attribute", "%s with %s" % (entity_text.capitalize(), attr))
            for attr in entity_schema.get("attributes", [])[:limit]]


def audience_family(entity_text, entity_schema, limit=3):
    return [("audience", "Best %s for %s" % (entity_text, aud))
            for aud in entity_schema.get("audiences", [])[:limit]]


def use_case_family(entity_text, entity_schema, limit=3):
    return [("use_case", "%s for %s" % (entity_text.capitalize(), uc))
            for uc in entity_schema.get("use_cases", [])[:limit]]


def quality_family(entity_text, entity_schema):
    return [("quality", "Premium %s" % entity_text), ("quality", "Budget %s" % entity_text)]


def recommendation_family(entity_text, entity_schema):
    return [("recommendation", "Best %s to buy" % entity_text)]


def availability_family(entity_text, entity_schema):
    return [("availability", "Is %s available" % entity_text)]


def complex_family(entity_text, entity_schema):
    """Gap-seeking on purpose: combines the entity with its OWN
    LEAST-evidenced audience/attribute (fewest supporting pages) rather
    than the most common ones -- a query more likely to actually reveal a
    gap, not one hand-picked to look good."""
    audiences = entity_schema.get("audience_evidence", {})
    attributes = entity_schema.get("attribute_evidence", {})
    price = entity_schema.get("price_signals")
    if not audiences or not attributes or not price or not price.get("max"):
        return []
    weakest_audience = min(audiences.items(), key=lambda kv: kv[1]["page_count"])[0]
    weakest_attribute = min(attributes.items(), key=lambda kv: kv[1]["page_count"])[0]
    sym = _currency_symbol(price)
    threshold = int(price["median"])
    return [(
        "complex",
        "Best %s for %s under %s%s with %s" % (
            entity_text, weakest_audience, sym, "{:,}".format(threshold), weakest_attribute
        ),
    )]


def comparison_family_cross_entity(entity_texts):
    if len(entity_texts) < 2:
        return []
    a, b = entity_texts[0], entity_texts[1]
    return [("comparison", "%s vs %s" % (a.capitalize(), b.capitalize()))]


PER_ENTITY_FAMILIES = [
    entity_family, price_family, attribute_family, audience_family,
    use_case_family, quality_family, recommendation_family,
    availability_family, complex_family,
]
