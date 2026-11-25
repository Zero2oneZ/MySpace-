#!/usr/bin/env python3
# ============================================================================
# AGENT CARD                                                                  =
# ----------------------------------------------------------------------------=
# name:        user_graph                                                     =
# role:        SUBSTRATE · USER_CHAIN_OF_THOUGHT                              =
# tier:        L0                                                             =
# substrate:   user_graph (the user's words → prompt → produced_chain DAG)    =
# engine:      extends ParserCursor (XMLParser API); writer appends turns +   =
#              ngrams + edges to JSONL                                        =
# storage:     ~/.cc/user_graph.jsonl                                         =
# card:        studio/assets/_agents/agent_defs/                              =
#              vm_mspc_001.agents.agent_defs.user_graph.active.json           =
# ----------------------------------------------------------------------------=
# ROUTING CONNECTIONS                                                         =
# ----------------------------------------------------------------------------=
# inbound:                                                                    =
#   - chat.py::_user_graph_predict  (cmd_full / cmd_godot pre-pipeline)       =
#   - chat.py::_user_graph_record   (cmd_full / cmd_godot post-log)           =
#   - CLI: python3 user_graph.py record | predict | walk | ngrams             =
# outbound:                                                                   =
#   - parser_cursor.ParserCursor (base class)                                 =
#   - parser_cursor.ParserWriter (appends to user_graph.jsonl)                =
# substrate touch:                                                            =
#   - reads:  ~/.cc/user_graph.jsonl  (UserGraphIndex.build_from)             =
#   - writes: ~/.cc/user_graph.jsonl  (record_turn: ~N+5 lines per turn)      =
# cross-substrate:                                                            =
#   - each <turn> carries chain_crystal pointing to its inference_logger      =
#     record (joinable via crystal_id)                                        =
#   - ngram hashes match moe_router's hashes (same algorithm, same key)       =
# ============================================================================
"""user_graph.py — XMLParser-shaped graph over a user's chain of thought.

The graph is an append-only JSONL document. Each chat turn lands as a `<turn>`
element with children (`words`, `prompt`, `produced_chain`, `forward_chain`,
plus a sequence of `<ngram>` children). Edges link n-gram hashes from one turn
to the next turn's outputs, so we can answer "what did the user typically do
after typing X" without retraining.

Storage: ~/.cc/user_graph.jsonl (configurable via CC_HOME).

Build pattern (mirrors XMLParser exactly):

    g = UserGraph()
    g.open()
    while g.read() != ERR_FILE_EOF:
        if g.get_node_type() == NODE_ELEMENT and g.get_node_name() == "turn":
            user = g.get_named_attribute_value_safe("user")
            ...

Query pattern:

    g = UserGraph()
    g.open()
    index = UserGraphIndex.build_from(g)
    predictions = index.predict_next("build forward projector", k=5)

Determinism: n-gram extraction is rule-based, hashes are blake3-truncated, the
in-memory index walks the JSONL in file order. Same bytes → same predictions.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Reuse the cursor base — XMLParser semantics stay visible.
from parser_cursor import (
    ParserCursor,
    ParserWriter,
    CursorNode,
    NODE_ELEMENT,
    NODE_ELEMENT_END,
    NODE_TEXT,
    NODE_EOF,
    OK,
    ERR_FILE_EOF,
    ERR_FILE_NOT_FOUND,
)

CC_HOME = Path(os.environ.get("CC_HOME", str(Path.home() / ".cc")))
USER_GRAPH_PATH = CC_HOME / "user_graph.jsonl"

# Try blake3; fall back to blake2b.
try:
    import blake3 as _blake3_mod
    def _hash(data: bytes) -> str:
        return _blake3_mod.blake3(data).hexdigest()
except ImportError:
    def _hash(data: bytes) -> str:
        return hashlib.blake2b(data).hexdigest()


# ---------------------------------------------------------------------------
# N-gram extraction (deterministic, language-agnostic, word-level)
# ---------------------------------------------------------------------------
_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _tokens(text: str) -> List[str]:
    return [t.lower() for t in _WORD_RE.findall(text or "")]


def extract_ngrams(text: str, sizes: Iterable[int] = (2, 3)) -> List[Tuple[str, str]]:
    """Return list of (ngram_text, ngram_hash) tuples. Deterministic order."""
    toks = _tokens(text)
    out: List[Tuple[str, str]] = []
    seen: set = set()
    for size in sizes:
        if size <= 0 or len(toks) < size:
            continue
        for i in range(len(toks) - size + 1):
            gram_text = " ".join(toks[i : i + size])
            if gram_text in seen:
                continue
            seen.add(gram_text)
            gram_hash = _hash(gram_text.encode("utf-8"))[:16]
            out.append((gram_text, gram_hash))
    return out


# ---------------------------------------------------------------------------
# UserGraph — XMLParser-shaped reader + writer
# ---------------------------------------------------------------------------
class UserGraph(ParserCursor):
    """The user's chain-of-thought graph. Inherits XMLParser cursor semantics
    and adds writers for the turn/edge protocol."""

    def __init__(self, path: Optional[Path] = None):
        super().__init__()
        self.path = Path(path) if path else USER_GRAPH_PATH
        self._writer = ParserWriter(self.path)

    def open(self, source=None) -> int:  # type: ignore[override]
        """Open the user graph. If file doesn't exist yet, seed it with a <root>."""
        path = Path(source) if source else self.path
        if not path.exists():
            self._writer.path = path
            self._writer.write_node(NODE_ELEMENT, name="root", attributes={"schema": "user_graph_v1"}, depth=0)
        return super().open(path)

    # ---- recording (writer side) --------------------------------------

    def record_turn(
        self,
        user: str,
        words: str,
        prompt: str = "",
        chain_crystal: str = "",
        tier: str = "",
        produced_chain: Optional[Dict[str, Any]] = None,
        forward_chain: str = "",
        turn_idx: Optional[int] = None,
        timestamp: Optional[str] = None,
    ) -> str:
        """Append one turn to the graph. Returns the turn's UUID (hash-based)."""
        ts = timestamp or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        idx = turn_idx if turn_idx is not None else self._next_turn_idx()

        # Turn UUID is deterministic from (user, idx, timestamp, words).
        turn_uuid = _hash(f"{user}|{idx}|{ts}|{words}".encode("utf-8"))[:24]

        # Open the <turn> element.
        self._writer.write_node(
            NODE_ELEMENT,
            name="turn",
            attributes={
                "uuid": turn_uuid,
                "user": user,
                "turn_idx": idx,
                "timestamp": ts,
                "chain_crystal": chain_crystal,
                "tier": tier,
            },
            parent="root",
            depth=1,
        )

        # Child text nodes.
        self._writer.write_node(NODE_TEXT, name="words", data=words, parent="turn", depth=2)
        if prompt:
            self._writer.write_node(NODE_TEXT, name="prompt", data=prompt, parent="turn", depth=2)
        if produced_chain is not None:
            self._writer.write_node(NODE_TEXT, name="produced_chain", data=produced_chain, parent="turn", depth=2)
        if forward_chain:
            self._writer.write_node(NODE_TEXT, name="forward_chain", data=forward_chain, parent="turn", depth=2)

        # N-gram children — each one indexes this turn in the predictor.
        grams = extract_ngrams(words)
        for gram_text, gram_hash in grams:
            self._writer.write_node(
                NODE_ELEMENT,
                name="ngram",
                attributes={"hash": gram_hash, "size": len(gram_text.split())},
                data=gram_text,
                parent="turn",
                depth=2,
            )

        # Close <turn>.
        self._writer.write_node(NODE_ELEMENT_END, name="turn", parent="root", depth=1)

        return turn_uuid

    def record_edge(self, from_ngram_hash: str, to_turn_uuid: str, weight: float = 1.0) -> None:
        """Append a graph edge (n-gram → past turn). Edges accumulate over time."""
        self._writer.write_node(
            NODE_ELEMENT,
            name="ngram_edge",
            attributes={"from_hash": from_ngram_hash, "to_turn_uuid": to_turn_uuid, "weight": weight},
            parent="root",
            depth=1,
        )

    def _next_turn_idx(self) -> int:
        """Count existing <turn> elements to assign next idx."""
        if not self.path.exists():
            return 0
        idx = 0
        scratch = ParserCursor()
        if scratch.open(self.path) != OK:
            return 0
        try:
            while scratch.read() != ERR_FILE_EOF:
                if scratch.get_node_type() == NODE_ELEMENT and scratch.get_node_name() == "turn":
                    idx += 1
        finally:
            scratch.close()
        return idx


# ---------------------------------------------------------------------------
# UserGraphIndex — fast in-memory predictor over the graph
# ---------------------------------------------------------------------------
@dataclass
class TurnRecord:
    uuid: str
    turn_idx: int
    user: str
    timestamp: str
    chain_crystal: str = ""
    tier: str = ""
    words: str = ""
    prompt: str = ""
    forward_chain: str = ""
    produced_chain: Any = None
    ngram_hashes: List[str] = field(default_factory=list)


@dataclass
class Prediction:
    turn_uuid: str
    score: int
    matched_ngrams: List[str]
    words: str
    prompt: str
    forward_chain: str
    timestamp: str
    tier: str
    chain_crystal: str


class UserGraphIndex:
    """In-memory n-gram → past-turn map. Built by walking a UserGraph once."""

    def __init__(self):
        self.turns: Dict[str, TurnRecord] = {}
        self.ngram_to_turns: Dict[str, List[str]] = {}

    @classmethod
    def build_from(cls, graph: UserGraph) -> "UserGraphIndex":
        """Walk the graph from the start and build the index. Idempotent."""
        idx = cls()
        # Re-open from offset 0 to ensure deterministic walk order.
        graph.seek(0)

        current_turn: Optional[TurnRecord] = None

        while graph.read() != ERR_FILE_EOF:
            node_type = graph.get_node_type()
            node_name = graph.get_node_name()

            if node_type == NODE_ELEMENT and node_name == "turn":
                current_turn = TurnRecord(
                    uuid=graph.get_named_attribute_value_safe("uuid"),
                    turn_idx=int(graph.get_named_attribute_value_safe("turn_idx") or 0),
                    user=graph.get_named_attribute_value_safe("user"),
                    timestamp=graph.get_named_attribute_value_safe("timestamp"),
                    chain_crystal=graph.get_named_attribute_value_safe("chain_crystal"),
                    tier=graph.get_named_attribute_value_safe("tier"),
                )
                if current_turn.uuid:
                    idx.turns[current_turn.uuid] = current_turn
                continue

            if node_type == NODE_ELEMENT_END and node_name == "turn":
                current_turn = None
                continue

            if current_turn is None:
                # Sibling element (e.g., ngram_edge) — not a turn child.
                continue

            if node_type == NODE_TEXT:
                if node_name == "words":
                    current_turn.words = graph.get_node_data() or ""
                elif node_name == "prompt":
                    current_turn.prompt = graph.get_node_data() or ""
                elif node_name == "forward_chain":
                    current_turn.forward_chain = graph.get_node_data() or ""
                elif node_name == "produced_chain":
                    current_turn.produced_chain = graph.get_node_data()
                continue

            if node_type == NODE_ELEMENT and node_name == "ngram":
                gram_hash = graph.get_named_attribute_value_safe("hash")
                if gram_hash:
                    current_turn.ngram_hashes.append(gram_hash)
                    idx.ngram_to_turns.setdefault(gram_hash, []).append(current_turn.uuid)
                continue

        return idx

    def predict_next(self, words: str, k: int = 5) -> List[Prediction]:
        """Given new user words, find past turns with overlapping n-grams."""
        if not words:
            return []
        incoming = extract_ngrams(words)
        scores: Dict[str, int] = {}
        matched: Dict[str, List[str]] = {}
        for gram_text, gram_hash in incoming:
            for turn_uuid in self.ngram_to_turns.get(gram_hash, []):
                scores[turn_uuid] = scores.get(turn_uuid, 0) + 1
                matched.setdefault(turn_uuid, []).append(gram_text)

        ranked = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
        out: List[Prediction] = []
        for turn_uuid, score in ranked[:k]:
            t = self.turns.get(turn_uuid)
            if not t:
                continue
            out.append(Prediction(
                turn_uuid=turn_uuid,
                score=score,
                matched_ngrams=matched.get(turn_uuid, []),
                words=t.words,
                prompt=t.prompt,
                forward_chain=t.forward_chain,
                timestamp=t.timestamp,
                tier=t.tier,
                chain_crystal=t.chain_crystal,
            ))
        return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main():
    import argparse
    import sys

    ap = argparse.ArgumentParser(description="user_graph — XMLParser-shaped chain-of-thought graph")
    sub = ap.add_subparsers(dest="cmd")

    p_rec = sub.add_parser("record", help="record one turn")
    p_rec.add_argument("--user", default=os.environ.get("USER", "anon"))
    p_rec.add_argument("--words", required=True)
    p_rec.add_argument("--prompt", default="")
    p_rec.add_argument("--chain-crystal", default="")
    p_rec.add_argument("--tier", default="")
    p_rec.add_argument("--forward", default="")

    p_pred = sub.add_parser("predict", help="predict next turns for given words")
    p_pred.add_argument("words")
    p_pred.add_argument("-k", type=int, default=5)
    p_pred.add_argument("--json", action="store_true")

    p_walk = sub.add_parser("walk", help="dump the graph node by node")

    p_grams = sub.add_parser("ngrams", help="extract n-grams from text (debug)")
    p_grams.add_argument("text")

    args = ap.parse_args()
    g = UserGraph()

    if args.cmd == "record":
        g.open()
        uuid = g.record_turn(
            user=args.user,
            words=args.words,
            prompt=args.prompt,
            chain_crystal=args.chain_crystal,
            tier=args.tier,
            forward_chain=args.forward,
        )
        print(json.dumps({"turn_uuid": uuid}, indent=2))

    elif args.cmd == "predict":
        g.open()
        idx = UserGraphIndex.build_from(g)
        preds = idx.predict_next(args.words, args.k)
        if args.json:
            print(json.dumps([{
                "turn_uuid": p.turn_uuid,
                "score": p.score,
                "matched_ngrams": p.matched_ngrams,
                "words": p.words,
                "prompt": p.prompt[:200],
                "forward_chain": p.forward_chain[:200],
                "timestamp": p.timestamp,
                "tier": p.tier,
            } for p in preds], indent=2))
        else:
            for p in preds:
                print(f"[score={p.score}] turn {p.turn_uuid[:12]} ({p.timestamp})")
                print(f"  words: {p.words[:80]}")
                print(f"  matched: {', '.join(p.matched_ngrams)}")
                if p.forward_chain:
                    print(f"  forward: {p.forward_chain[:160]}")
                print()

    elif args.cmd == "walk":
        if g.open() != OK:
            print("no graph yet", file=sys.stderr)
            sys.exit(1)
        n = 0
        while g.read() != ERR_FILE_EOF:
            n += 1
            attrs = ",".join(f"{k}={v!r}" for k, v in g._current.attributes.items())
            data_preview = ""
            if g.get_node_data() is not None:
                d = str(g.get_node_data())
                data_preview = f"  data={d[:60]!r}"
            print(f"[{g.get_current_line():>4}] @{g.get_node_offset():<8} d{g._current.depth} {g.get_node_type():<12} {g.get_node_name():<16} {attrs}{data_preview}")
        print(f"--- {n} nodes ---", file=sys.stderr)

    elif args.cmd == "ngrams":
        grams = extract_ngrams(args.text)
        for text, h in grams:
            print(f"{h}  {text}")

    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
