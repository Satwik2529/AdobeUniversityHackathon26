# Round 4 — Shooting script (5:00 hard cap)

Narration is timed at a normal pace, about 140 words per minute, and measured to fit.
Part 1 narration is 411 words, roughly 2:56. Every claim has a file and line number to
put on screen beside it. Paths are relative to `brand-ai-readiness-audit/`.

**Record Part 1 and Part 2 separately.** Part 1 may be re-taken freely. Part 2 must be
one continuous run, with only idle waiting trimmed.

---

# The four novelty points, ranked

Everything in Part 1 exists to land these. If a sentence does not serve one of them, cut it.

| # | Point | Why a judge cares | Anchor |
| --- | --- | --- | --- |
| 1 | **Role, not vendor, decides if a crawler block is a defect** | The most likely false positive in this domain, and almost every tool gets it wrong | `skills/crawl-access-audit/references/agent-roles.json` |
| 2 | **A finding neither detector can see alone** | Cross-detector correlation, not a checklist | `merge_findings.py:90` and `:200` |
| 3 | **Fix order comes from the funnel, not from severity** | Prioritisation with a mechanism behind it | `references/severity-model.md` and `merge_findings.py:227` |
| 4 | **An unevidenced finding cannot physically be emitted** | Precision enforced by code, not good intentions | `validate_report.py:106-111` |

---

# PART 1 — Thought process (2:56)

## 0:00–0:25 — The thesis

**On screen:** `README.md`, the funnel diagram. Then `marketplace.json`.

> "A website can be fully indexed and still never be cited. Discovery is a funnel, not a
> switch. Discovered, accessible, readable, understood, retrieved, selected, reflected. A
> page can pass one gate and fail the next, and a fix aimed at the wrong gate does nothing.
>
> So: one detector per gate. Nine skills, one snapshot, a different kind of evidence from
> each."

## 0:25–1:10 — Novelty 1: the signals, and engineering out false positives

**On screen:** `agent-roles.json`, the roles block. Then `tests/fixtures/F03-robots-blocks-training-only`.

> "The field research came down to one question: when is a crawler block actually a
> problem? The naive answer, that blocking an AI crawler hurts you, is the biggest false
> positive in this domain.
>
> This table maps each crawler to its role. GPTBot trains. OAI-SearchBot retrieves. A
> site blocking GPTBot while allowing OAI-SearchBot has opted out of training and stayed
> eligible for citation. Deliberate policy, reported at info, never a defect. Role
> decides, not vendor.
>
> And it is a test, not an opinion. F03 is a negative control targeting zero findings
> above info. Thirty-five fixtures, each a single-variable mutation of one clean control."

## 1:10–2:00 — Novelty 2: severity, and the finding no single detector can see

**On screen:** `severity-model.md`, the formula and the caps table. Then `merge_findings.py:90` and the `escalate` function at `:200`.

> "Severity is computed, not assigned by taste. Does the problem shut a gate, degrade it,
> or weaken it. Does it hit the whole site, one template, or one page. Did we measure it,
> or infer it.
>
> Then the anti-overclaim caps. Inferred evidence never exceeds high. A single-signal
> check caps at medium. Fewer than three pages caps at medium.
>
> And here is what a checklist cannot do. If the structured-data detector sees markup
> contradicting the visible price, and the freshness detector independently sees that same
> fact contradicted elsewhere, together they escalate to critical. The brand publishes two
> contradictory machine-readable versions of one fact. Neither detector sees that alone.
> It exists only in the correlation."

## 2:00–2:40 — Novelty 3: why the fixes are ordered the way they are

**On screen:** `severity-model.md`, the priority formula. Then `merge_findings.py:227`.

> "Severity describes damage. Priority describes what to do first. They are computed
> separately. Priority is impact times reach, divided by effort, multiplied by funnel
> precedence, and funnel precedence decides: earlier gates first. Perfect structured data
> on a page retrieval crawlers cannot reach is worth nothing.
>
> The code enforces it. While a site-wide access gate is shut, downstream findings are
> kept but demoted below the fix that opens it, and the report says later fixes cannot pay
> off until it does. Effort is honest: trivial, config, template change, platform change."

## 2:40–2:56 — Novelty 4: the precision guarantee

**On screen:** `validate_report.py`, lines 106 to 111.

> "One rule underpins all of it. No URL and observed value, no finding. Not a guideline, a
> gate at emission: a report that fails it is never written. And a check that could not
> run becomes coverage-not-assessed, never a defect."

---

# PART 2 — Trial run (2:00)

Narration here is 148 words, about 63 seconds, leaving roughly a minute of watching the
agent work and reading the report on screen.

## 0:00–0:12 — Harness, model, wiring

> "This is Claude Code version [X], driving [model name and version]. The session reads
> skills/brand-ai-readiness-audit/SKILL.md, the marketplace entrypoint from our Round 3
> package. Nothing is hardcoded, and the site is one the audit has never analysed."

## 0:12–0:25 — Enter the URL

Paste the prompt from the manifest, word for word, with the URL visible. Press Enter on camera.

## 0:25–0:50 — Let the agent work (trim idle time here, and only here)

> "The entrypoint dispatches the collector, the only skill that touches the network. It
> fetches each page twice, as a non-rendering crawler sees it and as a browser renders it.
> The six detectors then read that frozen snapshot, so every finding traces to one
> captured artefact."

## 0:50–1:35 — Drill into one finding

**On screen:** `audit-output/report.json`, one finding expanded.

Say these four things, in this order:

1. **Evidence.** "Here is the URL, and the value we actually observed on it."
2. **Severity and why.** "It is [severity] because it [shuts / degrades] the [gate] gate across [the site / this template], and we measured it rather than inferred it."
3. **The fix.** "The suggested action is [x], which works because [mechanism]."
4. **Its rank.** "It sits at position [n] because funnel precedence puts access before markup."

Prefer, in this order: a raw-HTML versus rendered-DOM gap, a structured-versus-visible
contradiction, a retrieval-crawler block, a date or fact conflict.

## 1:35–1:55 — Ranking and output

**On screen:** `audit-output/report.md`, action bands in order.

> "Fixes sort by impact into bands: unblock first, then make readable and quotable. The
> report lands at audit-output/report.json, the path in our manifest. Anything the engine
> could not assess is listed honestly rather than guessed."

## 1:55–2:00 — Close

> "Same engine as Round 3, running live, read-only, recommend-only."

---

# Rehearsal and safety

- [ ] **Rehearse the full agent run twice before recording.** This is the one path never yet verified. If the agent stalls, you have no Part 2.
- [ ] **Dry-run five or six candidate sites**, then record the one with a vivid finding. Never edit code between the dry run and the take.
- [ ] Read Part 1 aloud against a stopwatch. It is written to 2:56, so there is no slack for improvising.
- [ ] Do **not** run `tools/validate_marketplace.py` on camera on Windows. It falsely reports every skill as unlisted, a path-separator bug in the checker. It passes on macOS, Linux and WSL.
- [ ] If you show a test, show one fixture: `python tests/run_tests.py --only L2 --fixture F00-clean-control`, about 35 seconds, reports recall 1.00, precision 1.00, 0 false positives.
- [ ] Do **not** edit anything inside `brand-ai-readiness-audit/`, not even to fix that bug.
- [ ] Model, harness and URL spoken on camera must match the manifest exactly.
- [ ] Optional, only if Part 2 finishes by 1:45: one query-intelligence command, 10 seconds. Phrase the question with a category and a currency symbol, for example "cheap books under £50". Aim for a score below 100%, which shows real per-requirement checking.
- [ ] Optional, only if Part 1 comes in under 2:50: one spoken clause, nothing on screen. "Recent GEO research independently converges on the same multi-stage view." Never say you based the design on it.
