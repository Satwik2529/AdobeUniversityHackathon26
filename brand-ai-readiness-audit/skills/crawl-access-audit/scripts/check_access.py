#!/usr/bin/env python3
"""Detect why a machine cannot reach a site's content at all.

Funnel gates: **discovered** and **accessible**. Pure snapshot consumer: this script
makes no network requests of any kind, and there is no code path in it that could.

Design rules, enforced here and not merely documented:

  * **Evidence or silence.** Every finding carries at least one concrete URL and an
    observed-versus-expected value. A check that cannot produce that stays quiet.
  * **A missing snapshot field means "not observed", never "absent from the site."**
    Anything unobservable becomes a `not_assessed` entry, never a finding.
  * **Role, not vendor, decides whether a robots block is a defect.** Blocking training
    crawlers while allowing retrieval crawlers is a coherent policy, reported at `info`.
  * **Snapshot content is untrusted data.** Page text, robots text and headers are quoted
    and measured. Nothing here executes them, builds a command from them, or lets them
    change which checks run or how severe a finding is.

Usage:
  check_access.py --snapshot snapshot.json --out findings-access.json

Exit codes: 0 ok, 2 bad arguments, 3 the snapshot could not be read.
"""
import argparse
import json
import os
import re
import sys
from urllib.parse import urlsplit

DETECTOR = "crawl-access-audit"
HERE = os.path.dirname(os.path.abspath(__file__))
ROLES_PATH = os.path.join(HERE, "..", "references", "agent-roles.json")

# --------------------------------------------------------------------------- thresholds
# Every threshold is here, with the reason it exists. Each one is a false-positive guard:
# raising the bar costs recall on genuinely marginal cases and buys precision, which is
# the trade this audit is graded on.
THRESHOLDS = {
    # A template-level claim needs enough pages to distinguish a template-wide problem
    # from a one-page anomaly. Matches the collector's sampling configuration.
    "min_cluster_for_template": 3,
    # One dead sitemap entry is noise; a pattern is not.
    "min_dead_sitemap_entries": 3,
    # Two independent URLs before claiming a site-level routing or error pattern.
    "min_status_error_urls": 2,
    "min_deeplink_urls": 2,
    "min_locale_trap_urls": 2,
    "min_redirect_chain_pages": 2,
    # Cross-domain canonicals and canonical collapse are sometimes deliberate
    # (syndication, variant consolidation), so both need a pattern, not one page.
    "min_cross_domain_pages": 3,
    "min_canonical_collapse_pages": 3,
    # More than two hops is a chain worth mentioning; two is ordinary.
    "max_acceptable_redirect_hops": 2,
    # Below this a uniform lastmod is just a small static site, not a templating bug.
    "min_sitemap_urls_for_lastmod": 20,
    # Below this a missing sitemap barely matters: internal linking covers the site.
    "small_site_url_floor": 20,
    # Text length above which an unclassified page is still treated as content.
    "content_text_floor": 250,
}

BLOCKING_STATUSES = {401, 403, 407, 429, 503}
# Statuses that mean "we refuse *you*". Throttling (429) and unavailability (503) are
# about load or timing, not about the requester's identity, so they are not evidence of
# user-agent discrimination on their own.
IDENTITY_REFUSAL_STATUSES = {401, 403, 407}
THROTTLING_STATUSES = {429, 503}
HARD_ERROR_STATUSES = {404, 410, 500, 502, 504}
UTILITY_TYPES = {"utility"}
INFORMATIONAL_TYPES = {"homepage", "product", "category", "article", "docs", "about",
                       "contact", "faq", "press", "legal"}
CONFIDENT = {"high", "medium"}

_LOCALE_SEGMENT = re.compile(r"^[a-z]{2}(-[a-zA-Z]{2})?$")
_HREFLANG = re.compile(r"^([a-z]{2,3}(-[A-Za-z]{4})?(-([A-Za-z]{2}|\d{3}))?|x-default)$")


def load_roles():
    try:
        with open(ROLES_PATH, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {"roles": {}, "operators": {}, "cost_of_blocking": {}, "special_cases": {}}


# ------------------------------------------------------------------------------- helpers

def host_of(url):
    name = (urlsplit(url or "").hostname or "").lower()
    return name[4:] if name.startswith("www.") else name


def path_of(url):
    return urlsplit(url or "").path or "/"


def norm_path(url):
    path = path_of(url)
    if path.endswith("/") and path != "/":
        path = path[:-1]
    return path or "/"


def same_page(url_a, url_b):
    return (host_of(url_a), norm_path(url_a), urlsplit(url_a or "").query) == \
           (host_of(url_b), norm_path(url_b), urlsplit(url_b or "").query)


def directive_tokens(value):
    if not value:
        return set()
    return {token.strip().lower() for token in re.split(r"[,\s]+", str(value)) if token.strip()}


def has_noindex(page):
    tokens = directive_tokens(page.get("meta_robots"))
    tokens |= directive_tokens((page.get("headers") or {}).get("x-robots-tag"))
    return bool(tokens & {"noindex", "none"})


def is_content_page(page):
    """Content, as opposed to a utility surface. Conservative on both sides."""
    if not page.get("fetch_ok"):
        return False
    page_type = page.get("page_type")
    if page_type in UTILITY_TYPES:
        return False
    if page.get("page_type_confidence") in CONFIDENT and page_type != "unknown":
        return True
    # Unclassified but substantial prose is still content. Requiring a confident
    # classification would let a sitewide noindex hide behind an unusual site structure.
    return page.get("main_text_len", 0) >= THRESHOLDS["content_text_floor"]


def certainty_for(page):
    return "measured" if page.get("page_type_confidence") in CONFIDENT else "inferred"


def cluster_index(snapshot):
    return {c["id"]: c for c in snapshot.get("clusters", [])}


def reach_for(pages_hit, all_content_pages, clusters, snapshot):
    """sitewide / template / page, obeying the cluster sampling threshold."""
    if not pages_hit:
        return "page"
    if all_content_pages and len(pages_hit) == len(all_content_pages) and len(pages_hit) >= 2:
        return "sitewide"
    by_cluster = {}
    for page in pages_hit:
        by_cluster.setdefault(page.get("cluster_id"), []).append(page)
    index = cluster_index(snapshot)
    for cluster_id, members in by_cluster.items():
        cluster = index.get(cluster_id) or {}
        sampled = cluster.get("sampled") or []
        if (cluster.get("size", 0) >= THRESHOLDS["min_cluster_for_template"]
                and sampled and len(members) == len(sampled)):
            return "template"
    return "page"


def finding(check_id, title, gate_impact, reach, certainty, funnel_stage, evidence,
            urls, detail, action, severity_override=None, severity_ceiling=None,
            related=None):
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
    if severity_override:
        entry["severity_override"] = severity_override
    if severity_ceiling:
        entry["severity_ceiling"] = severity_ceiling
    if related:
        entry["related_checks"] = related
    return entry


class Context(object):
    """Everything the checks share, computed once."""

    def __init__(self, snapshot, roles):
        self.snapshot = snapshot
        self.roles = roles
        self.robots = snapshot.get("robots") or {}
        self.pages = snapshot.get("pages") or []
        self.coverage = snapshot.get("coverage") or {}
        self.site_host = host_of(snapshot.get("origin") or snapshot.get("entry_url") or "")
        self.fetched = [p for p in self.pages if p.get("fetch_ok")]
        self.content = [p for p in self.fetched if is_content_page(p)]
        self.not_assessed = []
        # A site that refused every request tells us nothing about its content, its
        # sitemap or its markup. Recording that once keeps every downstream check honest.
        self.ua_blocked_pages = self._ua_blocked_pages()
        self.blackout = bool(self.pages) and not self.fetched
        self.soft_404_urls = self._soft_404_urls()

    def note(self, dimension, reason):
        if not any(item["dimension"] == dimension for item in self.not_assessed):
            self.not_assessed.append({"dimension": dimension, "reason": reason,
                                      "detector": DETECTOR})

    def _ua_blocked_pages(self):
        """Pages the site refused to the audit agent but served to a browser string.

        Two things are deliberately *not* counted, because both produce a confident,
        wrong critical finding:

          * A transport failure on our side (no status, just an error). A timeout or a
            reset is our problem to report as coverage, not evidence about the site.
          * Throttling and unavailability (429, 503). Those are about load or timing.
            A single one is noise; a consistent pattern is suggestive but not proof, so
            it is kept separately and reported at reduced confidence.
        """
        hits, throttled = [], []
        for page in self.pages:
            control = page.get("control_fetch")
            if not control:
                continue
            control_status = control.get("status")
            page_status = page.get("status")
            if control_status is None or not (200 <= control_status < 300):
                continue
            if page_status in IDENTITY_REFUSAL_STATUSES:
                hits.append(page)
            elif page_status in THROTTLING_STATUSES:
                throttled.append(page)
        self.ua_throttled_pages = throttled
        return hits

    def _soft_404_urls(self):
        """Distinct URLs returning 200 with near-identical thin content.

        Used as a guard, not as a finding: a deep link that lands on a soft error page has
        not really "worked", and reporting it as a healthy landing would be wrong. The
        signal is structural (identical thin bodies across different URLs) rather than
        lexical, so it does not depend on the page being in English.
        """
        buckets = {}
        for page in self.fetched:
            text = (page.get("main_text") or "").strip()
            if len(text) > THRESHOLDS["content_text_floor"]:
                continue
            buckets.setdefault(text, []).append(page["url"])
        soft = set()
        for text, urls in buckets.items():
            if len(urls) >= 2 and text:
                soft.update(urls)
        return soft


# ================================================================================ robots

def check_robots(ctx):
    findings = []
    robots = ctx.robots
    roles = ctx.roles.get("roles", {})
    verdicts = robots.get("agent_verdicts") or {}
    matched = robots.get("matched_rules") or {}
    robots_url = robots.get("url") or ""

    status = robots.get("status")
    parse_ok = robots.get("parse_ok")

    # --- unreadable robots -------------------------------------------------------
    if status is None or (status not in (200, 404) and status is not None):
        ctx.note("robots.txt policy",
                 "robots.txt could not be read (status %s), so no crawler policy could "
                 "be resolved" % status)
        return findings

    if status == 404:
        discovered = (ctx.snapshot.get("discovery") or {}).get("urls_discovered", 0)
        findings.append(finding(
            "ACC.ROBOTS_MISSING",
            "No robots.txt is published",
            "weakens", "sitewide", "measured", "discovered",
            "A request for %s returned 404. No robots.txt means no crawler restrictions, "
            "so this does not block anything. It does mean there is nowhere to declare a "
            "sitemap or to state a deliberate policy for training versus retrieval "
            "crawlers." % robots_url,
            [robots_url],
            {"method": "single request for /robots.txt recorded in the snapshot",
             "observed": {"status": 404},
             "expected": "a robots.txt returning 200 with text/plain",
             "sample": {"checked": 1, "failing": 1},
             "confidence": "high", "nondeterministic": False},
            {"summary": "Publish a robots.txt that declares the sitemap and states an "
                        "explicit policy for training and retrieval crawlers.",
             "how": [
                 "Serve /robots.txt as text/plain.",
                 "Add a Sitemap: line pointing at the sitemap index.",
                 "Decide deliberately whether to allow training crawlers; leaving it "
                 "undeclared is a decision made by default rather than on purpose.",
                 "Keep retrieval and user-triggered agents allowed unless there is a "
                 "specific reason not to."],
             "mechanism": "Absence does not shut the discovered gate, but it forfeits the "
                          "one place to declare a sitemap and to record an intentional "
                          "crawler policy, so a future change can silently remove "
                          "citation eligibility.",
             "effort": "trivial", "owner": "engineering",
             "verification": "Request /robots.txt and confirm a 200 with text/plain and "
                             "a resolvable Sitemap line."},
            severity_ceiling="low" if discovered < THRESHOLDS["small_site_url_floor"]
                             else None))
        return findings

    # --- content type ------------------------------------------------------------
    content_type = (robots.get("content_type") or "").lower()
    if content_type and not content_type.startswith("text/plain"):
        findings.append(finding(
            "ACC.ROBOTS_WRONG_CTYPE",
            "robots.txt is served with the wrong content type",
            "weakens", "sitewide", "measured", "discovered",
            "%s returned 200 but with Content-Type %r rather than text/plain. Some "
            "crawlers will not parse a robots file served as another type, so the policy "
            "it expresses may not be applied at all."
            % (robots_url, robots.get("content_type")),
            [robots_url],
            {"method": "Content-Type header recorded on the robots.txt response",
             "observed": {"content_type": robots.get("content_type")},
             "expected": "text/plain",
             "sample": {"checked": 1, "failing": 1},
             "confidence": "high", "nondeterministic": False},
            {"summary": "Serve /robots.txt with Content-Type: text/plain.",
             "how": ["Set the content type on the robots.txt route or file handler.",
                     "Do not render it through a template that adds an HTML wrapper."],
             "mechanism": "A robots file that a crawler declines to parse is a policy that "
                          "does not exist, in either direction: intended allowances are "
                          "lost along with intended restrictions.",
             "effort": "config", "owner": "engineering",
             "verification": "curl -sI the robots URL and confirm the content type."},
            severity_ceiling="low"))

    # --- parse quality -----------------------------------------------------------
    errors = robots.get("errors") or []
    if parse_ok is False:
        findings.append(finding(
            "ACC.ROBOTS_MALFORMED",
            "robots.txt contains no usable directives",
            "weakens", "sitewide", "measured", "discovered",
            "%s returned 200 but parsing found %d usable directive lines and %d "
            "problems. Examples: %s. A file crawlers cannot parse expresses no policy."
            % (robots_url, robots.get("directive_lines", 0), len(errors),
               "; ".join("line %s: %s" % (e.get("line"), e.get("reason"))
                         for e in errors[:3]) or "none recorded"),
            [robots_url],
            {"method": "directive-level parse of the robots.txt body",
             "observed": {"directive_lines": robots.get("directive_lines", 0),
                          "parse_errors": len(errors), "examples": errors[:5]},
             "expected": "at least one parseable User-agent group",
             "sample": {"checked": 1, "failing": 1},
             "confidence": "high", "nondeterministic": False},
            {"summary": "Replace the robots.txt body with valid directives: one or more "
                        "User-agent groups, each followed by Allow or Disallow lines.",
             "how": ["Every line must be `Field: value`; anything else is ignored.",
                     "Allow and Disallow must follow a User-agent line, or they apply to "
                     "nothing.",
                     "Keep the Sitemap line, which is file-scoped rather than group-scoped."],
             "mechanism": "An unparseable file leaves crawler behaviour to each crawler's "
                          "default, so neither an intended allowance nor an intended "
                          "restriction is reliably honoured.",
             "effort": "trivial", "owner": "engineering",
             "verification": "Re-read the file and confirm each line parses as a known "
                             "directive."}))
    elif errors:
        findings.append(finding(
            "ACC.ROBOTS_MALFORMED",
            "robots.txt parses but contains malformed lines",
            "weakens", "sitewide", "measured", "discovered",
            "%s parses, but %d of its lines are not valid directives and are ignored by "
            "crawlers. Examples: %s."
            % (robots_url, len(errors),
               "; ".join("line %s: %s" % (e.get("line"), e.get("reason"))
                         for e in errors[:3])),
            [robots_url],
            {"method": "directive-level parse of the robots.txt body",
             "observed": {"parse_errors": len(errors), "examples": errors[:5],
                          "directive_lines": robots.get("directive_lines", 0)},
             "expected": "no unparseable lines",
             "sample": {"checked": robots.get("directive_lines", 0) + len(errors),
                        "failing": len(errors)},
             "confidence": "high", "nondeterministic": False},
            {"summary": "Correct or remove the malformed lines so the intended policy is "
                        "the policy crawlers actually apply.",
             "how": ["Fix each line listed in the evidence.",
                     "A rule that is silently ignored is the most dangerous kind: the "
                     "file looks like it says something it does not."],
             "mechanism": "Ignored lines mean the effective policy differs from the "
                          "written one, in a way nobody can see by reading the file.",
             "effort": "trivial", "owner": "engineering",
             "verification": "Re-parse the file and confirm zero ignored lines."},
            severity_ceiling="low"))

    if parse_ok is not True:
        return findings

    # --- role-resolved verdicts --------------------------------------------------
    def role_of(token):
        return roles.get(token, "unknown")

    def blocked(role_name):
        return [t for t, v in sorted(verdicts.items())
                if v == "disallow" and role_of(t) == role_name]

    def allowed_explicitly(role_name):
        """Allowed by a group naming the agent, not merely by the wildcard fallback."""
        out = []
        for token, verdict in sorted(verdicts.items()):
            if role_of(token) != role_name or verdict != "allow":
                continue
            token_match = (matched.get(token) or {}).get("matched_agent_token")
            if token_match and token_match != "*":
                out.append(token)
        return out

    blocked_retrieval = blocked("retrieval") + blocked("user-triggered")

    def blocked_by_own_group(token):
        """True when a named group decides it, not the wildcard fallback.

        A wildcard blackout already reports itself as ACC.ROBOTS_BLOCKS_ALL. Reporting
        the retrieval agents that merely inherit that rule as a second finding would
        describe one rule twice and split a single fix across two entries.
        """
        token_match = (matched.get(token) or {}).get("matched_agent_token")
        return bool(token_match) and token_match != "*"
    blocked_training = blocked("training")
    allowed_retrieval = allowed_explicitly("retrieval") + allowed_explicitly("user-triggered")
    wildcard_blocked = verdicts.get("*") == "disallow"

    def rule_text(token):
        rule = (matched.get(token) or {}).get("rule") or {}
        return "%s (line %s)" % (rule.get("raw") or "%s: %s" % (
            rule.get("directive", "?"), rule.get("path", "?")), rule.get("line"))

    def rules_for(tokens):
        return {t: (matched.get(t) or {}).get("rule") for t in tokens}

    # ACC.ROBOTS_BLOCKS_ALL: the wildcard group shuts the site, and nothing re-opens it
    # for a retrieval agent. If named retrieval agents are explicitly allowed, this is an
    # allowlist strategy rather than a blackout, and reporting it would be wrong.
    if wildcard_blocked and not allowed_retrieval:
        rule = (matched.get("*") or {}).get("rule") or {}
        findings.append(finding(
            "ACC.ROBOTS_BLOCKS_ALL",
            "robots.txt disallows every crawler from the whole site",
            "blocks", "sitewide", "measured", "accessible",
            "The wildcard group in %s disallows the site root for all agents. The rule "
            "that decides it is %s. No named group re-allows any retrieval agent, so no "
            "search index or AI assistant may crawl this site."
            % (robots_url, rule_text("*")),
            [robots_url],
            {"method": "robots.txt group selection with longest-match precedence",
             "observed": {"wildcard_verdict": "disallow", "matched_rule": rule},
             "expected": "content paths reachable by retrieval agents",
             "sample": {"checked": 1, "failing": 1},
             "excerpt": (rule.get("raw") or "")[:200],
             "confidence": "high", "nondeterministic": False},
            {"summary": "Remove the sitewide Disallow from the wildcard group, or add "
                        "explicit Allow groups for the retrieval and user-triggered "
                        "agents you want to remain eligible for citation.",
             "how": [
                 "If the blanket block is unintentional, replace `Disallow: /` in the "
                 "`User-agent: *` group with the specific paths that should stay private.",
                 "If it is intentional, add named groups allowing OAI-SearchBot, "
                 "ChatGPT-User, Claude-SearchBot, Claude-User, PerplexityBot and "
                 "Googlebot, so an allowlist policy still permits citation.",
                 "Keep any deliberate training opt-out separate from the retrieval policy."],
             "mechanism": "This shuts the accessible gate at the very first step. Nothing "
                          "downstream, no markup, no content, no site speed, can change "
                          "an answer while a crawler is not permitted to fetch the page. "
                          "Reopening it restores eligibility; it does not by itself "
                          "guarantee a citation.",
             "effort": "config", "owner": "engineering",
             "verification": "Re-read /robots.txt, then watch server logs for retrieval "
                             "agents returning, verifying them by the operators' "
                             "published address ranges rather than the user-agent header, "
                             "which is trivially spoofed."}))

    # ACC.ROBOTS_BLOCKS_RETRIEVAL: the defect that actually costs citations.
    # When the wildcard blackout is already being reported, only agents blocked by their
    # own named group add information here.
    if wildcard_blocked and not allowed_retrieval:
        blocked_retrieval = [t for t in blocked_retrieval if blocked_by_own_group(t)]

    if blocked_retrieval:
        rules = rules_for(blocked_retrieval)
        paths = {(r or {}).get("path") for r in rules.values()}
        reach = "sitewide" if paths <= {"/"} and paths else "template"
        operators = ctx.roles.get("operators", {})
        listed = ", ".join("%s (%s)" % (t, operators.get(t, "unknown operator"))
                           for t in blocked_retrieval)
        findings.append(finding(
            "ACC.ROBOTS_BLOCKS_RETRIEVAL",
            "robots.txt disallows the crawlers that feed AI answers and search results",
            "blocks", reach, "measured", "accessible",
            "%d retrieval or user-triggered agents are disallowed by %s: %s. The deciding "
            "rules are: %s. These are the agents that build the indexes AI assistants "
            "retrieve from and that fetch a page when a user asks about it, so this "
            "removes the site from that pool entirely."
            % (len(blocked_retrieval), robots_url, listed,
               "; ".join("%s -> %s" % (t, rule_text(t)) for t in blocked_retrieval)),
            [robots_url],
            {"method": "per-agent robots resolution using group selection and "
                       "longest-match precedence; roles from references/agent-roles.json",
             "observed": {"blocked_agents": blocked_retrieval, "matched_rules": rules},
             "expected": "retrieval and user-triggered agents allowed on content paths",
             "sample": {"checked": len(verdicts), "failing": len(blocked_retrieval)},
             "confidence": "high", "nondeterministic": False},
            {"summary": "Allow the retrieval and user-triggered agents on content paths, "
                        "keeping any deliberate training opt-out unchanged.",
             "how": [
                 "For each agent named in the evidence, either delete its Disallow rule "
                 "or replace it with `Allow: /` plus the specific private paths.",
                 "Keep training crawlers blocked if that is the intent; the two policies "
                 "are independent and blocking training costs nothing in citations.",
                 "Note that Googlebot also gates Google's AI surfaces: there is no way to "
                 "opt out of AI Overviews separately from Google Search. Google-Extended "
                 "is the training-only token."],
             "mechanism": "Retrieval agents populate the indexes that AI answers are "
                          "assembled from, and user-triggered agents fetch a page when "
                          "someone asks about it directly. Disallowing them makes the "
                          "site ineligible before relevance is ever considered. Allowing "
                          "them restores eligibility, not a guaranteed citation.",
             "effort": "config", "owner": "engineering",
             "verification": "Re-read /robots.txt, then confirm in server logs that those "
                             "agents begin fetching, verified by the operators' published "
                             "IP ranges rather than the spoofable user-agent string."}))

    # ACC.TRAINING_ONLY_BLOCK: a coherent policy, not a defect. Reported so the reader
    # knows the trade-off is being made, and knows it is intact.
    elif blocked_training:
        operators = ctx.roles.get("operators", {})
        findings.append(finding(
            "ACC.TRAINING_ONLY_BLOCK",
            "Training crawlers are blocked while retrieval crawlers are allowed",
            "weakens", "sitewide", "measured", "accessible",
            "%s disallows %d training crawlers (%s) while every retrieval and "
            "user-triggered agent remains allowed. This is a coherent, deliberate "
            "policy and is not a defect: it opts the site out of model training while "
            "keeping it eligible to be cited in AI answers."
            % (robots_url, len(blocked_training),
               ", ".join("%s (%s)" % (t, operators.get(t, "unknown"))
                         for t in blocked_training)),
            [robots_url],
            {"method": "per-agent robots resolution; roles from agent-roles.json",
             "observed": {"blocked_training_agents": blocked_training,
                          "retrieval_agents_allowed": True,
                          "matched_rules": rules_for(blocked_training)},
             "expected": "no defect; recorded so the trade-off is visible",
             "sample": {"checked": len(verdicts), "failing": 0},
             "confidence": "high", "nondeterministic": False},
            {"summary": "No change required. Review the policy deliberately rather than "
                        "leaving it to drift, and keep the two halves separate.",
             "how": [
                 "Keep retrieval and user-triggered agents allowed; that is what "
                 "preserves citation eligibility.",
                 "Re-check the list when new agents appear, which happens a few times a "
                 "year: an unlisted new retrieval agent inherits whatever the wildcard "
                 "group says.",
                 "Record the intent in a comment so a future edit does not merge the "
                 "training opt-out into a blanket block by accident."],
             "mechanism": "Training crawlers shape what a future model knows; retrieval "
                          "agents decide what today's answer cites. Blocking the first "
                          "costs nothing in citations, and this configuration correctly "
                          "keeps the second open.",
             "effort": "trivial", "owner": "engineering",
             "verification": "Re-resolve each agent against robots.txt after any edit and "
                             "confirm retrieval agents still resolve to allow."},
            severity_override="info"))

    return findings


# =============================================================================== sitemaps

def check_sitemaps(ctx):
    findings = []
    if ctx.blackout:
        ctx.note("sitemap health",
                 "no page could be fetched, so sitemap contents could not be checked")
        return findings

    records = ctx.snapshot.get("sitemaps") or []
    usable = [r for r in records if r.get("status") == 200 and r.get("parse_ok")]
    discovery = ctx.snapshot.get("discovery") or {}
    discovered = discovery.get("urls_discovered", 0)
    robots_status = ctx.robots.get("status")

    if not usable:
        attempted = ", ".join("%s (status %s)" % (r.get("url"), r.get("status"))
                              for r in records[:4]) or "no candidate location responded"
        findings.append(finding(
            "ACC.SITEMAP_MISSING",
            "No usable sitemap was found",
            "weakens", "sitewide", "measured", "discovered",
            "No sitemap could be read. Locations tried: %s. Discovery fell back to "
            "following links, which found %d URLs. This is a crawl-efficiency problem "
            "rather than a block: pages linked from the site are still reachable."
            % (attempted, discovered),
            [r.get("url") for r in records if r.get("url")] or
            [(ctx.snapshot.get("origin") or "") + "/sitemap.xml"],
            {"method": "sitemap locations from robots.txt, then conventional paths",
             "observed": {"candidates": records, "discovery_method": discovery.get("method"),
                          "urls_discovered": discovered},
             "expected": "at least one sitemap returning 200 and parsing as a urlset",
             "sample": {"checked": max(len(records), 1), "failing": max(len(records), 1)},
             "confidence": "high", "nondeterministic": False},
            {"summary": "Publish a sitemap with accurate lastmod values and declare it in "
                        "robots.txt.",
             "how": [
                 "Generate a sitemap from the publishing pipeline so lastmod reflects the "
                 "real content change date rather than the build clock.",
                 "Segment it by template (products, articles, static pages) so a crawler "
                 "can recrawl the fast-changing parts without refetching the rest.",
                 "Add a `Sitemap:` line to robots.txt pointing at the index."],
             "mechanism": "A sitemap does not unblock anything; it tells a crawler which "
                          "URLs exist and which have changed, so pages that are weakly "
                          "linked internally get discovered and changed pages get "
                          "recrawled sooner.",
             "effort": "config", "owner": "engineering",
             "verification": "Fetch the sitemap URL and confirm it returns 200, parses, "
                             "and lists the canonical URL of every template."},
            severity_ceiling="low" if discovered < THRESHOLDS["small_site_url_floor"]
                             else None))
        return findings

    # Declared in robots.txt?
    conventional = [r for r in usable if r.get("source") == "conventional location"]
    if conventional and robots_status == 200 and not (ctx.robots.get("sitemaps") or []):
        findings.append(finding(
            "ACC.SITEMAP_NOT_DECLARED",
            "The sitemap exists but is not declared in robots.txt",
            "weakens", "sitewide", "measured", "discovered",
            "A usable sitemap was found at %s, but robots.txt returned 200 and contains "
            "no Sitemap line. Crawlers that do not guess conventional locations will not "
            "find it." % conventional[0].get("url"),
            [conventional[0].get("url"), ctx.robots.get("url")],
            {"method": "comparison of robots.txt Sitemap directives against the sitemap "
                       "actually found",
             "observed": {"sitemap_url": conventional[0].get("url"),
                          "robots_sitemap_lines": []},
             "expected": "a Sitemap: line in robots.txt",
             "sample": {"checked": 1, "failing": 1},
             "confidence": "high", "nondeterministic": False},
            {"summary": "Add a `Sitemap:` line to robots.txt pointing at the sitemap "
                        "index.",
             "how": ["Append `Sitemap: %s` to robots.txt. The line is file-scoped, so it "
                     "belongs outside any User-agent group."
                     % conventional[0].get("url")],
             "mechanism": "The Sitemap directive is the one discovery hint that does not "
                          "depend on a crawler guessing a conventional path.",
             "effort": "trivial", "owner": "engineering",
             "verification": "Re-read robots.txt and confirm the line resolves to a 200."},
            severity_ceiling="low"))

    # Dead entries, measured over the sample only.
    from_sitemap = [p for p in ctx.pages if p.get("discovery_source") == "sitemap"]
    dead = [p for p in from_sitemap if (p.get("status") or 0) in HARD_ERROR_STATUSES]
    if len(dead) >= THRESHOLDS["min_dead_sitemap_entries"] and from_sitemap:
        total_listed = sum(r.get("url_count") or 0 for r in usable)
        rate = len(dead) / float(len(from_sitemap))
        findings.append(finding(
            "ACC.SITEMAP_DEAD_ENTRIES",
            "The sitemap lists URLs that no longer resolve",
            "weakens", "sitewide", "measured", "discovered",
            "%d of the %d sitemap URLs that were sampled returned an error status "
            "(%.0f%% of the sample). The sitemap declares %d URLs in total; only the "
            "sampled subset was checked, so this is a measured sample rate, not a count "
            "of every dead entry. Examples: %s."
            % (len(dead), len(from_sitemap), rate * 100, total_listed,
               ", ".join("%s -> %s" % (p["url"], p.get("status")) for p in dead[:3])),
            [p["url"] for p in dead],
            {"method": "status of sampled URLs whose discovery source was the sitemap",
             "observed": {"dead_in_sample": len(dead), "sampled_from_sitemap":
                          len(from_sitemap), "sample_error_rate": round(rate, 3),
                          "total_urls_listed": total_listed,
                          "statuses": sorted({p.get("status") for p in dead})},
             "expected": "every listed URL returns 200",
             "sample": {"checked": len(from_sitemap), "failing": len(dead)},
             "confidence": "high", "nondeterministic": False},
            {"summary": "Regenerate the sitemap from live routes so that removed pages "
                        "are dropped rather than left listed.",
             "how": [
                 "Build the sitemap from the same source of truth that serves the routes, "
                 "not from a stored snapshot of URLs.",
                 "Where a page moved, serve a 301 to its replacement and list the "
                 "replacement, not the old URL.",
                 "Where a page is genuinely gone, remove it from the sitemap and let it "
                 "return 404 or 410."],
             "mechanism": "Every dead entry spends crawl budget on a URL that cannot be "
                          "indexed and weakens the sitemap as a freshness signal, so real "
                          "changes are noticed more slowly.",
             "effort": "config", "owner": "engineering",
             "verification": "Re-run this audit and confirm the sampled error rate drops "
                             "to zero."}))

    # Uniform lastmod across a large sitemap.
    for record in usable:
        count = record.get("url_count") or 0
        distinct = record.get("lastmod_distinct") or 0
        if count >= THRESHOLDS["min_sitemap_urls_for_lastmod"] and distinct == 1:
            findings.append(finding(
                "ACC.SITEMAP_LASTMOD_UNIFORM",
                "Every sitemap entry carries the same modification date",
                "weakens", "sitewide", "measured", "discovered",
                "%s lists %d URLs and exactly one distinct lastmod value across all of "
                "them. A single shared date is the signature of a build timestamp rather "
                "than a real content change date, which makes the field useless for "
                "deciding what to recrawl." % (record.get("url"), count),
                [record.get("url")],
                {"method": "distinct lastmod values counted while parsing the sitemap",
                 "observed": {"url_count": count, "distinct_lastmod": distinct},
                 "expected": "lastmod varying with actual content changes",
                 "sample": {"checked": count, "failing": count},
                 "confidence": "high", "nondeterministic": False},
                {"summary": "Emit lastmod from the content's real modification time, not "
                            "from the build or deploy time.",
                 "how": ["Take lastmod from the publishing record for each page.",
                         "Omit lastmod entirely rather than emitting a value you cannot "
                         "make accurate; an absent field is better than a misleading one."],
                 "mechanism": "Crawlers use lastmod to prioritise recrawling. When every "
                              "value is identical it carries no information, so genuinely "
                              "updated pages wait in the same queue as unchanged ones.",
                 "effort": "config", "owner": "engineering",
                 "verification": "Re-fetch the sitemap and confirm the number of distinct "
                                 "lastmod values is close to the number of recently "
                                 "changed pages."},
                severity_ceiling="low"))
    return findings


# ============================================================================ page access

def check_ua_blocking(ctx):
    findings = []
    hits = ctx.ua_blocked_pages
    with_control = [p for p in ctx.pages if p.get("control_fetch")]
    if not with_control:
        ctx.note("user-agent differential blocking",
                 "no control fetch was recorded, so a refusal cannot be distinguished "
                 "from an audit-side access failure")
        return findings
    transport_failures = [p for p in ctx.pages
                          if p.get("control_fetch") and p.get("status") is None
                          and p.get("error")]
    if transport_failures:
        ctx.note("user-agent differential blocking on unreachable URLs",
                 "%d URLs failed at the transport layer for this audit (no status was "
                 "returned). That is an audit-side failure and is not evidence about how "
                 "the site treats crawlers" % len(transport_failures))

    if getattr(ctx, "ua_throttled_pages", None) and not hits:
        ctx.note("throttling of non-browser agents",
                 "%d URLs returned 429 or 503 to the audit agent while a browser string "
                 "succeeded. Throttling is about load and timing rather than identity, so "
                 "this is recorded rather than reported as user-agent blocking"
                 % len(ctx.ua_throttled_pages))

    if not hits:
        return findings

    reach = "sitewide" if len(hits) == len(with_control) else "template"
    example = hits[0]
    findings.append(finding(
        "ACC.UA_BLOCKED",
        "The site refuses non-browser agents while serving browsers normally",
        "blocks", reach, "measured", "accessible",
        "%d of %d sampled URLs returned a blocking status to the audit user agent while "
        "the same URL returned 200 to a mainstream browser user-agent string. Example: "
        "%s returned %s to the audit agent and %s to the browser string. That difference "
        "is decided by the requester's identity, not by the URL, which is what an edge or "
        "WAF rule that treats every non-browser agent as a scraper looks like."
        % (len(hits), len(with_control), example["url"], example.get("status"),
           (example.get("control_fetch") or {}).get("status")),
        [p["url"] for p in hits],
        {"method": "per-URL comparison of the machine-view fetch against a control fetch "
                   "sent with a mainstream browser user-agent string",
         "observed": {"blocked_statuses": sorted({p.get("status") for p in hits}),
                      "control_statuses": sorted({(p.get("control_fetch") or {}).get("status")
                                                  for p in hits}),
                      "blocked_urls": [p["url"] for p in hits][:10]},
         "expected": "the same status for both user agents",
         "sample": {"checked": len(with_control), "failing": len(hits)},
         "confidence": "high", "nondeterministic": False},
        {"summary": "Allowlist the retrieval and user-triggered AI agents at the CDN or "
                    "WAF layer, verified by the operators' published IP ranges.",
         "how": [
             "Find the bot rule that returns a challenge or a refusal to agents whose "
             "user-agent string is not a browser.",
             "Add an allow rule for the retrieval and user-triggered agents, matched by "
             "the operators' published address ranges rather than the user-agent header, "
             "which anyone can spoof.",
             "Keep rate limiting in place; the goal is to stop refusing them outright, "
             "not to remove protection.",
             "Test by requesting a content URL with a non-browser user agent and "
             "confirming a 200."],
         "mechanism": "This shuts the accessible gate below robots.txt, where the site "
                      "owner usually is not looking. robots.txt can say `Allow: /` while "
                      "the edge returns a refusal to the very agents it permits, so the "
                      "policy and the behaviour disagree and the behaviour wins.",
         "effort": "config", "owner": "engineering",
         "verification": "Request a content URL with a non-browser user agent and confirm "
                         "a 200 with the full HTML body, then watch server logs for those "
                         "agents returning."}))
    return findings


def check_status_errors(ctx):
    findings = []
    if ctx.blackout:
        ctx.note("page status health",
                 "no page could be fetched, so per-page status could not be assessed")
        return findings
    blocked_urls = {p["url"] for p in ctx.ua_blocked_pages}
    broken = [p for p in ctx.pages
              if (p.get("status") or 0) in HARD_ERROR_STATUSES
              and p["url"] not in blocked_urls]
    if len(broken) < THRESHOLDS["min_status_error_urls"]:
        return findings
    reach = reach_for(broken, ctx.content, ctx.snapshot.get("clusters", []), ctx.snapshot)
    findings.append(finding(
        "ACC.STATUS_ERRORS",
        "URLs the site itself publishes return errors",
        "degrades", reach, "measured", "accessible",
        "%d of %d sampled URLs returned an error status. Every one of them was published "
        "by the site, in its sitemap or its own links, so these are not guessed addresses. "
        "Examples: %s."
        % (len(broken), len(ctx.pages),
           ", ".join("%s -> %s" % (p["url"], p.get("status")) for p in broken[:3])),
        [p["url"] for p in broken],
        {"method": "status codes of sampled URLs, excluding any explained by user-agent "
                   "blocking",
         "observed": {"failing": [{"url": p["url"], "status": p.get("status"),
                                   "source": p.get("discovery_source")}
                                  for p in broken[:10]]},
         "expected": "200 for every published URL",
         "sample": {"checked": len(ctx.pages), "failing": len(broken)},
         "confidence": "high", "nondeterministic": False},
        {"summary": "Either restore the pages or stop publishing their URLs, and serve a "
                    "301 to the closest replacement where one exists.",
         "how": ["For each URL in the evidence, decide: restore, redirect to its "
                 "replacement with a 301, or remove it from the sitemap and internal "
                 "links and let it return 404.",
                 "Do not answer a missing page with a 200; a soft error is worse than an "
                 "honest 404 because it cannot be detected automatically."],
         "mechanism": "A published URL that errors is a dead end for both a crawler and a "
                      "visitor arriving from an answer that cited it.",
         "effort": "template-change", "owner": "engineering",
         "verification": "Re-request each URL in the evidence and confirm a 200 or an "
                         "intentional 301."}))
    return findings


def check_gated_content(ctx):
    findings = []
    gated = []
    ambiguous = []
    for page in ctx.pages:
        status = page.get("status")
        control_status = (page.get("control_fetch") or {}).get("status")
        page_type = page.get("page_type")
        if page_type not in INFORMATIONAL_TYPES:
            continue
        if status == 401:
            gated.append(page)
        elif status == 403 and control_status == 403:
            ambiguous.append(page)

    if ambiguous:
        ctx.note("content gating versus edge blocking",
                 "%d informational URLs returned 403 to both the audit agent and a "
                 "browser user-agent string. A login wall and an edge rule that refuses "
                 "unfamiliar clients are indistinguishable from status alone, so neither "
                 "was reported" % len(ambiguous))

    if not gated:
        return findings

    reach = reach_for(gated, ctx.content, ctx.snapshot.get("clusters", []), ctx.snapshot)
    findings.append(finding(
        "ACC.GATED_INFORMATIONAL_CONTENT",
        "Informational pages sit behind an authentication gate",
        "blocks", reach, "measured", "accessible",
        "%d sampled URLs classified as informational content returned 401, which is an "
        "explicit demand for authentication rather than an ambiguous refusal. Examples: "
        "%s. No credentials were used and none should be: the point is that a crawler "
        "cannot read these pages either."
        % (len(gated), ", ".join(p["url"] for p in gated[:3])),
        [p["url"] for p in gated],
        {"method": "401 status on pages classified as informational content types",
         "observed": {"urls": [{"url": p["url"], "page_type": p.get("page_type")}
                               for p in gated[:10]]},
         "expected": "informational content readable without authentication",
         "sample": {"checked": len(ctx.pages), "failing": len(gated)},
         "confidence": "high", "nondeterministic": False},
        {"summary": "Serve the informational parts of these pages without authentication, "
                    "and keep the gate on the parts that genuinely need an account.",
             "how": ["Split the page: publish the description, specification or answer "
                     "openly and require an account only for the transactional or "
                     "personalised portion.",
                     "If the whole page must stay private, remove it from the sitemap and "
                     "from public internal links so it is not advertised as reachable."],
         "mechanism": "A crawler has no account. Content behind authentication cannot "
                      "enter any index or any answer, however good it is.",
         "effort": "template-change", "owner": "engineering",
         "verification": "Request the URL with no session and confirm the informational "
                         "content is present in the response body."}))
    return findings


def check_noindex(ctx):
    findings = []
    if ctx.blackout:
        ctx.note("indexing directives",
                 "no page could be fetched, so meta robots and X-Robots-Tag could not be "
                 "read")
        return findings

    hits = [p for p in ctx.fetched if has_noindex(p) and is_content_page(p)]
    skipped_utility = [p for p in ctx.fetched
                       if has_noindex(p) and p.get("page_type") in UTILITY_TYPES]
    if skipped_utility:
        # Not a finding, and worth saying so: noindex on search, cart, account and
        # checkout is correct behaviour, and flagging it is the classic false positive.
        ctx.note("noindex on utility pages",
                 "%d utility pages carry noindex (search, cart, account, checkout or "
                 "similar). That is correct configuration and was deliberately not "
                 "reported" % len(skipped_utility))
    if not hits:
        return findings

    reach = reach_for(hits, ctx.content, ctx.snapshot.get("clusters", []), ctx.snapshot)
    certainty = "measured" if all(certainty_for(p) == "measured" for p in hits) else "inferred"
    sources = []
    for page in hits[:10]:
        source = "meta robots" if directive_tokens(page.get("meta_robots")) & {
            "noindex", "none"} else "X-Robots-Tag header"
        sources.append({"url": page["url"], "source": source,
                        "value": page.get("meta_robots")
                                 or (page.get("headers") or {}).get("x-robots-tag"),
                        "page_type": page.get("page_type")})

    findings.append(finding(
        "ACC.NOINDEX_ON_CONTENT",
        "Content pages instruct search engines not to index them",
        "blocks", reach, certainty, "accessible",
        "%d of %d sampled content pages carry a noindex directive. Utility pages such as "
        "search, cart and account were excluded, because noindex is correct there. "
        "Examples: %s."
        % (len(hits), len(ctx.content),
           "; ".join("%s (%s: %r)" % (s["url"], s["source"], s["value"])
                     for s in sources[:3])),
        [p["url"] for p in hits],
        {"method": "meta robots and X-Robots-Tag parsed per page, gated on page type and "
                   "page-type confidence",
         "observed": {"pages": sources},
         "expected": "no noindex on content page types",
         "sample": {"checked": len(ctx.content), "failing": len(hits),
                    "clusters_affected": sorted({p.get("cluster_id") for p in hits})},
         "confidence": "high" if certainty == "measured" else "medium",
         "nondeterministic": False},
        {"summary": "Remove noindex from these content templates and keep it on utility "
                    "templates only.",
         "how": [
             "Find where the directive is set: a meta tag in the template, or an "
             "X-Robots-Tag header from the server or CDN. The header wins if both exist.",
             "A staging configuration promoted to production is the usual cause; check "
             "whether the environment sets it globally.",
             "Keep noindex on search results, cart, account and checkout."],
         "mechanism": "noindex tells a search engine not to store the page. The indexes "
                      "that AI answers retrieve from honour it, so the page can be "
                      "crawled, read and understood and still never be available to cite. "
                      "Note this is narrower than a robots block: the crawler may fetch "
                      "the page, it just may not keep it.",
         "effort": "template-change", "owner": "engineering",
         "verification": "Request each URL, confirm no noindex in either the meta tag or "
                         "the response headers, then watch for the pages returning to the "
                         "index over the following weeks."}))
    return findings


# ============================================================== redirects and canonicals

def check_redirects(ctx):
    findings = []
    long_chains = [p for p in ctx.pages
                   if (p.get("redirect_count") or 0) > THRESHOLDS["max_acceptable_redirect_hops"]]
    if len(long_chains) >= THRESHOLDS["min_redirect_chain_pages"]:
        findings.append(finding(
            "ACC.REDIRECT_CHAIN",
            "Published URLs redirect through several hops before landing",
            "weakens", reach_for(long_chains, ctx.content,
                                 ctx.snapshot.get("clusters", []), ctx.snapshot),
            "measured", "discovered",
            "%d sampled URLs take more than %d redirect hops to resolve. Example: %s."
            % (len(long_chains), THRESHOLDS["max_acceptable_redirect_hops"],
               " -> ".join("%s (%s)" % (hop.get("url"), hop.get("status"))
                           for hop in (long_chains[0].get("status_chain") or [])[:5])),
            [p["url"] for p in long_chains],
            {"method": "redirect chains captured per request",
             "observed": {"chains": [{"url": p["url"], "hops": p.get("redirect_count"),
                                      "chain": p.get("status_chain")}
                                     for p in long_chains[:5]]},
             "expected": "at most %d hops" % THRESHOLDS["max_acceptable_redirect_hops"],
             "sample": {"checked": len(ctx.pages), "failing": len(long_chains)},
             "confidence": "high", "nondeterministic": False},
            {"summary": "Collapse each chain to a single redirect from the published URL "
                        "to its final destination.",
             "how": ["Chains usually accumulate from stacked rules: http to https, then "
                     "non-www to www, then a trailing-slash rule, then a path rewrite. "
                     "Combine them into one rule that jumps straight to the final URL.",
                     "Update internal links and the sitemap to point at the final URL so "
                     "the redirect is only a safety net."],
             "mechanism": "Each hop is a request a crawler may or may not follow, and "
                          "every hop adds latency for a visitor arriving from an answer.",
             "effort": "config", "owner": "engineering",
             "verification": "Request each URL and confirm at most one hop."},
            severity_ceiling="low"))
    return findings


def _locale_prefix(path):
    segments = [s for s in path.split("/") if s]
    if segments and _LOCALE_SEGMENT.match(segments[0]):
        return segments[0], "/" + "/".join(segments[1:])
    return None, path


def check_deeplinks_and_locale(ctx):
    findings = []
    redirected = [p for p in ctx.pages
                  if p.get("redirected") and norm_path(p["url"]) != "/"]
    if not redirected:
        return findings

    home_dumps, locale_traps = [], []
    for page in redirected:
        final_path = norm_path(page.get("final_url"))
        original_path = norm_path(page["url"])
        locale, remainder = _locale_prefix(final_path)

        if locale is not None:
            # A locale prefix that keeps the path is correct behaviour, not a trap.
            if norm_path(remainder) == original_path or original_path.endswith(
                    norm_path(remainder)) and norm_path(remainder) != "/":
                continue
            if norm_path(remainder) == "/":
                locale_traps.append(page)
                continue
        if final_path == "/":
            home_dumps.append(page)

    # Intentional routing to a related page is not homepage dumping. Only a landing on
    # the site root, having asked for something else, counts.
    if len(home_dumps) >= THRESHOLDS["min_deeplink_urls"]:
        soft = [p for p in home_dumps if p.get("final_url") in ctx.soft_404_urls]
        findings.append(finding(
            "ACC.DEEPLINK_TO_HOME_REDIRECT",
            "Published deep links redirect to the homepage",
            "blocks",
            reach_for(home_dumps, ctx.content, ctx.snapshot.get("clusters", []),
                      ctx.snapshot),
            "measured", "accessible",
            "%d URLs the site itself publishes redirect to the site root instead of "
            "serving the requested page. Example: %s returned %s and landed on %s. Both a "
            "crawler and a visitor arriving from an AI answer asked for something "
            "specific and were handed the front door."
            % (len(home_dumps), home_dumps[0]["url"],
               (home_dumps[0].get("status_chain") or [{}])[0].get("status"),
               home_dumps[0].get("final_url")),
            [p["url"] for p in home_dumps],
            {"method": "redirect chains of URLs published in the sitemap or the site's "
                       "own links; no URL was guessed",
             "observed": {"redirects": [{"url": p["url"], "final_url": p.get("final_url"),
                                         "chain": p.get("status_chain")}
                                        for p in home_dumps[:5]],
                          "landing_looks_like_soft_error": bool(soft)},
             "expected": "the requested URL is served, or redirected to its closest "
                         "equivalent page",
             "sample": {"checked": len(ctx.pages), "failing": len(home_dumps)},
             "confidence": "high", "nondeterministic": False},
            {"summary": "Serve the requested URL. Where a redirect is unavoidable, send "
                        "the request to the closest equivalent page rather than to the "
                        "site root, and preserve the query string.",
             "how": [
                 "Find the catch-all rule that rewrites unmatched paths to `/` and "
                 "replace it with a 404 for genuinely missing pages and a 301 to the "
                 "specific replacement for moved ones.",
                 "If these URLs no longer exist, remove them from the sitemap rather than "
                 "publishing addresses that discard the request.",
                 "Preserve non-tracking query parameters and any fragment through the "
                 "redirect."],
             "mechanism": "A redirect to the root throws away the only thing known about "
                          "the request. A crawler records the homepage instead of the "
                          "page, so the specific content never enters an index, and a "
                          "visitor who arrived holding a question has to start again.",
             "effort": "config", "owner": "engineering",
             "verification": "Request each URL in the evidence and confirm it returns 200 "
                             "with its own content, or a 301 to a specific related page."}))

    if len(locale_traps) >= THRESHOLDS["min_locale_trap_urls"]:
        findings.append(finding(
            "ACC.LOCALE_REDIRECT_TRAP",
            "Locale redirects discard the requested path",
            "blocks",
            reach_for(locale_traps, ctx.content, ctx.snapshot.get("clusters", []),
                      ctx.snapshot),
            "measured", "accessible",
            "%d URLs redirect into a locale prefix but lose the path on the way. Example: "
            "%s landed on %s, which is the root of a locale rather than the requested "
            "page. Adding a locale prefix is normal; dropping the path with it is not."
            % (len(locale_traps), locale_traps[0]["url"],
               locale_traps[0].get("final_url")),
            [p["url"] for p in locale_traps],
            {"method": "comparison of the requested path against the landed path after "
                       "removing a leading locale segment",
             "observed": {"redirects": [{"url": p["url"], "final_url": p.get("final_url"),
                                         "chain": p.get("status_chain")}
                                        for p in locale_traps[:5]]},
             "expected": "/{locale}{original path}, preserving the path",
             "sample": {"checked": len(ctx.pages), "failing": len(locale_traps)},
             "confidence": "high", "nondeterministic": False},
            {"summary": "Rewrite the locale redirect to prepend the locale segment while "
                        "keeping the rest of the path and the query string.",
             "how": [
                 "Change the rule from `redirect to /{locale}/` to `redirect to "
                 "/{locale}{original path}`.",
                 "Fall back to a default locale rather than to the locale root when the "
                 "requested path does not exist in the detected locale.",
                 "Declare the locale variants with hreflang so a crawler can tell they "
                 "are the same page rather than duplicates."],
             "mechanism": "Every locale-prefixed URL for a page collapses onto one "
                          "landing page, so no locale variant of the actual content is "
                          "ever reachable by a crawler following a published link.",
             "effort": "config", "owner": "engineering",
             "verification": "Request a deep URL from an address in another region and "
                             "confirm the landed path still contains the original path."}))
    return findings


def check_canonicals(ctx):
    findings = []
    if ctx.blackout:
        return findings
    # Canonical belongs to the page that was served. On a redirected request the canonical
    # describes the landing page, not the URL that was asked for, so comparing them would
    # manufacture a finding out of a redirect that is already reported elsewhere.
    candidates = [p for p in ctx.content if not p.get("redirected")]
    if not candidates:
        return findings

    missing = [p for p in candidates if not p.get("canonical")]
    if missing:
        reach = reach_for(missing, ctx.content, ctx.snapshot.get("clusters", []),
                          ctx.snapshot)
        findings.append(finding(
            "ACC.CANONICAL_MISSING",
            "Content pages declare no canonical URL",
            "weakens", reach, "measured", "discovered",
            "%d of %d sampled content pages carry no rel=canonical link. Without one, a "
            "crawler that reaches the same content through a different URL, for example "
            "with a tracking parameter or a trailing slash, has to guess which address is "
            "the real one. Examples: %s."
            % (len(missing), len(candidates),
               ", ".join(p["url"] for p in missing[:3])),
            [p["url"] for p in missing],
            {"method": "presence of a parsed rel=canonical link on sampled content pages",
             "observed": {"missing": [p["url"] for p in missing[:10]]},
             "expected": "a self-referencing canonical on every content page",
             "sample": {"checked": len(candidates), "failing": len(missing),
                        "clusters_affected": sorted({p.get("cluster_id") for p in missing})},
             "confidence": "high", "nondeterministic": False},
            {"summary": "Add a self-referencing rel=canonical to every content template, "
                        "pointing at the absolute preferred URL of that page.",
             "how": ["Emit the canonical from the route's own definition so it is always "
                     "the page's preferred absolute URL.",
                     "Use the same scheme, host and trailing-slash form as the sitemap, "
                     "so the two do not disagree."],
             "mechanism": "A canonical consolidates the signals for one piece of content "
                          "onto one address. Without it, parameterised and duplicated "
                          "variants compete with each other and none accumulates the full "
                          "weight.",
             "effort": "template-change", "owner": "engineering",
             "verification": "Request each URL and confirm the canonical matches the URL "
                             "that was requested."},
            severity_ceiling=None if reach == "sitewide" else "low"))

    # Cross-domain canonicals.
    cross = [p for p in candidates
             if p.get("canonical") and host_of(p["canonical"]) != ctx.site_host]
    if len(cross) >= THRESHOLDS["min_cross_domain_pages"]:
        hosts = sorted({host_of(p["canonical"]) for p in cross})
        findings.append(finding(
            "ACC.CANONICAL_CROSS_DOMAIN",
            "Content pages hand their canonical status to another domain",
            "degrades",
            reach_for(cross, ctx.content, ctx.snapshot.get("clusters", []), ctx.snapshot),
            "measured", "discovered",
            "%d of %d sampled content pages declare a canonical URL on a different host "
            "(%s). A cross-domain canonical is an instruction to credit the other domain "
            "with this content. It is occasionally deliberate for syndicated material, "
            "which is why several pages were required before reporting it. Example: %s "
            "points at %s."
            % (len(cross), len(candidates), ", ".join(hosts), cross[0]["url"],
               cross[0]["canonical"]),
            [p["url"] for p in cross],
            {"method": "host comparison between each page URL and its declared canonical, "
                       "after normalising a leading www",
             "observed": {"site_host": ctx.site_host, "canonical_hosts": hosts,
                          "pages": [{"url": p["url"], "canonical": p["canonical"]}
                                    for p in cross[:10]]},
             "expected": "a canonical on the site's own host, unless the content is "
                         "deliberately syndicated",
             "sample": {"checked": len(candidates), "failing": len(cross)},
             "confidence": "high", "nondeterministic": False},
            {"summary": "Point the canonical at this site's own URL unless the content is "
                        "genuinely syndicated from the other domain.",
             "how": ["Confirm whether the cross-domain target is intentional. A migration "
                     "or a shared template is the usual accidental cause.",
                     "If unintentional, emit a self-referencing canonical.",
                     "If the content really is syndicated, keep the canonical and stop "
                     "listing these URLs in this site's sitemap, so the two signals agree."],
             "mechanism": "A cross-domain canonical asks every system to attribute the "
                          "content to the other host. The page can be crawled and read, "
                          "and still never be the address that gets cited.",
             "effort": "template-change", "owner": "engineering",
             "verification": "Request each URL and confirm the canonical host matches the "
                             "site's own host."}))

    # Canonical collapse: several distinct pages consolidating onto one address.
    groups = {}
    for page in candidates:
        canonical = page.get("canonical")
        if not canonical or same_page(canonical, page.get("final_url") or page["url"]):
            continue
        if host_of(canonical) != ctx.site_host:
            continue      # already covered by the cross-domain check
        groups.setdefault(norm_path(canonical), []).append(page)

    for target, members in sorted(groups.items()):
        if len(members) < THRESHOLDS["min_canonical_collapse_pages"]:
            continue
        findings.append(finding(
            "ACC.CANONICAL_CONFLICT",
            "Several distinct pages declare the same canonical URL",
            "degrades",
            reach_for(members, ctx.content, ctx.snapshot.get("clusters", []), ctx.snapshot),
            "measured", "discovered",
            "%d distinct content pages all declare %s as their canonical URL while "
            "serving different content. That instructs crawlers to treat them as one "
            "page, so only the target can be indexed or cited. Pages: %s."
            % (len(members), target, ", ".join(p["url"] for p in members[:4])),
            [p["url"] for p in members],
            {"method": "grouping sampled content pages by their declared canonical target, "
                       "excluding self-referencing canonicals and redirected requests",
             "observed": {"canonical_target": target,
                          "pages": [{"url": p["url"], "main_text_len": p.get("main_text_len")}
                                    for p in members[:10]]},
             "expected": "each distinct page canonicalises to itself",
             "sample": {"checked": len(candidates), "failing": len(members)},
             "confidence": "high", "nondeterministic": False},
            {"summary": "Give each distinct page a self-referencing canonical, and reserve "
                        "a shared canonical for pages that really are the same content.",
             "how": ["Emit the canonical per route rather than from a shared layout "
                     "constant, which is the usual cause of every page inheriting one "
                     "value.",
                     "Where variants genuinely are the same content, such as sort orders "
                     "of one listing, a shared canonical is correct and should stay."],
             "mechanism": "A canonical is a consolidation instruction. Pointing distinct "
                          "content at one address removes the rest from the index, so "
                          "they cannot be retrieved or cited however good they are.",
             "effort": "template-change", "owner": "engineering",
             "verification": "Request each URL and confirm its canonical equals its own "
                             "address."}))
    return findings


def check_hreflang(ctx):
    findings = []
    pages_with = [p for p in ctx.fetched if p.get("hreflang")]
    if not pages_with:
        return findings      # a monolingual site is never penalised for this

    problems = []
    by_path = {norm_path(p["url"]): p for p in ctx.fetched}
    for page in pages_with:
        entries = page.get("hreflang") or []
        codes = [e.get("hreflang") for e in entries]
        bad_codes = [c for c in codes if not (c and _HREFLANG.match(c))]
        if bad_codes:
            problems.append({"url": page["url"], "issue": "invalid language codes",
                             "detail": bad_codes})
        self_declared = any(same_page(e.get("href") or "", page.get("final_url") or page["url"])
                            for e in entries)
        if not self_declared:
            problems.append({"url": page["url"], "issue": "no self-referencing alternate",
                             "detail": codes})
        for entry in entries:
            target = by_path.get(norm_path(entry.get("href") or ""))
            if target is None or not target.get("hreflang"):
                continue      # target not sampled: reciprocity is unobservable, not broken
            back = any(same_page(e.get("href") or "",
                                 page.get("final_url") or page["url"])
                       for e in target.get("hreflang") or [])
            if not back:
                problems.append({
                    "url": page["url"], "issue": "alternate does not link back",
                    "detail": {"declares": entry.get("href"), "target": target["url"]}})

    if not problems:
        return findings

    checked_pairs = sum(len(p.get("hreflang") or []) for p in pages_with)
    findings.append(finding(
        "ACC.HREFLANG_INVALID",
        "hreflang annotations are incomplete or invalid",
        "weakens",
        reach_for([p for p in pages_with
                   if any(x["url"] == p["url"] for x in problems)],
                  ctx.content, ctx.snapshot.get("clusters", []), ctx.snapshot),
        "measured", "discovered",
        "%d hreflang problems were found across %d annotated pages and %d declared "
        "alternates. Reciprocity was only checked between pages that were both sampled, "
        "so this is a sample result rather than a full audit. Examples: %s."
        % (len(problems), len(pages_with), checked_pairs,
           "; ".join("%s: %s" % (p["url"], p["issue"]) for p in problems[:3])),
        sorted({p["url"] for p in problems}),
        {"method": "language-code validation, self-reference check, and reciprocity "
                   "between pages that were both sampled",
         "observed": {"problems": problems[:10]},
         "expected": "valid codes, a self-referencing alternate, and mutual links between "
                     "every declared pair",
         "sample": {"checked": len(pages_with), "failing": len(
             {p["url"] for p in problems})},
         "confidence": "high", "nondeterministic": False},
        {"summary": "Emit the full alternate set, including a self-reference, from one "
                    "shared definition so every page in a language group lists every "
                    "other page and itself.",
         "how": ["Generate the group once per piece of content and render the identical "
                 "set on every member, which makes reciprocity structural rather than "
                 "something to remember.",
                 "Include a self-referencing entry on each page.",
                 "Use valid codes: a language subtag, optionally a region subtag, or "
                 "x-default."],
         "mechanism": "hreflang is only honoured when the annotations agree in both "
                      "directions. A one-sided or invalid set is discarded, so locale "
                      "variants compete as duplicates instead of being understood as one "
                      "piece of content in several languages.",
         "effort": "template-change", "owner": "engineering",
         "verification": "Request two pages in the same language group and confirm each "
                         "lists the other and itself."},
        severity_ceiling="low"))
    return findings


CHECKS = (check_robots, check_sitemaps, check_ua_blocking, check_status_errors,
          check_gated_content, check_noindex, check_redirects,
          check_deeplinks_and_locale, check_canonicals, check_hreflang)


def run(snapshot, roles=None):
    ctx = Context(snapshot, roles or load_roles())
    if ctx.blackout:
        ctx.note("page content",
                 "every sampled URL was refused, so nothing about the site's content, "
                 "markup or on-page directives could be observed")
    findings = []
    for check in CHECKS:
        findings.extend(check(ctx))
    findings.sort(key=lambda f: (f["check_id"], (f["affected_urls"] or [""])[0]))
    return findings, ctx.not_assessed


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Detect crawler access and discovery failures from a site snapshot.",
        epilog="Example: check_access.py --snapshot snapshot.json --out findings.json")
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    try:
        with open(args.snapshot, "r", encoding="utf-8") as handle:
            snapshot = json.load(handle)
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
