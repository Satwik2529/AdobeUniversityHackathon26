# Authoring report.md

The JSON is the contract; the Markdown is what a non-expert reads. Assume a brand or
marketing lead who will forward it to an engineer.

## Structure

1. **What this is** — one paragraph, plus the read-only attestation: no changes were
   made to the site.
2. **Headline** — counts by severity and the single most important sentence: what is
   currently preventing this brand from being found, read, cited or kept.
3. **Do this first** — the top three actions, each with what to change, who does it,
   how much work it is, and how to check it worked.
4. **Findings** — grouped by funnel stage, in severity order. Each: what we observed
   (with the URL), why it matters mechanically, what to do.
5. **Worth doing anyway** — the opportunities, clearly marked as improvements rather
   than defects.
6. **How you will know it worked** — the measurement plan.
7. **What we did not assess** — the coverage limits, stated plainly.

## Tone rules

- Plain sentences. No jargon without a five-word gloss the first time.
- Never say a fix guarantees citations. Say what mechanism it improves.
- Quantify: "0 of 12 product pages" beats "structured data is missing".
- Every finding must be locatable: at least one URL the reader can open.
- If something was not assessed, say so in the same voice as the findings. Silence
  reads as a clean bill of health and would be dishonest.
