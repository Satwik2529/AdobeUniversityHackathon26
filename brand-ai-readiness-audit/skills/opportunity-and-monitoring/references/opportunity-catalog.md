# Opportunity catalogue

**Scope note:** this document is a catalogue of opportunity *ideas*, organised by funnel
gate, for future extension of the rule set described authoritatively in
`references/checks.md`. The five rule families actually implemented today
(cross-detector compound, template leverage, monitoring, deferred-capability,
measurement plan) are archetype-agnostic by construction -- none of them currently vary
by site type. The ideas below are catalogued against the real, current
`site_archetype` values this marketplace's collector actually produces:
`ecommerce`, `docs`, `media`, `local-business`, `mixed`, `brochure`, `unknown`.
An earlier draft of this table used "commerce" and "software" as archetype names;
neither is a value the collector produces, and both have been corrected below.

Organised by funnel gate. Each entry carries the mechanism it improves.

| Gate | Opportunity | Mechanism | Archetypes |
| --- | --- | --- | --- |
| accessible | Make the crawler policy deliberate: state explicitly which agents may retrieve and which may train, rather than leaving it to a default | Prevents a future accidental loss of citation eligibility, and makes an implicit trade-off a decision | all |
| accessible | Segmented sitemaps with real modification dates | Freshness signalling and efficient recrawling of the templates that change | all with more than one template |
| readable | Server-render the fact set even where the rest of the interface stays client-side | The crawlers that assemble answers read raw HTML and do not run scripts | all |
| readable | Publish a text equivalent beside every fact-bearing image, specification sheet and document | A fact stated in readable text is extracted reliably; one locked in a non-textual form is missed | all |
| understood | One canonical organization entity with a stable identifier, and identity links whose target profiles carry the identical name, URL and description | Entity resolution: turns "probably this company" into "this company". Inconsistent profiles cause the confusion they were meant to prevent | all |
| understood | Validate structured data in the build pipeline | A single syntax error voids a block silently, with no visible page error | all |
| retrieved | A canonical facts surface: one dated page stating each key fact in a plain, self-contained sentence, designed to be copied verbatim | Gives every other surface, including third parties, one version to agree with | all |
| retrieved | Question-shaped headings with short self-contained answers, where the questions are real | A self-contained answer unit can be lifted and attributed; a narrative paragraph cannot | ecommerce, docs, media |
| retrieved | Brand-owned comparison surfaces for the comparisons buyers actually make | Comparative questions are asked constantly; a brand publishing none forfeits the surface entirely | ecommerce, local-business |
| retrieved | Stable heading anchors plus a lead summary on long pages | Lets an answer link to the exact section, which serves both the citation and the visitor who lands there | docs, media, ecommerce |
| selected | Fact propagation: update every surface the brand already controls to the current version, then watch for the old version resurfacing | An old version survives wherever it still lives; publishing a new page does not overwrite it | all |
| engagement | Deep-link-first information architecture: every fact has its own addressable URL with the answer above the fold | Meets a visitor who arrives mid-journey holding one specific question | all |
| engagement | Intent-preserving redirects that never drop a fragment or a non-tracking parameter | Preserves the question the visitor arrived with | all |
| engagement | Privacy-respecting continuity: prefill on-site search from the inbound fragment, surface related items for the section landed in | Two people asking the same question arrive primed differently; identical treatment discards that | all |
| all | The measurement plan | Without it, none of the above can be shown to have worked | all |

## Included with an explicit caveat

**A machine-readable index file at the site root**, sometimes proposed as a way to guide
assistants to a brand's best pages. Offer it as a **low-priority, low-cost experiment**,
never as a defect, and attach the caveat: adoption is low, no major assistant provider has
committed to consuming such a file at runtime, and the published studies have not found a
citation effect. Its clearest current value is for documentation consumed by coding tools.
Recommending it without that caveat would be mechanism-unsound; recommending it with the
caveat is honest and costs the reader nothing.
