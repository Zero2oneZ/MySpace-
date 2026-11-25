#!/usr/bin/env python3
# ============================================================================
# AGENT CARD                                                                  =
# ----------------------------------------------------------------------------=
# name:        moe_router                                                     =
# role:        ROUTER · MIXTURE_OF_EXPERTS_RETRIEVAL                          =
# tier:        L0                                                             =
# substrate:   moe_index (in-memory; rebuilt from crystal_chain each call)    =
# engine:      CrystalChainCursor extends ParserCursor (XMLParser);           =
#              each crystal record presented as <record> element              =
# storage:     reads ~/.cc/inference_master_chain.jsonl; writes nothing       =
# card:        studio/assets/_agents/agent_defs/                              =
#              vm_mspc_001.agents.agent_defs.moe_router.active.json           =
# ----------------------------------------------------------------------------=
# ROUTING CONNECTIONS                                                         =
# ----------------------------------------------------------------------------=
# inbound:                                                                    =
#   - chat.py::_moe_find_experts  (cmd_full / cmd_godot pre-pipeline)         =
#   - CLI: python3 moe_router.py find | walk | summary                        =
# outbound:                                                                   =
#   - parser_cursor.ParserCursor  (base class)                                =
# substrate touch:                                                            =
#   - reads:  ~/.cc/inference_master_chain.jsonl  (read-only)                 =
#   - writes: none                                                            =
# cross-substrate:                                                            =
#   - ngram hashes match user_graph's hashes — joinable by gram_hash          =
#   - non-overriding: does NOT change the deterministic token-bucket routing  =
#     decision; only enriches the prompt with PRIOR EXPERT FORWARD CHAINS     =
# ============================================================================
"""moe_router.py — Mixture-of-Experts router via retrieval over the crystal chain.

No training. No weights updated. The "experts" are past inference records living
in ~/.cc/inference_master_chain.jsonl. New prompts find similar past records by
n-gram overlap and inherit their forward chains as priors.

Engine pattern: same XMLParser cursor that drives parser_cursor.py and user_graph.py.
CrystalChainCursor adapts each crystal record into NODE_ELEMENT name="record" with
the routing/identity fields exposed as attributes (queryable via has_attribute /
get_named_attribute_value) and the larger text bodies kept on `data`.

Workflow:

    cursor = CrystalChainCursor()
    cursor.open()                            # opens ~/.cc/inference_master_chain.jsonl
    moe = MoERouter.build_from(cursor)
    matches = moe.find_experts("build the forward projector", k=5)
    for m in matches:
        print(m.crystal_id, m.tier, m.model, m.score, m.forward_chain[:80])

The router does NOT override the deterministic token-bucket routing — it informs
the prompt by surfacing past matching experts and injecting their forward chains
as additional context. Routing stays deterministic; smartness grows from the index.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from parser_cursor import (
    ParserCursor,
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
CRYSTAL_CHAIN_PATH = CC_HOME / "inference_master_chain.jsonl"

# Try blake3; fall back to blake2b.
try:
    import blake3 as _blake3_mod
    def _hash(data: bytes) -> str:
        return _blake3_mod.blake3(data).hexdigest()
except ImportError:
    def _hash(data: bytes) -> str:
        return hashlib.blake2b(data).hexdigest()


_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _tokens(text: str) -> List[str]:
    return [t.lower() for t in _WORD_RE.findall(text or "")]


def _extract_ngrams(text: str, sizes: Iterable[int] = (2, 3)) -> List[Tuple[str, str]]:
    """Same n-gram shape as user_graph — same hash → same key across substrates."""
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
# CrystalChainCursor — XMLParser-shaped view over inference_master_chain.jsonl
# ---------------------------------------------------------------------------

# Fields that become attributes (queryable via has_attribute / get_named_attribute_value).
_RECORD_ATTRS = (
    "crystal_id",
    "prev_crystal",
    "master_index",
    "agent_uuid",
    "correlation_id",
    "session_id",
    "timestamp",
    "latency_ms",
    "tier",
    "model",
    "scope",
    "tokens_in",
    "tokens_out",
    "complexity",
    "done_flag",
    "rc",
    "forward_source",
    "source_file",
    "source_folder",
    "source_action",
    "source_step",
)

# Fields that ride along on `data` as a dict of bigger text bodies.
_RECORD_DATA_KEYS = (
    "original_prompt",
    "enhanced_prompt",
    "output_text",
    "reasoning_trace",
    "forward_chain_inline",
    "forward_chain_posthoc",
    "chain_context",
    "coordinates",
    # Tri-modal axes (4D adjacent-possible — added 2026-05-28)
    "wave_emb",
    "time_vec",
    "tri_modal_crystal",
)


class CrystalChainCursor(ParserCursor):
    """ParserCursor specialized for the crystal chain JSONL.

    Each line in inference_master_chain.jsonl is one inference record. The cursor
    presents each as NODE_ELEMENT name='record' so the entire crystal chain looks
    like an XML document of <record> elements at depth 1 under a virtual <chain>.
    """

    def __init__(self, path: Optional[Path] = None):
        super().__init__()
        self.path = Path(path) if path else CRYSTAL_CHAIN_PATH

    def open(self, source=None) -> int:  # type: ignore[override]
        return super().open(Path(source) if source else self.path)

    @staticmethod
    def _dict_to_node(d: Dict[str, Any], offset: int, line_no: int) -> CursorNode:  # type: ignore[override]
        attributes = {k: d.get(k) for k in _RECORD_ATTRS if k in d}
        data = {k: d.get(k) for k in _RECORD_DATA_KEYS if k in d}
        return CursorNode(
            type=NODE_ELEMENT,
            name="record",
            data=data,
            attributes=attributes,
            parent="chain",
            depth=1,
            offset=offset,
            line_no=line_no,
        )


# ---------------------------------------------------------------------------
# Expert match dataclass
# ---------------------------------------------------------------------------

@dataclass
class ExpertMatch:
    crystal_id: str
    score: int
    matched_ngrams: List[str]
    tier: str
    model: str
    scope: str
    timestamp: str
    forward_source: str
    forward_chain: str        # the chosen forward chain (inline preferred, posthoc fallback)
    original_prompt: str
    enhanced_prompt_snip: str
    output_snip: str
    fit_ratio: float          # score / total_incoming_ngrams (rough fit indicator)


# ---------------------------------------------------------------------------
# MoERouter — retrieval over the crystal chain
# ---------------------------------------------------------------------------

@dataclass
class _ExpertEntry:
    crystal_id: str
    tier: str
    model: str
    scope: str
    timestamp: str
    forward_source: str
    forward_chain: str
    original_prompt: str
    enhanced_prompt: str
    output_text: str
    ngram_hashes: List[str] = field(default_factory=list)
    # Tri-modal axes (optional — may be empty for pre-tri-modal records)
    wave_emb: List[float] = field(default_factory=list)
    time_vec: Dict[str, Any] = field(default_factory=dict)
    tri_modal_crystal: str = ""


class MoERouter:
    """In-memory retrieval index over past inference records."""

    def __init__(self):
        self.experts: Dict[str, _ExpertEntry] = {}
        self.ngram_to_experts: Dict[str, List[str]] = {}

    @classmethod
    def build_from(cls, cursor: CrystalChainCursor) -> "MoERouter":
        """Walk the crystal chain from offset 0 and build the n-gram → expert map."""
        router = cls()
        cursor.seek(0)

        while cursor.read() != ERR_FILE_EOF:
            if cursor.get_node_type() != NODE_ELEMENT:
                continue
            if cursor.get_node_name() != "record":
                continue

            cid = cursor.get_named_attribute_value_safe("crystal_id") or ""
            if not cid:
                continue
            # Skip the genesis seed entry (no useful signal for routing).
            tier = cursor.get_named_attribute_value_safe("tier") or ""
            if tier == "genesis":
                continue

            data = cursor.get_node_data() or {}
            inline = data.get("forward_chain_inline") or ""
            posthoc = data.get("forward_chain_posthoc") or ""
            forward = inline or posthoc

            entry = _ExpertEntry(
                crystal_id=cid,
                tier=tier,
                model=cursor.get_named_attribute_value_safe("model") or "",
                scope=cursor.get_named_attribute_value_safe("scope") or "",
                timestamp=cursor.get_named_attribute_value_safe("timestamp") or "",
                forward_source=cursor.get_named_attribute_value_safe("forward_source") or "none",
                forward_chain=forward,
                original_prompt=data.get("original_prompt") or "",
                enhanced_prompt=data.get("enhanced_prompt") or "",
                output_text=data.get("output_text") or "",
                wave_emb=data.get("wave_emb") or [],
                time_vec=data.get("time_vec") or {},
                tri_modal_crystal=data.get("tri_modal_crystal") or "",
            )

            # Indexed surface: original + enhanced + reasoning_trace + output_text.
            indexed_text = " ".join([
                entry.original_prompt,
                entry.enhanced_prompt,
                data.get("reasoning_trace") or "",
                entry.output_text,
            ])
            for _, gram_hash in _extract_ngrams(indexed_text):
                entry.ngram_hashes.append(gram_hash)
                router.ngram_to_experts.setdefault(gram_hash, []).append(cid)

            router.experts[cid] = entry

        return router

    def find_experts(self, prompt: str, k: int = 5, min_score: int = 1) -> List[ExpertMatch]:
        """Top-k past experts whose n-grams overlap with the incoming prompt."""
        incoming = _extract_ngrams(prompt)
        if not incoming:
            return []

        scores: Dict[str, int] = {}
        matched: Dict[str, List[str]] = {}
        for gram_text, gram_hash in incoming:
            for cid in self.ngram_to_experts.get(gram_hash, []):
                scores[cid] = scores.get(cid, 0) + 1
                matched.setdefault(cid, []).append(gram_text)

        # Sort by score DESC, then deterministically by crystal_id.
        ranked = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
        total_in = len(incoming) or 1

        out: List[ExpertMatch] = []
        for cid, score in ranked:
            if score < min_score:
                break
            entry = self.experts.get(cid)
            if not entry:
                continue
            out.append(ExpertMatch(
                crystal_id=cid,
                score=score,
                matched_ngrams=matched.get(cid, [])[:12],
                tier=entry.tier,
                model=entry.model,
                scope=entry.scope,
                timestamp=entry.timestamp,
                forward_source=entry.forward_source,
                forward_chain=entry.forward_chain,
                original_prompt=entry.original_prompt,
                enhanced_prompt_snip=entry.enhanced_prompt[:300],
                output_snip=entry.output_text[:300],
                fit_ratio=round(score / total_in, 4),
            ))
            if len(out) >= k:
                break
        return out

    # ---- antithesis (negation) retrieval — 5 axes, one method each --------
    # For every find_*_neighbors method there is a paired find_antithesis_*
    # method. Same scoring loop, query is negated (energy_inversion). Returns
    # the records whose embedding most strongly OPPOSES the query.

    def find_antithesis_vector(self, prompt: str, k: int = 5,
                                 max_score: int = 99999) -> List[Dict[str, Any]]:
        """Vector-axis antithesis — experts with MINIMUM n-gram overlap with the
        query (ascending score). Used for 'what's the OPPOSITE topic.'"""
        try:
            from chain_builder import _hash as _bld_hash  # type: ignore
        except ImportError:
            pass
        import re
        incoming = _extract_ngrams(prompt)
        if not incoming:
            return []
        incoming_hashes = {h for _, h in incoming}
        scored = []
        for cid, entry in self.experts.items():
            # overlap = how many of query's grams appear in this expert
            overlap = sum(1 for h in incoming_hashes if h in entry.ngram_hashes)
            if overlap > max_score:
                continue
            scored.append({
                "crystal_id": cid,
                "antithesis_score": -overlap,    # negative so antithesis ranks high
                "raw_overlap": overlap,
                "tier": entry.tier,
                "model": entry.model,
                "timestamp": entry.timestamp,
                "forward_chain": entry.forward_chain[:200],
                "original_prompt": entry.original_prompt[:120],
            })
        # Sort by overlap ASCENDING (least overlap = best antithesis)
        scored.sort(key=lambda x: (x["raw_overlap"], x["crystal_id"]))
        return scored[:k]

    def find_antithesis_wave(self, query_wave: List[float], k: int = 5
                              ) -> List[Dict[str, Any]]:
        """Wave-axis antithesis — closest match to the NEGATED query."""
        try:
            from energy_inversion import invert_vec
        except ImportError:
            return []
        if not query_wave:
            return []
        return self.find_wave_neighbors(invert_vec(query_wave), k=k)

    def find_antithesis_time(self, query_time: Dict[str, Any], k: int = 5
                              ) -> List[Dict[str, Any]]:
        """Time-axis antithesis — find records whose forward-time vector is closest
        to the NEGATED forward-time of the query (sign-flip)."""
        try:
            from energy_inversion import invert_vec
        except ImportError:
            return []
        if not query_time:
            return []
        flipped = dict(query_time)
        flipped["forward"] = invert_vec(query_time.get("forward", []))
        return self.find_time_neighbors(flipped, k=k)

    def find_antithesis_sentence(self, query_text: str, k: int = 5,
                                   min_sim: float = -1.0) -> List[Dict[str, Any]]:
        """Sentence-axis antithesis — same scoring loop as find_sentence_neighbors
        but ranks records that OPPOSE the query's syntactic embedding."""
        try:
            from sentence_chain import embed_chain, cosine_similarity as sc_cos
            from energy_inversion import invert_vec
        except ImportError:
            return []
        if not query_text or not query_text.strip():
            return []
        q_nodes = embed_chain(query_text)
        if not q_nodes:
            return []
        # Negate each query sentence's embedding
        q_negated = [invert_vec(n.embedding) for n in q_nodes]
        scored = []
        for cid, entry in self.experts.items():
            if not entry.original_prompt:
                continue
            e_nodes = embed_chain(entry.original_prompt)
            if not e_nodes:
                continue
            best = -2.0
            for q_neg in q_negated:
                for e in e_nodes:
                    s = sc_cos(q_neg, e.embedding)
                    if s > best:
                        best = s
            if best < min_sim:
                continue
            scored.append({
                "crystal_id": cid,
                "antithesis_sentence_sim": round(best, 6),
                "tier": entry.tier,
                "model": entry.model,
                "timestamp": entry.timestamp,
                "forward_chain": entry.forward_chain[:200],
                "original_prompt": entry.original_prompt[:120],
            })
        scored.sort(key=lambda x: -x["antithesis_sentence_sim"])
        return scored[:k]

    def find_antithesis_svg(self, query_d: str, k: int = 5) -> List[Dict[str, Any]]:
        """SVG-axis antithesis — closest match to the NEGATED svg path embedding."""
        try:
            from svg_vector_embed import svg_path_embedding, cosine_similarity as svg_cos
            from energy_inversion import invert_vec
        except ImportError:
            return []
        # corpus comes from the same crystal chain — experts that carry an svg_emb
        # aren't tracked yet on _ExpertEntry; for now this method operates
        # on caller-provided corpora via find_antithesis_svg_in_corpus.
        # Provide a stub that returns empty so the API surface is uniform.
        _ = query_d  # noqa: F841
        return []

    def find_antithesis_svg_in_corpus(self, query_d: str,
                                        corpus: List[Dict[str, Any]],
                                        k: int = 5) -> List[Dict[str, Any]]:
        """SVG-axis antithesis against an explicit corpus (e.g., ~/.cc/svg_index.jsonl).
        Each corpus item: {embedding: List[float], ...}. Returns top-k most opposed."""
        try:
            from svg_vector_embed import svg_path_embedding, cosine_similarity as svg_cos
            from energy_inversion import invert_vec
        except ImportError:
            return []
        q_emb = svg_path_embedding(query_d)
        neg_q = invert_vec(q_emb)
        scored = []
        for item in corpus:
            emb = item.get("embedding") or []
            if not emb:
                continue
            sim = svg_cos(neg_q, emb)
            scored.append({**{kk: vv for kk, vv in item.items() if kk != "embedding"},
                            "antithesis_svg_sim": round(sim, 6)})
        scored.sort(key=lambda x: -x["antithesis_svg_sim"])
        return scored[:k]

    def find_wave_neighbors(self, query_wave: List[float], k: int = 5,
                             min_sim: float = 0.0) -> List[Dict[str, Any]]:
        """Cosine-similarity retrieval over the wave_emb axis. Records without
        a wave_emb are skipped. Returns top-k with sim scores."""
        if not query_wave:
            return []
        try:
            from tri_modal_embedder import cosine_similarity
        except ImportError:
            return []
        scored = []
        for cid, entry in self.experts.items():
            if not entry.wave_emb:
                continue
            sim = cosine_similarity(query_wave, entry.wave_emb)
            if sim < min_sim:
                continue
            scored.append({
                "crystal_id": cid,
                "wave_sim": round(sim, 6),
                "tier": entry.tier,
                "model": entry.model,
                "timestamp": entry.timestamp,
                "forward_chain": entry.forward_chain[:200],
                "original_prompt": entry.original_prompt[:120],
            })
        scored.sort(key=lambda x: -x["wave_sim"])
        return scored[:k]

    def find_sentence_neighbors(self, query_text: str, k: int = 5,
                                  min_sim: float = 0.0) -> List[Dict[str, Any]]:
        """4th retrieval axis: syntactic similarity via sentence_chain embeddings.
        Computes embeddings on-the-fly (no schema change to InferenceRecord). For
        each indexed expert, embeds its original_prompt and compares the cosine
        of the strongest sentence pair against the query's strongest sentence.
        FREE — pure-Python NLP heuristics, no LLM, no model load."""
        try:
            from sentence_chain import sentence_embedding, embed_chain, cosine_similarity as sc_cos
        except ImportError:
            return []
        if not query_text or not query_text.strip():
            return []

        q_nodes = embed_chain(query_text)
        if not q_nodes:
            return []
        scored = []
        for cid, entry in self.experts.items():
            if not entry.original_prompt:
                continue
            e_nodes = embed_chain(entry.original_prompt)
            if not e_nodes:
                continue
            # Best pairwise sentence similarity
            best = 0.0
            for q in q_nodes:
                for e in e_nodes:
                    s = sc_cos(q.embedding, e.embedding)
                    if s > best:
                        best = s
            if best < min_sim:
                continue
            scored.append({
                "crystal_id": cid,
                "sentence_sim": round(best, 6),
                "tier": entry.tier,
                "model": entry.model,
                "timestamp": entry.timestamp,
                "forward_chain": entry.forward_chain[:200],
                "original_prompt": entry.original_prompt[:120],
            })
        scored.sort(key=lambda x: -x["sentence_sim"])
        return scored[:k]

    def find_time_neighbors(self, query_time: Dict[str, Any], k: int = 5,
                             max_dist: float = float("inf")) -> List[Dict[str, Any]]:
        """Euclidean-distance retrieval over the time forward-axis. Returns top-k
        closest in time-space (smallest distance first)."""
        if not query_time:
            return []
        try:
            from tri_modal_embedder import time_distance
        except ImportError:
            return []
        scored = []
        for cid, entry in self.experts.items():
            if not entry.time_vec:
                continue
            d = time_distance(query_time, entry.time_vec)
            if d > max_dist:
                continue
            scored.append({
                "crystal_id": cid,
                "time_dist": round(d, 6),
                "tier": entry.tier,
                "model": entry.model,
                "timestamp": entry.timestamp,
                "forward_chain": entry.forward_chain[:200],
                "original_prompt": entry.original_prompt[:120],
            })
        scored.sort(key=lambda x: x["time_dist"])
        return scored[:k]

    def summarize_for_prompt(self, matches: List[ExpertMatch], max_chars: int = 1200) -> str:
        """Render the matched experts as a PRIOR EXPERT FORWARD CHAINS block.
        Deduplicates forward chains so we don't pile up identical text."""
        if not matches:
            return ""

        lines = ["PRIOR EXPERT FORWARD CHAINS (matched from past inference, consume as priors):"]
        seen_forwards: set = set()
        used_chars = 0
        for m in matches:
            if not m.forward_chain:
                continue
            key = m.forward_chain[:200]
            if key in seen_forwards:
                continue
            seen_forwards.add(key)
            header = f"# expert {m.crystal_id[:12]} (tier={m.tier} model={m.model} score={m.score} fit={m.fit_ratio})"
            block = header + "\n" + m.forward_chain.strip()
            if used_chars + len(block) > max_chars:
                break
            lines.append(block)
            used_chars += len(block)

        if len(lines) == 1:
            # No forward chains harvested.
            return ""
        return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main():
    import argparse

    ap = argparse.ArgumentParser(description="moe_router — retrieval-MoE over the crystal chain")
    sub = ap.add_subparsers(dest="cmd")

    p_find = sub.add_parser("find", help="find top-k past experts for a prompt")
    p_find.add_argument("prompt")
    p_find.add_argument("-k", type=int, default=5)
    p_find.add_argument("--json", action="store_true")

    p_walk = sub.add_parser("walk", help="dump the crystal chain as <record> elements")

    p_summary = sub.add_parser("summary", help="emit a PRIOR EXPERT block for a prompt")
    p_summary.add_argument("prompt")
    p_summary.add_argument("-k", type=int, default=5)
    p_summary.add_argument("--max-chars", type=int, default=1200)

    args = ap.parse_args()

    if args.cmd == "find":
        cursor = CrystalChainCursor()
        if cursor.open() != OK:
            print("crystal chain not found", file=sys.stderr)
            sys.exit(1)
        router = MoERouter.build_from(cursor)
        matches = router.find_experts(args.prompt, args.k)
        if args.json:
            print(json.dumps([{
                "crystal_id": m.crystal_id,
                "score": m.score,
                "fit_ratio": m.fit_ratio,
                "matched_ngrams": m.matched_ngrams,
                "tier": m.tier,
                "model": m.model,
                "timestamp": m.timestamp,
                "forward_source": m.forward_source,
                "forward_chain": m.forward_chain[:400],
                "original_prompt": m.original_prompt[:200],
            } for m in matches], indent=2))
        else:
            for m in matches:
                print(f"[score={m.score} fit={m.fit_ratio}] crystal {m.crystal_id[:12]} tier={m.tier} model={m.model}")
                print(f"  prompt: {m.original_prompt[:80]}")
                print(f"  matched: {', '.join(m.matched_ngrams[:8])}")
                if m.forward_chain:
                    print(f"  forward: {m.forward_chain[:160]}")
                print()

    elif args.cmd == "walk":
        cursor = CrystalChainCursor()
        if cursor.open() != OK:
            print("crystal chain not found", file=sys.stderr)
            sys.exit(1)
        n = 0
        while cursor.read() != ERR_FILE_EOF:
            n += 1
            cid = cursor.get_named_attribute_value_safe("crystal_id") or "?"
            tier = cursor.get_named_attribute_value_safe("tier") or "-"
            model = cursor.get_named_attribute_value_safe("model") or "-"
            fsrc = cursor.get_named_attribute_value_safe("forward_source") or "-"
            data = cursor.get_node_data() or {}
            prompt = (data.get("original_prompt") or "")[:50]
            print(f"[{cursor.get_current_line():>4}] @{cursor.get_node_offset():<8} {cid[:12]} tier={tier:<8} model={model:<24} fwd={fsrc:<8} | {prompt}")
        print(f"--- {n} records ---", file=sys.stderr)

    elif args.cmd == "summary":
        cursor = CrystalChainCursor()
        if cursor.open() != OK:
            print("crystal chain not found", file=sys.stderr)
            sys.exit(1)
        router = MoERouter.build_from(cursor)
        matches = router.find_experts(args.prompt, args.k)
        print(router.summarize_for_prompt(matches, args.max_chars))

    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
