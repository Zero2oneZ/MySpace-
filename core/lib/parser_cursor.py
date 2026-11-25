#!/usr/bin/env python3
# ============================================================================
# AGENT CARD                                                                  =
# ----------------------------------------------------------------------------=
# name:        parser_cursor                                                  =
# role:        ENGINE · CURSOR_BASE                                           =
# tier:        L0                                                             =
# substrate:   none (base class; substrates extend it)                        =
# engine:      XMLParser cursor API verbatim                                  =
# storage:     none (reads any JSONL the caller opens)                        =
# card:        studio/assets/_agents/agent_defs/                              =
#              vm_mspc_001.agents.agent_defs.parser_cursor.active.json        =
# ----------------------------------------------------------------------------=
# ROUTING CONNECTIONS                                                         =
# ----------------------------------------------------------------------------=
# inbound:                                                                    =
#   - user_graph.UserGraph              (subclass; appends + reads turns)     =
#   - moe_router.CrystalChainCursor     (subclass; reads crystal chain)       =
# outbound:                                                                   =
#   - none (pure cursor — calls only stdlib io)                               =
# substrate touch:                                                            =
#   - reads:  whatever path the caller passes to open()                       =
#   - writes: ParserWriter appends to whatever path the caller passes         =
# ============================================================================
"""parser_cursor.py — XMLParser-shaped cursor over an append-only JSONL document.

Mirrors Godot's XMLParser API (https://docs.godotengine.org/.../XMLParser.html).
The "document" is a JSONL file where each line is one node. Each node is a dict:

    {
      "type": "element" | "text" | "comment",
      "name": "<tag>",
      "data": <any>,
      "attributes": { "key": "value", ... },
      "parent": "<tag>" | null,
      "depth": int
    }

The cursor walks lines in file order. seek() jumps to any byte offset. skip_section()
fast-forwards past the current element's children by walking forward until we leave
the element's depth.

Why XMLParser shape: it's the engine pattern behind the BRAID DAG and the MoE router.
A node is addressable (by offset), inspectable (by attribute), and swappable (in BRAID,
skip_section becomes splice). user_graph and moe_router both build on this base.

Determinism: same JSONL bytes → same walk order → same node offsets. No randomness.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Union

# ---------------------------------------------------------------------------
# Node type constants — match XMLParser.NodeType from Godot
# ---------------------------------------------------------------------------
NODE_NONE = "none"
NODE_ELEMENT = "element"
NODE_ELEMENT_END = "element_end"
NODE_TEXT = "text"
NODE_COMMENT = "comment"
NODE_CDATA = "cdata"
NODE_UNKNOWN = "unknown"
NODE_EOF = "eof"


# ---------------------------------------------------------------------------
# Error codes — match Godot's Error enum subset we care about
# ---------------------------------------------------------------------------
OK = 0
ERR_FILE_NOT_FOUND = 7
ERR_FILE_EOF = 8
ERR_PARSE_ERROR = 43


# ---------------------------------------------------------------------------
# Node dataclass — the cursor's "current node" snapshot
# ---------------------------------------------------------------------------
@dataclass
class CursorNode:
    type: str = NODE_NONE
    name: str = ""
    data: Any = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    parent: Optional[str] = None
    depth: int = 0
    offset: int = 0    # byte offset of the line where this node starts
    line_no: int = 0   # 1-based line number


# ---------------------------------------------------------------------------
# ParserCursor — the XMLParser-shaped reader
# ---------------------------------------------------------------------------
class ParserCursor:
    """Streaming cursor over an append-only JSONL document.

    Usage (mirrors XMLParser exactly):

        parser = ParserCursor()
        if parser.open("path/to/doc.jsonl") != OK:
            return
        while parser.read() != ERR_FILE_EOF:
            if parser.get_node_type() == NODE_ELEMENT:
                name = parser.get_node_name()
                for key in parser.get_attribute_names():
                    val = parser.get_named_attribute_value(key)
                    ...
    """

    def __init__(self):
        self._fh = None
        self._path: Optional[Path] = None
        self._current: CursorNode = CursorNode(type=NODE_NONE)
        self._line_no: int = 0
        self._byte_offset: int = 0    # offset where the *next* read will start

    # ---- open / close --------------------------------------------------

    def open(self, source: Union[str, Path]) -> int:
        """Open a JSONL document for reading. Returns OK or ERR_*."""
        p = Path(source)
        if not p.exists():
            return ERR_FILE_NOT_FOUND
        try:
            self._fh = open(p, "rb")
        except OSError:
            return ERR_FILE_NOT_FOUND
        self._path = p
        self._line_no = 0
        self._byte_offset = 0
        self._current = CursorNode(type=NODE_NONE)
        return OK

    def open_buffer(self, buffer: bytes) -> int:
        """Open an in-memory byte buffer. Returns OK or ERR_*."""
        import io
        self._fh = io.BytesIO(buffer)
        self._path = None
        self._line_no = 0
        self._byte_offset = 0
        self._current = CursorNode(type=NODE_NONE)
        return OK

    def close(self) -> None:
        if self._fh is not None:
            try:
                self._fh.close()
            finally:
                self._fh = None

    # ---- read / seek / skip --------------------------------------------

    def read(self) -> int:
        """Advance one node. Returns OK or ERR_FILE_EOF."""
        if self._fh is None:
            return ERR_FILE_EOF

        while True:
            line_start = self._fh.tell()
            raw = self._fh.readline()
            if not raw:
                self._current = CursorNode(type=NODE_EOF, offset=line_start, line_no=self._line_no)
                return ERR_FILE_EOF

            self._line_no += 1
            self._byte_offset = line_start

            stripped = raw.strip()
            if not stripped:
                # Skip blank lines.
                continue

            try:
                node_dict = json.loads(stripped)
            except json.JSONDecodeError:
                self._current = CursorNode(
                    type=NODE_UNKNOWN,
                    data=raw.decode("utf-8", errors="replace"),
                    offset=line_start,
                    line_no=self._line_no,
                )
                return OK

            self._current = self._dict_to_node(node_dict, line_start, self._line_no)
            return OK

    def seek(self, position: int) -> int:
        """Jump cursor to a byte offset (start of a JSONL line). Returns OK."""
        if self._fh is None:
            return ERR_FILE_EOF
        self._fh.seek(position)
        self._byte_offset = position
        # line_no becomes approximate after a seek — count from start if accurate is needed
        return OK

    def skip_section(self) -> None:
        """Walk forward until we leave the current element's depth.

        XMLParser's skip_section() fast-forwards past the current element's children.
        Here we walk until we hit a node whose depth <= current depth, OR EOF.
        """
        if self._current.type == NODE_NONE or self._current.type == NODE_EOF:
            return
        anchor_depth = self._current.depth
        while True:
            rc = self.read()
            if rc == ERR_FILE_EOF:
                return
            if self._current.depth <= anchor_depth:
                # We've exited the section.
                return

    # ---- node inspection (mirrors XMLParser getters) ------------------

    def get_node_type(self) -> str:
        return self._current.type

    def get_node_name(self) -> str:
        return self._current.name

    def get_node_data(self) -> Any:
        return self._current.data

    def get_node_offset(self) -> int:
        return self._current.offset

    def get_current_line(self) -> int:
        return self._current.line_no

    def is_empty(self) -> bool:
        return self._current.data in (None, "", [], {})

    # ---- attribute accessors (mirrors XMLParser) -----------------------

    def get_attribute_count(self) -> int:
        return len(self._current.attributes)

    def get_attribute_names(self) -> list:
        return list(self._current.attributes.keys())

    def get_attribute_name(self, idx: int) -> str:
        keys = list(self._current.attributes.keys())
        if 0 <= idx < len(keys):
            return keys[idx]
        return ""

    def get_attribute_value(self, idx: int) -> Any:
        keys = list(self._current.attributes.keys())
        if 0 <= idx < len(keys):
            return self._current.attributes[keys[idx]]
        return ""

    def has_attribute(self, name: str) -> bool:
        return name in self._current.attributes

    def get_named_attribute_value(self, name: str) -> Any:
        if name not in self._current.attributes:
            raise KeyError(f"attribute {name!r} not on current node")
        return self._current.attributes[name]

    def get_named_attribute_value_safe(self, name: str) -> Any:
        """Like get_named_attribute_value but returns "" instead of raising."""
        return self._current.attributes.get(name, "")

    # ---- iteration helper (not in XMLParser but ergonomic) -------------

    def walk(self) -> Iterator[CursorNode]:
        """Yield every node from current position to EOF."""
        while True:
            rc = self.read()
            if rc == ERR_FILE_EOF:
                return
            yield self._current

    # ---- internals -----------------------------------------------------

    @staticmethod
    def _dict_to_node(d: Dict[str, Any], offset: int, line_no: int) -> CursorNode:
        return CursorNode(
            type=d.get("type", NODE_ELEMENT),
            name=d.get("name", ""),
            data=d.get("data"),
            attributes=d.get("attributes", {}) or {},
            parent=d.get("parent"),
            depth=int(d.get("depth", 0)),
            offset=offset,
            line_no=line_no,
        )


# ---------------------------------------------------------------------------
# ParserWriter — emit JSONL nodes in the shape ParserCursor expects
# ---------------------------------------------------------------------------
class ParserWriter:
    """Append-only writer that produces JSONL ParserCursor can read."""

    def __init__(self, path: Union[str, Path]):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write_node(
        self,
        type: str,
        name: str = "",
        data: Any = None,
        attributes: Optional[Dict[str, Any]] = None,
        parent: Optional[str] = None,
        depth: int = 0,
    ) -> int:
        """Append a node line. Returns the byte offset of the written line."""
        offset = self.path.stat().st_size if self.path.exists() else 0
        node = {
            "type": type,
            "name": name,
            "data": data,
            "attributes": attributes or {},
            "parent": parent,
            "depth": depth,
        }
        line = json.dumps(node, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line)
            f.write("\n")
        return offset


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

def _main():
    import argparse
    import sys

    ap = argparse.ArgumentParser(description="parser_cursor — XMLParser-shaped JSONL walker")
    sub = ap.add_subparsers(dest="cmd")

    p_walk = sub.add_parser("walk", help="walk a JSONL document and print each node")
    p_walk.add_argument("path")

    p_write = sub.add_parser("write-demo", help="write a small demo JSONL document")
    p_write.add_argument("path")

    args = ap.parse_args()

    if args.cmd == "walk":
        cur = ParserCursor()
        if cur.open(args.path) != OK:
            print(f"could not open {args.path}", file=sys.stderr)
            sys.exit(1)
        n = 0
        for node in cur.walk():
            n += 1
            attrs = ",".join(f"{k}={v!r}" for k, v in node.attributes.items())
            print(f"[{node.line_no:>4}] @{node.offset:<6} d{node.depth} {node.type:<12} name={node.name!r:<24} {attrs}")
        print(f"--- {n} nodes ---", file=sys.stderr)
    elif args.cmd == "write-demo":
        w = ParserWriter(args.path)
        w.write_node(NODE_ELEMENT, name="root", attributes={"version": "1"}, depth=0)
        w.write_node(NODE_ELEMENT, name="turn", attributes={"user": "tom", "idx": 0}, parent="root", depth=1)
        w.write_node(NODE_TEXT, name="words", data="build the forward projector", parent="turn", depth=2)
        w.write_node(NODE_ELEMENT_END, name="turn", parent="root", depth=1)
        w.write_node(NODE_ELEMENT, name="turn", attributes={"user": "tom", "idx": 1}, parent="root", depth=1)
        w.write_node(NODE_TEXT, name="words", data="now build user graph", parent="turn", depth=2)
        w.write_node(NODE_ELEMENT_END, name="turn", parent="root", depth=1)
        w.write_node(NODE_ELEMENT_END, name="root", depth=0)
        print(f"wrote demo to {args.path}")
    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
