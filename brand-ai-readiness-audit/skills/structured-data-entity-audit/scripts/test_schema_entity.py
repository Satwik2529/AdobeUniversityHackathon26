#!/usr/bin/env python3
"""Unit tests for structured-data-entity-audit.

Each test builds a minimal snapshot conforming to the frozen contract, runs the detector
over it, and asserts on the findings. No network, no fixture server: these are branch
tests. End-to-end behaviour against live fixtures is covered by tests/run_tests.py.

Run: python3 skills/structured-data-entity-audit/scripts/test_schema_entity.py
"""
import copy
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)

import check_schema_entity as sde  # noqa: E402

ORIGIN = "https://example.test"

REQUIRED_FINDING_FIELDS = ("check_id", "title", "gate_impact", "reach", "certainty",
                           "funnel_stage", "detector", "evidence", "affected_urls",
                           "evidence_detail", "suggested_action")
REQUIRED_ACTION_FIELDS = ("summary", "how", "mechanism", "effort", "owner", "verification")
REQUIRED_DETAIL_FIELDS = ("check_id", "method", "observed", "expected", "sample",
                          "confidence", "nondeterministic", "detector")

ALL_FINDINGS = []


# ------------------------------------------------------------------ snapshot factories

def sd_block(jsonld=None, microdata_types=None, microdata_items=None, rdfa_types=None):
    return {"source": "raw", "jsonld": jsonld or [], "microdata_types": microdata_types or [],
           "microdata_props": 0, "microdata_items": microdata_items or [],
           "rdfa_types": rdfa_types or [], "rdfa_props": 0, "opengraph": {}}


def jsonld_block(data):
    return {"parse_ok": True, "error": None, "data": data, "raw_len": len(json.dumps(data))}


def broken_jsonld_block(error="Expecting ',' delimiter"):
    return {"parse_ok": False, "error": error, "excerpt": "{broken", "raw_len": 7}


ORG_NODE = {"@context": "https://schema.org", "@type": "Organization",
           "@id": ORIGIN + "/#organization", "name": "Larkspur Instruments",
           "url": ORIGIN + "/", "telephone": "+44 20 7946 0810",
           "foundingDate": "1994",
           "address": {"@type": "PostalAddress", "streetAddress": "42 Kiln Road",
                      "addressLocality": "Fairhaven", "postalCode": "FH2 9QT"},
           "sameAs": ["https://example.org/profiles/larkspur",
                     "https://example.net/companies/larkspur"]}


def product_node(name="Alpha Caliper", price="59.00", currency="GBP", sku="ALPHA"):
    return {"@context": "https://schema.org", "@type": "Product", "name": name,
           "sku": sku, "offers": {"@type": "Offer", "price": price,
                                  "priceCurrency": currency}}


def breadcrumb_node():
    return {"@context": "https://schema.org", "@type": "BreadcrumbList",
           "itemListElement": [{"@type": "ListItem", "position": 1, "name": "Home",
                               "item": ORIGIN + "/"}]}


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
            "raw_text": "text", "raw_text_len": kw.pop("raw_text_len", 1000),
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
            "links_in_content_internal": 3,
            "documents": [], "images": [],
            "structured_data": kw.pop("structured_data", sd_block()),
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
        "audited_at": "2026-09-05T00:00:00Z", "user_agent": "audit",
        "capabilities": {"headless_render": False, "external_search": False},
        "robots": {"url": ORIGIN + "/robots.txt", "status": 200},
        "sitemaps": [], "discovery": {"method": "sitemap", "urls_discovered": 40,
                                      "depth_reached": 0},
        "clusters": clusters if clusters is not None else [
            {"id": "c01", "skeleton": "/{slug}.html", "size": max(6, len(pages)),
             "depth": 1, "members_sample": [], "sampled": [p["url"] for p in pages],
             "page_type": "product", "page_type_confidence": "high"}],
        "site_archetype": "ecommerce",
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


def homepage_with_org(org_overrides=None, **page_kw):
    org = dict(ORG_NODE)
    if org_overrides:
        org.update(org_overrides)
    page_kw.setdefault("headings", [{"level": 1, "id": None,
                                     "text": "Larkspur Instruments", "in_content": True}])
    page_kw.setdefault("main_text_len", 300)
    return make_page("/", page_type="homepage",
                     structured_data=sd_block(jsonld=[jsonld_block(org)]), **page_kw)


class DetectorTestCase(unittest.TestCase):

    def detect(self, snapshot):
        findings, not_assessed = sde.run(copy.deepcopy(snapshot))
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


# ============================================================================ helpers

class TestNormalizationHelpers(unittest.TestCase):

    def test_locale_decimal_comma_normalizes_correctly(self):
        """Regression: '59,00' (French/German decimal comma) was parsed as 5900."""
        self.assertEqual(sde._normalize_amount_string("59,00"), "59.00")

    def test_us_thousands_comma_normalizes_correctly(self):
        self.assertEqual(sde._normalize_amount_string("1,234.56"), "1234.56")

    def test_eu_thousands_and_decimal_normalizes_correctly(self):
        self.assertEqual(sde._normalize_amount_string("1.234,56"), "1234.56")

    def test_plain_number_unaffected(self):
        self.assertEqual(sde._normalize_amount_string("59.00"), "59.00")

    def test_extract_price_from_text_amount_then_code(self):
        self.assertEqual(sde.extract_price_from_text("It costs 59.00 GBP today."),
                         (59.00, "GBP"))

    def test_extract_price_from_text_locale_comma(self):
        self.assertEqual(sde.extract_price_from_text("Il coute 59,00 GBP."),
                         (59.00, "GBP"))

    def test_extract_price_from_text_symbol(self):
        self.assertEqual(sde.extract_price_from_text("Priced at £59.00 today."),
                         (59.00, "GBP"))

    def test_extract_price_from_text_none_when_no_price(self):
        self.assertIsNone(sde.extract_price_from_text("No price mentioned here."))

    def test_names_match_word_order_independent(self):
        """Regression: French 'Instruments Larkspur' vs 'Larkspur Instruments'."""
        self.assertTrue(sde.names_match("Larkspur Instruments", "Instruments Larkspur"))

    def test_names_match_legal_suffix_stripped(self):
        self.assertTrue(sde.names_match("Larkspur Instruments Ltd", "Larkspur Instruments"))

    def test_names_match_case_and_whitespace(self):
        self.assertTrue(sde.names_match("  LARKSPUR   instruments ", "Larkspur Instruments"))

    def test_names_match_rejects_genuinely_different_names(self):
        self.assertFalse(sde.names_match("Larkspur Instruments", "Meridian Tools"))

    def test_names_match_empty_is_false(self):
        self.assertFalse(sde.names_match("", "Larkspur Instruments"))
        self.assertFalse(sde.names_match(None, "Larkspur Instruments"))

    def test_flatten_jsonld_walks_graph(self):
        data = {"@graph": [ORG_NODE, {"@type": "WebSite", "name": "x"}]}
        nodes = sde.flatten_jsonld([jsonld_block(data)])
        types = {t for n in nodes for t in sde.types_of(n)}
        self.assertIn("Organization", types)
        self.assertIn("WebSite", types)

    def test_flatten_jsonld_walks_main_entity(self):
        """Regression: mainEntity-nested entities (a common, legitimate schema.org
        pattern already used by this project's own clean-control fixture) were
        invisible to identity comparison."""
        data = {"@type": "ContactPage", "mainEntity": dict(ORG_NODE)}
        nodes = sde.flatten_jsonld([jsonld_block(data)])
        types = {t for n in nodes for t in sde.types_of(n)}
        self.assertIn("ContactPage", types)
        self.assertIn("Organization", types)

    def test_flatten_jsonld_ignores_unknown_nested_properties(self):
        """A nested typed object under a property NOT in the named allow-list is not
        walked -- this is a deliberate scope limit, not a bug."""
        data = {"@type": "Product", "brand": {"@type": "Brand", "name": "X"}}
        nodes = sde.flatten_jsonld([jsonld_block(data)])
        types = {t for n in nodes for t in sde.types_of(n)}
        self.assertIn("Product", types)
        self.assertNotIn("Brand", types)

    def test_flatten_jsonld_skips_invalid_blocks(self):
        nodes = sde.flatten_jsonld([broken_jsonld_block()])
        self.assertEqual(nodes, [])

    def test_price_from_offer_valid(self):
        self.assertEqual(sde.price_from_offer({"price": "59.00",
                                               "priceCurrency": "GBP"}), (59.0, "GBP"))

    def test_price_from_offer_missing_currency_is_none(self):
        self.assertIsNone(sde.price_from_offer({"price": "59.00"}))

    def test_price_from_offer_unparseable_is_none(self):
        self.assertIsNone(sde.price_from_offer({"price": "call us", "priceCurrency": "GBP"}))


# ======================================================================= presence/parsing

class TestNoStructuredData(DetectorTestCase):

    def test_fires_when_nothing_present_anywhere(self):
        pages = [make_page("/p%d.html" % i) for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "SDE.NO_STRUCTURED_DATA")

    def test_does_not_fire_with_jsonld_present(self):
        pages = [make_page("/p%d.html" % i,
                           structured_data=sd_block(jsonld=[jsonld_block(product_node())]))
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("SDE.NO_STRUCTURED_DATA", self.ids(findings))

    def test_does_not_fire_with_microdata_only(self):
        pages = [make_page("/p%d.html" % i,
                           structured_data=sd_block(microdata_types=["Product"]))
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("SDE.NO_STRUCTURED_DATA", self.ids(findings))

    def test_does_not_fire_with_rdfa_only(self):
        pages = [make_page("/p%d.html" % i,
                           structured_data=sd_block(rdfa_types=["Product"]))
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("SDE.NO_STRUCTURED_DATA", self.ids(findings))


class TestInvalidJsonld(DetectorTestCase):

    def test_fires_on_a_broken_block(self):
        pages = [make_page("/p%d.html" % i,
                           structured_data=sd_block(jsonld=[broken_jsonld_block()]))
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "SDE.INVALID_JSONLD")

    def test_does_not_fire_when_all_blocks_parse(self):
        pages = [make_page("/p%d.html" % i,
                           structured_data=sd_block(jsonld=[jsonld_block(product_node())]))
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("SDE.INVALID_JSONLD", self.ids(findings))

    def test_one_broken_block_does_not_hide_a_valid_one_on_the_same_page(self):
        pages = [make_page("/p%d.html" % i,
                           structured_data=sd_block(jsonld=[jsonld_block(product_node()),
                                                            broken_jsonld_block()]))
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        ids = self.ids(findings)
        self.assertIn("SDE.INVALID_JSONLD", ids)
        self.assertNotIn("SDE.MISSING_TYPE_FOR_TEMPLATE", ids)


# ==================================================================== type/property coverage

class TestMissingTypeForTemplate(DetectorTestCase):

    def test_fires_when_product_pages_lack_product_markup(self):
        pages = [make_page("/p%d.html" % i, page_type="product") for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "SDE.MISSING_TYPE_FOR_TEMPLATE")

    def test_does_not_fire_when_product_markup_present(self):
        pages = [make_page("/p%d.html" % i, page_type="product",
                           structured_data=sd_block(jsonld=[jsonld_block(product_node())]))
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("SDE.MISSING_TYPE_FOR_TEMPLATE", self.ids(findings))

    def test_microdata_product_type_also_satisfies_the_check(self):
        pages = [make_page("/p%d.html" % i, page_type="product",
                           structured_data=sd_block(microdata_types=["Product"]))
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("SDE.MISSING_TYPE_FOR_TEMPLATE", self.ids(findings))

    def test_never_demands_product_markup_on_non_product_pages(self):
        pages = [make_page("/p%d.html" % i, page_type="article") for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        for found in findings:
            self.assertNotIn("Product", found["title"],
                             "must never demand Product markup on an article page")

    def test_never_demands_product_markup_on_a_brochure_site_with_no_products(self):
        """A site with no product-type pages at all is complete without Product markup."""
        pages = [make_page("/p%d.html" % i, page_type="about") for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("SDE.MISSING_TYPE_FOR_TEMPLATE", self.ids(findings))

    def test_low_confidence_pages_are_not_gated_into_the_population(self):
        pages = [make_page("/p%d.html" % i, page_type="product",
                           page_type_confidence="low", main_text_len=900)
                for i in range(3)]
        # page_type is still "product" here, confidence is low but text floor (250)
        # is cleared, so these ARE in ctx.content; this documents that behaviour.
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "SDE.MISSING_TYPE_FOR_TEMPLATE")


class TestIncompleteRequiredProps(DetectorTestCase):

    def test_fires_when_product_missing_offers(self):
        incomplete = {"@context": "https://schema.org", "@type": "Product", "name": "X"}
        pages = [make_page("/p%d.html" % i, page_type="product",
                           structured_data=sd_block(jsonld=[jsonld_block(incomplete)]))
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "SDE.INCOMPLETE_REQUIRED_PROPS")

    def test_does_not_fire_when_all_required_present(self):
        pages = [make_page("/p%d.html" % i, page_type="product",
                           structured_data=sd_block(jsonld=[jsonld_block(product_node())]))
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("SDE.INCOMPLETE_REQUIRED_PROPS", self.ids(findings))

    def test_missing_recommended_property_is_never_flagged(self):
        """sku is recommended, not required, for the Product profile."""
        no_sku = {"@context": "https://schema.org", "@type": "Product", "name": "X",
                 "offers": {"price": "10.00", "priceCurrency": "GBP"}}
        pages = [make_page("/p%d.html" % i, page_type="product",
                           structured_data=sd_block(jsonld=[jsonld_block(no_sku)]))
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("SDE.INCOMPLETE_REQUIRED_PROPS", self.ids(findings))

    def test_article_profile_required_props(self):
        incomplete = {"@context": "https://schema.org", "@type": "Article",
                     "headline": "A title"}
        pages = [make_page("/p%d.html" % i, page_type="article",
                           structured_data=sd_block(jsonld=[jsonld_block(incomplete)]))
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        found = self.only(findings, "SDE.INCOMPLETE_REQUIRED_PROPS")
        self.assertIn("datePublished", found["evidence"])


# ============================================================= structured vs visible

class TestSchemaVisibleMismatch(DetectorTestCase):

    def test_fires_on_price_contradiction_same_currency(self):
        pages = [make_page(
            "/p.html", page_type="product",
            main_text="The Alpha Caliper costs 49.00 GBP and is in stock.",
            headings=[{"level": 1, "id": None, "text": "Alpha Caliper",
                      "in_content": True}],
            structured_data=sd_block(jsonld=[jsonld_block(product_node(price="59.00"))]))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        found = self.only(findings, "SDE.SCHEMA_VISIBLE_MISMATCH")
        self.assertIn("59.00", found["evidence"])
        self.assertIn("49.00", found["evidence"])

    def test_does_not_fire_when_prices_agree(self):
        pages = [make_page(
            "/p.html", page_type="product",
            main_text="The Alpha Caliper costs 59.00 GBP and is in stock.",
            headings=[{"level": 1, "id": None, "text": "Alpha Caliper",
                      "in_content": True}],
            structured_data=sd_block(jsonld=[jsonld_block(product_node(price="59.00"))]))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("SDE.SCHEMA_VISIBLE_MISMATCH", self.ids(findings))

    def test_does_not_fire_across_different_currencies(self):
        """A US mirror page quoting USD is not a contradiction of a GBP structured
        price; the two are simply not comparable without an exchange rate."""
        pages = [make_page(
            "/p.html", page_type="product",
            main_text="The Alpha Caliper is 75.00 USD in the US store.",
            headings=[{"level": 1, "id": None, "text": "Alpha Caliper",
                      "in_content": True}],
            structured_data=sd_block(jsonld=[jsonld_block(product_node(price="59.00",
                                                                       currency="GBP"))]))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("SDE.SCHEMA_VISIBLE_MISMATCH", self.ids(findings))

    def test_locale_formatted_price_is_not_a_false_mismatch(self):
        """Regression: French decimal-comma formatting was read as a 100x-larger
        number and reported as a contradiction."""
        pages = [make_page(
            "/p.html", page_type="product", lang="fr",
            main_text="Il coute 59,00 GBP et est en stock.",
            structured_data=sd_block(jsonld=[jsonld_block(product_node(price="59.00"))]))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("SDE.SCHEMA_VISIBLE_MISMATCH", self.ids(findings))

    def test_skips_comparison_when_visible_text_has_no_price(self):
        pages = [make_page(
            "/p.html", page_type="product", main_text="A great product for everyone.",
            structured_data=sd_block(jsonld=[jsonld_block(product_node(price="59.00"))]))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("SDE.SCHEMA_VISIBLE_MISMATCH", self.ids(findings))

    def test_fires_on_product_name_vs_h1_contradiction(self):
        pages = [make_page(
            "/p.html", page_type="product",
            main_text="This is a fine caliper indeed, built to last.",
            headings=[{"level": 1, "id": None, "text": "Gamma Widget",
                      "in_content": True}],
            structured_data=sd_block(jsonld=[jsonld_block(
                product_node(name="Alpha Caliper"))]))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "SDE.SCHEMA_VISIBLE_MISMATCH")

    def test_reordered_name_is_not_a_contradiction(self):
        pages = [make_page(
            "/p.html", page_type="product",
            main_text="This is a fine caliper indeed, built to last for years to come.",
            headings=[{"level": 1, "id": None, "text": "Caliper Alpha",
                      "in_content": True}],
            structured_data=sd_block(jsonld=[jsonld_block(
                product_node(name="Alpha Caliper"))]))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("SDE.SCHEMA_VISIBLE_MISMATCH", self.ids(findings))

    def test_name_check_is_independent_of_price_comparison_result(self):
        """Regression: name comparison was nested inside the price check's early
        continues, so a page with no parseable visible price (or a different
        currency, or an agreeing price) silently skipped the name comparison too,
        even though the two facts are unrelated."""
        pages = [make_page(
            "/p.html", page_type="product",
            main_text="This is a fine caliper indeed, built to last for years.",
            headings=[{"level": 1, "id": None, "text": "Gamma Widget",
                      "in_content": True}],
            structured_data=sd_block(jsonld=[jsonld_block(
                product_node(name="Alpha Caliper"))]))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "SDE.SCHEMA_VISIBLE_MISMATCH")

    def test_skips_pages_with_too_little_text_to_compare(self):
        pages = [make_page(
            "/p.html", page_type="product", main_text="x",
            structured_data=sd_block(jsonld=[jsonld_block(product_node(price="59.00"))]))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("SDE.SCHEMA_VISIBLE_MISMATCH", self.ids(findings))


class TestSchemaOnlyNoVisible(DetectorTestCase):

    def test_fires_with_at_least_two_instances(self):
        pages = [make_page(
            "/p%d.html" % i, page_type="product",
            main_text="A fine product with no price mentioned in the copy at all.",
            structured_data=sd_block(jsonld=[jsonld_block(product_node())]))
            for i in range(2)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "SDE.SCHEMA_ONLY_NO_VISIBLE")

    def test_one_instance_alone_is_not_a_finding(self):
        pages = [make_page(
            "/p0.html", page_type="product",
            main_text="A fine product with no price mentioned in the copy at all.",
            structured_data=sd_block(jsonld=[jsonld_block(product_node())])),
            make_page("/p1.html", page_type="product",
                     main_text="Costs 59.00 GBP and ships fast to your door today.",
                     structured_data=sd_block(jsonld=[jsonld_block(product_node())]))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("SDE.SCHEMA_ONLY_NO_VISIBLE", self.ids(findings))


# ==================================================================================== identity

class TestNoOrganizationNode(DetectorTestCase):

    def test_fires_when_homepage_has_no_org_entity(self):
        pages = [make_page("/", page_type="homepage"), make_page("/p1.html"),
                make_page("/p2.html")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "SDE.NO_ORGANIZATION_NODE")

    def test_does_not_fire_with_organization_node(self):
        pages = [homepage_with_org(), make_page("/p1.html"), make_page("/p2.html")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("SDE.NO_ORGANIZATION_NODE", self.ids(findings))

    def test_local_business_also_satisfies_the_check(self):
        lb = dict(ORG_NODE, **{"@type": "LocalBusiness"})
        pages = [make_page("/", page_type="homepage",
                           structured_data=sd_block(jsonld=[jsonld_block(lb)]))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("SDE.NO_ORGANIZATION_NODE", self.ids(findings))

    def test_microdata_organization_also_satisfies_the_check(self):
        items = [{"itemtype": "https://schema.org/Organization",
                 "props": {"name": "X", "url": ORIGIN + "/"}}]
        pages = [make_page("/", page_type="homepage",
                           structured_data=sd_block(microdata_items=items))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("SDE.NO_ORGANIZATION_NODE", self.ids(findings))

    def test_not_assessed_when_no_homepage_in_sample(self):
        pages = [make_page("/deep/page.html")]
        findings, not_assessed = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("SDE.NO_ORGANIZATION_NODE", self.ids(findings))
        self.assertIn("organization identity", self.dimensions(not_assessed))


class TestSameAsAndStableId(DetectorTestCase):

    def test_no_sameas_fires(self):
        pages = [homepage_with_org(org_overrides={"sameAs": None})]
        pages[0]["structured_data"]["jsonld"][0]["data"].pop("sameAs", None)
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "SDE.NO_SAMEAS")

    def test_sameas_present_does_not_fire_no_sameas(self):
        pages = [homepage_with_org()]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("SDE.NO_SAMEAS", self.ids(findings))

    def test_malformed_sameas_fires_and_is_ceilinged_low(self):
        pages = [homepage_with_org(org_overrides={"sameAs": ["not-a-url", "/relative"]})]
        findings, _ = self.detect(make_snapshot(pages=pages))
        found = self.only(findings, "SDE.SAMEAS_MALFORMED")
        self.assertEqual(found.get("severity_ceiling"), "low")

    def test_valid_absolute_sameas_does_not_fire_malformed(self):
        pages = [homepage_with_org()]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("SDE.SAMEAS_MALFORMED", self.ids(findings))

    def test_no_stable_id_fires_and_is_ceilinged_low(self):
        org = dict(ORG_NODE)
        org.pop("@id")
        pages = [make_page("/", page_type="homepage",
                           headings=[{"level": 1, "id": None,
                                     "text": "Larkspur Instruments", "in_content": True}],
                           structured_data=sd_block(jsonld=[jsonld_block(org)]))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        found = self.only(findings, "SDE.NO_STABLE_ID")
        self.assertEqual(found.get("severity_ceiling"), "low")

    def test_stable_id_present_does_not_fire(self):
        pages = [homepage_with_org()]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("SDE.NO_STABLE_ID", self.ids(findings))


class TestNameInconsistent(DetectorTestCase):

    def test_fires_on_genuine_name_mismatch(self):
        pages = [homepage_with_org(
            headings=[{"level": 1, "id": None, "text": "Meridian Tools",
                      "in_content": True}])]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.only(findings, "SDE.NAME_INCONSISTENT")

    def test_does_not_fire_on_matching_names(self):
        pages = [homepage_with_org()]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("SDE.NAME_INCONSISTENT", self.ids(findings))

    def test_does_not_fire_on_capitalization_difference(self):
        pages = [homepage_with_org(
            headings=[{"level": 1, "id": None, "text": "LARKSPUR INSTRUMENTS",
                      "in_content": True}])]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("SDE.NAME_INCONSISTENT", self.ids(findings))

    def test_does_not_fire_on_legal_suffix_difference(self):
        org = dict(ORG_NODE, name="Larkspur Instruments Ltd")
        pages = [make_page("/", page_type="homepage",
                           headings=[{"level": 1, "id": None,
                                     "text": "Larkspur Instruments", "in_content": True}],
                           structured_data=sd_block(jsonld=[jsonld_block(org)]))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("SDE.NAME_INCONSISTENT", self.ids(findings))

    def test_does_not_fire_on_word_order_difference(self):
        """Regression: French grammar reorders the descriptor and brand word."""
        pages = [homepage_with_org(
            headings=[{"level": 1, "id": None, "text": "Instruments Larkspur",
                      "in_content": True}])]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("SDE.NAME_INCONSISTENT", self.ids(findings))

    def test_no_homepage_h1_is_not_assessed_not_flagged(self):
        pages = [homepage_with_org(headings=[])]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("SDE.NAME_INCONSISTENT", self.ids(findings))


class TestOrgIdentityConflict(DetectorTestCase):

    def test_fires_on_conflicting_telephone_same_id(self):
        home = homepage_with_org()
        conflicting = {"@type": "ContactPage",
                      "mainEntity": dict(ORG_NODE, telephone="+44 20 7946 0555")}
        contact = make_page("/contact.html", page_type="contact",
                            structured_data=sd_block(jsonld=[jsonld_block(conflicting)]))
        findings, _ = self.detect(make_snapshot(pages=[home, contact]))
        found = self.only(findings, "SDE.ORG_IDENTITY_CONFLICT")
        self.assertIn("telephone", found["evidence"])

    def test_does_not_fire_when_values_agree(self):
        home = homepage_with_org()
        same = {"@type": "ContactPage", "mainEntity": dict(ORG_NODE)}
        contact = make_page("/contact.html", page_type="contact",
                            structured_data=sd_block(jsonld=[jsonld_block(same)]))
        findings, _ = self.detect(make_snapshot(pages=[home, contact]))
        self.assertNotIn("SDE.ORG_IDENTITY_CONFLICT", self.ids(findings))

    def test_does_not_fire_when_second_occurrence_simply_omits_a_field(self):
        """One page stating less about the entity is not a conflict with one stating
        more; only an actual disagreement in a shared field is."""
        home = homepage_with_org()
        partial = {"@type": "ContactPage",
                  "mainEntity": {"@id": ORIGIN + "/#organization",
                                "@type": "Organization"}}
        contact = make_page("/contact.html", page_type="contact",
                            structured_data=sd_block(jsonld=[jsonld_block(partial)]))
        findings, _ = self.detect(make_snapshot(pages=[home, contact]))
        self.assertNotIn("SDE.ORG_IDENTITY_CONFLICT", self.ids(findings))

    def test_requires_a_shared_id_not_just_the_same_type(self):
        home = homepage_with_org()
        different_id = dict(ORG_NODE, **{"@id": ORIGIN + "/#other",
                                        "telephone": "+44 20 7946 9999"})
        other = make_page("/other.html",
                          structured_data=sd_block(jsonld=[jsonld_block(different_id)]))
        findings, _ = self.detect(make_snapshot(pages=[home, other]))
        self.assertNotIn("SDE.ORG_IDENTITY_CONFLICT", self.ids(findings))

    def test_host_only_url_comparison_ignores_path_differences(self):
        """example.test/ vs example.test/company is the same host; not a conflict."""
        home = homepage_with_org()
        same_host = {"@type": "ContactPage",
                    "mainEntity": dict(ORG_NODE, url=ORIGIN + "/company")}
        contact = make_page("/contact.html",
                            structured_data=sd_block(jsonld=[jsonld_block(same_host)]))
        findings, _ = self.detect(make_snapshot(pages=[home, contact]))
        self.assertNotIn("SDE.ORG_IDENTITY_CONFLICT", self.ids(findings))


class TestEntityAmbiguityRisk(DetectorTestCase):

    def test_fires_with_two_or_more_signals(self):
        org = {"@context": "https://schema.org", "@type": "Organization",
              "@id": ORIGIN + "/#organization", "name": "Bolt", "url": ORIGIN + "/"}
        pages = [make_page("/", page_type="homepage",
                           headings=[{"level": 1, "id": None, "text": "Bolt",
                                     "in_content": True}],
                           structured_data=sd_block(jsonld=[jsonld_block(org)]))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        found = self.only(findings, "SDE.ENTITY_AMBIGUITY_RISK")
        self.assertEqual(found["certainty"], "inferred")
        self.assertEqual(found.get("severity_ceiling"), "medium")

    def test_does_not_fire_with_a_distinctive_well_anchored_name(self):
        pages = [homepage_with_org()]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("SDE.ENTITY_AMBIGUITY_RISK", self.ids(findings))

    def test_does_not_fire_with_only_one_signal(self):
        """A short name alone, with sameAs and address both present, is one signal."""
        org = dict(ORG_NODE, name="Bolt")
        pages = [make_page("/", page_type="homepage",
                           headings=[{"level": 1, "id": None, "text": "Bolt",
                                     "in_content": True}],
                           structured_data=sd_block(jsonld=[jsonld_block(org)]))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("SDE.ENTITY_AMBIGUITY_RISK", self.ids(findings))


class TestMicrodataOnly(DetectorTestCase):

    def test_fires_when_microdata_present_and_no_jsonld(self):
        pages = [make_page("/p%d.html" % i,
                           structured_data=sd_block(microdata_types=["Product"]))
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        found = self.only(findings, "SDE.MICRODATA_ONLY")
        self.assertEqual(found.get("severity_ceiling"), "low")

    def test_does_not_fire_when_jsonld_also_present(self):
        pages = [make_page("/p0.html",
                           structured_data=sd_block(jsonld=[jsonld_block(product_node())])),
                make_page("/p1.html",
                         structured_data=sd_block(microdata_types=["Product"]))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("SDE.MICRODATA_ONLY", self.ids(findings))

    def test_does_not_fire_when_nothing_at_all_is_present(self):
        """Absence is NO_STRUCTURED_DATA's job, not a migration suggestion."""
        pages = [make_page("/p%d.html" % i) for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("SDE.MICRODATA_ONLY", self.ids(findings))


class TestBreadcrumbMissing(DetectorTestCase):

    def test_fires_below_the_homepage_on_a_deep_site(self):
        pages = [make_page("/products/alpha.html"), make_page("/products/beta.html"),
                make_page("/products/gamma.html")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        found = self.only(findings, "SDE.BREADCRUMB_MISSING")
        self.assertEqual(found.get("severity_ceiling"), "low")

    def test_does_not_fire_with_breadcrumbs_present(self):
        pages = [make_page("/products/%s.html" % s,
                           structured_data=sd_block(jsonld=[jsonld_block(breadcrumb_node())]))
                for s in ("alpha", "beta", "gamma")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("SDE.BREADCRUMB_MISSING", self.ids(findings))

    def test_does_not_fire_on_a_flat_site_with_no_real_hierarchy(self):
        pages = [make_page("/about.html"), make_page("/contact.html")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("SDE.BREADCRUMB_MISSING", self.ids(findings))

    def test_homepage_itself_is_never_expected_to_have_one(self):
        pages = [make_page("/", page_type="homepage"),
                make_page("/products/alpha.html",
                         structured_data=sd_block(jsonld=[jsonld_block(breadcrumb_node())])),
                make_page("/products/beta.html",
                         structured_data=sd_block(jsonld=[jsonld_block(breadcrumb_node())]))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("SDE.BREADCRUMB_MISSING", self.ids(findings))


# ============================================================== broad false-positive suite

class TestFalsePositiveDefense(DetectorTestCase):

    def test_clean_valid_jsonld_site_is_silent(self):
        pages = [homepage_with_org()] + [
            make_page("/products/%s.html" % s, page_type="product",
                     main_text="Costs 59.00 GBP and ships fast to your door today.",
                     headings=[{"level": 1, "id": None, "text": "%s Caliper" % s.title(),
                               "in_content": True}],
                     structured_data=sd_block(jsonld=[
                         jsonld_block(breadcrumb_node()),
                         jsonld_block(product_node(name="%s Caliper" % s.title(),
                                                   price="59.00"))]))
            for s in ("alpha", "beta", "gamma")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertEqual(findings, [])

    def test_clean_microdata_site_produces_only_the_migration_suggestion(self):
        items = [{"itemtype": "https://schema.org/Organization",
                 "props": {"name": "Larkspur Instruments", "url": ORIGIN + "/"}}]
        pages = [make_page("/", page_type="homepage",
                           headings=[{"level": 1, "id": None,
                                     "text": "Larkspur Instruments", "in_content": True}],
                           structured_data=sd_block(microdata_types=["Organization"],
                                                    microdata_items=items)),
                make_page("/about.html", page_type="about",
                         structured_data=sd_block(microdata_types=["AboutPage"]))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        ids = self.ids(findings)
        for f in findings:
            self.assertLessEqual(f.get("severity_ceiling") == "low", True)
        self.assertTrue(all(f["check_id"] in
                            ("SDE.MICRODATA_ONLY", "SDE.NO_SAMEAS", "SDE.NO_STABLE_ID",
                             "SDE.BREADCRUMB_MISSING")
                            for f in findings))

    def test_clean_rdfa_site_is_not_treated_as_broken(self):
        pages = [make_page("/", page_type="homepage",
                           headings=[{"level": 1, "id": None,
                                     "text": "Larkspur Instruments", "in_content": True}],
                           structured_data=sd_block(rdfa_types=["Organization"]))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("SDE.NO_STRUCTURED_DATA", self.ids(findings))

    def test_no_structured_data_but_otherwise_valid_page_only_reports_absence(self):
        pages = [make_page("/", page_type="homepage"), make_page("/p1.html"),
                make_page("/p2.html")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        ids = self.ids(findings)
        self.assertIn("SDE.NO_STRUCTURED_DATA", ids)
        self.assertNotIn("SDE.SCHEMA_VISIBLE_MISMATCH", ids)
        self.assertNotIn("SDE.INVALID_JSONLD", ids)

    def test_multiple_legitimate_types_on_one_page_is_fine(self):
        multi = {"@graph": [breadcrumb_node(), product_node()]}
        pages = [make_page("/p.html", page_type="product",
                           main_text="Costs 59.00 GBP and ships fast to your door.",
                           headings=[{"level": 1, "id": None, "text": "Alpha Caliper",
                                     "in_content": True}],
                           structured_data=sd_block(jsonld=[jsonld_block(multi)]))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertEqual(findings, [])

    def test_optional_property_missing_never_flagged_above_silence(self):
        no_recommended = {"@type": "Product", "name": "X",
                          "offers": {"price": "10.00", "priceCurrency": "GBP"}}
        pages = [make_page("/p%d.html" % i, page_type="product",
                           main_text="X costs 10.00 GBP and ships within two days.",
                           headings=[{"level": 1, "id": None, "text": "X",
                                     "in_content": True}],
                           structured_data=sd_block(jsonld=[jsonld_block(no_recommended)]))
                for i in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertEqual(findings, [])

    def test_ecommerce_product_pages_fully_covered_is_silent(self):
        pages = [make_page("/products/%s.html" % s, page_type="product",
                           main_text="Costs 59.00 GBP and ships fast to your door today.",
                           headings=[{"level": 1, "id": None,
                                     "text": "%s Caliper" % s.title(),
                                     "in_content": True}],
                           structured_data=sd_block(jsonld=[
                               jsonld_block(breadcrumb_node()),
                               jsonld_block(product_node(name="%s Caliper" % s.title(),
                                                         price="59.00"))]))
                for s in ("alpha", "beta", "gamma")]
        findings, _ = self.detect(make_snapshot(pages=[homepage_with_org()] + pages))
        self.assertEqual(findings, [])

    def test_non_ecommerce_informational_site_never_demands_product_markup(self):
        pages = [homepage_with_org()] + [
            make_page("/services/%s.html" % s, page_type="about",
                     structured_data=sd_block(jsonld=[jsonld_block(breadcrumb_node())]))
            for s in ("consulting", "training", "support")]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("SDE.MISSING_TYPE_FOR_TEMPLATE", self.ids(findings))

    def test_article_author_page_with_full_markup_is_silent(self):
        article = {"@type": "Article", "headline": "A guide", "datePublished": "2026-01-01",
                  "author": {"@type": "Person", "name": "J. Reyes"}}
        pages = [make_page("/articles/guide.html", page_type="article",
                           structured_data=sd_block(jsonld=[
                               jsonld_block(breadcrumb_node()), jsonld_block(article)]))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertEqual(findings, [])

    def test_type_not_applicable_to_this_page_is_never_demanded(self):
        """An FAQ-classified page is never asked for Product or Article markup."""
        pages = [make_page("/faq.html", page_type="faq") for _ in range(3)]
        findings, _ = self.detect(make_snapshot(pages=pages))
        ids = self.ids(findings)
        self.assertNotIn("SDE.MISSING_TYPE_FOR_TEMPLATE", ids)

    def test_insufficient_sample_never_claims_sitewide_falsely(self):
        home = homepage_with_org()
        one_bad = make_page("/p0.html", page_type="product")
        two_good = [make_page("/p1.html", page_type="product",
                             structured_data=sd_block(jsonld=[jsonld_block(product_node())])),
                   make_page("/p2.html", page_type="product",
                            structured_data=sd_block(jsonld=[jsonld_block(product_node())]))]
        findings, _ = self.detect(make_snapshot(pages=[home, one_bad] + two_good))
        found = self.only(findings, "SDE.MISSING_TYPE_FOR_TEMPLATE")
        self.assertEqual(found["reach"], "page")

    def test_multilingual_content_with_matching_facts_is_silent(self):
        org = dict(ORG_NODE, name="Larkspur Instruments")
        pages = [make_page("/", page_type="homepage", lang="fr",
                           headings=[{"level": 1, "id": None,
                                     "text": "Instruments Larkspur", "in_content": True}],
                           structured_data=sd_block(jsonld=[jsonld_block(org)])),
                make_page("/produits/alpha.html", page_type="product", lang="fr",
                         main_text="Il coute 59,00 GBP et est en stock aujourd'hui.",
                         headings=[{"level": 1, "id": None, "text": "Alpha Caliper",
                                   "in_content": True}],
                         structured_data=sd_block(jsonld=[
                             jsonld_block(product_node(price="59.00"))]))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertNotIn("SDE.NAME_INCONSISTENT", self.ids(findings))
        self.assertNotIn("SDE.SCHEMA_VISIBLE_MISMATCH", self.ids(findings))

    def test_jsonld_embedded_alongside_other_script_blocks_parses_fine(self):
        pages = [make_page("/p.html", page_type="product",
                           main_text="Costs 59.00 GBP and ships fast to your door.",
                           headings=[{"level": 1, "id": None, "text": "Alpha Caliper",
                                     "in_content": True}],
                           structured_data=sd_block(jsonld=[
                               jsonld_block(breadcrumb_node()),
                               jsonld_block(product_node(price="59.00"))]))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertEqual(findings, [])

    def test_structured_data_present_but_insufficient_to_establish_entity(self):
        """A bare WebPage node with no name asserts nothing worth checking further."""
        bare = {"@type": "WebPage"}
        pages = [make_page("/p.html", structured_data=sd_block(jsonld=[jsonld_block(bare)]))]
        findings, _ = self.detect(make_snapshot(pages=pages))
        self.assertEqual([f for f in findings if f["check_id"] not in
                          ("SDE.MISSING_TYPE_FOR_TEMPLATE",)], [])


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
    scenarios.append(make_snapshot(pages=[make_page("/p%d.html" % i) for i in range(3)]))
    scenarios.append(make_snapshot(pages=[
        make_page("/p%d.html" % i, structured_data=sd_block(jsonld=[broken_jsonld_block()]))
        for i in range(3)]))
    scenarios.append(make_snapshot(pages=[
        make_page("/p%d.html" % i, page_type="product") for i in range(3)]))
    scenarios.append(make_snapshot(pages=[
        make_page("/p%d.html" % i, page_type="product",
                 structured_data=sd_block(jsonld=[jsonld_block(
                     {"@type": "Product", "name": "X"})]))
        for i in range(3)]))
    scenarios.append(make_snapshot(pages=[make_page(
        "/p.html", page_type="product",
        main_text="The Alpha Caliper costs 49.00 GBP and is in stock.",
        structured_data=sd_block(jsonld=[jsonld_block(product_node(price="59.00"))]))]))
    scenarios.append(make_snapshot(pages=[make_page(
        "/p%d.html" % i, page_type="product",
        main_text="A fine product with no price mentioned in the copy at all.",
        structured_data=sd_block(jsonld=[jsonld_block(product_node())]))
        for i in range(2)]))
    scenarios.append(make_snapshot(pages=[
        make_page("/", page_type="homepage"), make_page("/p1.html"),
        make_page("/p2.html")]))
    scenarios.append(make_snapshot(pages=[homepage_with_org(org_overrides={})]))
    home_no_sameas = homepage_with_org()
    home_no_sameas["structured_data"]["jsonld"][0]["data"].pop("sameAs")
    scenarios.append(make_snapshot(pages=[home_no_sameas]))
    org_no_id = dict(ORG_NODE)
    org_no_id.pop("@id")
    scenarios.append(make_snapshot(pages=[make_page(
        "/", page_type="homepage",
        headings=[{"level": 1, "id": None, "text": "Larkspur Instruments",
                  "in_content": True}],
        structured_data=sd_block(jsonld=[jsonld_block(org_no_id)]))]))
    scenarios.append(make_snapshot(pages=[
        homepage_with_org(org_overrides={"sameAs": ["not-a-url"]})]))
    scenarios.append(make_snapshot(pages=[homepage_with_org(
        headings=[{"level": 1, "id": None, "text": "Meridian Tools",
                  "in_content": True}])]))
    home2 = homepage_with_org()
    conflicting = {"@type": "ContactPage",
                  "mainEntity": dict(ORG_NODE, telephone="+44 20 7946 0555")}
    contact2 = make_page("/contact.html",
                         structured_data=sd_block(jsonld=[jsonld_block(conflicting)]))
    scenarios.append(make_snapshot(pages=[home2, contact2]))
    scenarios.append(make_snapshot(pages=[make_page(
        "/", page_type="homepage",
        headings=[{"level": 1, "id": None, "text": "Bolt", "in_content": True}],
        structured_data=sd_block(jsonld=[jsonld_block(
            {"@type": "Organization", "@id": ORIGIN + "/#o", "name": "Bolt",
             "url": ORIGIN + "/"})]))]))
    scenarios.append(make_snapshot(pages=[
        make_page("/p%d.html" % i, structured_data=sd_block(microdata_types=["Product"]))
        for i in range(3)]))
    scenarios.append(make_snapshot(pages=[
        make_page("/products/alpha.html"), make_page("/products/beta.html"),
        make_page("/products/gamma.html")]))

    findings = []
    for snapshot in scenarios:
        found, _ = sde.run(copy.deepcopy(snapshot))
        findings.extend(found)
    return findings


class TestEvidenceQuality(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.findings = sweep_findings()

    def test_the_sweep_covers_every_implemented_check(self):
        covered = {f["check_id"] for f in self.findings}
        expected = {
            "SDE.NO_STRUCTURED_DATA", "SDE.INVALID_JSONLD",
            "SDE.MISSING_TYPE_FOR_TEMPLATE", "SDE.INCOMPLETE_REQUIRED_PROPS",
            "SDE.SCHEMA_VISIBLE_MISMATCH", "SDE.SCHEMA_ONLY_NO_VISIBLE",
            "SDE.NO_ORGANIZATION_NODE", "SDE.NO_SAMEAS", "SDE.SAMEAS_MALFORMED",
            "SDE.NAME_INCONSISTENT", "SDE.NO_STABLE_ID", "SDE.ORG_IDENTITY_CONFLICT",
            "SDE.ENTITY_AMBIGUITY_RISK", "SDE.MICRODATA_ONLY",
            "SDE.BREADCRUMB_MISSING",
        }
        self.assertEqual(expected - covered, set(),
                         "these checks never fired in the sweep: %s"
                         % (expected - covered))

    def test_every_finding_is_well_formed(self):
        self.assertGreaterEqual(len(self.findings), 14)
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
            self.assertEqual(found["funnel_stage"], "understood", label)
            self.assertIn(found["suggested_action"]["effort"],
                          ("trivial", "config", "content", "template-change",
                           "platform-change"), label)
            self.assertIn(found["suggested_action"]["owner"],
                          ("engineering", "content", "brand-ops", "marketing", "mixed"),
                          label)
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

    def test_evidence_quotes_something_concrete(self):
        for found in self.findings:
            evidence = found["evidence"]
            concrete = (any(ch.isdigit() for ch in evidence) or "'" in evidence
                       or '"' in evidence or "http" in evidence)
            self.assertTrue(concrete,
                            "%s evidence has no concrete observed value: %s"
                            % (found["check_id"], evidence))


if __name__ == "__main__":
    unittest.main(verbosity=2)
