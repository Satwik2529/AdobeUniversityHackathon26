# FRC check catalogue

**This document is generated against the implementation and must match it exactly.**
Every check_id below is implemented in `scripts/check_freshness.py` and covered by
`scripts/test_freshness.py`. 7 checks, 7 implemented, 0 documented-but-absent.

## A significant scope change from early planning

The early planning `SKILL.md` (written before every detector's architectural rule was
established with full rigor) described an optional "Part B": bounded external
corroboration using a web-search capability, with checks `FRC.UNCORROBORATED_FACT` and
`FRC.STALE_IN_THE_WILD`. **None of that is implemented.** Milestone J's own architectural
rule is explicit and unambiguous: this detector "MUST NOT... call external search
engines... query external APIs," and "the site-snapshot-collector remains the ONLY
component that touches the network" -- without exception. Implementing Part B would
directly violate that rule. `FRC.UNCORROBORATED_FACT`, `FRC.STALE_IN_THE_WILD` and
`FRC.CORROBORATION_NOT_ASSESSED` are not implemented, and the `SKILL.md` for this
detector has been rewritten to remove Part B entirely rather than describe a capability
this marketplace does not and will not have.

`FRC.LASTMOD_UNIFORM`, also mentioned in early planning, is not implemented either: it
is byte-for-byte the same check already implemented as `crawl-access-audit`'s
`ACC.SITEMAP_LASTMOD_UNIFORM` (a sitemap listing 20+ URLs with exactly one distinct
`lastmod`). Implementing it a second time here would be exactly the duplication this
marketplace's ownership-boundary discipline exists to prevent.

## How to read the columns

`gate_impact` / `reach` / `certainty` are the **severity inputs** the detector emits, not
a final severity. The entrypoint's `merge_findings.derive_severity` turns those into
`critical`/`high`/`medium`/`low`/`info`, applying reach-based stepping and confidence
caps, matching every other detector in this marketplace.

## The corroboration model

- **A. Consistent** -- the same fact, same value. No finding.
- **B. Harmless wording difference** -- "Phone: 123" vs "Call us at 123". No finding.
- **C. Contextual difference** -- two store locations, two products, a regional variant.
  No finding, because the snapshot gives no reason to expect these to match.
- **D. Genuine contradiction** -- the same fact, same context, different values, no
  temporal evidence either way. `FRC.INTRA_SITE_FACT_CONFLICT`.
- **E. Temporal evolution** -- the same fact, different values, **and** date evidence
  establishing which is older. `FRC.SUPERSEDED_CONTENT_LIVE`, not the plainer conflict
  finding (the two never co-fire for the same underlying disagreement; see the "no
  double-report" note below).
- **F. Insufficient evidence** -- `not_assessed`, never guessed into a finding.

## Checks

| check_id | Fires when | impact / reach / certainty | Pinned | False-positive guard |
| --- | --- | --- | --- | --- |
| `FRC.INTRA_SITE_FACT_CONFLICT` | (a) The same `Product.sku` states two different prices across pages, or (b) an explicit "tagline is..."/"slogan is..." phrase states two different wordings across English-language pages | degrades / sitewide, template or page / measured | -- | **(a)** matched by `sku`, never by product name or page proximity -- two different products are never compared. **(b)** English-lexical, gated to `lang == "en"`; a genuine, documented limitation (see below), not a silent gap. **No double-report:** when date evidence establishes which tagline value is older, this check yields to `FRC.SUPERSEDED_CONTENT_LIVE` for that specific pair instead of also firing. |
| `FRC.DATE_SIGNAL_CONFLICT` | Two or more of a page's own date signals (structured `dateModified`/`datePublished`, sitemap `lastmod`, the `Last-Modified` response header) disagree by more than 2 days | weakens / template or page / measured | -- | Only unambiguous ISO-8601-prefixed or RFC 7231 HTTP dates are parsed; an ambiguous format like `01/02/2026` is skipped, never guessed. The 2-day tolerance absorbs timezone-boundary rounding and same-day build-pipeline noise. |
| `FRC.STALE_CLAIM` | An English-language page contains a currency-claim phrase ("latest", "newest", "all-new", "current model", "now available") while its own newest date signal is more than a year older than the newest date signal found elsewhere in the sample | weakens / template or page / inferred | -- | Needs at least 3 dated pages in the sample before comparing at all. English-lexical (documented limitation): understanding "latest" as a currency claim requires the word itself. |
| `FRC.SUPERSEDED_CONTENT_LIVE` | The tagline conflict described above, specifically when the snapshot's own date evidence establishes which value is genuinely older | degrades / template or page / measured | -- | Requires two *different* dates (not merely two dated versions -- a sitewide `lastmod` stamp applied uniformly to every page gives no real ordering evidence, and is correctly treated as insufficient, not as "both are current"). |
| `FRC.NO_AVAILABILITY_SIGNAL` | A `product`-type page's Offer node (in either JSON-LD or Microdata) carries no `availability` property | weakens / template or page / measured | -- | Checked in **both** formats -- an earlier version checked JSON-LD only and wrongly flagged a site whose availability data had migrated to Microdata, still fully present. |
| `FRC.COPYRIGHT_YEAR_LAG` | A copyright year (matched via the universal `\u00a9` symbol or the English word "copyright") is more than one year behind the newest date signal found anywhere in the sample, or the audit's own crawl date if no other signal exists | weakens / template or page / measured | -- | More than one year specifically to survive the ordinary lag every site has every January. A historical year mentioned elsewhere in prose with no copyright marker nearby (a founding year, an event year) is never matched -- only text adjacent to the symbol or the word itself counts. |
| `FRC.NO_CANONICAL_FACT_SURFACE` | No sampled page combines the homepage's own subject name with 2 or more of: a year pattern, a price pattern, a phone-like digit run | degrades / sitewide / measured | -- | **Authoritative owner of this finding**: `merge_findings.DUPLICATE_OWNERSHIP` suppresses `answer-retrievability-audit`'s `ANS.NO_CANONICAL_FACT_SURFACE` once this one fires (both independently compute the same underlying condition; this is the one the entrypoint keeps). Requires at least 3 confidently-classified content pages before making this sitewide claim; a legitimately tiny site is `not_assessed`, not flagged. `not_assessed` when no homepage is in the sample. |

## Ownership boundaries

This detector never inspects: `robots.txt` policy or crawl access (`crawl-access-audit`);
raw-vs-rendered content, CSR shells, or structural readability (`render-readability-audit`);
the validity or `@id`-based cross-page consistency of Organization identity properties
such as telephone, address or url (`structured-data-entity-audit`'s
`SDE.ORG_IDENTITY_CONFLICT` -- this detector's own fact-conflict checks are deliberately
scoped to **`sku`-matched product price** and **free-text tagline**, a distinct,
non-overlapping fact set); or whether a single page states its own core fact plainly
(`answer-retrievability-audit`, except for the one check explicitly designated
authoritative here, `FRC.NO_CANONICAL_FACT_SURFACE`, per the dedup rule above). This
detector never opens or reasons about the `render` field. It makes no network requests,
performs no crawling, and calls no external search engine or API -- the
site-snapshot-collector remains the only network-touching component without exception.

## Cross-detector interactions (intentional)

- **With H (`structured-data-entity-audit`):** `SDE.ORG_IDENTITY_CONFLICT` establishes
  that two pages describe the *same entity* (via a shared `@id`) with conflicting
  property values. This detector does not reimplement that matching; its own
  `sku`-based product-price comparison is a distinct identity mechanism for a distinct
  fact type Milestone H does not check.
- **With I (`answer-retrievability-audit`):** `ANS.NO_CANONICAL_FACT_SURFACE` and
  `FRC.NO_CANONICAL_FACT_SURFACE` compute the same underlying condition from
  independent evidence lenses. The dedup rule keeps this detector's version once both
  fire, since it is the one positioned to reason about the surface's own dating.

## Known limitations

Stated because a reader needs to know the edges of what was checked.

1. **The tagline sub-check of `FRC.INTRA_SITE_FACT_CONFLICT` and `FRC.STALE_CLAIM`'s
   currency-claim detection are both genuinely English-lexical**, gated to
   `lang == "en"`. The snapshot has no structured field for a free-text brand slogan,
   and no structural alternative exists for recognising words like "latest" without
   understanding English. This is a real, acknowledged limitation, not a design
   oversight to be silently worked around.
2. **`FRC.INTRA_SITE_FACT_CONFLICT`'s price comparison does not account for regional
   currency variants.** A `sku` priced in GBP on one page and USD on another produces
   a distinct `(amount, currency)` pair per occurrence, which the current design still
   treats as "more than one value" rather than recognising a legitimate regional price
   difference. A genuinely multi-currency, multi-region catalogue could see a false
   positive here.
3. **Date parsing only accepts unambiguous formats** (ISO-8601-prefixed, or RFC 7231
   HTTP dates). A page using an ambiguous format such as `01/02/2026` is silently
   excluded from every date-aware check rather than guessed at, which trades recall for
   never asserting a wrong date-order comparison.
4. **`FRC.COPYRIGHT_YEAR_LAG` only recognises the `\u00a9` symbol and the English word
   "copyright".** A site using another language's word for copyright notices is not
   checked.
5. **`FRC.NO_CANONICAL_FACT_SURFACE`'s signal set is generic** (year, price,
   phone-like digit run), matching `answer-retrievability-audit`'s equivalent
   signals exactly, for the same reason: these are the fact types this snapshot
   supports recognising with confidence and without lexical assumptions.
6. **No off-site corroboration of any kind is performed**, by explicit, permanent
   architectural design -- not a temporary gap awaiting a future capability.
