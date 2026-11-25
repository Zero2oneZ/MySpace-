# MASTER ARCHITECTURE — gently + MySpace++ + cc + the DAG of DAGs

> One reference. Every layer, every flow, every file path, every contract.
> The substrate is two halves talking through one chain. This doc locks every
> piece into the same frame so you can build anything from it without
> reinventing what already exists.

**Owner:** Tom Lee (Zero2oneZ) — IP confidential
**Date:** 2026-05-29
**Universe DAG snapshot:** 256 nodes · 965 edges
**Sources scanned:** `/data/Projects/gently/` · `/data/Projects/MySpace++/`

---

## 0 — TL;DR (one screen, lock-rule above)

```
THE LAW (deterministic, all layers):
  every state change is one CRYSTAL on the chain.
  every CRYSTAL is content-addressed (BLAKE3 or blake2b-256).
  every COMPOSITION is a workflow_card_v0 (the IR).
  every KERNEL has an agent_def_v1 card (the registry entry).
  every EVALUATION is bottom-up within a card, top-down between cards.
  cc IS the Loom: the same surface composes itself.

THE TWO HALVES:
  gently/        — Rust + .bb + crystal DAG       (deterministic runtime)
  MySpace++/     — Python + bash + Streamlit       (user studio + Loom GUI)
  bridge file    — studio/docs/NOTES-FOR-INFERANCE.md  (cross-session protocol)
  shared chain   — db/schema/* (postgres, append-only ops_events)

THE THREE PLANES (per CC composition safety):
  DESCRIPTION    workflow_card_v0 + agent_def_v1 + composition cards     (DATA)
  VALIDATION     mocap_rig_anchor pattern + j2-prefer-path + IR schema   (GATE)
  FUNCTION       core/lib/*.py + gently crates + GDScript + Three.js     (KERNELS)

THE FOUR ARCHETYPES (one bottom-up grammar):
  morph.engine   1 card           geometry/data modifier stack
  blend.engine   full screen      scene composer (nests morph engines)
  engine.morpher 1 card           protocol governor (engine ↔ engine)
  leaf           injectable node  43 HF task categories (atomic kernels)

THE LAYERS YOU TOUCH FROM cc:
  L0 substrate   crystal chain, content-address, registries
  L1 cards       workflow + agent_def + element + composition + scope cards
  L2 dispatch    156 cc subcommands, .j2 templates, dispatcher catalog
  L3 surfaces    Streamlit · Godot · Blender · ComfyUI · SpriteForge · Loom
  L4 chains      five DAG sub-graphs woven into one universe
```

---

## 1 — INVENTORY (what exists right now)

### 1.1 — gently/ (Rust, the deterministic runtime)

```
crates/                 187 Rust crates (autopoietic core)
src/                    14 JS orchestration tools
db/schema/              17 canonical SQL schemas (000–016)
hooks/                  7 CC lifecycle hooks
mcp/                    3 MCP servers (cloud, scope, watchdog)
apps/                   7 minted apps (companion, glyph-editor, hash-state,
                          tensorchain-landing, tensorchain-onboarding,
                          terminal, znixz-ad-tokenomics)
bb/                     .bb stack-machine examples (universal IR)
```

**Key gently SQL schemas (the deterministic ledger):**

| File | Tables | Owner crates |
|---|---|---|
| `001_core.sql` | ops_events · crystals · sessions | gently-bus · gently-crystal |
| `002_identity.sql` | devices · vault_entries · wallets · key_rotations | telos-identity · telos-blind-vault |
| `003_messages.sql` | conversations · messages | telos-messages-service |
| `004_synth.sql` | synth_balance · synth_transactions · znixz_mint_log | gently-synth-ledger |
| `005_chain.sql` | trade_ledger · swaps · social_posts · feed_tasks | biz-trade.js · telos-swap |
| `006_mcp.sql` | mcp_tools · tool_permissions · tool_calls | mcp-registry.js |
| `007_crm.sql` | seats · orcs · rings · revenue_streams · sigil_tags | cell.js · crm.js |
| `008_thoughts.sql` | thought_archive · code_vault | thought-scraper.js · content-address.js |
| `009_agents.sql` | agents · agent_tasks · flow_steps · flow_runs · atlas_chains | telos-runtime · telos-triggers · bb-loop |
| `011_consolidation.sql` | consolidation runs | gently-dedup · gently-scraper |
| `012_operable_catalog.sql` | catalog of operable items | gently-catalog |
| `013_story_canon.sql` | narrative canon entries | telos-story |
| `014_semantic_index.sql` | 8 165+ public items across 156 crates | gently-scraper |
| `015_hf_index.sql` | HuggingFace task mappings | hf-index |
| `016_task_class.sql` | task classification rows | task-classifier |

**Key gently JS tools (orchestration layer):**

| File | Job |
|---|---|
| `src/cc-hierarchy.js` | tenant/scope hierarchy — clones inherit the engine, not state |
| `src/plan.js` | createPlan() with checkpoints + substeps |
| `src/task-graph.js` | spawnNode() — tracked task graph; never unscoped work |
| `src/cell.js` | CRM atomic unit (SEAT/ORC/RING/FACE/SIGIL — never company/employee) |
| `src/crm.js` | CRM aggregator |
| `src/content-address.js` | dehydrate() — content-address every thought before any API call |
| `src/key-client.js` | getKey() — single source of truth for all API keys |
| `src/chromium-mirror.js` | browser session mirror; NEVER localStorage tokens |
| `src/mcp-registry.js` | MCP tool catalog + tool_permissions enforcement |
| `src/bus-bridge.js` | gently-bus event bridge (pushes ops_events) |
| `src/biz-trade.js` | trade ledger writer |
| `src/chain-laws.js` | enforces the 8 deterministic invariants |
| `src/hive-cache.js` | shared cross-tenant cache (idempotent reads) |
| `src/backlog.js` | persistent backlog reader |

**gently hooks (Claude Code lifecycle):**

| File | Fires on |
|---|---|
| `hooks/session-start.js` | CC session boot — re-loads tenant, scopes, plan |
| `hooks/chain-gate.js` | every tool call — enforces tool_permissions row |
| `hooks/code-dehydrate.js` | pre-API — content-addresses code before LLM sees it |
| `hooks/codie-compress.js` | post-result — CODIE ~97% compression on outputs |
| `hooks/response-extract.js` | post-LLM — extracts structured outputs |
| `hooks/thought-scraper.js` | continuous — thought_archive append-only |
| `hooks/stop.js` | session end — finalize crystal chain segment |

---

### 1.2 — MySpace++/ (Python + bash, the user studio)

**core/lib/ (85 Python modules) grouped by role:**

| Group | Modules |
|---|---|
| **Crystal chain** | `inference_logger.py` · `dimension_pack.py` · `dag_loop.py` · `ops_dag.py` · `recursive_workflows.py` · `chain.py` · `chain_builder.py` · `dag_builder.py` |
| **Loom + IR** | `loom.py` · `morph_chain.py` · `kernel_registry.py` · `workflow_generator.py` · `godot_element_compiler.py` · `spriteforge_bridge.py` |
| **Composition** | `multi_layer_hex.py` · `tri_modal_embedder.py` · `energy_inversion.py` · `dialectic_walker.py` · `transition_field.py` · `forward_projector.py` · `morph_chain.py` |
| **Spatial / time** | `spatial_anchor.py` · `frame_clock.py` · `light_source.py` · `transition_field.py` |
| **Embeddings** | `stream_encoder.py` · `embedding_index.py` · `sentence_chain.py` · `svg_vector_embed.py` |
| **Mocap / pose** | `mocap_frame.py` · `mocap_rig_anchor.py` · `animation_registry.py` |
| **Render bridge** | `chain_event_render.py` · `hunyuan_video_worker.py` · `blob_to_unreal.py` |
| **Web3 oracle** | `program_registry.py` · `program_monitor.py` · `program_correlator.py` · `swap_router.py` · `defi_loop.py` |
| **Pump.fun** | `pump_stream_ingest.py` · `pump_feature_extractor.py` · `pump_gmm_classifier.py` · `pump_xgboost_gate.py` · `pump_surf_executor.py` · `pump_visualizer_3d.py` |
| **Models** | `hf_hub.py` · `hf_endpoints.py` · `model_api.py` · `model_registry.py` · `model_installer.py` · `cloud_providers.py` · `moe_router.py` · `token_router.py` |
| **Auth / endpoints** | `freetier_gate.py` · `godot_ssot_proxy.py` · `studio_runtime.py` · `endpoints_cli.py` · `service_supervisor.py` |
| **Util** | `db.py` · `gpu_scheduler.py` · `task_queue.py` · `result_cache.py` · `prompt_enhancer.py` · `template_walker.py` · `template_lint.py` · `template_binds` |
| **Doc / NLP** | `doc_parser.py` · `doc_parser_facebook_games.py` · `sentence_chain.py` |
| **Social** | `social_graph_persistence.py` · `friend_graph_visualizer.py` · `user_graph.py` · `token_wallet_mapper.py` · `mui_map.py` |
| **Identity / morph runtime** | `identity_resolver.py` · `morph_game_runtime.py` · `parser_cursor.py` |
| **Audio** | `audio_chromatize.py` |
| **UI editors** | `author_cards.py` · `author_gui.py` · `author_templates.py` · `studio.py` · `tui.py` · `chat.py` |
| **Deploy** | `deploy.py` · `third_party_cli.py` · `fix_template_binds.py` |

**studio/ inventory:**

| Path | Holds |
|---|---|
| `assets/_workflows/*.json` | 5 workflow cards: avatar / pinterest / realestate / pump_surf / **blob_to_unreal** |
| `assets/_workflows/templates/*.j2` | 6 Jinja2 templates: streamlit · godot · blender · spriteforge · comfyui · controller + 5 `_default_*` templates |
| `assets/_workflows/SCHEMA_workflow_card_v0.md` | the IR schema (Markdown) |
| `assets/_agents/agent_defs/*.json` | **96 agent_def_v1 cards** — the kernel registry |
| `assets/_godot_elements/*.json` | 8 atomic Godot node cards (Button, Label, VBox, HBox, Sprite3D, Camera3D, ColorRect, Panel) |
| `assets/_compositions/*.json` | composition cards (chain_render_wall, etc.) |
| `assets/_program_registry/catalog.jsonl` | 23 web3 programs (19 mainnet-verified Solana + 2 Sui + 2 token-system) |
| `assets/_animation_sources/*.json` | 3 mocap sources: meta_xr_quest3 · snap_lens_default · mediapipe_holistic_browser |
| `assets/_comfy_workflows/*.json` | 5 ComfyUI workflow JSONs: sd15_pump_create · flux_dev_t2i · avatar_pipeline + per-card emits |
| `assets/_recursions/` | persisted SCCs/cycles/motifs from recursive_workflows |
| `loom/` | **morph_engine.html** · **workspace.html** (the GUI surface; every Loom card lives here) |
| `dapp/server.py` | port 8520 — public + bearer-gated dApp routes |
| `godot/project/` | Godot 4 project — scenes, src/, autoloads, export presets |
| `endpoints/webhook/solana_webhook.py` | port 8524 — HMAC-verified Helius/Triton receiver |
| `endpoints/freetier_callback/` | callback handler + templates for GentlyOS.io + trollz.fun |
| `media/` + `passes/` | asset intake + filetype DAG |
| `spriteforge/` | sprite descriptor → workflow_card layer_stack bridge |
| `docs/` | TWINS-MASTER · TESSERACT · NOTES-FOR-INFERANCE · this file |
| `web/streamlit/` | rendered Streamlit prototypes from workflow_generator |
| `blender/scripts/` | rendered Blender headless scripts |
| `.venv/` | studio's venv (has jinja2; not torch) |

**cc.sh (the dispatcher catalog):**
- **156 subcommands** across `-flag` and `bare-word` styles
- Lives at `core/cc.sh`
- Single-file shell dispatcher: cards → kernels → outputs
- This is the **Loom** in CLI form. See §3.

---

## 2 — THE CRYSTAL CHAIN (substrate · L0)

Every event in the system is **one row** in `~/.cc/inference_master_chain.jsonl` (local) AND **one row** in postgres `ops_events` (gently, droplet). Both sides are append-only.

**Row shape (InferenceRecord):**

```python
{
  "crystal_id":      "<blake2b-256 of canonical_json>",
  "prev_crystal":    "<previous row's crystal_id>",     # chains rows together
  "master_index":    integer,                            # monotonic
  "agent_uuid":      "<cc agent id>",
  "session_id":      "<current cc session>",
  "timestamp":       "2026-05-29T18:00:00Z",
  "tier":            "render|swap|blob_to_unreal|...",   # high-level category
  "model":           "fluxv2|sd15|hunyuan|jupiter_v6",   # which kernel
  "scope":           "pass_3_video_to_pose:mp",          # what was done
  "original_prompt": "<user input>",
  "enhanced_prompt": "<system-augmented prompt or args>",
  "output_text":     "<terminal result>",
  "wave_emb":        [64 float32],                       # tri_modal_embedder
  "time_vec":        { forward/inverted/residual/btc },  # frame_clock
  "tri_modal_crystal": "<axis crystal>",
  "coordinates":     [...]                               # spatial_anchor refs
}
```

**dimension_pack adds the 5-tuple sidecar** (vector / circle / hex / rgb / fps) without modifying canonical_json, so chain v1 verification stays unchanged.

**Where the chain is read from:**
- `cc -chain` / `cc -log` / `cc -context` — terminal views
- `core/lib/dag_loop.py::build_loop_dag()` — universe DAG construction
- `core/lib/embedding_index.py::find_by_crystal()` — CLIP vector retrieval
- `core/lib/recursive_workflows.py::detect_all()` — SCC + simple cycles + motif
- `studio/godot/project/src/chain_render_bridge.gd` — 3D wall in Godot

**Where the chain is written from:**
- `core/lib/inference_logger.py::log()` — the single ingress
- `core/lib/dimension_pack.py::emit()` — applies the 5-tuple sidecar
- `studio/dapp/server.py` — every POST endpoint writes
- `core/lib/blob_to_unreal.py` — every pass anchors
- `core/lib/swap_router.py` — every quote AND every execute anchors
- `core/lib/program_monitor.py` — every chain event anchors
- `core/lib/stream_encoder.py` — every encoded event anchors

---

## 3 — cc IS THE LOOM (L2 · dispatch surface)

**cc hierarchy** (`gently/src/cc-hierarchy.js`):

```
GLOBAL          ~/.claude/             user profile · CLAUDE.md · projects/
                ↓
PROJECT         /data/Projects/<x>/    project root · local CLAUDE.md
                ↓
SESSION         per-tmux-pane          isolated agent + cwd state
                ↓
AGENT           per-spawn UUID         agent-level scope + DBs
```

**Each level exposes via cc:**
- `cc -context` — full state dump (cwd, project, agent, model, DBs)
- `cc -scope` — current project + agent UUID
- `cc -set-project <name>` — rebind local project name
- `cc -dag-studio` — open universe DAG editor

**156 dispatcher entries** group into families:

| Family | Subcommands | What |
|---|---|---|
| **Loom shell** | `loom-serve` · `loom-list` · `loom ground` · `loom mint` · `loom scopes` | Loom cards + scope mint |
| **Render** | `chain-render-{one,tail,prompt,sample}` · `solana-webhook-{serve,test}` | event → image dispatch |
| **Video** | `hunyuan-{run,one,status,seed,reset-lock,workflow-preview}` | image → video queue consumer |
| **Encoder** | `encoder-{run,stats,reset-lock,one}` · `embed-{ingest,save,load,stats,query}` | continuous CLIP + retrieval |
| **Programs** | `programs-{registry-{seed,list,add,verify,verify-live,watch},monitor-{start,status},watchset,correlate,correlate-stats,correlate-clear}` | web3 oracle |
| **Swap** | `swap-{routes,quote,execute}` | USDC↔SOL/SUI + cross-chain |
| **Godot** | `godot-{ssot-serve,issue-dev-token,chain-smoke,chain-wall}` | Godot bridge + wall |
| **Unreal** | `blob-to-unreal` · `unreal-live-link {send,synth}` | UE5 LiveLink pipeline |
| **Workflow** | `workflow-{card,run,publish}` · `studio-{list,run}` | card → 5 surfaces emit |
| **Pump.fun** | `pump-{ingest,features,train-{gmm,xgb},gate,surf-{status,buy,orders},wave-{build,preview}}` · `surf-run` | meme classifier + executor |
| **Auth** | `freetier-{issue,verify}` · `callback-serve` · `godot-issue-dev-token` | token issuance |
| **Foundation** | `passes-{run,stats}` · `weave-{seed,status,route}` · `tesseract-build` · `context` · `scope` · `chain` · `log` · `run` · `set-project` · `studio` · `dag-studio` · `clear-cache` · `wardrobe` · `yt-cut` · `social` · `social-{upload,dev,oauth}` | substrate operations |

**Pattern that holds for every dispatcher:**

```bash
cc <command> [args]
  ↓
core/cc.sh::cmd_<command>()
  ↓
python3 core/lib/<module>.py <subcommand> <args>   (or shells to MCP / Rust)
  ↓
result printed to terminal + crystal-anchored on the chain
```

---

## 4 — THE DAG OF DAGs (L4 · the universe)

**Five sub-DAGs woven into one universe at 256 nodes, 965 edges:**

```
                    UNIVERSE DAG  (dag_loop.build_loop_dag())
                                 │
        ┌────────────┬───────────┼───────────┬──────────────┐
        ▼            ▼           ▼           ▼              ▼
    PLATFORMS     DOCS      INFERENCE      APPS      RECURSIVE_WORKFLOWS
    (web3,        (cards,   (kernels,      (dApp,    (Tarjan SCC +
     external)     j2,       embeddings,    Loom,     simple cycles +
                   schemas)  models)        Godot)    motif mining)
```

**Sub-DAG modules:**

| Sub-DAG | Built by | Loaded from |
|---|---|---|
| PLATFORMS | `dag_loop.load_platforms_from_buildthese()` | `BUILD_THESE_INNOVATE.md` + program_registry |
| DOCS | `dag_loop.load_docs()` | every `core/lib/*.py` module + every workflow card + agent_def |
| INFERENCE | `dag_loop.load_inference_providers()` | hf_hub providers + model_registry + embeddings + kernels |
| APPS | `dag_loop.load_apps()` | dApp routes + Loom cards + Godot scenes + gently apps |
| RECURSIVE_WORKFLOWS | `dag_loop.load_recursive_workflows()` | persisted SCCs at `studio/assets/_recursions/` |

**The recursion detector (`recursive_workflows.py`):**

```
For every cycle in the universe:
  1. Tarjan SCC over (DOCS ∪ APPS ∪ INFERENCE) sub-DAGs
  2. simple_cycles up to length 4
  3. motif: pattern of categorical hops (e.g. comfy → render → encoder → embed → comfy)
  4. persist match → studio/assets/_recursions/<motif_id>.json

dimension_pack.circle_motif_id reads these to colorize chain events:
  same motif → same circle → NN gets a categorical bucket signal
```

**Building the universe:**

```bash
# refresh + print
PYTHONPATH=core/lib python3 -c "
import dag_loop
nodes, edges = dag_loop.build_loop_dag()
print(f'nodes: {len(nodes)} edges: {len(edges)}')
"

# emit a cycle (snapshot the universe at a point in time)
PYTHONPATH=core/lib python3 -c "
import dag_loop
dag_loop.cycle_once(persist=True)
"

# detect recursions
python3 core/lib/recursive_workflows.py detect --persist
python3 core/lib/recursive_workflows.py motifs
```

---

## 5 — workflow_card_v0 (L1 · the IR contract)

**The IR every kernel reads and every surface emits.**

### 5.1 — Required fields

```json
{
  "_schema":      "workflow_card_v0",
  "vm_id":        "vm_mspc_001",
  "name":         "snake_case_unique",
  "category":     "avatar|realestate|texture|sprite|compose|harvest|surf|...",
  "state":        "active|draft|archived",
  "version":      "v0",
  "inputs":       [ {name, type, required, default?} ],
  "outputs":      [ {name, type} ],
  "passes":       [ {id, agent, model_path, engine, in, out, tier, status, notes} ],
  "layer_stack":  [ {name, source, blend} ],   // hypershade vocabulary
  "surfaces":     { streamlit: {...}, godot: {...}, blender: {...},
                     spriteforge: {...}, comfyui: {...} },
  "depends_on":   [ crystal_ids ]
}
```

### 5.2 — The 14 canonical blend modes (layer_stack vocabulary)

```
base · multiply · screen · overlay · additive · normal_map ·
depth_uniform · alpha · opacity · gradient_h · gradient_v ·
color_dodge · soft_light · hard_light
```

Same vocabulary across **5 targets:**
- Godot shader uniforms
- Blender Principled BSDF sockets
- SpriteForge composition modes
- ComfyUI image-mix nodes
- HTML canvas blend modes

### 5.3 — Engine values (which kernel runs the pass)

| `engine` | Kernel target |
|---|---|
| `comfyui` | `chain_event_render.py` or `hunyuan_video_worker.py` (POSTs `/prompt`) |
| `blender` | `blender_mcp.py` (POSTs to blender MCP tool) |
| `mcp` | generic MCP tool call via dispatcher |
| `diffusers` | local HF diffusers pipeline (cloud_providers.py) |
| `spriteforge` | SpriteForge MCP server |
| `deterministic` | a pure Python kernel in core/lib/ |
| `mocap` | mocap_rig_anchor.verify_alignment |

### 5.4 — The 5 surfaces (workflow_generator emits)

Same card → 5 deterministic surfaces (Streamlit prototype, Godot scene+gd+cpp, Blender headless, SpriteForge manifest, ComfyUI JSON) via prefer-`.j2`-template path with internal f-string fallback. See `studio/docs/SURFACES_MATRIX.md` for the 4×5 success matrix.

**Resolver chain inside workflow_generator.py:**
```
candidate 1: card.surfaces.<surface>.template     (declared)
candidate 2: <card.name><suffix>                  (full snake_case)
candidate 3: <card.category><suffix>              (category default)
candidate 4: <first-word>< suffix>                (convenience)
candidate 5: _default<suffix>                     (universal fallback)
```

### 5.5 — Cards on disk

```
studio/assets/_workflows/
  vm_mspc_001.workflows.avatar.photo_to_avatar_rigged.v0.json
  vm_mspc_001.workflows.avatar.blob_to_unreal.v0.json          ← session-100
  vm_mspc_001.workflows.harvest.pinterest_vector_motherload.v0.json
  vm_mspc_001.workflows.realestate.realestate_walkthrough_full.v0.json
  vm_mspc_001.workflows.surf.pump_surf_pipeline.v0.json
```

---

## 6 — agent_def_v1 (L1 · the kernel registry)

**96 cards.** Every callable kernel has one. Pattern:

```json
{
  "_schema": "agent_def_v1",
  "name": "...",
  "module_path": "core/lib/<file>.py",
  "role": "ROLE_TIER · ONE_LINE_PURPOSE",
  "summary": "...",
  "engine_pattern": "...",
  "exports": [...],
  "cli": [...],
  "cc_dispatchers": [...],
  "routing_connections": {
    "inbound_callers":   [...],
    "outbound_calls":    [...],
    "substrate_reads":   [...],
    "substrate_writes":  [...]
  },
  "chain_runs": [...],
  "phase": "..."
}
```

**A workflow_card's `pass.agent` field is a foreign-key into this registry.** The validation gate (§7) resolves it against the catalog at evaluation time.

Lookup:
```bash
# what kernels exist?
ls /data/Projects/MySpace++/studio/assets/_agents/agent_defs/ | wc -l   # → 96

# inspect one
cat /data/Projects/MySpace++/studio/assets/_agents/agent_defs/vm_mspc_001.agents.agent_defs.mocap_rig_anchor.active.json
```

---

## 7 — THE VALIDATION GATE (the safety boundary)

**The contract:** every kernel_ref a workflow_card references must resolve in the agent_def registry, types must check between adjacent passes, no cycles in the pass graph. CC can compose, never inline.

**Implementation patterns:**

| Pattern | File | What it gates |
|---|---|---|
| Topology + tolerance check | `core/lib/mocap_rig_anchor.py::verify_alignment` | mocap frames against rig + spatial anchors → alignment_crystal |
| Resolver chain w/ existence-test | `core/lib/workflow_generator.py::_resolve_template_name` | template file existence per surface; falls back to f-string |
| Format + live-RPC check | `core/lib/program_registry.py::verify_live_solana` | program IDs against mainnet `getAccountInfo` |
| Sig + replay window | `studio/endpoints/webhook/solana_webhook.py::verify_signature` | HMAC-SHA256 + 5-min timestamp window |
| Pre-conditions for live | `core/lib/swap_router.py::execute` | env `MSPC_SWAP_LIVE=1` AND `--confirm` AND `dry_run=False` (3-gate) |

**The 3-gate pattern (write it any time you call into real money / real GPU / real network):**

```python
is_live = (not dry_run) and (os.environ.get("MSPC_SWAP_LIVE", "0") == "1")
# require explicit:
#   env flag    — set by operator on the box, not by code path
#   --confirm   — set by operator on the command line
#   dry_run=False — set by caller intentionally
# else: planned result + crystal-anchored, no real side effect
```

---

## 8 — THE LOOM (homoiconic composition surface)

> Every node IS a workspace. The workspace IS a node. cc IS the Loom.

**Four archetypes, one bottom-up grammar:**

| Archetype | Scope | Base | Stack layers | Needs |
|---|---|---|---|---|
| `morph.engine` | object | one mesh | geometry modifiers | 1 card |
| `blend.engine` | scene | empty scene | scene ops (obj/light/cam) | full screen |
| `engine.morpher` | channel | another engine | protocol governors | 1 card |
| `leaf` | task | task I/O | a single HF kernel | injectable node |

**Where the Loom lives:**

```
studio/loom/
  morph_engine.html       — one card · stack of nodes inside · self-running Three.js
  workspace.html          — meta workspace · stacks Loom cards top-down · iframe each as a node
```

**Top-down between workspaces, bottom-up within:**

```
loom.workspace (workspace.html)
  ├ TOP node: blob_to_unreal       ← modifies everything below
  │  └ internal stack of 5 passes  ← within: bottom-up eval
  ├ middle node: goo.primary
  │  └ 4-node stack (Noise / Spike / Twist / MeshSmooth)
  │     └ each itself a workspace
  └ BASE node: scope=character     ← foundation
```

**Loom serve:**

```bash
cc loom-serve                # static-serves studio/loom/ on :8526
cc loom-list                 # lists minted cards
# http://localhost:8526/workspace.html       — meta workspace
# http://localhost:8526/morph_engine.html    — one node = one workspace
```

**Scope mint (chat-grounded RAG):**

```bash
cc loom ground "I want character creation"
cc loom mint   "..." "character" "<chain_spec>"
cc loom scopes
cc loom scope  <scope_id>
```

Scope storage: `~/.cc/loom/scopes.jsonl` (append-only, dedup-by-id).
RAG grounding source: the closed `kernel_registry` + the `morph_chain` top-wheel taxonomy. RAG **does** include prior scopes (inclusive history).

---

## 9 — THE BRIDGE FILE (cross-half communication)

`studio/docs/NOTES-FOR-INFERANCE.md` — append-only at the section level, both halves read at session start and write at session end.

```
Open every session: cat studio/docs/NOTES-FOR-INFERANCE.md
Close every session: append your check-in, with iso-timestamp + half-tag [mspc]/[gently]/[both]
Cadence: mark TODO/PLAN checkboxes [x]; add Updated by: <half> at <iso-ts>
Q&A: number questions (Q-MSPC-001 / Q-GENTLY-001); answers copy + check off
```

**Hard rules (from /data/Projects/MySpace++/CLAUDE.md):**
- This file is the **only** path for coordinating with the gently half.
- `.env` is mirrored at `/data/Projects/MySpace++/.env` and `/data/Projects/gently/.env`. Never commit.
- `planning/hf_task_evolution.jsonl` is shared canonical opcode taxonomy.
- `studio/auth/keys.sqlite` (mode 600) is per-host. Tokens valid only on issuing host.
- Tom's in-flight files: never commit without explicit instruction.
- Agent identity header required on every response (per `~/.claude/CLAUDE.md`).

---

## 10 — FLOW INVENTORY (every chain you can run)

Each row maps a user intent → the cards/kernels that fire → the chain rows that land.

### 10.1 — Web3 oracle flows

| Intent | Trigger | Path |
|---|---|---|
| Watch mainnet program | `cc programs-monitor-start` | program_monitor → `~/.cc/program_events/<chain>/<short>/<date>.jsonl` → crystal `tier='external_chain_event'` |
| Correlate DOM intent | `cc programs-correlate --window 5s` | program_correlator → `~/.cc/correlations/<date>.jsonl` |
| Verify program live | `cc programs-registry-verify-live` | RPC `getAccountInfo` per entry; updates `verified_at` |

### 10.2 — Render flows

| Intent | Trigger | Path |
|---|---|---|
| Render one event | `cc chain-render-one --event-file X` | chain_event_render → ComfyUI → `~/.cc/chain_renders/<crystal>/image.png` + manifest |
| Tail live events | `cc chain-render-tail --cat MEMECOIN_LAUNCHPAD --verbose` | tails program_events sinks, renders matches |
| Push from webhook | Helius → `POST /webhook/solana` (HMAC) | solana_webhook → chain_event_render |
| Image → video | `cc hunyuan-run` (tails video queue) | hunyuan_video_worker → `<render_dir>/video.mp4` |

### 10.3 — Encoder + retrieval flows

| Intent | Trigger | Path |
|---|---|---|
| Embed every event | `cc encoder-run` | stream_encoder (warm CLIP) → `~/.cc/embeddings/<date>.jsonl` |
| Ingest into index | `cc embed-ingest` | embedding_index → `~/.cc/embeddings/_index.bin` + meta |
| Semantic retrieval | `cc embed-query "..."` | get_singleton().find_nearest → cosine top-K |
| `dim_pack` lookup | (automatic) | `_vector_hex_64` priority: inline → index → multi_layer_hex → SHA-256 |

### 10.4 — Mocap flows

| Intent | Trigger | Path |
|---|---|---|
| Capture (Meta XR) | Quest3 + LiveLink plugin | meta_xr_mocap_emit.gd → `~/.cc/meta_xr_mocap.jsonl` |
| Capture (Snap Lens) | Snap Studio Lens + local relay :7787 | snap_camera_kit.live_mocap_stream → `~/.cc/snap_lens_mocap.jsonl` |
| Verify alignment | (per frame) | mocap_rig_anchor.verify_alignment → alignment_crystal |
| Register source | `python3 core/lib/animation_registry.py seed/add-source/mark-verified` | `studio/assets/_animation_sources/<id>.json` |

### 10.5 — Swap flows (3-pair × 2-direction)

| Intent | Trigger | Path |
|---|---|---|
| Quote any of 6 routes | `cc swap-quote <FROM> <TO> <amt>` | Jupiter v6 / Cetus aggregator / Mayan (cross) → live HTTP |
| Dry-run execute | `cc swap-execute <FROM> <TO> <amt> --confirm` | always returns `dry-run` unless `MSPC_SWAP_LIVE=1` |
| Live execute (Solana) | `MSPC_SWAP_LIVE=1 cc swap-execute SOL USDC.sol 1 --confirm` | Jupiter `/swap` → solders sign → RPC `sendTransaction` (needs solders + base58 in venv) |
| dApp swap quote | `POST /dapp/api/swap` | always dry-run from web; crystal-anchored |

### 10.6 — Loom (workspace) flows

| Intent | Trigger | Path |
|---|---|---|
| Open Loom card | `cc loom-serve` + browse | static-serve studio/loom/*.html |
| Mint a scope | `cc loom mint "<intent>"` | loom.py + morph_chain + kernel_registry → scope row |
| Add node above | UI `+ add node above` | workspace.html prepends to stack; cascade-flash down |
| Edit modifier | UI slider | live ↑recalc ripple within card; dim_pack rgba on chain |

### 10.7 — Godot flows

| Intent | Trigger | Path |
|---|---|---|
| Open 3D wall | `cc godot-chain-wall` | launches Godot with chain_render_wall.tscn |
| Bridge proxy | `cc godot-ssot-serve` (port 8766) | godot_ssot_proxy → 6 chain endpoints + bearer gate |
| Issue dev token | `cc godot-issue-dev-token` | freetier_gate → 30-day token → `~/.cc/godot_dev_token.txt` |
| Compile composition | `python3 core/lib/godot_element_compiler.py compile <comp.json> --out <scene.tscn>` | element cards → .tscn + .gd |

### 10.8 — blob → Unreal (the 5-pass)

| Pass | Module | Output |
|---|---|---|
| 1 — blob_snapshot | (POST endpoint or CLI PNG file) | `~/.cc/blob_renders/<crystal>/snapshot.png` |
| 2 — image_to_video | hunyuan_video_worker queue OR synth stub | `<render_dir>/video.mp4` |
| 3 — video_to_pose | MediaPipe Holistic OR synth pose (PNG-hash seeded) | `<render_dir>/pose.jsonl` |
| 4 — pose_to_animation | mocap_rig_anchor per-frame → rolled hash | `animation_crystal` (single hash) |
| 5 — unreal_live_link | unreal_live_link UDP at fps | UE5 Live Link subject; subject_name `MspcBlob` by default |

```bash
cc blob-to-unreal                                       # synth smoke (dry-run UDP)
cc blob-to-unreal /path/to/snapshot.png --live          # real UDP (needs MSPC_UNREAL_LIVE=1)
cc unreal-live-link synth --n 90                        # 90 synthetic frames
cc unreal-live-link send <pose.jsonl> --host X --port N # stream pose.jsonl
```

---

## 11 — PORT MAP (no collisions)

| Port | Service | Where |
|---|---|---|
| 443 | Caddy TLS | droplet |
| 3100 | watchdog-mcp | droplet |
| 4444 | LiveLink Face (alternate) | local UE5 |
| 7392 | gently-scope-explorer | local |
| 7681 | claude-terminal PTY server | local |
| 7787 | snap_lens_mocap relay (TEXT-PLACEHOLDER) | local |
| 7778 | companion-server / droplet relay | local |
| 7779 | ClaudeCompanion Electron bridge | local |
| 7780 | embed-server | local |
| 8080 | trollz-api (Axum) | droplet |
| 8090 | zero2onez cross-post | local |
| 8091 | zero2onez MCP host | local |
| 8188 | ComfyUI | local (MediaLab) |
| 8520 | studio/dapp/server.py | local |
| 8521 | model_api unified surface | local |
| 8522 | (reserved) | |
| 8523 | stripe webhook receiver | local |
| 8524 | solana_webhook | local |
| 8525 | topstep_mcp local bridge | local |
| 8526 | **loom-serve** (studio/loom/ static) | local |
| 8765 | studio/mcp/replit-bridge | droplet via Caddy |
| 8766 | godot_ssot_proxy sidecar | local |
| 8767 | reserved-weave | |
| 11111 | **unreal_live_link UDP** | local UE5 |

---

## 12 — KEYS + AUTH SURFACES

| Where keys live | Mode |
|---|---|
| `/data/Projects/MySpace++/.env` (mirror) | mirrored to `/data/Projects/gently/.env`; never commit |
| `studio/auth/keys.sqlite` | mode 600 · per-host salted-token registry |
| `~/.cc/godot_dev_token.txt` | per-host freetier token for godot_ssot_proxy |
| `~/.config/solana/id.json` | Solana wallet keypair (Anza CLI default) |
| `studio/.bin/solana-wallet.json` | studio-specific Solana keypair (per `SOLANA_KEYPAIR_PATH`) |

**Auth gates:**
- `freetier_gate.py` — bearer tokens for the godot_ssot_proxy + future public APIs
- `verify_signature` (HMAC-SHA256) in `solana_webhook.py`
- 3-gate execute (env + flag + dry_run=False) in `swap_router.py`
- per-tool `mcp_tools.tool_permissions` rows (gently `db/schema/006_mcp.sql`)

---

## 13 — HOW TO BUILD ANYTHING (recipes)

### 13.1 — Add a new kernel

```bash
# 1. write the module
$EDITOR core/lib/my_new_kernel.py
# 2. write the agent_def card
$EDITOR studio/assets/_agents/agent_defs/vm_mspc_001.agents.agent_defs.my_new_kernel.active.json
# 3. add the cc dispatcher entry
$EDITOR core/cc.sh   # add cmd_my_kernel() + dispatch entry
# 4. (optional) workflow card that uses it
$EDITOR studio/assets/_workflows/vm_mspc_001.workflows.<cat>.<name>.v0.json
# 5. (optional) bind a key route in studio/dapp/server.py
```

### 13.2 — Add a new pipeline (chain of kernels)

```bash
# write one workflow_card_v0 with passes[]
# generate all 5 surfaces:
python3 core/lib/workflow_generator.py generate-all <card_path>
# inspect the matrix:
cat studio/docs/SURFACES_MATRIX.md
```

### 13.3 — Add a Loom card (new workspace node type)

```bash
# 1. drop the HTML (or use morph_engine.html as the seed)
$EDITOR studio/loom/<name>.html
# 2. register in workspace.html's NODE_REGISTRY
# 3. cc loom-list will show it
```

### 13.4 — Add a Godot composition (compiled scene)

```bash
# 1. write the composition card
$EDITOR studio/assets/_compositions/<name>.composition.json
# 2. compile
python3 core/lib/godot_element_compiler.py compile <comp.json> --out <scene.tscn>
# 3. open in Godot
cc godot-chain-wall   # adapt the dispatcher pattern
```

### 13.5 — Add a new chain — every event written to crystal chain + universe DAG

```python
from inference_logger import InferenceLogger
log = InferenceLogger()
crystal = log.log(
    original_prompt="...",
    enhanced_prompt=json.dumps({...}),
    output_text="...",
    tier="<your tier>",
    model="<your kernel>",
    scope="<what you did>",
    source_action="<module.function>",
)
# Then dimension_pack.emit() to attach the 5-tuple sidecar.
```

### 13.6 — Add a scope (RAG-grounded mint)

```bash
cc loom ground "I want X"           # interactive grounding
cc loom mint "I want X" "<label>" "<chain_spec>"
cc loom scopes                      # list
```

### 13.7 — Add a new chain (web3 oracle subscription)

```bash
# 1. add the program(s) to the registry
cc programs-registry-add solana <id> "Name" CATEGORY https://...
cc programs-registry-verify-live --chain solana
cc programs-registry-watch solana <id> on
# 2. start monitoring
cc programs-monitor-start --cat YOUR_CATEGORY --duration 60 --verbose
# 3. correlate with DOM intent (if you have phantom_dom_events.jsonl)
cc programs-correlate --window 5 --persist
# 4. (optional) render on top-K events
cc chain-render-tail --cat YOUR_CATEGORY --verbose
```

### 13.8 — Add a workflow surface template

```bash
# drop a .j2 at one of these names (resolver picks most specific):
studio/assets/_workflows/templates/<card_name><suffix>.j2
studio/assets/_workflows/templates/<category><suffix>.j2
studio/assets/_workflows/templates/<first_word><suffix>.j2
studio/assets/_workflows/templates/_default<suffix>.j2

# valid suffixes per surface:
_proto.py.j2                   (streamlit)
_scene.tscn.j2                 (godot scene)
_controller.gd.j2              (godot script)
_native.cpp.j2                 (godot cpp)
_bake.py.j2                    (blender)
_spriteforge_manifest.json.j2  (spriteforge)
_comfy.json.j2                 (comfyui)

# templates receive jinja2 context: card, card_crystal, rendered_ts, card_hash
```

### 13.9 — Add a swap route (extend swap_router.py)

```bash
# 1. add to TOKEN_LABELS + TOKEN_DECIMALS + token_chain() if a new chain
# 2. add the (fc, tc) tuple to quote()'s router
# 3. wire the provider's HTTP quote URL via env-overridable constant
# 4. wire the executor in _exec_* (or new function); leave TEXT-PLACEHOLDER for signing path
# 5. add cc dispatcher entry (already covered by cc swap-{routes,quote,execute})
```

### 13.10 — Send pose to Unreal Engine

```bash
# 1. UE5: enable Live Link + Live Link Skeletal Animation plugins, restart
# 2. UE5: Window → Live Link panel; auto-detects subjects when packets arrive
# 3. on this host:
MSPC_UNREAL_LIVE=1 cc unreal-live-link send /path/to/pose.jsonl \
    --subject MyChar --host 192.168.x.x --port 11111 --fps 30
# 4. UE5 Live Link panel: subject "MyChar" appears, bind to Animation Blueprint
```

---

## 14 — SOMETHING IS ALREADY THERE — DON'T DUPLICATE

**Tom's PRIME DIRECTIVE applies:** before writing any code, check in order:

1. `gently/REGISTRY.md` — 187 crates indexed
2. `gently/src/*.js` — 14 orchestration tools  
3. `gently/db/schema/*.sql` — 17 canonical schemas
4. `gently/hooks/` — 7 CC lifecycle hooks
5. `gently/BB.md` — can it be a `.bb` program?
6. `MySpace++/core/lib/*.py` — 85 Python modules
7. `MySpace++/studio/assets/_agents/agent_defs/*.json` — 96 kernel cards
8. `MySpace++/studio/assets/_workflows/*.json` — 5 workflow cards
9. `MySpace++/core/cc.sh` — 156 dispatcher entries

**If yes → use it, extend it, wire it. Do NOT duplicate.**
**If no → add to the registry/agent_def FIRST, then build the minimum.**

---

## 15 — THE NOTES-FOR-INFERANCE PROTOCOL (cross-session)

This is the only allowed cross-session communication channel. Every session starts and ends with reading + appending to `studio/docs/NOTES-FOR-INFERANCE.md`.

**Cadence:**

1. **Open every session**: read `NOTES-FOR-INFERANCE.md`.
2. **When you finish a thing** on the shared PLAN: mark it `[x]` and add `Updated by: <half> at <iso-ts>`.
3. **When you have a question** for the other side: add it to Q&A with a unique ID (`Q-MSPC-001`, `Q-GENTLY-001`).
4. **When you answer**: copy the question into the answers block + check it off.
5. **Append-only** at the section level. Don't delete.

The other half (gently/Rust chain) does complementary work:
- `.bb` stack-machine runtime (deterministic, content-addressed)
- Crystal DAG (IPFS + Sui NFT per session)
- `OpKind` instruction sequences targeting models via `telos-ml-tools` MCP
- `codie-v4-predict` (TabPFN-flavored opcode router)
- Mirror-pass + genesis-anchored self-validation

---

## 16 — THE FIVE-AXIS SIGNATURE (NN training corpus shape)

`dimension_pack.emit()` attaches a 5-tuple sidecar to every chain event:

```
vector  — first 32 bytes of multi_layer_hex.pack_layers   OR CLIP-512 from
           embedding_index (priority)  OR SHA-256 fallback
circle  — recursive_workflows match against persisted SCCs  OR
           categorical bucket like chain:<category>:<action>
hex     — InferenceLogger crystal_id
rgb     — deterministic HSV(sub_dag_hue, cost_class_sat, tier_val)
fps     — timestamp quantized at canonical FPS (24/30/60/90/120)
```

**Properties:**
- Deterministic — same record always produces the same 5-tuple
- Non-invasive — does not modify canonical_json (chain v1 verification unchanged)
- Backfillable — `audit_chain()` retro-applies to existing rows
- NN-trainable — vector (per-event uniqueness) + circle (categorical bucket) +
  rgb (visual) + fps (temporal) + hex (lineage) = complete training axes

---

## 17 — KNOWN PORT-FORWARDS + SHARED INFRASTRUCTURE

| Resource | Where | Notes |
|---|---|---|
| WireGuard | z21 ↔ droplet 159.89.181.146 | always-on tunnel |
| Postgres | droplet | append-only ops_events |
| Sui devnet | api.devnet.solana.com | needs flip to mainnet for live swaps |
| Solana devnet | api.devnet.solana.com | needs flip to mainnet for live swaps |
| ComfyUI MediaLab | local :8188 | FLUX-dev warm; CLIP-B in encoder daemon |
| HF cache | ~/.cache/huggingface/hub | 48 GB cached datasets + models |
| MediaLab | /data/Projects/MediaLab | FLUX-dev (23 GB) + HunyuanVideo (not yet downloaded) + SD3.5 Large |
| Datasets/3d | ~/Datasets/3d | Mixamo FBX + Godot binaries |

---

## 18 — REMINDERS FROM `~/.claude/CLAUDE.md`

- Identity header REQUIRED on every response: `[ AGENT: main|subagent | scope: <cwd> | doing: <one phrase> ]`
- Footer REQUIRED on every response: `[ end: <agent type> | scope: <cwd> ]`
- IP confidential — Tom Lee (Zero2oneZ) ownership
- DO NOT write file/dir-tree comments that leak intent in unmistakable patterns
- The PERMANENT OPERATING MANDATE: use what's built to build more

---

## 19 — WHERE TO LOOK NEXT (depth jumps from here)

| For what | Read |
|---|---|
| One-page card schema | `studio/assets/_workflows/SCHEMA_workflow_card_v0.md` |
| Surfaces emit matrix | `studio/docs/SURFACES_MATRIX.md` |
| Twin DAG (mspc ↔ gently) | `studio/docs/TWINS-MASTER.svg` |
| Tesseract (8-sub-DAG meta) | `studio/docs/TESSERACT.{svg,md}` |
| WEAVE (cross-device compute) | `studio/docs/WEAVE.md` |
| Pass DAG (filetype) | `studio/docs/PASSES_DAG.md` |
| Lucid Standard Import bridge | `studio/docs/LUCID_INTEGRATION.md` |
| Defold integration | `studio/docs/DEFOLD-INTEGRATION.md` |
| Rust chain consumer side | `studio/docs/RUST-CHAIN.md` |
| Cross-session protocol | `studio/docs/NOTES-FOR-INFERANCE.md` |
| gently navigation | `/data/Projects/gently/KNOWLEDGE_INDEX.md` |
| gently registry | `/data/Projects/gently/REGISTRY.md` |
| gently chain laws | `/data/Projects/gently/src/chain-laws.js` |
| gently .bb model | `/data/Projects/gently/BB.md` |
| Project tree CLAUDE.md | `/data/Projects/MySpace++/CLAUDE.md` |
| L0 master CLAUDE.md | `/data/Projects/CLAUDE.md` |

---

## 20 — THE ONE-LINE LAW

**cc IS the Loom. Every node IS a workspace. Every workspace IS a node. The IR is the safe interchange. The crystal chain is the immutable history. The DAG of DAGs is the live universe. The workflow_card is what you write; the agent_def is what runs; the dim_pack 5-tuple is what the NN sees; the validation gate is what keeps it deterministic. Top-down between workspaces; bottom-up inside them. Use what is built to build more.**

— EOF —
