# Measurement plan structure

Always emitted by `_build_measurement_plan`, never gated or capped -- without it a report
is a list of opinions that can never be settled. Matches `render_report_md.py`'s expected
shape exactly: `{"tracks": [{"track", "what", "how", "cadence"}, ...], "caveat": "..."}`.

## The four tracks always present

| Track | What to measure | How | Cadence |
| --- | --- | --- | --- |
| Visibility | Is the brand named, and is it cited | A fixed panel of 30 to 50 prompts covering category questions, brand-direct questions, comparisons and long-tail questions, run across several assistants in clean sessions, several repeats each. Record the **rate** at which the brand is named and cited, not a single outcome | monthly |
| Accessibility | Are the agents that matter actually reaching the site | Server-log monitoring of crawler activity: request counts, status codes and paths per agent, verified against the operators' published address ranges rather than the user-agent header | weekly |
| Factual accuracy | Is the current version of each key fact the one that exists in the world | For each canonical fact, check that independent sources state the current value; alert when a superseded version resurfaces | monthly |
| Regression | Did the fixes hold | Re-run this audit on a schedule and diff the reports by `check_id`: resolved, new, regressed | monthly |

## The conditional fifth track

**Engagement pathway coverage** is added only when the input findings include at least
one from `engagement-audit`. This is a **structural** track, not a behavioural one: "did
the same sampled pages keep exposing an observable next step," re-checked by re-running
the engagement checks against the same sampled page set and diffing by `check_id`. It is
deliberately **not** "do people who arrive from an assistant stay" -- that would require
referrer segmentation, scroll depth, and exit-rate data this marketplace has no access to
and must not claim to measure. A behavioural engagement track of that kind is exactly the
sort of thing that belongs in the **deferred-capability** entries this skill emits
instead (see `references/checks.md`): a measurement *recommendation* for whoever
controls the site's actual analytics, not something this skill can produce or verify
itself.

## The caveat that must accompany the visibility track

Assistants personalise. They draw on conversation history, earlier questions, stated
preferences and location, so two people asking the same question can get different brands
and framing. A single prompt on a single day is not a measurement. Run clean sessions,
repeat each prompt, and report rates with the sample size attached. Treat a change of a
few percentage points on a small panel as noise. This caveat is emitted with every plan,
not only when the visibility track happens to be relevant.

## Why `check_id` matters here

The report carries a stable `check_id` on every finding alongside the sequential `id`
precisely so that consecutive audits can be diffed. Sequential ids shift as findings are
added or resolved; `check_id` does not. This skill's own `related_findings` field on
every opportunity uses `check_id` for the same reason: at the point this skill runs, no
finding has been assigned a sequential `id` yet (that happens later, in
`merge_findings.build_report`), so `check_id` is the only stable reference available.

## No invented baselines

Never emit a numeric baseline (`"baseline": "12%"` or similar) for any track. Where no
baseline exists -- which is always, since this skill has no access to historical
analytics -- the track describes what to start measuring and how, not a number to
compare against.
