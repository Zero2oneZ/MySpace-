# AGENTIC BUILD MANIFEST — the self-referenced, rock-solid build plan
## Every constant defined once · every path referenced by name · every step executable by an agent · grounded in today's filesystem state

> **Status:** v1 canonical · 2026-06-02
> **Owner:** Tom Lee (Zero2oneZ)
> **Roll-up of:** the 7-doc suite (`REALTOR_VIRTUAL_TOUR_PIPELINE`, `LIVE_ACTION_AR_CHARACTER`, `GAMES_PLATFORM`, `BUSINESS_BUILD_PLAN`, `TRANSFORMING_WEBSITE_PLAN`, `AI_SWARM_SUBSTRATE`, `ENGINE_AS_A_SERVICE`)
> **System merkle root:** `106b80ac5878c4636f0e37822f029289980568f73349350e0e6cdbb0fbd836ad`
> **Current build readiness:** `62 / 100` (Agent-E reality check, 2026-06-02)
>
> **This doc is structured deliberately:** §1 is the **canonical manifest** of
> every constant, path, function, hash, model, schema, and opcode that exists
> in the project. Every later section references §1 entries **by name** rather
> than re-defining them — so the whole plan is **self-referenced**: change a
> constant once in §1, and the rest of the plan stays consistent. §2 is the
> **reality matrix** (what's shipped vs stub vs proposed, from Agent-E).
> §3–§6 are the agentic phases — each phase is **executable by a sub-agent**
> with the prompt template in that section, and each emits cid'd outputs that
> merge back into the manifest. §7 is the next 5 atomic moves.

---

## 1. CANONICAL MANIFEST — define once, reference everywhere

### 1.1 Constants & paths (Python `UPPER_SNAKE`, anchored to `/data/Projects/`)

```python
# ─── ATLAS ──────────────────────────────────────────────────────────────────
ATLAS                  = Path("/data/Projects/ATLAS")
ASSETS                 = ATLAS / "assets"
CAS                    = ASSETS / "cas"                    # canonical cid'd files
BYLAYER                = ASSETS / "by-layer"               # z-order symlink view
BYPASS                 = ASSETS / "by-pass"                # pass-tag symlink view (composite|depth|mask|...)
BYTYPE                 = ASSETS / "by-type"                # type symlink view (image|video|3d|...)
BYNAME                 = ASSETS / "by-name"                # searchable-name view
BYROLE                 = ASSETS / "by-role"                # IO/role-labelled view
ENGINE_THREE           = ASSETS / "engine" / "three"      # three.js viewer projects
ENGINE_GODOT           = ASSETS / "engine" / "godot"      # godot engine view
ENGINE_BLENDER         = ASSETS / "engine" / "blender"
TEMPLATES              = ATLAS / "templates"               # 8 factory_template_v0 recipes today
BRANCHES               = ATLAS / "branches"                # 5 branch_def_v0 leaves
LAUNCHES               = ATLAS / "launches"                # 3 launch_v0 instances today
BUNDLES                = ATLAS / "bundles"                 # character_bundle_v0 outputs
SHARE                  = ASSETS / "share"                  # vidplay share records
OUTPUT                 = ATLAS / "forge" / "factory_out"   # factory pipeline outputs (cid'd)
MANIFEST               = ASSETS / "manifest.json"          # ATLAS asset ledger
LOOPJSONL              = ATLAS / "loop.jsonl"              # opcode chain ledger (5,800+ lines)
ATOMS                  = ATLAS / "atoms"                   # 11 registry JSONs (models, tools, repos, flows, nodes, agents)
OLLAMA_ROUTER          = ATLAS / "ollama" / "router.json"  # 8-tier escalation ladder
ENGINE_MD              = ATLAS / "ENGINE.md"               # io_hash + PLACE + edit_mode formal model

# ─── ATLAS bin/ tools (executables) ─────────────────────────────────────────
FACTORY                = ATLAS / "bin" / "factory"         # FLUX-schnell CLI (~351 LOC)
RELAUNCH               = ATLAS / "bin" / "relaunch"        # 5-branch merkle CLI (~430 LOC)
VIDPLAY                = ATLAS / "bin" / "vidplay"         # HTMX playground (~533 LOC)
ASSETS_BIN             = ATLAS / "bin" / "assets"          # CAS + by-pass + by-layer (~277 LOC)
CHAIN                  = ATLAS / "bin" / "chain"           # loop.jsonl writer + mismatch (~317 LOC)
CONDUCTOR              = ATLAS / "bin" / "conductor"       # density-math agent team (~260 LOC)
GPUD                   = ATLAS / "bin" / "gpud"            # GPU governor @ :11430 (~104 LOC, RUNNING)
GPU                    = ATLAS / "bin" / "gpu"             # gpud CLI client
GOVERN                 = ATLAS / "bin" / "govern"          # rate-limit / quota gates (~45 LOC, stub)
FORGE                  = ATLAS / "bin" / "forge"           # backward-resolve workflow (~97 LOC)
ATOMIZE                = ATLAS / "bin" / "atomize"         # comfy node atom builder (~127 LOC)
TSCN2TSX               = ATLAS / "bin" / "tscn2tsx"        # PROPOSED — .tscn → JSX flattener

# ─── MySpace++ studio ───────────────────────────────────────────────────────
STUDIO                 = Path("/data/Projects/MySpace++/studio")
GODOT_PROJECT          = STUDIO / "godot" / "project"
GODOT_SCENES           = GODOT_PROJECT / "scenes"          # 14 prebuilt .tscn
GODOT_SRC              = GODOT_PROJECT / "src"
GODOT_CPP              = GODOT_PROJECT / "cpp"             # SpatialBridge + IKSolver — .so NOT BUILT
GODOT_EXPORT_PRESETS   = GODOT_PROJECT / "export_presets.cfg"
GODOT_WEB_SHELL        = STUDIO / "godot" / "templates" / "myspace_web_shell.html"
GODOT_FBINSTANT_SHELL  = STUDIO / "godot" / "templates" / "myspace_instant_games_shell.html"
SCENE_SPINE_JSON       = STUDIO / "scene_spine.json"
SCENE_SPINE_FLOOR      = STUDIO / "scene_spine.floorplan.json"
SCENE_SPINE_SKELE      = STUDIO / "scene_spine.skeleton.json"   # 25-joint Meta Body
SCENE_TO_GODOT         = STUDIO / "scene_to_godot.py"
FLOORPLAN_TO_SPINE     = STUDIO / "floorplan_to_spine.py"
SPINE_OPS              = STUDIO / "spine_ops.py"                # MASK / CUT / FLIP / REORDER
SKELETON_TO_SPINE      = STUDIO / "skeleton_to_spine.py"
PASSES_REGISTRY        = STUDIO / "passes" / "registry.py"      # 100+ passes
PASSES_FUSED_DEPTH     = STUDIO / "passes" / "fused_depth.py"   # 5-channel depth fusion
PASSES_SVG_LAYERS      = STUDIO / "passes" / "svg_layers.py"    # layered SVG emitter
TESSERACT_SVG          = STUDIO / "tesseract" / "svg.py"        # scene→SVG projection
BLENDER_MCP_SERVER     = STUDIO / "blender" / "mcp_server.py"
AVATAR_BAKE            = STUDIO / "blender" / "scripts" / "avatar_bake.py"  # LAYER_STACK PBR
AGENT_DEFS             = STUDIO / "assets" / "_agents" / "agent_defs"      # 96 agent_defs
WORKFLOWS              = STUDIO / "assets" / "_workflows"                  # 47 workflow JSONs
DOCS                   = STUDIO / "docs"                                   # the 7-doc suite

# ─── lyv-realty-ai (Rust + Next + RN) ───────────────────────────────────────
LYV                    = Path.home() / "Projects" / "lyv-realty-ai"
LYV_DASHBOARD          = LYV / "frontend" / "dashboard"                    # Next 14.2 App Router
LYV_DASHBOARD_APP      = LYV_DASHBOARD / "src" / "app"
LYV_TAILWIND           = LYV_DASHBOARD / "tailwind.config.ts"              # Lyv brand palette
LYV_SCANNER            = LYV / "frontend" / "scanner"                      # RN 0.76.5 + Vision Camera + MLKit
LYV_BACKEND            = LYV / "backend"                                   # Rust Axum + SQLx + Redis
LYV_ROUTES             = LYV_BACKEND / "src" / "routes"                    # 38 route .rs files

# ─── MediaLab ───────────────────────────────────────────────────────────────
MEDIALAB               = Path("/data/Projects/MediaLab")
COMFY                  = "http://localhost:8188"                           # ComfyUI HTTP API
COMFY_OUTPUT           = MEDIALAB / "ComfyUI" / "output"
WORKFLOW_TXT2IMG       = MEDIALAB / "studio" / "workflows" / "flux-schnell-txt2img.json"
WORKFLOW_IMG2IMG       = MEDIALAB / "studio" / "workflows" / "flux-schnell-img2img.json"
PIPELINE_ML            = MEDIALAB / "studio" / "pipeline_ml.py"            # TF-IDF + Markov predictor
KOKORO                 = MEDIALAB / "audio" / "tts" / "kokoro"             # streaming TTS
WHISPER                = MEDIALAB / "audio" / "asr" / "whisper"            # Whisper-large-v3-turbo

# ─── /home/tom/models/ (~39 dirs total) ─────────────────────────────────────
MODELS                 = Path.home() / "models"
M_VGGT                 = MODELS / "facebook_VGGT"                # 10 GB — multi-view geometry
M_COTRACKER3           = MODELS / "facebook_cotracker3"          # 407 MB — point tracks
M_DEPTHPRO             = MODELS / "apple_DepthPro"               # 1.9 GB
M_MARIGOLD             = MODELS / "prs-eth_marigold-normals-v0-1"# 15 GB — normals
M_TRELLIS              = MODELS / "TencentARC_Pixal3D"           # 24 GB — img→3D hero
M_SF3D                 = MODELS / "stable-fast-3d"               # 4 GB — fast img→3D
M_SAPIENS              = MODELS / "facebook_sapiens-pretrain-1b" # 4.5 GB — body pose
M_Q3TTS                = MODELS / "Qwen3-TTS-12Hz-1.7B-CustomVoice"  # 3.8 GB — voice clone
M_QWEN_EDIT            = MODELS / "Qwen_Image_Edit_2511"         # 115 GB — heavy inpaint
M_FINEGRAIN            = MODELS / "finegrain_box_segmenter"      # 189 MB — matting
M_LONGCAT              = MODELS / "LongCat-Video-Avatar-1.5"     # animation library bake
M_LTX                  = MODELS / "LTX2.3-Studio"                # 9 GB — img→video
M_GEMMA                = MODELS / "gemma-4-E4B-it"               # 16 GB — edge LLM
M_MARLIN               = MODELS / "Marlin-2B-ungated"            # 11 GB — alt edge LLM
M_KOLORS               = MODELS / "Kolors-Virtual-Try-On"        # 5.4 GB — garment try-on

# ─── ports + URLs ───────────────────────────────────────────────────────────
PORT_COMFY             = 8188   # ComfyUI (RUNNING)
PORT_GPUD              = 11430  # gpud (RUNNING)
PORT_OLLAMA            = 11434  # ollama (RUNNING)
PORT_VIDPLAY_DEFAULT   = 9111
PORT_GODOT_RENDER_BR   = 8766   # chain_render_bridge proxy
ROUTE_FACTORY          = "/api/factory"
ROUTE_ASSETS_CID       = "/api/assets/<cid>"
ROUTE_RELAUNCH         = "/api/relaunch"
ROUTE_SCENE_CID        = "/api/scene/<cid>"           # PROPOSED — tscn2tsx output server
ROUTE_CHAIN_BURST      = "/api/chain/burst"           # PROPOSED — opcode burst endpoint
ROUTE_SHARE_CARD       = "/api/share-card/<slug>.png" # PROPOSED — OG card generator
ROUTE_EVENTS_CID       = "/api/events/cid"            # PROPOSED — SSE cid:new fan-out
ROUTE_BRANCH_LAUNCH    = "/[branch]/launch/[slug]"    # Next.js dynamic
ROUTE_LAUNCH_SLUG      = "/launch/<slug>/"            # vidplay HTMX
```

### 1.2 Function inventory (by source file)

```python
# bin/factory  (FLUX-schnell wrapper)
now()                              -> ISO8601 str
comfy_alive(timeout=2)             -> bool
comfy_submit(workflow)             -> prompt_id
comfy_history(pid)                 -> dict
comfy_view(filename, subfolder)    -> bytes
base_workflow(path)                -> dict
patch_workflow(wf, prompt, ...)    -> dict        # patches FLUX-schnell node 5 + 7 + 2/6
wait_for_output(pid, timeout_s)    -> (fn, sub, nid)
download_to_output(fn, sub, slug)  -> Path
file_cid(path)                     -> str         # sha256[:16]
assets_scan(dirpath)               -> str
find_cid_for_path(path)            -> str | None  # heals via file_cid fallback
template_save(name, recipe, ...)   -> Path
template_load(name)                -> dict
template_list()                    -> list[str]
emit_bundle(name, recipe, prompt, cids, paths) -> Path
run_recipe(recipe_id, prompt, ...) -> result_dict
cmd_list_recipes()                 -> None
cmd_list_templates()               -> None

# bin/relaunch  (5-branch merkle CLI)
merkle(o)                          -> str         # sha256(JSON.stringify(o, sort_keys=True))[:16]
slug(s)                            -> kebab-case str
persist_branches()                 -> None        # writes branches/<name>/BRANCH.json per BRANCH_DEFS
load_branch(name)                  -> dict
render_text_logo(text, color, ...) -> Path        # PIL→font; SVG fallback
write_theme(launch_dir, color, brand) -> None
write_index(launch_dir, branch_def, inputs, slug, logo) -> None
ask_questions(branch_def, scripted) -> dict
seed_branch_templates(branch_def, brand_slug) -> list[str]
do_launch(vertical, scripted, interactive) -> launch_state
show_tree()                        -> None        # merkle tree visualisation
show_list()                        -> None

# bin/vidplay  (HTMX playground)
jload(p, d=None)                   -> dict
manifest()                         -> dict
list_layer_bands()                 -> list[str]
pick_assets(seed=42, n=5)          -> list[asset_dict]  # deterministic
comfy_alive() / comfy_submit / comfy_history  # same as factory
flux_workflow(prompt, seed, w, h)  -> dict        # minimal inline FLUX workflow
job_set(jid, **kw)                 -> None
run_layer_remix(jid, seed, n, proj)   -> None     # background thread
run_cutout(jid, cid, proj)         -> None        # background thread
run_factory(jid, prompt, template, seed) -> None  # shells out to bin/factory
run_flux(jid, prompt, seed)        -> None
list_factory_templates()           -> list[str]
page_home(host_hint) / page_job / page_login / page_gallery / page_share -> str  # HTML
H.do_GET(self)                     -> None        # routes /play/*, /job/*, /share/*, /view/*, /launch/*
H.do_POST(self)                    -> None        # /login

# bin/assets  (CAS + multi-view symlinks)
cid_of(path)                       -> str         # sha256[:16]
pass_of(name)                      -> str         # picks from PASS_TOKENS
role_hint(name) / layer_of(name) / link(src, dst)
register(path, m)                  -> (status, asset_dict)
walk_media(dirs)                   -> generator
cmd_scan / cmd_watch / cmd_engine / cmd_label / cmd_find / cmd_stats
cid_to_uid(cid)                    -> str         # deterministic Godot uid:// (base-25)
emit_three_scene(base, assets)     -> (path, n_nodes)
```

### 1.3 Schemas (all JSON-serialised, all cid'd by `bin/assets`)

```
factory_template_v0   {name, recipe, fixed_inputs:{negative,width,height,guidance,style_suffix?},
                       example_cids, created_at, branch?, brand?}
branch_def_v0         {name, title, pitch, questions:[(key,label,default)],
                       recipes:[{name,recipe,style_suffix}], carry_templates,
                       target_surfaces, break_points, primary_pipeline, merkle}
launch_v0             {slug, vertical, branch_merkle, launch_merkle, inputs,
                       seeded_templates, created_at, logo, target_surfaces,
                       break_points, primary_pipeline}
character_bundle_v0   {cid, metadata, mesh, textures, animation_library,
                       voice_clone, paperdoll_layers, staging}
character_bundle_v1   PROPOSED (AI_SWARM_SUBSTRATE.md §9):
                       character_bundle_v0 + {instruct, skills, allowed_signals,
                       bound_objects[], opcode_vocabulary}
template_v0           PROPOSED (ENGINE_AS_A_SERVICE.md §2):
                       {id, branch_merkle, parent_root, design_tokens, scenes[],
                       characters[], payment, deploy, viral, tier, price_usd_month}
sprite_layer_v0       {cid, layer:int 0-99, layer_name, role, type}
```

### 1.4 Opcode set (the swarm's bounded action surface)

```
RUN        execute a workflow / subprocess action            (most common — 41/50 in loop.jsonl tail)
MAIN       top-of-tree / primary entry point                  (9/50 in tail)
EDIT       modify a composed asset or scene
SCAN       read-only inventory / audit
WRAP       density escalation — agent climbs a tier
ACCEPT     density commit — agent finds its place

(per AI_SWARM_SUBSTRATE.md §8: every burst picks exactly one opcode from this set,
 bounded further by the scene's allowed_signals; chain mismatch rejects collisions)
```

### 1.5 Pass tokens (assets.py PASS_TOKENS — the LAYER_STACK names)

```
albedo / u_albedo / basecolor / diffuse          → "albedo"
normal / u_normal                                 → "normal"
depth  / u_depth                                  → "depth"
ao     / u_ao / occlusion                         → "ao"
alpha  / u_alpha / matte / mask / opacity         → "mask"  (or "opacity")
pose   / openpose / dwpose / skeleton             → "pose"
bbox   / region / crop                            → "bbox"
(default for everything else)                     → "composite"
```

### 1.6 Merkle / cid roots (all 16-char hex)

```
SYSTEM_MERKLE_ROOT     = 106b80ac5878c4636f0e37822f029289980568f73349350e0e6cdbb0fbd836ad
  inputs (sorted, concatenated, sha256):
   A /home/tom/models       = 35ea5dbeafe7d04603af2626dcf7cac09608f38cc8dd2797e0282728dd1820f4
   B MediaLab               = fabaee3b12db77e11cdbcff7b6fa5bc5d33b959c740adf5944351ac3897f65f7
   C MySpace++/studio       = c6080116f228e8d846262f10bc5e51e99a2553c1d5e825577414081ffabb2c1f
   D NVIDIA hunt            = 02fb3f4a58640943c83ad46119db8c79e4c3e51af0755f882a54247f043cec58
   E ATLAS + ~/Projects     = a03f1b0d76d6c5a23bad0deca0cf4b1cf86565cd22fa393d940fa34e491a282f

BRANCH_MERKLES (from bin/relaunch BRANCH_DEFS):
   realestate-tour  = 88293abce0433daa
   nft-mint         = 881728c78aa50884
   snap-filter      = f3aa17ff03d0500b
   clothing-store   = bd5276e8f6a38128
   game-launch      = 63cb0d06639c2cb5

LAUNCH_MERKLES (current launches):
   nft-mint-pixelwolves-85f4a8     launch=85f4a85e421513e9
   snap-filter-sparklefox-93f020   launch=93f020e2d1edda64
   game-launch-pumprush-293ee3     launch=293ee3e48fb3119d

ASSET CIDS (canonical examples from today's smoke tests):
   smoketest robot polaroid           b2f626754d98c437
   cyber-rabbit (moody-portrait tpl)  271fda28c7b3905c
   chrome frog (clean-product tpl)    43d9089b9e469893
   glass marble (render-ready tpl)    5be317bab9c1360c
   sphere truth-depth bake            (cid prefix 6a8f49fb)
```

---

## 2. REALITY MATRIX — current state on disk (Agent-E scan, 2026-06-02)

### 2.1 Shipped + proven (A-tier)

```
bin/                  factory · relaunch · vidplay · assets · chain · conductor · gpud · forge ·
                      atomize · govern (stub) · gpu  — all functional, smoke-tested
templates/            8 factory_template_v0 (clean-product, moody-portrait, render-ready-asset,
                      pixelwolves-{character,trait}, pumprush-{asset,bg}, sparklefox-filter-overlay)
branches/             5 branch_def_v0 (realestate-tour, nft-mint, snap-filter, clothing-store,
                      game-launch) — all merkles stable
launches/             3 launch_v0 instances live + serveable via vidplay /launch/<slug>/
assets/cas/           77 cid'd entries
assets/by-pass/       composite (74), depth (2 ← from today's truth-loop), mask (1)
assets/by-layer/      35 layer bands
assets/engine/three/  4 viewer projects (cutout, factory, layer_42, mygame)
forge/factory_out/    5 outputs (~2.3 MB)
loop.jsonl            5,800+ lines, live opcode chain
atoms/                11 JSON registries
ollama/router.json    8-tier ladder live
godot/project/        Godot 4.6.3 root + 14 scenes + export_presets.cfg + 2 HTML5 shells
scene_to_godot.py     spine → .tscn transpiler
passes/               registry.py (100+), fused_depth.py (5-ch), svg_layers.py — live
agent_defs/           96 .json
_workflows/           47 .json
lyv-realty-ai/        full-stack RUNNING: Next 14 dashboard + RN scanner + Rust Axum backend
                      (38 route .rs files including slugs.rs, tours.rs, trident.rs, ar.rs, glasses.rs)
gently/REGISTRY.md    159 lines — 157 crate domain registry
/home/tom/models/     39 model directories
```

### 2.2 Stub / partial (B-tier)

```
bin/govern                   45 LOC stub — functional but minimal
godot/project/cpp/           SConstruct present; .cpp/.h source absent; .so NOT BUILT
                             (blocks SpatialBridge::solve_ccd + IK gaze)
ATLAS/CLAUDE.md              40 bytes (header only)
```

### 2.3 Proposed (C-tier — referenced by docs, not built)

```
bin/tscn2tsx                 .tscn → JSX flattener (AI_SWARM_SUBSTRATE §11, TRANSFORMING_WEBSITE_PLAN §3,
                             ENGINE_AS_A_SERVICE §4) — UNBUILT
cmd_capture <bake-dir>       byproduct ingestion (ENGINE.md §34) — UNBUILT
LYV_ROUTES / scene.rs        /api/scene/<cid> handler — UNBUILT
LYV_DASHBOARD_APP / [branch] polymorphic Next.js segment — UNBUILT
EaaSBadge / DuplicateThisCTA viral components — UNBUILT
/api/share-card/<slug>.png   FLUX-into-OG-card endpoint — UNBUILT
/api/events/cid              SSE cid:new fan-out — UNBUILT
character_bundle_v1          schema extension to v0 — UNBUILT (one JSON addition)
```

### 2.4 Running services (D-tier — listening NOW)

```
:8188   ComfyUI         python3 PID 15779   LIVE
:11430  gpud            python3 PID 3070    LIVE
:11434  ollama daemon                       LIVE
:8765   (test http)                         LIVE on idle port
```

### 2.5 EaaS branch readiness (Agent-E, current launches × break-point completion)

```
realestate-tour     0%    (no launches, 4 break-points unwired)
nft-mint           25%    (1 launch: pixelwolves; image-gen only; chain/wallet unwired)
snap-filter        25%    (1 launch: sparklefox; template seeded; WebAR unwired)
clothing-store      0%    (no launches, Kolors unwired)
game-launch        20%    (1 launch: pumprush; HTML5 export untested)
AVG                14%

BUILD-READINESS SCORE: 62 / 100
  A-tier shipped:        +45
  B-tier stubs:           +5
  D-tier running:        +12
  EaaS launch coverage:  +15
  Proposed unbuilt:      −15  ← the only deduction; concentrate here
```

---

## 3. PHASE 1 — close the C-tier proposed list (the four unbuilt pieces)

The proposed-only list (§2.3) is the ENTIRE deduction in the build-readiness score. Closing it lifts the score from **62 → 85+**. Each piece below is a small, isolated unit of work; each has an executable agent prompt.

### 3.1 Build `TSCN2TSX` — `.tscn` → JSX flattener

**Constants used:** `TSCN2TSX`, `GODOT_SCENES`, `ASSETS_BIN`, `LYV_DASHBOARD_APP`
**Inputs:** the 14 `.tscn` files in `GODOT_SCENES`
**Outputs:** TSX files under `LYV_DASHBOARD_APP / "_generated"`
**Verification:** `social_panel.tscn` (simplest, pure UI) flattens cleanly + renders in `LYV_DASHBOARD`

**Executable agent prompt** (give to a sub-agent):
```
Build /data/Projects/ATLAS/bin/tscn2tsx (Python, stdlib only, ~300 LOC):
1. Parse Godot .tscn format (INI-style: [gd_scene load_steps=N format=3 uid="..."],
   [ext_resource type=... path=... id=...], [node name=... type=... parent=...], [connection signal=...]).
2. Walk the node tree; emit JSX/TSX per Godot node class via the mapping in
   AI_SWARM_SUBSTRATE.md §3 (Control→<div>, Label→<span>, Button→<button>, etc.).
3. Resolve [ext_resource path=res://…] to React imports.
4. Generate signal handlers from [connection] blocks (signal pressed → onClick).
5. Write output to LYV_DASHBOARD_APP / "_generated" / "<scene_basename>.tsx".
6. Validate by flattening GODOT_SCENES / "social_panel.tscn" — output must parse with
   `node --check` and render without runtime errors when imported into a Next.js page.
Mark CHOKE points: anything that can't translate cleanly (custom Resource files,
@tool scripts, AnimationPlayer keyframes) gets a TODO stub with the original signal.
```

### 3.2 Build `SpatialBridge.so` (the C++ native extension)

**Constants used:** `GODOT_CPP`, `GODOT_PROJECT`
**Inputs:** `GODOT_CPP / "SConstruct"` (already present)
**Outputs:** `GODOT_CPP / "bin" / "libmspc.linux.template_debug.x86_64.so"` (per `mspc.gdextension`)
**Verification:** headless Godot boot prints "SpatialBridge ready" instead of "not compiled yet — run build-cpp.sh"

**Executable agent prompt:**
```
At /data/Projects/MySpace++/studio/godot/project/, run:
  nix-shell -p scons --run "bash build-cpp.sh"
This will:
  1. git clone --depth 1 --branch 4.3-stable https://github.com/godotengine/godot-cpp (~500 MB)
  2. scons platform=linux target=template_debug -j$(nproc)
  3. scons platform=linux target=template_release -j$(nproc)
Expected result: GODOT_CPP / bin / libmspc.linux.template_*.so present.
Verify by re-running:
  bin/godot --headless --path GODOT_PROJECT -s src/backface_test.gd
Output should include "SpatialBridge ready" instead of the "not compiled yet" warning.
This unblocks IK gaze (solve_ccd), depth fusion (fuse_depth), and mirror_drift across
LIVE_ACTION_AR_CHARACTER.md §7, REALTOR_VIRTUAL_TOUR_PIPELINE.md §9, and AI_SWARM_SUBSTRATE.md §8.
```

### 3.3 Write `LYV_ROUTES / "scene.rs"` (Axum bridge)

**Constants used:** `LYV_ROUTES`, `CAS`, `ROUTE_SCENE_CID`, `ROUTE_ASSETS_CID`
**Inputs:** GET `/api/scene/<cid>` and `/api/assets/<cid>`
**Outputs:** scene bundle JSON / asset bytes streamed from `CAS / "<cid>.<ext>"`
**Verification:** `curl http://localhost:<lyv-backend-port>/api/assets/b2f626754d98c437.png` returns the today's smoke-test PNG bytes

**Executable agent prompt:**
```
Add to LYV_BACKEND / "src" / "routes" / "scene.rs":
  pub fn router() -> Router<AppState>
  - GET /api/scene/{cid} → reads ASSETS / "cas" / "{cid}.tscn", returns the parsed
    JSON-ified node tree (call tscn2tsx as a subprocess if needed for v0).
  - GET /api/assets/{cid} → streams ASSETS / "cas" / "{cid}.{ext}" with
    Cache-Control: public, max-age=31536000, immutable; Content-Type from extension.
  - Both with #[axum::handler] and tower-http compression.
Register in LYV_BACKEND / "src" / "routes" / "mod.rs".
Verify: curl returns bytes; rebuild with `cargo build` succeeds.
```

### 3.4 Schema upgrade: `character_bundle_v1`

**Constants used:** `BUNDLES`
**Inputs:** existing `character_bundle_v0` examples
**Outputs:** one JSON schema file + the existing `emit_bundle()` in `FACTORY` extended to write v1 fields when present
**Verification:** running `factory --bundle <name>` and inspecting the bundle JSON shows the new fields

**Executable agent prompt:**
```
Edit /data/Projects/ATLAS/bin/factory:
  Find emit_bundle(...). Add five new keys to the bundle dict (alongside existing):
    "instruct":          str   (from CLI flag --instruct or empty)
    "skills":            list  (from CLI flag --skills as comma list, or [])
    "allowed_signals":   list  (default ["speak","look_at","point","react","idle","dispose"])
    "bound_objects":     list  (default [])
    "opcode_vocabulary": list  (default ["RUN","MAIN","EDIT","SCAN","WRAP","ACCEPT"])
  Set "_schema" to "character_bundle_v1".
  Recompute bundle.cid as sha256 over the v1 fields (sort_keys=True).
Verify: factory "test" --bundle bundle_v1_test produces a bundle.json with all five new keys
  and a stable cid that re-runs reproduce.
```

---

## 4. PHASE 2 — wire the EaaS shell into `LYV_DASHBOARD` (the polymorphic shell)

After Phase 1, the four C-tier pieces are built. Phase 2 mounts them into the Next.js shell so the realtor friend's onboarding actually has a place to land.

### 4.1 Add the `[branch]` dynamic segment

**Constants used:** `LYV_DASHBOARD_APP`, `BRANCHES`, `LAUNCHES`, `BRANCH_MERKLES`
**Files to create:**
```
LYV_DASHBOARD_APP / "[branch]" / "layout.tsx"
LYV_DASHBOARD_APP / "[branch]" / "page.tsx"
LYV_DASHBOARD_APP / "[branch]" / "launch" / "[slug]" / "page.tsx"
```

**Executable agent prompt:**
```
Per TRANSFORMING_WEBSITE_PLAN.md §2 + §8 step 2:
1. Create the three TSX files above.
2. layout.tsx: reads BRANCHES / params.branch / "BRANCH.json", injects theme.css from
   LAUNCHES / params.slug / "theme.css" via a <link>.
3. page.tsx (branch root): renders the branch's pitch + recipe cards (from BRANCH.json).
4. launch/[slug]/page.tsx: reads LAUNCHES / params.slug / "LAUNCH.json", composes the
   index.html into RSC. Use Suspense around any factory-call-bearing component.
5. Wire to existing LYV_TAILWIND palette — add a CSS-var override for --brand per launch.
6. Verify: cd LYV_DASHBOARD && pnpm dev; open http://localhost:3001/snap-filter — branch
   landing renders. Then http://localhost:3001/snap-filter/launch/snap-filter-sparklefox-93f020
   — the actual launch page renders themed in #ff66cc.
```

### 4.2 Add the viral components

**Constants used:** `LYV_DASHBOARD_APP`, `ROUTE_SHARE_CARD`, `FACTORY`
**Files to create:**
```
LYV_DASHBOARD_APP / "_components" / "EaaSBadge.tsx"
LYV_DASHBOARD_APP / "_components" / "DuplicateThisCTA.tsx"
LYV_BACKEND / "src" / "routes" / "share_card.rs"     # /api/share-card/<slug>.png
```

**Executable agent prompt:**
```
Per ENGINE_AS_A_SERVICE.md §3:
1. EaaSBadge.tsx:
   - Footer slot, inherits `var(--brand)` so it matches the launch's theme.
   - Link to /signup?ref=<slug>.
   - Auto-suppressed when `tier !== "free"` (read from LAUNCH.json or Postgres).
   - Voice: "made with eaas." (lowercase, no emoji, per §7 microcopy).
2. DuplicateThisCTA.tsx:
   - Lower-right pill; link to /signup?ref=<slug>&prefill=<template_id>.
   - Only on Free tier launches.
3. share_card.rs: GET /api/share-card/<slug>.png → reads LAUNCHES/<slug>/LAUNCH.json,
   composes a prompt for FACTORY, returns the resulting PNG cached in Redis by slug cid.
4. Add <meta property="og:image" content="/api/share-card/<slug>.png"> to launch/[slug]/page.tsx.
5. Verify: open a Free launch, view source — meta is present; render the meta URL — get a 1200x630
   PNG with the launch hero baked in.
```

### 4.3 Wire `/api/factory` and `/api/events/cid`

**Constants used:** `LYV_DASHBOARD_APP`, `FACTORY`, `ROUTE_EVENTS_CID`, `MANIFEST`
**Files to create:** `LYV_DASHBOARD_APP / "api" / "factory" / "route.ts"` (Node runtime),
`LYV_DASHBOARD_APP / "api" / "events" / "cid" / "route.ts"` (SSE Node runtime)

**Executable agent prompt:**
```
1. /api/factory route.ts (Node runtime): POST { prompt, template?, seed?, bundle? } →
   spawn FACTORY via subprocess, capture stdout JSON, return { cid, path, share }.
2. /api/events/cid route.ts (Node runtime): GET → SSE stream of cid:new events.
   Subscribe to a Redis pub/sub channel (or inotify on CAS if Redis not wired yet).
3. Test: open a browser console on LYV_DASHBOARD, run:
     const es = new EventSource('/api/events/cid');
     es.onmessage = (e) => console.log('NEW CID:', e.data);
   Then in another terminal: factory "test prompt" --quiet
   Expected: the browser logs the new cid within ~10 seconds.
```

---

## 5. PHASE 3 — close the swarm loop (opcode bursts in the renderer)

After Phase 2, the shell is polymorphic and the API is wired. Phase 3 puts the agentic swarm INSIDE the renderer per `AI_SWARM_SUBSTRATE.md` + `ENGINE_AS_A_SERVICE.md §5`.

### 5.1 Wire `/api/chain/burst`

**Constants used:** `LYV_BACKEND`, `CHAIN`, `LOOPJSONL`, `GPUD`, `ROUTE_CHAIN_BURST`
**Files to create:** `LYV_BACKEND / "src" / "routes" / "chain_burst.rs"`

**Executable agent prompt:**
```
Per ENGINE_AS_A_SERVICE.md §5:
1. POST /api/chain/burst body schema:
   { burst_id, scene_cid, character_cid, context_window, allowed_opcodes,
     allowed_signals, tier:"qwen2.5:0.5b", max_tokens, prompt }
2. Route handler:
   a. Validate burst_id is unique (Redis SET NX with 60s TTL).
   b. Build LLM prompt that constrains output to JSON of shape:
        { opcode: <one of allowed_opcodes>, signal: <one of allowed_signals>, args: {} }
   c. Call gpud at GPUD URL with model=tier, max_tokens=max_tokens, format=json.
   d. Parse response → run `chain mismatch` validation:
        - opcode must be in allowed_opcodes
        - signal must be in allowed_signals
        - args.target (if present) must be a node name in scene_cid
   e. If valid: append to LOOPJSONL via CHAIN add → return the parsed response.
   f. If invalid: return { opcode: "idle" } and log the rejection.
3. Verify: POST a burst, get a valid opcode response, see new line in LOOPJSONL with
   the right scene_cid and character_cid fields.
```

### 5.2 Drive a character through one burst end-to-end

**Constants used:** `GODOT_SCENES / "social_panel.tscn"`, `BUNDLES / "<name>" / "bundle.json"` (v1)

**Executable agent prompt:**
```
Per ENGINE_AS_A_SERVICE.md §11 (realtor friend onboarding, week 5):
1. Build a character_bundle_v1 for "realtor host" with:
   - instruct: "Greet visitor by first name if present. Point to one feature. Offer a tour."
   - allowed_signals: ["speak","look_at","point","react","idle","dispose"]
   - allowed_opcodes: ["RUN","MAIN","EDIT","SCAN","WRAP","ACCEPT"]
   - voice_clone.speaker_code: Q3-TTS embedding (or null if not yet cloned)
2. Trigger via fetch from the snap-filter test launch page:
     fetch(ROUTE_CHAIN_BURST, { method: 'POST', body: JSON.stringify({
       burst_id: crypto.randomUUID(),
       scene_cid: '<social_panel cid from bin/assets>',
       character_cid: '<bundle cid>',
       context_window: ['dwell_ms:1200', 'cursor_on:kitchen_island_marker'],
       allowed_opcodes: ['RUN','MAIN','EDIT','SCAN','WRAP','ACCEPT'],
       allowed_signals: ['speak','look_at','point','react','idle'],
       tier: 'qwen2.5:0.5b',
       max_tokens: 120,
       prompt: 'Visitor dwelling on kitchen island. Greet by gesture, name one feature.'
     }) })
3. Expected: { opcode: 'MAIN', signal: 'point', args: { target: 'kitchen_island_marker',
   speak_after_ms: 400, line: '...' } }
4. Reject test: pass a target NOT in the scene's cid (e.g. 'wine_cellar') — chain mismatch
   rejects → response is { opcode: 'idle' }.
```

---

## 6. PHASE 4 — switch on revenue (realtor friend onboards)

After Phase 3, the swarm is closed-loop. Phase 4 ships the first paid SKU per `ENGINE_AS_A_SERVICE.md §9` Milestone 2.

### 6.1 Compose `realtor.cozy-cottage.001` template_v0

**Constants used:** `TEMPLATES`, `BRANCH_MERKLES["realestate-tour"]`, `SCENE_TO_GODOT`, `BUNDLES`

**Executable agent prompt:**
```
Write TEMPLATES / "realtor.cozy-cottage.001.json" with the template_v0 schema
(per ENGINE_AS_A_SERVICE.md §2):
{
  "schema": "template_v0",
  "id": "realtor.cozy-cottage.001",
  "branch_merkle": "88293abce0433daa",
  "parent_root": "106b80ac...",
  "design_tokens": { colors, type, motion per §7 of EAaS doc },
  "scenes": [{ "path": "scenes/realestate_walkthrough_full.tscn", "cid": "<from assets>" }],
  "characters": [{ "role": "host", "bundle_cid": "<v1 cid>",
                   "instruct": "...", "allowed_signals": [...], "allowed_opcodes": [...] }],
  "payment": { "provider": "stripe", "plan_id": "tpl_realtor_pro" },
  "tier": "pro",
  "price_usd_month": 49
}
Verify: bin/relaunch realestate-tour --brand "<her brokerage>" --tagline "..." --color "#d4a373"
  --listing-name "<her listing>" --style "warm" --scripted
  → produces LAUNCHES / realestate-tour-<her-slug>-<merkle>/ with the template's tokens applied.
```

### 6.2 Wire Stripe through the existing backend

**Constants used:** `LYV_BACKEND / "src" / "routes" / "billing.rs"` (NEW), `LYV_ROUTES`

**Executable agent prompt:**
```
Per BUSINESS_BUILD_PLAN.md §4 Week 4:
1. Add Stripe SDK to LYV_BACKEND Cargo.toml (async-stripe crate).
2. Create LYV_ROUTES / "billing.rs" with:
   - POST /api/billing/subscribe { template_id, customer_email } → creates Stripe Checkout session
   - POST /api/billing/webhook → handles stripe events; on subscription.created, writes
     a row in Postgres `subscriptions` table with { customer_id, template_id, slug, branch_merkle }.
3. Validate: stripe trigger checkout.session.completed → backend writes a row → slug becomes active.
4. Test with the realtor friend as customer #1: she runs the full /signup flow, picks the
   Pro tier, Stripe charges $49, her LAUNCHES dir gets a new launch with tier="pro" in LAUNCH.json.
```

### 6.3 Open the referral flywheel

**Constants used:** `LYV_DASHBOARD_APP / "signup" / "page.tsx"`, `LYV_BACKEND / "src" / "routes" / "referral.rs"`

**Executable agent prompt:**
```
Per ENGINE_AS_A_SERVICE.md §3:
1. /signup?ref=<slug> reads the ref param, persists it as a hidden form field, posts to
   /api/billing/subscribe with referral_slug.
2. /api/referral records the edge in Postgres `referrals` (referrer_slug, referred_customer_id,
   started_at, expires_at = started_at + 12 months).
3. Monthly job: for each active referral, credit 20% of the referred customer's
   subscription to the referrer's Stripe Connect account (or hold as platform credit
   if Stripe Connect isn't wired yet).
4. Verify: the realtor friend shares her slug, a visitor signs up at /signup?ref=<her>,
   referrals table gets a row, her account shows pending credit.
```

---

## 7. PHASE 5 — the next 5 atomic moves (the build order in execution form)

Pick the next 5 hours of build time. These are the atomic steps that, in this order, do the most for the build-readiness score.

```
TASK 1 — Build SpatialBridge.so (§3.2)
  estimate:     ~5 min wall-clock + ~5 min compile + ~500 MB godot-cpp clone
  constants:    GODOT_CPP, GODOT_PROJECT
  unblocks:     IK gaze + fuse_depth + mirror_drift across 3 docs
  agent_prompt: §3.2 above

TASK 2 — Write bin/tscn2tsx (§3.1)
  estimate:     ~3 hours (Python, stdlib, ~300 LOC)
  constants:    TSCN2TSX, GODOT_SCENES, LYV_DASHBOARD_APP
  unblocks:     the entire Phase 2 polymorphic shell
  agent_prompt: §3.1 above

TASK 3 — Add the [branch] segment + first launch page (§4.1)
  estimate:     ~4 hours (3 TSX files + theme injection + Suspense)
  constants:    LYV_DASHBOARD_APP, BRANCHES, LAUNCHES, BRANCH_MERKLES
  unblocks:     the realtor friend's URL has a destination
  agent_prompt: §4.1 above

TASK 4 — Wire /api/factory + /api/events/cid (§4.3)
  estimate:     ~2 hours (two Node-runtime route handlers + SSE wiring)
  constants:    LYV_DASHBOARD_APP, FACTORY, ROUTE_EVENTS_CID
  unblocks:     the closed-loop CID round trip end-to-end
  agent_prompt: §4.3 above

TASK 5 — Compose realtor.cozy-cottage.001 + Stripe webhook (§6.1 + §6.2)
  estimate:     ~6 hours (template JSON + Stripe SDK + billing.rs + webhook test)
  constants:    TEMPLATES, BRANCH_MERKLES["realestate-tour"], LYV_BACKEND
  unblocks:     the realtor friend's first paid signup
  agent_prompt: §6.1 + §6.2 above
```

**Total estimated time: ~15 wall-clock hours** to reach BUILD_READINESS = 85+ and the first paid SKU shipped. Per `ENGINE_AS_A_SERVICE.md §11` this is the realtor friend's week 5.

---

## 8. THE VERIFICATION CHAIN

Each phase produces a verifiable signal. The signals stack so the agent + user can audit progress without re-reading the docs.

```
Phase 1 verification:
  ✓ ls GODOT_CPP / "bin" / "libmspc.linux.*.so" returns 2 files
  ✓ Godot headless boot prints "SpatialBridge ready"
  ✓ bin/tscn2tsx social_panel.tscn → LYV_DASHBOARD_APP/_generated/social_panel.tsx
    parses with `node --check`
  ✓ curl /api/assets/<known-cid> returns bytes
  ✓ factory "...test..." --bundle v1test produces bundle with all 5 new v1 keys

Phase 2 verification:
  ✓ http://localhost:3001/snap-filter shows branch landing themed in Lyv-purple
  ✓ http://localhost:3001/snap-filter/launch/snap-filter-sparklefox-93f020 renders
    with #ff66cc theme and the sparklefox logo
  ✓ EaaSBadge appears in the Free-tier launch footer
  ✓ /api/share-card/sparklefox.png returns a 1200x630 PNG
  ✓ /api/events/cid streams a new cid event when factory finishes

Phase 3 verification:
  ✓ POST /api/chain/burst with valid args returns a structured opcode
  ✓ POST with an out-of-bounds target returns { opcode: "idle" } via chain mismatch
  ✓ LOOPJSONL gains a new line with the right scene_cid + character_cid

Phase 4 verification:
  ✓ Stripe test webhook flows through → subscriptions row written
  ✓ /signup?ref=<slug> records a referral row
  ✓ relaunch tree shows the new realtor.cozy-cottage launch under the
    realestate-tour branch leaf (88293abce0433daa)
  ✓ realtor friend completes onboarding in <30 min wall-clock, has a billable URL
```

---

## 9. THE MERGE-BACK STEP — every output joins the manifest

Each phase emits new cids that join `CAS` and become referenceable in §1 of THIS doc on next re-read. The merge step is automatic and is the literal closure of the merkle DAG: today's expensive work is tomorrow's free input.

```
new outputs of every phase           →    bin/assets scan automatically
                                          register as a new cid under CAS / "<cid>.<ext>"
                                          + symlinks into BYPASS / BYLAYER / BYTYPE / BYNAME
                                          + an entry in MANIFEST
                                          + a line in LOOPJSONL (opcode=EDIT or ACCEPT)
                                          + an SSE event on ROUTE_EVENTS_CID
                                          + visibility from every branch's RSC query
```

When the system-state changes meaningfully, **re-run** the five Agent-A through Agent-E
scans (per `BUSINESS_BUILD_PLAN.md` Appendix B reproducibility snippet),
recompute the `SYSTEM_MERKLE_ROOT`, diff sub-trees, and **only the affected sub-trees
re-bake**. Everything else stays cached. The seven-doc suite + this manifest evolve
together because the substrate evolves together.

---

## 10. APPENDIX A — full path-to-doc cross-reference

Every file path declared in §1 maps to a doc that explains its role:

```
ATLAS                       BUSINESS_BUILD_PLAN.md (the substrate root)
FACTORY                     ENGINE_AS_A_SERVICE.md §4 (the prompt → cid pipeline)
RELAUNCH                    ENGINE_AS_A_SERVICE.md §2 (the template = unit of sale)
VIDPLAY                     ENGINE_AS_A_SERVICE.md §3 (the current friends-only slug server)
ASSETS_BIN                  REALTOR_VIRTUAL_TOUR_PIPELINE.md §6 (cid + by-pass)
CHAIN                       AI_SWARM_SUBSTRATE.md §1 piece 7 (opcode chain)
GPUD                        BUSINESS_BUILD_PLAN.md §7 (GPU policy)
TSCN2TSX                    AI_SWARM_SUBSTRATE.md §11, TRANSFORMING_WEBSITE_PLAN.md §8.1
GODOT_SCENES                GAMES_PLATFORM.md §2 (the 12 published games + 2 utility)
GODOT_CPP                   LIVE_ACTION_AR_CHARACTER.md §7 (SpatialBridge IK gaze)
SCENE_TO_GODOT              GAMES_PLATFORM.md §7 (universal scene format)
PASSES_FUSED_DEPTH          REALTOR_VIRTUAL_TOUR_PIPELINE.md §1 (5-channel fusion)
PASSES_SVG_LAYERS           AI_SWARM_SUBSTRATE.md §5 (vectorised inference shell)
TESSERACT_SVG               AI_SWARM_SUBSTRATE.md §5 (scene → SVG projection)
AGENT_DEFS                  AI_SWARM_SUBSTRATE.md §1 (96 tiny boxes)
LYV_DASHBOARD               TRANSFORMING_WEBSITE_PLAN.md §1 (the Next.js shell)
LYV_SCANNER                 TRANSFORMING_WEBSITE_PLAN.md §6 (the RN companion)
LYV_BACKEND                 TRANSFORMING_WEBSITE_PLAN.md §1 (Rust Axum + 38 routes)
LYV_TAILWIND                TRANSFORMING_WEBSITE_PLAN.md §1 (Lyv brand palette)
M_VGGT, M_COTRACKER3,
M_DEPTHPRO, M_MARIGOLD,
M_TRELLIS, M_SF3D,
M_SAPIENS, M_Q3TTS,
M_FINEGRAIN, M_LONGCAT,
M_LTX, M_GEMMA, M_MARLIN    REALTOR_VIRTUAL_TOUR_PIPELINE.md §2 (the asset map)
COMFY                       BUSINESS_BUILD_PLAN.md §1 (ComfyUI + 47 workflows)
WORKFLOW_TXT2IMG            ENGINE_AS_A_SERVICE.md §4 (FLUX-schnell base workflow)
SYSTEM_MERKLE_ROOT          all 7 docs (the closure)
BRANCH_MERKLES              ENGINE_AS_A_SERVICE.md §0 (the 5 boxes)
LAUNCH_MERKLES              ENGINE_AS_A_SERVICE.md §11 (the realtor friend's flow)
opcodes (RUN/MAIN/EDIT/...) AI_SWARM_SUBSTRATE.md §1 + §8 (the action surface)
PASS_TOKENS                 REALTOR_VIRTUAL_TOUR_PIPELINE.md §6 (the LAYER_STACK)
```

---

## 11. APPENDIX B — agent execution contract

When an agent picks up a phase task, it MUST:

1. **Read** this manifest's §1 (the canonical constants) FIRST.
2. **Read** the doc referenced in §10 for the task it's executing.
3. **Reference** constants by NAME from §1, never re-declare them.
4. **Emit** every artifact through `ASSETS_BIN scan` so it joins `CAS` + `MANIFEST`.
5. **Append** at least one row to `LOOPJSONL` describing the work (opcode `EDIT` for
   code change, `ACCEPT` for milestone, `RUN` for execution).
6. **Verify** against the matching checklist row in §8.
7. **Report** the new `SYSTEM_MERKLE_ROOT` if §1's constants changed (e.g. new model
   on disk → new A scan root → new system root).

When a HUMAN picks up the next move:
1. **Re-read this manifest.** §1 is the ground truth; §2 is the live state; §3–§6 are
   the executable plan.
2. **Pick the next atomic task** from §7 (the 5 ranked moves).
3. **Run it OR delegate** to an agent using the corresponding §3/§4/§5/§6 prompt.

---

## 12. APPENDIX C — system merkle (closure)

```
SYSTEM_MERKLE_ROOT  = 106b80ac5878c4636f0e37822f029289980568f73349350e0e6cdbb0fbd836ad
BUILD_READINESS    = 62 / 100   (Agent-E reality check, 2026-06-02)
TARGET_READINESS   = 85 / 100   (after Phase 1 closes C-tier proposed list)
NEXT_MILESTONE     = realtor friend's first paid slug live (≤ week 5 per EaaS §11)
SUITE_LINE_COUNT   = 5,400+ lines across 7 design docs + this manifest
```

Re-run the scan, recompute the root, diff sub-trees, only re-bake what changed.
**The substrate is the product. The manifest is the substrate's index. The build
plan is the manifest in motion.**

---

*End of canonical agentic build manifest.*
