"""Cross-requirement joint-satisfiability check — the fix for a real gap
found during Phase 4 quality review: evidence_matcher.py verifies each
requirement independently against the whole set of entity pages, so
"price <= X" and "RAM = Y" and "for students" can each be individually
SUPPORTED while being true of three DIFFERENT products, not one. A query
like "laptop for students under ₹60,000 with 16GB RAM" was scoring 100%
coverage even when no single product on the site actually meets all
three criteria at once — the system was assembling a "Frankenstein"
answer out of unrelated evidence instead of verifying the combination.

This runs AFTER evidence_matcher.py, over its own output: it only reads
which page each SUPPORTED, cross-entity-schema-valid requirement's
evidence came from, and asks whether any single page accounts for more
than one of them. Nothing here re-touches the snapshot or invents new
evidence — it is a consistency check over evidence already found.
"""
from collections import defaultdict

# entity/quality_qualifier/unrecognized_term are deliberately excluded:
# entity identity isn't "one of several facts a product must jointly
# satisfy", a qualifier's evidence is diffuse brand-copy rather than a
# per-product fact, and unrecognized terms never reach SUPPORTED at all.
_COMBINABLE_CATEGORIES = {"price_constraint", "attribute", "audience", "use_case"}


def check_combination(evaluated_requirements):
    """Returns a synthesized "combination" requirement dict, or None if
    there were fewer than two combinable, evidenced requirements to check
    (nothing to combine — a single-fact query is not a "Frankenstein"
    risk by construction)."""
    candidates = [
        r for r in evaluated_requirements
        if r["category"] in _COMBINABLE_CATEGORIES
        and r["evidence"]["status"] == "SUPPORTED"
        and r["evidence"].get("url")
    ]
    # One evidenced fact per category/key at most (already true upstream,
    # de-duplicated defensively here so a repeated requirement can't
    # inflate the "how many were satisfied together" count).
    seen_identity = set()
    deduped = []
    for r in candidates:
        identity = (r["category"], r["key"])
        if identity in seen_identity:
            continue
        seen_identity.add(identity)
        deduped.append(r)
    candidates = deduped

    if len(candidates) < 2:
        return None

    by_url = defaultdict(set)
    labels_by_identity = {}
    for r in candidates:
        identity = (r["category"], r["key"])
        by_url[r["evidence"]["url"]].add(identity)
        labels_by_identity[identity] = r.get("raw") or r["key"]

    total_required = set(labels_by_identity.keys())
    best_url, best_set = max(by_url.items(), key=lambda kv: len(kv[1]))
    best_labels = [labels_by_identity[i] for i in best_set]
    missing_labels = [labels_by_identity[i] for i in (total_required - best_set)]

    if len(best_set) == len(total_required):
        status = "SUPPORTED"
        note = "One product satisfies all %d of these requirements together: %s." % (
            len(total_required), ", ".join(sorted(best_labels)))
        confidence = 0.8
    elif len(best_set) >= 2:
        status = "PARTIALLY_SUPPORTED"
        note = (
            "The closest single match satisfies %d of %d requirements together (%s); %s could not be confirmed "
            "on that same product." % (
                len(best_set), len(total_required), ", ".join(sorted(best_labels)), ", ".join(sorted(missing_labels))
            )
        )
        confidence = 0.5
    else:
        status = "NOT_FOUND"
        note = (
            "Each of these requirements is individually supported somewhere on the site, but never on the same "
            "product: %s." % ", ".join(sorted(labels_by_identity[i] for i in total_required))
        )
        confidence = 0.5

    return {
        "id": "R-COMBINATION",
        "category": "combination",
        "key": "single_product_match",
        "raw": " + ".join(sorted(labels_by_identity[i] for i in total_required)),
        "detail": {"requirement_count": len(total_required), "best_match_count": len(best_set)},
        "evidence": {
            "status": status,
            "url": best_url,
            "field": "cross_requirement_consistency",
            "observed_value": "%d/%d requirements confirmed on one product" % (len(best_set), len(total_required)),
            "evidence_type": "cross_page_combination",
            "confidence": confidence,
            "note": note,
        },
    }
