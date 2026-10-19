"""Read-only adapter around the existing collector's snapshot.json.

This module never writes to a snapshot file and never mutates the parsed
dict it hands back. It is the only place that touches snapshot.json's shape,
mirroring the frontend's own normalize/index.ts convention of one seam
between raw evidence and everything downstream.
"""
import hashlib
import json
import os


class SnapshotError(Exception):
    pass


def load_snapshot(path):
    """Load snapshot.json read-only. Raises SnapshotError with a message
    fit to surface to a user (missing file, unreadable, not JSON)."""
    if not path or not os.path.isfile(path):
        raise SnapshotError("snapshot.json not found at %r" % (path,))
    with open(path, "rb") as fh:
        raw = fh.read()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise SnapshotError("snapshot.json could not be parsed: %s" % exc)
    if not isinstance(data, dict) or "pages" not in data:
        raise SnapshotError("snapshot.json does not look like a collector snapshot (no 'pages')")
    return data, hashlib.sha256(raw).hexdigest()


def pages(snapshot):
    """Every fetched page record, skipping ones with no usable text."""
    return [p for p in snapshot.get("pages", []) if isinstance(p, dict) and p.get("fetch_ok")]


def page_text_fields(page):
    """The text-bearing fields evidence lookups read — all already present
    on disk in snapshot.json, so this never triggers a network request."""
    return {
        "title": page.get("title") or "",
        "meta_description": page.get("meta_description") or "",
        "headings": [h.get("text", "") for h in (page.get("headings") or []) if isinstance(h, dict)],
        "main_text": page.get("main_text") or page.get("raw_text") or "",
    }
