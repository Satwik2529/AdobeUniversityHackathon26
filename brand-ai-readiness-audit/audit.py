#!/usr/bin/env python3
"""Run a complete AI-readiness audit with one command.

    python3 audit.py https://example.com

This is a convenience runner, not a tenth skill and not a second entrypoint. It
executes exactly the sequence that `skills/brand-ai-readiness-audit/SKILL.md`
describes for an agent: collect one snapshot, run the six detectors against it,
synthesise opportunities, merge, validate, render. Every step is the same script an
agent would invoke; nothing here contains audit logic of its own, and removing this
file would not change what the marketplace can do.

Only step 1 touches the network. Everything after it reads the frozen snapshot.

Exit codes: 0 the audit completed, 1 the audit could not be completed, 2 bad arguments.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.join(ROOT, "skills")

COLLECTOR = ("site-snapshot-collector", "collect.py")

DETECTORS = [
    ("crawl-access-audit", "check_access.py", "access"),
    ("render-readability-audit", "check_render.py", "render"),
    ("structured-data-entity-audit", "check_schema_entity.py", "schema"),
    ("answer-retrievability-audit", "check_answerability.py", "answers"),
    ("freshness-corroboration-audit", "check_freshness.py", "freshness"),
    ("engagement-audit", "check_engagement.py", "engagement"),
]

SYNTHESIS = ("opportunity-and-monitoring", "select_opportunities.py")
ENTRY = "brand-ai-readiness-audit"

SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"]


def skill_script(skill, script):
    return os.path.join(SKILLS, skill, "scripts", script)


def run(argv, label, quiet):
    """Run one pipeline step. Returns (ok, stderr_text)."""
    started = time.time()
    proc = subprocess.run([sys.executable] + argv, capture_output=True, text=True)
    elapsed = time.time() - started
    if proc.returncode == 0:
        if not quiet:
            sys.stderr.write("  ok    %-12s %5.1fs\n" % (label, elapsed))
        return True, proc.stderr
    sys.stderr.write("  FAIL  %-12s %5.1fs\n" % (label, elapsed))
    tail = (proc.stderr or proc.stdout or "").strip().splitlines()
    for line in tail[-4:]:
        sys.stderr.write("        %s\n" % line)
    return False, proc.stderr


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Run a complete AI-readiness audit of a website with one command.",
        epilog="Example: python3 audit.py https://example.com --out ./my-audit")
    parser.add_argument("url", help="site URL or domain to audit")
    parser.add_argument("--out", default="audit-output",
                        help="directory for the snapshot, findings and report "
                             "(default: audit-output)")
    parser.add_argument("--render", choices=["auto", "on", "off"], default="auto",
                        help="run a headless browser to see JavaScript-rendered "
                             "content; auto uses one only if installed (default: auto)")
    parser.add_argument("--max-pages", type=int, default=None,
                        help="how many pages to sample (default 25, cap 40)")
    parser.add_argument("--time-budget", type=int, default=None,
                        help="seconds allowed for fetching (default 150)")
    parser.add_argument("--user-agent-contact", default=None,
                        help="contact string added to the audit user agent; polite "
                             "to set when auditing a site you do not own")
    parser.add_argument("--keep-going", action="store_true",
                        help="continue if a single detector fails, instead of "
                             "stopping; the report records what was not assessed")
    parser.add_argument("--quiet", action="store_true", help="only print the summary")
    args = parser.parse_args(argv)

    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    snapshot = os.path.join(out, "snapshot.json")
    report_json = os.path.join(out, "report.json")
    report_md = os.path.join(out, "report.md")
    opportunities = os.path.join(out, "opportunities.json")

    started = time.time()
    if not args.quiet:
        sys.stderr.write("\nAuditing %s\n" % args.url)
        sys.stderr.write("Output   %s\n\n" % out)
        sys.stderr.write("1. collecting a snapshot (the only step that goes online)\n")

    collect_argv = [skill_script(*COLLECTOR), "--url", args.url,
                    "--out", snapshot, "--render", args.render]
    if args.max_pages:
        collect_argv += ["--max-pages", str(args.max_pages)]
    if args.time_budget:
        collect_argv += ["--time-budget", str(args.time_budget)]
    if args.user_agent_contact:
        collect_argv += ["--user-agent-contact", args.user_agent_contact]

    ok, _ = run(collect_argv, "collect", args.quiet)
    if not ok:
        sys.stderr.write("\nThe site could not be captured, so there is nothing to "
                         "audit. Common causes: the host is unreachable, the URL is "
                         "wrong, or an egress proxy is blocking the request.\n")
        return 1

    try:
        snap = json.load(open(snapshot, encoding="utf-8"))
    except (OSError, ValueError) as exc:
        sys.stderr.write("\nThe snapshot could not be read: %s\n" % exc)
        return 1

    fetched = snap.get("coverage", {}).get("pages_fetched", 0)
    sampled = snap.get("coverage", {}).get("pages_sampled", 0)
    if not fetched:
        sys.stderr.write("\nNo page could be fetched (%d sampled, 0 retrieved). This "
                         "is itself a finding worth knowing: robots.txt may be "
                         "blocking the audit agent, or the host may be refusing it. "
                         "Inspect %s.\n" % (sampled, snapshot))
        return 1

    if not args.quiet:
        sys.stderr.write("\n2. running the six detectors against that one snapshot\n")

    finding_files, failed = [], []
    for skill, script, label in DETECTORS:
        path = os.path.join(out, "findings-%s.json" % skill)
        ok, _ = run([skill_script(skill, script), "--snapshot", snapshot,
                     "--out", path], label, args.quiet)
        if ok:
            finding_files.append(path)
        else:
            failed.append(skill)
            if not args.keep_going:
                sys.stderr.write("\nStopping because %s failed. Re-run with "
                                 "--keep-going to produce a partial report "
                                 "instead.\n" % skill)
                return 1

    if not finding_files:
        sys.stderr.write("\nEvery detector failed; no report can be produced.\n")
        return 1

    if not args.quiet:
        sys.stderr.write("\n3. synthesising opportunities and the measurement plan\n")
    ok, _ = run([skill_script(*SYNTHESIS), "--snapshot", snapshot,
                 "--findings"] + finding_files + ["--out", opportunities],
                "opportunities", args.quiet)
    opp_arg = ["--opportunities", opportunities] if ok else []

    if not args.quiet:
        sys.stderr.write("\n4. merging, validating and rendering the report\n")
    ok, _ = run([skill_script(ENTRY, "merge_findings.py"), "--snapshot", snapshot,
                 "--findings"] + finding_files + opp_arg +
                ["--out", report_json, "--duration", "%.1f" % (time.time() - started)],
                "merge", args.quiet)
    if not ok:
        return 1

    valid, _ = run([skill_script(ENTRY, "validate_report.py"), "--report", report_json,
                    "--quiet"], "validate", args.quiet)
    run([skill_script(ENTRY, "render_report_md.py"), "--report", report_json,
         "--out", report_md], "render", args.quiet)

    # ------------------------------------------------------------------ summary
    report = json.load(open(report_json, encoding="utf-8"))
    summary = report.get("summary", {})
    total = summary.get("total_findings", 0)

    print("")
    print("=" * 62)
    print("  AI-readiness audit: %s" % report.get("site", args.url))
    print("=" * 62)
    print("  pages sampled %-4s fetched %-4s rendered %s"
          % (sampled, fetched, snap.get("coverage", {}).get("pages_rendered", 0)))
    print("  runtime %.1fs   requests %s"
          % (time.time() - started, snap.get("coverage", {}).get("requests_made", "?")))
    print("")
    if total:
        parts = ["%s %s" % (summary.get(s, 0), s) for s in SEVERITY_ORDER
                 if summary.get(s)]
        print("  %d findings: %s" % (total, ", ".join(parts)))
        print("")
        for band in report.get("action_sequence", []):
            if band["actions"]:
                print("  %s" % band["band"])
                for action in band["actions"][:5]:
                    print("    - [%s] %s" % (action["check_id"], action["action"]))
                if len(band["actions"]) > 5:
                    print("    ... and %d more" % (len(band["actions"]) - 5))
    else:
        print("  No findings. Every check that could be assessed came back clean.")
        print("  That is a real result, not an empty run -- see the report's coverage")
        print("  section for what was checked and what could not be assessed.")

    opps = report.get("opportunities", [])
    if opps:
        print("")
        print("  %d opportunities beyond the defects found:" % len(opps))
        for o in opps[:3]:
            print("    - %s" % o.get("title", ""))
        if len(opps) > 3:
            print("    ... and %d more" % (len(opps) - 3))

    if failed:
        print("")
        print("  Not assessed: %s failed to run, so those checks are missing from"
              % ", ".join(failed))
        print("  this report. It is a partial audit, not a clean bill of health.")

    print("")
    print("  schema valid: %s" % ("yes" if valid else "NO -- inspect report.json"))
    print("  read:  %s" % report_md)
    print("  data:  %s" % report_json)
    print("=" * 62)
    print("")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.stderr.write("\nInterrupted.\n")
        sys.exit(1)
