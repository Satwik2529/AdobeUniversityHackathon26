#!/usr/bin/env python3
"""Validate the marketplace manifest and every skill folder against the Agent Skills spec.

Checks, per the agentskills.io specification and this contest's manifest convention:
  - marketplace.json parses and declares name, version and skills
  - every declared skill path resolves to a directory containing SKILL.md
  - exactly one skill is marked as the entrypoint
  - no skill folder on disk is missing from the manifest, and no duplicates
  - SKILL.md has well-formed YAML frontmatter delimited by --- on the first line
  - name: 1-64 chars, lowercase alphanumeric and hyphens, no leading, trailing or
    consecutive hyphens, and identical to the parent directory name
  - description: 1-1024 chars, non-empty
  - compatibility: at most 500 chars when present
  - metadata: a flat map of string keys to string values
  - allowed-tools: a space-separated string
  - no angle brackets anywhere in the frontmatter (prompt-injection safety)
  - SKILL.md stays under the recommended 500-line ceiling
  - every relative file reference inside SKILL.md resolves (reported as a warning until
    the referenced script is implemented; must be zero before packaging)

Usage:
  validate_marketplace.py [--root .] [--json] [--strict]

Exit codes:
  0  no errors (warnings may be present unless --strict)
  1  at least one error, or a warning while --strict is set
  2  bad arguments
  3  the marketplace root or manifest could not be read
"""
import argparse
import json
import os
import re
import sys

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
REFERENCE_RE = re.compile(r"(?<![\w/.])((?:references|scripts|assets)/[A-Za-z0-9_.\-/]+)")
MAX_SKILL_MD_LINES = 500
MAX_DESCRIPTION = 1024
MAX_COMPATIBILITY = 500
MAX_NAME = 64


class Report(object):
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.checked = 0

    def error(self, where, message):
        self.errors.append({"where": where, "message": message})

    def warn(self, where, message):
        self.warnings.append({"where": where, "message": message})


def parse_frontmatter(text, where, report):
    """Parse the small YAML subset skills are allowed to use.

    Supports top-level `key: value` scalars and one level of nested mapping. Anything
    else is reported rather than silently accepted, because invalid frontmatter causes
    a skill to fail to load with no visible error.
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        report.error(where, "frontmatter must start on line 1 with ---")
        return None
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        report.error(where, "frontmatter is not closed with a second ---")
        return None

    data = {}
    current_key = None
    for offset, raw in enumerate(lines[1:end], start=2):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indented = raw[0] in (" ", "\t")
        if ":" not in raw:
            report.error(where, "line %d: not a key: value pair: %r" % (offset, raw.strip()))
            continue
        key, _, value = raw.partition(":")
        key, value = key.strip(), value.strip()
        if indented:
            if current_key is None:
                report.error(where, "line %d: indented entry with no parent key" % offset)
                continue
            if not isinstance(data.get(current_key), dict):
                data[current_key] = {}
            data[current_key][key] = value.strip('"').strip("'")
        else:
            current_key = key
            if value == "":
                data[key] = {}
            else:
                data[key] = value
    return data


def check_skill(root, skill_id, rel_path, report):
    where = rel_path or skill_id
    skill_dir = os.path.join(root, rel_path)
    if not os.path.isdir(skill_dir):
        report.error(where, "manifest path does not resolve to a directory")
        return
    skill_md = os.path.join(skill_dir, "SKILL.md")
    if not os.path.isfile(skill_md):
        report.error(where, "no SKILL.md in the skill directory")
        return

    with open(skill_md, "r", encoding="utf-8") as handle:
        text = handle.read()
    report.checked += 1

    line_count = text.count("\n") + 1
    if line_count > MAX_SKILL_MD_LINES:
        report.warn(where, "SKILL.md is %d lines; the spec recommends staying under %d. "
                           "Move detail into references/." % (line_count, MAX_SKILL_MD_LINES))

    front = parse_frontmatter(text, where, report)
    if front is None:
        return

    raw_front = text.split("---", 2)[1] if text.count("---") >= 2 else ""
    if "<" in raw_front or ">" in raw_front:
        report.error(where, "frontmatter contains an angle bracket; the spec advises "
                            "against them because they can inject instructions")

    name = front.get("name")
    if not isinstance(name, str) or not name:
        report.error(where, "frontmatter is missing the required 'name' field")
    else:
        if len(name) > MAX_NAME:
            report.error(where, "name is %d chars; the maximum is %d" % (len(name), MAX_NAME))
        if not NAME_RE.match(name):
            report.error(where, "name %r must be lowercase alphanumeric and hyphens, with "
                                "no leading, trailing or consecutive hyphens" % name)
        folder = os.path.basename(os.path.normpath(skill_dir))
        if name != folder:
            report.error(where, "name %r must match the parent directory name %r or the "
                                "skill will not load" % (name, folder))
        if name != skill_id:
            report.error(where, "name %r does not match the manifest id %r" % (name, skill_id))

    description = front.get("description")
    if not isinstance(description, str) or not description.strip():
        report.error(where, "frontmatter is missing a non-empty 'description'")
    elif len(description) > MAX_DESCRIPTION:
        report.error(where, "description is %d chars; the maximum is %d"
                            % (len(description), MAX_DESCRIPTION))
    elif len(description) < 40:
        report.warn(where, "description is very short; it is the primary triggering "
                           "signal and should say what the skill does and when to use it")

    compatibility = front.get("compatibility")
    if isinstance(compatibility, str) and len(compatibility) > MAX_COMPATIBILITY:
        report.error(where, "compatibility is %d chars; the maximum is %d"
                            % (len(compatibility), MAX_COMPATIBILITY))

    metadata = front.get("metadata")
    if metadata is not None:
        if not isinstance(metadata, dict):
            report.error(where, "metadata must be a mapping of string keys to string values")
        else:
            for key, value in metadata.items():
                if not isinstance(value, str):
                    report.error(where, "metadata.%s must be a string" % key)

    tools = front.get("allowed-tools")
    if tools is not None:
        if not isinstance(tools, str) or not tools.strip():
            report.error(where, "allowed-tools must be a non-empty space-separated string")
    else:
        report.warn(where, "no allowed-tools declared; the contest asks each skill to "
                           "declare its tool needs")

    if not front.get("license"):
        report.warn(where, "no license field declared")

    body = text.split("---", 2)[2] if text.count("---") >= 2 else ""
    for reference in sorted(set(REFERENCE_RE.findall(body))):
        target = os.path.join(skill_dir, reference)
        if not os.path.exists(target):
            report.warn(where, "SKILL.md references %s, which does not exist yet"
                               % reference)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate the marketplace manifest and every skill against the spec.",
        epilog="Example: validate_marketplace.py --root . --strict",
    )
    parser.add_argument("--root", default=".", help="marketplace root (default: .)")
    parser.add_argument("--json", action="store_true", help="emit JSON only")
    parser.add_argument("--strict", action="store_true",
                        help="treat warnings as failures (use before packaging)")
    args = parser.parse_args(argv)

    root = os.path.abspath(args.root)
    report = Report()

    manifest_path = os.path.join(root, "marketplace.json")
    if not os.path.isfile(manifest_path):
        sys.stderr.write("Error: no marketplace.json at %s\n" % root)
        return 3
    try:
        with open(manifest_path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except ValueError as exc:
        sys.stderr.write("Error: marketplace.json does not parse: %s\n" % exc)
        return 3

    for field in ("name", "version", "skills"):
        if field not in manifest:
            report.error("marketplace.json", "missing required field %r" % field)

    if not isinstance(manifest.get("name"), str) or not NAME_RE.match(manifest.get("name", "")):
        report.error("marketplace.json", "marketplace name must follow the same naming "
                                         "rules as a skill name")

    skills = manifest.get("skills") or []
    if not isinstance(skills, list) or not skills:
        report.error("marketplace.json", "skills must be a non-empty array")
        skills = []

    entrypoints = [s for s in skills if s.get("entrypoint") is True]
    if len(entrypoints) != 1:
        report.error("marketplace.json",
                     "exactly one skill must be marked entrypoint; found %d" % len(entrypoints))
    elif manifest.get("entrypoint") and manifest["entrypoint"] != entrypoints[0].get("id"):
        report.error("marketplace.json",
                     "top-level entrypoint %r disagrees with the skill marked entrypoint (%r)"
                     % (manifest["entrypoint"], entrypoints[0].get("id")))

    seen_ids, seen_paths = set(), set()
    for entry in skills:
        skill_id, rel_path = entry.get("id"), entry.get("path")
        if not skill_id or not rel_path:
            report.error("marketplace.json", "every skill entry needs an id and a path")
            continue
        if skill_id in seen_ids:
            report.error("marketplace.json", "duplicate skill id %r" % skill_id)
        if rel_path in seen_paths:
            report.error("marketplace.json", "duplicate skill path %r" % rel_path)
        seen_ids.add(skill_id)
        seen_paths.add(rel_path)
        check_skill(root, skill_id, rel_path, report)

    skills_dir = os.path.join(root, "skills")
    if os.path.isdir(skills_dir):
        for folder in sorted(os.listdir(skills_dir)):
            candidate = os.path.join(skills_dir, folder)
            if os.path.isdir(candidate) and os.path.isfile(os.path.join(candidate, "SKILL.md")):
                if os.path.join("skills", folder) not in seen_paths:
                    report.error("skills/%s" % folder,
                                 "a skill folder exists on disk but is not listed in the manifest")

    result = {
        "root": root,
        "skills_declared": len(skills),
        "skills_checked": report.checked,
        "entrypoints": len(entrypoints),
        "error_count": len(report.errors),
        "warning_count": len(report.warnings),
        "errors": report.errors,
        "warnings": report.warnings,
        "ok": not report.errors and (not args.strict or not report.warnings),
    }

    if args.json:
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print("Marketplace: %s" % manifest.get("name"))
        print("Skills declared: %d   validated: %d   entrypoints: %d"
              % (len(skills), report.checked, len(entrypoints)))
        print("Errors: %d   Warnings: %d" % (len(report.errors), len(report.warnings)))
        for item in report.errors:
            print("  ERROR   [%s] %s" % (item["where"], item["message"]))
        for item in report.warnings:
            print("  WARNING [%s] %s" % (item["where"], item["message"]))
        print("RESULT: %s" % ("PASS" if result["ok"] else "FAIL"))

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
