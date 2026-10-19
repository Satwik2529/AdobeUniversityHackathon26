#!/usr/bin/env python3
"""Detect why an assistant repeats an outdated or internally-contradicted version of a
brand's facts.

Funnel gate: **selected**. Pure snapshot consumer: this script makes no network requests
of any kind, no code path in it could, and does not call any external search engine or
API. The site-snapshot-collector remains the only network-touching component in this
marketplace, without exception.

Design rules, enforced here and not merely documented:

  * **No evidence, no finding.** Every finding quotes the exact conflicting values and
    the URLs they came from. Where the snapshot cannot establish something, that
    dimension is `not_assessed`, never guessed into a defect.
  * **A date is not automatically a freshness problem.** Publication date, modification
    date, copyright year, an event date and a date mentioned in prose are different
    things; conflating them produces exactly the false positives this detector exists
    to avoid. See the DATE RULE note on each date-aware check below.
  * **Only a genuine contradiction is a finding.** Two pages describing different
    products, different locations, or the same fact with harmless wording differences
    are not contradictions. A disagreement is only reported when there is no
    legitimate reason evident in the snapshot for the two pages to differ.
  * **This is not a second structured-data or answerability detector.** Cross-page
    Organization-identity conflicts on a shared `@id` (telephone, address, url) are
    `structured-data-entity-audit`'s territory (`SDE.ORG_IDENTITY_CONFLICT`). Whether a
    single page states its own core fact plainly is `answer-retrievability-audit`'s
    territory. This detector's distinct territory is temporal reliability and
    cross-page corroboration of the same fact -- price drift for the same product,
    date-signal disagreement, a stale currency claim, and superseded content that is
    still live and dated.

Usage:
  check_freshness.py --snapshot snapshot.json --out findings-freshness.json

Exit codes: 0 ok, 2 bad arguments, 3 the snapshot could not be read.
"""
import argparse
import json
import os
import re
import sys
from datetime import date, datetime

DETECTOR = "freshness-corroboration-audit"

THRESHOLDS = {
    "min_cluster_for_template": 3,
    "min_main_text_for_comparison": 40,
    # Two date signals for the SAME page are only a genuine conflict beyond this many
    # days apart -- absorbs timezone-boundary rounding and same-day build-pipeline
    # noise, which are not freshness defects.
    "date_signal_tolerance_days": 2,
    # More than one calendar year, specifically to survive the ordinary lag every site
    # has every January before its footer script runs.
    "copyright_year_lag_years": 1,
    "min_pages_for_canonical_fact_surface": 3,
}

UTILITY_TYPES = {"utility"}
CONFIDENT = {"high", "medium"}
FACT_BEARING_TYPES = frozenset({"product"})

_CURRENCY_SYMBOLS = {"£": "GBP", "$": "USD", "€": "EUR", "¥": "JPY"}
_PRICE_CODE_AFTER = re.compile(
    r"([£$€¥]?)\s*(\d[\d,]*(?:\.\d+)?)\s*(GBP|USD|EUR|JPY|CAD|AUD|CHF|NZD|SEK|NOK)\b", re.I)
_PRICE_SYMBOL = re.compile(r"([£$€¥])\s*(\d[\d,]*(?:\.\d+)?)")
_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})")
_HTTP_DATE_YEAR = re.compile(r"\b(19|20)\d{2}\b")

# Copyright detection anchors on the universal "\u00a9" symbol first (no language
# dependency at all), falling back to the English word only as a secondary signal --
# most sites use one or the other, and "copyright" in other languages is not
# attempted, which is an acknowledged limitation, not a silent assumption.
_COPYRIGHT_SYMBOL_YEAR = re.compile(r"\u00a9\s*(\d{4})")
_COPYRIGHT_WORD_YEAR = re.compile(r"\bcopyright\b\s*(\d{4})", re.I)

# Narrow, explicitly English-lexical patterns, used only where the snapshot provides no
# structural alternative (no field carries a brand slogan/tagline as structured data,
# and definition-list cell content is not in the snapshot at all -- only a count of
# how many exist). Documented as a genuine, necessary limitation in checks.md, not
# hidden. Gated to lang == "en" throughout.
_TAGLINE_PATTERN = re.compile(
    r"\b(?:tagline|slogan)(?:\s+is)?[:\s]+([^.\n]{2,80})[.\n]", re.I)
_CURRENCY_CLAIM = re.compile(
    r"\b(latest|newest|all-new|current model|now available)\b", re.I)


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


# ------------------------------------------------------------------------------- helpers

def norm_ws(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def norm_text_value(s):
    return norm_ws(s).casefold().strip(".,;:")


def is_definitely_utility(page):
    return page.get("page_type") in UTILITY_TYPES and page.get(
        "page_type_confidence") in CONFIDENT


def is_confident_content(page):
    if is_definitely_utility(page):
        return False
    if page.get("page_type_confidence") in CONFIDENT and page.get(
            "page_type") not in (None, "unknown"):
        return True
    return page.get("main_text_len", 0) >= 250


def flatten_jsonld(blocks):
    """Mirrors the equivalent function in every other detector in this marketplace
    (walks @graph and arrays). Duplicated locally rather than imported across skill
    boundaries, matching the established convention."""
    nodes = []

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            if "@graph" in node:
                walk(node["@graph"])
            nodes.append(node)

    for block in blocks or []:
        if block.get("parse_ok"):
            walk(block.get("data"))
    return nodes


def types_of(node):
    raw = node.get("@type") if isinstance(node, dict) else None
    if raw is None:
        return []
    values = raw if isinstance(raw, list) else [raw]
    return [v.rsplit("/", 1)[-1].rsplit("#", 1)[-1] for v in values if isinstance(v, str)]


def has_type(node, *names):
    lowered = {t.lower() for t in types_of(node)}
    return bool(lowered & {n.lower() for n in names})


def h1_of(page):
    for h in page.get("headings") or []:
        if h.get("level") == 1 and h.get("text"):
            return h["text"]
    return None


def parse_date_loose(value):
    """A best-effort date (year, month, day) from an ISO-ish string, or None. Never
    guesses a format that could be ambiguous (e.g. bare "01/02/2026"); only accepts
    unambiguous ISO-8601-prefixed values, which is what structured data, sitemap
    lastmod and HTTP dates all use in practice."""
    if not value:
        return None
    match = _ISO_DATE.search(str(value))
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def parse_http_date(value):
    """RFC 7231 HTTP-date, e.g. 'Wed, 12 Aug 2026 00:00:00 GMT'. Falls back to None
    rather than guessing on an unrecognised format."""
    if not value:
        return None
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S GMT"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def price_from_offer(offer):
    if not isinstance(offer, dict):
        return None
    price, currency = offer.get("price"), offer.get("priceCurrency")
    if price is None or not currency:
        return None
    try:
        amount = round(float(str(price).replace(",", "")), 2)
    except (TypeError, ValueError):
        return None
    return amount, str(currency).upper()


def get_offer(node):
    offers = node.get("offers") if isinstance(node, dict) else None
    if isinstance(offers, list):
        offers = offers[0] if offers else None
    return offers if isinstance(offers, dict) else None


def find_price_in_text(text):
    if not text:
        return None
    match = _PRICE_CODE_AFTER.search(text)
    if match:
        symbol, amount, code = match.groups()
        code = code.upper()
        if symbol and _CURRENCY_SYMBOLS.get(symbol) not in (None, code):
            match = None
    if not match:
        match = _PRICE_SYMBOL.search(text)
        if match:
            symbol, amount = match.groups()
            code = _CURRENCY_SYMBOLS.get(symbol)
            if not code:
                match = None
    if not match:
        return None
    try:
        return round(float(amount.replace(",", "")), 2), code
    except ValueError:
        return None


def page_date_signals(page):
    """{source: date} for every date this page carries, from independent sources."""
    signals = {}
    for node in flatten_jsonld((page.get("structured_data") or {}).get("jsonld") or []):
        for prop in ("dateModified", "datePublished"):
            parsed = parse_date_loose(node.get(prop))
            if parsed:
                signals.setdefault("structured:%s" % prop, parsed)
    lastmod = parse_date_loose(page.get("sitemap_lastmod"))
    if lastmod:
        signals["sitemap_lastmod"] = lastmod
    header_date = parse_http_date((page.get("headers") or {}).get("last-modified"))
    if header_date:
        signals["last-modified header"] = header_date
    return signals


def latest_date_signal(page):
    signals = page_date_signals(page)
    return max(signals.values()) if signals else None


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

class Context(object):

    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.pages = snapshot.get("pages") or []
        self.clusters = snapshot.get("clusters") or []
        self.audited_at = parse_date_loose(snapshot.get("audited_at"))
        self.fetched = [p for p in self.pages if p.get("fetch_ok")]
        self.blackout = bool(self.pages) and not self.fetched
        self.content = [p for p in self.fetched if is_confident_content(p)]
        self.homepage = next((p for p in self.fetched
                              if p.get("page_type") == "homepage"), None)
        self.not_assessed = []

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


# ===================================================== FRC.INTRA_SITE_FACT_CONFLICT

def _skus_by_page(ctx):
    by_sku = {}
    for page in ctx.content:
        for node in flatten_jsonld((page.get("structured_data") or {}).get("jsonld") or []):
            if not has_type(node, "Product"):
                continue
            sku = node.get("sku")
            price = price_from_offer(get_offer(node))
            if sku and price:
                by_sku.setdefault(str(sku), []).append((page, price))
    return by_sku


def _taglines_by_page(ctx):
    """English-lexical, gated to lang == 'en': see the module docstring and
    checks.md's documented limitation. No structural alternative exists in the
    snapshot for a free-text brand slogan."""
    hits = []
    for page in ctx.content:
        if (page.get("lang") or "").split("-")[0].lower() != "en":
            continue
        match = _TAGLINE_PATTERN.search(page.get("main_text") or "")
        if match:
            hits.append((page, norm_text_value(match.group(1))))
    return hits


def check_intra_site_fact_conflict(ctx):
    findings = []

    sku_hits = []
    for sku, occurrences in sorted(_skus_by_page(ctx).items()):
        if len(occurrences) < 2:
            continue
        values = {}
        for page, price in occurrences:
            values.setdefault(price, []).append(page["url"])
        if len(values) > 1:
            sku_hits.append((sku, values))

    if sku_hits:
        sku, values = sku_hits[0]
        urls_involved = sorted({u for urls in values.values() for u in urls})
        pages_hit = [p for p, pr in _skus_by_page(ctx)[sku]]
        reach = reach_for(pages_hit, ctx.content, ctx.clusters)
        findings.append(finding(
            "FRC.INTRA_SITE_FACT_CONFLICT",
            "The same product is priced differently on different pages",
            "degrades", reach, "measured", "selected",
            "Product with sku %r is priced differently depending on which page states "
            "it: %s. The same product should have one price wherever it is stated."
            % (sku, "; ".join("%s on %s" % (v, ", ".join(u[:1]))
                              for v, u in sorted(values.items()))),
            urls_involved,
            {"method": "Product.sku used to match the same product across pages, "
                       "then Product.offers.price compared between occurrences",
             "observed": {"sku": sku, "values": {str(v): u for v, u in values.items()}},
             "expected": "every occurrence of the same sku states the same price",
             "sample": {"checked": len(pages_hit), "failing": len(pages_hit)},
             "confidence": "high", "nondeterministic": False},
            {"summary": "Drive the price shown for this product from one source so "
                        "every page referencing it agrees.",
             "how": ["Identify which pages independently declare a price for this "
                     "sku (a listing card, a homepage feature, the product's own "
                     "detail page).",
                     "Generate all of them from the same field rather than "
                     "maintaining separate copies."],
             "mechanism": "A machine comparing two of the brand's own pages sees a "
                          "genuine disagreement about a fact with no ambiguity about "
                          "which product is meant; it has no way to know which price "
                          "is current.",
             "effort": "template-change", "owner": "engineering",
             "verification": "Re-check every page referencing this sku and confirm "
                             "the price agrees everywhere."}))

    if not _tagline_conflict_has_temporal_ordering(ctx):
        # Only emitted here when the snapshot gives no way to tell which value is
        # older; when it does, FRC.SUPERSEDED_CONTENT_LIVE is the more specific,
        # more actionable finding for the exact same underlying disagreement, and
        # reporting both would describe one contradiction twice.
        tagline_hits = _taglines_by_page(ctx)
        values = {}
        for page, tagline in tagline_hits:
            values.setdefault(tagline, []).append(page["url"])
        if len(values) > 1:
            pages_hit = [p for p, _ in tagline_hits]
            reach = reach_for(pages_hit, pages_hit, ctx.clusters)
            findings.append(finding(
                "FRC.INTRA_SITE_FACT_CONFLICT",
                "The brand's own tagline is stated differently on different pages",
                "degrades", reach, "measured", "selected",
                "The brand's tagline is stated with %d different wordings across "
                "the sampled pages: %s."
                % (len(values), "; ".join("%r on %s" % (v, ", ".join(u[:1]))
                                          for v, u in sorted(values.items()))),
                [u for urls in values.values() for u in urls],
                {"method": "an explicit 'tagline is ...' or 'slogan is ...' phrase "
                           "matched in the page's own main text, on English-language "
                           "pages only",
                 "observed": {"values": {v: u for v, u in values.items()}},
                 "expected": "the same tagline wording wherever it is stated",
                 "sample": {"checked": len(pages_hit), "failing": len(pages_hit)},
                 "confidence": "high", "nondeterministic": False,
                 "note": "English-lexical: the snapshot has no structured field for "
                         "a brand tagline, so this specific sub-check cannot run on "
                         "other languages; see checks.md for the documented "
                         "limitation"},
                {"summary": "Use one current tagline and update every page that "
                            "states it in words to match.",
                 "how": ["Decide which wording is current.",
                         "Update the other page(s) named in the evidence to match "
                         "exactly."],
                 "mechanism": "A brand's own pages disagreeing about its own "
                              "tagline is the clearest possible internal "
                              "contradiction signal a system can find; it directly "
                              "weakens confidence in every other fact the same "
                              "pages state.",
                 "effort": "content", "owner": "brand-ops",
                 "verification": "Re-check both pages and confirm the tagline "
                                 "wording matches exactly."}))
    return findings


def _tagline_conflict_has_temporal_ordering(ctx):
    """True only when FRC.SUPERSEDED_CONTENT_LIVE would actually fire for this exact
    tagline conflict -- mirrors that check's own condition precisely, rather than a
    looser "some date exists" test. Two conflicting values that each happen to carry
    a date signal, but the SAME date (as a sitewide lastmod stamp often is), give no
    real ordering evidence; requiring them to differ is what distinguishes genuine
    supersession from two equally-dated, equally-unexplained versions."""
    tagline_hits = _taglines_by_page(ctx)
    values = {}
    for page, tagline in tagline_hits:
        values.setdefault(tagline, []).append(page)
    if len(values) < 2:
        return False
    dated_versions = []
    for tagline, pages in values.items():
        dates = [d for d in (latest_date_signal(p) for p in pages) if d]
        if dates:
            dated_versions.append(max(dates))
    return len(dated_versions) >= 2 and max(dated_versions) > min(dated_versions)


# ========================================================== FRC.DATE_SIGNAL_CONFLICT

def check_date_signal_conflict(ctx):
    findings = []
    hits = []
    for page in ctx.content:
        signals = page_date_signals(page)
        if len(signals) < 2:
            continue
        values = sorted(signals.items(), key=lambda kv: kv[1])
        spread = (values[-1][1] - values[0][1]).days
        if spread > THRESHOLDS["date_signal_tolerance_days"]:
            hits.append((page, dict(signals)))

    if not hits:
        return findings
    reach = reach_for([p for p, _ in hits], ctx.content, ctx.clusters)
    example = hits[0]
    findings.append(finding(
        "FRC.DATE_SIGNAL_CONFLICT",
        "A page's own date signals disagree with each other",
        "weakens", reach, "measured", "selected",
        "%d pages carry two or more independent date signals (structured data, "
        "sitemap lastmod, or the Last-Modified header) that disagree by more than "
        "%d days. Example: %s: %s."
        % (len(hits), THRESHOLDS["date_signal_tolerance_days"], example[0]["url"],
           ", ".join("%s=%s" % (k, v.isoformat()) for k, v in example[1].items())),
        [p["url"] for p, _ in hits],
        {"method": "pairwise comparison of every date signal available for a page: "
                   "structured dateModified/datePublished, sitemap lastmod, and the "
                   "Last-Modified response header",
         "observed": {"pages": [{"url": p["url"],
                                 "signals": {k: v.isoformat() for k, v in s.items()}}
                                for p, s in hits[:8]]},
         "expected": "a page's own date signals agree within a few days of each "
                     "other",
         "sample": {"checked": len(ctx.content), "failing": len(hits)},
         "confidence": "high", "nondeterministic": False},
        {"summary": "Drive every date signal for a page (structured data, sitemap, "
                    "and the server's Last-Modified header) from the same "
                    "publication event.",
         "how": ["Identify which signal is stale (often the sitemap or the header, "
                 "if the page's own template renders a correct structured date).",
                 "Update the publishing pipeline so all three are set together."],
         "mechanism": "A system weighing how current a page is may consult any of "
                      "these signals; when they disagree, the signal most likely to "
                      "be trusted is unpredictable, and could be the stale one.",
         "effort": "config", "owner": "engineering",
         "verification": "Re-check the page and confirm all available date signals "
                         "agree."}))
    return findings


# =================================================================== FRC.STALE_CLAIM

def check_stale_claim(ctx):
    """English-lexical: detecting a currency claim ('latest', 'newest') requires
    understanding the words. Gated to lang == 'en'; documented as a limitation."""
    findings = []
    dated_pages = [(p, latest_date_signal(p)) for p in ctx.content]
    dated_pages = [(p, d) for p, d in dated_pages if d]
    if len(dated_pages) < 3:
        return findings
    newest_others = {}
    for page, d in dated_pages:
        others = [d2 for p2, d2 in dated_pages if p2["url"] != page["url"]]
        if others:
            newest_others[page["url"]] = max(others)

    hits = []
    for page, own_date in dated_pages:
        if (page.get("lang") or "").split("-")[0].lower() != "en":
            continue
        if not _CURRENCY_CLAIM.search(page.get("main_text") or ""):
            continue
        newest_other = newest_others.get(page["url"])
        if newest_other and (newest_other - own_date).days > 365:
            hits.append((page, own_date, newest_other))

    if not hits:
        return findings
    reach = reach_for([p for p, _, _ in hits], ctx.content, ctx.clusters)
    example = hits[0]
    findings.append(finding(
        "FRC.STALE_CLAIM",
        "A page claims to be current while carrying the site's oldest date signal",
        "weakens", reach, "inferred", "selected",
        "%d pages contain a currency claim (a word such as 'latest' or 'newest') "
        "while their own date signal (%s) is over a year older than the newest date "
        "signal found elsewhere on the site (%s). Example: %s."
        % (len(hits), example[1].isoformat(), example[2].isoformat(), example[0]["url"]),
        [p["url"] for p, _, _ in hits],
        {"method": "a currency-claim phrase in the page's own text, correlated with "
                   "that page's own date signal being materially older than the "
                   "newest date signal observed elsewhere in the sample",
         "observed": {"pages": [{"url": p["url"], "own_date": od.isoformat(),
                                 "newest_elsewhere": no.isoformat()}
                                for p, od, no in hits[:8]]},
         "expected": "a page claiming currency carries a date signal at least "
                     "roughly as recent as the rest of the site",
         "sample": {"checked": len(dated_pages), "failing": len(hits)},
         "confidence": "medium", "nondeterministic": False,
         "note": "English-lexical: the currency-claim phrase list only covers "
                 "English wording; see checks.md for the documented limitation"},
        {"summary": "Confirm whether this page still describes the current offering; "
                    "if not, remove the currency claim or update the page.",
         "how": ["Check whether a newer page or product has superseded what this "
                 "page describes.",
                 "If it has, remove words like 'latest' or 'newest' from this page, "
                 "or update the page to describe the current offering."],
         "mechanism": "A page asserting it is the current or newest option, while "
                      "carrying the oldest date signal on the site, risks a system "
                      "repeating a superseded claim as if it were current.",
         "effort": "content", "owner": "content",
         "verification": "Re-check the page's date signal relative to the rest of "
                         "the site after the update."}))
    return findings


# ======================================================== FRC.SUPERSEDED_CONTENT_LIVE

def check_superseded_content_live(ctx):
    """Distinct from INTRA_SITE_FACT_CONFLICT: fires only when the snapshot's own
    date evidence establishes which of two conflicting values is older, so the
    finding can name the newer value with confidence rather than leaving the reader
    to guess which of two contradicting pages to trust."""
    findings = []
    tagline_hits = _taglines_by_page(ctx)
    values = {}
    for page, tagline in tagline_hits:
        values.setdefault(tagline, []).append(page)
    if len(values) < 2:
        return findings

    dated_versions = []
    for tagline, pages in values.items():
        dates = [latest_date_signal(p) for p in pages]
        dates = [d for d in dates if d]
        if dates:
            dated_versions.append((tagline, max(dates), pages))

    if len(dated_versions) < 2:
        return findings  # cannot establish temporal order; INTRA_SITE_FACT_CONFLICT
    dated_versions.sort(key=lambda t: t[1])
    older, newer = dated_versions[0], dated_versions[-1]
    if older[1] >= newer[1]:
        return findings

    older_urls = [p["url"] for p in older[2]]
    findings.append(finding(
        "FRC.SUPERSEDED_CONTENT_LIVE",
        "An older version of a stated fact is still live alongside a newer one",
        "degrades", "template" if len(older_urls) >= 2 else "page", "measured",
        "selected",
        "The tagline %r (dated %s) is still live on %s, while %r (dated %s) is the "
        "more recently dated version found elsewhere on the site."
        % (older[0], older[1].isoformat(), ", ".join(older_urls[:2]), newer[0],
           newer[1].isoformat()),
        older_urls,
        {"method": "same fact type (tagline) stated with two different values, each "
                   "with its own date signal, compared to establish which is older",
         "observed": {"older_value": older[0], "older_dated": older[1].isoformat(),
                     "newer_value": newer[0], "newer_dated": newer[1].isoformat()},
         "expected": "the superseded value is updated or removed once a newer "
                     "dated version exists",
         "sample": {"checked": len(values), "failing": 1},
         "confidence": "high", "nondeterministic": False},
        {"summary": "Update the pages listed to the newer, more recently dated "
                    "version.",
         "how": ["Replace the older wording on the listed pages with the current "
                 "version found elsewhere on the site."],
         "mechanism": "The snapshot provides direct date evidence for which version "
                      "is older; leaving the superseded version live and indexed "
                      "risks a system citing it as if it were current.",
         "effort": "content", "owner": "content",
         "verification": "Re-check the listed pages and confirm they now state the "
                         "newer version."}))
    return findings


# ====================================================== FRC.NO_AVAILABILITY_SIGNAL

def check_no_availability_signal(ctx):
    findings = []
    candidates = [p for p in ctx.content if p.get("page_type") == "product"]
    missing = []
    for page in candidates:
        has_availability = False
        for node in flatten_jsonld((page.get("structured_data") or {}).get(
                "jsonld") or []):
            offer = get_offer(node)
            if offer and offer.get("availability"):
                has_availability = True
                break
        if not has_availability:
            for item in (page.get("structured_data") or {}).get(
                    "microdata_items") or []:
                if item.get("itemtype", "").rsplit("/", 1)[-1].lower() == "offer":
                    if (item.get("props") or {}).get("availability"):
                        has_availability = True
                        break
        if not has_availability:
            missing.append(page)

    if not missing:
        return findings
    reach = reach_for(missing, candidates, ctx.clusters)
    findings.append(finding(
        "FRC.NO_AVAILABILITY_SIGNAL",
        "Product pages state no availability signal",
        "weakens", reach, "measured", "selected",
        "%d of %d sampled product pages have no Product.offers.availability property "
        "in structured data. Examples: %s."
        % (len(missing), len(candidates), ", ".join(p["url"] for p in missing[:3])),
        [p["url"] for p in missing],
        {"method": "presence of an availability property on the first Offer node "
                   "found for each product page, checked in both JSON-LD and "
                   "Microdata",
         "observed": {"pages_missing": [p["url"] for p in missing[:10]]},
         "expected": "an explicit availability state (in stock, out of stock, "
                     "preorder, discontinued) on every product page",
         "sample": {"checked": len(candidates), "failing": len(missing)},
         "confidence": "high", "nondeterministic": False},
        {"summary": "Add an explicit availability value to each product's Offer "
                    "markup.",
         "how": ["Set offers.availability to the schema.org value matching the "
                 "product's real current state (InStock, OutOfStock, PreOrder, "
                 "Discontinued)."],
         "mechanism": "Without an explicit availability signal, a system has no "
                      "reliable way to know whether a product can still be bought, "
                      "and risks presenting a discontinued item as available or vice "
                      "versa.",
         "effort": "template-change", "owner": "engineering",
         "verification": "Re-check the product's markup and confirm availability is "
                         "present and accurate."}))
    return findings


# ========================================================= FRC.COPYRIGHT_YEAR_LAG

def check_copyright_year_lag(ctx):
    findings = []
    reference_dates = [d for p in ctx.content for d in [latest_date_signal(p)] if d]
    reference = max(reference_dates) if reference_dates else ctx.audited_at
    if not reference:
        return findings

    hits = []
    for page in ctx.content:
        text = page.get("raw_text") or page.get("main_text") or ""
        match = _COPYRIGHT_SYMBOL_YEAR.search(text) or _COPYRIGHT_WORD_YEAR.search(text)
        if not match:
            continue
        try:
            year = int(match.group(1))
        except ValueError:
            continue
        if reference.year - year > THRESHOLDS["copyright_year_lag_years"]:
            hits.append((page, year))

    if not hits:
        return findings
    reach = reach_for([p for p, _ in hits], ctx.content, ctx.clusters)
    example = hits[0]
    findings.append(finding(
        "FRC.COPYRIGHT_YEAR_LAG",
        "The copyright year lags the site's own newest content by more than a year",
        "weakens", reach, "measured", "selected",
        "%d pages show a copyright year of %d, while the newest date signal observed "
        "anywhere in the sample is %d -- a gap of %d years. Example: %s."
        % (len(hits), example[1], reference.year, reference.year - example[1],
           example[0]["url"]),
        [p["url"] for p, _ in hits],
        {"method": "a copyright year (matched via the \u00a9 symbol or the word "
                   "'copyright') compared against the newest date signal (structured "
                   "data, sitemap, or Last-Modified header) found anywhere in the "
                   "sample, or the audit's own crawl date if no other signal exists",
         "observed": {"pages": [{"url": p["url"], "copyright_year": y}
                                for p, y in hits[:8]],
                     "reference_year": reference.year},
         "expected": "the copyright year within a year of the site's own newest "
                     "content",
         "sample": {"checked": len(ctx.content), "failing": len(hits)},
         "confidence": "high", "nondeterministic": False},
        {"summary": "Update the copyright year, ideally driven automatically from "
                    "the current date rather than a hand-maintained value.",
         "how": ["Generate the footer copyright year from the server's own clock "
                 "at render time, so it never needs manual updating."],
         "mechanism": "A lagging copyright year is a weak but real signal a system "
                      "may use when judging how actively a site is maintained, "
                      "independent of whether the content itself is still accurate.",
         "effort": "trivial", "owner": "engineering",
         "verification": "Re-check the footer and confirm the year matches or "
                         "exceeds the site's own newest content date."}))
    return findings


# ==================================================== FRC.NO_CANONICAL_FACT_SURFACE

def check_no_canonical_fact_surface(ctx):
    """Authoritative owner of this finding (see merge_findings.DUPLICATE_OWNERSHIP,
    which suppresses answer-retrievability-audit's ANS.NO_CANONICAL_FACT_SURFACE once
    this one fires). Adds one dimension ANS's version does not have: a genuine
    canonical surface should also carry a discoverable date signal, since a page with
    no way to tell how current it is cannot anchor freshness the way a dated one can.
    """
    if not ctx.homepage:
        ctx.note("canonical fact surface",
                 "no page in the sample was classified as the homepage, so this "
                 "could not be assessed")
        return []
    if len(ctx.content) < THRESHOLDS["min_pages_for_canonical_fact_surface"]:
        ctx.note("canonical fact surface",
                 "too few confidently-classified content pages in the sample for a "
                 "sitewide claim about a canonical fact surface to be meaningful")
        return []
    h1 = h1_of(ctx.homepage)
    if not h1:
        return []
    h1_words = set(re.findall(r"[^\W\d_]+", h1.casefold(), re.UNICODE))
    if not h1_words:
        return []

    for page in ctx.content:
        text = page.get("main_text") or ""
        if not (h1_words & set(re.findall(r"[^\W\d_]+", text.casefold(), re.UNICODE))):
            continue
        signals = 0
        if _YEAR.search(text):
            signals += 1
        if find_price_in_text(text):
            signals += 1
        if re.search(r"\b\d[\d\s-]{6,}\d\b", text):
            signals += 1
        if signals >= 2:
            return []  # a canonical surface exists; nothing to report

    return [finding(
        "FRC.NO_CANONICAL_FACT_SURFACE",
        "No page states the brand's key facts together in plain, dated text",
        "degrades", "sitewide", "measured", "selected",
        "No sampled page combines the brand's own name with at least two independent "
        "kinds of key fact (a year, a price, or a phone-like number) stated together "
        "in plain text. There is no single page a third party, or a system deciding "
        "which version of a fact to trust, could point to as the brand's own current "
        "statement of its facts.",
        [p["url"] for p in ctx.content],
        {"method": "co-occurrence, on the same page, of the homepage's own subject "
                   "name and at least 2 of: a year pattern, a price pattern, a "
                   "phone-like digit run",
         "observed": {"pages_checked": len(ctx.content)},
         "expected": "at least one page combining the brand name with several key "
                     "facts in plain text",
         "sample": {"checked": len(ctx.content), "failing": len(ctx.content)},
         "confidence": "medium", "nondeterministic": False},
        {"summary": "Publish one page (an About or Company page is the natural home) "
                    "stating the brand's key facts plainly: founding, location, "
                    "contact, and its core offering, in complete sentences.",
         "how": ["Bring the facts already scattered across the site onto one page, "
                 "in plain prose.",
                 "State each fact as a complete, self-contained sentence naming the "
                 "brand.",
                 "Keep the page's own date signal current when the facts change."],
         "mechanism": "One canonical, plainly-worded, appropriately dated page gives "
                      "both machines and third parties a single version of the "
                      "brand's facts to copy and a way to judge how current it is, "
                      "which is how agreement about those facts starts.",
         "effort": "content", "owner": "content",
         "verification": "Confirm the new or updated page states the brand name "
                         "alongside at least two key facts in plain text."})]


CHECKS = (
    check_intra_site_fact_conflict,
    check_date_signal_conflict,
    check_stale_claim,
    check_superseded_content_live,
    check_no_availability_signal,
    check_copyright_year_lag,
    check_no_canonical_fact_surface,
)


def run(snapshot):
    ctx = Context(snapshot)
    if ctx.blackout:
        ctx.note("page content",
                 "every sampled URL was refused, so freshness and corroboration "
                 "could not be assessed")
        return [], ctx.not_assessed

    findings = []
    for check in CHECKS:
        findings.extend(check(ctx))
    findings.sort(key=lambda f: (f["check_id"], (f["affected_urls"] or [""])[0]))
    return findings, ctx.not_assessed


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Detect freshness and corroboration failures from a site "
                    "snapshot.",
        epilog="Example: check_freshness.py --snapshot snapshot.json "
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
