# /home/tom/models — DAG-GUI

Generated 2026-05-26. Source: `DAG.md` (8 input types, 13 tools, 12 models, 1 lora, 1 class, 11 output types).
Purpose: enumerate every realistic chain the DAG allows, then specify the GUI/UI/UX
needed to drive those chains as a desktop application.

---

## 1. Chain enumeration

### 1.1 Single-hop chains (input → node → output)

| # | Input | Node | Output |
|---|-------|------|--------|
| S01 | IMG | CLIP-Interrogator | TXT |
| S02 | IMG | apple_DepthPro | DEPTH |
| S03 | IMG + BOX | finegrain_box_segmenter | MASK |
| S04 | IMG | metaclip-2-mt5 | EMB |
| S05 | IMG | qualcomm_MediaPipe_Pose | KPTS |
| S06 | IMG + TXT | FireRed-Image-Edit (→ Qwen_Image_Edit) | IMG |
| S07 | IMG | TencentARC_Pixal3D | 3D |
| S08 | IMG | Flux2-Klein-Face-Swap (opt. bg-remove lora) | IMG |
| S09 | IMG | Kolors-Virtual-Try-On | IMG |
| S10 | IMG + AUD | LongCat-Video-Avatar-1.5 | VID |
| S11 | VID | CorridorKey | VID |
| S12 | VID | video-background-removal | VID |
| S13 | VID | pe-av-small | EMB |
| S14 | AUD | Vocal-Isolator | AUD (stems) |
| S15 | AUD | ultravox-v0_7-glm-4_6 | TXT |
| S16 | TXT | melodyflow-t24-30secs | MUS |
| S17 | TXT | gemma-4-E4B-it (ft: claude-opus-reasoning-8.7k) | TXT |
| S18 | TXT | LTX2.3-Studio | VID |
| S19 | PDF | MinerU | MD |
| S20 | POSE + IMG | Qwen-AnyPose (→ Qwen_Image_Edit) | IMG |
| S21 | CAM + IMG | qwen-3d-camera (→ Qwen_Image_Edit) | IMG |
| S22 | VID | SpaceTimeGPT | TXT (caption) |
| S23 | VID + TXT (mode/query) | Marlin-2B-ungated | TXT (dense caption / temporal span) |
| S24 | TXT + TXT (instruction/timbre) | Qwen3-TTS-12Hz-1.7B-CustomVoice | AUD (speech) |

### 1.2 Two-hop chains (recipes from DAG.md plus implied combinations)

| # | Goal | Chain |
|---|------|-------|
| C01 | Photo → talking avatar | IMG + AUD → LongCat → VID |
| C02 | Photo → 3D asset | IMG → DepthPro → DEPTH → Pixal3D → 3D |
| C03 | Pose-controlled edit | IMG → MediaPipe_Pose → KPTS → Qwen-AnyPose → IMG |
| C04 | Auto-prompt → T2V | IMG → CLIP-Interrogator → TXT → LTX2.3 → VID |
| C05 | Song splitter → remix | AUD → Vocal-Isolator → AUD → melodyflow → MUS |
| C06 | Doc ingest → LLM answer | PDF → MinerU → MD → gemma → TXT |
| C07 | Green-screen comp | VID → CorridorKey → VID → video-background-removal → VID |
| C08 | Image → mood music | IMG → CLIP-Interrogator → TXT → melodyflow → MUS |
| C09 | Image → described 3D | IMG → CLIP → TXT → gemma → TXT (caption) + IMG → DepthPro → Pixal3D → 3D |
| C10 | Voice memo → markdown brief | AUD → ultravox → TXT → gemma → TXT/MD |
| C11 | PDF → narrated explainer | PDF → MinerU → MD → gemma → TXT → ultravox-reverse? → AUD → LongCat (with IMG) → VID |
| C12 | Pose+style restyle | IMG → MediaPipe → KPTS → AnyPose → IMG → FireRed (TXT prompt) → IMG |
| C13 | Subject-only image | IMG + BOX → segmenter → MASK → Flux2-Klein-Face-Swap → IMG |
| C14 | Try-on then animate | IMG → Kolors-Virtual-Try-On → IMG → LongCat (+AUD) → VID |
| C15 | Camera-controlled scene | IMG + CAM → qwen-3d-camera → IMG → LTX2.3 (TXT motion) → VID |
| C16 | Video → music score | VID → pe-av-small → EMB → (TXT bridge via gemma) → melodyflow → MUS |
| C17 | Video clean + bg remove combo | VID → CorridorKey → VID → video-background-removal → VID → LongCat re-comp |
| C18 | Video → spoken summary | VID → Marlin → TXT → gemma (summarize) → TXT → Qwen3-TTS → AUD |
| C19 | Video → narrated avatar recap | VID → Marlin → TXT → gemma → TXT → Qwen3-TTS → AUD + IMG → LongCat → VID |
| C20 | Image → captioned voice-over | IMG → CLIP-Interrogator → TXT → gemma (rewrite) → TXT → Qwen3-TTS → AUD |
| C21 | Video → short caption (cheap) | VID → SpaceTimeGPT → TXT |
| C22 | Find-a-moment then cut | VID + TXT(query) → Marlin → TXT(start,end span) → (downstream trim tool) → VID |
| C23 | PDF → audiobook | PDF → MinerU → MD → gemma (clean to script) → TXT → Qwen3-TTS → AUD |
| C24 | Voice memo → spoken reply | AUD → ultravox → TXT → gemma → TXT → Qwen3-TTS → AUD |
| C25 | Music + narration mix | TXT → melodyflow → MUS + TXT → Qwen3-TTS → AUD → (mix in viewer) |

### 1.3 Branch fan-outs (one input feeds many nodes in parallel)

| # | Pattern |
|---|---------|
| F01 | IMG → { CLIP, DepthPro, MediaPipe_Pose, segmenter } in parallel → combine in inspector |
| F02 | AUD → { Vocal-Isolator, ultravox, pe-av-small } in parallel |
| F03 | TXT → { gemma, melodyflow, LTX2.3 } in parallel — useful for A/B prompting |
| F04 | PDF → MinerU → MD → fan-out → { gemma summarize, gemma extract entities, gemma QA } |
| F05 | VID → { SpaceTimeGPT (short cap), Marlin (dense+spans), pe-av-small (emb) } in parallel — caption A/B + retrieval-ready embedding |
| F06 | TXT → { Qwen3-TTS (timbre A), Qwen3-TTS (timbre B), gemma rewrite then Qwen3-TTS } — voice A/B/C audition |

### 1.4 Type-compatibility matrix (legal edges)

| Producer port | Consumes into |
|---|---|
| TXT  | gemma, melodyflow, LTX2.3, FireRed (cond), AnyPose (cond), 3d-camera (cond), ultravox (system prompt), Qwen3-TTS (text + instruction), Marlin (query for find mode) |
| IMG  | every IMG-input node + LongCat (portrait), Pixal3D, FireRed (init), Face-Swap, Kolors |
| VID  | CorridorKey, video-bg-removal, pe-av-small, SpaceTimeGPT, Marlin |
| AUD  | Vocal-Isolator, ultravox, pe-av-small, LongCat (voice track) |
| DEPTH| Pixal3D |
| MASK | video-bg-removal, Face-Swap (subject mask), FireRed (inpaint mask) |
| KPTS | Qwen-AnyPose |
| EMB  | (terminal — viewer / vector-store sink only) |
| MD   | gemma, viewer |
| PDF  | MinerU |
| BOX  | segmenter |
| CAM  | qwen-3d-camera |

---

## 2. GUI application — "Models DAG Studio"

### 2.1 Shell layout

```
┌──────────────────────────────────────────────────────────────────────────┐
│  TOPBAR  [▶ Run] [■ Stop] [⟳ Reset] | Recipes ▾ | File ▾ | View ▾ | GPU% │
├────────────┬─────────────────────────────────────────────┬───────────────┤
│            │                                             │               │
│  PALETTE   │                                             │   INSPECTOR   │
│            │                                             │               │
│ ▾ Inputs   │                                             │  selected     │
│   IMG VID  │              CANVAS (graph)                 │  node:        │
│   AUD TXT  │                                             │  ─ params     │
│   PDF POSE │              pan / zoom / grid              │  ─ presets    │
│   CAM BOX  │                                             │  ─ cache key  │
│ ▾ Models   │                                             │  ─ cost est.  │
│   (9)      │                                             │               │
│ ▾ Tools    │                                             │  OUTPUT       │
│   (13)     │                                             │  PREVIEW      │
│ ▾ Loras    │                                             │  (type-aware) │
│   (1)      │                                             │               │
│ ▾ Outputs  │                                             │               │
│   (11)     │                                             │               │
│ ▾ Recipes  │                                             │               │
│   C01..C17 │                                             │               │
├────────────┴─────────────────────────────────────────────┴───────────────┤
│  JOB QUEUE   ▢ idle ▣ running 23%  | logs ▾ | VRAM 7.2/24G | cache 412MB │
└──────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Node-based canvas (ComfyUI-style, opinionated)

- **Infinite canvas** with grid snap (24 px), pan = middle-drag, zoom = wheel.
- **Nodes** are rectangles with: title bar (icon + name + status dot), left-edge **input ports**, right-edge **output ports**, body = collapsed parameter form (expand on click).
- **Ports** are colored by type — IMG=cyan, VID=indigo, AUD=amber, TXT=white, PDF=red, DEPTH=violet, MASK=lime, KPTS=pink, EMB=grey, MD=tan, BOX=orange, CAM=teal, MUS=gold, 3D=green.
- **Edges** auto-route as bezier; refuse to connect type-mismatched ports (red flash + tooltip "TXT cannot feed an IMG input").
- **Node status dot**: grey=idle, blue=queued, yellow=running (animated), green=done (cached), red=error.
- **Double-click empty canvas** opens fuzzy-search palette ("type a node name").
- **Right-click node**: Duplicate / Pin output / Bypass / Cache off / Reveal in palette.
- **Group box** lasso + Ctrl+G to collapse a sub-graph into a single "sub-recipe" node.

### 2.3 Palette (left)

Six accordions: **Inputs · Models · Tools · Loras · Outputs · Recipes**.
Each item shows: small icon, name, output-port color chips, and est. VRAM.
Drag onto canvas to instantiate. `/` focuses the palette search.
"Recipes" accordion lists C01–C17 — click to drop the full sub-graph at cursor.

### 2.4 Inspector (right)

Two stacked panels:

1. **Parameters** — auto-generated form per node:
   - IMG input → file picker, paste-image, webcam capture, recent-files dropdown.
   - VID input → file picker + scrub-bar + in/out trim.
   - AUD input → file picker + record button + waveform preview.
   - TXT input → multiline editor with prompt-template chooser.
   - Model nodes → numeric (slider+number), enum (segmented control), bool (switch),
     seed (number + 🎲 randomize), prompt (textarea), negative-prompt (textarea).
   - Show **cache key** at bottom + "this run is cached, will re-use ✓" badge.
   - Show **VRAM/time estimate** computed from prior runs.

2. **Output preview** — type-aware viewer:
   - IMG → zoomable canvas + before/after slider when input IMG exists.
   - VID → HTML5 player + frame stepper.
   - AUD → waveform + transport + spectrogram toggle.
   - 3D  → three.js orbit viewer + wireframe toggle + export GLB/OBJ.
   - DEPTH → heatmap with viridis/grey toggle.
   - MASK → checkerboard + alpha-overlay onto source IMG.
   - KPTS → skeleton over source IMG.
   - EMB → first-3-PCA projector (mini scatter) + copy-to-clipboard.
   - TXT/MD → rendered markdown + raw toggle + copy.
   - MUS → waveform + bpm/key detected.

### 2.5 Topbar

- **▶ Run** — executes the whole graph (topo-sorted, cache-aware). Hold Shift = run only selected node + descendants.
- **■ Stop** — cancels current job, leaves cache.
- **⟳ Reset** — clears outputs, keeps wiring.
- **Recipes ▾** — dropdown showing C01–C17 with thumbnail; selecting one replaces canvas (with confirm if dirty).
- **File ▾** — New / Open `.dag.json` / Save / Save As / Export PNG of canvas / Export Mermaid (round-trip with `DAG.md`).
- **View ▾** — Toggle minimap, snap, port labels, dark/light.
- **GPU%** — live nvidia-smi readout; click to open Job Queue full view.

### 2.6 Job queue / status bar (bottom)

Collapsible drawer. Columns: time | node | status | duration | VRAM peak | cache hit | error.
Click a row to jump-zoom the canvas to that node. Filter by status. Re-run / clear-cache buttons per row.

### 2.7 Cross-cutting UX rules

- **Cache by content-address** — node output keyed on (impl-hash, params, hash(inputs)). Re-runs are free.
- **Auto-suggest next node** — clicking a free output port shows a context menu of every node whose first input matches that type, grouped by Model/Tool.
- **Type-aware connection** — dragging from a typed port and dropping on empty canvas opens the palette already filtered to compatible nodes.
- **Sub-recipe collapse** — any selection can become a reusable "macro" node saved to Palette → User.
- **Dry-run** — Alt+Run computes only cache keys + VRAM/time forecast; no GPU work.
- **Single-GPU scheduler** — queue serializes GPU-heavy nodes; CPU-only nodes (CLIP-Interrogator on CPU, MinerU, gemma-small) run in parallel.
- **Crash isolation** — each node runs in a subprocess; OOM kills only the offending node and surfaces a "downsize" suggestion (e.g. lower resolution slider).

---

## 3. Component breakdown (build order)

| Phase | Component | Notes |
|---|---|---|
| 1 | Canvas (pan/zoom/grid, node, port, edge, type-check) | use `react-flow` or `rete.js`; type system = enum from §1.4 |
| 2 | Palette + Inspector + dynamic param-form renderer | param schemas declared per node in `nodes/*.yaml` |
| 3 | Runtime: topo-sort, subprocess executor, content-addressed cache | cache dir `~/.cache/dag-studio/`, key = blake3(impl+params+inputs) |
| 4 | Type-specific viewers (IMG/VID/AUD/3D/DEPTH/MASK/KPTS/EMB/TXT/MD/MUS) | each is a small React component |
| 5 | Recipe loader (C01–C17 as `.dag.json` files) | also "Save as recipe" from current graph |
| 6 | Job queue UI + nvidia-smi poller | 1 Hz; drawer at bottom |
| 7 | Round-trip with `DAG.md` (import Mermaid as graph, export graph as Mermaid) | round-trip is the audit story |
| 8 | Sub-recipe collapse + user palette persistence | nice-to-have |

### Suggested stack

- **Shell**: Electron or Tauri (Tauri preferred — smaller, Rust backend).
- **Frontend**: React + react-flow + zustand + Tailwind.
- **Backend**: Python (FastAPI) subprocess workers, one per node impl. Each model already has a venv under its own directory — reuse those venvs directly.
- **IPC**: Unix socket JSON-RPC; output artifacts written to `~/.cache/dag-studio/{cache_key}/`.
- **Persistence**: graphs as `.dag.json`; recipes ship in `recipes/`.

---

## 4. Mapping nodes → existing dirs (so the GUI can launch them today)

Each palette entry resolves to a directory under `/home/tom/models/`. The runtime
spawns `python -m <entrypoint>` inside that dir's venv. Discovery comes from the
prior scan; the GUI reads a `nodes/*.yaml` manifest per node, e.g.:

```yaml
id: T_LCV
name: LongCat-Video-Avatar-1.5
dir: /home/tom/models/LongCat-Video-Avatar-1.5
venv: .venv
entry: app.py
inputs:  [{name: portrait, type: IMG}, {name: voice, type: AUD}]
outputs: [{name: video,    type: VID}]
params:
  - {name: fps,       type: int,   min: 12, max: 60, default: 25}
  - {name: duration,  type: float, min: 1,  max: 30, default: 8}
vram_estimate_gb: 12
```

One manifest per item in §1.1; the GUI is data-driven from those files.

Manifests for the three additions:

```yaml
id: M_STG
name: SpaceTimeGPT
dir: /home/tom/models/SpaceTimeGPT
venv: .venv
entry: infer.py
inputs:  [{name: video, type: VID}]
outputs: [{name: caption, type: TXT}]
params:
  - {name: num_frames,   type: int,   min: 4,  max: 16, default: 8}
  - {name: max_new_tokens, type: int, min: 16, max: 128, default: 64}
vram_estimate_gb: 3
```

```yaml
id: M_MAR
name: Marlin-2B-ungated
dir: /home/tom/models/Marlin-2B-ungated
venv: .venv
entry: infer.py
inputs:
  - {name: video, type: VID}
  - {name: query, type: TXT, optional: true}   # required only in find mode
outputs:
  - {name: result, type: TXT}                  # scene+event JSON or (start,end) span
params:
  - {name: mode, type: enum, choices: [caption, find], default: caption}
  - {name: fps_sample,    type: int,   min: 1, max: 8, default: 2}
  - {name: max_new_tokens, type: int,  min: 64, max: 1024, default: 384}
  - {name: temperature,   type: float, min: 0.0, max: 1.0, default: 0.2}
vram_estimate_gb: 8
```

```yaml
id: M_QTTS
name: Qwen3-TTS-12Hz-1.7B-CustomVoice
dir: /home/tom/models/Qwen3-TTS-12Hz-1.7B-CustomVoice
venv: .venv
entry: infer.py
inputs:
  - {name: text,        type: TXT}
  - {name: instruction, type: TXT, optional: true}   # style/emotion/prosody control
outputs:
  - {name: audio, type: AUD}
params:
  - {name: timbre,      type: enum, choices: [t1,t2,t3,t4,t5,t6,t7,t8,t9], default: t1}
  - {name: language,    type: enum, choices: [zh,en,ja,ko,de,fr,ru,pt,es,it], default: en}
  - {name: speaking_rate, type: float, min: 0.5, max: 2.0, default: 1.0}
  - {name: streaming,   type: bool, default: false}
  - {name: seed,        type: int,  default: 0}
vram_estimate_gb: 6
```

---

## 5. Acceptance checklist for v0.1

- [ ] Drop any input node, connect to a compatible model/tool, click Run, see preview.
- [ ] Load recipe C02 (Photo → 3D), run on a sample image, rotate result in 3D viewer.
- [ ] Re-running an unchanged graph hits cache for every node (all dots green instantly).
- [ ] Mismatched type drag shows red-flash refusal.
- [ ] Export current canvas to Mermaid; diff against `DAG.md` shows zero structural drift for recipe graphs.
- [ ] OOM on one node leaves the rest of the graph queryable.
- [ ] Recipe C18 (video → spoken summary): drop a clip, run, hear Marlin→gemma→Qwen3-TTS chain produce a voice-over.
- [ ] Recipe C22 (find-a-moment): give Marlin a query string, see (start,end) span; clicking it scrubs the VID preview to that range.
- [ ] Qwen3-TTS timbre dropdown swaps voices without retriggering upstream nodes (cache hits on text input).
