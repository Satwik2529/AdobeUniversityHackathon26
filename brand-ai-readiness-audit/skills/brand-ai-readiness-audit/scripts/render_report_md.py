#!/usr/bin/env python3
"""Render report.json as plain-English Markdown a non-expert can act on.

Usage:
  render_report_md.py --report report.json --out report.md

Exit codes: 0 ok, 2 bad arguments, 3 unreadable input.
"""
import argparse
import json
import sys

STAGE_LABEL = {
    "discovered": "Can a machine find it",
    "accessible": "Can a machine get in",
    "readable": "Can a machine read it",
    "understood": "Can a machine tell what it is",
    "retrieved": "Can a machine quote the specific fact",
    "selected": "Does the right version win",
    "engagement": "Does the visitor who arrives stay",
}
STAGE_ORDER = list(STAGE_LABEL.keys())
SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def line(out, text=""):
    out.append(text)


def render(report):
    out = []
    summary = report.get("summary", {})
    coverage = report.get("coverage", {})
    findings = report.get("findings", [])

    line(out, "# AI-readiness audit: %s" % report.get("site", "unknown site"))
    line(out)
    line(out, "Audited %s. This audit is read-only and recommend-only: **no changes were "
              "made to the site.** Everything below is advice for whoever owns it."
              % report.get("audited_at", ""))
    line(out)
    line(out, "It looks at two things. First, whether AI assistants can find, read, "
              "understand and quote this brand at all. Second, whether a person who "
              "arrives from one of those answers can find what they came for.")
    line(out)

    line(out, "## What we found")
    line(out)
    line(out, "| Severity | Count | What it means |")
    line(out, "| --- | --- | --- |")
    line(out, "| Critical | %d | Structurally blocks the brand from being found, read or cited |"
              % summary.get("critical", 0))
    line(out, "| High | %d | Badly degrades a key page type, or a key fact is contradicted |"
              % summary.get("high", 0))
    line(out, "| Medium | %d | Real degradation on part of the site |" % summary.get("medium", 0))
    line(out, "| Low | %d | Hygiene, small compounding effects |" % summary.get("low", 0))
    line(out, "| Info | %d | Deliberate configuration or context, not a defect |"
              % summary.get("info", 0))
    line(out)

    bands = report.get("action_sequence", [])
    top = []
    for band in bands:
        top.extend(band.get("actions", []))
    top = [a for a in top if a.get("priority") in ("critical", "high")][:3]
    if top:
        line(out, "## Do these first")
        line(out)
        for index, action in enumerate(top, start=1):
            line(out, "%d. **%s**" % (index, action.get("action", "")))
            line(out, "   Owner: %s. Effort: %s. (Finding %s)"
                      % (action.get("owner", "mixed"), action.get("effort", "unknown"),
                         action.get("finding_id", "")))
        line(out)

    line(out, "## Findings")
    line(out)
    if not findings:
        line(out, "No defects were detected in the checks that could be run. See "
                  "*What we did not assess* below before treating that as a clean bill of health.")
        line(out)
    else:
        grouped = {}
        for finding in findings:
            grouped.setdefault(finding.get("funnel_stage", "understood"), []).append(finding)
        for stage in STAGE_ORDER:
            group = grouped.get(stage)
            if not group:
                continue
            line(out, "### %s" % STAGE_LABEL[stage])
            line(out)
            for finding in sorted(group, key=lambda f: SEV_ORDER.get(f["severity"], 9)):
                action = finding.get("suggested_action", {})
                line(out, "#### %s — %s (%s)"
                          % (finding.get("id"), finding.get("title"),
                             finding.get("severity", "").upper()))
                line(out)
                line(out, "**What we observed.** %s" % finding.get("evidence", ""))
                line(out)
                if action.get("mechanism"):
                    line(out, "**Why it matters.** %s" % action["mechanism"])
                    line(out)
                line(out, "**What to do.** %s" % action.get("summary", ""))
                line(out)
                for step in action.get("how", []) or []:
                    line(out, "- %s" % step)
                if action.get("how"):
                    line(out)
                meta = "Priority: %s. Effort: %s. Owner: %s." % (
                    action.get("priority", "-"), action.get("effort", "-"),
                    action.get("owner", "-"))
                if action.get("verification"):
                    meta += " Check it worked: %s" % action["verification"]
                line(out, meta)
                line(out)
                urls = finding.get("affected_urls") or []
                if urls:
                    line(out, "Affected pages (sample): %s"
                              % ", ".join("`%s`" % u for u in urls[:5]))
                    line(out)

    opportunities = report.get("opportunities") or []
    if opportunities:
        line(out, "## Worth doing anyway")
        line(out)
        line(out, "These are not defects. They are improvements that would strengthen how "
                  "this brand is found, cited and experienced.")
        line(out)
        for opportunity in opportunities:
            line(out, "- **%s** — %s *(%s effort, %s; %s)*"
                      % (opportunity.get("title", ""), opportunity.get("summary", ""),
                         opportunity.get("effort", "unknown"), opportunity.get("owner", "mixed"),
                         opportunity.get("mechanism", "")))
        line(out)

    plan = report.get("measurement_plan") or {}
    if plan:
        line(out, "## How you will know it worked")
        line(out)
        for item in plan.get("tracks", []):
            line(out, "- **%s** (%s): %s" % (item.get("what", ""), item.get("cadence", ""),
                                             item.get("how", "")))
        line(out)
        if plan.get("caveat"):
            line(out, "%s" % plan["caveat"])
            line(out)

    line(out, "## What we did not assess")
    line(out)
    line(out, "Pages discovered: %s. Sampled: %s. Fetched: %s. Rendered in a browser: %s."
              % (coverage.get("pages_discovered", "?"), coverage.get("pages_sampled", "?"),
                 coverage.get("pages_fetched", "?"), coverage.get("pages_rendered", "?")))
    line(out)
    not_assessed = coverage.get("not_assessed") or []
    if not_assessed:
        for item in not_assessed:
            line(out, "- **%s** — %s" % (item.get("dimension", ""), item.get("reason", "")))
    else:
        line(out, "- Every check in the catalogue ran.")
    line(out)
    line(out, "A dimension listed here was **not** checked. It is not a pass.")
    line(out)
    line(out, "---")
    line(out)
    line(out, "*Technical measures such as structured data and server-side rendering improve "
              "whether a machine can reach, read, understand and quote this brand. They raise "
              "eligibility; no technique guarantees that an assistant will cite you.*")
    return "\n".join(out) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Render report.json as Markdown.")
    parser.add_argument("--report", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        with open(args.report, "r", encoding="utf-8") as handle:
            report = json.load(handle)
    except (OSError, ValueError) as exc:
        sys.stderr.write("Error: cannot read report: %s\n" % exc)
        return 3
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(render(report))
    sys.stderr.write("Wrote %s\n" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
