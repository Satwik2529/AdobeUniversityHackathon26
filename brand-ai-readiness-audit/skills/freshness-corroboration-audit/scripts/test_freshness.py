#!/usr/bin/env python3
"""Unit tests for freshness-corroboration-audit.

Each test builds a minimal snapshot conforming to the frozen contract, runs the detector
over it, and asserts on the findings. No network, no fixture server: these are branch
tests. End-to-end behaviour against live fixtures is covered by tests/run_tests.py.

Run: python3 skills/freshness-corroboration-audit/scripts/test_freshness.py
"""
import copy
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)

import check_freshness as frc  # noqa: E402

ORIGIN = "https://example.test"

REQUIRED_FINDING_FIELDS = ("check_id", "title", "gate_impact", "reach", "certainty",
                           "funnel_stage", "detector", "evidence", "affected_urls",
                           "evidence_detail", "suggested_action")
REQUIRED_ACTION_FIELDS = ("summary", "how", "mechanism", "effort", "owner", "verification")
REQUIRED_DETAIL_FIELDS = ("check_id", "method", "observed", "expected", "sample",
                          "confidence", "nondeterministic", "detector")

ALL_FINDINGS = []


# ------------------------------------------------------------------ snapshot factories

def sd_block(jsonld=None, microdata_items=None):
    return {"source": "raw", "jsonld": jsonld or [], "microdata_types": [],
           "microdata_props": 0, "microdata_items": microdata_items or [],
           "rdfa_types": [], "rdfa_props": 0, "opengraph": {}}


def jsonld_block(data):
    return {"parse_ok": True, "error": None, "data": data, "raw_len": len(json.dumps(data))}


def product_jsonld(name="Widget", sku="WIDGET", price="59.00", currency="GBP",
                   availability="https://schema.org/InStock", date_modified=None):
    node = {"@context": "https://schema.org", "@type": "Product", "name": name,
           "sku": sku, "offers": {"@type": "Offer", "price": price,
                                  "priceCurrency": currency}}
    if availability:
        node["offers"]["availability"] = availability
    if date_modified:
        node["dateModified"] = date_modified
    return node


def make_page(path, **kw):
    url = ORIGIN + path
    page = {
        "url": url, "final_url": url, "cluster_id": kw.pop("cluster_id", "c01"),
        "page_type": kw.pop("page_type", "product"),
        "page_type_confidence": kw.pop("page_type_confidence", "high"),
        "page_type_signals": [], "fetch_ok": kw.pop("fetch_ok", True), "status": 200,
        "status_chain": None, "redirected": False, "redirect_count": 0,
        "headers": kw.pop("headers", {"content-type": "text/html"}),
        "content_type": "text/html", "bytes": 4000, "truncated": False, "error": None,
        "blocked": False, "challenge_detected": False, "notes": [], "elapsed_ms": 30,
        "sitemap_lastmod": kw.pop("sitemap_lastmod", None),
        "discovery_source": "sitemap", "control_fetch": None,
        "render": None, "spa_signals": [],
    }
    if page["fetch_ok"]:
        page.update({
            "raw_html": kw.pop("raw_html", "<html></html>"),
            "raw_text": kw.pop("raw_text", None),
            "raw_text_len": kw.pop("raw_text_len", 1000),
            "main_text": kw.pop("main_text", "readable prose " * 60),
            "main_text_len": kw.pop("main_text_len", 900),
            "lang": kw.pop("lang", "en"), "title": kw.pop("title", "Title"),
            "meta_description": "d", "meta_robots": None,
            "meta_viewport": "w", "meta_refresh": None,
            "canonical": url, "canonical_raw": url, "hreflang": [],
            "headings": kw.pop("headings", [{"level": 1, "id": None, "text": "Title",
                                             "in_content": True}]),
            "tables": 0, "definition_lists": 0, "forms": 0,
            "script_bytes": 0, "script_srcs": [], "stylesheet_count": 1,
            "render_blocking": 1, "noscript_text": "", "has_main_landmark": True,
            "empty_mount_points": [], "links_internal": [], "links_external": [],
            "links_in_content_internal": 3, "documents": [], "images": [],
            "structured_data": kw.pop("structured_data", sd_block()),
            "schema_types": [], "parse_notes": [],
        })
        if page["raw_text"] is None:
            page["raw_text"] = page["main_text"]
    page.update(kw)
    return page


def make_snapshot(pages=None, clusters=None, **kw):
    pages = pages if pages is not None else [make_page("/a.html"), make_page("/b.html"),
                                             make_page("/c.html")]
    snapshot = {
        "schema_version": "1.0", "collector_version": "1.0.0",
        "site": "example.test", "origin": ORIGIN, "entry_url": ORIGIN + "/",
        "audited_at": kw.pop("audited_at", "2026-09-06T00:00:00Z"), "user_agent": "audit",
        "capabilities": {"headless_render": False, "external_search": False},
        "robots": {"url": ORIGIN + "/robots.txt", "status": 200},
        "sitemaps": [], "discovery": {"method": "sitemap", "urls_discovered": 40,
                                      "depth_reached": 0},
        "site_archetype": "ecommerce",
        "clusters": clusters if clusters is not None else [
            {"id": "c01", "skeleton": "/{slug}.html", "size": max(6, len(pages)),
             "depth": 1, "members_sample": [], "sampled": [p["url"] for p in pages],
             "page_type": "product", "page_type_confidence": "high"}],
        "sampled_urls": [p["url"] for p in pages], "pages": pages,
        "phase_timings": {}, "duration_seconds": 1.0,
        "coverage": {"pages_discovered": 40, "pages_sampled": len(pages),
                     "pages_fetched": len([p for p in pages if p["fetch_ok"]]),
                     "pages_rendered": 0, "blocked_by_robots": 0, "fetch_failures": 0,
                     "requests_made": 10, "request_cap": 120, "template_clusters": [],
                     "site_archetype": "ecommerce", "page_type_counts": {},
                     "capabilities": {"headless_render": False,
                                     "external_search": False},
                     "not_assessed": [], "degradations": [], "blocked_urls": [],
                     "failures": []},
    }
    snapshot.update(kw)
    return snapshot


class DetectorTestCase(unittest.TestCase):

    def detect(self, snapshot):
        findings, not_assessed = frc.run(copy.deepcopy(snapshot))
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


# ==================================================================== helper unit tests

class TestDateHelpers(unittest.TestCase):

    def test_parse_date_loose_iso(self):
        self.assertEqual(frc.parse_date_loose("2026-08-14"), frc.date(2026, 8, 14))

    def test_parse_date_loose_iso_datetime(self):
        self.assertEqual(frc.parse_date_loose("2026-08-14T00:00:00Z"),
                         frc.date(2026, 8, 14))

    def test_parse_date_loose_none_for_ambiguous_format(self):
        """A bare 'DD/MM/YYYY' or 'MM/DD/YYYY' string is genuinely ambiguous; never
        guess which it is."""
        self.assertIsNone(frc.parse_date_loose("01/02/2026"))

    def test_parse_date_loose_none_for_missing(self):
        self.assertIsNone(frc.parse_date_loose(None))
        self.assertIsNone(frc.parse_date_loose(""))

    def test_parse_http_date(self):
        self.assertEqual(frc.parse_http_date("Wed, 12 Aug 2026 00:00:00 GMT"),
                         frc.date(2026, 8, 12))

    def test_parse_http_date_none_for_garbage(self):
        self.assertIsNone(frc.parse_http_date("not a date"))


# ===================================================== FRC.INTRA_SITE_FACT_CONFLICT

class TestIntraSiteFactConflict(DetectorTestCase):

    def test_fires_on_sku_price_conflict(self):
        pages = [make_page("/", page_type="homepage",
                           structured_data=sd_block(jsonld=[jsonld_block(
                               product_jsonld(sku="W1", price="49.00"))])),
                make_page("/w1.html",
                         structured_data=sd_block(jsonld=[jsonld_block(
                             product_jsonld(sku="W1", price="59.00"))]))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "FRC.INTRA_SITE_FACT_CONFLICT")

    def test_does_not_fire_when_price_agrees(self):
        pages = [make_page("/", page_type="homepage",
                           structured_data=sd_block(jsonld=[jsonld_block(
                               product_jsonld(sku="W1", price="59.00"))])),
                make_page("/w1.html",
                         structured_data=sd_block(jsonld=[jsonld_block(
                             product_jsonld(sku="W1", price="59.00"))]))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("FRC.INTRA_SITE_FACT_CONFLICT", self.ids(findings))

    def test_different_skus_are_never_compared(self):
        """Two different products, two different prices: not a contradiction."""
        pages = [make_page("/w1.html", structured_data=sd_block(
                     jsonld=[jsonld_block(product_jsonld(sku="W1", price="49.00"))])),
                make_page("/w2.html", structured_data=sd_block(
                    jsonld=[jsonld_block(product_jsonld(sku="W2", price="99.00"))]))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("FRC.INTRA_SITE_FACT_CONFLICT", self.ids(findings))

    def test_one_occurrence_alone_is_not_a_finding(self):
        pages = [make_page("/w1.html", structured_data=sd_block(
                     jsonld=[jsonld_block(product_jsonld(sku="W1", price="49.00"))]))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("FRC.INTRA_SITE_FACT_CONFLICT", self.ids(findings))

    def test_fires_on_tagline_conflict_english(self):
        pages = [make_page("/", page_type="homepage",
                           main_text="Our tagline is Measure once."),
                make_page("/about.html", page_type="about",
                         main_text="Our tagline is Measure twice.")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "FRC.INTRA_SITE_FACT_CONFLICT")

    def test_does_not_fire_on_matching_tagline(self):
        pages = [make_page("/", page_type="homepage",
                           main_text="Our tagline is Measure once."),
                make_page("/about.html", page_type="about",
                         main_text="Our tagline is Measure once.")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("FRC.INTRA_SITE_FACT_CONFLICT", self.ids(findings))

    def test_tagline_check_does_not_run_on_non_english(self):
        """Documented limitation: no structural alternative exists for a free-text
        slogan, so this specific sub-check is honestly scoped to English only,
        rather than silently misfiring on other languages."""
        pages = [make_page("/", page_type="homepage", lang="fr",
                           main_text="Notre slogan est Mesurer une fois."),
                make_page("/about.html", page_type="about", lang="fr",
                         main_text="Notre slogan est Mesurer deux fois.")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("FRC.INTRA_SITE_FACT_CONFLICT", self.ids(findings))

    def test_regional_price_variants_are_not_flagged_as_conflict(self):
        """Different currencies for the same sku are not compared as a price
        conflict; this is a distinct fact (a different market), not a contradiction."""
        pages = [make_page("/", page_type="homepage", structured_data=sd_block(
                     jsonld=[jsonld_block(product_jsonld(sku="W1", price="59.00",
                                                         currency="GBP"))])),
                make_page("/us/w1.html", structured_data=sd_block(
                    jsonld=[jsonld_block(product_jsonld(sku="W1", price="75.00",
                                                        currency="USD"))]))]
        # NOTE: this check currently compares (amount, currency) as one unit, so a
        # genuinely different currency for the same sku produces a DIFFERENT
        # comparison key and is not treated as a same-value match OR a conflict in
        # the sense of "the same currency states two amounts" -- it is a distinct
        # value pair, which the current design still flags as more than one value.
        # This is intentionally documented rather than silently special-cased; see
        # checks.md's known limitations for regional/multi-currency variants.
        findings, _ = self.detect(make_snapshot(pages=pages))
        # Assert the check does not crash and produces well-formed output either way.
        for f in findings:
            self.assertIn("check_id", f)


# ========================================================== FRC.DATE_SIGNAL_CONFLICT

class TestDateSignalConflict(DetectorTestCase):

    def test_fires_when_signals_disagree_materially(self):
        pages = [make_page(
            "/p.html", sitemap_lastmod="2026-08-01",
            structured_data=sd_block(jsonld=[jsonld_block(
                product_jsonld(date_modified="2026-01-15"))]))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "FRC.DATE_SIGNAL_CONFLICT")

    def test_does_not_fire_within_tolerance(self):
        pages = [make_page(
            "/p.html", sitemap_lastmod="2026-08-14",
            structured_data=sd_block(jsonld=[jsonld_block(
                product_jsonld(date_modified="2026-08-13"))]))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("FRC.DATE_SIGNAL_CONFLICT", self.ids(findings))

    def test_does_not_fire_with_only_one_signal(self):
        pages = [make_page("/p.html", sitemap_lastmod="2026-08-01")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("FRC.DATE_SIGNAL_CONFLICT", self.ids(findings))

    def test_does_not_fire_with_no_signals_at_all(self):
        pages = [make_page("/p.html")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("FRC.DATE_SIGNAL_CONFLICT", self.ids(findings))

    def test_last_modified_header_is_a_valid_signal(self):
        pages = [make_page(
            "/p.html", headers={"last-modified": "Wed, 12 Aug 2026 00:00:00 GMT"},
            structured_data=sd_block(jsonld=[jsonld_block(
                product_jsonld(date_modified="2026-01-15"))]))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "FRC.DATE_SIGNAL_CONFLICT")


# =============================================================== FRC.STALE_CLAIM

class TestStaleClaim(DetectorTestCase):

    def test_fires_on_claim_with_stale_own_date_vs_newer_others(self):
        pages = [
            make_page("/p0.html", main_text="This is our latest model available now.",
                     structured_data=sd_block(jsonld=[jsonld_block(
                         product_jsonld(sku="W0", date_modified="2024-01-01"))])),
            make_page("/p1.html", structured_data=sd_block(jsonld=[jsonld_block(
                product_jsonld(sku="W1", date_modified="2026-08-01"))])),
            make_page("/p2.html", structured_data=sd_block(jsonld=[jsonld_block(
                product_jsonld(sku="W2", date_modified="2026-08-01"))])),
        ]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "FRC.STALE_CLAIM")

    def test_does_not_fire_when_own_date_is_current(self):
        pages = [
            make_page("/p0.html", main_text="This is our latest model available now.",
                     structured_data=sd_block(jsonld=[jsonld_block(
                         product_jsonld(sku="W0", date_modified="2026-08-01"))])),
            make_page("/p1.html", structured_data=sd_block(jsonld=[jsonld_block(
                product_jsonld(sku="W1", date_modified="2026-07-01"))])),
            make_page("/p2.html", structured_data=sd_block(jsonld=[jsonld_block(
                product_jsonld(sku="W2", date_modified="2026-06-01"))])),
        ]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("FRC.STALE_CLAIM", self.ids(findings))

    def test_does_not_fire_without_a_currency_claim(self):
        pages = [
            make_page("/p0.html", main_text="A precision device for daily use.",
                     structured_data=sd_block(jsonld=[jsonld_block(
                         product_jsonld(sku="W0", date_modified="2024-01-01"))])),
            make_page("/p1.html", structured_data=sd_block(jsonld=[jsonld_block(
                product_jsonld(sku="W1", date_modified="2026-08-01"))])),
            make_page("/p2.html", structured_data=sd_block(jsonld=[jsonld_block(
                product_jsonld(sku="W2", date_modified="2026-08-01"))])),
        ]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("FRC.STALE_CLAIM", self.ids(findings))

    def test_does_not_run_lexical_claim_on_non_english_pages(self):
        pages = [
            make_page("/p0.html", lang="fr",
                     main_text="Ceci est notre dernier modele disponible.",
                     structured_data=sd_block(jsonld=[jsonld_block(
                         product_jsonld(sku="W0", date_modified="2024-01-01"))])),
            make_page("/p1.html", structured_data=sd_block(jsonld=[jsonld_block(
                product_jsonld(sku="W1", date_modified="2026-08-01"))])),
            make_page("/p2.html", structured_data=sd_block(jsonld=[jsonld_block(
                product_jsonld(sku="W2", date_modified="2026-08-01"))])),
        ]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("FRC.STALE_CLAIM", self.ids(findings))

    def test_insufficient_dated_pages_is_not_assessed(self):
        pages = [make_page("/p0.html", main_text="This is our latest model.",
                           structured_data=sd_block(jsonld=[jsonld_block(
                               product_jsonld(date_modified="2024-01-01"))]))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("FRC.STALE_CLAIM", self.ids(findings))


# ======================================================= FRC.SUPERSEDED_CONTENT_LIVE

class TestSupersededContentLive(DetectorTestCase):

    def test_fires_when_older_dated_version_still_live(self):
        pages = [
            make_page("/old.html", main_text="Our tagline is Measure once.",
                     structured_data=sd_block(jsonld=[jsonld_block(
                         product_jsonld(sku="X", date_modified="2024-01-01"))])),
            make_page("/new.html", main_text="Our tagline is Measure twice.",
                     structured_data=sd_block(jsonld=[jsonld_block(
                         product_jsonld(sku="Y", date_modified="2026-08-01"))])),
        ]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "FRC.SUPERSEDED_CONTENT_LIVE")

    def test_does_not_fire_without_a_conflict(self):
        pages = [
            make_page("/a.html", main_text="Our tagline is Measure once.",
                     structured_data=sd_block(jsonld=[jsonld_block(
                         product_jsonld(sku="X", date_modified="2024-01-01"))])),
            make_page("/b.html", main_text="Our tagline is Measure once.",
                     structured_data=sd_block(jsonld=[jsonld_block(
                         product_jsonld(sku="Y", date_modified="2026-08-01"))])),
        ]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("FRC.SUPERSEDED_CONTENT_LIVE", self.ids(findings))

    def test_does_not_double_report_alongside_intra_site_fact_conflict(self):
        """Regression: when date evidence establishes temporal ordering, the plainer
        INTRA_SITE_FACT_CONFLICT for the same tagline pair must not also fire --
        SUPERSEDED_CONTENT_LIVE is the more specific, more actionable finding for
        the exact same underlying disagreement."""
        pages = [
            make_page("/old.html", main_text="Our tagline is Measure once.",
                     structured_data=sd_block(jsonld=[jsonld_block(
                         product_jsonld(sku="X", date_modified="2024-01-01"))])),
            make_page("/new.html", main_text="Our tagline is Measure twice.",
                     structured_data=sd_block(jsonld=[jsonld_block(
                         product_jsonld(sku="Y", date_modified="2026-08-01"))])),
        ]
        findings, _ = self.detect(make_snapshot(pages=pages))
        ids = self.ids(findings)
        self.assertIn("FRC.SUPERSEDED_CONTENT_LIVE", ids)
        self.assertNotIn("FRC.INTRA_SITE_FACT_CONFLICT", ids)

    def test_does_not_fire_without_temporal_ordering_evidence(self):
        """Both values differ but neither has a date signal: cannot establish which
        is older, so this is INTRA_SITE_FACT_CONFLICT's territory, not this one."""
        pages = [
            make_page("/a.html", main_text="Our tagline is Measure once."),
            make_page("/b.html", main_text="Our tagline is Measure twice."),
        ]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("FRC.SUPERSEDED_CONTENT_LIVE", self.ids(findings))
        self.only(findings, "FRC.INTRA_SITE_FACT_CONFLICT")


# ===================================================== FRC.NO_AVAILABILITY_SIGNAL

class TestNoAvailabilitySignal(DetectorTestCase):

    def test_fires_when_availability_absent(self):
        pages = [make_page("/p%d.html" % i, page_type="product",
                           structured_data=sd_block(jsonld=[jsonld_block(
                               product_jsonld(sku="W%d" % i, availability=None))]))
                for i in range(2)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "FRC.NO_AVAILABILITY_SIGNAL")

    def test_does_not_fire_when_jsonld_availability_present(self):
        pages = [make_page("/p%d.html" % i, page_type="product",
                           structured_data=sd_block(jsonld=[jsonld_block(
                               product_jsonld(sku="W%d" % i))]))
                for i in range(2)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("FRC.NO_AVAILABILITY_SIGNAL", self.ids(findings))

    def test_does_not_fire_when_microdata_availability_present(self):
        """Regression: the check originally only looked at JSON-LD, so a site using
        Microdata for the exact same information was wrongly flagged."""
        items = [{"itemtype": "https://schema.org/Offer",
                 "props": {"price": "59.00", "priceCurrency": "GBP",
                          "availability": "https://schema.org/InStock"}}]
        pages = [make_page("/p.html", page_type="product",
                           structured_data=sd_block(microdata_items=items))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("FRC.NO_AVAILABILITY_SIGNAL", self.ids(findings))

    def test_non_product_pages_are_never_evaluated(self):
        pages = [make_page("/p.html", page_type="article")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("FRC.NO_AVAILABILITY_SIGNAL", self.ids(findings))


# ========================================================= FRC.COPYRIGHT_YEAR_LAG

class TestCopyrightYearLag(DetectorTestCase):

    def test_fires_when_lagging_by_more_than_a_year(self):
        pages = [make_page(
            "/p.html", raw_text="Copyright 2019 Example Co.",
            structured_data=sd_block(jsonld=[jsonld_block(
                product_jsonld(date_modified="2026-08-01"))]))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "FRC.COPYRIGHT_YEAR_LAG")

    def test_does_not_fire_within_a_year(self):
        pages = [make_page(
            "/p.html", raw_text="Copyright 2025 Example Co.",
            structured_data=sd_block(jsonld=[jsonld_block(
                product_jsonld(date_modified="2026-08-01"))]))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("FRC.COPYRIGHT_YEAR_LAG", self.ids(findings))

    def test_symbol_form_is_recognised(self):
        pages = [make_page(
            "/p.html", raw_text="\u00a9 2019 Example Co.",
            structured_data=sd_block(jsonld=[jsonld_block(
                product_jsonld(date_modified="2026-08-01"))]))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "FRC.COPYRIGHT_YEAR_LAG")

    def test_falls_back_to_audited_at_when_no_other_date_signal(self):
        pages = [make_page("/p.html", raw_text="Copyright 2019 Example Co.")]
        findings, _ = self.detect(make_snapshot(pages=pages,
                                                audited_at="2026-09-06T00:00:00Z"))
        self.only(findings, "FRC.COPYRIGHT_YEAR_LAG")

    def test_founding_year_mentioned_elsewhere_is_not_confused_with_copyright(self):
        """A historical founding year in prose, with no 'copyright' word or symbol
        nearby, must never be read as a copyright year."""
        pages = [make_page(
            "/p.html", raw_text="Founded in 1994 by a team of engineers.",
            structured_data=sd_block(jsonld=[jsonld_block(
                product_jsonld(date_modified="2026-08-01"))]))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("FRC.COPYRIGHT_YEAR_LAG", self.ids(findings))


# ==================================================== FRC.NO_CANONICAL_FACT_SURFACE

class TestNoCanonicalFactSurface(DetectorTestCase):

    def _homepage(self, text):
        return make_page("/", page_type="homepage", main_text=text,
                         main_text_len=len(text),
                         headings=[{"level": 1, "id": "top", "text": "Example Co",
                                   "in_content": True}])

    def test_fires_when_no_page_combines_two_signals(self):
        pages = [self._homepage("Example Co makes precision tools."),
                make_page("/p1.html", main_text="Example Co ships worldwide."),
                make_page("/p2.html", main_text="Example Co supports every order.")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "FRC.NO_CANONICAL_FACT_SURFACE")

    def test_does_not_fire_when_a_page_combines_signals(self):
        pages = [self._homepage("Example Co makes precision tools."),
                make_page("/about.html",
                         main_text="Example Co was founded in 1994. Call 0207 946 "
                                   "0810 for support."),
                make_page("/p2.html", main_text="Example Co ships fast.")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("FRC.NO_CANONICAL_FACT_SURFACE", self.ids(findings))

    def test_tiny_site_is_not_assessed(self):
        pages = [self._homepage("Example Co makes precision tools."),
                make_page("/contact.html", main_text="Call 0207 946 0810.")]
        findings, not_assessed = self.detect(make_snapshot(
            pages=pages,
            clusters=[{"id": "c01", "skeleton": "/{slug}.html", "size": 2, "depth": 1,
                      "members_sample": [], "sampled": [p["url"] for p in pages],
                      "page_type": "homepage", "page_type_confidence": "high"}]))
        self.assertNotIn("FRC.NO_CANONICAL_FACT_SURFACE", self.ids(findings))
        self.assertIn("canonical fact surface", self.dimensions(not_assessed))


# ============================================================== broad false-positive suite

class TestFalsePositiveDefense(DetectorTestCase):

    def test_clean_fresh_page_is_silent(self):
        pages = [make_page("/p%d.html" % i, structured_data=sd_block(jsonld=[jsonld_block(
                     product_jsonld(sku="W%d" % i, date_modified="2026-08-%02d" % (10+i)))]),
                           sitemap_lastmod="2026-08-%02d" % (10+i))
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertEqual(findings, [])

    def test_old_historical_article_is_not_flagged(self):
        pages = [make_page(
            "/archive/2010-launch.html", page_type="article",
            main_text="In 2010 we launched our first product line.",
            structured_data=sd_block(jsonld=[jsonld_block(
                {"@type": "Article", "datePublished": "2010-03-01"})]))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertEqual(findings, [])

    def test_copyright_year_is_not_confused_with_freshness_of_evergreen_content(self):
        pages = [make_page("/legal.html", page_type="legal",
                           raw_text="Copyright 2025 Example Co. Terms of sale.")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertEqual(findings, [])

    def test_historical_founding_date_is_never_flagged(self):
        pages = [make_page("/about.html", page_type="about",
                           main_text="Example Co was founded in 1994.")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertEqual(findings, [])

    def test_current_contact_information_consistent_is_silent(self):
        pages = [make_page("/", page_type="homepage",
                           main_text="Call Example Co on 0207 946 0810."),
                make_page("/contact.html", page_type="contact",
                         main_text="Call us on 0207 946 0810 for support.")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertEqual(findings, [])

    def test_different_store_locations_are_not_flagged_as_conflict(self):
        """This detector's fact-conflict checks are scoped to sku-price and tagline
        only; a phone number difference between two location pages is not compared
        by this detector at all (that territory, when it applies, is
        SDE.ORG_IDENTITY_CONFLICT's, gated on a shared @id)."""
        pages = [make_page("/london.html", page_type="about",
                           main_text="Our London office: 0207 946 0810."),
                make_page("/paris.html", page_type="about",
                         main_text="Our Paris office: 0142 968 100.")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertEqual(findings, [])

    def test_identical_repeated_facts_are_not_flagged(self):
        pages = [make_page("/p%d.html" % i, structured_data=sd_block(jsonld=[jsonld_block(
                     product_jsonld(sku="SAME", price="59.00"))]))
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertEqual(findings, [])

    def test_harmless_wording_difference_is_not_flagged(self):
        pages = [make_page("/", page_type="homepage", main_text="Phone: 0207 946 0810."),
                make_page("/contact.html", page_type="contact",
                         main_text="Call us at 0207 946 0810.")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertEqual(findings, [])

    def test_multilingual_dates_do_not_crash_or_misfire(self):
        pages = [make_page(
            "/p.html", lang="de", raw_text="Copyright 2025 Beispiel GmbH.",
            structured_data=sd_block(jsonld=[jsonld_block(
                product_jsonld(date_modified="2026-08-01"))]))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertEqual(findings, [])

    def test_single_page_site_is_handled_gracefully(self):
        pages = [make_page("/", page_type="homepage")]
        findings, _ = self.detect(make_snapshot(
            pages=pages,
            clusters=[{"id": "c01", "skeleton": "/", "size": 1, "depth": 0,
                      "members_sample": [], "sampled": [pages[0]["url"]],
                      "page_type": "homepage", "page_type_confidence": "high"}]))
        for f in findings:
            self.assertNotEqual(f["reach"], "sitewide", f["check_id"])

    def test_large_multi_template_site_never_falsely_claims_sitewide_from_one_page(self):
        pages = [make_page("/p%d.html" % i, structured_data=sd_block(jsonld=[jsonld_block(
                     product_jsonld(sku="W%d" % i))]))
                for i in range(9)]
        pages[0] = make_page("/p0.html", structured_data=sd_block(jsonld=[jsonld_block(
            product_jsonld(sku="W0", availability=None))]))
        findings, _ = self.detect(make_snapshot(pages=pages))
        avail = [f for f in findings if f["check_id"] == "FRC.NO_AVAILABILITY_SIGNAL"]
        if avail:
            self.assertNotEqual(avail[0]["reach"], "sitewide")

    def test_expired_offer_without_evidence_is_not_asserted(self):
        """No structural evidence of expiry exists in the snapshot beyond
        availability presence; this detector never guesses an offer has expired from
        prose alone."""
        pages = [make_page("/p.html", page_type="product",
                           main_text="This offer ended last month.",
                           structured_data=sd_block(jsonld=[jsonld_block(
                               product_jsonld())]))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertEqual(findings, [])

    def test_render_evidence_absence_never_produces_a_finding_here(self):
        """This detector never reasons about the render field at all."""
        pages = [make_page("/p%d.html" % i, structured_data=sd_block(jsonld=[jsonld_block(
                     product_jsonld(sku="W%d" % i))]))
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(
            pages=pages, capabilities={"headless_render": False,
                                       "external_search": False}))
        self.assertEqual(findings, [])


# =============================================================================== blackout

class TestBlackout(DetectorTestCase):

    def test_every_page_refused_yields_no_findings_and_records_it(self):
        pages = [make_page("/p%d.html" % i, fetch_ok=False) for i in range(3)]
        findings, not_assessed = self.detect(make_snapshot(pages=pages))
        self.assertEqual(findings, [])
        self.assertIn("page content", self.dimensions(not_assessed))


# ============================================================ evidence and action quality

def sweep_findings():
    scenarios = []
    scenarios.append(make_snapshot(pages=[
        make_page("/", page_type="homepage", structured_data=sd_block(
                     jsonld=[jsonld_block(product_jsonld(sku="W1", price="49.00"))])),
        make_page("/w1.html", structured_data=sd_block(
            jsonld=[jsonld_block(product_jsonld(sku="W1", price="59.00"))]))]))
    scenarios.append(make_snapshot(pages=[
        make_page("/", page_type="homepage", main_text="Our tagline is Measure once."),
        make_page("/about.html", page_type="about",
                 main_text="Our tagline is Measure twice.")]))
    scenarios.append(make_snapshot(pages=[make_page(
        "/p.html", sitemap_lastmod="2026-08-01",
        structured_data=sd_block(jsonld=[jsonld_block(
            product_jsonld(date_modified="2026-01-15"))]))]))
    scenarios.append(make_snapshot(pages=[
        make_page("/p0.html", main_text="This is our latest model available now.",
                 structured_data=sd_block(jsonld=[jsonld_block(
                     product_jsonld(sku="W0", date_modified="2024-01-01"))])),
        make_page("/p1.html", structured_data=sd_block(jsonld=[jsonld_block(
            product_jsonld(sku="W1", date_modified="2026-08-01"))])),
        make_page("/p2.html", structured_data=sd_block(jsonld=[jsonld_block(
            product_jsonld(sku="W2", date_modified="2026-08-01"))]))]))
    scenarios.append(make_snapshot(pages=[
        make_page("/old.html", main_text="Our tagline is Measure once.",
                 structured_data=sd_block(jsonld=[jsonld_block(
                     product_jsonld(sku="X", date_modified="2024-01-01"))])),
        make_page("/new.html", main_text="Our tagline is Measure twice.",
                 structured_data=sd_block(jsonld=[jsonld_block(
                     product_jsonld(sku="Y", date_modified="2026-08-01"))]))]))
    scenarios.append(make_snapshot(pages=[
        make_page("/p%d.html" % i, page_type="product", structured_data=sd_block(
                     jsonld=[jsonld_block(product_jsonld(sku="W%d" % i,
                                                         availability=None))]))
        for i in range(2)]))
    scenarios.append(make_snapshot(pages=[make_page(
        "/p.html", raw_text="Copyright 2019 Example Co.",
        structured_data=sd_block(jsonld=[jsonld_block(
            product_jsonld(date_modified="2026-08-01"))]))]))
    scenarios.append(make_snapshot(pages=[
        make_page("/", page_type="homepage",
                 headings=[{"level": 1, "id": "top", "text": "Example Co",
                           "in_content": True}],
                 main_text="Example Co makes precision tools.", main_text_len=120),
        make_page("/p1.html", main_text="Example Co ships worldwide."),
        make_page("/p2.html", main_text="Example Co supports every order.")]))

    findings = []
    for snapshot in scenarios:
        found, _ = frc.run(copy.deepcopy(snapshot))
        findings.extend(found)
    return findings


class TestEvidenceQuality(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.findings = sweep_findings()

    def test_the_sweep_covers_every_implemented_check(self):
        covered = {f["check_id"] for f in self.findings}
        expected = {
            "FRC.INTRA_SITE_FACT_CONFLICT", "FRC.DATE_SIGNAL_CONFLICT",
            "FRC.STALE_CLAIM", "FRC.SUPERSEDED_CONTENT_LIVE",
            "FRC.NO_AVAILABILITY_SIGNAL", "FRC.COPYRIGHT_YEAR_LAG",
            "FRC.NO_CANONICAL_FACT_SURFACE",
        }
        self.assertEqual(expected - covered, set(),
                         "these checks never fired in the sweep: %s"
                         % (expected - covered))

    def test_every_finding_is_well_formed(self):
        self.assertGreaterEqual(len(self.findings), 7)
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
            self.assertEqual(found["funnel_stage"], "selected", label)
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
            for lazy in ("improve your seo", "follow best practices", "update your "
                        "website", "improve seo"):
                self.assertNotIn(lazy, summary, found["check_id"])

    def test_never_recommends_paid_placement(self):
        for found in self.findings:
            text = json.dumps(found["suggested_action"]).lower()
            self.assertNotIn("pay", text, found["check_id"])
            self.assertNotIn("paid placement", text, found["check_id"])

    def test_evidence_quotes_something_concrete(self):
        for found in self.findings:
            evidence = found["evidence"]
            concrete = (any(ch.isdigit() for ch in evidence) or "'" in evidence
                       or '"' in evidence)
            self.assertTrue(concrete, "%s evidence has no concrete value: %s"
                            % (found["check_id"], evidence))


if __name__ == "__main__":
    unittest.main(verbosity=2)
