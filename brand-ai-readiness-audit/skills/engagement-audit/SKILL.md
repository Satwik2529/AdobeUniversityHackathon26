---
name: engagement-audit
description: Detect whether a visitor who has found useful content can understand and follow a next useful on-site action or content pathway. Checks whether product, article and documentation pages expose an in-content next step or are dead ends, whether in-content links that do exist actually lead to related content rather than only utility destinations, whether product pages expose an observable purchase or inquiry action surface, whether high-value content sits unusually deep in the site's own sampled structure, whether sampled pages are reachable from any other sampled page or are orphan-like within the sampled graph, and whether generic, repeated link text makes it impossible to tell which of several destinations a link leads to. Use this when useful content exists and is readable but a visitor or an AI-assisted user has no clear next step once they arrive. Read-only and recommend-only, consumes a snapshot, and makes no network requests of any kind.
license: Apache-2.0
compatibility: Requires Python 3.9 or newer. Consumes a snapshot from site-snapshot-collector. Every check reads only links_internal, links_external, page_type and clusters; none require render evidence, structured data, or robots data. One check (an action-phrase and generic-anchor lexicon) is genuinely English-lexical and documented as a limitation, not silently worked around.
allowed-tools: Bash Read
metadata:
  role: detector
  funnel_gates: engagement
  namespace: ENG
---

# Engagement audit

Stage: **post-discovery, on-site**. Content exists, is readable, and is understood. Once
someone is on the page, can they tell what to do next?

## The mechanism

A visitor (human or an AI-assisted agent following a link) who finds a useful page is not
finished: a product page with nothing to click leads nowhere, an article with no related
reading is a terminus, and a page nobody else on the site links to is hard to find again
even once it has been found once. None of this is about aesthetics, copy quality, or
predicted behaviour -- it is about whether the site's own structure, as captured in the
snapshot, offers an observable next step.

This is deliberately **not** a generic UX, accessibility, or Core Web Vitals audit, and it
makes no claim about actual visitor behaviour: no click-through rate, conversion rate,
bounce rate, or time on page. This snapshot has no behavioural data, so none is invented.
See `references/checks.md` for the full analytics boundary.

## Architecture

This detector is a **pure snapshot consumer**, without exception. It makes no network
requests, launches no browser, calls no external API or analytics platform, and requires
no credentials. `site-snapshot-collector` remains the only network-touching component in
this marketplace. Every check reads only `links_internal`, `links_external`, `page_type`,
and `clusters` from the frozen snapshot.

## Input and output

```bash
python3 scripts/check_engagement.py --snapshot audit-output/snapshot.json --out audit-output/findings-engagement.json
```

## Procedure

1. Identify high-value content types (`product`, `article`, `docs` -- deliberately not
   "service", which this snapshot's page-type classifier has no way to distinguish from
   "about" or "product") and check each for at least one in-content internal link.
2. Where in-content links exist, check whether any of them resolve to another sampled
   page of a content-bearing or listing type, distinguishing genuine related-content
   continuation from links that only lead to utility destinations.
3. On `product` pages specifically, check for an observable link anywhere on the page
   whose text signals a purchase, contact, or inquiry action.
4. Compare each high-value template cluster's sampled depth against this site's own
   median sampled depth, flagging only a relative, sample-scoped excess.
5. Check whether every sampled page has an inbound link from at least one other sampled
   page, wording any absence as "orphan-like within the sampled graph," never as a claim
   of global orphaning.
6. Check for generic, repeated anchor text pointing to different destinations on the
   same page.

Full catalogue: `references/checks.md`.

## Page-type awareness

Every check above is gated by page type. A legal page being a dead end is not a defect. A
contact page needs no further action link -- it is the endpoint. An endpoint type
(`contact`, `legal`, `faq`, `utility`, `homepage`) is never a candidate for the dead-end
or orphan checks. Never apply the same expectations to a homepage, a checkout page, and a
product page.

## Gotchas

- **Navigation and footer links are the same on every page and do not count as
  contextual continuation or related content** -- only links flagged `in_content` do.
  They do count toward the action-pathway and orphan checks, since a consistent
  site-wide path is still a real, observable one for those specific questions.
- **A low-confidence destination classification is inconclusive, not negative
  evidence.** A page's own classifier confidence can degrade for reasons unrelated to
  whether it is actually related content (non-English text, structured data in a format
  the classifier weighs less); never blame the source page for a classification gap on
  the destination.
- **Never claim global site structure or global orphaning from a bounded sample.**
  Every reach and depth claim is scoped explicitly to what was sampled.
- **Never invent a behavioural metric.** "No observable action pathway" is a structural
  finding; "visitors will bounce" is not something this snapshot can establish.
- **Never recommend a fix this snapshot cannot verify.** Every suggested action names a
  concrete structural change (add a link, change anchor text) and a way to re-check it
  from the same kind of evidence the finding used.
