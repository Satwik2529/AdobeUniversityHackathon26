---
name: opportunity-and-monitoring
description: Turn evidence-backed findings into what a site owner should do next, and how they will know it worked. Correlates findings across detector pairs into compound, template-level opportunities, surfaces cases where one template fix would address several findings at once, recommends monitoring for defect classes that have already recurred once, documents the capabilities this snapshot cannot assess, and emits a standing measurement plan. Never emits findings, never re-derives final severity, and never touches action_sequence, which the entrypoint builds centrally. Use this at the end of an AI-readiness audit, or whenever someone asks what to do beyond fixing specific defects, or how to measure AI visibility over time. Read-only and recommend-only; consumes only the snapshot and the detectors' own findings, and makes no network requests.
license: Apache-2.0
compatibility: Requires Python 3.9 or newer. Consumes a snapshot and the raw per-detector findings files (before the entrypoint's own deduplication, severity assignment, or id numbering). No network access needed or possible.
allowed-tools: Bash Read
metadata:
  role: uplift
  namespace: OPP
---

# Opportunity and monitoring

This is a synthesis skill, not a detector. The detectors all take a snapshot as input
and answer "what is wrong here?" This skill takes their findings as input and answers
"given these findings and how they relate, what should the site owner do next, and how
will they know it worked?" It is the only skill in this marketplace that reasons about
relationships *between* findings rather than deriving a finding from the snapshot
directly, which is why it is separate.

## Input and output

```bash
python3 scripts/select_opportunities.py --snapshot audit-output/snapshot.json \
  --findings audit-output/findings-*.json --out audit-output/opportunities.json
```

`--findings` accepts one or more paths or globs, expanded exactly like
`merge_findings.py`'s own `--findings` argument, and reads the **raw** per-detector
finding files -- before the entrypoint's own deduplication, severity derivation, or
sequential `id` numbering. Findings at this stage carry `check_id`, `gate_impact`,
`reach`, `certainty` and `evidence_detail`, but no final `severity` and no `F-NNN` id
yet; every opportunity therefore references findings by their stable `check_id`, the
same identifier the measurement plan's regression track diffs consecutive audits by.

Emits `{"opportunities": [...], "measurement_plan": {...}}`. **Never emits findings**,
and **never produces `action_sequence`** -- that remains entirely
`merge_findings.build_action_sequence`'s responsibility, built centrally from
`findings` directly, after this skill has already run.

## The five rule families, then a hard cap

1. **Cross-detector compound.** A small, named table of detector pairs (access+render,
   structured-data+answerability, answerability+engagement, freshness+structured-data,
   freshness+answerability, access+answerability). Fires only on genuine `affected_urls`
   overlap between a finding from each named detector -- never merely "both fired
   somewhere on the site."
2. **Template leverage.** Any 2+ distinct check_ids, from the same detector or
   different ones, sharing the same 2+ affected URLs, when that exact finding set is
   not already covered by a named compound above. Deliberately a distinct category
   (`template-leverage`) from the named-pair rule above, so a reader can tell "this is
   one of the six specific relationships we named" from "this is a generic
   same-template pattern we noticed."
3. **Monitoring.** Tied to specific, real check_ids already present in the input:
   currently `FRC.INTRA_SITE_FACT_CONFLICT`, `FRC.SUPERSEDED_CONTENT_LIVE`,
   `SDE.ORG_IDENTITY_CONFLICT`. Never speculative, never fires on a check_id that
   is not actually present.
4. **Deferred capability.** A small, fixed set of things this snapshot cannot
   measure (behavioural engagement, off-site corroboration, actual AI referral/
   citation frequency), always present, scored low.
5. **Measurement plan.** Always emitted, never gated or capped -- it is a plan, not
   an opportunity.

**Hard cap: 8 total**, matching the entrypoint's own documented contract exactly
("it returns at most 8 opportunities"). This is one unified cap across every
category, including deferred-capability entries -- not 8 remediation opportunities
plus an unbounded appendix. Deferred-capability entries are scored low enough that
they only occupy a slot when few or no higher-priority opportunities exist, which is
exactly the case (a clean or near-clean site) where surfacing them is most useful.

Selection is deterministic: candidates are gated (non-duplication: a single-check_id
opportunity is dropped unless it is a monitoring recommendation, which is a
legitimately different ask than the check's own fix), deduplicated by
`(category, related_findings)`, sorted by score with title as a tiebreaker, and only
then capped and assigned sequential `OPP-NNN` ids -- so output order and ids never
depend on dict or set iteration order.

Full catalogue: `references/checks.md`. Opportunity ideas beyond the current rule set,
organised by funnel gate, for future extension: `references/opportunity-catalog.md`.
The measurement plan's structure: `references/measurement-plan.md`.

## Severity, reused not reinvented

Prioritisation uses `_derive_severity`, a verbatim duplicate of
`merge_findings.derive_severity` -- the same tables, the same stepping and caps, kept
in sync deliberately, matching the "duplicate small shared logic rather than
cross-import" convention every detector in this marketplace already follows. This is
not a second, competing scoring model; it is the same severity concept the final
report will independently compute for the same findings, reused here to rank
opportunities rather than findings.

## Ownership boundary

This skill is a pure findings-and-snapshot consumer. It makes no network requests of
any kind, launches no browser, calls no external API, search engine, or analytics
platform, and requires no credentials -- `site-snapshot-collector` remains the only
network-touching component in this marketplace. It does not duplicate any detector's
own logic: it reads `check_id`, `detector`, `affected_urls`, and the severity-input
fields already computed by each detector, and combines them; it never re-derives a
fact about the site that a detector is responsible for observing.

## Honesty rules

- Correlation is not causality. Two related findings co-occurring is described in
  mechanism terms ("a shared template fix may address both"), never as a business
  outcome, a percentage, or a guarantee.
- Never claim a behavioural metric this snapshot cannot observe: no click-through
  rate, conversion rate, bounce rate, time on page, actual AI referral traffic, or
  citation frequency. These become measurement or deferred-capability entries, never
  an observed result.
- Never invent a numeric baseline. Where none exists, say so; do not fabricate one.
- Never claim a technique guarantees citation, ranking or inclusion.
- Never recommend paid placement, sponsorship, influencer deals, paying an AI vendor
  for placement, agency retainers, hiring, acquisitions, or co-branding. If the main
  lever is "spend money so someone else features us," it does not belong here.
- Never recommend fabricating content, such as marking up questions a page does not
  answer or publishing facts the brand cannot substantiate.
- A healthy site stays healthy: no findings, or only informational ones, produces no
  manufactured remediation opportunity. Measurement and deferred-capability entries
  may still appear, since they are useful regardless of current health.
