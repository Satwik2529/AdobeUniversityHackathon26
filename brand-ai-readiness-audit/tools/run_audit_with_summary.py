#!/usr/bin/env python3
"""Run audit.py, then write SUMMARY.md next to its output — one command.

A convenience wrapper only: it runs the existing audit.py exactly as you
would from the command line, then runs generate_summary.py against whatever
--out directory that run used. It contains no audit logic of its own; it
does not modify audit.py, and skipping it and running the two scripts
yourself produces an identical result.

Usage:
  python3 tools/run_audit_with_summary.py https://example.com
  python3 tools/run_audit_with_summary.py https://example.com --out ./my-audit --render off

All arguments are forwarded to audit.py unchanged; see `python3 audit.py -h`
for the full list. The summary step is skipped if the audit itself fails.

Exit codes: whatever audit.py returns (0 completed, 1 could not complete,
2 bad arguments); 1 if the summary step fails after a successful audit.
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    # Only peel off --out to know where generate_summary.py should look;
    # everything else (including --out itself) passes through to audit.py
    # untouched.
    peek = argparse.ArgumentParser(add_help=False)
    peek.add_argument("--out", default="audit-output")
    known, _ = peek.parse_known_args()

    audit_result = subprocess.run(
        [sys.executable, str(ROOT / "audit.py")] + sys.argv[1:],
    )
    if audit_result.returncode != 0:
        return audit_result.returncode

    summary_result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "generate_summary.py"), "--out", known.out],
    )
    return summary_result.returncode


if __name__ == "__main__":
    sys.exit(main())
