# ANS check catalogue

**This document is generated against the implementation and must match it exactly.**
Every check_id below is implemented in `scripts/check_answerability.py` and covered by
`scripts/test_answerability.py`. 9 checks, 9 implemented, 0 documented-but-absent.
`ANS.NO_COMPARISON_SURFACE`, mentioned in early planning, is deliberately **not**
implemented here: publishing comparison content is an opportunity, not a defect, and
belongs entirely to `opportunity-and-monitoring`.

## How to read the columns

`gate_impact` / `reach` / `certainty` are the **severity inputs** the detector emits, not
a final severity. The entrypoint's `merge_findings.derive_severity` turns those into
`critical`/`high`/`medium`/`low`/`info`, applying reach-based stepping (page reach always
steps down one level; template reach steps down only from critical) and confidence caps.
Where a check needs an outcome the natural math would overshoot, it sets an explicit
`severity_ceiling`, matching every other detector in this marketplace.

## A note on language neutrality

Every check in this catalogue is **structural**, not lexical: character position, word-set
overlap (Unicode-aware, not dependent on English vocabulary), presence of a digit or
punctuation pattern, and count of headings or table/list elements. None of them require
understanding what a sentence *means*. An earlier version of two checks
(`ANS.NO_DIRECT_ANSWER_LEAD`'s self-containment test and `ANS.NO_QA_SURFACE`'s question
detection) gated themselves behind an English-only language check anyway, which meant
those checks could never run at all on non-English content -- silently under-serving
exactly the sites this project's language-neutrality principle exists to protect. That
gate has been removed; every check here now runs on any language.

## The core-fact checks

| check_id | Fires when | impact / reach / certainty | Pinned | False-positive guard |
| --- | --- | --- | --- | --- |
| `ANS.NO_DIRECT_ANSWER_LEAD` | On `product` pages with a structured price: the first mention of that price in the main text is either **buried** (past a lenient position floor: the greater of 150 characters or 35% of the page's own length) or **not self-contained** (the page's own h1 does not recur, as a word-overlap match, within 220 characters before the fact) | weakens / template or page / inferred | -- | Scoped to product pages only, where "core fact" (price) is well-defined. The self-containment window, not a strict same-sentence rule, is deliberate: this project's own clean-control fixture states its price as "It costs 59.00 GBP" one sentence after naming the product, which a strict same-sentence rule would have wrongly flagged. |
| `ANS.SPECS_NOT_EXTRACTABLE` | A `product` page states 2 or more distinct unit-bearing decimal values in prose, with zero tables or definition lists anywhere on the page | weakens / template or page / measured | -- | Requires **2 or more** values (one alone is not a pattern) and **zero** structural elements (any table or dl at all is enough to exempt the page, regardless of whether that specific element holds these specific values). |
| `ANS.UNITLESS_VALUES` | A `product` page states a decimal number with no unit or currency token within a 20-character window, excluding years and model-like alphanumeric tokens | weakens / template or page / measured | ceiling `low` | Unit matching is whole-word (`\bmm\b`, `\bgrams?\b`, etc.), not substring, and deliberately excludes short abbreviations that collide with ordinary English words (bare "in", "a", "g", "l", "w", "v") even with word boundaries -- "in" is overwhelmingly the preposition, not the unit, in running prose. |
| `ANS.ENTITY_NEVER_NAMED` | On `product` pages only: the page's own h1, as a **complete word set**, never recurs anywhere in the body after the heading itself. Needs 2 or more pages | weakens / template or page / measured | -- | Full word-set containment, not partial: for a two-word h1 like "Alpha Widget," the generic noun ("Widget") recurring alone is not enough, because it would recur across an entire widget-selling site regardless of which specific product is being discussed -- only the distinguishing word ("Alpha") actually names the entity. Scoped to product pages only: a FAQ, legal, contact or category page's h1 is a generic section label ("Frequently asked questions," "Terms of sale"), not an entity that needs restating. Word-set comparison is order-independent, so grammatically reordered translations (French "Instruments Larkspur" vs English "Larkspur Instruments") are not penalised. |

## Structure and surface checks

| check_id | Fires when | impact / reach / certainty | Pinned | False-positive guard |
| --- | --- | --- | --- | --- |
| `ANS.NO_HEADING_ANCHORS` | A page above the long-page floor (3000 characters of main text), with 4 or more level-2-or-below headings, has **no** heading anywhere with an id | weakens / template or page / measured | -- | All-or-nothing by design: a page with even one addressable heading is not flagged, since partial anchor coverage is a milder, different concern this check does not claim to measure. |
| `ANS.NO_SUMMARY_BLOCK` | A long page's first level-2-or-below heading's own text appears within the opening 80 characters of main text | weakens / template or page / inferred | ceiling `low` | Heading position in extracted text is a proxy for lead-in length, not a direct summary-quality measurement, hence the ceiling and `inferred` certainty. |
| `ANS.NO_QA_SURFACE` | A page already classified as `faq` type has headings, but none of them end in a question mark (ASCII `?` or full-width `\uff1f`) | weakens / template or page / inferred | -- | Only evaluates a page **already** classified as FAQ content by the collector; never asserts that a site lacking FAQ content should add it (that is an opportunity, routed elsewhere, never emitted here). |
| `ANS.NO_CANONICAL_FACT_SURFACE` | No sampled page combines the homepage's own subject name with 2 or more of: a year pattern, a price pattern, a phone-like digit run | degrades / sitewide / measured | -- | Requires at least 3 confidently-classified content pages before making this sitewide claim at all -- a legitimately tiny 2-page site is `not_assessed`, not flagged, since a small site naturally has few pages to combine facts on. `not_assessed` (not a finding) when no page in the sample was classified as the homepage. |
| `ANS.KEY_FACT_OUTSIDE_MAIN_CONTENT` | On `product` pages: the structured price is confirmed present, at the exact same value and currency, in the page's full text, but that specific value is **not** found again within the extracted main-content text | degrades / template or page / measured | -- | Requires the fact to be **positively confirmed present** in the full page first; a fact absent from both full and main text is a different, unrelated concern (structured-data-only claims with no visible counterpart at all are `SDE.SCHEMA_ONLY_NO_VISIBLE`'s territory, not this one). A different currency or amount mentioned elsewhere on the page (a regional aside) does not satisfy the "same fact" requirement and is correctly ignored. |

## Ownership boundaries

This detector never inspects: `robots.txt` policy, crawler access, redirect behaviour, UA
blocking (`crawl-access-audit`'s territory); raw-vs-rendered content gaps, CSR shells,
heading/main-landmark structure, or thin content generally (`render-readability-audit`'s
territory); or the validity, completeness or cross-page consistency of structured data
markup itself (`structured-data-entity-audit`'s territory). This detector consumes
structured data only as **supporting evidence** for what a page's core fact is (reading
`Product.offers.price`, never re-validating the markup that carries it) and never opens or
reasons about the `render` field at all -- if a finding would depend on rendering
evidence (a fact only visible after JavaScript runs), that is `render-readability-audit`'s
`RND.PARTIAL_JS_CONTENT` or `RND.CSR_SHELL`, not this detector's concern.

## Known limitations

Stated because a reader needs to know the edges of what was checked.

1. **Core-fact checks are scoped to `product` pages only**, because price is the one
   fact type this snapshot lets a detector identify with confidence, extract, and
   compare against visible text without inventing snapshot fields or lexical
   assumptions. Article, docs and other content types do not get an equivalent
   core-fact check in this milestone.
2. **`ANS.NO_HEADING_ANCHORS` is all-or-nothing.** A page with 3 addressable headings
   and 1 unaddressable one is not flagged, even though partial coverage is a real,
   milder concern this catalogue does not currently measure.
3. **`ANS.NO_SUMMARY_BLOCK`'s position proxy is approximate.** It measures where a
   heading's own text first appears in the flattened main-text string, which is not a
   true DOM-position measurement (the snapshot does not carry character offsets for
   headings); certainty is `inferred` and severity is capped at `low` to reflect that.
4. **Unit detection is a fixed, generic vocabulary** (metric and imperial length/mass
   units, major currency codes, percent, degrees). A specialised domain with its own
   unit conventions not in this list will not be recognised, and a genuinely unit-bearing
   value in such a domain could be wrongly flagged as unitless.
5. **`ANS.NO_CANONICAL_FACT_SURFACE`'s signal set is generic** (year, price, phone-like
   digit run). A brand whose key facts are, say, a certification number or a founding
   story with no digits at all would not be recognised by this check's current signals,
   even if a canonical page genuinely exists.
6. **`ANS.KEY_FACT_OUTSIDE_MAIN_CONTENT` only checks price**, the same fact type the
   other core-fact checks use, for the same reason: it is the one fact this snapshot
   supports comparing with confidence.
7. **No check here evaluates table or list internal structure** (whether a table's
   label-value pairing is preserved by extraction, or a list's item-context
   relationship). The snapshot records only counts of tables and definition lists, not
   their cell- or item-level content, so this level of evaluation is not assessable
   from the current contract without inventing fields this milestone was explicitly
   told not to invent.
8. **Extraction-order effects on meaning are not evaluated.** Whether reordering
   sentences during extraction changes what a passage means is a genuine failure mode
   named in this milestone's brief, but reliably detecting it requires understanding
   meaning, not structure, which is outside what this catalogue's conservative,
   structural approach can safely claim.
