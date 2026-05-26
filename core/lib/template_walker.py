#!/usr/bin/env python3
"""template_walker.py — simulates a workflow_templates row end-to-end
WITHOUT running any models. For each step:

  1. shows the step opcode + purpose
  2. predicts the GUI widgets that would render (from gui_cards + mui_map)
  3. validates the step's binds (do they reference upstream outputs or
     legitimate $input_* placeholders?)
  4. previews the NEXT step's GUI (what the user sees after this step
     completes)
  5. reports HITL gates and __BRANCH__ retry loops

Output is a markdown-shaped walk-through suitable for review or for
feeding into a frontend's "rehearsal" mode (show the user the whole
flow before they commit to running it).

Usage:
    template_walker.py <template_name>
    template_walker.py --all
    template_walker.py --report <name> > /tmp/walkthrough.md
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB_PATH = (os.environ.get("CC_DB")
           or os.environ.get("CC_GLOBAL_DB")
           or str(Path.home() / ".cc" / "cc.db"))

# Load the MUI map for widget→MUI lookups
try:
    sys.path.insert(0, str(HERE))
    from mui_map import lookup as mui_lookup
except ImportError:
    def mui_lookup(widget: str, kind: str = "") -> dict:
        return {"component": "Box", "props": {}}


# ---- loaders -----------------------------------------------------------

def db() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    return c


def load_template(name: str) -> dict | None:
    with db() as c:
        r = c.execute(
            "SELECT name, primary_opcode, description, tags, template_json "
            "FROM workflow_templates WHERE name=?",
            (name,),
        ).fetchone()
    if not r:
        return None
    try:
        tpl = json.loads(r[4])
    except json.JSONDecodeError:
        return None
    tpl["_meta"] = {"name": r[0], "primary_opcode": r[1],
                    "description": r[2], "tags": r[3] or ""}
    return tpl


def load_gui_card(opcode: str) -> dict | None:
    with db() as c:
        r = c.execute(
            "SELECT card_json FROM gui_cards WHERE opcode=?", (opcode,),
        ).fetchone()
    if not r:
        return None
    try:
        return json.loads(r[0])
    except json.JSONDecodeError:
        return None


def load_capability_card(opcode: str) -> dict | None:
    with db() as c:
        r = c.execute(
            "SELECT card_json FROM capability_cards WHERE opcode=?", (opcode,),
        ).fetchone()
    if not r:
        return None
    try:
        return json.loads(r[0])
    except json.JSONDecodeError:
        return None


def opcode_io(opcode: str) -> tuple[list[str], list[str]]:
    """Return (inputs, outputs) from the dag_nodes payload."""
    with db() as c:
        r = c.execute(
            "SELECT payload_json FROM dag_nodes "
            "WHERE node_kind='opcode' AND name=?",
            (opcode,),
        ).fetchone()
    if not r:
        return [], []
    try:
        p = json.loads(r[0])
        return p.get("inputs", []) or [], p.get("outputs", []) or []
    except json.JSONDecodeError:
        return [], []


def list_templates() -> list[str]:
    with db() as c:
        return [r[0] for r in c.execute(
            "SELECT name FROM workflow_templates ORDER BY name"
        )]


# ---- validation --------------------------------------------------------

def validate_step(step_idx: int, step: dict, prev_outs: set[str],
                  user_inputs: set[str]) -> list[str]:
    """Check that step's binds reference legitimate sources. Returns
    list of warnings (empty if all good).

    Variable resolution rules:
      $step_N_out (any name in prev_outs)  → chained from upstream  ✓
      $input_*                             → initial user input     ✓
      $other                               → implied initial input  ✓
                                             (runtime must supply;
                                              same role as $input_*
                                              but using Claude's own
                                              naming, e.g. $text,
                                              $source_frame, $voice_sample)
    Sub-field accessors (`$var.field`) inherit the same rules from
    their base var.
    """
    warns: list[str] = []
    op = step.get("opcode")
    if op in ("__BRANCH__", "__PASSTHROUGH__"):
        return warns
    binds = step.get("binds") or {}
    for slot, src in binds.items():
        if not isinstance(src, str):
            warns.append(f"step {step_idx} bind {slot!r}: value not a string")
            continue
        if not src.startswith("$"):
            continue
        var = src[1:]
        base = var.split(".")[0]
        # All three branches accept the bind — chained, conventional
        # input slot, or implied initial input.
        if base in prev_outs:
            continue
        if base.startswith("input_"):
            continue
        # Otherwise it's an implied initial input (Claude-named).
        # Track it in user_inputs so downstream knows runtime must
        # provide it.
        user_inputs.add(base)
    return warns


# ---- rendering ---------------------------------------------------------

def render_step(step_idx: int, step: dict, total: int, prev_outs: set[str],
                user_inputs: set[str]) -> str:
    out: list[str] = []
    op = step.get("opcode", "?")
    purpose = step.get("purpose", "")
    progress = f"[{step_idx + 1}/{total}]"

    # ── BRANCH steps render differently ──
    if op == "__BRANCH__":
        bo = step.get("branch_on", "?")
        branches = step.get("branches") or {}
        out.append(f"### {progress} **`__BRANCH__`** on `{bo}`")
        out.append("")
        if purpose:
            out.append(f"> {purpose}")
            out.append("")
        out.append("**Branch decisions:**")
        out.append("")
        for pred, action in branches.items():
            if not isinstance(action, dict):
                continue
            goto = action.get("goto")
            retries = action.get("max_retries")
            mut = action.get("mutate")
            line = f"  - `{pred}` → goto step {goto}"
            if retries:
                line += f" (max retries {retries})"
            out.append(line)
            if mut:
                out.append(f"      _mutation:_ {mut}")
        out.append("")
        out.append("**GUI for this step:** _no widgets — pure control flow_")
        out.append("")
        out.append("**System decides automatically; no human interaction.**")
        out.append("")
        return "\n".join(out)

    # ── PASSTHROUGH steps: data-flow no-op (re-emits upstream output) ──
    if op == "__PASSTHROUGH__":
        out.append(f"### {progress} **`__PASSTHROUGH__`**")
        out.append("")
        if purpose:
            out.append(f"> {purpose}")
            out.append("")
        binds = step.get("binds") or {}
        out.append("**Binds (rebinds upstream output):**")
        out.append("")
        for slot, src in binds.items():
            out.append(f"  - `{slot}` ← `{src}`")
        out.append("")
        out_var = step.get("out")
        if out_var:
            out.append(f"**Emits:** `{out_var}` (same content, renamed for "
                       "downstream binding stability)")
            out.append("")
        out.append("**GUI for this step:** _no widgets — pure data passthrough_")
        out.append("")
        hc = step.get("human_checkpoint")
        if isinstance(hc, dict):
            out.append(f"**🟧 HITL checkpoint** (type=`{hc.get('type','?')}`)")
            out.append(f"  prompt: \"{hc.get('prompt','')}\"")
            out.append(f"  default: `{hc.get('default','-')}`")
            out.append("")
            out.append("_Even though no model runs here, the human may approve "
                       "/ reject the upstream artifact at this gate._")
            out.append("")
        else:
            out.append("**No human interaction.**")
            out.append("")
        return "\n".join(out)

    out.append(f"### {progress} `{op}`")
    out.append("")
    if purpose:
        out.append(f"> {purpose}")
        out.append("")

    # Validate binds
    warns = validate_step(step_idx, step, prev_outs, user_inputs)
    binds = step.get("binds") or {}
    out.append("**Binds (inputs to this step):**")
    out.append("")
    if not binds:
        out.append("  _none — opcode takes no inputs_")
    else:
        out.append("  | Slot | Source | Type |")
        out.append("  |---|---|---|")
        for slot, src in binds.items():
            if isinstance(src, str) and src.startswith("$"):
                var = src[1:]
                base = var.split(".")[0]
                if base in prev_outs:
                    typ = "🔗 from prior step"
                elif base.startswith("input_"):
                    typ = "🟦 user input"
                else:
                    typ = "❓ unknown"
            else:
                typ = "📌 literal"
            out.append(f"  | `{slot}` | `{src}` | {typ} |")
    out.append("")

    if warns:
        out.append("**⚠ Bind warnings:**")
        for w in warns:
            out.append(f"  - {w}")
        out.append("")

    # Model candidates
    cands = step.get("model_candidates") or []
    if cands:
        out.append(f"**Model candidates** (ordered preference, "
                   f"{len(cands)}):")
        for i, c in enumerate(cands, 1):
            out.append(f"  {i}. `{c}`")
        out.append("")

    # Predict GUI from the opcode's gui_card
    gui = load_gui_card(op)
    if gui:
        widgets_in = gui.get("inputs") or []
        widgets_out = gui.get("outputs") or []
        meta = gui.get("meta") or {}
        out.append("**Predicted GUI elements (from `gui_cards[" + op + "]`):**")
        out.append("")
        if widgets_in:
            out.append("  _inputs:_")
            for w in widgets_in:
                wn = w.get("name", "?")
                wt = w.get("widget", "?")
                req = "**!**" if w.get("required") else " "
                accept = (w.get("props") or {}).get("accept", "")
                ax = f" accept=`{accept}`" if accept else ""
                mui = mui_lookup(wt)
                out.append(f"    {req} `{wt}` `{wn}`{ax}  "
                           f"→ MUI: `<{mui.get('component','Box')}>`")
        if widgets_out:
            out.append("")
            out.append("  _outputs:_")
            for w in widgets_out:
                wt = w.get("widget", "output_preview")
                kind = (w.get("props") or {}).get("kind", "")
                mod = w.get("modality", "?")
                mui = mui_lookup(wt, kind)
                inner = mui.get("inner_render", {}).get("inner", "")
                inner_str = f"  inner: `<{inner}>`" if inner else ""
                out.append(f"    `{wt}` modality=`{mod}` kind=`{kind}`  "
                           f"→ MUI: `<{mui.get('component','Box')}>`{inner_str}")
        out.append("")
        rt = meta.get("estimated_runtime_s", "?")
        out.append(f"  _est runtime: {rt}s_")
        if meta.get("hitl_likely"):
            out.append(f"  _⚠ HITL likely (per gui_card meta)_")
        out.append("")
    else:
        out.append(f"**⚠ No gui_card for `{op}` — UI must be hand-coded**")
        out.append("")

    # HITL checkpoint from template
    hc = step.get("human_checkpoint")
    if isinstance(hc, dict):
        out.append(f"**🟧 HITL checkpoint** (type=`{hc.get('type','?')}`)")
        out.append(f"  prompt: \"{hc.get('prompt','')}\"")
        out.append(f"  default: `{hc.get('default','-')}`")
        out.append("")

    return "\n".join(out)


def predict_next_step(steps: list[dict], curr_idx: int) -> str | None:
    """Return a short description of what the user sees after this step
    completes. Considers __BRANCH__ jumps + HITL pauses."""
    if curr_idx + 1 >= len(steps):
        return None
    nxt = steps[curr_idx + 1]
    nop = nxt.get("opcode", "?")
    if nop == "__BRANCH__":
        return (f"branch on `{nxt.get('branch_on','?')}` — system decides "
                f"automatically, no UI shown")
    return f"step {curr_idx + 2} ({nop}) UI loads with previous output pre-bound"


# ---- whole-template walk ----------------------------------------------

def walk(template_name: str) -> str:
    tpl = load_template(template_name)
    if not tpl:
        return f"# template not found: {template_name!r}\n"

    meta = tpl["_meta"]
    steps = tpl.get("steps") or []
    out: list[str] = []
    out.append(f"# Walk-through: `{meta['name']}`")
    out.append("")
    out.append(f"**Primary opcode:** `{meta['primary_opcode']}`  "
               f"·  **Steps:** {len(steps)}  "
               f"·  **Tags:** `{meta['tags']}`")
    out.append("")
    out.append(f"> {meta['description']}")
    out.append("")

    # Initial user inputs — scan ALL non-control step binds for `$X`
    # where X is neither a step `out` nor produced inside the template.
    # This captures both the `$input_*` convention AND Claude's own
    # implicit naming (`$text`, `$source_frame`, …).
    all_outs = {s.get("out") for s in steps
                if isinstance(s, dict)
                and s.get("opcode") not in ("__BRANCH__",)
                and s.get("out")}
    user_inputs: set[str] = set()
    for step in steps:
        if not isinstance(step, dict):
            continue
        if step.get("opcode") == "__BRANCH__":
            continue
        for v in (step.get("binds") or {}).values():
            if not (isinstance(v, str) and v.startswith("$")):
                continue
            base = v[1:].split(".")[0]
            if base in all_outs:
                continue   # chained — not an input
            user_inputs.add(base)
    out.append("**Initial inputs the user provides:**")
    if user_inputs:
        for var in sorted(user_inputs):
            if var.startswith("input_"):
                mod = var.replace("input_", "").upper()
                out.append(f"  - `${var}` (modality: `{mod}`)")
            else:
                out.append(f"  - `${var}` (implied — Claude-named "
                           "rather than `$input_*` convention)")
    else:
        out.append("  _none — first step opcode takes no inputs_")
    out.append("")
    out.append("---")
    out.append("")

    prev_outs: set[str] = set()
    total = len(steps)
    for i, step in enumerate(steps):
        out.append(render_step(i, step, total, prev_outs, user_inputs))
        nxt = predict_next_step(steps, i)
        if nxt:
            out.append(f"_**→ next:** {nxt}_")
            out.append("")
        out.append("---")
        out.append("")
        # Track the output variable name for downstream binds
        if step.get("opcode") != "__BRANCH__":
            out_var = step.get("out")
            if out_var:
                prev_outs.add(out_var)

    # Overall validation summary
    n_steps = sum(1 for s in steps if s.get("opcode") != "__BRANCH__")
    n_branches = sum(1 for s in steps if s.get("opcode") == "__BRANCH__")
    n_hitl = sum(1 for s in steps
                 if s.get("human_checkpoint") not in (None, "null"))
    out.append("## Walk-through summary")
    out.append("")
    out.append(f"- **Total steps:** {len(steps)} "
               f"({n_steps} model calls + {n_branches} branch decisions)")
    out.append(f"- **HITL pauses:** {n_hitl}")
    out.append(f"- **User inputs:** {len(user_inputs)}")
    out.append(f"- **Intermediate outputs:** {len(prev_outs)}")
    # Total bind warnings
    total_warns = 0
    for i, s in enumerate(steps):
        if s.get("opcode") == "__BRANCH__":
            continue
        total_warns += len(validate_step(i, s, set(steps[k].get("out", "")
                                                  for k in range(i)
                                                  if steps[k].get("opcode") != "__BRANCH__"),
                                          user_inputs))
    if total_warns:
        out.append(f"- **⚠ Total bind warnings:** {total_warns}  "
                   f"(see per-step warnings above)")
    else:
        out.append(f"- **✓ All binds resolve to legitimate sources**")
    out.append("")
    out.append("---")
    out.append("")
    out.append("_Dry-run rehearsal — no models were called, no API tokens spent._")

    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(prog="template_walker.py")
    ap.add_argument("name", nargs="?", default=None)
    ap.add_argument("--all", action="store_true",
                    help="walk every template (long output)")
    ap.add_argument("--brief", action="store_true",
                    help="brief summary only (no per-step detail)")
    args = ap.parse_args()

    if args.all:
        for n in list_templates():
            print(walk(n))
            print("=" * 70)
            print()
        return
    if not args.name:
        print("Available templates:", file=sys.stderr)
        for n in list_templates():
            print(f"  {n}", file=sys.stderr)
        sys.exit(2)
    print(walk(args.name))


if __name__ == "__main__":
    main()
