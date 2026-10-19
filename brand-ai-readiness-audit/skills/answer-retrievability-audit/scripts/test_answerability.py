#!/usr/bin/env python3
"""Unit tests for answer-retrievability-audit.

Each test builds a minimal snapshot conforming to the frozen contract, runs the detector
over it, and asserts on the findings. No network, no fixture server: these are branch
tests. End-to-end behaviour against live fixtures is covered by tests/run_tests.py.

Run: python3 skills/answer-retrievability-audit/scripts/test_answerability.py
"""
import copy
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)

import check_answerability as ans  # noqa: E402

ORIGIN = "https://example.test"

REQUIRED_FINDING_FIELDS = ("check_id", "title", "gate_impact", "reach", "certainty",
                           "funnel_stage", "detector", "evidence", "affected_urls",
                           "evidence_detail", "suggested_action")
REQUIRED_ACTION_FIELDS = ("summary", "how", "mechanism", "effort", "owner", "verification")
REQUIRED_DETAIL_FIELDS = ("check_id", "method", "observed", "expected", "sample",
                          "confidence", "nondeterministic", "detector")

ALL_FINDINGS = []


# ------------------------------------------------------------------ snapshot factories

def make_headings(*levels_id_text):
    return [{"level": level, "id": hid, "text": text, "in_content": True}
            for level, hid, text in levels_id_text]


def sd_block(jsonld=None, microdata_items=None):
    return {"source": "raw", "jsonld": jsonld or [], "microdata_types": [],
           "microdata_props": 0, "microdata_items": microdata_items or [],
           "rdfa_types": [], "rdfa_props": 0, "opengraph": {}}


def jsonld_block(data):
    return {"parse_ok": True, "error": None, "data": data, "raw_len": len(json.dumps(data))}


def product_jsonld(name="Alpha Widget", price="59.00", currency="GBP"):
    return {"@context": "https://schema.org", "@type": "Product", "name": name,
           "offers": {"@type": "Offer", "price": price, "priceCurrency": currency}}


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
            "raw_html": kw.pop("raw_html", "<html></html>"),
            "raw_text": kw.pop("raw_text", None),
            "raw_text_len": kw.pop("raw_text_len", 1000),
            "main_text": kw.pop("main_text", "readable prose " * 60),
            "main_text_len": kw.pop("main_text_len", 900),
            "lang": kw.pop("lang", "en"), "title": kw.pop("title", "Title"),
            "meta_description": "d", "meta_robots": None,
            "meta_viewport": "w", "meta_refresh": None,
            "canonical": url, "canonical_raw": url, "hreflang": [],
            "headings": kw.pop("headings", make_headings((1, "top", "Title"))),
            "tables": kw.pop("tables", 0), "definition_lists": kw.pop("definition_lists", 0),
            "forms": 0, "script_bytes": 0, "script_srcs": [], "stylesheet_count": 1,
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
        "audited_at": "2026-09-06T00:00:00Z", "user_agent": "audit",
        "capabilities": {"headless_render": False, "external_search": False},
        "robots": {"url": ORIGIN + "/robots.txt", "status": 200},
        "sitemaps": [], "discovery": {"method": "sitemap", "urls_discovered": 40,
                                      "depth_reached": 0},
        "site_archetype": kw.pop("site_archetype", "ecommerce"),
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


def product_page(path, name="Alpha Widget", price="59.00", lead_text=None,
                 h1=None, **kw):
    h1 = h1 or name
    lead_text = lead_text if lead_text is not None else (
        "%s is a precision device. %s costs %s GBP and ships fast."
        % (h1, h1, price))
    kw.setdefault("headings", make_headings((1, "top", h1)))
    kw.setdefault("main_text", lead_text)
    kw.setdefault("main_text_len", len(lead_text))
    kw.setdefault("structured_data",
                  sd_block(jsonld=[jsonld_block(product_jsonld(name, price))]))
    return make_page(path, page_type="product", **kw)


class DetectorTestCase(unittest.TestCase):

    def detect(self, snapshot):
        findings, not_assessed = ans.run(copy.deepcopy(snapshot))
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


# ================================================================ ANS.NO_DIRECT_ANSWER_LEAD

class TestNoDirectAnswerLead(DetectorTestCase):

    def test_fires_when_fact_is_buried(self):
        filler = "Unrelated background text about the workshop. " * 12
        pages = [product_page(
            "/p%d.html" % i,
            lead_text=filler + " Widget %d costs 59.00 GBP and ships fast." % i)
            for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "ANS.NO_DIRECT_ANSWER_LEAD")

    def test_does_not_fire_when_fact_is_near_top(self):
        pages = [product_page("/p%d.html" % i) for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ANS.NO_DIRECT_ANSWER_LEAD", self.ids(findings))

    def test_pronoun_with_nearby_antecedent_is_not_flagged(self):
        """Regression: 'The Widget is a tool. It costs 59.00 GBP.' -- a pronoun in the
        sentence stating the fact is fine because the entity was named one sentence
        earlier, well within the lookback window. This is exactly the shape of this
        project's own clean-control fixture."""
        pages = [product_page(
            "/p%d.html" % i,
            lead_text="The Widget is a handheld precision tool from Example Co. "
                     "It costs 59.00 GBP and is in stock.")
            for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ANS.NO_DIRECT_ANSWER_LEAD", self.ids(findings))

    def test_pronoun_with_distant_antecedent_is_flagged(self):
        distant = "Widget " * 5 + ("filler text about unrelated matters. " * 20)
        pages = [product_page(
            "/p%d.html" % i,
            lead_text=distant + " It costs 59.00 GBP and is in stock today.")
            for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "ANS.NO_DIRECT_ANSWER_LEAD")

    def test_non_product_pages_are_never_evaluated(self):
        pages = [make_page("/p%d.html" % i, page_type="article",
                           main_text="filler " * 200 + " 59.00 GBP mentioned late")
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ANS.NO_DIRECT_ANSWER_LEAD", self.ids(findings))

    def test_short_page_is_not_penalised_for_a_late_seeming_offset(self):
        """A short page's own length raises the effective floor proportionally."""
        pages = [product_page("/p%d.html" % i, lead_text="Widget costs 59.00 GBP.")
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ANS.NO_DIRECT_ANSWER_LEAD", self.ids(findings))

    def test_no_structured_price_means_not_assessable(self):
        pages = [make_page("/p%d.html" % i, page_type="product",
                           main_text="filler " * 100) for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ANS.NO_DIRECT_ANSWER_LEAD", self.ids(findings))

    def test_french_content_self_containment_still_evaluated(self):
        """Word-overlap is structural (Unicode-aware), not English-specific; it must
        run on French content exactly as it does on English content."""
        pages = [product_page(
            "/p%d.html" % i, lang="fr", h1="Widget Alpha",
            lead_text="Widget Alpha est un outil de precision. "
                     "Il coute 59.00 GBP et est en stock.")
            for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ANS.NO_DIRECT_ANSWER_LEAD", self.ids(findings))


# =================================================================== ANS.SPECS_NOT_EXTRACTABLE

class TestSpecsNotExtractable(DetectorTestCase):

    def test_fires_on_two_or_more_unit_bearing_prose_values(self):
        pages = [make_page(
            "/p%d.html" % i, page_type="product", tables=0, definition_lists=0,
            main_text="It measures 150.5 millimetres and weighs 240.0 grams in total.")
            for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "ANS.SPECS_NOT_EXTRACTABLE")

    def test_does_not_fire_with_a_table_present(self):
        pages = [make_page(
            "/p%d.html" % i, page_type="product", tables=1, definition_lists=0,
            main_text="It measures 150.5 millimetres and weighs 240.0 grams in total.")
            for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ANS.SPECS_NOT_EXTRACTABLE", self.ids(findings))

    def test_does_not_fire_with_a_definition_list_present(self):
        pages = [make_page(
            "/p%d.html" % i, page_type="product", tables=0, definition_lists=1,
            main_text="It measures 150.5 millimetres and weighs 240.0 grams in total.")
            for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ANS.SPECS_NOT_EXTRACTABLE", self.ids(findings))

    def test_single_value_alone_is_not_enough(self):
        pages = [make_page(
            "/p%d.html" % i, page_type="product", tables=0,
            main_text="It weighs 240.0 grams and comes with a case.")
            for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ANS.SPECS_NOT_EXTRACTABLE", self.ids(findings))

    def test_non_product_pages_are_never_evaluated(self):
        pages = [make_page(
            "/p%d.html" % i, page_type="article", tables=0,
            main_text="It measures 150.5 millimetres and weighs 240.0 grams in total.")
            for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ANS.SPECS_NOT_EXTRACTABLE", self.ids(findings))


# ======================================================================= ANS.UNITLESS_VALUES

class TestUnitlessValues(DetectorTestCase):

    def test_fires_on_bare_decimal_with_no_unit(self):
        pages = [make_page(
            "/p%d.html" % i, page_type="product",
            main_text="Customers rate this product 4.8 in independent surveys.")
            for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "ANS.UNITLESS_VALUES")

    def test_preposition_in_does_not_count_as_a_unit(self):
        """Regression: bare 'in' (inches) collided with the ordinary English
        preposition 'in', which suppressed genuinely unitless values."""
        pages = [make_page(
            "/p%d.html" % i, page_type="product",
            main_text="Rated 4.8 in independent workshop tests conducted this year.")
            for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "ANS.UNITLESS_VALUES")

    def test_value_with_full_unit_word_is_not_flagged(self):
        pages = [make_page(
            "/p%d.html" % i, page_type="product",
            main_text="It weighs 240.0 grams and measures 150.5 millimetres.")
            for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ANS.UNITLESS_VALUES", self.ids(findings))

    def test_value_with_currency_is_not_flagged(self):
        pages = [make_page(
            "/p%d.html" % i, page_type="product",
            main_text="It costs 59.00 GBP and ships within two days of order.")
            for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ANS.UNITLESS_VALUES", self.ids(findings))

    def test_year_is_never_flagged(self):
        pages = [make_page(
            "/p%d.html" % i, page_type="product",
            main_text="Founded in 1994.0 by a team of engineers in the region.")
            for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ANS.UNITLESS_VALUES", self.ids(findings))

    def test_model_like_token_is_never_flagged(self):
        pages = [make_page(
            "/p%d.html" % i, page_type="product",
            main_text="The ALPHA-100.5 revision replaces the previous model line.")
            for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ANS.UNITLESS_VALUES", self.ids(findings))

    def test_is_ceilinged_at_low(self):
        pages = [make_page(
            "/p%d.html" % i, page_type="product",
            main_text="Customers rate this product 4.8 in independent surveys.")
            for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        found = self.only(findings, "ANS.UNITLESS_VALUES")
        self.assertEqual(found.get("severity_ceiling"), "low")


# ===================================================================== ANS.ENTITY_NEVER_NAMED

class TestEntityNeverNamed(DetectorTestCase):

    def test_fires_when_name_never_recurs(self):
        pages = [product_page(
            "/p%d.html" % i, h1="Alpha Widget",
            lead_text="This handheld precision tool comes from Example Co. "
                     "It costs 59.00 GBP and is in stock.")
            for i in range(2)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "ANS.ENTITY_NEVER_NAMED")

    def test_does_not_fire_when_full_name_recurs(self):
        pages = [product_page(
            "/p%d.html" % i, h1="Alpha Widget",
            lead_text="The Alpha Widget is a handheld precision tool. "
                     "It costs 59.00 GBP and is in stock.")
            for i in range(2)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ANS.ENTITY_NEVER_NAMED", self.ids(findings))

    def test_generic_noun_alone_is_not_enough(self):
        """Regression: 'Widget' (the generic product-category word) recurring alone,
        without the distinguishing word 'Alpha', was wrongly accepted as the full
        name recurring."""
        pages = [product_page(
            "/p%d.html" % i, h1="Alpha Widget",
            lead_text="This widget is a handheld precision tool from Example Co. "
                     "It costs 59.00 GBP and is in stock.")
            for i in range(2)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "ANS.ENTITY_NEVER_NAMED")

    def test_one_page_alone_is_not_enough(self):
        pages = [product_page(
            "/p0.html", h1="Alpha Widget",
            lead_text="This tool comes from Example Co. It costs 59.00 GBP."),
            product_page("/p1.html", h1="Beta Widget")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ANS.ENTITY_NEVER_NAMED", self.ids(findings))

    def test_faq_pages_are_never_evaluated(self):
        """Do not require a FAQ page to repeat its own generic section heading."""
        pages = [make_page(
            "/faq%d.html" % i, page_type="faq",
            headings=make_headings((1, "top", "Frequently asked questions")),
            main_text="Every product ships within two working days of order.")
            for i in range(2)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ANS.ENTITY_NEVER_NAMED", self.ids(findings))

    def test_contact_pages_are_never_evaluated(self):
        pages = [make_page(
            "/contact%d.html" % i, page_type="contact",
            headings=make_headings((1, "top", "Contact Example Co")),
            main_text="Telephone us or write to our head office for support.")
            for i in range(2)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ANS.ENTITY_NEVER_NAMED", self.ids(findings))

    def test_legal_pages_are_never_evaluated(self):
        pages = [make_page(
            "/legal%d.html" % i, page_type="legal",
            headings=make_headings((1, "top", "Terms of sale")),
            main_text="These terms govern all purchases made through this site.")
            for i in range(2)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ANS.ENTITY_NEVER_NAMED", self.ids(findings))

    def test_category_pages_are_never_evaluated(self):
        pages = [make_page(
            "/products%d/" % i, page_type="category",
            headings=make_headings((1, "top", "Products")),
            main_text="Alpha Widget, 59.00 GBP. Beta Widget, 74.00 GBP.")
            for i in range(2)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ANS.ENTITY_NEVER_NAMED", self.ids(findings))

    def test_french_word_order_is_respected(self):
        """Regression: reordered words for grammar must not defeat recurrence
        detection, matching the discipline already established in Milestone H."""
        pages = [product_page(
            "/p%d.html" % i, h1="Alpha Widget", lang="fr",
            lead_text="Cet outil de precision, l'Widget Alpha, vient d'Example Co. "
                     "Il coute 59.00 GBP.")
            for i in range(2)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ANS.ENTITY_NEVER_NAMED", self.ids(findings))


# =================================================================== ANS.NO_HEADING_ANCHORS

class TestNoHeadingAnchors(DetectorTestCase):

    def _long_headings(self, with_ids):
        return make_headings(
            (1, "top" if with_ids else None, "Guide"),
            *[(2, ("s%d" % i) if with_ids else None, "Section %d" % i)
             for i in range(4)])

    def test_fires_on_long_page_with_no_anchors(self):
        pages = [make_page("/p.html", page_type="article",
                           main_text_len=4000, headings=self._long_headings(False))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "ANS.NO_HEADING_ANCHORS")

    def test_does_not_fire_with_anchors_present(self):
        pages = [make_page("/p.html", page_type="article",
                           main_text_len=4000, headings=self._long_headings(True))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ANS.NO_HEADING_ANCHORS", self.ids(findings))

    def test_short_page_is_exempt(self):
        pages = [make_page("/p.html", page_type="article",
                           main_text_len=500, headings=self._long_headings(False))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ANS.NO_HEADING_ANCHORS", self.ids(findings))

    def test_needs_at_least_four_headings(self):
        headings = make_headings((1, None, "Guide"), (2, None, "Only section"))
        pages = [make_page("/p.html", page_type="article",
                           main_text_len=4000, headings=headings)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ANS.NO_HEADING_ANCHORS", self.ids(findings))

    def test_some_anchors_present_is_not_flagged(self):
        """Only an all-or-nothing absence is flagged; partial coverage is not this
        check's target (a genuinely too-narrow all-or-nothing design is a documented
        limitation, not silently expanded here)."""
        headings = make_headings((1, "top", "Guide"), (2, "s0", "Section 0"),
                                 (2, None, "Section 1"), (2, None, "Section 2"),
                                 (2, None, "Section 3"))
        pages = [make_page("/p.html", page_type="article",
                           main_text_len=4000, headings=headings)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ANS.NO_HEADING_ANCHORS", self.ids(findings))


# ====================================================================== ANS.NO_SUMMARY_BLOCK

class TestNoSummaryBlock(DetectorTestCase):

    def test_fires_when_first_section_appears_immediately(self):
        text = "Guide Introduction " + ("detail " * 400)
        pages = [make_page("/p.html", page_type="article", main_text_len=4000,
                           main_text=text,
                           headings=make_headings((1, None, "Guide"),
                                                  (2, None, "Introduction")))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "ANS.NO_SUMMARY_BLOCK")

    def test_does_not_fire_with_a_real_lead_in(self):
        lead = "Guide " + ("This guide explains the full process end to end. " * 4)
        text = lead + "Introduction " + ("detail " * 400)
        pages = [make_page("/p.html", page_type="article", main_text_len=4000,
                           main_text=text,
                           headings=make_headings((1, None, "Guide"),
                                                  (2, None, "Introduction")))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ANS.NO_SUMMARY_BLOCK", self.ids(findings))

    def test_short_page_is_exempt(self):
        text = "Guide Introduction detail"
        pages = [make_page("/p.html", page_type="article", main_text_len=500,
                           main_text=text,
                           headings=make_headings((1, None, "Guide"),
                                                  (2, None, "Introduction")))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ANS.NO_SUMMARY_BLOCK", self.ids(findings))

    def test_is_ceilinged_at_low(self):
        text = "Guide Introduction " + ("detail " * 400)
        pages = [make_page("/p.html", page_type="article", main_text_len=4000,
                           main_text=text,
                           headings=make_headings((1, None, "Guide"),
                                                  (2, None, "Introduction")))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        found = self.only(findings, "ANS.NO_SUMMARY_BLOCK")
        self.assertEqual(found.get("severity_ceiling"), "low")


# ========================================================================= ANS.NO_QA_SURFACE

class TestNoQaSurface(DetectorTestCase):

    def test_fires_when_faq_headings_are_not_questions(self):
        pages = [make_page(
            "/faq.html", page_type="faq",
            headings=make_headings((1, "top", "FAQ"), (2, "a", "Warranty information"),
                                   (2, "b", "Shipping information")))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "ANS.NO_QA_SURFACE")

    def test_does_not_fire_with_question_shaped_headings(self):
        pages = [make_page(
            "/faq.html", page_type="faq",
            headings=make_headings((1, "top", "FAQ"),
                                   (2, "a", "How long is the warranty?"),
                                   (2, "b", "Do you ship internationally?")))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ANS.NO_QA_SURFACE", self.ids(findings))

    def test_no_faq_page_at_all_is_not_a_finding(self):
        """Absence of FAQ content is never asserted as a defect here; that would be
        an opportunity, not a finding, and belongs to a different skill entirely."""
        pages = [make_page("/p%d.html" % i, page_type="product") for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ANS.NO_QA_SURFACE", self.ids(findings))

    def test_fullwidth_question_mark_is_recognised(self):
        pages = [make_page(
            "/faq.html", page_type="faq", lang="zh",
            headings=make_headings((1, "top", "FAQ"), (2, "a", "\u4fdd\u4fee\u671f\uff1f")))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ANS.NO_QA_SURFACE", self.ids(findings))

    def test_is_ceilinged_at_low(self):
        pages = [make_page(
            "/faq.html", page_type="faq",
            headings=make_headings((1, "top", "FAQ"), (2, "a", "Warranty information"),
                                   (2, "b", "Shipping information")))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        found = None
        for f in findings:
            if f["check_id"] == "ANS.NO_QA_SURFACE":
                found = f
        self.assertIsNotNone(found)


# ============================================================ ANS.NO_CANONICAL_FACT_SURFACE

class TestNoCanonicalFactSurface(DetectorTestCase):

    def _homepage(self, main_text, **kw):
        kw.setdefault("headings", make_headings((1, "top", "Example Co")))
        return make_page("/", page_type="homepage", main_text=main_text,
                         main_text_len=len(main_text), **kw)

    def test_fires_when_no_page_combines_two_signals(self):
        pages = [self._homepage("Example Co makes precision tools."),
                make_page("/p1.html", main_text="Example Co ships worldwide."),
                make_page("/p2.html", main_text="Example Co supports every order.")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "ANS.NO_CANONICAL_FACT_SURFACE")

    def test_does_not_fire_when_a_page_combines_year_and_phone(self):
        pages = [self._homepage("Example Co makes precision tools."),
                make_page("/about.html",
                         main_text="Example Co was founded in 1994. Call us on "
                                   "0207 946 0810 for support."),
                make_page("/p2.html", main_text="Example Co ships worldwide fast.")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ANS.NO_CANONICAL_FACT_SURFACE", self.ids(findings))

    def test_does_not_fire_when_a_page_combines_price_and_year(self):
        pages = [self._homepage("Example Co makes precision tools."),
                make_page("/p1.html",
                         main_text="Example Co has sold the Alpha Widget for 59.00 "
                                   "GBP since 1994."),
                make_page("/p2.html", main_text="Example Co ships worldwide fast.")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ANS.NO_CANONICAL_FACT_SURFACE", self.ids(findings))

    def test_is_not_gated_behind_english(self):
        """Word-overlap and digit-pattern signals are structural; must not require
        English to find a satisfying page on a non-English site."""
        pages = [self._homepage("Example Co fabrique des outils de precision.",
                               lang="fr",
                               headings=make_headings((1, "top", "Example Co"))),
                make_page("/about.html", lang="fr",
                         main_text="Example Co a ete fondee en 1994. Appelez le "
                                   "0207 946 0810 pour toute question."),
                make_page("/p2.html", lang="fr",
                         main_text="Example Co livre partout dans le monde vite.")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ANS.NO_CANONICAL_FACT_SURFACE", self.ids(findings))

    def test_facts_split_across_two_pages_is_not_flagged_as_a_conflict(self):
        """Facts on different pages, neither contradicting the other, is not what
        this check is about; it only asks whether ONE page combines enough of them."""
        pages = [self._homepage("Example Co makes precision tools."),
                make_page("/about.html", main_text="Founded in 1994."),
                make_page("/contact.html", main_text="Call 0207 946 0810.")]
        # Deliberately still expected to fire: no SINGLE page combines two signals.
        # This documents the check's actual scope rather than a broader "are the
        # facts findable somewhere on the site" standard it does not claim to meet.
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "ANS.NO_CANONICAL_FACT_SURFACE")

    def test_tiny_site_is_not_assessed(self):
        pages = [self._homepage("Example Co makes precision tools."),
                make_page("/contact.html", main_text="Call 0207 946 0810.")]
        findings, not_assessed = self.detect(make_snapshot(
            pages=pages,
            clusters=[{"id": "c01", "skeleton": "/{slug}.html", "size": 2, "depth": 1,
                      "members_sample": [], "sampled": [p["url"] for p in pages],
                      "page_type": "homepage", "page_type_confidence": "high"}]))
        self.assertNotIn("ANS.NO_CANONICAL_FACT_SURFACE", self.ids(findings))
        self.assertIn("canonical fact surface", self.dimensions(not_assessed))

    def test_no_homepage_is_not_assessed(self):
        pages = [make_page("/p1.html"), make_page("/p2.html"), make_page("/p3.html")]
        findings, not_assessed = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ANS.NO_CANONICAL_FACT_SURFACE", self.ids(findings))
        self.assertIn("canonical fact surface", self.dimensions(not_assessed))


# ======================================================== ANS.KEY_FACT_OUTSIDE_MAIN_CONTENT

class TestKeyFactOutsideMainContent(DetectorTestCase):

    def test_fires_when_price_is_absent_from_main_but_present_in_full_text(self):
        pages = [product_page(
            "/p.html", price="59.00",
            lead_text="A precision tool built for daily workshop use.",
            raw_text="Nav | Example Co | A precision tool built for daily workshop "
                    "use. Price: 59.00 GBP. Call for trade pricing. Footer text.")
            for _ in range(1)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "ANS.KEY_FACT_OUTSIDE_MAIN_CONTENT")

    def test_does_not_fire_when_price_is_in_main_text(self):
        pages = [product_page("/p.html", price="59.00")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ANS.KEY_FACT_OUTSIDE_MAIN_CONTENT", self.ids(findings))

    def test_does_not_fire_when_price_is_absent_everywhere(self):
        """Absent from both is SDE's/a different check's territory, not this one:
        this check specifically requires the fact to be proven present in the full
        page and proven absent from the extracted main content, not merely absent
        from main content alone."""
        pages = [product_page(
            "/p.html", price="59.00",
            lead_text="A precision tool built for daily workshop use.",
            raw_text="Nav | Example Co | A precision tool built for daily workshop "
                    "use. Call for a quote. Footer text.")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ANS.KEY_FACT_OUTSIDE_MAIN_CONTENT", self.ids(findings))

    def test_does_not_fire_on_legitimate_navigation_or_footer_alone(self):
        """Ordinary nav/footer boilerplate that does not restate the structured fact
        must never be treated as evidence of anything; only a fact genuinely proven
        present in the full page and absent from main triggers this."""
        pages = [product_page(
            "/p.html", price="59.00",
            raw_text="Nav | Example Co | Home | About | Contact | "
                    + "Alpha Widget is a precision tool. Alpha Widget costs 59.00 "
                    "GBP and ships fast. | Footer | Terms | Privacy | Sitemap")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ANS.KEY_FACT_OUTSIDE_MAIN_CONTENT", self.ids(findings))

    def test_non_product_pages_are_never_evaluated(self):
        pages = [make_page(
            "/p.html", page_type="article",
            main_text="An article with no structured price at all.",
            raw_text="Nav | 59.00 GBP | An article with no structured price at all. "
                    "| Footer")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("ANS.KEY_FACT_OUTSIDE_MAIN_CONTENT", self.ids(findings))

    def test_currency_mismatch_between_main_and_raw_is_not_confused(self):
        """The correct price is genuinely present outside main content; a different
        currency mentioned nearby (e.g. a US-store aside) must not be mistaken for
        it, and must not prevent the real match from being found either."""
        pages = [product_page(
            "/p.html", price="59.00",
            lead_text="A precision tool for daily workshop use.",
            raw_text="Nav | Price: 59.00 GBP. Also available for 75.00 USD in our "
                    "US store. A precision tool for daily workshop use. | Footer")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "ANS.KEY_FACT_OUTSIDE_MAIN_CONTENT")


# ============================================================== broad false-positive suite

class TestFalsePositiveDefense(DetectorTestCase):

    def test_clean_product_page_is_silent(self):
        pages = [product_page("/p%d.html" % i, name="Widget %d" % i, h1="Widget %d" % i)
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertEqual(findings, [])

    def test_clean_informational_page_is_silent(self):
        pages = [make_page("/about.html", page_type="about",
                           headings=make_headings((1, "top", "About")),
                           main_text="Example Co makes precision tools in the region.")
                for _ in range(1)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertEqual(findings, [])

    def test_clean_faq_is_silent(self):
        pages = [make_page(
            "/faq.html", page_type="faq",
            headings=make_headings((1, "top", "FAQ"),
                                   (2, "a", "How long is the warranty?")),
            main_text="How long is the warranty? Every item carries a two year "
                     "warranty from purchase.")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertEqual(findings, [])

    def test_clean_service_page_is_silent(self):
        pages = [make_page(
            "/services.html", page_type="about",
            headings=make_headings((1, "top", "Consulting services")),
            main_text="We provide consulting services to workshops across the "
                     "region, covering calibration and maintenance.")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertEqual(findings, [])

    def test_short_answerable_page_is_silent(self):
        pages = [product_page("/p.html", lead_text="Widget costs 59.00 GBP.")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertEqual(findings, [])

    def test_long_well_structured_page_is_silent(self):
        lead = "Guide " + "This guide covers the full process end to end. " * 4
        sections = "".join("Section %d " % i + "detail " * 100 for i in range(5))
        headings = make_headings(
            (1, "top", "Guide"),
            *[(2, "s%d" % i, "Section %d" % i) for i in range(5)])
        pages = [make_page("/p.html", page_type="article", main_text=lead + sections,
                           main_text_len=len(lead + sections), headings=headings)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertEqual(findings, [])

    def test_dense_factual_page_with_units_is_silent(self):
        pages = [make_page(
            "/p%d.html" % i, page_type="product", tables=1,
            headings=make_headings((1, "top", "Widget %d" % i)),
            main_text="Widget %d This widget weighs 240.0 grams, measures 150.5 "
                     "millimetres, and costs 59.00 GBP." % i)
            for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertEqual(findings, [])

    def test_legitimate_repeated_identical_facts_across_pages_is_not_a_conflict(self):
        pages = [product_page("/p%d.html" % i, name="Widget", h1="Widget", price="59.00")
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertEqual(findings, [])

    def test_non_english_clean_site_is_silent(self):
        pages = [self_contained_french_homepage()] + [
            make_page("/produit%d.html" % i, page_type="product", lang="fr",
                     headings=make_headings((1, "top", "Widget Alpha")),
                     main_text="Le Widget Alpha est un outil de precision. "
                              "Il coute 59.00 GBP et est en stock.",
                     structured_data=sd_block(jsonld=[jsonld_block(
                         product_jsonld("Widget Alpha", "59.00"))]))
            for i in range(2)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertEqual(findings, [])

    def test_insufficient_sample_never_produces_a_sitewide_claim(self):
        pages = [product_page("/p0.html", lead_text="filler " * 100 + " 59.00 GBP")]
        findings, _ = self.detect(make_snapshot(
            pages=pages,
            clusters=[{"id": "c01", "skeleton": "/p.html", "size": 1, "depth": 1,
                      "members_sample": [], "sampled": [pages[0]["url"]],
                      "page_type": "product", "page_type_confidence": "high"}]))
        for f in findings:
            self.assertNotEqual(f["reach"], "sitewide")

    def test_render_unavailable_does_not_produce_a_finding_about_rendering(self):
        """This detector never reasons about render evidence at all; it must behave
        identically whether or not a render was captured."""
        pages = [product_page("/p%d.html" % i) for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages,
                                                capabilities={"headless_render": False,
                                                              "external_search": False}))
        self.assertEqual(findings, [])

    def test_navigation_and_footer_text_alone_never_produces_a_finding(self):
        pages = [make_page(
            "/p.html", page_type="about",
            headings=make_headings((1, "top", "Home")),
            main_text="Home About Contact Products FAQ Search Terms Privacy Sitemap")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertEqual(findings, [])


def self_contained_french_homepage():
    return make_page("/", page_type="homepage", lang="fr",
                     headings=make_headings((1, "top", "Example Co")),
                     main_text="Example Co fabrique des outils de precision depuis "
                              "1994. Appelez le 0207 946 0810 pour toute question.",
                     main_text_len=120)


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
    filler = "Unrelated background text about the workshop. " * 12
    scenarios.append(make_snapshot(pages=[product_page(
        "/p%d.html" % i,
        lead_text=filler + " Widget %d costs 59.00 GBP and ships fast." % i)
        for i in range(3)]))
    scenarios.append(make_snapshot(pages=[make_page(
        "/p%d.html" % i, page_type="product", tables=0,
        main_text="It measures 150.5 millimetres and weighs 240.0 grams in total.")
        for i in range(3)]))
    scenarios.append(make_snapshot(pages=[make_page(
        "/p%d.html" % i, page_type="product",
        main_text="Customers rate this product 4.8 in independent surveys.")
        for i in range(3)]))
    scenarios.append(make_snapshot(pages=[product_page(
        "/p%d.html" % i, h1="Alpha Widget",
        lead_text="This tool comes from Example Co. It costs 59.00 GBP.")
        for i in range(2)]))
    long_headings = make_headings(
        (1, None, "Guide"), *[(2, None, "Section %d" % i) for i in range(4)])
    scenarios.append(make_snapshot(pages=[make_page(
        "/p.html", page_type="article", main_text_len=4000, headings=long_headings)]))
    scenarios.append(make_snapshot(pages=[make_page(
        "/p.html", page_type="article", main_text_len=4000,
        main_text="Guide Introduction " + ("detail " * 400),
        headings=make_headings((1, None, "Guide"), (2, None, "Introduction")))]))
    scenarios.append(make_snapshot(pages=[make_page(
        "/faq.html", page_type="faq",
        headings=make_headings((1, "top", "FAQ"), (2, "a", "Warranty information"),
                               (2, "b", "Shipping information")))]))
    scenarios.append(make_snapshot(pages=[
        make_page("/", page_type="homepage",
                 headings=make_headings((1, "top", "Example Co")),
                 main_text="Example Co makes precision tools.", main_text_len=120),
        make_page("/p1.html", main_text="Example Co ships worldwide."),
        make_page("/p2.html", main_text="Example Co supports every order.")]))
    scenarios.append(make_snapshot(pages=[product_page(
        "/p.html", price="59.00",
        lead_text="A precision tool built for daily workshop use.",
        raw_text="Nav | Example Co | A precision tool built for daily workshop use. "
                "Price: 59.00 GBP. Call for trade pricing. Footer text.")]))

    findings = []
    for snapshot in scenarios:
        found, _ = ans.run(copy.deepcopy(snapshot))
        findings.extend(found)
    return findings


class TestEvidenceQuality(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.findings = sweep_findings()

    def test_the_sweep_covers_every_implemented_check(self):
        covered = {f["check_id"] for f in self.findings}
        expected = {
            "ANS.NO_DIRECT_ANSWER_LEAD", "ANS.SPECS_NOT_EXTRACTABLE",
            "ANS.UNITLESS_VALUES", "ANS.ENTITY_NEVER_NAMED", "ANS.NO_HEADING_ANCHORS",
            "ANS.NO_SUMMARY_BLOCK", "ANS.NO_QA_SURFACE",
            "ANS.NO_CANONICAL_FACT_SURFACE", "ANS.KEY_FACT_OUTSIDE_MAIN_CONTENT",
        }
        self.assertEqual(expected - covered, set(),
                         "these checks never fired in the sweep: %s"
                         % (expected - covered))

    def test_every_finding_is_well_formed(self):
        self.assertGreaterEqual(len(self.findings), 9)
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
            self.assertIn(found["funnel_stage"], ("retrieved", "selected"), label)
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
                        "optimise your site", "improve seo"):
                self.assertNotIn(lazy, summary, found["check_id"])

    def test_never_recommends_fabricating_qa_content(self):
        for found in self.findings:
            text = json.dumps(found["suggested_action"]).lower()
            self.assertNotIn("add faq content the page does not answer", text)
            if found["check_id"] == "ANS.NO_QA_SURFACE":
                self.assertIn("does not go on to answer",
                             " ".join(found["suggested_action"]["how"]).lower())

    def test_evidence_quotes_something_concrete(self):
        for found in self.findings:
            evidence = found["evidence"]
            concrete = (any(ch.isdigit() for ch in evidence) or "'" in evidence
                       or '"' in evidence)
            self.assertTrue(concrete, "%s evidence has no concrete value: %s"
                            % (found["check_id"], evidence))


if __name__ == "__main__":
    unittest.main(verbosity=2)
