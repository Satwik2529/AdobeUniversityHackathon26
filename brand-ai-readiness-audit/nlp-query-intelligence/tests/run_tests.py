#!/usr/bin/env python3
"""The NLP Query Intelligence test harness — its own suite, independent of
the parent marketplace's tests/run_tests.py, mirroring the same layered
spirit at a scale that fits this subsystem:

  NL0  fixture integrity   every fixtures/*/snapshot.json parses
  NL1  unit tests           every test_*.py module (unittest discovery)
  NL3  determinism          covered inline within NL1 (query_generator,
                             pipeline_integration) rather than a separate pass
  NL4  output schema        covered inline within NL1 (schema.py's
                             validate_query_result runs on every built result)
  NL5  negative controls    test_negative_controls.py, called out separately
                             below so a false pass there is never buried in
                             an aggregate count

Usage: python3 run_tests.py [--json]
Exit codes: 0 all layers passed, 1 a failure.
"""
import glob
import io
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

from lib import snapshot_adapter  # noqa: E402


def layer_nl0_fixture_integrity():
    results = []
    for path in sorted(glob.glob(os.path.join(HERE, "fixtures", "*", "snapshot.json"))):
        name = os.path.basename(os.path.dirname(path))
        try:
            snap, _ = snapshot_adapter.load_snapshot(path)
            ok = isinstance(snap.get("pages"), list) and len(snap["pages"]) > 0
        except snapshot_adapter.SnapshotError:
            ok = False
        results.append((name, ok))
    return results


def _run_unittest_module(module_name):
    suite = unittest.TestLoader().loadTestsFromName(module_name)
    runner = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0)
    result = runner.run(suite)
    return result.testsRun, len(result.failures) + len(result.errors), result.failures + result.errors


def layer_nl1_unit_tests():
    modules = sorted(
        os.path.splitext(os.path.basename(p))[0]
        for p in glob.glob(os.path.join(HERE, "test_*.py"))
    )
    results = []
    for module in modules:
        ran, failed, problems = _run_unittest_module(module)
        results.append((module, ran, failed, problems))
    return results


def main():
    as_json = "--json" in sys.argv
    report = {"layers": []}
    overall_ok = True

    nl0 = layer_nl0_fixture_integrity()
    nl0_ok = all(ok for _, ok in nl0)
    overall_ok &= nl0_ok
    report["layers"].append({"layer": "NL0 fixture integrity", "ok": nl0_ok,
                             "detail": {name: ok for name, ok in nl0}})

    nl1 = layer_nl1_unit_tests()
    nl1_ok = all(failed == 0 for _, _, failed, _ in nl1)
    overall_ok &= nl1_ok
    report["layers"].append({
        "layer": "NL1 unit tests (incl. NL3 determinism, NL4 schema)",
        "ok": nl1_ok,
        "detail": {mod: {"ran": ran, "failed": failed} for mod, ran, failed, _ in nl1},
    })

    negative_controls = next(((m, r, f, p) for m, r, f, p in nl1 if m == "test_negative_controls"), None)
    nl5_ok = negative_controls is not None and negative_controls[2] == 0
    overall_ok &= nl5_ok
    report["layers"].append({"layer": "NL5 negative controls", "ok": nl5_ok,
                             "detail": {"ran": negative_controls[1] if negative_controls else 0}})

    if as_json:
        print(json.dumps(report, indent=2))
    else:
        for layer in report["layers"]:
            print("%-6s %s" % ("ok" if layer["ok"] else "FAIL", layer["layer"]))
        for module, ran, failed, problems in nl1:
            if failed:
                print("\n  %s: %d/%d failed" % (module, failed, ran))
                for name, trace in problems:
                    print("    - %s" % name)
        print("\nRESULT:", "PASS" if overall_ok else "FAIL")

    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
