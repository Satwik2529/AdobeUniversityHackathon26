# Brand AI-Readiness Audit — an Agent Skill Marketplace

← [Back to project README](../README.md)

Point a general AI agent at a website. It audits the site read-only and emits one
structured report: evidence-backed findings about why the brand is hard for AI assistants
to find, read, understand, quote and keep, plus prioritized, mechanism-sound fixes.

**Recommend-only.** No skill in this marketplace changes a live site. **Read-only.** GET
and HEAD requests only, robots.txt respected, no authentication, no bot-challenge
circumvention.

---

## The idea: one skill per gate of the discovery funnel

Discovery is a funnel, not a switch. A page can pass one stage and fail the next:

```
Exists → discovered → accessible → readable → understood → retrieved → selected
       → reflected in the answer                                    … then the click
```

"The page is indexed" does not mean "the assistant will mention it". Different failures
happen at different stages, and a fix aimed at the wrong stage does nothing. So the
marketplace has **one detector per gate**, plus a post-discovery, on-site stage that
checks whether a visitor who found something useful can tell what to do next.

That is why the decomposition is not padding: each detector consumes a different slice of
the captured site, produces a different category of evidence, and could be owned by a
different engineer.

## The skills

| Skill | Gate | Responsibility |
| --- | --- | --- |
| **`brand-ai-readiness-audit`** *(entrypoint)* | — | Plans the audit, dispatches everything else, correlates and deduplicates findings, applies the severity and priority models, emits `report.json` and `report.md`. Owns no checks. |
| `site-snapshot-collector` | — | **The only skill that touches the network.** Parses robots.txt with correct precedence, discovers and template-clusters URLs, samples deterministically, and fetches each page twice: as a non-rendering crawler sees it and as a browser renders it, plus a control fetch that exposes user-agent blocking. Emits `snapshot.json`. |
| `crawl-access-audit` | discovered, accessible | Robots policy resolved **per crawler role**, noindex, sitemap health, status and redirect integrity, canonicals, user-agent differential blocking, gated content. |
| `render-readability-audit` | readable | Raw-HTML versus rendered-DOM gaps, facts locked in images or PDFs, content behind interaction, interstitials in the raw response, semantic structure. |
| `structured-data-entity-audit` | understood | Structured-data validity and per-page-type coverage, structured-versus-visible contradictions, organization entity identity, `sameAs`, entity ambiguity risk. |
| `answer-retrievability-audit` | retrieved, selected | Whether a machine can locate and quote the one fact a question asks for: answer position, specification extractability, entity naming, units, heading anchors. |
| `freshness-corroboration-audit` | selected | Which version of a fact survives: intra-site contradictions (product price by sku, brand tagline), date-signal integrity, superseded content still live, availability signals, copyright-year lag, canonical fact surfaces. On-site only, by permanent architectural rule -- no off-site or external corroboration of any kind. |
| `engagement-audit` | post-discovery, on-site | Whether a visitor who found useful content can follow a next step: dead-end high-value pages, in-content links that lead nowhere related, missing action pathways on product pages, pathway depth relative to the site's own sampled structure, pages orphan-like within the sampled graph, and ambiguous repeated link text. |
| `opportunity-and-monitoring` | — | The only skill that reasons about relationships *between* findings rather than deriving one from the snapshot: cross-detector compound opportunities, template-leverage, monitoring recommendations tied to specific recurring check_ids, deferred-capability notes, and the measurement plan. Capped at 8 total. |

## How the entrypoint composes them

The Agent Skills specification defines the single-skill format but **not** skill-to-skill
invocation — the manifest here is this contest's own convention. The entrypoint therefore
does not assume the harness can dispatch to a sibling skill. Three paths produce the same
report, in preference order:

1. **Agent-native activation** — activate the sibling by its manifest id.
2. **Relative-path reading** — read `../<skill-id>/SKILL.md` and follow it. Needs nothing
   from the harness but file reads.
3. **Direct script execution** — every detector script runs standalone with
   `--snapshot` and `--out`. Merging their outputs yields a complete report even if no
   sub-skill is ever activated.

Then: `merge_findings.py` deduplicates by ownership rules, escalates corroborating pairs,
derives severity from `gate_impact × reach × certainty` with anti-overclaim caps, ranks by
funnel precedence, and emits. `validate_report.py` gates emission — an invalid report is
never written.

## Running it

```bash
# validate the marketplace itself
python3 tools/validate_marketplace.py --root . --strict

# run the full test suite (spec conformance, fixtures, scoring, determinism)
python3 tests/run_tests.py

# rebuild the local fixture sites
python3 tests/make_fixtures.py
```

## False positives are a feature target, not an afterthought

The audit is graded on *few misses and few false positives*, so precision is engineered.
Eleven guards are documented across the skills; the load-bearing ones:

- **Evidence-or-silence.** No concrete URL and observed value, no finding. Enforced in
  `validate_report.py`, so an unevidenced finding cannot even be emitted.
- **Training versus retrieval crawlers.** A site that blocks `GPTBot` while allowing
  `OAI-SearchBot` has opted out of training and stayed eligible for citation. That is a
  deliberate policy reported at `info`, **not** a defect. This is the most likely false
  positive in the whole problem domain.
- **Capability gating.** A check that could not run becomes `coverage.not_assessed`. The
  absence of our headless browser is never reported as a defect in someone's site.
- **Page-type gating.** No demand for product markup on a blog, or FAQ markup where there
  is no question-and-answer content.
- **Language neutrality.** Structural checks run anywhere; lexical checks run only where
  the page language is detected and supported. A site is never penalised for not being in
  English.
- **Two-signal rule** for every inference-heavy check, and severity caps by certainty.

Several fixtures are **negative controls** whose target is zero findings above
`info`: a clean site, a training-only crawler block, a non-English site, a two-page site,
a Microdata-only site, and correctly noindexed utility pages.

## Fixtures

One clean base site, then **single-variable mutations** — 35 fixtures in total under
`tests/fixtures/` (see `tests/fixtures/index.json` for the complete list). Every fixture
differs from the control in exactly one respect, so a firing check can be attributed to
one cause, and a negative control cannot pass by accident. The first 13 — covering crawl
access, render/readability, structured data and freshness — are detailed individually
below; the remaining 22 extend the same one-variable-per-fixture pattern to
answer-retrievability, freshness/corroboration and engagement-audit.

| Fixture | Tests |
| --- | --- |
| `F00-clean-control` | Precision. Contains three traps: a correctly noindexed search page, a decorative empty `alt`, an evergreen page last reviewed in 2019. |
| `F01-csr-shell` | Content only present after JavaScript runs. |
| `F02-robots-blocks-retrieval` | Retrieval agents disallowed — a real defect. |
| `F03-robots-blocks-training-only` | **Negative control.** Deliberate training opt-out. |
| `F04-schema-visible-mismatch` | Structured price contradicts the visible price. |
| `F05-deeplink-redirect` | Published deep links bounce to the homepage. |
| `F06-facts-in-images` | Specifications only as an image and a PDF. |
| `F07-stale-conflict` | The site contradicts itself on four facts. |
| `F08-non-english-clean` | **Negative control.** Valid site, not in English. |
| `F09-small-site-clean` | **Negative control.** Two pages, below the template threshold. |
| `F10-microdata-only` | **Negative control.** Valid Microdata is not a defect. |
| `F11-noindex-utility-ok` | **Negative control.** Cart, account, checkout, search. |
| `F12-ua-blocked` | Edge serves 403 to non-browser agents. The fabricated-evidence test: nothing could be read, so no content finding may be invented. |

## Honesty commitments

These are written into the skills, not just this README:

- **No technique is claimed to guarantee citation.** Structured data and server-side
  rendering improve reachability, readability and entity resolution. They raise
  eligibility. Nothing promises an assistant will cite you, and the report says so.
- **A machine-readable site index file** is offered only as a low-priority experiment,
  with the caveat that adoption is low and no major assistant provider has committed to
  consuming it at runtime. Its absence is never a defect.
- **Nothing commercial.** No paid placement, sponsorships, influencer deals, agency
  retainers, hiring, acquisitions or co-branding. Technical and editorial levers only.
- **`not_assessed` is stated as loudly as a finding**, because silence reads as a clean
  bill of health.

## Quick start

```bash
python3 audit.py https://your-site.com
```

That is the whole thing. Python 3.9 or newer, no dependencies to install. It writes
`audit-output/report.md` (read this), `report.json` (the same data, schema-validated)
and `snapshot.json` (the raw evidence every finding was derived from).

| Option | Default | What it does |
| --- | --- | --- |
| `--out DIR` | `audit-output` | where to write the snapshot, findings and report |
| `--render auto\|on\|off` | `auto` | use a headless browser to see JavaScript-rendered content; `auto` uses one only if installed |
| `--max-pages N` | 25 (cap 40) | how many pages to sample |
| `--time-budget N` | 150 | seconds allowed for fetching |
| `--user-agent-contact STR` | — | contact string added to the audit user agent; polite to set on a site you do not own |
| `--keep-going` | off | finish with a partial report if one detector fails, instead of stopping |
| `--quiet` | off | print only the summary |

Optional, for JavaScript-heavy sites: `pip install playwright && playwright install chromium`.
Without it, `--render auto` simply audits the raw HTML and says so in the report's
coverage section rather than guessing.

Exit codes: `0` audit completed, `1` it could not be completed, `2` bad arguments.

`audit.py` is a convenience runner, not a tenth skill and not a second entrypoint. It
executes exactly the sequence `skills/brand-ai-readiness-audit/SKILL.md` tells an agent
to follow, calling the same scripts in the same order. It contains no audit logic of its
own; deleting it would not change what the marketplace can do.

### Trying it without a live site

The 35 test fixtures are real websites served over HTTP on localhost, so the whole
pipeline can be exercised offline:

```bash
python3 tests/fixture_server.py --dir tests/fixtures/F07-stale-conflict   # terminal 1
python3 audit.py http://localhost:8099 --render off                        # terminal 2
```

`F00-clean-control` is the healthy site and should produce zero findings.

### Running the test suite

```bash
python3 tests/run_tests.py                     # 8 layers, 35 fixtures
python3 tools/validate_marketplace.py --root . # marketplace spec conformance
```

## Status

| Component | State |
| --- | --- |
| Manifest, all nine `SKILL.md` files, reference catalogues | complete |
| Spec validator plus 17 adversarial self-tests | complete, passing |
| Frozen `snapshot.json` contract | complete, v1.0 |
| Entrypoint merge, ranking, report schema and renderer | complete |
| 35 fixtures, rule-driven fixture server, scoring harness | complete |
| `site-snapshot-collector` | complete, 94 tests |
| `crawl-access-audit` (21 ACC checks) | complete, 77 tests |
| `render-readability-audit` (17 RND checks, 15 finding-emitting) | complete, 87 tests |
| `structured-data-entity-audit` (15 SDE checks) | complete, 100 tests |
| `answer-retrievability-audit` (9 ANS checks) | complete, 75 tests |
| `freshness-corroboration-audit` (7 FRC checks) | complete, 60 tests |
| `engagement-audit` (6 ENG checks) | complete, 64 tests |
| `opportunity-and-monitoring` (5 synthesis rule families) | complete, 61 tests |
| **All nine skills** | **complete** -- final integration remains |

### Measured results, Milestone L

| Measurement | Value |
| --- | --- |
| Opportunity-and-monitoring unit tests | 61 |
| Adversarial cases (beyond the unit suite) | 30 run, 0 failed |
| Total tests at this point | 635 (94 collector + 77 access + 87 render + 100 SDE + 75 ANS + 60 FRC + 64 ENG + 61 OPP + 17 validator self-tests) |
| Marketplace validator | 0 errors, **0 warnings** (all nine skills now implemented) |
| Determinism | identical opportunities and measurement plan across repeated runs |

**This is a synthesis skill, not a detector.** It consumes the raw per-detector findings
files and the snapshot -- never the pages directly -- and emits `opportunities` and a
`measurement_plan`, both loaded verbatim into the final report by `merge_findings.py`.
It does not produce `action_sequence`, which remains entirely the entrypoint's own
`build_action_sequence(findings)`. Severity used for prioritising opportunities is a
verbatim duplicate of `merge_findings.derive_severity`, kept in sync deliberately,
matching the "duplicate small shared logic rather than cross-import" convention every
detector already follows -- not a second, competing scoring model.

**Two genuine, pre-existing schema defects were found and fixed during end-to-end
integration testing** (running the real pipeline -- collector, all six detectors,
opportunity synthesis, merge, validate, render -- together for the first time):
`report.schema.json`'s `effort` enum was missing `"content"`, despite five of six
detectors consistently using it since Milestone G; its `owner` enum was missing
`"marketing"`, used by the structured-data detector. Both were narrow, additive,
backward-compatible corrections (widening an enum only accepts previously-rejected
values that detectors were already, correctly, emitting) verified by re-running the
full prior-milestone regression suite afterward with zero regressions.

A category-naming ambiguity was also found and fixed: an early version of the
template-leverage rule (any 2+ checks sharing a page set, same or different detector)
reused the same category name as the named cross-detector compound rule (a small,
explicit table of six specific detector-pair relationships), which made it impossible
to tell, from category alone, whether an opportunity came from a hand-written
relationship or a generic same-template observation. They are now `template-leverage`
and `cross-detector-template` respectively.

## Layout

```
brand-ai-readiness-audit/
├── marketplace.json          manifest: nine skills, exactly one entrypoint
├── README.md  LICENSE
├── skills/                   nine agentskills.io-compliant skill folders, each with its own SKILL.md
├── tools/validate_marketplace.py
└── tests/                    fixtures, expectations, server, harness
```

## Related documentation

- [Project root README](../README.md) — project overview and quick start
