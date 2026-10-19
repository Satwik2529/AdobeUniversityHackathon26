#!/usr/bin/env python3
"""Turn evidence-backed findings into what a site owner should do next, and how they
will know it worked.

This is not a detector. It never emits findings, never re-derives final severity, and
never touches anything the entrypoint (`brand-ai-readiness-audit`) already owns
(`action_sequence` is built centrally from `findings` by `merge_findings.py`'s
`build_action_sequence`; this script does not produce it and must not attempt to).

Pure snapshot-and-findings consumer: this script makes no network requests of any kind,
no code path in it could, and calls no external API, search engine, or analytics
platform. `site-snapshot-collector` remains the only network-touching component in this
marketplace. This skill reasons entirely about evidence other components already
gathered.

Design rules, enforced here and not merely documented:

  * **No evidence, no opportunity.** Every opportunity names the exact check_ids and
    URLs/clusters it was derived from. An opportunity that cannot point at real findings
    is not emitted.
  * **Correlation is not causality.** Two related findings co-occurring is described in
    mechanism terms ("a shared template fix may address both"), never as a business
    outcome, a percentage, or a guarantee.
  * **A healthy site stays healthy.** No finding, or only informational findings, means
    no remediation opportunity is fabricated. Measurement and monitoring may still be
    offered, since they are useful regardless of current health.
  * **Existing severity math, not a new one.** `_derive_severity` below is a verbatim
    duplicate of `merge_findings.derive_severity`, kept in sync deliberately (mirroring
    the same "duplicate small shared logic rather than cross-import" convention already
    used by every detector in this marketplace) so opportunity prioritisation reasons
    about the *same* severity the final report will independently compute, without a
    second, competing scoring model.
  * **Non-duplication.** An opportunity restating a single check_id's own fix is
    padding; only findings that combine into something more than any one of them says
    alone become an opportunity.
"""
import argparse
import glob
import json
import os
import sys

DETECTOR = "opportunity-and-monitoring"

# ------------------------------------------------------------- severity (verbatim mirror)
# Kept identical to skills/brand-ai-readiness-audit/scripts/merge_findings.py's tables
# and derive_severity(), on purpose: see the module docstring.

SEVERITY_ORDER = ["info", "low", "medium", "high", "critical"]
BASE_BY_IMPACT = {"blocks": "critical", "degrades": "high", "weakens": "medium"}
SEVERITY_WEIGHT = {"critical": 5.0, "high": 3.0, "medium": 1.6, "low": 0.7, "info": 0.0}
REACH_WEIGHT = {"sitewide": 1.0, "template": 0.7, "page": 0.4}
GATE_BLOCKERS = {
    "ACC.ROBOTS_BLOCKS_ALL", "ACC.ROBOTS_BLOCKS_RETRIEVAL",
    "ACC.UA_BLOCKED", "ACC.NOINDEX_ON_CONTENT",
}


def _step(severity, delta):
    index = SEVERITY_ORDER.index(severity)
    return SEVERITY_ORDER[max(0, min(len(SEVERITY_ORDER) - 1, index + delta))]


def _cap(severity, ceiling):
    if SEVERITY_ORDER.index(severity) > SEVERITY_ORDER.index(ceiling):
        return ceiling
    return severity


def _derive_severity(finding):
    if finding.get("severity_override"):
        return finding["severity_override"]
    severity = BASE_BY_IMPACT.get(finding.get("gate_impact", "weakens"), "medium")
    reach = finding.get("reach", "template")
    if reach == "page":
        severity = _step(severity, -1)
    elif reach == "template" and severity == "critical":
        severity = _step(severity, -1)
    detail = finding.get("evidence_detail") or {}
    if finding.get("certainty") == "inferred":
        severity = _cap(severity, "high")
    if detail.get("nondeterministic"):
        severity = _cap(severity, "high")
    if detail.get("confidence") == "medium":
        severity = _cap(severity, "high")
    elif detail.get("confidence") == "low":
        severity = _cap(severity, "medium")
    ceiling = finding.get("severity_ceiling")
    if ceiling:
        severity = _cap(severity, ceiling)
    sample = detail.get("sample") or {}
    checked = sample.get("checked")
    origin_level = reach == "sitewide" and detail.get("confidence") == "high"
    if (isinstance(checked, int) and 0 < checked < 3
            and reach != "page" and not origin_level):
        severity = _cap(severity, "medium")
    return severity


def _score(finding):
    """A relative ranking score for prioritising opportunities, using the same
    severity/reach weighting the entrypoint uses for findings -- not a competing model,
    the same one, reused for a different purpose (ranking opportunities rather than
    findings)."""
    severity = _derive_severity(finding)
    return SEVERITY_WEIGHT.get(severity, 0.0) * REACH_WEIGHT.get(
        finding.get("reach", "template"), 0.5)


# --------------------------------------------------------------------------- taxonomy

CATEGORIES = (
    "access-remediation", "rendering-readability-remediation",
    "entity-schema-alignment", "answer-surface-improvement",
    "freshness-source-of-truth", "engagement-action-pathway",
    "cross-detector-template", "template-leverage", "measurement", "monitoring",
    "deferred-capability",
)

# Real site_archetype values this collector actually produces. "software" and
# "commerce" (mentioned in an earlier planning draft) are not among them; using the
# real values here, not the draft's, is a deliberate correction.
ARCHETYPES = frozenset({"ecommerce", "docs", "media", "local-business", "mixed",
                        "brochure", "unknown"})

MAX_OPPORTUNITIES = 8

# Cross-detector compound rules: (detector_a, detector_b) -> template. Order-independent
# (checked both ways). Each template's mechanism/actions are generic across the check
# pairs that can trigger it within that detector combination, since the underlying
# relationship -- not the exact check_id -- is what makes it a compound opportunity.
_COMPOUND_TEMPLATES = {
    frozenset({"crawl-access-audit", "render-readability-audit"}): {
        "category": "cross-detector-template",
        "title": "Treat access and render problems on the same template as one compound gate",
        "mechanism": "A page an agent cannot reach and a page it can reach but cannot "
                     "read are two different symptoms of the same outcome: the content "
                     "never reaches an answer. Fixing access without fixing render, or "
                     "the reverse, still leaves the gate shut.",
        "expected_effect": "Once both are addressed on the same template, the pages in "
                           "that cluster stop failing at either the accessible or the "
                           "readable gate.",
        "recommended_actions": [
            "Confirm both issues affect the same template cluster, not merely the same "
            "site.",
            "Sequence the access fix first, since a render fix cannot be verified by "
            "an agent that cannot reach the page at all.",
            "Re-run the audit against representative URLs from the cluster after both "
            "changes ship."],
    },
    frozenset({"structured-data-entity-audit", "answer-retrievability-audit"}): {
        "category": "entity-schema-alignment",
        "title": "Align machine-readable structured data with the visible canonical facts",
        "mechanism": "Structured data that is incomplete or invalid, alongside prose "
                     "that does not state the same facts plainly, leaves a machine with "
                     "no reliable source for this template's facts in either form.",
        "expected_effect": "A machine reading either the markup or the prose for this "
                           "template reaches the same, complete set of facts.",
        "recommended_actions": [
            "Generate the structured data and the visible fact statement from the same "
            "underlying field, so they cannot drift apart.",
            "Validate the structured data and re-check the visible text on the same "
            "representative pages together, not separately."],
    },
    frozenset({"answer-retrievability-audit", "engagement-audit"}): {
        "category": "engagement-action-pathway",
        "title": "Create a reusable answer-to-action pathway on this template",
        "mechanism": "A page whose core fact is reachable and quotable but that offers "
                     "no next step converts a successful answer into a dead end. The "
                     "two problems compound: the better the answer, the more visitors "
                     "arrive with nothing to do next.",
        "expected_effect": "A visitor who arrives at this template already holding the "
                           "answer has an observable next step from the same page.",
        "recommended_actions": [
            "Identify the single most relevant next step for this template's purpose "
            "(a related item, a contact or inquiry path).",
            "Add it as a real, in-content link with descriptive anchor text, not only "
            "in site-wide navigation."],
    },
    frozenset({"freshness-corroboration-audit", "structured-data-entity-audit"}): {
        "category": "freshness-source-of-truth",
        "title": "Establish one canonical entity/fact source and propagate it",
        "mechanism": "A fact contradicted across the site's own pages, alongside "
                     "structured data that does not agree with itself either, means "
                     "there is no single version of this fact a machine could trust "
                     "even if it wanted to.",
        "expected_effect": "Every surface stating this fact, structured or visible, "
                           "states the same current value.",
        "recommended_actions": [
            "Decide which value is current and correct.",
            "Update every surface named in the underlying findings to match it, and "
            "reference a single source (a stable @id, or one field) going forward "
            "rather than maintaining separate copies."],
    },
    frozenset({"freshness-corroboration-audit", "answer-retrievability-audit"}): {
        "category": "freshness-source-of-truth",
        "title": "Establish a canonical, maintained fact surface rather than patching pages",
        "mechanism": "Stale or conflicting facts alongside the absence of any single "
                     "page stating the brand's key facts plainly means there is no "
                     "anchor to correct toward -- fixing one page does not establish "
                     "which version is authoritative.",
        "expected_effect": "One page becomes the brand's own reference for its key "
                           "facts, dated and kept current, that other surfaces and "
                           "third parties can be corrected against.",
        "recommended_actions": [
            "Publish or designate one page stating the brand's key facts in complete, "
            "plainly worded sentences, with a current date signal.",
            "Link to it from the pages that currently restate those facts "
            "independently."],
    },
    frozenset({"crawl-access-audit", "answer-retrievability-audit"}): {
        "category": "access-remediation",
        "title": "Fix access before investing further in content optimisation",
        "mechanism": "Content-quality work on a template an agent cannot reliably "
                     "reach cannot pay off until access is fixed first; the two "
                     "findings are not equally urgent even though both affect the same "
                     "pages.",
        "expected_effect": "Once access is restored, the answerability work already "
                           "done on this template becomes reachable.",
        "recommended_actions": [
            "Treat the access finding as the prerequisite, not a parallel work item.",
            "Re-verify the access fix with an unauthenticated fetch before assuming "
            "the answerability improvements are now effective."],
    },
}


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def load_findings(patterns):
    findings = []
    seen_paths = set()
    for pattern in patterns:
        expanded = sorted(glob.glob(pattern))
        for path in (expanded if expanded else [pattern]):
            if path in seen_paths or not os.path.exists(path):
                continue
            seen_paths.add(path)
            try:
                payload = load_json(path)
            except (OSError, ValueError):
                continue
            items = payload if isinstance(payload, list) else payload.get("findings", [])
            for item in items:
                if isinstance(item, dict) and item.get("check_id"):
                    findings.append(item)
    return findings


def cluster_key(finding):
    urls = finding.get("affected_urls") or []
    return frozenset(urls)


def url_overlap(a, b):
    ua, ub = cluster_key(a), cluster_key(b)
    return bool(ua and ub and (ua & ub))


# --------------------------------------------------------------------------- synthesis

class Opportunity(object):
    _next_id = [1]

    def __init__(self, category, title, summary, description, rationale,
                related_findings, scope, mechanism, expected_effect,
                recommended_actions, verification, owner, effort, score,
                dependencies=None):
        self.data = {
            "id": None,  # assigned after sorting, for deterministic sequential ids
            "category": category,
            "title": title,
            "summary": summary,
            "description": description,
            "rationale": rationale,
            "related_findings": sorted(set(related_findings)),
            "scope": scope,
            "mechanism": mechanism,
            "expected_effect": expected_effect,
            "recommended_actions": list(recommended_actions),
            "verification": verification,
            "owner": owner,
            "effort": effort,
            "dependencies": list(dependencies or []),
        }
        self._score = score

    def key(self):
        """Identity for deduplication: same category + same related-finding set is the
        same opportunity, even if produced by a different rule."""
        return (self.data["category"], frozenset(self.data["related_findings"]))


def _detect_compounds(findings):
    by_detector = {}
    for f in findings:
        by_detector.setdefault(f.get("detector"), []).append(f)

    opportunities = []
    for pair, template in _COMPOUND_TEMPLATES.items():
        # sorted(), not list(): iterating a frozenset has no guaranteed order across
        # Python processes (hash randomization), which made this description's
        # wording nondeterministic between runs of the same input -- a genuine
        # determinism defect found during final-integration testing.
        detectors = sorted(pair)
        if len(detectors) != 2:
            continue
        left, right = by_detector.get(detectors[0], []), by_detector.get(detectors[1], [])
        if not left or not right:
            continue
        matched = [(a, b) for a in left for b in right if url_overlap(a, b)]
        if not matched:
            continue
        related = sorted({f["check_id"] for pair_ in matched for f in pair_})
        urls = sorted({u for pair_ in matched for f in pair_ for u in (f.get(
            "affected_urls") or [])})[:10]
        score = max(_score(f) for pair_ in matched for f in pair_)
        opportunities.append(Opportunity(
            category=template["category"],
            title=template["title"],
            summary=template["recommended_actions"][0],
            description="Findings from %s and %s co-occur on overlapping pages: %s." % (
                detectors[0], detectors[1], ", ".join(related)),
            rationale="Both detectors independently flagged overlapping pages (%s), "
                      "which is stronger evidence of a compound, template-level "
                      "problem than either finding alone." % ", ".join(urls[:3]),
            related_findings=related,
            scope="Observed across %d overlapping sampled page(s): %s%s" % (
                len(urls), ", ".join(urls[:3]), " (and more)" if len(urls) > 3 else ""),
            mechanism=template["mechanism"],
            expected_effect=template["expected_effect"],
            recommended_actions=template["recommended_actions"],
            verification="Re-run the audit against the URLs named in scope and confirm "
                         "none of %s fire again." % ", ".join(related),
            owner="mixed",
            effort="template-change",
            score=score,
        ))
    return opportunities


def _detect_template_leverage(findings, already_covered):
    """Findings (any detector mix) sharing a cluster whose overlap is not already
    explained by a compound opportunity above -- a single template affecting several
    distinct check_ids is itself worth surfacing as "one fix, many findings", even
    without a specific named cross-detector relationship."""
    by_cluster = {}
    for f in findings:
        urls = cluster_key(f)
        if not urls:
            continue
        by_cluster.setdefault(urls, []).append(f)

    opportunities = []
    for urls, members in by_cluster.items():
        check_ids = {f["check_id"] for f in members}
        if len(check_ids) < 2 or len(urls) < 2:
            continue
        if check_ids <= already_covered:
            continue
        detectors = sorted({f.get("detector") for f in members})
        score = max(_score(f) for f in members)
        opportunities.append(Opportunity(
            category="template-leverage",
            title="One template fix could address several findings together",
            summary="Confirm the shared template and fix it once rather than patching "
                    "each page separately.",
            description="%d distinct checks (%s) from %s all affect the same %d "
                       "sampled pages." % (len(check_ids), ", ".join(sorted(check_ids)),
                                          ", ".join(detectors), len(urls)),
            rationale="Findings affecting exactly the same page set are more likely to "
                      "share a root cause (one template) than to be independent.",
            related_findings=sorted(check_ids),
            scope="Observed across the sampled page set: %s" % ", ".join(
                sorted(urls)[:5]),
            mechanism="A single shared template, once identified, is usually a single "
                      "engineering change rather than several independent ones.",
            expected_effect="Fixing the shared template addresses every finding listed, "
                            "verifiable by re-checking the same sampled pages.",
            recommended_actions=[
                "Confirm the affected pages genuinely share one template or component.",
                "Fix the shared template once rather than patching each page "
                "separately."],
            verification="Re-check the listed pages and confirm none of the related "
                         "check_ids fire again.",
            owner="engineering",
            effort="template-change",
            score=score,
        ))
    return opportunities


_MONITORING_RULES = (
    ("FRC.INTRA_SITE_FACT_CONFLICT", "monitoring",
     "Monitor for the fact conflict recurring after correction",
     "A fact that has disagreed across the site's own pages once can drift apart "
     "again after being fixed, especially if the pages are maintained independently.",
     "Re-run this audit's freshness check on a schedule and alert if the same "
     "check_id fires again on the same or a related page set.",
     "monthly"),
    ("FRC.SUPERSEDED_CONTENT_LIVE", "monitoring",
     "Monitor for superseded content resurfacing",
     "An older version of a fact that was live once can resurface through a "
     "template revert, a cached build, or a new page copied from an old one.",
     "Re-run the freshness check on a schedule and alert if the older value is "
     "observed again anywhere in the sample.",
     "monthly"),
    ("SDE.ORG_IDENTITY_CONFLICT", "monitoring",
     "Monitor entity-identity properties for renewed drift",
     "The same stable identifier disagreeing across pages once suggests the "
     "properties are maintained in more than one place, which can drift again.",
     "Re-run the structured-data check on a schedule and alert if the same @id "
     "shows disagreeing properties again.",
     "quarterly"),
)


def _detect_monitoring(findings):
    present = {f["check_id"]: f for f in findings}
    opportunities = []
    for check_id, category, title, mechanism, how, cadence in _MONITORING_RULES:
        finding = present.get(check_id)
        if not finding:
            continue
        urls = (finding.get("affected_urls") or [])[:5]
        opportunities.append(Opportunity(
            category=category,
            title=title,
            summary=how,
            description="%s was observed in this audit; recommending a monitoring "
                       "cadence rather than treating a single re-check as sufficient."
                       % check_id,
            rationale="This class of issue has already occurred once, which is "
                      "evidence it can recur, not evidence it will.",
            related_findings=[check_id],
            scope="Tied to the finding observed on: %s" % ", ".join(urls),
            mechanism=mechanism,
            expected_effect="An early alert if the same condition recurs, rather than "
                            "discovering it at the next full audit.",
            recommended_actions=[how, "Set the cadence to %s unless the site's own "
                                     "publishing rhythm suggests otherwise." % cadence],
            verification="Confirm the monitoring check actually re-evaluates %s, not "
                         "a proxy for it." % check_id,
            owner="engineering",
            effort="config",
            score=_score(finding) * 0.6,  # monitoring ranks below active remediation
        ))
    return opportunities


_DEFERRED_CAPABILITIES = (
    ("Actual behavioural engagement (click-through, conversion, bounce, time on "
     "page)", "answer-retrievability-audit and engagement-audit reason from "
     "structural evidence only; no behavioural data exists in this snapshot.",
     "Track conversion or engagement from answer-bearing pages to the relevant "
     "action, segmented by referrer, after implementing any recommended action "
     "pathway.", "continuous"),
    ("External/off-site corroboration of key facts", "freshness-corroboration-audit "
     "is a pure snapshot consumer by explicit architectural rule; it cannot query "
     "external sources.", "Periodically check whether independent sources still "
     "state a superseded value for each canonical fact.", "monthly"),
    ("Actual AI referral traffic and citation frequency", "no assistant, search "
     "engine, or analytics platform is queried by this marketplace.",
     "Run a fixed panel of prompts across assistants in clean sessions, repeated, "
     "and record the rate at which the brand is named and cited.", "monthly"),
)


def _deferred_capability_opportunities():
    return [Opportunity(
        category="deferred-capability",
        title="Deferred: %s" % name,
        summary=how,
        description=why,
        rationale="This is a capability gap in what can be measured from a snapshot, "
                  "not a defect found on the site.",
        related_findings=[],
        scope="Sitewide, not tied to a specific sampled page",
        mechanism="Without this data, the audit can recommend but cannot confirm "
                  "outcome, only mechanism.",
        expected_effect="Establishes a baseline for a capability this audit cannot "
                        "measure directly.",
        recommended_actions=[how],
        verification="Not applicable: this is a measurement gap, not a fix to verify.",
        owner="mixed",
        effort="platform-change",
        score=0.1,
    ) for name, why, how, _cadence in _DEFERRED_CAPABILITIES]


def _build_measurement_plan(findings, snapshot):
    tracks = [
        {"track": "Visibility", "what": "Whether the brand is named, and cited, in "
                                        "assistant answers to category, brand-direct, "
                                        "comparison and long-tail questions",
         "how": "A fixed panel of 30 to 50 prompts, run across several assistants in "
               "clean sessions, several repeats each; record the rate the brand is "
               "named and cited, not a single outcome",
         "cadence": "monthly"},
        {"track": "Accessibility", "what": "Whether the agents that matter are "
                                          "actually reaching the site",
         "how": "Server-log monitoring of crawler activity (request counts, status "
               "codes and paths per agent), verified against each operator's "
               "published address ranges rather than the user-agent header alone",
         "cadence": "weekly"},
        {"track": "Factual accuracy", "what": "Whether the current version of each "
                                             "canonical fact is the one that exists "
                                             "in the world",
         "how": "For each canonical fact, check independent sources state the "
               "current value; alert when a superseded version resurfaces",
         "cadence": "monthly"},
        {"track": "Regression", "what": "Whether the fixes from this audit held",
         "how": "Re-run this audit on a schedule and diff the reports by check_id: "
               "resolved, new, regressed",
         "cadence": "monthly"},
    ]
    if any(f.get("detector") == "engagement-audit" for f in findings):
        tracks.append({
            "track": "Engagement pathway coverage",
            "what": "Whether representative high-value pages continue to expose an "
                   "observable next step",
            "how": "Re-run the engagement check on a schedule against the same "
                  "sampled page set and diff by check_id",
            "cadence": "monthly"})
    return {
        "tracks": tracks,
        "caveat": "Assistants personalise: two people asking the same question can "
                 "get different brands and framing. A single prompt on a single day "
                 "is not a measurement. Run clean sessions, repeat each prompt, and "
                 "report rates with the sample size attached. The report carries a "
                 "stable check_id on every finding precisely so consecutive audits "
                 "can be diffed; the sequential id shifts as findings are added or "
                 "resolved, check_id does not.",
    }


def select_opportunities(snapshot, findings):
    archetype = snapshot.get("site_archetype")
    if archetype not in ARCHETYPES:
        archetype = "unknown"

    candidates = []
    candidates.extend(_detect_compounds(findings))

    already_covered = set()
    for opp in candidates:
        already_covered |= set(opp.data["related_findings"])
    candidates.extend(_detect_template_leverage(findings, already_covered))
    candidates.extend(_detect_monitoring(findings))

    # Non-duplication gate: an opportunity whose entire related-finding set is a
    # single check_id restates that finding's own fix and adds nothing; only
    # multi-finding or genuinely synthesised opportunities survive.
    candidates = [o for o in candidates if len(o.data["related_findings"]) != 1
                 or o.data["category"] == "monitoring"]

    # Deterministic dedup: same (category, related_findings) key collapses to one,
    # keeping the highest-scored instance.
    by_key = {}
    for opp in candidates:
        existing = by_key.get(opp.key())
        if not existing or opp._score > existing._score:
            by_key[opp.key()] = opp
    candidates = list(by_key.values())

    # Deterministic ordering, then cap. Ties broken by title so output order never
    # depends on dict/set iteration order. The cap is total, matching the entrypoint's
    # own SKILL.md ("it returns at most 8 opportunities") -- deferred-capability items
    # compete for the same slots, deliberately: their low, fixed score means they only
    # displace a genuine remediation opportunity when fewer than a handful of those
    # exist, which is exactly the case (a clean or near-clean site) where surfacing
    # them is most useful and least likely to crowd out active work.
    deferred = _deferred_capability_opportunities()
    candidates = candidates + deferred
    candidates.sort(key=lambda o: (-o._score, o.data["title"]))
    all_opportunities = candidates[:MAX_OPPORTUNITIES]

    for index, opp in enumerate(all_opportunities, start=1):
        opp.data["id"] = "OPP-%03d" % index

    measurement_plan = _build_measurement_plan(findings, snapshot)
    return [o.data for o in all_opportunities], measurement_plan


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Synthesise opportunities and a measurement plan from an audit "
                    "snapshot and its detector findings.",
        epilog="Example: select_opportunities.py --snapshot snapshot.json "
              "--findings audit-output/findings-*.json --out opportunities.json")
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--findings", nargs="+", required=True,
                        help="detector findings files; globs are expanded")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    try:
        snapshot = load_json(args.snapshot)
    except (OSError, ValueError) as exc:
        sys.stderr.write("Error: cannot read snapshot: %s\n" % exc)
        return 3

    findings = load_findings(args.findings)
    opportunities, measurement_plan = select_opportunities(snapshot, findings)

    directory = os.path.dirname(os.path.abspath(args.out))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump({"opportunities": opportunities, "measurement_plan": measurement_plan},
                  handle, indent=2)
        handle.write("\n")

    sys.stderr.write("%s: %d opportunities, measurement plan with %d tracks -> %s\n"
                     % (DETECTOR, len(opportunities),
                        len(measurement_plan.get("tracks", [])), args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
