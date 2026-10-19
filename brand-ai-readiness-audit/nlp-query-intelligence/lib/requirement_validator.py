"""The TOKEN -> CONCEPT -> DOMAIN RELATIONSHIP gate.

A word matching a taxonomy entry (vocabulary.py) only establishes that
the word is a recognized CONCEPT — "RAM" is a known attribute concept
somewhere on the web. It says nothing about whether that concept is a
genuine property of the specific entity this query is about. This module
is what answers that second question, using entity_schema.py's per-entity
relationships (built only from pages that actually mention the entity) as
the source of truth. This is the fix for cross-entity attribute leakage:
"RAM", discovered from laptop pages, can never validate a keyboard
requirement, because entity_schemas["keyboard"]["attributes"] was built
only from pages that mention "keyboard".

Every requirement gets a verdict here before evidence_matcher.py ever
looks anything up:

  - no entity in the query at all        -> NOT_ASSESSABLE (nothing to
                                             scope evidence by)
  - unrecognized_term (not in ANY         -> NOT_ASSESSABLE (a real
    controlled-vocabulary category)          capability gap, not a
                                              fabricated pass or fail)
  - recognized concept, but NOT in this   -> INVALID_REQUIREMENT (the
    entity's own discovered schema           query asked about something
                                              with no evidenced relationship
                                              to this entity on this site)
  - recognized concept, present in this   -> proceed to evidence_matcher
    entity's schema                          for the real SUPPORTED /
                                              PARTIALLY_SUPPORTED /
                                              NOT_FOUND / CONTRADICTED call
  - entity / price_constraint /           -> proceed to evidence_matcher
    quality_qualifier                        unchanged (see module notes)
"""

# category -> which entity_schema list membership decides its fate.
# entity, price_constraint and quality_qualifier are NOT schema-gated:
# price is a universal product property, and qualifiers are evaluated by
# a fixed, entity-independent phrase list (evidence_matcher.py already
# requires an entity to scope evidence, which is enough for those).
_SCHEMA_GATED_CATEGORIES = {
    "attribute": "attributes",
    "audience": "audiences",
    "use_case": "use_cases",
}

RESOLVED = "resolved"
PENDING = "pending"


def _evidence(status, note):
    return {"status": status, "url": None, "field": None, "observed_value": None,
            "evidence_type": None, "confidence": None, "note": note}


def validate(requirements, entity_requirement, entity_schemas):
    """Returns a list of (requirement, outcome) where outcome is either
    ("resolved", evidence_dict) — final, evidence_matcher should not touch
    it — or ("pending", None) — evidence_matcher should evaluate it as
    before."""
    entity_schema = entity_schemas.get(entity_requirement["key"]) if entity_requirement else None
    out = []
    for req in requirements:
        category = req["category"]

        if category == "unrecognized_term":
            out.append((req, RESOLVED, _evidence(
                "NOT_ASSESSABLE",
                "%r is not part of this domain's recognized vocabulary (attribute, audience, use-case or "
                "qualifier concept), so it cannot be checked against the site's evidence." % req["key"],
            )))
            continue

        schema_field = _SCHEMA_GATED_CATEGORIES.get(category)
        if schema_field is None:
            out.append((req, PENDING, None))
            continue

        if entity_requirement is None:
            out.append((req, RESOLVED, _evidence(
                "NOT_ASSESSABLE",
                "No product or category was recognized in this query, so %r cannot be checked." % req["key"],
            )))
            continue

        known = set((entity_schema or {}).get(schema_field, []))
        if req["key"] not in known:
            out.append((req, RESOLVED, _evidence(
                "INVALID_REQUIREMENT",
                "%r is a recognized %s concept, but no evidence connects it to %r on this site — none of the "
                "pages that identify %r mention it." % (
                    req["key"], category.replace("_", " "), entity_requirement["key"], entity_requirement["key"]
                ),
            )))
            continue

        out.append((req, PENDING, None))
    return out
