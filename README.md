# Brand AI Readiness Audit and query processing

**An Agent Skill marketplace that audits any public website, read-only, for why AI
assistants can't find, read, understand or quote the brand — and emits one
evidence-backed report with prioritized fixes.**

Built for the Adobe University Hackathon 2026 by a team of three — see [Team](#team).

---

## What problem does this solve?

A website can genuinely contain the information a user wants and still fail an AI
assistant. The fact might be locked in an image, blocked by `robots.txt` for retrieval
bots, contradicted elsewhere on the site, rendered only by JavaScript, or never tied to a
clearly identified brand. "The page is indexed" does not mean "the assistant will mention
it."

This project finds those structural gaps, cites the exact evidence for each one, and
tells the site owner what to fix first.

## Key capabilities

- **Nine Agent Skills, one per gate of the discovery funnel** — crawl access,
  render/readability, structured data and entity identity, answer retrievability,
  freshness and contradictions, on-site engagement, plus opportunities and monitoring.
- **Evidence-or-silence.** No concrete URL and observed value, no finding. Enforced by a
  validator, so an unevidenced finding cannot even be emitted.
- **Read-only and recommend-only.** GET/HEAD only, `robots.txt` respected, no
  authentication, no bot-challenge circumvention, and nothing is ever written back to the
  audited site.
- **Precision-engineered.** Training-only crawler blocks, valid Microdata, correctly
  noindexed utility pages and non-English sites are *not* reported as defects.
- **Honest coverage.** Anything that could not be checked is listed under
  `coverage.not_assessed` — never a silent pass or fail.
- **Zero dependencies.** Python 3.9+ standard library only. No API keys, no LLM calls.

---

## How it works

### The discovery funnel

Discovery is a funnel, not a switch. A page can pass one stage and fail the next, and a
fix aimed at the wrong stage does nothing — so the marketplace has one detector per gate:

```
Exists → discovered → accessible → readable → understood → retrieved → selected → cited
```

### Architecture

```
                     WEBSITE
                        │
                        ▼
            site-snapshot-collector          ← the only step that touches the network
                        │
                        ▼
                  snapshot.json              (frozen evidence: robots, sitemap, pages,
                        │                     raw HTML + rendered DOM, structured data)
       ┌────────┬───────┼────────┬────────┬────────┐
       ▼        ▼       ▼        ▼        ▼        ▼
     crawl   render  structured answer freshness engagement     six detectors, each
     access  readab.  data /    retriev. corrob.   audit         reads the same snapshot
       │        │     entity     │        │        │
       └────────┴───────┬────────┴────────┴────────┘
                        ▼
            opportunity-and-monitoring       cross-detector opportunities (max 8)
                        │
                        ▼
      merge → dedupe → severity → priority → validate
                        │
                        ▼
              report.json  +  report.md
```

### The skills

| Skill | Gate | What it checks |
|---|---|---|
| `brand-ai-readiness-audit` *(entrypoint)* | — | Plans the audit, dispatches every skill below, merges and deduplicates findings, applies severity and priority, emits the report. Owns no checks itself. |
| `site-snapshot-collector` | — | **The only skill that touches the network.** Parses `robots.txt`, discovers and samples URLs, fetches each page as a crawler and (optionally) as a browser, plus a control fetch that exposes user-agent blocking. Emits `snapshot.json`. |
| `crawl-access-audit` | discovered, accessible | Robots policy per crawler role, `noindex`, sitemap health, redirects, canonicals, user-agent blocking. |
| `render-readability-audit` | readable | Raw-HTML vs. rendered-DOM gaps, facts locked in images/PDFs, content behind interaction, interstitials. |
| `structured-data-entity-audit` | understood | Structured-data validity and coverage, structured-vs-visible contradictions, organization identity, `sameAs`. |
| `answer-retrievability-audit` | retrieved, selected | Whether a machine can locate and quote the exact fact a question asks for: answer position, specs, units, entity naming. |
| `freshness-corroboration-audit` | selected | Intra-site contradictions (e.g. price by SKU), date-signal integrity, stale content, availability signals. |
| `engagement-audit` | post-discovery | Whether a visitor who found something useful can follow a next step: dead ends, orphan pages, missing action paths. |
| `opportunity-and-monitoring` | — | Relationships *between* findings: compound opportunities, template leverage, monitoring and measurement plan. Capped at 8. |

Severity is derived from `gate_impact × reach × certainty`, with caps that stop
low-certainty findings from being overclaimed.

---

## Quick Start

### Prerequisites

- **Python 3.9+** — nothing to `pip install`.
- *Optional:* a headless browser for the rendered-DOM half of the render checks:
  `pip install playwright && playwright install chromium`. Without it the audit still
  runs on raw HTML and says so in the report.

### Run an audit

```bash
git clone https://github.com/psp2535/AdobeUniversityHackathon26.git
cd AdobeUniversityHackathon26/brand-ai-readiness-audit
python audit.py https://example.com
```

It writes three files to `audit-output/`:

| File | What it is |
|---|---|
| `report.md` | The human-readable report — **read this** |
| `report.json` | The same data, schema-validated |
| `snapshot.json` | The raw evidence every finding was derived from |

Useful options:

| Option | Default | What it does |
|---|---|---|
| `--out DIR` | `audit-output` | Where to write the output |
| `--max-pages N` | 25 (cap 40) | How many pages to sample |
| `--render auto\|on\|off` | `auto` | Use a headless browser for JavaScript-rendered content; `auto` uses one only if installed |
| `--time-budget N` | 150 | Seconds allowed for fetching |
| `--user-agent-contact STR` | — | Contact string added to the user agent; polite on sites you don't own |
| `--keep-going` | off | Finish with a partial report if one detector fails |
| `--quiet` | off | Print only the summary |

For a short `SUMMARY.md` next to the report, run
`python tools/run_audit_with_summary.py https://example.com` instead.

### Run it through an AI agent

The marketplace is designed to be driven by a general agent harness (e.g. Claude Code).
Start the agent inside `brand-ai-readiness-audit/` and prompt:

> Read `skills/brand-ai-readiness-audit/SKILL.md` and follow it as the marketplace
> entrypoint. Audit https://example.com and write the report to `./audit-output`. Do not
> invent findings: anything you cannot verify goes in `coverage.not_assessed`.

`audit.py` runs exactly the same sequence of scripts the entrypoint skill tells an agent
to follow — it contains no audit logic of its own.

### Try it without a live site

The 35 test fixtures are small websites served on localhost, so the whole pipeline runs
offline:

```bash
cd brand-ai-readiness-audit
python tests/fixture_server.py --dir tests/fixtures/F07-stale-conflict   # terminal 1
python audit.py http://localhost:8099 --render off                       # terminal 2
```

Or just read a complete, checked-in run:
[dry-runs/books-toscrape/report.md](dry-runs/books-toscrape/report.md).

---

## Sample output

From the checked-in audit of books.toscrape.com:

```
| Severity | Count |
| Critical | 0     |
| High     | 2     |
| Medium   | 6     |
| Low      | 2     |

Do these first
1. Publish a robots.txt that declares the sitemap and states an explicit policy
   for training and retrieval crawlers.                 (engineering · trivial)
2. Publish a sitemap with accurate lastmod values.      (engineering · config)
3. Add one Organization node to the homepage, in JSON-LD, with a stable
   identifier.                                          (engineering · template-change)
```

Every finding in the full report states what was observed (with example URLs), why it
matters, what to do, its priority, effort and owner, and how to check the fix worked.

---

## Project structure

```
AdobeUniversityHackathon26/
├── brand-ai-readiness-audit/          the Agent Skill marketplace   → brand-ai-readiness-audit/README.md
│   ├── marketplace.json                 manifest: 9 skills, 1 entrypoint
│   ├── audit.py                         CLI: runs the full audit pipeline
│   ├── skills/                          the 9 Agent Skills, each with its own SKILL.md + scripts
│   ├── tests/                           35 fixture sites, expectations, fixture server, test harness
│   └── tools/                           marketplace validator, summary generator
├── dry-runs/books-toscrape/           a complete example audit (report, findings, snapshot)
└── Backend-Architecture.pdf           architecture overview
```

---

## Testing

```bash
cd brand-ai-readiness-audit
python tools/validate_marketplace.py --root . --strict   # Agent Skills spec conformance
python tests/run_tests.py                                 # 8 layers, 35 fixtures: scoring, determinism, schema
```

Several fixtures are **negative controls** whose target is zero findings above `info`: a
clean site, a training-only crawler block, a non-English site, a two-page site, a
Microdata-only site, and correctly noindexed utility pages.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `python: command not found` | Use `python3`, or the `py` launcher on Windows. |
| `audit.py` produces 0 findings | That can be a genuinely clean result — check the report's coverage section for what was actually assessed. |
| Render checks listed under `coverage.not_assessed` | No headless browser is installed. Install Playwright + Chromium (see Prerequisites); the rest of the audit is unaffected. |
| Exit code `1` | The audit could not be completed (e.g. the site was unreachable). Exit code `2` means bad arguments. |

---

## Design principles

- **Evidence-or-silence.** No concrete URL and observed value, no finding.
- **Capability gating, not fabrication.** A check that couldn't run is reported as
  not assessed — the absence of our headless browser is never a defect in someone's site.
- **No technique guarantees citation.** Structured data and server-side rendering raise
  eligibility; the report never promises an assistant will cite you.
- **Nothing commercial.** No paid placement, sponsorships or retainers — technical and
  editorial levers only.

## Limitations

- Samples up to 40 pages per run, so very large sites are audited by template sample,
  not exhaustively.
- Rendered-DOM checks need Playwright + Chromium; without them those checks are reported
  as not assessed.
- Freshness checks compare the site only against itself — no off-site corroboration.
- Lexical checks run only where the page language is detected and supported; structural
  checks run everywhere.

## Team

| Name | GitHub | LinkedIn |
|---|---|---|
| Pathange Sai Pranav | [@psp2535](https://github.com/psp2535) | [pathangesaipranav](https://www.linkedin.com/in/pathangesaipranav/) |
| Chakali Surendra | [@suri5790](https://github.com/suri5790) | [surendrachakali](https://www.linkedin.com/in/surendrachakali/) |
| Duppala Satwik | [@Satwik2529](https://github.com/Satwik2529) | [satwik2529dsk](https://www.linkedin.com/in/satwik2529dsk/) |

## License

Apache License 2.0 — see [`brand-ai-readiness-audit/LICENSE`](brand-ai-readiness-audit/LICENSE).
