"""Generic JSON-LD helpers shared by evidence_index.py and
domain_profiler.py (moved here to break what would otherwise be a
circular import between them once domain_profiler needs the page index
too — see entity_schema.py).
"""


def node_types(node):
    """@type is a string per the common case but valid JSON-LD also allows a
    list of types on one node — normalize to a lowercase set either way."""
    raw = node.get("@type", [])
    values = raw if isinstance(raw, list) else [raw]
    return {v.lower() for v in values if isinstance(v, str)}


def flatten_jsonld(data):
    if isinstance(data, dict):
        yield data
        for v in data.get("@graph", []) or []:
            yield from flatten_jsonld(v)
    elif isinstance(data, list):
        for item in data:
            yield from flatten_jsonld(item)


def iter_offers(structured_data):
    if not structured_data:
        return
    for block in structured_data.get("jsonld") or []:
        data = block.get("data")
        for node in flatten_jsonld(data):
            if not isinstance(node, dict):
                continue
            types = node_types(node)
            offer = node.get("offers") if "product" in types else None
            if isinstance(offer, dict):
                yield offer
            elif types & {"offer", "aggregateoffer"}:
                yield node


def iter_product_names(structured_data):
    """Product.name strings — used as a corroboration signal for entity
    candidacy (see entity_schema.py) independent of title/heading text."""
    if not structured_data:
        return
    for block in structured_data.get("jsonld") or []:
        data = block.get("data")
        for node in flatten_jsonld(data):
            if not isinstance(node, dict):
                continue
            if "product" in node_types(node):
                name = node.get("name")
                if isinstance(name, str) and name.strip():
                    yield name.strip()
