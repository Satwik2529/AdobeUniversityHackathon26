"""Query difficulty — a deterministic count of distinct non-entity
requirement categories the query actually combines. Used to group and
filter generated queries, and to show coverage-by-difficulty so a
falling curve (simple facts answered, combinations not) is visible
instead of one flat average.
"""

LABELS = {
    "L1": "Entity only",
    "L2": "Entity + one requirement",
    "L3": "Entity + two requirements",
    "L4": "Entity + three requirements",
    "L5": "Entity + four or more requirements",
}


def classify_difficulty(evaluated_requirements):
    categories = {
        r["category"] for r in evaluated_requirements
        # "combination" is a derived consistency check over the OTHER
        # requirements, not something the user separately asked for -- it
        # must not inflate the difficulty count of the query that produced it.
        if r["category"] not in ("entity", "unrecognized_term", "combination")
    }
    n = len(categories)
    if n == 0:
        return "L1"
    if n == 1:
        return "L2"
    if n == 2:
        return "L3"
    if n == 3:
        return "L4"
    return "L5"
