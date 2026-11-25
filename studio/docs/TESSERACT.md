# Tesseract Renderer

The Tesseract is a **meta-DAG over every other DAG in the studio** —
opcodes, models, recipes, flows, passes, workflow templates, subsystems,
project types — bundled into one master SVG that is both the document
**and** the executable plan.

> The master SVG is the source of truth.
> This file is a reading guide.

---

## What it is

```
studio/docs/Tesseract.svg          ← the artifact (~120 KB, layered)
studio/tesseract/                  ← the code that produces + walks it
  ├── projects.py                  ← subsystems + project-type matrix
  ├── inventory.py                 ← discovers all 8 source DAGs (253 nodes)
  ├── svg.py                       ← emits the master SVG
  ├── walker.py                    ← agent walker contract enforcer
  └── plan.py                      ← step tracker + help graph
```

The SVG itself contains:

| Layer | Content | What it shows |
|---|---|---|
| 0 | **Instructions** | Agent contract — visible at top-left |
| 1 | **Systems** | 10 subsystem tiles, status-colored |
| 2 | **DAG of DAGs** | Cluster blobs for the 8 source DAGs |
| 3 | **Nodes** | Every individual node, colored by source DAG |
| 4 | **Project types** | Switchboard: which subsystems each type activates |
| 5 | **Plan** | Current plan steps from `plan.py` |

The `<metadata>` block at the top of the SVG carries the **machine-readable
manifest** — every node's `id`, `kind`, `source_dag`, `walk-state`,
`walk-by`, `walk-at`, `walk-neighbors`, `walk-subjects`. The walker
reads/writes this manifest; the visual `<circle>` elements get their
`fill` attribute synced so a browser shows progress visually.

---

## The agent contract (also embedded in the SVG)

To advance through one node, an agent **must** satisfy three requirements:

### 1. Identify the node
Set `data-walk-id` to the canonical node id, `data-walk-by` to your
agent identifier. This confirms you actually read the node.

### 2. Identify every adjacent node
List the UIDs of every node connected to this one (edges in either
direction) in `data-walk-neighbors` (JSON array).

### 3. Map the subject matter at each layer
Record in `data-walk-subjects` (JSON dict):
- `dag` — which source DAG owns this node
- `subsystem` — which subsystem this node serves (or `null`)
- `project_types` — list of project types where this node is reachable

Only when all three are populated may the walker set
`walk-state="processed"` and advance. The walker enforces this — calling
`identify()` without the required fields returns `{"ok": false, ...}`.

---

## CLI surface

```
cc -tesseract-build                  # emit/refresh the master SVG
cc -tesseract-status                 # walk progress by DAG
cc -tesseract-walk                   # show the next pending node + contract
cc -tesseract-identify <uid> --neighbors '[...]' --subjects '{...}'
cc -tesseract-project <name>         # show subsystem activation for a project type
cc -tesseract-plan                   # current plan steps
cc -tesseract-plan-seed              # seed the plan from work already done
cc -tesseract-reset [uid]            # reset one node (or every node) to pending
```

---

## Subsystems (status as of build)

| Subsystem | Status | Files |
|---|---|---|
| 3D Scene engine | partial | `studio/media/Media/3d/`, `studio/projects/*/scene.json` |
| Texture system | partial | `studio/media/Media/3d/textures/`, `passes/inference.py` |
| Inference system | impl | `studio/passes/`, `studio/nodes.py`, `studio/runtime.py` |
| Makeup design system | placeholder | `studio/projects/*/makeup/` |
| Furniture design system | stub | `studio/media/Furniture/`, `studio/projects/*/scene.json` |
| Search system | impl | `studio/passes/pieces_index.py`, `studio/pinterest/` |
| Render system | partial | `studio/runtime.py`, `passes/svg_layers.py` |
| Business system | placeholder | _TODO: studio/business/_ |
| App + website builder | placeholder | _TODO: studio/app_builder/_ |
| Communications system | placeholder | _TODO: studio/comms/_, `studio/proxy/` |

Status colors in the SVG:
- **green** = implemented
- **yellow** = partial
- **orange** = stub (addressable but not yet wired up)
- **gray** = placeholder (earmarked, no code yet)

---

## Project types (switchboard)

| Project type | Required subsystems | Default passes |
|---|---|---|
| 3d-scene | scene_3d, render | thumb, content_hash, bbox_volume, mesh_thumb |
| texture | texture | thumb, normal_map, depth, mask, albedo |
| makeup-designer | makeup, render | thumb, mask, keypoints, depth |
| furniture-designer | furniture, scene_3d, render | thumb, mesh_thumb, bbox_volume, depth |
| image-search | search, inference | thumb, content_hash, embedding, caption, tags |
| render | render, inference | thumb |
| business-record | business | _(none)_ |
| app-builder | app_builder | thumb |
| comms | comms | _(none)_ |

When the user opens a project of a specific type, the studio activates
only the required + optional subsystems for that type — the master SVG
visually toggles those tiles bright while dimming the rest.

---

## Source DAGs that feed the Tesseract

| DAG | Count | Origin |
|---|---|---|
| opcode | 53 | `planning/hf_task_evolution.jsonl` (HF task taxonomy) |
| model | 47 | `studio/nodes.py` (dag_studio NODES_BY_ID) |
| recipe | 49 | `studio/recipes.py` (C01-C25 + S01-S21) |
| flow | 12 | `studio/flows.py` (F-PHOTO-3D, F-NARRATE-VIDEO, ...) |
| pass | 20 | `studio/passes/registry.py` (thumb, mask, depth, ...) |
| template | 53 | `cc.db workflow_templates` (Claude-authored) |
| subsystem | 10 | `studio/tesseract/projects.py SUBSYSTEMS` |
| project_type | 9 | `studio/tesseract/projects.py PROJECT_TYPES` |
| **total** | **253 nodes, 729 edges** | |

---

## Walking — example

```bash
# What's next?
$ cc -tesseract-walk
{
  "uid": "opcode:Image Classification",
  "label": "Image Classification",
  "kind": "opcode",
  "edges": 4,
  "status": "impl",
  "contract": {
    "must_identify_node": true,
    "must_list_neighbors": true,
    "must_map_subjects": true,
    "required_subject_levels": ["dag", "subsystem", "project_types"]
  }
}

# Satisfy the contract.
$ cc -tesseract-identify "opcode:Image Classification" \
    --neighbors '["opcode:Image Segmentation", "opcode:Image Feature Extraction"]' \
    --subjects '{"dag":"opcode","subsystem":"inference","project_types":["image-search","3d-scene"]}'
{"ok": true, "node_uid": "opcode:Image Classification", "at": "2026-05-26T18:47:41Z"}

# Walker advances. SVG circle for this node turns green.
$ cc -tesseract-status
{"total": 253, "by_state": {"pending": 252, "processed": 1}, "by_dag": {...}}
```

---

## Refresh strategy

The SVG should be **rebuilt** whenever:
- A new pass is added to `passes/registry.py`
- A new opcode is added to `hf_task_evolution.jsonl`
- A new model is added to `studio/nodes.py`
- A subsystem changes status (e.g. moved from `stub` to `partial`)
- A new project type is added to `tesseract/projects.py`

`cc -tesseract-build` is idempotent — re-running it picks up all source
changes. Walk state is **NOT** preserved across rebuilds (the manifest is
regenerated from scratch). If you need to preserve walks, `cc -tesseract-status`
+ `cc -tesseract-walk` before rebuilding, capture the processed-set, then
re-identify after the rebuild.

---

## What the SVG actually looks like

```
┌────────────────────────────────────────────────────────────────────────┐
│ ┌──────────────────────┐  ┌──── SUBSYSTEMS (color = status) ─────────┐ │
│ │ TESSERACT RENDERER   │  │ [green]3D Scene  [yellow]Inference  ... │ │
│ │ Agent contract text  │  │ [gray]Business  [gray]Comms  [gray]App │ │
│ │ Read this first      │  └─────────────────────────────────────────┘ │
│ │ ...                  │                                              │
│ │ ...                  │  ┌──── DAG OF DAGS ─────────────────────┐    │
│ │ ...                  │  │ OPCODE 53  MODEL 47  RECIPE 49 FLOW 12│    │
│ └──────────────────────┘  │ PASS 20  TEMPLATE 53  SUBSYS 10  PT 9│    │
│                           └──────────────────────────────────────┘    │
│ ┌──────────── NODES (every node, every DAG) ────────────────────────┐ │
│ │ opcode (53) ●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●● │ │
│ │ model  (47) ●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●    │ │
│ │ recipe (49) ●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●●  │ │
│ │ ...                                                              │ │
│ └──────────────────────────────────────────────────────────────────┘ │
│                                                                       │
│ ┌──────────── PROJECT TYPES (switchboard) ────────────────────────┐  │
│ │ 3d-scene    texture    makeup    furniture    image-search    ...│  │
│ └──────────────────────────────────────────────────────────────────┘  │
│ Tesseract · 253 nodes · 729 edges · 8 DAGs · built YYYY-MM-DD HH:MM   │
└────────────────────────────────────────────────────────────────────────┘
```

Open the SVG in any browser to inspect / right-click any dot to see its
`data-node-id`, `data-source-dag`, `data-walk-state` attributes.
