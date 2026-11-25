#!/usr/bin/env python3
# ============================================================================
# GODOT ELEMENT COMPILER
# ----------------------------------------------------------------------------
# name:        godot_element_compiler
# role:        COMPILER · COMPOSITION_CARD_TO_TSCN
# tier:        L0
# substrate:   studio/assets/_godot_elements/*.json (element registry)
#              + composition cards (godot_composition_v0)
# engine:      pure-python string assembly (stdlib only)
# ----------------------------------------------------------------------------
#
# Composition card schema (godot_composition_v0):
# {
#   "_schema":       "godot_composition_v0",
#   "name":          "<scene_name>",            # used for root node name
#   "root_class":    "Node3D",                  # Godot class for the root
#   "root_inherits": "Node3D",                  # for GD stub `extends`
#   "script_path":   "res://src/<file>.gd",    # optional ExtResource script
#   "children": [
#     {
#       "element":  "button"      | "Camera3D", # registry key OR raw class
#       "name":     "MyNode",
#       "exports":  {"text": "\"Hello\"", "fov": "75.0"},
#       "children": [ ... ]                    # recursive
#     }
#   ]
# }
#
# FALLBACK BEHAVIOR (important):
# If a child's `element` is not in the registry, the compiler treats the
# value as a raw Godot class name (e.g. "Camera3D", "Node3D", "Sprite3D").
# This means the compiler still functions when _godot_elements/ is empty
# or partially populated (Agent 7 owns those cards).
#
# Property assignment in [node] blocks uses the element card's `exports[]`
# list as the canonical name set (when card present); unknown export keys
# are still emitted (raw passthrough).
# ============================================================================

from __future__ import annotations

import argparse
import json
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ----------------------------------------------------------------------------
# Layout constants
# ----------------------------------------------------------------------------

ELEMENTS_DIR = Path(__file__).resolve().parents[2] / "studio" / "assets" / "_godot_elements"


# ----------------------------------------------------------------------------
# Dataclasses
# ----------------------------------------------------------------------------

@dataclass
class CompChild:
    """One child node in a composition card (resolved form)."""
    element: str                                  # registry key OR raw class name
    name: str                                     # node name in scene
    exports: Dict[str, str] = field(default_factory=dict)
    children: List["CompChild"] = field(default_factory=list)


@dataclass
class Composition:
    """Parsed composition card."""
    name: str
    root_class: str
    root_inherits: str
    script_path: Optional[str]
    children: List[CompChild] = field(default_factory=list)


# ----------------------------------------------------------------------------
# Registry loading
# ----------------------------------------------------------------------------

def load_registry() -> Dict[str, dict]:
    """Load all element cards from ELEMENTS_DIR keyed by `name` field.

    Gracefully returns {} with a warning when the directory is missing
    or empty (Agent 7 hasn't populated cards yet).
    """
    registry: Dict[str, dict] = {}
    if not ELEMENTS_DIR.exists():
        warnings.warn(
            f"godot_element_compiler: elements dir missing ({ELEMENTS_DIR}); "
            "compiler will treat element names as raw Godot class names."
        )
        return registry

    cards = sorted(ELEMENTS_DIR.glob("*.json"))
    if not cards:
        warnings.warn(
            f"godot_element_compiler: no element cards found in {ELEMENTS_DIR}; "
            "compiler will treat element names as raw Godot class names."
        )
        return registry

    for path in cards:
        try:
            with path.open("r", encoding="utf-8") as fh:
                card = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            warnings.warn(f"godot_element_compiler: skipping {path.name}: {exc}")
            continue
        key = card.get("name")
        if not key:
            warnings.warn(f"godot_element_compiler: card {path.name} has no 'name' field")
            continue
        registry[key] = card
    return registry


# ----------------------------------------------------------------------------
# Composition loading
# ----------------------------------------------------------------------------

def _parse_children(raw: List[dict]) -> List[CompChild]:
    out: List[CompChild] = []
    for i, c in enumerate(raw or []):
        element = c.get("element")
        if not element:
            raise ValueError(f"composition child #{i} missing 'element' field")
        out.append(CompChild(
            element=element,
            name=c.get("name") or element,
            exports=dict(c.get("exports") or {}),
            children=_parse_children(c.get("children") or []),
        ))
    return out


def load_composition(path: str) -> dict:
    """Load + minimally validate a composition card from disk.

    Returns the raw dict (callers may wrap via _to_dataclass when needed).
    """
    p = Path(path)
    with p.open("r", encoding="utf-8") as fh:
        comp = json.load(fh)

    schema = comp.get("_schema")
    if schema != "godot_composition_v0":
        warnings.warn(
            f"godot_element_compiler: composition {p.name} has _schema={schema!r}, "
            "expected 'godot_composition_v0'"
        )

    if not comp.get("name"):
        raise ValueError(f"composition {p.name} missing top-level 'name'")
    if not comp.get("root_class"):
        raise ValueError(f"composition {p.name} missing 'root_class'")

    return comp


def _to_dataclass(comp: dict) -> Composition:
    return Composition(
        name=comp["name"],
        root_class=comp["root_class"],
        root_inherits=comp.get("root_inherits") or comp["root_class"],
        script_path=comp.get("script_path") or None,
        children=_parse_children(comp.get("children") or []),
    )


# ----------------------------------------------------------------------------
# Resolution helpers
# ----------------------------------------------------------------------------

def _resolve_class(element: str, registry: Dict[str, dict]) -> str:
    """Map an element name to a Godot class name.

    Registry hits use the card's `godot_class`; misses pass the value
    through verbatim (fallback for the unpopulated-registry case).
    """
    card = registry.get(element)
    if card and card.get("godot_class"):
        return card["godot_class"]
    return element


# ----------------------------------------------------------------------------
# .tscn emission
# ----------------------------------------------------------------------------

def _format_node_block(
    node_name: str,
    godot_class: str,
    parent_path: Optional[str],
    exports: Dict[str, str],
    script_ext_id: Optional[str] = None,
) -> str:
    """Emit one [node ...] block + its property lines.

    parent_path uses Godot conventions:
        - root node: omit `parent`
        - first-level child: parent="."
        - deeper child: parent="Parent/Sub"
    """
    header_parts = [f'name="{node_name}"', f'type="{godot_class}"']
    if parent_path is not None:
        header_parts.append(f'parent="{parent_path}"')
    header = "[node " + " ".join(header_parts) + "]"

    lines = [header]
    for key, value in exports.items():
        # Values are pre-formatted Godot literals (quoted strings, Vector3(...), bools, ints).
        lines.append(f"{key} = {value}")
    if script_ext_id is not None:
        lines.append(f'script = ExtResource("{script_ext_id}")')
    return "\n".join(lines)


def _walk_children(
    children: List[CompChild],
    registry: Dict[str, dict],
    parent_path: str,
    blocks: List[str],
) -> None:
    for child in children:
        klass = _resolve_class(child.element, registry)
        blocks.append(_format_node_block(
            node_name=child.name,
            godot_class=klass,
            parent_path=parent_path,
            exports=child.exports,
        ))
        if child.children:
            sub_parent = child.name if parent_path == "." else f"{parent_path}/{child.name}"
            _walk_children(child.children, registry, sub_parent, blocks)


def compile_tscn(comp: dict, registry: Dict[str, dict]) -> str:
    """Compile a composition dict into Godot 4 .tscn text."""
    c = _to_dataclass(comp)

    ext_resources: List[str] = []
    script_ext_id: Optional[str] = None
    if c.script_path:
        script_ext_id = "1_script"
        ext_resources.append(
            f'[ext_resource type="Script" path="{c.script_path}" id="{script_ext_id}"]'
        )

    blocks: List[str] = []
    blocks.append(_format_node_block(
        node_name=c.name,
        godot_class=c.root_class,
        parent_path=None,
        exports={},  # root exports could be added later if needed
        script_ext_id=script_ext_id,
    ))

    _walk_children(c.children, registry, parent_path=".", blocks=blocks)

    # load_steps = number of [ext_resource] + [sub_resource] + 1 (the scene itself).
    load_steps = len(ext_resources) + 1
    header = f"[gd_scene load_steps={load_steps} format=3]"

    parts: List[str] = [header, ""]
    if ext_resources:
        parts.extend(ext_resources)
        parts.append("")
    parts.append("\n\n".join(blocks))
    parts.append("")  # trailing newline
    return "\n".join(parts)


# ----------------------------------------------------------------------------
# .gd stub emission
# ----------------------------------------------------------------------------

def _collect_signals(children: List[CompChild], registry: Dict[str, dict]) -> List[dict]:
    seen = set()
    out: List[dict] = []
    for child in children:
        card = registry.get(child.element)
        if card:
            for sig in card.get("signals") or []:
                sig_name = sig.get("name")
                if sig_name and sig_name not in seen:
                    seen.add(sig_name)
                    out.append(sig)
        out.extend(_collect_signals(child.children, registry))
    return out


def _collect_exports(children: List[CompChild], registry: Dict[str, dict]) -> List[dict]:
    """Pull a deduplicated list of (name, type, default) exports from cards."""
    seen = set()
    out: List[dict] = []
    for child in children:
        card = registry.get(child.element)
        if card:
            for exp in card.get("exports") or []:
                ename = exp.get("name")
                if ename and ename not in seen:
                    seen.add(ename)
                    out.append(exp)
        out.extend(_collect_exports(child.children, registry))
    return out


def compile_gd(comp: dict, registry: Optional[Dict[str, dict]] = None) -> str:
    """Emit a starter GDScript stub for a composition.

    Returns an `extends <root_class>` file with @export lines for top-level
    element exports + signal declarations harvested from card metadata.
    """
    c = _to_dataclass(comp)
    reg = registry if registry is not None else {}

    lines: List[str] = []
    lines.append(f"extends {c.root_inherits}")
    lines.append(f"## {c.name} — auto-generated from godot_composition_v0 card.")
    lines.append("##")
    lines.append("## Hand-edit freely; the compiler will not overwrite this file")
    lines.append("## unless you explicitly request a regenerate.")
    lines.append("")

    signals = _collect_signals(c.children, reg)
    for sig in signals:
        params = sig.get("params") or []
        if params:
            lines.append(f"signal {sig['name']}({', '.join(params)})")
        else:
            lines.append(f"signal {sig['name']}")
    if signals:
        lines.append("")

    exports = _collect_exports(c.children, reg)
    for exp in exports:
        ename = exp["name"]
        etype = exp.get("type") or "Variant"
        default = exp.get("default")
        # Godot @export syntax: @export var name: Type = default
        if default is not None and default != "":
            lines.append(f"@export var {ename}: {etype} = {default}")
        else:
            lines.append(f"@export var {ename}: {etype}")
    if exports:
        lines.append("")

    lines.append("func _ready() -> void:")
    lines.append("\tpass")
    lines.append("")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# Disk emit
# ----------------------------------------------------------------------------

def emit(
    comp_path: str,
    out_tscn: str,
    out_gd: Optional[str] = None,
) -> Tuple[Path, Optional[Path]]:
    """Load + compile + write. Returns (tscn_path, gd_path_or_None)."""
    registry = load_registry()
    comp = load_composition(comp_path)

    tscn_text = compile_tscn(comp, registry)
    tscn_path = Path(out_tscn)
    tscn_path.parent.mkdir(parents=True, exist_ok=True)
    tscn_path.write_text(tscn_text, encoding="utf-8")

    gd_path: Optional[Path] = None
    if out_gd:
        gd_path = Path(out_gd)
        if gd_path.exists():
            warnings.warn(
                f"godot_element_compiler: {gd_path} exists; skipping GD stub emission."
            )
        else:
            gd_text = compile_gd(comp, registry)
            gd_path.parent.mkdir(parents=True, exist_ok=True)
            gd_path.write_text(gd_text, encoding="utf-8")

    return tscn_path, gd_path


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def _cli_compile(args: argparse.Namespace) -> int:
    tscn_path, gd_path = emit(args.composition, args.out, args.out_gd)
    print(f"wrote {tscn_path}")
    if gd_path is not None:
        print(f"wrote {gd_path}")
    return 0


def _cli_inspect(args: argparse.Namespace) -> int:
    registry = load_registry()
    card = registry.get(args.name)
    if card is None:
        print(f"element {args.name!r} not in registry", file=sys.stderr)
        return 1
    print(json.dumps(card, indent=2))
    return 0


def _cli_list(_args: argparse.Namespace) -> int:
    registry = load_registry()
    if not registry:
        print("(registry empty)")
        return 0
    width = max(len(k) for k in registry.keys())
    for name in sorted(registry.keys()):
        klass = registry[name].get("godot_class", "?")
        print(f"{name.ljust(width)}  -> {klass}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="godot_element_compiler",
        description="Compile godot_composition_v0 cards into Godot 4 .tscn scenes.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_compile = sub.add_parser("compile", help="compile a composition into a .tscn")
    p_compile.add_argument("composition", help="path to composition JSON")
    p_compile.add_argument("--out", required=True, help="output .tscn path")
    p_compile.add_argument("--out-gd", dest="out_gd", default=None,
                           help="optional output .gd stub path")
    p_compile.set_defaults(func=_cli_compile)

    p_inspect = sub.add_parser("inspect", help="print a registered element card")
    p_inspect.add_argument("name", help="element name (e.g. 'button')")
    p_inspect.set_defaults(func=_cli_inspect)

    p_list = sub.add_parser("list", help="list registered elements")
    p_list.set_defaults(func=_cli_list)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
