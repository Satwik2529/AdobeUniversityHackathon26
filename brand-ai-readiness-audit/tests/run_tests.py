#!/usr/bin/env python3
"""The marketplace test harness.

Layers, in the order they run:

  L5  marketplace and Agent Skills spec conformance (tools/validate_marketplace.py)
  L5b validator self-test (tests/test_validator.py) - a validator that never fails is
      not a validator
  L0  fixture integrity - every fixture builds, serves, and has an expectation manifest
  L1  unit tests, if any detector has shipped unit tests
  L2  fixture scoring - run the audit against each local fixture and score the findings
      against the expectation manifests, producing precision, recall and, most
      importantly, the false-positive count on the negative controls
  L3  determinism - the same fixture audited twice must produce identical findings
  L4  report schema conformance - every emitted report validates

Layers that need components not yet implemented report SKIPPED with the reason, and the
run still passes. They must all be green before packaging.

Usage:
  run_tests.py [--only L0,L2] [--fixture F00-clean-control] [--json]

Exit codes: 0 all executed layers passed, 1 a failure, 2 bad arguments.
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIXTURES = os.path.join(HERE, "fixtures")
EXPECTED = os.path.join(HERE, "expected")

sys.path.insert(0, HERE)
from fixture_server import FixtureServer  # noqa: E402

SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}

sys.path.insert(0, os.path.join(ROOT, "skills", "brand-ai-readiness-audit", "scripts"))
import merge_findings  # noqa: E402


def derived_severity(finding):
    """Severity as the entrypoint will actually compute it.

    Detectors emit severity *inputs*, not a severity. Scoring against a default
    would test the harness rather than the pipeline the judges will run.
    """
    severity, _notes = merge_findings.derive_severity(dict(finding))
    return severity

COLLECTOR = os.path.join(ROOT, "skills", "site-snapshot-collector", "scripts", "collect.py")
NAMESPACE_BY_SKILL = {
    "crawl-access-audit": "ACC",
    "render-readability-audit": "RND",
    "structured-data-entity-audit": "SDE",
    "answer-retrievability-audit": "ANS",
    "freshness-corroboration-audit": "FRC",
    "engagement-audit": "ENG",
}

DETECTORS = [
    ("crawl-access-audit", "check_access.py"),
    ("render-readability-audit", "check_render.py"),
    ("structured-data-entity-audit", "check_schema_entity.py"),
    ("answer-retrievability-audit", "check_answerability.py"),
    ("freshness-corroboration-audit", "check_freshness.py"),
    ("engagement-audit", "check_engagement.py"),
]


class Results(object):
    def __init__(self):
        self.layers = []

    def add(self, name, status, detail=""):
        self.layers.append({"layer": name, "status": status, "detail": detail})
        marker = {"PASS": "PASS   ", "FAIL": "FAIL   ", "SKIP": "SKIPPED"}[status]
        print("%s  %s%s" % (marker, name, ("  -  " + detail) if detail else ""))

    @property
    def failed(self):
        return any(layer["status"] == "FAIL" for layer in self.layers)


def detector_path(skill, script):
    return os.path.join(ROOT, "skills", skill, "scripts", script)


def available_detectors():
    return [(s, p) for s, p in DETECTORS if os.path.isfile(detector_path(s, p))]


# ---------------------------------------------------------------------------- L5, L5b

def layer_spec_conformance(results):
    proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, "tools", "validate_marketplace.py"),
         "--root", ROOT, "--json"],
        capture_output=True, text=True)
    try:
        payload = json.loads(proc.stdout)
    except ValueError:
        results.add("L5 spec conformance", "FAIL", "validator produced no JSON")
        return
    detail = "%d errors, %d warnings, %d skills, %d entrypoint" % (
        payload["error_count"], payload["warning_count"],
        payload["skills_checked"], payload["entrypoints"])
    results.add("L5 spec conformance", "PASS" if payload["error_count"] == 0 else "FAIL",
                detail)
    if payload["warning_count"]:
        for warning in payload["warnings"]:
            print("        warning: [%s] %s" % (warning["where"], warning["message"]))


def layer_catalogue_integrity(results):
    """No check_id may be referenced anywhere -- in a detector's related_checks, in the
    entrypoint's deduplication table, or in a fixture expectation -- unless some
    detector can actually emit it.

    Added during the final adversarial review, which found a real instance: a generated
    report cited ENG.DEEPLINK_LANDING_MISMATCH in related_checks, a check_id left over
    from engagement-audit's superseded scope that exists nowhere in the marketplace. A
    dangling reference is invisible to every other layer -- the report still validates,
    every unit test still passes -- so it needs its own structural guard.
    """
    import re
    emittable = set()
    for path in sorted(glob.glob(os.path.join(ROOT, "skills", "*", "scripts", "check_*.py"))):
        if os.path.basename(path).startswith("test_"):
            continue
        source = open(path, encoding="utf-8").read()
        # a check_id is emittable if it is passed as the first argument to finding(...)
        emittable |= set(re.findall(r'finding\(\s*\n?\s*"([A-Z]+\.[A-Z0-9_]+)"', source))

    problems = []

    # 1. related_checks hard-coded in detector sources
    for path in sorted(glob.glob(os.path.join(ROOT, "skills", "*", "scripts", "check_*.py"))):
        if os.path.basename(path).startswith("test_"):
            continue
        source = open(path, encoding="utf-8").read()
        for match in re.findall(r'related=\[([^\]]*)\]', source):
            for cid in re.findall(r'"([A-Z]+\.[A-Z0-9_]+)"', match):
                if cid not in emittable:
                    problems.append("%s hard-codes related_check %s, which no detector emits"
                                    % (os.path.basename(path), cid))

    # 2. the entrypoint's deduplication table
    sys.path.insert(0, os.path.join(ROOT, "skills", "brand-ai-readiness-audit", "scripts"))
    import merge_findings as mf
    for authoritative, subordinate in mf.DUPLICATE_OWNERSHIP:
        if subordinate not in emittable and authoritative not in emittable:
            problems.append("DUPLICATE_OWNERSHIP row (%s -> %s) references two check_ids "
                            "that no detector emits" % (authoritative, subordinate))
    for blocker in mf.GATE_BLOCKERS:
        if blocker not in emittable:
            problems.append("GATE_BLOCKERS lists %s, which no detector emits" % blocker)

    # 3. fixture expectations that REQUIRE a check no detector can produce
    for path in sorted(glob.glob(os.path.join(ROOT, "tests", "expected", "*.json"))):
        spec = json.load(open(path, encoding="utf-8"))
        for entry in spec.get("must_include", []):
            cid = entry["check_id"] if isinstance(entry, dict) else entry
            if cid not in emittable:
                problems.append("%s requires %s, which no detector emits"
                                % (os.path.basename(path), cid))

    results.add("L6 catalogue integrity", "FAIL" if problems else "PASS",
                "; ".join(problems) if problems
                else "%d emittable check_ids; no dangling references in detector "
                     "related_checks, the deduplication table, gate blockers, or "
                     "fixture expectations" % len(emittable))


def layer_validator_selftest(results):
    proc = subprocess.run([sys.executable, os.path.join(HERE, "test_validator.py")],
                          capture_output=True, text=True)
    last = [line for line in proc.stdout.strip().split("\n") if line.strip()][-1]
    results.add("L5b validator self-test", "PASS" if proc.returncode == 0 else "FAIL", last)


# ---------------------------------------------------------------------------------- L0

def layer_fixture_integrity(results, only_fixture=None):
    if not os.path.isdir(FIXTURES):
        results.add("L0 fixture integrity", "FAIL", "no fixtures; run make_fixtures.py")
        return []
    names = sorted(n for n in os.listdir(FIXTURES)
                   if os.path.isdir(os.path.join(FIXTURES, n)))
    if only_fixture:
        names = [n for n in names if n == only_fixture]
    problems, checked = [], 0
    for name in names:
        directory = os.path.join(FIXTURES, name)
        if not os.path.isfile(os.path.join(EXPECTED, name + ".json")):
            problems.append("%s: no expectation manifest" % name)
            continue
        try:
            with FixtureServer(directory) as server:
                for path in ("/robots.txt", "/"):
                    request = urllib.request.Request(
                        server.base_url + path,
                        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0)"})
                    with urllib.request.urlopen(request, timeout=5) as response:
                        if response.status != 200:
                            problems.append("%s: %s returned %d"
                                            % (name, path, response.status))
                checked += 1
        except (urllib.error.URLError, OSError) as exc:
            problems.append("%s: server error %s" % (name, exc))
    status = "FAIL" if problems else "PASS"
    results.add("L0 fixture integrity", status,
                "%d fixtures served and paired with expectations" % checked
                if not problems else "; ".join(problems[:4]))
    return names


# ---------------------------------------------------------------------------------- L1

def layer_unit_tests(results):
    unit_files = []
    # opportunity-and-monitoring is deliberately not in DETECTORS: its CLI takes
    # --findings (plural, required) rather than the shared --snapshot/--out contract
    # every detector uses, and it does not participate in L2 fixture scoring the same
    # way (it consumes findings, not a snapshot, to produce opportunities). Its own
    # unit tests still belong in the standard gauntlet, so it is added here directly
    # rather than folded into the shared DETECTORS list.
    for skill, _ in DETECTORS + [("site-snapshot-collector", ""),
                                 ("opportunity-and-monitoring", "")]:
        directory = os.path.join(ROOT, "skills", skill, "scripts")
        if os.path.isdir(directory):
            unit_files += [os.path.join(directory, f) for f in sorted(os.listdir(directory))
                           if f.startswith("test_") and f.endswith(".py")]
    if not unit_files:
        results.add("L1 unit tests", "SKIP", "no detector unit tests have shipped yet")
        return
    failures = []
    for path in unit_files:
        proc = subprocess.run([sys.executable, path], capture_output=True, text=True)
        if proc.returncode != 0:
            failures.append("%s: %s" % (os.path.basename(path),
                                        proc.stdout.strip().split("\n")[-1:]))
    results.add("L1 unit tests", "FAIL" if failures else "PASS",
                "; ".join(failures) if failures else "%d unit test files passed"
                % len(unit_files))


# ------------------------------------------------------------------------------ L2, L3

def run_audit(base_url, workdir):
    """Run the collector then every available detector. Returns (findings, coverage)."""
    os.makedirs(workdir, exist_ok=True)
    snapshot = os.path.join(workdir, "snapshot.json")
    proc = subprocess.run(
        [sys.executable, COLLECTOR, "--url", base_url, "--out", snapshot,
         "--max-pages", "25", "--render", "off"],
        capture_output=True, text=True, timeout=300)
    if proc.returncode != 0 or not os.path.isfile(snapshot):
        raise RuntimeError("collector failed: %s" % proc.stderr.strip()[:400])

    findings = []
    for skill, script in available_detectors():
        out = os.path.join(workdir, "findings-%s.json" % skill)
        detector = subprocess.run(
            [sys.executable, detector_path(skill, script), "--snapshot", snapshot,
             "--out", out], capture_output=True, text=True, timeout=180)
        if detector.returncode != 0:
            raise RuntimeError("%s failed: %s" % (skill, detector.stderr.strip()[:400]))
        with open(out, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        findings.extend(payload if isinstance(payload, list)
                        else payload.get("findings", []))

    with open(snapshot, "r", encoding="utf-8") as handle:
        coverage = json.load(handle).get("coverage", {})
    return findings, coverage


def shipped_namespaces():
    return {NAMESPACE_BY_SKILL[skill] for skill, _ in available_detectors()
            if skill in NAMESPACE_BY_SKILL}


def score_fixture(name, findings, namespaces=None):
    with open(os.path.join(EXPECTED, name + ".json"), "r", encoding="utf-8") as handle:
        spec = json.load(handle)

    fired = {}
    for finding in findings:
        check = finding.get("check_id", "?")
        severity = finding.get("severity") or derived_severity(finding)
        if check not in fired or SEVERITY_RANK.get(severity, 0) > SEVERITY_RANK.get(
                fired[check], 0):
            fired[check] = severity

    hits, misses, false_positives, pending = [], [], [], []
    namespaces = namespaces if namespaces is not None else shipped_namespaces()

    for requirement in spec.get("must_include", []):
        check = requirement["check_id"]
        # Only demand checks whose detector has shipped. Counting a check from an
        # unbuilt detector as a miss would make the score meaningless mid-build, and
        # counting it as a pass would be worse.
        if check.split(".")[0] not in namespaces:
            pending.append(check)
            continue
        if check not in fired:
            misses.append("%s not raised" % check)
            continue
        actual = SEVERITY_RANK.get(fired[check], 0)
        floor = SEVERITY_RANK.get(requirement.get("min_severity", "info"), 0)
        ceiling = SEVERITY_RANK.get(requirement.get("max_severity", "critical"), 4)
        if actual < floor:
            misses.append("%s raised at %s, below the required %s"
                          % (check, fired[check], requirement["min_severity"]))
        elif actual > ceiling:
            false_positives.append("%s over-escalated to %s, ceiling is %s"
                                   % (check, fired[check], requirement["max_severity"]))
        else:
            hits.append(check)

    required = {r["check_id"] for r in spec.get("must_include", [])}
    allowed = set(spec.get("allowed", []))
    forbidden = set(spec.get("must_not_include", []))
    ceiling = spec.get("forbid_any_above")

    for check, severity in sorted(fired.items()):
        if check in required:
            continue
        if check in forbidden:
            false_positives.append("%s must not fire here (fired at %s)" % (check, severity))
        elif ceiling and SEVERITY_RANK.get(severity, 0) > SEVERITY_RANK.get(ceiling, 0):
            false_positives.append("%s fired at %s on a negative control capped at %s"
                                   % (check, severity, ceiling))
        elif check not in allowed and not ceiling:
            false_positives.append("%s fired but was neither expected nor allowed" % check)

    return {"fixture": name, "hits": hits, "misses": misses, "pending": pending,
            "false_positives": false_positives,
            "negative_control": bool(spec.get("negative_control")),
            "fired": fired}


def layer_fixture_scoring(results, names, keep_dir=None):
    if not os.path.isfile(COLLECTOR):
        results.add("L2 fixture scoring", "SKIP",
                    "site-snapshot-collector/scripts/collect.py has not shipped yet")
        return None
    detectors = available_detectors()
    if not detectors:
        results.add("L2 fixture scoring", "SKIP", "no detectors have shipped yet")
        return None

    import tempfile
    scores, failed = [], []
    workroot = keep_dir or tempfile.mkdtemp(prefix="fixture-run-")
    for name in names:
        try:
            with FixtureServer(os.path.join(FIXTURES, name)) as server:
                findings, _ = run_audit(server.base_url, os.path.join(workroot, name))
        except Exception as exc:  # noqa: BLE001
            failed.append("%s: %s" % (name, exc))
            continue
        score = score_fixture(name, findings)
        scores.append(score)
        if score["misses"] or score["false_positives"]:
            for problem in score["misses"]:
                print("        MISS  [%s] %s" % (name, problem))
            for problem in score["false_positives"]:
                print("        FP    [%s] %s" % (name, problem))

    total_pending = sum(len(s["pending"]) for s in scores)
    total_hits = sum(len(s["hits"]) for s in scores)
    total_misses = sum(len(s["misses"]) for s in scores)
    total_fp = sum(len(s["false_positives"]) for s in scores)
    control_fp = sum(len(s["false_positives"]) for s in scores if s["negative_control"])

    recall = total_hits / float(total_hits + total_misses) if (total_hits + total_misses) else 1.0
    precision = total_hits / float(total_hits + total_fp) if (total_hits + total_fp) else 1.0

    detail = ("%d/%d detectors, recall %.2f, precision %.2f, %d false positives "
              "(%d on negative controls), %d expectations pending unbuilt detectors"
              % (len(detectors), len(DETECTORS), recall, precision, total_fp, control_fp,
                 total_pending))
    status = "FAIL" if (failed or control_fp or total_misses) else "PASS"
    if failed:
        detail += " | errors: " + "; ".join(failed[:3])
    results.add("L2 fixture scoring", status, detail)
    return {"recall": recall, "precision": precision, "false_positives": total_fp,
            "negative_control_false_positives": control_fp, "scores": scores}


def layer_determinism(results, names):
    if not os.path.isfile(COLLECTOR) or not available_detectors():
        results.add("L3 determinism", "SKIP", "needs the collector and at least one detector")
        return
    import tempfile
    sample = names[:3]
    mismatches = []
    for name in sample:
        signatures = []
        for attempt in range(2):
            with FixtureServer(os.path.join(FIXTURES, name)) as server:
                findings, _ = run_audit(
                    server.base_url,
                    os.path.join(tempfile.mkdtemp(prefix="det-"), "run%d" % attempt))
            signatures.append(json.dumps(
                sorted((f.get("check_id"), sorted(f.get("affected_urls") or []))
                       for f in findings), sort_keys=True))
        if signatures[0] != signatures[1]:
            mismatches.append(name)
    results.add("L3 determinism", "FAIL" if mismatches else "PASS",
                "differed on %s" % ", ".join(mismatches) if mismatches
                else "%d fixtures produced identical findings across two runs" % len(sample))


# ---------------------------------------------------------------------------------- L4

def layer_report_schema(results):
    entry = os.path.join(ROOT, "skills", "brand-ai-readiness-audit", "scripts")
    merge = os.path.join(entry, "merge_findings.py")
    validate = os.path.join(entry, "validate_report.py")
    if not (os.path.isfile(merge) and os.path.isfile(validate)):
        results.add("L4 report schema", "SKIP", "entrypoint scripts not present")
        return
    import tempfile
    workdir = tempfile.mkdtemp(prefix="schema-")
    snapshot = os.path.join(workdir, "snapshot.json")
    with open(snapshot, "w", encoding="utf-8") as handle:
        json.dump({"site": "fixture.test", "audited_at": "2026-09-05T00:00:00Z",
                   "coverage": {"pages_sampled": 1, "not_assessed": []}}, handle)
    findings = os.path.join(workdir, "findings-synthetic.json")
    with open(findings, "w", encoding="utf-8") as handle:
        json.dump([{
            "check_id": "ACC.ROBOTS_BLOCKS_RETRIEVAL",
            "title": "Retrieval crawlers are disallowed sitewide",
            "gate_impact": "blocks", "reach": "sitewide", "certainty": "measured",
            "funnel_stage": "accessible", "detector": "crawl-access-audit",
            "evidence": "robots.txt line 4 disallows OAI-SearchBot from the whole site.",
            "affected_urls": ["https://fixture.test/robots.txt"],
            "evidence_detail": {"confidence": "high", "nondeterministic": False},
            "suggested_action": {
                "summary": "Allow retrieval agents while keeping any training opt-out.",
                "how": ["Add an explicit Allow rule for retrieval agents."],
                "mechanism": "Reopens the accessible gate.",
                "effort": "config", "owner": "engineering",
                "verification": "Re-read robots.txt and watch server logs."}}], handle)
    report = os.path.join(workdir, "report.json")
    merged = subprocess.run(
        [sys.executable, merge, "--snapshot", snapshot, "--findings", findings,
         "--out", report], capture_output=True, text=True)
    if merged.returncode != 0:
        results.add("L4 report schema", "FAIL", "merge failed: %s" % merged.stderr[:200])
        return
    checked = subprocess.run([sys.executable, validate, "--report", report],
                             capture_output=True, text=True)
    results.add("L4 report schema", "PASS" if checked.returncode == 0 else "FAIL",
                "synthetic report merged and validated"
                if checked.returncode == 0 else checked.stdout[:300])


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the marketplace test suite.")
    parser.add_argument("--only", help="comma-separated layer prefixes, e.g. L0,L2")
    parser.add_argument("--fixture", help="restrict fixture layers to one fixture")
    parser.add_argument("--json", action="store_true", help="emit a JSON summary")
    parser.add_argument("--keep", help="keep audit working files in this directory")
    args = parser.parse_args(argv)

    wanted = set(args.only.split(",")) if args.only else None

    def want(prefix):
        return wanted is None or prefix in wanted

    results = Results()
    print("Brand AI-readiness marketplace test suite\n" + "-" * 60)

    if want("L5"):
        layer_spec_conformance(results)
        layer_validator_selftest(results)
    if want("L6"):
        layer_catalogue_integrity(results)
    names = []
    if want("L0"):
        names = layer_fixture_integrity(results, args.fixture)
    else:
        names = sorted(n for n in os.listdir(FIXTURES)
                       if os.path.isdir(os.path.join(FIXTURES, n)))
        if args.fixture:
            names = [n for n in names if n == args.fixture]
    if want("L1"):
        layer_unit_tests(results)
    scoring = None
    if want("L2"):
        scoring = layer_fixture_scoring(results, names, args.keep)
    if want("L3"):
        layer_determinism(results, names)
    if want("L4"):
        layer_report_schema(results)

    print("-" * 60)
    passed = sum(1 for layer in results.layers if layer["status"] == "PASS")
    skipped = sum(1 for layer in results.layers if layer["status"] == "SKIP")
    failed = sum(1 for layer in results.layers if layer["status"] == "FAIL")
    print("RESULT: %d passed, %d skipped, %d failed" % (passed, skipped, failed))
    if skipped:
        print("Skipped layers must be green before packaging.")

    if args.json:
        json.dump({"layers": results.layers, "scoring": scoring}, sys.stdout, indent=2)
        sys.stdout.write("\n")

    return 1 if results.failed else 0


if __name__ == "__main__":
    sys.exit(main())
