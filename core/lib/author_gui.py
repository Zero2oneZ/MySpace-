#!/usr/bin/env python3
"""author_gui.py — drafts per-opcode GUI widget specs via tiny-model chain.

Reads the existing capability_card[opcode] (drafted by author_cards.py)
and turns each user_param into a concrete UI widget. Output is a
gui_card with three sections:

  inputs[]    — one widget per opcode input modality + each user_param
  outputs[]   — one widget per output modality + downloads/preview
  meta        — layout_hint, estimated_runtime_s, hitl-likely flag

This card is what the Phase-3 Gradio/Streamlit frontends will consume
to render the right widgets for each step of a workflow.

Strategy is HYBRID: a deterministic "modality → default widget"
baseline that always works, AUGMENTED with tiny-model suggestions for
widget choice on user_params (slider vs dropdown vs text_input).
If the tiny model fails or returns garbage, the baseline still gives
us a usable card.

Widget vocabulary (10 widgets):
  text_input         single-line text
  text_input_multi   multi-line text (prompts, paragraphs)
  file_upload        file picker, typed by accept= attribute
  audio_recorder     in-browser mic
  video_recorder     in-browser camera
  slider             numeric range
  number_input       free numeric
  dropdown           categorical options
  toggle             boolean
  output_preview     polymorphic — renders image/audio/video/text/3d

Usage:
  author_gui.py <opcode>                  # one opcode
  author_gui.py --all                     # every opcode that has a capability card
  author_gui.py --missing                 # only opcodes without a gui card
  author_gui.py --baseline-only OP        # skip model call, deterministic widgets only
  author_gui.py --dry OP                  # print prompts only
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

HERE = Path(__file__).resolve().parent
CC_BIN = os.environ.get("CC_BIN") or "cc"
DB_BIN = HERE / "db.py"


# ---- modality → default widget mapping (the deterministic baseline) ----

MODALITY_INPUT_WIDGETS: dict[str, dict] = {
    "TEXT":         {"widget": "text_input_multi",
                     "props": {"placeholder": "Enter text", "rows": 4}},
    "IMAGE":        {"widget": "file_upload",
                     "props": {"accept": "image/*"}},
    "AUDIO":        {"widget": "file_upload",
                     "props": {"accept": "audio/*",
                               "alt_widget": "audio_recorder"}},
    "VIDEO":        {"widget": "file_upload",
                     "props": {"accept": "video/*",
                               "alt_widget": "video_recorder"}},
    "DOC":          {"widget": "file_upload",
                     "props": {"accept": ".pdf,.docx,.txt,.md"}},
    "3D":           {"widget": "file_upload",
                     "props": {"accept": ".glb,.obj,.ply,.stl"}},
    "TABULAR":      {"widget": "file_upload",
                     "props": {"accept": ".csv,.tsv,.xlsx,.parquet"}},
    "GRAPH":        {"widget": "file_upload",
                     "props": {"accept": ".graphml,.gexf,.json"}},
    "TIMESERIES":   {"widget": "file_upload",
                     "props": {"accept": ".csv,.parquet"}},
    "LABELS":       {"widget": "text_input",
                     "props": {"placeholder": "Comma-separated labels"}},
    "EMBEDDING":    {"widget": "file_upload",
                     "props": {"accept": ".npy,.bin"}},
    "STATE":        {"widget": "text_input_multi",
                     "props": {"placeholder": "Environment state JSON"}},
}

# Output modality → preview widget. All use the polymorphic
# `output_preview` widget; only the `kind` prop changes.
MODALITY_OUTPUT_WIDGETS: dict[str, dict] = {
    "TEXT":         {"widget": "output_preview", "props": {"kind": "text"}},
    "IMAGE":        {"widget": "output_preview", "props": {"kind": "image",
                     "downloadable": True}},
    "AUDIO":        {"widget": "output_preview", "props": {"kind": "audio",
                     "downloadable": True}},
    "VIDEO":        {"widget": "output_preview", "props": {"kind": "video",
                     "downloadable": True}},
    "3D":           {"widget": "output_preview", "props": {"kind": "3d_viewer",
                     "downloadable": True}},
    "DOC":          {"widget": "output_preview", "props": {"kind": "doc"}},
    "MASK":         {"widget": "output_preview", "props": {"kind": "mask"}},
    "BOXES":        {"widget": "output_preview", "props": {"kind": "boxes_overlay"}},
    "KEYPOINTS":    {"widget": "output_preview", "props": {"kind": "keypoints_overlay"}},
    "DEPTH_MAP":    {"widget": "output_preview", "props": {"kind": "heatmap"}},
    "LABEL":        {"widget": "output_preview", "props": {"kind": "label"}},
    "LABEL_SEQ":    {"widget": "output_preview", "props": {"kind": "label_seq"}},
    "SCALAR":       {"widget": "output_preview", "props": {"kind": "scalar"}},
    "TIMESERIES":   {"widget": "output_preview", "props": {"kind": "chart"}},
    "EMBEDDING":    {"widget": "output_preview", "props": {"kind": "vector"}},
    "GRAPH":        {"widget": "output_preview", "props": {"kind": "graph"}},
    "ACTION":       {"widget": "output_preview", "props": {"kind": "action"}},
    "TABULAR":      {"widget": "output_preview", "props": {"kind": "table"}},
}


# ---- taxonomy + capability card IO -------------------------------------

def _find_taxonomy() -> Path:
    candidates = [
        HERE / "hf_task_evolution.jsonl",
        HERE.parent.parent / "planning" / "hf_task_evolution.jsonl",
        HERE.parent / "planning" / "hf_task_evolution.jsonl",
    ]
    env = os.environ.get("CC_TAXONOMY")
    if env:
        candidates.insert(0, Path(env))
    for c in candidates:
        if c.is_file():
            return c
    return candidates[0]


def load_taxonomy(path: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        rows[r["task"]] = r
    return rows


def load_capability_card(opcode: str) -> Optional[dict]:
    db_path = (os.environ.get("CC_DB")
               or os.environ.get("CC_GLOBAL_DB")
               or str(Path.home() / ".cc" / "cc.db"))
    import sqlite3
    c = sqlite3.connect(db_path)
    try:
        r = c.execute(
            "SELECT card_json FROM capability_cards WHERE opcode=?",
            (opcode,),
        ).fetchone()
    finally:
        c.close()
    if not r:
        return None
    try:
        return json.loads(r[0])
    except json.JSONDecodeError:
        return None


# ---- deterministic baseline --------------------------------------------

def build_baseline_card(opcode_row: dict, cap_card: Optional[dict]) -> dict:
    """Compose a usable gui_card from modalities alone. Always works,
    even without a capability card and without the tiny model."""
    op = opcode_row["task"]
    ins = opcode_row.get("inputs", []) or []
    outs = opcode_row.get("outputs", []) or []

    inputs: list[dict] = []

    # Map user_params → modality coverage so we know which modality
    # slots are already accounted for by named params.
    user_params: list[dict] = []
    if cap_card and isinstance(cap_card.get("user_params"), list):
        user_params = [p for p in cap_card["user_params"]
                       if isinstance(p, dict) and p.get("name")]

    def _param_covers_modality(p: dict, mod: str) -> bool:
        name = (p.get("name") or "").lower()
        ptype = (p.get("type") or "").lower()
        # Generic: if the param's name is literally `input_<modality>`
        # the tiny model meant for it to be the modality slot.
        if name == f"input_{mod.lower()}":
            return True
        if mod == "TEXT" and ptype in ("string", "str", "text"):
            return name in ("text", "prompt", "input", "input_text",
                            "instruction", "query", "message", "description")
        if mod == "IMAGE" and any(k in name for k in ("image", "img", "photo")):
            return True
        if mod == "AUDIO" and any(k in name for k in ("audio", "voice", "sound")):
            return True
        if mod == "VIDEO" and any(k in name for k in ("video", "clip")):
            return True
        if mod == "DOC" and any(k in name for k in ("doc", "pdf", "file")):
            return True
        if mod == "TIMESERIES" and any(k in name for k in
                                       ("timeseries", "series", "ts_")):
            return True
        if mod == "TABULAR" and any(k in name for k in
                                     ("tabular", "table", "csv", "df")):
            return True
        if mod == "GRAPH" and any(k in name for k in ("graph", "node", "edge")):
            return True
        if mod == "EMBEDDING" and any(k in name for k in
                                       ("embedding", "vector", "embed")):
            return True
        if mod == "STATE" and "state" in name:
            return True
        return False

    param_modalities: set[str] = set()
    for mod in ins:
        if any(_param_covers_modality(p, mod) for p in user_params):
            param_modalities.add(mod)

    # 1) Add modality-slot widgets ONLY for modalities NOT covered by a
    #    named user_param. Avoids duplicating TEXT inputs when the
    #    capability card already named a "prompt" param.
    seen_slots: set[str] = set()
    for mod in ins:
        if mod in seen_slots or mod in param_modalities:
            continue
        seen_slots.add(mod)
        if mod == "LABELS":
            continue
        if mod in MODALITY_INPUT_WIDGETS:
            spec = MODALITY_INPUT_WIDGETS[mod]
            inputs.append({
                "widget": spec["widget"],
                "name": f"input_{mod.lower()}",
                "props": dict(spec["props"]),
                "required": True,
                "modality_slot": mod,
            })

    # 2) Add a widget per user_param from the capability card.
    for p in user_params:
        pname = p["name"]
        # Skip params that the model labelled as outputs (the tiny model
        # sometimes puts "output_video", "result_image" into user_params
        # even though those belong on the output side).
        if pname.lower().startswith(("output_", "result_", "out_")):
            continue
        ptype = (p.get("type") or "string").lower()
        # If the param name implies a FILE modality, use file_upload with
        # the right `accept` filter instead of a string widget.
        covered_mod = None
        for mod in ("IMAGE", "AUDIO", "VIDEO", "DOC"):
            if _param_covers_modality(p, mod):
                covered_mod = mod
                break
        if covered_mod and covered_mod in MODALITY_INPUT_WIDGETS:
            spec = MODALITY_INPUT_WIDGETS[covered_mod]
            inputs.append({
                "widget": spec["widget"],
                "name": pname,
                "props": dict(spec["props"]),
                "required": bool(p.get("required", False)),
                "modality_slot": covered_mod,
                "description": p.get("description", ""),
            })
            continue
        widget = _baseline_widget_for_type(ptype, p)
        inputs.append({
            "widget": widget["widget"],
            "name": pname,
            "props": widget["props"],
            "required": bool(p.get("required", False)),
            "description": p.get("description", ""),
        })

    outputs: list[dict] = []
    for mod in outs:
        if mod in MODALITY_OUTPUT_WIDGETS:
            spec = MODALITY_OUTPUT_WIDGETS[mod]
            outputs.append({
                "widget": spec["widget"],
                "props": dict(spec["props"]),
                "modality": mod,
            })

    return {
        "opcode": op,
        "drafted_by": "baseline",
        "inputs": inputs,
        "outputs": outputs,
        "meta": {
            "layout_hint": "two-column" if len(inputs) > 2 else "single-column",
            "estimated_runtime_s": _estimated_runtime(opcode_row),
            "hitl_likely": (opcode_row.get("layer") or 0) >= 4 or
                           "VIDEO" in outs or "3D" in outs,
        },
    }


def _baseline_widget_for_type(ptype: str, param: dict) -> dict:
    """Map a capability-card param type to a default widget+props."""
    ptype = ptype.lower()
    desc = (param.get("description") or "").lower()
    name = (param.get("name") or "").lower()

    if ptype in ("bool", "boolean"):
        return {"widget": "toggle", "props": {"default": False}}
    if ptype in ("int", "integer", "number"):
        # Heuristic: if "seed" / "id" / "count" → number_input; else slider
        if any(k in name for k in ("seed", "id", "count", "max", "min")):
            return {"widget": "number_input", "props": {}}
        return {"widget": "slider", "props": {}}
    if ptype in ("float", "double", "decimal"):
        return {"widget": "slider", "props": {"step": 0.1}}
    if ptype in ("enum", "choice"):
        opts = param.get("options") or param.get("choices") or []
        return {"widget": "dropdown", "props": {"options": opts}}
    if ptype == "string":
        # Long-form heuristic: name/desc mentions "prompt" / "description"
        # / "text" → multi-line.
        is_long = any(k in name for k in ("prompt", "description", "context"))
        is_long = is_long or "describ" in desc or "explain" in desc
        if is_long:
            return {"widget": "text_input_multi",
                    "props": {"placeholder": param.get("description", ""),
                              "rows": 3}}
        return {"widget": "text_input",
                "props": {"placeholder": param.get("description", "")}}
    # Fallback
    return {"widget": "text_input",
            "props": {"placeholder": param.get("description", "")}}


def _estimated_runtime(opcode_row: dict) -> int:
    """Crude heuristic by modality + layer for the meta.estimated_runtime_s.
    The Phase-3 frontend uses this to show a progress hint."""
    outs = opcode_row.get("outputs", []) or []
    layer = opcode_row.get("layer") or 1
    if "VIDEO" in outs:
        return 60
    if "3D" in outs:
        return 30
    if "IMAGE" in outs:
        return 8
    if "AUDIO" in outs:
        return 5
    return max(2, 2 + layer)


# ---- tiny-model enrichment ---------------------------------------------

def _refine_prompt(opcode_row: dict, cap_card: Optional[dict],
                   baseline: dict) -> str:
    """One prompt that asks the tiny model to either refine the
    baseline's widget choices OR confirm them. We don't ask it to
    re-emit the whole card — just say what to change."""
    op = opcode_row["task"]
    n_in = len(baseline["inputs"])
    summary = [
        {"name": i["name"], "widget": i["widget"],
         "type_hint": (cap_card or {}).get("user_params") and
                      next((p.get("type") for p in cap_card["user_params"]
                            if p.get("name") == i["name"]), None)}
        for i in baseline["inputs"]
    ]
    cap_params = []
    if cap_card and isinstance(cap_card.get("user_params"), list):
        cap_params = [{"name": p.get("name"), "type": p.get("type"),
                       "desc": p.get("description")}
                      for p in cap_card["user_params"]
                      if isinstance(p, dict)]
    return (
        f"Opcode: {op}\n"
        f"Current widgets: {json.dumps(summary)}\n"
        f"User params: {json.dumps(cap_params)}\n"
        "\n"
        "Widget vocabulary: text_input, text_input_multi, file_upload, "
        "audio_recorder, video_recorder, slider, number_input, dropdown, toggle.\n"
        "\n"
        "Suggest improvements to widget choices for the input fields ONLY. "
        "Reply with ONLY a compact JSON array of "
        '{"name":<str>,"widget":<str>,"reason":<str>}'
        " — at most 3 changes, name MUST match an existing field. "
        "If no changes needed, return []. No commentary, no fences."
    )


def _salvage_json(text: str):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    for start, end in (('[', ']'), ('{', '}')):
        i = text.find(start)
        if i < 0:
            continue
        depth, in_str, esc = 0, False, False
        for j in range(i, len(text)):
            c = text[j]
            if esc:
                esc = False
                continue
            if c == '\\':
                esc = True
                continue
            if c == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if c == start:
                depth += 1
            elif c == end:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[i:j + 1])
                    except json.JSONDecodeError:
                        break
    return None


def apply_refinements(baseline: dict, refinements: list) -> dict:
    """Apply tiny-model refinements to the baseline card. Only changes
    `widget` field; everything else stays. Unknown widget names are
    ignored (safety)."""
    valid = {"text_input", "text_input_multi", "file_upload",
             "audio_recorder", "video_recorder", "slider", "number_input",
             "dropdown", "toggle"}
    # Recorders are inputs only; don't let the tiny model retarget an
    # output-shaped field name to a recorder.
    by_name = {i["name"]: i for i in baseline["inputs"]}
    applied: list[dict] = []
    for r in refinements:
        if not isinstance(r, dict):
            continue
        name = r.get("name")
        widget = r.get("widget")
        if name not in by_name or widget not in valid:
            continue
        if name.lower().startswith(("output_", "result_", "out_")):
            continue
        prev = by_name[name]["widget"]
        if prev == widget:
            continue
        by_name[name]["widget"] = widget
        applied.append({"name": name, "from": prev, "to": widget,
                        "reason": r.get("reason", "")})
    baseline["refinements"] = applied
    return baseline


def run_tiny(prompt: str, model: Optional[str] = None,
             dry: bool = False) -> str:
    if dry:
        return "[DRY]"
    args = [CC_BIN, "tiny"]
    if model:
        args += ["-model", model]
    args.append(prompt)
    r = subprocess.run(args, capture_output=True, text=True, timeout=120)
    return r.stdout.rstrip()


def author_gui_card(opcode_row: dict, cap_card: Optional[dict],
                    model: Optional[str] = None, baseline_only: bool = False,
                    dry: bool = False) -> dict:
    baseline = build_baseline_card(opcode_row, cap_card)
    if baseline_only or dry:
        if dry:
            print(json.dumps(baseline, indent=2))
        return baseline
    t0 = time.monotonic()
    prompt = _refine_prompt(opcode_row, cap_card, baseline)
    raw = run_tiny(prompt, model=model, dry=False)
    refinements = _salvage_json(raw) or []
    ms = int((time.monotonic() - t0) * 1000)
    card = apply_refinements(baseline, refinements
                             if isinstance(refinements, list) else [])
    card["drafted_by"] = model or os.environ.get("CC_TINY_MODEL",
                                                 "qwen2.5-coder:1.5b")
    card["drafted_ms"] = ms
    return card


def persist_gui_card(opcode: str, card: dict, drafted_by: str) -> None:
    db_path = (os.environ.get("CC_DB")
               or os.environ.get("CC_GLOBAL_DB")
               or str(Path.home() / ".cc" / "cc.db"))
    env = {**os.environ, "CC_DB": db_path}
    subprocess.run(
        [sys.executable, str(DB_BIN), "gui-upsert",
         opcode, drafted_by, json.dumps(card, ensure_ascii=False),
         "baseline" if drafted_by == "baseline" else "tiny-chain"],
        check=True, env=env,
    )


def main():
    ap = argparse.ArgumentParser(prog="author_gui.py")
    ap.add_argument("opcode", nargs="?", default=None)
    ap.add_argument("--all", action="store_true",
                    help="every opcode that has a capability card")
    ap.add_argument("--missing", action="store_true",
                    help="only opcodes that lack a gui card")
    ap.add_argument("--baseline-only", action="store_true",
                    help="skip tiny model, use modality defaults only")
    ap.add_argument("--model", default=None)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--taxonomy", default=str(_find_taxonomy()))
    args = ap.parse_args()

    tax = load_taxonomy(Path(args.taxonomy))

    targets: list[str] = []
    if args.opcode:
        if args.opcode not in tax:
            sys.exit(f"unknown opcode: {args.opcode!r}")
        targets = [args.opcode]
    elif args.all:
        # Only opcodes that already have a capability card — otherwise
        # the refinement prompt has nothing to refine against.
        db_path = (os.environ.get("CC_DB")
                   or os.environ.get("CC_GLOBAL_DB")
                   or str(Path.home() / ".cc" / "cc.db"))
        import sqlite3
        c = sqlite3.connect(db_path)
        try:
            existing = [r[0] for r in
                        c.execute("SELECT opcode FROM capability_cards")]
        finally:
            c.close()
        targets = sorted(existing)
    else:
        ap.print_help()
        sys.exit(2)

    if args.missing and not args.dry:
        db_path = (os.environ.get("CC_DB")
                   or os.environ.get("CC_GLOBAL_DB")
                   or str(Path.home() / ".cc" / "cc.db"))
        import sqlite3
        c = sqlite3.connect(db_path)
        try:
            already = {r[0] for r in
                       c.execute("SELECT opcode FROM gui_cards")}
        finally:
            c.close()
        before = len(targets)
        targets = [t for t in targets if t not in already]
        print(f"# --missing: filtered {before} → {len(targets)}",
              file=sys.stderr)

    print(f"# authoring {len(targets)} gui card(s)…", file=sys.stderr)

    for i, op in enumerate(targets, 1):
        print(f"\n[{i}/{len(targets)}] {op}", file=sys.stderr, flush=True)
        cap = load_capability_card(op)
        if cap is None:
            print(f"  ℹ no capability card — baseline only",
                  file=sys.stderr)
        opcode_row = tax[op]
        try:
            card = author_gui_card(
                opcode_row, cap, model=args.model,
                baseline_only=args.baseline_only, dry=args.dry,
            )
        except subprocess.TimeoutExpired:
            print("  TIMEOUT — falling back to baseline", file=sys.stderr)
            card = build_baseline_card(opcode_row, cap)
        if args.dry:
            continue
        persist_gui_card(op, card,
                         drafted_by=card.get("drafted_by", "baseline"))
        n_in = len(card.get("inputs", []))
        n_out = len(card.get("outputs", []))
        refs = card.get("refinements", []) or []
        print(f"  ✓ inputs={n_in} outputs={n_out} refinements={len(refs)} "
              f"({card.get('drafted_ms', 0)}ms)", file=sys.stderr)

    print("\n# done.", file=sys.stderr)


if __name__ == "__main__":
    main()
