#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        multi_layer_hex
# role:        SUBSTRATE · SIDECAR_MULTI_MODAL_HEX_PACKER
# tier:        L0
# substrate:   none (pure-math transform; caller persists the hex string)
# engine:      8-slot fixed-layout int8 quantization → 512-char hex envelope
# storage:     none — sidecar field on InferenceRecord, NOT chain-hashed
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.multi_layer_hex.active.json
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - moe_router         (slot-wise distance lookup on a single hex envelope)
#   - dialectic_walker   (writes slot 5 once integrated)
#   - inference_logger callers (attach hex to a record AFTER log() returns)
# outbound:
#   - energy_inversion.to_hex_int8 / from_hex_int8 (when importable)
#   - sentence_chain.sentence_embedding (when importable)
#   - svg_vector_embed.embed_svg_file   (when importable)
#   - stdlib fallback: math + struct only
# substrate touch:
#   - reads:  none
#   - writes: none (caller chooses to set record.multi_layer_hex)
# determinism:
#   - same record dict → same 512-char hex string (slot order locked, int8 round-half-to-nearest)
# sidecar discipline:
#   - This field is INTENTIONALLY off canonical_json() for inference_logger v1.
#   - The crystal hash must remain stable for the existing chain. Callers attach
#     multi_layer_hex AFTER logger.log() returns; only schema_version='v2' will
#     fold this into the chain hash (planned, not implemented).
# ============================================================================
"""multi_layer_hex.py — pack N modal embeddings into one deterministic hex envelope.

The envelope is exactly 256 bytes (512 hex chars), split into 8 contiguous
32-byte slots. Each slot holds the int8-quantized leading 32 dimensions of
its source vector, OR 32 zero bytes when the modality is absent.

Slot layout (locked; index N starts at hex position N*64):

  0  sentence              first 32 dims of sentence_chain.sentence_embedding(prompt)
  1  svg                   first 32 dims of embed_svg_file(source_file)[0].embedding
  2  wave                  first 32 dims of record['wave_emb']  (the 64-d DCT-II spectrum)
  3  time_forward          first 32 dims of record['time_vec']['forward']
  4  time_inverted         first 32 dims of record['time_vec']['inverted']
  5  dialectic_position    EMPTY in v1 — reserved for dialectic_walker integration
  6  visual_bitmap_dct     EMPTY in v1 — reserved for visual DCT slot
  7  antipodal_xor         byte-wise XOR of slot 0 ⊕ slot 1 (differential-amplifier sanity check)

Why a fixed-layout hex envelope (not JSON)?
  - Length-stable: callers slice by slot index without parsing.
  - Compact: 256 bytes vs ~2 KB JSON of the same float vectors.
  - Tamper-stable: any single-byte edit changes slot_distance() noticeably.
  - Slot 7 (antipodal_xor) reveals slot-correlation drift for free.

SIDECAR FIELD — CRITICAL:
  This output is NOT part of InferenceRecord.canonical_json(). It must NOT be
  added to the canonical hash in schema_version='v1'. The caller attaches it
  to a record AFTER `logger.log()` returns (set record.multi_layer_hex =
  pack_layers(asdict(record))). Folding it into the hash is a v2-schema task
  that requires re-genesis of the chain — explicitly NOT done here.

Slot computation rule:
  For each slot's source vector:
    - Pull first 32 dims (no decimation; deterministic and trivial to reverse).
    - Pad with 0.0 if vector is shorter than 32.
    - int8-quantize via to_hex_int8(scale=127): round-half-to-nearest, clamp to
      [-127, 127], byte-cast. Empty/missing → 32 zero bytes.

Distance metric:
  slot_distance() returns 1 - cosine_similarity over the 32 dequantized floats.
  Range: 0.0 (identical direction) → 2.0 (antipodal).
  Zero-slot vs zero-slot returns 0.0 (treated as identical empty).
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Slot layout (LOCKED; do not reorder)
# ---------------------------------------------------------------------------

SLOT_NAMES: Tuple[str, ...] = (
    "sentence",
    "svg",
    "wave",
    "time_forward",
    "time_inverted",
    "dialectic_position",
    "visual_bitmap_dct",
    "antipodal_xor",
)

SLOT_BYTES = 32                            # bytes per slot (int8 × 32 dims)
SLOT_HEX_CHARS = SLOT_BYTES * 2            # 64 hex chars per slot
NUM_SLOTS = len(SLOT_NAMES)                # 8
TOTAL_BYTES = SLOT_BYTES * NUM_SLOTS       # 256
TOTAL_HEX_CHARS = TOTAL_BYTES * 2          # 512
ZERO_SLOT_HEX = "00" * SLOT_BYTES          # 64-char all-zero hex
ZERO_SLOT_BYTES = bytes(SLOT_BYTES)        # 32 zero bytes
SCALE = 127                                # int8 symmetric range


_SLOT_INDEX: Dict[str, int] = {n: i for i, n in enumerate(SLOT_NAMES)}


# ---------------------------------------------------------------------------
# Optional dependency probes (graceful stdlib fallbacks)
# ---------------------------------------------------------------------------

def _try_import_energy_inversion():
    try:
        from energy_inversion import to_hex_int8 as _hx, from_hex_int8 as _fx  # type: ignore
        return _hx, _fx
    except Exception:
        try:
            from core.lib.energy_inversion import to_hex_int8 as _hx, from_hex_int8 as _fx  # type: ignore
            return _hx, _fx
        except Exception:
            return None, None


def _try_import_sentence_embedding():
    try:
        from sentence_chain import sentence_embedding as _se  # type: ignore
        return _se
    except Exception:
        try:
            from core.lib.sentence_chain import sentence_embedding as _se  # type: ignore
            return _se
        except Exception:
            return None


def _try_import_svg_embed():
    try:
        from svg_vector_embed import embed_svg_file as _ev  # type: ignore
        return _ev
    except Exception:
        try:
            from core.lib.svg_vector_embed import embed_svg_file as _ev  # type: ignore
            return _ev
        except Exception:
            return None


_to_hex_int8_ext, _from_hex_int8_ext = _try_import_energy_inversion()
_sentence_embedding_ext = _try_import_sentence_embedding()
_embed_svg_file_ext = _try_import_svg_embed()


# ---------------------------------------------------------------------------
# Stdlib-only int8 codec (used when energy_inversion isn't importable)
# ---------------------------------------------------------------------------

def _stdlib_to_hex_int8(vec: Iterable[float], scale: int = SCALE) -> str:
    """Pure-stdlib mirror of energy_inversion.to_hex_int8 (same rounding semantics).

    Per-component math:
      q = int(round(v * scale)); clamp to [-127, 127]; byte-cast (two's complement).
    """
    bs = bytearray()
    for v in vec:
        try:
            q = int(round(float(v) * scale))
        except (TypeError, ValueError):
            q = 0
        if q > 127:
            q = 127
        elif q < -127:
            q = -127
        bs.append(q & 0xFF)
    return bytes(bs).hex()


def _stdlib_from_hex_int8(hex_str: str, scale: int = SCALE) -> List[float]:
    bs = bytes.fromhex(hex_str)
    out: List[float] = []
    for b in bs:
        s = b - 256 if b > 127 else b
        out.append(s / scale)
    return out


def _to_hex_int8(vec: List[float]) -> str:
    """Quantize floats → int8 → hex. Delegates to energy_inversion when available."""
    if _to_hex_int8_ext is not None:
        try:
            return _to_hex_int8_ext(list(vec), SCALE)
        except Exception:
            pass
    return _stdlib_to_hex_int8(vec, SCALE)


def _from_hex_int8(hex_str: str) -> List[float]:
    if _from_hex_int8_ext is not None:
        try:
            return _from_hex_int8_ext(hex_str, None, SCALE)
        except Exception:
            pass
    return _stdlib_from_hex_int8(hex_str, SCALE)


# ---------------------------------------------------------------------------
# Slot-level vector preparation: pull → take_first(32) → pad → quantize
# ---------------------------------------------------------------------------

def _take_first_32(vec: Optional[Iterable[float]]) -> List[float]:
    """Trim to exactly 32 dims; pad short vectors with 0.0; reject non-iterables."""
    if vec is None:
        return [0.0] * SLOT_BYTES
    out: List[float] = []
    try:
        for x in vec:
            if len(out) >= SLOT_BYTES:
                break
            try:
                out.append(float(x))
            except (TypeError, ValueError):
                out.append(0.0)
    except TypeError:
        return [0.0] * SLOT_BYTES
    if len(out) < SLOT_BYTES:
        out.extend([0.0] * (SLOT_BYTES - len(out)))
    return out


def _slot_hex_from_vec(vec: Optional[Iterable[float]]) -> str:
    """Empty/missing vec → 32 zero bytes. Otherwise int8-quantize first 32 dims."""
    if vec is None:
        return ZERO_SLOT_HEX
    sized = _take_first_32(vec)
    if all(abs(x) < 1e-12 for x in sized):
        return ZERO_SLOT_HEX
    h = _to_hex_int8(sized)
    # Defensive: enforce exact 64-char slot length even if helper misbehaves.
    if len(h) > SLOT_HEX_CHARS:
        h = h[:SLOT_HEX_CHARS]
    elif len(h) < SLOT_HEX_CHARS:
        h = h + "0" * (SLOT_HEX_CHARS - len(h))
    return h


# ---------------------------------------------------------------------------
# Per-slot source extractors (each may return None to mean "no data")
# ---------------------------------------------------------------------------

def _slot_sentence(record: Dict[str, Any]) -> Optional[List[float]]:
    prompt = record.get("original_prompt") or ""
    if not prompt or not isinstance(prompt, str):
        return None
    if _sentence_embedding_ext is None:
        return None
    try:
        emb = _sentence_embedding_ext(prompt)
        return list(emb) if emb else None
    except Exception:
        return None


def _slot_svg(record: Dict[str, Any]) -> Optional[List[float]]:
    src = record.get("source_file") or ""
    if not src or not isinstance(src, str):
        return None
    if not src.lower().endswith(".svg"):
        return None
    if _embed_svg_file_ext is None:
        return None
    try:
        recs = _embed_svg_file_ext(src)
        if not recs:
            return None
        # Take the first path's embedding as the file-level slot.
        first = recs[0]
        emb = getattr(first, "embedding", None)
        if emb is None and isinstance(first, dict):
            emb = first.get("embedding")
        return list(emb) if emb else None
    except Exception:
        return None


def _slot_wave(record: Dict[str, Any]) -> Optional[List[float]]:
    wave = record.get("wave_emb")
    if not wave:
        return None
    try:
        return list(wave)
    except TypeError:
        return None


def _slot_time(record: Dict[str, Any], key: str) -> Optional[List[float]]:
    tv = record.get("time_vec") or {}
    if not isinstance(tv, dict):
        return None
    arm = tv.get(key)
    if not arm:
        return None
    try:
        return list(arm)
    except TypeError:
        return None


def _xor_hex(a: str, b: str) -> str:
    """Byte-wise XOR of two equal-length hex strings."""
    try:
        ba = bytes.fromhex(a)
        bb = bytes.fromhex(b)
    except ValueError:
        return ZERO_SLOT_HEX
    n = min(len(ba), len(bb))
    out = bytes(ba[i] ^ bb[i] for i in range(n))
    if len(out) < SLOT_BYTES:
        out = out + bytes(SLOT_BYTES - len(out))
    elif len(out) > SLOT_BYTES:
        out = out[:SLOT_BYTES]
    return out.hex()


# ---------------------------------------------------------------------------
# Public API: pack / unpack / inspect
# ---------------------------------------------------------------------------

def pack_layers(record: Dict[str, Any]) -> str:
    """Pack an InferenceRecord-shaped dict into the 512-char multi-layer hex envelope.

    Slot rules (in lock-step with SLOT_NAMES):
      0 sentence            sentence_chain.sentence_embedding(record['original_prompt'])
      1 svg                 embed_svg_file(record['source_file']) when path ends in .svg
      2 wave                record['wave_emb']                    (64-d DCT-II spectrum)
      3 time_forward        record['time_vec']['forward']
      4 time_inverted       record['time_vec']['inverted']
      5 dialectic_position  EMPTY in v1 (placeholder for dialectic_walker)
      6 visual_bitmap_dct   EMPTY in v1 (placeholder for visual DCT)
      7 antipodal_xor       XOR of slot 0 ⊕ slot 1 (sentence ⊕ svg differential check)

    Empty slots are 32 zero bytes (length-stable so callers can slice by slot index).
    Returns: 512-char lowercase hex string.

    SIDECAR: do NOT add the returned string to the InferenceRecord canonical JSON
    used for crystal hashing. The caller stores it on a sidecar attribute.
    """
    if not isinstance(record, dict):
        record = {}

    slot_hex: List[str] = []

    # Slot 0 — sentence
    slot_hex.append(_slot_hex_from_vec(_slot_sentence(record)))
    # Slot 1 — svg
    slot_hex.append(_slot_hex_from_vec(_slot_svg(record)))
    # Slot 2 — wave (already 64-d; first 32 dims used)
    slot_hex.append(_slot_hex_from_vec(_slot_wave(record)))
    # Slot 3 — time_forward
    slot_hex.append(_slot_hex_from_vec(_slot_time(record, "forward")))
    # Slot 4 — time_inverted
    slot_hex.append(_slot_hex_from_vec(_slot_time(record, "inverted")))
    # Slot 5 — dialectic_position (v1 reserved)
    slot_hex.append(ZERO_SLOT_HEX)
    # Slot 6 — visual_bitmap_dct (v1 reserved)
    slot_hex.append(ZERO_SLOT_HEX)
    # Slot 7 — antipodal XOR of sentence ⊕ svg
    slot_hex.append(_xor_hex(slot_hex[0], slot_hex[1]))

    envelope = "".join(slot_hex)
    # Defensive length enforcement (should never trigger if slots stay 64-char).
    if len(envelope) > TOTAL_HEX_CHARS:
        envelope = envelope[:TOTAL_HEX_CHARS]
    elif len(envelope) < TOTAL_HEX_CHARS:
        envelope = envelope + "0" * (TOTAL_HEX_CHARS - len(envelope))
    return envelope


def unpack_layers(hex_str: str) -> Dict[str, bytes]:
    """Return {slot_name: 32 raw bytes} for diagnostics.

    Short/long inputs are padded/truncated to TOTAL_HEX_CHARS so the dict
    always has every slot name with exactly SLOT_BYTES bytes.
    """
    if not isinstance(hex_str, str):
        hex_str = ""
    s = hex_str.strip().lower()
    if len(s) < TOTAL_HEX_CHARS:
        s = s + "0" * (TOTAL_HEX_CHARS - len(s))
    elif len(s) > TOTAL_HEX_CHARS:
        s = s[:TOTAL_HEX_CHARS]
    out: Dict[str, bytes] = {}
    for i, name in enumerate(SLOT_NAMES):
        chunk = s[i * SLOT_HEX_CHARS:(i + 1) * SLOT_HEX_CHARS]
        try:
            out[name] = bytes.fromhex(chunk)
        except ValueError:
            out[name] = ZERO_SLOT_BYTES
    return out


def has_slot(hex_str: str, slot: str) -> bool:
    """True if the named slot contains at least one non-zero byte."""
    if slot not in _SLOT_INDEX:
        return False
    chunks = unpack_layers(hex_str)
    return any(b != 0 for b in chunks[slot])


def _slot_hex_chunk(hex_str: str, slot: str) -> str:
    """Extract the 64-char hex chunk for one slot (zero-pads if input is short)."""
    if slot not in _SLOT_INDEX:
        return ZERO_SLOT_HEX
    if not isinstance(hex_str, str):
        hex_str = ""
    s = hex_str.strip().lower()
    if len(s) < TOTAL_HEX_CHARS:
        s = s + "0" * (TOTAL_HEX_CHARS - len(s))
    i = _SLOT_INDEX[slot]
    chunk = s[i * SLOT_HEX_CHARS:(i + 1) * SLOT_HEX_CHARS]
    if len(chunk) != SLOT_HEX_CHARS:
        return ZERO_SLOT_HEX
    return chunk


def slot_distance(hex_a: str, hex_b: str, slot: str) -> float:
    """Cosine-style distance over just one slot.

    Returns 1 - cosine_similarity over the 32 dequantized floats:
      - 0.0  → slots point in the same direction (identical, modulo quantization)
      - 1.0  → orthogonal
      - 2.0  → antipodal
    Two zero slots (both unset) return 0.0 — they're identically empty.
    A zero vs non-zero slot returns 1.0 (orthogonal by convention).
    """
    chunk_a = _slot_hex_chunk(hex_a, slot)
    chunk_b = _slot_hex_chunk(hex_b, slot)

    a_zero = chunk_a == ZERO_SLOT_HEX
    b_zero = chunk_b == ZERO_SLOT_HEX
    if a_zero and b_zero:
        return 0.0
    if a_zero or b_zero:
        return 1.0

    va = _from_hex_int8(chunk_a)
    vb = _from_hex_int8(chunk_b)
    n = min(len(va), len(vb), SLOT_BYTES)
    if n == 0:
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for i in range(n):
        dot += va[i] * vb[i]
        na += va[i] * va[i]
        nb += vb[i] * vb[i]
    denom = math.sqrt(na) * math.sqrt(nb)
    if denom < 1e-12:
        return 0.0 if dot == 0.0 else 1.0
    cos = dot / denom
    if cos > 1.0:
        cos = 1.0
    elif cos < -1.0:
        cos = -1.0
    return 1.0 - cos


# ---------------------------------------------------------------------------
# CLI (diagnostic only — never required for the runtime path)
# ---------------------------------------------------------------------------

def _main() -> None:
    import argparse
    import json
    import sys

    ap = argparse.ArgumentParser(description="multi_layer_hex — sidecar 8-slot envelope")
    sub = ap.add_subparsers(dest="cmd")

    p_pack = sub.add_parser("pack", help="pack a JSON record dict from stdin → 512-char hex")
    p_pack.add_argument("record_json", nargs="?", default="-", help="JSON or '-' for stdin")

    p_unpack = sub.add_parser("unpack", help="unpack a hex envelope and show each slot's nonzero count")
    p_unpack.add_argument("hex_str")

    p_dist = sub.add_parser("distance", help="slot distance between two hex envelopes")
    p_dist.add_argument("hex_a")
    p_dist.add_argument("hex_b")
    p_dist.add_argument("--slot", required=True, choices=list(SLOT_NAMES))

    p_layout = sub.add_parser("layout", help="print the locked slot layout")

    args = ap.parse_args()

    if args.cmd == "pack":
        raw = sys.stdin.read() if args.record_json == "-" else args.record_json
        rec = json.loads(raw) if raw.strip() else {}
        h = pack_layers(rec)
        print(json.dumps({
            "hex": h,
            "len": len(h),
            "slots": {name: has_slot(h, name) for name in SLOT_NAMES},
        }, indent=2))

    elif args.cmd == "unpack":
        unpacked = unpack_layers(args.hex_str)
        summary = {}
        for name, raw in unpacked.items():
            nonzero = sum(1 for b in raw if b != 0)
            summary[name] = {"nonzero_bytes": nonzero, "head_hex": raw[:8].hex()}
        print(json.dumps(summary, indent=2))

    elif args.cmd == "distance":
        d = slot_distance(args.hex_a, args.hex_b, args.slot)
        print(json.dumps({"slot": args.slot, "distance": round(d, 6)}, indent=2))

    elif args.cmd == "layout":
        layout = {
            "slot_names": list(SLOT_NAMES),
            "slot_bytes": SLOT_BYTES,
            "slot_hex_chars": SLOT_HEX_CHARS,
            "num_slots": NUM_SLOTS,
            "total_bytes": TOTAL_BYTES,
            "total_hex_chars": TOTAL_HEX_CHARS,
            "scale": SCALE,
        }
        print(json.dumps(layout, indent=2))

    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
