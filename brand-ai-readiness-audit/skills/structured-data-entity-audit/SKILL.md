---
name: structured-data-entity-audit
description: Detect why a machine that can read a page still cannot tell what it is about or which real-world brand it belongs to. Extracts JSON-LD, Microdata, RDFa and OpenGraph from a captured snapshot and checks parse validity, per-page-type type coverage, required property completeness, contradictions between structured values and the visible text, markup with no visible counterpart, the presence of one canonical organization entity with a stable identifier, sameAs identity links, brand-name consistency across surfaces, the same stable identifier being described with contradictory property values on different pages, and entity ambiguity risk when a name collides with other things. Use this when auditing why an assistant confuses a brand with something else, attributes the wrong details to it, omits it from category answers, or gets a fact like a phone number or address wrong because two pages disagree. Read-only and recommend-only, consumes a snapshot, and makes no network requests.
license: Apache-2.0
compatibility: Requires Python 3.9 or newer. Consumes a snapshot from site-snapshot-collector. No network access needed.
allowed-tools: Bash Read
metadata:
  role: detector
  funnel_gates: understood
  namespace: SDE
---

# Structured data and entity audit

Funnel gate: **understood**. The text is readable. Can a machine tell what it is, and
whose it is?

## What structured data does and does not do

State this accurately in every fix you write. Structured data helps a machine classify
content and resolve which real-world entity a page is about. That improves retrieval
eligibility and reduces mistaken identity. **It does not guarantee a citation, a ranking
or inclusion in any answer.** A report that claims otherwise is wrong and will mislead
the person acting on it.

The related failure is mistaken identity: when several different things share a name, a
system will mix them up unless something clearly distinguishes one from the others.

## Input and output

```bash
python3 scripts/check_schema_entity.py --snapshot audit-output/snapshot.json --out audit-output/findings-schema.json
```

## Procedure

1. Extract from the **raw HTML** first, since that is what a non-rendering crawler sees.
   Traverse `@graph` fully before declaring any node missing.
2. Validate in order: parse, context, type, required properties, consistency with visible
   text, identity anchoring, per-page-type coverage. See `references/schema-profiles.md`.
3. Gate coverage checks on `page_type` and `page_type_confidence`. Never demand product
   markup from an article, FAQ markup where there is no question-and-answer content, or
   breadcrumb markup on the homepage. This is the most common false positive in this
   family.
4. Compare structured values against the visible text on the same page, after full
   normalisation of currency, digit separators, whitespace and unicode. Report **only
   exact contradictions**, never near-misses.
5. Check entity identity: one canonical organization node, a stable identifier, and
   `sameAs` links that are syntactically valid.
6. Where the same `@id` appears on more than one page, compare identity-bearing
   properties (telephone, address, url) across occurrences. A genuine disagreement is a
   finding; one occurrence simply omitting a field the other states is not.
7. Score entity ambiguity risk from at least two independent signals. Cap it at `medium`
   and flag confidence. This check is inferential by nature and must never be presented
   as measured fact.

Full catalogue: `references/checks.md`.

## Gotchas

- **Microdata and RDFa are valid.** A site marked up entirely in Microdata is not broken.
  JSON-LD is the recommendation for new work and parses more reliably across AI systems,
  so the finding is `low` and phrased as a migration suggestion, never as a defect.
- **One JSON syntax error voids the whole block silently.** There is no visible page
  error, so a parse failure is a serious finding even when the markup looks complete.
- **Structured data injected only by JavaScript belongs to the render detector.** Note it
  here as evidence at most.
- **`sameAs` pointing at inconsistent or dead profiles is worse than no `sameAs`.**
  Always pair the recommendation with making name, URL and description identical on those
  profiles. Never recommend adding links to profiles the brand does not control.
- **Do not fetch anything to verify a link.** Syntactic validation only; recommend that
  the owner run the official validators.
- **A page's own `@id`-referenced entity nesting is a normal pattern, not a defect.**
  `ContactPage.mainEntity`, `Article.author` and `Article.publisher` commonly embed a
  full entity inline rather than by reference; this is walked and compared like any
  other node, not flagged merely for existing.
- **Page-type classification here relies partly on structured data itself.** A page can
  only be confidently typed `article` when Article/BlogPosting markup (or another
  corroborating signal) is already present, so a true "this page should be an article
  but declares no Article markup at all" case is architecturally narrow to detect from
  this snapshot. Coverage checks still run correctly whenever the type is present but
  incomplete.
- **RDFa gives type names, not property values.** The snapshot records which RDFa types
  exist and how many properties were seen, but not their values. RDFa nodes are checked
  for presence (`SDE.NO_ORGANIZATION_NODE`, `SDE.NO_STRUCTURED_DATA`), never for required
  properties or value-level contradictions, which need real data this format doesn't
  provide in the snapshot.
