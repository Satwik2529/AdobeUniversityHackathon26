---
name: freshness-corroboration-audit
description: Detect why an assistant repeats an outdated or internally-contradicted version of a brand's facts. Compares the same fact across a site's own pages to find genuine contradictions in product price (matched by sku) and brand tagline, checks whether a page's own date signals (structured data, response headers, sitemap entries) agree with each other, finds a page claiming to be current while carrying the site's oldest date signal, finds an older version of a fact still live once a newer, dated version exists, checks product pages for an explicit availability signal, checks whether the site's copyright year keeps pace with its own newest content, and checks whether the site has a canonical, dated, plainly-worded statement of its key facts. Use this when assistants cite a stale price, a dead tagline, or an outdated fact after a rebrand or update has not fully propagated. Read-only and recommend-only, consumes a snapshot, and makes no network requests of any kind.
license: Apache-2.0
compatibility: Requires Python 3.9 or newer. Consumes a snapshot from site-snapshot-collector. Every check is on-site and deterministic; there is no external or off-site component. Two checks (a free-text tagline comparison and a currency-claim phrase match) are genuinely English-lexical and gated to English-language pages; every other check is structural and runs on any language.
allowed-tools: Bash Read
metadata:
  role: detector
  funnel_gates: selected
  namespace: FRC
---

# Freshness and corroboration audit

Funnel gate: **selected**. Several versions of the same fact can exist on a brand's own
site. Which one does a system pick, and is it the right one?

## The mechanism

Updating a page does not erase older versions elsewhere on the same site: a category
listing, a homepage callout, an old about-page paragraph and the current product page
can all state slightly different things. A system assembling an answer has no way to
know which of a brand's own contradicting pages to trust. The fix is almost never
"update your page" -- the brand usually already did, somewhere. The fix is to find every
surface still stating the old version and bring it in line with the current one.

This is a distinct gate from structured-data validity (Milestone H) and from whether a
single page states its own fact plainly (Milestone I). This detector's territory is
specifically **temporal reliability and cross-page corroboration**: does the same fact
agree with itself across the pages that state it, and does a page's own dating hold up.

## Architecture

This detector is a **pure snapshot consumer**, without exception. It makes no network
requests, performs no crawling, opens no external API, and calls no search engine.
`site-snapshot-collector` remains the only network-touching component in this
marketplace. Every check here runs deterministically from the frozen `snapshot.json`.

## Input and output

```bash
python3 scripts/check_freshness.py --snapshot audit-output/snapshot.json --out audit-output/findings-freshness.json
```

## Procedure

1. Match the same product across pages by `Product.sku` (never by name or page
   proximity) and compare `offers.price`; a genuine disagreement is the highest-precision
   finding in this family: two URLs, two values, no inference.
2. Look for an explicit "tagline is..."/"slogan is..." phrase on English-language pages
   and compare wording across pages that state one.
3. Check date-signal integrity: structured `dateModified`/`datePublished`, the
   `Last-Modified` header, and sitemap `lastmod`, for the same page.
4. Check for a currency claim ("latest", "newest") on a page whose own date signal is
   materially older than the rest of the site.
5. When a fact conflict (step 1 or 2) has date evidence establishing which version is
   older, report it as `FRC.SUPERSEDED_CONTENT_LIVE` instead of the plainer conflict
   finding -- never both, for the same underlying disagreement.
6. Check product pages for an explicit availability signal, in JSON-LD or Microdata.
7. Check the copyright year against the newest date signal observed anywhere in the
   sample.
8. Check whether the site has a canonical, dated fact surface at all.

Full catalogue and the corroboration model behind each check: `references/checks.md`.

## A note on scope: no off-site corroboration

Earlier planning for this skill described an optional external-corroboration step using
a web-search capability. **That is not implemented, and will not be**, because this
marketplace's architecture is explicit and permanent: only `site-snapshot-collector`
touches the network, and every detector, including this one, is a pure snapshot
consumer. This is a deliberate scope boundary, not a temporary gap. See
`references/checks.md` for the full explanation and the specific check_ids this
removes.

## Language neutrality

Most checks here are structural: matching a `sku`, comparing parsed dates, checking for
a `\u00a9` symbol or an `availability` property. Two checks are genuinely English-lexical
(a free-text tagline phrase, and a currency-claim word list) because the snapshot
provides no structural alternative for either; both are honestly gated to English-language
pages and documented as a real limitation, not silently worked around.

## Gotchas

- **A date on a page does not automatically prove staleness.** Publication date,
  modification date, copyright year, an event date, a product model year and a date
  mentioned in prose are different things. Conflating them is the primary source of
  false positives in this family.
- **An old date signal alone is never a finding.** Evergreen content (a legal page, a
  historical article) is legitimately old. It only becomes a finding when paired with a
  second signal: a contradicted fact, a currency claim, or a copyright year lagging
  the site's own newest content.
- **A copyright year lagging by one is normal in January.** Require a gap of more than
  one year.
- **Do not treat formatting or contextual differences as contradictions.** Two store
  locations, two products, or a price written two ways is not a site defect.
- **Never fabricate or imply an external check that did not happen.** There is no
  off-site component; do not word a finding as if independent sources were consulted.
