#!/usr/bin/env python3
"""Validate an audit report against the bundled report schema.

No third-party dependencies: implements the JSON Schema subset the report schema
actually uses (type, required, enum, pattern, properties, items).

Usage:
  validate_report.py --report report.json [--schema assets/report.schema.json]

Exit codes:
  0  report is valid
  1  report is invalid (errors printed to stdout as JSON)
  2  bad arguments
  3  a file could not be read or parsed
"""
import argparse
import json
import os
import re
import sys

TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
}


def _type_ok(value, expected):
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    py = TYPES.get(expected)
    return py is None or isinstance(value, py)


def validate(node, schema, path="$"):
    """Return a list of human-readable error strings."""
    errors = []
    if not isinstance(schema, dict) or not schema:
        return errors

    expected_type = schema.get("type")
    if expected_type and not _type_ok(node, expected_type):
        errors.append("%s: expected %s, got %s" % (path, expected_type, type(node).__name__))
        return errors

    if "enum" in schema and node not in schema["enum"]:
        errors.append("%s: %r is not one of %s" % (path, node, schema["enum"]))

    if "pattern" in schema and isinstance(node, str):
        if not re.match(schema["pattern"], node):
            errors.append("%s: %r does not match pattern %s" % (path, node, schema["pattern"]))

    if isinstance(node, dict):
        for key in schema.get("required", []):
            if key not in node:
                errors.append("%s: missing required property %r" % (path, key))
        for key, subschema in schema.get("properties", {}).items():
            if key in node:
                errors.extend(validate(node[key], subschema, "%s.%s" % (path, key)))

    if isinstance(node, list) and "items" in schema:
        for index, item in enumerate(node):
            errors.extend(validate(item, schema["items"], "%s[%d]" % (path, index)))

    return errors


def semantic_checks(report):
    """Invariants the schema cannot express."""
    errors = []
    findings = report.get("findings", [])
    summary = report.get("summary", {})

    if isinstance(findings, list) and isinstance(summary, dict):
        if summary.get("total_findings") != len(findings):
            errors.append(
                "$.summary.total_findings (%s) must equal the number of findings (%d)"
                % (summary.get("total_findings"), len(findings))
            )
        counted = {}
        for finding in findings:
            sev = finding.get("severity")
            counted[sev] = counted.get(sev, 0) + 1
        for sev in ("critical", "high", "medium", "low", "info"):
            if sev in summary and summary[sev] != counted.get(sev, 0):
                errors.append(
                    "$.summary.%s (%s) does not match the findings (%d)"
                    % (sev, summary[sev], counted.get(sev, 0))
                )

    seen = set()
    for index, finding in enumerate(findings if isinstance(findings, list) else []):
        fid = finding.get("id")
        if fid in seen:
            errors.append("$.findings[%d]: duplicate finding id %r" % (index, fid))
        seen.add(fid)
        # Evidence-or-silence: every finding must be locatable and substantive.
        evidence = finding.get("evidence") or ""
        if len(evidence.strip()) < 20:
            errors.append("$.findings[%d]: evidence is too thin to be verifiable" % index)
        detail = finding.get("evidence_detail") or {}
        urls = finding.get("affected_urls") or detail.get("urls") or []
        if finding.get("severity") != "info" and not urls:
            errors.append(
                "$.findings[%d]: no concrete URL. Evidence-or-silence: a finding a site "
                "owner cannot locate must be downgraded or dropped." % index
            )

    audited_at = report.get("audited_at", "")
    if audited_at and not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$", audited_at):
        errors.append("$.audited_at: must be ISO-8601 UTC with a Z suffix")

    return errors


def main(argv=None):
    here = os.path.dirname(os.path.abspath(__file__))
    default_schema = os.path.join(here, "..", "assets", "report.schema.json")

    parser = argparse.ArgumentParser(
        description="Validate an audit report against the bundled report schema.",
        epilog="Example: validate_report.py --report audit-output/report.json",
    )
    parser.add_argument("--report", required=True, help="path to report.json")
    parser.add_argument("--schema", default=default_schema, help="path to report.schema.json")
    parser.add_argument("--quiet", action="store_true", help="suppress the success line")
    args = parser.parse_args(argv)

    try:
        with open(args.report, "r", encoding="utf-8") as handle:
            report = json.load(handle)
        with open(args.schema, "r", encoding="utf-8") as handle:
            schema = json.load(handle)
    except (OSError, ValueError) as exc:
        sys.stderr.write("Error: could not read or parse input: %s\n" % exc)
        return 3

    errors = validate(report, schema) + semantic_checks(report)

    if errors:
        json.dump({"valid": False, "error_count": len(errors), "errors": errors},
                  sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 1

    if not args.quiet:
        json.dump({"valid": True, "findings": len(report.get("findings", []))},
                  sys.stdout, indent=2)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
