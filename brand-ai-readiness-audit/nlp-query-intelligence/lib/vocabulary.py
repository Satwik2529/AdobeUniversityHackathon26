"""The domain-AGNOSTIC controlled taxonomy the hybrid NLP engine and
evidence matcher share — stopwords, subjective qualifiers, intent
markers, and the language-neutrality guard. None of it is specific to
shopping, education or healthcare; the domain-specific concept
dictionaries (attributes/audiences/use-cases) live in
domain_vocabulary.py and are selected per-site via
domain_vocabulary.get_vocabulary(profile["domain_type"]) — see that
module's docstring for why the engine itself never branches on domain.
"""

STOPWORDS = {
    "a", "an", "the", "and", "or", "with", "for", "of", "in", "on", "to",
    "is", "are", "be", "at", "under", "over", "than", "this", "that",
    "i", "need", "want", "looking", "me", "my", "please", "good", "which",
    "what", "how", "does", "has", "have", "it", "its",
}

# Phrases that mention an audience word without asserting suitability for
# that audience — the "student discount" negative control (see
# evidence_matcher.py). Any audience-term match whose immediate context
# contains one of these is not counted as audience-relevance evidence.
# Domain-agnostic: a commercial-upsell context invalidates suitability
# evidence the same way regardless of what's being sold.
AUDIENCE_FALSE_CONTEXT = [
    "discount", "offer", "pricing", "coupon", "promo", "promotion",
    "scheme", "id card", "verification", "sale",
]

# Quality/recommendation qualifiers. "best" and "top" are intentionally NOT
# given an evidence-phrase list: no single site's own content can verify a
# superlative claim, so the matcher marks these NOT_ASSESSABLE rather than
# inventing a pass/fail (see evidence_matcher.py, and README "Honest
# reporting"). Kept domain-agnostic — "premium"/"budget" mean the same
# thing whether applied to a laptop, a degree program or a clinic visit.
QUALITY_QUALIFIERS = {
    "premium": ["premium", "flagship", "high-end", "aluminium body",
                "aluminum body", "metal body", "oled display", "premium build",
                "premium design"],
    "budget": ["budget", "affordable", "value for money", "entry-level",
               "pocket-friendly", "economical"],
    "best": None,
    "top": None,
    "great": None,
    "good": None,
}

# Raw query words that mean one of the canonical qualifiers above. A query
# saying "cheap laptop" must be scored against the same evidence-phrase list
# as "budget laptop" — and, just as importantly, must NOT have the NLP
# engine invent a numeric price threshold for "cheap" that the user never
# stated (see nlp_engine.py: qualifiers never produce a price_constraint).
QUALIFIER_SYNONYMS = {
    "premium": ["premium", "flagship", "high-end", "high end"],
    "budget": ["budget", "cheap", "affordable", "inexpensive", "low-cost", "low cost"],
    "best": ["best"],
    "top": ["top"],
    "great": ["great"],
    "good": ["good"],
}

INTENT_MARKERS = {
    "recommendation": ["best", "recommend", "suggest", "top", "should i buy",
                        "which is the best"],
    "comparison": [" vs ", " versus ", "compare", "better than", " or "],
    "availability": ["available", "in stock", "buy", "where can i", "does it come"],
    "specification": ["specs", "specification", "specifications", "features",
                       "what are the"],
}

QUANTITY_WORDS = {
    "single": 1, "one": 1, "a couple of": 2, "few": 3, "several": 4,
}


def _flatten_single_words(*term_maps):
    words = set()
    for term_map in term_maps:
        for synonyms in term_map.values():
            for phrase in (synonyms or []):
                words.update(phrase.split())
    return words


# Words owned by the UNIVERSAL (domain-agnostic) vocabulary only --
# stopwords, subjective qualifiers ("premium"), intent markers ("best").
# entity_schema.py excludes these from candidate *entity* names
# regardless of domain, and separately layers in the DETECTED domain's
# OWN concept words via domain_vocabulary.concept_words_for(domain_type)
# -- deliberately not a cross-domain union; see that function's
# docstring for the real bug a global union caused (see also
# tests/test_negative_controls.py and tests/test_entity_schema.py).
UNIVERSAL_EXCLUDED_WORDS = (
    _flatten_single_words(QUALIFIER_SYNONYMS, INTENT_MARKERS) | STOPWORDS
)

# Language neutrality, mirroring the parent audit's own rule (README:
# "Structural checks run anywhere; lexical checks run only where the page
# language is detected and supported. A site is never penalised for not
# being in English."). Every phrase list above is English-only, so
# evidence_matcher.py restricts phrase-based matching (audience, use_case,
# qualifier) to pages in this set and returns NOT_ASSESSABLE rather than a
# false NOT_FOUND when none qualify.
SUPPORTED_LEXICAL_LANGUAGES = {"en"}
