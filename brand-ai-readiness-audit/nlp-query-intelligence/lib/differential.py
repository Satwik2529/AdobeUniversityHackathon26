"""Query-vs-query differential analysis: what changed, and which newly
introduced (or dropped) requirement explains most of the score delta.
"""


def _requirement_key(entry):
    return "%s:%s" % (entry["category"], entry["key"])


def compare_two(result_a, result_b):
    by_key_a = {_requirement_key(r): r for r in result_a["scoring"]["breakdown"]}
    by_key_b = {_requirement_key(r): r for r in result_b["scoring"]["breakdown"]}

    shared, added, removed = [], [], []
    for key, rb in by_key_b.items():
        ra = by_key_a.get(key)
        if ra is None:
            added.append({"category": rb["category"], "key": rb["key"], "raw": rb["raw"],
                          "status": rb["status"], "points_in_b": rb["points_earned"]})
        else:
            shared.append({
                "category": rb["category"], "key": rb["key"],
                "status_a": ra["status"], "status_b": rb["status"],
                "points_a": ra["points_earned"], "points_b": rb["points_earned"],
                "delta": round(rb["points_earned"] - ra["points_earned"], 1),
            })
    for key, ra in by_key_a.items():
        if key not in by_key_b:
            removed.append({"category": ra["category"], "key": ra["key"], "raw": ra["raw"],
                            "status": ra["status"], "points_in_a": ra["points_earned"]})

    contributors = sorted(shared, key=lambda d: d["delta"])
    for a in added:
        contributors.append({"category": a["category"], "key": a["key"],
                             "status_a": None, "status_b": a["status"],
                             "points_a": 0, "points_b": a["points_in_b"],
                             "delta": round(a["points_in_b"] - 0, 1), "newly_introduced": True})
    contributors.sort(key=lambda d: d["delta"])

    def _summary(r):
        return {
            "id": r.get("query_id"),
            "text": r["nlp"]["raw_query"],
            "score": r["scoring"]["overall_score"],
            "evidence_coverage": r["scoring"]["evidence_coverage"],
            "answerability": r["scoring"]["answerability"],
            "query_quality": r["query_quality"]["overall"],
            "overall_query_health": r["overall_query_health"],
        }

    return {
        "query_a": _summary(result_a),
        "query_b": _summary(result_b),
        "score_delta": result_b["scoring"]["overall_score"] - result_a["scoring"]["overall_score"],
        "health_delta": (
            (result_b["overall_query_health"] or 0) - (result_a["overall_query_health"] or 0)
            if result_a["overall_query_health"] is not None and result_b["overall_query_health"] is not None
            else None
        ),
        "added_requirements": added,
        "removed_requirements": removed,
        "top_contributors": [c for c in contributors if c["delta"] < 0][:5],
    }


def compare_many(results):
    """A flat score table for N results — used by the comparison UI when
    more than two queries are selected; the richer top-contributor narrative
    is inherently pairwise, see compare_two()."""
    return {
        "queries": [
            {
                "id": r.get("query_id"),
                "text": r["nlp"]["raw_query"],
                "score": r["scoring"]["overall_score"],
                "evidence_coverage": r["scoring"]["evidence_coverage"],
                "answerability": r["scoring"]["answerability"],
                "query_quality": r["query_quality"]["overall"],
                "overall_query_health": r["overall_query_health"],
            }
            for r in results
        ]
    }
