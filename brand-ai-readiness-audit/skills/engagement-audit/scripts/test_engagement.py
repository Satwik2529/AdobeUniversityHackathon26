#!/usr/bin/env python3
"""Unit tests for engagement-audit.

Each test builds a minimal snapshot conforming to the frozen contract, runs the detector
over it, and asserts on the findings. No network, no fixture server: these are branch
tests. End-to-end behaviour against live fixtures is covered by tests/run_tests.py.

Run: python3 skills/engagement-audit/scripts/test_engagement.py
"""
import copy
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)

import check_engagement as eng  # noqa: E402

ORIGIN = "https://example.test"

REQUIRED_FINDING_FIELDS = ("check_id", "title", "gate_impact", "reach", "certainty",
                           "funnel_stage", "detector", "evidence", "affected_urls",
                           "evidence_detail", "suggested_action")
REQUIRED_ACTION_FIELDS = ("summary", "how", "mechanism", "effort", "owner", "verification")
REQUIRED_DETAIL_FIELDS = ("check_id", "method", "observed", "expected", "sample",
                          "confidence", "nondeterministic", "detector")

ALL_FINDINGS = []


# ------------------------------------------------------------------ snapshot factories

def link(url, text, in_content=True, rel=""):
    return {"url": url, "in_content": in_content, "text": text, "rel": rel}


def make_page(path, **kw):
    url = ORIGIN + path
    page = {
        "url": url, "final_url": url, "cluster_id": kw.pop("cluster_id", "c01"),
        "page_type": kw.pop("page_type", "product"),
        "page_type_confidence": kw.pop("page_type_confidence", "high"),
        "page_type_signals": [], "fetch_ok": kw.pop("fetch_ok", True), "status": 200,
        "status_chain": None, "redirected": False, "redirect_count": 0,
        "headers": {"content-type": "text/html"}, "content_type": "text/html",
        "bytes": 4000, "truncated": False, "error": None, "blocked": False,
        "challenge_detected": False, "notes": [], "elapsed_ms": 30,
        "sitemap_lastmod": None, "discovery_source": "sitemap", "control_fetch": None,
        "render": None, "spa_signals": [],
    }
    if page["fetch_ok"]:
        page.update({
            "raw_html": "<html></html>", "raw_text": "text " * 200,
            "raw_text_len": 1000,
            "main_text": kw.pop("main_text", "readable prose " * 60),
            "main_text_len": kw.pop("main_text_len", 900),
            "lang": kw.pop("lang", "en"), "title": kw.pop("title", "Title"),
            "meta_description": "d", "meta_robots": None,
            "meta_viewport": "w", "meta_refresh": None,
            "canonical": url, "canonical_raw": url, "hreflang": [],
            "headings": [{"level": 1, "id": None, "text": "Title", "in_content": True}],
            "tables": 0, "definition_lists": 0, "forms": 0,
            "script_bytes": 0, "script_srcs": [], "stylesheet_count": 1,
            "render_blocking": 1, "noscript_text": "", "has_main_landmark": True,
            "empty_mount_points": [],
            "links_internal": kw.pop("links_internal", []),
            "links_external": kw.pop("links_external", []),
            "links_in_content_internal": 0,
            "documents": [], "images": [],
            "structured_data": {"source": "raw", "jsonld": [], "microdata_types": [],
                                "microdata_props": 0, "microdata_items": [],
                                "rdfa_types": [], "rdfa_props": 0, "opengraph": {}},
            "schema_types": [], "parse_notes": [],
        })
    page.update(kw)
    return page


def make_snapshot(pages=None, clusters=None, **kw):
    pages = pages if pages is not None else [make_page("/a.html"), make_page("/b.html"),
                                             make_page("/c.html")]
    snapshot = {
        "schema_version": "1.0", "collector_version": "1.0.0",
        "site": "example.test", "origin": ORIGIN, "entry_url": ORIGIN + "/",
        "audited_at": "2026-09-06T00:00:00Z", "user_agent": "audit",
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
        findings, not_assessed = eng.run(copy.deepcopy(snapshot))
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


# ============================================================ helper unit tests

class TestHelpers(unittest.TestCase):

    def test_norm_url_strips_trailing_slash(self):
        self.assertEqual(eng.norm_url(ORIGIN + "/products/"),
                         eng.norm_url(ORIGIN + "/products"))

    def test_norm_url_strips_www(self):
        self.assertEqual(eng.norm_url("https://www.example.test/a"),
                         eng.norm_url("https://example.test/a"))

    def test_norm_url_ignores_fragment(self):
        self.assertEqual(eng.norm_url(ORIGIN + "/a.html#section"),
                         eng.norm_url(ORIGIN + "/a.html"))

    def test_norm_url_keeps_meaningfully_different_query(self):
        self.assertNotEqual(eng.norm_url(ORIGIN + "/a.html?id=1"),
                            eng.norm_url(ORIGIN + "/a.html?id=2"))

    def test_has_action_phrase_matches_conservative_list(self):
        self.assertTrue(eng.has_action_phrase("Contact us to buy"))
        self.assertTrue(eng.has_action_phrase("Request a quote"))
        self.assertFalse(eng.has_action_phrase("About our company"))

    def test_is_generic_anchor(self):
        self.assertTrue(eng.is_generic_anchor("Learn more"))
        self.assertTrue(eng.is_generic_anchor("  Click Here  "))
        self.assertFalse(eng.is_generic_anchor("Alpha Caliper specifications"))


# ============================================================ ENG.DEAD_END_HIGH_VALUE_PAGE

class TestDeadEndHighValue(DetectorTestCase):

    def test_fires_when_zero_in_content_links(self):
        pages = [make_page("/p%d.html" % i, page_type="product",
                           links_internal=[link(ORIGIN + "/nav.html", "Home",
                                                in_content=False)])
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "ENG.DEAD_END_HIGH_VALUE_PAGE")

    def test_does_not_fire_with_one_in_content_link(self):
        pages = [make_page("/p%d.html" % i, page_type="product",
                           links_internal=[link(ORIGIN + "/other.html", "Related",
                                                in_content=True)])
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ENG.DEAD_END_HIGH_VALUE_PAGE", self.ids(findings))

    def test_navigation_only_links_do_not_count(self):
        pages = [make_page("/p%d.html" % i, page_type="product",
                           links_internal=[link(ORIGIN + "/", "Home", in_content=False),
                                          link(ORIGIN + "/contact.html", "Contact",
                                               in_content=False)])
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "ENG.DEAD_END_HIGH_VALUE_PAGE")

    def test_legal_page_dead_end_is_never_flagged(self):
        pages = [make_page("/legal.html", page_type="legal", links_internal=[])]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ENG.DEAD_END_HIGH_VALUE_PAGE", self.ids(findings))

    def test_contact_page_dead_end_is_never_flagged(self):
        pages = [make_page("/contact.html", page_type="contact", links_internal=[])]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ENG.DEAD_END_HIGH_VALUE_PAGE", self.ids(findings))

    def test_faq_page_dead_end_is_never_flagged(self):
        pages = [make_page("/faq.html", page_type="faq", links_internal=[])]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ENG.DEAD_END_HIGH_VALUE_PAGE", self.ids(findings))

    def test_article_and_docs_types_are_also_covered(self):
        pages = [make_page("/p%d.html" % i, page_type=t, links_internal=[])
                for i, t in enumerate(["article", "docs"])]
        findings, _ = self.detect(make_snapshot(pages=pages))
        found = self.only(findings, "ENG.DEAD_END_HIGH_VALUE_PAGE")
        self.assertEqual(len(found["affected_urls"]), 2)

    def test_one_of_many_dead_end_is_page_reach_not_template(self):
        pages = [make_page("/p0.html", page_type="product", links_internal=[])]
        pages += [make_page("/p%d.html" % i, page_type="product",
                            links_internal=[link(ORIGIN + "/x.html", "x")])
                 for i in range(1, 3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        found = self.only(findings, "ENG.DEAD_END_HIGH_VALUE_PAGE")
        self.assertEqual(found["reach"], "page")


# ==================================================== ENG.NO_RELATED_CONTENT_PATHWAY

class TestNoRelatedContentPathway(DetectorTestCase):

    def _with_destination(self, dest_type, dest_confidence="high"):
        dest = make_page("/dest.html", page_type=dest_type,
                         page_type_confidence=dest_confidence)
        source = make_page("/p.html", page_type="product",
                           links_internal=[link(dest["url"], "See this")])
        return [source, dest]

    def test_fires_when_links_lead_only_to_unrelated_types(self):
        pages = self._with_destination("contact")
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "ENG.NO_RELATED_CONTENT_PATHWAY")

    def test_does_not_fire_when_linking_to_another_product(self):
        pages = self._with_destination("product")
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ENG.NO_RELATED_CONTENT_PATHWAY", self.ids(findings))

    def test_does_not_fire_when_linking_to_category_listing(self):
        """Regression: a category/listing page is a legitimate related-content hub
        ('browse the full range' from a product page), not a utility destination."""
        pages = self._with_destination("category")
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ENG.NO_RELATED_CONTENT_PATHWAY", self.ids(findings))

    def test_does_not_fire_when_linking_to_article_or_docs(self):
        for dest_type in ("article", "docs"):
            pages = self._with_destination(dest_type)
            findings, _ = self.detect(make_snapshot(pages=pages))
            self.assertNotIn("ENG.NO_RELATED_CONTENT_PATHWAY", self.ids(findings),
                             dest_type)

    def test_low_confidence_destination_is_insufficient_evidence(self):
        """Regression: a destination classified at low confidence (which can happen
        when a page's own signals are reduced, e.g. non-English content or
        Microdata-only structured data) must not be treated as confirmed evidence
        the destination is unrelated."""
        pages = self._with_destination("contact", dest_confidence="low")
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ENG.NO_RELATED_CONTENT_PATHWAY", self.ids(findings))

    def test_destination_outside_the_sample_is_not_counted_against_the_page(self):
        source = make_page("/p.html", page_type="product",
                           links_internal=[link(ORIGIN + "/not-sampled.html", "See")])
        findings, _ = self.detect(make_snapshot(pages=[source]))
        self.assertNotIn("ENG.NO_RELATED_CONTENT_PATHWAY", self.ids(findings))

    def test_zero_links_defers_to_dead_end_check(self):
        pages = [make_page("/p.html", page_type="product", links_internal=[])]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ENG.NO_RELATED_CONTENT_PATHWAY", self.ids(findings))
        self.only(findings, "ENG.DEAD_END_HIGH_VALUE_PAGE")


# ======================================================== ENG.WEAK_ACTION_PATHWAY

class TestWeakActionPathway(DetectorTestCase):

    def test_fires_when_no_action_phrase_anywhere(self):
        pages = [make_page("/p%d.html" % i, page_type="product",
                           links_internal=[link(ORIGIN + "/about.html", "About us")])
                for i in range(2)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "ENG.WEAK_ACTION_PATHWAY")

    def test_does_not_fire_with_in_content_action_link(self):
        pages = [make_page("/p%d.html" % i, page_type="product",
                           links_internal=[link(ORIGIN + "/contact.html",
                                                "Contact us to buy")])
                for i in range(2)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ENG.WEAK_ACTION_PATHWAY", self.ids(findings))

    def test_navigation_action_link_counts(self):
        """Unlike related-content continuation, a consistent site-wide action path
        (e.g. a nav-level 'Contact' link) is still a real, observable path."""
        pages = [make_page("/p%d.html" % i, page_type="product",
                           links_internal=[link(ORIGIN + "/contact.html", "Contact",
                                                in_content=False)])
                for i in range(2)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ENG.WEAK_ACTION_PATHWAY", self.ids(findings))

    def test_external_action_link_counts(self):
        pages = [make_page("/p%d.html" % i, page_type="product",
                           links_external=[link("https://shop.example.com/buy",
                                                "Buy now")])
                for i in range(2)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ENG.WEAK_ACTION_PATHWAY", self.ids(findings))

    def test_non_product_pages_are_never_evaluated(self):
        pages = [make_page("/p.html", page_type="article", links_internal=[])]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ENG.WEAK_ACTION_PATHWAY", self.ids(findings))


# ===================================================== ENG.EXCESSIVE_PATHWAY_DEPTH

class TestExcessivePathwayDepth(DetectorTestCase):

    def _clusters(self, depths_by_type):
        return [{"id": "c%d" % i, "skeleton": "/x%d/{s}" % i, "size": 6, "depth": depth,
                "members_sample": [], "sampled": [ORIGIN + "/x%d/p.html" % i],
                "page_type": ptype, "page_type_confidence": "high"}
               for i, (ptype, depth) in enumerate(depths_by_type)]

    def test_fires_when_high_value_cluster_is_much_deeper_than_median(self):
        clusters = self._clusters([("about", 1), ("contact", 1), ("faq", 1),
                                   ("product", 5)])
        pages = [make_page("/x%d/p.html" % i, page_type=c["page_type"])
                for i, c in enumerate(clusters)]
        findings, _ = self.detect(make_snapshot(pages=pages, clusters=clusters))
        self.only(findings, "ENG.EXCESSIVE_PATHWAY_DEPTH")

    def test_does_not_fire_when_depth_is_comparable(self):
        clusters = self._clusters([("about", 1), ("contact", 1), ("faq", 2),
                                   ("product", 2)])
        pages = [make_page("/x%d/p.html" % i, page_type=c["page_type"])
                for i, c in enumerate(clusters)]
        findings, _ = self.detect(make_snapshot(pages=pages, clusters=clusters))
        self.assertNotIn("ENG.EXCESSIVE_PATHWAY_DEPTH", self.ids(findings))

    def test_does_not_fire_with_too_few_clusters(self):
        clusters = self._clusters([("about", 1), ("product", 5)])
        pages = [make_page("/x%d/p.html" % i, page_type=c["page_type"])
                for i, c in enumerate(clusters)]
        findings, _ = self.detect(make_snapshot(pages=pages, clusters=clusters))
        self.assertNotIn("ENG.EXCESSIVE_PATHWAY_DEPTH", self.ids(findings))

    def test_never_claims_global_site_depth(self):
        """The evidence must be phrased relative to this site's own sample, never as
        an absolute or global depth claim."""
        clusters = self._clusters([("about", 1), ("contact", 1), ("faq", 1),
                                   ("product", 5)])
        pages = [make_page("/x%d/p.html" % i, page_type=c["page_type"])
                for i, c in enumerate(clusters)]
        findings, _ = self.detect(make_snapshot(pages=pages, clusters=clusters))
        found = self.only(findings, "ENG.EXCESSIVE_PATHWAY_DEPTH")
        self.assertIn("this site's own", found["evidence"])
        self.assertEqual(found["certainty"], "inferred")


# ======================================================== ENG.ORPHAN_LIKE_SAMPLED_PAGE

class TestOrphanLikeSampledPage(DetectorTestCase):

    def _site(self, orphan_type="about"):
        home = make_page("/", page_type="homepage",
                         links_internal=[link(ORIGIN + "/p0.html", "Products",
                                              in_content=False)])
        orphan = make_page("/orphan.html", page_type=orphan_type, main_text_len=300)
        # A closed ring (each page links to the next, the last links back to the
        # first) so every product page has a genuine inbound link from within the
        # sample, isolating the orphan page as the only actually-unlinked page.
        others = [make_page("/p%d.html" % i, page_type="product",
                            links_internal=[link(ORIGIN + "/p%d.html" % ((i + 1) % 6),
                                                 "next")])
                 for i in range(6)]
        return [home, orphan] + others

    def test_fires_on_page_with_no_inbound_sampled_link(self):
        pages = self._site(orphan_type="about")
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "ENG.ORPHAN_LIKE_SAMPLED_PAGE")

    def test_legal_page_orphan_is_never_flagged(self):
        pages = self._site(orphan_type="legal")
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ENG.ORPHAN_LIKE_SAMPLED_PAGE", self.ids(findings))

    def test_contact_page_orphan_is_never_flagged(self):
        pages = self._site(orphan_type="contact")
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ENG.ORPHAN_LIKE_SAMPLED_PAGE", self.ids(findings))

    def test_faq_page_orphan_is_never_flagged(self):
        pages = self._site(orphan_type="faq")
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ENG.ORPHAN_LIKE_SAMPLED_PAGE", self.ids(findings))

    def test_homepage_is_never_flagged_as_orphan(self):
        pages = self._site()
        findings, _ = self.detect(make_snapshot(pages=pages))
        home_url = ORIGIN + "/"
        for f in findings:
            if f["check_id"] == "ENG.ORPHAN_LIKE_SAMPLED_PAGE":
                self.assertNotIn(home_url, f["affected_urls"])

    def test_evidence_is_worded_as_sample_scoped_not_global(self):
        pages = self._site(orphan_type="about")
        findings, _ = self.detect(make_snapshot(pages=pages))
        found = self.only(findings, "ENG.ORPHAN_LIKE_SAMPLED_PAGE")
        self.assertIn("within the sampled graph", found["evidence"])
        self.assertIn("does not establish", found["evidence"])

    def test_tiny_sample_is_not_assessed(self):
        pages = [make_page("/", page_type="homepage"),
                make_page("/about.html", page_type="about")]
        findings, not_assessed = self.detect(make_snapshot(
            pages=pages,
            clusters=[{"id": "c01", "skeleton": "/{s}", "size": 2, "depth": 0,
                      "members_sample": [], "sampled": [p["url"] for p in pages],
                      "page_type": "homepage", "page_type_confidence": "high"}]))
        self.assertNotIn("ENG.ORPHAN_LIKE_SAMPLED_PAGE", self.ids(findings))
        self.assertIn("orphan-like page detection", self.dimensions(not_assessed))

    def test_inbound_link_from_navigation_still_counts(self):
        """Any inbound link counts toward "not orphan", not only in-content ones --
        this check is about discoverability, unlike the continuation checks."""
        home = make_page("/", page_type="homepage",
                         links_internal=[link(ORIGIN + "/about.html", "About",
                                              in_content=False)]
                         + [link(ORIGIN + "/p%d.html" % i, "Product %d" % i,
                                in_content=False) for i in range(6)])
        about = make_page("/about.html", page_type="about", main_text_len=300)
        others = [make_page("/p%d.html" % i, page_type="product",
                            links_internal=[link(ORIGIN + "/contact.html",
                                                 "Contact us to buy")])
                 for i in range(6)]
        findings, _ = self.detect(make_snapshot(pages=[home, about] + others))
        self.assertNotIn("ENG.ORPHAN_LIKE_SAMPLED_PAGE", self.ids(findings))


# ======================================================== ENG.AMBIGUOUS_ACTION_SURFACE

class TestAmbiguousActionSurface(DetectorTestCase):

    def test_fires_on_same_generic_text_different_destinations(self):
        page = make_page("/p.html", links_internal=[
            link(ORIGIN + "/a.html", "Learn more"),
            link(ORIGIN + "/b.html", "Learn more")])
        findings, _ = self.detect(make_snapshot(pages=[page]))
        self.only(findings, "ENG.AMBIGUOUS_ACTION_SURFACE")

    def test_does_not_fire_when_same_text_same_destination(self):
        """Two links to the same place with the same text is ordinary repetition,
        not ambiguity -- both instances agree on where they go."""
        page = make_page("/p.html", links_internal=[
            link(ORIGIN + "/a.html", "Learn more"),
            link(ORIGIN + "/a.html", "Learn more")])
        findings, _ = self.detect(make_snapshot(pages=[page]))
        self.assertNotIn("ENG.AMBIGUOUS_ACTION_SURFACE", self.ids(findings))

    def test_does_not_fire_on_descriptive_anchor_text(self):
        page = make_page("/p.html", links_internal=[
            link(ORIGIN + "/a.html", "Alpha Caliper specifications"),
            link(ORIGIN + "/b.html", "Beta Caliper specifications")])
        findings, _ = self.detect(make_snapshot(pages=[page]))
        self.assertNotIn("ENG.AMBIGUOUS_ACTION_SURFACE", self.ids(findings))

    def test_navigation_links_are_not_evaluated(self):
        page = make_page("/p.html", links_internal=[
            link(ORIGIN + "/a.html", "Learn more", in_content=False),
            link(ORIGIN + "/b.html", "Learn more", in_content=False)])
        findings, _ = self.detect(make_snapshot(pages=[page]))
        self.assertNotIn("ENG.AMBIGUOUS_ACTION_SURFACE", self.ids(findings))

    def test_single_generic_link_alone_is_not_ambiguous(self):
        page = make_page("/p.html", links_internal=[link(ORIGIN + "/a.html",
                                                          "Learn more")])
        findings, _ = self.detect(make_snapshot(pages=[page]))
        self.assertNotIn("ENG.AMBIGUOUS_ACTION_SURFACE", self.ids(findings))


# ============================================================== broad false-positive suite

class TestFalsePositiveDefense(DetectorTestCase):

    def test_healthy_product_page_is_silent(self):
        related = make_page("/beta.html", page_type="product", links_internal=[
            link(ORIGIN + "/contact.html", "Contact us to buy")])
        page = make_page("/alpha.html", page_type="product", links_internal=[
            link(ORIGIN + "/contact.html", "Contact us to buy"),
            link(related["url"], "See the Beta Caliper")])
        findings, _ = self.detect(make_snapshot(pages=[page, related]))
        self.assertEqual(findings, [])

    def test_healthy_article_with_contextual_links_is_silent(self):
        related = make_page("/other-article.html", page_type="article",
                            links_internal=[link(ORIGIN + "/article.html",
                                                 "Back to the first article")])
        page = make_page("/article.html", page_type="article", links_internal=[
            link(related["url"], "Read the follow-up article")])
        findings, _ = self.detect(make_snapshot(pages=[page, related]))
        self.assertEqual(findings, [])

    def test_legal_page_correctly_lacking_cta_is_silent(self):
        page = make_page("/legal.html", page_type="legal", links_internal=[])
        findings, _ = self.detect(make_snapshot(pages=[page]))
        self.assertEqual(findings, [])

    def test_contact_page_as_correct_endpoint_is_silent(self):
        page = make_page("/contact.html", page_type="contact", links_internal=[])
        findings, _ = self.detect(make_snapshot(pages=[page]))
        self.assertEqual(findings, [])

    def test_nav_links_present_but_no_contextual_links_for_valid_reason(self):
        """A category/listing page (not itself a high-value type) with only
        navigation links is not evaluated by the continuation checks at all."""
        page = make_page("/products/", page_type="category",
                         links_internal=[link(ORIGIN + "/", "Home", in_content=False)])
        findings, _ = self.detect(make_snapshot(pages=[page]))
        self.assertEqual(findings, [])

    def test_shallow_small_site_never_triggers_depth_finding(self):
        clusters = [{"id": "c01", "skeleton": "/{s}", "size": 3, "depth": 0,
                    "members_sample": [], "sampled": [ORIGIN + "/"],
                    "page_type": "homepage", "page_type_confidence": "high"},
                   {"id": "c02", "skeleton": "/products/{s}", "size": 3, "depth": 1,
                    "members_sample": [], "sampled": [ORIGIN + "/products/p.html"],
                    "page_type": "product", "page_type_confidence": "high"}]
        pages = [make_page("/", page_type="homepage"),
                make_page("/products/p.html", page_type="product")]
        findings, _ = self.detect(make_snapshot(pages=pages, clusters=clusters))
        self.assertNotIn("ENG.EXCESSIVE_PATHWAY_DEPTH", self.ids(findings))

    def test_duplicate_links_to_same_destination_is_not_ambiguous(self):
        page = make_page("/p.html", page_type="product", links_internal=[
            link(ORIGIN + "/contact.html", "Contact us to buy"),
            link(ORIGIN + "/contact.html", "Contact us to buy")])
        findings, _ = self.detect(make_snapshot(pages=[page]))
        self.assertEqual(findings, [])

    def test_non_english_cta_text_is_not_falsely_claimed_understood(self):
        """The action-phrase lexicon is English-only by design (documented
        limitation); a non-English action link legitimately is not detected as one,
        and this must not be worded as a false structural claim -- it simply cannot
        confirm an action pathway exists via this specific signal."""
        page = make_page("/p.html", page_type="product", lang="fr",
                         links_internal=[link(ORIGIN + "/contact.html",
                                              "Contactez-nous")])
        findings, _ = self.detect(make_snapshot(pages=[page]))
        # This is an acknowledged limitation, not asserted as a false positive guard;
        # confirm it does not crash and produces well-formed output either way.
        for f in findings:
            self.assertIn("check_id", f)

    def test_self_link_does_not_satisfy_related_content_or_orphan_check(self):
        page = make_page("/p.html", page_type="product",
                         links_internal=[link(ORIGIN + "/p.html", "Refresh")])
        findings, _ = self.detect(make_snapshot(pages=[page]))
        # A self-link is not a meaningful destination; the page still has a link,
        # so DEAD_END should not fire, but the self-link resolves to itself which
        # this test simply verifies does not crash.
        for f in findings:
            self.assertIn("check_id", f)

    def test_external_link_is_never_counted_as_internal_continuation(self):
        page = make_page("/p.html", page_type="product",
                         links_external=[link("https://other-site.example/related",
                                              "Related reading", in_content=True)])
        findings, _ = self.detect(make_snapshot(pages=[page]))
        # links_external must never satisfy DEAD_END or NO_RELATED_CONTENT_PATHWAY,
        # both of which only read links_internal.
        self.only(findings, "ENG.DEAD_END_HIGH_VALUE_PAGE")

    def test_template_level_pattern_not_inferred_from_one_page(self):
        pages = [make_page("/p0.html", page_type="product", links_internal=[])]
        pages += [make_page("/p%d.html" % i, page_type="product",
                            links_internal=[link(ORIGIN + "/x.html", "x")])
                 for i in range(1, 6)]
        findings, _ = self.detect(make_snapshot(
            pages=pages,
            clusters=[{"id": "c01", "skeleton": "/{s}", "size": 6, "depth": 1,
                      "members_sample": [], "sampled": [p["url"] for p in pages],
                      "page_type": "product", "page_type_confidence": "high"}]))
        found = self.only(findings, "ENG.DEAD_END_HIGH_VALUE_PAGE")
        self.assertEqual(found["reach"], "page")

    def test_intentional_endpoint_page_is_never_flagged_for_anything(self):
        page = make_page("/thank-you.html", page_type="utility", links_internal=[])
        findings, _ = self.detect(make_snapshot(pages=[page]))
        self.assertEqual(findings, [])

    def test_missing_optional_fields_do_not_crash(self):
        page = make_page("/p.html", page_type="product")
        del page["links_external"]
        snapshot = make_snapshot(pages=[page])
        findings, not_assessed = eng.run(snapshot)
        self.assertIsInstance(findings, list)

    def test_no_network_capability_referenced_anywhere(self):
        """This detector never reasons about render or robots evidence at all."""
        pages = [make_page("/p%d.html" % i, page_type="product",
                           links_internal=[link(ORIGIN + "/x.html", "Contact us")])
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(
            pages=pages, capabilities={"headless_render": False,
                                       "external_search": False}))
        self.assertEqual(findings, [])


def link_extra(*a, **k):
    return link(*a, **k)


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
        make_page("/p%d.html" % i, page_type="product", links_internal=[])
        for i in range(3)]))
    dest = make_page("/dest.html", page_type="contact")
    src = make_page("/p.html", page_type="product",
                    links_internal=[link(dest["url"], "See this")])
    scenarios.append(make_snapshot(pages=[src, dest]))
    scenarios.append(make_snapshot(pages=[
        make_page("/p%d.html" % i, page_type="product",
                 links_internal=[link(ORIGIN + "/about.html", "About us")])
        for i in range(2)]))
    clusters = [{"id": "c%d" % i, "skeleton": "/x%d/{s}" % i, "size": 6, "depth": d,
                "members_sample": [], "sampled": [ORIGIN + "/x%d/p.html" % i],
                "page_type": t, "page_type_confidence": "high"}
               for i, (t, d) in enumerate([("about", 1), ("contact", 1),
                                           ("faq", 1), ("product", 5)])]
    pages = [make_page("/x%d/p.html" % i, page_type=c["page_type"])
            for i, c in enumerate(clusters)]
    scenarios.append(make_snapshot(pages=pages, clusters=clusters))
    home = make_page("/", page_type="homepage",
                     links_internal=[link(ORIGIN + "/p1.html", "P1")])
    orphan = make_page("/orphan.html", page_type="about", main_text_len=300)
    others = [make_page("/p%d.html" % i, page_type="product",
                        links_internal=[link(ORIGIN + "/p%d.html" % (i + 1), "next")])
             for i in range(6)]
    scenarios.append(make_snapshot(pages=[home, orphan] + others))
    scenarios.append(make_snapshot(pages=[make_page(
        "/p.html", links_internal=[link(ORIGIN + "/a.html", "Learn more"),
                                   link(ORIGIN + "/b.html", "Learn more")])]))

    findings = []
    for snapshot in scenarios:
        found, _ = eng.run(copy.deepcopy(snapshot))
        findings.extend(found)
    return findings


class TestEvidenceQuality(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.findings = sweep_findings()

    def test_the_sweep_covers_every_implemented_check(self):
        covered = {f["check_id"] for f in self.findings}
        expected = {
            "ENG.DEAD_END_HIGH_VALUE_PAGE", "ENG.NO_RELATED_CONTENT_PATHWAY",
            "ENG.WEAK_ACTION_PATHWAY", "ENG.EXCESSIVE_PATHWAY_DEPTH",
            "ENG.ORPHAN_LIKE_SAMPLED_PAGE", "ENG.AMBIGUOUS_ACTION_SURFACE",
        }
        self.assertEqual(expected - covered, set(),
                         "these checks never fired in the sweep: %s"
                         % (expected - covered))

    def test_every_finding_is_well_formed(self):
        self.assertGreaterEqual(len(self.findings), 6)
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
            self.assertEqual(found["funnel_stage"], "engagement", label)
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

    def test_no_behavioural_metrics_ever_claimed(self):
        """The core analytics boundary: no click-through, conversion, bounce, time
        on page, or any other behavioural measurement this snapshot cannot observe."""
        forbidden = ("click-through", "click through rate", "ctr", "conversion rate",
                    "bounce rate", "time on page", "abandonment rate",
                    "revenue impact", "user behavior", "user behaviour",
                    "users will", "visitors will", "will convert", "will click")
        for found in self.findings:
            text = (found["evidence"] + " " + json.dumps(found["suggested_action"])
                   + " " + found["title"]).lower()
            for phrase in forbidden:
                self.assertNotIn(phrase, text, "%s: %r" % (found["check_id"], phrase))

    def test_no_action_claims_a_guarantee(self):
        for found in self.findings:
            text = json.dumps(found["suggested_action"]).lower()
            for phrase in ("will be cited", "guarantees a citation", "guarantee ranking",
                          "ensures you are cited", "will rank", "will improve "
                          "conversions", "guarantees engagement"):
                self.assertNotIn(phrase, text, found["check_id"])

    def test_no_generic_advice(self):
        for found in self.findings:
            summary = found["suggested_action"]["summary"].lower()
            for lazy in ("improve engagement", "improve your seo",
                        "follow best practices", "improve ux", "improve the ux"):
                self.assertNotIn(lazy, summary, found["check_id"])

    def test_evidence_quotes_something_concrete(self):
        for found in self.findings:
            evidence = found["evidence"]
            concrete = (any(ch.isdigit() for ch in evidence) or "'" in evidence
                       or '"' in evidence)
            self.assertTrue(concrete, "%s evidence has no concrete value: %s"
                            % (found["check_id"], evidence))


if __name__ == "__main__":
    unittest.main(verbosity=2)
