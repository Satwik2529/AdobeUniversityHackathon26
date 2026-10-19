#!/usr/bin/env python3
"""Template clustering, deterministic sampling, and page-type classification.

Three separate jobs that share the same principle: **decide from observed signals, and
when the signals are weak, say `unknown` rather than guessing.** A wrong page type causes
a confident, wrong finding downstream — a blog post flagged for missing product markup —
which is worse than no classification at all.

Nothing here references a domain, a brand, a CMS or a framework's CSS classes. Clustering
works on URL shape; classification works on structured-data types, DOM structure and the
site's own navigation.
"""
import urlnorm

# --------------------------------------------------------------------------- clustering


SECTION_VOCABULARY = None  # populated below, after the segment sets are defined


def merge_sibling_leaves(clusters, min_siblings=2):
    """Second clustering pass: fold sibling leaf pages into one template.

    Skeletons alone under-cluster. `/products/alpha` and `/products/beta` are obviously
    one template to a human, but neither segment looks like a slug by shape: they are
    short and contain no hyphen. Real catalogues are full of short slugs, so relying on
    shape alone would scatter one template across many clusters and defeat the sampling
    strategy.

    The structural signal is co-occurrence: several leaf pages sharing a parent directory
    are the same template. Guards keep this from over-merging:

      * only below the root, because root-level pages genuinely are different templates
        (an about page and a contact page are not one template),
      * only leaves with the same file extension,
      * never when a leaf name is a known section word, so `/docs/api` and `/docs/guide`
        are left alone,
      * at least `min_siblings` members.
    """
    by_parent = {}
    for entry in clusters:
        skeleton = entry["skeleton"]
        if "?" in skeleton or skeleton.endswith("/"):
            continue
        segments = [s for s in skeleton.split("/") if s]
        if len(segments) < 2:
            continue                      # root-level page: leave it alone
        leaf = segments[-1]
        if leaf.startswith("{"):
            continue                      # already a template
        stem = leaf.rsplit(".", 1)[0]
        extension = "." + leaf.rsplit(".", 1)[1] if "." in leaf else ""
        if stem.lower() in SECTION_VOCABULARY:
            continue
        parent = "/" + "/".join(segments[:-1])
        by_parent.setdefault((parent, extension), []).append(entry)

    merged, consumed = [], set()
    for (parent, extension), group in sorted(by_parent.items()):
        if len(group) < min_siblings:
            continue
        members = sorted({m for entry in group for m in entry["members"]})
        merged.append({
            "id": None,
            "skeleton": "%s/{slug}%s" % (parent, extension),
            "size": len(members),
            "depth": min(entry["depth"] for entry in group),
            "members": members,
            "sampled": [],
            "page_type": None,
            "page_type_confidence": None,
            "merged_from": sorted(entry["skeleton"] for entry in group),
        })
        consumed.update(id(entry) for entry in group)

    survivors = [entry for entry in clusters if id(entry) not in consumed] + merged
    survivors.sort(key=lambda entry: entry["skeleton"])
    for index, entry in enumerate(survivors, start=1):
        entry["id"] = "c%02d" % index
    return survivors


def build_clusters(urls, merge_siblings=True):
    """Group URLs by path skeleton. Returns a deterministic, ordered list of clusters.

    Cluster ids are assigned after sorting skeletons lexicographically, never in
    discovery order, so two runs over the same site produce the same ids.
    """
    groups = {}
    for url in urls:
        groups.setdefault(urlnorm.path_skeleton(url), []).append(url)

    clusters = []
    for index, skeleton in enumerate(sorted(groups), start=1):
        members = sorted(set(groups[skeleton]))
        clusters.append({
            "id": "c%02d" % index,
            "skeleton": skeleton,
            "size": len(members),
            "depth": min(urlnorm.depth(u) for u in members),
            "members": members,
            "sampled": [],
            "page_type": None,
            "page_type_confidence": None,
        })
    if merge_siblings:
        clusters = merge_sibling_leaves(clusters)
    return clusters


def rank_clusters(clusters, nav_skeletons=()):
    """Order clusters for sampling: navigation-linked first, then reach, then shallowness.

    Small clusters reachable from the primary navigation are ranked up deliberately.
    About, contact and press pages are tiny clusters that carry most of a brand's
    canonical facts, and a purely size-ranked sample would never look at them.
    """
    nav = set(nav_skeletons)

    def key(cluster):
        return (
            0 if cluster["skeleton"] in nav else 1,
            # Faceted and filtered URLs are rarely the canonical version of anything.
            # They stay eligible, because some sites do publish them deliberately, but
            # they rank behind real templates so they cannot consume the sample.
            1 if "?" in cluster["skeleton"] else 0,
            -cluster["size"],
            cluster["depth"],
            cluster["skeleton"],
        )

    return sorted(clusters, key=key)


def sample(clusters, max_pages, homepage=None, nav_skeletons=(), per_cluster_cap=3):
    """Choose which URLs to fetch. Deterministic, breadth-first across templates.

    The homepage is always included. Then one URL is taken from each cluster in rank
    order, then a second from each, and so on up to `per_cluster_cap`, until `max_pages`
    is reached. Within a cluster, members are chosen in sorted order, so a rerun over an
    unchanged site picks exactly the same pages.

    Sampling first-N would spend the whole budget on one template. Sampling randomly
    would break determinism. Breadth-first across templates does neither.
    """
    ordered = rank_clusters(clusters, nav_skeletons)
    chosen, seen = [], set()

    if homepage:
        chosen.append(homepage)
        seen.add(homepage)

    # Pass 1 - fairness. Every template gets up to `per_cluster_cap` pages before any
    # template gets more, so a large catalogue cannot crowd out the about page.
    for round_index in range(per_cluster_cap):
        if len(chosen) >= max_pages:
            break
        for cluster in ordered:
            if len(chosen) >= max_pages:
                break
            members = cluster["members"]
            if round_index >= len(members):
                continue
            candidate = members[round_index]
            if candidate in seen:
                continue
            chosen.append(candidate)
            seen.add(candidate)

    # Pass 2 - fill. `per_cluster_cap` is a fairness floor, not a ceiling on the sample.
    # Once every template has been represented, spend the remaining budget round-robin in
    # rank order. A template-level claim like "0 of 12 product pages carry markup" is much
    # stronger evidence than the same claim over 3 pages, and the budget is already paid
    # for, so leaving it unspent would weaken the report for no gain.
    round_index = per_cluster_cap
    while len(chosen) < max_pages:
        added = False
        for cluster in ordered:
            if len(chosen) >= max_pages:
                break
            if "?" in cluster["skeleton"]:
                # Faceted variants are the same content re-sorted or re-filtered. Three
                # is enough to characterise the template; spending more of the sample on
                # them would also manufacture spurious duplicate-content findings.
                continue
            members = cluster["members"]
            if round_index >= len(members):
                continue
            candidate = members[round_index]
            if candidate in seen:
                continue
            chosen.append(candidate)
            seen.add(candidate)
            added = True
        if not added:
            break              # every cluster is exhausted
        round_index += 1

    by_url = {}
    for cluster in clusters:
        for member in cluster["members"]:
            by_url[member] = cluster
    for url in chosen:
        cluster = by_url.get(url)
        if cluster is not None and url not in cluster["sampled"]:
            cluster["sampled"].append(url)

    return chosen


# ----------------------------------------------------------------- page classification

UTILITY_SEGMENTS = {
    "search", "cart", "basket", "checkout", "account", "login", "signin", "sign-in",
    "signup", "register", "logout", "wishlist", "compare", "filter", "preferences",
    "my-account", "customer", "order", "orders",
}
ABOUT_SEGMENTS = {"about", "about-us", "company", "who-we-are", "our-story", "team"}
CONTACT_SEGMENTS = {"contact", "contact-us", "support", "help", "reach-us"}
PRESS_SEGMENTS = {"press", "news", "newsroom", "media", "media-kit", "press-kit"}
LEGAL_SEGMENTS = {"legal", "terms", "terms-of-service", "terms-and-conditions", "privacy",
                  "privacy-policy", "cookies", "cookie-policy", "imprint", "impressum",
                  "disclaimer", "gdpr"}
DOCS_SEGMENTS = {"docs", "documentation", "guide", "guides", "reference", "manual", "api"}

SECTION_VOCABULARY = (UTILITY_SEGMENTS | ABOUT_SEGMENTS | CONTACT_SEGMENTS
                      | PRESS_SEGMENTS | LEGAL_SEGMENTS | DOCS_SEGMENTS
                      | {"index", "home", "default"})

TYPE_BY_SCHEMA = {
    "product": "product",
    "productgroup": "product",
    "offer": "product",
    "itemlist": "category",
    "collectionpage": "category",
    "article": "article",
    "blogposting": "article",
    "newsarticle": "article",
    "techarticle": "docs",
    "aboutpage": "about",
    "contactpage": "contact",
    "faqpage": "faq",
    "qapage": "faq",
    "organization": None,      # present sitewide; not a page-type signal on its own
    "website": None,
    "breadcrumblist": None,
}

CONFIDENCE_BY_SCORE = ((3, "high"), (2, "medium"), (1, "low"))


def classify_page(url, entry_url, parsed, schema_types, nav_targets=()):
    """Return (page_type, confidence, signals).

    A weighted vote. Structured data is the strongest signal because it is the site's own
    declaration; URL shape and DOM structure corroborate it. A single weak signal yields
    `low` confidence, and detectors run only type-agnostic checks against low-confidence
    pages.
    """
    signals = []
    votes = {}

    def vote(page_type, weight, reason):
        if not page_type:
            return
        votes[page_type] = votes.get(page_type, 0) + weight
        signals.append({"type": page_type, "weight": weight, "reason": reason})

    path = urlnorm.path_of(url)
    segments = [s.lower() for s in path.split("/") if s]
    stem = segments[-1].rsplit(".", 1)[0] if segments else ""

    # 1. Homepage is structural and unambiguous.
    if urlnorm.dedupe_key(url) == urlnorm.dedupe_key(entry_url) or path in ("/", ""):
        return "homepage", "high", [{"type": "homepage", "weight": 3,
                                     "reason": "path is the site root"}]

    # 2. Structured data: the site's own declaration of what the page is.
    for schema_type in schema_types:
        mapped = TYPE_BY_SCHEMA.get(schema_type.lower(), "__unmapped__")
        if mapped != "__unmapped__":
            vote(mapped, 3, "structured data declares %s" % schema_type)

    # 3. URL segments naming a well-known section.
    for segment in segments + [stem]:
        if segment in UTILITY_SEGMENTS:
            vote("utility", 3, "path segment %r is a utility section" % segment)
        elif segment in ABOUT_SEGMENTS:
            vote("about", 2, "path segment %r" % segment)
        elif segment in CONTACT_SEGMENTS:
            vote("contact", 2, "path segment %r" % segment)
        elif segment in PRESS_SEGMENTS:
            vote("press", 2, "path segment %r" % segment)
        elif segment in LEGAL_SEGMENTS:
            vote("legal", 2, "path segment %r" % segment)
        elif segment in DOCS_SEGMENTS:
            vote("docs", 2, "path segment %r" % segment)

    # 4. Parameter-only or filter-shaped URLs are utility surfaces.
    if urlnorm.query_keys(url) and not segments:
        vote("utility", 2, "query-only URL")

    # 5. DOM structure corroborates.
    headings = parsed.get("headings") or []
    internal_links = [link for link in parsed.get("links") or [] if link.get("in_content")]
    if parsed.get("forms") and parsed.get("main_text_len", 0) < 800:
        vote("contact", 1, "form-dominant page with little prose")
    if len(internal_links) >= 12 and parsed.get("main_text_len", 0) < 1500:
        vote("category", 1, "many in-content links and little prose")
    if len([h for h in headings if h["level"] >= 2]) >= 5 and any(
            h.get("id") for h in headings):
        vote("docs", 1, "deep anchored heading structure")
    if any(h["text"].strip().endswith("?") for h in headings if h.get("text")):
        vote("faq", 1, "question-shaped headings")

    # 6. Reachable from the primary navigation as a top-level section.
    if url in set(nav_targets) and len(segments) == 1:
        vote("about", 0, "linked from the primary navigation")

    if not votes:
        return "unknown", "low", signals

    best = max(sorted(votes), key=lambda name: votes[name])
    score = votes[best]
    runner_up = max([votes[n] for n in votes if n != best], default=0)

    confidence = "low"
    for threshold, label in CONFIDENCE_BY_SCORE:
        if score >= threshold:
            confidence = label
            break
    if score == runner_up:
        # A genuine tie is ambiguity, not a decision.
        return "unknown", "low", signals
    if score - runner_up < 2 and confidence == "high":
        confidence = "medium"

    return best, confidence, signals


ARCHETYPE_RULES = (
    ("ecommerce", lambda counts: counts.get("product", 0) >= 2),
    ("docs", lambda counts: counts.get("docs", 0) >= 3),
    ("media", lambda counts: counts.get("article", 0) >= 4),
)


def classify_archetype(page_types, has_local_business=False):
    """Derive one site archetype from the distribution of page types.

    `mixed` and `unknown` are first-class outcomes. They narrow the check set rather than
    forcing a guess, which is exactly what should happen when the evidence is thin.
    """
    counts = {}
    for page_type in page_types:
        counts[page_type] = counts.get(page_type, 0) + 1

    known = sum(value for key, value in counts.items() if key not in ("unknown",))
    if known < 2:
        return "unknown", counts

    if has_local_business and counts.get("contact", 0) >= 1 and counts.get("product", 0) < 2:
        return "local-business", counts

    for name, predicate in ARCHETYPE_RULES:
        if predicate(counts):
            return name, counts

    if counts.get("article", 0) >= 2 and counts.get("product", 0) >= 1:
        return "mixed", counts
    if known <= 6 and counts.get("product", 0) == 0 and counts.get("article", 0) <= 1:
        return "brochure", counts
    return "mixed", counts
