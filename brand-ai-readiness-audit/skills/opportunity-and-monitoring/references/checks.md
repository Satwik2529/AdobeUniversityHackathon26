# OPP synthesis rule catalogue

**This document is generated against the implementation and must match it exactly.**
This is not a detector: it emits `opportunities` and a `measurement_plan`, never a
`finding`, and the entrypoint's `action_sequence` is built centrally from `findings`
alone by `merge_findings.build_action_sequence` -- this skill does not produce or
touch it. Five rule families, one deterministic selection pipeline, one hard cap.

## Input and output contract

```bash
python3 scripts/select_opportunities.py --snapshot snapshot.json \
  --findings audit-output/findings-*.json --out opportunities.json
```

`--findings` accepts one or more paths or globs, expanded and deduplicated exactly like
`merge_findings.py`'s own `--findings` argument. Each file is either a bare list of
finding dicts or a detector-shaped payload (`{"detector":..., "findings":[...],
"not_assessed":[...]}`); `not_assessed` entries are ignored here (the entrypoint folds
those into `coverage` directly). A finding with no `check_id` is skipped rather than
crashing the run.

**Output:** `{"opportunities": [...], "measurement_plan": {...}}`, loaded verbatim by
`merge_findings.py` into the final report's `opportunities` and `measurement_plan`
fields. The report schema only requires these to be an array and an object
respectively, so this shape is this skill's own, internally consistent contract, not
a second schema competing with the report's.

## Severity: reused, not reinvented

`_derive_severity` is a **verbatim duplicate** of `merge_findings.derive_severity`
(same tables, same stepping, same caps, same small-sample guard), kept in sync
deliberately -- the same "duplicate small shared logic rather than cross-import"
convention every detector in this marketplace already follows. `_score` combines
that severity with `REACH_WEIGHT` to rank candidate opportunities; it is the *same*
severity concept the final report will independently compute for the underlying
findings, not a second, competing scoring model.

## The five rule families

### 1. Cross-detector compound (`_detect_compounds`)

A small, named lookup table of detector pairs. Fires only when at least one finding
from each named detector shares a real URL overlap (`affected_urls` intersect) --
never merely "both detectors fired somewhere on the site."

| Detector pair | Category | Opportunity |
| --- | --- | --- |
| crawl-access-audit + render-readability-audit | `cross-detector-template` | Treat access and render problems on the same template as one compound gate |
| structured-data-entity-audit + answer-retrievability-audit | `entity-schema-alignment` | Align machine-readable structured data with the visible canonical facts |
| answer-retrievability-audit + engagement-audit | `engagement-action-pathway` | Create a reusable answer-to-action pathway on this template |
| freshness-corroboration-audit + structured-data-entity-audit | `freshness-source-of-truth` | Establish one canonical entity/fact source and propagate it |
| freshness-corroboration-audit + answer-retrievability-audit | `freshness-source-of-truth` | Establish a canonical, maintained fact surface rather than patching pages |
| crawl-access-audit + answer-retrievability-audit | `access-remediation` | Fix access before investing further in content optimisation |

### 2. Template leverage (`_detect_template_leverage`)

Distinct from the named pairs above, and given its **own category**
(`template-leverage`) specifically to avoid the confusion an earlier draft had of
reusing `cross-detector-template` for both: this rule fires on **any** 2+ distinct
check_ids (same detector or different detectors) sharing the same set of 2+
`affected_urls`, when that exact finding set is not already explained by a named
compound above. "One template, several findings" is itself useful signal even
without a hand-written relationship between the specific checks involved.

### 3. Monitoring (`_detect_monitoring`)

Tied to specific, real check_ids already present in the input findings -- never
speculative. Currently: `FRC.INTRA_SITE_FACT_CONFLICT`, `FRC.SUPERSEDED_CONTENT_LIVE`,
`SDE.ORG_IDENTITY_CONFLICT`. Each names what to re-check, why (a defect that occurred
once is evidence it can recur, not evidence it will), a cadence, and scores below
active remediation (`score * 0.6`) so monitoring never outranks a fix for the same
underlying problem.

### 4. Deferred capability (`_deferred_capability_opportunities`)

A small, fixed set of capabilities this marketplace cannot assess from a snapshot,
always present, competing for the same 8 slots as everything else (see below), scored
low (`0.1`) so they only displace genuine remediation when few or none exist -- exactly
the case (a clean or near-clean site) where surfacing them is most useful:

- Actual behavioural engagement (click-through, conversion, bounce, time on page)
- External/off-site corroboration of key facts
- Actual AI referral traffic and citation frequency

### 5. Measurement plan (`_build_measurement_plan`)

Always emitted, never gated or capped (it is a plan, not an opportunity). Four
tracks always present (Visibility, Accessibility, Factual accuracy, Regression),
matching `render_report_md.py`'s expected `{track, what, how, cadence}` shape
exactly; a fifth ("Engagement pathway coverage") is added only when the input
findings include at least one from `engagement-audit`, since recommending an
engagement-specific measurement track on a site where nothing was even checked for
engagement would be unsupported. The plan always carries a `caveat` about assistant
personalisation and sample-size discipline; never a numeric baseline (`baseline: N`),
since none exists to report.

## Selection pipeline (deterministic)

1. Run all three "candidate" rule families (compound, template-leverage, monitoring)
   plus the fixed deferred-capability set.
2. **Non-duplication gate**: an opportunity whose entire `related_findings` is a
   single check_id is dropped unless its category is `monitoring` (monitoring is
   legitimately single-check by design -- it recommends *watching*, which is a
   different ask than the check's own fix, not a restatement of it).
3. **Dedup**: candidates sharing the same `(category, related_findings)` key collapse
   to the highest-scored instance.
4. **Sort**: by descending score, ties broken by title, so output order never depends
   on dict/set iteration order.
5. **Cap**: the entrypoint's own `SKILL.md` states "at most 8 opportunities" as a
   total; this is a single, unified cap across every category including
   deferred-capability entries, not 8 remediation opportunities plus an unbounded
   appendix.
6. Sequential `OPP-NNN` ids are assigned only after the final sort and cap, so ids
   are stable for a given input regardless of which rule produced which candidate.

## What this skill does NOT do

- **Does not produce findings.** `related_findings` references the `check_id`s that
  justify an opportunity; it is never itself scored, deduplicated by
  `merge_findings.deduplicate`, or counted in `summary.total_findings`.
- **Does not produce `action_sequence`.** That remains entirely
  `merge_findings.build_action_sequence`'s responsibility, derived from `findings`
  directly.
- **Does not invent causality or business outcomes.** Every mechanism is phrased as
  "this fixes X because Y," never "this will increase/decrease Z by N%."
- **Does not touch the network.** No detector logic is duplicated or re-run; every
  fact used here was already gathered by the collector and the detectors.

## Known limitations

1. **Compound detection is page-overlap-based, not semantically verified.** Two
   findings from a named detector pair sharing a URL are treated as a genuine
   compound even when the specific facts involved are not obviously related (a
   stale copyright year and a conflicting phone number, say, both happening to be
   wrong on the homepage). The opportunity's mechanism text should be read alongside
   the underlying check_ids, not assumed automatically precise.
2. **The compound and monitoring rule sets are small and fixed.** A genuinely novel
   cross-detector relationship, or a new class of recurring defect, is not detected
   until a rule for it is added; this is a deliberate trade against an
   over-engineered, self-inferring correlation engine for a hackathon-scoped
   marketplace.
3. **Archetype gating is currently latent, not applied as a hard filter.** The real
   `site_archetype` values (`ecommerce`, `docs`, `media`, `local-business`, `mixed`,
   `brochure`, `unknown`) are read and normalised, but the current rule set does not
   yet vary its recommendations by archetype the way `references/opportunity-catalog.md`
   describes for a fuller future catalogue; every current rule is archetype-agnostic
   by construction (a compound access+render finding matters regardless of site type).
