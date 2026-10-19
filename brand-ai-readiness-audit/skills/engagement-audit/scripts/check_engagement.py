#!/usr/bin/env python3
"""Detect whether a visitor who has found useful content can understand and follow a
next useful on-site action or content pathway.

Funnel stage: post-discovery engagement (site-internal). Pure snapshot consumer: this
script makes no network requests of any kind, no code path in it could, does not crawl,
does not launch a browser, does not call any external API or analytics platform, and
requires no credentials. The site-snapshot-collector remains the only network-touching
component in this marketplace, without exception.

Scope note, stated here because it is a significant, deliberate departure from an
earlier planning draft: this detector does NOT implement the "arriving visitor mid
journey" model (landing-integrity redirects, modal interruption, forced gates, fragment
preservation, first-paint weight, mobile viewport) that an earlier SKILL.md draft
described. That territory either duplicates an existing detector outright
(deep-link-to-home redirects are `crawl-access-audit`'s `ACC.DEEPLINK_TO_HOME_REDIRECT`;
heading anchors are `answer-retrievability-audit`'s `ANS.NO_HEADING_ANCHORS`; missing alt
on informational images is `render-readability-audit`'s `RND.FACTS_IN_IMAGES`, each
already the designated authoritative owner per merge_findings.DUPLICATE_OWNERSHIP) or
falls outside what this milestone's own scope defines as engagement. This detector's
actual, current scope -- observable on-site action and continuation pathways -- is
defined in references/checks.md.

Design rules, enforced here and not merely documented:

  * **No evidence, no finding.** Every finding names the exact link evidence (URLs,
    anchor text, in-content vs chrome) it was derived from.
  * **Never claim behavioural measurement.** No click-through rate, conversion rate,
    bounce rate, time on page, or any other metric this snapshot cannot observe.
    Findings are worded as structural observations ("no observable action pathway"),
    never as predictions about what a visitor will do.
  * **Page-type aware, always.** A legal page being a dead end is not a defect. A
    contact page needs no further action link. High-value content types are treated
    differently from utility and administrative types throughout.
  * **Sample-scoped language.** "Orphan-like within the sampled graph" is not "globally
    orphaned"; a depth observation is relative to this site's own sampled clusters, not
    a universal threshold.
"""
import argparse
import json
import os
import re
import sys
from urllib.parse import urlsplit

DETECTOR = "engagement-audit"

THRESHOLDS = {
    "min_cluster_for_template": 3,
    # Types where an ongoing continuation pathway is expected regardless of business
    # model or sector -- deliberately not "service", which this snapshot's page-type
    # classifier has no way to distinguish from "about" or "product" (see
    # checks.md's documented limitation).
    "high_value_types": frozenset({"product", "article", "docs"}),
    # The one type where "expects a purchase or inquiry action" is inferable without
    # assuming a specific business model.
    "action_expected_types": frozenset({"product"}),
    # A category or listing page legitimately aggregates related content of the same
    # type -- "browse the full range" from a product page is exactly the kind of
    # related-content pathway this check looks for, not a utility destination. An
    # earlier version excluded it, which meant linking to the most natural next step
    # from a product page (its own category listing) still counted as a failure.
    "related_content_destination_types": frozenset({"product", "article", "docs",
                                                     "category"}),
    "min_pages_for_orphan_check": 6,
    "min_clusters_for_depth_comparison": 3,
    # A cluster's depth must exceed the site's own median by at least this many
    # levels, on a high-value type, before being called "unusually deep" -- relative
    # to this site's own sampled structure, never an absolute threshold.
    "depth_excess_levels": 2,
}

UTILITY_TYPES = {"utility"}
CONFIDENT = {"high", "medium"}
# Types where "no action pathway" or "no continuation" is expected and correct, not a
# defect: an endpoint page, an administrative page, or a page whose whole purpose is
# to be the destination rather than a waypoint.
ENDPOINT_TYPES = frozenset({"contact", "legal", "faq", "utility", "homepage"})

# A conservative, generic action-surface lexicon. Presence alone never proves a link
# is commercially meaningful; it is combined with structural evidence (an actual href,
# in-content or navigation placement) throughout. Documented as English-lexical in
# checks.md -- no structural alternative exists for recognising action intent in link
# text.
_ACTION_PHRASES = (
    "contact", "request a quote", "get a quote", "get started", "buy", "shop",
    "book", "schedule", "demo", "download", "subscribe", "apply", "enquire",
    "inquire", "request", "add to cart", "order", "purchase", "sign up",
    "view pricing", "get in touch", "talk to", "speak to", "call us",
)
_GENERIC_ANCHOR_TEXT = frozenset({
    "click here", "here", "read more", "learn more", "more", "more info",
    "find out more", "see more", "details", "link",
})


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


# ------------------------------------------------------------------------------- helpers

def norm_ws(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def norm_url(url):
    """Scheme/host/path/query normalised for same-page and cross-page comparison,
    ignoring a bare trailing slash and a fragment, since a fragment difference does
    not change which page is the destination."""
    try:
        parts = urlsplit(url or "")
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path.rstrip("/") or "/"
    return "%s%s?%s" % (host, path, parts.query) if parts.query else "%s%s" % (host, path)


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


def in_content_internal_links(page):
    return [l for l in (page.get("links_internal") or []) if l.get("in_content")]


def has_action_phrase(text):
    lowered = (text or "").casefold()
    return any(phrase in lowered for phrase in _ACTION_PHRASES)


def is_generic_anchor(text):
    return norm_ws(text).casefold() in _GENERIC_ANCHOR_TEXT


def content_type_destination(url_norm, url_index):
    """The page_type of the sampled page this URL resolves to, or None if the URL
    does not resolve to a page in this sample, or the destination's own
    classification is not confident enough to assert what type it is.

    A destination classified at low confidence (which can happen when a page's own
    signals are reduced -- non-English content, or structured data that migrated to
    a format the classifier weighs less heavily) is treated as unresolved, not as
    confirmed evidence the destination is unrelated. Confidently asserting "this
    link is not to related content" from a classification the collector itself is
    not confident in would blame the source page for a classification gap on the
    destination page.
    """
    page = url_index.get(url_norm)
    if not page:
        return None
    if page.get("page_type_confidence") not in CONFIDENT:
        return None
    return page.get("page_type")


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
        self.fetched = [p for p in self.pages if p.get("fetch_ok")]
        self.blackout = bool(self.pages) and not self.fetched
        self.content = [p for p in self.fetched if is_confident_content(p)]
        self.url_index = {}
        for p in self.fetched:
            key = norm_url(p.get("url"))
            if key:
                self.url_index[key] = p
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


# ============================================================ ENG.DEAD_END_HIGH_VALUE

def check_dead_end_high_value(ctx):
    findings = []
    candidates = [p for p in ctx.content
                 if p.get("page_type") in THRESHOLDS["high_value_types"]]
    hits = [p for p in candidates if not in_content_internal_links(p)]

    if not hits:
        return findings
    reach = reach_for(hits, candidates, ctx.clusters)
    findings.append(finding(
        "ENG.DEAD_END_HIGH_VALUE_PAGE",
        "High-value pages expose no in-content next step",
        "weakens", reach, "measured", "engagement",
        "%d of %d sampled %s pages carry zero in-content internal links -- no "
        "editorial link anywhere in the page's own content offers a next step. "
        "Navigation and footer links are not counted, since they are the same on "
        "every page and do not represent a next step this specific page's content "
        "leads to. Examples: %s."
        % (len(hits), len(candidates),
           "/".join(sorted({p["page_type"] for p in candidates})),
           ", ".join(p["url"] for p in hits[:3])),
        [p["url"] for p in hits],
        {"method": "count of internal links flagged in_content (as opposed to "
                   "navigation or footer chrome) on pages of a type where an "
                   "ongoing pathway is expected regardless of sector",
         "observed": {"pages": [{"url": p["url"], "page_type": p.get("page_type"),
                                 "in_content_internal_links": 0}
                                for p in hits[:10]]},
         "expected": "at least one in-content internal link offering a next step",
         "sample": {"checked": len(candidates), "failing": len(hits)},
         "confidence": "high", "nondeterministic": False},
        {"summary": "Add at least one in-content link from each of these pages to a "
                    "genuinely related next step -- a related product, the next "
                    "article in a series, or the relevant contact or inquiry path.",
         "how": ["Identify what a reader who finished this page would plausibly "
                 "want next.",
                 "Add that as a real editorial link inside the page's own content, "
                 "with descriptive anchor text naming the destination, not only in "
                 "the site-wide navigation."],
         "mechanism": "A page with no in-content link anywhere is an observable "
                      "dead end: a reader who finishes it has no next step offered "
                      "by the content itself, only whatever the same navigation "
                      "menu offers on every other page too.",
         "effort": "content", "owner": "content",
         "verification": "Re-check the page and confirm at least one in-content "
                         "internal link is present."}))
    return findings


# ==================================================== ENG.NO_RELATED_CONTENT_PATHWAY

def check_no_related_content_pathway(ctx):
    """Distinct from DEAD_END: the page has SOME in-content links, but none of them
    lead to another sampled page of a content-bearing type -- the links exist but do
    not constitute a related-content pathway (they go to utility destinations: cart,
    search, login, a generic category index)."""
    findings = []
    candidates = [p for p in ctx.content
                 if p.get("page_type") in THRESHOLDS["high_value_types"]]
    hits = []
    for page in candidates:
        links = in_content_internal_links(page)
        if not links:
            continue  # DEAD_END_HIGH_VALUE_PAGE's territory, not this one
        destinations = {norm_url(l.get("url")) for l in links}
        destination_types = {content_type_destination(d, ctx.url_index)
                             for d in destinations if d}
        resolved_types = {t for t in destination_types if t is not None}
        if not resolved_types:
            continue  # no confidently-classified destination; insufficient evidence
        related = resolved_types & THRESHOLDS["related_content_destination_types"]
        if not related:
            hits.append(page)

    if not hits:
        return findings
    reach = reach_for(hits, candidates, ctx.clusters)
    example = hits[0]
    example_links = in_content_internal_links(example)
    findings.append(finding(
        "ENG.NO_RELATED_CONTENT_PATHWAY",
        "In-content links exist but none lead to related content",
        "weakens", reach, "measured", "engagement",
        "%d pages carry in-content internal links, but none of them lead to another "
        "sampled page of a content-bearing or listing type (%s) -- every in-content "
        "link on these pages points elsewhere (search, contact, or another utility "
        "page). Example: %s links to %s."
        % (len(hits), "/".join(sorted(THRESHOLDS["related_content_destination_types"])),
           example["url"], ", ".join(l.get("url", "") for l in example_links[:2])),
        [p["url"] for p in hits],
        {"method": "destination page_type of every in-content internal link on the "
                   "page, cross-referenced against the sampled pages those URLs "
                   "resolve to",
         "observed": {"pages": [{"url": p["url"],
                                 "in_content_destinations":
                                     [l.get("url") for l in
                                      in_content_internal_links(p)][:5]}
                                for p in hits[:8]]},
         "expected": "at least one in-content link to another content-bearing or "
                     "listing page (a related product, article, documentation, or "
                     "category page)",
         "sample": {"checked": len(candidates), "failing": len(hits)},
         "confidence": "medium", "nondeterministic": False,
         "note": "a destination outside this sample cannot be classified and is not "
                 "counted against the page; this only flags links that resolve to a "
                 "sampled utility-type destination"},
        {"summary": "Add at least one in-content link from each of these pages to "
                    "another genuinely related content page.",
         "how": ["Identify the most relevant related product, article or "
                 "documentation page.",
                 "Add it as an in-content link with descriptive anchor text."],
         "mechanism": "Links to a cart, search or category index keep a visitor "
                      "moving through the site's structure, but do not offer the "
                      "kind of topical continuation that keeps someone engaged with "
                      "the specific subject this page covers.",
         "effort": "content", "owner": "content",
         "verification": "Re-check the page and confirm at least one in-content "
                         "link now leads to a related content page."}))
    return findings


# ======================================================== ENG.WEAK_ACTION_PATHWAY

def check_weak_action_pathway(ctx):
    findings = []
    candidates = [p for p in ctx.content
                 if p.get("page_type") in THRESHOLDS["action_expected_types"]]
    hits = []
    for page in candidates:
        all_links = ((page.get("links_internal") or [])
                    + (page.get("links_external") or []))
        if not any(has_action_phrase(l.get("text")) for l in all_links):
            hits.append(page)

    if not hits:
        return findings
    reach = reach_for(hits, candidates, ctx.clusters)
    findings.append(finding(
        "ENG.WEAK_ACTION_PATHWAY",
        "Product pages expose no observable action pathway",
        "weakens", reach, "measured", "engagement",
        "%d of %d sampled product pages have no link, anywhere on the page (in "
        "content or navigation), whose text matches a purchase, contact or inquiry "
        "phrase. Examples: %s."
        % (len(hits), len(candidates), ", ".join(p["url"] for p in hits[:3])),
        [p["url"] for p in hits],
        {"method": "anchor text of every internal and external link on the page, "
                   "checked against a conservative purchase/contact/inquiry phrase "
                   "list",
         "observed": {"pages_without_action_link": [p["url"] for p in hits[:10]]},
         "expected": "at least one link whose text signals a purchase, contact or "
                     "inquiry action, reachable from the page (navigation counts, "
                     "since a consistent site-wide action path is still a real, "
                     "observable path)",
         "sample": {"checked": len(candidates), "failing": len(hits)},
         "confidence": "medium", "nondeterministic": False,
         "note": "this is a conservative, English-lexical phrase list; it cannot "
                 "detect an action surface expressed only as an icon, an image, or "
                 "text this list does not cover"},
        {"summary": "Add an observable link to the appropriate next action for this "
                    "product -- a purchase link, a contact form, or an inquiry path "
                    "-- reachable from the page.",
         "how": ["Identify what action this product page should lead to.",
                 "Add a link with clear, action-oriented text (\"Buy now\", "
                 "\"Request a quote\", \"Contact sales\") either in the page's own "
                 "content or in consistent site navigation."],
         "mechanism": "A product page with no observable way to act on it, "
                      "anywhere on the page, gives a visitor who is ready to act no "
                      "next step to take.",
         "effort": "template-change", "owner": "engineering",
         "verification": "Re-check the page and confirm an action-oriented link is "
                         "present and reachable."}))
    return findings


# ===================================================== ENG.EXCESSIVE_PATHWAY_DEPTH

def check_excessive_pathway_depth(ctx):
    findings = []
    dated_clusters = [c for c in ctx.clusters
                      if c.get("page_type") in THRESHOLDS["high_value_types"]
                      and isinstance(c.get("depth"), int)]
    all_depths = [c["depth"] for c in ctx.clusters if isinstance(c.get("depth"), int)]
    if len(all_depths) < THRESHOLDS["min_clusters_for_depth_comparison"]:
        return findings
    sorted_depths = sorted(all_depths)
    median_depth = sorted_depths[len(sorted_depths) // 2]

    hits = [c for c in dated_clusters
           if c["depth"] - median_depth >= THRESHOLDS["depth_excess_levels"]]
    if not hits:
        return findings

    example = hits[0]
    sample_urls = (example.get("sampled") or [])[:3]
    findings.append(finding(
        "ENG.EXCESSIVE_PATHWAY_DEPTH",
        "A high-value template sits unusually deep in the sampled site structure",
        "weakens", "template", "inferred", "engagement",
        "The %s template cluster sits at depth %d, %d levels deeper than this "
        "site's own median sampled depth (%d). Example URLs: %s."
        % (example.get("page_type"), example["depth"],
           example["depth"] - median_depth, median_depth,
           ", ".join(sample_urls)),
        sample_urls,
        {"method": "cluster depth (from the collector's own discovery graph) "
                   "compared against the median depth across all sampled clusters "
                   "on this site",
         "observed": {"cluster_depth": example["depth"],
                     "site_median_depth": median_depth,
                     "page_type": example.get("page_type")},
         "expected": "high-value content within a comparable depth to the rest of "
                     "the site's own sampled structure",
         "sample": {"checked": len(all_depths), "failing": len(hits)},
         "confidence": "medium", "nondeterministic": False,
         "note": "relative to this site's own sampled structure only, not a "
                 "universal depth threshold, and not a claim about the site's full, "
                 "unsampled structure"},
        {"summary": "Bring this content closer to the site's main navigation "
                    "structure, for example by linking to it from a category or "
                    "hub page nearer the top of the site.",
         "how": ["Identify a higher-level page this content should be linked from.",
                 "Add a direct in-content or navigational link from that page."],
         "mechanism": "Content reachable only through many intermediate pages is "
                      "harder for both a visitor and an automated crawler to reach "
                      "in a small number of steps, relative to the rest of this "
                      "site's own structure.",
         "effort": "template-change", "owner": "engineering",
         "verification": "Re-check the site's discovery structure and confirm this "
                         "content is reachable in fewer steps."}))
    return findings


# ======================================================== ENG.ORPHAN_LIKE_SAMPLED_PAGE

def check_orphan_like_sampled_page(ctx):
    findings = []
    if len(ctx.content) < THRESHOLDS["min_pages_for_orphan_check"]:
        ctx.note("orphan-like page detection",
                 "too few sampled pages for an absence of inbound sampled links to "
                 "be meaningful evidence")
        return findings

    inbound = set()
    for page in ctx.fetched:
        for link in (page.get("links_internal") or []):
            key = norm_url(link.get("url"))
            if key and key != norm_url(page.get("url")):
                inbound.add(key)

    hits = []
    for page in ctx.content:
        # Endpoint types (legal, contact, faq) and administrative pages are commonly
        # and legitimately kept out of primary navigation flow -- a terms page
        # reachable only via the footer or the sitemap, not the main nav, is normal,
        # not an engagement-pathway problem. An earlier version excluded only
        # homepage and utility types, which flagged exactly this normal pattern.
        if page.get("page_type") in ENDPOINT_TYPES:
            continue
        if norm_url(page.get("url")) not in inbound:
            hits.append(page)

    if not hits:
        return findings
    reach = reach_for(hits, ctx.content, ctx.clusters)
    findings.append(finding(
        "ENG.ORPHAN_LIKE_SAMPLED_PAGE",
        "Sampled pages have no inbound link from any other sampled page",
        "weakens", reach, "measured", "engagement",
        "%d sampled pages are not linked to by any other page in this sample -- "
        "orphan-like within the sampled graph. This does not establish that the "
        "page is globally unreachable, only that no other page this audit observed "
        "points to it. Examples: %s."
        % (len(hits), ", ".join(p["url"] for p in hits[:3])),
        [p["url"] for p in hits],
        {"method": "every internal link URL across every sampled page, normalised "
                   "and compared against each sampled page's own URL",
         "observed": {"orphan_like_pages": [p["url"] for p in hits[:10]]},
         "expected": "at least one other sampled page links to this page",
         "sample": {"checked": len(ctx.content), "failing": len(hits)},
         "confidence": "medium", "nondeterministic": False,
         "note": "scoped explicitly to the sampled graph; a page reached only "
                 "through pages outside the sample, or through a sitemap alone, "
                 "would appear orphan-like here without genuinely being orphaned"},
        {"summary": "Link to these pages from at least one other relevant page in "
                    "the site's own content or navigation.",
         "how": ["Identify a relevant category, hub or related-content page for "
                 "each listed URL.",
                 "Add a direct link to it from there."],
         "mechanism": "A page with no inbound link from anything else this audit "
                      "sampled is reachable only through a sitemap or direct URL "
                      "knowledge, which is a weaker discovery and continuation path "
                      "than an in-content link from a related page.",
         "effort": "content", "owner": "content",
         "verification": "Re-check the site's sampled link graph and confirm at "
                         "least one other page now links to this URL."}))
    return findings


# ======================================================== ENG.AMBIGUOUS_ACTION_SURFACE

def check_ambiguous_action_surface(ctx):
    findings = []
    hits = []
    for page in ctx.content:
        links = in_content_internal_links(page)
        by_text = {}
        for link in links:
            if is_generic_anchor(link.get("text")):
                key = norm_ws(link.get("text")).casefold()
                by_text.setdefault(key, set()).add(norm_url(link.get("url")))
        ambiguous = {text: dests for text, dests in by_text.items() if len(dests) > 1}
        if ambiguous:
            hits.append((page, ambiguous))

    if not hits:
        return findings
    reach = reach_for([p for p, _ in hits], ctx.content, ctx.clusters)
    example = hits[0]
    example_text = sorted(example[1])[0]
    findings.append(finding(
        "ENG.AMBIGUOUS_ACTION_SURFACE",
        "The same generic link text points to different destinations on one page",
        "weakens", reach, "measured", "engagement",
        "%d pages reuse the same generic anchor text for links to different "
        "destinations, so which destination a given instance leads to cannot be "
        "told from the link text alone. Example: %s uses %r for %d different "
        "destinations."
        % (len(hits), example[0]["url"], example_text, len(example[1][example_text])),
        [p["url"] for p, _ in hits],
        {"method": "in-content links grouped by normalised anchor text, restricted "
                   "to a conservative list of generic phrases (\"click here\", "
                   "\"read more\", \"learn more\", and similar), checked for more "
                   "than one distinct destination sharing the same text on one page",
         "observed": {"pages": [{"url": p["url"],
                                 "ambiguous_text": {t: sorted(d) for t, d in a.items()}}
                                for p, a in hits[:8]]},
         "expected": "distinct links carry distinct, descriptive text, or generic "
                     "text is reused only for links to the same destination",
         "sample": {"checked": len(ctx.content), "failing": len(hits)},
         "confidence": "high", "nondeterministic": False},
        {"summary": "Replace the reused generic link text with descriptive text "
                    "naming each specific destination.",
         "how": ["For each generic-text link named in the evidence, replace it "
                 "with text describing where it actually goes (e.g. \"Read more "
                 "about pricing\" instead of \"Read more\")."],
         "mechanism": "Identical link text pointing to different places on the "
                      "same page cannot be told apart by anyone, human or "
                      "automated, reading only the link text, which is the "
                      "information most systems and most skimming readers rely on.",
         "effort": "content", "owner": "content",
         "verification": "Re-check the page and confirm each link's text uniquely "
                         "identifies its destination."}))
    return findings


CHECKS = (
    check_dead_end_high_value,
    check_no_related_content_pathway,
    check_weak_action_pathway,
    check_excessive_pathway_depth,
    check_orphan_like_sampled_page,
    check_ambiguous_action_surface,
)


def run(snapshot):
    ctx = Context(snapshot)
    if ctx.blackout:
        ctx.note("page content",
                 "every sampled URL was refused, so engagement pathways could not "
                 "be assessed")
        return [], ctx.not_assessed

    findings = []
    for check in CHECKS:
        findings.extend(check(ctx))
    findings.sort(key=lambda f: (f["check_id"], (f["affected_urls"] or [""])[0]))
    return findings, ctx.not_assessed


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Detect on-site engagement pathway failures from a site "
                    "snapshot.",
        epilog="Example: check_engagement.py --snapshot snapshot.json "
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
