# RND check catalogue

**This document is generated against the implementation and must match it exactly.**
Every check_id below is implemented in `scripts/check_render.py` and covered by
`scripts/test_render.py`. 17 catalogue entries: 15 can emit a finding,
`RND.NOSCRIPT_WARNING` is a supporting signal that never stands alone (folded into
`RND.CSR_SHELL`'s evidence), and `RND.CONTENT_BEHIND_INTERACTION` is architecturally
unassessable and always emits `not_assessed` (see below).

## How to read the columns

`gate_impact` / `reach` / `certainty` are the **severity inputs** the detector emits, not
a final severity. The entrypoint's `merge_findings.derive_severity` turns those into
`critical`/`high`/`medium`/`low`/`info`, applying reach-based stepping (page always steps
down one level; template steps down only from critical) and confidence/certainty caps.
Where a check needs an outcome the natural math would overshoot, it sets an explicit
`severity_ceiling`, exactly as `crawl-access-audit` does.

## The raw-vs-rendered checks

| check_id | Fires when | impact / reach / certainty | Pinned | False-positive guard |
| --- | --- | --- | --- | --- |
| `RND.CSR_SHELL` | **With a browser:** raw main text is below the thin-content floor (150 chars) and the rendered main text clears both a growth ratio (3x) and an absolute floor (80 chars). **Without one:** the collector's own `spa_signals` — 2 high-weight signals fire at `blocks`, 1 high + 1 medium fires at `degrades`. | blocks / sitewide or template / measured | fallback path forces `evidence_detail.confidence: medium`, capping the result at `high` regardless of reach | Never fires on a single signal. The only two "high" signals in the collector's vocabulary are thin main text and an empty framework mount point, so a 2-high-signal fallback hit is really "thin AND has a literal empty app root" — the strongest, most specific pairing available without a browser. Page classification confidence is deliberately **not** required (see gotcha below). |
| `RND.PARTIAL_JS_CONTENT` | Raw main text is **substantial** (>=150 chars, so this is not a shell) but the page's only table or definition list -- the structural home for a specification or price list -- is absent from raw and present after rendering. Requires a browser. | blocks / template / measured | reach=template auto-steps critical->high | Deliberately excludes pages that qualify for `CSR_SHELL`, so the same page is never reported under both check_ids for the same underlying gap. |
| `RND.JS_ONLY_STRUCTURED_DATA` | More valid JSON-LD blocks or Microdata types in the rendered DOM than in raw. Requires a browser. | degrades / template / measured | -- | Counts only JSON-LD blocks that actually parse (`parse_ok`); a JSON-LD block present in both raw and rendered but broken in one is a different, unrelated defect. |

## Facts trapped in non-text media

| check_id | Fires when | impact / reach / certainty | Pinned | False-positive guard |
| --- | --- | --- | --- | --- |
| `RND.FACTS_IN_IMAGES` | A `product`-type page has no table or definition list **and** an in-content image with no alt text (missing or empty). | degrades / template / inferred | confidence: medium | Gated to `product` pages specifically, not any content type. An image with **real, descriptive alt text** is never flagged -- alt text is itself a text equivalent. A page with a table already holding the facts is never flagged, whatever its images look like. The evidence names the images but does not claim to know which are decorative; the suggested action says so explicitly. |
| `RND.FACTS_IN_DOCUMENTS_ONLY` | A `product`/`docs`/`press` page links to a PDF or office document and has no table or definition list of its own. Needs >=2 pages. | weakens / template / inferred | confidence: medium | One page alone is not a finding, per the catalogue. A page with its own table, alongside a supplementary PDF, is not flagged. |
| `RND.TEXT_IN_NONTEXT_ELEMENT` | The page's raw HTML contains a `<canvas>` element, or an `<svg>` with >=3 `<text>` nodes and no `<title>`, `<desc>` or `aria-label`, **and** the page's own main text is below the thin floor. | degrades / page / measured | reach=page always steps down one level, landing on medium | Narrow by design: canvas and SVG have countless benign uses. Only fires when the page is *also* thin, so a canvas game or a small icon SVG on an otherwise content-rich page is never flagged. Certainty is `inferred`, confidence `medium`: this is reported for human review, not asserted as a certain defect. |

## Gates that replace content

| check_id | Fires when | impact / reach / certainty | Pinned | False-positive guard |
| --- | --- | --- | --- | --- |
| `RND.INTERSTITIAL_IN_RAW` | Raw HTML contains an ARIA dialog marker (`role="dialog"` or `aria-modal="true"`) **and** the page's main text is below the thin floor. | blocks / sitewide or page / measured | confidence: medium, capping the typical case at `high` | `aria-modal="false"` -- a documented pattern for a deliberately non-blocking dialog such as a toast -- exempts the page even if `role="dialog"` is also present. A dialog marker on an otherwise content-rich page is never flagged; thinness alone without a dialog marker is `RND.THIN_CONTENT`'s territory, not this one. |
| `RND.CONTENT_BEHIND_INTERACTION` | **Never fires.** Always emits `not_assessed`. | -- | -- | See "Known limitations" below: this is a permanent architectural gap, not a confidence-reduced attempt. |

## Semantic structure

All of these operate on the **raw** page fields only, never on `render`, because they ask
what a non-rendering crawler receives.

| check_id | Fires when | impact / reach / certainty | Pinned | False-positive guard |
| --- | --- | --- | --- | --- |
| `RND.NO_H1` | No h1 on a content page, at template scale. | weakens / template / measured | -- | Utility pages excluded. Low-confidence/unknown-type pages are **not** excluded (see gotcha). |
| `RND.MULTIPLE_H1` | More than one h1 on a page. | weakens / template / measured | ceiling `low` | Some sectioning patterns legitimately use more than one; capped low rather than excluded entirely. |
| `RND.HEADING_LEVEL_JUMPS` | A heading level skips by more than one step. Needs >=4 headings on the page. | weakens / template / measured | ceiling `low` | Below 4 headings the outline is too short for a "jump" to mean anything. |
| `RND.NO_MAIN_LANDMARK` | No main/article element, at template scale (>=3 pages). | weakens / template / measured | ceiling `low` | Many valid layouts omit this; never above low. |
| `RND.BOILERPLATE_RATIO` | Main-content text is under 20% of total raw text. Only on pages with a main landmark present, and only on prose-bearing types (`product`, `article`, `docs`, `about`). | weakens / template / measured | -- | Requires a main landmark to exist at all -- without one, `main_text` equals the full page text by the collector's own convention, so the ratio is always ~1.0 and the check self-gates. Category, contact, legal, FAQ and homepage types are excluded: the clean control's own category page sits at ~31% by nature and must never trip this. |
| `RND.THIN_CONTENT` | A `product`/`article`/`docs` page's main text (using the **rendered** figure when available, so a render-side gap is not double-counted here) is below 150 characters. Needs a cluster of >=3. | weakens / template / measured | -- | Restricted to types where substantial content is actually expected. The floor (150) sits well under the clean control's own shortest genuine product page (~400 characters), calibrated against real fixture output rather than reused from the collector's unrelated `thin_content_floor` (250), which would have misfired on this project's own category and contact pages. |
| `RND.TITLE_MISSING` | No title, or a whitespace-only one. | degrades / template / measured | confidence: low, capping at medium | -- |
| `RND.TITLE_DUPLICATE` | >=5 distinct pages share one title after whitespace/case normalisation. | weakens / template / measured | ceiling `low` | Paginated or otherwise genuinely distinct titles (`"Products - Page 1"` vs `"Products - Page 2"`) are different strings and are never grouped together. |
| `RND.NOSCRIPT_WARNING` | Never emitted on its own. | supporting signal | -- | Feeds `RND.CSR_SHELL`'s fallback scoring only, via the collector's `spa_signals`. |

## A deliberate gotcha: two different page-eligibility gates

Render/shell checks (`CSR_SHELL`, `PARTIAL_JS_CONTENT`, `JS_ONLY_STRUCTURED_DATA`,
`INTERSTITIAL_IN_RAW`) use a **permissive** gate: only pages confidently classified as
`utility` are excluded. A genuine CSR shell is exactly the page most likely to defeat
classification, because the classifier itself reads the impoverished raw HTML -- excluding
low-confidence pages from shell detection would systematically hide the failure mode this
detector exists to find.

Structural/prose checks (`NO_H1`, `THIN_CONTENT`, `BOILERPLATE_RATIO`, title checks) use a
**strict** gate mirroring `crawl-access-audit`'s `is_content_page`: confident non-utility
classification, or a text-length floor for the unclassified case. Here the risk runs the
other way -- judging a misclassified utility page for missing an h1 would be wrong.

## Known limitations

Stated because a reader needs to know the edges of what was checked.

1. **`RND.CONTENT_BEHIND_INTERACTION` cannot be measured by this marketplace, ever, with
   or without a browser.** The collector is built to never click, submit or otherwise
   interact with a page -- a deliberate safety property, not an oversight. Content that
   only enters the DOM after a tab or accordion click cannot be distinguished from
   content that was never going to appear at all. This is recorded as a permanent
   `not_assessed` entry rather than attempted via an indirect proxy that could not
   actually confirm or rule out the failure mode.
2. **`RND.INTERSTITIAL_IN_RAW` and `RND.TEXT_IN_NONTEXT_ELEMENT` scan raw HTML with
   regular expressions, not a full parser, and scan the whole page rather than
   per-element.** A dialog-role string embedded inside a `<script>` block's JavaScript
   (not real markup) is not distinguished from genuine markup; on a page that is also
   thin, this could in principle false-positive. This was checked directly during
   adversarial review and did not occur on any fixture, but the general risk is real and
   unmitigated. Similarly, a page mixing one modal dialog and one deliberately
   non-modal (`aria-modal="false"`) dialog would have the non-modal one's exemption
   apply page-wide, potentially suppressing a genuine finding about the other.
3. **`RND.THIN_CONTENT`'s and `RND.BOILERPLATE_RATIO`'s floors were calibrated against
   this project's own fixture suite**, not derived from an external standard. They are
   deliberately conservative (set well under the clean control's own shortest legitimate
   pages) to protect precision, which costs some recall on genuinely borderline cases.
4. **Fact-bearing page types are a fixed, small set** (`product` for images;
   `product`/`docs`/`press` for documents). A site whose spec sheets live on a
   differently-typed page will not be checked by `RND.FACTS_IN_IMAGES` or
   `RND.FACTS_IN_DOCUMENTS_ONLY`.
5. **Rendering is optional and honestly caveated.** `RND.PARTIAL_JS_CONTENT` and
   `RND.JS_ONLY_STRUCTURED_DATA` do not run at all without a browser (recorded as
   `not_assessed`, never guessed). `RND.CSR_SHELL`'s fallback trades recall for the
   ability to screen without one, and is capped at `high`, never `critical`, to reflect
   that trade honestly.
6. **No check here inspects prose quality or fact extractability.** Whether readable
   content actually answers a likely question belongs to `answer-retrievability-audit`,
   not this detector.
