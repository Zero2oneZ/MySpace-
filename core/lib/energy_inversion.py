#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        energy_inversion
# role:        SUBSTRATE · ANTIPODAL_TWIN + HEX_QUANTIZED_STORAGE
# tier:        L0
# substrate:   pairs of (forward_hex, inverted_hex) — applies to ANY embedding
# engine:      int8 quantization + hex encoding + antipodal sign-flip
# storage:     none (stateless transform; caller persists hex strings)
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.energy_inversion.active.json
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - tri_modal_embedder (every wave_emb gets an antipodal twin)
#   - sentence_chain     (every sentence_emb gets an antipodal twin)
#   - svg_vector_embed   (every svg_path_emb gets an antipodal twin)
#   - moe_router         (negation retrieval — find experts at -query)
# outbound:
#   - stdlib only: math (no numpy, no bitstruct, no msgpack)
# substrate touch:
#   - reads:  none
#   - writes: none (caller stores)
# determinism:
#   - same float vector → same hex pair, byte-exact (int8 quantization rounds half-to-nearest)
# the negation lens:
#   - for query q, also look up matches for -q → retrieves the ANTITHESIS
#   - "find me modern minimalist" + look at -q → "find me cluttered traditional"
#   - chain learns by both proximity AND opposition
# ============================================================================
"""energy_inversion.py — antipodal twin + hex quantization for any embedding.

For an L2-normalized vector v on the unit hypersphere:
  - The antipodal twin -v lives at the opposite pole.
  - Both carry identical energy (|v|² = |-v|² = 1).
  - Their cosine similarity is exactly -1.

Quantizing each float component to int8 ([-127, 127]) → packing to bytes →
hex-encoding gives a stable string. The pair (forward_hex, inverted_hex)
is self-verifying: byte-wise sign-flip must match within quantization noise.

Adds two capabilities to the MoE retrieval stack:
  1. NEGATION RETRIEVAL — query -q to find the antithesis of q.
  2. COMPACT STORAGE — int8 hex is 1/8 the size of JSON-encoded float64.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import List, Optional, Tuple


try:
    import blake3 as _blake3_mod
    def _hash(data: bytes) -> str:
        return _blake3_mod.blake3(data).hexdigest()
except ImportError:
    def _hash(data: bytes) -> str:
        return hashlib.blake2b(data).hexdigest()


DEFAULT_SCALE = 127            # int8 range: [-127, 127] (avoid -128 for symmetry)
QUANTIZATION_EPS = 1.0 / 127   # max quantization error per component


# ---------------------------------------------------------------------------
# Quantization + hex encoding
# ---------------------------------------------------------------------------

def to_hex_int8(vec: List[float], scale: int = DEFAULT_SCALE) -> str:
    """Quantize floats in [-1, 1] to signed int8, pack to bytes, hex-encode.
    Assumes vector is L2-normalized (caller responsibility)."""
    bs = bytearray(len(vec))
    for i, x in enumerate(vec):
        q = int(round(x * scale))
        if q > 127:
            q = 127
        elif q < -127:
            q = -127
        bs[i] = q & 0xFF
    return bytes(bs).hex()


def from_hex_int8(hex_str: str, dim: Optional[int] = None, scale: int = DEFAULT_SCALE) -> List[float]:
    """Decode hex → bytes → signed int8 → floats in [-1, 1]."""
    bs = bytes.fromhex(hex_str)
    if dim is not None:
        bs = bs[:dim]
    out: List[float] = []
    for b in bs:
        # unsigned byte → signed int8
        s = b - 256 if b > 127 else b
        out.append(s / scale)
    return out


# ---------------------------------------------------------------------------
# Antipodal twin
# ---------------------------------------------------------------------------

def invert_vec(vec: List[float]) -> List[float]:
    """Negate every component. The antipodal twin on the unit hypersphere."""
    return [-x for x in vec]


def energy_of(vec: List[float]) -> float:
    """Sum of squared components (== |v|² == ⟨v, v⟩). For L2-normed vec ≈ 1.0."""
    return sum(x * x for x in vec)


# ---------------------------------------------------------------------------
# The pair: (forward, inverted, energy, crystal)
# ---------------------------------------------------------------------------

@dataclass
class EmbeddingPair:
    forward_hex: str
    inverted_hex: str
    energy: float                  # |v|²
    dim: int
    crystal: str                   # blake3 over canonical pair
    quantization_eps: float = QUANTIZATION_EPS


def make_pair(vec: List[float]) -> EmbeddingPair:
    """Compute the full antipodal-hex pair for a vector."""
    inv = invert_vec(vec)
    fwd_hex = to_hex_int8(vec)
    inv_hex = to_hex_int8(inv)
    e = energy_of(vec)
    # crystal: blake3 over canonical concatenation
    canonical = (f"{fwd_hex}|{inv_hex}|{round(e, 8)}|{len(vec)}").encode("utf-8")
    crystal = _hash(canonical)
    return EmbeddingPair(
        forward_hex=fwd_hex,
        inverted_hex=inv_hex,
        energy=round(e, 8),
        dim=len(vec),
        crystal=crystal,
        quantization_eps=QUANTIZATION_EPS,
    )


def verify_pair(pair: EmbeddingPair) -> dict:
    """Differential-amplifier check: byte-wise sign-flip must hold within
    quantization noise. Recompute crystal and confirm canonical hash."""
    fwd = from_hex_int8(pair.forward_hex, pair.dim)
    inv = from_hex_int8(pair.inverted_hex, pair.dim)

    # 1. Antipodal check: forward[i] + inverted[i] should be ~0 (quantization noise)
    max_residual = 0.0
    for f, i in zip(fwd, inv):
        r = abs(f + i)
        if r > max_residual:
            max_residual = r
    antipodal_ok = max_residual <= 2 * QUANTIZATION_EPS

    # 2. Energy check: |forward|² should approximately equal stored energy
    actual_e = sum(x * x for x in fwd)
    # tolerance because of quantization
    energy_ok = abs(actual_e - pair.energy) < 0.05

    # 3. Crystal recompute
    canonical = (f"{pair.forward_hex}|{pair.inverted_hex}|{pair.energy}|{pair.dim}").encode("utf-8")
    expected_crystal = _hash(canonical)
    crystal_ok = expected_crystal == pair.crystal

    return {
        "antipodal_ok": antipodal_ok,
        "max_residual": round(max_residual, 6),
        "energy_ok": energy_ok,
        "actual_energy": round(actual_e, 6),
        "stored_energy": pair.energy,
        "crystal_ok": crystal_ok,
        "all_ok": antipodal_ok and energy_ok and crystal_ok,
    }


# ---------------------------------------------------------------------------
# Negation retrieval — same pattern as wave/sentence/svg neighbors but for -q
# ---------------------------------------------------------------------------

def cosine_similarity(a: List[float], b: List[float]) -> float:
    if len(a) != len(b):
        n = min(len(a), len(b))
        a = a[:n]; b = b[:n]
    return sum(x * y for x, y in zip(a, b))


def find_antithesis(query_vec: List[float],
                    corpus: List[dict],
                    k: int = 5,
                    embedding_key: str = "embedding") -> List[dict]:
    """For each corpus entry, score its similarity to -query_vec.
    Returns top-k records ranked by how strongly they OPPOSE the query.

    This is the negation lens: 'what's the OPPOSITE of what I'm asking?'
    Cross-axis: works on wave_emb, sentence_emb, svg_path_emb identically."""
    neg_q = invert_vec(query_vec)
    scored = []
    for item in corpus:
        emb = item.get(embedding_key) or []
        if not emb:
            continue
        sim = cosine_similarity(neg_q, emb)
        scored.append({**{k: v for k, v in item.items() if k != embedding_key},
                       "antithesis_sim": round(sim, 6)})
    scored.sort(key=lambda x: -x["antithesis_sim"])
    return scored[:k]


def hex_pair_for_lookup(query_vec: List[float]) -> Tuple[str, str]:
    """Convenience: emit (forward_hex, inverted_hex) for a query vector.
    The caller can use forward_hex to find SIMILAR experts and inverted_hex
    to find ANTITHESIS experts — same hex format, opposite poles."""
    pair = make_pair(query_vec)
    return pair.forward_hex, pair.inverted_hex


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main():
    import argparse, json, sys

    ap = argparse.ArgumentParser(description="energy_inversion — antipodal hex twins")
    sub = ap.add_subparsers(dest="cmd")

    p_pair = sub.add_parser("pair", help="emit the (forward_hex, inverted_hex, crystal) for a vector")
    p_pair.add_argument("vec_json", help="JSON list of floats, or '-' for stdin")

    p_v = sub.add_parser("verify", help="verify a pair's antipodal + energy invariants")
    p_v.add_argument("pair_json", help="JSON of EmbeddingPair dict, or '-' for stdin")

    p_invert = sub.add_parser("invert", help="invert a vector and emit both hex forms")
    p_invert.add_argument("vec_json")

    p_demo = sub.add_parser("demo", help="demo: pair → verify → tamper → re-verify")

    args = ap.parse_args()

    if args.cmd == "pair":
        raw = sys.stdin.read() if args.vec_json == "-" else args.vec_json
        vec = json.loads(raw)
        pair = make_pair(vec)
        print(json.dumps({
            "forward_hex": pair.forward_hex[:64] + ("…" if len(pair.forward_hex) > 64 else ""),
            "inverted_hex": pair.inverted_hex[:64] + ("…" if len(pair.inverted_hex) > 64 else ""),
            "energy": pair.energy,
            "dim": pair.dim,
            "crystal": pair.crystal[:32],
        }, indent=2))

    elif args.cmd == "verify":
        raw = sys.stdin.read() if args.pair_json == "-" else args.pair_json
        d = json.loads(raw)
        pair = EmbeddingPair(
            forward_hex=d["forward_hex"], inverted_hex=d["inverted_hex"],
            energy=d["energy"], dim=d["dim"], crystal=d["crystal"],
        )
        print(json.dumps(verify_pair(pair), indent=2))

    elif args.cmd == "invert":
        vec = json.loads(args.vec_json)
        fwd, inv = hex_pair_for_lookup(vec)
        print(json.dumps({"forward_hex": fwd, "inverted_hex": inv,
                          "energy": energy_of(vec)}, indent=2))

    elif args.cmd == "demo":
        # Build a deterministic L2-normalized test vector
        import math
        v = [math.sin(i * 0.3) for i in range(64)]
        n = math.sqrt(sum(x*x for x in v))
        v = [x / n for x in v]

        print("--- (1) make_pair on a 64-d L2-normalized vector ---")
        pair = make_pair(v)
        print(json.dumps({
            "forward_hex_head": pair.forward_hex[:64],
            "inverted_hex_head": pair.inverted_hex[:64],
            "energy": pair.energy,
            "crystal": pair.crystal[:32],
        }, indent=2))

        print("\n--- (2) verify_pair — antipodal residual + energy + crystal ---")
        print(json.dumps(verify_pair(pair), indent=2))

        print("\n--- (3) tamper test: flip one byte of forward_hex ---")
        tampered = pair.forward_hex[:6] + ("ff" if pair.forward_hex[6:8] != "ff" else "00") + pair.forward_hex[8:]
        tampered_pair = EmbeddingPair(
            forward_hex=tampered,
            inverted_hex=pair.inverted_hex,
            energy=pair.energy,
            dim=pair.dim,
            crystal=pair.crystal,
        )
        print(json.dumps(verify_pair(tampered_pair), indent=2))

        print("\n--- (4) negation retrieval against a small fake corpus ---")
        # Forward similar entry + an opposite entry
        corpus = [
            {"id": "alpha", "embedding": v},                                # identical
            {"id": "beta",  "embedding": invert_vec(v)},                    # antipodal
            {"id": "gamma", "embedding": [math.cos(i * 0.3) for i in range(64)]},  # different shape
        ]
        # normalize beta + gamma
        for c in corpus:
            nrm = math.sqrt(sum(x*x for x in c["embedding"]))
            if nrm > 0:
                c["embedding"] = [x/nrm for x in c["embedding"]]
        anti = find_antithesis(v, corpus, k=3)
        print(json.dumps([{"id": r["id"], "antithesis_sim": r["antithesis_sim"]} for r in anti], indent=2))

    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
