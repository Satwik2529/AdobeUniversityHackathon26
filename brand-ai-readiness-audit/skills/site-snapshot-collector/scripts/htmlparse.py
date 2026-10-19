#!/usr/bin/env python3
"""HTML extraction for the snapshot, using only the standard library.

Everything a detector will later need must be recoverable from the snapshot, because
detectors never fetch. That is the design rule this module exists to satisfy: extract
once, generously, and record where each thing came from.

Deliberately tolerant. Real HTML is malformed, and a parse error must degrade to partial
extraction rather than losing the page. `html.parser` is forgiving by default; anything it
cannot handle is recorded in `parse_notes` rather than raised.

**Untrusted input.** Page content is data. Nothing here executes, evaluates, or interprets
page content as an instruction. Script bodies are measured, never run. JSON-LD is parsed
with `json.loads`, which cannot execute code.
"""
import json
import re
from html.parser import HTMLParser

BOILERPLATE_TAGS = {"header", "nav", "footer", "aside"}
SKIP_TEXT_TAGS = {"script", "style", "template", "svg", "noscript", "iframe",
                  "canvas", "title"}
MAIN_TAGS = ("main", "article")
HEADING_TAGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
             "param", "source", "track", "wbr"}

_WS = re.compile(r"\s+")


def _clean(text):
    return _WS.sub(" ", text or "").strip()


class Extractor(HTMLParser):
    def __init__(self, spa_config=None):
        HTMLParser.__init__(self, convert_charrefs=True)
        spa_config = spa_config or {}
        self._mount_ids = {i.lower() for i in spa_config.get("empty_mount_ids", [])}
        self._mount_tags = {t.lower() for t in spa_config.get("empty_mount_tags", [])}

        self.lang = None
        self.title = None
        self.meta = {}
        self.opengraph = {}
        self.canonical = None
        self.hreflang = []
        self.meta_refresh = None
        self.headings = []
        self.links = []            # [{"href","in_content","rel","text"}]
        self.images = []           # [{"src","alt","in_content","has_alt"}]
        self.jsonld_blocks = []    # [{"parse_ok","error","data","raw_len"}]
        self.microdata_types = []
        self.microdata_props = 0
        self.microdata_items = []      # [{"itemtype", "props": {name: value}}]
        self._item_stack = []
        self._current_prop = None
        self.rdfa_types = []
        self.rdfa_props = 0
        self.tables = 0
        self.definition_lists = 0
        self.forms = 0
        self.script_bytes = 0
        self.script_srcs = []
        self.stylesheet_count = 0
        self.render_blocking = 0
        self.noscript_text = ""
        self.empty_mount_points = []
        self.parse_notes = []
        self.body_seen = False
        self._found_main = False

        self._stack = []
        self._text_chunks = []
        self._main_chunks = []
        self._in_main_depth = 0
        self._boiler_depth = 0
        self._skip_depth = 0
        self._script_stack = []
        self._current_heading = None
        self._current_link = None
        self._noscript_depth = 0
        self._element_text_len = {}   # id(frame) -> accumulated text length
        self._frame_counter = 0

    # ------------------------------------------------------------------ helpers

    @property
    def _in_content(self):
        if self._in_main_depth > 0:
            return True
        return self._boiler_depth == 0 and self._found_main is False

    def _push(self, tag, attrs):
        self._frame_counter += 1
        frame = {"tag": tag, "attrs": attrs, "uid": self._frame_counter, "text_len": 0,
                 "child_elements": 0}
        if self._stack:
            self._stack[-1]["child_elements"] += 1
        self._stack.append(frame)
        return frame

    def _add_text(self, text):
        for frame in self._stack:
            frame["text_len"] += len(text)

    # ------------------------------------------------------------------ handlers

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attributes = {k.lower(): (v if v is not None else "") for k, v in attrs}
        frame = self._push(tag, attributes)

        if tag == "html":
            self.lang = attributes.get("lang") or self.lang
        elif tag == "body":
            self.body_seen = True

        if tag in MAIN_TAGS:
            self._found_main = True
            self._in_main_depth += 1
        elif tag in BOILERPLATE_TAGS:
            self._boiler_depth += 1
        if tag in SKIP_TEXT_TAGS:
            self._skip_depth += 1
        if tag == "noscript":
            self._noscript_depth += 1

        if tag == "meta":
            self._handle_meta(attributes)
        elif tag == "link":
            self._handle_link(attributes)
        elif tag == "script":
            self._script_stack.append(attributes)
            if attributes.get("src"):
                self.script_srcs.append(attributes["src"])
                if "async" not in attributes and "defer" not in attributes:
                    self.render_blocking += 1
        elif tag == "a" and attributes.get("href"):
            self._current_link = {"href": attributes["href"],
                                  "rel": attributes.get("rel", ""),
                                  "in_content": self._in_content, "text": ""}
        elif tag == "img":
            self.images.append({
                "src": attributes.get("src", ""),
                "alt": attributes.get("alt"),
                "has_alt": "alt" in attributes,
                "in_content": self._in_content,
            })
        elif tag in HEADING_TAGS:
            self._current_heading = {"level": HEADING_TAGS[tag],
                                     "id": attributes.get("id"),
                                     "text": "", "in_content": self._in_content}
        elif tag == "table":
            self.tables += 1
        elif tag == "dl":
            self.definition_lists += 1
        elif tag == "form":
            self.forms += 1

        if "itemtype" in attributes:
            self.microdata_types.append(attributes["itemtype"])
        if "itemprop" in attributes:
            self.microdata_props += 1
            name = attributes["itemprop"]
            # A value may be an attribute (content, href, src, datetime) or element text.
            value = (attributes.get("content") or attributes.get("href")
                     or attributes.get("src") or attributes.get("datetime"))
            # Attribute the property to the enclosing item *before* this element opens a
            # nested one, otherwise a nested item swallows the property that names it.
            if self._item_stack:
                if value is not None:
                    self._item_stack[-1][1]["props"].setdefault(name, value)
                elif "itemscope" not in attributes:
                    self._current_prop = (tag, name, [])
        if "itemscope" in attributes or "itemtype" in attributes:
            item = {"itemtype": attributes.get("itemtype", ""), "props": {}}
            self.microdata_items.append(item)
            self._item_stack.append((tag, item))
        if "typeof" in attributes:
            self.rdfa_types.append(attributes["typeof"])
        if "property" in attributes and tag != "meta":
            self.rdfa_props += 1

        # Structural mount-point detection is finished in handle_endtag, once we know
        # whether the element ever received any text.
        frame["is_mount_candidate"] = (
            attributes.get("id", "").lower() in self._mount_ids
            or tag in self._mount_tags)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID_TAGS:
            self.handle_endtag(tag)
        else:
            self._pop(tag.lower())

    def _pop(self, tag):
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index]["tag"] == tag:
                frame = self._stack[index]
                del self._stack[index:]
                return frame
        return None

    def handle_endtag(self, tag):
        tag = tag.lower()

        if tag == "a" and self._current_link is not None:
            self._current_link["text"] = _clean(self._current_link["text"])
            self.links.append(self._current_link)
            self._current_link = None
        elif tag in HEADING_TAGS and self._current_heading is not None:
            self._current_heading["text"] = _clean(self._current_heading["text"])
            self.headings.append(self._current_heading)
            self._current_heading = None
        elif tag == "script" and self._script_stack:
            self._script_stack.pop()

        if self._current_prop and self._current_prop[0] == tag:
            _, name, chunks = self._current_prop
            if self._item_stack:
                self._item_stack[-1][1]["props"].setdefault(name, _clean("".join(chunks)))
            self._current_prop = None
        if self._item_stack and self._item_stack[-1][0] == tag:
            self._item_stack.pop()

        frame = self._pop(tag)
        if frame and frame.get("is_mount_candidate") and frame["text_len"] == 0:
            self.empty_mount_points.append({
                "tag": tag,
                "id": frame["attrs"].get("id", ""),
                "child_elements": frame["child_elements"],
            })

        if tag in MAIN_TAGS and self._in_main_depth > 0:
            self._in_main_depth -= 1
        elif tag in BOILERPLATE_TAGS and self._boiler_depth > 0:
            self._boiler_depth -= 1
        if tag in SKIP_TEXT_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag == "noscript" and self._noscript_depth > 0:
            self._noscript_depth -= 1

    def handle_data(self, data):
        if self._script_stack:
            attributes = self._script_stack[-1]
            self.script_bytes += len(data)
            script_type = (attributes.get("type") or "").lower()
            if "ld+json" in script_type:
                self._add_jsonld(data)
            return
        if self._noscript_depth:
            self.noscript_text += data
            return
        if self._skip_depth:
            return
        self._add_text(data)
        self._text_chunks.append(data)
        if self._in_main_depth > 0 or (self._boiler_depth == 0 and not self._found_main):
            self._main_chunks.append(data)
        if self._current_link is not None:
            self._current_link["text"] += data
        if self._current_heading is not None:
            self._current_heading["text"] += data
        if self._current_prop is not None:
            self._current_prop[2].append(data)

    def _add_jsonld(self, raw):
        entry = {"parse_ok": False, "error": None, "data": None, "raw_len": len(raw)}
        stripped = raw.strip()
        if not stripped:
            entry["error"] = "empty script block"
            self.jsonld_blocks.append(entry)
            return
        try:
            entry["data"] = json.loads(stripped)
            entry["parse_ok"] = True
        except ValueError as exc:
            entry["error"] = str(exc)[:200]
            entry["excerpt"] = stripped[:200]
        self.jsonld_blocks.append(entry)

    def _handle_meta(self, attributes):
        name = (attributes.get("name") or "").lower()
        prop = (attributes.get("property") or "").lower()
        content = attributes.get("content", "")
        if name:
            self.meta[name] = content
        if prop:
            self.opengraph[prop] = content
        if (attributes.get("http-equiv") or "").lower() == "refresh":
            self.meta_refresh = content
        if (attributes.get("http-equiv") or "").lower() == "content-language":
            self.lang = self.lang or content

    def _handle_link(self, attributes):
        rel = (attributes.get("rel") or "").lower()
        href = attributes.get("href", "")
        if "canonical" in rel and href:
            self.canonical = self.canonical or href
        if "alternate" in rel and attributes.get("hreflang"):
            self.hreflang.append({"hreflang": attributes["hreflang"], "href": href})
        if "stylesheet" in rel:
            self.stylesheet_count += 1
            self.render_blocking += 1

    def error(self, message):  # html.parser in older Pythons
        self.parse_notes.append(str(message)[:200])

    # -------------------------------------------------------------------- results

    def result(self):
        text = _clean("".join(self._text_chunks))
        main_text = _clean("".join(self._main_chunks))
        if not main_text and not self._found_main:
            # No main landmark: the whole non-boilerplate body is the main text. When a
            # landmark exists and is empty, an empty main text is the true signal and
            # must not be masked by falling back to the page chrome.
            main_text = text
        return {
            "lang": (self.lang or "").strip() or None,
            "title": _clean(self.title),
            "meta": self.meta,
            "opengraph": self.opengraph,
            "canonical": self.canonical,
            "hreflang": self.hreflang,
            "meta_refresh": self.meta_refresh,
            "headings": self.headings,
            "links": self.links,
            "images": self.images,
            "structured_data": {
                "jsonld": self.jsonld_blocks,
                "microdata_types": self.microdata_types,
                "microdata_props": self.microdata_props,
                "microdata_items": self.microdata_items[:60],
                "rdfa_types": self.rdfa_types,
                "rdfa_props": self.rdfa_props,
                "opengraph": self.opengraph,
            },
            "text": text,
            "text_len": len(text),
            "main_text": main_text,
            "main_text_len": len(main_text),
            "tables": self.tables,
            "definition_lists": self.definition_lists,
            "forms": self.forms,
            "script_bytes": self.script_bytes,
            "script_srcs": self.script_srcs,
            "stylesheet_count": self.stylesheet_count,
            "render_blocking": self.render_blocking,
            "noscript_text": _clean(self.noscript_text),
            "empty_mount_points": self.empty_mount_points,
            "has_main_landmark": self._found_main,
            "body_seen": self.body_seen,
            "parse_notes": self.parse_notes,
        }


class _TitleCatcher(Extractor):
    def handle_data(self, data):
        if self._stack and self._stack[-1]["tag"] == "title" and self.title is None:
            self.title = data
        Extractor.handle_data(self, data)


def extract(html, spa_config=None, text_cap=400000):
    """Parse HTML into the signal bundle the snapshot stores. Never raises."""
    parser = _TitleCatcher(spa_config=spa_config)
    notes = []
    try:
        parser.feed(html[:text_cap] if text_cap else html)
        parser.close()
    except Exception as exc:  # noqa: BLE001 - malformed HTML must degrade, not abort
        notes.append("parser stopped early: %s: %s" % (type(exc).__name__, exc))
    # Real HTML is often unclosed at the end of the document. Flush anything still open
    # so a truncated or malformed page still yields its last heading and link.
    if parser._current_heading is not None:
        parser._current_heading["text"] = _clean(parser._current_heading["text"])
        parser.headings.append(parser._current_heading)
        parser._current_heading = None
    if parser._current_link is not None:
        parser._current_link["text"] = _clean(parser._current_link["text"])
        parser.links.append(parser._current_link)
        parser._current_link = None
    result = parser.result()
    result["parse_notes"] = result["parse_notes"] + notes
    if text_cap and len(html) > text_cap:
        result["parse_notes"].append(
            "HTML truncated at %d bytes for parsing; text measurements are lower bounds"
            % text_cap)
    return result


def flatten_jsonld(blocks):
    """Yield every JSON-LD node, walking @graph and arrays.

    A detector that only looks at the top level of each block will report a missing
    Organization on a site that declares one inside an @graph, which is a false positive.
    """
    nodes = []

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            if "@graph" in node:
                walk(node["@graph"])
            nodes.append(node)

    for block in blocks:
        if block.get("parse_ok"):
            walk(block.get("data"))
    return nodes


def types_of(node):
    """Normalised @type list for a JSON-LD node."""
    raw = node.get("@type") if isinstance(node, dict) else None
    if raw is None:
        return []
    values = raw if isinstance(raw, list) else [raw]
    out = []
    for value in values:
        if isinstance(value, str):
            out.append(value.rsplit("/", 1)[-1].rsplit("#", 1)[-1])
    return out
