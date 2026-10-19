# Severity, correlation and priority

Severity describes the damage. Priority describes what to do first. They are computed
separately and must never be conflated.

## 1. Severity

```
severity = f(gate_impact, reach, certainty)
```

| Factor | Values |
| --- | --- |
| `gate_impact` | `blocks` (a funnel gate is shut) / `degrades` / `weakens` |
| `reach` | `sitewide` / `template` (a whole page cluster) / `page` |
| `certainty` | `measured` (observed directly) / `inferred` |

| Severity | Meaning |
| --- | --- |
| `critical` | A gate is shut for a large share of the site. The brand structurally cannot be found, read or cited. |
| `high` | A gate is shut or badly degraded on the most valuable templates, or a key fact is contradicted. |
| `medium` | Real degradation on a subset, or a missing capability with a clear mechanism. |
| `low` | Hygiene. Small compounding effects. |
| `info` | Deliberate configuration, trade-offs or context. **Not a defect.** |

Reach modifiers: `sitewide` may raise one level; `page` lowers one level from a
template-level default.

## 2. Certainty caps (anti-overclaim)

| Condition | Cap |
| --- | --- |
| Evidence is `inferred`, not `measured` | `high` |
| Evidence is nondeterministic (external search) | `high`, and must carry `confidence` |
| Cluster below the sample threshold (fewer than 3 pages) | `medium`, reported page-level |
| Single-signal inference-heavy check | `medium` |
| Capability unavailable | not a finding — `coverage.not_assessed` |

## 3. Cross-skill correlation rules

| Rule | Behaviour |
| --- | --- |
| Funnel suppression | If a sitewide access gate is shut (`ACC.ROBOTS_BLOCKS_ALL`, `ACC.ROBOTS_BLOCKS_RETRIEVAL`, `ACC.UA_BLOCKED`, sitewide `ACC.NOINDEX_ON_CONTENT`), keep downstream findings but demote their priority below the unblocker and state plainly that later fixes cannot help until the gate opens. |
| Duplicate ownership | When two detectors describe the same DOM condition, keep the finding whose fix is authoritative and record the other as `related_checks`. Authoritative owners: render layer beats content layer; access layer beats everything. Pairs today: `FRC.NO_CANONICAL_FACT_SURFACE` over `ANS.NO_CANONICAL_FACT_SURFACE` (live -- both detectors emit their side); and `RND.CONTENT_BEHIND_INTERACTION` over `ANS.SPECS_NOT_EXTRACTABLE`, kept deliberately but inert, since the authoritative check is documented as permanently `not_assessed` (this collector never clicks). Three further pairs whose subordinate was an `ENG.*` check from engagement-audit's superseded scope were removed during final review: none was ever implemented, so they could never fire. The `L6 catalogue integrity` harness layer now fails the build if any rule, `related_checks` entry, gate blocker or fixture expectation names a check_id no detector can emit. |
| Corroborating escalation | `SDE.SCHEMA_VISIBLE_MISMATCH` plus `FRC.INTRA_SITE_FACT_CONFLICT` on the same fact escalates to `critical`: the brand publishes two contradictory machine-readable versions of one fact. Neither detector can see this alone. |
| Coverage honesty | Any check that could not run becomes a `coverage.not_assessed` entry, never a finding. |

## 4. Priority

```
priority_score = impact * reach * (1 / effort) * funnel_precedence
```

`funnel_precedence` is decisive: **earlier gates first**. Perfect markup on a page a
retrieval crawler cannot reach yields nothing. Effort is coarse and honest:
`trivial`, `config`, `template-change`, `platform-change`.

Ties break on reach, then severity, then `check_id`, so ranking is deterministic.

## 5. Action bands in the report

1. **Unblock (do first)** — anything shutting a gate.
2. **Make readable and quotable (next)** — rendering, extractability, structured data, canonical facts.
3. **Keep them and keep it true (ongoing)** — engagement fixes, corroboration, monitoring.
