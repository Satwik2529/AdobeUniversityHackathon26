"""Per-entity relationship schema: which attributes, audiences, use-cases
and price range are actually evidenced for EACH discovered entity —
replacing the old site-wide "bag of vocabulary" domain_profiler produced.

This is the fix for cross-entity attribute leakage (a site selling both
laptops and keyboards must never let "RAM", discovered from laptop pages,
attach itself to a keyboard query) and for entity candidates being
polluted by repeated feature words ("shortcuts", "backlighting") instead
of actual products: entity candidacy now comes only from page TITLES and
structured-data Product.name, gated to product/category-typed pages when
that signal is available at all, never from H2/H3 feature-bullet text.
"""
import statistics
from collections import Counter, defaultdict

from . import domain_vocabulary, normalizer, snapshot_adapter, structured_data as sd, vocabulary
from .evidence_index import PRODUCT_LIKE_PAGE_TYPES, EvidenceIndex

_MIN_PAGE_COUNT_FOR_ENTITY = 2  # real cross-page repetition, not a single product's own name

# Marketing modifier words ("Pro", "Max", "Air"...) legitimately repeat
# across unrelated product lines (a "Pro Laptop" and a "Keyboard Pro" share
# nothing but the word "Pro") and would otherwise pass the page-count
# threshold as a false "entity". Excluded from entity candidacy only —
# still perfectly valid as ordinary tokens/attributes elsewhere.
_GENERIC_PRODUCT_MODIFIERS = {
    "pro", "plus", "max", "mini", "lite", "air", "se", "premium", "ultra",
    "edition", "series", "new", "classic",
}


def _phrases(text, excluded_words):
    """Unigrams plus TRUE-adjacency bigrams — bigrams are built from the
    original token sequence before stopword filtering, then filtered, so
    two words that were never actually next to each other (e.g. "laptop"
    ... "16GB RAM" ... "laptop" after "with 16GB RAM" is stripped) can
    never masquerade as a phrase like "laptop laptop".

    `excluded_words` must be scoped to the SITE'S OWN detected domain
    (universal words + that one domain's concept words), never a
    cross-domain union — see domain_vocabulary.concept_words_for()'s
    docstring for the real bug ("business", a shopping audience word,
    deleting "Business Administration" as a candidate on an education
    site) that a global union caused."""
    raw_tokens = normalizer.tokenize(text)
    keep = lambda t: t not in excluded_words and len(t) > 2  # noqa: E731
    phrases = {t for t in raw_tokens if keep(t)}
    for a, b in zip(raw_tokens, raw_tokens[1:]):
        if a != b and keep(a) and keep(b):
            phrases.add("%s %s" % (a, b))
    return phrases


def _entity_candidates(pages, domain_type):
    """Returns (candidates, degraded) — degraded True means nothing
    repeated across pages at all and this is a lower-confidence, single-
    page fallback (small-site graceful degradation, not a false claim of
    a "category" the site may only have one product in)."""
    excluded_words = vocabulary.UNIVERSAL_EXCLUDED_WORDS | domain_vocabulary.concept_words_for(domain_type)
    has_page_type_signal = any(p.get("page_type") for p in pages)
    supporting_pages = defaultdict(set)
    product_typed_pages = defaultdict(set)
    structured_corroborated = defaultdict(set)

    for page in pages:
        fields = snapshot_adapter.page_text_fields(page)
        url = page.get("url")
        is_product_like = page.get("page_type") in PRODUCT_LIKE_PAGE_TYPES

        for phrase in _phrases(fields["title"], excluded_words):
            supporting_pages[phrase].add(url)
            if is_product_like:
                product_typed_pages[phrase].add(url)

        for name in sd.iter_product_names(page.get("structured_data")):
            for phrase in _phrases(name, excluded_words):
                supporting_pages[phrase].add(url)
                structured_corroborated[phrase].add(url)
                if is_product_like:
                    product_typed_pages[phrase].add(url)

    qualifying = {}
    for phrase, pages_supporting in supporting_pages.items():
        if phrase in _GENERIC_PRODUCT_MODIFIERS:
            continue  # a marketing modifier, not a product category
        if has_page_type_signal and not product_typed_pages[phrase]:
            continue  # never appears on a product/category-typed page
        if len(pages_supporting) < _MIN_PAGE_COUNT_FOR_ENTITY:
            continue  # a single product's own name/title, not a category
        qualifying[phrase] = pages_supporting

    # Subsumption: a single-word fragment ("business") that carries the
    # EXACT SAME supporting pages as a longer phrase containing it
    # ("business administration") adds no information beyond what the
    # longer phrase already says -- drop the fragment, keep the more
    # specific name. A word with a genuinely different page set (e.g.
    # "degree", shared across multiple distinct programs) is kept: it
    # is a real standalone concept, not a fragment of one bigram.
    redundant = set()
    for phrase, pages in qualifying.items():
        words = phrase.split()
        if len(words) != 1:
            continue
        for other_phrase, other_pages in qualifying.items():
            if other_phrase == phrase or len(other_phrase.split()) <= 1:
                continue
            if words[0] in other_phrase.split() and pages == other_pages:
                redundant.add(phrase)
                break

    gated = []
    for phrase, pages_supporting in qualifying.items():
        if phrase in redundant:
            continue
        page_count = len(pages_supporting)
        confidence = "high" if (page_count >= 3 or structured_corroborated[phrase]) else "medium"
        gated.append({"text": phrase, "page_count": page_count, "confidence": confidence})
    gated.sort(key=lambda c: (-c["page_count"], c["text"]))
    if gated:
        return gated[:10], False

    fallback = sorted(supporting_pages.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:5]
    return [{"text": p, "page_count": len(urls), "confidence": "low"} for p, urls in fallback], True


def _vocab_hits_scoped(entity_pages, term_map):
    hits = {}
    for key, synonyms in term_map.items():
        if synonyms is None:
            continue
        urls = []
        for page in entity_pages:
            if any(normalizer.contains_phrase(page["blob"], normalizer.normalize_text(s)) for s in synonyms):
                urls.append(page["url"])
        if urls:
            hits[key] = {"page_count": len(urls), "urls": urls[:5]}
    return hits


def _price_signals_scoped(entity_pages):
    # One representative price PER PAGE (structured data preferred over a
    # body-text mention), so a single product with both an offer price and
    # its own price repeated in prose doesn't count twice in the median —
    # query_templates.py needs a per-PRODUCT distribution to pick a
    # genuinely selective threshold, not a per-mention one.
    per_page_prices = []
    currency_votes = Counter()
    for page in entity_pages:
        page_price = None
        for offer in page["offers"]:
            price = offer.get("price")
            try:
                if price is not None:
                    page_price = float(price)
                    currency = offer.get("priceCurrency")
                    if currency:
                        currency_votes[str(currency).lower()] += 1
                    break
            except (TypeError, ValueError):
                continue
        if page_price is None:
            for _m, value, currency in normalizer.iter_money_matches(page["blob"][:4000]):
                page_price = value
                currency_votes[currency] += 1
                break
        if page_price is not None:
            per_page_prices.append(page_price)
    if not per_page_prices:
        return None
    per_page_prices.sort()
    return {
        "min": min(per_page_prices),
        "max": max(per_page_prices),
        "median": statistics.median(per_page_prices),
        "sample_size": len(per_page_prices),
        "currency": currency_votes.most_common(1)[0][0] if currency_votes else None,
    }


def build_entity_schemas(snapshot, index=None, domain_type=None):
    """{entity_text: {attributes, audiences, use_cases, price_signals,
    page_count, product_page_count, degraded}} — the per-entity source of
    truth requirement_validator.py checks a requirement's domain
    relationship against. `index` may be passed in to reuse an
    already-built EvidenceIndex rather than rebuilding page blobs twice.

    `domain_type` selects which concept dictionary (shopping/education/
    healthcare/generic — see domain_vocabulary.py) this site's attributes/
    audiences/use-cases are scanned against; every entity on one site
    shares the same domain, so this is resolved once here rather than
    per-entity."""
    pages = snapshot_adapter.pages(snapshot)
    index = index or EvidenceIndex(snapshot)
    candidates, degraded = _entity_candidates(pages, domain_type)
    concepts = domain_vocabulary.get_vocabulary(domain_type)

    schemas = {}
    for candidate in candidates:
        entity_pages = index.pages_mentioning(candidate["text"])
        attributes = _vocab_hits_scoped(entity_pages, concepts["attributes"])
        audiences = _vocab_hits_scoped(entity_pages, concepts["audiences"])
        use_cases = _vocab_hits_scoped(entity_pages, concepts["use_cases"])
        schemas[candidate["text"]] = {
            "confidence": candidate["confidence"],
            "page_count": candidate["page_count"],
            "product_page_count": sum(1 for p in entity_pages if p["page_type"] in PRODUCT_LIKE_PAGE_TYPES),
            "attributes": sorted(attributes.keys()),
            "attribute_evidence": attributes,
            "audiences": sorted(audiences.keys()),
            "audience_evidence": audiences,
            "use_cases": sorted(use_cases.keys()),
            "use_case_evidence": use_cases,
            "price_signals": _price_signals_scoped(entity_pages),
        }
    return {"entities": candidates, "schemas": schemas, "degraded": degraded}
