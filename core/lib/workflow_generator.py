#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        workflow_generator
# role:        GENERATOR · WORKFLOW_CARD_TO_5_SURFACES
# tier:        L0
# substrate:   studio/assets/_workflows/*.json (input cards)
# engine:      template-fill (Python f-strings) + nano text-gen for descriptions
# storage:     emits files to surface-specific paths declared in card.surfaces
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.workflow_generator.active.json
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - core/cc.sh::cmd_workflow_generate (cc workflow generate <card> --target *)
#   - CLI: python3 workflow_generator.py generate <card_path> --target *
# outbound:
#   - task_queue.TaskQueue (nano text-gen via qwen2.5:0.5b)
#   - inference_logger (crystal chain per generation event)
#   - filesystem writes (5 surface paths from card.surfaces)
# substrate touch:
#   - reads:  studio/assets/_workflows/<card>.json
#   - writes:
#     * studio/web/streamlit/<name>.py
#     * studio/godot/project/scenes/<name>.tscn
#     * studio/godot/project/src/<name>_controller.gd
#     * studio/godot/project/cpp/src/<name>_native.cpp
#     * studio/blender/scripts/<name>_bake.py
#     * studio/spriteforge/manifests/<name>_sheet.json
#     * /data/Projects/ComfyUI/user/workflows/<name>.json
# determinism:
#   - Same card_crystal → same emitted file bytes (modulo nano text-gen)
#   - card_crystal in every file's header
# ============================================================================
"""workflow_generator.py — emit 5 semantically-equivalent surfaces from one card.

Reads a workflow_card_v0 JSON. Emits, in parallel where useful:
  * Streamlit proto      (.py)            — fast prototype UI
  * Godot scene          (.tscn)          — production runtime
  * Godot controller     (.gd)            — scene logic
  * Godot native bridge  (.cpp)           — GDExtension (C++ default)
  * Blender bake         (.py)            — headless PBR bake script
  * SpriteForge manifest (.json)          — sprite sheet composition spec
  * ComfyUI workflow     (.json)          — drag-into-ComfyUI graph

Each emitted file carries a card_crystal header so we can verify they all came
from the same card. Re-running with no card changes produces identical bytes.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from task_queue import TaskQueue, Task, TaskKind  # type: ignore

try:
    import blake3 as _blake3_mod
    def _hash(data: bytes) -> str:
        return _blake3_mod.blake3(data).hexdigest()
except ImportError:
    def _hash(data: bytes) -> str:
        return hashlib.blake2b(data).hexdigest()


REPO_ROOT = Path("/data/Projects/MySpace++")
NANO_MODEL = os.environ.get("CC_NANO_MODEL", "qwen2.5:0.5b")
COMFY_INSTALL = Path(os.environ.get("CC_COMFY_INSTALL", "/data/Projects/ComfyUI"))

# Canonical morph-layer vocabulary (Photoshop / Hypershade layer-style universe)
# This is invariant #3 from architectural_invariants.md — same vocabulary across
# Godot shader uniforms, Blender Principled BSDF sockets, SpriteForge layers,
# ComfyUI image-mix nodes. Non-canonical names get warned (non-fatal).
CANONICAL_LAYERS = frozenset({
    "alpha", "normal", "depth", "albedo", "opacity", "ao",
    "gradient", "metallic", "roughness", "emission",
    "specular", "subsurface", "clearcoat", "transmission",
})
CANONICAL_BLENDS = frozenset({
    "base", "multiply", "screen", "overlay", "additive",
    "normal_map", "depth_uniform", "alpha", "opacity",
    "gradient_h", "gradient_v", "color_dodge", "soft_light", "hard_light",
    "subtract", "difference", "average",
})


def validate_card(card: Dict) -> List[str]:
    """Non-fatal validation against canonical morph-layer vocabulary.
    Returns a list of warning strings. Empty list = card is canonical."""
    issues: List[str] = []
    for i, layer in enumerate(card.get("layer_stack", []) or []):
        name = (layer.get("name") or "").lower()
        blend = (layer.get("blend") or "").lower()
        if name and name not in CANONICAL_LAYERS:
            issues.append(f"layer_stack[{i}].name='{name}' is non-canonical "
                          f"(allowed: {sorted(CANONICAL_LAYERS)})")
        if blend and blend not in CANONICAL_BLENDS:
            issues.append(f"layer_stack[{i}].blend='{blend}' is non-canonical "
                          f"(allowed: {sorted(CANONICAL_BLENDS)})")
    return issues


# ---------------------------------------------------------------------------
# Card loader + crystal
# ---------------------------------------------------------------------------

def load_card(path: str | Path) -> Dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def compute_card_crystal(card: Dict) -> str:
    canonical = json.dumps(
        {k: v for k, v in card.items() if k not in ("crystal", "_notes")},
        sort_keys=True, ensure_ascii=True, separators=(",", ":"),
    )
    return _hash(canonical.encode("utf-8"))


# ---------------------------------------------------------------------------
# Jinja2 template prefer-path — landed 2026-05-29.
# Each gen_* function tries a .j2 in studio/assets/_workflows/templates/
# before falling back to its internal f-string emitter. The convention is:
#   <surface>_<name>.j2 OR <name>_<surface_suffix>.j2 depending on history.
# Cards may override by declaring surfaces.<surface>.template (basename or
# full path relative to TEMPLATE_DIR).
# ---------------------------------------------------------------------------

TEMPLATE_DIR = REPO_ROOT / "studio" / "assets" / "_workflows" / "templates"


def _try_jinja_render(template_name: str, card: Dict, card_crystal: str,
                       extra: Optional[Dict] = None) -> Optional[str]:
    """Render `<TEMPLATE_DIR>/<template_name>` with Jinja2. Returns the
    rendered string, or None if the template doesn't exist, jinja2 isn't
    importable, or rendering raised. None lets the caller fall back to its
    f-string generator transparently.
    """
    if not template_name:
        return None
    path = TEMPLATE_DIR / template_name
    if not path.exists():
        return None
    try:
        import jinja2  # type: ignore
    except ImportError:
        sys.stderr.write(
            f"[workflow_generator] jinja2 not importable; falling back to "
            f"f-string emitter for {template_name}\n")
        return None
    try:
        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)),
            keep_trailing_newline=True,
            undefined=jinja2.StrictUndefined,
            autoescape=False,
        )
        tmpl = env.get_template(template_name)
        ctx = {
            "card": card,
            "card_crystal": card_crystal,
            "rendered_ts": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                          time.gmtime()),
            "card_hash": _hash(json.dumps(card, sort_keys=True,
                                            separators=(",", ":"),
                                            ensure_ascii=True
                                            ).encode())[:16],
        }
        if extra:
            ctx.update(extra)
        return tmpl.render(**ctx)
    except Exception as exc:
        sys.stderr.write(
            f"[workflow_generator] jinja render fail for {template_name}: "
            f"{exc!r}\n")
        return None


def _resolve_template_name(card: Dict, surface: str,
                            default_suffix: str) -> str:
    """Return the first existing .j2 basename for this (card, surface),
    trying the most-specific name first. Order:
        1. card.surfaces.<surface>.template (basename)
        2. <card.name><suffix>                — full snake_case
        3. <card.category><suffix>            — category-shared template
        4. <first word of card.name><suffix>  — convenience (e.g. 'pinterest')
    Returns the most-specific name even if nothing exists, so the caller's
    None-path through _try_jinja_render still falls back to f-string."""
    name = card.get("name", "untitled")
    category = card.get("category", "")
    first_word = name.split("_", 1)[0]

    candidates = []
    declared = ((card.get("surfaces") or {}).get(surface) or {}).get("template")
    if declared:
        candidates.append(Path(str(declared)).name)
    candidates.append(f"{name}{default_suffix}")
    if category and f"{category}{default_suffix}" not in candidates:
        candidates.append(f"{category}{default_suffix}")
    if first_word and f"{first_word}{default_suffix}" not in candidates:
        candidates.append(f"{first_word}{default_suffix}")
    # Universal fallback — a generic template that drives off card schema only.
    candidates.append(f"_default{default_suffix}")

    for c in candidates:
        if (TEMPLATE_DIR / c).exists():
            return c
    return candidates[0]  # nothing exists; _try_jinja_render will return None


# ---------------------------------------------------------------------------
# Nano text generator (descriptions, docstrings, UI labels)
# ---------------------------------------------------------------------------

class NanoDescriber:
    def __init__(self, queue: TaskQueue, model: str = NANO_MODEL):
        self.queue = queue
        self.model = model

    async def describe(self, intent: str, max_chars: int = 200) -> str:
        prompt = (
            f"Write ONE short sentence (max {max_chars} chars) describing this. "
            f"No preamble, no markdown, no quotes. Just the sentence.\n\nIntent: {intent}\n"
        )
        result = await self.queue.submit(Task(
            kind=TaskKind.OLLAMA,
            agent=self.model,
            prompt=prompt,
            params={"timeout": 20},
            label="nano_describe",
        ))
        out = (result.output or intent).strip()
        # Strip surrounding quotes / markdown
        out = out.strip('"').strip("'").strip("`").strip()
        # Take first line only
        out = out.split("\n")[0].strip()
        return out[:max_chars]


# ---------------------------------------------------------------------------
# Surface generators
# ---------------------------------------------------------------------------

@dataclass
class GenResult:
    surface: str
    out_path: Path
    bytes_written: int
    card_crystal: str


def _header_lines(prefix: str, card: Dict, card_crystal: str, target: str) -> str:
    """Generated-file header in the given comment prefix (e.g., '#', '//')."""
    return (
        f"{prefix} GENERATED from workflow_card: {card.get('name','?')}\n"
        f"{prefix} card_crystal: {card_crystal}\n"
        f"{prefix} target: {target}\n"
        f"{prefix} schema: {card.get('_schema','workflow_card_v0')}\n"
        f"{prefix} DO NOT EDIT BY HAND — regenerate via: cc workflow generate {card.get('name','?')}\n"
    )


# --- Streamlit ---------------------------------------------------------------

def gen_streamlit(card: Dict, card_crystal: str) -> str:
    j2 = _try_jinja_render(_resolve_template_name(card, "streamlit", "_proto.py.j2"),
                            card, card_crystal)
    if j2 is not None:
        return j2
    name = card.get("name", "untitled")
    summary = card.get("summary", "")
    inputs = card.get("inputs", [])
    outputs = card.get("outputs", [])
    passes = card.get("passes", [])

    input_widgets = []
    for inp in inputs:
        n = inp.get("name", "")
        t = inp.get("type", "")
        req = inp.get("required", False)
        label = n.replace("_", " ").title()
        if "image" in t:
            input_widgets.append(f'    {n} = st.file_uploader("{label}", type=["png","jpg","jpeg","webp"], help="{t}")')
        elif "audio" in t:
            input_widgets.append(f'    {n} = st.file_uploader("{label}", type=["wav","mp3","flac"], help="{t}")')
        elif "workflow_ref" in t:
            input_widgets.append(f'    {n} = st.text_input("{label}", help="workflow_ref or path")')
        else:
            input_widgets.append(f'    {n} = st.text_input("{label}", help="{t}")')
        if req:
            input_widgets.append(f'    # required: {n}')

    pass_lines = []
    for p in passes:
        pid = p.get("id", "?")
        agent = p.get("agent", "?")
        engine = p.get("engine", "?")
        status = p.get("status", "?")
        pass_lines.append(
            f'    with st.expander("pass: {pid} — {agent} [{engine}] ({status})"):\n'
            f'        st.code("in: {p.get("in",[])} → out: {p.get("out","?")}", language="text")'
        )

    body = "\n".join(input_widgets) or "    st.write('no inputs declared')"
    pass_body = "\n".join(pass_lines) or "    st.write('no passes declared')"

    return (
        _header_lines("#", card, card_crystal, "streamlit") +
        '"""Streamlit proto for ' + name + '."""\n'
        "import streamlit as st\n"
        "import json\n"
        "from pathlib import Path\n\n"
        f'st.set_page_config(page_title={json.dumps(name)}, layout="wide")\n'
        f'st.title({json.dumps(name)})\n'
        f'st.caption({json.dumps(summary)})\n'
        f'st.code("card_crystal: {card_crystal[:16]}…", language="text")\n\n'
        'st.subheader("Inputs")\n'
        'with st.form("inputs"):\n'
        f'{body}\n'
        '    submit = st.form_submit_button("Run pipeline")\n\n'
        'if submit:\n'
        '    st.subheader("Passes")\n'
        f'{pass_body}\n'
        '    st.success("Pipeline dispatched. See ~/.cc/inference_master_chain.jsonl for crystal trace.")\n'
    )


# --- Godot scene -------------------------------------------------------------

def gen_godot_tscn(card: Dict, card_crystal: str) -> str:
    j2 = _try_jinja_render(_resolve_template_name(card, "godot", "_scene.tscn.j2"),
                            card, card_crystal)
    if j2 is not None:
        return j2
    name = card.get("name", "untitled")
    uid_seed = card_crystal[:24]
    # Map name to script path declared in card
    surfaces = card.get("surfaces", {})
    gd_out = surfaces.get("godot", {}).get("out_script",
                                          f"studio/godot/project/src/{name}_controller.gd")
    script_res = "res://src/" + Path(gd_out).name

    return (
        '[gd_scene load_steps=2 format=3 uid="uid://' + uid_seed + '"]\n'
        '\n'
        '[ext_resource type="Script" path="' + script_res + '" id="1_main"]\n'
        '\n'
        f'; GENERATED · card_crystal={card_crystal}\n'
        f'[node name="{name.title().replace("_","")}" type="Node3D"]\n'
        'script = ExtResource("1_main")\n'
        '\n'
        '[node name="Camera3D" type="Camera3D" parent="."]\n'
        'transform = Transform3D(1, 0, 0, 0, 0.866, 0.5, 0, -0.5, 0.866, 0, 2.5, 5)\n'
        '\n'
        '[node name="Light" type="DirectionalLight3D" parent="."]\n'
        'transform = Transform3D(0.866, 0, -0.5, 0, 1, 0, 0.5, 0, 0.866, 0, 4, 0)\n'
        '\n'
        '[node name="AvatarMount" type="Node3D" parent="."]\n'
    )


# --- Godot GDScript controller ----------------------------------------------

def gen_godot_gd(card: Dict, card_crystal: str, nano_doc: str = "") -> str:
    j2 = _try_jinja_render(
        _resolve_template_name(card, "godot", "_controller.gd.j2"),
        card, card_crystal, extra={"nano_doc": nano_doc})
    if j2 is not None:
        return j2
    name = card.get("name", "untitled")
    summary = card.get("summary", "")
    passes = card.get("passes", [])
    inputs = card.get("inputs", [])
    layer_stack = card.get("layer_stack", [])

    pass_signals = "\n".join(f"signal {p.get('id','?')}_done(result)" for p in passes)
    in_vars = "\n".join(f"@export var {i.get('name','?')}: String = \"\"" for i in inputs)
    layer_consts = "\n".join(
        f'    "{layer.get("name","?")}": {{"blend": "{layer.get("blend","?")}", '
        f'"source": "{layer.get("source","?")}", '
        f'"uniform": "{layer.get("target_uniform","")}"}}'
        for layer in layer_stack
    )

    pass_calls = []
    for p in passes:
        pid = p.get("id", "?")
        agent = p.get("agent", "?")
        engine = p.get("engine", "?")
        pass_calls.append(
            f'    # pass: {pid} ({agent} via {engine})\n'
            f'    var {pid}_result = await _dispatch_pass("{pid}", "{agent}", "{engine}")\n'
            f'    emit_signal("{pid}_done", {pid}_result)'
        )

    safe_doc = nano_doc.replace('"', "'") if nano_doc else summary[:160]

    return (
        _header_lines("#", card, card_crystal, "godot_gd") +
        "extends Node3D\n"
        f"## {safe_doc}\n"
        f"## Summary: {summary[:200]}\n\n"
        f"{in_vars}\n\n"
        f"{pass_signals}\n\n"
        "const CARD_NAME: String = \"" + name + "\"\n"
        f"const CARD_CRYSTAL: String = \"{card_crystal}\"\n"
        "const LAYER_STACK: Dictionary = {\n"
        f"{layer_consts}\n"
        "}\n\n"
        "func _ready() -> void:\n"
        f"    print(\"[{name}] booted — crystal=\", CARD_CRYSTAL.substr(0, 16))\n"
        "    if CCBridge != null:\n"
        "        CCBridge.packet_received.connect(_on_cc_packet)\n"
        "    await _run_pipeline()\n\n"
        "func _run_pipeline() -> void:\n"
        f"{chr(10).join(pass_calls) if pass_calls else '    pass'}\n\n"
        "func _dispatch_pass(pass_id: String, agent: String, engine: String) -> Variant:\n"
        "    # Dispatches via CCBridge → task_queue → appropriate pool.\n"
        "    if CCBridge == null: return null\n"
        "    var packet := {\n"
        "        \"protocol\": \"cc_godot_bridge_v1\",\n"
        "        \"card_crystal\": CARD_CRYSTAL,\n"
        "        \"pass_id\": pass_id,\n"
        "        \"agent\": agent,\n"
        "        \"engine\": engine,\n"
        "    }\n"
        "    return await CCBridge.dispatch(packet)\n\n"
        "func _on_cc_packet(packet: Dictionary) -> void:\n"
        f"    print(\"[{name}] cc packet: \", packet.get(\"pass_id\", \"?\"))\n"
    )


# --- Godot C++ GDExtension --------------------------------------------------

def gen_godot_cpp(card: Dict, card_crystal: str) -> str:
    j2 = _try_jinja_render(_resolve_template_name(card, "godot", "_native.cpp.j2"),
                            card, card_crystal)
    if j2 is not None:
        return j2
    name = card.get("name", "untitled")
    class_name = "".join(p.capitalize() for p in name.split("_"))
    return (
        _header_lines("//", card, card_crystal, "godot_cpp") +
        '#include <godot_cpp/classes/node3d.hpp>\n'
        '#include <godot_cpp/core/class_db.hpp>\n'
        '#include <godot_cpp/variant/utility_functions.hpp>\n\n'
        'namespace godot {\n\n'
        f'class {class_name} : public Node3D {{\n'
        f'    GDCLASS({class_name}, Node3D);\n'
        'protected:\n'
        '    static void _bind_methods() {\n'
        f'        ClassDB::bind_method(D_METHOD("run_pipeline"), &{class_name}::run_pipeline);\n'
        f'        ClassDB::bind_method(D_METHOD("get_card_crystal"), &{class_name}::get_card_crystal);\n'
        '    }\n'
        'public:\n'
        f'    String get_card_crystal() const {{ return "{card_crystal}"; }}\n'
        '    void run_pipeline() {\n'
        f'        UtilityFunctions::print("[{name}] native pipeline run — crystal=", get_card_crystal().substr(0, 16));\n'
        '        // each pass dispatches via the CC bridge (see GDScript controller)\n'
        '    }\n'
        '};\n\n'
        '} // namespace godot\n'
    )


# --- Blender headless bake ---------------------------------------------------

def gen_blender(card: Dict, card_crystal: str) -> str:
    j2 = _try_jinja_render(_resolve_template_name(card, "blender", "_bake.py.j2"),
                            card, card_crystal)
    if j2 is not None:
        return j2
    name = card.get("name", "untitled")
    passes = card.get("passes", [])
    layer_stack = card.get("layer_stack", [])

    needs_bake = any(p.get("engine") == "blender" or "bake" in p.get("id", "") for p in passes)

    lines = []
    lines.append(_header_lines("#", card, card_crystal, "blender"))
    lines.append('"""Blender headless script. Usage:')
    lines.append(f'    blender --background --python {Path(card.get("surfaces", {}).get("blender", {}).get("out_path", "this.py")).name}')
    lines.append('"""')
    lines.append('import bpy')
    lines.append('import json')
    lines.append('import sys')
    lines.append('from pathlib import Path')
    lines.append('')
    lines.append(f'CARD_CRYSTAL = "{card_crystal}"')
    lines.append(f'CARD_NAME    = "{name}"')
    lines.append('')
    lines.append('LAYER_STACK = ' + json.dumps(layer_stack, indent=2))
    lines.append('')
    lines.append('def ensure_clean_scene():')
    lines.append('    for obj in list(bpy.data.objects):')
    lines.append('        bpy.data.objects.remove(obj, do_unlink=True)')
    lines.append('')
    lines.append('def add_pbr_material(name: str) -> bpy.types.Material:')
    lines.append('    mat = bpy.data.materials.new(name=name)')
    lines.append('    mat.use_nodes = True')
    lines.append('    return mat')
    lines.append('')
    lines.append('def main():')
    lines.append(f'    print(f"[{name}] blender headless start — crystal={{CARD_CRYSTAL[:16]}}…")')
    lines.append('    ensure_clean_scene()')
    lines.append('    mat = add_pbr_material(f"mat_{CARD_NAME}")')
    lines.append('    # Wire layer_stack channels onto Principled BSDF inputs:')
    lines.append('    for layer in LAYER_STACK:')
    lines.append('        ch = layer["name"]; src = layer["source"]; blend = layer["blend"]')
    lines.append('        print(f"  layer {ch} ← {src} ({blend})")')
    if needs_bake:
        lines.append('    # bake passes were declared by the card — wire actual bake nodes per layer here')
    lines.append('    print(f"[{CARD_NAME}] blender headless done")')
    lines.append('')
    lines.append('if __name__ == "__main__":')
    lines.append('    main()')
    return "\n".join(lines) + "\n"


# --- SpriteForge manifest ----------------------------------------------------

def gen_spriteforge(card: Dict, card_crystal: str) -> str:
    j2 = _try_jinja_render(
        _resolve_template_name(card, "spriteforge", "_spriteforge_manifest.json.j2"),
        card, card_crystal)
    if j2 is not None:
        return j2
    manifest = {
        "_schema": "spriteforge_manifest_v0",
        "card_name": card.get("name", "untitled"),
        "card_crystal": card_crystal,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "layer_stack": card.get("layer_stack", []),
        "passes": [
            {"id": p.get("id"), "agent": p.get("agent"), "engine": p.get("engine"),
             "status": p.get("status"), "in": p.get("in"), "out": p.get("out")}
            for p in card.get("passes", [])
        ],
        "spriteforge_mcp": card.get("surfaces", {}).get("spriteforge", {}).get("mcp_server", "spriteforge-mcp"),
        "tools_to_call": card.get("surfaces", {}).get("spriteforge", {}).get("tools", []),
        "outputs": card.get("outputs", []),
    }
    return json.dumps(manifest, indent=2)


# --- ComfyUI workflow JSON ---------------------------------------------------

def gen_comfyui(card: Dict, card_crystal: str) -> str:
    """Emit a starter ComfyUI workflow JSON. Uses LoadImage → PreviewImage with
    Notes for each declared pass so the user can wire them in the GUI."""
    j2 = _try_jinja_render(_resolve_template_name(card, "comfyui", "_comfy.json.j2"),
                            card, card_crystal)
    if j2 is not None:
        return j2
    name = card.get("name", "untitled")
    passes = card.get("passes", [])

    nodes: Dict[str, Dict[str, Any]] = {}
    next_id = 1

    # Node 1: LoadImage
    nodes[str(next_id)] = {
        "inputs": {"image": "input.png", "upload": "image"},
        "class_type": "LoadImage",
        "_meta": {"title": "LoadImage (card input)"}
    }
    load_id = str(next_id)
    next_id += 1

    # One Note per pass — gives the user a placeholder to wire up
    last_image_node = load_id
    for p in passes:
        note_id = str(next_id)
        nodes[note_id] = {
            "inputs": {"text": (
                f"PASS: {p.get('id','?')}\n"
                f"agent: {p.get('agent','?')}\n"
                f"engine: {p.get('engine','?')}\n"
                f"in: {p.get('in', [])}\n"
                f"out: {p.get('out','?')}\n"
                f"status: {p.get('status','?')}\n"
                f"model_path: {p.get('model_path','-')}"
            )},
            "class_type": "Note",
            "_meta": {"title": f"pass · {p.get('id','?')} · {p.get('agent','?')}"}
        }
        next_id += 1

    # Final PreviewImage so something renders
    nodes[str(next_id)] = {
        "inputs": {"images": [last_image_node, 0]},
        "class_type": "PreviewImage",
        "_meta": {"title": "PreviewImage"}
    }

    return json.dumps({
        "_meta": {
            "card_name": name,
            "card_crystal": card_crystal,
            "schema": "comfy_workflow_starter_v0",
        },
        **nodes,
    }, indent=2)


# ---------------------------------------------------------------------------
# Generate-all orchestrator
# ---------------------------------------------------------------------------

class WorkflowGenerator:
    def __init__(self, queue: Optional[TaskQueue] = None, dry_run: bool = False):
        self.queue = queue
        self.dry_run = dry_run

    async def generate_all(self, card: Dict, repo_root: Path = REPO_ROOT) -> List[GenResult]:
        card_crystal = compute_card_crystal(card)
        name = card.get("name", "untitled")
        surfaces = card.get("surfaces", {})

        # Invariant #3 — morph layer canonical-vocab enforcement (warnings only)
        issues = validate_card(card)
        if issues:
            sys.stderr.write(f"[workflow_generator] non-canonical layer_stack in '{name}':\n")
            for w in issues:
                sys.stderr.write(f"  warn: {w}\n")

        # Optional: nano text-gen for descriptions
        nano_doc = ""
        if self.queue is not None:
            try:
                nano = NanoDescriber(self.queue)
                intent = (
                    f"What does this workflow do? Name: {name}. "
                    f"Inputs: {[i.get('name') for i in card.get('inputs',[])]}. "
                    f"Outputs: {[o.get('name') for o in card.get('outputs',[])]}."
                )
                nano_doc = await nano.describe(intent, max_chars=180)
            except Exception:
                nano_doc = card.get("summary", "")[:180]
        else:
            nano_doc = card.get("summary", "")[:180]

        plan: List[tuple] = []  # (surface_name, out_path, content)

        # Streamlit
        if "streamlit" in surfaces:
            out = repo_root / surfaces["streamlit"].get("out_path", f"studio/web/streamlit/{name}.py")
            plan.append(("streamlit", out, gen_streamlit(card, card_crystal)))

        # Godot scene + script + native
        if "godot" in surfaces:
            g = surfaces["godot"]
            if g.get("out_scene"):
                plan.append(("godot_scene", repo_root / g["out_scene"], gen_godot_tscn(card, card_crystal)))
            if g.get("out_script"):
                plan.append(("godot_gd", repo_root / g["out_script"], gen_godot_gd(card, card_crystal, nano_doc)))
            if g.get("out_native") and g.get("language", "cpp") == "cpp":
                plan.append(("godot_cpp", repo_root / g["out_native"], gen_godot_cpp(card, card_crystal)))

        # Blender
        if "blender" in surfaces:
            out = repo_root / surfaces["blender"].get("out_path", f"studio/blender/scripts/{name}_bake.py")
            plan.append(("blender", out, gen_blender(card, card_crystal)))

        # --- BRIDGE NOTE (2026-05-29) -------------------------------------
        # A Jinja2 manifest template now exists at:
        #   studio/assets/_workflows/templates/pinterest_spriteforge_manifest.json.j2
        # It emits the newer SpriteForge manifest shape (top-level: name,
        # version, category, crystal_anchor, layers[], passes[],
        # inputs_schema[], outputs[], target_format, frame_grid, depends_on[]).
        #
        # MISMATCH: the dispatcher below writes <name>_sheet.json (legacy
        # spriteforge_manifest_v0 produced by gen_spriteforge) — the new
        # template writes <name>.manifest.json with the renamed/restructured
        # fields. A future refactor can switch this dispatcher to render the
        # Jinja template when surfaces.spriteforge.template_path is set;
        # leave dispatcher logic unchanged in this commit.
        # ------------------------------------------------------------------
        # SpriteForge
        if "spriteforge" in surfaces:
            out = repo_root / surfaces["spriteforge"].get("manifest_out",
                                                          f"studio/spriteforge/manifests/{name}_sheet.json")
            plan.append(("spriteforge", out, gen_spriteforge(card, card_crystal)))

        # ComfyUI
        if "comfyui" in surfaces:
            out_path = surfaces["comfyui"].get("out_path",
                                                str(COMFY_INSTALL / "user" / "workflows" / f"{name}.json"))
            out = Path(out_path)
            plan.append(("comfyui", out, gen_comfyui(card, card_crystal)))

        results: List[GenResult] = []
        for surface, out_path, content in plan:
            if self.dry_run:
                results.append(GenResult(surface=surface, out_path=out_path,
                                          bytes_written=0, card_crystal=card_crystal))
                continue
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(content, encoding="utf-8")
            results.append(GenResult(surface=surface, out_path=out_path,
                                      bytes_written=len(content), card_crystal=card_crystal))

        return results

    async def generate_one(self, card: Dict, target: str, repo_root: Path = REPO_ROOT) -> GenResult:
        card_crystal = compute_card_crystal(card)
        name = card.get("name", "untitled")
        surfaces = card.get("surfaces", {})

        generators = {
            "streamlit":  lambda: (gen_streamlit(card, card_crystal),
                                   surfaces.get("streamlit", {}).get("out_path", f"studio/web/streamlit/{name}.py")),
            "godot_scene":lambda: (gen_godot_tscn(card, card_crystal),
                                   surfaces.get("godot", {}).get("out_scene", f"studio/godot/project/scenes/{name}.tscn")),
            "godot_gd":   lambda: (gen_godot_gd(card, card_crystal, card.get("summary", "")[:180]),
                                   surfaces.get("godot", {}).get("out_script", f"studio/godot/project/src/{name}_controller.gd")),
            "godot_cpp":  lambda: (gen_godot_cpp(card, card_crystal),
                                   surfaces.get("godot", {}).get("out_native", f"studio/godot/project/cpp/src/{name}_native.cpp")),
            "blender":    lambda: (gen_blender(card, card_crystal),
                                   surfaces.get("blender", {}).get("out_path", f"studio/blender/scripts/{name}_bake.py")),
            "spriteforge":lambda: (gen_spriteforge(card, card_crystal),
                                   surfaces.get("spriteforge", {}).get("manifest_out", f"studio/spriteforge/manifests/{name}_sheet.json")),
            "comfyui":    lambda: (gen_comfyui(card, card_crystal),
                                   surfaces.get("comfyui", {}).get("out_path", str(COMFY_INSTALL / "user" / "workflows" / f"{name}.json"))),
        }
        if target not in generators:
            raise ValueError(f"unknown target: {target}. one of: {list(generators)}")
        content, rel = generators[target]()
        out = Path(rel)
        if not out.is_absolute():
            out = repo_root / rel
        if self.dry_run:
            return GenResult(surface=target, out_path=out, bytes_written=0, card_crystal=card_crystal)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding="utf-8")
        return GenResult(surface=target, out_path=out, bytes_written=len(content), card_crystal=card_crystal)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main():
    import argparse
    ap = argparse.ArgumentParser(description="workflow_generator — emit 5 surfaces from a card")
    sub = ap.add_subparsers(dest="cmd")

    p_gen = sub.add_parser("generate", help="generate one or all surfaces")
    p_gen.add_argument("card", help="path to workflow_card JSON")
    p_gen.add_argument("--target", default="all",
                       choices=["all","streamlit","godot_scene","godot_gd","godot_cpp",
                                "blender","spriteforge","comfyui"])
    p_gen.add_argument("--dry-run", action="store_true", help="show what would be written")
    p_gen.add_argument("--no-nano", action="store_true", help="skip the nano-text-gen description step")

    p_crystal = sub.add_parser("crystal", help="compute the card_crystal for a card")
    p_crystal.add_argument("card")

    args = ap.parse_args()

    if args.cmd == "crystal":
        card = load_card(args.card)
        print(compute_card_crystal(card))
        return

    if args.cmd != "generate":
        ap.print_help()
        return

    card = load_card(args.card)

    async def run():
        queue = None if args.no_nano else TaskQueue()
        if queue:
            await queue.start()
        try:
            gen = WorkflowGenerator(queue=queue, dry_run=args.dry_run)
            if args.target == "all":
                results = await gen.generate_all(card)
            else:
                r = await gen.generate_one(card, args.target)
                results = [r]
            out = {
                "card_name": card.get("name"),
                "card_crystal": results[0].card_crystal if results else "",
                "dry_run": args.dry_run,
                "generated": [
                    {"surface": r.surface, "path": str(r.out_path), "bytes": r.bytes_written}
                    for r in results
                ],
            }
            print(json.dumps(out, indent=2))
        finally:
            if queue:
                await queue.stop()

    asyncio.run(run())


if __name__ == "__main__":
    _main()
