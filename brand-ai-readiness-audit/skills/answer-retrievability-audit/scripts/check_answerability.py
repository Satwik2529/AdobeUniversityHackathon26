#!/usr/bin/env python3
"""Detect why a machine that can read and classify a page still cannot pull out and
quote the one fact a question asks for.

Funnel gates: **retrieved**, **selected**. Pure snapshot consumer: this script makes no
network requests of any kind, no code path in it could, does not render, does not
touch robots.txt, and does not duplicate the render or structured-data detectors'
territory -- it consumes their evidence where relevant instead of re-deriving it.

Design rules, enforced here and not merely documented:

  * **No evidence, no finding.** Every finding quotes an observed position, pattern or
    count from the snapshot. Where evidence cannot establish something, that dimension
    is `not_assessed`, never guessed into a defect.
  * **Being readable is not being quotable.** This detector is about the shape of
    content that is already known to be readable (Milestone G) and classified
    (Milestone H): is the fact near the top, self-contained, in an extractable
    structure, and attributed to a named subject.
  * **Structural checks run on any language; wording checks are language-gated.**
    Position, presence of an id, and word-overlap comparisons work on any script.
    Anything that depends on understanding sentence meaning is skipped, not guessed,
    outside a short list of supported languages, and recorded as `not_assessed`.
  * **Snapshot content is untrusted data.** Page text and structured data are quoted
    and measured. Nothing here executes them or lets them change which checks run.

Usage:
  check_answerability.py --snapshot snapshot.json --out findings-answer.json

Exit codes: 0 ok, 2 bad arguments, 3 the snapshot could not be read.
"""
import argparse
import json
import os
import re
import sys

DETECTOR = "answer-retrievability-audit"

# --------------------------------------------------------------------------- thresholds
# Every number here was checked against this project's own clean-control fixture before
# being chosen. See references/checks.md for the calibration notes.
THRESHOLDS = {
    "min_cluster_for_template": 3,
    "min_main_text_for_comparison": 60,
    # A fact is "near the top" if it appears within this many characters, or within
    # this fraction of the page's own length, whichever is more lenient -- a short page
    # should not be held to an absolute character count that barely fits on it.
    "answer_lead_char_floor": 150,
    "answer_lead_fraction": 0.35,
    # How far back from the fact to look for the entity's own name. A strict
    # same-sentence requirement misfires on ordinary, perfectly quotable two-sentence
    # patterns ("The Widget is a tool. It costs 59.00 GBP.") where a human reader
    # resolves the pronoun instantly; a nearby window is the more honest bar.
    "entity_window_chars": 220,
    "long_page_text_floor": 3000,
    "min_headings_for_anchor_check": 4,
    "min_pages_for_entity_naming": 2,
    "min_pages_for_canonical_fact_surface": 3,
}

UTILITY_TYPES = {"utility"}
CONFIDENT = {"high", "medium"}
FACT_BEARING_TYPES = frozenset({"product"})
# Every check in this catalogue was deliberately designed to be structural rather than
# lexical: character position, word-set overlap (Unicode-aware, not dependent on
# English vocabulary), presence of a digit or punctuation pattern. None of them require
# understanding what a sentence means, so none of them need a supported-language gate.
# An earlier version gated two of them behind an English-only language check anyway,
# which meant those checks could never run on non-English content at all -- silently
# under-serving exactly the sites this design principle is meant to protect. See
# checks.md for the corresponding regression notes.

_CURRENCY_SYMBOLS = {"£": "GBP", "$": "USD", "€": "EUR", "¥": "JPY"}
_PRICE_CODE_AFTER = re.compile(
    r"([£$€¥]?)\s*(\d[\d,]*(?:\.\d+)?)\s*(GBP|USD|EUR|JPY|CAD|AUD|CHF|NZD|SEK|NOK)\b", re.I)
_PRICE_SYMBOL = re.compile(r"([£$€¥])\s*(\d[\d,]*(?:\.\d+)?)")
_UNIT_TOKENS = (
    r"millimetres?", r"millimeters?", r"centimetres?", r"centimeters?",
    r"kilometres?", r"kilometers?", r"metres?", r"meters?",
    r"kilograms?", r"milligrams?", r"grams?", r"pounds?", r"ounces?",
    r"litres?", r"liters?", r"millilitres?", r"milliliters?",
    r"inches?", r"feet", r"percent",
    r"degrees?", r"mm", r"cm", r"km", r"kg", r"mg", r"lb", r"oz", r"ml",
    r"gbp", r"usd", r"eur", r"jpy", r"cad", r"aud", r"hz", r"khz", r"mhz", r"ghz",
)
# Deliberately excludes single-letter and highly ambiguous short abbreviations ("in"
# without a period, bare "g", "a", "l", "w", "v") even with word-boundary matching:
# "in" alone is overwhelmingly the preposition, not the unit, in ordinary prose ("costs
# 4.8 in total"), and a false "has a unit nearby" verdict from a collision like that
# silently hides a genuinely unitless value rather than merely misdescribing one that
# has a unit. Full words and currency codes above are unambiguous even matched as
# whole words. Currency symbols are handled separately since they are not word
# characters and cannot use a \b word-boundary match.
_UNIT_WORD_PATTERN = re.compile(r"\b(?:" + "|".join(_UNIT_TOKENS) + r")\b", re.I)
_UNIT_SYMBOLS = ("%", "£", "$", "€", "¥", "°c", "°f")
_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_DECIMAL_NUMBER = re.compile(r"(?<![\w.])(\d+\.\d+)(?![\w.])")
_MODEL_LIKE = re.compile(r"[A-Za-z]-?\d|\d-?[A-Za-z]")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?\u3002\uff01\uff1f])\s+")
_QUESTION_MARK = re.compile(r"[?\uff1f]\s*$")


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


# ------------------------------------------------------------------------------- helpers

def norm_ws(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def norm_words(s):
    return set(re.findall(r"[^\W\d_]+", (s or "").casefold(), re.UNICODE))


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


def flatten_jsonld(blocks):
    """Mirrors site-snapshot-collector's function of the same name (walks @graph and
    arrays). Duplicated locally, like every other detector in this marketplace, so this
    skill remains independently portable rather than importing across skill boundaries.
    """
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


def find_product_price(page):
    """(amount, currency, source) from this page's own structured data, or None."""
    sd = page.get("structured_data") or {}
    for node in flatten_jsonld(sd.get("jsonld") or []):
        if "Product" in types_of(node):
            price = price_from_offer(get_offer(node))
            if price:
                return price
    for item in sd.get("microdata_items") or []:
        if item.get("itemtype", "").rsplit("/", 1)[-1].lower() == "offer":
            props = item.get("props") or {}
            price = price_from_offer(props)
            if price:
                return price
    return None


def find_price_in_text(text):
    """First (amount, currency, start_offset) match in free text, or None."""
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
        value = round(float(amount.replace(",", "")), 2)
    except ValueError:
        return None
    return value, code, match.start()


def has_unit_nearby(text, start, end, window=20):
    around = text[max(0, start - window):min(len(text), end + window)].casefold()
    if _UNIT_WORD_PATTERN.search(around):
        return True
    return any(sym in around for sym in _UNIT_SYMBOLS)


def looks_like_year_or_model(text, start, end):
    token = text[max(0, start - 4):end + 4]
    if _YEAR.search(text[start:end]):
        return True
    return bool(_MODEL_LIKE.search(token))


def h1_of(page):
    for h in page.get("headings") or []:
        if h.get("level") == 1 and h.get("text"):
            return h["text"]
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

class Context(object):

    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.pages = snapshot.get("pages") or []
        self.clusters = snapshot.get("clusters") or []
        self.site_archetype = snapshot.get("site_archetype")
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


# =============================================================== ANS.NO_DIRECT_ANSWER_LEAD

def check_no_direct_answer_lead(ctx):
    findings = []
    hits = []

    for page in ctx.content:
        if page.get("page_type") not in FACT_BEARING_TYPES:
            continue
        main_text = page.get("main_text") or ""
        if len(main_text) < THRESHOLDS["min_main_text_for_comparison"]:
            continue
        structured_price = find_product_price(page)
        if not structured_price:
            continue
        found = find_price_in_text(main_text)
        if not found:
            continue
        _, _, offset = found

        buried = offset > max(THRESHOLDS["answer_lead_char_floor"],
                              THRESHOLDS["answer_lead_fraction"] * len(main_text))

        h1 = h1_of(page)
        self_contained = True
        if h1:
            window_start = max(0, offset - THRESHOLDS["entity_window_chars"])
            window = main_text[window_start:offset]
            h1_words = norm_words(h1)
            self_contained = bool(h1_words and (h1_words & norm_words(window)))

        if buried or not self_contained:
            hits.append((page, offset, len(main_text), buried, self_contained))

    if not hits:
        return findings
    reach = reach_for([h[0] for h in hits], ctx.content, ctx.clusters)
    example = hits[0]
    reasons = []
    if example[3]:
        reasons.append("the fact first appears at character %d of %d" % (example[1],
                                                                          example[2]))
    if not example[4]:
        reasons.append("the sentence carrying it has no nearby mention of the "
                       "page's own subject")
    findings.append(finding(
        "ANS.NO_DIRECT_ANSWER_LEAD",
        "The page's core fact is not stated plainly near the top",
        "weakens", reach, "inferred", "retrieved",
        "%d pages state their core fact late in the page, without a nearby restatement "
        "of the subject, or both. Example: %s -- %s."
        % (len(hits), example[0]["url"], "; ".join(reasons)),
        [h[0]["url"] for h in hits],
        {"method": "character offset of the first structurally-confirmed core fact "
                   "within the page's extracted main text, and word overlap between "
                   "the page's own h1 and the text immediately preceding that fact",
         "observed": {"pages": [{"url": p["url"], "fact_offset": off,
                                 "main_text_len": length, "buried": buried,
                                 "self_contained": contained}
                                for p, off, length, buried, contained in hits[:8]]},
         "expected": "the core fact stated within the first part of the page, in a "
                     "sentence that also names the subject",
         "sample": {"checked": len(ctx.content), "failing": len(hits)},
         "confidence": "medium", "nondeterministic": False,
         "note": "position and word-overlap are proxies for quotability, not a "
                 "certain measurement of it"},
        {"summary": "Open the page with one self-contained sentence stating the core "
                    "fact and naming the subject explicitly, before any narrative "
                    "lead-in.",
         "how": ["Move the sentence stating the price (or core fact) into the first "
                 "paragraph.",
                 "Name the product or entity in that same sentence rather than "
                 "relying on a pronoun from an earlier sentence.",
                 "Keep any narrative framing after the fact, not before it."],
         "mechanism": "A fact that is present but late or pronoun-dependent is "
                      "expensive to locate and risky to quote out of context; a system "
                      "assembling an answer favours a source where the fact can be "
                      "lifted as a single self-contained unit.",
         "effort": "content", "owner": "content",
         "verification": "Read only the first paragraph and confirm the core fact is "
                         "stated there with its subject named."}))
    return findings


# ================================================================= ANS.SPECS_NOT_EXTRACTABLE

def check_specs_not_extractable(ctx):
    findings = []
    hits = []
    for page in ctx.content:
        if page.get("page_type") not in FACT_BEARING_TYPES:
            continue
        if (page.get("tables", 0) or 0) + (page.get("definition_lists", 0) or 0) > 0:
            continue
        main_text = page.get("main_text") or ""
        decimal_matches = list(_DECIMAL_NUMBER.finditer(main_text))
        spec_like = [m for m in decimal_matches
                    if has_unit_nearby(main_text, m.start(), m.end())]
        if len(spec_like) >= 2:
            hits.append((page, len(spec_like)))

    if not hits:
        return findings
    reach = reach_for([p for p, _ in hits], ctx.content, ctx.clusters)
    example = hits[0]
    findings.append(finding(
        "ANS.SPECS_NOT_EXTRACTABLE",
        "Specification values exist only in prose, not in an extractable structure",
        "weakens", reach, "measured", "retrieved",
        "%d pages state 2 or more distinct measurements with units in running prose, "
        "with no table or definition list anywhere on the page to hold them as "
        "extractable label-value pairs. Example: %s has %d such values."
        % (len(hits), example[0]["url"], example[1]),
        [p["url"] for p, _ in hits],
        {"method": "count of decimal numbers with an adjacent unit or currency token "
                   "in the page's main text, on pages with zero tables or definition "
                   "lists",
         "observed": {"pages": [{"url": p["url"], "spec_like_values": count}
                                for p, count in hits[:8]]},
         "expected": "specification values in a table or definition list, not solely "
                     "in prose",
         "sample": {"checked": len(ctx.content), "failing": len(hits)},
         "confidence": "high", "nondeterministic": False},
        {"summary": "Move the specification values into a table or definition list, "
                    "with each label immediately adjacent to its value.",
         "how": ["Identify the specification sentence(s) named in the evidence.",
                 "Convert each label-value pair into a table row or a dt/dd pair.",
                 "Keep the prose as a description alongside the table, not instead of "
                 "it."],
         "mechanism": "Label-value adjacency in a table or list is what makes a "
                      "specification extractable without inference. The same values "
                      "in a sentence require a system to correctly parse which number "
                      "belongs to which property, which is unreliable.",
         "effort": "template-change", "owner": "content",
         "verification": "Confirm each specification value now also appears in a "
                         "table or definition list on the page."}))
    return findings


# ====================================================================== ANS.UNITLESS_VALUES

def check_unitless_values(ctx):
    findings = []
    hits = []
    for page in ctx.content:
        if page.get("page_type") not in FACT_BEARING_TYPES:
            continue
        main_text = page.get("main_text") or ""
        bare = []
        for m in _DECIMAL_NUMBER.finditer(main_text):
            if has_unit_nearby(main_text, m.start(), m.end()):
                continue
            if looks_like_year_or_model(main_text, m.start(), m.end()):
                continue
            bare.append(m.group(1))
        if bare:
            hits.append((page, bare))

    if not hits:
        return findings
    reach = reach_for([p for p, _ in hits], ctx.content, ctx.clusters)
    example = hits[0]
    findings.append(finding(
        "ANS.UNITLESS_VALUES",
        "Numeric values appear with no unit or currency",
        "weakens", reach, "measured", "retrieved",
        "%d pages state a decimal number with no unit or currency token nearby, and "
        "the number does not look like a year or a model identifier. Example: %s: "
        "%r."
        % (len(hits), example[0]["url"], example[1][0]),
        [p["url"] for p, _ in hits],
        {"method": "decimal numbers in main text with no unit or currency token "
                   "within a 15-character window, excluding years and model-like "
                   "alphanumeric tokens",
         "observed": {"pages": [{"url": p["url"], "unitless_values": vals[:5]}
                                for p, vals in hits[:8]]},
         "expected": "every measurement or price paired with an explicit unit or "
                     "currency",
         "sample": {"checked": len(ctx.content), "failing": len(hits)},
         "confidence": "high", "nondeterministic": False},
        {"summary": "Add the missing unit or currency immediately next to each value "
                    "named in the evidence.",
         "how": ["State the unit or currency code explicitly rather than assuming "
                 "context carries it."],
         "mechanism": "A bare number is ambiguous across markets and measurement "
                      "systems; an explicit unit makes it safe to repeat and quote.",
         "effort": "content", "owner": "content",
         "verification": "Re-check the page and confirm each value has an explicit "
                         "unit or currency immediately adjacent."},
        severity_ceiling="low"))
    return findings


# =================================================================== ANS.ENTITY_NEVER_NAMED

def check_entity_never_named(ctx):
    """Scoped to product-type pages, where the h1 genuinely *is* the entity of
    interest (the product name). On other page types -- FAQ, legal, contact,
    category -- the h1 is a generic section label ("Frequently asked questions",
    "Terms of sale"), not an entity that needs restating in the body; a first pass at
    this check applied the same test to every page type and consequently flagged
    ordinary, well-written FAQ and legal pages purely for not repeating their own
    section heading, which is not what this check is meant to measure.
    """
    findings = []
    hits = []
    for page in ctx.content:
        if page.get("page_type") not in FACT_BEARING_TYPES:
            continue
        h1 = h1_of(page)
        if not h1:
            continue
        main_text = page.get("main_text") or ""
        if len(main_text) < THRESHOLDS["min_main_text_for_comparison"]:
            continue
        h1_words = norm_words(h1)
        if not h1_words:
            continue
        body_after_h1 = main_text
        idx = main_text.find(h1)
        if idx == 0:
            body_after_h1 = main_text[len(h1):]
        recurs = h1_words <= norm_words(body_after_h1)
        if not recurs:
            hits.append(page)

    if len(hits) < THRESHOLDS["min_pages_for_entity_naming"]:
        return findings
    reach = reach_for(hits, ctx.content, ctx.clusters)
    findings.append(finding(
        "ANS.ENTITY_NEVER_NAMED",
        "The body never restates the page's own subject after the heading",
        "weakens", reach, "measured", "retrieved",
        "%d pages never restate their own h1's subject anywhere in the body text "
        "after the heading itself. Examples: %s."
        % (len(hits), ", ".join(p["url"] for p in hits[:3])),
        [p["url"] for p in hits],
        {"method": "word overlap between the page's own h1 and the body text "
                   "following it, structural and language-neutral",
         "observed": {"pages": [{"url": p["url"], "h1": h1_of(p)} for p in hits[:10]]},
         "expected": "the h1's subject named again at least once in the body",
         "sample": {"checked": len(ctx.content), "failing": len(hits)},
         "confidence": "high", "nondeterministic": False},
        {"summary": "Restate the full subject name at least once in the body, "
                    "ideally in the sentence carrying the page's core fact.",
         "how": ["Replace one pronoun-only reference to the subject with its full "
                 "name, in the paragraph most likely to be quoted."],
         "mechanism": "A sentence quoted out of context needs its own subject to be "
                      "usable; a page that only ever refers to its subject via the "
                      "heading and pronouns produces no self-contained quotable "
                      "sentence anywhere in the body.",
         "effort": "content", "owner": "content",
         "verification": "Read the body text alone, without the heading, and confirm "
                         "the subject is still identifiable."}))
    return findings


# =================================================================== ANS.NO_HEADING_ANCHORS

def check_no_heading_anchors(ctx):
    findings = []
    hits = []
    for page in ctx.content:
        if (page.get("main_text_len", 0) or 0) < THRESHOLDS["long_page_text_floor"]:
            continue
        headings = [h for h in page.get("headings") or [] if h.get("level", 1) > 1]
        if len(headings) < THRESHOLDS["min_headings_for_anchor_check"]:
            continue
        without_id = [h for h in headings if not h.get("id")]
        if len(without_id) == len(headings):
            hits.append((page, len(headings)))

    if not hits:
        return findings
    reach = reach_for([p for p, _ in hits], ctx.content, ctx.clusters)
    example = hits[0]
    findings.append(finding(
        "ANS.NO_HEADING_ANCHORS",
        "Long pages have no stable heading identifiers",
        "weakens", reach, "measured", "retrieved",
        "%d long pages (over %d characters of main content, with %d or more headings) "
        "have no id attribute on any heading. Example: %s has %d headings, none "
        "addressable."
        % (len(hits), THRESHOLDS["long_page_text_floor"],
           THRESHOLDS["min_headings_for_anchor_check"], example[0]["url"], example[1]),
        [p["url"] for p, _ in hits],
        {"method": "presence of an id attribute on every heading, on pages above the "
                   "long-page floor with at least %d headings"
                   % THRESHOLDS["min_headings_for_anchor_check"],
         "observed": {"pages": [{"url": p["url"], "heading_count": c}
                                for p, c in hits[:8]]},
         "expected": "a stable id on each heading of a long page",
         "sample": {"checked": len(ctx.content), "failing": len(hits)},
         "confidence": "high", "nondeterministic": False},
        {"summary": "Add a stable id attribute to every heading on long pages.",
         "how": ["Generate the id from the heading text at build time.",
                 "Keep ids stable across edits so existing links do not break."],
         "mechanism": "A stable id lets an answer link directly to the section that "
                      "answers a question, rather than the top of a long page, which "
                      "helps both the citation and the visitor who follows it.",
         "effort": "template-change", "owner": "engineering",
         "verification": "Confirm each heading on the page has a unique, stable id."}))
    return findings


# ==================================================================== ANS.NO_SUMMARY_BLOCK

def check_no_summary_block(ctx):
    findings = []
    hits = []
    for page in ctx.content:
        if (page.get("main_text_len", 0) or 0) < THRESHOLDS["long_page_text_floor"]:
            continue
        headings = [h for h in page.get("headings") or []
                   if h.get("level", 1) >= 2 and h.get("text")]
        if not headings:
            continue
        main_text = page.get("main_text") or ""
        first_section_text = headings[0]["text"]
        idx = main_text.find(first_section_text)
        if idx < 0:
            continue  # heading text not found verbatim; not assessable for this page
        if idx < 80:
            hits.append((page, idx))

    if not hits:
        return findings
    reach = reach_for([p for p, _ in hits], ctx.content, ctx.clusters)
    example = hits[0]
    findings.append(finding(
        "ANS.NO_SUMMARY_BLOCK",
        "Long pages have no lead summary before the first section",
        "weakens", reach, "inferred", "retrieved",
        "%d long pages appear to move into their first named section within the "
        "opening %d characters, suggesting little or no orienting summary precedes "
        "the detailed narrative. Example: %s."
        % (len(hits), 80, example[0]["url"]),
        [p["url"] for p, _ in hits],
        {"method": "character offset of the first level-2-or-below heading's own "
                   "text within the page's main text, as a proxy for how much lead-in "
                   "content precedes the first section",
         "observed": {"pages": [{"url": p["url"], "first_section_offset": off}
                                for p, off in hits[:8]]},
         "expected": "a short orienting summary before the first named section",
         "sample": {"checked": len(ctx.content), "failing": len(hits)},
         "confidence": "medium", "nondeterministic": False,
         "note": "heading position in extracted text is a proxy for lead-in length, "
                 "not a direct measurement of summary quality"},
        {"summary": "Add a short paragraph after the heading stating what the page "
                    "covers, before the first detailed section.",
         "how": ["Write two or three sentences summarising the page's key facts "
                 "immediately after the h1."],
         "mechanism": "A brief lead summary gives a system (and a visitor) the page's "
                      "shape before committing to reading the detail, which is what "
                      "the first screenful is for.",
         "effort": "content", "owner": "content",
         "verification": "Confirm a short summary now appears before the first "
                         "section heading."},
        severity_ceiling="low"))
    return findings


# ======================================================================= ANS.NO_QA_SURFACE

def check_no_qa_surface(ctx):
    findings = []
    faq_pages = [p for p in ctx.content if p.get("page_type") == "faq"]
    if not faq_pages:
        return findings  # no evidence the site intends question content anywhere
    hits = []
    for page in faq_pages:
        headings = [h for h in page.get("headings") or [] if h.get("text")]
        questions = [h for h in headings if _QUESTION_MARK.search(h["text"])]
        if headings and not questions:
            hits.append(page)

    if not hits:
        return findings
    reach = reach_for(hits, faq_pages, ctx.clusters)
    findings.append(finding(
        "ANS.NO_QA_SURFACE",
        "The FAQ-classified page has no question-shaped headings",
        "weakens", reach, "inferred", "selected",
        "%d pages classified as FAQ content have headings, but none of them are "
        "phrased as questions. Examples: %s."
        % (len(hits), ", ".join(p["url"] for p in hits[:3])),
        [p["url"] for p in hits],
        {"method": "presence of a question mark at the end of each heading, on pages "
                   "already classified as FAQ content",
         "observed": {"pages": [{"url": p["url"],
                                 "headings": [h["text"] for h in
                                             (p.get("headings") or [])[:6]]}
                                for p in hits[:8]]},
         "expected": "headings phrased as the questions they answer",
         "sample": {"checked": len(faq_pages), "failing": len(hits)},
         "confidence": "medium", "nondeterministic": False,
         "note": "this only evaluates a page already classified as FAQ content; it "
                 "never asserts that a site without one should add FAQ content"},
        {"summary": "Phrase each section heading on this page as the actual question "
                    "it answers.",
         "how": ["Rewrite each heading in question form, matching what the "
                 "paragraph beneath it actually answers.",
                 "Never phrase a heading as a question the page does not go on to "
                 "answer."],
         "mechanism": "A heading phrased as the question it answers, with a "
                      "self-contained answer beneath it, is easy to lift as a "
                      "quotable unit for a question-shaped query.",
         "effort": "content", "owner": "content",
         "verification": "Confirm each heading on the page is phrased as a question "
                         "the following text actually answers."}))
    return findings


# ============================================================ ANS.NO_CANONICAL_FACT_SURFACE

def check_no_canonical_fact_surface(ctx):
    if not ctx.homepage:
        ctx.note("canonical fact surface",
                 "no page in the sample was classified as the homepage, so this could "
                 "not be assessed")
        return []
    if len(ctx.content) < THRESHOLDS["min_pages_for_canonical_fact_surface"]:
        ctx.note("canonical fact surface",
                 "too few confidently-classified content pages in the sample for a "
                 "sitewide claim about a canonical fact surface to be meaningful")
        return []
    h1 = h1_of(ctx.homepage)
    if not h1:
        return []
    h1_words = norm_words(h1)
    if not h1_words:
        return []

    # Word-overlap, year, price and phone-digit patterns are all structural, not
    # lexical -- none of them require understanding the page's language -- so this
    # check runs on every language for that reason.
    for page in ctx.content:
        text = page.get("main_text") or ""
        if not (h1_words & norm_words(text)):
            continue
        signals = 0
        if _YEAR.search(text):
            signals += 1
        if find_price_in_text(text):
            signals += 1
        if re.search(r"\b\d[\d\s-]{6,}\d\b", text):  # phone-like digit run
            signals += 1
        if signals >= 2:
            return []  # a canonical surface exists; nothing to report

    return [finding(
        "ANS.NO_CANONICAL_FACT_SURFACE",
        "No page states the brand's key facts together in plain text",
        "degrades", "sitewide", "measured", "retrieved",
        "No sampled page combines the brand's own name with at least two independent "
        "kinds of key fact (a year, a price, or a phone-like number) stated together "
        "in plain text. A third party has no single page to copy the brand's basic "
        "facts from."
        % (),
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
                 "brand."],
         "mechanism": "One canonical, plainly-worded page gives both machines and "
                      "third parties a single version of the brand's facts to copy, "
                      "which is how agreement about those facts starts.",
         "effort": "content", "owner": "content",
         "verification": "Confirm the new or updated page states the brand name "
                         "alongside at least two key facts in plain text."})]


# ======================================================== ANS.KEY_FACT_OUTSIDE_MAIN_CONTENT

def check_key_fact_outside_main_content(ctx):
    """A structured core fact exists on the page but the text stating it fell outside
    the extracted main-content region -- a boundary problem distinct from render.py's
    territory (which is about raw HTML vs the rendered DOM, not main vs full text on
    the same, already-rendered-equivalent, raw response).
    """
    findings = []
    hits = []
    for page in ctx.content:
        if page.get("page_type") not in FACT_BEARING_TYPES:
            continue
        structured_price = find_product_price(page)
        if not structured_price:
            continue
        raw_text = page.get("raw_text") or ""
        main_text = page.get("main_text") or ""
        if len(raw_text) < THRESHOLDS["min_main_text_for_comparison"]:
            continue
        in_raw = find_price_in_text(raw_text)
        in_main = find_price_in_text(main_text)
        amount, currency = structured_price
        if in_raw and in_raw[0] == amount and in_raw[1] == currency:
            if not (in_main and in_main[0] == amount and in_main[1] == currency):
                hits.append(page)

    if not hits:
        return findings
    reach = reach_for(hits, ctx.content, ctx.clusters)
    findings.append(finding(
        "ANS.KEY_FACT_OUTSIDE_MAIN_CONTENT",
        "The page's core fact falls outside the extracted main content",
        "degrades", reach, "measured", "retrieved",
        "%d pages state their structured core fact somewhere in the full page text, "
        "but that statement falls outside the region identified as main content -- "
        "typically a sidebar, a repeated banner, or a footer rather than the article "
        "or product body. Example: %s."
        % (len(hits), hits[0]["url"]),
        [p["url"] for p in hits],
        {"method": "the structured price is confirmed present in the page's full "
                   "text, then searched for again within the extracted main-content "
                   "text specifically; present in one and absent from the other is "
                   "the finding",
         "observed": {"pages": [{"url": p["url"]} for p in hits[:8]]},
         "expected": "the core fact stated within the main-content region, not only "
                     "elsewhere on the page",
         "sample": {"checked": len(ctx.content), "failing": len(hits)},
         "confidence": "high", "nondeterministic": False},
        {"summary": "Move the statement of the core fact into the article or product "
                    "body itself, not only into a sidebar, banner or footer element.",
         "how": ["Check where on the page the fact is currently stated (view the "
                 "full page source and compare against the main article or product "
                 "region).",
                 "Restate it in the body copy, alongside its structured "
                 "representation."],
         "mechanism": "Extraction pipelines that identify a page's main content "
                      "region deliberately exclude chrome such as navigation and "
                      "footers. A fact that only exists in that excluded region is "
                      "invisible to the same extraction a retrieval system relies on, "
                      "even though a person skimming the page might still notice it.",
         "effort": "template-change", "owner": "engineering",
         "verification": "Re-check the page's main-content extraction and confirm "
                         "the fact is now present within it."}))
    return findings


CHECKS = (
    check_no_direct_answer_lead,
    check_specs_not_extractable,
    check_unitless_values,
    check_entity_never_named,
    check_no_heading_anchors,
    check_no_summary_block,
    check_no_qa_surface,
    check_no_canonical_fact_surface,
    check_key_fact_outside_main_content,
)


def run(snapshot):
    ctx = Context(snapshot)
    if ctx.blackout:
        ctx.note("page content",
                 "every sampled URL was refused, so answer retrievability could not "
                 "be assessed")
        return [], ctx.not_assessed

    findings = []
    for check in CHECKS:
        findings.extend(check(ctx))
    findings.sort(key=lambda f: (f["check_id"], (f["affected_urls"] or [""])[0]))
    return findings, ctx.not_assessed


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Detect answer-retrievability failures from a site snapshot.",
        epilog="Example: check_answerability.py --snapshot snapshot.json "
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
