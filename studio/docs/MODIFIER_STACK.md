# The Modifier Stack · canonical taxonomy of STEPs

**Generated**: 2026-05-30 from `core/lib/kernel_registry.py::registry()` (128 kernels, 7 planes)
**Manifest**: `studio/loom/step_registry.json`
**Source of truth**: this doc supersedes the demo `STEPS = {noise, spike, twist, bend, smooth, hue}` dict that was hard-coded into early morph_engine iterations.

---

## The 7 modifier categories

Every STEP in a SEQUENCE belongs to exactly one of these 7 categories. The category is determined by the kernel's `plane` in the closed safety set.

| # | category | plane | count | role | typical I/O |
|---|---|---|---|---|---|
| 1 | **TRANSFORM** | `modifier` | 6 | geometry / shape / state mutation | `GEO → GEO` |
| 2 | **COMPOSE** | `scene` | 5 | scene composition | `SCENE → SCENE` or `SCENE → IMAGE\|VIDEO` |
| 3 | **PROTOCOL** | `governor` | 6 | channel encode / frame / verify (the `.bb` chain protocol) | `CHAN → CHAN` |
| 4 | **EMIT** | `connector` | 5 | external system dispatch | varies per connector |
| 5 | **ATTACH** | `attachment` | 6 | persistent metadata · sub-objects that extend `tool_options` | `ANY → ANY` (passthrough) |
| 6 | **INFER** | `hf` | 53 | AI inference (HuggingFace task taxonomy) | varies per HF task |
| 7 | **RECURSE** | `card` | 47 | sub-workflow_card call (the recursive close) | varies per card |

**Total**: 128 steps. Grows monotonically — every new card auto-registers under RECURSE.

---

## Category details

### 1. TRANSFORM (6) · `GEO → GEO`

Pure geometry / state modifiers. Deterministic, reversible (mostly), composable bottom-up.

| step | glyph | desc |
|---|---|---|
| Noise | ∿ | fbm displacement along normal |
| Spike | ✦ | sharp spikes · pow falloff |
| Twist | ⟲ | rotate around Y by height |
| Bend | ⌒ | parabolic lean |
| MeshSmooth | ◠ | relax toward base · removes spikes below |
| HueShift | ◐ | set material hue |

Stack order: **bottom-up** within a single engine_component. Data flows ↑ from INPUT through each enabled STEP to OUTPUT.

### 2. COMPOSE (5) · `SCENE → SCENE`

Scene-level composition. Place objects, arrange transforms, add lights, set cameras, render.

| step | glyph | I/O |
|---|---|---|
| Object | ■ | SCENE → SCENE |
| Arrange | ⌗ | SCENE → SCENE |
| Light | ☀ | SCENE → SCENE |
| Camera | ◎ | SCENE → SCENE |
| Render | ⬡ | SCENE → IMAGE\|VIDEO |

Render is the only one that crosses out of the SCENE type — its output flows to the next engine_component (likely a CONNECTOR for emit).

### 3. PROTOCOL (6) · `CHAN → CHAN`

The `.bb` chain protocol layer. Channel encoding, schema framing, depth routing, gate-checked containment, genesis-anchor verification, duplex channels.

| step | glyph | desc |
|---|---|---|
| Encode | ⟹ | dictionary + ratio compression |
| Frame | ▢ | schema-shaped framing |
| Route | ⇆ | depth-routed dispatch |
| Contain | ⌖ | gate-checked containment |
| Verify | ⊕ | genesis-anchor verification |
| Channel | ≑ | duplex peer link |

This plane is what makes the chain protocol-compliant; it's the substrate the GentlyOS half consumes via the `.bb` instruction format.

### 4. EMIT (5) · `* → external system`

External system dispatch. Each connector targets one runtime.

| step | glyph | I/O | dispatcher |
|---|---|---|---|
| blender | ⌬ | ANY → 3D | `_dispatch_blender` (MCP or `blender --background --python`) |
| godot | ◧ | 3D → SCENE | `_dispatch_godot` (scene + controller scaffold; SSoT proxy when ready) |
| comfyui | ⊞ | ANY → IMAGE\|VIDEO | `_dispatch_comfyui` (submit_workflow over `/prompt`) |
| generative | ⛓ | ANY → ANY | `_dispatch_generative` (fanout MCP) |
| topstep | $ | ANY → LABEL | `_dispatch_topstep` (DRY-RUN trade dispatch) |

### 5. ATTACH (6) · `ANY → ANY` (passthrough)

Persistent metadata. Sub-objects of a STEP or siblings in the SEQUENCE. Do NOT transform data. Extend the per-step `tool_options` rendered in the CONTROLS pane.

| step | glyph | typical content |
|---|---|---|
| doc | 📄 | text body |
| asset | 🎁 | prop / sprite / model with URI |
| ref | 🔗 | external citation / link with body |
| note | ✎ | inline note |
| file | 📁 | local file path |
| link | 🌐 | external URL |

Live as either:
- **sub-object**: `pass.attachments[]` — attached to one specific STEP
- **object in stack**: a SEQUENCE step with `engine: "attachment"` + `kernel_ref: "attachment:doc"` — siblings of TRANSFORM/INFER/COMPOSE STEPs
- **card-level**: `card.attachments[]` — between this card and the downstream card (the blue doc chips in the GUI's gap row)

### 6. INFER (53) · the HF task taxonomy

The 53 HuggingFace tasks. Grouped here by I/O signature into 9 functional sub-categories.

| sub-category | glyph | count | exemplar tasks | typical I/O |
|---|---|---|---|---|
| **multimodal_fuse** | ✺ | 11 | Any-to-Any, Audio-Text-to-Text, Image-Text-to-Text, Audio-Image-to-Video | multi-in → multi-out |
| **generate_modality** | ❖ | 8 | Text-to-Image, Text-to-Video, Image-to-3D, Text-to-Speech, Text-to-Audio | one modality → another |
| **classify** | ⊞ | 7 | Image / Text / Audio / Token Classification | X → LABEL |
| **transform_text** | ═ | 6 | Summarization, Translation, Question Answering, Fill-Mask, Text Generation | TEXT → TEXT |
| **detect_localize** | ◫ | 6 | Object Detection, Image Segmentation, Mask Generation | IMAGE → BOXES\|MASK |
| **misc** | ◌ | 6 | special-shape leaves | (other) |
| **process_speech** | ♬ | 4 | ASR, Audio-to-Audio, Audio Classification | AUDIO → * |
| **extract_features** | ⊙ | 4 | Feature Extraction, Image Feature Extraction, Depth Estimation, Pose Estimation | X → EMBEDDING\|DEPTH_MAP\|KEYPOINTS |
| **tabular_analyze** | ◉ | 1 | Tabular Classification / Regression | TABULAR → LABEL\|FLOAT |

Full enumeration lives in `studio/loom/step_registry.json` and `planning/hf_task_evolution.jsonl`.

### 7. RECURSE (46) · sub-workflow_card calls

Every workflow_card_v0 JSON in `studio/assets/_workflows/` auto-registers as a kernel under the CARD plane. A STEP with `kernel_ref: "card:<name>"` recursively dispatches that whole sub-card via `_dispatch_card`. Tarjan SCC over the CARD plane rejects cycles before write.

Grouped by `category` field on the card:

| sub-category | glyph | count | role |
|---|---|---|---|
| compose | ⬡ | 9 | composer + workspace_stack + auto-generated composer outputs |
| scope | ◇ | 8 | character_creation, document_processing, scene scopes |
| assets | ◯ | 5 | autonomous_3d_asset, texture_only_bake, shader_graph_compose |
| avatar | ◐ | 2 | photo_to_avatar_rigged, blob_to_unreal |
| inference | ∞ | 2 | unified_model_api, deepseek_chat |
| render | ❖ | 2 | event_burst, landing_page |
| deploy | △ | 2 | replit_to_droplet, hf_endpoint_provision |
| harvest | ⊙ | 2 | twitter_timeline, pinterest_vector_motherload |
| trade | $ | 3 | topstep_dry_run, topstep.dryrun.trade, **solana_pattern_trade** |
| (others) | ◌ | 12 | one each: test, embed, swap, world, generative, surf, xr, realestate, dapp, mocap, monitor, defi |

---

## The type-DAG topology

How STEPs connect: each step's `out_type` must match the next step's `in_type`. The 7 categories form a layered topology — early TRANSFORM/INFER steps produce typed data, COMPOSE arranges it, PROTOCOL frames it, EMIT renders it externally. RECURSE crosses layers via card calls. ATTACH passes through without changing type.

```
TEXT  ──┬──→ [INFER · transform_text]   ─→  TEXT
        ├──→ [INFER · classify]         ─→  LABEL
        ├──→ [INFER · generate_modality]─→  IMAGE / VIDEO / AUDIO / 3D
        └──→ [INFER · process_speech]   ─→  TEXT       (when TEXT→AUDIO→TEXT loop)

IMAGE ──┬──→ [INFER · detect_localize]  ─→  BOXES / MASK
        ├──→ [INFER · extract_features] ─→  DEPTH_MAP / KEYPOINTS / EMBEDDING
        ├──→ [INFER · classify]         ─→  LABEL
        ├──→ [INFER · generate_modality]─→  IMAGE / VIDEO / 3D
        ├──→ [EMIT · comfyui]           ─→  IMAGE / VIDEO
        └──→ [EMIT · blender]           ─→  3D

AUDIO ──┬──→ [INFER · process_speech]   ─→  TEXT / AUDIO / LABEL
        └──→ [INFER · multimodal_fuse]  ─→  *

GEO   ──→  [TRANSFORM · {noise,spike,twist,bend,smooth,hue}]
                      └──→  GEO  (stack bottom-up within one engine_component)

3D    ──→  [EMIT · godot]               ─→  SCENE
3D    ──→  [EMIT · blender]             ─→  3D

SCENE ──┬──→ [COMPOSE · {object,arrange,light,camera}]
        │              └──→  SCENE
        └──→ [COMPOSE · render]         ─→  IMAGE / VIDEO

CHAN  ──→  [PROTOCOL · {encode,frame,route,contain,verify,channel}]
                      └──→  CHAN

ANY   ──┬──→ [ATTACH · {doc,asset,ref,note,file,link}]
        │              └──→  ANY     (passthrough · adds metadata only)
        └──→ [RECURSE · card:<name>]
                       └──→  *       (recursive sub-card · typed per card spec)
```

---

## The stack-ordering law

Within a single engine_component's SEQUENCE, STEPs evaluate **bottom-up**: from INPUT (base) through each enabled STEP toward TOP (output). The TOP is what feeds downstream via FEEDS.

Between engine_components, the chain runs **top-down**: each component's OUTPUT becomes the next's INPUT. Each pair of consecutive components has:
- a green **TWEEN line** carrying `tweenDown[]` inference patterns (pre-prompts that wrap upstream output before downstream input)
- blue **DOC CHIPS** carrying `docsDown[]` persistent metadata (passthrough, no behavior change)

Within a BUILD (outer engine), this whole structure stacks recursively — each outer engine contains a chain of inner engine_components, each of which contains a SEQUENCE of STEPs. The same primitive at every level (the recursion close).

---

## Why the demo STEP names are misleading

The original `STEPS = {noise, spike, twist, bend, smooth, hue}` dict in early `morph_engine.html` was a demo for one specific case: a 3D mesh blob. Those 6 steps are the **TRANSFORM** category, plane `modifier`. They are NOT the full STEP vocabulary — they cover 6 out of 128 kernels (4.7%). A user opening the GUI and seeing only those 6 might reasonably conclude this is a 3D mesh editor; in fact this is a deterministic-pipeline composer that *happens* to use a 3D blob as the live-preview when the SEQUENCE is GEO→GEO.

The proper STEP picker exposes:
- The 7 top-level categories above (with their plane labels)
- Sub-categories for INFER (9) and RECURSE (21)
- The closed kernel set as the actual menu

When a user clicks "+ STEP" inside an open engine_component, they should land on a picker that surfaces those 7 categories → drill in → pick a specific kernel. The picker's options come straight from `studio/loom/step_registry.json`.

---

## Mapping to the current codebase

| GUI concept | doc category | IR field | Python module |
|---|---|---|---|
| SEQUENCE STEP | one of 7 categories | `card.passes[i]` | dispatched by `studio_runtime._dispatch_*` |
| inner blob demo (noise/spike/...) | TRANSFORM | `kernel_ref: "modifier:Noise"` | `applyStep` in browser; geometry-only |
| Text-to-Image, Depth Estimation, ... | INFER | `kernel_ref: "hf:<task>"` | `_dispatch_hf` → `hf_hub.inference` |
| blender / godot / comfyui call | EMIT | `kernel_ref: "connector:<id>"` | `_dispatch_blender / _dispatch_godot / _dispatch_comfyui` |
| sub-card recursion | RECURSE | `kernel_ref: "card:<name>"` | `_dispatch_card` (cycle-safe) |
| persistent metadata | ATTACH | `pass.attachments[]` or `card.attachments[]` | `_dispatch_attachment` (no-op transform) |
| scene assembly | COMPOSE | `kernel_ref: "scene:<id>"` | currently `_dispatch_deterministic` |
| .bb chain ops | PROTOCOL | `kernel_ref: "governor:<id>"` | currently `_dispatch_deterministic`; targets GentlyOS Rust side via `.bb` |

---

## Promotion checklist (to graduate the GUI from demo)

When `morph_engine.html` is updated to read this registry:

- [ ] `STEPS = {…}` dict replaced with `fetch('step_registry.json')` loader
- [ ] `+ STEP` button opens a category picker (7 cards) → sub-category → kernel
- [ ] Each STEP renders its glyph + category-color + I/O type chips
- [ ] Validation rejects placing a STEP whose `in_type` doesn't match the previous STEP's `out_type` (with ANY as wildcard)
- [ ] CONTROLS pane renders `params` from the kernel spec, not from a hand-written `schema`
- [ ] The demo blob preview still works for any SEQUENCE that's pure TRANSFORM (GEO→GEO)
- [ ] Non-TRANSFORM SEQUENCEs swap the WebGL preview for a type-appropriate one (image grid, text panel, scene viewport, etc.)

---

## One-line summary

The modifier stack is **the closed kernel set, organized by plane, surfaced as a 7-category picker**. The 6-step demo (`noise/spike/twist/bend/smooth/hue`) is one tiny slice of one category (TRANSFORM); the full vocabulary is 128 steps across 7 categories with deterministic type-flow guaranteed by the registry safety gate.
