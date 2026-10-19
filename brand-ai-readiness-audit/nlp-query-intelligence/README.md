# NLP Query Intelligence

← [Back to project README](../../README.md)

A standalone, read-only subsystem layered on top of an existing
brand-ai-readiness-audit run. It never modifies the existing audit and the
existing audit does not depend on it — see "Isolation" below.

It answers one question a raw findings report does not: **for a specific
natural-language query someone might type into an AI assistant, does this
website actually expose enough retrievable evidence to support an answer?**

It does **not** query Google, ChatGPT, Gemini or Perplexity, and makes no
claim about what any of them would actually say. It tests only whether the
audited site's own already-captured content contains sufficient evidence
for the query's requirements.

## Not a marketplace skill

This directory is deliberately **not** under `skills/` and is **not**
registered in `marketplace.json`. It is an application subsystem the
frontend calls directly, not a tenth detector in the funnel-gate pipeline.

## Data flow

```
audit-output/snapshot.json  (read-only)  ─┐
audit-output/report.json    (read-only, optional) ─┤
                                                     ▼
                                       nlp-query-intelligence/pipeline.py
                                                     │
                                                     ▼
                                          nlp-output/  (its own tree)
```

Nothing under `nlp-query-intelligence/` is imported by anything under
`skills/`, and `pipeline.py` never opens `snapshot.json` or `report.json`
in write mode.

## Usage

```bash
python3 pipeline.py profile  --snapshot audit-output/snapshot.json --out nlp-output/website-profile.json
python3 pipeline.py generate --snapshot audit-output/snapshot.json --profile nlp-output/website-profile.json --out nlp-output/generated-queries.json
python3 pipeline.py test     --query "Best laptop for CSE students under ₹60,000 with 16GB RAM" \
                              --snapshot audit-output/snapshot.json \
                              --report audit-output/report.json \
                              --out nlp-output/query-results/q1.json
python3 pipeline.py compare  --results nlp-output/query-results/q1.json nlp-output/query-results/q2.json \
                              --out nlp-output/comparisons/c1.json
```

`--profile` and `--report` are always optional — `test`/`generate` build a
profile in memory from the snapshot if none is given, and finding
correlation is silently skipped (not an error) if no report is supplied.

## Hybrid NLP, no mandatory API key

Normalization → regex/pattern rules → a small hand-maintained controlled
taxonomy (`lib/vocabulary.py`) → evidence matching against the snapshot's
own text. No external LLM or embedding call anywhere in the default path;
nothing here requires an API key.

## Internal architecture

One domain-agnostic engine; only the *vocabulary* it's handed changes per
site. `lib/domain_vocabulary.py` is the single resolution point — nothing
else branches on domain type.

```
snapshot.json / report.json
        │
        ▼
snapshot_adapter.py / report_adapter.py     parse the audit's own output
        │
        ▼
domain_profiler.py                          classify domain: shopping | education | healthcare | generic
        │
        ▼
entity_schema.py                            build per-entity schemas (candidate entities, attributes, prices) from the snapshot
        │
        ▼
nlp_engine.py                               parse a query: intent, entity, constraints, attributes, qualifiers
        │            (normalizer.py for tokenization/phrase matching, domain_vocabulary.py for the active vocabulary)
        ▼
requirement_validator.py                    is each requirement even valid to ask of this entity → INVALID_REQUIREMENT gating
        │
        ▼
evidence_index.py  +  evidence_matcher.py   locate and verify evidence per requirement, against the snapshot only
        │
        ▼
combination_checker.py                      cross-requirement check — does ONE page account for more than one requirement's evidence
        │
        ▼
scoring.py  +  query_quality.py  +  opportunity.py  +  difficulty.py    five independent dimensions, never one blended percentage
        │
        ▼
schema.py                                   orchestrates the above into one query-result object, validates it against assets/*.schema.json
        │
        ▼
recommendations.py  +  finding_correlator.py (optional, needs --report)  +  differential.py (optional, needs two results)
        │
        ▼
pipeline.py                                 the CLI surface: profile | generate | test | compare | dataset
```

`query_generator.py` and `query_templates.py` are the `generate` path's own
producers — they build candidate queries from a site's `entity_schema.py`
output and run each one through the same `schema.py` orchestration as a
manually typed query, so generated and custom queries are scored identically.

| File | Responsibility |
|---|---|
| `nlp_engine.py` | Parses one natural-language query into intent/entity/constraints/attributes/qualifiers |
| `entity_schema.py` | Builds what's actually known about each entity from the snapshot |
| `evidence_index.py` / `evidence_matcher.py` | Finds and verifies evidence for one requirement |
| `combination_checker.py` | Blocks "Frankenstein" answers assembled from unrelated products |
| `requirement_validator.py` | Decides whether a requirement is even meaningful for this entity |
| `scoring.py` / `query_quality.py` / `opportunity.py` / `difficulty.py` | The five scoring dimensions |
| `domain_profiler.py` / `domain_vocabulary.py` | Domain detection and the four pluggable vocabularies |
| `query_generator.py` / `query_templates.py` | Builds realistic candidate queries from a site's own entity schemas |
| `schema.py` | Orchestrates a full query result and validates it against `assets/*.schema.json` |

## Isolation

- Reads `snapshot.json` / `report.json` read-only; never writes to either.
- Writes only under its own `nlp-output/` tree.
- Makes no network requests of its own — evidence comes only from fields
  already captured in `snapshot.json`.
- Can be deleted entirely without changing what `audit.py` or any skill does.

## Running the tests

```bash
python3 tests/run_tests.py
```

18 test modules over 8 synthetic fixtures — see
[tests/README.md](tests/README.md) for what each one covers.

## Related documentation

- [Project root README](../../README.md) — whole-project architecture, quick start
- [Brand AI-Readiness Audit](../README.md) — the 9-skill backend this subsystem reads output from
- [tests/README.md](tests/README.md) — test file and fixture breakdown
