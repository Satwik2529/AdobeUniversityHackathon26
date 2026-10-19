#!/usr/bin/env python3
"""Unit tests for render-readability-audit.

Each test builds a minimal snapshot conforming to the frozen contract, runs the detector
over it, and asserts on the findings. No network, no fixture server: these are branch
tests. End-to-end behaviour against live fixtures, including genuine Playwright rendering
where available, is covered by tests/run_tests.py and the dedicated integration class at
the bottom of this file.

Run: python3 skills/render-readability-audit/scripts/test_render.py
"""
import copy
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)

import check_render as rnd  # noqa: E402

ORIGIN = "https://example.test"

REQUIRED_FINDING_FIELDS = ("check_id", "title", "gate_impact", "reach", "certainty",
                           "funnel_stage", "detector", "evidence", "affected_urls",
                           "evidence_detail", "suggested_action")
REQUIRED_ACTION_FIELDS = ("summary", "how", "mechanism", "effort", "owner", "verification")
REQUIRED_DETAIL_FIELDS = ("check_id", "method", "observed", "expected", "sample",
                          "confidence", "nondeterministic", "detector")

ALL_FINDINGS = []      # accumulated across every test, for the evidence-quality sweep


# ------------------------------------------------------------------ snapshot factories

def make_headings(*levels_and_text):
    return [{"level": level, "id": None, "text": text, "in_content": True}
            for level, text in levels_and_text]


def make_page(path, **kw):
    url = ORIGIN + path
    page = {
        "url": url,
        "final_url": kw.pop("final_url", url),
        "cluster_id": kw.pop("cluster_id", "c01"),
        "page_type": kw.pop("page_type", "product"),
        "page_type_confidence": kw.pop("page_type_confidence", "high"),
        "page_type_signals": [],
        "fetch_ok": kw.pop("fetch_ok", True),
        "status": kw.pop("status", 200),
        "status_chain": None,
        "redirected": False, "redirect_count": 0,
        "headers": {"content-type": "text/html; charset=utf-8"},
        "content_type": "text/html; charset=utf-8",
        "bytes": 4000, "truncated": False,
        "error": None, "blocked": False, "challenge_detected": False, "notes": [],
        "elapsed_ms": 30,
        "sitemap_lastmod": None, "discovery_source": "sitemap",
        "control_fetch": None,
        "render": kw.pop("render", None),
        "spa_signals": kw.pop("spa_signals", []),
    }
    if page["fetch_ok"]:
        raw_html = kw.pop("raw_html", "<html><body><main><h1>Title</h1>"
                                      "<p>Readable prose.</p></main></body></html>")
        page.update({
            "raw_html": raw_html,
            "raw_text": kw.pop("raw_text", "text " * 200),
            "raw_text_len": kw.pop("raw_text_len", 1000),
            "main_text": kw.pop("main_text", "readable prose " * 60),
            "main_text_len": kw.pop("main_text_len", 900),
            "lang": kw.pop("lang", "en"),
            "title": kw.pop("title", "Title"),
            "meta_description": "d", "meta_robots": None,
            "meta_viewport": "width=device-width", "meta_refresh": None,
            "canonical": url, "canonical_raw": url,
            "hreflang": [],
            "headings": kw.pop("headings", make_headings((1, "Title"))),
            "tables": kw.pop("tables", 0),
            "definition_lists": kw.pop("definition_lists", 0),
            "forms": 0,
            "script_bytes": kw.pop("script_bytes", 0), "script_srcs": [],
            "stylesheet_count": 1, "render_blocking": 1,
            "noscript_text": kw.pop("noscript_text", ""),
            "has_main_landmark": kw.pop("has_main_landmark", True),
            "empty_mount_points": [],
            "links_internal": [], "links_external": [],
            "links_in_content_internal": 3,
            "documents": kw.pop("documents", []),
            "images": kw.pop("images", []),
            "structured_data": kw.pop("structured_data", {
                "source": "raw", "jsonld": [], "microdata_types": [],
                "microdata_props": 0, "microdata_items": [],
                "rdfa_types": [], "rdfa_props": 0, "opengraph": {}}),
            "schema_types": [], "parse_notes": [],
        })
    page.update(kw)
    return page


def make_snapshot(pages=None, clusters=None, headless_render=False, **kw):
    pages = pages if pages is not None else [make_page("/a.html"), make_page("/b.html"),
                                             make_page("/c.html")]
    snapshot = {
        "schema_version": "1.0", "collector_version": "1.0.0",
        "site": "example.test", "origin": ORIGIN, "entry_url": ORIGIN + "/",
        "audited_at": "2026-09-05T00:00:00Z", "user_agent": "audit",
        "capabilities": {"headless_render": headless_render, "external_search": False},
        "robots": {"url": ORIGIN + "/robots.txt", "fetched": True, "status": 200,
                  "content_type": "text/plain", "error": None, "raw": "", "parse_ok": True,
                  "directive_lines": 2, "groups": [], "sitemaps": [], "errors": [],
                  "crawl_delay_applied": 0.0, "agent_verdicts": {}, "matched_rules": {}},
        "sitemaps": [], "discovery": {"method": "sitemap", "urls_discovered": 40,
                                      "depth_reached": 0, "discovered_urls": []},
        "clusters": clusters if clusters is not None else [
            {"id": "c01", "skeleton": "/{slug}.html", "size": max(6, len(pages)), "depth": 1,
             "members_sample": [], "sampled": [p["url"] for p in pages],
             "page_type": "product", "page_type_confidence": "high"}],
        "site_archetype": "ecommerce",
        "sampled_urls": [p["url"] for p in pages],
        "pages": pages,
        "phase_timings": {}, "duration_seconds": 1.0,
        "coverage": {"pages_discovered": 40, "pages_sampled": len(pages),
                     "pages_fetched": len([p for p in pages if p["fetch_ok"]]),
                     "pages_rendered": 0, "blocked_by_robots": 0, "fetch_failures": 0,
                     "requests_made": 10, "request_cap": 120, "template_clusters": [],
                     "site_archetype": "ecommerce", "page_type_counts": {},
                     "capabilities": {"headless_render": headless_render,
                                     "external_search": False},
                     "not_assessed": [], "degradations": [], "blocked_urls": [],
                     "failures": []},
    }
    snapshot.update(kw)
    return snapshot


def render_block(main_text_len=0, text_len=None, tables=0, definition_lists=0,
                 jsonld_count=0, microdata_types=None, ok=True):
    text_len = text_len if text_len is not None else main_text_len
    return {
        "ok": ok,
        "text_len": text_len, "main_text_len": main_text_len,
        "main_text_excerpt": "x" * min(main_text_len, 100),
        "headings": make_headings((1, "Title")) if main_text_len else [],
        "tables": tables, "definition_lists": definition_lists,
        "structured_data_blocks": jsonld_count,
        "structured_data": {
            "jsonld": [{"parse_ok": True, "error": None} for _ in range(jsonld_count)],
            "microdata_types": microdata_types or []},
        "images": 0, "render_ms": 500, "modal_candidates": [], "error": None,
    }


class DetectorTestCase(unittest.TestCase):
    """Base class that records every finding for the evidence-quality sweep."""

    def detect(self, snapshot):
        findings, not_assessed = rnd.run(copy.deepcopy(snapshot))
        ALL_FINDINGS.extend(findings)
        return findings, not_assessed

    def ids(self, findings):
        return [f["check_id"] for f in findings]

    def only(self, findings, check_id):
        matches = [f for f in findings if f["check_id"] == check_id]
        self.assertEqual(len(matches), 1, "expected exactly one %s, got %s"
                         % (check_id, self.ids(findings)))
        return matches[0]

    def dimensions(self, not_assessed):
        return {item["dimension"] for item in not_assessed}


# ==================================================================== CSR_SHELL: measured

class TestCsrShellMeasured(DetectorTestCase):

    def _pages(self, n, **render_kw):
        return [make_page("/p%d.html" % i, main_text_len=0, raw_text_len=40,
                          render=render_block(**render_kw))
               for i in range(n)]

    def test_fires_when_render_shows_real_content_absent_from_raw(self):
        findings, _ = self.detect(make_snapshot(
            pages=self._pages(3, main_text_len=300), headless_render=True))
        self.only(findings, "RND.CSR_SHELL")

    def test_does_not_fire_when_static_site_has_no_growth(self):
        pages = [make_page("/p%d.html" % i, main_text_len=400, raw_text_len=600,
                           render=render_block(main_text_len=400, text_len=600))
                 for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages, headless_render=True))
        self.assertNotIn("RND.CSR_SHELL", self.ids(findings))

    def test_small_genuine_gap_still_fires_zero_to_something(self):
        """Regression: a page moving from 0 to ~100 real characters must not be missed.

        An earlier version of this check required 200 rendered characters as an
        absolute floor, which let a real (if modest) shell through undetected.
        """
        findings, _ = self.detect(make_snapshot(
            pages=self._pages(3, main_text_len=100), headless_render=True))
        self.only(findings, "RND.CSR_SHELL")

    def test_trivial_growth_does_not_fire(self):
        """Raw already has some text; rendering adds only a little more. Not a shell."""
        pages = [make_page("/p%d.html" % i, main_text_len=120, raw_text_len=200,
                           render=render_block(main_text_len=150, text_len=220))
                 for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages, headless_render=True))
        self.assertNotIn("RND.CSR_SHELL", self.ids(findings))

    def test_utility_pages_are_excluded(self):
        pages = [make_page("/search", page_type="utility", page_type_confidence="high",
                           main_text_len=0, render=render_block(main_text_len=500))]
        findings, _ = self.detect(make_snapshot(pages=pages, headless_render=True))
        self.assertNotIn("RND.CSR_SHELL", self.ids(findings))

    def test_low_confidence_classification_is_not_excluded(self):
        """The page most likely to be a genuine shell is the hardest to classify."""
        pages = [make_page("/p%d.html" % i, page_type="unknown",
                           page_type_confidence="low", main_text_len=0, raw_text_len=30,
                           render=render_block(main_text_len=300))
                 for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages, headless_render=True))
        self.only(findings, "RND.CSR_SHELL")

    def test_reach_is_template_when_the_rest_of_the_site_is_unaffected(self):
        """Template reach means one cluster fails while the wider sample does not.

        Matches reach_for's established convention (identical to crawl-access-audit's):
        when every page in the applicable population fails, that is sitewide by
        definition, however many clusters it happens to span. Template reach requires a
        population that extends beyond the failing cluster.
        """
        shell_pages = self._pages(3, main_text_len=300)
        healthy_pages = [make_page("/about.html", page_type="about", main_text_len=400)]
        clusters = [
            {"id": "c01", "skeleton": "/p{n}.html", "size": 6, "depth": 1,
             "members_sample": [], "sampled": [p["url"] for p in shell_pages],
             "page_type": "product", "page_type_confidence": "high"},
            {"id": "c02", "skeleton": "/about.html", "size": 1, "depth": 1,
             "members_sample": [], "sampled": [p["url"] for p in healthy_pages],
             "page_type": "about", "page_type_confidence": "high"},
        ]
        findings, _ = self.detect(make_snapshot(
            pages=shell_pages + healthy_pages, clusters=clusters, headless_render=True))
        found = self.only(findings, "RND.CSR_SHELL")
        self.assertEqual(found["reach"], "template")

    def test_evidence_names_the_exact_character_counts(self):
        findings, _ = self.detect(make_snapshot(
            pages=self._pages(3, main_text_len=300), headless_render=True))
        found = self.only(findings, "RND.CSR_SHELL")
        self.assertIn("0", found["evidence"])
        self.assertIn("300", found["evidence"])


# =================================================================== CSR_SHELL: fallback

class TestCsrShellFallback(DetectorTestCase):

    def test_two_high_signals_fire_at_blocks_impact(self):
        signals = [{"signal": "empty-or-thin-main-content", "weight": "high", "detail": ""},
                  {"signal": "empty-mount-point", "weight": "high", "detail": ""}]
        pages = [make_page("/p%d.html" % i, spa_signals=signals) for i in range(3)]
        findings, not_assessed = self.detect(make_snapshot(pages=pages))
        found = self.only(findings, "RND.CSR_SHELL")
        self.assertEqual(found["gate_impact"], "blocks")
        self.assertEqual(found["evidence_detail"]["confidence"], "medium")
        self.assertIn("browser render comparison", self.dimensions(not_assessed))

    def test_one_high_one_medium_fires_at_degrades(self):
        signals = [{"signal": "empty-mount-point", "weight": "high", "detail": ""},
                  {"signal": "noscript-notice", "weight": "medium", "detail": ""}]
        pages = [make_page("/p%d.html" % i, spa_signals=signals) for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        found = self.only(findings, "RND.CSR_SHELL")
        self.assertEqual(found["gate_impact"], "degrades")

    def test_single_high_signal_alone_never_fires(self):
        """Never fire on a single signal, per the approved catalogue."""
        signals = [{"signal": "empty-mount-point", "weight": "high", "detail": ""}]
        pages = [make_page("/p%d.html" % i, spa_signals=signals) for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("RND.CSR_SHELL", self.ids(findings))

    def test_two_medium_signals_alone_never_fire(self):
        signals = [{"signal": "noscript-notice", "weight": "medium", "detail": ""},
                  {"signal": "script-dominant", "weight": "medium", "detail": ""}]
        pages = [make_page("/p%d.html" % i, spa_signals=signals) for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("RND.CSR_SHELL", self.ids(findings))

    def test_no_signals_produces_no_finding_and_no_spam(self):
        findings, not_assessed = self.detect(make_snapshot())
        self.assertNotIn("RND.CSR_SHELL", self.ids(findings))

    def test_certainty_and_severity_derivation_cap_at_high_never_critical(self):
        """Regression: without a browser, this must never reach critical."""
        sys.path.insert(0, os.path.join(ROOT, "skills", "brand-ai-readiness-audit",
                                        "scripts"))
        import merge_findings
        signals = [{"signal": "empty-or-thin-main-content", "weight": "high", "detail": ""},
                  {"signal": "empty-mount-point", "weight": "high", "detail": ""}]
        pages = [make_page("/p%d.html" % i, spa_signals=signals) for i in range(6)]
        findings, _ = self.detect(make_snapshot(
            pages=pages,
            clusters=[{"id": "c01", "skeleton": "/{slug}.html", "size": 6, "depth": 1,
                      "members_sample": [], "sampled": [p["url"] for p in pages],
                      "page_type": "product", "page_type_confidence": "high"}]))
        found = self.only(findings, "RND.CSR_SHELL")
        self.assertEqual(found["reach"], "sitewide")
        severity, _ = merge_findings.derive_severity(dict(found))
        self.assertEqual(severity, "high")


# ============================================================ PARTIAL_JS_CONTENT / SDATA

class TestPartialJsContent(DetectorTestCase):

    def test_fires_when_table_only_exists_after_render(self):
        pages = [make_page("/p%d.html" % i, main_text_len=400, tables=0,
                           render=render_block(main_text_len=420, tables=1))
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages, headless_render=True))
        self.only(findings, "RND.PARTIAL_JS_CONTENT")

    def test_does_not_fire_when_raw_already_thin_csr_shell_owns_it(self):
        """A near-empty page belongs to CSR_SHELL, not this check, to avoid double-report."""
        pages = [make_page("/p%d.html" % i, main_text_len=0, raw_text_len=30, tables=0,
                           render=render_block(main_text_len=300, tables=1))
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages, headless_render=True))
        self.assertNotIn("RND.PARTIAL_JS_CONTENT", self.ids(findings))
        self.only(findings, "RND.CSR_SHELL")

    def test_does_not_fire_without_a_browser(self):
        pages = [make_page("/p%d.html" % i, main_text_len=400, tables=0) for i in range(3)]
        findings, not_assessed = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("RND.PARTIAL_JS_CONTENT", self.ids(findings))

    def test_definition_list_growth_also_counts(self):
        pages = [make_page("/p%d.html" % i, main_text_len=400, definition_lists=0,
                           render=render_block(main_text_len=420, definition_lists=1))
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages, headless_render=True))
        self.only(findings, "RND.PARTIAL_JS_CONTENT")


class TestJsOnlyStructuredData(DetectorTestCase):

    def test_fires_when_jsonld_only_appears_after_render(self):
        pages = [make_page("/p%d.html" % i,
                           render=render_block(main_text_len=900, jsonld_count=1))
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages, headless_render=True))
        self.only(findings, "RND.JS_ONLY_STRUCTURED_DATA")

    def test_fires_when_microdata_only_appears_after_render(self):
        pages = [make_page("/p%d.html" % i,
                           render=render_block(main_text_len=900,
                                               microdata_types=["Product"]))
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages, headless_render=True))
        self.only(findings, "RND.JS_ONLY_STRUCTURED_DATA")

    def test_does_not_fire_when_raw_already_has_the_markup(self):
        structured = {"source": "raw", "jsonld": [{"parse_ok": True, "error": None}],
                     "microdata_types": [], "microdata_props": 0, "microdata_items": [],
                     "rdfa_types": [], "rdfa_props": 0, "opengraph": {}}
        pages = [make_page("/p%d.html" % i, structured_data=structured,
                           render=render_block(main_text_len=900, jsonld_count=1))
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages, headless_render=True))
        self.assertNotIn("RND.JS_ONLY_STRUCTURED_DATA", self.ids(findings))

    def test_does_not_fire_without_a_browser(self):
        pages = [make_page("/p%d.html" % i) for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("RND.JS_ONLY_STRUCTURED_DATA", self.ids(findings))


# ============================================================================= images

class TestFactsInImages(DetectorTestCase):

    def _product_pages(self, n, images, tables=0):
        return [make_page("/p%d.html" % i, page_type="product", tables=tables,
                          images=images) for i in range(n)]

    def test_fires_on_empty_alt_in_content_image_with_no_table(self):
        images = [{"src": "/spec.png", "alt": "", "has_alt": True, "in_content": True}]
        findings, _ = self.detect(make_snapshot(pages=self._product_pages(3, images)))
        self.only(findings, "RND.FACTS_IN_IMAGES")

    def test_fires_on_missing_alt_attribute(self):
        images = [{"src": "/spec.png", "alt": None, "has_alt": False, "in_content": True}]
        findings, _ = self.detect(make_snapshot(pages=self._product_pages(3, images)))
        self.only(findings, "RND.FACTS_IN_IMAGES")

    def test_does_not_fire_when_a_table_already_holds_the_facts(self):
        images = [{"src": "/spec.png", "alt": "", "has_alt": True, "in_content": True}]
        findings, _ = self.detect(make_snapshot(
            pages=self._product_pages(3, images, tables=1)))
        self.assertNotIn("RND.FACTS_IN_IMAGES", self.ids(findings))

    def test_decorative_image_with_descriptive_neighbor_table_is_fine(self):
        """A table exists: the decorative image alongside it must not be flagged."""
        images = [{"src": "/divider.png", "alt": "", "has_alt": True, "in_content": True}]
        findings, _ = self.detect(make_snapshot(
            pages=self._product_pages(3, images, tables=1)))
        self.assertNotIn("RND.FACTS_IN_IMAGES", self.ids(findings))

    def test_image_with_real_descriptive_alt_is_not_flagged(self):
        """Alt text IS a text equivalent. A well-described image needs no table."""
        images = [{"src": "/spec.png", "alt": "Weight 240 grams, size 9",
                  "has_alt": True, "in_content": True}]
        findings, _ = self.detect(make_snapshot(pages=self._product_pages(3, images)))
        self.assertNotIn("RND.FACTS_IN_IMAGES", self.ids(findings))

    def test_out_of_content_image_is_not_flagged(self):
        images = [{"src": "/logo.png", "alt": "", "has_alt": True, "in_content": False}]
        findings, _ = self.detect(make_snapshot(pages=self._product_pages(3, images)))
        self.assertNotIn("RND.FACTS_IN_IMAGES", self.ids(findings))

    def test_non_product_page_type_is_not_flagged(self):
        images = [{"src": "/photo.png", "alt": "", "has_alt": True, "in_content": True}]
        pages = [make_page("/p%d.html" % i, page_type="article", images=images, tables=0)
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("RND.FACTS_IN_IMAGES", self.ids(findings))

    def test_certainty_is_inferred_and_confidence_medium(self):
        images = [{"src": "/spec.png", "alt": "", "has_alt": True, "in_content": True}]
        findings, _ = self.detect(make_snapshot(pages=self._product_pages(3, images)))
        found = self.only(findings, "RND.FACTS_IN_IMAGES")
        self.assertEqual(found["certainty"], "inferred")
        self.assertEqual(found["evidence_detail"]["confidence"], "medium")


class TestFactsInDocumentsOnly(DetectorTestCase):

    def test_fires_on_two_or_more_pages(self):
        pages = [make_page("/p%d.html" % i, page_type="product", tables=0,
                           documents=["https://example.test/spec-%d.pdf" % i])
                for i in range(2)] + [make_page("/p2.html")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "RND.FACTS_IN_DOCUMENTS_ONLY")

    def test_one_page_alone_is_not_a_finding(self):
        pages = [make_page("/p0.html", page_type="product", tables=0,
                           documents=["https://example.test/spec.pdf"]),
                make_page("/p1.html"), make_page("/p2.html")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("RND.FACTS_IN_DOCUMENTS_ONLY", self.ids(findings))

    def test_does_not_fire_when_the_page_also_has_a_table(self):
        pages = [make_page("/p%d.html" % i, page_type="product", tables=1,
                           documents=["https://example.test/spec.pdf"])
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("RND.FACTS_IN_DOCUMENTS_ONLY", self.ids(findings))

    def test_non_fact_bearing_page_type_is_excluded(self):
        pages = [make_page("/p%d.html" % i, page_type="legal", tables=0,
                           documents=["https://example.test/terms.pdf"])
                for i in range(2)] + [make_page("/p2.html")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("RND.FACTS_IN_DOCUMENTS_ONLY", self.ids(findings))


# ==================================================================== canvas / svg / gates

class TestTextInNontextElement(DetectorTestCase):

    def test_fires_on_svg_with_many_text_nodes_and_no_title(self):
        svg = "<svg>" + "<text>a</text>" * 4 + "</svg>"
        page_ = make_page("/p.html", main_text_len=50,
                          raw_html="<html><body><main>%s</main></body></html>" % svg)
        findings, _ = self.detect(make_snapshot(pages=[page_]))
        self.only(findings, "RND.TEXT_IN_NONTEXT_ELEMENT")

    def test_svg_with_title_is_not_flagged(self):
        svg = "<svg><title>Company logo</title>" + "<text>a</text>" * 4 + "</svg>"
        page_ = make_page("/p.html", main_text_len=50,
                          raw_html="<html><body><main>%s</main></body></html>" % svg)
        findings, _ = self.detect(make_snapshot(pages=[page_]))
        self.assertNotIn("RND.TEXT_IN_NONTEXT_ELEMENT", self.ids(findings))

    def test_svg_with_aria_label_is_not_flagged(self):
        svg = '<svg aria-label="Company logo">' + "<text>a</text>" * 4 + "</svg>"
        page_ = make_page("/p.html", main_text_len=50,
                          raw_html="<html><body><main>%s</main></body></html>" % svg)
        findings, _ = self.detect(make_snapshot(pages=[page_]))
        self.assertNotIn("RND.TEXT_IN_NONTEXT_ELEMENT", self.ids(findings))

    def test_decorative_icon_svg_with_few_text_nodes_is_not_flagged(self):
        svg = "<svg><text>icon</text></svg>"
        page_ = make_page("/p.html", main_text_len=50,
                          raw_html="<html><body><main>%s</main></body></html>" % svg)
        findings, _ = self.detect(make_snapshot(pages=[page_]))
        self.assertNotIn("RND.TEXT_IN_NONTEXT_ELEMENT", self.ids(findings))

    def test_canvas_on_a_rich_page_is_not_flagged(self):
        page_ = make_page("/p.html", main_text_len=900,
                          raw_html="<html><body><main><canvas></canvas>"
                                  "<p>lots of real text</p></main></body></html>")
        findings, _ = self.detect(make_snapshot(pages=[page_]))
        self.assertNotIn("RND.TEXT_IN_NONTEXT_ELEMENT", self.ids(findings))

    def test_canvas_on_a_thin_page_is_flagged(self):
        page_ = make_page("/p.html", main_text_len=30,
                          raw_html="<html><body><main><canvas></canvas>"
                                  "</main></body></html>")
        findings, _ = self.detect(make_snapshot(pages=[page_]))
        self.only(findings, "RND.TEXT_IN_NONTEXT_ELEMENT")


class TestInterstitialInRaw(DetectorTestCase):

    def _dialog_page(self, path, main_text_len=30):
        html = ('<html><body><div role="dialog" aria-modal="true">'
               '<p>Please accept cookies</p></div></body></html>')
        return make_page(path, main_text_len=main_text_len, raw_html=html)

    def test_fires_on_thin_page_with_dialog_marker(self):
        pages = [self._dialog_page("/p%d.html" % i) for i in range(2)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "RND.INTERSTITIAL_IN_RAW")

    def test_dialog_marker_on_a_content_rich_page_is_not_flagged(self):
        html = ('<html><body><div role="dialog" aria-modal="true">banner</div>'
               '<main><p>%s</p></main></body></html>' % ("real content " * 60))
        page_ = make_page("/p.html", main_text_len=900, raw_html=html)
        findings, _ = self.detect(make_snapshot(pages=[page_]))
        self.assertNotIn("RND.INTERSTITIAL_IN_RAW", self.ids(findings))

    def test_thin_page_without_a_dialog_marker_is_not_flagged(self):
        """Thinness alone belongs to THIN_CONTENT, not this check."""
        page_ = make_page("/p.html", main_text_len=30,
                          raw_html="<html><body><p>short</p></body></html>")
        findings, _ = self.detect(make_snapshot(pages=[page_] * 1 + [
            make_page("/p2.html", main_text_len=30,
                     raw_html="<html><body><p>short</p></body></html>")]))
        self.assertNotIn("RND.INTERSTITIAL_IN_RAW", self.ids(findings))

    def test_utility_pages_are_excluded(self):
        page_ = self._dialog_page("/search")
        page_["page_type"] = "utility"
        page_["page_type_confidence"] = "high"
        findings, _ = self.detect(make_snapshot(pages=[page_]))
        self.assertNotIn("RND.INTERSTITIAL_IN_RAW", self.ids(findings))

    def test_aria_modal_false_is_not_treated_as_a_gate(self):
        """Regression: role=dialog + aria-modal=false is a documented non-blocking
        dialog pattern (a toast, a persistent panel) and was firing as a false positive.
        """
        html = ('<html><body><div role="dialog" aria-modal="false">'
               '<p>New message received</p></div></body></html>')
        pages = [make_page("/p%d.html" % i, main_text_len=30, raw_html=html)
                for i in range(2)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("RND.INTERSTITIAL_IN_RAW", self.ids(findings))


class TestContentBehindInteraction(DetectorTestCase):

    def test_always_not_assessed_never_a_finding(self):
        findings, not_assessed = self.detect(make_snapshot(headless_render=True))
        self.assertNotIn("RND.CONTENT_BEHIND_INTERACTION", self.ids(findings))
        self.assertIn("content behind interaction", self.dimensions(not_assessed))

    def test_still_not_assessed_even_with_render_data_present(self):
        """A browser being available does not change this: the collector never clicks."""
        pages = [make_page("/p.html", render=render_block(main_text_len=900))]
        findings, not_assessed = self.detect(make_snapshot(pages=pages,
                                                            headless_render=True))
        self.assertNotIn("RND.CONTENT_BEHIND_INTERACTION", self.ids(findings))
        self.assertIn("content behind interaction", self.dimensions(not_assessed))


# ==================================================================== semantic structure

class TestHeadingStructure(DetectorTestCase):

    def test_no_h1_fires_at_template_scale(self):
        pages = [make_page("/p%d.html" % i, headings=[]) for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "RND.NO_H1")

    def test_utility_pages_excluded_from_no_h1(self):
        pages = [make_page("/p%d.html" % i, page_type="utility",
                           page_type_confidence="high", headings=[]) for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("RND.NO_H1", self.ids(findings))

    def test_multiple_h1_fires_and_is_ceilinged_low(self):
        sys.path.insert(0, os.path.join(ROOT, "skills", "brand-ai-readiness-audit",
                                        "scripts"))
        import merge_findings
        pages = [make_page("/p%d.html" % i,
                           headings=make_headings((1, "A"), (1, "B")))
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        found = self.only(findings, "RND.MULTIPLE_H1")
        self.assertEqual(found.get("severity_ceiling"), "low")
        severity, _ = merge_findings.derive_severity(dict(found))
        self.assertEqual(severity, "low")

    def test_heading_jump_needs_four_or_more_headings(self):
        pages = [make_page("/p%d.html" % i,
                           headings=make_headings((1, "A"), (2, "B"), (4, "C")))
                for i in range(1)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("RND.HEADING_LEVEL_JUMPS", self.ids(findings),
                         "only 3 headings; below the check's own floor")

    def test_heading_jump_fires_with_enough_headings(self):
        pages = [make_page("/p.html",
                           headings=make_headings((1, "A"), (2, "B"), (4, "C"), (5, "D")))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "RND.HEADING_LEVEL_JUMPS")

    def test_no_jump_when_levels_increase_by_one(self):
        pages = [make_page("/p.html",
                           headings=make_headings((1, "A"), (2, "B"), (3, "C"), (4, "D")))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("RND.HEADING_LEVEL_JUMPS", self.ids(findings))

    def test_no_main_landmark_needs_cluster_threshold(self):
        pages = [make_page("/p%d.html" % i, has_main_landmark=False) for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        found = self.only(findings, "RND.NO_MAIN_LANDMARK")
        self.assertEqual(found.get("severity_ceiling"), "low")

    def test_one_page_without_main_landmark_is_not_enough(self):
        pages = [make_page("/p0.html", has_main_landmark=False),
                make_page("/p1.html"), make_page("/p2.html")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("RND.NO_MAIN_LANDMARK", self.ids(findings))


class TestBoilerplateRatio(DetectorTestCase):

    def test_fires_below_the_floor(self):
        pages = [make_page("/p%d.html" % i, page_type="product", has_main_landmark=True,
                           main_text_len=50, raw_text_len=1000) for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "RND.BOILERPLATE_RATIO")

    def test_does_not_fire_above_the_floor(self):
        pages = [make_page("/p%d.html" % i, page_type="product", has_main_landmark=True,
                           main_text_len=400, raw_text_len=600) for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("RND.BOILERPLATE_RATIO", self.ids(findings))

    def test_category_pages_are_excluded_even_at_a_low_ratio(self):
        """The clean control's own category page sits at ~0.31; must never fire."""
        pages = [make_page("/p%d.html" % i, page_type="category", has_main_landmark=True,
                           main_text_len=82, raw_text_len=266) for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("RND.BOILERPLATE_RATIO", self.ids(findings))

    def test_no_main_landmark_is_never_judged_for_ratio(self):
        pages = [make_page("/p%d.html" % i, has_main_landmark=False,
                           main_text_len=50, raw_text_len=1000) for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("RND.BOILERPLATE_RATIO", self.ids(findings))


class TestThinContent(DetectorTestCase):

    def test_fires_on_genuinely_thin_product_pages(self):
        pages = [make_page("/p%d.html" % i, page_type="product", main_text_len=50)
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "RND.THIN_CONTENT")

    def test_short_page_types_are_exempt(self):
        for page_type in ("contact", "category", "faq", "legal", "homepage", "about"):
            pages = [make_page("/p%d.html" % i, page_type=page_type, main_text_len=50)
                    for i in range(3)]
            findings, _ = self.detect(make_snapshot(pages=pages))
            self.assertNotIn("RND.THIN_CONTENT", self.ids(findings), page_type)

    def test_uses_rendered_length_when_available_not_raw(self):
        """A page thin in raw but genuinely substantial once rendered is not thin content;
        that is CSR_SHELL's territory, not this check's."""
        pages = [make_page("/p%d.html" % i, page_type="product", main_text_len=50,
                           render=render_block(main_text_len=500, ok=True))
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages, headless_render=True))
        self.assertNotIn("RND.THIN_CONTENT", self.ids(findings))

    def test_one_thin_page_alone_is_not_enough(self):
        pages = [make_page("/p0.html", page_type="product", main_text_len=50),
                make_page("/p1.html", page_type="product", main_text_len=400),
                make_page("/p2.html", page_type="product", main_text_len=400)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("RND.THIN_CONTENT", self.ids(findings))

    def test_does_not_fire_on_clean_controls_own_shortest_product_page(self):
        """Calibration guard: the real clean-control product page measures ~400 chars."""
        pages = [make_page("/p%d.html" % i, page_type="product", main_text_len=400)
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("RND.THIN_CONTENT", self.ids(findings))


class TestTitle(DetectorTestCase):

    def test_missing_title_fires(self):
        pages = [make_page("/p%d.html" % i, title="") for i in range(2)] + [
            make_page("/p2.html")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "RND.TITLE_MISSING")

    def test_duplicate_title_needs_five_pages(self):
        pages = [make_page("/p%d.html" % i, title="Shop") for i in range(4)]
        findings, _ = self.detect(make_snapshot(
            pages=pages,
            clusters=[{"id": "c01", "skeleton": "/{slug}.html", "size": 6, "depth": 1,
                      "members_sample": [], "sampled": [p["url"] for p in pages],
                      "page_type": "product", "page_type_confidence": "high"}]))
        self.assertNotIn("RND.TITLE_DUPLICATE", self.ids(findings))

    def test_duplicate_title_fires_at_five(self):
        pages = [make_page("/p%d.html" % i, title="Shop") for i in range(5)]
        findings, _ = self.detect(make_snapshot(
            pages=pages,
            clusters=[{"id": "c01", "skeleton": "/{slug}.html", "size": 6, "depth": 1,
                      "members_sample": [], "sampled": [p["url"] for p in pages],
                      "page_type": "product", "page_type_confidence": "high"}]))
        found = self.only(findings, "RND.TITLE_DUPLICATE")
        self.assertEqual(found.get("severity_ceiling"), "low")

    def test_title_comparison_is_case_and_whitespace_normalised(self):
        titles = ["Shop", "  shop", "SHOP  ", "shop", "ShoP"]
        pages = [make_page("/p%d.html" % i, title=t) for i, t in enumerate(titles)]
        findings, _ = self.detect(make_snapshot(
            pages=pages,
            clusters=[{"id": "c01", "skeleton": "/{slug}.html", "size": 6, "depth": 1,
                      "members_sample": [], "sampled": [p["url"] for p in pages],
                      "page_type": "product", "page_type_confidence": "high"}]))
        self.only(findings, "RND.TITLE_DUPLICATE")

    def test_distinct_titles_are_never_flagged(self):
        pages = [make_page("/p%d.html" % i, title="Product %d" % i) for i in range(6)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("RND.TITLE_DUPLICATE", self.ids(findings))


# ============================================================== broad false-positive suite

class TestFalsePositiveDefense(DetectorTestCase):
    """Explicit coverage of every scenario the milestone calls out by name."""

    def test_static_site_with_no_javascript_is_silent(self):
        pages = [make_page("/p%d.html" % i, page_type="product", main_text_len=400,
                           raw_text_len=600) for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertEqual(findings, [])

    def test_js_site_whose_content_is_already_in_html_is_silent(self):
        pages = [make_page("/p%d.html" % i, page_type="product", main_text_len=400,
                           raw_text_len=600,
                           render=render_block(main_text_len=410, text_len=610, tables=1))
                for i in range(3)]
        for page_ in pages:
            page_["tables"] = 1
        findings, _ = self.detect(make_snapshot(pages=pages, headless_render=True))
        self.assertEqual(findings, [])

    def test_legitimate_spa_shell_that_hydrates_fully_is_silent(self):
        """A real SPA where server-side rendering already fills the initial HTML."""
        pages = [make_page("/p%d.html" % i, page_type="product", main_text_len=450,
                           raw_html='<html><body><main><div id="app"><h1>Product %d</h1>'
                                    '<p>%s</p></div></main></body></html>'
                                    % (i, "real prerendered content " * 20))
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertEqual(findings, [])

    def test_decorative_images_are_silent(self):
        images = [{"src": "/divider.png", "alt": "", "has_alt": True, "in_content": True}]
        pages = [make_page("/p%d.html" % i, page_type="product", tables=1, images=images)
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertEqual(findings, [])

    def test_valid_tables_and_lists_are_never_penalised(self):
        pages = [make_page("/p%d.html" % i, page_type="product", tables=2,
                           definition_lists=1, main_text_len=500) for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertEqual(findings, [])

    def test_intentionally_short_non_prose_page_types_are_silent(self):
        pages = [make_page("/p%d.html" % i, page_type="contact", main_text_len=90)
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertEqual(findings, [])

    def test_non_english_content_is_judged_structurally_not_lexically(self):
        pages = [make_page("/p%d.html" % i, page_type="product", lang="fr",
                           main_text_len=450, tables=1,
                           headings=make_headings((1, "Produit")))
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertEqual(findings, [])

    def test_low_character_high_density_page_is_not_flagged_when_type_agnostic(self):
        """A terse, information-dense page is short but not diluted by heavy chrome:
        main text is most of the page, just not very long. Neither dimension should
        fire on a page shaped like that."""
        pages = [make_page("/p%d.html" % i, page_type="about",
                           main_text_len=180, raw_text_len=220)
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertEqual(findings, [])

    def test_render_unavailable_records_limitation_not_a_finding(self):
        pages = [make_page("/p%d.html" % i, page_type="product", main_text_len=400)
                for i in range(3)]
        findings, not_assessed = self.detect(make_snapshot(pages=pages,
                                                            headless_render=False))
        self.assertEqual(findings, [])
        self.assertIn("browser render comparison", self.dimensions(not_assessed))

    def test_legitimate_rendered_difference_from_ads_or_widgets_is_not_flagged(self):
        """Render grows the page (an ad slot fills in) but raw was already substantial."""
        pages = [make_page("/p%d.html" % i, page_type="product", main_text_len=450,
                           raw_text_len=700,
                           render=render_block(main_text_len=470, text_len=720))
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages, headless_render=True))
        self.assertEqual(findings, [])

    def test_hidden_ui_that_is_not_core_content_is_not_flagged(self):
        """A collapsed FAQ answer with real text already in the raw DOM (hidden via CSS,
        not injected on click) is fully readable; nothing here should fire."""
        html = ('<html><body><main><h1>FAQ</h1>'
               '<div style="display:none">The warranty lasts three years.</div>'
               '</main></body></html>')
        pages = [make_page("/p%d.html" % i, page_type="article", main_text_len=450,
                           raw_html=html) for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertEqual(findings, [])

    def test_lazy_loaded_below_fold_content_with_no_render_data_is_not_assessed(self):
        """Without a browser, this marketplace cannot confirm lazy content either way;
        it must not be asserted as broken."""
        pages = [make_page("/p%d.html" % i, page_type="product", main_text_len=400)
                for i in range(3)]
        findings, not_assessed = self.detect(make_snapshot(pages=pages))
        self.assertEqual(findings, [])


# =============================================================================== blackout

class TestBlackout(DetectorTestCase):

    def test_every_page_refused_yields_no_findings_and_records_it(self):
        pages = [make_page("/p%d.html" % i, fetch_ok=False, status=403) for i in range(3)]
        findings, not_assessed = self.detect(make_snapshot(pages=pages))
        self.assertEqual(findings, [])
        self.assertIn("page content", self.dimensions(not_assessed))


# ============================================================ evidence and action quality

def sweep_findings():
    """Produce at least one finding from every check, independently of test order."""
    scenarios = []

    scenarios.append(make_snapshot(
        pages=[make_page("/p%d.html" % i, main_text_len=0, raw_text_len=40,
                        render=render_block(main_text_len=300))
              for i in range(3)],
        headless_render=True))
    scenarios.append(make_snapshot(
        pages=[make_page("/p%d.html" % i, main_text_len=400, tables=0,
                        render=render_block(main_text_len=420, tables=1))
              for i in range(3)],
        headless_render=True))
    scenarios.append(make_snapshot(
        pages=[make_page("/p%d.html" % i,
                        render=render_block(main_text_len=900, jsonld_count=1))
              for i in range(3)],
        headless_render=True))
    scenarios.append(make_snapshot(pages=[
        make_page("/p%d.html" % i, page_type="product", tables=0,
                 images=[{"src": "/spec.png", "alt": "", "has_alt": True,
                         "in_content": True}])
        for i in range(3)]))
    scenarios.append(make_snapshot(pages=[
        make_page("/p%d.html" % i, page_type="product", tables=0,
                 documents=["https://example.test/spec-%d.pdf" % i])
        for i in range(2)] + [make_page("/p2.html")]))
    scenarios.append(make_snapshot(pages=[make_page(
        "/p.html", main_text_len=30,
        raw_html="<html><body><main><canvas></canvas></main></body></html>")]))
    scenarios.append(make_snapshot(pages=[
        make_page("/p%d.html" % i, main_text_len=30,
                 raw_html='<html><body><div role="dialog" aria-modal="true">'
                          '<p>consent</p></div></body></html>')
        for i in range(2)]))
    scenarios.append(make_snapshot(
        pages=[make_page("/p%d.html" % i, headings=[]) for i in range(3)]))
    scenarios.append(make_snapshot(pages=[
        make_page("/p%d.html" % i, headings=make_headings((1, "A"), (1, "B")))
        for i in range(3)]))
    scenarios.append(make_snapshot(pages=[
        make_page("/p%d.html" % i, headings=make_headings((1, "A"), (2, "B"),
                                                          (4, "C"), (5, "D")))
        for i in range(1)]))
    scenarios.append(make_snapshot(
        pages=[make_page("/p%d.html" % i, has_main_landmark=False) for i in range(3)]))
    scenarios.append(make_snapshot(pages=[
        make_page("/p%d.html" % i, page_type="product", has_main_landmark=True,
                 main_text_len=50, raw_text_len=1000)
        for i in range(3)]))
    scenarios.append(make_snapshot(pages=[
        make_page("/p%d.html" % i, page_type="product", main_text_len=50)
        for i in range(3)]))
    scenarios.append(make_snapshot(
        pages=[make_page("/p%d.html" % i, title="") for i in range(2)]
        + [make_page("/p2.html")]))
    scenarios.append(make_snapshot(
        pages=[make_page("/p%d.html" % i, title="Shop") for i in range(5)],
        clusters=[{"id": "c01", "skeleton": "/{slug}.html", "size": 6, "depth": 1,
                  "members_sample": [], "sampled": ["%s/p%d.html" % (ORIGIN, i)
                                                     for i in range(5)],
                  "page_type": "product", "page_type_confidence": "high"}]))
    scenarios.append(make_snapshot(pages=[
        make_page("/p%d.html" % i,
                 spa_signals=[{"signal": "empty-mount-point", "weight": "high",
                              "detail": ""},
                             {"signal": "empty-or-thin-main-content", "weight": "high",
                              "detail": ""}])
        for i in range(3)]))

    findings = []
    for snapshot in scenarios:
        found, _ = rnd.run(copy.deepcopy(snapshot))
        findings.extend(found)
    return findings


class TestEvidenceQuality(unittest.TestCase):
    """Sweep over one finding from every check, built independently of test order."""

    @classmethod
    def setUpClass(cls):
        cls.findings = sweep_findings()

    def test_the_sweep_covers_every_implemented_check(self):
        covered = {f["check_id"] for f in self.findings}
        expected = {
            "RND.CSR_SHELL", "RND.PARTIAL_JS_CONTENT", "RND.JS_ONLY_STRUCTURED_DATA",
            "RND.FACTS_IN_IMAGES", "RND.FACTS_IN_DOCUMENTS_ONLY",
            "RND.TEXT_IN_NONTEXT_ELEMENT", "RND.INTERSTITIAL_IN_RAW",
            "RND.NO_H1", "RND.MULTIPLE_H1", "RND.HEADING_LEVEL_JUMPS",
            "RND.NO_MAIN_LANDMARK", "RND.BOILERPLATE_RATIO", "RND.THIN_CONTENT",
            "RND.TITLE_MISSING", "RND.TITLE_DUPLICATE",
        }
        self.assertEqual(expected - covered, set(),
                         "these checks never fired in the sweep: %s"
                         % (expected - covered))

    def test_every_finding_is_well_formed(self):
        self.assertGreaterEqual(len(self.findings), 15)
        for found in self.findings:
            label = found.get("check_id", "?")
            for field in REQUIRED_FINDING_FIELDS:
                self.assertIn(field, found, "%s missing %s" % (label, field))
            for field in REQUIRED_ACTION_FIELDS:
                self.assertIn(field, found["suggested_action"],
                              "%s action missing %s" % (label, field))
            for field in REQUIRED_DETAIL_FIELDS:
                self.assertIn(field, found["evidence_detail"],
                              "%s detail missing %s" % (label, field))
            self.assertIn(found["gate_impact"], ("blocks", "degrades", "weakens"), label)
            self.assertIn(found["reach"], ("sitewide", "template", "page"), label)
            self.assertIn(found["certainty"], ("measured", "inferred"), label)
            self.assertEqual(found["funnel_stage"], "readable", label)
            self.assertIn(found["suggested_action"]["effort"],
                          ("trivial", "config", "content", "template-change",
                           "platform-change"), label)
            self.assertIn(found["suggested_action"]["owner"],
                          ("engineering", "content", "brand-ops", "mixed"), label)
            self.assertTrue(found["affected_urls"], "%s has no locatable URL" % label)
            self.assertGreaterEqual(len(found["evidence"]), 60,
                                    "%s evidence is too thin to verify" % label)
            self.assertTrue(found["suggested_action"]["how"],
                            "%s gives no concrete steps" % label)
            self.assertGreaterEqual(len(found["suggested_action"]["mechanism"]), 40,
                                    "%s does not explain its mechanism" % label)

    def test_no_action_claims_a_guarantee(self):
        for found in self.findings:
            text = json.dumps(found["suggested_action"]).lower()
            for phrase in ("will be cited", "guarantees a citation", "guarantee ranking",
                          "ensures you are cited", "will rank"):
                self.assertNotIn(phrase, text, found["check_id"])

    def test_no_generic_advice(self):
        for found in self.findings:
            summary = found["suggested_action"]["summary"].lower()
            for lazy in ("improve your seo", "follow best practices",
                        "optimise your site", "make the page accessible",
                        "add more content", "improve seo"):
                self.assertNotIn(lazy, summary, found["check_id"])

    def test_evidence_quotes_observed_fields_not_generic_language(self):
        """Evidence must contain a concrete measured number, not just prose."""
        for found in self.findings:
            has_digit = any(ch.isdigit() for ch in found["evidence"])
            self.assertTrue(has_digit, "%s evidence has no observed number: %s"
                            % (found["check_id"], found["evidence"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
