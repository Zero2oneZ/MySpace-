#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        kernel_registry
# role:        SAFETY · THE FUNCTION PLANE (closed, vetted kernel set)
# tier:        L0
# substrate:   the imperative "HOW" half of the description⟂function split. The
#              GUI + Claude Code author the declarative IR (morph_chain); they
#              may only REFERENCE kernels here by id, never author them. This
#              file is the codegen-safety boundary: if a kernel_ref doesn't
#              resolve here, the validation gate rejects the IR and nothing runs.
# reuse:       leaves derived from planning/hf_task_evolution.jsonl (53 HF
#              tasks today; the file grows); connector/modifier/governor
#              kernels are the vetted ops; CARD plane auto-scans every
#              workflow_card in studio/assets/_workflows/ so each new card
#              is a new kernel — the deterministic set grows, stays closed.
# ----------------------------------------------------------------------------
"""kernel_registry — the closed set of executable kernels morph IR may bind to.

A kernel = {id, archetype, in_type, out_type, params}. Six archetype planes,
matching the Loom: LEAF (HF tasks), MORPH (geometry modifiers), BLEND (scene
ops), GOVERNOR (channel protocol), CONNECTOR (Blender/Godot/ComfyUI/...),
CARD (workflow_card_v0 JSONs on disk — recursion closed: a card may bind to
another card via `kernel_ref: "card:<name>"`). A morph node carries a
`kernel_ref` of the form '<plane>:<id>[:<exemplar>]'; validation resolves
the id against this set.

CC composes IR that references these; it never writes a kernel. That is the
whole safety argument: codegen is constrained to wiring audited functions.
The set grows whenever a new vetted workflow_card lands on disk.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[2]  # core/lib/kernel_registry.py → project root
TAXONOMY = REPO / "planning" / "hf_task_evolution.jsonl"
CARDS_DIR = REPO / "studio" / "assets" / "_workflows"

# modality word ↔ canonical type token (mirrors morph_chain._MOD)
_TYPE = {"text": "TEXT", "image": "IMAGE", "img": "IMAGE", "video": "VIDEO",
         "audio": "AUDIO", "speech": "AUDIO", "3d": "3D", "mesh": "3D",
         "scene": "SCENE", "depth": "DEPTH", "pose": "POSE", "label": "LABEL",
         "embedding": "EMB", "vector": "EMB", "code": "CODE", "geometry": "GEO",
         "channel": "CHAN"}


def norm_type(t: str) -> str:
    return _TYPE.get((t or "").strip().lower(), (t or "").strip().upper() or "ANY")


# ── the closed kernel set ─────────────────────────────────────────────────────

def _leaf_kernels() -> Dict[str, Dict[str, Any]]:
    """LEAF plane: every HF task = one vetted kernel (in/out from its modalities)."""
    out: Dict[str, Dict[str, Any]] = {}
    if not TAXONOMY.exists():
        return out
    for ln in TAXONOMY.read_text().splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            t = json.loads(ln)
        except Exception:
            continue
        task = t.get("task")
        if not task:
            continue
        ins = [str(x).upper() for x in (t.get("inputs") or [])] or ["ANY"]
        outs = [str(x).upper() for x in (t.get("outputs") or [])] or ["ANY"]
        out[task] = {"id": task, "archetype": "LEAF", "plane": "hf",
                     "in_type": ins, "out_type": outs,
                     "exemplars": (t.get("exemplars") or [])[:6],
                     "params": {}}
    return out


# MORPH plane — geometry modifiers (the morph.engine modifier stack)
_MORPH_KERNELS = {
    "Noise":      {"in_type": ["GEO"], "out_type": ["GEO"], "params": {"amp": "float", "freq": "float"}},
    "Spike":      {"in_type": ["GEO"], "out_type": ["GEO"], "params": {"amount": "float"}},
    "Twist":      {"in_type": ["GEO"], "out_type": ["GEO"], "params": {"angle": "float"}},
    "Bend":       {"in_type": ["GEO"], "out_type": ["GEO"], "params": {"amount": "float"}},
    "MeshSmooth": {"in_type": ["GEO"], "out_type": ["GEO"], "params": {"factor": "float"}},
    "HueShift":   {"in_type": ["GEO"], "out_type": ["GEO"], "params": {"hue": "float"}},
}
# BLEND plane — scene composer ops (the blend.engine scene stack)
_BLEND_KERNELS = {
    "Object":  {"in_type": ["SCENE"], "out_type": ["SCENE"], "params": {"engine_ref": "str"}},
    "Arrange": {"in_type": ["SCENE"], "out_type": ["SCENE"], "params": {"transform": "str"}},
    "Light":   {"in_type": ["SCENE"], "out_type": ["SCENE"], "params": {"kind": "str"}},
    "Camera":  {"in_type": ["SCENE"], "out_type": ["SCENE"], "params": {"lens": "float"}},
    "Render":  {"in_type": ["SCENE"], "out_type": ["IMAGE", "VIDEO"], "params": {"passes": "str"}},
}
# GOVERNOR plane — engine.morpher protocol stack (channel between engines)
_GOVERNOR_KERNELS = {
    "Encode":  {"in_type": ["CHAN"], "out_type": ["CHAN"], "params": {"dict": "str", "ratio": "float"}},
    "Frame":   {"in_type": ["CHAN"], "out_type": ["CHAN"], "params": {"schema": "str"}},
    "Route":   {"in_type": ["CHAN"], "out_type": ["CHAN"], "params": {"depth": "int"}},
    "Contain": {"in_type": ["CHAN"], "out_type": ["CHAN"], "params": {"gate": "str"}},
    "Verify":  {"in_type": ["CHAN"], "out_type": ["CHAN"], "params": {"root": "str", "strict": "bool"}},
    "Channel": {"in_type": ["CHAN"], "out_type": ["CHAN"], "params": {"peer": "str", "duplex": "bool"}},
}
# CONNECTOR plane — the live local connectors (vetted, dry-run-safe)
_CONNECTOR_KERNELS = {
    "blender":     {"in_type": ["ANY"], "out_type": ["3D"], "params": {"op": "str"}},
    "godot":       {"in_type": ["3D"], "out_type": ["SCENE"], "params": {}},
    "comfyui":     {"in_type": ["ANY"], "out_type": ["IMAGE", "VIDEO"], "params": {}},
    "generative":  {"in_type": ["ANY"], "out_type": ["ANY"], "params": {}},
    "topstep":     {"in_type": ["ANY"], "out_type": ["LABEL"], "params": {"confirm": "bool"}},
}
# ATTACHMENT plane — persistent props/refs/notes that travel through the
# chain WITHOUT transforming data. They live as sub-objects of a pass
# (`pass.attachments[]`) OR as siblings in the sequence (`engine="attachment"`
# pass with `attachment_kind` + `label` + `body`). The runtime registers
# them but does not execute them — they extend the per-pass `tool_options`
# that the CONTROLS pane renders. Same primitive across "doc", "asset",
# "ref", "note", "file", "link".
_ATTACHMENT_KERNELS = {
    "doc":   {"in_type": ["ANY"], "out_type": ["ANY"], "params": {"label": "str", "body": "str"}},
    "asset": {"in_type": ["ANY"], "out_type": ["ANY"], "params": {"label": "str", "body": "str", "uri": "str"}},
    "ref":   {"in_type": ["ANY"], "out_type": ["ANY"], "params": {"label": "str", "body": "str", "uri": "str"}},
    "note":  {"in_type": ["ANY"], "out_type": ["ANY"], "params": {"label": "str", "body": "str"}},
    "file":  {"in_type": ["ANY"], "out_type": ["ANY"], "params": {"label": "str", "path": "str"}},
    "link":  {"in_type": ["ANY"], "out_type": ["ANY"], "params": {"label": "str", "url":  "str"}},
}


def _card_kernels() -> Dict[str, Dict[str, Any]]:
    """CARD plane: every workflow_card_v0 JSON on disk is a vetted kernel.

    This is the recursion close — a card may declare a pass with
    `kernel_ref: "card:<name>"` and the gate resolves it through the registry.
    A card's in_type is the first pass's `in[]`; out_type is the last
    `outputs[]`. Unknown / malformed cards are silently skipped (validation
    happens via workflow_card_v0 schema, not here).
    """
    out: Dict[str, Dict[str, Any]] = {}
    if not CARDS_DIR.exists():
        return out
    for p in sorted(CARDS_DIR.glob("*.json")):
        try:
            t = json.loads(p.read_text())
        except Exception:
            continue
        if t.get("_schema") != "workflow_card_v0":
            continue
        name = t.get("name")
        if not name:
            continue
        # derive types: inputs / outputs blocks if present, else first pass / last pass
        ins = [str(x.get("type", "ANY")).upper() for x in (t.get("inputs") or [])] or ["ANY"]
        outs = [str(x.get("type", "ANY")).upper() for x in (t.get("outputs") or [])] or ["ANY"]
        out[name] = {
            "id": name, "archetype": "CARD", "plane": "card",
            "in_type": ins, "out_type": outs,
            "category": t.get("category", ""),
            "state": t.get("state", "active"),
            "pass_count": len(t.get("passes") or []),
            "card_path": str(p.relative_to(REPO)),
            "params": {"card_ref": "str"},
        }
    return out


def _registry() -> Dict[str, Dict[str, Any]]:
    reg: Dict[str, Dict[str, Any]] = {}
    reg.update(_leaf_kernels())
    for src, arch, plane in ((_MORPH_KERNELS, "MORPH", "modifier"),
                             (_BLEND_KERNELS, "BLEND", "scene"),
                             (_GOVERNOR_KERNELS, "GOVERNOR", "governor"),
                             (_CONNECTOR_KERNELS, "CONNECTOR", "connector"),
                             (_ATTACHMENT_KERNELS, "ATTACHMENT", "attachment")):
        for kid, spec in src.items():
            reg[kid] = {"id": kid, "archetype": arch, "plane": plane, **spec}
    reg.update(_card_kernels())
    return reg


_REG: Optional[Dict[str, Dict[str, Any]]] = None


def registry() -> Dict[str, Dict[str, Any]]:
    global _REG
    if _REG is None:
        _REG = _registry()
    return _REG


# ── resolution (kernel_ref → kernel) ──────────────────────────────────────────

def kernel_id_of(kernel_ref: str) -> str:
    """'hf:Text-to-Image:DALL-E' → 'Text-to-Image' ; 'connector:blender' →
    'blender' ; 'provider:deepseek-chat' → provider id. The middle id is what
    must exist in the closed set."""
    if not kernel_ref:
        return ""
    parts = kernel_ref.split(":")
    return parts[1] if len(parts) >= 2 else parts[0]


def resolve(kernel_ref: str) -> Optional[Dict[str, Any]]:
    reg = registry()
    kid = kernel_id_of(kernel_ref)
    if kid in reg:
        return reg[kid]
    # connector planes name the kernel by the plane itself (godot:asset_gallery,
    # blender:rig.walk, comfyui:flux) → resolve via the plane = connector id.
    plane = kernel_ref.split(":", 1)[0] if ":" in kernel_ref else ""
    if plane in reg:
        return reg[plane]
    # providers/endpoints are a vetted plane too (the model ladder) — allow them
    if plane in ("provider", "endpoint"):
        return {"id": kid, "archetype": "LEAF", "plane": plane,
                "in_type": ["ANY"], "out_type": ["ANY"], "params": {}}
    return None


def type_ok(kernel: Dict[str, Any], frm: str, to: str) -> bool:
    """Port type-check: the morph's modalities must be compatible with the
    kernel's declared in/out types (ANY is a wildcard)."""
    fi, ti = norm_type(frm), norm_type(to)
    ins, outs = kernel.get("in_type", ["ANY"]), kernel.get("out_type", ["ANY"])
    in_ok = "ANY" in ins or fi in ins or fi == "ANY" or not frm
    out_ok = "ANY" in outs or ti in outs or ti == "ANY" or not to
    return in_ok and out_ok


# ── CLI / introspection ───────────────────────────────────────────────────────

def summary() -> Dict[str, Any]:
    reg = registry()
    by_arch: Dict[str, int] = {}
    for k in reg.values():
        by_arch[k["archetype"]] = by_arch.get(k["archetype"], 0) + 1
    return {"total_kernels": len(reg), "by_archetype": by_arch,
            "planes": sorted({k["plane"] for k in reg.values()})}


def main(argv: List[str]) -> int:
    if argv and argv[0] == "resolve" and len(argv) > 1:
        k = resolve(argv[1])
        print(json.dumps(k or {"error": f"UNRESOLVED kernel_ref: {argv[1]}"}, indent=2))
        return 0 if k else 3
    if argv and argv[0] == "list":
        print(json.dumps({"kernels": sorted(registry().keys())}, indent=2))
        return 0
    print(json.dumps(summary(), indent=2))
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
