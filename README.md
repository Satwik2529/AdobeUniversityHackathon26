# Brand AI Readiness Audit + Query Intelligence

Point it at a website. It tells you — with cited evidence, not guesses —
whether AI assistants can find, read, understand and quote the brand, and
whether the site could actually answer specific natural-language questions
a real user might ask.

## What problem does this solve?

A website can genuinely contain the information a user wants and still fail
an AI assistant: the fact might be locked in an image, blocked by robots.txt
for retrieval bots, contradicted elsewhere on the site, or simply never
tied together into one place. **Brand AI Readiness Audit** finds those
structural gaps. **Query Intelligence** goes one step further: given an
actual query ("best laptop for students under ₹60,000 with 16GB RAM"), it
checks whether the site's own already-captured evidence could support that
specific answer — and shows exactly why or why not.

## Two systems, one direction of dependency

```
Brand AI-Readiness Audit  (9 Agent Skills, read-only, works standalone)
          │
          │  snapshot.json / report.json  — READ ONLY, never written to
          ▼
   Query Intelligence     (separate subsystem, reads the audit's output)
```

The audit works completely on its own. Query Intelligence is optional and
can be deleted without changing anything the audit does — it only ever
*reads* what the audit already produced.

---

## Key capabilities

- **Read-only audit** of any public website: crawl access, render/readability
  gaps, structured data, answer retrievability, freshness/contradictions,
  on-site engagement — each owned by its own Agent Skill.
- **Evidence-backed findings only** — no concrete URL and observed value, no
  finding. Nothing is asserted without a citation.
- **Query Intelligence**: give it a real question, see it decomposed into
  requirements, each checked against the site's own evidence, with an
  explainable, multi-dimensional score — not a single opaque percentage.
- **Cross-entity consistency checking** so a query isn't marked "supported"
  by evidence assembled from three unrelated products (see [§ The
  combination check](#the-combination-check)).
- **Domain-aware** without being domain-*specific* — one NLP engine, four
  pluggable vocabularies (shopping / education / healthcare / generic).
- **No API key, no external LLM, no extra network access.** Query
  Intelligence is deterministic rule-based extraction over a controlled
  vocabulary, not a model call.

---

## How it works

### System architecture

```
                    WEBSITE
                       │
                       ▼
              SITE SNAPSHOT COLLECTOR        ← the only step that touches the network
                       │
                       ▼
              EXISTING AUDIT · 9 SKILLS
                       │
                       ▼
              AUDIT REPORT (report.json / report.md)
                       │
                       ▼
             QUERY INTELLIGENCE  (reads the snapshot + report, read-only)
                       │
                       ▼
                 NLP ENGINE
                       │
       ┌───────────────┼───────────────┐
       ▼               ▼               ▼
    Intent          Entity        Attributes / Constraints
       │               │               │
       └───────────────┴───────────────┘
                       ▼
                 Requirements
                       │
                       ▼
             Evidence retrieval  (search the frozen snapshot)
                       │
                       ▼
             Evidence verification + combination check
                       │
                       ▼
        Score + Explanation  (Coverage · Answerability · Quality · Opportunity)
                       │
                       ▼
               query-result.json
```

### Brand AI Readiness Audit

Nine Agent Skills, each owning one gate of the discovery funnel:

```
Exists → discovered → accessible → readable → understood → retrieved → selected → cited
```

| Skill | Purpose |
|---|---|
| `brand-ai-readiness-audit` *(entrypoint)* | Plans the audit, dispatches every skill below, merges and deduplicates findings, emits `report.json` / `report.md`. |
| `site-snapshot-collector` | **The only skill that touches the network.** Parses `robots.txt`, discovers and samples URLs, fetches each page as a crawler and (optionally) a browser. Emits `snapshot.json`. |
| `crawl-access-audit` | Robots policy per crawler role, `noindex`, sitemap health, redirects, canonicals, user-agent blocking. |
| `render-readability-audit` | Raw-HTML vs. rendered-DOM gaps, facts locked in images/PDFs, content behind interaction. |
| `structured-data-entity-audit` | Structured-data validity, structured-vs-visible contradictions, entity identity. |
| `answer-retrievability-audit` | Whether a machine can locate and quote the exact fact a question asks for. |
| `freshness-corroboration-audit` | Which version of a fact survives: intra-site contradictions, stale content, availability signals. |
| `engagement-audit` | Whether a visitor who found something useful can follow a next step. |
| `opportunity-and-monitoring` | Cross-detector opportunities and the measurement plan (capped at 8). |

Read-only and recommend-only: GET/HEAD only, robots.txt respected, no
authentication, no bot-challenge circumvention, and no skill ever writes
back to the audited site.

### Query Intelligence

**Example.** For the query:

> "Best laptop for CSE students under ₹60,000 with 16GB RAM and good
> battery life"

the engine extracts:

```
Intent:      recommendation
Entity:      laptop
Audience:    CSE students
Price:       ≤ ₹60,000
Attribute:   RAM = 16GB
Attribute:   battery life = good
Qualifier:   best   (subjective — flagged, never silently assumed true)
```

Each requirement is then checked, independently and with a citation, against
the pages that actually identify "laptop" on the audited site — never a
sitewide keyword search.

#### Evidence statuses

| Status | Meaning |
|---|---|
| `SUPPORTED` | The requirement is genuinely evidenced on the entity's own pages. |
| `PARTIALLY_SUPPORTED` | Evidence exists but is incomplete or ambiguous. |
| `NOT_FOUND` | No evidence for this requirement was found anywhere on the entity's pages. |
| `CONTRADICTED` | Evidence was found, and it conflicts with what the query asked for. |
| `NOT_ASSESSABLE` | Genuinely can't be checked (no entity to scope by, unsupported language, or a subjective claim like "best" no site can verify about itself). Excluded from the score, never penalized. |
| `INVALID_REQUIREMENT` | The concept is real (RAM is a recognized attribute) but has **no evidenced relationship to this entity** — e.g. asking a keyboard product about RAM. Unlike `NOT_ASSESSABLE`, this *does* count against the score. |

#### The combination check

Checking requirements independently has a real failure mode. Suppose the
site has:

```
Product A:  positioned for students, ₹45,000, 8GB RAM
Product B:  16GB RAM, ₹95,000, no student positioning
```

A query for *"laptop for students under ₹60,000 with 16GB RAM"* must **not**
be marked fully supported just because each individual piece is true of
*some* product on the site — no single product actually satisfies all
three. The combination checker verifies whether one page accounts for more
than one requirement's evidence, and reports exactly which product came
closest and what it was missing, instead of quietly assembling a
"Frankenstein" answer from unrelated products.

#### Domain support

One NLP/evidence engine — it never branches on domain. What changes per
site is only which **vocabulary** it's handed:

```
Common NLP + evidence engine
       │
       ├── Shopping schema     (RAM, storage, battery · students, gamers · programming, gaming)
       ├── Education schema    (tuition, accreditation · undergrad/grad/international · research)
       ├── Healthcare schema   (insurance, telehealth, specialty · patients, seniors · checkups)
       └── Generic fallback    (no attribute guesses — only broad, safe audience/use-case terms)
```

Domain is detected from the snapshot's own `schema.org` types first (e.g.
`Course` → education), falling back to a conservative keyword check only
when structured data gives no signal at all. A site that doesn't confidently
match any of the three schemas gets the generic fallback rather than a wrong
guess.

#### Scoring

Never one blended percentage — five independent numbers:

| Dimension | Answers |
|---|---|
| **Evidence coverage** | Of what could be checked, how well is it supported? |
| **Answerability** | Of everything the query asked, how much could be checked at all? |
| **Confidence** | How strong is the evidence behind the coverage number? |
| **Query quality** | Is this a coherent, realistic, testable question? |
| **Opportunity** | A realistic query with a genuine, actionable content gap? |

---

## Where do I go?

Each part of the codebase documents itself — this README stays an overview
and links down to the detail:

| I want to... | Read |
|---|---|
| Understand the whole project | this file |
| Modify or add an audit check (an Agent Skill) | [brand-ai-readiness-audit/README.md](brand-ai-readiness-audit/README.md) |
| Modify the NLP / Query Intelligence engine | [nlp-query-intelligence/README.md](brand-ai-readiness-audit/nlp-query-intelligence/README.md) |
| Understand Query Intelligence's test suite and fixtures | [nlp-query-intelligence/tests/README.md](brand-ai-readiness-audit/nlp-query-intelligence/tests/README.md) |
| Read the design rationale and supporting material | [docs/SUPPORTING_DOCS.md](docs/SUPPORTING_DOCS.md) |
| See the backend architecture diagram | [Backend-Architecture.pdf](Backend-Architecture.pdf) |

## Project structure

```
AdobeUniversityHackathon26/
├── brand-ai-readiness-audit/          the 9-skill audit                                         → brand-ai-readiness-audit/README.md
│   ├── marketplace.json                 manifest: 9 skills, 1 entrypoint
│   ├── audit.py                         CLI: runs the full audit pipeline
│   ├── skills/                          the 9 Agent Skills, each with its own SKILL.md
│   ├── tests/                           audit fixtures + test harness
│   ├── tools/                           marketplace validator + report summary helpers
│   └── nlp-query-intelligence/          Query Intelligence — separate subsystem                 → nlp-query-intelligence/README.md
│       ├── pipeline.py                    CLI: profile | generate | test | compare | dataset
│       ├── lib/                           NLP engine, domain vocabularies, scoring, evidence
│       ├── assets/                        JSON Schemas for its own output files
│       └── tests/                         its own test suite + synthetic fixtures              → nlp-query-intelligence/tests/README.md
├── dry-runs/books-toscrape/           a complete example audit of books.toscrape.com (checked in)
├── docs/                              supporting docs, project explainer, Round 4 video plan
├── Backend-Architecture.pdf           architecture diagram
└── REPLAY_TEAMNAME.txt                Round 4 reproduction manifest (template)
```

`nlp-query-intelligence/` is **not** in `marketplace.json` — it's an
application subsystem, not a tenth Agent Skill.

---

## Prerequisites

- **Python 3.9+** — no pip dependencies (standard library only).
- *Optional:* Playwright + Chromium for the headless-render half of the
  render checks (see [Limitations](#limitations)).

---

## Quick Start

```bash
git clone https://github.com/psp2535/AdobeUniversityHackathon26.git
cd AdobeUniversityHackathon26
```

### Run an audit

```bash
cd brand-ai-readiness-audit
python audit.py https://example.com
```

Writes `audit-output/snapshot.json`, `report.json` and `report.md`. Each run
overwrites the last unless you pass `--out DIR`. Other useful flags:
`--max-pages N`, `--render auto|on|off`, `--quiet`.

You can also run it through an agent harness (e.g. Claude Code) by pointing
the agent at `skills/brand-ai-readiness-audit/SKILL.md` as the marketplace
entrypoint.

No live site handy? `dry-runs/books-toscrape/` holds a complete, checked-in
run — read its `report.md`.

### Use Query Intelligence

From the repository root, against the checked-in example run:

```bash
cd brand-ai-readiness-audit/nlp-query-intelligence
python pipeline.py profile  --snapshot ../../dry-runs/books-toscrape/snapshot.json --out nlp-output/website-profile.json
python pipeline.py generate --snapshot ../../dry-runs/books-toscrape/snapshot.json --profile nlp-output/website-profile.json --out nlp-output/generated-queries.json
python pipeline.py test     --query "Is there a mystery book under 20 pounds" --snapshot ../../dry-runs/books-toscrape/snapshot.json --profile nlp-output/website-profile.json --report ../../dry-runs/books-toscrape/report.json --out nlp-output/result.json
```

To use your own audit instead, swap `../../dry-runs/books-toscrape/` for
`../audit-output/`.

### Fresh-clone reproducibility

| | |
|---|---|
| **Required after cloning** | Python 3.9+. Nothing to install or build. |
| **Checked in for an immediate demo** | `dry-runs/books-toscrape/` — a real, complete example run. |
| **Generated, not committed** | `audit-output/`, `nlp-output/`, `__pycache__/` — all reproducible by running the commands above. |

---

## Testing

From the repository root:

```bash
# Existing 9-skill audit
cd brand-ai-readiness-audit
python tools/validate_marketplace.py --root . --strict   # Agent Skills spec conformance
python tests/run_tests.py                                 # fixtures, scoring, determinism, schema

# Query Intelligence
cd nlp-query-intelligence
python tests/run_tests.py                                 # its own layered harness + fixtures
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `python: command not found` | Some systems only expose `python3`, or need the Python launcher (`py`) on Windows. |
| `audit.py` produces 0 findings | That can be a genuinely clean result, not an error — check the report's coverage section for what was actually assessed. |
| Render checks listed under `coverage.not_assessed` | No headless browser is installed — see [Limitations](#limitations). The rest of the audit still runs. |

---

## Important design principles

- **Evidence-or-silence.** No concrete URL and observed value, no finding.
- **Capability gating, not fabrication.** A check that couldn't run is
  `NOT_ASSESSABLE` / `coverage.not_assessed`, never a quiet pass or fail.
- **No technique guarantees citation**, and Query Intelligence never claims
  to know what an AI assistant would actually answer — only whether the
  site's own evidence could support the answer.
- **Nothing commercial.** No paid placement, no sponsorships, no retainers.

## Limitations

- Query Intelligence's "valued" attribute extraction (explicit numbers like
  `16GB`) is strongest for shopping/electronics; education and healthcare
  domains rely more on presence-based attributes and price/duration
  constraints.
- Domain detection uses `schema.org` types first and a conservative keyword
  fallback second — a site with neither signal falls back to the generic
  vocabulary rather than guessing.
- The audit's headless-render step (`--render on/auto`) requires
  `pip install playwright && playwright install chromium`; without it, the
  audit still runs against raw HTML and says so in the report.

## License

Apache License 2.0 — see
[`brand-ai-readiness-audit/LICENSE`](brand-ai-readiness-audit/LICENSE).
