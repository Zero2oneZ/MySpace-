#!/usr/bin/env python3
# ============================================================================
# AGENT CARD                                                                  =
# ----------------------------------------------------------------------------=
# name:        doc_parser_facebook_games                                      =
# role:        ENGINE · DOC_ADAPTER · FACEBOOK_GAMES                          =
# tier:        L0                                                             =
# substrate:   _doc_corpus/facebook_games                                     =
# engine:      extends doc_parser.DocAdapter; registers FacebookGamesAdapter  =
# storage:     studio/assets/_doc_corpus/facebook_games/<crystal>.jsonl       =
# card:        studio/assets/_agents/agent_defs/                              =
#              vm_mspc_001.agents.agent_defs.facebook_games_docs.active.json  =
# ----------------------------------------------------------------------------=
# ROUTING CONNECTIONS                                                         =
# ----------------------------------------------------------------------------=
# inbound:                                                                    =
#   - core/scripts/facebook_games_ingest.sh (driver script)                   =
#   - dag_loop.load_docs() — walks _doc_corpus/facebook_games/*.jsonl         =
# outbound:                                                                   =
#   - doc_parser.ADAPTERS['facebook_games'] (registry insertion)              =
#   - doc_parser.parse_url() / parse_html_file() — driver entry points        =
#   - inference_logger.InferenceLogger.log() (one crystal per page)           =
# substrate touch:                                                            =
#   - reads:  HTML bytes from developers.facebook.com/docs/games/...          =
#   - writes: studio/assets/_doc_corpus/facebook_games/<crystal>.jsonl        =
# ============================================================================
"""doc_parser_facebook_games.py — Facebook Games developer doc adapter.

DOES NOT modify doc_parser.py. Imports its base class + registry, defines
FacebookGamesAdapter, and exposes register() so callers can splice the new
adapter into the running registry without edit-conflicts on doc_parser.py.

The Facebook Games docs are React-rendered SSR pages. The structure that
survives in the static HTML is:

    <title>... | Facebook for Developers</title>
    <meta property="og:site_name" content="Facebook for Developers">
    <body>
      ... lots of nav/cookie shells ...
      <main> (sometimes; usually a div with data-testid)
        <h1>...</h1>
        <h2>...</h2>
        <p>...</p>
        <pre><code>...</code></pre>
        <a href="/docs/games/...">guide link</a>
        <dl><dt>SDK method</dt><dd>desc</dd></dl>  (rare but happens)
      </main>
    </body>

Mapping rules (when adapter signature matches):
  - h1            -> CursorNode(node_type="section", depth=1)
  - h2            -> CursorNode(node_type="section", depth=2)
  - h3            -> CursorNode(node_type="section", depth=3)
  - dt + dd       -> CursorNode(node_type="sdk_method") then ("definition")
  - <pre><code>   -> CursorNode(node_type="code_sample") with language attr
  - <a href> ptr  -> CursorNode(node_type="guide_link") (only if href matches
                     /docs/games/... — internal doc cross-link)

Fallback: if .matches() returns False the generic _generic_walk from
doc_parser is used (driver triggers it; this module never duplicates it).

Determinism: same HTML bytes -> same node stream -> same JSONL bytes.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

# Make the sibling doc_parser importable regardless of the caller's cwd.
_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import doc_parser  # noqa: E402 (sys.path mutation above)
from doc_parser import (  # noqa: E402
    DocAdapter,
    _AdapterSignature,
    _collect_events,
    _extract_head_meta,
)
from parser_cursor import CursorNode, NODE_ELEMENT  # noqa: E402


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------
class FacebookGamesAdapter(DocAdapter):
    """Parse Facebook for Developers / Games doc pages.

    Detected by either:
      - <title> contains "Facebook for Developers"
      - <meta property="og:site_name" content="Facebook for Developers">
      - body markers "developers.facebook.com/docs/games" / "instant games"

    Emits node_type in {section, sdk_method, code_sample, guide_link, doc}.
    The first node yielded is always the document header carrying page title
    + canonical url so downstream walkers can stitch pages together.
    """

    name = "facebook_games"
    signature = _AdapterSignature(
        site_name_substr=("facebook for developers",),
        title_substr=("facebook for developers", "facebook gaming", "instant games"),
        body_marker_substr=(
            "developers.facebook.com/docs/games",
            "instant games",
            "graph api",
            "facebook gaming services",
            "fb gaming",
        ),
    )

    # Tags whose end events we react to in parse()
    _SECTION_TAGS = {"h1", "h2", "h3"}

    def parse(self, html_bytes: bytes) -> Iterator[CursorNode]:
        events = _collect_events(html_bytes)
        head_meta = _extract_head_meta(events)

        page_title = (
            head_meta.get("__title__")
            or head_meta.get("og:title")
            or "untitled"
        )
        canonical_url = (
            head_meta.get("og:url")
            or head_meta.get("canonical")
            or ""
        )

        # 1) Document header — always emitted first
        yield CursorNode(
            type=NODE_ELEMENT,
            name="document",
            data=page_title,
            attributes={
                "_quality": "facebook_games_v1",
                "_source": "facebook_games",
                "title": page_title,
                "site_name": head_meta.get("og:site_name", ""),
                "url": canonical_url,
                "description": head_meta.get("og:description", "")[:512],
            },
            parent=None,
            depth=0,
        )

        # 2) Walk the body — track section context so methods nest under h2
        current_h1: Optional[str] = None
        current_h2: Optional[str] = None

        in_h1 = in_h2 = in_h3 = False
        in_dt = in_dd = False
        in_pre = in_code = False
        in_a = False

        h1_buf: List[str] = []
        h2_buf: List[str] = []
        h3_buf: List[str] = []
        dt_buf: List[str] = []
        dd_buf: List[str] = []
        code_buf: List[str] = []
        a_buf: List[str] = []

        last_term: str = ""
        pre_attrs: Dict[str, str] = {}
        a_attrs: Dict[str, str] = {}

        for kind, tag, payload, depth in events:
            if kind == "start":
                if tag == "h1":
                    in_h1 = True; h1_buf = []
                elif tag == "h2":
                    in_h2 = True; h2_buf = []
                elif tag == "h3":
                    in_h3 = True; h3_buf = []
                elif tag == "dt":
                    in_dt = True; dt_buf = []
                elif tag == "dd":
                    in_dd = True; dd_buf = []
                elif tag == "pre":
                    in_pre = True
                    pre_attrs = payload or {}
                    code_buf = []
                elif tag == "code" and in_pre:
                    in_code = True
                elif tag == "a":
                    in_a = True
                    a_attrs = payload or {}
                    a_buf = []
            elif kind == "data":
                if in_dt:
                    dt_buf.append(payload)
                elif in_dd:
                    dd_buf.append(payload)
                elif in_pre:
                    # Preserve code samples as-is (don't merge into surrounding text)
                    code_buf.append(payload)
                elif in_a:
                    a_buf.append(payload)
                elif in_h3:
                    h3_buf.append(payload)
                elif in_h2:
                    h2_buf.append(payload)
                elif in_h1:
                    h1_buf.append(payload)
            elif kind == "end":
                if tag == "h1" and in_h1:
                    text = " ".join(h1_buf).strip()
                    in_h1 = False
                    if text:
                        current_h1 = text
                        current_h2 = None
                        yield CursorNode(
                            type=NODE_ELEMENT,
                            name="section",
                            data=text,
                            attributes={
                                "_quality": "facebook_games_v1",
                                "_source": "facebook_games",
                                "node_type": "section",
                                "section_level": "1",
                                "tag": "h1",
                            },
                            parent="document",
                            depth=1,
                        )
                elif tag == "h2" and in_h2:
                    text = " ".join(h2_buf).strip()
                    in_h2 = False
                    if text:
                        current_h2 = text
                        yield CursorNode(
                            type=NODE_ELEMENT,
                            name="section",
                            data=text,
                            attributes={
                                "_quality": "facebook_games_v1",
                                "_source": "facebook_games",
                                "node_type": "section",
                                "section_level": "2",
                                "h1_context": current_h1 or "",
                                "tag": "h2",
                            },
                            parent=current_h1 or "document",
                            depth=2,
                        )
                elif tag == "h3" and in_h3:
                    text = " ".join(h3_buf).strip()
                    in_h3 = False
                    if text:
                        yield CursorNode(
                            type=NODE_ELEMENT,
                            name="section",
                            data=text,
                            attributes={
                                "_quality": "facebook_games_v1",
                                "_source": "facebook_games",
                                "node_type": "section",
                                "section_level": "3",
                                "h1_context": current_h1 or "",
                                "h2_context": current_h2 or "",
                                "tag": "h3",
                            },
                            parent=current_h2 or current_h1 or "document",
                            depth=3,
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
                                "_quality": "facebook_games_v1",
                                "_source": "facebook_games",
                                "node_type": "sdk_method",
                                "signature": last_term,
                                "h1_context": current_h1 or "",
                                "h2_context": current_h2 or "",
                            },
                            parent=current_h2 or current_h1 or "document",
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
                                "_quality": "facebook_games_v1",
                                "_source": "facebook_games",
                                "node_type": "doc",
                                "term": last_term,
                                "h1_context": current_h1 or "",
                                "h2_context": current_h2 or "",
                            },
                            parent=last_term or current_h2 or current_h1 or "document",
                            depth=4,
                        )
                elif tag == "code" and in_code:
                    in_code = False
                elif tag == "pre" and in_pre:
                    code_text = "".join(code_buf).strip()
                    in_pre = False
                    code_buf = []
                    if code_text:
                        # Detect language hint from <pre class="..."> / <code class="...">
                        cls = (pre_attrs.get("class") or "").lower()
                        lang = _detect_language(cls, code_text)
                        yield CursorNode(
                            type=NODE_ELEMENT,
                            name="code",
                            data=code_text,
                            attributes={
                                "_quality": "facebook_games_v1",
                                "_source": "facebook_games",
                                "node_type": "code_sample",
                                "language": lang,
                                "h1_context": current_h1 or "",
                                "h2_context": current_h2 or "",
                            },
                            parent=current_h2 or current_h1 or "document",
                            depth=3,
                        )
                elif tag == "a" and in_a:
                    text = " ".join(a_buf).strip()
                    href = (a_attrs.get("href") or "").strip()
                    in_a = False
                    if href and _is_games_doc_link(href) and text:
                        yield CursorNode(
                            type=NODE_ELEMENT,
                            name="link",
                            data=text,
                            attributes={
                                "_quality": "facebook_games_v1",
                                "_source": "facebook_games",
                                "node_type": "guide_link",
                                "href": href,
                                "h1_context": current_h1 or "",
                                "h2_context": current_h2 or "",
                            },
                            parent=current_h2 or current_h1 or "document",
                            depth=3,
                        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _detect_language(class_attr: str, code_text: str) -> str:
    """Best-effort language detection from <pre>/<code> class + content hints."""
    cls = class_attr.lower()
    for marker in (
        "javascript", "typescript", "python", "java", "kotlin", "swift",
        "objectivec", "objective-c", "csharp", "c#", "cpp", "c++", "ruby",
        "php", "go", "rust", "bash", "shell", "html", "json", "xml", "yaml",
    ):
        if marker in cls:
            return marker.replace("c#", "csharp").replace("c++", "cpp").replace(
                "objective-c", "objectivec"
            )
    head = code_text[:128].lstrip()
    if head.startswith("{") or head.startswith("["):
        return "json"
    if head.startswith("<"):
        return "html"
    if "FBInstant" in code_text or "function " in head or "const " in head or "let " in head:
        return "javascript"
    if head.startswith("#!/"):
        return "bash"
    return "unknown"


def _is_games_doc_link(href: str) -> bool:
    """True if the href looks like an internal Facebook Games doc cross-link."""
    h = href.strip().lower()
    if not h:
        return False
    if h.startswith("#") or h.startswith("mailto:") or h.startswith("javascript:"):
        return False
    return (
        "/docs/games" in h
        or "/docs/games-services" in h
        or "/docs/instant" in h
        or "/docs/cloud-gaming" in h
    )


# ---------------------------------------------------------------------------
# Registry splice — call register() to make doc_parser.parse_url('facebook_games', ...) work
# ---------------------------------------------------------------------------
def register() -> str:
    """Splice FacebookGamesAdapter into doc_parser.ADAPTERS at runtime.

    Returns the adapter name that was registered. Idempotent — safe to call
    multiple times in one process.
    """
    doc_parser.ADAPTERS["facebook_games"] = FacebookGamesAdapter
    # Mirror state into ADAPTER_STATE if present
    state_map = getattr(doc_parser, "ADAPTER_STATE", None)
    if isinstance(state_map, dict):
        state_map["facebook_games"] = "live"
    return "facebook_games"


# Auto-register on import. Tom's driver scripts can either:
#   (a) `import doc_parser_facebook_games`  (auto-registers)
#   (b) `from doc_parser_facebook_games import register; register()` (explicit)
# Both work.
register()


if __name__ == "__main__":
    # Smoke: print the registered adapter set.
    import json as _json
    print(_json.dumps({
        "registered": "facebook_games" in doc_parser.ADAPTERS,
        "adapters": sorted(doc_parser.ADAPTERS.keys()),
        "state": doc_parser.ADAPTER_STATE.get("facebook_games", ""),
    }, indent=2))
