#!/usr/bin/env python3
"""Merge detector findings into one audit report.

This is the only place severity normalisation, deduplication, cross-skill correlation
and prioritisation happen. Detectors propose; the entrypoint decides.

Input finding contract (what every detector emits):
  {
    "check_id":        "RND.CSR_SHELL",           # stable across runs
    "title":           "short human title",
    "gate_impact":     "blocks" | "degrades" | "weakens",
    "reach":           "sitewide" | "template" | "page",
    "certainty":       "measured" | "inferred",
    "funnel_stage":    "discovered|accessible|readable|understood|retrieved|selected|engagement",
    "detector":        "render-readability-audit",
    "evidence":        "one to three sentences a non-expert can verify",
    "evidence_detail": {...},                      # see references/../evidence contract
    "affected_urls":   ["https://..."],
    "suggested_action":{"summary","how","mechanism","effort","owner","verification"},
    "severity_override": "info",                   # optional, for deliberate-policy notes
    "severity_ceiling":  "low"                     # optional, caps the derived severity
  }

A detector may emit either a bare JSON array of findings, or an object of the form
  {"detector": "...", "findings": [...], "not_assessed": [{"dimension", "reason"}]}
The not_assessed entries are folded into the report's coverage block.

Usage:
  merge_findings.py --snapshot snapshot.json --findings f1.json f2.json \
                    [--opportunities opps.json] --out report.json

Exit codes: 0 ok, 2 bad arguments, 3 unreadable input.
"""
import argparse
import datetime
import glob
import json
import os
import sys

SEVERITY_ORDER = ["info", "low", "medium", "high", "critical"]

BASE_BY_IMPACT = {"blocks": "critical", "degrades": "high", "weakens": "medium"}

# Earlier gates are fixed first: a later fix cannot help while an earlier gate is shut.
FUNNEL_PRECEDENCE = {
    "discovered": 0,
    "accessible": 1,
    "readable": 2,
    "understood": 3,
    "retrieved": 4,
    "selected": 5,
    "engagement": 6,
}

EFFORT_WEIGHT = {"trivial": 1.0, "config": 0.9, "template-change": 0.6, "platform-change": 0.35}
REACH_WEIGHT = {"sitewide": 1.0, "template": 0.7, "page": 0.4}
SEVERITY_WEIGHT = {"critical": 5.0, "high": 3.0, "medium": 1.6, "low": 0.7, "info": 0.0}

# A shut gate at these checks makes everything downstream moot until it is opened.
GATE_BLOCKERS = {
    "ACC.ROBOTS_BLOCKS_ALL",
    "ACC.ROBOTS_BLOCKS_RETRIEVAL",
    "ACC.UA_BLOCKED",
    "ACC.NOINDEX_ON_CONTENT",
}

# When two detectors describe the same condition on the same URL set, the first entry
# is authoritative and the second becomes a related_check rather than a second finding.
DUPLICATE_OWNERSHIP = [
    # Inert by design, kept deliberately: RND.CONTENT_BEHIND_INTERACTION is documented
    # as permanently not_assessed (this marketplace's collector never clicks), so it is
    # never emitted and this rule never fires today. It records the intended ownership
    # if that capability ever becomes assessable, and costs nothing meanwhile.
    ("RND.CONTENT_BEHIND_INTERACTION", "ANS.SPECS_NOT_EXTRACTABLE"),
    # Live: both sides are emitted by their detectors today.
    ("FRC.NO_CANONICAL_FACT_SURFACE", "ANS.NO_CANONICAL_FACT_SURFACE"),
]
# Removed during final adversarial review: three rows whose subordinate check_ids
# (ENG.NO_HEADING_ANCHORS, ENG.MISSING_ALT_ON_INFORMATIONAL_IMAGES,
# ENG.DEEPLINK_LANDING_MISMATCH) came from engagement-audit's superseded "arriving
# visitor" model. Milestone K redefined that skill's scope and none of the three was
# ever implemented, so the rows could never fire and only served to make the
# deduplication table look larger than it is. The conditions themselves remain owned,
# unambiguously and solely, by ANS.NO_HEADING_ANCHORS, RND.FACTS_IN_IMAGES and
# ACC.DEEPLINK_TO_HOME_REDIRECT respectively.

# Two independent detectors seeing contradictory machine-readable versions of one fact
# is worse than either alone.
ESCALATION_PAIRS = [("SDE.SCHEMA_VISIBLE_MISMATCH", "FRC.INTRA_SITE_FACT_CONFLICT")]


def _step(severity, delta):
    index = SEVERITY_ORDER.index(severity)
    return SEVERITY_ORDER[max(0, min(len(SEVERITY_ORDER) - 1, index + delta))]


def _cap(severity, ceiling):
    if SEVERITY_ORDER.index(severity) > SEVERITY_ORDER.index(ceiling):
        return ceiling
    return severity


def derive_severity(finding):
    """severity = f(gate_impact, reach, certainty), then anti-overclaim caps."""
    if finding.get("severity_override"):
        return finding["severity_override"], ["explicit override by detector"]

    notes = []
    severity = BASE_BY_IMPACT.get(finding.get("gate_impact", "weakens"), "medium")

    reach = finding.get("reach", "template")
    if reach == "page":
        severity = _step(severity, -1)
        notes.append("single page, lowered one level")
    elif reach == "template" and severity == "critical":
        severity = _step(severity, -1)
        notes.append("one template rather than sitewide, lowered one level")

    detail = finding.get("evidence_detail") or {}

    if finding.get("certainty") == "inferred":
        capped = _cap(severity, "high")
        if capped != severity:
            notes.append("inferred rather than measured, capped at high")
        severity = capped

    if detail.get("nondeterministic"):
        capped = _cap(severity, "high")
        if capped != severity:
            notes.append("nondeterministic evidence, capped at high")
        severity = capped

    if detail.get("confidence") == "medium":
        capped = _cap(severity, "high")
        if capped != severity:
            notes.append("medium confidence, capped at high")
        severity = capped
    elif detail.get("confidence") == "low":
        capped = _cap(severity, "medium")
        if capped != severity:
            notes.append("low confidence, capped at medium")
        severity = capped

    ceiling = finding.get("severity_ceiling")
    if ceiling:
        capped = _cap(severity, ceiling)
        if capped != severity:
            notes.append("detector capped this check at %s" % ceiling)
        severity = capped

    # The small-sample cap exists to stop a *template* claim resting on one or two
    # pages: "this template is broken" needs more than a single example.
    #
    # It must not apply to a sitewide condition observed at the origin level. When a
    # site refuses every non-browser agent, or robots disallows everything, exactly one
    # page is reachable *because of the defect itself*. Capping there would punish the
    # detector for correctly finding the thing that shrank the sample, and would hide
    # the most severe class of failure behind a medium.
    sample = detail.get("sample") or {}
    checked = sample.get("checked")
    origin_level = reach == "sitewide" and detail.get("confidence") == "high"
    if (isinstance(checked, int) and 0 < checked < 3
            and reach != "page" and not origin_level):
        capped = _cap(severity, "medium")
        if capped != severity:
            notes.append("sample below the template threshold, capped at medium")
        severity = capped

    return severity, notes


def _url_key(finding):
    return frozenset((finding.get("affected_urls") or [])[:20])


def deduplicate(findings):
    """Apply duplicate-ownership rules. Returns (kept, suppressed_count)."""
    by_check = {}
    for finding in findings:
        by_check.setdefault(finding["check_id"], []).append(finding)

    suppressed = set()
    for authoritative, subordinate in DUPLICATE_OWNERSHIP:
        if authoritative not in by_check or subordinate not in by_check:
            continue
        for sub in by_check[subordinate]:
            for auth in by_check[authoritative]:
                if _url_key(sub) & _url_key(auth) or not _url_key(sub):
                    auth.setdefault("related_checks", [])
                    if subordinate not in auth["related_checks"]:
                        auth["related_checks"].append(subordinate)
                    suppressed.add(id(sub))
                    break

    kept = [f for f in findings if id(f) not in suppressed]
    return kept, len(suppressed)


def escalate(findings):
    present = {f["check_id"] for f in findings}
    for left, right in ESCALATION_PAIRS:
        if left in present and right in present:
            for finding in findings:
                if finding["check_id"] in (left, right):
                    finding["severity"] = "critical"
                    finding.setdefault("severity_notes", []).append(
                        "escalated: %s and %s co-occur, so the site publishes two "
                        "contradictory machine-readable versions of one fact" % (left, right)
                    )
    return findings


def priority_of(finding, gate_shut):
    if finding["severity"] == "info":
        return "info", 0.0
    action = finding.get("suggested_action") or {}
    score = (
        SEVERITY_WEIGHT.get(finding["severity"], 1.0)
        * REACH_WEIGHT.get(finding.get("reach", "template"), 0.7)
        * EFFORT_WEIGHT.get(action.get("effort", "template-change"), 0.6)
    )
    # Funnel precedence: earlier gates score higher.
    stage = FUNNEL_PRECEDENCE.get(finding.get("funnel_stage", "understood"), 3)
    score *= 1.0 + (len(FUNNEL_PRECEDENCE) - stage) * 0.12

    # Funnel suppression: while an access gate is shut, downstream work cannot pay off.
    if gate_shut and finding["check_id"] not in GATE_BLOCKERS:
        score *= 0.35
        finding.setdefault("severity_notes", []).append(
            "priority demoted: an access gate is currently shut, so this fix cannot "
            "take effect until that is opened"
        )

    if score >= 4.0:
        bucket = "critical"
    elif score >= 2.0:
        bucket = "high"
    elif score >= 0.8:
        bucket = "medium"
    else:
        bucket = "low"
    return bucket, round(score, 3)


def build_report(snapshot, findings, opportunities, measurement_plan, started_at, duration):
    for finding in findings:
        severity, notes = derive_severity(finding)
        finding["severity"] = severity
        if notes:
            finding.setdefault("severity_notes", []).extend(notes)

    findings, suppressed = deduplicate(findings)
    findings = escalate(findings)

    gate_shut = any(
        f["check_id"] in GATE_BLOCKERS and f["severity"] in ("critical", "high")
        for f in findings
    )

    for finding in findings:
        bucket, score = priority_of(finding, gate_shut)
        action = finding.setdefault("suggested_action", {})
        action["priority"] = bucket
        finding["_score"] = score

    findings.sort(
        key=lambda f: (
            -SEVERITY_WEIGHT.get(f["severity"], 0),
            FUNNEL_PRECEDENCE.get(f.get("funnel_stage", "understood"), 9),
            f["check_id"],
            sorted(f.get("affected_urls") or [""])[0],
        )
    )

    counts = {sev: 0 for sev in SEVERITY_ORDER}
    for index, finding in enumerate(findings, start=1):
        finding["id"] = "F-%03d" % index
        counts[finding["severity"]] += 1
        finding.pop("gate_impact", None)
        finding.pop("certainty", None)
        finding.pop("severity_override", None)
        finding.pop("severity_ceiling", None)
        finding.pop("_score", None)

    coverage = snapshot.get("coverage", {})
    bands = build_action_sequence(findings)

    return {
        "site": snapshot.get("site", ""),
        "audited_at": started_at,
        "summary": {
            "total_findings": len(findings),
            "critical": counts["critical"],
            "high": counts["high"],
            "medium": counts["medium"],
            "low": counts["low"],
            "info": counts["info"],
        },
        "audit": {
            "marketplace_version": "1.0.0",
            "entrypoint": "brand-ai-readiness-audit",
            "duration_seconds": duration,
            "phase_timings": snapshot.get("phase_timings", {}),
            "no_changes_made": True,
            "duplicate_findings_merged": suppressed,
        },
        "coverage": coverage,
        "findings": findings,
        "opportunities": opportunities,
        "measurement_plan": measurement_plan,
        "action_sequence": bands,
    }


def build_action_sequence(findings):
    bands = [
        {"band": "Unblock (do first)",
         "rationale": "These shut a gate. Nothing downstream can help until they are open.",
         "actions": []},
        {"band": "Make readable and quotable (next)",
         "rationale": "The content can be reached but a machine cannot read, understand or quote it.",
         "actions": []},
        {"band": "Keep them and keep it true (ongoing)",
         "rationale": "Hold the visitor who arrives, and keep the facts current everywhere.",
         "actions": []},
    ]
    for finding in findings:
        if finding["severity"] == "info":
            continue
        stage = finding.get("funnel_stage", "understood")
        if stage in ("discovered", "accessible"):
            index = 0
        elif stage in ("readable", "understood", "retrieved", "selected"):
            index = 1
        else:
            index = 2
        bands[index]["actions"].append({
            "finding_id": finding["id"],
            "check_id": finding["check_id"],
            "action": finding["suggested_action"].get("summary", ""),
            "priority": finding["suggested_action"].get("priority"),
            "effort": finding["suggested_action"].get("effort"),
            "owner": finding["suggested_action"].get("owner"),
        })
    return bands


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Merge detector findings into a single audit report.",
        epilog="Example: merge_findings.py --snapshot s.json --findings out/findings-*.json --out report.json",
    )
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--findings", nargs="+", required=True,
                        help="detector findings files; globs are expanded")
    parser.add_argument("--opportunities", help="opportunity-and-monitoring output")
    parser.add_argument("--out", required=True)
    parser.add_argument("--duration", type=float, default=0.0)
    args = parser.parse_args(argv)

    try:
        with open(args.snapshot, "r", encoding="utf-8") as handle:
            snapshot = json.load(handle)
    except (OSError, ValueError) as exc:
        sys.stderr.write("Error: cannot read snapshot: %s\n" % exc)
        return 3

    paths = []
    for pattern in args.findings:
        expanded = sorted(glob.glob(pattern))
        paths.extend(expanded if expanded else [pattern])

    findings = []
    detector_not_assessed = []
    for path in sorted(set(paths)):
        if not os.path.exists(path):
            sys.stderr.write("Warning: findings file not found, skipping: %s\n" % path)
            continue
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except ValueError as exc:
            sys.stderr.write("Error: cannot parse %s: %s\n" % (path, exc))
            return 3
        if isinstance(payload, list):
            findings.extend(payload)
        else:
            findings.extend(payload.get("findings", []))
            detector_not_assessed.extend(payload.get("not_assessed", []))

    opportunities, plan = [], {}
    if args.opportunities and os.path.exists(args.opportunities):
        with open(args.opportunities, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        opportunities = payload.get("opportunities", [])
        plan = payload.get("measurement_plan", {})

    started_at = snapshot.get("audited_at") or datetime.datetime.now(
        datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # A detector reporting that it could not assess something must reach the report.
    # Dropping it would turn a capability gap into apparent silence, which reads as a
    # clean bill of health.
    if detector_not_assessed:
        coverage = snapshot.setdefault("coverage", {})
        existing = coverage.setdefault("not_assessed", [])
        for item in detector_not_assessed:
            if not any(e.get("dimension") == item.get("dimension") for e in existing):
                existing.append(item)

    report = build_report(snapshot, findings, opportunities, plan, started_at, args.duration)

    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=False)
        handle.write("\n")

    sys.stderr.write("Merged %d findings into %s (%d duplicates folded)\n"
                     % (len(report["findings"]), args.out,
                        report["audit"]["duplicate_findings_merged"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
