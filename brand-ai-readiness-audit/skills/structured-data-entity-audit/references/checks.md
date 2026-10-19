# SDE check catalogue

**This document is generated against the implementation and must match it exactly.**
Every check_id below is implemented in `scripts/check_schema_entity.py` and covered by
`scripts/test_schema_entity.py`. 15 checks, 15 implemented, 0 documented-but-absent.

## How to read the columns

`gate_impact` / `reach` / `certainty` are the **severity inputs** the detector emits, not
a final severity. The entrypoint's `merge_findings.derive_severity` turns those into
`critical`/`high`/`medium`/`low`/`info`, applying reach-based stepping (page reach always
steps down one level; template reach steps down only from critical) and confidence caps.
Where a check needs an outcome the natural math would overshoot, it sets an explicit
`severity_ceiling`, exactly as `crawl-access-audit` and `render-readability-audit` do.

`reach` for every check here is computed the same way as the other detectors: a
population relevant to that specific check (e.g. all sampled content pages, or all
`product`-type pages) and a cluster-size-3 threshold before a claim reaches `template`
or `sitewide`. A finding confined to one page out of several in its population correctly
reports `reach: page`, which lowers its derived severity by one level — this is the same
sample-size discipline established in Milestone F, not a special case for this detector.

## Presence and parsing

| check_id | Fires when | impact / reach / certainty | Pinned | False-positive guard |
| --- | --- | --- | --- | --- |
| `SDE.NO_STRUCTURED_DATA` | No JSON-LD, Microdata or RDFa anywhere across the sampled content pages | degrades / sitewide / measured | -- | Checks all three formats before firing. A Microdata-only or RDFa-only site is `SDE.MICRODATA_ONLY`, not this. |
| `SDE.INVALID_JSONLD` | A `<script type="application/ld+json">` block fails to parse | degrades / template or page / measured | -- | Reports the exact parse error. A broken block alongside a valid one on the same page does not hide the valid one from other checks. |

## Type and property coverage

| check_id | Fires when | impact / reach / certainty | Pinned | False-positive guard |
| --- | --- | --- | --- | --- |
| `SDE.MISSING_TYPE_FOR_TEMPLATE` | A `product` or `article` page (confidently classified) has no corresponding JSON-LD/Microdata type, after full `@graph` traversal | degrades / template or page / measured | -- | Gated on `page_type`: never demands `Product` outside product pages, never demands `Article` outside article pages. A site with no product-type pages at all triggers nothing. |
| `SDE.INCOMPLETE_REQUIRED_PROPS` | The expected type is present but missing a **required** property (`Product`: name, offers; `Article`: headline, datePublished) | weakens / template or page / measured | -- | Only required properties matter here; a missing recommended property (`sku`, `author`) is never flagged by this check at all. |

## Structured vs visible consistency

| check_id | Fires when | impact / reach / certainty | Pinned | False-positive guard |
| --- | --- | --- | --- | --- |
| `SDE.SCHEMA_VISIBLE_MISMATCH` | A `Product.offers.price` disagrees with a price stated in the page's own visible text (same currency), **or** `Product.name` shares no word overlap with the page's own h1 | degrades / template or page / measured | -- | Price comparison requires the same currency on both sides and a locale-aware decimal parse (`59,00` and `59.00` are the same value); a different currency is not comparable and is skipped, not flagged. Name comparison is word-order- and legal-suffix-tolerant. The two comparisons are independent: a page with no comparable visible price still gets its name checked, and vice versa. |
| `SDE.SCHEMA_ONLY_NO_VISIBLE` | A structured price exists with no price pattern anywhere in the page's own visible text | degrades / template or page / measured | confidence: medium | Needs at least 2 instances -- catalogue only, one page alone is not a finding. Confidence is medium because text extraction cannot rule out a price shown only as an image or a script-rendered widget; the evidence says so. |

## Identity

| check_id | Fires when | impact / reach / certainty | Pinned | False-positive guard |
| --- | --- | --- | --- | --- |
| `SDE.NO_ORGANIZATION_NODE` | The homepage has no `Organization`/`LocalBusiness`/`Corporation` node in JSON-LD (after full `@graph` traversal), Microdata, or RDFa | degrades / sitewide / measured | -- | All three formats checked. `not_assessed` (not a finding) when no page in the sample was classified as the homepage at all. |
| `SDE.NO_SAMEAS` | The homepage's Organization node declares no `sameAs` | weakens / sitewide / measured | -- | Only runs when an Organization node exists. |
| `SDE.SAMEAS_MALFORMED` | A `sameAs` entry is not an absolute `http(s)` URL | weakens / sitewide / measured | ceiling `low` | Syntactic check only, no fetching. |
| `SDE.NAME_INCONSISTENT` | The Organization's `name` shares no word overlap with the homepage's own h1 | weakens / sitewide / measured | -- | Word-order-independent (French "Instruments Larkspur" vs English "Larkspur Instruments" is the same two words) and legal-suffix-tolerant ("Ltd", "Inc", etc. stripped before comparing). `not_assessed`, not a finding, when the homepage has no h1 to compare against. |
| `SDE.NO_STABLE_ID` | The Organization node has no `@id` | weakens / sitewide / measured | ceiling `low` | -- |
| `SDE.ORG_IDENTITY_CONFLICT` | The same `@id`, found on two or more pages, disagrees on telephone, address, or url (host) | degrades / sitewide / measured | -- | Requires a **shared `@id`**, not merely a shared name or type -- two different, unrelated Organization nodes are never compared. A page that simply omits a field the other states is not a conflict; only an actual disagreeing value is. URL comparison is by host only (`www.` normalised away), so a trailing slash or a different path on the same site is never flagged. |
| `SDE.ENTITY_AMBIGUITY_RISK` | At least 2 independent risk signals: a short/common name, no `sameAs`, no address or founding date | weakens / sitewide / inferred | ceiling `medium` | Two independent signals required, never one alone. Certainty is `inferred` and the evidence says explicitly this is a risk assessment, not a measured defect. |

## Format and structure hygiene

| check_id | Fires when | impact / reach / certainty | Pinned | False-positive guard |
| --- | --- | --- | --- | --- |
| `SDE.MICRODATA_ONLY` | Valid Microdata or RDFa is present and no JSON-LD is, anywhere in the sample | weakens / sitewide / measured | ceiling `low` | Never fires when structured data is completely absent (that is `SDE.NO_STRUCTURED_DATA`'s job). Phrased and capped as a migration suggestion, never a defect. |
| `SDE.BREADCRUMB_MISSING` | A non-homepage page has no `BreadcrumbList`, on a site with a real hierarchy | weakens / template or page / measured | ceiling `low` | Skipped entirely on a flat site (no URL path two or more segments deep) where a breadcrumb would express nothing. The homepage itself is never expected to have one. |

---

## A genuinely new check: `SDE.ORG_IDENTITY_CONFLICT`

The original planning catalogue (Milestones A-D) did not include this check. It was
added during Milestone H because the milestone's own requirements explicitly call for
detecting "inconsistent entity identifiers across sampled pages" and "conflicting
organization/entity names," and because building it surfaced a real defect worth having
a permanent check for: two pages can each declare an Organization node sharing the exact
same `@id` -- a strong, explicit claim that they describe the same entity -- while
disagreeing on a property like telephone. `SDE.NAME_INCONSISTENT` does not catch this
(it compares structured data against on-page text, not structured node against
structured node), and no other existing check owns cross-page structured-to-structured
identity comparison. This is exactly the kind of contradiction the entity-consistency
model calls a genuine conflict (category C in the design notes), not a harmless
difference.

## Entity consistency model

Every identity comparison in this detector follows the same discipline:

- **A. Consistent** -- values agree after normalisation. No finding.
- **B. Different but harmless** -- capitalisation, punctuation, word order, legal
  suffixes, or a trailing slash. No finding.
- **C. Genuine contradiction** -- a real disagreement in a value both sides state. A
  finding.
- **D. Insufficient evidence** -- one side states nothing to compare (a missing
  optional field, no homepage in the sample, no comparable price in the visible text).
  Recorded as `not_assessed` or simply not evaluated, never guessed into a finding.

Only category C produces a finding anywhere in this catalogue.

## Ownership boundaries

This detector never inspects: `robots.txt` policy, crawler access, redirect behaviour,
UA blocking (all `crawl-access-audit`); the raw-vs-rendered content gap, CSR shells,
heading/main-landmark structure, thin content (all `render-readability-audit`); or
generic accessibility or SEO hygiene unrelated to machine understanding of entities and
facts. Where a finding would depend on rendered evidence (structured data injected only
by JavaScript), that evidence is `render-readability-audit`'s (`RND.JS_ONLY_STRUCTURED_DATA`);
this detector consumes only the `structured_data` already captured on the raw page, and
does not open, parse, or reason about the `render` field at all.

## Known limitations

Stated because a reader needs to know the edges of what was checked.

1. **`article` page-type classification is itself partly structured-data-dependent.**
   The collector classifies `page_type: article` primarily from Article/BlogPosting
   JSON-LD (there is no independent URL-segment or DOM signal for "article" the way
   there is for `about`, `contact`, `docs`, and so on). This means a genuine "this page
   should declare Article markup but declares none at all" case is architecturally
   narrow to observe: on a site with no structured-data corroboration at all, an article
   page is more likely to be classified `unknown` than confidently `article`, and
   `SDE.MISSING_TYPE_FOR_TEMPLATE` requires that confident classification to engage.
   `SDE.INCOMPLETE_REQUIRED_PROPS` does not have this limitation: it only needs the type
   to already be present (which is what let the page classify correctly) while a
   required property is missing, and this path was verified end-to-end against a real
   fixture (`F18-article-pages`). This is a property of the classifier's design, not of
   this detector, and is unrelated to any change made in this milestone (the collector
   was not modified).
2. **Nested-entity traversal is a small, named allow-list (`mainEntity`, `author`,
   `publisher`), not an unbounded walk.** These are schema.org's own conventions for
   embedding one entity inside another. A node embedded under a different, unlisted
   property is not discovered. This is deliberate: an unbounded recursive search would
   also descend into unrelated structures (an `Offer.seller`, a `Product.brand`) with no
   clear stopping point.
3. **RDFa is checked for presence only, never for required properties or value-level
   contradictions.** The snapshot records RDFa type names and a property count, not
   property values, so `SDE.INCOMPLETE_REQUIRED_PROPS` and `SDE.SCHEMA_VISIBLE_MISMATCH`
   cannot evaluate RDFa nodes the way they evaluate JSON-LD or Microdata (which does
   carry real values in `microdata_items`).
4. **Organization.url disagreeing with the page's own canonical or hosting origin is not
   a standalone finding.** `SDE.ORG_IDENTITY_CONFLICT` compares the *same `@id`* across
   *different pages*; it does not check a single Organization node's `url` against the
   origin of the page it is declared on. A site whose Organization node points at an
   entirely different domain than the one serving it would not be caught by any check in
   this catalogue today.
5. **Price and name comparisons are the only structured-vs-visible fact types checked.**
   Availability ("in stock" / "out of stock") was deliberately excluded from
   `SDE.SCHEMA_VISIBLE_MISMATCH`'s scope: reliably detecting availability language in
   visible text requires English-specific lexical keyword matching, which this project's
   multilingual principle avoids elsewhere (see `render-readability-audit`'s equivalent
   scope decisions). Price and name comparisons stay language-neutral: numeric parsing
   and word-set identity respectively, neither requiring English vocabulary.
6. **Removing all structured data can degrade the collector's own page-type
   classification**, since JSON-LD/Microdata type is one of the classifier's strongest
   signals. On a site with zero structured data anywhere, product or article pages may
   be reclassified with lower confidence or into a different type, which can prevent
   `SDE.MISSING_TYPE_FOR_TEMPLATE` from recognising its intended population in that
   specific scenario. `SDE.NO_STRUCTURED_DATA` does not depend on page-type accuracy and
   still correctly reports the overall, most important defect in that case (verified via
   `F17-no-structured-data-clean`).
