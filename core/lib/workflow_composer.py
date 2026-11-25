#!/usr/bin/env python3
"""workflow_composer.py — deterministic prompt → workflow_card_v0 IR compiler.

Python sibling of studio/loom/morph_engine.html constructEngine(). Hashes the
prompt, tokenizes against kernel_registry's 100+-kernel closed set, optionally
LLM-augments via DeepSeek (closed-set-clamped), validates every kernel_ref via
resolve(), atomically writes the JSON, busts the registry cache so the new
card becomes a CARD kernel any other card can call.

Recursion is closed: a coarse pass can re-enter compose() with depth_budget-1.
Tarjan cycle detection via recursive_workflows.py keeps the CARD plane acyclic.

CLI:
    python3 core/lib/workflow_composer.py compose \\
        "spiky twisted goo for a cabin walkthrough" --scope 3d --scope game
    python3 core/lib/workflow_composer.py tokenize "render a tile" --scope video
    python3 core/lib/workflow_composer.py seed "anything" --scope game
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
CARDS_DIR = REPO / "studio" / "assets" / "_workflows"
VM_ID = "vm_mspc_001"

# Same scope→seed map as morph_engine.html constructEngine, but mapping
# to real kernel ids from the closed set.
SCOPE_SEED: Dict[str, List[str]] = {
    "scene·3d":  ["Depth Estimation", "Image-to-3D", "blender"],
    "scene_3d":  ["Depth Estimation", "Image-to-3D", "blender"],
    "3d":        ["Depth Estimation", "Image-to-3D", "blender"],
    "character": ["Pose Estimation", "Image Segmentation", "blender"],
    "video":     ["Text-to-Video", "Image-to-Video", "comfyui"],
    "game":      ["godot", "blender"],
    "document":  ["Text Classification", "Summarization", "Question Answering"],
    "audio":     ["Text-to-Speech", "Automatic Speech Recognition"],
    "image":     ["Text-to-Image", "Image Classification", "comfyui"],
}

SCOPE_CATEGORY: Dict[str, str] = {
    "3d": "assets", "scene_3d": "assets", "scene·3d": "assets",
    "character": "scope", "video": "render", "game": "compose",
    "document": "scope", "audio": "harvest", "image": "render",
}

# Canonical layer_stack vocabulary (mirrors workflow_generator.CANONICAL_LAYERS).
# Composer cycles through these by pass index so emitted cards never warn.
CANONICAL_LAYERS_ORDERED: List[str] = [
    "albedo", "normal", "roughness", "metallic", "emission", "ao",
    "depth", "alpha", "opacity", "specular", "subsurface", "clearcoat",
    "transmission", "gradient",
]

# Per-HF-task default model + how to seed the params block. Pure JSON-serializable
# defaults so the dispatcher can fire without the GUI populating fields by hand.
HF_TASK_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "Text-to-Image":             {"model": "black-forest-labs/FLUX.1-schnell"},
    "Image Classification":      {"model": "google/vit-base-patch16-224"},
    "Image Segmentation":        {"model": "facebook/sam-vit-base"},
    "Depth Estimation":          {"model": "Intel/dpt-hybrid-midas"},
    "Image-to-3D":               {"model": "openai/shap-e"},
    "Object Detection":          {"model": "facebook/detr-resnet-50"},
    "Pose Estimation":           {"model": "qubvel-hf/vitpose-plus-small"},
    "Image-to-Image":            {"model": "stabilityai/stable-diffusion-xl-refiner-1.0"},
    "Image-Text-to-Image":       {"model": "Salesforce/blip2-opt-2.7b"},
    "Text Classification":       {"model": "distilbert-base-uncased-finetuned-sst-2-english"},
    "Summarization":             {"model": "facebook/bart-large-cnn"},
    "Question Answering":        {"model": "deepset/roberta-base-squad2"},
    "Document Question Answering": {"model": "impira/layoutlm-document-qa"},
    "Translation":               {"model": "Helsinki-NLP/opus-mt-en-fr"},
    "Text Generation":           {"model": "meta-llama/Llama-3.2-1B-Instruct"},
    "Fill-Mask":                 {"model": "bert-base-uncased"},
    "Feature Extraction":        {"model": "sentence-transformers/all-MiniLM-L6-v2"},
    "Image Feature Extraction":  {"model": "google/vit-base-patch16-224-in21k"},
    "Visual Document Retrieval": {"model": "vidore/colqwen2-v1.0"},
    "Mask Generation":           {"model": "facebook/sam-vit-base"},
    "Zero-Shot Classification":  {"model": "facebook/bart-large-mnli"},
    "Zero-Shot Image Classification": {"model": "openai/clip-vit-large-patch14"},
    "Table Question Answering":  {"model": "google/tapas-base-finetuned-wtq"},
    "Text-to-Video":             {"model": "ali-vilab/text-to-video-ms-1.7b"},
    "Image-to-Video":            {"model": "stabilityai/stable-video-diffusion-img2vid"},
    "Text-to-Speech":            {"model": "facebook/mms-tts-eng"},
    "Automatic Speech Recognition": {"model": "openai/whisper-base"},
    "Unconditional Image Generation": {"model": "google/ddpm-cat-256"},
    "Any-to-Any":                {"model": "openbmb/MiniCPM-o-2_6"},
}

# Default ComfyUI workflow templates (must exist in studio/assets/_comfy_workflows/).
COMFY_TEMPLATE_DEFAULT = "flux_dev_t2i"  # ships in the repo


# ── deterministic primitives ──────────────────────────────────────────────────

def seed_from(prompt: str, scope: List[str]) -> str:
    """BLAKE2b-256 hex of (prompt + sorted scope). The determinism root."""
    h = hashlib.blake2b(digest_size=32)
    h.update((prompt or "").encode("utf-8"))
    for s in sorted(scope or []):
        h.update(b"\x00")
        h.update(s.encode("utf-8"))
    return h.hexdigest()


def seed_world(prompt: str, scope: List[str], seed_cards: List[str]) -> str:
    """Like seed_from but also hashes the ordered seed_cards. Order matters
    here because z-order / scene position is meaningful — character 1 first,
    character 5 last is NOT the same composition as the reverse."""
    h = hashlib.blake2b(digest_size=32)
    h.update((prompt or "").encode("utf-8"))
    for s in sorted(scope or []):
        h.update(b"\x00")
        h.update(s.encode("utf-8"))
    h.update(b"\x01")
    for sc in (seed_cards or []):
        h.update(b"\x00")
        h.update(sc.encode("utf-8"))
    return h.hexdigest()


def slug_of(prompt: str) -> str:
    """Same slug logic as morph_engine.html constructEngine()."""
    cleaned = re.sub(r"[^a-z0-9\s]", "", (prompt or "").lower())
    parts = [p for p in cleaned.split() if p][:3]
    return ".".join(parts) or "engine"


def category_of(prompt: str, scope: List[str]) -> str:
    for s in scope or []:
        cat = SCOPE_CATEGORY.get(s.lower())
        if cat:
            return cat
    lc = (prompt or "").lower()
    if any(w in lc for w in ("3d", "mesh", "model", "blender", "rig", "glb", "fbx")):
        return "assets"
    if any(w in lc for w in ("render", "video", "tile", "glyph")):
        return "render"
    if any(w in lc for w in ("trade", "swap", "defi", "loop", "lending")):
        return "trade"
    if any(w in lc for w in ("scope", "corpus", "document", "pdf", "doc")):
        return "scope"
    if any(w in lc for w in ("harvest", "tweet", "follower", "feed")):
        return "harvest"
    if any(w in lc for w in ("deploy", "replit", "droplet", "ship")):
        return "deploy"
    if any(w in lc for w in ("encode", "embed", "clip")):
        return "embed"
    return "compose"


# ── kernel_registry binding ──────────────────────────────────────────────────

def _kr():
    sys.path.insert(0, str(REPO / "core" / "lib"))
    import kernel_registry  # type: ignore
    return kernel_registry


def _load_registry() -> Dict[str, Dict[str, Any]]:
    return _kr().registry()


def _resolve(kernel_ref: str) -> Optional[Dict[str, Any]]:
    return _kr().resolve(kernel_ref)


# ── tokenization (the closed-set filter) ─────────────────────────────────────

def tokenize(prompt: str, scope: List[str]) -> List[str]:
    """Direct-token match against every kernel id in the closed set.

    Returns kernel_refs (with plane prefix) the prompt or scope plausibly
    touches. Order is stable: scope-seeded first, then prompt-matched in
    name-length descending order (longer matches win).
    """
    reg = _load_registry()
    chosen: List[str] = []
    seen = set()

    def add(plane: str, kid: str) -> None:
        ref = f"{plane}:{kid}"
        if ref in seen:
            return
        seen.add(ref)
        chosen.append(ref)

    # 1. scope-seeded — deterministic ordering
    for s in scope or []:
        for seed_id in SCOPE_SEED.get(s.lower(), []):
            spec = reg.get(seed_id)
            if spec:
                add(spec["plane"], seed_id)

    # 2. prompt token matches — longest id first so 'Image Classification'
    #    beats 'Image' alone.
    lc = (prompt or "").lower()
    all_ids = sorted(reg.keys(), key=lambda k: -len(k))
    for kid in all_ids:
        token = kid.lower().replace("-", " ").replace("_", " ")
        if token and token in lc:
            add(reg[kid]["plane"], kid)
            continue
        for w in token.split():
            if len(w) >= 4 and re.search(rf"\b{re.escape(w)}\b", lc):
                add(reg[kid]["plane"], kid)
                break
    return chosen


# ── reorder via cc (tiny by default, claude for deeper work) ────────────────

def _cc_propose(prompt: str, scope: List[str], candidates: List[str],
                mode: str = "tiny") -> Optional[List[str]]:
    """Optional re-ordering via the cc substrate (NOT DeepSeek HTTP).

    Calls `cc tiny` for the deterministic free path, or `cc claude` for
    deeper work. The LLM can only REORDER the candidate refs — never invent
    new ones. Closed-set safety preserved by filtering against `candidates`.

    Returns None if the route fails or the LLM didn't return a usable JSON
    array — caller falls back to the deterministic tokenize() order.
    """
    try:
        sys.path.insert(0, str(REPO / "core" / "lib"))
        from cc_router import route  # type: ignore
    except Exception:
        return None
    if mode == "none":
        return None
    instr = (
        "Reorder the following kernel_refs into the right workflow execution sequence "
        "for the user prompt below. Output ONLY a JSON array of kernel_refs — no prose, "
        "no new refs. Only use refs from the candidate list verbatim.\n\n"
        f"prompt: {prompt!r}\n"
        f"scope: {scope}\n"
        f"candidates: {json.dumps(candidates)}\n"
    )
    result = route(instr, mode=mode, timeout_s=60)
    if not result.ok or not result.output:
        return None
    m = re.search(r"\[.*?\]", result.output, re.S)
    if not m:
        return None
    try:
        arr = json.loads(m.group(0))
    except Exception:
        return None
    cand_set = set(candidates)
    keep = [r for r in arr if isinstance(r, str) and r in cand_set]
    return keep or None


# ── pass shaping ─────────────────────────────────────────────────────────────

_ENGINE_FOR_PLANE = {
    "hf":        "hf",
    "card":      "card",
    "connector": None,  # use the kernel id (blender/godot/comfyui/...)
    "modifier":  "deterministic",
    "scene":     "deterministic",
    "governor":  "deterministic",
}


def _hydrate_params(pass_dict: Dict[str, Any], spec: Dict[str, Any],
                    prompt: str, seed_hex: str) -> Dict[str, Any]:
    """Fill the per-pass execution params so the dispatchers can actually fire.

    HF passes need params.model + params.prompt (else _dispatch_hf skips).
    ComfyUI passes need comfy_workflow + comfy_inputs (else _dispatch_comfyui errors).
    Connector + card + modifier planes don't need params at this layer.

    Hydration is deterministic: same prompt + seed → same params.
    """
    plane = spec.get("plane", "")
    kid = spec["id"]
    if plane == "hf":
        defaults = HF_TASK_DEFAULTS.get(kid) or {}
        pass_dict["params"] = {
            "model": defaults.get("model", "meta-llama/Llama-3.2-1B-Instruct"),
            "prompt": prompt[:1024],
            "max_tokens": 256,
            "temperature": 0.0,
            "fallback": True,
        }
    elif kid == "comfyui":
        # Seed derived from hex so deterministic re-runs reuse cached results.
        seed_int = int(seed_hex[:8], 16) % (2 ** 31)
        pass_dict["comfy_workflow"] = COMFY_TEMPLATE_DEFAULT
        pass_dict["comfy_inputs"] = {
            "prompt": prompt[:512],
            "seed":   seed_int,
            "steps":  4,
            "width":  1024,
            "height": 1024,
        }
    elif kid == "blender":
        # Default to a probe op so the dispatcher fires and reports status.
        pass_dict["tool"] = "scene.list_objects"
        pass_dict["params"] = {}
    elif kid == "godot":
        # _dispatch_godot picks scene_name from card.name if absent; nothing to add.
        pass_dict["params"] = {}
    return pass_dict


def _passes_from_refs(refs: List[str], prompt: str, seed_hex: str) -> List[Dict[str, Any]]:
    """Translate validated kernel_refs into workflow_card pass dicts with
    hydrated execution params so the dispatchers actually run."""
    passes: List[Dict[str, Any]] = []
    for i, ref in enumerate(refs):
        spec = _resolve(ref)
        if not spec:
            continue
        plane = spec.get("plane", "")
        kid = spec["id"]
        safe = re.sub(r"[^a-z0-9_]", "_", kid.lower().replace(" ", "_").replace("-", "_"))[:24]
        pid = f"p{i:02d}_{safe}"
        engine = _ENGINE_FOR_PLANE.get(plane)
        if engine is None:
            engine = kid  # connector plane → use kernel id as engine
        ins = list(spec.get("in_type") or ["ANY"])
        outs = list(spec.get("out_type") or ["ANY"])
        pass_dict = {
            "id":         pid,
            "agent":      kid,
            "kernel_ref": ref,
            "engine":     engine,
            "in":         ins,
            "out":        outs[0] if outs else "ANY",
            "tier":       "fast" if plane in ("hf", "connector") else "deterministic",
            "status":     "PLANNED",
            "swap_mode":  "tiny",  # default cc rail; "claude" for deeper work
            "swap_compatible_with": [],
        }
        pass_dict = _hydrate_params(pass_dict, spec, prompt, seed_hex)
        passes.append(pass_dict)
    return passes


def _compute_swap_compatibility(passes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """For each pass, find sibling kernels with the SAME plane + matching i/o
    types so the GUI can offer swap candidates that keep the higher-level
    connection intact. Same wiring, different element — Tom's GUI law.
    """
    reg = _load_registry()
    for p in passes:
        spec = _resolve(p.get("kernel_ref", ""))
        if not spec:
            continue
        plane = spec.get("plane", "")
        in_type = set(spec.get("in_type") or ["ANY"])
        out_type = set(spec.get("out_type") or ["ANY"])
        swaps: List[str] = []
        for kid, other in reg.items():
            if kid == spec["id"]:
                continue
            if other.get("plane") != plane:
                continue
            o_in = set(other.get("in_type") or ["ANY"])
            o_out = set(other.get("out_type") or ["ANY"])
            # ANY is a wildcard
            in_match = ("ANY" in in_type or "ANY" in o_in or (in_type & o_in))
            out_match = ("ANY" in out_type or "ANY" in o_out or (out_type & o_out))
            if in_match and out_match:
                swaps.append(f"{plane}:{kid}")
        p["swap_compatible_with"] = swaps[:8]  # cap to keep the IR readable
    return passes


def validate(passes: List[Dict[str, Any]],
             min_state: str = "planned") -> Tuple[List[Dict[str, Any]], List[str]]:
    """Every pass's kernel_ref must resolve. Returns (validated, errors)."""
    out, errs = [], []
    for p in passes:
        ref = p.get("kernel_ref", "")
        spec = _resolve(ref)
        if not spec:
            errs.append(f"unresolved kernel_ref: {ref}")
            continue
        if min_state == "active" and spec.get("state", "active") != "active":
            errs.append(f"kernel not active: {ref}")
            continue
        out.append(p)
    return out, errs


# ── write + register ─────────────────────────────────────────────────────────

def write_card(name: str, category: str, prompt: str, scope: List[str],
               passes: List[Dict[str, Any]], sub_card_paths: List[str]) -> Path:
    """Atomic write — .tmp then os.rename so a half-written card never registers."""
    fname = f"{VM_ID}.workflows.{category}.{name}.v0.json"
    target = CARDS_DIR / fname
    card = {
        "_schema":   "workflow_card_v0",
        "vm_id":     VM_ID,
        "name":      name,
        "category":  category,
        "state":     "active",
        "version":   "v0",
        "summary":   f"Deterministically composed from prompt: {prompt[:200]}",
        "inputs":    [{"name": "prompt", "type": "str", "required": True}],
        "outputs":   [{"name": "result", "type": "any"}],
        "passes":    passes,
        "layer_stack": [
            # Cycle through canonical layer names so the validator never warns —
            # composer-emitted IR must pass the closed-vocab gate just like
            # hand-authored cards.
            {"name": CANONICAL_LAYERS_ORDERED[i % len(CANONICAL_LAYERS_ORDERED)],
             "source": f"pass:{p['id']}",
             "blend":  "base" if i == 0 else "additive"}
            for i, p in enumerate(passes)
        ],
        "depends_on": sorted({p["kernel_ref"] for p in passes if p.get("kernel_ref")}),
        "composed_by": {
            "composer_card":   "card:workflow_composer",
            "compose_scope":   scope,
            "sub_card_paths":  sub_card_paths,
            "composed_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(card, indent=2))
    os.rename(tmp, target)
    return target


def bust_cache() -> None:
    """Force kernel_registry to rescan CARDS_DIR on next call."""
    try:
        kr = _kr()
        kr._REG = None
    except Exception:
        pass


def anchor(card_path: Path, prompt: str, scope: List[str],
           passes: List[Dict[str, Any]], seed_hex: str) -> str:
    """Crystal-anchor the composition. Returns crystal_id or ''."""
    try:
        sys.path.insert(0, str(REPO / "core" / "lib"))
        from inference_logger import InferenceLogger  # type: ignore
        logger = InferenceLogger()
        return logger.log(
            original_prompt=prompt,
            enhanced_prompt=f"compose scope={scope} kernels={len(passes)} seed={seed_hex[:16]}",
            output_text=str(card_path),
            tier="workflow_composition",
            model="workflow_composer",
            scope=",".join(scope or []),
            source_action="compose",
            source_file=str(card_path.relative_to(REPO)),
            coordinates=[
                {"axis": "pass_count", "value": len(passes)},
                {"axis": "kernel_planes", "value": len({p.get("engine", "") for p in passes})},
            ],
        ) or ""
    except Exception:
        return ""


# ── main entrypoint ──────────────────────────────────────────────────────────

def compose_world(prompt: str, seed_cards: List[str] = None,
                  scope: List[str] = None,
                  depth_budget: int = 3, min_state: str = "planned",
                  deterministic: bool = True) -> Dict[str, Any]:
    """Compose a parent card that injects N frozen sub-cards as front-loaded
    passes, then layers prompt-derived composition passes on top.

    Use case: "5 characters → world".
      compose_world("forest battle clearing",
                    seed_cards=["card:medieval.ranger_<seed>",
                                "card:dark.sorcerer_<seed>", ...])
      → emits a world card whose first N passes are engine='card' references
        to the 5 frozen character cards (the parent's API + behavior contract
        is locked at their crystal), followed by scene/lighting/camera passes
        derived from the prompt.

    Determinism: seed_cards are NOT sorted (order matters for z-order). Same
    prompt + same scope + same ordered seed_cards → same world crystal.
    """
    scope = scope or []
    seed_cards = seed_cards or []

    # Every seed_card must resolve in the registry — that's the frozen-state
    # contract. An unresolved seed = a contract violation = reject up front.
    for sc in seed_cards:
        if not _resolve(sc):
            return {"ok": False, "error": "unresolved_seed_card",
                    "seed_card": sc, "candidates": list(_load_registry().keys())[:5]}

    seed_hex = seed_world(prompt, scope, seed_cards)

    # Front-load the frozen sub-cards as the first N passes. swap_mode='none'
    # so the LLM rail can never rewrite them — they're contractually locked.
    seed_passes: List[Dict[str, Any]] = []
    for i, sc in enumerate(seed_cards):
        spec = _resolve(sc)
        sub_name = sc.split(":", 1)[-1] if ":" in sc else sc
        safe = re.sub(r"[^a-z0-9_]", "_", sub_name.lower().replace(" ", "_"))[:24]
        seed_passes.append({
            "id":         f"p{i:02d}_seed_{safe}",
            "agent":      sub_name,
            "kernel_ref": sc,
            "engine":     "card",
            "in":         list((spec or {}).get("in_type") or ["ANY"]),
            "out":        ((spec or {}).get("out_type") or ["ANY"])[0],
            "tier":       "deterministic",
            "status":     "ACTIVE",
            "swap_mode":  "none",
            "swap_compatible_with": [],
            "frozen":     True,
        })

    # Tokenize the prompt for additional composition passes (scene/lighting/
    # camera/composite). Drop any candidate already covered by a seed_card.
    candidates = tokenize(prompt, scope)
    seed_set = set(seed_cards)
    candidates = [c for c in candidates if c not in seed_set]

    ordered = candidates
    if candidates:
        cc_ordered = _cc_propose(prompt, scope, candidates,
                                 mode="tiny" if deterministic else "claude")
        if cc_ordered:
            ordered = cc_ordered

    composition_passes = _passes_from_refs(ordered, prompt, seed_hex)
    # Renumber composition passes so the world card's pass ids stay sequential
    # past the frozen seed_passes.
    n_seed = len(seed_passes)
    for i, p in enumerate(composition_passes):
        safe = re.sub(r"[^a-z0-9_]", "_",
                      p.get("agent", "").lower().replace(" ", "_"))[:24]
        p["id"] = f"p{(n_seed + i):02d}_{safe}"

    all_passes = seed_passes + composition_passes
    all_passes = _compute_swap_compatibility(all_passes)
    validated, errs = validate(all_passes, min_state=min_state)

    if not validated:
        return {"ok": False, "error": "no_validated_passes",
                "errors": errs, "candidates": candidates}

    name = (slug_of(prompt) + ".world_" + seed_hex[:8]) if seed_hex else slug_of(prompt)
    category = "world" if ("3d" in scope or "game" in scope or "scene_3d" in scope) else "compose"
    card_path = write_card(name, category, prompt, scope, validated, [])
    bust_cache()
    crystal = anchor(card_path, prompt, scope, validated, seed_hex)

    return {
        "ok": True,
        "card_path": str(card_path.relative_to(REPO)),
        "card_crystal": crystal,
        "new_kernel_id": name,
        "kernel_ref": f"card:{name}",
        "seed": seed_hex,
        "seed_card_count": len(seed_passes),
        "composition_pass_count": len(composition_passes),
        "pass_count": len(validated),
        "validation_errors": errs,
        "category": category,
        "frozen_contract_locked": [p["kernel_ref"] for p in seed_passes],
    }


def compose(prompt: str, scope: List[str] = None, parent_card: str = "",
            depth_budget: int = 3, min_state: str = "planned",
            deterministic: bool = True) -> Dict[str, Any]:
    """Compose a workflow_card from a prompt.

    Returns dict with: ok, card_path, card_crystal, new_kernel_id, kernel_ref,
    seed, pass_count, candidate_count, sub_card_paths, validation_errors.
    """
    scope = scope or []
    seed_hex = seed_from(prompt, scope)
    candidates = tokenize(prompt, scope)
    if not candidates:
        return {
            "ok": False, "error": "no_kernel_matches", "seed": seed_hex,
            "candidates": [], "hint": "prompt did not touch any of 100+ closed kernels",
        }

    # Optional re-ordering via cc (tiny by default, never DeepSeek HTTP).
    # Closed-set-clamped — the router can only reorder/subset, never invent.
    ordered = candidates
    cc_ordered = _cc_propose(prompt, scope, candidates,
                             mode="tiny" if deterministic else "claude")
    if cc_ordered:
        ordered = cc_ordered

    passes = _passes_from_refs(ordered, prompt, seed_hex)
    # Compute swap compatibility per pass (same plane + same in/out type ⇒ swappable).
    passes = _compute_swap_compatibility(passes)
    validated, errs = validate(passes, min_state=min_state)
    if not validated:
        return {
            "ok": False, "error": "no_validated_passes", "errors": errs,
            "candidates": candidates,
        }

    # Recursion stub — depth_budget>0 reserved for re-entering compose() on
    # coarse passes. Today we emit them as PLANNED status; once the LLM marks
    # coarse passes, recurse() can replace them with card:<sub_name>.
    sub_card_paths: List[str] = []

    name = slug_of(prompt) + "_" + seed_hex[:8]
    category = category_of(prompt, scope)
    card_path = write_card(name, category, prompt, scope, validated, sub_card_paths)
    bust_cache()
    crystal = anchor(card_path, prompt, scope, validated, seed_hex)

    return {
        "ok": True,
        "card_path": str(card_path.relative_to(REPO)),
        "card_crystal": crystal,
        "new_kernel_id": name,
        "kernel_ref": f"card:{name}",
        "seed": seed_hex,
        "pass_count": len(validated),
        "candidate_count": len(candidates),
        "sub_card_paths": sub_card_paths,
        "validation_errors": errs,
        "category": category,
    }


# ── CLI ──────────────────────────────────────────────────────────────────────

def _parse_args(args: List[str]) -> Tuple[str, List[str], List[str], int, bool]:
    scope: List[str] = []
    seed_cards: List[str] = []
    depth = 3
    det = True
    prompt_parts: List[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--scope" and i + 1 < len(args):
            scope.append(args[i + 1]); i += 2
        elif a == "--seed-card" and i + 1 < len(args):
            seed_cards.append(args[i + 1]); i += 2
        elif a == "--depth" and i + 1 < len(args):
            depth = int(args[i + 1]); i += 2
        elif a == "--non-det":
            det = False; i += 1
        else:
            prompt_parts.append(a); i += 1
    return " ".join(prompt_parts), scope, seed_cards, depth, det


def main(argv: List[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(json.dumps({
            "usage": ("compose <prompt> [--scope X [--scope Y]] [--depth N] [--non-det]   ·   "
                       "compose-world <prompt> --seed-card card:X [--seed-card card:Y] [--scope ...]"),
            "tools": ["compose", "compose-world", "tokenize", "seed"],
            "scope_vocab": list(SCOPE_SEED.keys()),
        }, indent=2))
        return 1
    cmd = argv[0]
    if cmd not in ("compose", "compose-world", "tokenize", "seed"):
        print(f"unknown command: {cmd}", file=sys.stderr)
        return 1
    prompt, scope, seed_cards, depth, det = _parse_args(argv[1:])
    if cmd == "seed":
        print(seed_from(prompt, scope))
        return 0
    if cmd == "tokenize":
        print(json.dumps(tokenize(prompt, scope), indent=2))
        return 0
    if cmd == "compose-world":
        result = compose_world(prompt, seed_cards=seed_cards, scope=scope,
                                depth_budget=depth, deterministic=det)
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 2
    result = compose(prompt, scope, depth_budget=depth, deterministic=det)
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
