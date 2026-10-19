"""Read-only, OPTIONAL adapter around the existing entrypoint's report.json.

Used only for finding_correlator.py's cautious cross-referencing. Every
caller must tolerate this returning None — a missing report.json is not an
error for this subsystem (see nlp-query-intelligence/README.md, "Existing
report input").
"""
import json
import os


def load_report(path):
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (ValueError, OSError):
        return None
    if not isinstance(data, dict) or "findings" not in data:
        return None
    return data
