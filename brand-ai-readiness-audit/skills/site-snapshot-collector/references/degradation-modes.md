# Degradation modes

Every failure has one defined behaviour. In all cases: record the truth in `coverage`,
never fabricate, never abort the audit.

| Condition | Behaviour |
| --- | --- |
| `robots.txt` missing (404) | Treat as "no restrictions". Not a crawl error. The access detector decides whether the absence itself is worth reporting. |
| `robots.txt` unparseable or served as HTML | `parse_ok: false`, keep the raw body as evidence, fetch conservatively as if `Disallow: /` were absent but note the ambiguity. |
| `robots.txt` disallows everything for us | Stop crawling. Record `blocked_by_robots` and the matched rule. Do not fetch anyway. The report still gets written. |
| No sitemap | Fall back to breadth-first in-domain crawling, depth 3. Record `discovery.method: crawl`. |
| Sitemap enormous | Cap at 5,000 URLs and 3 index levels. Record the cap. |
| Bot challenge or WAF interstitial | Mark the page `fetch_ok: false` with `challenge_detected: true`. Do not parse the challenge as content. Do not retry aggressively. Never attempt to solve it. |
| 429 or 503 | Back off, drop concurrency to 1, retry once, then record and move on. |
| Repeated timeouts | Reduce the sample, keep cluster coverage, record the degradation. |
| No headless browser | `capabilities.headless_render: false`, `render: null` on every page, and a `not_assessed` entry. The render detector falls back to static SPA signatures and lowers its own confidence. |
| Render times out on a page | `render.ok: false` for that page only. Other pages keep their render data. |
| Response larger than 3 MB | Truncate, set `truncated: true`, and note that text-length comparisons on that page are unreliable. |
| Non-HTML content type | Skip parsing, keep the URL and content type. Linked documents are still recorded so the readability detector can see PDF-only fact surfaces. |
| Redirect loop | Stop at 5 hops, keep the chain as evidence. |
| Login or paywall gate | Never authenticate. Record the gate. The access detector decides whether gated informational content is a finding. |
| DNS failure or unreachable host | Exit with a clean structured error. Do not emit a partial snapshot that looks like a successful audit. |
| Site has fewer than 3 pages | Complete normally. Template-level checks will disable themselves downstream; that is the detectors' job, not the collector's. |
