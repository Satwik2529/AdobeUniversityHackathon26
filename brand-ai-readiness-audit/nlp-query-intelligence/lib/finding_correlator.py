"""Cautious cross-referencing between a weak query requirement and the
existing audit's own report.json findings. Never asserts causality — every
relation is phrased "potentially related" and requires an actual URL
overlap between the requirement's evidence and the finding's affected_urls,
not just a topical guess. If report.json wasn't supplied, this step is
skipped entirely rather than treated as an error (see report_adapter.py).
"""

_WEAK_STATUSES = {"NOT_FOUND", "CONTRADICTED", "PARTIALLY_SUPPORTED"}

# Which existing check_id prefixes are plausibly relevant to a weak
# requirement of a given category. Deliberately small and hand-written —
# adding a category here is a reviewable decision, not a heuristic guess.
_CATEGORY_TO_CHECK_PREFIXES = {
    "entity": ["SDE.", "ACC."],
    "price_constraint": ["FRC.", "SDE."],
    "attribute": ["ANS.", "RND."],
    "audience": ["ANS.", "ENG."],
    "use_case": ["ANS.", "ENG."],
    "quality_qualifier": ["RND.", "ANS."],
    "combination": ["SDE.", "FRC."],
}


def correlate(evaluated_requirements, report):
    if not report:
        return []
    findings = report.get("findings", []) or []
    correlations = []
    for req in evaluated_requirements:
        evidence = req["evidence"]
        if evidence["status"] not in _WEAK_STATUSES:
            continue
        prefixes = _CATEGORY_TO_CHECK_PREFIXES.get(req["category"], [])
        if not prefixes:
            continue
        requirement_url = evidence.get("url")
        for finding in findings:
            check_id = finding.get("check_id", "")
            if not any(check_id.startswith(p) for p in prefixes):
                continue
            affected = finding.get("affected_urls") or []
            if requirement_url and requirement_url not in affected:
                continue
            correlations.append({
                "requirement_id": req["id"],
                "requirement_category": req["category"],
                "requirement_key": req["key"],
                "finding_id": finding.get("id"),
                "check_id": check_id,
                "finding_title": finding.get("title"),
                "relation": "Potentially related — may contribute to weak %s evidence for this query."
                            % req["category"].replace("_", " "),
            })
    return correlations
