# Query Intelligence — tests

Purpose of this document: with 18 test modules and 8 fixture sites, explain
what each one actually covers so a change to `lib/` can be checked against
the right file without opening all of them.

← [Back to Query Intelligence](../README.md)

## Running them

```bash
python3 run_tests.py
```

A layered harness, mirroring the parent audit's own `tests/run_tests.py`:

| Layer | Checks | Where |
|---|---|---|
| **NL0** fixture integrity | Every `fixtures/*/snapshot.json` parses | `run_tests.py` itself |
| **NL1** unit tests | Every `test_*.py` module (`unittest` discovery) | this directory |
| NL3 determinism | Same input → same output, re-run twice | inline within NL1 (`test_query_generator.py`, `test_differential.py`) |
| NL4 output schema | Every emitted JSON validates against `assets/*.schema.json` | inline within NL1 (`schema.py`'s own `validate_query_result`) |
| **NL5** negative controls | Evidence matching isn't fooled by unrelated reuse of the same word | `test_negative_controls.py`, run and reported separately |

Run one file directly during development: `python3 -m unittest test_nlp_engine.py -v`.

## Test files, by pipeline stage

| File | Exercises |
|---|---|
| `test_normalizer.py` | Text normalization, tokenization, word-boundary-safe phrase matching (`contains_phrase`/`find_phrase`) |
| `test_domain_profiler.py` | Domain classification (`shopping`/`education`/`healthcare`/`generic`) from a snapshot's structured-data types and keyword fallback |
| `test_domain_vocabulary.py` | The four pluggable vocabulary bundles and `get_vocabulary()`/`concept_words_for()` |
| `test_entity_schema.py` | Per-entity schema construction from the snapshot — candidate entities, phrase extraction, price-signal scoping |
| `test_evidence_matcher.py` | Requirement-to-evidence matching for every requirement category (price, attribute, audience, use case) |
| `test_nlp_engine.py` | Query parsing: intent, entity detection (incl. comparison queries), constraints, qualifiers, unrecognized terms |
| `test_requirement_validator.py` | Domain-relationship gating — is a requirement even valid to ask of this entity (`INVALID_REQUIREMENT`) |
| `test_combination_checker.py` | Cross-requirement co-occurrence — the fix for evidence assembled from unrelated products |
| `test_scoring.py` | The five independent scoring dimensions and their point-by-point math |
| `test_opportunity.py` | Opportunity scoring — gated to actionable gaps only, excludes `INVALID_REQUIREMENT` |
| `test_query_quality.py` | The five query-quality factors |
| `test_query_generator.py` | Generated-query diversity, per-entity families, quality gating |
| `test_finding_correlator.py` | Linking a Query Intelligence gap back to the audit's own findings (`report.json`), when a report is supplied |
| `test_differential.py` | Comparing two tested queries — which requirement explains the score difference |
| `test_negative_controls.py` | The specific traps: *premium laptop* vs. *subscription*, *keyboard* vs. *laptop RAM*, etc. — see NL5 above |
| `test_pipeline_integration.py` | `pipeline.py` invoked as a subprocess with `--snapshot`/`--out`, exactly as the frontend orchestrator calls it |

`_pathfix.py` is not a test — every other module imports it first so `lib/`
resolves regardless of the working directory `python3` was started from.

## Fixtures

Synthetic sites under `fixtures/`, one directory per `snapshot.json`:

| Fixture | Domain | Purpose |
|---|---|---|
| `shopping-site` | shopping | The main case — laptops with real attributes (RAM, storage, battery), audiences, use cases |
| `mixed-category-site` | shopping | Laptop **and** keyboard on the same site — the cross-entity leakage trap (keyboard-with-RAM) |
| `university-site` | education | `schema_types: ["Course"]` — verifies domain detection and the education vocabulary |
| `hospital-site` | healthcare | `schema_types: ["MedicalClinic"]` — verifies domain detection and the healthcare vocabulary |
| `unknown-domain-site` | generic | A consulting firm with no recognizable `schema_types` — verifies the generic fallback, not a wrong guess |
| `sparse-site` | shopping | Minimal content — answerability/coverage on a thin snapshot |
| `blog-site` | generic | No product/entity structure at all |
| `non-english-site` | shopping | Non-English content — language-scoped checks behave, lexical checks don't over-claim |

## Related documentation

- [Query Intelligence](../README.md) — module overview, pipeline, isolation
- [Project root README](../../../README.md) — whole-project architecture
