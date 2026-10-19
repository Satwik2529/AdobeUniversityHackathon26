"""A read-only, in-memory index over fields already present in snapshot.json
— no new network access, matching the marketplace's "only the collector
touches the network" rule. Built fresh per pipeline invocation; never
written back to snapshot.json.
"""
from . import normalizer, snapshot_adapter, structured_data as sd

# Pages of these types are the trustworthy source for "what does this page
# say IT is" (entity candidacy, see entity_schema.py) — a category or
# generic page can *mention* many entities without being one.
PRODUCT_LIKE_PAGE_TYPES = {"product", "category"}


class EvidenceIndex:
    def __init__(self, snapshot):
        self.pages = []
        for page in snapshot_adapter.pages(snapshot):
            fields = snapshot_adapter.page_text_fields(page)
            blob = normalizer.normalize_text(
                " ".join([fields["title"], fields["meta_description"],
                          " ".join(fields["headings"]), fields["main_text"]])
            )
            self.pages.append({
                "url": page.get("url"),
                "page_type": page.get("page_type"),
                "lang": (page.get("lang") or "").split("-")[0].lower() or None,
                "title": fields["title"],
                "headings": fields["headings"],
                "blob": blob,
                "title_blob": normalizer.normalize_text(fields["title"]),
                "heading_blob": normalizer.normalize_text(" ".join(fields["headings"])),
                "product_names": list(sd.iter_product_names(page.get("structured_data"))),
                "offers": list(sd.iter_offers(page.get("structured_data"))),
            })

    def pages_mentioning(self, text):
        needle = normalizer.normalize_text(text)
        if not needle:
            return []
        return [p for p in self.pages if normalizer.contains_phrase(p["blob"], needle)]

    def locate(self, page, text):
        """Which structural tier a phrase was found in on one page —
        structured_data (product_names) > title > heading > body-only. Used
        by evidence_matcher.py to grade evidence strength instead of
        treating every text hit the same way."""
        needle = normalizer.normalize_text(text)
        if not needle:
            return None
        if any(normalizer.contains_phrase(normalizer.normalize_text(n), needle) for n in page["product_names"]):
            return "structured_data"
        if normalizer.contains_phrase(page["title_blob"], needle):
            return "title"
        if normalizer.contains_phrase(page["heading_blob"], needle):
            return "heading"
        if normalizer.contains_phrase(page["blob"], needle):
            return "body"
        return None

    def context_window(self, page, needle, radius=60):
        """The text immediately around the first WHOLE-WORD occurrence of
        `needle` in a page's blob — the unit evidence_matcher screens for
        false-context terms (e.g. "student" appearing only near
        "discount")."""
        needle = normalizer.normalize_text(needle)
        match = normalizer.find_phrase(page["blob"], needle)
        if match is None:
            return ""
        idx = match.start()
        start = max(0, idx - radius)
        end = min(len(page["blob"]), idx + len(needle) + radius)
        return page["blob"][start:end]
