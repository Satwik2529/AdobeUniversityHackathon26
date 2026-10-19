---
name: crawl-access-audit
description: Detect why an AI assistant or search crawler cannot reach a site's content at all. Reads a captured site snapshot and checks robots.txt policy resolved per crawler role, noindex directives in meta tags and X-Robots-Tag headers, sitemap presence and health, status codes and redirect chains, canonical correctness, user-agent differential blocking by a CDN or WAF, deep links that redirect to the homepage, locale redirect traps, and informational content behind a login or paywall. Use this when auditing why a brand is absent from AI answers or search results, or whenever the first two gates of the discovery funnel, being found and being let in, need to be verified. Read-only and recommend-only. It makes no network requests and never changes the site.
license: Apache-2.0
compatibility: Requires Python 3.9 or newer. Consumes a snapshot produced by site-snapshot-collector. No network access needed.
allowed-tools: Bash Read
metadata:
  role: detector
  funnel_gates: discovered, accessible
  namespace: ACC
---

# Crawl and access audit

Funnel gates: **discovered**, **accessible**. If a machine cannot be let in, nothing
downstream matters. This detector runs first for that reason.

## Input and output

```bash
python3 scripts/check_access.py --snapshot audit-output/snapshot.json --out audit-output/findings-access.json
```

Emits a JSON array of findings in the shared detector contract (documented in
`../brand-ai-readiness-audit/scripts/merge_findings.py`). Makes no network requests.

## The one distinction that matters most

AI vendors run **three kinds of agent** and blocking them means completely different
things:

| Role | Examples | Blocking it costs |
| --- | --- | --- |
| Training | GPTBot, ClaudeBot, Google-Extended, CCBot, Applebot-Extended, Meta-ExternalAgent | Nothing in citations. It is a legitimate content-licensing choice. |
| Retrieval or search index | OAI-SearchBot, Claude-SearchBot, PerplexityBot, Googlebot, Bingbot | Eligibility for AI answers, entirely. |
| User-triggered fetch | ChatGPT-User, Claude-User, Perplexity-User | Answers about a page a user explicitly asked about. |

**A site that blocks training agents while allowing retrieval and user agents is
correctly configured, not broken.** Report that at `info` with the trade-off explained.
Only report a defect when a retrieval or user-triggered agent, or Googlebot, is blocked
from content. Getting this wrong is the single most likely false positive in this domain.

The role table lives in `references/ai-crawler-agents.md`. Treat it as data that ages:
an unknown agent token is `unknown` role and is never the basis for a finding on its own.

## Procedure

1. Read the snapshot. If `robots.parse_ok` is false, emit the parse finding and continue.
2. Resolve every known agent token against the site's robots groups using the snapshot's
   `agent_verdicts` and `matched_rules`. Quote the literal matched rule and its line
   number as evidence. Never substring-match.
3. Classify each verdict by agent role. Apply the distinction above.
4. Check `meta_robots` and the `x-robots-tag` header on every fetched page. Exclude
   `utility` page types: `noindex` on search, cart, account, checkout, login and
   parameter-only URLs is correct behaviour, not a defect.
5. Check sitemap presence, declaration in robots, dead entries and `lastmod` variety.
6. Check status codes, redirect chains, canonical presence and target, and hreflang
   validity where hreflang exists.
7. Compare each page's machine-view status against its `control_fetch` status. Only
   report user-agent blocking when the control fetch succeeded and the machine view did
   not: if both failed, that is our access problem, not the site's, and belongs in
   coverage.
8. Check deep-link integrity and locale redirects using the status chains already in the
   snapshot. Never guess a URL to probe.
9. Check for login or paywall gating on pages classified as informational content.

Full catalogue with severity factors and false-positive guards: `references/checks.md`.

## Gotchas

- **A 403 to us is not automatically a finding.** Without a successful control fetch you
  cannot distinguish "the site blocks non-browser agents" from "the site blocked this
  audit". Record coverage instead.
- **`noindex` is about search indexes, not about assistants fetching a page.** It is still
  a serious finding on content, because the search indexes that AI answers retrieve from
  honour it, but the mechanism sentence must say that accurately rather than claiming it
  blocks assistants outright.
- **A missing robots.txt is not a defect.** It means no restrictions. At most it is a
  `low` hygiene note alongside a missing sitemap.
- **One dead sitemap entry is noise.** Require at least three before reporting.
- **Never claim a robots change guarantees citation.** It restores eligibility.
