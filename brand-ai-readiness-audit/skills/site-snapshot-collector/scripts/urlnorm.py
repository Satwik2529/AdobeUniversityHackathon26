#!/usr/bin/env python3
"""Deterministic URL normalisation, deduplication keys and path skeletons.

Every rule here is documented in `references/sampling-strategy.md`. Two properties matter
more than anything else:

  1. **Determinism.** The same input URL always produces the same output, so two audits of
     an unchanged site sample the same pages and produce diffable reports.
  2. **Meaning preservation.** Only parameters known not to change the resource are
     stripped. Dropping a meaningful parameter would make the audit describe a page the
     site does not actually serve.

Two different outputs are produced for every URL and they must not be confused:

  `normalize(url)` -> the **fetchable** form. Safe to request. Trailing slashes and
                      meaningful query parameters are preserved exactly as the site uses
                      them.
  `dedupe_key(url)` -> the **identity** form. Never fetched. Additionally folds the
                      trailing slash and lowercases the scheme, so `/a` and `/a/` collapse
                      to one entry in the visited set.
"""
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

DEFAULT_PORTS = {"http": "80", "https": "443"}

# Shapes that identify a variable path segment. Order matters: the first match wins.
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_HEX = re.compile(r"^[0-9a-f]{12,}$", re.I)
_NUMERIC = re.compile(r"^\d+$")
_YEAR = re.compile(r"^(19|20)\d{2}$")
_YEAR_MONTH = re.compile(r"^(19|20)\d{2}-\d{2}$")
_SESSION_VALUE = re.compile(r"^[0-9a-f]{16,}$", re.I)

SLUG_MIN_LENGTH = 8

# Hyphenated words that name a section rather than an item. Generic across sites and
# sectors; an unlisted word simply falls through to the length and shape rules.
RESERVED_HYPHENATED = {
    "about-us", "contact-us", "our-story", "our-team", "who-we-are", "work-with-us",
    "terms-of-service", "terms-and-conditions", "privacy-policy", "cookie-policy",
    "sign-in", "sign-up", "log-in", "my-account", "press-kit", "media-kit",
    "customer-service", "get-started", "how-it-works", "case-studies", "site-map",
}


def _split_extension(segment):
    if "." in segment[1:]:
        stem, _, extension = segment.rpartition(".")
        if extension and len(extension) <= 5 and extension.isalnum():
            return stem, "." + extension.lower()
    return segment, ""


def normalize(url, base=None, tracking_params=(), session_params=()):
    """Return the canonical fetchable form of `url`, or None if it is not fetchable.

    Rules applied, in order:
      1. Resolve against `base` when the URL is relative.
      2. Lowercase the scheme and the host. Reject any scheme other than http or https.
      3. Drop the fragment. Fragments are never transmitted to a server, so keeping one
         would create two entries for a single resource.
      4. Drop the default port for the scheme.
      5. Drop userinfo. Credentials in a URL are never carried into an audit request.
      6. Collapse duplicate slashes in the path and resolve `.` and `..` segments.
      7. Remove tracking and session parameters, matched case-insensitively by name.
      8. Sort the surviving parameters by name then value, so parameter order cannot
         create two entries for one resource.
      9. Leave the trailing slash exactly as the site wrote it.
    """
    if url is None:
        return None
    url = url.strip()
    if not url or url.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
        return None
    if base:
        url = urljoin(base, url)

    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        return None

    host = (parts.hostname or "").lower()
    if not host:
        return None
    port = parts.port
    netloc = host
    if port and str(port) != DEFAULT_PORTS.get(scheme):
        netloc = "%s:%d" % (host, port)

    path = _collapse_path(parts.path or "/")
    query = _clean_query(parts.query, tracking_params, session_params)
    return urlunsplit((scheme, netloc, path, query, ""))


def _collapse_path(path):
    if not path.startswith("/"):
        path = "/" + path
    trailing = path.endswith("/") and path != "/"
    segments = []
    for segment in path.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            if segments:
                segments.pop()
            continue
        segments.append(segment)
    collapsed = "/" + "/".join(segments)
    if trailing and collapsed != "/":
        collapsed += "/"
    return collapsed


def _clean_query(query, tracking_params, session_params):
    if not query:
        return ""
    drop = {p.lower() for p in tracking_params} | {p.lower() for p in session_params}
    kept = []
    for name, value in parse_qsl(query, keep_blank_values=True):
        lowered = name.lower()
        if lowered in drop:
            continue
        # A session identifier can also appear under an unlisted name; a long pure-hex
        # value under a short name is the recognisable shape.
        if len(lowered) <= 12 and _SESSION_VALUE.match(value or ""):
            continue
        kept.append((name, value))
    kept.sort(key=lambda pair: (pair[0], pair[1]))
    return urlencode(kept)


def dedupe_key(url, tracking_params=(), session_params=()):
    """Identity form used for the visited set. Never fetched."""
    normalized = normalize(url, tracking_params=tracking_params,
                           session_params=session_params)
    if normalized is None:
        return None
    parts = urlsplit(normalized)
    path = parts.path
    if path.endswith("/") and path != "/":
        path = path[:-1]
    if path == "":
        path = "/"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))


def same_origin(url_a, url_b):
    a, b = urlsplit(url_a), urlsplit(url_b)
    return (a.scheme, a.hostname, a.port) == (b.scheme, b.hostname, b.port)


def same_site(url_a, url_b):
    """Same registrable host, ignoring a leading `www.` and the scheme.

    Deliberately conservative: an audit follows links inside one host, and treating a
    subdomain as a different site is the safer error, because over-crawling is a real
    harm to the audited site while under-crawling is recorded honestly in coverage.
    """
    def host(url):
        name = (urlsplit(url).hostname or "").lower()
        return name[4:] if name.startswith("www.") else name
    return host(url_a) == host(url_b)


def path_of(url):
    return urlsplit(url).path or "/"


def query_keys(url):
    query = urlsplit(url).query
    if not query:
        return []
    return sorted({name.lower() for name, _ in parse_qsl(query, keep_blank_values=True)})


def depth(url):
    """Number of non-empty path segments. The homepage is depth 0."""
    return len([s for s in path_of(url).split("/") if s])


def _skeleton_segment(segment):
    stem, extension = _split_extension(segment)
    if _UUID.match(stem):
        return "{id}" + extension
    if _YEAR_MONTH.match(stem) or _YEAR.match(stem):
        return "{date}" + extension
    if _NUMERIC.match(stem):
        return "{n}" + extension
    if _HEX.match(stem):
        return "{id}" + extension
    if stem.lower() in RESERVED_HYPHENATED:
        return segment.lower()
    if "-" in stem and len(stem) >= SLUG_MIN_LENGTH:
        return "{slug}" + extension
    if len(stem) >= 24:
        return "{slug}" + extension
    return segment.lower()


def path_skeleton(url):
    """A template key: the path with variable segments replaced by placeholders.

    `/products/velocity-x9` becomes `/products/{slug}`.
    `/blog/2026/09/a-long-title` becomes `/blog/{date}/{n}/{slug}`.

    Query parameter *names* are appended (values are not), so faceted navigation collapses
    into one template instead of exploding the cluster count.
    """
    path = path_of(url)
    trailing = path.endswith("/") and path != "/"
    segments = [s for s in path.split("/") if s]
    if not segments:
        skeleton = "/"
    else:
        skeleton = "/" + "/".join(_skeleton_segment(s) for s in segments)
        if trailing:
            skeleton += "/"
    keys = query_keys(url)
    if keys:
        skeleton += "?" + "&".join(keys)
    return skeleton


def is_probably_non_html(url):
    """Extension-based pre-filter so the crawler does not spend budget on binaries."""
    path = path_of(url).lower()
    _, extension = _split_extension(path.rsplit("/", 1)[-1])
    return extension in {
        ".pdf", ".zip", ".gz", ".tar", ".rar", ".7z", ".doc", ".docx", ".xls", ".xlsx",
        ".ppt", ".pptx", ".csv", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico",
        ".mp4", ".webm", ".mp3", ".wav", ".avi", ".mov", ".woff", ".woff2", ".ttf",
        ".eot", ".js", ".css", ".rss", ".atom", ".dmg", ".exe", ".apk",
    }


def is_document(url):
    """A linked document that may hold facts the linking page does not state in text."""
    path = path_of(url).lower()
    _, extension = _split_extension(path.rsplit("/", 1)[-1])
    return extension in {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"}
