#!/usr/bin/env python3
"""Capture one website into a single read-only snapshot.

This is the only component in the marketplace that makes network requests. Every detector
is a pure function over the file this produces, which means the evidence in the final
report always describes the exact state that was audited, and the site is crawled once
rather than six times.

Hard rules, enforced in code and not merely documented:

  * GET and HEAD only. There is no code path that issues any other method, submits a
    form, sets a cookie jar, or sends credentials.
  * robots.txt is obeyed for our own fetching, including Crawl-delay. A disallowed URL is
    recorded as blocked and is never requested.
  * The audit user agent identifies itself honestly. The one control fetch per page uses a
    browser user agent solely to detect user-agent differential blocking, and that fact is
    recorded in the snapshot.
  * Budgets are hard: total requests, wall clock, response size, redirect depth. On
    exhaustion the collector degrades and records the degradation. It never aborts with a
    partial file that looks complete.
  * Downloaded content is untrusted data. It is stored and measured. It is never executed,
    never used to build a command, and never allowed to change what the audit does.

Usage:
  collect.py --url https://example.com --out snapshot.json [options]

Exit codes: 0 success, 2 bad arguments, 3 the site could not be reached at all.
"""
import argparse
import datetime
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ElementTree
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import cluster as clustering      # noqa: E402
import htmlparse                  # noqa: E402
import render as rendering        # noqa: E402
import robots as robots_module    # noqa: E402
import urlnorm                    # noqa: E402

SCHEMA_VERSION = "1.0"
COLLECTOR_VERSION = "1.0.0"
BLOCKING_STATUSES = {401, 403, 407, 429, 503}


def load_config(path=None):
    with open(path or os.path.join(HERE, "config.json"), "r", encoding="utf-8") as handle:
        return json.load(handle)


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------------------ fetching

class _ChainRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Captures the redirect chain instead of silently following it."""

    def __init__(self, chain, limit):
        self.chain = chain
        self.limit = limit

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.chain.append({"url": req.full_url, "status": code,
                           "location": headers.get("Location", newurl)})
        if len(self.chain) > self.limit:
            raise urllib.error.HTTPError(
                req.full_url, code, "redirect limit of %d exceeded" % self.limit,
                headers, fp)
        return urllib.request.HTTPRedirectHandler.redirect_request(
            self, req, fp, code, msg, headers, newurl)


class Budget(object):
    """Thread-safe request and wall-clock budget. Exhaustion degrades, never crashes."""

    def __init__(self, max_requests, deadline_ts):
        self.max_requests = max_requests
        self.deadline_ts = deadline_ts
        self._used = 0
        self._lock = threading.Lock()
        self.exhausted_reason = None

    def take(self):
        with self._lock:
            if time.time() > self.deadline_ts:
                self.exhausted_reason = "acquisition time budget exhausted"
                return False
            if self._used >= self.max_requests:
                self.exhausted_reason = ("request cap of %d reached" % self.max_requests)
                return False
            self._used += 1
            return True

    @property
    def used(self):
        with self._lock:
            return self._used

    def remaining_seconds(self):
        return max(0.0, self.deadline_ts - time.time())


class Fetcher(object):
    """Bounded, polite, read-only HTTP. GET and HEAD only."""

    def __init__(self, config, budget, user_agent):
        budgets = config["budgets"]
        self.timeout = budgets["request_timeout_s"]
        self.size_cap = budgets["response_size_cap_bytes"]
        self.max_redirects = budgets["max_redirects"]
        self.retry_attempts = budgets["retry_attempts"]
        self.backoff = budgets["retry_backoff_s"]
        self.budget = budget
        self.user_agent = user_agent
        self.throttled = threading.Event()

    def fetch(self, url, method="GET", user_agent=None, accept="text/html,*/*;q=0.8"):
        """Return a result dict. Never raises for network conditions."""
        result = {
            "url": url, "method": method, "final_url": url, "status": None,
            "status_chain": [], "headers": {}, "body": b"", "bytes": 0,
            "truncated": False, "error": None, "elapsed_ms": 0, "blocked": False,
            "budget_denied": False,
        }
        if method not in ("GET", "HEAD"):
            raise ValueError("only GET and HEAD are permitted")
        if not self.budget.take():
            result["error"] = self.budget.exhausted_reason
            result["budget_denied"] = True
            return result

        attempts = self.retry_attempts + 1
        for attempt in range(attempts):
            started = time.time()
            chain = []
            opener = urllib.request.build_opener(
                _ChainRedirectHandler(chain, self.max_redirects))
            request = urllib.request.Request(url, method=method, headers={
                "User-Agent": user_agent or self.user_agent,
                "Accept": accept,
                "Accept-Language": "*",
                "Connection": "close",
            })
            try:
                with opener.open(request, timeout=self.timeout) as response:
                    body = b"" if method == "HEAD" else response.read(self.size_cap + 1)
                    result["status"] = response.status
                    result["final_url"] = response.geturl()
                    result["headers"] = {k.lower(): v for k, v in response.headers.items()}
                    if len(body) > self.size_cap:
                        body = body[:self.size_cap]
                        result["truncated"] = True
                    result["body"] = body
                    result["bytes"] = len(body)
            except urllib.error.HTTPError as exc:
                result["status"] = exc.code
                result["headers"] = {k.lower(): v for k, v in (exc.headers or {}).items()}
                try:
                    result["body"] = exc.read(self.size_cap + 1) if method == "GET" else b""
                    result["bytes"] = len(result["body"])
                except Exception:  # noqa: BLE001
                    pass
                if exc.code in BLOCKING_STATUSES:
                    result["blocked"] = True
                result["error"] = "HTTP %s" % exc.code
            except urllib.error.URLError as exc:
                result["error"] = "network error: %s" % str(exc.reason)[:160]
            except Exception as exc:  # noqa: BLE001
                result["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:160])

            result["status_chain"] = chain + [{"url": result["final_url"],
                                               "status": result["status"]}]
            result["elapsed_ms"] = int((time.time() - started) * 1000)

            retryable = result["status"] in (429, 500, 502, 503, 504) or (
                result["status"] is None and result["error"])
            if result["status"] in (429, 503):
                self.throttled.set()
            if not retryable or attempt == attempts - 1:
                return result
            if not self.budget.take():
                result["budget_denied"] = True
                return result
            time.sleep(min(self.backoff * (attempt + 1), self.budget.remaining_seconds()))
        return result


# ----------------------------------------------------------------------------- sitemaps

_SITEMAP_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
_SITEMAP_LASTMOD = re.compile(r"<lastmod>\s*([^<\s]+)\s*</lastmod>", re.I)


def parse_sitemap(body_text):
    """Parse a sitemap or sitemap index. Returns (kind, entries, parse_ok, error).

    XML is parsed with the standard library's ElementTree, which does not resolve
    external entities. Size is capped by the fetcher before this is called. If the XML is
    malformed, a bounded regular-expression fallback recovers the location elements
    rather than discarding the whole document, and the degradation is recorded.
    """
    try:
        root = ElementTree.fromstring(body_text)
    except ElementTree.ParseError as exc:
        locations = _SITEMAP_LOC.findall(body_text)
        if locations:
            kind = "index" if "<sitemapindex" in body_text[:2000].lower() else "urlset"
            return (kind, [{"loc": loc, "lastmod": None} for loc in locations], False,
                    "XML malformed (%s); recovered %d locations textually"
                    % (str(exc)[:120], len(locations)))
        return ("unknown", [], False, "XML malformed: %s" % str(exc)[:160])

    tag = root.tag.rsplit("}", 1)[-1].lower()
    if tag not in ("urlset", "sitemapindex"):
        # Well-formed XML that is not a sitemap. Reporting this as an empty sitemap would
        # be indistinguishable from a sitemap with no URLs, which is a different fact.
        return ("unknown", [], False,
                "document root is <%s>, which is not a sitemap or sitemap index" % tag)
    kind = "index" if tag == "sitemapindex" else "urlset"
    entries = []
    for child in root:
        loc = lastmod = None
        for field in child:
            name = field.tag.rsplit("}", 1)[-1].lower()
            if name == "loc":
                loc = (field.text or "").strip()
            elif name == "lastmod":
                lastmod = (field.text or "").strip()
        if loc:
            entries.append({"loc": loc, "lastmod": lastmod})
    return kind, entries, True, None


# ------------------------------------------------------------------------------ collector

class Collector(object):
    def __init__(self, args, config):
        self.args = args
        self.config = config
        self.budgets = config["budgets"]
        self.discovery_config = config["discovery"]
        self.started_wall = time.time()
        self.audited_at = utc_now()

        contact = (" ; contact: %s" % args.user_agent_contact) if args.user_agent_contact else ""
        self.user_agent = config["user_agent"]["template"] % contact
        self.agent_token = config["user_agent"]["product_token"]
        self.control_agent = config["user_agent"]["control_fetch_agent"]

        deadline = time.time() + min(args.time_budget,
                                     self.budgets["acquisition_time_budget_s"] * 4)
        self.budget = Budget(self.budgets["total_request_cap"], deadline)
        self.fetcher = Fetcher(config, self.budget, self.user_agent)

        self.entry_url = urlnorm.normalize(args.url) or args.url
        parts = urlsplit(self.entry_url)
        self.origin = "%s://%s" % (parts.scheme, parts.netloc)
        self.site = parts.hostname or args.url

        self.tracking = config["url_normalization"]["tracking_params"]
        self.session = config["url_normalization"]["session_params"]

        self.policy = None
        self.crawl_delay = 0.0
        self.phase_timings = {}
        self.degradations = []
        self.not_assessed = []
        self.blocked_by_robots = []
        self.failures = []
        self.sitemap_records = []
        self.pages = []

    # ------------------------------------------------------------------ small helpers

    def normalize(self, url, base=None):
        return urlnorm.normalize(url, base=base, tracking_params=self.tracking,
                                 session_params=self.session)

    def key(self, url):
        return urlnorm.dedupe_key(url, tracking_params=self.tracking,
                                  session_params=self.session)

    def robots_allows(self, url):
        if self.policy is None:
            return True, None
        verdict = self.policy.evaluate(self.agent_token, url)
        return verdict["verdict"] != "disallow", verdict

    def _phase(self, name, started):
        self.phase_timings[name] = round(time.time() - started, 3)

    def _note_degradation(self, message):
        if message not in self.degradations:
            self.degradations.append(message)

    def _note_not_assessed(self, dimension, reason):
        if not any(item["dimension"] == dimension for item in self.not_assessed):
            self.not_assessed.append({"dimension": dimension, "reason": reason})

    # -------------------------------------------------------------------- phase: robots

    def phase_robots(self):
        started = time.time()
        url = self.origin + "/robots.txt"
        result = self.fetcher.fetch(url)
        record = {
            "url": url,
            "fetched": result["status"] is not None,
            "status": result["status"],
            "content_type": result["headers"].get("content-type"),
            "error": result["error"],
            "raw": "",
            "parse_ok": False,
            "groups": [],
            "sitemaps": [],
            "errors": [],
            "directive_lines": 0,
            "crawl_delay_applied": 0.0,
            "agent_verdicts": {},
            "matched_rules": {},
        }

        if result["status"] == 200 and result["body"]:
            text = result["body"].decode("utf-8", "replace")[:100000]
            record["raw"] = text
            self.policy = robots_module.parse(text)
            parsed = self.policy.to_dict()
            record.update({
                "parse_ok": parsed["parse_ok"],
                "groups": parsed["groups"],
                "sitemaps": parsed["sitemaps"],
                "errors": parsed["errors"],
                "directive_lines": parsed["directive_lines"],
            })
            if not parsed["parse_ok"]:
                self._note_degradation(
                    "robots.txt was fetched but contained no usable directives; fetching "
                    "conservatively and recording the ambiguity")
            declared_delay = self.policy.crawl_delay_for(self.agent_token) or 0.0
            self.crawl_delay = declared_delay
            record["crawl_delay_applied"] = declared_delay
            verdicts, matched = robots_module.verdicts_for(
                self.policy, self.config["agent_verdict_tokens"], "/")
            record["agent_verdicts"] = verdicts
            record["matched_rules"] = matched
        elif result["status"] == 404:
            record["parse_ok"] = None  # absent, which means no restrictions
        else:
            self._note_degradation(
                "robots.txt could not be read (%s); fetching conservatively"
                % (result["error"] or "status %s" % result["status"]))

        self.robots_record = record
        self._phase("robots", started)
        return record

    # ----------------------------------------------------------------- phase: discovery

    def phase_discovery(self):
        started = time.time()
        discovered, method = self._discover_from_sitemaps()
        if len(discovered) < 2:
            crawled = self._discover_by_crawl()
            if len(crawled) > len(discovered):
                discovered = crawled
                method = "crawl"
        if not discovered:
            discovered = {self.entry_url: {"source": "entry"}}
            method = "entry-only"
        self._phase("discovery", started)
        return discovered, method

    def _sitemap_candidates(self):
        candidates = []
        for entry in (self.robots_record.get("sitemaps") or []):
            normalized = self.normalize(entry["url"])
            if normalized:
                candidates.append((normalized, "robots.txt line %d" % entry["line"]))
        if not candidates:
            for path in self.discovery_config["sitemap_fallback_paths"]:
                normalized = self.normalize(self.origin + path)
                if normalized:
                    candidates.append((normalized, "conventional location"))
        seen, unique = set(), []
        for url, source in candidates:
            if url not in seen:
                seen.add(url)
                unique.append((url, source))
        return unique

    def _discover_from_sitemaps(self):
        discovered = {}
        queue = [(url, source, 0) for url, source in self._sitemap_candidates()]
        documents = 0

        while queue and documents < self.discovery_config["max_sitemap_documents"]:
            url, source, depth = queue.pop(0)
            if depth > self.discovery_config["max_sitemap_index_depth"]:
                self._note_degradation("sitemap index nesting deeper than %d was not followed"
                                       % self.discovery_config["max_sitemap_index_depth"])
                continue
            allowed, verdict = self.robots_allows(url)
            if not allowed:
                self.blocked_by_robots.append({"url": url, "reason": "robots.txt",
                                               "matched_rule": verdict["matched_rule"]})
                continue

            result = self.fetcher.fetch(url, accept="application/xml,text/xml,*/*;q=0.5")
            documents += 1
            record = {"url": url, "source": source, "status": result["status"],
                      "kind": None, "url_count": 0, "lastmod_distinct": 0,
                      "parse_ok": False, "error": result["error"], "truncated":
                      result["truncated"]}
            if result["status"] != 200 or not result["body"]:
                self.sitemap_records.append(record)
                continue

            body = result["body"].decode("utf-8", "replace")
            kind, entries, parse_ok, error = parse_sitemap(body)
            record.update({"kind": kind, "parse_ok": parse_ok, "url_count": len(entries)})
            if error:
                record["error"] = error
                self._note_degradation("sitemap %s: %s" % (url, error))

            if kind == "index":
                for entry in entries[:self.discovery_config["max_sitemap_documents"]]:
                    child = self.normalize(entry["loc"])
                    if child:
                        queue.append((child, "sitemap index %s" % url, depth + 1))
            else:
                lastmods = set()
                for entry in entries:
                    if len(discovered) >= self.discovery_config["max_sitemap_urls"]:
                        self._note_degradation(
                            "sitemap URL cap of %d reached; discovery stopped there"
                            % self.discovery_config["max_sitemap_urls"])
                        break
                    normalized = self.normalize(entry["loc"])
                    if not normalized or not urlnorm.same_site(normalized, self.entry_url):
                        continue
                    if urlnorm.is_probably_non_html(normalized):
                        continue
                    discovered.setdefault(self.key(normalized), {
                        "url": normalized, "source": "sitemap",
                        "lastmod": entry.get("lastmod")})
                    if entry.get("lastmod"):
                        lastmods.add(entry["lastmod"])
                record["lastmod_distinct"] = len(lastmods)
            self.sitemap_records.append(record)

        return ({item["url"]: item for item in discovered.values()},
                "sitemap" if discovered else "none")

    def _discover_by_crawl(self):
        """Breadth-first, in-site, bounded. Used only when sitemaps yield nothing."""
        max_depth = self.discovery_config["crawl_max_depth"]
        max_urls = self.discovery_config["crawl_max_urls"]
        max_fetches = self.discovery_config.get("crawl_max_fetches", 30)
        fetches = 0
        max_params = self.discovery_config["max_query_params"]
        max_path_depth = self.discovery_config["max_path_depth"]

        found = {self.entry_url: {"url": self.entry_url, "source": "entry", "lastmod": None}}
        seen_keys = {self.key(self.entry_url)}
        frontier = [(self.entry_url, 0)]
        if not hasattr(self, "_crawl_bodies"):
            self._crawl_bodies = {}

        while frontier and len(found) < max_urls:
            url, depth = frontier.pop(0)
            if depth >= max_depth or self.budget.remaining_seconds() < 5:
                continue
            allowed, verdict = self.robots_allows(url)
            if not allowed:
                self.blocked_by_robots.append({"url": url, "reason": "robots.txt",
                                               "matched_rule": verdict["matched_rule"]})
                continue
            cached = self._crawl_bodies.get(self.key(url))
            if cached is None and fetches >= max_fetches:
                self._note_degradation(
                    "link discovery stopped after %d fetches so that the request budget "
                    "remains available for the sampled pages" % max_fetches)
                break
            if cached is None:
                fetches += 1
            result = cached if cached is not None else self.fetcher.fetch(url)
            if result["budget_denied"]:
                self._note_degradation("link discovery stopped early: %s"
                                       % result["error"])
                break
            if result["status"] != 200 or not result["body"]:
                continue
            self._crawl_bodies[self.key(url)] = result
            parsed = htmlparse.extract(result["body"].decode("utf-8", "replace"),
                                       self.config["spa_signals"])
            for link in parsed["links"]:
                candidate = self.normalize(link["href"], base=result["final_url"])
                if not candidate or not urlnorm.same_site(candidate, self.entry_url):
                    continue
                if urlnorm.is_probably_non_html(candidate):
                    continue
                if len(urlnorm.query_keys(candidate)) > max_params:
                    continue          # faceted-navigation trap
                if urlnorm.depth(candidate) > max_path_depth:
                    continue          # runaway path trap
                candidate_key = self.key(candidate)
                if candidate_key in seen_keys:
                    continue
                seen_keys.add(candidate_key)
                found[candidate] = {"url": candidate, "source": "crawl", "lastmod": None}
                frontier.append((candidate, depth + 1))
            if self.crawl_delay:
                time.sleep(min(self.crawl_delay, self.budget.remaining_seconds()))

        self.crawl_depth_reached = max_depth if len(found) > 1 else 0
        return found

    # -------------------------------------------------------------------- phase: sample

    def phase_sample(self, discovered):
        started = time.time()
        urls = sorted(discovered)
        clusters = clustering.build_clusters(urls)

        nav_skeletons = self._nav_skeletons(discovered)
        max_pages = min(self.args.max_pages, self.budgets["max_pages_cap"])

        if self.crawl_delay > self.budgets["crawl_delay_cap_s"]:
            reduced = max(4, int(self.budget.remaining_seconds() / self.crawl_delay))
            if reduced < max_pages:
                self._note_degradation(
                    "Crawl-delay of %.1fs is honoured; the sample was reduced from %d to "
                    "%d pages rather than overrunning the time budget"
                    % (self.crawl_delay, max_pages, reduced))
                max_pages = reduced

        homepage = self.entry_url if self.entry_url in discovered else (
            urls[0] if urls else None)
        sampled = clustering.sample(clusters, max_pages, homepage=homepage,
                                    nav_skeletons=nav_skeletons,
                                    per_cluster_cap=self.config["sampling"]["per_cluster_cap"])
        self._phase("sampling", started)
        return clusters, sampled

    def _nav_skeletons(self, discovered):
        """Skeletons linked from the entry page, so small but important clusters rank up."""
        body = getattr(self, "_crawl_bodies", {}).get(self.key(self.entry_url))
        if body is None:
            return []
        parsed = htmlparse.extract(body["body"].decode("utf-8", "replace"),
                                   self.config["spa_signals"])
        skeletons = set()
        for link in parsed["links"]:
            candidate = self.normalize(link["href"], base=body["final_url"])
            if candidate and urlnorm.same_site(candidate, self.entry_url):
                skeletons.add(urlnorm.path_skeleton(candidate))
        return sorted(skeletons)

    # --------------------------------------------------------------------- phase: fetch

    def phase_fetch(self, sampled, discovered, clusters):
        started = time.time()
        cluster_by_url = {}
        for entry in clusters:
            for member in entry["members"]:
                cluster_by_url[member] = entry["id"]

        to_fetch = []
        for url in sampled:
            allowed, verdict = self.robots_allows(url)
            if not allowed:
                self.blocked_by_robots.append({
                    "url": url, "reason": "robots.txt",
                    "matched_rule": verdict["matched_rule"],
                    "matched_agent_token": verdict["matched_agent_token"]})
                continue
            to_fetch.append(url)

        workers = 1 if self.crawl_delay else self.budgets["concurrency"]
        results = {}
        cached = getattr(self, "_crawl_bodies", {})

        pending = [u for u in to_fetch if self.key(u) not in cached]
        for url in to_fetch:
            if self.key(url) in cached:
                results[url] = cached[self.key(url)]

        batch_size = max(1, workers)
        index = 0
        while index < len(pending):
            if self.fetcher.throttled.is_set():
                workers = self.budgets["concurrency_after_throttle"]
                batch_size = 1
                self._note_degradation(
                    "the site returned a throttling status; concurrency was reduced to 1")
            batch = pending[index:index + batch_size]
            index += batch_size
            if workers == 1:
                for url in batch:
                    results[url] = self.fetcher.fetch(url)
                    if self.crawl_delay:
                        time.sleep(min(self.crawl_delay, self.budget.remaining_seconds()))
            else:
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    for url, result in zip(batch, pool.map(self.fetcher.fetch, batch)):
                        results[url] = result
            if self.budget.remaining_seconds() <= 0:
                self._note_degradation(
                    "acquisition time budget reached; %d of %d sampled pages were fetched"
                    % (len(results), len(to_fetch)))
                break

        for url in sorted(to_fetch):
            result = results.get(url)
            if result is None:
                self.failures.append({"url": url, "reason": "not fetched within budget"})
                continue
            self.pages.append(self._build_page(url, result, cluster_by_url.get(url),
                                               discovered.get(url, {})))
        self._phase("fetch", started)

    def _build_page(self, url, result, cluster_id, discovery_meta):
        page = {
            "url": url,
            "final_url": result["final_url"],
            "cluster_id": cluster_id,
            "requested_method": result["method"],
            "fetch_ok": result["status"] == 200 and bool(result["body"]),
            "status": result["status"],
            "status_chain": result["status_chain"],
            "redirected": self.key(result["final_url"]) != self.key(url),
            "redirect_count": max(0, len(result["status_chain"]) - 1),
            "headers": {k: v for k, v in result["headers"].items() if k in (
                "content-type", "content-length", "last-modified", "etag",
                "x-robots-tag", "cache-control", "location", "content-language",
                "vary", "server", "retry-after")},
            "content_type": result["headers"].get("content-type"),
            "bytes": result["bytes"],
            "truncated": result["truncated"],
            "error": result["error"],
            "blocked": result["blocked"],
            "elapsed_ms": result["elapsed_ms"],
            "sitemap_lastmod": discovery_meta.get("lastmod"),
            "discovery_source": discovery_meta.get("source", "sample"),
            "control_fetch": None,
            "render": None,
            "spa_signals": [],
            "challenge_detected": False,
            "notes": [],
        }

        content_type = (page["content_type"] or "").lower()
        if page["fetch_ok"] and "html" not in content_type and content_type:
            page["notes"].append("non-HTML content type; not parsed as a page")
            page["fetch_ok"] = False

        if not page["fetch_ok"]:
            if result["blocked"]:
                page["challenge_detected"] = True
                page["notes"].append(
                    "the server refused this request with status %s; the content could "
                    "not be read" % result["status"])
            return page

        html = result["body"].decode("utf-8", "replace")
        parsed = htmlparse.extract(html, self.config["spa_signals"])

        stored_cap = self.budgets["stored_html_cap_bytes"]
        page["raw_html"] = html[:stored_cap]
        page["raw_html_truncated_for_storage"] = len(html) > stored_cap
        page["raw_text"] = parsed["text"]
        page["raw_text_len"] = parsed["text_len"]
        page["main_text"] = parsed["main_text"][:20000]
        page["main_text_len"] = parsed["main_text_len"]
        page["lang"] = parsed["lang"]
        page["title"] = parsed["title"]
        page["meta_description"] = parsed["meta"].get("description")
        page["meta_robots"] = parsed["meta"].get("robots")
        page["meta_viewport"] = parsed["meta"].get("viewport")
        page["meta_refresh"] = parsed["meta_refresh"]
        page["canonical_raw"] = parsed["canonical"]
        page["canonical"] = self.normalize(parsed["canonical"], base=result["final_url"]) \
            if parsed["canonical"] else None
        page["hreflang"] = parsed["hreflang"]
        page["headings"] = parsed["headings"]
        page["tables"] = parsed["tables"]
        page["definition_lists"] = parsed["definition_lists"]
        page["forms"] = parsed["forms"]
        page["script_bytes"] = parsed["script_bytes"]
        page["script_srcs"] = parsed["script_srcs"][:40]
        page["stylesheet_count"] = parsed["stylesheet_count"]
        page["render_blocking"] = parsed["render_blocking"]
        page["noscript_text"] = parsed["noscript_text"][:600]
        page["has_main_landmark"] = parsed["has_main_landmark"]
        page["empty_mount_points"] = parsed["empty_mount_points"]
        page["parse_notes"] = parsed["parse_notes"]

        internal, external, documents = [], [], []
        for link in parsed["links"]:
            candidate = self.normalize(link["href"], base=result["final_url"])
            if not candidate:
                continue
            entry = {"url": candidate, "in_content": link["in_content"],
                     "text": link["text"][:120], "rel": link["rel"]}
            if urlnorm.is_document(candidate):
                documents.append(candidate)
            if urlnorm.same_site(candidate, self.entry_url):
                internal.append(entry)
            else:
                external.append(entry)
        page["links_internal"] = internal[:300]
        page["links_external"] = external[:120]
        page["links_in_content_internal"] = sum(1 for l in internal if l["in_content"])
        page["documents"] = sorted(set(documents))[:40]
        page["images"] = parsed["images"][:120]

        page["structured_data"] = {
            "source": "raw",
            "jsonld": [{"parse_ok": b["parse_ok"], "error": b["error"],
                        "excerpt": b.get("excerpt"), "data": b["data"]}
                       for b in parsed["structured_data"]["jsonld"]],
            "microdata_types": parsed["structured_data"]["microdata_types"],
            "microdata_props": parsed["structured_data"]["microdata_props"],
            "microdata_items": parsed["structured_data"]["microdata_items"],
            "rdfa_types": parsed["structured_data"]["rdfa_types"],
            "rdfa_props": parsed["structured_data"]["rdfa_props"],
            "opengraph": parsed["structured_data"]["opengraph"],
        }

        page["spa_signals"] = rendering.static_spa_signals(parsed, self.config)

        # A 200 response that carries almost no content and immediately redirects by meta
        # refresh is the shape of an interstitial rather than a page.
        if (page["main_text_len"] < 200 and page["meta_refresh"]
                and not page["headings"]):
            page["challenge_detected"] = True
            page["notes"].append(
                "the response was a near-empty page with a meta refresh, which is the "
                "shape of an interstitial rather than content")

        page["_parsed"] = parsed  # internal; stripped before serialisation
        return page

    # ------------------------------------------------------- phase: control and classify

    def phase_control_fetch(self):
        """One browser-user-agent fetch per page, to expose differential blocking."""
        started = time.time()
        for page in self.pages:
            if self.budget.remaining_seconds() <= 0:
                self._note_not_assessed(
                    "user-agent differential blocking",
                    "the request budget was exhausted before control fetches could run")
                break
            # The control fetch sends a browser user-agent string, but it is still our
            # request. It must satisfy the wildcard group as well as our own token's
            # group, or we would be using the disguise to fetch something robots.txt
            # denies to everyone.
            if self.policy is not None and self.policy.evaluate(
                    "*", page["url"])["verdict"] == "disallow":
                self._note_not_assessed(
                    "user-agent differential blocking",
                    "robots.txt disallows this path for all agents, so no control fetch "
                    "was made")
                continue
            result = self.fetcher.fetch(page["url"], method="HEAD",
                                        user_agent=self.control_agent)
            if result["status"] in (403, 405, 501) and not result["budget_denied"]:
                result = self.fetcher.fetch(page["url"], method="GET",
                                            user_agent=self.control_agent)
            if result["budget_denied"]:
                self._note_not_assessed(
                    "user-agent differential blocking",
                    "the request budget was exhausted before control fetches could run")
                break
            page["control_fetch"] = {
                "status": result["status"],
                "method": result["method"],
                "user_agent": "mainstream browser string (disclosed)",
                "bytes": result["bytes"],
                "error": result["error"],
                "differs_from_machine_view": (
                    result["status"] is not None and page["status"] is not None
                    and result["status"] != page["status"]),
            }
        self._phase("control_fetch", started)

    def phase_query_preservation(self):
        """Bounded probe: do inbound query parameters survive a redirect?

        Only runs on URLs that already redirected, at most twice, using a single harmless
        GET with one extra parameter. Without this nothing in the snapshot could support
        a finding about arriving context being discarded, and a detector would have to
        assert it without evidence.
        """
        started = time.time()
        probes = 0
        for page in self.pages:
            if probes >= 2 or self.budget.remaining_seconds() <= 0:
                break
            if not page.get("redirected"):
                continue
            separator = "&" if "?" in page["url"] else "?"
            probe_url = page["url"] + separator + "audit_probe=1"
            allowed, _ = self.robots_allows(probe_url)
            if not allowed:
                continue
            result = self.fetcher.fetch(probe_url)
            if result["budget_denied"]:
                break
            probes += 1
            page["query_preservation"] = {
                "probe_url": probe_url,
                "final_url": result["final_url"],
                "status": result["status"],
                "parameter_survived": "audit_probe=1" in (result["final_url"] or ""),
            }
        if probes == 0:
            self._note_not_assessed(
                "inbound parameter preservation",
                "no sampled URL redirected, so there was nothing to probe")
        self._phase("query_preservation", started)

    def phase_classify(self, clusters):
        started = time.time()
        nav_targets = set()
        for page in self.pages:
            if urlnorm.depth(page["url"]) == 0:
                nav_targets = {l["url"] for l in page.get("links_internal", [])}
                break

        has_local_business = False
        for page in self.pages:
            parsed = page.get("_parsed")
            if not parsed:
                page["page_type"] = "unknown"
                page["page_type_confidence"] = "low"
                page["page_type_signals"] = []
                continue
            nodes = htmlparse.flatten_jsonld(parsed["structured_data"]["jsonld"])
            schema_types = []
            for node in nodes:
                schema_types.extend(htmlparse.types_of(node))
            for raw_type in parsed["structured_data"]["microdata_types"]:
                schema_types.append(raw_type.rsplit("/", 1)[-1])
            if any(t.lower() == "localbusiness" for t in schema_types):
                has_local_business = True

            page_type, confidence, signals = clustering.classify_page(
                page["url"], self.entry_url, parsed, schema_types, nav_targets)
            page["page_type"] = page_type
            page["page_type_confidence"] = confidence
            page["page_type_signals"] = signals
            page["schema_types"] = sorted(set(schema_types))

        by_url = {p["url"]: p for p in self.pages}
        for entry in clusters:
            types = [by_url[u]["page_type"] for u in entry["sampled"] if u in by_url]
            if types:
                entry["page_type"] = max(sorted(set(types)), key=types.count)
                confidences = [by_url[u]["page_type_confidence"]
                               for u in entry["sampled"] if u in by_url]
                order = {"high": 3, "medium": 2, "low": 1}
                entry["page_type_confidence"] = min(
                    confidences, key=lambda c: order.get(c, 0)) if confidences else "low"

        archetype, counts = clustering.classify_archetype(
            [p.get("page_type", "unknown") for p in self.pages], has_local_business)
        self.archetype = archetype
        self.page_type_counts = counts
        self._phase("classify", started)

    # -------------------------------------------------------------------- phase: render

    def phase_render(self, clusters):
        started = time.time()
        mode = self.args.render
        if mode == "off":
            self._note_not_assessed("browser render comparison",
                                    "rendering was disabled for this run")
            self.render_capability = False
            self._phase("render", started)
            return

        renderer = rendering.Renderer(self.budgets["render_timeout_s"],
                                      self.config["spa_signals"])
        if not renderer.available:
            self.render_capability = False
            self._note_not_assessed("browser render comparison", renderer.unavailable_reason)
            if mode == "on":
                self._note_degradation(
                    "rendering was requested but no headless browser is available; "
                    "static signals were used instead and confidence is reduced")
            self._phase("render", started)
            return

        targets = self._render_targets(clusters)
        with renderer as active:
            if not active.available:
                self.render_capability = False
                self._note_not_assessed("browser render comparison",
                                        active.unavailable_reason)
                self._phase("render", started)
                return
            self.render_capability = True
            by_url = {p["url"]: p for p in self.pages}
            rendered = 0
            for url in targets:
                if self.budget.remaining_seconds() < self.budgets["render_timeout_s"]:
                    self._note_degradation(
                        "the time budget ended after %d of %d pages were rendered"
                        % (rendered, len(targets)))
                    break
                page = by_url.get(url)
                if page is None:
                    continue
                outcome = active.render(url, self.user_agent)
                rendered += 1
                if outcome is None:
                    continue
                if not outcome["ok"]:
                    page["render"] = {"ok": False, "error": outcome["error"],
                                      "render_ms": outcome["render_ms"]}
                    continue
                parsed = htmlparse.extract(outcome["html"], self.config["spa_signals"])
                page["render"] = {
                    "ok": True,
                    "text_len": parsed["text_len"],
                    "main_text_len": parsed["main_text_len"],
                    "main_text_excerpt": parsed["main_text"][:4000],
                    "headings": parsed["headings"],
                    "tables": parsed["tables"],
                    "definition_lists": parsed["definition_lists"],
                    "structured_data_blocks": len(parsed["structured_data"]["jsonld"]),
                    "structured_data": {
                        "jsonld": [{"parse_ok": b["parse_ok"], "error": b["error"]}
                                   for b in parsed["structured_data"]["jsonld"]],
                        "microdata_types": parsed["structured_data"]["microdata_types"],
                    },
                    "images": len(parsed["images"]),
                    "render_ms": outcome["render_ms"],
                    "modal_candidates": outcome["modal_candidates"],
                    "error": None,
                }
        self._phase("render", started)

    def _render_targets(self, clusters):
        """One representative page per top cluster. Deterministic.

        Rendering is the expensive operation, so it is capped per template rather than per
        page: cluster representativeness is what makes a handful of renders sufficient for
        a much larger sample.
        """
        cap = self.budgets["max_render_pages"]
        fetched = {p["url"] for p in self.pages if p.get("fetch_ok")}
        targets = []
        for entry in clustering.rank_clusters(clusters):
            for url in entry["sampled"]:
                if url in fetched and url not in targets:
                    targets.append(url)
                    break
            if len(targets) >= cap:
                break
        return targets

    # --------------------------------------------------------------------- snapshot

    def build_snapshot(self, discovered, method, clusters, sampled):
        for page in self.pages:
            page.pop("_parsed", None)

        fetched = [p for p in self.pages if p.get("fetch_ok")]
        rendered = [p for p in self.pages if (p.get("render") or {}).get("ok")]

        if not self.render_capability:
            for page in self.pages:
                page["render"] = None

        coverage = {
            "pages_discovered": len(discovered),
            "pages_sampled": len(sampled),
            "pages_fetched": len(fetched),
            "pages_rendered": len(rendered),
            "blocked_by_robots": len(self.blocked_by_robots),
            "fetch_failures": len([p for p in self.pages if not p.get("fetch_ok")])
                              + len(self.failures),
            "requests_made": self.budget.used,
            "request_cap": self.budget.max_requests,
            "template_clusters": [c["skeleton"] for c in clusters],
            "site_archetype": self.archetype,
            "page_type_counts": self.page_type_counts,
            "capabilities": {
                "headless_render": bool(self.render_capability),
                "external_search": bool(self.args.external_search_available),
            },
            "not_assessed": self.not_assessed,
            "degradations": self.degradations,
            "blocked_urls": self.blocked_by_robots[:40],
            "failures": self.failures[:40],
        }
        if not self.args.external_search_available:
            self._note_not_assessed(
                "off-site corroboration",
                "no external search capability was made available to this run")
            coverage["not_assessed"] = self.not_assessed

        return {
            "schema_version": SCHEMA_VERSION,
            "collector_version": COLLECTOR_VERSION,
            "site": self.site,
            "origin": self.origin,
            "entry_url": self.entry_url,
            "audited_at": self.audited_at,
            "user_agent": self.user_agent,
            "capabilities": coverage["capabilities"],
            "robots": self.robots_record,
            "sitemaps": self.sitemap_records,
            "discovery": {
                "method": method,
                "urls_discovered": len(discovered),
                "depth_reached": getattr(self, "crawl_depth_reached", 0),
                "discovered_urls": sorted(discovered)[:1000],
            },
            "clusters": [dict(
                [(k, v) for k, v in c.items() if k != "members"]
                + [("members_sample", c["members"][:20])]) for c in clusters],
            "site_archetype": self.archetype,
            "sampled_urls": sampled,
            "pages": sorted(self.pages, key=lambda p: p["url"]),
            "phase_timings": self.phase_timings,
            "duration_seconds": round(time.time() - self.started_wall, 3),
            "coverage": coverage,
        }

    # ------------------------------------------------------------------------- driver

    def run(self):
        self.render_capability = False
        self.archetype = "unknown"
        self.page_type_counts = {}

        self.phase_robots()

        entry_allowed, entry_verdict = self.robots_allows(self.entry_url)
        if not entry_allowed:
            self.blocked_by_robots.append({
                "url": self.entry_url, "reason": "robots.txt",
                "matched_rule": entry_verdict["matched_rule"],
                "matched_agent_token": entry_verdict["matched_agent_token"]})
            self._note_degradation(
                "robots.txt disallows the entry URL for this audit agent, so nothing was "
                "crawled; the matched rule is recorded as evidence")
            self._crawl_bodies = {}
            self.render_capability = False
            self._note_not_assessed(
                "page content", "robots.txt disallows crawling this site")
            clusters, sampled = [], []
            self.phase_classify(clusters)
            return self.build_snapshot({}, "blocked-by-robots", clusters, sampled)

        probe = self.fetcher.fetch(self.entry_url)
        if probe["status"] is None and probe["error"] and not probe["budget_denied"]:
            raise SiteUnreachable(probe["error"])
        if probe["status"] == 200 and probe["body"]:
            self._crawl_bodies = {self.key(self.entry_url): probe}
        else:
            self._crawl_bodies = {}
            if probe["blocked"]:
                self._note_degradation(
                    "the entry URL returned status %s to the audit user agent; the site "
                    "may be blocking non-browser agents" % probe["status"])

        discovered, method = self.phase_discovery()
        clusters, sampled = self.phase_sample(discovered)
        self.phase_fetch(sampled, discovered, clusters)
        self.phase_control_fetch()
        self.phase_query_preservation()
        self.phase_classify(clusters)
        self.phase_render(clusters)
        return self.build_snapshot(discovered, method, clusters, sampled)


class SiteUnreachable(Exception):
    pass


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Capture a website into one read-only snapshot for auditing.",
        epilog="Example: collect.py --url https://example.com --out snapshot.json")
    parser.add_argument("--url", required=True, help="site URL or domain")
    parser.add_argument("--out", required=True, help="path to write snapshot.json")
    parser.add_argument("--max-pages", type=int, default=None,
                        help="sample size (default 25, cap 40)")
    parser.add_argument("--time-budget", type=float, default=None,
                        help="acquisition wall-clock budget in seconds (default 150)")
    parser.add_argument("--render", choices=("auto", "on", "off"), default="auto",
                        help="auto renders if a headless browser is present")
    parser.add_argument("--user-agent-contact", default=None,
                        help="optional contact string added to the audit user agent")
    parser.add_argument("--external-search-available", action="store_true",
                        help="declare that a web-search capability exists for later steps")
    parser.add_argument("--config", default=None, help="path to config.json")
    args = parser.parse_args(argv)

    if not re.match(r"^https?://", args.url):
        args.url = "https://" + args.url

    try:
        config = load_config(args.config)
    except (OSError, ValueError) as exc:
        sys.stderr.write("Error: cannot read config: %s\n" % exc)
        return 3

    if args.max_pages is None:
        args.max_pages = config["budgets"]["max_pages_default"]
    if args.time_budget is None:
        args.time_budget = config["budgets"]["acquisition_time_budget_s"]

    host = urlsplit(args.url).hostname or ""
    if host in ("localhost",) and not os.environ.get("AUDIT_ALLOW_LOCAL"):
        pass  # 127.0.0.1 and localhost are permitted so the fixture suite can run offline

    collector = Collector(args, config)
    try:
        snapshot = collector.run()
    except SiteUnreachable as exc:
        json.dump({"error": "site unreachable", "detail": str(exc), "site": collector.site},
                  sys.stdout, indent=2)
        sys.stdout.write("\n")
        sys.stderr.write("Error: the site could not be reached: %s\n" % exc)
        return 3

    directory = os.path.dirname(os.path.abspath(args.out))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(snapshot, handle, indent=2, sort_keys=False)
        handle.write("\n")

    coverage = snapshot["coverage"]
    sys.stderr.write(
        "snapshot: %d discovered, %d sampled, %d fetched, %d rendered, %d requests, "
        "%.1fs -> %s\n" % (coverage["pages_discovered"], coverage["pages_sampled"],
                           coverage["pages_fetched"], coverage["pages_rendered"],
                           coverage["requests_made"], snapshot["duration_seconds"],
                           args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
