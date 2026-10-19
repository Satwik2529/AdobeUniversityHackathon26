# Opportunity synthesis fixtures

Unlike every detector's fixtures (real, served websites in `tests/fixtures/`), this
skill's input is a set of already-computed detector findings, not a snapshot of pages.
These fixtures are therefore synthetic finding sets, not served sites: each is a small
JSON file shaped like a detector's own findings output (`{"detector": ..., "findings":
[...], "not_assessed": []}`), constructed to exercise one specific synthesis condition.

Each fixture's intended condition, and why it should or should not produce a given
opportunity, is documented in `scripts/test_opportunity.py`, which is the authoritative,
executable specification these fixtures support. This directory exists to let the
synthesis logic also be exercised via the same `--findings` CLI a real audit run uses,
end to end, separate from the unit-test factories.
