#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        dimension_pack
# role:        SUBSTRATE · UNIVERSAL_5_TUPLE_RECORD_SIGNATURE
# tier:        L0
# substrate:   the audit layer that makes every chain entry queryable in all
#              five canonical frames simultaneously (vector / circle / hex /
#              rgb / fps) without re-computation
# storage:     SIDECAR — does NOT enter canonical_json; v1 chain verification
#              unchanged. Stored optionally at ~/.cc/dimension_packs/<crystal>.json
# ----------------------------------------------------------------------------
# THE FIVE CANONICAL FRAMES (per Tom's directive 2026-05-28)
# ----------------------------------------------------------------------------
#   vector_hex_64    — first 64 hex chars of multi_layer_hex.pack_layers(record)
#                       (continuous embedding axis; what the chain "looks like"
#                        in frequency-domain via DCT-II + int8 quant)
#   circle_motif_id  — recursive_workflows match: which SCC/cycle this event
#                       closes into (the loop axis — every event is part of
#                       SOME closed cycle; if not yet, it's a leaf marked '*')
#   crystal_hex       — InferenceRecord.crystal_id (the universal anchor;
#                       BLAKE3 deterministic fingerprint of (tier,model,scope,
#                       prompt,output,prev_crystal))
#   rgba              — deterministic 4-float color derived from
#                       (tier, cost_class, sub_dag); same inputs → same color
#                       across all sub-DAGs forever
#   frame_pack         — frame_clock.FrameClock.now() at all 5 canonical FPS
#                       (24, 30, 60, 90, 120) — every event becomes
#                       "constant-time data" in 5 reference frames at once
# ----------------------------------------------------------------------------
# WHY SIDECAR
# ----------------------------------------------------------------------------
# v1 of the crystal chain (~500 records this session) hashes a specific set of
# fields via canonical_json. Adding new fields to the hash would invalidate
# existing crystals. By holding dimension_pack as a sidecar (parallel JSON file
# OR a non-hashed coordinates entry), we preserve the chain's tamper-evidence
# while gaining the 5-tuple audit. A v2 schema can later promote to canonical.
# ============================================================================
"""dimension_pack.py — the 5-tuple universal record signature.

Every chain entry, regardless of sub-DAG or tier, becomes queryable in 5
canonical frames at once. No re-computation needed; just pick which slot
you want to read against.

Public API:
    emit(record_dict, crystal_id='') -> DimensionPack
    pack_to_dict(pack) -> dict
    deterministic_rgba(tier, cost_class='', sub_dag='') -> list[float]  # [r,g,b,a]
    match_recursion(involved_nodes_or_record) -> str
    audit_chain(chain_jsonl_path, sample=20, only_missing=False) -> list[dict]

CLI:
    python3 core/lib/dimension_pack.py emit --tier model_api \
        --cost-class cheap --sub-dag INFERENCE [--save]
    python3 core/lib/dimension_pack.py audit --sample 20
    python3 core/lib/dimension_pack.py rgba-table
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
_PROJECT_ROOT = _HERE.parent.parent


# ---------------------------------------------------------------------------
# Canonical FPS (mirrors frame_clock; copied here for zero-dep fallback)
# ---------------------------------------------------------------------------

CANONICAL_FPS: Tuple[int, ...] = (24, 30, 60, 90, 120)


# ---------------------------------------------------------------------------
# Sub-DAG hue assignment (deterministic, locked)
# ---------------------------------------------------------------------------

SUB_DAG_HUES: Dict[str, float] = {
    "PLATFORMS":            210.0,   # blue
    "DOCS":                 130.0,   # green
    "INFERENCE":             30.0,   # orange
    "APPS":                 290.0,   # purple
    "RECURSIVE_WORKFLOWS":    0.0,   # red
    "ORCHESTRATION":        220.0,   # slate-blue
    "":                      60.0,   # default yellow when sub_dag absent
}

COST_CLASS_SATURATION: Dict[str, float] = {
    "deterministic": 0.95,
    "free":          0.90,
    "cheap":         0.75,
    "medium":        0.60,
    "fast":          0.85,
    "expensive":     0.50,
    "premium":       0.45,
    "large":         0.35,
    "unknown":       0.55,
    "":              0.55,
}

# Tier → value (V in HSV). Lower = darker. Categorical priorities.
TIER_VALUE: Dict[str, float] = {
    "genesis":             1.0,
    "monetization":        0.95,
    "trade_action":        0.90,
    "deploy":              0.85,
    "model_api":           0.80,
    "inference":           0.75,
    "ml_train":            0.70,
    "ml_inference":        0.65,
    "social_event":        0.60,
    "social_graph":        0.55,
    "legal_acceptance":    0.95,
    "documentation":       0.50,
    "generative":          0.65,
    "morph_plan":          0.70,
    "morph_plan_served":   0.65,
    "identity_resolution": 0.75,
    "visualization":       0.55,
    "fb_event":            0.60,
    "pump_stream_session": 0.50,
    "pump_wave_served":    0.50,
    "ssot_api":            0.70,
    "noun_project_import": 0.50,
    "loop_cycle":          0.95,
    "runtime":             0.80,
    "queue":               0.40,
    "large":               0.40,
    "defi_loop":           0.85,
}


# ---------------------------------------------------------------------------
# HSV → RGB helper (stdlib; deterministic)
# ---------------------------------------------------------------------------

def _hsv_to_rgb(h_deg: float, s: float, v: float) -> Tuple[float, float, float]:
    h = (h_deg % 360.0) / 60.0
    c = v * s
    x = c * (1 - abs((h % 2) - 1))
    m = v - c
    if h < 1:
        r, g, b = c, x, 0
    elif h < 2:
        r, g, b = x, c, 0
    elif h < 3:
        r, g, b = 0, c, x
    elif h < 4:
        r, g, b = 0, x, c
    elif h < 5:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x
    return (r + m, g + m, b + m)


def deterministic_rgba(tier: str = "", cost_class: str = "",
                          sub_dag: str = "", alpha: float = 0.92) -> List[float]:
    """Deterministic 4-float color from (tier, cost_class, sub_dag).
    Same inputs always produce the same color — across runs, across machines."""
    h = SUB_DAG_HUES.get(sub_dag, SUB_DAG_HUES[""])
    s = COST_CLASS_SATURATION.get(cost_class, COST_CLASS_SATURATION[""])
    v = TIER_VALUE.get(tier, 0.55)
    r, g, b = _hsv_to_rgb(h, s, v)
    return [round(r, 4), round(g, 4), round(b, 4), round(alpha, 4)]


# ---------------------------------------------------------------------------
# Frame pack (FPS quantization across all 5 canonical rates simultaneously)
# ---------------------------------------------------------------------------

def _frame_pack_from_ts(ts: float) -> Dict[int, int]:
    """For each canonical FPS, compute the integer frame index for this ts.
    Mirrors frame_clock.timestamp_to_frame logic with zero-dep fallback."""
    try:
        from frame_clock import timestamp_to_frame, CANONICAL_FPS as _FC_FPS  # type: ignore
        return {fps: timestamp_to_frame(ts, fps) for fps in _FC_FPS}
    except Exception:
        pass
    # Fallback: floor(ts * fps) — same semantics as frame_clock
    return {fps: int(math.floor(ts * fps)) for fps in CANONICAL_FPS}


# ---------------------------------------------------------------------------
# Vector slot (DCT-II 64-d, packed to hex via multi_layer_hex)
# ---------------------------------------------------------------------------

def _vector_hex_64(record: Dict[str, Any]) -> str:
    """First 64 hex chars (= 32 bytes = 1 slot) of multi_layer_hex.pack_layers.
    Graceful fallback: SHA-256 of canonical record JSON truncated to 64 hex.

    Lookup priority (Tom's "continuous encoder" wedge):
      1. record["embedding_hex"] — caller pre-computed via stream_encoder.
      2. embedding_index lookup by record["crystal_id"] — find the encoder's
         output if the event's been embedded.
      3. multi_layer_hex.pack_layers — original wave-emb path.
      4. SHA-256 of canonical JSON — hash fallback for raw chain events.

    Same record always produces the same 64-char prefix across runs.
    """
    # Priority 1: caller-supplied embedding (encoded inline by stream_encoder)
    inline = record.get("embedding_hex") if isinstance(record, dict) else None
    if isinstance(inline, str) and len(inline) >= 64:
        return inline[:64]

    canonical = json.dumps(record, sort_keys=True, separators=(",", ":"),
                            ensure_ascii=True, default=str)
    sha_fallback = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:64]

    # Priority 2: embedding_index lookup by crystal_id
    crystal = record.get("crystal_id") if isinstance(record, dict) else None
    if crystal:
        try:
            from embedding_index import get_singleton  # type: ignore
            idx = get_singleton()
            hit = idx.find_by_crystal(str(crystal))
            if hit is not None:
                _, vec = hit
                # Pack first 8 floats (32 bytes) → 64 hex
                import struct
                buf = b"".join(struct.pack("<f", float(v)) for v in vec[:8])
                return buf.hex()[:64]
        except Exception:
            pass

    # Priority 3: multi_layer_hex
    try:
        from multi_layer_hex import pack_layers  # type: ignore
        full = pack_layers(record)
        head = (full or "")[:64].ljust(64, "0")
        # All-zero prefix means the packer had no payload to hash → use SHA.
        if head == "0" * 64 or set(head) <= {"0"}:
            return sha_fallback
        return head
    except Exception:
        return sha_fallback


# ---------------------------------------------------------------------------
# Circle slot (recursion match)
# ---------------------------------------------------------------------------

_RECURSIONS_DIR = _PROJECT_ROOT / "studio" / "assets" / "_recursions"


def match_recursion(record_or_nodes: Any) -> str:
    """Returns the recursion crystal_id this event closes into, or '*' if
    the event is a leaf (not yet part of any detected SCC/cycle/motif).
    Cheap: scans persisted recursions; first match wins."""
    if not _RECURSIONS_DIR.exists():
        return "*"
    # Extract the set of node IDs this record is "about"
    nodes: List[str] = []
    if isinstance(record_or_nodes, list):
        nodes = list(record_or_nodes)
    elif isinstance(record_or_nodes, dict):
        for k in ("involved_nodes", "model", "scope", "agent",
                   "source_action", "model_path"):
            v = record_or_nodes.get(k)
            if isinstance(v, list):
                nodes.extend(str(x) for x in v)
            elif isinstance(v, str):
                nodes.append(v)
    if not nodes:
        return "*"
    nodes_lower = {n.lower() for n in nodes if n}
    for f in sorted(_RECURSIONS_DIR.glob("*.json")):
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        rec_nodes = {str(n).lower() for n in (r.get("nodes") or [])}
        # Match if ANY of the record's node names appears in the recursion's nodes
        if rec_nodes & nodes_lower or any(
            any(rn in node or node in rn for rn in rec_nodes)
            for node in nodes_lower
        ):
            return r.get("crystal", "*")[:32] or "*"
    return "*"


# ---------------------------------------------------------------------------
# DimensionPack dataclass + emit()
# ---------------------------------------------------------------------------

@dataclass
class DimensionPack:
    vector_hex_64: str
    circle_motif_id: str
    crystal_hex: str
    rgba: List[float]
    frame_pack: Dict[int, int]
    ts: float = field(default_factory=time.time)
    pack_schema_version: str = "v1"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def emit(record: Dict[str, Any], crystal_id: str = "") -> DimensionPack:
    """Build a DimensionPack for any chain record (or any dict, really).
    Use after inference_logger.log() returns the crystal_id."""
    tier = str(record.get("tier", ""))
    cost_class = str(record.get("cost_class", ""))
    sub_dag = str(record.get("sub_dag", ""))
    ts = float(record.get("ts") or record.get("timestamp_unix") or time.time())
    # Infer sub_dag from tier if not provided
    if not sub_dag:
        sub_dag = _infer_sub_dag_from_tier(tier)
    crystal_hex = (crystal_id or record.get("crystal_id", "") or "")[:128]
    return DimensionPack(
        vector_hex_64=_vector_hex_64(record),
        circle_motif_id=match_recursion(record),
        crystal_hex=crystal_hex,
        rgba=deterministic_rgba(tier, cost_class, sub_dag),
        frame_pack=_frame_pack_from_ts(ts),
        ts=ts,
    )


_TIER_TO_SUB_DAG: Dict[str, str] = {
    "monetization":        "PLATFORMS",
    "trade_action":        "PLATFORMS",
    "social_event":        "PLATFORMS",
    "social_graph":        "PLATFORMS",
    "fb_event":            "PLATFORMS",
    "noun_project_import": "PLATFORMS",
    "documentation":       "DOCS",
    "inference":           "INFERENCE",
    "model_api":           "INFERENCE",
    "ml_inference":        "INFERENCE",
    "ml_train":            "INFERENCE",
    "generative":          "INFERENCE",
    "morph_plan":          "APPS",
    "morph_plan_served":   "APPS",
    "deploy":              "APPS",
    "visualization":       "APPS",
    "ssot_api":            "APPS",
    "pump_stream_session": "APPS",
    "pump_wave_served":    "APPS",
    "identity_resolution": "APPS",
    "legal_acceptance":    "PLATFORMS",
    "loop_cycle":          "RECURSIVE_WORKFLOWS",
    "defi_loop":           "PLATFORMS",
    "runtime":             "ORCHESTRATION",
    "queue":               "ORCHESTRATION",
}


def _infer_sub_dag_from_tier(tier: str) -> str:
    return _TIER_TO_SUB_DAG.get(tier, "")


# ---------------------------------------------------------------------------
# Optional persistence (sidecar)
# ---------------------------------------------------------------------------

def save_pack(pack: DimensionPack, output_dir: Optional[Path] = None) -> Path:
    if output_dir is None:
        output_dir = Path.home() / ".cc" / "dimension_packs"
    output_dir.mkdir(parents=True, exist_ok=True)
    key = pack.crystal_hex[:32] or hashlib.sha256(
        json.dumps(pack.to_dict(), sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:32]
    out_path = output_dir / f"{key}.json"
    out_path.write_text(json.dumps(pack.to_dict(), separators=(",", ":"),
                                       sort_keys=True), encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# Audit — apply emit() to existing chain entries to fill the gap retroactively
# ---------------------------------------------------------------------------

def audit_chain(chain_jsonl_path: Optional[Path] = None,
                  sample: int = 20, only_missing: bool = False) -> List[Dict[str, Any]]:
    """Walk the master chain; emit a DimensionPack for each entry (or a sample);
    return a list of summary dicts. only_missing=True → skip entries whose
    crystal already has a sidecar file."""
    if chain_jsonl_path is None:
        chain_jsonl_path = Path.home() / ".cc" / "inference_master_chain.jsonl"
    if not chain_jsonl_path.exists():
        return []
    existing_dir = Path.home() / ".cc" / "dimension_packs"
    existing = set()
    if only_missing and existing_dir.exists():
        existing = {f.stem for f in existing_dir.glob("*.json")}

    lines = chain_jsonl_path.read_text(encoding="utf-8").splitlines()
    if sample > 0:
        lines = lines[-sample:]

    out: List[Dict[str, Any]] = []
    for ln in lines:
        if not ln.strip():
            continue
        try:
            r = json.loads(ln)
        except Exception:
            continue
        crystal = r.get("crystal_id", "") or r.get("crystal", "")
        if only_missing and crystal[:32] in existing:
            continue
        pack = emit(r, crystal_id=crystal)
        out.append({
            "tier": r.get("tier", ""),
            "model": r.get("model", "")[:32],
            "crystal_short": crystal[:16],
            "rgba": pack.rgba,
            "circle": pack.circle_motif_id,
            "frame_60fps": pack.frame_pack.get(60, 0),
            "vec_head": pack.vector_hex_64[:12],
        })
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="dimension_pack — 5-tuple universal record signature")
    sub = ap.add_subparsers(dest="cmd")

    p_emit = sub.add_parser("emit", help="build a pack for a one-off synthetic record")
    p_emit.add_argument("--tier", default="model_api")
    p_emit.add_argument("--cost-class", default="cheap")
    p_emit.add_argument("--sub-dag", default="")
    p_emit.add_argument("--model", default="deepseek-chat")
    p_emit.add_argument("--scope", default="model_api_text")
    p_emit.add_argument("--prompt", default="hello")
    p_emit.add_argument("--save", action="store_true")

    p_audit = sub.add_parser("audit", help="apply emit() to recent chain entries")
    p_audit.add_argument("--chain", default=str(Path.home() / ".cc" / "inference_master_chain.jsonl"))
    p_audit.add_argument("--sample", type=int, default=20)
    p_audit.add_argument("--only-missing", action="store_true")
    p_audit.add_argument("--save-all", action="store_true",
                          help="persist a sidecar JSON per record under ~/.cc/dimension_packs/")

    p_rgba = sub.add_parser("rgba-table", help="dump the deterministic (tier x cost_class) → rgba color table")
    sub.add_parser("self-test", help="quick determinism check")

    args = ap.parse_args()

    if args.cmd == "emit":
        rec = {
            "tier": args.tier, "cost_class": args.cost_class, "sub_dag": args.sub_dag,
            "model": args.model, "scope": args.scope, "original_prompt": args.prompt,
            "ts": time.time(),
        }
        pack = emit(rec)
        out = pack.to_dict()
        print(json.dumps(out, indent=2, sort_keys=True))
        if args.save:
            p = save_pack(pack)
            print(f"\nsaved sidecar to {p}", file=sys.stderr)

    elif args.cmd == "audit":
        rows = audit_chain(Path(args.chain), sample=args.sample,
                            only_missing=args.only_missing)
        for r in rows:
            rgba_s = ",".join(f"{x:.2f}" for x in r["rgba"])
            print(f"{r['tier']:22s} {r['model']:24s} cry={r['crystal_short']:16s}  "
                   f"rgba=({rgba_s})  circle={r['circle']:18s}  f60={r['frame_60fps']:>14d}  vec={r['vec_head']}")
        if args.save_all:
            saved = 0
            chain_path = Path(args.chain)
            for ln in chain_path.read_text(encoding="utf-8").splitlines():
                if not ln.strip():
                    continue
                try:
                    rec = json.loads(ln)
                except Exception:
                    continue
                pack = emit(rec, crystal_id=rec.get("crystal_id", ""))
                save_pack(pack)
                saved += 1
            print(f"\npersisted {saved} sidecar packs", file=sys.stderr)
        if not rows:
            print("(no chain entries)")

    elif args.cmd == "rgba-table":
        tiers = sorted(set(TIER_VALUE.keys()))
        cost_classes = ["free", "cheap", "fast", "medium", "premium"]
        print(f"{'TIER':24s} " + "  ".join(f"{c:11s}" for c in cost_classes))
        for t in tiers:
            row = [f"{t:24s}"]
            for cc in cost_classes:
                rgba = deterministic_rgba(t, cc, _infer_sub_dag_from_tier(t))
                row.append(f"#{int(rgba[0]*255):02x}{int(rgba[1]*255):02x}{int(rgba[2]*255):02x}    ")
            print(" ".join(row))

    elif args.cmd == "self-test":
        # Determinism: same input → same color, same vector, same frame pack
        rec = {"tier": "model_api", "cost_class": "cheap",
                "sub_dag": "INFERENCE", "model": "deepseek-chat",
                "ts": 1.234567}
        p1 = emit(rec)
        p2 = emit(rec)
        assert p1.rgba == p2.rgba, "rgba not deterministic"
        assert p1.vector_hex_64 == p2.vector_hex_64, "vector_hex not deterministic"
        assert p1.frame_pack == p2.frame_pack, "frame_pack not deterministic"
        assert set(p1.frame_pack.keys()) == set(CANONICAL_FPS), "frame_pack missing canonical FPS"
        # Different sub_dag → different color
        rec2 = {**rec, "sub_dag": "APPS"}
        p3 = emit(rec2)
        assert p1.rgba != p3.rgba, "sub_dag change should change color"
        print("self-test OK")
        print(f"  vector_hex_64: {p1.vector_hex_64[:32]}...")
        print(f"  circle_motif:  {p1.circle_motif_id}")
        print(f"  rgba:          {p1.rgba}")
        print(f"  frame_pack:    {p1.frame_pack}")

    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
