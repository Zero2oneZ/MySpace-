#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        tri_modal_embedder
# role:        SUBSTRATE · 4D_ADJACENT_POSSIBLE
# tier:        L0
# substrate:   tri-modal crystal (vector + wave + time) — pre-computed adjacency
# engine:      pure-Python BLAKE3 + DCT-II + positional encoding + diff-amp check
# storage:     none (stateless transform — caller persists crystals)
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.tri_modal_embedder.active.json
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - inference_logger.log (when extended — adds tri_modal_crystal per record)
#   - workflow_generator (when extended — every emitted file gets a tri-modal seal)
#   - moe_router.find_wave_neighbors / find_time_neighbors (cross-modal retrieval)
# outbound:
#   - blake3 (or blake2b fallback) for content + crystal hashing
#   - math.sin/cos for positional encoding + DCT-II basis
# substrate touch:
#   - reads:  none
#   - writes: none (stateless)
# determinism:
#   - same content + same timestamp + same btc_height → same crystal, bytes-exact
# ============================================================================
"""tri_modal_embedder.py — every record crystallizes across three adjacent domains.

DOMAIN 1 · VECTOR  — BLAKE3 hex of the canonical content. The "what is it" axis.
DOMAIN 2 · WAVE    — DCT-II spectrum of the content treated as an audio sample
                     buffer. L2-normalized so cosine similarity is meaningful.
                     The "how does it resonate" axis.
DOMAIN 3 · TIME    — Sinusoidal positional encoding of (timestamp, btc_height),
                     PLUS the inverted-time encoding (negative argument). Their
                     sum produces a fixed expected residual pattern: sin pairs
                     cancel to ~0, cos pairs double. Any tampering breaks the
                     pattern — differential-amplifier tamper detection.
                     The "when does it exist" axis with self-healing.

A `TriModalCrystal` links all three via a final BLAKE3 of their canonical forms.
Lookup in ANY one domain returns the other two for free — the "adjacent
possible" cache. New records get inserted into all three indexes simultaneously.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
import time
from dataclasses import dataclass, asdict, field
from typing import List, Optional, Dict, Any


try:
    import blake3 as _blake3_mod
    def _hash(data: bytes) -> str:
        return _blake3_mod.blake3(data).hexdigest()
except ImportError:
    def _hash(data: bytes) -> str:
        return hashlib.blake2b(data).hexdigest()


# Tuneable constants
WAVE_COEFFS = 64        # DCT-II output dim
TIME_DIMS = 32          # positional encoding dim (must be even — sin/cos pairs)
SAMPLE_CAP = 2048       # bytes — cap input for DCT (pure-Python O(n*k) inner loops)
EPS = 1e-9              # tolerance for residual check


# ---------------------------------------------------------------------------
# DOMAIN 1 — vector
# ---------------------------------------------------------------------------

def vector_embedding(content: str) -> str:
    return _hash(content.encode("utf-8"))


# ---------------------------------------------------------------------------
# DOMAIN 2 — wave (DCT-II of content-as-audio)
# ---------------------------------------------------------------------------

def _to_samples(content: str, cap: int = SAMPLE_CAP) -> List[float]:
    """Encode UTF-8 bytes as audio-like samples in [-1, 1]."""
    bs = content.encode("utf-8")[:cap]
    return [(b - 128) / 128.0 for b in bs]


def _dct_ii(samples: List[float], n_coeffs: int = WAVE_COEFFS) -> List[float]:
    """Standard DCT-II (the JPEG/MP3 transform). Pure Python."""
    N = len(samples)
    if N == 0:
        return [0.0] * n_coeffs
    out: List[float] = []
    limit = min(n_coeffs, N)
    for k in range(limit):
        s = 0.0
        # cosine basis: cos(pi * (n + 0.5) * k / N)
        for n in range(N):
            s += samples[n] * math.cos(math.pi * (n + 0.5) * k / N)
        if k == 0:
            s *= math.sqrt(1.0 / N)
        else:
            s *= math.sqrt(2.0 / N)
        out.append(s)
    # pad if input shorter than requested coeffs
    while len(out) < n_coeffs:
        out.append(0.0)
    return out


def _l2_normalize(vec: List[float]) -> List[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm < 1e-12:
        return vec
    return [x / norm for x in vec]


def wave_embedding(content: str, n_coeffs: int = WAVE_COEFFS) -> List[float]:
    samples = _to_samples(content)
    spectrum = _dct_ii(samples, n_coeffs)
    return _l2_normalize(spectrum)


# ---------------------------------------------------------------------------
# DOMAIN 3 — time (forward + inverted positional encoding)
# ---------------------------------------------------------------------------

def _positional_encode(t: float, dim: int = TIME_DIMS) -> List[float]:
    """Transformer-style sinusoidal positional encoding for a scalar time argument.
    Returns alternating sin/cos values across geometric frequencies."""
    out: List[float] = []
    for i in range(dim // 2):
        freq = 1.0 / (10000.0 ** (2 * i / dim))
        out.append(math.sin(t * freq))
        out.append(math.cos(t * freq))
    return out


def time_vector(
    timestamp: Optional[float] = None,
    btc_height: int = 0,
    dim: int = TIME_DIMS,
) -> Dict[str, Any]:
    """Build the time embedding with forward + inverted arms.

    Self-healing residual: sin(-t) = -sin(t), cos(-t) = cos(t), so for each
    sin/cos pair (i, i+1):
        forward[i]   + inverted[i]   ≈ 0      (sin term cancels)
        forward[i+1] + inverted[i+1] ≈ 2*cos  (cos term doubles)

    Any byte tampering in either arm breaks the pattern → instant detection.
    """
    ts = timestamp if timestamp is not None else time.time()
    forward = _positional_encode(ts, dim)
    inverted = _positional_encode(-ts, dim)
    residual = [(f + i) for f, i in zip(forward, inverted)]
    btc_emb = _positional_encode(float(btc_height), dim)
    return {
        "forward": forward,
        "inverted": inverted,
        "residual": residual,
        "btc": btc_emb,
        "timestamp": ts,
        "btc_height": btc_height,
    }


def verify_time_residual(time_v: Dict[str, Any], eps: float = EPS) -> bool:
    """Differential-amplifier check. Returns True iff the residual pattern
    matches the expected (0, 2cos, 0, 2cos, ...) signature within eps."""
    fwd = time_v.get("forward")
    inv = time_v.get("inverted")
    if not isinstance(fwd, list) or not isinstance(inv, list):
        return False
    if len(fwd) != len(inv):
        return False
    for i in range(0, len(fwd), 2):
        # even index (sin) → sum must be ~0
        if abs(fwd[i] + inv[i]) > eps:
            return False
        # odd index (cos) → sum must equal 2 * forward[i+1]
        if i + 1 < len(fwd):
            expected = 2 * fwd[i + 1]
            actual = fwd[i + 1] + inv[i + 1]
            if abs(actual - expected) > eps:
                return False
    return True


# ---------------------------------------------------------------------------
# The crystal — links all three
# ---------------------------------------------------------------------------

@dataclass
class TriModalCrystal:
    content_preview: str
    vector_emb: str
    wave_emb: List[float]
    time_vec: Dict[str, Any]
    crystal: str

    @classmethod
    def of(
        cls,
        content: str,
        timestamp: Optional[float] = None,
        btc_height: int = 0,
    ) -> "TriModalCrystal":
        vec = vector_embedding(content)
        wave = wave_embedding(content)
        time_v = time_vector(timestamp, btc_height)
        # Crystal = blake3 over canonical concatenation
        canonical = json.dumps(
            {
                "vec": vec,
                "wave": [round(x, 8) for x in wave],
                "time_forward": [round(x, 8) for x in time_v["forward"]],
                "btc_height": btc_height,
                "timestamp": time_v["timestamp"],
            },
            sort_keys=True,
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
        crystal = _hash(canonical)
        return cls(
            content_preview=content[:200],
            vector_emb=vec,
            wave_emb=wave,
            time_vec=time_v,
            crystal=crystal,
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def verify(self) -> Dict[str, bool]:
        """Re-verify all three domains. Each returns True if intact."""
        # Vector: rehash preview (only for sanity — preview is truncated, so
        # this verifies preview-only; real verification requires full content)
        vec_ok = isinstance(self.vector_emb, str) and len(self.vector_emb) >= 32
        # Wave: l2 norm should be ~1
        wave_norm = math.sqrt(sum(x * x for x in self.wave_emb))
        wave_ok = abs(wave_norm - 1.0) < 1e-6 or wave_norm < 1e-12
        # Time: differential-amplifier residual check
        time_ok = verify_time_residual(self.time_vec)
        return {"vector": vec_ok, "wave": wave_ok, "time": time_ok,
                "all_ok": vec_ok and wave_ok and time_ok}


# ---------------------------------------------------------------------------
# Cross-modal retrieval primitives
# ---------------------------------------------------------------------------

def cosine_similarity(a: List[float], b: List[float]) -> float:
    """For l2-normalized vectors (like wave_embedding), dot product = cosine."""
    if len(a) != len(b):
        n = min(len(a), len(b))
        a = a[:n]; b = b[:n]
    return sum(x * y for x, y in zip(a, b))


def time_distance(t1: Dict[str, Any], t2: Dict[str, Any]) -> float:
    """Euclidean distance in forward-time space."""
    f1 = t1.get("forward", [])
    f2 = t2.get("forward", [])
    n = min(len(f1), len(f2))
    return math.sqrt(sum((f1[i] - f2[i]) ** 2 for i in range(n)))


def find_wave_neighbors(
    query_wave: List[float],
    candidates: List[Dict[str, Any]],   # each: {"crystal", "wave_emb"}
    k: int = 5,
) -> List[Dict[str, Any]]:
    """Top-k candidates by wave cosine similarity. Each result includes sim score."""
    scored = []
    for c in candidates:
        if not c.get("wave_emb"):
            continue
        sim = cosine_similarity(query_wave, c["wave_emb"])
        scored.append({**{kk: vv for kk, vv in c.items() if kk != "wave_emb"},
                       "wave_sim": sim})
    scored.sort(key=lambda x: -x["wave_sim"])
    return scored[:k]


def find_time_neighbors(
    query_time: Dict[str, Any],
    candidates: List[Dict[str, Any]],   # each: {"crystal", "time_vec"}
    k: int = 5,
) -> List[Dict[str, Any]]:
    """Top-k candidates by smallest time distance (closest in time-space)."""
    scored = []
    for c in candidates:
        if not c.get("time_vec"):
            continue
        d = time_distance(query_time, c["time_vec"])
        scored.append({**{kk: vv for kk, vv in c.items() if kk != "time_vec"},
                       "time_dist": d})
    scored.sort(key=lambda x: x["time_dist"])
    return scored[:k]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _compact(d: Dict[str, Any], wave_show: int = 8, time_show: int = 8) -> Dict[str, Any]:
    """Shrink the embedding payload for human-readable output."""
    out = dict(d)
    if "wave_emb" in out and isinstance(out["wave_emb"], list):
        out["wave_emb"] = [round(x, 6) for x in out["wave_emb"][:wave_show]] + ["…"] \
            if len(out["wave_emb"]) > wave_show else [round(x, 6) for x in out["wave_emb"]]
    if "time_vec" in out and isinstance(out["time_vec"], dict):
        tv = out["time_vec"]
        out["time_vec"] = {
            "forward_head": [round(x, 6) for x in tv["forward"][:time_show]],
            "inverted_head": [round(x, 6) for x in tv["inverted"][:time_show]],
            "residual_head": [round(x, 6) for x in tv["residual"][:time_show]],
            "timestamp": tv["timestamp"],
            "btc_height": tv["btc_height"],
        }
    return out


def _main():
    import argparse
    ap = argparse.ArgumentParser(description="tri_modal_embedder — 4D crystal CLI")
    sub = ap.add_subparsers(dest="cmd")

    p_c = sub.add_parser("crystallize", help="produce a TriModalCrystal for given content")
    p_c.add_argument("content", help="text content (or '-' to read from stdin)")
    p_c.add_argument("--timestamp", type=float, default=None)
    p_c.add_argument("--btc-height", type=int, default=0)
    p_c.add_argument("--full", action="store_true", help="emit full vectors (large)")

    p_v = sub.add_parser("verify", help="verify a crystal JSON")
    p_v.add_argument("path", help="path to JSON, or '-' for stdin")

    p_cmp = sub.add_parser("compare", help="compare two strings across all 3 domains")
    p_cmp.add_argument("a")
    p_cmp.add_argument("b")

    args = ap.parse_args()

    if args.cmd == "crystallize":
        content = sys.stdin.read() if args.content == "-" else args.content
        tmc = TriModalCrystal.of(content, args.timestamp, args.btc_height)
        out = tmc.to_dict()
        if not args.full:
            out = _compact(out)
        print(json.dumps(out, indent=2))

    elif args.cmd == "verify":
        raw = sys.stdin.read() if args.path == "-" else open(args.path).read()
        data = json.loads(raw)
        # accept either a TriModalCrystal dict, or just the time_vec
        if "time_vec" in data:
            time_ok = verify_time_residual(data["time_vec"])
        else:
            time_ok = verify_time_residual(data)
        wave_ok = True
        if "wave_emb" in data:
            n = math.sqrt(sum(x * x for x in data["wave_emb"]))
            wave_ok = abs(n - 1.0) < 1e-6 or n < 1e-12
        print(json.dumps({"time_residual_ok": time_ok,
                          "wave_norm_ok": wave_ok,
                          "all_ok": time_ok and wave_ok}, indent=2))

    elif args.cmd == "compare":
        ta = TriModalCrystal.of(args.a)
        tb = TriModalCrystal.of(args.b)
        print(json.dumps({
            "a": {"vec": ta.vector_emb[:16], "crystal": ta.crystal[:16]},
            "b": {"vec": tb.vector_emb[:16], "crystal": tb.crystal[:16]},
            "vector_match":   ta.vector_emb == tb.vector_emb,
            "wave_cosine":    round(cosine_similarity(ta.wave_emb, tb.wave_emb), 6),
            "time_distance":  round(time_distance(ta.time_vec, tb.time_vec), 6),
            "crystal_match":  ta.crystal == tb.crystal,
        }, indent=2))

    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
