# ENG check catalogue

**This document is generated against the implementation and must match it exactly.**
Every check_id below is implemented in `scripts/check_engagement.py` and covered by
`scripts/test_engagement.py`. 6 checks, 6 implemented, 0 documented-but-absent.

## A significant scope change from early planning

An early planning draft of this `SKILL.md` described an "arriving visitor mid-journey"
model: landing-integrity redirects, modal interruption, forced gates, fragment/query
preservation, first-paint weight, and mobile viewport declaration. **None of that is
implemented.** Milestone K's own, much more detailed and more recent instructions
redefine this detector's scope entirely around **observable on-site action and content
continuation pathways** -- can a visitor who has found useful content understand and
follow a next useful step. Three of the old draft's checks were already dead slots
regardless: `ENG.DEEPLINK_LANDING_MISMATCH` (crawl-access-audit's
`ACC.DEEPLINK_TO_HOME_REDIRECT` is the sole owner of that condition),
`ENG.NO_HEADING_ANCHORS`
(answer-retrievability-audit's `ANS.NO_HEADING_ANCHORS` owns it), and
`ENG.MISSING_ALT_ON_INFORMATIONAL_IMAGES` (render-readability-audit's
`RND.FACTS_IN_IMAGES` owns it). A stale fixture-manifest requirement for
`ENG.DEEPLINK_LANDING_MISMATCH` was found and corrected during this milestone (see
`tests/expected/F05-deeplink-redirect.json`'s notes) to require the check's actual,
already-correct owner instead. The final adversarial review then found that
`crawl-access-audit` was still attaching `related_checks=["ENG.DEEPLINK_LANDING_MISMATCH"]`
to its own finding, so a generated report cited a check_id that exists nowhere in this
marketplace; that reference and the three corresponding inert `DUPLICATE_OWNERSHIP` rows
were removed, and the `L6 catalogue integrity` harness layer now fails the build if any
such dangling reference reappears.

## How to read the columns

`gate_impact` / `reach` / `certainty` are the **severity inputs** the detector emits, not
a final severity. The entrypoint's `merge_findings.derive_severity` turns those into
`critical`/`high`/`medium`/`low`/`info`, matching every other detector in this
marketplace. No check here bypasses that central derivation.

## The analytics boundary

This snapshot contains no behavioural data. No check here claims, implies, or estimates
click-through rate, conversion rate, bounce rate, time on page, abandonment rate, or any
other measurement of what a visitor actually did. Every finding is worded as a structural
observation ("no observable action pathway was found"), never a behavioural prediction
("visitors will leave"). Actual behavioural measurement belongs to
`opportunity-and-monitoring`, if and when a capability exists to gather it.

## Checks

| check_id | Fires when | impact / reach / certainty | Pinned | False-positive guard |
| --- | --- | --- | --- | --- |
| `ENG.DEAD_END_HIGH_VALUE_PAGE` | A `product`/`article`/`docs` page has zero internal links flagged `in_content` (navigation and footer links, present on every page regardless of content, do not count) | weakens / template or page / measured | -- | Scoped to types where an ongoing pathway is expected regardless of business model. Endpoint types (`contact`, `legal`, `faq`, `utility`, `homepage`) are never candidates: a legal page being a dead end is correct, not a defect. |
| `ENG.NO_RELATED_CONTENT_PATHWAY` | The page has some in-content links, but none resolve to a sampled page of a content-bearing or listing type (`product`, `article`, `docs`, `category`) | weakens / template or page / measured | -- | Distinct from `DEAD_END`: only evaluated once at least one in-content link exists. A destination outside the sample, or one classified at low confidence, is treated as inconclusive, never as confirmed evidence the link is unrelated -- classifier confidence gaps on the *destination* page are never held against the *source* page. A category/listing page ("browse the full range") is a legitimate related-content hub, not a utility destination. |
| `ENG.WEAK_ACTION_PATHWAY` | A `product` page has no link anywhere on the page (in-content or navigation, internal or external) whose text matches a conservative purchase/contact/inquiry phrase list | weakens / template or page / measured | -- | The one page type where "expects a purchase or inquiry action" is inferable without assuming a business model -- this snapshot's page-type classifier has no distinct "service" type to gate on, and none is assumed. Navigation-level action links count here (unlike contextual continuation), since a consistent site-wide action path is still a real, observable path. English-lexical (documented limitation below). |
| `ENG.EXCESSIVE_PATHWAY_DEPTH` | A `product`/`article`/`docs` template cluster's depth exceeds this site's own median sampled cluster depth by 2 or more levels | weakens / template / inferred | -- | Needs at least 3 clusters with a known depth before any comparison is made. Relative to this site's own sampled structure only -- never an absolute threshold, and never a claim about the site's full, unsampled structure. |
| `ENG.ORPHAN_LIKE_SAMPLED_PAGE` | A sampled page has no inbound internal link (navigation or content) from any other sampled page | weakens / template or page / measured | -- | Endpoint types are excluded: a terms or FAQ page reachable only via the footer or the sitemap, not the main nav, is a normal, common pattern, not an engagement-pathway problem. Needs at least 6 confidently-classified content pages before this evidence is meaningful. Worded explicitly as "orphan-like within the sampled graph," never as a claim of global orphaning -- a page reached only through pages outside the sample would appear orphan-like here without genuinely being orphaned. |
| `ENG.AMBIGUOUS_ACTION_SURFACE` | Two or more in-content links on the same page share identical generic anchor text (from a fixed, conservative list: "click here", "read more", "learn more", and similar) but point to different destinations | weakens / template or page / measured | -- | Restricted to a fixed generic-phrase list, not any repeated text -- descriptive anchor text repeated for links to different destinations is not evaluated at all. Two links sharing generic text to the *same* destination is ordinary repetition, not ambiguity, and is not flagged. |

## Ownership boundaries

This detector never inspects: `robots.txt` policy, crawl access, redirect behaviour, or
landing-page integrity (`crawl-access-audit`, including `ACC.DEEPLINK_TO_HOME_REDIRECT`,
which remains the sole owner of "does a published URL land where it should"); raw-vs-
rendered content, CSR shells, heading structure, or thin content
(`render-readability-audit`); the validity or cross-page consistency of structured data
(`structured-data-entity-audit`); or whether a page states its own core fact plainly, has
heading anchors, or has a summary block (`answer-retrievability-audit`, whose
`ANS.NO_HEADING_ANCHORS` remains the sole owner of that check). This detector never opens
or reasons about the `render` field, `robots`, or `structured_data` at all -- its evidence
is drawn entirely from `links_internal`, `links_external`, `page_type`, and `clusters`.
Proactive, forward-looking recommendations (adding content that does not yet exist, or
capabilities this snapshot cannot measure, such as personalisation or actual behavioural
engagement) belong to `opportunity-and-monitoring`, never emitted here as a defect.

## Known limitations

Stated because a reader needs to know the edges of what was checked.

1. **The action-phrase and generic-anchor lexicons are English-only.** No structural
   alternative exists for recognising purchase/contact intent or genericness in link
   text without understanding the words. A non-English action link (e.g.
   "Contactez-nous") will not be recognised as satisfying `ENG.WEAK_ACTION_PATHWAY`,
   which could produce a false positive on an otherwise healthy non-English product
   page. This is a genuine, acknowledged limitation, not a design oversight.
2. **A self-referencing in-content link technically satisfies `ENG.DEAD_END_HIGH_VALUE_PAGE`'s
   "has an in-content link" test**, even though a link back to the same page is not a
   real next step. This is a rare pattern in practice and is not specially detected, in
   favour of a simpler, more conservative implementation; it is a false-negative risk,
   not a false-positive one.
3. **`ENG.EXCESSIVE_PATHWAY_DEPTH` depends on the collector's own cluster `depth` field**
   and says nothing about a site's true, unsampled structure -- only about this specific
   sample's own relative shape.
4. **`ENG.NO_RELATED_CONTENT_PATHWAY`'s destination classification depends on the
   collector's own page-type confidence**, which can itself degrade when a page's
   signals are reduced (non-English content, or structured data in a format the
   classifier weighs less heavily); this detector treats that gap as inconclusive rather
   than guessing, which trades recall for avoiding a confident, wrong finding.
5. **No check here evaluates image-only or JavaScript-rendered action surfaces** beyond
   what the collector's own link and structured-data extraction already captures; an
   action expressed purely as an unlabelled icon or a script-driven element with no
   `href` is invisible to this detector, and no finding is fabricated to cover that gap.
6. **This detector cannot and does not measure real user behaviour of any kind.** Every
   finding here is a structural observation about the sampled link graph, never a claim
   or estimate about what an actual visitor did or would do.
