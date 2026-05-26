#!/usr/bin/env python3
"""dag_generator.py — emits planning/DAG.md from the seeded library.

For every opcode in hf_task_evolution.jsonl, synthesizes a section in
DAG.md combining:
  - taxonomy row (era, layer, exemplars, role)
  - capability_card (user_params, failure_modes, candidate_models)
  - gui_card (widgets to render, layout hint, runtime estimate)
  - path_builder.py top-3 chains involving the opcode
  - an ASCII mockup auto-rendered from the widget list

Groups by the HF macro category (Multimodal, Computer Vision, NLP,
Audio, Tabular, Reinforcement Learning, Other). The output is meant to
be reviewed by Tom + consumed by the Phase-3 frontend builders + read
by Claude during W2-claude template authoring.

Run:
    python3 planning/dag_generator.py > planning/DAG.md
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from textwrap import wrap

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
TAXONOMY_PATH = HERE / "hf_task_evolution.jsonl"
PATH_BUILDER = HERE / "path_builder.py"
DB_PATH = (os.environ.get("CC_DB")
           or os.environ.get("CC_GLOBAL_DB")
           or str(Path.home() / ".cc" / "cc.db"))

CATEGORY_ORDER = [
    "Multimodal",
    "Computer Vision",
    "Natural Language Processing",
    "Audio",
    "Tabular",
    "Reinforcement Learning",
    "Other",
]


# ---- data loaders ------------------------------------------------------

def load_taxonomy() -> list[dict]:
    rows = []
    for line in TAXONOMY_PATH.read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def load_card_table(table: str) -> dict[str, dict]:
    c = sqlite3.connect(DB_PATH)
    try:
        out: dict[str, dict] = {}
        for op, blob in c.execute(f"SELECT opcode, card_json FROM {table}"):
            try:
                out[op] = json.loads(blob)
            except json.JSONDecodeError:
                pass
        return out
    finally:
        c.close()


def top_chains_for(opcode: str, row: dict, top: int = 3) -> list[list[str]]:
    """Run path_builder twice (in-modality → out-modality) and filter
    chains that include this opcode. Returns at most `top` distinct."""
    ins = row.get("inputs") or []
    outs = row.get("outputs") or []
    seen: set[tuple] = set()
    result: list[list[str]] = []
    for in_mod in (ins[:1] or [""]):
        for out_mod in (outs[:1] or [""]):
            if not in_mod or not out_mod:
                continue
            try:
                r = subprocess.run(
                    [sys.executable, str(PATH_BUILDER), "rank",
                     in_mod, out_mod, "--top", str(top * 4)],
                    capture_output=True, text=True, timeout=20,
                )
            except (subprocess.TimeoutExpired, FileNotFoundError):
                return result
            for line in r.stdout.splitlines():
                # Format: `[ 0] ★ score=12.3   Task A → Task B → Task C`
                # Skip past the score= prefix to capture just the chain.
                m = re.match(
                    r"^\[\s*\d+\][^A-Za-z]*score=[\d.]+\s+(.+?)\s*$",
                    line,
                )
                if not m:
                    continue
                chain = [s.strip() for s in m.group(1).split("→")]
                if opcode not in chain:
                    continue
                key = tuple(chain)
                if key in seen:
                    continue
                seen.add(key)
                result.append(chain)
                if len(result) >= top:
                    return result
    return result


# ---- ASCII mockup renderer ---------------------------------------------

WIDGET_GLYPH = {
    "text_input":       "[___________________]",
    "text_input_multi": "┌─────────────────┐\n│                 │\n│                 │\n└─────────────────┘",
    "file_upload":      "[📁 Browse...    ]",
    "audio_recorder":   "[🎤 Record        ]",
    "video_recorder":   "[📹 Capture       ]",
    "slider":           "├──────◉────────────┤",
    "number_input":     "[ 42  ▲▼          ]",
    "dropdown":         "[Choose...      ▾  ]",
    "toggle":           "[ ● ○ ]",
}

OUTPUT_KIND_GLYPH = {
    "text":          "┌─────────────────┐\n│  Response text  │\n│  ...            │\n└─────────────────┘",
    "image":         "┌─────────────────┐\n│                 │\n│   ▒ IMAGE ▒     │\n│                 │\n└─────────────────┘",
    "audio":         "[▶  ──◉────────  0:23 / 1:05 ]",
    "video":         "┌─────────────────┐\n│                 │\n│   ▶ VIDEO       │\n│                 │\n└─────────────────┘",
    "3d_viewer":     "┌─────────────────┐\n│   ◇ 3D mesh ◇   │\n│   (drag-rotate) │\n└─────────────────┘",
    "doc":           "┌─────────────────┐\n│  📄 Document    │\n└─────────────────┘",
    "mask":          "┌─────────────────┐\n│  ░▒▓ MASK ▓▒░  │\n└─────────────────┘",
    "boxes_overlay": "┌─────────────────┐\n│  □ □ □ (boxes)  │\n└─────────────────┘",
    "keypoints_overlay": "┌─────────────────┐\n│  • • • (joints) │\n└─────────────────┘",
    "heatmap":       "┌─────────────────┐\n│  ░▒▓ heatmap ▒░ │\n└─────────────────┘",
    "label":         "[ Predicted: \"…\" 0.87 ]",
    "label_seq":     "[ B-PER  I-PER  O  B-LOC ... ]",
    "scalar":        "[ 0.847 ]",
    "chart":         "┌─────────────────┐\n│  /\\___/\\___      │\n└─────────────────┘",
    "vector":        "[ [0.21, -0.4, 0.8, ...]  (768-d) ]",
    "graph":         "┌─────────────────┐\n│  ●──●──●        │\n│   \\  │  /       │\n│    ●─●─●        │\n└─────────────────┘",
    "action":        "[ → MoveTo(x,y) | params: ... ]",
    "table":         "┌─────┬─────┬─────┐\n│ ... │ ... │ ... │\n└─────┴─────┴─────┘",
}


def render_widget(w: dict) -> str:
    kind = w.get("widget", "")
    return WIDGET_GLYPH.get(kind, f"[{kind}]")


def render_output(w: dict) -> str:
    if w.get("widget") == "output_preview":
        return OUTPUT_KIND_GLYPH.get(w.get("props", {}).get("kind", ""),
                                      "[ output ]")
    return WIDGET_GLYPH.get(w.get("widget", ""), "[output]")


def _safe_id(s: str, prefix: str = "n") -> str:
    """Mermaid node ID: alphanumeric+underscore, prefixed to avoid collisions."""
    clean = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")
    if not clean:
        clean = "x"
    if clean[0].isdigit():
        clean = "_" + clean
    return f"{prefix}_{clean}"


def gui_dag_mermaid(gui_card: dict, cap_card: dict, opcode: str) -> str:
    """Render a Mermaid `flowchart LR` describing the per-opcode GUI
    interaction DAG. Nodes are widgets/states; edges are user events
    or system transitions. Branches include HITL approval (when likely),
    failure mitigation loops, and the happy path → output → download."""
    inputs = gui_card.get("inputs") or []
    outputs = gui_card.get("outputs") or []
    meta = gui_card.get("meta") or {}
    hitl = bool(meta.get("hitl_likely"))
    rt = meta.get("estimated_runtime_s", "?")
    failures = (cap_card or {}).get("failure_modes") or []

    lines: list[str] = ["flowchart LR"]
    # Style classes for readability
    lines.append("    classDef inputNode fill:#e3f2fd,stroke:#1976d2,color:#0d47a1")
    lines.append("    classDef requiredNode fill:#fff8e1,stroke:#f57c00,color:#e65100,stroke-width:2px")
    lines.append("    classDef stateNode fill:#f3e5f5,stroke:#7b1fa2,color:#4a148c")
    lines.append("    classDef outputNode fill:#e8f5e9,stroke:#388e3c,color:#1b5e20")
    lines.append("    classDef hitlNode fill:#fff3e0,stroke:#f4511e,color:#bf360c,stroke-width:2px")
    lines.append("    classDef errorNode fill:#ffebee,stroke:#d32f2f,color:#b71c1c")

    # Input widget nodes (typed by widget kind)
    required_ids: list[str] = []
    optional_ids: list[str] = []
    for w in inputs:
        wid = _safe_id(w.get("name", "x"), prefix="in")
        label = w.get("name", "?")
        widget = w.get("widget", "?")
        accept = (w.get("props") or {}).get("accept", "")
        sub = f"<br/><i>{widget}"
        if accept:
            sub += f"  {accept}"
        sub += "</i>"
        lines.append(f'    {wid}(["{label}{sub}"])')
        if w.get("required"):
            lines.append(f"    class {wid} requiredNode")
            required_ids.append(wid)
        else:
            lines.append(f"    class {wid} inputNode")
            optional_ids.append(wid)

    # Validate gate — only required inputs determine readiness
    has_validate = len(required_ids) >= 2
    if has_validate:
        lines.append('    validate{{"validate<br/>(all required filled?)"}}')
        lines.append("    class validate stateNode")
        for rid in required_ids:
            lines.append(f"    {rid} -->|required| validate")
        for oid in optional_ids:
            lines.append(f"    {oid} -.->|optional| validate")
        upstream = "validate"
    else:
        upstream = required_ids[0] if required_ids else (optional_ids[0] if optional_ids else None)

    # Submit
    lines.append('    submit(["▶ Run"])')
    lines.append("    class submit stateNode")
    if has_validate:
        lines.append(f"    validate -->|ready| submit")
    else:
        # Wire each input directly to submit
        for rid in required_ids:
            lines.append(f"    {rid} -->|required| submit")
        for oid in optional_ids:
            lines.append(f"    {oid} -.->|optional| submit")

    # Running state
    lines.append(f'    running["⏳ running<br/>~{rt}s"]')
    lines.append("    class running stateNode")
    lines.append("    submit -->|click| running")

    # Output nodes
    out_ids: list[str] = []
    for w in outputs:
        oid = _safe_id(w.get("modality", "out"), prefix="out")
        out_ids.append(oid)
        kind = (w.get("props") or {}).get("kind", "?")
        mod = w.get("modality", "?")
        lines.append(f'    {oid}["{mod} output<br/><i>{kind} preview</i>"]')
        lines.append(f"    class {oid} outputNode")
        lines.append(f"    running -->|complete| {oid}")

    # Error / mitigation path
    if failures:
        lines.append('    error["⚠ failed<br/>see hint"]')
        lines.append("    class error errorNode")
        lines.append("    running -.->|model err| error")
        # Loop back to submit so user can retry with adjusted inputs
        lines.append("    error -.->|retry| submit")

    # Download / share is universal
    if out_ids:
        lines.append('    download(["⬇ download / share"])')
        lines.append("    class download stateNode")

    # HITL or terminal done
    if hitl:
        lines.append('    hitl{"awaiting human<br/>approve / reject?"}')
        lines.append("    class hitl hitlNode")
        for oid in out_ids:
            lines.append(f"    {oid} --> hitl")
        lines.append('    done(["✓ done"])')
        lines.append("    class done outputNode")
        lines.append("    hitl -->|approve| download")
        lines.append("    hitl -.->|reject + replan| submit")
        lines.append("    download --> done")
    else:
        lines.append('    done(["✓ done"])')
        lines.append("    class done outputNode")
        for oid in out_ids:
            lines.append(f"    {oid} --> download")
        lines.append("    download --> done")

    return "\n".join(lines)


def ascii_mockup(gui_card: dict) -> str:
    """Two-column layout: inputs on the left, outputs on the right.
    Each side renders top-to-bottom. Run button below."""
    inputs = gui_card.get("inputs") or []
    outputs = gui_card.get("outputs") or []
    meta = gui_card.get("meta") or {}

    def lines_for_field(w: dict, is_output: bool = False) -> list[str]:
        label = w.get("name") or (w.get("modality") or "")
        if is_output:
            label = f"output  ({w.get('modality','?')})"
        glyph = render_output(w) if is_output else render_widget(w)
        out = [f"  {label}:"]
        out.extend(["  " + g for g in glyph.split("\n")])
        out.append("")
        return out

    left: list[str] = ["INPUTS"]
    if not inputs:
        left.append("  (no inputs)")
    for w in inputs:
        left.extend(lines_for_field(w))

    right: list[str] = ["OUTPUTS"]
    if not outputs:
        right.append("  (no outputs)")
    for w in outputs:
        right.extend(lines_for_field(w, is_output=True))

    # Pad to equal length and interleave with a vertical separator.
    H = max(len(left), len(right))
    left += [""] * (H - len(left))
    right += [""] * (H - len(right))
    W_LEFT = max((len(l) for l in left), default=20)
    W_LEFT = max(W_LEFT, 28)
    rows = []
    rows.append("┌" + "─" * (W_LEFT + 2) + "┬" + "─" * 30 + "┐")
    for a, b in zip(left, right):
        rows.append(f"│ {a:<{W_LEFT}} │ {b:<28} │")
    rows.append("└" + "─" * (W_LEFT + 2) + "┴" + "─" * 30 + "┘")
    rt = meta.get("estimated_runtime_s", "?")
    hitl = " — HITL likely" if meta.get("hitl_likely") else ""
    rows.append("")
    rows.append(f"                    [ ▶ Run ]      ~{rt}s{hitl}")
    return "\n".join(rows)


# ---- category overviews (hand-written) ---------------------------------

CATEGORY_OVERVIEW = {
    "Multimodal": (
        "Multimodal opcodes are where MySpace++ shines hardest: ONE model "
        "absorbs two or more modality types and emits a third. The UI pattern "
        "is consistent — a multi-input panel on the left (each modality gets "
        "its own widget, typed appropriately), a single output preview on the "
        "right, and an explicit submit. Era-5 collapse means most of these "
        "subsume what used to be 3-step chains in earlier eras — surface the "
        "alternatives as 'advanced mode' tabs if needed."
    ),
    "Computer Vision": (
        "Computer Vision splits into two UX classes: ANALYZE (Image → Label/"
        "Mask/Boxes/Depth/Keypoints) where the input panel is a single file "
        "drop zone and the output is a typed overlay/visualization; and "
        "GENERATE (Text/Image → Image/Video/3D) where the input panel adds a "
        "prompt + sliders for diffusion params, and the output preview is "
        "polymorphic by modality. Always include a download/share button on "
        "outputs — these are sharable artifacts."
    ),
    "Natural Language Processing": (
        "NLP is the quietest category UX-wise — most opcodes are TEXT → TEXT/"
        "LABEL. Single-column layouts work fine. The interesting variation is "
        "the COMPOUND tasks (Question Answering needs context + question; "
        "Sentence Similarity needs two texts; Text Ranking needs a query + "
        "candidate list). These get two-column input panels. Default fonts "
        "should be monospace for token-level outputs (NER, Fill-Mask)."
    ),
    "Audio": (
        "Audio inputs offer a critical UX upgrade: in-browser recording vs "
        "file upload. The GUI cards already mark `audio_recorder` as the "
        "preferred widget for ASR-style opcodes (live capture) and "
        "`file_upload` for batch-processing ones (Audio Classification, "
        "Audio-to-Audio). Outputs split into AUDIO (with `[▶  ──◉── ]` player "
        "and download) and TEXT (transcription panel). Real-time streaming "
        "models warrant a partial-transcript view that updates as audio plays."
    ),
    "Tabular": (
        "Tabular is the only category where the input is almost always a FILE "
        "(CSV/Parquet/XLSX). UI should preview the first 10 rows after upload "
        "so users confirm the right file went in. Outputs vary: classification "
        "and regression render a per-row prediction column appended to the "
        "preview table; forecasting renders an inline chart of the predicted "
        "series. This category is the entry point for the trading-bot and "
        "business-automation use cases."
    ),
    "Reinforcement Learning": (
        "RL opcodes have unusual UI needs because they're stateful — the user "
        "configures an environment, runs the policy, then watches frames roll "
        "back as the agent acts. Two-panel layout: left configures env + "
        "policy params; right is a live frame viewer with playback controls. "
        "Robotics layers on a 3D scene viewer (input is camera + text, output "
        "is action). Not for the v1 launch; this is the long-tail category."
    ),
    "Other": (
        "Graph ML is the loneliest opcode in the taxonomy — it doesn't share "
        "modalities with anyone else. UI is a file upload (.graphml, .gexf), "
        "an algorithm dropdown (GCN, GAT, GraphSAGE, Graphormer), and an "
        "output visualization (node coloring for classification, or a new "
        "graph structure for graph-level outputs). Targets the network-"
        "analysis use case if/when that becomes a real audience."
    ),
}

GLOBAL_PRINCIPLES = """\
1. **Modality drives layout.** File modalities (IMAGE/AUDIO/VIDEO/DOC) get
   `file_upload` with the right `accept=` filter. Live capture (mic, camera)
   is a same-spec alternative widget — show it as a tab or alt button.
2. **One Run button, one progress indicator.** Every opcode panel is a
   submit-and-wait cycle. The Run button disables during inference; a
   progress strip estimates time from `meta.estimated_runtime_s`.
3. **HITL is a checkpoint, not a permanent prompt.** `meta.hitl_likely=true`
   surfaces a "review before saving" modal on the output — `[approve]` /
   `[reject]` / `[redo with adjustments]`. The chain pauses there.
4. **Outputs are first-class artifacts.** Every output gets a Download
   button (with sensible filename and format), a Copy-to-clipboard for
   text outputs, and a Share-link for media outputs (when authenticated).
5. **Failure modes from capability cards drive error UX.** Each opcode's
   `failure_modes` translates to UI hint cards: "if the model returns
   '<failure>', try '<mitigation>'". Pre-emptive, not reactive.
6. **Param widgets vs modality widgets are different layers.** Modality
   inputs go in the primary panel; param widgets (sliders, dropdowns,
   number inputs) collapse into an "Advanced" disclosure by default.
7. **Chain steps look the same as single steps.** When the user is inside
   a multi-step workflow (e.g., the YouTube-avatar template), each step
   renders as one of these per-opcode panels, with progress strip showing
   which step is active and what's already done.
"""


# ---- emit --------------------------------------------------------------

def emit_opcode_section(row: dict, cap: dict, gui: dict,
                        chains: list[list[str]]) -> str:
    out: list[str] = []
    op = row["task"]
    out.append(f"### {op}")
    out.append("")
    ins = "+".join(row.get("inputs") or ["-"])
    outs = "+".join(row.get("outputs") or ["-"])
    out.append(f"**I/O** `{ins} → {outs}`   "
               f"**Era** {row.get('era')}   "
               f"**Layer** L{row.get('layer')}   "
               f"**First practical** {row.get('year')}")
    out.append("")
    if row.get("role_in_avatar"):
        out.append(f"_Role:_ {row['role_in_avatar']}")
        out.append("")

    # Top chains
    if chains:
        out.append("**Top chains involving this opcode:**")
        for c in chains:
            out.append(f"- `{' → '.join(c)}`")
        out.append("")

    # Widget spec
    out.append("**Widget spec** (from `gui_card`):")
    if gui:
        n_in = len(gui.get("inputs") or [])
        n_out = len(gui.get("outputs") or [])
        meta = gui.get("meta") or {}
        out.append(f"- {n_in} input widget(s), {n_out} output widget(s), "
                   f"layout `{meta.get('layout_hint','?')}`, "
                   f"est `{meta.get('estimated_runtime_s','?')}s`"
                   + (", **HITL likely**" if meta.get("hitl_likely") else ""))
        for w in (gui.get("inputs") or []):
            slot = f" slot={w['modality_slot']}" if w.get("modality_slot") else ""
            req = "**!**" if w.get("required") else " "
            accept = (w.get("props") or {}).get("accept")
            ax = f"  accept=`{accept}`" if accept else ""
            out.append(f"  - {req} `{w['widget']}`  `{w['name']}`{slot}{ax}")
        for w in (gui.get("outputs") or []):
            kind = (w.get("props") or {}).get("kind", "")
            out.append(f"  - output: `{w['widget']}` kind=`{kind}` "
                       f"modality=`{w.get('modality','?')}`")
    else:
        out.append("- (gui_card not authored)")
    out.append("")

    # Failure modes
    if cap and cap.get("failure_modes"):
        out.append("**Failure modes the UI should pre-empt:**")
        for f in (cap["failure_modes"] or [])[:3]:
            failure = (f.get("failure") or "")[:80]
            mit = (f.get("mitigation") or "")[:120]
            out.append(f"- _{failure}_  →  {mit}")
        out.append("")

    # Mockup
    out.append("**Interface mockup:**")
    out.append("")
    out.append("```")
    if gui:
        out.append(ascii_mockup(gui))
    else:
        out.append("(no gui_card — run `cc -author-gui-cards "
                   f"\"{op}\"` first)")
    out.append("```")
    out.append("")

    # Per-card GUI interaction DAG (Mermaid — renders in GitHub /
    # CC studio / most modern markdown viewers).
    out.append("**GUI interaction DAG** — widget → submit → progress → "
               "output → download (with HITL / failure loops where relevant):")
    out.append("")
    out.append("```mermaid")
    if gui:
        out.append(gui_dag_mermaid(gui, cap, op))
    else:
        out.append("flowchart LR")
        out.append("    no_card[\"no gui_card yet\"]")
    out.append("```")
    out.append("")

    return "\n".join(out)


def main():
    tax = load_taxonomy()
    cap_table = load_card_table("capability_cards")
    gui_table = load_card_table("gui_cards")

    by_cat: dict[str, list[dict]] = defaultdict(list)
    for row in tax:
        by_cat[row.get("category", "Other")].append(row)
    for cat in by_cat:
        by_cat[cat].sort(key=lambda r: (r.get("layer", 99), r["task"]))

    out: list[str] = []
    out.append("# DAG.md — Interface designs for the HF task taxonomy")
    out.append("")
    out.append("> Generated by `planning/dag_generator.py` from the live "
               "`capability_cards` + `gui_cards` tables and the "
               "`path_builder.py` chain ranker. Regenerate after any card "
               "or taxonomy change with:")
    out.append("> ```")
    out.append("> python3 planning/dag_generator.py > planning/DAG.md")
    out.append("> ```")
    out.append("")
    n_op = len(tax)
    n_cap = sum(1 for op in tax if op["task"] in cap_table)
    n_gui = sum(1 for op in tax if op["task"] in gui_table)
    out.append(f"**Coverage:** {n_op} opcodes · {n_cap} capability cards · "
               f"{n_gui} gui cards.")
    out.append("")
    out.append("---")
    out.append("")
    out.append("## Global UX principles")
    out.append("")
    out.append(GLOBAL_PRINCIPLES)
    out.append("")
    out.append("---")
    out.append("")

    for cat in CATEGORY_ORDER:
        rows = by_cat.get(cat, [])
        if not rows:
            continue
        out.append(f"## {cat}  ({len(rows)} opcodes)")
        out.append("")
        if cat in CATEGORY_OVERVIEW:
            out.append("> " + CATEGORY_OVERVIEW[cat].replace("\n", "\n> "))
            out.append("")
        for row in rows:
            op = row["task"]
            chains = top_chains_for(op, row, top=3)
            out.append(emit_opcode_section(
                row, cap_table.get(op, {}), gui_table.get(op, {}), chains,
            ))
        out.append("---")
        out.append("")

    out.append("## Regeneration")
    out.append("")
    out.append("This document is **deterministic** — regenerating after a "
               "card update produces an isomorphic diff. To extend:")
    out.append("")
    out.append("- Add an opcode → edit `hf_task_evolution.jsonl`, then "
               "`cc -author-cards <opcode>` + `cc -author-gui-cards <opcode>`")
    out.append("- Tune a widget choice → edit the `gui_card` directly via "
               "`cc -gui-show <opcode>` → modify JSON → re-upsert, or "
               "re-run `cc -author-gui-cards <opcode>` with a different "
               "tiny model.")
    out.append("- Adjust ASCII glyphs / mockup layout → edit "
               "`dag_generator.py`")
    out.append("- Add a category overview → edit `CATEGORY_OVERVIEW` in "
               "`dag_generator.py`.")

    sys.stdout.write("\n".join(out))


if __name__ == "__main__":
    main()
