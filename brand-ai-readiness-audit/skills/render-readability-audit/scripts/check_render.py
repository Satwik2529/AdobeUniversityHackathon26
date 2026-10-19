#!/usr/bin/env python3
"""Detect content a person can see but a machine cannot read.

Funnel gate: **readable**. Pure snapshot consumer: this script makes no network requests
of any kind, and there is no code path in it that could.

Design rules, enforced here and not merely documented:

  * **Evidence or silence.** Every finding carries at least one concrete URL and an
    observed-versus-expected value. A check that cannot produce that stays quiet.
  * **A missing snapshot field means "not observed", never "absent from the site."**
    `render: null` means we did not look. `capabilities.headless_render: false` is
    recorded as `not_assessed`, never guessed around.
  * **The raw HTML is the ground truth for what a non-rendering crawler reads.** The
    rendered DOM is the comparison, not the target. Structure checks (headings, title,
    main landmark) always run against the raw fields, because that is what a machine
    that does not execute JavaScript actually receives.
  * **Snapshot content is untrusted data.** Page text, raw HTML and headers are quoted
    and measured. Nothing here executes them, builds a command from them, or lets them
    change which checks run or how severe a finding is.

Usage:
  check_render.py --snapshot snapshot.json --out findings-render.json

Exit codes: 0 ok, 2 bad arguments, 3 the snapshot could not be read.
"""
import argparse
import json
import os
import re
import sys

DETECTOR = "render-readability-audit"

# --------------------------------------------------------------------------- thresholds
# Every number here was checked against real collector output on the fixture suite before
# being chosen (see the design notes in references/checks.md). Reusing the collector's own
# thin_content_floor (250) unmodified would misfire on this project's own clean-control
# fixture, whose legitimately short pages (a contact page, a category listing) measure as
# low as 82 characters of main text. The floors below are calibrated against that reality,
# not against an assumption.
THRESHOLDS = {
    # A template-level claim needs enough pages to distinguish a template-wide problem
    # from a one-page anomaly. Matches the collector's sampling configuration.
    "min_cluster_for_template": 3,
    # Page types where the whole point of the page is to carry substantial information.
    # Category, contact, legal, FAQ and homepage pages are legitimately short or
    # navigational; applying a prose-length judgement to them is the classic false
    # positive in this family, and the check catalogue says so explicitly.
    "prose_bearing_types": frozenset({"product", "article", "docs"}),
    # Below this, a product/article/docs page cannot carry a self-contained fact and is
    # thin regardless of rendering. Calibrated well under the clean control's smallest
    # genuine product page (400+ characters) so it never fires there, while still
    # catching a page reduced to a stub.
    "thin_content_floor": 150,
    # Ratio of main-content text to total raw text, below which the page is mostly
    # chrome. Calibrated with a safety margin under the clean control's lowest
    # prose-bearing ratio (~0.68 on a product page) so ordinary boilerplate does not
    # trip it.
    "boilerplate_ratio_floor": 0.20,
    # A genuine content-growth gap after rendering. Two ways to qualify:
    #   (a) raw is near-empty and something substantive appears after render, or
    #   (b) raw has some text but rendering multiplies it well beyond normal variance.
    # A fixed high absolute floor (an earlier version used 200) missed real cases: a
    # page moving from 0 to roughly 100 characters of genuine facts is exactly the
    # shell this check exists to find, and requiring 200 characters of post-render
    # content let it through. The floor is now relative to how thin the raw side is.
    "csr_growth_ratio": 3.0,
    "csr_min_rendered_chars_absolute": 80,
    "min_pages_for_documents_only": 2,
    "min_pages_for_title_duplicate": 5,
    "min_headings_for_jump_check": 4,
    # A structural proxy for "this SVG is probably an infographic carrying real
    # information" rather than a small icon or logo.
    "min_svg_text_nodes": 3,
}

UTILITY_TYPES = {"utility"}
CONFIDENT = {"high", "medium"}

# Generic ARIA and role conventions, not tied to any framework, vendor or site. A
# consent/age gate implemented this way is detectable from raw markup alone; one that
# relies purely on CSS with no semantic marker is not, and is not claimed.
_DIALOG_ROLE = re.compile(r'role\s*=\s*["\']dialog["\']', re.I)
_ARIA_MODAL = re.compile(r'aria-modal\s*=\s*["\']true["\']', re.I)
# aria-modal="false" is a documented WAI-ARIA pattern for a deliberately non-blocking
# dialog (a toast notification, a persistent side panel). Its presence anywhere on the
# page is treated as a page-wide signal that at least one dialog was authored not to
# gate content, which is enough to withhold this check: a false positive here asserts
# the site is doing the opposite of what it explicitly declared, while a missed
# genuine gate is caught by RND.CSR_SHELL or RND.THIN_CONTENT via its content effect
# regardless. This is a whole-page regex scan, not a per-element parse, so a page
# mixing one modal and one deliberately non-modal dialog is not distinguished; that
# imprecision is accepted in the safer direction.
_ARIA_MODAL_FALSE = re.compile(r'aria-modal\s*=\s*["\']false["\']', re.I)
_SVG_BLOCK = re.compile(r"<svg\b.*?</svg>", re.I | re.S)
_SVG_TEXT = re.compile(r"<text\b", re.I)
_SVG_TITLE_OR_DESC = re.compile(r"<(title|desc)\b", re.I)
_SVG_ARIA_LABEL = re.compile(r'aria-label\s*=\s*["\'][^"\']+["\']', re.I)
_CANVAS_TAG = re.compile(r"<canvas\b", re.I)


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


# ------------------------------------------------------------------------------- helpers

def fetched(pages):
    return [p for p in pages if p.get("fetch_ok")]


def is_definitely_utility(page):
    """True only when we are confident this page is a utility surface.

    Deliberately permissive in the other direction: an unclassified or low-confidence
    page is treated as potentially-content, never excluded. A genuinely client-rendered
    page is exactly the page most likely to defeat classification, because the raw HTML
    the classifier reads is itself impoverished. Excluding low-confidence pages from
    render checks would systematically hide the shells this detector exists to find.
    """
    return page.get("page_type") in UTILITY_TYPES and page.get(
        "page_type_confidence") in CONFIDENT


def is_confident_content(page):
    """Stricter gate for prose/structure judgements, where misclassification risk cuts
    the other way: judging a mislabelled utility page for missing an h1 would be wrong.
    """
    if is_definitely_utility(page):
        return False
    if page.get("page_type_confidence") in CONFIDENT and page.get("page_type") != "unknown":
        return True
    return page.get("main_text_len", 0) >= 250


def cluster_index(snapshot):
    return {c["id"]: c for c in snapshot.get("clusters", [])}


def reach_for(pages_hit, population, clusters):
    """sitewide / template / page, obeying the cluster sampling threshold.

    `population` is the denominator relevant to this check (e.g. all confident content
    pages for a structural check, or all render-eligible pages for a shell check) so
    "sitewide" means "every page this check could possibly apply to", not merely "every
    page fetched".
    """
    if not pages_hit:
        return "page"
    if population and len(pages_hit) == len(population) and len(pages_hit) >= 2:
        return "sitewide"
    by_cluster = {}
    for page in pages_hit:
        by_cluster.setdefault(page.get("cluster_id"), []).append(page)
    index = cluster_index({"clusters": []}) if clusters is None else \
        {c["id"]: c for c in clusters}
    for cluster_id, members in by_cluster.items():
        cluster = index.get(cluster_id) or {}
        sampled = cluster.get("sampled") or []
        if (cluster.get("size", 0) >= THRESHOLDS["min_cluster_for_template"]
                and sampled and len(members) == len(sampled)):
            return "template"
    return "page"


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


class Context(object):
    """Everything the checks share, computed once."""

    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.pages = snapshot.get("pages") or []
        self.clusters = snapshot.get("clusters") or []
        self.capabilities = snapshot.get("capabilities") or {}
        self.headless_render = bool(self.capabilities.get("headless_render"))
        self.fetched = fetched(self.pages)
        self.blackout = bool(self.pages) and not self.fetched
        # Render-eligible: any fetched, non-utility page. Deliberately not gated on
        # classification confidence; see is_definitely_utility's docstring.
        self.render_eligible = [p for p in self.fetched if not is_definitely_utility(p)]
        self.content = [p for p in self.fetched if is_confident_content(p)]
        self.rendered = [p for p in self.fetched if (p.get("render") or {}).get("ok")]
        self.not_assessed = []

    def note(self, dimension, reason):
        if not any(item["dimension"] == dimension for item in self.not_assessed):
            self.not_assessed.append({"dimension": dimension, "reason": reason,
                                      "detector": DETECTOR})


# =================================================================== RND.CSR_SHELL et al

def _measured_growth(page):
    """(raw_len, rendered_len, ratio) using main-content length when meaningful.

    Falls back to whole-page text when there is no main landmark, matching the
    collector's own convention that main_text equals the full text in that case.
    """
    render = page.get("render") or {}
    raw_len = page.get("main_text_len", 0) or 0
    rendered_len = render.get("main_text_len", 0) or 0
    if raw_len == 0 and rendered_len == 0:
        raw_len = page.get("raw_text_len", 0) or 0
        rendered_len = render.get("text_len", 0) or 0
    ratio = (rendered_len / float(raw_len)) if raw_len else (
        float("inf") if rendered_len else 0.0)
    return raw_len, rendered_len, ratio


def check_csr_shell(ctx):
    findings = []
    measured_hits, fallback_hits = [], []

    for page in ctx.render_eligible:
        render = page.get("render") or {}
        if render.get("ok"):
            raw_len, rendered_len, ratio = _measured_growth(page)
            required_rendered = max(THRESHOLDS["csr_min_rendered_chars_absolute"],
                                    raw_len * THRESHOLDS["csr_growth_ratio"])
            if (raw_len < THRESHOLDS["thin_content_floor"]
                    and rendered_len >= required_rendered
                    and rendered_len >= THRESHOLDS["csr_min_rendered_chars_absolute"]):
                measured_hits.append((page, raw_len, rendered_len, ratio))
        elif not ctx.headless_render:
            weights = [s.get("weight") for s in (page.get("spa_signals") or [])]
            highs = weights.count("high")
            mediums = weights.count("medium")
            if highs >= 2:
                fallback_hits.append((page, "blocks", page.get("spa_signals")))
            elif highs >= 1 and mediums >= 1:
                fallback_hits.append((page, "degrades", page.get("spa_signals")))

    if measured_hits:
        pages_hit = [h[0] for h in measured_hits]
        reach = reach_for(pages_hit, ctx.render_eligible, ctx.clusters)
        example = measured_hits[0]
        findings.append(finding(
            "RND.CSR_SHELL",
            "Content only exists after JavaScript runs",
            "blocks", reach, "measured", "readable",
            "%d of %d render-eligible pages carry far less text in the raw HTML than in "
            "the rendered page. Example: %s measured %d characters of main content "
            "before rendering and %d characters after, a %.1fx growth. A crawler that "
            "does not execute JavaScript, which the major AI crawlers do not, receives "
            "the smaller figure."
            % (len(measured_hits), len(ctx.render_eligible), example[0]["url"],
               example[1], example[2], example[3]),
            [h[0]["url"] for h in measured_hits],
            {"method": "main-content text length compared between the raw HTML fetch and "
                       "the rendered DOM, both captured for the same page",
             "observed": {"pages": [{"url": p["url"], "raw_chars": r, "rendered_chars": v,
                                     "ratio": round(rt, 2)}
                                    for p, r, v, rt in measured_hits[:8]]},
             "expected": "raw HTML carries the bulk of the content a browser shows",
             "sample": {"checked": len(ctx.render_eligible), "failing": len(measured_hits)},
             "confidence": "high", "nondeterministic": False},
            {"summary": "Server-render or pre-render the page's core content so it is "
                        "present in the initial HTML response, before any script runs.",
             "how": [
                 "Identify the framework responsible (the render comparison shows a "
                 "large content gap; the collector's spa_signals field on the same page "
                 "names the empty mount point if one was involved).",
                 "Enable server-side rendering or static pre-rendering for this "
                 "template, so the fact set is in the response body.",
                 "Verify with `curl` or view-source, not a browser's inspector, which "
                 "shows the post-JavaScript DOM and will hide this problem.",
                 "Keep interactive enhancement client-side; only the substantive content "
                 "needs to be server-rendered."],
             "mechanism": "This is the readable gate. The crawlers that assemble AI "
                          "answers fetch raw HTML and do not execute JavaScript, so "
                          "content that exists only after a script runs is never seen, "
                          "however good it is. Reopening this gate is a precondition for "
                          "citation, not a guarantee of one.",
             "effort": "platform-change", "owner": "engineering",
             "verification": "Fetch the page without a browser and confirm the core "
                             "facts are present in the response body."}))

    if fallback_hits and not measured_hits:
        ctx.note("browser render comparison",
                 "no headless browser was available in this run, so the pages below "
                 "were screened using static signals only, at reduced confidence: %s"
                 % ", ".join(sorted({p["url"] for p, _, _ in fallback_hits}))[:400])
        blocks = [h for h in fallback_hits if h[1] == "blocks"]
        degrades = [h for h in fallback_hits if h[1] == "degrades"]
        for tier_hits, impact in ((blocks, "blocks"), (degrades, "degrades")):
            if not tier_hits:
                continue
            reach = reach_for([h[0] for h in tier_hits], ctx.render_eligible, ctx.clusters)
            example = tier_hits[0]
            findings.append(finding(
                "RND.CSR_SHELL",
                "Content appears to exist only after JavaScript runs",
                impact, reach, "measured", "readable",
                "%d pages show the structural signature of a client-rendered shell in "
                "the raw HTML: %s. No headless browser was available in this run to "
                "confirm directly by comparison, so this is inferred from structure "
                "rather than measured against a render."
                % (len(tier_hits), "; ".join(
                    "%s (%s)" % (example[0]["url"],
                                ", ".join("%s/%s" % (s["signal"], s["weight"])
                                          for s in example[2]))
                    for example in tier_hits[:1])),
                [h[0]["url"] for h in tier_hits],
                {"method": "static structural signals computed by the collector: an "
                           "empty framework mount point, thin main content, a noscript "
                           "notice, or a script-to-text ratio far above normal",
                 "observed": {"pages": [{"url": p["url"], "signals": s}
                                        for p, _, s in tier_hits[:8]]},
                 "expected": "no combination of these signals on a content page",
                 "sample": {"checked": len(ctx.render_eligible), "failing": len(tier_hits)},
                 "confidence": "medium", "nondeterministic": False,
                 "note": "confirm with a real render comparison when a browser is "
                         "available; this fallback trades recall for the ability to "
                         "screen without one"},
                {"summary": "Confirm with a real browser render comparison, then "
                            "server-render or pre-render the core content if confirmed.",
                 "how": [
                     "Run this audit with a headless browser available, or manually "
                     "compare `curl` output against a browser's view-source for these "
                     "URLs.",
                     "If confirmed, enable server-side rendering or static pre-rendering "
                     "for the template.",
                     "Keep interactive enhancement client-side."],
                 "mechanism": "The same mechanism as a confirmed shell: crawlers that do "
                              "not execute JavaScript receive only what is in the raw "
                              "response. This is flagged at reduced confidence because "
                              "it was inferred from structure, not measured directly.",
                 "effort": "platform-change", "owner": "engineering",
                 "verification": "Re-run with a browser available and confirm the raw "
                                 "versus rendered comparison."}))
    return findings


def check_partial_js_content(ctx):
    """A structural fact-block (a table or definition list) exists only after render.

    Deliberately narrower than CSR_SHELL: this fires on pages with substantial raw text
    overall (so they would not qualify as a shell) where specifically the structured
    fact block -- the table or definition list a specification or price list would live
    in -- is absent from the raw HTML and present after rendering.
    """
    findings = []
    hits = []
    for page in ctx.rendered:
        render = page.get("render") or {}
        raw_structured = (page.get("tables", 0) or 0) + (page.get("definition_lists", 0) or 0)
        rendered_structured = (render.get("tables", 0) or 0) + (
            render.get("definition_lists", 0) or 0)
        raw_main = page.get("main_text_len", 0) or 0
        if (raw_structured == 0 and rendered_structured > 0
                and raw_main >= THRESHOLDS["thin_content_floor"]):
            hits.append(page)

    if not hits:
        return findings
    reach = reach_for(hits, ctx.rendered, ctx.clusters)
    example = hits[0]
    findings.append(finding(
        "RND.PARTIAL_JS_CONTENT",
        "A structured fact block exists only after rendering",
        "blocks", reach, "measured", "readable",
        "%d pages carry substantial prose in the raw HTML (so they are not a full "
        "shell) but their only table or definition list, the structural home for a "
        "specification or price list, is absent from the raw response and present "
        "only after rendering. Example: %s has 0 raw tables or lists and %d after "
        "rendering."
        % (len(hits), example["url"],
           (example.get("render") or {}).get("tables", 0)
           + (example.get("render") or {}).get("definition_lists", 0)),
        [p["url"] for p in hits],
        {"method": "count of table and definition-list elements compared between the "
                   "raw HTML and the rendered DOM, on pages with substantial raw text",
         "observed": {"pages": [{"url": p["url"],
                                 "raw_structured_blocks":
                                     (p.get("tables", 0) or 0)
                                     + (p.get("definition_lists", 0) or 0),
                                 "rendered_structured_blocks":
                                     ((p.get("render") or {}).get("tables", 0) or 0)
                                     + ((p.get("render") or {}).get(
                                         "definition_lists", 0) or 0)}
                                for p in hits[:8]]},
         "expected": "a fact-bearing structural block present in the raw HTML",
         "sample": {"checked": len(ctx.rendered), "failing": len(hits)},
         "confidence": "high", "nondeterministic": False},
        {"summary": "Move the specification or price table into the initial HTML "
                    "response rather than injecting it after the page loads.",
         "how": ["Render the table or definition list server-side, in the same "
                 "template that already renders the surrounding prose.",
                 "Keep any interactive sorting or filtering of that table client-side; "
                 "only the initial data needs to be in the response.",
                 "Verify with view-source, not a browser inspector."],
         "mechanism": "The surrounding prose is already reachable, which is why this "
                      "is narrower than a full shell finding, but the specific "
                      "structured facts a question is likely to ask for are not.",
         "effort": "template-change", "owner": "engineering",
         "verification": "Fetch the page without a browser and confirm the table or "
                         "list is present in the response body."}))
    return findings


def check_js_only_structured_data(ctx):
    findings = []
    hits = []
    for page in ctx.rendered:
        render = page.get("render") or {}
        raw_sd = page.get("structured_data") or {}
        raw_valid = sum(1 for b in (raw_sd.get("jsonld") or []) if b.get("parse_ok"))
        raw_micro = len(raw_sd.get("microdata_types") or [])
        rendered_sd = render.get("structured_data") or {}
        rendered_valid = sum(1 for b in (rendered_sd.get("jsonld") or [])
                             if b.get("parse_ok"))
        rendered_micro = len(rendered_sd.get("microdata_types") or [])
        if (rendered_valid > raw_valid) or (rendered_micro > raw_micro):
            hits.append((page, raw_valid, rendered_valid, raw_micro, rendered_micro))

    if not hits:
        return findings
    reach = reach_for([h[0] for h in hits], ctx.rendered, ctx.clusters)
    example = hits[0]
    findings.append(finding(
        "RND.JS_ONLY_STRUCTURED_DATA",
        "Structured data is injected only by JavaScript",
        "degrades", reach, "measured", "readable",
        "%d pages carry more valid structured-data blocks in the rendered DOM than in "
        "the raw HTML. Example: %s has %d valid JSON-LD block(s) in the raw response "
        "and %d after rendering. A crawler that does not execute JavaScript never sees "
        "the markup that was added after load."
        % (len(hits), example[0]["url"], example[1], example[2]),
        [h[0]["url"] for h in hits],
        {"method": "count of successfully parsed JSON-LD blocks and Microdata types, "
                   "compared between the raw HTML and the rendered DOM",
         "observed": {"pages": [{"url": p["url"], "raw_valid_jsonld": rv,
                                 "rendered_valid_jsonld": nv,
                                 "raw_microdata_types": rm, "rendered_microdata_types": nm}
                                for p, rv, nv, rm, nm in hits[:8]]},
         "expected": "the same or more structured data in the raw HTML as in the "
                     "rendered DOM",
         "sample": {"checked": len(ctx.rendered), "failing": len(hits)},
         "confidence": "high", "nondeterministic": False},
        {"summary": "Emit structured data in the initial HTML response rather than "
                    "injecting it after the page loads.",
         "how": ["Move the JSON-LD script block into the server-rendered template.",
                 "If a client-side framework currently injects it into <head> after "
                 "hydration, render it server-side instead; the markup itself does not "
                 "need to change.",
                 "Validate with a plain HTTP fetch, not a browser, since the browser "
                 "will show the post-JavaScript state."],
         "mechanism": "Structured data helps a machine classify content and resolve "
                      "which entity a page is about. Markup that only exists after a "
                      "script runs is invisible to a crawler that does not execute "
                      "scripts, so it provides none of that benefit to those crawlers.",
         "effort": "template-change", "owner": "engineering",
         "verification": "Fetch the page without a browser and confirm the structured "
                         "data is present in the response body."}))
    return findings


# =============================================================== facts in non-text media

FACT_BEARING_IMAGE_TYPES = frozenset({"product"})
FACT_BEARING_DOCUMENT_TYPES = frozenset({"product", "docs", "press"})


def check_facts_in_images(ctx):
    findings = []
    hits = []
    for page in ctx.content:
        if page.get("page_type") not in FACT_BEARING_IMAGE_TYPES:
            continue
        structured = (page.get("tables", 0) or 0) + (page.get("definition_lists", 0) or 0)
        if structured > 0:
            continue  # the facts have a textual home; an image alongside them is fine
        suspect_images = [img for img in (page.get("images") or [])
                          if img.get("in_content")
                          and (not img.get("has_alt") or not (img.get("alt") or "").strip())]
        if suspect_images:
            hits.append((page, suspect_images))

    if not hits:
        return findings
    reach = reach_for([h[0] for h in hits], ctx.content, ctx.clusters)
    example = hits[0]
    findings.append(finding(
        "RND.FACTS_IN_IMAGES",
        "Product pages may hold specification facts only in images",
        "degrades", reach, "inferred", "readable",
        "%d product pages carry no table or definition list to hold specification "
        "facts in text, and also contain in-content images with no descriptive "
        "alternative text. Example: %s has %d such image(s), for instance %s. Where "
        "any of these images conveys information such as a dimension, a specification "
        "or a price, that information does not exist in a form a crawler can read; a "
        "purely decorative image correctly keeps an empty alt and is not itself a "
        "problem."
        % (len(hits), example[0]["url"], len(example[1]),
           example[1][0].get("src", "")),
        [p["url"] for p, _ in hits],
        {"method": "presence of a table or definition list on the page, cross-checked "
                   "against in-content images with no alt text, on pages classified as "
                   "the product page type",
         "observed": {"pages": [{"url": p["url"], "images_without_alt":
                                 [img.get("src") for img in imgs]}
                                for p, imgs in hits[:8]]},
         "expected": "specification facts stated in text, or informative images "
                     "carrying descriptive alt text",
         "sample": {"checked": len(ctx.content), "failing": len(hits)},
         "confidence": "medium", "nondeterministic": False,
         "note": "this check cannot tell which images are decorative and which carry "
                 "information; a human review of the listed images is the next step"},
        {"summary": "For each listed image that conveys information rather than "
                    "decoration, add the same facts as visible text near the image, or "
                    "add a descriptive alt attribute stating them.",
         "how": ["Review the images listed in the evidence for this page.",
                 "Where an image shows a dimension, a specification table, or a price, "
                 "add that as plain text or as an HTML table alongside it.",
                 "Where an image is purely decorative, an empty alt is correct and no "
                 "change is needed for that image."],
         "mechanism": "The more explicitly a fact is stated in plain readable text, "
                      "the more reliably it is extracted; a fact locked in an image "
                      "with no text equivalent is invisible to a crawler that reads "
                      "text, whichever crawler that is.",
         "effort": "content", "owner": "content",
         "verification": "View the page's extracted text (not a screenshot) and "
                         "confirm the specification facts are present in it."}))
    return findings


def check_facts_in_documents_only(ctx):
    findings = []
    hits = []
    for page in ctx.content:
        if page.get("page_type") not in FACT_BEARING_DOCUMENT_TYPES:
            continue
        if not page.get("documents"):
            continue
        structured = (page.get("tables", 0) or 0) + (page.get("definition_lists", 0) or 0)
        if structured == 0:
            hits.append(page)

    if len(hits) < THRESHOLDS["min_pages_for_documents_only"]:
        return findings
    reach = reach_for(hits, ctx.content, ctx.clusters)
    example = hits[0]
    findings.append(finding(
        "RND.FACTS_IN_DOCUMENTS_ONLY",
        "Specification facts are reachable only inside a linked document",
        "weakens", reach, "inferred", "readable",
        "%d pages link to a PDF or office document and carry no table or definition "
        "list of their own. Example: %s links to %s but states no specifications in "
        "text on the page itself. A linked document is markedly less likely to be "
        "read, fetched or quoted than the page's own text."
        % (len(hits), example["url"], example["documents"][0]),
        [p["url"] for p in hits],
        {"method": "presence of linked PDF or office documents, cross-checked against "
                   "the absence of a table or definition list on the linking page",
         "observed": {"pages": [{"url": p["url"], "documents": p.get("documents")}
                                for p in hits[:8]]},
         "expected": "the same facts also stated in the page's own text",
         "sample": {"checked": len(ctx.content), "failing": len(hits)},
         "confidence": "medium", "nondeterministic": False},
        {"summary": "Publish the specification facts as plain HTML text or a table on "
                    "the page itself, keeping the document as a supplementary download.",
         "how": ["Extract the key facts from the linked document into a table or list "
                 "in the page's own HTML.",
                 "Keep the document linked for readers who want the full detail."],
         "mechanism": "A fact stated in the page's own text is far more reachable, "
                      "readable and quotable than one that requires opening a separate "
                      "document, which not every crawler follows or parses.",
         "effort": "content", "owner": "content",
         "verification": "Read the page's own extracted text and confirm the key facts "
                         "appear there without opening the linked document."}))
    return findings


def check_text_in_nontext_element(ctx):
    """Substantive text drawn into canvas or an untitled SVG, on an otherwise thin page.

    Narrow and conservative by design: canvas and SVG are used for countless benign
    purposes (icons, charts, decoration), so this only fires when the page's own text is
    thin AND the element looks like it is carrying content rather than decoration.
    """
    findings = []
    hits = []
    for page in ctx.content:
        html = page.get("raw_html") or ""
        if not html:
            continue
        main_len = page.get("main_text_len", 0) or 0
        if main_len >= THRESHOLDS["thin_content_floor"]:
            continue

        reasons = []
        if _CANVAS_TAG.search(html):
            reasons.append("a <canvas> element is present")
        for svg in _SVG_BLOCK.findall(html):
            text_nodes = len(_SVG_TEXT.findall(svg))
            if (text_nodes >= THRESHOLDS["min_svg_text_nodes"]
                    and not _SVG_TITLE_OR_DESC.search(svg)
                    and not _SVG_ARIA_LABEL.search(svg)):
                reasons.append("an <svg> with %d text nodes and no title, desc or "
                              "aria-label" % text_nodes)
                break
        if reasons:
            hits.append((page, reasons))

    for page, reasons in hits:
        findings.append(finding(
            "RND.TEXT_IN_NONTEXT_ELEMENT",
            "Page content may be rendered into a non-text element",
            "degrades", "page", "inferred", "readable",
            "%s has only %d characters of main text, and its raw HTML contains %s. "
            "Text drawn into canvas has no DOM text node at all; text placed in an SVG "
            "without a title, desc or label is not reliably associated with what it "
            "means. Either pattern can make substantive content invisible to a text "
            "extractor even though a person can see it."
            % (page["url"], page.get("main_text_len", 0), " and ".join(reasons)),
            [page["url"]],
            {"method": "presence of canvas or SVG elements in the raw HTML, correlated "
                       "with thin extracted main text on the same page",
             "observed": {"main_text_len": page.get("main_text_len"),
                          "reasons": reasons},
             "expected": "substantive content available as real text",
             "sample": {"checked": 1, "failing": 1},
             "confidence": "medium", "nondeterministic": False,
             "note": "canvas and SVG have many legitimate non-content uses; this is "
                     "reported for review, not as a certain defect"},
            {"summary": "If this element carries information rather than decoration, "
                        "add the same content as real text alongside it.",
             "how": ["Check what the canvas or SVG element in the evidence actually "
                     "shows.",
                     "If it conveys information, add a plain-text equivalent nearby, or "
                     "an accessible title/desc on the SVG.",
                     "If it is decorative (an icon, a logo, a chart with no unique "
                     "information), no change is needed."],
             "mechanism": "A crawler that reads text finds nothing inside a canvas and "
                          "nothing reliably associated with an untitled SVG's text "
                          "nodes. Content is only readable when it exists as real,\n"
                          "labelled text.",
             "effort": "content", "owner": "content",
             "verification": "Select the visible text with a mouse (canvas content "
                             "cannot be selected at all) and confirm it also appears in "
                             "the page's extracted text."}))
    return findings


# ============================================================================ gates in raw

def check_interstitial_in_raw(ctx):
    findings = []
    hits = []
    for page in ctx.render_eligible:
        html = page.get("raw_html") or ""
        if not html:
            continue
        main_len = page.get("main_text_len", 0) or 0
        if main_len >= THRESHOLDS["thin_content_floor"]:
            continue
        if _ARIA_MODAL_FALSE.search(html):
            continue  # explicitly declared non-modal; not what this check targets
        if _DIALOG_ROLE.search(html) or _ARIA_MODAL.search(html):
            hits.append(page)

    if not hits:
        return findings
    reach = reach_for(hits, ctx.render_eligible, ctx.clusters)
    example = hits[0]
    findings.append(finding(
        "RND.INTERSTITIAL_IN_RAW",
        "A gate appears to replace content in the raw response",
        "blocks", reach, "measured", "readable",
        "%d pages combine a thin raw response (%s: %d characters of main text) with a "
        "dialog or modal marker (role=\"dialog\" or aria-modal=\"true\") in the raw "
        "HTML. When the response is this thin and already declares a dialog, the "
        "dialog is plausibly most of what a non-rendering crawler receives, rather "
        "than an overlay on top of substantial content."
        % (len(hits), example["url"], example.get("main_text_len", 0)),
        [p["url"] for p in hits],
        {"method": "presence of an ARIA dialog or modal marker in the raw HTML, "
                   "correlated with thin extracted main text on the same page",
         "observed": {"pages": [{"url": p["url"], "main_text_len": p.get("main_text_len")}
                                for p in hits[:8]]},
         "expected": "substantive page content in the raw response, independent of any "
                     "consent or gate overlay",
         "sample": {"checked": len(ctx.render_eligible), "failing": len(hits)},
         "confidence": "medium", "nondeterministic": False,
         "note": "raw HTML alone cannot prove the dialog visually occupies the page; "
                 "this is reported from the combination of thinness and the marker"},
        {"summary": "Serve the page's real content in the initial response and layer "
                    "consent, age or locale gates on top of it, rather than in place of "
                    "it.",
         "how": ["Confirm which of the listed pages are gated this way.",
                 "Render the underlying page content server-side regardless of consent "
                 "state, and use the gate purely as a client-side overlay.",
                 "Where a jurisdiction genuinely requires blocking content pre-consent, "
                 "there is no readability fix; note the trade-off deliberately."],
         "mechanism": "A machine that does not execute JavaScript, or that fetches the "
                      "page directly, receives whatever the raw response contains. A "
                      "response dominated by a gate contains no page content to be "
                      "read, however good the content is once the gate is dismissed.",
         "effort": "template-change", "owner": "engineering",
         "verification": "Fetch the page without a browser and confirm the substantive "
                         "content, not just the gate, is present in the response."}))
    return findings


# ======================================================= content behind interaction gate

def check_content_behind_interaction(ctx):
    """Always not_assessed.

    This check exists in the catalogue because a genuine failure mode exists: content
    that only enters the DOM after a click on a tab or accordion. It cannot be measured
    by this marketplace's architecture, with or without a browser, because the collector
    is built to never interact with a page -- it loads and waits, and does not click,
    which is a deliberate safety property (see site-snapshot-collector's SKILL.md), not
    an oversight. Recording a guess here, using indirect proxies that cannot actually
    confirm or rule out click-triggered content, would risk exactly the kind of
    fabricated evidence this marketplace is built to avoid. The honest position is
    permanent non-assessment, not a lower-confidence attempt.
    """
    ctx.note("content behind interaction",
             "this marketplace's collector never clicks, submits or interacts with a "
             "page by design, so content that only appears after a tab, accordion or "
             "similar interaction cannot be distinguished from content that was never "
             "going to appear at all. This is a permanent architectural limit, not a "
             "capability that a browser being available would remove.")
    return []


# ==================================================================== semantic structure

def check_h1(ctx):
    findings = []
    zero, multiple = [], []
    for page in ctx.content:
        h1_count = sum(1 for h in (page.get("headings") or []) if h.get("level") == 1)
        if h1_count == 0:
            zero.append(page)
        elif h1_count > 1:
            multiple.append((page, h1_count))

    if len(zero) >= THRESHOLDS["min_cluster_for_template"] or (
            zero and reach_for(zero, ctx.content, ctx.clusters) != "page"):
        reach = reach_for(zero, ctx.content, ctx.clusters)
        findings.append(finding(
            "RND.NO_H1",
            "Content pages have no top-level heading",
            "weakens", reach, "measured", "readable",
            "%d of %d sampled content pages carry no h1. Examples: %s."
            % (len(zero), len(ctx.content), ", ".join(p["url"] for p in zero[:3])),
            [p["url"] for p in zero],
            {"method": "count of level-1 headings extracted from the raw HTML",
             "observed": {"pages_without_h1": [p["url"] for p in zero[:10]]},
             "expected": "exactly one h1 naming the page's subject",
             "sample": {"checked": len(ctx.content), "failing": len(zero)},
             "confidence": "high", "nondeterministic": False},
            {"summary": "Add one h1 to each of these templates, naming the specific "
                        "subject of that page.",
             "how": ["Use the page's own subject, not the site name, as the h1 text.",
                     "Keep it to one h1 per page; use h2 and below for sections."],
             "mechanism": "An h1 is the strongest structural signal of what a page is "
                          "about. Its absence makes it harder for a machine to confirm "
                          "the subject and to distinguish content from chrome.",
             "effort": "template-change", "owner": "engineering",
             "verification": "View source and confirm exactly one h1 naming the page's "
                             "subject."}))

    if multiple:
        pages = [p for p, _ in multiple]
        reach = reach_for(pages, ctx.content, ctx.clusters)
        example = multiple[0]
        findings.append(finding(
            "RND.MULTIPLE_H1",
            "Several h1 elements compete to name the page",
            "weakens", reach, "measured", "readable",
            "%d pages carry more than one h1. Example: %s has %d."
            % (len(multiple), example[0]["url"], example[1]),
            [p["url"] for p, _ in multiple],
            {"method": "count of level-1 headings extracted from the raw HTML",
             "observed": {"pages": [{"url": p["url"], "h1_count": c}
                                    for p, c in multiple[:10]]},
             "expected": "exactly one h1 per page",
             "sample": {"checked": len(ctx.content), "failing": len(multiple)},
             "confidence": "high", "nondeterministic": False},
            {"summary": "Reduce each page to one h1 naming its primary subject, and "
                        "demote the others to h2 or below.",
             "how": ["Some sectioning patterns legitimately use more than one h1 inside "
                     "independent sections; where that is not the intent here, keep "
                     "only the one that names the page as a whole."],
             "mechanism": "Multiple h1 elements make it ambiguous which one names the "
                          "page, which weakens rather than blocks understanding.",
             "effort": "template-change", "owner": "engineering",
             "verification": "View source and confirm one h1 remains."},
            severity_ceiling="low"))
    return findings


def check_heading_jumps(ctx):
    findings = []
    hits = []
    for page in ctx.content:
        headings = [h for h in (page.get("headings") or []) if h.get("level")]
        if len(headings) < THRESHOLDS["min_headings_for_jump_check"]:
            continue
        levels = [h["level"] for h in headings]
        for previous, current in zip(levels, levels[1:]):
            if current - previous > 1:
                hits.append(page)
                break

    if not hits:
        return findings
    reach = reach_for(hits, ctx.content, ctx.clusters)
    findings.append(finding(
        "RND.HEADING_LEVEL_JUMPS",
        "Heading levels skip, breaking the outline",
        "weakens", reach, "measured", "readable",
        "%d pages with 4 or more headings have at least one level jump of more than "
        "one step, for example h2 directly to h4. Example: %s."
        % (len(hits), hits[0]["url"]),
        [p["url"] for p in hits],
        {"method": "sequence of heading levels extracted from the raw HTML, checked "
                   "for jumps greater than one level, on pages with at least 4 "
                   "headings",
         "observed": {"pages": [{"url": p["url"],
                                 "levels": [h["level"] for h in p.get("headings") or []]}
                                for p in hits[:8]]},
         "expected": "heading levels increase by at most one step at a time",
         "sample": {"checked": len(ctx.content), "failing": len(hits)},
         "confidence": "high", "nondeterministic": False},
        {"summary": "Fill in the skipped heading levels so the outline descends one "
                    "step at a time.",
         "how": ["Replace a jump such as h2 to h4 with h2 to h3 to h4, or demote the "
                 "deeper heading if no intermediate section exists."],
         "mechanism": "A skipped level breaks the outline a machine would otherwise use "
                      "to navigate straight to the section that answers a question.",
         "effort": "template-change", "owner": "content",
         "verification": "List the heading levels on the page and confirm no step "
                         "exceeds one."},
        severity_ceiling="low"))
    return findings


def check_main_landmark(ctx):
    findings = []
    missing = [p for p in ctx.content if not p.get("has_main_landmark")]
    if len(missing) < THRESHOLDS["min_cluster_for_template"]:
        return findings
    reach = reach_for(missing, ctx.content, ctx.clusters)
    findings.append(finding(
        "RND.NO_MAIN_LANDMARK",
        "Content pages have no main or article landmark",
        "weakens", reach, "measured", "readable",
        "%d of %d sampled content pages have no main or article element distinguishing "
        "content from surrounding chrome. Examples: %s."
        % (len(missing), len(ctx.content), ", ".join(p["url"] for p in missing[:3])),
        [p["url"] for p in missing],
        {"method": "presence of a main or article landmark, recorded during HTML "
                   "extraction",
         "observed": {"pages_without_landmark": [p["url"] for p in missing[:10]]},
         "expected": "a main or article element wrapping the page's content",
         "sample": {"checked": len(ctx.content), "failing": len(missing)},
         "confidence": "high", "nondeterministic": False},
        {"summary": "Wrap each template's content in a main or article element, "
                    "outside the header, navigation and footer.",
         "how": ["Add a single <main> around the content unique to the page.",
                 "Many valid layouts omit this; treat it as a low-cost improvement "
                 "rather than an urgent fix."],
         "mechanism": "A landmark helps a machine separate content from chrome without "
                      "guessing, which is what the boilerplate-ratio check otherwise "
                      "has to approximate.",
         "effort": "template-change", "owner": "engineering",
         "verification": "View source and confirm a main or article element wraps the "
                         "page's own content."},
        severity_ceiling="low"))
    return findings


def check_boilerplate_ratio(ctx):
    findings = []
    hits = []
    for page in ctx.content:
        if not page.get("has_main_landmark"):
            continue  # no reliable extraction to judge a ratio from
        if page.get("page_type") not in THRESHOLDS["prose_bearing_types"] | {"about"}:
            continue
        raw_len = page.get("raw_text_len", 0) or 0
        main_len = page.get("main_text_len", 0) or 0
        if raw_len <= 0:
            continue
        ratio = main_len / float(raw_len)
        if ratio < THRESHOLDS["boilerplate_ratio_floor"]:
            hits.append((page, ratio))

    if not hits:
        return findings
    reach = reach_for([h[0] for h in hits], ctx.content, ctx.clusters)
    example = hits[0]
    findings.append(finding(
        "RND.BOILERPLATE_RATIO",
        "Main content is a small fraction of the page",
        "weakens", reach, "measured", "readable",
        "%d pages have a main-content landmark holding less than %.0f%% of the page's "
        "total text. Example: %s: %d of %d characters are inside the main landmark "
        "(%.0f%%)."
        % (len(hits), THRESHOLDS["boilerplate_ratio_floor"] * 100, example[0]["url"],
           example[0].get("main_text_len", 0), example[0].get("raw_text_len", 0),
           example[1] * 100),
        [p["url"] for p, _ in hits],
        {"method": "ratio of main-content text length to total raw text length, only "
                   "on pages with a main or article landmark present",
         "observed": {"pages": [{"url": p["url"], "ratio": round(r, 3),
                                 "main_text_len": p.get("main_text_len"),
                                 "raw_text_len": p.get("raw_text_len")}
                                for p, r in hits[:8]]},
         "expected": "the main landmark holding the substantial majority of page text",
         "sample": {"checked": len(ctx.content), "failing": len(hits)},
         "confidence": "high", "nondeterministic": False},
        {"summary": "Reduce repeated navigation, promotional or boilerplate text inside "
                    "or around the main landmark so the substantive content dominates "
                    "the page.",
         "how": ["Check what is inside the main element versus outside it.",
                 "Move navigation, related-links blocks and repeated footer content "
                 "outside the main landmark if they are currently inside it.",
                 "Where the ratio is low because of genuinely large chrome (a heavy "
                 "mega-menu, a long related-products rail), consider trimming it."],
         "mechanism": "A low ratio makes it harder for extraction to find the part of "
                      "the page actually worth quoting, and dilutes the signal that "
                      "distinguishes this page from every other page sharing the same "
                      "chrome.",
         "effort": "template-change", "owner": "engineering",
         "verification": "Recompute the ratio after the change and confirm it clears "
                         "the floor."}))
    return findings


def check_thin_content(ctx):
    findings = []
    hits = []
    for page in ctx.content:
        if page.get("page_type") not in THRESHOLDS["prose_bearing_types"]:
            continue
        render = page.get("render") or {}
        effective_len = render.get("main_text_len") if render.get("ok") else None
        if effective_len is None:
            effective_len = page.get("main_text_len", 0) or 0
        if effective_len < THRESHOLDS["thin_content_floor"]:
            hits.append((page, effective_len))

    if len(hits) < THRESHOLDS["min_cluster_for_template"]:
        return findings
    reach = reach_for([h[0] for h in hits], ctx.content, ctx.clusters)
    example = hits[0]
    findings.append(finding(
        "RND.THIN_CONTENT",
        "Content pages carry very little text, even after rendering",
        "weakens", reach, "measured", "readable",
        "%d pages of a type expected to carry substantial information (product, "
        "article or documentation) measure under %d characters of main content, using "
        "the rendered figure where a render was available. Example: %s: %d characters."
        % (len(hits), THRESHOLDS["thin_content_floor"], example[0]["url"], example[1]),
        [p["url"] for p, _ in hits],
        {"method": "main-content text length, using the rendered measurement when "
                   "available and the raw measurement otherwise, so this reflects "
                   "genuine thinness rather than a render gap already reported "
                   "separately",
         "observed": {"pages": [{"url": p["url"], "effective_main_text_len": length}
                                for p, length in hits[:8]]},
         "expected": "a self-contained statement of the page's core fact, well above "
                     "the floor",
         "sample": {"checked": len(ctx.content), "failing": len(hits)},
         "confidence": "high", "nondeterministic": False},
        {"summary": "Add the substantive information this page type is expected to "
                    "carry: for a product, its specifications and description; for an "
                    "article, the body; for documentation, the explanation.",
         "how": ["Compare this page against a well-developed page of the same type on "
                 "the same site and identify what is missing.",
                 "This is a content gap, not a markup or rendering gap: the text needs "
                 "to be written, not merely relocated."],
         "mechanism": "A page with almost nothing to say has almost nothing for a "
                      "crawler to extract or quote, independent of how readable its "
                      "markup is.",
         "effort": "content", "owner": "content",
         "verification": "Recount the main content length after the addition and "
                         "confirm it clears the floor."}))
    return findings


def check_title(ctx):
    findings = []
    missing = [p for p in ctx.content if not (p.get("title") or "").strip()]
    if missing:
        reach = reach_for(missing, ctx.content, ctx.clusters)
        findings.append(finding(
            "RND.TITLE_MISSING",
            "Content pages have no title element",
            "degrades", reach, "measured", "readable",
            "%d of %d sampled content pages have no title, or an empty one. Examples: "
            "%s."
            % (len(missing), len(ctx.content), ", ".join(p["url"] for p in missing[:3])),
            [p["url"] for p in missing],
            {"method": "presence of non-empty title text extracted from the raw HTML",
             "observed": {"pages_without_title": [p["url"] for p in missing[:10]]},
             "expected": "a descriptive, non-empty title on every content page",
             "sample": {"checked": len(ctx.content), "failing": len(missing)},
             "confidence": "low", "nondeterministic": False},
            {"summary": "Add a descriptive title to each of these pages, naming the "
                        "specific subject rather than only the site name.",
             "how": ["Set the title from the page's own subject.",
                     "Keep the site name as a suffix rather than the whole title."],
             "mechanism": "The title is one of the first signals used to classify and "
                          "summarise a page. An empty one gives a machine nothing to "
                          "work with before it reads the body.",
             "effort": "template-change", "owner": "content",
             "verification": "View source and confirm a descriptive title is present."}))

    normalised = {}
    for page in ctx.content:
        title = re.sub(r"\s+", " ", (page.get("title") or "")).strip().casefold()
        if title:
            normalised.setdefault(title, []).append(page)
    for title, pages in sorted(normalised.items()):
        if len(pages) >= THRESHOLDS["min_pages_for_title_duplicate"]:
            reach = reach_for(pages, ctx.content, ctx.clusters)
            findings.append(finding(
                "RND.TITLE_DUPLICATE",
                "The same title is shared across many distinct pages",
                "weakens", reach, "measured", "readable",
                "%d distinct pages share the title %r. Examples: %s."
                % (len(pages), pages[0].get("title"),
                   ", ".join(p["url"] for p in pages[:3])),
                [p["url"] for p in pages],
                {"method": "titles normalised for whitespace and case, then grouped "
                           "across sampled content pages",
                 "observed": {"shared_title": pages[0].get("title"),
                              "pages": [p["url"] for p in pages[:10]]},
                 "expected": "a distinct title per distinct page",
                 "sample": {"checked": len(ctx.content), "failing": len(pages)},
                 "confidence": "high", "nondeterministic": False},
                {"summary": "Give each page a title that names its own specific "
                            "subject rather than sharing one generic title.",
                 "how": ["Generate the title from the page's own data, such as the "
                         "product or article name, rather than a static template "
                         "value."],
                 "mechanism": "An identical title across distinct pages makes them "
                              "harder to tell apart in a list of results, weakening "
                              "rather than blocking their individual identification.",
                 "effort": "template-change", "owner": "engineering",
                 "verification": "Sample several of the listed pages and confirm each "
                                 "now has its own title."},
                severity_ceiling="low"))
    return findings


CHECKS = (
    check_csr_shell,
    check_partial_js_content,
    check_js_only_structured_data,
    check_facts_in_images,
    check_facts_in_documents_only,
    check_text_in_nontext_element,
    check_interstitial_in_raw,
    check_content_behind_interaction,
    check_h1,
    check_heading_jumps,
    check_main_landmark,
    check_boilerplate_ratio,
    check_thin_content,
    check_title,
)


def run(snapshot):
    ctx = Context(snapshot)
    if ctx.blackout:
        ctx.note("page content",
                 "every sampled URL was refused, so nothing about this site's "
                 "readability could be observed")
        return [], ctx.not_assessed
    if not ctx.headless_render:
        ctx.note("browser render comparison",
                 "no headless browser was available in this run, so the checks that "
                 "compare raw HTML against a rendered DOM either used the collector's "
                 "static structural signals at reduced confidence, or could not run at "
                 "all")

    findings = []
    for check in CHECKS:
        findings.extend(check(ctx))
    findings.sort(key=lambda f: (f["check_id"], (f["affected_urls"] or [""])[0]))
    return findings, ctx.not_assessed


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Detect render and readability failures from a site snapshot.",
        epilog="Example: check_render.py --snapshot snapshot.json --out findings.json")
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
