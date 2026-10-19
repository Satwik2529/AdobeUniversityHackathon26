---
name: render-readability-audit
description: Detect content that a person can see but a machine cannot read. Compares the raw HTML a non-rendering crawler receives against the browser-rendered DOM to measure client-side-rendering gaps, and checks for facts locked in images, PDFs, canvas or untitled SVG, content that only appears after a tab, accordion or lazy-load interaction, structured data injected only by JavaScript, interstitials that replace content in the raw response, and missing semantic structure such as no h1 or no main landmark. Use this when auditing why a page that looks fine in a browser is missing or empty in AI answers, why a single-page application is invisible to assistants, or whenever the readable gate of the discovery funnel needs verification. Read-only and recommend-only, consumes a captured snapshot, and makes no network requests.
license: Apache-2.0
compatibility: Requires Python 3.9 or newer. Consumes a snapshot from site-snapshot-collector. Works without a headless browser by falling back to static signatures at reduced confidence.
allowed-tools: Bash Read
metadata:
  role: detector
  funnel_gates: readable
  namespace: RND
---

# Render and readability audit

Funnel gate: **readable**. The crawler got in. Can it actually read the facts?

## Why this gate is usually the expensive one

Published crawler-traffic analysis has consistently found that the major AI crawlers
fetch raw HTML and do not execute JavaScript. Several download script files without ever
running them. The practical exceptions ride existing search infrastructure. So a page can
rank well in a search engine that renders JavaScript and still be an empty shell to every
assistant that does not.

Two consequences shape every check here:

- The **raw HTML** is the ground truth for what a machine reads. The rendered DOM is the
  comparison, not the target.
- Content does not have to be visible prose to count. Data present in the initial HTML as
  inline JSON, structured-data markup or a server-rendered payload is still readable.
  Only content the browser builds **after** the response is at risk.

## Input and output

```bash
python3 scripts/check_render.py --snapshot audit-output/snapshot.json --out audit-output/findings-render.json
```

## Procedure

1. For each fetched page, compare `raw_text_len` and `main_text_len` against
   `render.text_len` and `render.main_text_len`.
2. If `capabilities.headless_render` is false, **do not assume**. Fall back to static
   signatures and lower confidence accordingly. See the fallback table below.
3. Identify which facts exist only after rendering: price, availability, specifications,
   FAQ answers, and any structured-data block whose `source` is `rendered` but not `raw`.
4. Check for fact-bearing content that is non-textual: images without a text equivalent
   in surrounding content, specification or press facts available only inside linked
   documents, and text rendered into canvas or untitled SVG.
5. Check semantic structure: presence of exactly one h1, a main or article landmark,
   heading levels that do not skip, and a workable main-content-to-boilerplate ratio.
6. Check whether an interstitial is present in the **raw** response, which means a machine
   receives the gate rather than the page.
7. Aggregate per template cluster. A cluster-level finding needs at least 3 sampled pages
   in that cluster and a failure rate over the threshold; otherwise report page-level.

Full catalogue: `references/checks.md`.

## Fallback when no browser is available

Score these static signals per page. Two high-weight signals fire `RND.CSR_SHELL` at
`blocks` impact with `confidence: medium`. One high plus one medium fires it as
`degrades` with `confidence: medium`. Anything less records
`render comparison` in `coverage.not_assessed` and emits **nothing**.

| Signal | Weight |
| --- | --- |
| Extracted body text below the content threshold on a content page type | high |
| An empty framework mount point in the raw HTML | high |
| A `noscript` block telling the visitor to enable JavaScript | medium |
| Script bytes far exceeding text bytes | medium |
| An inline JSON state blob with no corresponding rendered prose in the raw HTML | medium |

Mount points are matched structurally, by "an element with no children whose id or tag
matches a common framework root convention", never by a fixed list of one framework's
selectors.

## Gotchas

- **A short page is not a broken page.** Landing pages, contact pages and legal notices
  are legitimately short. Exempt pages whose total text is below the short-page floor from
  thin-content and answer-position judgements rather than flagging them.
- **Inline JSON in the raw HTML is readable.** Do not report a page as unreadable when the
  facts are present in a server-rendered data payload.
- **`render: null` means we did not look.** It never means rendering changes nothing.
- **Do not double-report.** Content behind a tab is a render finding; the fact that its
  specifications cannot be extracted is the same defect seen from the content side. The
  entrypoint folds the second into the first, so keep the evidence in the render finding.
- **Never claim server-side rendering guarantees citation.** It reopens the readable gate.
