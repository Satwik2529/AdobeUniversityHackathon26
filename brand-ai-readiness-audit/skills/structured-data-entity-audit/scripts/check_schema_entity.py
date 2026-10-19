#!/usr/bin/env python3
"""Detect why a machine that can read a page still cannot tell what it is about or which
real-world brand it belongs to.

Funnel gate: **understood**. Pure snapshot consumer: this script makes no network
requests of any kind, no code path in it could, and it does not independently crawl,
fetch, or parse anything the collector did not already capture.

Design rules, enforced here and not merely documented:

  * **No evidence, no finding.** Every finding quotes an observed value from the
    snapshot. Where the snapshot cannot establish something, that dimension is
    `not_assessed`, never guessed into a defect.
  * **Absence is not automatically a defect.** A brochure site with no products is
    complete without Product markup. A site that never claims a fact cannot contradict
    itself about it.
  * **Only genuine contradictions are findings.** Capitalisation, punctuation, harmless
    URL-normalisation and legitimate type differences are not contradictions. Two
    representations of the same entity that merely differ in optional detail are not a
    conflict; two that assert different values for the same property are.
  * **Snapshot content is untrusted data.** JSON-LD payloads, Microdata values and page
    text are quoted and compared. Nothing here executes them or lets them change which
    checks run.

Usage:
  check_schema_entity.py --snapshot snapshot.json --out findings-schema.json

Exit codes: 0 ok, 2 bad arguments, 3 the snapshot could not be read.
"""
import argparse
import json
import os
import re
import sys
from urllib.parse import urlsplit

DETECTOR = "structured-data-entity-audit"

# --------------------------------------------------------------------------- thresholds
THRESHOLDS = {
    "min_cluster_for_template": 3,
    "min_pages_for_schema_only_no_visible": 2,
    # A property-level fact worth comparing only once a page carries enough of its own
    # text to plausibly restate the structured claim at all.
    "min_main_text_for_comparison": 40,
    # Below this the whole sample is too small for a sitewide organization-identity
    # claim to mean anything more than "one page looked odd".
    "min_pages_for_identity_claims": 1,
}

UTILITY_TYPES = {"utility"}
CONFIDENT = {"high", "medium"}

# Common legal-entity suffixes, stripped before comparing organisation names. This list
# is generic across jurisdictions, not tied to any brand.
_LEGAL_SUFFIXES = re.compile(
    r"\b(ltd\.?|limited|llc|l\.l\.c\.?|inc\.?|incorporated|corp\.?|corporation|"
    r"gmbh|plc|co\.?|company|s\.a\.?|sa|ag|nv|bv|pte\.?|pty\.?)\b\.?\s*$",
    re.I)

_CURRENCY_SYMBOLS = {"£": "GBP", "$": "USD", "€": "EUR", "¥": "JPY"}
_KNOWN_CODES = {"GBP", "USD", "EUR", "JPY", "CAD", "AUD", "CHF", "NZD", "SEK", "NOK"}
_PRICE_CODE_AFTER = re.compile(
    r"([£$€¥]?)\s*(\d[\d,]*(?:\.\d+)?)\s*(GBP|USD|EUR|JPY|CAD|AUD|CHF|NZD|SEK|NOK)\b", re.I)
_PRICE_CODE_BEFORE = re.compile(
    r"(GBP|USD|EUR|JPY|CAD|AUD|CHF|NZD|SEK|NOK)\s*(\d[\d,]*(?:\.\d+)?)", re.I)
_PRICE_SYMBOL = re.compile(r"([£$€¥])\s*(\d[\d,]*(?:\.\d+)?)")

_ABSOLUTE_URL = re.compile(r"^https?://", re.I)


def _normalize_amount_string(raw):
    """A currency amount to a plain float-parseable string, handling both decimal
    conventions. "59.00" and "59,00" (French/German decimal comma) must normalise to
    the same value; "1,234.56" and "1.234,56" (US vs EU thousands+decimal) must too.
    Never guesses across a genuine ambiguity it cannot resolve; the caller treats a
    ValueError from float() as "not confidently parseable" and skips the comparison.
    """
    s = raw.strip()
    has_comma, has_period = "," in s, "." in s
    if has_comma and has_period:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif has_comma:
        head, _, tail = s.rpartition(",")
        if len(tail) == 2 and tail.isdigit():
            # the last comma is a decimal separator; anything earlier is thousands
            s = head.replace(",", "") + "." + tail
        else:
            s = s.replace(",", "")
    return s


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


# ------------------------------------------------------------------------------- helpers
# flatten_jsonld / types_of intentionally mirror site-snapshot-collector/scripts/
# htmlparse.py's functions of the same name. Duplicated rather than imported so this
# skill remains a standalone, independently portable unit (matching the convention
# already established by crawl-access-audit and render-readability-audit, neither of
# which imports across skill boundaries). Behaviour is identical and covered by this
# detector's own tests.

# Properties that commonly embed a typed entity directly rather than by reference.
# "mainEntity" (ContactPage/FAQPage/QAPage), "author" and "publisher" (Article) are the
# well-known schema.org conventions used this way. This list is deliberately small and
# named, not a blind full-tree walk: an unbounded recursive search through every
# property of every node would also descend into unrelated structures (an Offer's
# "seller", a Product's "brand", geographic data, and so on) with no clear stopping
# point, turning "find the entity" into "guess which of dozens of nested objects might
# be one". A node embedded under one of these named properties is unambiguously being
# asserted as an entity in its own right by the page; that is what makes it safe to
# also treat as an independent node for identity comparison.
_ENTITY_NESTING_PROPS = ("mainEntity", "author", "publisher")


def flatten_jsonld(blocks):
    """Every JSON-LD node reachable from the given blocks.

    Walks @graph and arrays (mirroring site-snapshot-collector's function of the same
    name, used for page-type classification) and additionally descends into the small,
    named set of properties in _ENTITY_NESTING_PROPS, so a Q&A page's own embedded
    Organization (schema.org's own recommended pattern for a ContactPage, for example)
    is not invisible to entity-identity comparison.
    """
    nodes = []
    seen_ids = set()

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            if "@graph" in node:
                walk(node["@graph"])
            marker = id(node)
            if marker not in seen_ids:
                seen_ids.add(marker)
                nodes.append(node)
            for prop in _ENTITY_NESTING_PROPS:
                nested = node.get(prop)
                if isinstance(nested, dict) and "@type" in nested:
                    walk(nested)

    for block in blocks or []:
        if block.get("parse_ok"):
            walk(block.get("data"))
    return nodes


def types_of(node):
    raw = node.get("@type") if isinstance(node, dict) else None
    if raw is None:
        return []
    values = raw if isinstance(raw, list) else [raw]
    out = []
    for value in values:
        if isinstance(value, str):
            out.append(value.rsplit("/", 1)[-1].rsplit("#", 1)[-1])
    return out


def has_type(node, *names):
    lowered = {t.lower() for t in types_of(node)}
    return bool(lowered & {n.lower() for n in names})


def norm_ws(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def norm_name(s):
    """Case, whitespace and legal-suffix normalised, for identity comparison."""
    s = norm_ws(s).casefold()
    s = _LEGAL_SUFFIXES.sub("", s).strip()
    s = re.sub(r"[.,]+$", "", s).strip()
    return s


def names_match(a, b):
    """Same brand name, tolerant of word order and legal-suffix differences.

    A descriptor translated for grammar can reorder words while naming the same
    brand (English "Larkspur Instruments" vs French "Instruments Larkspur" -- the
    same two words). Comparing as an order-independent token set, rather than
    substring or exact-string equality, is what makes that harmless. A genuine name
    change (different words, not just a different order) still fails this check.
    """
    a, b = norm_name(a), norm_name(b)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    words_a, words_b = set(a.split()), set(b.split())
    if not words_a or not words_b:
        return False
    return words_a == words_b or words_a <= words_b or words_b <= words_a


def norm_phone(s):
    if not s:
        return None
    digits = re.sub(r"[^\d+]", "", s)
    return digits or None


def norm_text_value(s):
    return norm_ws(s).casefold().strip(".,;:")


def norm_host(url):
    try:
        host = (urlsplit(url or "").hostname or "").lower()
    except ValueError:
        return None
    return host[4:] if host.startswith("www.") else host


def is_absolute_url(s):
    return bool(s) and bool(_ABSOLUTE_URL.match(s.strip()))


def extract_price_from_text(text):
    """Best-effort (amount, currency_code) from free text. None if not confident.

    Deliberately conservative: only fires on an explicit ISO code or a symbol this
    project maps unambiguously. A bare number with no currency marker is not treated as
    a price, because there is nothing to compare it against safely.
    """
    if not text:
        return None
    for pattern, order in ((_PRICE_CODE_AFTER, ("amount", "code")),
                          (_PRICE_CODE_BEFORE, ("code", "amount"))):
        match = pattern.search(text)
        if match:
            groups = match.groups()
            if pattern is _PRICE_CODE_AFTER:
                symbol, amount, code = groups
                code = code.upper()
                if symbol and _CURRENCY_SYMBOLS.get(symbol) not in (None, code):
                    continue  # symbol and code disagree; not confident
            else:
                code, amount = groups
                code = code.upper()
            try:
                return round(float(_normalize_amount_string(amount)), 2), code
            except ValueError:
                continue
    match = _PRICE_SYMBOL.search(text)
    if match:
        symbol, amount = match.groups()
        code = _CURRENCY_SYMBOLS.get(symbol)
        if code:
            try:
                return round(float(_normalize_amount_string(amount)), 2), code
            except ValueError:
                return None
    return None


def price_from_offer(offer):
    if not isinstance(offer, dict):
        return None
    price = offer.get("price")
    currency = offer.get("priceCurrency")
    if price is None or not currency:
        return None
    try:
        amount = round(float(_normalize_amount_string(str(price))), 2)
    except (TypeError, ValueError):
        return None
    return amount, str(currency).upper()


def get_offer(node):
    offers = node.get("offers") if isinstance(node, dict) else None
    if isinstance(offers, list):
        offers = offers[0] if offers else None
    return offers if isinstance(offers, dict) else None


def microdata_organization_facts(items):
    """Best-effort Organization-shaped facts from Microdata items, or None."""
    for item in items or []:
        itemtype = (item.get("itemtype") or "")
        if itemtype.rsplit("/", 1)[-1].lower() != "organization":
            continue
        props = item.get("props") or {}
        return {"name": props.get("name"), "url": props.get("url"),
               "telephone": props.get("telephone")}
    return None


# ------------------------------------------------------------------------------- finding

def finding(check_id, title, gate_impact, reach, certainty, funnel_stage, evidence,
            urls, detail, action, severity_ceiling=None, related=None):
    entry = {
        "check_id": check_id,
        "title": title,
        "gate_impact": gate_impact,
        "reach": reach,
        "certainty": certainty,
        "funnel_stage": funnel_stage,
        "detector": DETECTOR,
        "evidence": evidence,
        "affected_urls": sorted(set(urls))[:20],
        "evidence_detail": dict(detail, check_id=check_id, detector=DETECTOR),
        "suggested_action": action,
    }
    if severity_ceiling:
        entry["severity_ceiling"] = severity_ceiling
    if related:
        entry["related_checks"] = related
    return entry


# ------------------------------------------------------------------------------- context

class PageSchema(object):
    """Structured-data view of one page, computed once."""

    def __init__(self, page):
        self.page = page
        self.url = page["url"]
        sd = page.get("structured_data") or {}
        self.jsonld_blocks = sd.get("jsonld") or []
        self.jsonld_nodes = flatten_jsonld(self.jsonld_blocks)
        self.microdata_items = sd.get("microdata_items") or []
        self.microdata_types = sd.get("microdata_types") or []
        self.rdfa_types = sd.get("rdfa_types") or []
        self.invalid_blocks = [b for b in self.jsonld_blocks if not b.get("parse_ok")]
        self.has_any_structured_data = bool(
            any(b.get("parse_ok") for b in self.jsonld_blocks)
            or self.microdata_types or self.rdfa_types)

    def nodes_of_type(self, *names):
        return [n for n in self.jsonld_nodes if has_type(n, *names)]


class Context(object):

    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.pages = snapshot.get("pages") or []
        self.clusters = snapshot.get("clusters") or []
        self.fetched = [p for p in self.pages if p.get("fetch_ok")]
        self.blackout = bool(self.pages) and not self.fetched
        self.schemas = {p["url"]: PageSchema(p) for p in self.fetched}
        self.content = [p for p in self.fetched if self._is_confident_content(p)]
        self.homepage = self._find_homepage()
        self.not_assessed = []

    @staticmethod
    def _is_confident_content(page):
        if page.get("page_type") in UTILITY_TYPES and page.get(
                "page_type_confidence") in CONFIDENT:
            return False
        if page.get("page_type_confidence") in CONFIDENT and page.get(
                "page_type") not in (None, "unknown"):
            return True
        return page.get("main_text_len", 0) >= 250

    def _find_homepage(self):
        for page in self.fetched:
            if page.get("page_type") == "homepage":
                return page
        return None

    def note(self, dimension, reason):
        if not any(item["dimension"] == dimension for item in self.not_assessed):
            self.not_assessed.append({"dimension": dimension, "reason": reason,
                                      "detector": DETECTOR})


def cluster_index(clusters):
    return {c["id"]: c for c in clusters}


def reach_for(pages_hit, population, clusters):
    if not pages_hit:
        return "page"
    if population and len(pages_hit) == len(population) and len(pages_hit) >= 2:
        return "sitewide"
    by_cluster = {}
    for page in pages_hit:
        by_cluster.setdefault(page.get("cluster_id"), []).append(page)
    index = cluster_index(clusters)
    for cluster_id, members in by_cluster.items():
        cluster = index.get(cluster_id) or {}
        sampled = cluster.get("sampled") or []
        if (cluster.get("size", 0) >= THRESHOLDS["min_cluster_for_template"]
                and sampled and len(members) == len(sampled)):
            return "template"
    return "page"


# =================================================================== presence and parsing

def check_no_structured_data(ctx):
    if not ctx.content:
        return []
    any_sd = any(ctx.schemas[p["url"]].has_any_structured_data for p in ctx.content
                if p["url"] in ctx.schemas)
    if any_sd:
        return []
    findings = [finding(
        "SDE.NO_STRUCTURED_DATA",
        "No structured data of any kind was found on the sampled pages",
        "degrades", "sitewide", "measured", "understood",
        "None of the %d sampled content pages carry JSON-LD, Microdata or RDFa. A "
        "machine can read the text but has no explicit signal for what kind of thing "
        "each page describes or which entity it belongs to."
        % len(ctx.content),
        [p["url"] for p in ctx.content],
        {"method": "presence of any parseable JSON-LD, Microdata itemtype or RDFa "
                   "typeof, checked across every sampled content page",
         "observed": {"pages_checked": len(ctx.content), "structured_data_found": 0},
         "expected": "at least some structured data, of any of the three formats",
         "sample": {"checked": len(ctx.content), "failing": len(ctx.content)},
         "confidence": "high", "nondeterministic": False},
        {"summary": "Add structured data for at least the organisation identity and "
                    "the page types this site actually has, in JSON-LD.",
         "how": ["Start with an Organization node on the homepage.",
                 "Add the type each template warrants: Product for product pages, "
                 "Article for editorial content, and so on.",
                 "JSON-LD in a single script block in the page head is the easiest to "
                 "maintain and validate."],
         "mechanism": "Structured data lets a machine classify content and resolve "
                      "which real-world entity a page is about, without inferring it "
                      "from prose. Its absence does not block reading the page, but it "
                      "leaves classification to inference, which is less reliable.",
         "effort": "template-change", "owner": "engineering",
         "verification": "Run the page through a structured-data validator and confirm "
                         "at least one recognised type is detected."})]
    return findings


def check_invalid_jsonld(ctx):
    findings = []
    hits = []
    for page in ctx.content:
        schema = ctx.schemas.get(page["url"])
        if schema and schema.invalid_blocks:
            hits.append((page, schema.invalid_blocks))
    if not hits:
        return findings
    reach = reach_for([p for p, _ in hits], ctx.content, ctx.clusters)
    example = hits[0]
    findings.append(finding(
        "SDE.INVALID_JSONLD",
        "A JSON-LD block fails to parse",
        "degrades", reach, "measured", "understood",
        "%d pages carry a JSON-LD script block that does not parse as valid JSON. "
        "Example: %s: %s. A single syntax error voids that entire block; there is no "
        "visible error on the page, so this is invisible without checking the markup "
        "directly."
        % (len(hits), example[0]["url"], example[1][0].get("error", "parse error")),
        [p["url"] for p, _ in hits],
        {"method": "JSON parse of every application/ld+json script block found in the "
                   "raw HTML",
         "observed": {"pages": [{"url": p["url"],
                                 "errors": [b.get("error") for b in blocks]}
                                for p, blocks in hits[:8]]},
         "expected": "every JSON-LD block parses as valid JSON",
         "sample": {"checked": len(ctx.content), "failing": len(hits)},
         "confidence": "high", "nondeterministic": False},
        {"summary": "Fix the JSON syntax error in each listed block; validate JSON-LD "
                    "in the build pipeline so a malformed block cannot ship.",
         "how": ["Open the exact block named in the evidence and check for a trailing "
                 "comma, an unescaped quote, or a missing bracket.",
                 "Add a JSON-LD lint step to the build so this is caught before "
                 "deployment, not after."],
         "mechanism": "A JSON-LD block that fails to parse contributes nothing: the "
                      "whole block is discarded, silently, with no visible symptom on "
                      "the page itself.",
         "effort": "trivial", "owner": "engineering",
         "verification": "Re-parse the page's JSON-LD blocks and confirm all parse."}))
    return findings


# ============================================================= type and property coverage

_TYPE_PROFILES = {
    "product": {"types": ("Product",), "required": ("name", "offers")},
    "article": {"types": ("Article", "BlogPosting", "NewsArticle"),
               "required": ("headline", "datePublished")},
}


def check_missing_type_for_template(ctx):
    findings = []
    for page_type, profile in _TYPE_PROFILES.items():
        candidates = [p for p in ctx.content if p.get("page_type") == page_type]
        if not candidates:
            continue
        missing = [p for p in candidates
                  if not ctx.schemas[p["url"]].nodes_of_type(*profile["types"])
                  and not any(t.rsplit("/", 1)[-1] in profile["types"]
                             for t in ctx.schemas[p["url"]].microdata_types)]
        if not missing:
            continue
        reach = reach_for(missing, candidates, ctx.clusters)
        findings.append(finding(
            "SDE.MISSING_TYPE_FOR_TEMPLATE",
            "%s pages carry no %s structured data" % (page_type.title(),
                                                       "/".join(profile["types"])),
            "degrades", reach, "measured", "understood",
            "%d of %d sampled %s pages have no %s markup, in JSON-LD or Microdata. "
            "Examples: %s."
            % (len(missing), len(candidates), page_type, "/".join(profile["types"]),
               ", ".join(p["url"] for p in missing[:3])),
            [p["url"] for p in missing],
            {"method": "presence of a JSON-LD node (after full @graph traversal) or a "
                       "Microdata item of the expected type, on pages classified as "
                       "%s with confident classification" % page_type,
             "observed": {"pages_missing": [p["url"] for p in missing[:10]]},
             "expected": "%s markup on every %s page" % (
                 "/".join(profile["types"]), page_type),
             "sample": {"checked": len(candidates), "failing": len(missing)},
             "confidence": "high", "nondeterministic": False},
            {"summary": "Add %s structured data to this template, in JSON-LD, "
                        "covering at least: %s."
                        % ("/".join(profile["types"]), ", ".join(profile["required"])),
             "how": ["Emit the markup from the same data the template already renders, "
                     "so it cannot drift from the visible page.",
                     "Validate with a structured-data validator after deployment."],
             "mechanism": "The type a template warrants is the strongest signal a "
                          "machine has for classifying that page's content and "
                          "resolving what it is about, distinct from inferring it from "
                          "prose alone.",
             "effort": "template-change", "owner": "engineering",
             "verification": "Re-check the page and confirm the type is present and "
                             "parses."}))
    return findings


def check_incomplete_required_props(ctx):
    findings = []
    for page_type, profile in _TYPE_PROFILES.items():
        candidates = [p for p in ctx.content if p.get("page_type") == page_type]
        hits = []
        for page in candidates:
            nodes = ctx.schemas[page["url"]].nodes_of_type(*profile["types"])
            if not nodes:
                continue
            node = nodes[0]
            missing_props = [prop for prop in profile["required"]
                             if not node.get(prop)]
            if missing_props:
                hits.append((page, missing_props))
        if not hits:
            continue
        reach = reach_for([p for p, _ in hits], candidates, ctx.clusters)
        example = hits[0]
        findings.append(finding(
            "SDE.INCOMPLETE_REQUIRED_PROPS",
            "%s markup is present but missing required properties" % page_type.title(),
            "weakens", reach, "measured", "understood",
            "%d pages have %s markup but are missing: %s. Example: %s is missing %s."
            % (len(hits), "/".join(profile["types"]),
               sorted(set(p2 for _, ps in hits for p2 in ps)),
               example[0]["url"], example[1]),
            [p["url"] for p, _ in hits],
            {"method": "presence of each required property on the first matching "
                       "JSON-LD node of the expected type",
             "observed": {"pages": [{"url": p["url"], "missing": ps}
                                    for p, ps in hits[:8]]},
             "expected": "%s present on every instance" % ", ".join(profile["required"]),
             "sample": {"checked": len(candidates), "failing": len(hits)},
             "confidence": "high", "nondeterministic": False},
            {"summary": "Add the missing required properties to the existing markup "
                        "block.",
             "how": ["Populate each missing property listed in the evidence from the "
                     "same source the visible page already uses."],
             "mechanism": "A type declared without its required properties is "
                          "incomplete data: a machine can tell what kind of thing the "
                          "page is about but not the specific facts that make it "
                          "useful to cite.",
             "effort": "template-change", "owner": "engineering",
             "verification": "Re-check the markup and confirm the properties are "
                             "present with real values."}))
    return findings


# ===================================================== structured vs visible consistency

def check_schema_visible_mismatch(ctx):
    findings = []
    price_hits, name_hits = [], []

    for page in ctx.content:
        schema = ctx.schemas[page["url"]]
        main_text = page.get("main_text") or ""
        if len(main_text) < THRESHOLDS["min_main_text_for_comparison"]:
            continue

        for node in schema.nodes_of_type("Product"):
            # Price and name are independent comparisons. An earlier version nested
            # the name check inside the price check's early exits, so a page with an
            # unparseable or absent visible price silently skipped the name comparison
            # too, even though the two facts have nothing to do with each other.
            structured = price_from_offer(get_offer(node))
            if structured is not None:
                visible = extract_price_from_text(main_text)
                if (visible is not None and structured[1] == visible[1]
                        and abs(structured[0] - visible[0]) > 0.001):
                    price_hits.append((page, structured, visible))
                # else: no visible price, or a different currency, or they agree --
                # none of that is comparable evidence either way, so stay silent.

            node_name = node.get("name")
            h1_texts = [h.get("text") for h in page.get("headings") or []
                       if h.get("level") == 1 and h.get("text")]
            if node_name and h1_texts:
                if not any(names_match(node_name, h1) for h1 in h1_texts):
                    name_hits.append((page, node_name, h1_texts[0]))

    if price_hits:
        reach = reach_for([p for p, _, _ in price_hits], ctx.content, ctx.clusters)
        example = price_hits[0]
        findings.append(finding(
            "SDE.SCHEMA_VISIBLE_MISMATCH",
            "A structured price contradicts the visible price on the same page",
            "degrades", reach, "measured", "understood",
            "%d pages declare a structured price that does not match a price stated in "
            "the page's own visible text, in the same currency. Example: %s: markup "
            "says %.2f %s, the visible text says %.2f %s."
            % (len(price_hits), example[0]["url"], example[1][0], example[1][1],
               example[2][0], example[2][1]),
            [p["url"] for p, _, _ in price_hits],
            {"method": "Product.offers.price/priceCurrency compared against a price "
                       "pattern extracted from the page's own main text, matched only "
                       "when both sides resolve to the same currency",
             "observed": {"pages": [{"url": p["url"], "structured": list(s),
                                     "visible": list(v)}
                                    for p, s, v in price_hits[:8]]},
             "expected": "the structured price and the visible price agree",
             "sample": {"checked": len(ctx.content), "failing": len(price_hits)},
             "confidence": "high", "nondeterministic": False},
            {"summary": "Make one source of truth drive both the visible price and the "
                        "structured price so they cannot drift apart.",
             "how": ["Find where the two values are set independently (often a "
                     "template constant next to a CMS-driven price, or a stale build).",
                     "Generate both from the same field."],
             "mechanism": "A contradictory machine-readable value is worse than no "
                          "markup at all: it gives a specific, wrong number equal "
                          "billing with the correct one, and a system has no way to "
                          "know which to trust.",
             "effort": "template-change", "owner": "engineering",
             "verification": "Re-check the page and confirm both values match exactly."}))

    if name_hits:
        reach = reach_for([p for p, _, _ in name_hits], ctx.content, ctx.clusters)
        example = name_hits[0]
        findings.append(finding(
            "SDE.SCHEMA_VISIBLE_MISMATCH",
            "A structured product name does not match the page's own heading",
            "degrades", reach, "measured", "understood",
            "%d pages declare a Product name in structured data that shares no "
            "overlap with the page's own h1. Example: %s: markup says %r, the h1 says "
            "%r."
            % (len(name_hits), example[0]["url"], example[1], example[2]),
            [p["url"] for p, _, _ in name_hits],
            {"method": "Product.name compared against the page's own h1 text, after "
                       "case and whitespace normalisation, allowing either to be a "
                       "substring of the other",
             "observed": {"pages": [{"url": p["url"], "structured_name": n, "h1": h}
                                    for p, n, h in name_hits[:8]]},
             "expected": "the structured name and the h1 refer to the same product",
             "sample": {"checked": len(ctx.content), "failing": len(name_hits)},
             "confidence": "high", "nondeterministic": False},
            {"summary": "Generate the structured name from the same field that "
                        "populates the h1, rather than a separately maintained value.",
             "how": ["Point the Product.name field at the same template variable that "
                     "renders the h1."],
             "mechanism": "A page whose markup names a different product than its own "
                          "heading describes a materially different entity than the "
                          "one a visitor and a crawler both see on the page.",
             "effort": "template-change", "owner": "engineering",
             "verification": "Re-check the page and confirm the structured name and "
                             "the h1 refer to the same thing."}))
    return findings


def check_schema_only_no_visible(ctx):
    findings = []
    hits = []
    for page in ctx.content:
        schema = ctx.schemas[page["url"]]
        main_text = page.get("main_text") or ""
        for node in schema.nodes_of_type("Product"):
            structured = price_from_offer(get_offer(node))
            if structured is None:
                continue
            if len(main_text) < THRESHOLDS["min_main_text_for_comparison"]:
                continue
            if extract_price_from_text(main_text) is None:
                hits.append((page, structured))

    if len(hits) < THRESHOLDS["min_pages_for_schema_only_no_visible"]:
        return findings
    reach = reach_for([p for p, _ in hits], ctx.content, ctx.clusters)
    example = hits[0]
    findings.append(finding(
        "SDE.SCHEMA_ONLY_NO_VISIBLE",
        "A structured price has no visible counterpart on the page",
        "degrades", reach, "measured", "understood",
        "%d pages declare a structured price with no comparable price stated anywhere "
        "in the page's own visible text. Example: %s declares %.2f %s in markup but "
        "states no price in its own text."
        % (len(hits), example[0]["url"], example[1][0], example[1][1]),
        [p["url"] for p, _ in hits],
        {"method": "Product.offers.price present in structured data with no price "
                   "pattern found anywhere in the page's own main text",
         "observed": {"pages": [{"url": p["url"], "structured_price": list(s)}
                                for p, s in hits[:8]]},
         "expected": "a claim made in markup is also stated to a human reader",
         "sample": {"checked": len(ctx.content), "failing": len(hits)},
         "confidence": "medium", "nondeterministic": False,
         "note": "text extraction cannot rule out a price shown only as an image or "
                 "widget; this is reported as a gap between the two signals, not a "
                 "certain absence"},
        {"summary": "State the same price in the page's own visible text, not only in "
                    "markup.",
         "how": ["Add the price as plain text next to wherever it is currently shown "
                 "(an image, a script-rendered widget, or omitted from the page "
                 "entirely)."],
         "mechanism": "Markup that asserts a fact the page itself never states to a "
                      "reader is disconnected from the page's actual meaning, and is "
                      "the kind of pattern that gets structured data ignored or "
                      "penalised as unreliable.",
         "effort": "content", "owner": "content",
         "verification": "Re-check the page's visible text and confirm the price "
                         "appears in it."}))
    return findings


# ============================================================================= identity

def check_no_organization_node(ctx):
    if not ctx.homepage:
        ctx.note("organization identity",
                 "no page in the sample was classified as the homepage, so identity "
                 "could not be checked")
        return []
    schema = ctx.schemas.get(ctx.homepage["url"])
    if not schema:
        return []
    org_nodes = schema.nodes_of_type("Organization", "LocalBusiness", "Corporation")
    micro_org = microdata_organization_facts(schema.microdata_items)
    rdfa_org = any(t.rsplit("/", 1)[-1].lower() in ("organization", "localbusiness")
                  for t in schema.rdfa_types)
    if org_nodes or micro_org or rdfa_org:
        return []
    return [finding(
        "SDE.NO_ORGANIZATION_NODE",
        "The homepage declares no organization or local-business entity",
        "degrades", "sitewide", "measured", "understood",
        "The homepage (%s) has no Organization, LocalBusiness or equivalent entity in "
        "its JSON-LD, Microdata or RDFa, after traversing any @graph fully. There is no "
        "explicit machine-readable statement of which brand this site belongs to."
        % ctx.homepage["url"],
        [ctx.homepage["url"]],
        {"method": "JSON-LD @graph traversal, Microdata itemtype and RDFa typeof "
                   "checked for an Organization, LocalBusiness or Corporation node on "
                   "the homepage",
         "observed": {"jsonld_types_found": schema.jsonld_nodes and
                     sorted({t for n in schema.jsonld_nodes for t in types_of(n)}) or [],
                     "microdata_types_found": schema.microdata_types,
                     "rdfa_types_found": schema.rdfa_types},
         "expected": "an Organization or LocalBusiness node on the homepage",
         "sample": {"checked": 1, "failing": 1},
         "confidence": "high", "nondeterministic": False},
        {"summary": "Add one Organization (or LocalBusiness, if there is a physical "
                    "location) node to the homepage, in JSON-LD, with a stable "
                    "identifier.",
         "how": ["Include at minimum name, url, and logo.",
                 "Give it an @id so other structured data on the site can reference it "
                 "rather than duplicating it.",
                 "Add sameAs links to profiles the brand actually controls."],
         "mechanism": "This is the single node a system uses to resolve 'this site' "
                      "into 'this real-world brand'. Without it, every other page's "
                      "content is attributed to an inferred entity rather than a "
                      "declared one.",
         "effort": "template-change", "owner": "engineering",
         "verification": "Fetch the homepage and confirm an Organization node with a "
                         "name and url parses successfully."})]


def check_sameas_and_stable_id(ctx):
    findings = []
    if not ctx.homepage:
        return findings
    schema = ctx.schemas.get(ctx.homepage["url"])
    if not schema:
        return findings
    org_nodes = schema.nodes_of_type("Organization", "LocalBusiness", "Corporation")
    if not org_nodes:
        return findings
    org = org_nodes[0]

    same_as = org.get("sameAs")
    same_as_list = same_as if isinstance(same_as, list) else (
        [same_as] if same_as else [])
    if not same_as_list:
        findings.append(finding(
            "SDE.NO_SAMEAS",
            "The organization entity has no identity links",
            "weakens", "sitewide", "measured", "understood",
            "The Organization node on the homepage (%s) declares no sameAs property. "
            "There are no links to independent profiles a system could use to confirm "
            "this is the same real-world brand it may already know from elsewhere."
            % ctx.homepage["url"],
            [ctx.homepage["url"]],
            {"method": "presence of a non-empty sameAs property on the homepage's "
                       "Organization node",
             "observed": {"sameAs": same_as},
             "expected": "one or more sameAs links to profiles the brand controls",
             "sample": {"checked": 1, "failing": 1},
             "confidence": "high", "nondeterministic": False},
            {"summary": "Add sameAs links to profiles the brand actually controls or "
                        "is represented on (its own social profiles, a Wikidata or "
                        "Wikipedia entry if one exists, a company registry listing).",
             "how": ["List only profiles the brand controls or that are independently "
                     "authoritative about it.",
                     "Never add a link purely to satisfy this check; an irrelevant or "
                     "unrelated link is worse than none."],
             "mechanism": "sameAs links a site to profiles a system may already trust, "
                          "turning 'probably this company' into 'this company'.",
             "effort": "trivial", "owner": "marketing",
             "verification": "Re-check the Organization node and confirm each sameAs "
                             "URL resolves to a real, brand-controlled profile."}))
    else:
        malformed = [s for s in same_as_list if not is_absolute_url(s)]
        if malformed:
            findings.append(finding(
                "SDE.SAMEAS_MALFORMED",
                "sameAs entries are not valid absolute URLs",
                "weakens", "sitewide", "measured", "understood",
                "%d of %d sameAs entries on the homepage's Organization node are not "
                "absolute URLs. Examples: %s."
                % (len(malformed), len(same_as_list), ", ".join(repr(m) for m in
                                                                malformed[:3])),
                [ctx.homepage["url"]],
                {"method": "syntactic check that each sameAs entry starts with http:// "
                           "or https://; no URL is fetched",
                 "observed": {"malformed": malformed, "total": len(same_as_list)},
                 "expected": "every sameAs entry is an absolute http(s) URL",
                 "sample": {"checked": len(same_as_list), "failing": len(malformed)},
                 "confidence": "high", "nondeterministic": False},
                {"summary": "Correct each malformed sameAs entry to a full absolute "
                            "URL.",
                 "how": ["Add the missing scheme and host to each entry listed in the "
                         "evidence."],
                 "mechanism": "A relative or malformed URL cannot be resolved by a "
                              "system reading the markup in isolation from the page "
                              "it came from.",
                 "effort": "trivial", "owner": "engineering",
                 "verification": "Re-check each sameAs entry and confirm it is a "
                                 "well-formed absolute URL."},
                severity_ceiling="low"))

    if not org.get("@id"):
        findings.append(finding(
            "SDE.NO_STABLE_ID",
            "The organization entity has no stable identifier",
            "weakens", "sitewide", "measured", "understood",
            "The Organization node on the homepage (%s) has no @id. Other structured "
            "data on the site, such as a WebSite or ContactPage node, has no way to "
            "reference this entity directly and must duplicate its facts instead."
            % ctx.homepage["url"],
            [ctx.homepage["url"]],
            {"method": "presence of an @id property on the homepage's Organization "
                       "node",
             "observed": {"has_id": False},
             "expected": "a stable @id, typically the homepage URL plus a fragment",
             "sample": {"checked": 1, "failing": 1},
             "confidence": "high", "nondeterministic": False},
            {"summary": "Give the Organization node a stable @id (for example, the "
                        "homepage URL with a #organization fragment) and reference it "
                        "from other nodes instead of repeating its properties.",
             "how": ["Add \"@id\": \"<homepage-url>#organization\" to the node.",
                     "On other pages, reference it as {\"@id\": \"<same value>\"} "
                     "rather than re-declaring name, url and address."],
             "mechanism": "A stable identifier lets every other structured-data block "
                          "on the site point at one canonical entity instead of each "
                          "declaring its own copy, which is what keeps them from "
                          "drifting apart.",
             "effort": "template-change", "owner": "engineering",
             "verification": "Re-check the node and confirm @id is present and "
                             "referenced elsewhere on the site."},
            severity_ceiling="low"))
    return findings


def check_name_inconsistent(ctx):
    if not ctx.homepage:
        return []
    schema = ctx.schemas.get(ctx.homepage["url"])
    if not schema:
        return []
    org_nodes = schema.nodes_of_type("Organization", "LocalBusiness", "Corporation")
    if not org_nodes:
        return []
    org_name = org_nodes[0].get("name")
    if not org_name:
        return []
    normalized_org = norm_name(org_name)
    if not normalized_org:
        return []

    h1_texts = [h.get("text") for h in ctx.homepage.get("headings") or []
               if h.get("level") == 1 and h.get("text")]
    if not h1_texts:
        return []  # no homepage h1 to compare against; not assessable, not a finding

    if any(names_match(org_name, h1) for h1 in h1_texts):
        return []

    return [finding(
        "SDE.NAME_INCONSISTENT",
        "The organization name does not match the homepage's own heading",
        "weakens", "sitewide", "measured", "understood",
        "The homepage's Organization node declares the name %r, which shares no "
        "overlap with the homepage's own h1, %r, after normalising case, punctuation "
        "and common legal suffixes."
        % (org_name, ctx.homepage["headings"][0].get("text")
           if ctx.homepage.get("headings") else None),
        [ctx.homepage["url"]],
        {"method": "Organization.name compared against the homepage's own h1 text, "
                   "after normalising case, whitespace and legal suffixes such as Ltd "
                   "or Inc",
         "observed": {"organization_name": org_name,
                     "homepage_h1": [h.get("text") for h in
                                    ctx.homepage.get("headings") or []
                                    if h.get("level") == 1]},
         "expected": "the organization name and the homepage h1 name the same brand",
         "sample": {"checked": 1, "failing": 1},
         "confidence": "high", "nondeterministic": False},
        {"summary": "Use one canonical brand name and reference it consistently "
                    "between the structured Organization entity and the homepage's own "
                    "heading.",
         "how": ["Decide which name is current and correct.",
                 "Generate both the Organization.name value and the h1 from the same "
                 "source."],
         "mechanism": "A system resolving which entity a site belongs to sees two "
                      "different names for what should be one brand, which weakens "
                      "confidence in the identity resolution rather than blocking it "
                      "outright.",
         "effort": "template-change", "owner": "engineering",
         "verification": "Re-check the homepage and confirm the same name appears in "
                         "both places."})]


def check_org_identity_conflict(ctx):
    """The same @id is described with contradictory property values across pages.

    Distinct from SDE.NAME_INCONSISTENT (which compares structured data against
    on-page text signals): this compares structured node to structured node, across
    different pages, for the fields most likely to be duplicated rather than
    referenced -- telephone, address and url -- and fires only on a genuine value-level
    disagreement, never on one page simply omitting a field the other states.
    """
    by_id = {}
    for url, schema in ctx.schemas.items():
        for node in schema.jsonld_nodes:
            node_id = node.get("@id")
            if node_id and has_type(node, "Organization", "LocalBusiness",
                                    "Corporation"):
                by_id.setdefault(node_id, []).append((url, node))

    findings = []
    for node_id, occurrences in sorted(by_id.items()):
        if len(occurrences) < 2:
            continue
        conflicts = {}
        for prop, extractor in (
                ("telephone", lambda n: norm_phone(n.get("telephone"))),
                ("url", lambda n: norm_host(n.get("url"))),
                ("address", lambda n: norm_text_value(json.dumps(
                    n.get("address"), sort_keys=True)) if n.get("address") else None)):
            values = {}
            for url, node in occurrences:
                value = extractor(node)
                if value:
                    values.setdefault(value, []).append(url)
            if len(values) > 1:
                conflicts[prop] = values

        if not conflicts:
            continue
        prop, values = sorted(conflicts.items())[0]
        urls_involved = sorted({u for urls in values.values() for u in urls})
        findings.append(finding(
            "SDE.ORG_IDENTITY_CONFLICT",
            "The same organization identifier has conflicting %s across pages" % prop,
            "degrades", "sitewide", "measured", "understood",
            "The entity identified as %s appears on %d pages with %d different values "
            "for %s: %s. The same stable identifier should describe one consistent "
            "entity wherever it is referenced."
            % (node_id, len(occurrences), len(values), prop,
               "; ".join("%r on %s" % (v, ", ".join(urls[:2]))
                        for v, urls in sorted(values.items())[:4])),
            urls_involved,
            {"method": "grouping JSON-LD nodes by @id across all sampled pages, then "
                       "comparing normalised %s values between occurrences of the same "
                       "@id" % prop,
             "observed": {"entity_id": node_id, "conflicting_property": prop,
                         "values": {v: urls for v, urls in values.items()}},
             "expected": "every occurrence of the same @id agrees on identity "
                         "properties",
             "sample": {"checked": len(occurrences), "failing": len(occurrences)},
             "confidence": "high", "nondeterministic": False},
            {"summary": "Reconcile the conflicting %s value and, where possible, "
                        "reference the canonical entity by @id instead of duplicating "
                        "its properties on each page." % prop,
             "how": ["Decide which value is current and correct.",
                     "Where a page needs to mention this entity, reference "
                     '{"@id": "%s"} rather than re-declaring the property, so future '
                     "changes cannot drift apart again." % node_id],
             "mechanism": "A stable identifier is a promise that every occurrence "
                          "describes the same thing. When the values disagree, the "
                          "identifier stops being reliable and a system has no way to "
                          "know which occurrence to trust.",
             "effort": "template-change", "owner": "engineering",
             "verification": "Re-check every page referencing this @id and confirm "
                             "%s agrees everywhere." % prop}))
    return findings


def check_entity_ambiguity_risk(ctx):
    if not ctx.homepage:
        return []
    schema = ctx.schemas.get(ctx.homepage["url"])
    if not schema:
        return []
    org_nodes = schema.nodes_of_type("Organization", "LocalBusiness", "Corporation")
    org = org_nodes[0] if org_nodes else None
    name = org.get("name") if org else None
    if not name:
        return []

    signals = []
    words = re.findall(r"[A-Za-z]+", name)
    if len(words) <= 1 and len(name) <= 8:
        signals.append("the name is a single short word (%r)" % name)
    same_as = org.get("sameAs") if org else None
    if not (isinstance(same_as, list) and same_as) and not (
            isinstance(same_as, str) and same_as):
        signals.append("no sameAs identity links are declared")
    if not org.get("address") and not org.get("foundingDate"):
        signals.append("no address or founding date disambiguates the brand")

    if len(signals) < 2:
        return []

    return [finding(
        "SDE.ENTITY_AMBIGUITY_RISK",
        "The brand name may be hard to disambiguate from other things",
        "weakens", "sitewide", "inferred", "understood",
        "At least two independent risk signals are present for the name %r: %s. None "
        "of these alone would justify a finding; together they suggest a system may "
        "struggle to tell this brand apart from other things that share or resemble "
        "its name."
        % (name, "; ".join(signals)),
        [ctx.homepage["url"]],
        {"method": "count of independent ambiguity signals: short/common name, "
                   "absence of sameAs, absence of address or founding date",
         "observed": {"name": name, "signals": signals, "signal_count": len(signals)},
         "expected": "fewer than 2 ambiguity signals, or explicit disambiguating facts",
         "sample": {"checked": 1, "failing": 1},
         "confidence": "medium", "nondeterministic": False,
         "note": "this is an inferential risk assessment, not a measured defect; it "
                 "does not claim the name actually is confused with anything"},
        {"summary": "Add the distinguishing facts a system can use to tell this brand "
                    "apart from other things that share its name: sector, location, "
                    "founding date, and sameAs identity links.",
         "how": ["Add foundingDate and address to the Organization node if not "
                 "already present.",
                 "Add sameAs links to profiles the brand controls.",
                 "Use a distinguishing descriptor consistently near the brand name in "
                 "visible copy, such as the sector or location."],
         "mechanism": "A system resolving a name to a real-world entity relies on "
                      "distinguishing facts when the name itself is ambiguous. Without "
                      "them, a common or short name risks being conflated with "
                      "something else.",
         "effort": "content", "owner": "brand-ops",
         "verification": "Re-check the Organization node for the added facts."},
        severity_ceiling="medium")]


def check_microdata_only(ctx):
    if not ctx.content:
        return []
    any_jsonld = any(any(b.get("parse_ok") for b in ctx.schemas[p["url"]].jsonld_blocks)
                     for p in ctx.content if p["url"] in ctx.schemas)
    if any_jsonld:
        return []
    any_micro_or_rdfa = any(
        ctx.schemas[p["url"]].microdata_types or ctx.schemas[p["url"]].rdfa_types
        for p in ctx.content if p["url"] in ctx.schemas)
    if not any_micro_or_rdfa:
        return []
    pages_with = [p for p in ctx.content
                 if ctx.schemas[p["url"]].microdata_types
                 or ctx.schemas[p["url"]].rdfa_types]
    return [finding(
        "SDE.MICRODATA_ONLY",
        "Structured data uses Microdata or RDFa but no JSON-LD",
        "weakens", "sitewide", "measured", "understood",
        "%d sampled pages carry valid Microdata or RDFa markup and none carry JSON-LD. "
        "Microdata and RDFa are valid formats; this is a migration suggestion, not a "
        "defect."
        % len(pages_with),
        [p["url"] for p in pages_with],
        {"method": "presence of any parseable JSON-LD checked across the sample, "
                   "compared against presence of Microdata or RDFa",
         "observed": {"pages_with_microdata_or_rdfa": len(pages_with),
                     "pages_with_jsonld": 0},
         "expected": "no expectation; recorded as a suggestion",
         "sample": {"checked": len(ctx.content), "failing": len(pages_with)},
         "confidence": "high", "nondeterministic": False},
        {"summary": "Consider JSON-LD for new structured-data work; it is not required "
                    "to change what already works.",
         "how": ["Leave existing Microdata or RDFa in place; it is valid and working.",
                 "For new templates, JSON-LD is easier to maintain and parses more "
                 "reliably across different systems, since it lives in one script "
                 "block rather than being woven through the HTML."],
         "mechanism": "JSON-LD and Microdata are both valid; the recommendation is "
                      "about maintainability and consistency of parsing, not "
                      "correctness.",
         "effort": "template-change", "owner": "engineering",
         "verification": "No verification needed; this is a suggestion, not a defect."},
        severity_ceiling="low")]


# ============================================================================ breadcrumbs

def check_breadcrumb_missing(ctx):
    def path_depth(url):
        return len([s for s in urlsplit(url).path.split("/") if s])

    non_home = [p for p in ctx.content if p.get("page_type") != "homepage"]
    if not non_home:
        return []
    if not any(path_depth(p["url"]) >= 2 for p in ctx.content):
        return []  # a flat site has nothing for a breadcrumb to express

    missing = [p for p in non_home
              if not ctx.schemas[p["url"]].nodes_of_type("BreadcrumbList")]
    if not missing:
        return []
    reach = reach_for(missing, non_home, ctx.clusters)
    findings = [finding(
        "SDE.BREADCRUMB_MISSING",
        "Pages below the homepage carry no breadcrumb markup",
        "weakens", reach, "measured", "understood",
        "%d of %d sampled non-homepage pages have no BreadcrumbList markup. Examples: "
        "%s."
        % (len(missing), len(non_home), ", ".join(p["url"] for p in missing[:3])),
        [p["url"] for p in missing],
        {"method": "presence of a BreadcrumbList node, after full @graph traversal, "
                   "on pages other than the homepage",
         "observed": {"pages_missing": [p["url"] for p in missing[:10]]},
         "expected": "BreadcrumbList markup below the homepage, where the site has a "
                     "real hierarchy",
         "sample": {"checked": len(non_home), "failing": len(missing)},
         "confidence": "high", "nondeterministic": False},
        {"summary": "Add BreadcrumbList markup reflecting each page's position in the "
                    "site hierarchy.",
         "how": ["Generate it from the same navigation hierarchy the template already "
                 "renders as a visible breadcrumb, if one exists.",
                 "Each ListItem needs position, name and item (the URL)."],
         "mechanism": "Breadcrumb markup gives a machine an explicit statement of "
                      "where a page sits in the site's structure, which is otherwise "
                      "only inferable from the URL path.",
         "effort": "template-change", "owner": "engineering",
         "verification": "Re-check the page and confirm BreadcrumbList markup "
                         "parses and matches the page's actual position."},
        severity_ceiling="low")]
    return findings


CHECKS = (
    check_no_structured_data,
    check_invalid_jsonld,
    check_missing_type_for_template,
    check_incomplete_required_props,
    check_schema_visible_mismatch,
    check_schema_only_no_visible,
    check_no_organization_node,
    check_sameas_and_stable_id,
    check_name_inconsistent,
    check_org_identity_conflict,
    check_entity_ambiguity_risk,
    check_microdata_only,
    check_breadcrumb_missing,
)


def run(snapshot):
    ctx = Context(snapshot)
    if ctx.blackout:
        ctx.note("page content",
                 "every sampled URL was refused, so no structured data or entity "
                 "identity could be observed")
        return [], ctx.not_assessed

    findings = []
    for check in CHECKS:
        findings.extend(check(ctx))
    findings.sort(key=lambda f: (f["check_id"], (f["affected_urls"] or [""])[0]))
    return findings, ctx.not_assessed


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Detect structured-data and entity-identity failures from a site "
                    "snapshot.",
        epilog="Example: check_schema_entity.py --snapshot snapshot.json "
              "--out findings.json")
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    try:
        snapshot = load_json(args.snapshot)
    except (OSError, ValueError) as exc:
        sys.stderr.write("Error: cannot read snapshot: %s\n" % exc)
        return 3

    version = str(snapshot.get("schema_version", ""))
    if not version.startswith("1."):
        sys.stderr.write("Error: unsupported snapshot schema_version %r\n" % version)
        return 3

    findings, not_assessed = run(snapshot)

    directory = os.path.dirname(os.path.abspath(args.out))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump({"detector": DETECTOR, "findings": findings,
                   "not_assessed": not_assessed}, handle, indent=2)
        handle.write("\n")

    sys.stderr.write("%s: %d findings, %d dimensions not assessed -> %s\n"
                     % (DETECTOR, len(findings), len(not_assessed), args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
