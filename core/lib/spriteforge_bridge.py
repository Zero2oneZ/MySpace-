#!/usr/bin/env python3
"""
spriteforge_bridge — translate between SpriteForge descriptors and
workflow_card_v0 cards.

SpriteForge ships hand-authored / dispatcher-emitted manifests under
`studio/spriteforge/manifests/<name>_sheet.json` in a schema we call
`spriteforge_manifest_v0`. workflow_card_v0 lives under
`studio/assets/_workflows/`. Both already share the `layer_stack[]`
vocabulary (see SCHEMA_workflow_card_v0.md).

This module is the inverse pump: it lets a hand-rolled spriteforge
descriptor become a workflow_card, and lets a workflow_card emit a
descriptor the existing SpriteForge frontend / MCP can consume.

The bridge accepts TWO input shapes for descriptors:

  A) Canonical spriteforge_manifest_v0 — already has layer_stack[]
     with blend ∈ {base, multiply, normal_map, depth_uniform, alpha,
     opacity, additive, screen, overlay, gradient_h, gradient_v,
     color_dodge, soft_light, hard_light}.

  B) "Loose" shape — a top-level `layers[]` of rows shaped like
     {name, blend_mode|blend|mode, source}. blend_mode names are
     normalised via BLEND_MODE_ALIASES.

stdlib only. No external deps.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Canonical blend modes (workflow_card_v0 / Hypershade-style vocabulary)
# ---------------------------------------------------------------------------

CANONICAL_BLEND_MODES: tuple[str, ...] = (
    "base",
    "multiply",
    "screen",
    "overlay",
    "additive",
    "normal_map",
    "depth_uniform",
    "alpha",
    "opacity",
    "gradient_h",
    "gradient_v",
    "color_dodge",
    "soft_light",
    "hard_light",
)

# Maps common spriteforge / Photoshop / web-canvas blend names to the
# canonical 13. Keys are lower-cased and stripped of separators
# (`-`, `_`, ` `) before lookup, so "Linear Dodge", "linear-dodge",
# and "linear_dodge" all resolve.
BLEND_MODE_ALIASES: dict[str, str] = {
    # base / passthrough
    "base":            "base",
    "normal":          "base",
    "source-over":     "base",
    "passthrough":     "base",
    # darken family
    "multiply":        "multiply",
    "darken":          "multiply",
    "darker":          "multiply",
    "linearburn":      "multiply",
    "colorburn":       "multiply",
    # lighten family
    "screen":          "screen",
    "lighten":         "screen",
    "lighter":         "screen",
    # additive family
    "additive":        "additive",
    "add":             "additive",
    "lineardodge":     "additive",
    "lineardodgeadd":  "additive",
    "plus":            "additive",
    "linearlight":     "additive",
    # contrast family
    "overlay":         "overlay",
    "softlight":       "soft_light",
    "hardlight":       "hard_light",
    "vividlight":      "hard_light",
    "pinlight":        "hard_light",
    "hardmix":         "hard_light",
    # dodge family
    "colordodge":      "color_dodge",
    "dodge":           "color_dodge",
    # material / channel uniforms
    "normalmap":       "normal_map",
    "normal_map":      "normal_map",
    "bumpmap":         "normal_map",
    "depth":           "depth_uniform",
    "depthuniform":    "depth_uniform",
    "alpha":           "alpha",
    "mask":            "alpha",
    "opacity":         "opacity",
    "alphablend":      "opacity",
    # gradients
    "gradient":        "gradient_h",
    "gradienth":       "gradient_h",
    "horizontalgradient": "gradient_h",
    "gradientv":       "gradient_v",
    "verticalgradient": "gradient_v",
}


def normalise_blend_mode(mode: str | None) -> str:
    """Coerce any incoming blend string to a canonical mode. Unknown→base."""
    if not mode:
        return "base"
    key = str(mode).lower().replace("-", "").replace("_", "").replace(" ", "")
    return BLEND_MODE_ALIASES.get(key, "base")


# ---------------------------------------------------------------------------
# Descriptor loading
# ---------------------------------------------------------------------------

def load_spriteforge_descriptor(path: str) -> dict:
    """Read a SpriteForge JSON descriptor from disk and return the dict.

    Accepts spriteforge_manifest_v0 OR a loose {layers:[...]} shape.
    Light validation only — raises on unparseable JSON or non-dict roots.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"descriptor not found: {path}")
    raw = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"descriptor root must be object, got {type(raw).__name__}")
    return raw


def _extract_layers(descriptor: dict) -> list[dict]:
    """Pull the layer rows out of either shape (A or B)."""
    if "layer_stack" in descriptor and isinstance(descriptor["layer_stack"], list):
        return descriptor["layer_stack"]
    if "layers" in descriptor and isinstance(descriptor["layers"], list):
        return descriptor["layers"]
    return []


# ---------------------------------------------------------------------------
# Forward: descriptor → workflow_card layer_stack[]
# ---------------------------------------------------------------------------

def descriptor_to_layer_stack(descriptor: dict) -> list[dict]:
    """Convert spriteforge layer rows into workflow_card_v0 layer_stack[]."""
    out: list[dict] = []
    for row in _extract_layers(descriptor):
        if not isinstance(row, dict):
            continue
        name = row.get("name") or row.get("id") or "unnamed"
        source = row.get("source") or row.get("from") or "literal:0.0"
        raw_blend = row.get("blend") or row.get("blend_mode") or row.get("mode")
        blend = normalise_blend_mode(raw_blend)
        entry: dict[str, Any] = {
            "name": str(name),
            "source": str(source),
            "blend": blend,
        }
        if "target_uniform" in row:
            entry["target_uniform"] = row["target_uniform"]
        out.append(entry)
    return out


# ---------------------------------------------------------------------------
# Reverse: workflow_card layer_stack[] → descriptor
# ---------------------------------------------------------------------------

def layer_stack_to_descriptor(layer_stack: list[dict]) -> dict:
    """Emit a spriteforge_manifest_v0-shaped descriptor from a layer_stack."""
    layers: list[dict] = []
    for row in layer_stack:
        if not isinstance(row, dict):
            continue
        name = row.get("name", "unnamed")
        entry: dict[str, Any] = {
            "name": name,
            "source": row.get("source", "literal:0.0"),
            "blend": normalise_blend_mode(row.get("blend") or row.get("blend_mode")),
            "target_uniform": row.get("target_uniform") or f"u_{name}",
        }
        layers.append(entry)
    return {
        "_schema": "spriteforge_manifest_v0",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "layer_stack": layers,
        "spriteforge_mcp": "spriteforge-mcp",
        "tools_to_call": ["sprite_refine_prompt", "sprite_generate"],
    }


# ---------------------------------------------------------------------------
# Card composition
# ---------------------------------------------------------------------------

def compose_card_from_descriptor(descriptor: dict, name: str) -> dict:
    """Build a minimal workflow_card_v0 from a spriteforge descriptor."""
    layer_stack = descriptor_to_layer_stack(descriptor)

    # Stub passes — one spriteforge engine pass that consumes the
    # descriptor's named layers and emits a sprite atlas.
    layer_names = [row["name"] for row in layer_stack] or ["albedo"]
    passes = [
        {
            "id": "sprite_compose",
            "agent": "spriteforge_mcp",
            "engine": "spriteforge",
            "in": layer_names,
            "out": "sprite_sheet",
            "tier": "low",
            "status": descriptor.get("status", "STUB"),
        }
    ]

    inputs = descriptor.get("inputs") or [
        {"name": "photo", "type": "image/jpeg|png", "required": True}
    ]
    outputs = descriptor.get("outputs") or [
        {"name": "sprite_sheet", "type": "png_atlas+manifest"}
    ]

    card: dict[str, Any] = {
        "_schema": "workflow_card_v0",
        "vm_id": "vm_mspc_001",
        "symbol": "vm_mspc_001",
        "domain": "workflows",
        "category": "sprite",
        "name": name,
        "state": "draft",
        "version": "v0",
        "summary": descriptor.get(
            "summary",
            f"Auto-composed sprite workflow from spriteforge descriptor: {name}.",
        ),
        "inputs": inputs,
        "outputs": outputs,
        "passes": passes,
        "layer_stack": layer_stack,
        "surfaces": {
            "spriteforge": {
                "mcp_server": "spriteforge-mcp",
                "tools": ["sprite_refine_prompt", "sprite_generate"],
                "manifest_out": f"studio/spriteforge/manifests/{name}_sheet.json",
            }
        },
        "crystal": "",
        "depends_on": descriptor.get("depends_on", []),
        "_provenance": {
            "source": "spriteforge_bridge.compose_card_from_descriptor",
            "src_schema": descriptor.get("_schema", "unknown"),
            "src_card_name": descriptor.get("card_name"),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
    }
    return card


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _write_json(path: str, data: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")


def _cmd_to_card(args: argparse.Namespace) -> int:
    descriptor = load_spriteforge_descriptor(args.descriptor)
    name = args.name or descriptor.get("card_name") or Path(args.descriptor).stem
    card = compose_card_from_descriptor(descriptor, name)
    _write_json(args.out, card)
    print(f"wrote workflow_card → {args.out} "
          f"(layer_stack={len(card['layer_stack'])}, passes={len(card['passes'])})")
    return 0


def _cmd_to_descriptor(args: argparse.Namespace) -> int:
    card = json.loads(Path(args.card).read_text(encoding="utf-8"))
    layer_stack = card.get("layer_stack", [])
    descriptor = layer_stack_to_descriptor(layer_stack)
    descriptor["card_name"] = card.get("name", "untitled")
    if "crystal" in card and card["crystal"]:
        descriptor["card_crystal"] = card["crystal"]
    _write_json(args.out, descriptor)
    print(f"wrote spriteforge descriptor → {args.out} "
          f"(layer_stack={len(descriptor['layer_stack'])})")
    return 0


def _cmd_list_modes(_args: argparse.Namespace) -> int:
    print("canonical blend modes:")
    for m in CANONICAL_BLEND_MODES:
        print(f"  {m}")
    print(f"\naliases ({len(BLEND_MODE_ALIASES)}):")
    for k, v in sorted(BLEND_MODE_ALIASES.items()):
        if k != v:
            print(f"  {k:<22} -> {v}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="spriteforge_bridge",
        description="Bridge SpriteForge descriptors <-> workflow_card_v0 cards.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_to_card = sub.add_parser("to-card", help="descriptor → workflow_card")
    p_to_card.add_argument("descriptor", help="path to spriteforge descriptor JSON")
    p_to_card.add_argument("--out", required=True, help="output card path")
    p_to_card.add_argument("--name", help="card name (default: descriptor.card_name)")
    p_to_card.set_defaults(func=_cmd_to_card)

    p_to_desc = sub.add_parser("to-descriptor", help="workflow_card → descriptor")
    p_to_desc.add_argument("card", help="path to workflow_card JSON")
    p_to_desc.add_argument("--out", required=True, help="output descriptor path")
    p_to_desc.set_defaults(func=_cmd_to_descriptor)

    p_modes = sub.add_parser("list-modes", help="print canonical modes + aliases")
    p_modes.set_defaults(func=_cmd_list_modes)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
