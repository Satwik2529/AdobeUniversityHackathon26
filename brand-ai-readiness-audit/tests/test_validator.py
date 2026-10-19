#!/usr/bin/env python3
"""Adversarial tests for tools/validate_marketplace.py.

A validator that never fails is not a validator. Each case below builds a deliberately
broken marketplace in a temporary directory and asserts the specific violation is caught.

Usage: python3 tests/test_validator.py
Exit codes: 0 all passed, 1 one or more failed.
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import validate_marketplace as vm  # noqa: E402

GOOD_FRONTMATTER = """---
name: {name}
description: A deliberately valid skill used as the baseline for validator tests. Use it only inside the validator test harness.
license: Apache-2.0
allowed-tools: Bash Read
---

# Test skill

Body.
"""


def build(tmp, skills, manifest_overrides=None, bodies=None):
    os.makedirs(os.path.join(tmp, "skills"))
    for name in skills:
        folder = os.path.join(tmp, "skills", name)
        os.makedirs(folder)
        body = (bodies or {}).get(name, GOOD_FRONTMATTER.format(name=name))
        with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as handle:
            handle.write(body)
    manifest = {
        "name": "test-marketplace",
        "version": "1.0.0",
        "skills": [
            {"id": n, "path": "skills/%s" % n, "entrypoint": (i == 0)}
            for i, n in enumerate(skills)
        ],
    }
    manifest.update(manifest_overrides or {})
    with open(os.path.join(tmp, "marketplace.json"), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle)
    return tmp


def run(tmp, strict=False):
    argv = ["--root", tmp, "--json"] + (["--strict"] if strict else [])
    import io
    import contextlib
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        vm.main(argv)
    return json.loads(buffer.getvalue())


CASES = []


def case(name):
    def wrap(fn):
        CASES.append((name, fn))
        return fn
    return wrap


@case("baseline valid marketplace passes")
def _(tmp):
    build(tmp, ["alpha-skill", "beta-skill"])
    result = run(tmp)
    return result["error_count"] == 0, result["errors"]


@case("two entrypoints is an error")
def _(tmp):
    build(tmp, ["alpha-skill", "beta-skill"])
    path = os.path.join(tmp, "marketplace.json")
    manifest = json.load(open(path))
    manifest["skills"][1]["entrypoint"] = True
    json.dump(manifest, open(path, "w"))
    result = run(tmp)
    return any("exactly one" in e["message"] for e in result["errors"]), result["errors"]


@case("zero entrypoints is an error")
def _(tmp):
    build(tmp, ["alpha-skill"])
    path = os.path.join(tmp, "marketplace.json")
    manifest = json.load(open(path))
    manifest["skills"][0]["entrypoint"] = False
    json.dump(manifest, open(path, "w"))
    result = run(tmp)
    return any("exactly one" in e["message"] for e in result["errors"]), result["errors"]


@case("name not matching the folder is an error")
def _(tmp):
    build(tmp, ["alpha-skill"], bodies={
        "alpha-skill": GOOD_FRONTMATTER.format(name="different-name")})
    result = run(tmp)
    return any("must match the parent directory" in e["message"] for e in result["errors"]), \
        result["errors"]


@case("consecutive hyphens in a name are an error")
def _(tmp):
    os.makedirs(os.path.join(tmp, "skills", "bad--name"))
    with open(os.path.join(tmp, "skills", "bad--name", "SKILL.md"), "w") as handle:
        handle.write(GOOD_FRONTMATTER.format(name="bad--name"))
    json.dump({"name": "test-marketplace", "version": "1.0.0",
               "skills": [{"id": "bad--name", "path": "skills/bad--name", "entrypoint": True}]},
              open(os.path.join(tmp, "marketplace.json"), "w"))
    result = run(tmp)
    return any("consecutive hyphens" in e["message"] for e in result["errors"]), result["errors"]


@case("uppercase in a name is an error")
def _(tmp):
    os.makedirs(os.path.join(tmp, "skills", "BadName"))
    with open(os.path.join(tmp, "skills", "BadName", "SKILL.md"), "w") as handle:
        handle.write(GOOD_FRONTMATTER.format(name="BadName"))
    json.dump({"name": "test-marketplace", "version": "1.0.0",
               "skills": [{"id": "BadName", "path": "skills/BadName", "entrypoint": True}]},
              open(os.path.join(tmp, "marketplace.json"), "w"))
    result = run(tmp)
    return any("lowercase" in e["message"] for e in result["errors"]), result["errors"]


@case("missing description is an error")
def _(tmp):
    build(tmp, ["alpha-skill"], bodies={
        "alpha-skill": "---\nname: alpha-skill\nlicense: Apache-2.0\n---\n\nBody.\n"})
    result = run(tmp)
    return any("description" in e["message"] for e in result["errors"]), result["errors"]


@case("over-long description is an error")
def _(tmp):
    body = "---\nname: alpha-skill\ndescription: %s\n---\n\nBody.\n" % ("x" * 1100)
    build(tmp, ["alpha-skill"], bodies={"alpha-skill": body})
    result = run(tmp)
    return any("maximum is 1024" in e["message"] for e in result["errors"]), result["errors"]


@case("angle brackets in frontmatter are an error")
def _(tmp):
    body = ("---\nname: alpha-skill\ndescription: Uses a tag like <script> in the "
            "frontmatter, which the spec advises against for injection safety reasons.\n"
            "---\n\nBody.\n")
    build(tmp, ["alpha-skill"], bodies={"alpha-skill": body})
    result = run(tmp)
    return any("angle bracket" in e["message"] for e in result["errors"]), result["errors"]


@case("frontmatter not on line 1 is an error")
def _(tmp):
    body = ("\n---\nname: alpha-skill\ndescription: Frontmatter that does not start on the "
            "first line, which silently prevents the skill from loading.\n---\n\nBody.\n")
    build(tmp, ["alpha-skill"], bodies={"alpha-skill": body})
    result = run(tmp)
    return any("line 1" in e["message"] for e in result["errors"]), result["errors"]


@case("unclosed frontmatter is an error")
def _(tmp):
    body = ("---\nname: alpha-skill\ndescription: Frontmatter that is never closed, which "
            "is invalid and prevents loading.\n\nBody.\n")
    build(tmp, ["alpha-skill"], bodies={"alpha-skill": body})
    result = run(tmp)
    return any("not closed" in e["message"] for e in result["errors"]), result["errors"]


@case("manifest path that does not resolve is an error")
def _(tmp):
    build(tmp, ["alpha-skill"])
    path = os.path.join(tmp, "marketplace.json")
    manifest = json.load(open(path))
    manifest["skills"][0]["path"] = "skills/nope"
    json.dump(manifest, open(path, "w"))
    result = run(tmp)
    return any("does not resolve" in e["message"] for e in result["errors"]), result["errors"]


@case("skill folder on disk missing from the manifest is an error")
def _(tmp):
    build(tmp, ["alpha-skill"])
    orphan = os.path.join(tmp, "skills", "orphan-skill")
    os.makedirs(orphan)
    with open(os.path.join(orphan, "SKILL.md"), "w") as handle:
        handle.write(GOOD_FRONTMATTER.format(name="orphan-skill"))
    result = run(tmp)
    return any("not listed in the manifest" in e["message"] for e in result["errors"]), \
        result["errors"]


@case("duplicate skill id is an error")
def _(tmp):
    build(tmp, ["alpha-skill"])
    path = os.path.join(tmp, "marketplace.json")
    manifest = json.load(open(path))
    manifest["skills"].append({"id": "alpha-skill", "path": "skills/alpha-skill"})
    json.dump(manifest, open(path, "w"))
    result = run(tmp)
    return any("duplicate skill id" in e["message"] for e in result["errors"]), result["errors"]


@case("unresolved file reference is a warning, not an error")
def _(tmp):
    body = GOOD_FRONTMATTER.format(name="alpha-skill") + "\nSee references/missing.md\n"
    build(tmp, ["alpha-skill"], bodies={"alpha-skill": body})
    loose = run(tmp)
    strict = run(tmp, strict=True)
    return (loose["error_count"] == 0 and loose["warning_count"] >= 1
            and strict["ok"] is False), (loose["warnings"], strict["ok"])


@case("top-level entrypoint disagreeing with the skill flag is an error")
def _(tmp):
    build(tmp, ["alpha-skill", "beta-skill"], manifest_overrides={"entrypoint": "beta-skill"})
    result = run(tmp)
    return any("disagrees" in e["message"] for e in result["errors"]), result["errors"]


@case("harness scores via the real severity derivation, not a default")
def _(tmp):
    """Guard: L2 scoring must not treat detector severity inputs as a final severity.

    Detectors emit gate_impact/reach/certainty and let the entrypoint derive severity.
    A harness that defaults a missing `severity` to a fixed value silently mis-scores
    every finding - which is exactly the bug that once made a critical read as medium
    and an info-override read as a false positive.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "run_tests_mod", os.path.join(ROOT, "tests", "run_tests.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, "derived_severity"):
        return False, "run_tests.py has no derived_severity(); scoring may use a default"

    blocker = {"check_id": "X.BLOCK", "gate_impact": "blocks", "reach": "sitewide",
               "certainty": "measured",
               "evidence_detail": {"confidence": "high", "nondeterministic": False,
                                   "sample": {"checked": 1, "failing": 1}}}
    policy = dict(blocker, check_id="X.POLICY", severity_override="info")

    got_blocker = module.derived_severity(blocker)
    got_policy = module.derived_severity(policy)
    if got_blocker != "critical":
        return False, "sitewide blocker derived as %r, expected critical" % got_blocker
    if got_policy != "info":
        return False, "severity_override ignored: got %r, expected info" % got_policy

    source = open(os.path.join(ROOT, "tests", "run_tests.py"), encoding="utf-8").read()
    if 'finding.get("severity", "medium")' in source:
        return False, "scoring still falls back to a hard-coded default severity"
    return True, {"blocker": got_blocker, "policy": got_policy}


def main():
    passed, failed = 0, 0
    for name, fn in CASES:
        tmp = tempfile.mkdtemp(prefix="vmtest-")
        try:
            ok, detail = fn(tmp)
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, "raised %s: %s" % (type(exc).__name__, exc)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if ok:
            passed += 1
            print("  PASS  %s" % name)
        else:
            failed += 1
            print("  FAIL  %s -> %s" % (name, detail))
    print("\nvalidator self-test: %d passed, %d failed" % (passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
