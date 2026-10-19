"""Builds website-profile.json from a snapshot — evidence-grounded, never
hardcoded to a category. Every list in the output is something that was
actually observed on the audited site.

Entity candidacy and per-entity attribute/audience/use-case/price
relationships now live in entity_schema.py — this module classifies the
domain type and assembles the top-level profile, but `entity_schemas` is
the authoritative source requirement_validator.py checks against. The
top-level `attributes`/`audiences`/`use_cases`/`price_signals` fields
here are kept for backward-compatible display purposes only (a
site-wide union) — nothing in the reasoning pipeline should treat them as
"this attribute belongs to this entity"; that question can only be
answered per-entity, via `entity_schemas[entity]`.
"""
from collections import Counter

from . import normalizer, snapshot_adapter, structured_data as sd, vocabulary
from .entity_schema import build_entity_schemas
from .evidence_index import EvidenceIndex
from .versions import PROFILER_VERSION

_SHOPPING_TYPES = {"product", "offer", "aggregateoffer", "individualproduct"}
_EDUCATION_TYPES = {"educationalorganization", "college", "university", "school", "course", "coursemodule"}
_HEALTHCARE_TYPES = {"hospital", "medicalorganization", "physician", "medicalclinic", "dentist", "medicalbusiness"}
_CONTENT_TYPES = {"article", "blogposting", "newsarticle", "report"}
_SOFTWARE_TYPES = {"softwareapplication", "webapplication", "mobileapplication"}

# Used only as a fallback when structured data gives no domain signal at
# all (see _keyword_domain_hits) — a handful of strong, low-ambiguity
# terms for the two domains that have no distinctive schema.org type in
# wide use. Deliberately conservative: this only ever fires when
# structured data was silent, and requires >=2 distinct pages before it
# overrides the "generic" default, so a single incidental mention (e.g.
# a "patients" link in an unrelated site's footer) can't misclassify it.
_EDUCATION_KEYWORDS = ["tuition", "admissions", "undergraduate", "graduate program",
                       "faculty", "curriculum", "enrollment", "semester", "campus"]
_HEALTHCARE_KEYWORDS = ["patient", "physician", "appointment", "insurance accepted",
                        "diagnosis", "treatment plan", "clinic", "specialist"]


def classify_domain_type(schema_type_counts, page_type_counts, keyword_hits=None):
    lowered = {t.lower(): c for t, c in schema_type_counts.items()}
    # Structured data is checked against EVERY domain before any generic
    # page_type heuristic is allowed to fire -- the collector's own
    # page-type classifier predates this subsystem and knows nothing
    # about education/healthcare, so it can (and in practice does) label
    # a course or clinic page "product"; a specific, machine-declared
    # schema.org type must always outrank that generic guess.
    if any(t in lowered for t in _EDUCATION_TYPES):
        return "education"
    if any(t in lowered for t in _HEALTHCARE_TYPES):
        return "healthcare"
    if any(t in lowered for t in _SHOPPING_TYPES):
        return "shopping"
    if any(t in lowered for t in _SOFTWARE_TYPES):
        return "software"
    if any(t in lowered for t in _CONTENT_TYPES):
        return "content"
    # No structured signal at all -- fall back to page_type heuristics,
    # then the keyword fallback, in that order.
    if page_type_counts.get("product", 0) >= 2:
        return "shopping"
    if page_type_counts.get("article", 0) >= 2:
        return "content"
    if keyword_hits:
        best_domain, best_count = max(keyword_hits.items(), key=lambda kv: kv[1], default=(None, 0))
        if best_count >= 2:
            return best_domain
    if page_type_counts.get("homepage") and len(page_type_counts) <= 3:
        return "corporate"
    return "generic"


def _keyword_domain_hits(pages):
    """Distinct-page counts of education/healthcare keyword mentions —
    the fallback signal classify_domain_type() uses only when structured
    data was silent (see its docstring)."""
    hits = {"education": 0, "healthcare": 0}
    for page in pages:
        fields = snapshot_adapter.page_text_fields(page)
        blob = normalizer.normalize_text(
            " ".join([fields["title"], fields["meta_description"], " ".join(fields["headings"])])
        )
        if any(normalizer.contains_phrase(blob, k) for k in _EDUCATION_KEYWORDS):
            hits["education"] += 1
        if any(normalizer.contains_phrase(blob, k) for k in _HEALTHCARE_KEYWORDS):
            hits["healthcare"] += 1
    return hits


def _site_wide_price_signals(pages):
    values = []
    currency_votes = Counter()
    for page in pages:
        for offer in sd.iter_offers(page.get("structured_data")):
            price = offer.get("price")
            try:
                if price is not None:
                    values.append(float(price))
                    currency = offer.get("priceCurrency")
                    if currency:
                        currency_votes[str(currency).lower()] += 1
            except (TypeError, ValueError):
                continue
        text_fields = snapshot_adapter.page_text_fields(page)
        for hit in _find_money_safe(text_fields["main_text"][:4000]):
            values.append(hit["value"])
            currency_votes[hit["currency"]] += 1
    if not values:
        return None
    return {
        "min": min(values),
        "max": max(values),
        "sample_size": len(values),
        "currency": currency_votes.most_common(1)[0][0] if currency_votes else None,
    }


def _find_money_safe(text):
    from . import normalizer
    return normalizer.find_money(text)


def build_profile(snapshot, snapshot_hash):
    pages = snapshot_adapter.pages(snapshot)

    schema_type_counts = Counter()
    page_type_counts = Counter()
    for page in pages:
        for t in page.get("schema_types") or []:
            schema_type_counts[t] += 1
        pt = page.get("page_type")
        if pt:
            page_type_counts[pt] += 1

    keyword_hits = _keyword_domain_hits(pages)
    domain_type = classify_domain_type(schema_type_counts, page_type_counts, keyword_hits)

    index = EvidenceIndex(snapshot)
    entity_result = build_entity_schemas(snapshot, index=index, domain_type=domain_type)
    entities = entity_result["entities"]
    entity_schemas = entity_result["schemas"]

    # Site-wide unions, for display only — see module docstring.
    all_attributes = sorted({a for s in entity_schemas.values() for a in s["attributes"]})
    all_audiences = sorted({a for s in entity_schemas.values() for a in s["audiences"]})
    all_use_cases = sorted({u for s in entity_schemas.values() for u in s["use_cases"]})

    categories = sorted({c.get("page_type") for c in snapshot.get("clusters", []) if c.get("page_type")})

    return {
        "profiler_version": PROFILER_VERSION,
        "snapshot_hash": snapshot_hash,
        "site": snapshot.get("site"),
        "pages_considered": len(pages),
        "domain_type": domain_type,
        "entities": entities,
        "entities_degraded": entity_result["degraded"],
        "entity_schemas": entity_schemas,
        "categories": categories,
        "attributes": all_attributes,
        "audiences": all_audiences,
        "use_cases": all_use_cases,
        "price_signals": _site_wide_price_signals(pages),
    }
