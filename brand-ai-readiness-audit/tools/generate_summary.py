#!/usr/bin/env python3
"""Write a short, human-readable SUMMARY.md next to an audit's report.json.

Reads only report.json (never modifies it or any other audit output) and
writes a 5-6 line summary — severity breakdown, coverage, opportunity count —
into the same output directory. Not part of audit.py's own pipeline; run it
as a second step after an audit so the summary reflects that run's data.

Usage:
  python3 tools/generate_summary.py               # reads/writes audit-output/
  python3 tools/generate_summary.py --out DIR      # same DIR you passed to audit.py

Exit codes:
  0  summary written
  1  report.json missing or unreadable
  2  bad arguments
"""
import argparse
import json
import sys
from pathlib import Path


def build_summary(report: dict) -> str:
    site = report.get("site", "(unknown site)")
    audited_at = report.get("audited_at", "(unknown date)")
    summary = report.get("summary", {})
    coverage = report.get("coverage", {})
    opportunities = report.get("opportunities", [])
    action_sequence = report.get("action_sequence", [])

    total = summary.get("total_findings", 0)
    critical = summary.get("critical", 0)
    high = summary.get("high", 0)
    medium = summary.get("medium", 0)
    low = summary.get("low", 0)
    info = summary.get("info", 0)

    discovered = coverage.get("pages_discovered", 0)
    sampled = coverage.get("pages_sampled", 0)
    fetched = coverage.get("pages_fetched", 0)
    failures = coverage.get("fetch_failures", 0)
    blocked = coverage.get("blocked_by_robots", 0)

    if critical or high:
        headline = (
            "Structural problems were found that can block or degrade AI "
            "discoverability — see the priority fixes in report.md first."
        )
    elif total:
        headline = (
            "No structural blockers — the issues found are hygiene-level, "
            "not defects that hide the brand from AI assistants."
        )
    else:
        headline = "No findings above info — a clean result."

    return f"""# Audit Summary — {site}

Audited {audited_at}. Sampled {sampled} of {discovered} discovered pages ({fetched} fetched, {failures} failed, {blocked} blocked by robots.txt).

**{total} findings total: {critical} critical, {high} high, {medium} medium, {low} low, {info} info.** {headline}

**{len(opportunities)} opportunities identified, {len(action_sequence)} prioritized as an action sequence** — see `report.md` (human-readable) or `report.json` (full data) for details, one fix at a time, cited to the exact page and observed value.

No changes were made to the live site — this audit is read-only and recommend-only.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="audit-output", help="audit output directory (same one passed to audit.py)")
    args = parser.parse_args()

    out_dir = Path(args.out)
    report_path = out_dir / "report.json"
    if not report_path.exists():
        print(f"error: {report_path} not found — run audit.py first", file=sys.stderr)
        return 1

    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: could not read {report_path}: {exc}", file=sys.stderr)
        return 1

    summary_path = out_dir / "SUMMARY.md"
    summary_path.write_text(build_summary(report), encoding="utf-8")
    print(f"wrote {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
