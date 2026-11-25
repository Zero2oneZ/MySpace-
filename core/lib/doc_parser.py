#!/usr/bin/env python3
# ============================================================================
# AGENT CARD                                                                  =
# ----------------------------------------------------------------------------=
# name:        doc_parser                                                     =
# role:        ENGINE · DOC_ADAPTER                                           =
# tier:        L0                                                             =
# substrate:   _doc_corpus (per-adapter JSONL shards)                         =
# engine:      html.parser.HTMLParser → CursorNode → ParserWriter JSONL       =
# storage:     studio/assets/_doc_corpus/<adapter>/<crystal>.jsonl            =
# card:        studio/assets/_agents/agent_defs/                              =
#              vm_mspc_001.agents.agent_defs.doc_parser.active.json           =
# ----------------------------------------------------------------------------=
# ROUTING CONNECTIONS                                                         =
# ----------------------------------------------------------------------------=
# inbound:                                                                    =
#   - cc -docs-import <adapter> <html> / <url>  (planned core/cc cmd)         =
#   - studio passes (pass_06_doc_index) — discover_inputs reads _doc_corpus   =
# outbound:                                                                   =
#   - parser_cursor.CursorNode / ParserWriter (the JSONL writer)              =
#   - inference_logger.InferenceLogger.log()  (one crystal per parsed page)   =
#   - urllib.request.urlopen (parse_url; stdlib only)                         =
# substrate touch:                                                            =
#   - reads:  HTML file or URL bytes                                          =
#   - writes: <_doc_corpus>/<adapter>/<crystal>.jsonl  +  master chain entry  =
# ============================================================================
"""doc_parser.py — generic HTML → ParserCursor-shaped JSONL with adapter slots.

The MoE-chain-router's "documentation substrate". Every external doc page
(Godot HTML, Blender bpy reference, Blender Compositor reference, future
Substance/Mari/FB-Sapiens drops) gets walked into the same JSONL shape that
parser_cursor.ParserCursor already reads. That means existing tooling
(cursor walk, byte-addressable seek, skip_section) works on docs verbatim.

Architecture:

    HTML bytes
        │
        ▼
    DocAdapter.parse()  ─► yields CursorNode stream
        │                     (per-adapter mapping rules)
        ▼
    ParserWriter writes JSONL  ►  studio/assets/_doc_corpus/<adapter>/<sha>.jsonl
        │
        ▼
    InferenceLogger.log(tier='documentation', ...)  ►  crystal anchor

Adapters:
    GodotDocAdapter           v1 live    — class/method/property nodes
    BlenderPyAdapter          v1 live    — bpy.* python ref → method nodes
    BlenderCompositorAdapter  v1 live    — Compositor node reference pages
    SubstanceNodeAdapter      stub        — placeholder (raises NotImplementedError)
    MariProjectAdapter        stub        — placeholder
    FacebookSapiensAdapter    stub        — placeholder

When an adapter's signature check fails (generator tag mismatched, site_name
mismatched, etc.) we fall back to a `_GenericWalker` so output is still valid
JSONL — but tagged `_quality: "generic"` for downstream filters.

Determinism: same HTML bytes → same CursorNode order → same JSONL bytes →
same crystal hash.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple, Type, Union

# Make parser_cursor + inference_logger importable when this module is loaded
# from anywhere (cc.sh, studio passes, ad-hoc python -c).
_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from parser_cursor import (  # noqa: E402  (sys.path mutation above is intentional)
    CursorNode,
    NODE_ELEMENT,
    NODE_ELEMENT_END,
    NODE_TEXT,
    NODE_COMMENT,
    ParserWriter,
)

try:
    from inference_logger import InferenceLogger  # noqa: E402
    _HAS_LOGGER = True
except Exception:
    _HAS_LOGGER = False


# ---------------------------------------------------------------------------
# Output target
# ---------------------------------------------------------------------------
# studio/assets/_doc_corpus/<adapter>/<crystal>.jsonl
# Resolved relative to repo root: core/lib/doc_parser.py → up two = repo root.
_REPO_ROOT = _LIB_DIR.parent.parent
DOC_CORPUS_DIR = _REPO_ROOT / "studio" / "assets" / "_doc_corpus"


def _ensure_corpus_dir(adapter_name: str) -> Path:
    target = DOC_CORPUS_DIR / adapter_name
    target.mkdir(parents=True, exist_ok=True)
    return target


def _crystal_short(data: bytes) -> str:
    """12-char content-addressed name for the output JSONL (collision-resistant
    enough for filenames; the full crystal hash lives in InferenceLogger)."""
    return hashlib.blake2b(data, digest_size=8).hexdigest()


# ---------------------------------------------------------------------------
# DocAdapter base — every adapter implements parse() and matches()
# ---------------------------------------------------------------------------
@dataclass
class _AdapterSignature:
    """Cheap header signal an adapter exposes so the dispatcher can tell whether
    the supplied bytes look like the format the adapter targets."""
    generator_substr: Tuple[str, ...] = ()
    site_name_substr: Tuple[str, ...] = ()
    title_substr: Tuple[str, ...] = ()
    body_marker_substr: Tuple[str, ...] = ()


class DocAdapter:
    """Base — subclasses implement parse(html_bytes) -> Iterator[CursorNode].

    Subclasses also override `.signature` with the markers we look for in
    the page head so callers can use `matches(html_bytes)` to detect format.
    """

    name: str = ""
    signature: _AdapterSignature = _AdapterSignature()

    def matches(self, html_bytes: bytes) -> bool:
        """Cheap signature check — scan the first 8 KB for any of our markers."""
        head_blob = html_bytes[:8192].decode("utf-8", errors="replace").lower()
        sig = self.signature
        for needle in sig.generator_substr + sig.site_name_substr + sig.title_substr + sig.body_marker_substr:
            if needle and needle.lower() in head_blob:
                return True
        return False

    def parse(self, html_bytes: bytes) -> Iterator[CursorNode]:
        raise NotImplementedError(
            f"{self.__class__.__name__}.parse() not implemented"
        )


# ---------------------------------------------------------------------------
# Internal HTML walker — collects every (event, payload) the adapters use
# ---------------------------------------------------------------------------
class _StructuredHTMLCollector(HTMLParser):
    """Walks an HTML document and records a structured event log:

        ("start", tag, dict(attrs), depth)
        ("end",   tag, None,        depth)
        ("data",  None, text,       depth)

    Depth is incremented on `<startendtag>` events that aren't void.
    The collector is intentionally simple — adapters interpret the events.
    """

    # Void elements that should not be tracked on the depth stack
    _VOID = {
        "br", "hr", "img", "input", "meta", "link", "area", "base", "col",
        "embed", "param", "source", "track", "wbr",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.events: List[Tuple[str, Optional[str], Any, int]] = []
        self._depth_stack: List[str] = []

    def _depth(self) -> int:
        return len(self._depth_stack)

    def handle_starttag(self, tag, attrs):
        attr_dict = {k: (v if v is not None else "") for k, v in attrs}
        depth = self._depth()
        self.events.append(("start", tag, attr_dict, depth))
        if tag not in self._VOID:
            self._depth_stack.append(tag)

    def handle_endtag(self, tag):
        # Pop until we hit a matching tag (HTML in the wild is rarely tidy).
        if tag in self._depth_stack:
            while self._depth_stack and self._depth_stack[-1] != tag:
                popped = self._depth_stack.pop()
                self.events.append(("end", popped, None, self._depth()))
            if self._depth_stack:
                popped = self._depth_stack.pop()
                self.events.append(("end", popped, None, self._depth()))
        else:
            # Spurious end-tag — emit at current depth, do not mutate stack
            self.events.append(("end", tag, None, self._depth()))

    def handle_startendtag(self, tag, attrs):
        attr_dict = {k: (v if v is not None else "") for k, v in attrs}
        depth = self._depth()
        self.events.append(("start", tag, attr_dict, depth))
        self.events.append(("end", tag, None, depth))

    def handle_data(self, data):
        text = data.strip()
        if text:
            self.events.append(("data", None, text, self._depth()))

    def handle_comment(self, data):
        text = data.strip()
        if text:
            self.events.append(("comment", None, text, self._depth()))


def _collect_events(html_bytes: bytes) -> List[Tuple[str, Optional[str], Any, int]]:
    """Cheap entry point for adapters that need the raw event stream."""
    text = html_bytes.decode("utf-8", errors="replace")
    coll = _StructuredHTMLCollector()
    coll.feed(text)
    coll.close()
    return coll.events


def _extract_head_meta(events) -> Dict[str, str]:
    """Pull common <meta> + <title> + <h1> signals out of the head for logging."""
    meta: Dict[str, str] = {}
    in_title = False
    title_chunks: List[str] = []
    for kind, tag, payload, _depth in events:
        if kind == "start" and tag == "meta":
            attrs = payload or {}
            key = (attrs.get("name") or attrs.get("property") or "").strip().lower()
            val = (attrs.get("content") or "").strip()
            if key and val and key not in meta:
                meta[key] = val
        elif kind == "start" and tag == "title":
            in_title = True
        elif kind == "end" and tag == "title":
            in_title = False
        elif kind == "data" and in_title:
            title_chunks.append(payload)
    if title_chunks:
        meta["__title__"] = " ".join(title_chunks).strip()
    return meta


# ---------------------------------------------------------------------------
# Generic fallback walker — h1/h2/dl/dt/dd → CursorNode stream
# ---------------------------------------------------------------------------
def _generic_walk(html_bytes: bytes, *, source: str = "generic") -> Iterator[CursorNode]:
    """Low-quality but valid CursorNode stream for any HTML page.

    Walks <h1>, <h2>, <h3>, <dl>, <dt>, <dd>, <pre>. Each one becomes a node.
    Output is tagged `_quality: "generic"` so consumers can filter.
    """
    events = _collect_events(html_bytes)
    interesting = {"h1", "h2", "h3", "dl", "dt", "dd", "pre", "code"}

    stack: List[Tuple[str, int]] = []  # (tag, depth)
    text_buf: List[str] = []
    current_tag: Optional[str] = None
    current_depth: int = 0
    current_attrs: Dict[str, str] = {}

    for kind, tag, payload, depth in events:
        if kind == "start" and tag in interesting:
            # Flush any pending node
            if current_tag is not None:
                yield CursorNode(
                    type=NODE_ELEMENT,
                    name=_doc_node_kind(current_tag),
                    data=" ".join(text_buf).strip() or None,
                    attributes={
                        "_quality": "generic",
                        "_source": source,
                        "tag": current_tag,
                        **{f"attr_{k}": v for k, v in current_attrs.items() if k in ("class", "id")},
                    },
                    parent=stack[-1][0] if stack else None,
                    depth=current_depth,
                )
                text_buf = []
            current_tag = tag
            current_depth = depth
            current_attrs = payload or {}
            stack.append((tag, depth))
        elif kind == "data" and current_tag is not None:
            text_buf.append(payload)
        elif kind == "end" and tag in interesting:
            if current_tag is not None:
                yield CursorNode(
                    type=NODE_ELEMENT,
                    name=_doc_node_kind(current_tag),
                    data=" ".join(text_buf).strip() or None,
                    attributes={
                        "_quality": "generic",
                        "_source": source,
                        "tag": current_tag,
                        **{f"attr_{k}": v for k, v in current_attrs.items() if k in ("class", "id")},
                    },
                    parent=stack[-1][0] if stack else None,
                    depth=current_depth,
                )
                text_buf = []
                current_tag = None
                current_depth = 0
                current_attrs = {}
            # Pop matching from stack if present
            for i in range(len(stack) - 1, -1, -1):
                if stack[i][0] == tag:
                    stack.pop(i)
                    break


def _doc_node_kind(tag: str) -> str:
    """Map HTML tag → semantic doc node kind."""
    return {
        "h1": "section",
        "h2": "section",
        "h3": "subsection",
        "dl": "definition_list",
        "dt": "term",
        "dd": "definition",
        "pre": "code_block",
        "code": "code_inline",
    }.get(tag, tag)


# ---------------------------------------------------------------------------
# Godot Doc Adapter (v1 live)
# ---------------------------------------------------------------------------
class GodotDocAdapter(DocAdapter):
    """Parse Godot HTML docs (Sphinx-based + classic synthetic-generator pages).

    Signals matched:
      - <meta name="generator" content="Godot Engine ...">           (synthetic / older)
      - <meta property="og:site_name" content="Godot Engine ...">    (Sphinx stable docs)
      - <title> includes "Godot Engine" + "documentation"

    Mapping rules:
      - <h1> → CursorNode(type=element, name="section", attributes={node_type: "class"})
        if the heading contains "Class:" or matches "<Title> — Godot Engine".
      - <h2> → CursorNode(name="section", attributes={node_type: "method_group"|"property_group"})
        Detection is heuristic on the heading text ("Methods", "Properties", "Constants").
      - <dl><dt>method foo(...)</dt><dd>...</dd></dl> →
            method node, with signature in `data`, doc body collected from the
            following <dd>'s text.
      - <dl class="py method"> handled the same way in case Sphinx grew Godot tags.
      - Otherwise → text node with the data trimmed.
    """

    name = "godot"
    signature = _AdapterSignature(
        generator_substr=("godot engine",),
        site_name_substr=("godot engine documentation",),
        title_substr=("godot engine",),
        body_marker_substr=("class_xmlparser", "godotengine.org/en/"),
    )

    def parse(self, html_bytes: bytes) -> Iterator[CursorNode]:
        events = _collect_events(html_bytes)
        head_meta = _extract_head_meta(events)

        # Emit a single document-level header node carrying the page title
        page_title = head_meta.get("__title__") or head_meta.get("og:title") or "untitled"
        yield CursorNode(
            type=NODE_ELEMENT,
            name="document",
            data=page_title,
            attributes={
                "_quality": "godot_v1",
                "_source": "godot",
                "title": page_title,
                "site_name": head_meta.get("og:site_name", ""),
                "url": head_meta.get("og:url", ""),
            },
            parent=None,
            depth=0,
        )

        # Walk the body — track the current class context so methods nest
        current_class: Optional[str] = None
        in_h1 = in_h2 = in_dt = in_dd = False
        h1_buf: List[str] = []
        h2_buf: List[str] = []
        dt_buf: List[str] = []
        dd_buf: List[str] = []
        dt_attrs: Dict[str, str] = {}
        last_term: str = ""

        for kind, tag, payload, depth in events:
            if kind == "start":
                if tag == "h1":
                    in_h1 = True; h1_buf = []
                elif tag == "h2":
                    in_h2 = True; h2_buf = []
                elif tag == "dt":
                    in_dt = True; dt_buf = []
                    dt_attrs = payload or {}
                elif tag == "dd":
                    in_dd = True; dd_buf = []
            elif kind == "data":
                if in_dt:
                    dt_buf.append(payload)
                elif in_dd:
                    dd_buf.append(payload)
                elif in_h2:
                    h2_buf.append(payload)
                elif in_h1:
                    h1_buf.append(payload)
            elif kind == "end":
                if tag == "h1" and in_h1:
                    text = " ".join(h1_buf).strip()
                    in_h1 = False
                    if not text:
                        continue
                    cls_name = _strip_class_prefix(text)
                    if cls_name:
                        current_class = cls_name
                    yield CursorNode(
                        type=NODE_ELEMENT,
                        name="section",
                        data=text,
                        attributes={
                            "_quality": "godot_v1",
                            "_source": "godot",
                            "node_type": "class" if cls_name else "section",
                            "class_name": cls_name or "",
                            "tag": "h1",
                        },
                        parent="document",
                        depth=1,
                    )
                elif tag == "h2" and in_h2:
                    text = " ".join(h2_buf).strip()
                    in_h2 = False
                    if not text:
                        continue
                    group_kind = _classify_h2_group(text)
                    yield CursorNode(
                        type=NODE_ELEMENT,
                        name="section",
                        data=text,
                        attributes={
                            "_quality": "godot_v1",
                            "_source": "godot",
                            "node_type": group_kind,
                            "class_context": current_class or "",
                            "tag": "h2",
                        },
                        parent=current_class or "document",
                        depth=2,
                    )
                elif tag == "dt" and in_dt:
                    last_term = " ".join(dt_buf).strip()
                    in_dt = False
                    # Term alone — kind inferred from the signature text
                    if last_term:
                        kind_ = _classify_term(last_term)
                        yield CursorNode(
                            type=NODE_ELEMENT,
                            name="term",
                            data=last_term,
                            attributes={
                                "_quality": "godot_v1",
                                "_source": "godot",
                                "node_type": kind_,
                                "signature": last_term,
                                "class_context": current_class or "",
                                "dt_class": dt_attrs.get("class", ""),
                            },
                            parent=current_class or "document",
                            depth=3,
                        )
                elif tag == "dd" and in_dd:
                    body = " ".join(dd_buf).strip()
                    in_dd = False
                    if body:
                        yield CursorNode(
                            type=NODE_ELEMENT,
                            name="definition",
                            data=body,
                            attributes={
                                "_quality": "godot_v1",
                                "_source": "godot",
                                "node_type": "doc",
                                "term": last_term,
                                "class_context": current_class or "",
                            },
                            parent=last_term or current_class or "document",
                            depth=4,
                        )


def _strip_class_prefix(text: str) -> str:
    """If h1 looks like 'Class: Node' or 'Node — Godot Engine ...', return 'Node'."""
    t = text.strip()
    lower = t.lower()
    if lower.startswith("class:"):
        return t.split(":", 1)[1].strip()
    # Sphinx stable docs: "XMLParser — Godot Engine (stable) documentation in English"
    if "godot engine" in lower and " — " in t:
        head = t.split(" — ", 1)[0].strip()
        # Heuristic: single token title → looks like a class
        if head and " " not in head:
            return head
    if lower.startswith("class "):
        return t.split(" ", 1)[1].strip()
    return ""


def _classify_h2_group(text: str) -> str:
    t = text.lower()
    if "method" in t:
        return "method_group"
    if "propert" in t:
        return "property_group"
    if "constant" in t:
        return "constant_group"
    if "signal" in t:
        return "signal_group"
    if "enum" in t or "enumerat" in t:
        return "enum_group"
    return "section"


def _classify_term(text: str) -> str:
    t = text.strip()
    lt = t.lower()
    if lt.startswith("method") or "(" in t and ")" in t:
        return "method"
    if lt.startswith("property") or lt.startswith("var ") or lt.startswith("get_") or lt.startswith("set_"):
        return "property"
    if lt.startswith("signal"):
        return "signal"
    if lt.startswith("constant") or t.isupper():
        return "constant"
    if lt.startswith("enum"):
        return "enum"
    return "symbol"


# ---------------------------------------------------------------------------
# Blender Python Adapter (v1 live)
# ---------------------------------------------------------------------------
class BlenderPyAdapter(DocAdapter):
    """Parse Blender's bpy reference HTML (Sphinx-generated).

    Signals matched:
      - <meta name="generator" content="Sphinx ...">  (any Sphinx page; refined by markers)
      - <title> includes "Blender" + ("Python API" | "bpy" | "Documentation")
      - body markers: "bpy.types", "bpy.ops", "bpy.context", "py method"

    Mapping rules:
      - <dl class="py method">   → method node
      - <dl class="py function"> → function node
      - <dl class="py class">    → class node
      - <dl class="py attribute"|"py data"> → property node
      - <dt id="..."> → signature in `data`, id attr captures fully-qualified name
      - <dd> → description doc

    Stub-safe: if the page has none of those classes we still emit the document
    header + any h1/h2 we find so the output is valid JSONL.
    """

    name = "blender_py"
    signature = _AdapterSignature(
        site_name_substr=("blender",),
        title_substr=("python api", "bpy", "blender"),
        body_marker_substr=("bpy.types", "bpy.ops", "bpy.context", "py method", "py function", "py class"),
    )

    _PY_DL_CLASSES = {
        "py method": "method",
        "py function": "function",
        "py class": "class",
        "py attribute": "property",
        "py data": "property",
        "py classmethod": "classmethod",
        "py staticmethod": "staticmethod",
        "py exception": "exception",
    }

    def parse(self, html_bytes: bytes) -> Iterator[CursorNode]:
        events = _collect_events(html_bytes)
        head_meta = _extract_head_meta(events)

        page_title = head_meta.get("__title__") or head_meta.get("og:title") or "untitled"
        yield CursorNode(
            type=NODE_ELEMENT,
            name="document",
            data=page_title,
            attributes={
                "_quality": "blender_py_v1",
                "_source": "blender_py",
                "title": page_title,
                "url": head_meta.get("og:url", ""),
            },
            parent=None,
            depth=0,
        )

        in_h1 = False
        h1_buf: List[str] = []

        # State for the current py-* <dl> we are inside
        cur_kind: Optional[str] = None     # method / function / class / ...
        cur_id: str = ""
        in_dt = in_dd = False
        dt_buf: List[str] = []
        dd_buf: List[str] = []
        last_term: str = ""

        # Track <dl> nesting so we can pop kind when one closes
        dl_stack: List[Optional[str]] = []

        for kind, tag, payload, depth in events:
            if kind == "start":
                if tag == "h1":
                    in_h1 = True; h1_buf = []
                elif tag == "dl":
                    cls = (payload or {}).get("class", "").strip().lower()
                    mapped = None
                    for marker, node_kind in self._PY_DL_CLASSES.items():
                        if marker in cls:
                            mapped = node_kind
                            break
                    dl_stack.append(mapped)
                    cur_kind = mapped if mapped is not None else cur_kind
                elif tag == "dt":
                    in_dt = True; dt_buf = []
                    cur_id = (payload or {}).get("id", "")
                elif tag == "dd":
                    in_dd = True; dd_buf = []
            elif kind == "data":
                if in_dt:
                    dt_buf.append(payload)
                elif in_dd:
                    dd_buf.append(payload)
                elif in_h1:
                    h1_buf.append(payload)
            elif kind == "end":
                if tag == "h1" and in_h1:
                    text = " ".join(h1_buf).strip()
                    in_h1 = False
                    if text:
                        yield CursorNode(
                            type=NODE_ELEMENT,
                            name="section",
                            data=text,
                            attributes={
                                "_quality": "blender_py_v1",
                                "_source": "blender_py",
                                "node_type": "section",
                                "tag": "h1",
                            },
                            parent="document",
                            depth=1,
                        )
                elif tag == "dt" and in_dt:
                    last_term = " ".join(dt_buf).strip()
                    in_dt = False
                    if last_term:
                        yield CursorNode(
                            type=NODE_ELEMENT,
                            name="term",
                            data=last_term,
                            attributes={
                                "_quality": "blender_py_v1",
                                "_source": "blender_py",
                                "node_type": cur_kind or "symbol",
                                "signature": last_term,
                                "qualified_id": cur_id,
                            },
                            parent="document",
                            depth=2,
                        )
                elif tag == "dd" and in_dd:
                    body = " ".join(dd_buf).strip()
                    in_dd = False
                    if body:
                        yield CursorNode(
                            type=NODE_ELEMENT,
                            name="definition",
                            data=body,
                            attributes={
                                "_quality": "blender_py_v1",
                                "_source": "blender_py",
                                "node_type": "doc",
                                "term": last_term,
                                "qualified_id": cur_id,
                            },
                            parent=last_term or "document",
                            depth=3,
                        )
                elif tag == "dl" and dl_stack:
                    dl_stack.pop()
                    cur_kind = next((k for k in reversed(dl_stack) if k is not None), None)


# ---------------------------------------------------------------------------
# Blender Compositor Adapter (v1 live)
# ---------------------------------------------------------------------------
class BlenderCompositorAdapter(DocAdapter):
    """Parse Blender Compositor node reference pages.

    Signals matched:
      - body marker "compositor" / "compositing nodes"
      - title / breadcrumb references "Compositor" or "Compositing"
      - Sphinx generated, like the bpy ref, but with section structure built
        around node families: Input nodes, Output nodes, Filter nodes, ...

    Mapping rules:
      - <h1>/<h2> → section nodes; first h1 becomes the node-family name
      - <dl><dt>… → comp_node terms (one per compositor node)
      - <ul>/<li> inside a section's body → input/output socket descriptors
        emitted as terms with node_type="socket"

    Falls back to generic walker if the page doesn't look compositor-shaped.
    """

    name = "blender_compositor"
    signature = _AdapterSignature(
        title_substr=("compositor", "compositing"),
        body_marker_substr=("compositor", "compositing nodes", "compositor node"),
    )

    def parse(self, html_bytes: bytes) -> Iterator[CursorNode]:
        events = _collect_events(html_bytes)
        head_meta = _extract_head_meta(events)

        page_title = head_meta.get("__title__") or head_meta.get("og:title") or "untitled"
        yield CursorNode(
            type=NODE_ELEMENT,
            name="document",
            data=page_title,
            attributes={
                "_quality": "blender_compositor_v1",
                "_source": "blender_compositor",
                "title": page_title,
                "url": head_meta.get("og:url", ""),
            },
            parent=None,
            depth=0,
        )

        current_family: Optional[str] = None
        in_h1 = in_h2 = in_li = in_dt = in_dd = False
        h1_buf: List[str] = []
        h2_buf: List[str] = []
        li_buf: List[str] = []
        dt_buf: List[str] = []
        dd_buf: List[str] = []
        last_term: str = ""

        # We only emit list items when nested under a section that looks like a
        # socket section ("Inputs" / "Outputs" / "Properties"). Track that.
        section_kind: str = ""

        for kind, tag, payload, depth in events:
            if kind == "start":
                if tag == "h1":
                    in_h1 = True; h1_buf = []
                elif tag == "h2":
                    in_h2 = True; h2_buf = []
                elif tag == "li":
                    in_li = True; li_buf = []
                elif tag == "dt":
                    in_dt = True; dt_buf = []
                elif tag == "dd":
                    in_dd = True; dd_buf = []
            elif kind == "data":
                if in_dt:
                    dt_buf.append(payload)
                elif in_dd:
                    dd_buf.append(payload)
                elif in_li:
                    li_buf.append(payload)
                elif in_h2:
                    h2_buf.append(payload)
                elif in_h1:
                    h1_buf.append(payload)
            elif kind == "end":
                if tag == "h1" and in_h1:
                    text = " ".join(h1_buf).strip()
                    in_h1 = False
                    if text:
                        current_family = text
                        yield CursorNode(
                            type=NODE_ELEMENT,
                            name="section",
                            data=text,
                            attributes={
                                "_quality": "blender_compositor_v1",
                                "_source": "blender_compositor",
                                "node_type": "node_family",
                                "family": text,
                                "tag": "h1",
                            },
                            parent="document",
                            depth=1,
                        )
                elif tag == "h2" and in_h2:
                    text = " ".join(h2_buf).strip()
                    in_h2 = False
                    if text:
                        lt = text.lower()
                        if "input" in lt:
                            section_kind = "input"
                        elif "output" in lt:
                            section_kind = "output"
                        elif "propert" in lt:
                            section_kind = "property"
                        else:
                            section_kind = ""
                        yield CursorNode(
                            type=NODE_ELEMENT,
                            name="section",
                            data=text,
                            attributes={
                                "_quality": "blender_compositor_v1",
                                "_source": "blender_compositor",
                                "node_type": f"{section_kind}_group" if section_kind else "section",
                                "family": current_family or "",
                                "tag": "h2",
                            },
                            parent=current_family or "document",
                            depth=2,
                        )
                elif tag == "dt" and in_dt:
                    last_term = " ".join(dt_buf).strip()
                    in_dt = False
                    if last_term:
                        yield CursorNode(
                            type=NODE_ELEMENT,
                            name="term",
                            data=last_term,
                            attributes={
                                "_quality": "blender_compositor_v1",
                                "_source": "blender_compositor",
                                "node_type": "comp_node",
                                "family": current_family or "",
                            },
                            parent=current_family or "document",
                            depth=3,
                        )
                elif tag == "dd" and in_dd:
                    body = " ".join(dd_buf).strip()
                    in_dd = False
                    if body:
                        yield CursorNode(
                            type=NODE_ELEMENT,
                            name="definition",
                            data=body,
                            attributes={
                                "_quality": "blender_compositor_v1",
                                "_source": "blender_compositor",
                                "node_type": "doc",
                                "term": last_term,
                                "family": current_family or "",
                            },
                            parent=last_term or current_family or "document",
                            depth=4,
                        )
                elif tag == "li" and in_li:
                    text = " ".join(li_buf).strip()
                    in_li = False
                    if text and section_kind:
                        yield CursorNode(
                            type=NODE_ELEMENT,
                            name="term",
                            data=text,
                            attributes={
                                "_quality": "blender_compositor_v1",
                                "_source": "blender_compositor",
                                "node_type": "socket" if section_kind in ("input", "output") else section_kind,
                                "socket_direction": section_kind,
                                "family": current_family or "",
                            },
                            parent=current_family or "document",
                            depth=3,
                        )


# ---------------------------------------------------------------------------
# Placeholder adapters — registered but raise NotImplementedError on parse()
# ---------------------------------------------------------------------------
class _PlaceholderAdapter(DocAdapter):
    """Common stub shape for not-yet-built adapters.

    They register themselves in ADAPTERS so `cc -docs-list-adapters` shows them
    as roadmap entries, but calling parse() raises a clear NotImplementedError.
    """
    placeholder_for: str = ""

    def parse(self, html_bytes: bytes) -> Iterator[CursorNode]:
        raise NotImplementedError(
            f"{self.__class__.__name__} is a registered placeholder "
            f"(target: {self.placeholder_for}). Not yet implemented."
        )


class SubstanceNodeAdapter(_PlaceholderAdapter):
    name = "substance"
    placeholder_for = "Substance Designer / Substance 3D node reference HTML"
    signature = _AdapterSignature(
        title_substr=("substance", "substance 3d"),
        body_marker_substr=("substance designer", "sbsar"),
    )


class MariProjectAdapter(_PlaceholderAdapter):
    name = "mari"
    placeholder_for = "Foundry Mari project + node reference HTML"
    signature = _AdapterSignature(
        title_substr=("mari",),
        body_marker_substr=("mari project", "foundry mari"),
    )


class FacebookSapiensAdapter(_PlaceholderAdapter):
    name = "fb_sapiens"
    placeholder_for = "Facebook / Meta Sapiens human-mesh model documentation"
    signature = _AdapterSignature(
        title_substr=("sapiens",),
        body_marker_substr=("sapiens", "facebookresearch/sapiens"),
    )


# ---------------------------------------------------------------------------
# Adapter registry
# ---------------------------------------------------------------------------
ADAPTERS: Dict[str, Type[DocAdapter]] = {
    "godot":               GodotDocAdapter,
    "blender_py":          BlenderPyAdapter,
    "blender_compositor":  BlenderCompositorAdapter,
    "substance":           SubstanceNodeAdapter,
    "mari":                MariProjectAdapter,
    "fb_sapiens":          FacebookSapiensAdapter,
}

# Public state map (kept in sync with ADAPTERS — also reflected in the agent card)
ADAPTER_STATE: Dict[str, str] = {
    "godot":               "live",
    "blender_py":          "live",
    "blender_compositor":  "live",
    "substance":           "placeholder",
    "mari":                "placeholder",
    "fb_sapiens":          "placeholder",
}


def get_adapter(name: str) -> DocAdapter:
    cls = ADAPTERS.get(name)
    if cls is None:
        raise KeyError(f"unknown adapter {name!r} — known: {sorted(ADAPTERS)}")
    return cls()


# ---------------------------------------------------------------------------
# Driver — read HTML, run adapter (with generic fallback), write JSONL,
# log a crystal anchor via InferenceLogger.
# ---------------------------------------------------------------------------
def _emit_jsonl(nodes: Iterator[CursorNode], out_path: Path) -> int:
    """Write a node iterator as JSONL using ParserWriter. Returns count."""
    writer = ParserWriter(out_path)
    n = 0
    for node in nodes:
        writer.write_node(
            type=node.type,
            name=node.name,
            data=node.data,
            attributes=node.attributes,
            parent=node.parent,
            depth=node.depth,
        )
        n += 1
    return n


def _log_anchor(adapter_name: str, html_path: Union[str, Path], out_jsonl: Path, n_nodes: int, quality: str) -> str:
    """Emit one crystal anchor per parsed page. Returns crystal_id (or '')."""
    if not _HAS_LOGGER:
        return ""
    try:
        logger = InferenceLogger()
        crystal = logger.log(
            original_prompt=str(html_path),
            enhanced_prompt=f"doc_parser:{adapter_name}",
            output_text=str(out_jsonl),
            tier="documentation",
            model="doc_parser",
            scope=f"doc_{adapter_name}",
            tokens_in=0,
            tokens_out=n_nodes,
            complexity=0.0,
            done_flag=True,
            rc=0,
            source_file=str(html_path),
            source_folder=str(out_jsonl.parent),
            source_action=f"parse_{adapter_name}",
            source_step=0,
        )
        return crystal
    except Exception as e:
        # Never let logging failure break a parse
        print(f"[doc_parser] crystal anchor failed: {e}", file=sys.stderr)
        return ""


def _run_adapter(adapter: DocAdapter, html_bytes: bytes) -> Tuple[List[CursorNode], str]:
    """Run an adapter; if it returns nothing useful or doesn't match, fall back.

    Returns (nodes_list, quality_tag).
    """
    # Quick signature check — if it mismatches, use generic walker
    if not adapter.matches(html_bytes):
        return list(_generic_walk(html_bytes, source=adapter.name)), "generic"

    try:
        nodes = list(adapter.parse(html_bytes))
    except NotImplementedError:
        raise
    except Exception as e:
        print(f"[doc_parser] adapter {adapter.name} threw: {e}; falling back to generic", file=sys.stderr)
        return list(_generic_walk(html_bytes, source=adapter.name)), "generic"

    if not nodes:
        return list(_generic_walk(html_bytes, source=adapter.name)), "generic"

    # Quality tag = first non-generic _quality value we see, else "generic"
    quality = "generic"
    for n in nodes:
        q = (n.attributes or {}).get("_quality", "")
        if q and q != "generic":
            quality = q
            break
    return nodes, quality


def parse_html_file(
    adapter_name: str,
    html_path: Union[str, Path],
    out_jsonl: Optional[Path] = None,
) -> Path:
    """Read HTML, run adapter, write JSONL to studio/assets/_doc_corpus/<adapter>/<crystal>.jsonl.

    Returns the path to the written JSONL.
    """
    p = Path(html_path)
    html_bytes = p.read_bytes()
    adapter = get_adapter(adapter_name)

    nodes, quality = _run_adapter(adapter, html_bytes)

    if out_jsonl is None:
        corpus_dir = _ensure_corpus_dir(adapter_name)
        crystal = _crystal_short(html_bytes)
        out_jsonl = corpus_dir / f"{crystal}.jsonl"
    else:
        out_jsonl = Path(out_jsonl)
        out_jsonl.parent.mkdir(parents=True, exist_ok=True)

    # ParserWriter appends, so if the file exists wipe it for an idempotent run
    if out_jsonl.exists():
        out_jsonl.unlink()

    n_nodes = _emit_jsonl(iter(nodes), out_jsonl)
    _log_anchor(adapter_name, p, out_jsonl, n_nodes, quality)
    return out_jsonl


def parse_url(
    adapter_name: str,
    url: str,
    out_jsonl: Optional[Path] = None,
    timeout: float = 30.0,
) -> Path:
    """Fetch via urllib + parse. stdlib only."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "MySpace++-doc-parser/1.0 (stdlib)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (intentional — caller supplies URL)
        html_bytes = resp.read()

    adapter = get_adapter(adapter_name)
    nodes, quality = _run_adapter(adapter, html_bytes)

    if out_jsonl is None:
        corpus_dir = _ensure_corpus_dir(adapter_name)
        crystal = _crystal_short(html_bytes)
        out_jsonl = corpus_dir / f"{crystal}.jsonl"
    else:
        out_jsonl = Path(out_jsonl)
        out_jsonl.parent.mkdir(parents=True, exist_ok=True)

    if out_jsonl.exists():
        out_jsonl.unlink()

    n_nodes = _emit_jsonl(iter(nodes), out_jsonl)
    _log_anchor(adapter_name, url, out_jsonl, n_nodes, quality)
    return out_jsonl


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _main(argv: Optional[List[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="doc_parser — generic HTML → CursorNode JSONL")
    sub = ap.add_subparsers(dest="cmd")

    p_file = sub.add_parser("parse-file", help="parse a local HTML file")
    p_file.add_argument("adapter", choices=sorted(ADAPTERS))
    p_file.add_argument("path")
    p_file.add_argument("--out", default=None)

    p_url = sub.add_parser("parse-url", help="fetch + parse a URL")
    p_url.add_argument("adapter", choices=sorted(ADAPTERS))
    p_url.add_argument("url")
    p_url.add_argument("--out", default=None)

    p_list = sub.add_parser("list", help="list registered adapters + state")

    args = ap.parse_args(argv)

    if args.cmd == "parse-file":
        out = parse_html_file(args.adapter, args.path, Path(args.out) if args.out else None)
        print(json.dumps({"ok": True, "out": str(out), "adapter": args.adapter}))
        return 0
    elif args.cmd == "parse-url":
        out = parse_url(args.adapter, args.url, Path(args.out) if args.out else None)
        print(json.dumps({"ok": True, "out": str(out), "adapter": args.adapter}))
        return 0
    elif args.cmd == "list":
        rows = [{"name": k, "state": ADAPTER_STATE[k], "class": ADAPTERS[k].__name__} for k in sorted(ADAPTERS)]
        print(json.dumps(rows, indent=2))
        return 0
    else:
        ap.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(_main())
