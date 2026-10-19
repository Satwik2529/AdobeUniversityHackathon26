"""Recommendation text, generated only from the evidence gap actually
computed for this query — never generic boilerplate independent of the
result.
"""

_WEAK_STATUSES = {"NOT_FOUND", "CONTRADICTED", "PARTIALLY_SUPPORTED"}

_LABELS = {
    "entity": "product identity",
    "price_constraint": "price",
    "attribute": "attribute",
    "audience": "audience relevance",
    "use_case": "use-case relevance",
    "quality_qualifier": "quality claim",
}


def build_recommendations(evaluated_requirements):
    out = []
    for req in evaluated_requirements:
        evidence = req["evidence"]
        if evidence["status"] not in _WEAK_STATUSES:
            continue
        if req["category"] == "combination":
            # The combination check's own note already names which
            # product came closest and what it's missing -- a generic
            # "add evidence" template would be less specific than that.
            out.append({
                "requirement_id": req["id"],
                "category": "combination",
                "status": evidence["status"],
                "recommendation": "Offer one product that meets all of these requirements together: %s" % (
                    evidence.get("note") or req["raw"]
                ),
            })
            continue
        label = _LABELS.get(req["category"], req["category"])
        if evidence["status"] == "NOT_FOUND":
            action = "Add explicit %s evidence (%r) to the pages that describe this product." % (label, req["raw"])
        elif evidence["status"] == "CONTRADICTED":
            action = "Resolve the conflicting %s information found on the site (%r)." % (label, req["raw"])
        else:
            action = "Strengthen the existing %s evidence for %r — it is present but not conclusive." % (
                label, req["raw"])
        out.append({
            "requirement_id": req["id"],
            "category": req["category"],
            "status": evidence["status"],
            "recommendation": action,
        })
    return out
