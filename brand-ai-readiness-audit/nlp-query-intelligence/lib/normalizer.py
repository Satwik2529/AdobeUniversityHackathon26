"""Text, number, currency and unit normalization shared by the profiler,
the NLP engine and the evidence matcher — the one place parsing rules live,
so "60k" and "16GB" are recognized the same way on the query side and the
evidence side.
"""
import re
import unicodedata

CURRENCY_SYMBOLS = {
    "₹": "inr", "rs.": "inr", "rs": "inr", "inr": "inr",
    "$": "usd", "usd": "usd",
    "€": "eur", "eur": "eur",
    "£": "gbp", "gbp": "gbp",
}

_MONEY_RE = re.compile(
    r"(?P<sym>₹|€|£|\$|rs\.?|inr|usd|eur|gbp)\s*"
    r"(?P<num>[\d,]+(?:\.\d+)?)\s*(?P<mag>k|lakh|lakhs|l|cr|crore|m)?",
    re.IGNORECASE,
)
_MONEY_TRAILING_RE = re.compile(
    r"(?P<num>[\d,]+(?:\.\d+)?)\s*(?P<mag>k|lakh|lakhs|l|cr|crore|m)?\s*"
    r"(?P<sym>₹|€|£|\$|rs\.?|inr|usd|eur|gbp)",
    re.IGNORECASE,
)

_MAGNITUDE = {
    "k": 1_000,
    "lakh": 100_000, "lakhs": 100_000, "l": 100_000,
    "cr": 10_000_000, "crore": 10_000_000,
    "m": 1_000_000,
}

_UNIT_RE = re.compile(
    r"(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>gb|tb|mb|mp|mah|inch(?:es)?|\"|hz|ghz|kg|g)\b",
    re.IGNORECASE,
)


def normalize_text(text):
    if not text:
        return ""
    folded = unicodedata.normalize("NFKC", text)
    folded = folded.lower()
    return re.sub(r"\s+", " ", folded).strip()


_TOKEN_RE = re.compile(r"[a-z0-9]+(?:['-][a-z0-9]+)*")


def tokenize(text):
    return _TOKEN_RE.findall(normalize_text(text))


_phrase_pattern_cache = {}


def _phrase_pattern(phrase):
    """Word-boundary-aware pattern for a (already-normalized) phrase,
    cached by phrase text. Plain `needle in haystack` substring checks are
    a real bug, not a simplification -- "ram" is a substring of
    "programming", "pro" of "professional", "mat" of "format". Every
    phrase-containment check in this package must go through this (or
    find_phrase/contains_phrase below), never bare `in`."""
    pattern = _phrase_pattern_cache.get(phrase)
    if pattern is None:
        pattern = re.compile(r"\b%s\b" % re.escape(phrase))
        _phrase_pattern_cache[phrase] = pattern
    return pattern


def find_phrase(haystack, phrase, start=0):
    """Returns the Match for the first whole-word occurrence of `phrase`
    in `haystack` (both assumed already normalize_text'd), or None."""
    if not phrase:
        return None
    return _phrase_pattern(phrase).search(haystack, start)


def contains_phrase(haystack, phrase):
    return find_phrase(haystack, phrase) is not None


def tokenize_with_spans(normalized_text):
    """Like tokenize(), but over text the caller has ALREADY normalized
    (not re-normalizing here matters: spans must line up with the exact
    string the caller is tracking, e.g. nlp_engine's consumption map over
    its own `normalized_query`)."""
    return [(m.group(0), m.start(), m.end()) for m in _TOKEN_RE.finditer(normalized_text)]


def _to_number(num_str, mag):
    value = float(num_str.replace(",", ""))
    if mag:
        value *= _MAGNITUDE.get(mag.lower(), 1)
    return value


def iter_money_matches(text):
    """Yields (match_object, value, currency) for every currency amount in
    text, symbol-before and symbol-after forms alike ("$599", "60,000 INR")."""
    if not text:
        return
    for rx in (_MONEY_RE, _MONEY_TRAILING_RE):
        for m in rx.finditer(text):
            sym = m.group("sym").lower().rstrip(".")
            currency = CURRENCY_SYMBOLS.get(sym) or CURRENCY_SYMBOLS.get(sym + ".") or "inr"
            try:
                value = _to_number(m.group("num"), m.group("mag"))
            except ValueError:
                continue
            yield m, value, currency


def find_money(text):
    """Every currency amount mentioned in text, normalized to (value, currency)."""
    return [{"value": v, "currency": c, "raw": m.group(0).strip()}
            for m, v, c in iter_money_matches(text)]


def iter_unit_matches(text):
    """Yields (match_object, value, unit) for every "<number><unit>" mention
    (16GB, 108MP, 6.5 inch, ...)."""
    if not text:
        return
    for m in _UNIT_RE.finditer(text):
        unit = m.group("unit").lower().replace('"', "inch")
        yield m, float(m.group("num")), unit


def find_units(text):
    return [{"value": v, "unit": u, "raw": m.group(0).strip()} for m, v, u in iter_unit_matches(text)]
