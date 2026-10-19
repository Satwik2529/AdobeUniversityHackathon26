#!/usr/bin/env python3
"""Unit tests for the site-snapshot collector.

Covers the deterministic primitives in isolation, then exercises the whole collector
against the local fixture server. Everything here runs offline.

Run: python3 skills/site-snapshot-collector/scripts/test_collector.py
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import cluster as clustering      # noqa: E402
import collect                    # noqa: E402
import htmlparse                  # noqa: E402
import render as rendering        # noqa: E402
import robots as robots_module    # noqa: E402
import urlnorm                    # noqa: E402
from fixture_server import FixtureServer  # noqa: E402

CONFIG = collect.load_config()
TRACKING = CONFIG["url_normalization"]["tracking_params"]
SESSION = CONFIG["url_normalization"]["session_params"]
FIXTURES = os.path.join(ROOT, "tests", "fixtures")
COLLECT = os.path.join(HERE, "collect.py")


# ============================================================================ robots.txt

class TestRobotsParsing(unittest.TestCase):

    def test_groups_and_directives(self):
        policy = robots_module.parse(
            "User-agent: *\n"
            "Disallow: /private\n"
            "\n"
            "User-agent: GoodBot\n"
            "User-agent: OtherBot\n"
            "Allow: /\n"
            "Crawl-delay: 3\n"
            "\n"
            "Sitemap: https://example.test/sitemap.xml\n")
        self.assertTrue(policy.parse_ok)
        self.assertEqual(len(policy.groups), 2)
        self.assertEqual(policy.groups[1].agents, ["goodbot", "otherbot"])
        self.assertEqual(policy.groups[1].crawl_delay, 3.0)
        self.assertEqual(policy.sitemaps[0]["url"], "https://example.test/sitemap.xml")
        self.assertEqual(policy.sitemaps[0]["line"], 9)

    def test_consecutive_user_agents_share_one_group(self):
        policy = robots_module.parse(
            "User-agent: A\nUser-agent: B\nDisallow: /x\nUser-agent: C\nDisallow: /y\n")
        self.assertEqual(len(policy.groups), 2)
        self.assertEqual(policy.groups[0].agents, ["a", "b"])
        self.assertEqual(policy.groups[1].agents, ["c"])

    def test_specific_group_beats_wildcard(self):
        policy = robots_module.parse(
            "User-agent: *\nDisallow: /\n\nUser-agent: SearchBot\nAllow: /\n")
        self.assertTrue(policy.can_fetch("SearchBot", "/page"))
        self.assertFalse(policy.can_fetch("OtherBot", "/page"))

    def test_longest_agent_token_wins(self):
        policy = robots_module.parse(
            "User-agent: Bot\nDisallow: /\n\nUser-agent: BotSpecial\nAllow: /\n")
        self.assertTrue(policy.can_fetch("BotSpecial/1.0", "/page"))
        self.assertFalse(policy.can_fetch("BotOther/1.0", "/page"))

    def test_agent_matching_is_case_insensitive(self):
        policy = robots_module.parse("User-agent: GPTBot\nDisallow: /\n")
        self.assertFalse(policy.can_fetch("gptbot", "/x"))
        self.assertFalse(policy.can_fetch("GPTBOT", "/x"))

    def test_longest_path_match_wins(self):
        policy = robots_module.parse(
            "User-agent: *\nDisallow: /docs\nAllow: /docs/public\n")
        self.assertFalse(policy.can_fetch("Any", "/docs/private"))
        self.assertTrue(policy.can_fetch("Any", "/docs/public/a"))

    def test_allow_wins_on_equal_specificity(self):
        policy = robots_module.parse("User-agent: *\nDisallow: /x\nAllow: /x\n")
        self.assertTrue(policy.can_fetch("Any", "/x/y"))

    def test_empty_disallow_allows_everything(self):
        policy = robots_module.parse("User-agent: *\nDisallow:\n")
        self.assertTrue(policy.can_fetch("Any", "/anything"))

    def test_wildcard_and_end_anchor(self):
        policy = robots_module.parse(
            "User-agent: *\nDisallow: /*.pdf$\nDisallow: /a/*/b\n")
        self.assertFalse(policy.can_fetch("Any", "/files/report.pdf"))
        self.assertTrue(policy.can_fetch("Any", "/files/report.pdf?x=1"))
        self.assertFalse(policy.can_fetch("Any", "/a/middle/b"))
        self.assertTrue(policy.can_fetch("Any", "/a/middle/c"))

    def test_no_substring_matching(self):
        """The classic naive bug: a token appearing anywhere in the file is not a rule."""
        policy = robots_module.parse(
            "# We considered blocking GPTBot but decided not to\n"
            "User-agent: *\nAllow: /\n")
        self.assertTrue(policy.can_fetch("GPTBot", "/"))
        self.assertEqual(policy.evaluate("GPTBot", "/")["matched_agent_token"], "*")

    def test_matched_rule_carries_line_number_as_evidence(self):
        policy = robots_module.parse(
            "User-agent: *\nAllow: /\n\nUser-agent: SearchBot\nDisallow: /\n")
        verdict = policy.evaluate("SearchBot", "/products/a")
        self.assertEqual(verdict["verdict"], "disallow")
        self.assertEqual(verdict["matched_rule"]["line"], 5)
        self.assertEqual(verdict["matched_rule"]["path"], "/")
        self.assertEqual(verdict["matched_agent_token"], "searchbot")

    def test_crawl_delay_resolution_follows_group_selection(self):
        policy = robots_module.parse(
            "User-agent: *\nCrawl-delay: 10\nDisallow:\n\n"
            "User-agent: Mine\nCrawl-delay: 1.5\nDisallow:\n")
        self.assertEqual(policy.crawl_delay_for("Mine/1.0"), 1.5)
        self.assertEqual(policy.crawl_delay_for("Someone"), 10.0)

    def test_malformed_lines_are_recorded_not_fatal(self):
        policy = robots_module.parse(
            "this is not a directive\nUser-agent: *\nDisallow: /x\nCrawl-delay: soon\n")
        self.assertTrue(policy.parse_ok)
        reasons = " ".join(error["reason"] for error in policy.errors)
        self.assertIn("no directive separator", reasons)
        self.assertIn("Crawl-delay", reasons)
        self.assertFalse(policy.can_fetch("Any", "/x"))

    def test_rule_before_any_user_agent_is_an_error_not_a_rule(self):
        policy = robots_module.parse("Disallow: /\nUser-agent: *\nAllow: /\n")
        self.assertTrue(policy.can_fetch("Any", "/page"))
        self.assertIn("before any User-agent", policy.errors[0]["reason"])

    def test_entirely_unparseable_file_is_flagged(self):
        policy = robots_module.parse("<html><body>Not found</body></html>")
        self.assertFalse(policy.parse_ok)

    def test_no_group_verdict(self):
        policy = robots_module.parse("User-agent: OnlyBot\nDisallow: /\n")
        self.assertEqual(policy.evaluate("Someone", "/")["verdict"], "no-group")

    def test_verdicts_for_multiple_agents(self):
        policy = robots_module.parse(
            "User-agent: *\nAllow: /\n\nUser-agent: TrainBot\nDisallow: /\n")
        verdicts, matched = robots_module.verdicts_for(
            policy, ["TrainBot", "SearchBot", "*"], "/")
        self.assertEqual(verdicts["TrainBot"], "disallow")
        self.assertEqual(verdicts["SearchBot"], "allow")
        self.assertIsNotNone(matched["TrainBot"]["rule"])


# ==================================================================== URL normalisation

class TestUrlNormalization(unittest.TestCase):

    def n(self, url, base=None):
        return urlnorm.normalize(url, base=base, tracking_params=TRACKING,
                                 session_params=SESSION)

    def test_host_and_scheme_lowercased(self):
        self.assertEqual(self.n("HTTP://Example.TEST/Path"),
                         "http://example.test/Path")

    def test_default_ports_removed_and_others_kept(self):
        self.assertEqual(self.n("https://example.test:443/a"), "https://example.test/a")
        self.assertEqual(self.n("http://example.test:80/a"), "http://example.test/a")
        self.assertEqual(self.n("http://example.test:8099/a"),
                         "http://example.test:8099/a")

    def test_fragment_dropped(self):
        self.assertEqual(self.n("https://example.test/a#specs"), "https://example.test/a")

    def test_duplicate_slashes_and_dot_segments_collapsed(self):
        self.assertEqual(self.n("https://example.test//a///b/../c"),
                         "https://example.test/a/c")

    def test_trailing_slash_preserved_for_fetching(self):
        self.assertEqual(self.n("https://example.test/a/"), "https://example.test/a/")
        self.assertEqual(self.n("https://example.test/a"), "https://example.test/a")

    def test_dedupe_key_folds_trailing_slash(self):
        key = lambda u: urlnorm.dedupe_key(u, TRACKING, SESSION)  # noqa: E731
        self.assertEqual(key("https://example.test/a/"), key("https://example.test/a"))
        self.assertEqual(key("https://example.test/"), "https://example.test/")

    def test_tracking_parameters_removed(self):
        self.assertEqual(self.n("https://example.test/a?utm_source=x&gclid=y"),
                         "https://example.test/a")

    def test_session_parameters_removed_by_name_and_by_shape(self):
        self.assertEqual(self.n("https://example.test/a?PHPSESSID=abc123"),
                         "https://example.test/a")
        self.assertEqual(self.n("https://example.test/a?sid=0123456789abcdef0123"),
                         "https://example.test/a")

    def test_meaningful_parameters_preserved(self):
        self.assertEqual(self.n("https://example.test/s?q=calipers&page=2"),
                         "https://example.test/s?page=2&q=calipers")

    def test_parameter_order_does_not_create_two_urls(self):
        self.assertEqual(self.n("https://example.test/a?b=2&a=1"),
                         self.n("https://example.test/a?a=1&b=2"))

    def test_non_http_schemes_rejected(self):
        for url in ("mailto:x@example.test", "javascript:void(0)", "tel:+1",
                    "ftp://example.test/a", "data:text/html,x", "#anchor"):
            self.assertIsNone(self.n(url), url)

    def test_relative_resolution(self):
        self.assertEqual(self.n("../b", base="https://example.test/x/y/c"),
                         "https://example.test/x/b")

    def test_credentials_stripped(self):
        self.assertEqual(self.n("https://user:pw@example.test/a"),
                         "https://example.test/a")

    def test_same_site_ignores_www(self):
        self.assertTrue(urlnorm.same_site("https://www.example.test/a",
                                          "https://example.test/b"))
        self.assertFalse(urlnorm.same_site("https://example.test/a",
                                           "https://other.test/b"))

    def test_path_skeletons(self):
        cases = {
            "https://e.test/": "/",
            "https://e.test/products/velocity-x9": "/products/{slug}",
            "https://e.test/blog/2026/09/a-long-article-title": "/blog/{date}/{n}/{slug}",
            "https://e.test/item/12345": "/item/{n}",
            "https://e.test/x/550e8400-e29b-41d4-a716-446655440000": "/x/{id}",
            "https://e.test/p/alpha.html": "/p/alpha.html",
            "https://e.test/s?q=a&sort=b": "/s?q&sort",
        }
        for url, expected in cases.items():
            self.assertEqual(urlnorm.path_skeleton(url), expected, url)

    def test_faceted_urls_share_one_skeleton(self):
        self.assertEqual(urlnorm.path_skeleton("https://e.test/c?color=red&size=9"),
                         urlnorm.path_skeleton("https://e.test/c?color=blue&size=10"))

    def test_binary_and_document_detection(self):
        self.assertTrue(urlnorm.is_probably_non_html("https://e.test/a.png"))
        self.assertTrue(urlnorm.is_probably_non_html("https://e.test/a.pdf"))
        self.assertTrue(urlnorm.is_document("https://e.test/spec.pdf"))
        self.assertFalse(urlnorm.is_document("https://e.test/a.html"))

    def test_normalisation_is_idempotent(self):
        once = self.n("HTTPS://Example.TEST:443//a//b/?utm_source=x&z=1#f")
        self.assertEqual(once, self.n(once))


# ========================================================================= sitemap parsing

class TestSitemapParsing(unittest.TestCase):

    URLSET = ('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/'
              'sitemap/0.9"><url><loc>https://e.test/a</loc><lastmod>2026-01-02</lastmod>'
              '</url><url><loc>https://e.test/b</loc></url></urlset>')
    INDEX = ('<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/'
             'sitemap/0.9"><sitemap><loc>https://e.test/s1.xml</loc></sitemap>'
             '</sitemapindex>')

    def test_urlset(self):
        kind, entries, ok, error = collect.parse_sitemap(self.URLSET)
        self.assertEqual((kind, ok, error), ("urlset", True, None))
        self.assertEqual(entries[0], {"loc": "https://e.test/a", "lastmod": "2026-01-02"})
        self.assertIsNone(entries[1]["lastmod"])

    def test_index(self):
        kind, entries, ok, _ = collect.parse_sitemap(self.INDEX)
        self.assertEqual((kind, ok, len(entries)), ("index", True, 1))

    def test_malformed_xml_recovers_locations_and_reports_it(self):
        broken = self.URLSET.replace("</urlset>", "")
        kind, entries, ok, error = collect.parse_sitemap(broken)
        self.assertFalse(ok)
        self.assertEqual(len(entries), 2)
        self.assertIn("malformed", error)

    def test_unrecoverable_xml_is_not_silently_empty(self):
        kind, entries, ok, error = collect.parse_sitemap("<html><body>nope</body></html>")
        self.assertFalse(ok)
        self.assertEqual(entries, [])
        self.assertIsNotNone(error)

    def test_namespaced_and_unnamespaced_both_parse(self):
        plain = "<urlset><url><loc>https://e.test/a</loc></url></urlset>"
        kind, entries, ok, _ = collect.parse_sitemap(plain)
        self.assertEqual((kind, ok, len(entries)), ("urlset", True, 1))


# ========================================================== clustering and classification

class TestClustering(unittest.TestCase):

    URLS = [
        "https://e.test/",
        "https://e.test/about.html",
        "https://e.test/contact.html",
        "https://e.test/products/",
        "https://e.test/products/alpha.html",
        "https://e.test/products/beta.html",
        "https://e.test/products/gamma.html",
        "https://e.test/blog/2026/first-long-post-title",
        "https://e.test/blog/2026/second-long-post-title",
    ]

    def test_sibling_leaves_merge_into_one_template(self):
        clusters = clustering.build_clusters(self.URLS)
        skeletons = {c["skeleton"]: c for c in clusters}
        self.assertIn("/products/{slug}.html", skeletons)
        self.assertEqual(skeletons["/products/{slug}.html"]["size"], 3)

    def test_root_level_pages_do_not_merge(self):
        clusters = clustering.build_clusters(self.URLS)
        skeletons = {c["skeleton"] for c in clusters}
        self.assertIn("/about.html", skeletons)
        self.assertIn("/contact.html", skeletons)
        self.assertNotIn("/{slug}.html", skeletons)

    def test_section_words_do_not_merge(self):
        clusters = clustering.build_clusters(
            ["https://e.test/docs/api", "https://e.test/docs/guide"])
        self.assertEqual({c["skeleton"] for c in clusters},
                         {"/docs/api", "/docs/guide"})

    def test_cluster_ids_are_stable_regardless_of_input_order(self):
        first = clustering.build_clusters(self.URLS)
        second = clustering.build_clusters(list(reversed(self.URLS)))
        self.assertEqual([(c["id"], c["skeleton"]) for c in first],
                         [(c["id"], c["skeleton"]) for c in second])

    def test_sampling_always_includes_the_homepage(self):
        clusters = clustering.build_clusters(self.URLS)
        chosen = clustering.sample(clusters, 3, homepage="https://e.test/")
        self.assertEqual(chosen[0], "https://e.test/")

    def test_sampling_is_breadth_first_across_templates(self):
        clusters = clustering.build_clusters(self.URLS)
        chosen = clustering.sample(clusters, 5, homepage="https://e.test/")
        skeletons = {urlnorm.path_skeleton(u) for u in chosen}
        self.assertGreaterEqual(len(skeletons), 4,
                                "a 5-page sample must not sit inside one template")

    def test_sampling_respects_max_pages(self):
        clusters = clustering.build_clusters(self.URLS)
        self.assertEqual(len(clustering.sample(clusters, 4,
                                               homepage="https://e.test/")), 4)

    def test_sampling_is_deterministic(self):
        runs = []
        for _ in range(3):
            clusters = clustering.build_clusters(self.URLS)
            runs.append(clustering.sample(clusters, 6, homepage="https://e.test/"))
        self.assertEqual(runs[0], runs[1])
        self.assertEqual(runs[1], runs[2])

    def test_sampling_spends_its_budget_after_guaranteeing_fairness(self):
        """per_cluster_cap is a fairness floor, not a ceiling on the whole sample."""
        urls = (["https://e.test/"]
                + ["https://e.test/p/item-%03d.html" % i for i in range(60)]
                + ["https://e.test/b/post-number-%03d.html" % i for i in range(40)])
        clusters = clustering.build_clusters(urls)
        chosen = clustering.sample(clusters, 30, homepage="https://e.test/")
        self.assertEqual(len(chosen), 30,
                         "a 30-page budget must not be left mostly unspent")
        counts = {}
        for url in chosen:
            skeleton = urlnorm.path_skeleton(url)
            counts[skeleton] = counts.get(skeleton, 0) + 1
        self.assertGreaterEqual(counts["/p/{slug}.html"], 3)
        self.assertGreaterEqual(counts["/b/{slug}.html"], 3)

    def test_faceted_variants_cannot_consume_the_sample(self):
        urls = (["https://e.test/"]
                + ["https://e.test/p/item-%03d.html" % i for i in range(30)]
                + ["https://e.test/p/?color=%s&size=%s" % (c, s)
                   for c in ("red", "blue", "green") for s in ("8", "9", "10", "11")])
        clusters = clustering.build_clusters(urls)
        chosen = clustering.sample(clusters, 25, homepage="https://e.test/")
        faceted = [u for u in chosen if "?" in u]
        self.assertLessEqual(len(faceted), 3,
                             "faceted variants are the same content re-filtered")
        self.assertTrue(faceted, "they should still be represented, just not dominate")

    def test_navigation_linked_clusters_rank_up(self):
        clusters = clustering.build_clusters(self.URLS)
        chosen = clustering.sample(clusters, 3, homepage="https://e.test/",
                                   nav_skeletons=["/contact.html"])
        self.assertIn("https://e.test/contact.html", chosen)


class TestPageClassification(unittest.TestCase):

    EMPTY = {"headings": [], "links": [], "forms": 0, "main_text_len": 500}

    def classify(self, url, schema=(), parsed=None):
        return clustering.classify_page(url, "https://e.test/",
                                        parsed or dict(self.EMPTY), list(schema))

    def test_homepage_is_structural(self):
        self.assertEqual(self.classify("https://e.test/")[:2], ("homepage", "high"))

    def test_structured_data_drives_the_type(self):
        self.assertEqual(self.classify("https://e.test/x/y", ["Product"])[0], "product")
        self.assertEqual(self.classify("https://e.test/x/y", ["BlogPosting"])[0], "article")

    def test_utility_paths_recognised(self):
        for path in ("/search", "/cart", "/account", "/checkout"):
            self.assertEqual(self.classify("https://e.test" + path)[0], "utility", path)

    def test_organization_alone_is_not_a_page_type(self):
        page_type, confidence, _ = self.classify("https://e.test/x", ["Organization"])
        self.assertEqual(page_type, "unknown")
        self.assertEqual(confidence, "low")

    def test_unknown_stays_unknown(self):
        page_type, confidence, _ = self.classify("https://e.test/zx9")
        self.assertEqual(page_type, "unknown")
        self.assertEqual(confidence, "low")

    def test_ties_resolve_to_unknown_not_a_guess(self):
        page_type, _, _ = self.classify("https://e.test/x", ["Product", "BlogPosting"])
        self.assertEqual(page_type, "unknown")

    def test_archetype_needs_evidence(self):
        self.assertEqual(clustering.classify_archetype(["unknown"])[0], "unknown")
        self.assertEqual(
            clustering.classify_archetype(
                ["homepage", "product", "product", "category"])[0], "ecommerce")
        self.assertEqual(
            clustering.classify_archetype(
                ["homepage", "about", "contact"])[0], "brochure")


# ============================================================= static client-render signals

class TestStaticSpaSignals(unittest.TestCase):

    def signals(self, html):
        parsed = htmlparse.extract(html, CONFIG["spa_signals"])
        return {s["signal"] for s in rendering.static_spa_signals(parsed, CONFIG)}

    def test_shell_produces_two_high_weight_signals(self):
        html = ('<html><body><main><div id="app"></div></main>'
                '<noscript>Enable JavaScript</noscript>'
                '<script>' + "x" * 30000 + '</script></body></html>')
        parsed = htmlparse.extract(html, CONFIG["spa_signals"])
        signals = rendering.static_spa_signals(parsed, CONFIG)
        high = [s for s in signals if s["weight"] == "high"]
        self.assertGreaterEqual(len(high), 2)

    def test_a_normal_page_produces_no_signals(self):
        html = "<html><body><main><h1>Title</h1><p>%s</p></main></body></html>" % (
            "Readable prose. " * 60)
        self.assertEqual(self.signals(html), set())

    def test_absence_of_a_browser_is_never_inferred_as_a_defect(self):
        renderer = rendering.Renderer(5, CONFIG["spa_signals"])
        if not renderer.available:
            self.assertIsNotNone(renderer.unavailable_reason)
            self.assertIsNone(renderer.render("https://e.test/", "ua"))


# =========================================================================== HTML extraction

class TestHtmlExtraction(unittest.TestCase):

    def test_malformed_html_degrades_rather_than_failing(self):
        result = htmlparse.extract("<html><body><p>unclosed<div><h1>Title", {})
        self.assertEqual(result["headings"][0]["text"], "Title")

    def test_jsonld_parse_error_is_recorded_not_raised(self):
        result = htmlparse.extract(
            '<script type="application/ld+json">{"a":}</script>', {})
        block = result["structured_data"]["jsonld"][0]
        self.assertFalse(block["parse_ok"])
        self.assertIsNotNone(block["error"])

    def test_graph_is_traversed(self):
        html = ('<script type="application/ld+json">'
                '{"@context":"https://schema.org","@graph":'
                '[{"@type":"Organization","name":"X"},{"@type":"WebSite"}]}</script>')
        result = htmlparse.extract(html, {})
        nodes = htmlparse.flatten_jsonld(result["structured_data"]["jsonld"])
        types = [t for node in nodes for t in htmlparse.types_of(node)]
        self.assertIn("Organization", types)
        self.assertIn("WebSite", types)

    def test_microdata_values_are_captured_not_just_counted(self):
        """A value-versus-visible-text check on a Microdata-only site needs the values."""
        html = ('<div itemscope itemtype="https://schema.org/Product">'
                '<h1 itemprop="name">Alpha</h1>'
                '<div itemprop="offers" itemscope itemtype="https://schema.org/Offer">'
                '<meta itemprop="price" content="59.00">'
                '<meta itemprop="priceCurrency" content="GBP"></div></div>')
        items = htmlparse.extract(html, {})["structured_data"]["microdata_items"]
        product = next(i for i in items if i["itemtype"].endswith("Product"))
        offer = next(i for i in items if i["itemtype"].endswith("Offer"))
        self.assertEqual(product["props"]["name"], "Alpha")
        self.assertEqual(offer["props"]["price"], "59.00")
        self.assertNotIn("offers", offer["props"],
                         "a nested item must not swallow the property that names it")

    def test_microdata_and_rdfa_are_captured(self):
        result = htmlparse.extract(
            '<div itemscope itemtype="https://schema.org/Product">'
            '<span itemprop="name">A</span></div>', {})
        self.assertEqual(result["structured_data"]["microdata_types"],
                         ["https://schema.org/Product"])
        self.assertEqual(result["structured_data"]["microdata_props"], 1)

    def test_empty_main_landmark_is_not_masked_by_page_chrome(self):
        html = ("<html><body><header>Site name</header><main><div id='app'></div></main>"
                "<footer>Legal</footer></body></html>")
        result = htmlparse.extract(html, CONFIG["spa_signals"])
        self.assertEqual(result["main_text_len"], 0)
        self.assertGreater(result["text_len"], 0)

    def test_script_content_is_measured_never_evaluated(self):
        result = htmlparse.extract(
            "<html><body><script>window.x=1</script><p>Hi</p></body></html>", {})
        self.assertGreater(result["script_bytes"], 0)
        self.assertNotIn("window.x", result["text"])


# ==================================================================== budgets and fetching

class TestBudget(unittest.TestCase):

    def test_request_cap_is_enforced(self):
        budget = collect.Budget(2, time.time() + 60)
        self.assertTrue(budget.take())
        self.assertTrue(budget.take())
        self.assertFalse(budget.take())
        self.assertIn("request cap", budget.exhausted_reason)

    def test_deadline_is_enforced(self):
        budget = collect.Budget(100, time.time() - 1)
        self.assertFalse(budget.take())
        self.assertIn("time budget", budget.exhausted_reason)

    def test_only_get_and_head_are_permitted(self):
        fetcher = collect.Fetcher(CONFIG, collect.Budget(10, time.time() + 30), "ua")
        with self.assertRaises(ValueError):
            fetcher.fetch("http://localhost/", method="POST")

    def test_unreachable_host_fails_cleanly(self):
        fetcher = collect.Fetcher(CONFIG, collect.Budget(10, time.time() + 30), "ua")
        result = fetcher.fetch("http://this-host-does-not-exist.invalid/")
        self.assertIsNone(result["status"])
        self.assertIsNotNone(result["error"])


# ================================================================ end to end, live fixtures

def run_collect(fixture, extra=()):
    directory = os.path.join(FIXTURES, fixture)
    workdir = tempfile.mkdtemp(prefix="collect-test-")
    out = os.path.join(workdir, "snapshot.json")
    with FixtureServer(directory) as server:
        started = time.time()
        proc = subprocess.run(
            [sys.executable, COLLECT, "--url", server.base_url, "--out", out,
             "--render", "off"] + list(extra),
            capture_output=True, text=True, timeout=180)
        elapsed = time.time() - started
    if proc.returncode != 0 or not os.path.isfile(out):
        raise AssertionError("collector failed on %s: %s" % (fixture, proc.stderr[-500:]))
    with open(out, "r", encoding="utf-8") as handle:
        return json.load(handle), elapsed


class TestEndToEnd(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.clean, cls.clean_seconds = run_collect("F00-clean-control")

    def test_snapshot_carries_every_contract_field(self):
        for field in ("schema_version", "site", "origin", "entry_url", "audited_at",
                      "capabilities", "robots", "sitemaps", "discovery", "clusters",
                      "site_archetype", "sampled_urls", "pages", "phase_timings",
                      "coverage"):
            self.assertIn(field, self.clean, field)
        for field in ("pages_discovered", "pages_sampled", "pages_fetched",
                      "pages_rendered", "blocked_by_robots", "fetch_failures",
                      "requests_made", "template_clusters", "site_archetype",
                      "capabilities", "not_assessed", "degradations"):
            self.assertIn(field, self.clean["coverage"], field)

    def test_every_page_carries_the_evidence_a_detector_will_need(self):
        page = next(p for p in self.clean["pages"] if p["url"].endswith("alpha.html"))
        for field in ("url", "final_url", "status", "status_chain", "headers",
                      "content_type", "bytes", "raw_html", "raw_text", "raw_text_len",
                      "main_text_len", "structured_data", "links_internal", "images",
                      "headings", "canonical", "lang", "page_type",
                      "page_type_confidence", "cluster_id", "control_fetch", "render",
                      "spa_signals", "documents", "elapsed_ms"):
            self.assertIn(field, page, field)

    def test_page_types_are_classified_correctly_on_a_known_site(self):
        types = {p["url"].rsplit("8099", 1)[-1]: p["page_type"]
                 for p in self.clean["pages"]}
        self.assertEqual(types["/"], "homepage")
        self.assertEqual(types["/products/alpha.html"], "product")
        self.assertEqual(types["/contact.html"], "contact")
        self.assertEqual(self.clean["site_archetype"], "ecommerce")

    def test_product_template_reaches_the_cluster_threshold(self):
        products = next(c for c in self.clean["clusters"]
                        if c["skeleton"] == "/products/{slug}.html")
        self.assertGreaterEqual(products["size"], 3)
        self.assertEqual(products["page_type"], "product")

    def test_rendering_off_is_recorded_and_never_faked(self):
        self.assertFalse(self.clean["capabilities"]["headless_render"])
        self.assertTrue(all(p["render"] is None for p in self.clean["pages"]))
        dimensions = {i["dimension"] for i in self.clean["coverage"]["not_assessed"]}
        self.assertIn("browser render comparison", dimensions)

    def test_control_fetch_runs_and_is_disclosed(self):
        page = self.clean["pages"][0]
        self.assertIsNotNone(page["control_fetch"])
        self.assertIn("disclosed", page["control_fetch"]["user_agent"])

    def test_request_budget_is_respected(self):
        coverage = self.clean["coverage"]
        self.assertLessEqual(coverage["requests_made"], coverage["request_cap"])

    def test_runtime_is_far_inside_the_limit(self):
        self.assertLess(self.clean_seconds, 60)

    def test_snapshot_is_deterministic_across_runs(self):
        second, _ = run_collect("F00-clean-control")

        def signature(snapshot):
            return json.dumps({
                "sampled": snapshot["sampled_urls"],
                "clusters": [(c["id"], c["skeleton"], c["size"], c["page_type"])
                             for c in snapshot["clusters"]],
                "pages": [(p["url"], p["status"], p["page_type"], p["raw_text_len"],
                           p["cluster_id"]) for p in snapshot["pages"]],
                "archetype": snapshot["site_archetype"],
                "robots": snapshot["robots"]["agent_verdicts"],
            }, sort_keys=True)

        self.assertEqual(signature(self.clean), signature(second))

    def test_robots_verdicts_and_matched_rules_are_captured(self):
        snapshot, _ = run_collect("F02-robots-blocks-retrieval")
        verdicts = snapshot["robots"]["agent_verdicts"]
        self.assertEqual(verdicts["OAI-SearchBot"], "disallow")
        self.assertEqual(verdicts["GPTBot"], "allow")
        rule = snapshot["robots"]["matched_rules"]["OAI-SearchBot"]["rule"]
        self.assertIsNotNone(rule["line"])
        self.assertEqual(rule["directive"], "disallow")

    def test_training_only_block_is_captured_without_interpretation(self):
        snapshot, _ = run_collect("F03-robots-blocks-training-only")
        verdicts = snapshot["robots"]["agent_verdicts"]
        self.assertEqual(verdicts["GPTBot"], "disallow")
        self.assertEqual(verdicts["OAI-SearchBot"], "allow")
        self.assertEqual(verdicts["PerplexityBot"], "allow")

    def test_collector_obeys_robots_for_its_own_fetching(self):
        snapshot, _ = run_collect("F00-clean-control")
        fetched = {p["url"] for p in snapshot["pages"]}
        self.assertFalse(any(url.endswith("/search.html") for url in fetched),
                         "a URL disallowed by robots.txt must never be fetched")

    def test_redirect_chain_is_preserved_as_evidence(self):
        snapshot, _ = run_collect("F05-deeplink-redirect")
        redirected = [p for p in snapshot["pages"] if p["redirected"]]
        self.assertTrue(redirected, "the fixture redirects product deep links")
        page = redirected[0]
        self.assertTrue(page["final_url"].rstrip("/").endswith("8099"))
        self.assertGreaterEqual(page["redirect_count"], 1)
        self.assertEqual(page["status_chain"][0]["status"], 302)

    def test_blocking_site_yields_no_invented_content(self):
        snapshot, _ = run_collect("F12-ua-blocked")
        self.assertEqual(snapshot["coverage"]["pages_fetched"], 0)
        for page in snapshot["pages"]:
            self.assertFalse(page["fetch_ok"])
            self.assertNotIn("raw_text", page)
        self.assertTrue(snapshot["coverage"]["degradations"])

    def test_client_rendered_site_yields_static_signals(self):
        snapshot, _ = run_collect("F01-csr-shell")
        product = next(p for p in snapshot["pages"] if p["url"].endswith("alpha.html"))
        weights = [s["weight"] for s in product["spa_signals"]]
        self.assertGreaterEqual(weights.count("high"), 2)

    def test_small_site_completes_without_inventing_templates(self):
        snapshot, _ = run_collect("F09-small-site-clean")
        self.assertEqual(snapshot["coverage"]["pages_fetched"], 2)
        self.assertTrue(all(c["size"] < 3 for c in snapshot["clusters"]))

    def test_non_english_site_is_captured_with_its_language(self):
        snapshot, _ = run_collect("F08-non-english-clean")
        langs = {p.get("lang") for p in snapshot["pages"] if p["fetch_ok"]}
        self.assertEqual(langs, {"fr"})

    def test_robots_disallowing_everything_stops_the_crawl_entirely(self):
        """The entry URL must be robots-checked before it is probed, not after."""
        import shutil
        source = os.path.join(FIXTURES, "F00-clean-control")
        workdir = tempfile.mkdtemp(prefix="robots-block-")
        target = os.path.join(workdir, "site")
        shutil.copytree(source, target)
        with open(os.path.join(target, "robots.txt"), "w", encoding="utf-8") as handle:
            handle.write("User-agent: *\nDisallow: /\n")
        out = os.path.join(workdir, "snapshot.json")
        with FixtureServer(target) as server:
            proc = subprocess.run(
                [sys.executable, COLLECT, "--url", server.base_url, "--out", out,
                 "--render", "off"], capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0)
        with open(out, "r", encoding="utf-8") as handle:
            snapshot = json.load(handle)
        self.assertEqual(snapshot["coverage"]["pages_fetched"], 0)
        self.assertEqual(snapshot["pages"], [])
        self.assertGreaterEqual(snapshot["coverage"]["blocked_by_robots"], 1)
        self.assertEqual(snapshot["discovery"]["method"], "blocked-by-robots")
        blocked = snapshot["coverage"]["blocked_urls"][0]
        self.assertEqual(blocked["matched_rule"]["directive"], "disallow")
        self.assertIsNotNone(blocked["matched_rule"]["line"])
        # Only robots.txt itself should ever have been requested.
        self.assertLessEqual(snapshot["coverage"]["requests_made"], 2)

    def test_query_preservation_is_probed_when_something_redirects(self):
        snapshot, _ = run_collect("F05-deeplink-redirect")
        probed = [p for p in snapshot["pages"] if p.get("query_preservation")]
        self.assertTrue(probed, "a redirecting URL must be probed for parameter loss")
        self.assertFalse(probed[0]["query_preservation"]["parameter_survived"],
                         "this fixture drops the query on redirect")

    def test_query_preservation_records_not_assessed_when_nothing_redirects(self):
        dimensions = {i["dimension"] for i in self.clean["coverage"]["not_assessed"]}
        self.assertIn("inbound parameter preservation", dimensions)

    def test_link_discovery_cannot_exhaust_the_request_budget(self):
        """Without a sitemap, crawling must leave budget for the pages it discovers."""
        import shutil
        workdir = tempfile.mkdtemp(prefix="nositemap-")
        site = os.path.join(workdir, "site")
        os.makedirs(os.path.join(site, "p"))
        links = "".join('<a href="/p/item-%03d.html">i</a>' % i for i in range(80))
        with open(os.path.join(site, "index.html"), "w", encoding="utf-8") as handle:
            handle.write("<html lang='en'><head><title>H</title></head><body><main>"
                         "<h1>H</h1>%s</main></body></html>" % links)
        for index in range(80):
            with open(os.path.join(site, "p", "item-%03d.html" % index), "w",
                      encoding="utf-8") as handle:
                handle.write("<html lang='en'><head><title>I%d</title></head><body><main>"
                             "<h1>Item %d</h1><p>%s</p>%s</main></body></html>"
                             % (index, index, "text " * 60, links))
        with open(os.path.join(site, "robots.txt"), "w", encoding="utf-8") as handle:
            handle.write("User-agent: *\nAllow: /\n")
        out = os.path.join(workdir, "snapshot.json")
        with FixtureServer(site) as server:
            proc = subprocess.run(
                [sys.executable, COLLECT, "--url", server.base_url, "--out", out,
                 "--render", "off", "--max-pages", "20"],
                capture_output=True, text=True, timeout=180)
        self.assertEqual(proc.returncode, 0, proc.stderr[-400:])
        with open(out, "r", encoding="utf-8") as handle:
            snapshot = json.load(handle)
        coverage = snapshot["coverage"]
        self.assertEqual(snapshot["discovery"]["method"], "crawl")
        self.assertEqual(coverage["pages_fetched"], 20,
                         "discovery must not starve the sampling phase")
        self.assertLessEqual(coverage["requests_made"], coverage["request_cap"])
        shutil.rmtree(workdir, ignore_errors=True)

    def test_max_pages_is_honoured(self):
        snapshot, _ = run_collect("F00-clean-control", extra=["--max-pages", "4"])
        self.assertLessEqual(snapshot["coverage"]["pages_sampled"], 4)
        self.assertEqual(snapshot["sampled_urls"][0], snapshot["entry_url"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
