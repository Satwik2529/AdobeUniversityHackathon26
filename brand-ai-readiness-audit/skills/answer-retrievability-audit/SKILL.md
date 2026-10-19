---
name: answer-retrievability-audit
description: Detect why a machine that can read and classify a page still cannot pull out and quote the one fact a question asks for. Checks whether product pages state their core fact in a self-contained sentence near the top, whether specifications are extractable as tables or lists with explicit units and currency rather than buried in prose or images, whether the body ever names the full entity instead of relying entirely on pronouns, whether long pages carry stable heading anchors and a lead summary, whether an FAQ-classified page's headings are actually phrased as questions, whether the site has any canonical, quotable statement of its key facts, and whether a core fact that exists on the page falls outside the extracted main-content region. Use this when a brand is indexed and readable yet still absent from AI answers, or when assistants paraphrase it vaguely instead of citing specifics. Read-only and recommend-only, consumes a snapshot, and makes no network requests.
license: Apache-2.0
compatibility: Requires Python 3.9 or newer. Consumes a snapshot from site-snapshot-collector. Every check is structural (position, word-set overlap, punctuation, digit patterns) rather than lexical, so all of them run on any language; none are gated behind a supported-language list.
allowed-tools: Bash Read
metadata:
  role: detector
  funnel_gates: retrieved, selected
  namespace: ANS
---

# Answer retrievability audit

Funnel gates: **retrieved**, **selected**. The page is readable and classified. Can a
machine find the specific fact, and is that fact in a shape worth quoting?

## The mechanism

An assistant assembling an answer picks sources it can reach, read, and quote a clear
fact from. Being indexed is not being quoted. A page whose central fact is implied,
scattered, unit-less or only inferable from a table image will lose to a page that states
it plainly in one sentence, even if the first page is more authoritative.

This is a distinct gate from structured data. Valid product markup and a readable price
sentence are independent: many sites have one without the other, and the fixes differ.
Markup is machine metadata; this gate is about the prose and its shape.

## Input and output

```bash
python3 scripts/check_answerability.py --snapshot audit-output/snapshot.json --out audit-output/findings-answer.json
```

## Procedure

1. Derive each product page's **core fact** from its own structured price -- never assume
   a topic from outside the page.
2. Measure **answer distance**: how far into the readable text the core fact is first
   stated, and whether the page's own h1 recurs as a nearby word-overlap match, not
   strictly in the same sentence. Skip pages below the short-page floor.
3. Check **specification extractability**: unit-bearing values stated only in prose, with
   no table or definition list anywhere on the page.
4. Check **entity naming** on product pages only: does the body ever restate the h1's full
   word set, or does it rely entirely on pronouns and a generic category word after the h1.
5. Check **anchors and a lead summary** on long pages.
6. Check whether a page already classified as FAQ content phrases its headings as
   questions.
7. Check whether the site has a **canonical fact surface** at all: one page stating the
   brand's key facts plainly, in text, in a form a third party could copy.
8. Check whether a core fact confirmed present in the full page text falls outside the
   extracted main-content region.
9. Route genuinely additive ideas, such as comparison content, to
   `opportunity-and-monitoring` rather than emitting them as defects.

Full catalogue and the patterns behind each check: `references/checks.md` and
`references/quotability-patterns.md`.

## Language neutrality

Every check in this catalogue is structural: character position, word-set overlap
(Unicode-aware, not English vocabulary), presence of a digit or punctuation pattern.
None of them require understanding what a sentence means, so none of them are gated
behind a supported-language list -- an earlier version incorrectly gated two of them
behind English-only support, which meant those checks could never run on non-English
content at all. **Never penalise a site for not being in English**, including by silently
skipping a check that would otherwise run on any script.

## Gotchas

- **Short pages are exempt.** A contact page does not need a summary block.
- **Prose is not a defect.** Only report specification extractability on page types that
  genuinely carry specifications, and only when the values exist elsewhere on the page in
  a non-extractable form.
- **A generic category word recurring is not the entity being named.** "Widget" recurring
  on every page of a widget-selling site does not mean any specific widget was actually
  named; the check requires the h1's complete, distinguishing word set.
- **Never require a non-product page to restate its own generic heading.** A FAQ, legal,
  contact or category page's h1 is a section label, not an entity.
- **Never recommend inventing question-and-answer content that does not reflect the
  page.** Marking up questions the page does not answer is misrepresentation.
- **Never claim a formatting change guarantees a citation.** It makes the fact quotable,
  which is a precondition, not a promise.
