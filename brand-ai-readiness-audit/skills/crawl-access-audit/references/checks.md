# ACC check catalogue

**This document is generated against the implementation and must match it exactly.** A
reference that claims a check the code does not implement is worse than no reference: a
reader trusts it and gets a wrong picture of what was audited.

Every check below is implemented in `scripts/check_access.py` and covered by
`scripts/test_access.py`. 21 checks, 21 implemented, 0 documented-but-absent.

## How to read the columns

`gate_impact` / `reach` / `certainty` are the **severity inputs** the detector emits. The
detector never sets a final severity: the entrypoint's `merge_findings.derive_severity`
turns those inputs into `critical` / `high` / `medium` / `low` / `info` and applies the
anti-overclaim caps. Where a check pins the outcome, it does so with an explicit
`severity_override` or `severity_ceiling`, noted below.

---

## robots.txt

| check_id | Fires when | impact / reach / certainty | Pinned | False-positive guard |
| --- | --- | --- | --- | --- |
| `ACC.ROBOTS_MISSING` | `/robots.txt` returns 404 | weakens / sitewide / measured | ceiling `low` when fewer than 20 URLs were discovered | Absence restricts nothing. Never framed as a block; the finding says so explicitly. |
| `ACC.ROBOTS_WRONG_CTYPE` | 200 but `Content-Type` does not start with `text/plain` | weakens / sitewide / measured | ceiling `low` | Only fires when a content type was actually recorded. |
| `ACC.ROBOTS_MALFORMED` | `parse_ok` is false, **or** parseable with unparseable lines | weakens / sitewide / measured | ceiling `low` for the partial case | Two distinct variants with different wording. Must have fetched 200 first. |
| `ACC.ROBOTS_BLOCKS_ALL` | wildcard group disallows the root **and** no retrieval agent is explicitly allowed by a named group | blocks / sitewide / measured | — | **Allowlist guard:** a site that blocks `*` and then names `Allow` groups for retrieval agents is running an allowlist, not a blackout, and is not reported. |
| `ACC.ROBOTS_BLOCKS_RETRIEVAL` | an agent with role `retrieval` or `user-triggered` resolves to disallow | blocks / sitewide when every rule path is `/`, else template / measured | — | Roles come from `agent-roles.json`; an unlisted token is `unknown` and never triggers this. **Double-report guard:** under a wildcard blackout, only agents blocked by their *own named group* are reported, because the inherited block is already `ACC.ROBOTS_BLOCKS_ALL`. |
| `ACC.TRAINING_ONLY_BLOCK` | training agents disallowed while **no** retrieval or user-triggered agent is | weakens / sitewide / measured | **`severity_override: info`** | Never a defect. The action explicitly says no change is required. |

All robots findings quote the **literal matched rule and its line number**, taken from the
collector's `matched_rules`, so a reader can open `robots.txt` and verify the claim.

## Sitemaps

| check_id | Fires when | impact / reach / certainty | Pinned | False-positive guard |
| --- | --- | --- | --- | --- |
| `ACC.SITEMAP_MISSING` | no sitemap returned 200 and parsed | weakens / sitewide / measured | ceiling `low` under 20 discovered URLs | Framed as crawl efficiency, never as a block. Skipped entirely if nothing could be fetched. |
| `ACC.SITEMAP_NOT_DECLARED` | a usable sitemap was found at a conventional location, robots returned 200, and it declares no `Sitemap:` line | weakens / sitewide / measured | ceiling `low` | Requires robots to have been readable; otherwise the absence is unobservable. |
| `ACC.SITEMAP_DEAD_ENTRIES` | at least 3 sampled sitemap URLs return 404/410/500/502/504 | weakens / sitewide / measured | — | **Denominator is stated:** the evidence reports dead-in-sample over sampled-from-sitemap, plus the total listed, and says explicitly that only the sample was checked. |
| `ACC.SITEMAP_LASTMOD_UNIFORM` | a sitemap lists ≥20 URLs with exactly 1 distinct `lastmod` | weakens / sitewide / measured | ceiling `low` | Below 20 URLs a shared date is just a small static site. `distinct == 0` (no lastmod at all) is deliberately not this finding. |

## Page access

| check_id | Fires when | impact / reach / certainty | Pinned | False-positive guard |
| --- | --- | --- | --- | --- |
| `ACC.UA_BLOCKED` | a URL returns **401/403/407** to the audit agent while the browser control fetch returns 2xx | blocks / sitewide when all controlled pages hit, else template / measured | — | Requires a **successful control fetch**. Throttling (429/503) is excluded and recorded as coverage, because it is about load, not identity. An audit-side transport failure (no status) is excluded and recorded as coverage. |
| `ACC.STATUS_ERRORS` | ≥2 sampled URLs return 404/410/500/502/504 | degrades / computed / measured | — | URLs explained by user-agent blocking are excluded so one cause is not reported twice. Only site-published URLs are ever sampled. |
| `ACC.GATED_INFORMATIONAL_CONTENT` | an informational page returns **401** | blocks / computed / measured | — | Only 401, which is an explicit demand for credentials. A 403 seen by both agents is genuinely ambiguous between a login wall and an edge rule, so it is recorded as coverage instead. Never authenticates. |
| `ACC.NOINDEX_ON_CONTENT` | `noindex`/`none` in meta robots or `X-Robots-Tag` on a content page | blocks / computed / measured or inferred | — | Utility pages (search, cart, account, checkout) are excluded and the exclusion is recorded as coverage. Unclassified pages count only when they carry ≥250 characters of main text; certainty drops to `inferred` if any hit was unconfidently classified. |

## Redirects, canonicals, hreflang

| check_id | Fires when | impact / reach / certainty | Pinned | False-positive guard |
| --- | --- | --- | --- | --- |
| `ACC.REDIRECT_CHAIN` | ≥2 URLs need more than 2 hops | weakens / computed / measured | ceiling `low` | Two hops is ordinary and not reported. |
| `ACC.DEEPLINK_TO_HOME_REDIRECT` | ≥2 published non-root URLs land on the site root | blocks / computed / measured | — | Only URLs the collector actually discovered; none are guessed. A redirect to a *different real page* is intentional routing and is not reported. Soft-404 landings are flagged in the evidence. |
| `ACC.LOCALE_REDIRECT_TRAP` | ≥2 URLs redirect into a locale prefix but land on the locale root | blocks / computed / measured | — | A locale prefix that **preserves the path** is correct behaviour and explicitly skipped. |
| `ACC.CANONICAL_MISSING` | content pages carry no `rel=canonical` | weakens / computed / measured | ceiling `low` unless sitewide | Redirected requests are excluded: the canonical describes the landing page, not the requested URL. |
| `ACC.CANONICAL_CROSS_DOMAIN` | ≥3 content pages canonicalise to another host | degrades / computed / measured | — | `www` is normalised away first. Requires a pattern, because syndication is legitimate; the finding says so. |
| `ACC.CANONICAL_CONFLICT` | ≥3 distinct pages declare the same on-site canonical target | degrades / computed / measured | — | Self-referencing canonicals and redirected requests excluded. Cross-domain targets handled by the check above, not double-reported. |
| `ACC.HREFLANG_INVALID` | invalid language tags, a missing self-reference, or a non-reciprocal pair | weakens / computed / measured | ceiling `low` | Only runs on pages that already publish hreflang, so a monolingual site is never penalised. Reciprocity is checked **only between pages both sampled**; an unsampled target is unobservable, not broken. Accepts script and region subtags and `x-default`. |

"computed" reach means `reach_for()` decides page / template / sitewide from the sample,
requiring a cluster of ≥3 sampled pages before any template-level claim.

---

## Known limitations

Stated because a reader needs to know the edges of what was checked.

1. **Sitemap health is sampled, not exhaustive.** Dead entries and `lastmod` are measured
   over the sampled subset. The evidence always carries the denominator.
2. **hreflang reciprocity is sample-bounded.** A one-way annotation whose target was not
   sampled is not reported.
3. **403 is ambiguous by design.** A login wall and an edge bot rule are indistinguishable
   from status alone when both agents are refused. Neither is claimed.
4. **Cross-domain canonical intent is unknowable from markup.** Syndication is legitimate,
   so this is reported for confirmation, not as a certain defect.
5. **Crawler roles age.** `agent-roles.json` lists the agents known at authoring time. A
   new token resolves to `unknown` and never triggers a finding on its own — the failure
   mode is silence, not a guess.
6. **`ACC.UA_BLOCKED` cannot see per-path bot rules that the sample missed**, and cannot
   distinguish a bot-management vendor from a hand-written rule.
7. **No check here inspects page content for meaning.** Whether the reachable content is
   any good belongs to the readability, structured-data and answer detectors.
