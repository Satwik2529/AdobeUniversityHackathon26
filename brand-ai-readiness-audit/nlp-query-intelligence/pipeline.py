#!/usr/bin/env python3
"""NLP Query Intelligence — a standalone, read-only subsystem over an
existing brand-ai-readiness-audit run.

Reads audit-output/snapshot.json (required) and audit-output/report.json
(optional, for cautious finding correlation only) and never writes to
either. All output goes under its own tree (nlp-output/ by default),
mirroring audit.py's own "one convenience runner, no logic of its own"
posture: everything here is exactly what lib/ computes, nothing is
duplicated or reinterpreted at this layer.

Subcommands:
  profile   snapshot.json           -> website-profile.json
  generate  website-profile.json    -> generated-queries.json
  test      one query + snapshot    -> query-result.json
  compare   two or more results     -> comparison.json
  dataset   profile+queries+results -> dataset/

Exit codes: 0 completed, 1 could not complete, 2 bad arguments.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lib import domain_profiler, evidence_index, query_generator, report_adapter, schema, snapshot_adapter, differential  # noqa: E402


def _write_json(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=False)
    os.replace(tmp, path)


def _load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def cmd_profile(args):
    snapshot, snapshot_hash = snapshot_adapter.load_snapshot(args.snapshot)
    profile = domain_profiler.build_profile(snapshot, snapshot_hash)
    _write_json(args.out, profile)
    sys.stderr.write("  ok    profile   domain_type=%s entities=%d\n"
                      % (profile["domain_type"], len(profile["entities"])))
    return 0


def cmd_generate(args):
    snapshot, snapshot_hash = snapshot_adapter.load_snapshot(args.snapshot)
    profile = _load_json(args.profile) if args.profile else domain_profiler.build_profile(snapshot, snapshot_hash)
    report = report_adapter.load_report(args.report) if args.report else None
    index = evidence_index.EvidenceIndex(snapshot)
    result = query_generator.generate_queries(profile, snapshot, snapshot_hash, index=index, report=report)
    _write_json(args.out, result)
    sys.stderr.write("  ok    generate  %d queries (%d discarded as low-quality)\n"
                      % (result["count"], result["discarded_low_quality"]))
    return 0


def cmd_test(args):
    snapshot, snapshot_hash = snapshot_adapter.load_snapshot(args.snapshot)
    profile = _load_json(args.profile) if args.profile else domain_profiler.build_profile(snapshot, snapshot_hash)
    report = report_adapter.load_report(args.report) if args.report else None
    index = evidence_index.EvidenceIndex(snapshot)
    result = schema.build_query_result(args.query, snapshot, snapshot_hash, profile, report=report, index=index)
    _write_json(args.out, result)
    sys.stderr.write("  ok    test      score=%s%%\n" % result["scoring"]["overall_score"])
    return 0


def cmd_compare(args):
    results = [_load_json(p) for p in args.results]
    if len(results) == 2:
        out = differential.compare_two(results[0], results[1])
    else:
        out = differential.compare_many(results)
    _write_json(args.out, out)
    sys.stderr.write("  ok    compare   %d quer%s\n" % (len(results), "y" if len(results) == 1 else "ies"))
    return 0


def cmd_dataset(args):
    from lib.versions import DATASET_VERSION
    profile = _load_json(args.profile)
    queries = _load_json(args.queries)
    results = [_load_json(p) for p in args.results]
    dataset = {
        "dataset_version": DATASET_VERSION,
        "snapshot_hash": profile.get("snapshot_hash"),
        "generator_version": queries.get("generator_version"),
        "nlp_version": results[0]["nlp"]["nlp_engine_version"] if results else None,
        "label_source": "automatically_generated",
        "profile": profile,
        "queries": queries.get("queries", []),
        "results": results,
    }
    os.makedirs(args.out, exist_ok=True)
    _write_json(os.path.join(args.out, "dataset.json"), dataset)
    _write_json(os.path.join(args.out, "manifest.json"), {
        "dataset_version": DATASET_VERSION,
        "query_count": len(queries.get("queries", [])),
        "result_count": len(results),
        "label_source": "automatically_generated",
    })
    sys.stderr.write("  ok    dataset   %d results\n" % len(results))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_profile = sub.add_parser("profile", help="build website-profile.json from a snapshot")
    p_profile.add_argument("--snapshot", required=True)
    p_profile.add_argument("--out", required=True)
    p_profile.set_defaults(func=cmd_profile)

    p_generate = sub.add_parser("generate", help="generate queries from a profile (or a snapshot directly)")
    p_generate.add_argument("--snapshot", required=True)
    p_generate.add_argument("--profile", default=None)
    p_generate.add_argument("--report", default=None)
    p_generate.add_argument("--out", required=True)
    p_generate.set_defaults(func=cmd_generate)

    p_test = sub.add_parser("test", help="analyze one query against a snapshot's evidence")
    p_test.add_argument("--query", required=True)
    p_test.add_argument("--snapshot", required=True)
    p_test.add_argument("--profile", default=None)
    p_test.add_argument("--report", default=None)
    p_test.add_argument("--out", required=True)
    p_test.set_defaults(func=cmd_test)

    p_compare = sub.add_parser("compare", help="compare two or more query-result.json files")
    p_compare.add_argument("--results", nargs="+", required=True)
    p_compare.add_argument("--out", required=True)
    p_compare.set_defaults(func=cmd_compare)

    p_dataset = sub.add_parser("dataset", help="bundle a profile + queries + results into a labeled dataset")
    p_dataset.add_argument("--profile", required=True)
    p_dataset.add_argument("--queries", required=True)
    p_dataset.add_argument("--results", nargs="+", required=True)
    p_dataset.add_argument("--out", required=True)
    p_dataset.set_defaults(func=cmd_dataset)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except snapshot_adapter.SnapshotError as exc:
        sys.stderr.write("  FAIL  %s\n" % exc)
        return 1
    except schema.SchemaError as exc:
        sys.stderr.write("  FAIL  invalid output: %s\n" % exc)
        return 1
    except (OSError, ValueError) as exc:
        sys.stderr.write("  FAIL  %s\n" % exc)
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.stderr.write("\nInterrupted.\n")
        sys.exit(1)
