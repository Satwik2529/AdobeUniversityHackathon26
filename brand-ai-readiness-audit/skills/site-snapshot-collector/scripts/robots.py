#!/usr/bin/env python3
"""robots.txt parsing with correct group selection and longest-match precedence.

Naive substring matching against the raw file is the classic source of both false
positives ("your robots blocks GPTBot" when a later group re-allows it) and accidental
impoliteness (fetching a path a rule actually disallows). This module implements the
rules properly and, just as importantly, **returns the literal rule that decided each
verdict together with its line number**, so a detector can quote it as evidence rather
than asserting a conclusion the reader cannot check.

Implemented behaviour:

  * Groups. Consecutive `User-agent` lines share one group. A rule line closes the
    agent list; the next `User-agent` after a rule starts a new group.
  * Group selection. The group whose agent token is the longest case-insensitive prefix
    of the crawler's product token wins. `*` is a fallback used only when no specific
    token matches. If several groups declare the same token they are merged, in file
    order.
  * Path matching. `*` matches any run of characters and `$` anchors to the end of the
    path. Everything else is a literal prefix match, per the standard.
  * Precedence. The most specific rule wins, measured by the length of the rule path as
    written. On a tie, `Allow` wins, which is the standard's tie-break.
  * An empty `Disallow:` value means "allow everything" and is not a block.
  * `Crawl-delay` is captured per group even though it is not in the core standard,
    because several operators honour it and ignoring a declared delay would be impolite.
  * `Sitemap` is file-scoped, not group-scoped, and is captured with its line number.
  * Malformed lines are recorded as parse errors and skipped rather than aborting. A file
    that is entirely unparseable is reported as such; it is never silently treated as
    permissive.
"""
import re
from urllib.parse import unquote, urlsplit

DIRECTIVES = ("user-agent", "allow", "disallow", "crawl-delay", "sitemap", "host")


class Rule(object):
    __slots__ = ("directive", "path", "line", "raw")

    def __init__(self, directive, path, line, raw):
        self.directive = directive          # "allow" or "disallow"
        self.path = path
        self.line = line
        self.raw = raw

    def specificity(self):
        return len(self.path)

    def to_dict(self):
        return {"directive": self.directive, "path": self.path,
                "line": self.line, "raw": self.raw}

    def __repr__(self):
        return "Rule(%s %s @%d)" % (self.directive, self.path, self.line)


class Group(object):
    def __init__(self, index):
        self.index = index
        self.agents = []                    # lowercase tokens
        self.agent_lines = []
        self.rules = []
        self.crawl_delay = None
        self.crawl_delay_line = None

    def to_dict(self):
        return {
            "index": self.index,
            "agents": list(self.agents),
            "agent_lines": list(self.agent_lines),
            "rules": [r.to_dict() for r in self.rules],
            "crawl_delay": self.crawl_delay,
            "crawl_delay_line": self.crawl_delay_line,
        }


class RobotsPolicy(object):
    """Parsed policy. Construct with `parse()`."""

    def __init__(self):
        self.groups = []
        self.sitemaps = []                  # [{"url": ..., "line": ...}]
        self.errors = []                    # [{"line": ..., "reason": ..., "raw": ...}]
        self.parse_ok = True
        self.directive_lines = 0
        self.raw = ""

    # ---------------------------------------------------------------- group selection

    def _matching_groups(self, agent):
        """Return (groups, matched_token). Longest specific token wins; `*` is fallback."""
        name = (agent or "").lower()
        best_token, best_groups = None, []
        for group in self.groups:
            for token in group.agents:
                if token == "*":
                    continue
                if name.startswith(token) or token == name:
                    if best_token is None or len(token) > len(best_token):
                        best_token, best_groups = token, [group]
                    elif token == best_token and group not in best_groups:
                        best_groups.append(group)
        if best_token is not None:
            return best_groups, best_token
        wildcard = [g for g in self.groups if "*" in g.agents]
        return (wildcard, "*") if wildcard else ([], None)

    # ------------------------------------------------------------------ path matching

    @staticmethod
    def _rule_matches(rule_path, request_path):
        """Standard path matching with `*` wildcards and `$` end anchoring."""
        if rule_path == "":
            return False
        anchored = rule_path.endswith("$")
        pattern_source = rule_path[:-1] if anchored else rule_path
        if "*" not in pattern_source:
            if anchored:
                return request_path == pattern_source
            return request_path.startswith(pattern_source)
        pattern = "".join(
            ".*" if part == "*" else re.escape(part)
            for part in re.split(r"(\*)", pattern_source))
        pattern = "^" + pattern + ("$" if anchored else "")
        return re.search(pattern, request_path) is not None

    @staticmethod
    def _request_path(url_or_path):
        if "://" in url_or_path:
            parts = urlsplit(url_or_path)
            path = parts.path or "/"
            if parts.query:
                path += "?" + parts.query
        else:
            path = url_or_path or "/"
        if not path.startswith("/"):
            path = "/" + path
        return path

    # ------------------------------------------------------------------------ verdicts

    def evaluate(self, agent, url_or_path):
        """Return a verdict dict for one agent against one path.

        {"verdict": "allow"|"disallow"|"no-group",
         "matched_rule": {...} or None,
         "group_index": int or None,
         "matched_agent_token": str or None}
        """
        groups, token = self._matching_groups(agent)
        if not groups:
            return {"verdict": "no-group", "matched_rule": None,
                    "group_index": None, "matched_agent_token": None}

        path = self._request_path(url_or_path)
        decoded = unquote(path)
        candidates = []
        for group in groups:
            for rule in group.rules:
                if not rule.path:
                    continue  # `Disallow:` with an empty value allows everything
                if (self._rule_matches(rule.path, path)
                        or self._rule_matches(rule.path, decoded)):
                    candidates.append((group, rule))

        if not candidates:
            return {"verdict": "allow", "matched_rule": None,
                    "group_index": groups[0].index, "matched_agent_token": token}

        # Most specific wins; on a tie Allow beats Disallow; then earliest line, so the
        # outcome cannot depend on dictionary or thread ordering.
        def sort_key(item):
            _, rule = item
            return (-rule.specificity(), 0 if rule.directive == "allow" else 1, rule.line)

        group, rule = sorted(candidates, key=sort_key)[0]
        return {
            "verdict": "allow" if rule.directive == "allow" else "disallow",
            "matched_rule": rule.to_dict(),
            "group_index": group.index,
            "matched_agent_token": token,
        }

    def can_fetch(self, agent, url_or_path):
        """True when `agent` may fetch the path. Absence of a rule means allowed."""
        return self.evaluate(agent, url_or_path)["verdict"] != "disallow"

    def crawl_delay_for(self, agent):
        groups, _ = self._matching_groups(agent)
        for group in groups:
            if group.crawl_delay is not None:
                return group.crawl_delay
        return None

    def to_dict(self):
        return {
            "parse_ok": self.parse_ok,
            "directive_lines": self.directive_lines,
            "groups": [g.to_dict() for g in self.groups],
            "sitemaps": list(self.sitemaps),
            "errors": list(self.errors),
        }


def parse(text):
    """Parse robots.txt content into a RobotsPolicy. Never raises on malformed input."""
    policy = RobotsPolicy()
    if text is None:
        policy.parse_ok = False
        policy.errors.append({"line": 0, "reason": "no content", "raw": ""})
        return policy

    policy.raw = text
    if text.startswith("\ufeff"):
        text = text[1:]

    current = None
    accepting_agents = False

    for number, raw_line in enumerate(text.split("\n"), start=1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if ":" not in line:
            policy.errors.append({"line": number, "reason": "no directive separator",
                                  "raw": raw_line.strip()[:200]})
            continue
        field, _, value = line.partition(":")
        field = field.strip().lower()
        value = value.strip()

        if field not in DIRECTIVES:
            policy.errors.append({"line": number, "reason": "unknown directive %r" % field,
                                  "raw": raw_line.strip()[:200]})
            continue
        policy.directive_lines += 1

        if field == "sitemap":
            if value:
                policy.sitemaps.append({"url": value, "line": number})
            else:
                policy.errors.append({"line": number, "reason": "empty Sitemap value",
                                      "raw": raw_line.strip()[:200]})
            continue

        if field == "host":
            continue

        if field == "user-agent":
            if current is None or not accepting_agents:
                current = Group(len(policy.groups))
                policy.groups.append(current)
                accepting_agents = True
            token = value.lower()
            if not token:
                policy.errors.append({"line": number, "reason": "empty User-agent value",
                                      "raw": raw_line.strip()[:200]})
                continue
            current.agents.append(token)
            current.agent_lines.append(number)
            continue

        # From here the directive belongs to a group.
        if current is None:
            policy.errors.append({
                "line": number,
                "reason": "%s before any User-agent line, so it applies to nothing" % field,
                "raw": raw_line.strip()[:200]})
            continue
        accepting_agents = False

        if field in ("allow", "disallow"):
            current.rules.append(Rule(field, value, number, raw_line.strip()[:200]))
        elif field == "crawl-delay":
            try:
                current.crawl_delay = float(value)
                current.crawl_delay_line = number
            except ValueError:
                policy.errors.append({"line": number,
                                      "reason": "Crawl-delay value is not a number",
                                      "raw": raw_line.strip()[:200]})

    if policy.directive_lines == 0:
        policy.parse_ok = False
        if not policy.errors:
            policy.errors.append({"line": 0, "reason": "no directives found", "raw": ""})
    return policy


def verdicts_for(policy, agents, path="/"):
    """Resolve a list of agent tokens against one path.

    Returns (verdicts, matched_rules) where verdicts maps token to
    allow / disallow / no-group, and matched_rules maps token to the deciding rule.
    The collector attaches **no meaning** to any token; interpreting a verdict is the
    access detector's job.
    """
    verdicts, matched = {}, {}
    for agent in agents:
        result = policy.evaluate(agent, path)
        verdicts[agent] = result["verdict"]
        matched[agent] = {
            "group_index": result["group_index"],
            "matched_agent_token": result["matched_agent_token"],
            "rule": result["matched_rule"],
        }
    return verdicts, matched
