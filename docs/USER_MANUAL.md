# User Manual

How to use the running dashboard. For installation and setup, see the
[root README](../README.md).

---

## 1. Start the application

```bash
cd frontend
npm run dev
```

Open **http://localhost:3000**.

## 2. Run an audit

Type a URL into the landing page and submit — you'll land on a live view of
the audit running (`Collecting a snapshot…`, then each detector in turn).

No live site handy, or want to skip the wait? Click **"Load a saved
report.json instead"** on the landing page and select
`brand-ai-readiness-audit/audit-output/report.json` (optionally its
`snapshot.json` too — Query Intelligence needs the snapshot to work).

## 3. Open the report

Once the audit finishes (or a saved report loads), you land on the report
dashboard. The left rail switches between **Overview**, **Crawl
Intelligence**, **Funnel**, **Findings**, **Opportunities**, **Knowledge
Graph**, **Recommendations**, and **Raw Report** — the audit's own findings,
each with a cited URL and observed value.

## 4. Open Query Intelligence

Below the tab list, click **Query Intelligence**. This is a separate page
from the audit report — it reads the same snapshot but reasons about
specific queries rather than site-wide findings.

If it says *"Query Intelligence is unavailable for this audit,"* the job has
no `snapshot.json` yet (wait for the audit to finish) or none was loaded
(reload with the snapshot file included).

## 5. Use a generated query

Click **Generate Queries**. The system builds a set of realistic queries
grounded in what it actually found on the site (its discovered products/
categories, their real attributes, audiences and use-cases) — not a fixed
template list. Each row shows a difficulty badge (`L1`–`L5`, roughly how
many requirements it combines) and a live score. Click **Test** on any row
to see the full breakdown.

## 6. Enter your own query

Scroll to **Test Your Own Query**, type a natural-language question (e.g.
*"Best laptop for CSE students under ₹60,000 with 16GB RAM"*), and click
**Test Query**.

## 7. Read the requirement analysis

The **Requirement Analysis** panel lists every requirement the system
understood from your query — entity, price, attributes, audience, use case,
qualifiers — each with a status chip (`Supported`, `Partially supported`,
`Not found`, `Contradicted`, `Not assessable`, or `Invalid for this
product`). Anything the system couldn't classify at all still shows up here
labeled "unrecognized" — it's never silently dropped.

## 8. Inspect evidence

Click any requirement row to expand it. You'll see the exact page URL, the
observed value, what field it came from, and a confidence score — the
citation the status was decided from. For price requirements you'll also
see selectivity (how much of the catalog the constraint actually filters)
and a realism flag if the threshold was unrealistically high or low.

## 9. Understand the score

The **"Why this score?"** panel shows five independent numbers — Coverage,
Answerability, Confidence, Query quality, Opportunity — plus the exact
point-by-point calculation and a Strong / Weak / Invalid-for-this-product /
Contradicted breakdown. There is no single hidden "the score," so a low
number is always traceable to a specific requirement.

## 10. Compare queries

Once you've tested two or more queries, the **Compare Tested Queries** panel
appears. Select any two and click **Compare** to see which specific
requirement explains the score difference between them.

## 11. Understand opportunities

Back on the overview, the **Highest-value opportunity** card (when one
exists) surfaces the generated query with the largest *genuine, actionable*
gap — not just the lowest score. A query that scored low only because it
asked about something irrelevant to the entity (an `INVALID_REQUIREMENT`)
is deliberately **not** treated as an opportunity, since there's nothing a
site owner could add to fix that.
