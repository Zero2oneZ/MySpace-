# GAMES PLATFORM — MASTER DESIGN
## Prebuilt catalogue + Build-Your-Own-Games-as-a-Service

> **Status:** v1 design synthesis · 2026-06-01
> **Owner:** Tom Lee (Zero2oneZ)
> **Sibling docs:**
> – [`REALTOR_VIRTUAL_TOUR_PIPELINE.md`](REALTOR_VIRTUAL_TOUR_PIPELINE.md) — pre-rendered tours
> – [`LIVE_ACTION_AR_CHARACTER.md`](LIVE_ACTION_AR_CHARACTER.md) — live AR characters
> **System merkle root (shared, "what we have today"):**
> `106b80ac5878c4636f0e37822f029289980568f73349350e0e6cdbb0fbd836ad`
>
> Third in the series. Same substrate, third product surface: **games**.
> Two delivery modes from one engine:
> 1. **Prebuilt catalogue** — 14 already-authored Godot scenes ship as published games
>    via Godot HTML5 export → Facebook Instant Games + slug URLs
> 2. **Build-Your-Own-Games-as-a-Service (BYOG)** — creator prompts in plain English,
>    the pipeline assembles assets + scene + logic, ships a playable game in minutes
>
> This is the "most advanced fastest we can get" — built from already-paid-for parts.

---

## 0. The product

**A two-sided games platform: ready-to-play catalogue + creator-built games as a service,
both running on the same Godot 4.6.3 + WebGL/WebXR substrate and shared asset cache.**

Three actors:
1. **Player** — opens a URL or Facebook Instant Games entry, plays in browser, optionally on Meta glasses
2. **Creator** — types a prompt, watches the pipeline assemble + publish a game in minutes-to-hours
3. **Publisher** (us / platform owner) — curates the catalogue, takes a revenue split

**The bargain we make with the player:**
- No download — WebGL/WebXR in any modern browser
- Same character/avatar travels across **every** game (cross-game identity)
- Multiplayer comes free where the game wants it (WebRTC P2P)
- Same Q3-TTS-cloned voices, same AI NPCs as the live-AR doc

**The bargain we make with the creator:**
- Plain-English prompt → playable game in **<5 min** for template-derived, **<30 min** for novel
- Every asset they make is **cid'd** and joins the shared catalogue (becomes reusable royalty share)
- Built-in distribution: their slug URL, optional Facebook Instant Games packaging, optional Meta glasses build

**The bargain we make with compute:**
- 14 scenes already authored → instant catalogue at zero marginal cost
- Asset gen (T4) is **creator-time only**, cached forever
- Runtime is **T0/T1/T2** (same cost ladder as the other docs)
- LLM is async, scoped to gameplay events, never blocks render

---

## 1. The cost ladder — same rules, game-specific tier choices

| tier | technique | role in this product |
|---|---|---|
| **T0** | scene.json spine + symlinked assets + Godot SceneTree | scene composition |
| **T1a** | back-face cutout for character / level geometry | free occlusion + parallax (same proof as the other docs) |
| **T1b** | matcap baked per-level lighting | scene matches its art direction without runtime light sim |
| **T2a** | per-level lightmap (Blender Cycles, one bake) | photoreal mode for hero games |
| **T2b** | screen-space AO | grounding |
| **T2c** | matcap + SSAO + cutout combined (the archviz sweet spot) | most levels live here |
| **T3** | Forward+ PBR with shadows | premium toggle (creator-controlled, usually off) |
| **T4a** | NN delight on source art | creator-time art polish |
| **T4b** | img → 3D (stable-fast-3d / TRELLIS) | creator-time mesh build |
| **T4c** | img → video (LTX / HunyuanVideo / Wan) | creator-time intro/cinematic baking |
| **T4d** | LLM → game asset (level layout, dialog tree, quest descriptor) | creator-time content generation, **runtime NPC behavior** |

### Runtime tier choices (the hard constraints)

| stage | tier | budget |
|---|---|---|
| frame render | T0 + T1a + T1b + T2b | 16 ms / frame (60 fps) |
| character occlusion | T1a × scene depth | <0.5 ms / frame |
| NPC lipsync | amplitude blendshape from Kokoro stream | <0.5 ms / frame |
| IK gaze + reach | SpatialBridge `solve_ccd` / `solve_two_bone` | <0.1 ms / frame |
| physics | Godot built-in + SpatialBridge `fuse_depth` for AR variants | <2 ms / frame |
| multiplayer state sync | Yjs CRDT over WebRTC | async, ~50 ms p95 |
| NPC dialog (LLM) | Gemma-4-E4B-it / Marlin-2B at edge | <500 ms first token |
| TTS streaming | Kokoro | <50 ms first chunk |
| asset gen during play (rare, opt-in) | T4b/T4c capped to ~1 per minute per player | budget-bounded |

### Hard "do nots" at runtime

- ❌ No diffusion in the render loop
- ❌ No img→3D in the render loop
- ❌ No img→video in the render loop
- ❌ No server-side rendering — everything visual is client-side WebGL/WebXR
- ❌ No cloud GPU round-trip in the per-frame path (only in async game-event paths)

### The architectural collapse, restated for games

**Render in T0/T1/T2. Generate assets in T4 at creator-time. Cache the boundary in
ATLAS by cid. The same scene runs at 60 fps on a phone or 144 Hz on a desktop with no
code change.** This is why the platform can promise "creator prompt to playable in
minutes" — the expensive work is bounded to the asset-gen step, everything downstream
is free.

---

## 2. Asset inventory — the catalogue we already own

### The 14 prebuilt scenes (already authored, ready to ship)

From `MySpace++/studio/godot/project/scenes/` (verified by Agent C scan):

| scene | what it is | publish-as-game template |
|---|---|---|
| `main.tscn` | hub / launcher | platform launcher |
| `realestate_walkthrough_full.tscn` | property tour with camera spline | **archviz tour** (overlaps realtor doc) |
| `pump_surf.tscn` + `pump_surf_pipeline.tscn` | pump.fun surfer | **endless runner / crypto-tied arcade** |
| `morphing_game.tscn` | morph-engine canvas play | **creative sandbox** |
| `forest_clearing_dawn_world_a7316b8d.tscn` | atmospheric world scene | **walking simulator** |
| `2d_pixel_platformer_2b1633b7.tscn` | side-scroll platformer | **2D platformer** |
| `stylized_2d_topdown_6bb5d96b.tscn` | 2D topdown | **Zelda-class topdown** |
| `planet_map.tscn` | procedural planet | **exploration / map sandbox** |
| `avatar_rigged.tscn` | character display | **avatar studio / character showcase** |
| `chain_render_wall.tscn` + `chain_render_wall_compiled.tscn` | rendered gallery wall | **render gallery / NFT showroom** |
| `asset_3d_gallery.tscn` | 3D asset browser | **3D model gallery** |
| `social_panel.tscn` | social feed UI | **social hub overlay** |

**These ship as 12 distinct game templates from day one.** Zero new code; each gets a
slug URL via lyv-realty-ai shell + Godot HTML5 export + Facebook Instant Games packaging.

### Engine + autoload substrate (already wired)

`project.godot` declares 10 autoloads — every game inherits them for free:

| autoload | function | game use |
|---|---|---|
| `VMNavigator` | VM graph walking + SHA-256 crystal hashing | deterministic state across save/load |
| `ChainRunner` | async chain execution | tutorial/quest step sequencing |
| `TaskManager` | task queue + flush | mission tracking |
| `SymIndexer` | symbol table CRUD | game-script symbol lookup |
| `CCBridge` | Claude/Anthropic bridge | dynamic dialog generation |
| `SocialClient` | localhost:8765 social bridge | leaderboards, friends |
| `MetaXRBridge` | Quest XR integration | VR mode (already proven via `meta_xr_mocap_emit.gd`) |
| `FacebookSDKBridge` | FB Instant Games SDK | platform deployment |
| `ScenePlanLoader` | spine-format scene loader | dynamic level construction |
| `ChainRenderBridge` | render proxy polling | async render insertion (cinematics) |

### Capability ↔ tool map (carries over from the other docs)

The exact same 30+ models + 47 workflows + 96 agent_defs catalogued in the realtor + live-AR
docs apply here. Highlights for games:

- **Godot 4.6.3 + `bin/godot` wrapper + `engine.env.path`** — the runtime + builder
- **C++ `SpatialBridge` + `IKSolver`** (`.so` NOT BUILT) — physics + IK at native speed
- **Blender + `avatar_bake.py` LAYER_STACK** — creator-time PBR bakes
- **`scene_spine.json` + `spine_ops.py`** — universal scene format
- **`scene_to_godot.py`** — spine → SceneTree transpiler (and a Three.js branch we landed today)
- **`floorplan_to_spine.py`** — 2D → 3D scene (already in service for realestate)
- **VGGT + cotracker3 + DepthPro + Marigold** — world capture from video (creator-time)
- **TRELLIS / stable-fast-3d** — img → 3D meshes (creator-time)
- **FLUX-dev + Qwen_Image_Edit_2511** — img → img (creator-time art)
- **LTX2.3-Studio + Wan2.1-T2V-14B** — img → video (creator-time cinematics)
- **LongCat-Video-Avatar-1.5** — character animation library bake
- **Q3-TTS clone + Kokoro stream + Whisper STT** — NPC voice loop
- **Sapiens-1b** — player body parse (AR variants)
- **Gemma-4-E4B-it + Marlin-2B** — edge LLM for NPCs / quests / dialog
- **ATLAS `bin/assets`** — content-addressed asset cache → games share catalogues
- **ATLAS `bin/conductor`** — density-math agent team for creator's prompt
- **ATLAS `bin/forge`** — backward-resolve minimal valid workflow from creator's intent
- **ATLAS `bin/gpud`** — GPU governor for creator-time asset bakes
- **MediaLab `pipeline_ml.py`** — TF-IDF + Markov + beam search workflow predictor
- **ComfyUI + 47 pre-authored workflows** — production graph for asset gen
- **lyv-realty-ai (10 GB Rust + Next.js)** — slug-URL shell, perfect reuse for game pages
- **`FACEBOOK_INSTANT_GAMES_PLAYBOOK.md`** in this docs/ dir — the FB Instant Games deployment path is **already documented**

### What's NOT here (same gaps, same workarounds)

| gap | impact | workaround |
|---|---|---|
| IC-Light | no per-frame relight | matcap (T1b) per level + Blender lightmap (T2a) for hero scenes |
| gsplat trainer | no Gaussian-splat | VGGT mesh → back-face cutout (T1a) at ~3% the cost |
| Cosmos-Reason1-7B weights | no in-game world-model planner | metadata at `gently/.consolidation/run19b_spatial/`; download to add as "AI director" for v3 |
| audio-flamingo-2 weights | no phoneme-driven lipsync | amplitude lipsync covers it; download for v2 polish |
| `SpatialBridge.so` not built | physics + IK in stubs | `nix-shell -p scons --run "bash build-cpp.sh"` — one-time |

---

## 3. Three actor flows

### A. Player (consumer)

```
TIME COMMITMENT:  <5 seconds from URL-click to playing

  1. URL or Facebook Instant Games entry           (~0 — link click)
  2. browser loads Godot HTML5 bundle              (~1–3 s — ~5 MB cached aggressively)
  3. WebXR session attaches if device supports     (~0.5 s, optional)
  4. Player's cross-game character mounts          (~0 — cached client-side)
  5. game starts at last-known save state          (~0 — server KV)
  6. multiplayer room joined if applicable          (~0.5 s — WebRTC handshake)

OUTPUT: player is playing.  Game writes per-player state to server KV; the cross-game
character carries forward unchanged.
```

### B. Creator (BYOG, the as-a-Service flow)

```
TIME COMMITMENT:  <5 min for template-derived, <30 min for novel, hours for polish

  1. PROMPT:  "make me a roguelike where I'm a chef in a haunted kitchen"
                (free-form English, optional refs / style images / voice samples)

  2. INTENT PARSE:  ATLAS `bin/conductor` density-math team assembly +
                    `bin/forge` backward-resolve minimal valid workflow
                    → "I need: 1×scene_template, 1×player_character, 8×kitchen_props,
                       4×ghost_npc, dialog_tree, level_layout, music_bed"
                    (~10 s, LLM-driven)

  3. SCAFFOLD:  match prompt → closest of the 12 existing templates
                ("roguelike" + "kitchen" → start from `stylized_2d_topdown_6bb5d96b`)
                → clone scene, swap art-direction tags
                (~5 s)

  4. ASSET GEN (parallelized across GPUs via `bin/gpud`):
                ├─ kitchen props: FLUX gen + finegrain matte + stable-fast-3d
                ├─ ghost NPCs:    FLUX gen + matte + stable-fast-3d + photo_to_avatar_rigged
                ├─ player chef:   creator's reference + photo_to_avatar_rigged
                ├─ voices:        Q3-TTS clone per NPC personality
                ├─ animations:    LongCat-Video-Avatar bakes (idle, walk, attack, hit, die)
                ├─ music:         (future: when audio-gen lands)
                └─ env shader:    matcap probe for "haunted kitchen" vibe
                (parallel, ~3–10 min depending on prompt complexity)

  5. SCENE ASSEMBLY:  spine_ops compose → scene.json spine →
                      scene_to_godot.py → .tscn + .gd controllers
                      (~30 s)

  6. GAME LOGIC:  LLM emits GDScript HOOKS bound to scene signals
                  + behavior trees for NPCs (deterministic + replayable)
                  + dialog tree (driven by edge LLM at runtime)
                  + quest descriptors (TaskManager autoload consumes)
                  (~30 s)

  7. BAKE + EXPORT:  Blender lightmap bake (T2a, optional, hero levels)
                     + Godot HTML5 export (one `godot --headless --export-debug` pass)
                     + Facebook Instant Games packaging (optional, automated)
                     (~1–3 min)

  8. PREVIEW:  creator plays in browser; iterate by re-running steps 4–7
               with targeted edits ("the ghosts are too friendly, make them scarier")
               (live)

  9. PUBLISH:  slug URL goes live + Facebook Instant Games published if opted in
               creator's revenue split is auto-configured

OUTPUT: game/<game_cid>/ → ATLAS, slug URL live, every cid'd asset added to shared catalogue
```

### C. Publisher / catalogue curator (us)

```
ONGOING:

  • feature catalogue games on the platform home
  • set revenue splits + payment rails
  • curate cross-game asset sharing (royalty paid back when assets are reused)
  • track player metrics (the dataset byproducts power retention models)
  • run platform LLM that recommends "you might also like" across games
  • host the Facebook Instant Games partner integration
```

---

## 4. The DAG — full ordering

```
                        [PREBUILT CATALOGUE — zero marginal cost]
                                          │
                  the 14 existing scenes in scenes/ + autoloads
                                          │
                                          ▼
                          Godot HTML5 export per scene
                          (godot --headless --export-debug)
                                          │
                                          ▼
                          per-game slug URL via lyv-realty-ai
                          + optional Facebook Instant Games package
                          (FACEBOOK_INSTANT_GAMES_PLAYBOOK.md already documented)
                                          │
                                          ▼
                          CATALOGUE OF 12 PUBLISHED GAMES READY DAY ONE


                        [BYOG — creator-prompted game]
                                          │
                              creator prompt + optional refs
                                          │
                                          ▼
                          ATLAS `bin/conductor` density-math team
                          + `bin/forge` backward-resolve
                          → workflow plan with capability slots filled
                                          │
                                          ▼
                          MediaLab `pipeline_ml.py`
                          (TF-IDF + Markov + beam search)
                          autonomously chains ComfyUI nodes
                                          │
                ┌──────────────────────────┼──────────────────────────┐
                ▼                          ▼                          ▼
        scene template select      asset generation             game logic
        (closest of 12 OR          (parallel via bin/gpud)      generation
         spine-gen new layout)                                  (LLM → GDScript
                │                          │                     hooks + behavior
                │                          │                     trees + dialog
                │                          │                     trees + quest
                │                          │                     descriptors)
                │                          │                          │
                │                          ▼                          │
                │          per-asset pipelines (T4-tier):              │
                │          ├─ art:   FLUX / Qwen_Image_Edit            │
                │          ├─ matte: finegrain / SAM2                  │
                │          ├─ 3D:    stable-fast-3d / TRELLIS          │
                │          ├─ rig:   photo_to_avatar_rigged.v0         │
                │          ├─ anim:  LongCat-Video-Avatar bake         │
                │          ├─ voice: Q3-TTS clone                      │
                │          ├─ video: LTX2.3 / Wan21 (cinematics)       │
                │          └─ light: matcap probe + lightmap bake      │
                │                          │                          │
                │                          ▼                          │
                │          every asset → cid → ATLAS by-type/3d/      │
                │          catalogue grows monotonically              │
                │                          │                          │
                └──────────────────────────┼──────────────────────────┘
                                          ▼
                          SCENE ASSEMBLY
                          spine_ops compose → scene.json spine
                          → scene_to_godot.py → .tscn + .gd
                                          │
                                          ▼
                          BAKE + EXPORT
                          (optional T2a lightmap)
                          + Godot HTML5 export
                          + optional FB Instant Games package
                                          │
                                          ▼
                          PREVIEW → ITERATE → PUBLISH
                                          │
                                          ▼
                          game/<game_cid>/ live at slug URL


                        [RUNTIME — per player session]
                                          │
                              browser opens URL / FB IG entry
                                          │
                ┌──────────────────────────┼──────────────────────────┐
                ▼                          ▼                          ▼
        fetch game/<cid>/             player's avatar.glb       multiplayer room
        (cached, immutable,           (cross-game identity      (WebRTC + Yjs CRDT)
         CDN'd)                        from live-AR doc)
                                          │
                                          ▼
                          Godot HTML5 boots
                          autoloads init: VMNavigator, ChainRunner,
                          TaskManager, SymIndexer, CCBridge, SocialClient,
                          MetaXRBridge, FacebookSDKBridge, ScenePlanLoader,
                          ChainRenderBridge
                                          │
                                          ▼
                          RENDER LOOP   60 fps target
                          T0 spine + T1a cutout + T1b matcap + T2b SSAO
                                          │
                                          ▼
                          GAMEPLAY LOOP
                          ┌─ player input ─┐
                          │ NPC behavior trees (deterministic)
                          │ NPC dialog (async edge LLM)
                          │ quest progression (TaskManager)
                          │ multiplayer state diff (Yjs CRDT)
                          │ TTS streaming (Kokoro)
                          │ amplitude lipsync (~30 LOC JS / GD)
                          │ IK gaze / point (SpatialBridge solve_ccd)
                          └─ player render ─┘
                                          │
                                          ▼
                          PERSISTENCE
                          ─ player state → server KV (per-game)
                          ─ cross-game character → unchanged
                          ─ catalogue contribution stats (royalty tracking)
                          ─ session telemetry → dataset byproducts
                                          │
                                          ▼
                          OPTIONAL: ON-DEMAND ASSET GEN
                          (capped to ~1/min/player)
                          rare, surprise content; budget-bounded by gpud
```

---

## 5. Pre-render vs realtime — the games split

| stage | mode | cost | cached as |
|---|---|---|---|
| scene templates (the 14) | **already authored** | $0 marginal | tscn files |
| asset generation (art, mesh, anim, voice) | **pre-render** (creator time) | minutes per asset | `game/<cid>/assets/` + ATLAS by-type/3d |
| scene assembly | **pre-render** | seconds | `game/<cid>/scene.json` + `.tscn` |
| game logic compile | **pre-render** | seconds | `game/<cid>/scripts/*.gd` |
| lightmap bake (T2a, optional) | **pre-render** | ~5 min | `game/<cid>/lightmap.png` |
| matcap probes (T1b) | **pre-render** | <1 s | `game/<cid>/matcaps/` |
| Godot HTML5 export | **pre-render (build)** | ~1–3 min | static bundle (CDN-cached) |
| Facebook Instant Games package | **pre-render** | <1 min | uploaded to FB |
| player render | **realtime, browser** | client GPU | – |
| NPC behavior trees | **realtime, deterministic** | <0.5 ms / frame | – |
| NPC dialog (LLM) | **realtime, async edge** | 200–500 ms first token | – |
| NPC TTS | **realtime, edge stream** | <50 ms first chunk | – |
| NPC lipsync (amplitude) | **realtime, browser** | <0.5 ms / frame | – |
| IK behaviors | **realtime, browser** | <0.1 ms / frame | – |
| multiplayer state | **realtime, P2P + CRDT** | 50 ms p95 | – |
| save state | **async** | ~10 ms per write | server KV |
| **on-demand asset gen during play** | **realtime, server-async, BUDGET-BOUNDED** | capped to ~1/min/player via `bin/gpud` | new cid → joins catalogue |

The rule:
- **Everything about the game's structure** is pre-rendered + cid'd + cached
- **Everything about the player's session** is realtime, client-side or P2P
- **Edge LLM + TTS** are the only server-side runtime touches (and they're bounded)
- **Surprise content** (rare on-demand asset gen) is opt-in and capped — it cannot blow up costs

---

## 6. Dataset byproducts

Every published game + every play session contributes labeled training data to ATLAS:

1. **prompt ↔ assembled-game pairs** → game-from-prompt model fine-tuning
2. **prompt ↔ asset-gen workflow pairs** → workflow predictor (`pipeline_ml.py`) training
3. **scene.json spines per genre** → spine-from-genre LLM corpus
4. **player choice traces** → narrative branching + difficulty curve training
5. **multiplayer interaction logs** → multi-agent coordination training
6. **NPC dialog ↔ player response pairs** → conversational agent training
7. **Q3-TTS character voice ↔ used phrases** → voice clone fine-tune corpus
8. **player retention curves per template** → recommendation engine training
9. **cross-game asset reuse stats** → catalogue curation + royalty model
10. **failed-export logs** → error-prediction training (less broken games)
11. **prebuilt scene playtime distributions** → scene-template-fit prediction
12. **bot vs human player traces** → bot detection / bot training (same data, dual use)

> **Self-amortizing loop:** every game makes the next game faster to build, more
> beautiful, smarter at picking templates, better at writing dialog. The dataset
> itself is the moat — and it grows on autopilot.

---

## 7. Architectural primitives — what makes this fast

### Inheritance of the cheap-render primitives

Same back-face cutout (T1a) + matcap (T1b) + SSAO (T2b) stack as the other docs. In a
game context, this means a 60 fps render budget on a mid-range phone — which is the
only budget you actually have for WebGL/WebXR. Every game gets it for free.

### The ML workflow predictor (already in MediaLab)

`pipeline_ml.py` — TF-IDF over 73 historical workflows + Markov transitions + beam
search → given a creator prompt, **autonomously assembles a ComfyUI node graph for the
asset gen step**. This is what makes "prompt to playable in <5 min" feasible: no human
in the loop for the workflow design.

### ATLAS `bin/conductor` density-math agent team

Given a creator's free-form prompt, conductor decomposes by **density** (where the work
will redline) and **promotes** mid-tier coordinators only when needed. The escalation
order is fixed: **split horizontally first (more tinies) → promote a manager second →
change model tier last.** This is why complex prompts don't immediately escalate to
expensive cloud LLMs — most work happens at the tinies level.

### ATLAS `bin/forge` backward-resolved workflow

Given a goal type ("playable game with chef-roguelike vibe") and a list of musts,
forge **walks backward through the capability graph** to find the minimal sub-chain
that produces a type-valid output. Missing capabilities are flagged as gaps the creator
must approve (e.g. "no music-gen available; ship without music?"). This is the
deterministic planner; no LLM hallucination in the build pipeline.

### Godot HTML5 export — the universal target

Godot 4.6.3 with `gl_compatibility` renderer exports to **WebGL 2.0** running in a
`<canvas>`. That same canvas can be:
- a slug URL page (lyv-realty-ai shell)
- a Facebook Instant Games container (playbook documented)
- an embedded iframe on any creator's website
- a WebXR-enabled scene on Meta glasses

**One export. Four distribution channels. Zero per-platform port.**

### Cross-game character continuity

Every player has an `avatar.glb` cid'd in ATLAS (from the live-AR or realtor docs).
Every game's player-controller scene-spine has a "player slot" — at boot, the slot is
filled with the player's cached avatar.glb. The character literally travels between
games. This is the **retention engine** — your level-50 chef-character keeps her clothes
+ voice + name across every chef-game you play.

### The C++ extension as the deterministic physics + IK substrate

`SpatialBridge` + `IKSolver` provide native-speed:
- `solve_two_bone` — knee/elbow IK
- `solve_ccd` — multi-joint chain IK (good enough for gaze, arms, tails)
- `ik_delta` — strain metric (drives "this pose is uncomfortable" reaction)
- `fuse_depth` — multi-source depth fusion (drives AR variants)
- `mirror_drift` — crystal Hamming distance (drives "is this state reproducible?")
- `crystal_hash` — deterministic state identity

When built, every game gets native-speed physics + IK at <0.1 ms / frame total.

### Behavior trees over LLM for NPCs

NPC moment-to-moment behavior runs on **deterministic behavior trees** (state machines
with priority + selectors). LLM only kicks in for **dialog** and **decisions that
aren't tree-encodable** ("what should I say about the player's outfit?"). This is the
key to making AI NPCs cheap: 95% of NPC compute is a state machine; 5% is the LLM.

---

## 8. Existing pipelines we plug into (don't rebuild)

### Workflow: `photo_to_avatar_rigged.v0`
Same workflow that builds the realtor's avatar + the live-AR character now also builds
**every player character + every NPC**. Single source of truth for "make a rigged avatar
from a picture." **Direct reuse, no changes.**

### Workflow: `blob_to_unreal.v0` (livelink pattern)
Same pattern: server emits behavior diffs → datachannel → on-device animation
dispatcher. Used for NPC behavior streaming in multiplayer games.

### Workflow: `realestate.walkthrough_8f28d17e.v0`
Powers the **archviz tour** game template directly. The realtor doc IS one of the
catalogue games. Cross-doc reuse: a realtor's published listing IS a published game on
the platform.

### Existing 14 scenes
The catalogue. Already authored. Already proven. Already wired to the autoloads. Each
becomes a Godot HTML5 export with one command + a published slug URL.

### Facebook Instant Games playbook
`MySpace++/studio/docs/FACEBOOK_INSTANT_GAMES_PLAYBOOK.md` — the distribution channel
is already documented. Plug in, ship to ~3 B Facebook users.

### ComfyUI custom_nodes + 47 workflows
Asset gen runs through the existing ComfyUI plumbing. The ML workflow predictor knows
how to chain Impact-Pack + IPAdapter + FLUX + SD3.5 + Q3-TTS + LongCat into novel
graphs for novel prompts.

### lyv-realty-ai shell (Rust + Next.js)
The slug-URL shell that hosts realtor tours hosts game pages too. Same Rust backend,
same Next.js frontend, just a different mounting point per game.

### GentlyOS substrate
- `bin/assets` — every game asset is cid'd, cross-game shared
- `bin/gpud` — creator-time GPU scheduling with cloud-first policy
- `bin/conductor` + `bin/forge` — prompt → workflow planner
- `bin/chain` — orchestrator + loop.jsonl for chain-of-events tracing
- The `.bb` format and metabolism OpKinds — when wired, gives us reproducible
  build steps for every game export

---

## 9. Implementation plan — ordered by ROI

1. **Build `SpatialBridge.so`** (~5 min) — same step every doc opens with.
   `nix-shell -p scons --run "bash build-cpp.sh"`
   Unblocks physics + IK natively for every game.

2. **Wire Godot HTML5 export → lyv-realty-ai slug pages** (~1 day) —
   `godot --headless --export-debug "Web" <game_cid>.html` per scene → bundle goes to
   lyv-realty-ai static, served at `/game/<cid>`. Day-one ship: the 14 prebuilt
   templates each become a published game.

3. **Wire Facebook Instant Games packaging** (~1 day) —
   playbook is already documented; this is mostly automation. After this, the
   catalogue lives on FB too.

4. **Ship the catalogue UI** (~2 days) —
   Next.js page listing the 14 templates with "play now" + "remix this game" buttons.
   "Remix" routes into the BYOG flow with the template pre-selected.

5. **Build the BYOG creator-side UI** (~5 days) —
   prompt input + asset-gen progress + preview iframe + publish button. Drives
   `bin/conductor` + `bin/forge` + ComfyUI underneath.

6. **Wire NPC behavior trees + edge LLM dialog** (~3 days) —
   behavior tree runtime in Godot (one autoload), edge Gemma-4-E4B-it for dialog,
   Kokoro streaming for voice, amplitude lipsync for mouth. The live-AR character
   pipeline drops in directly.

7. **Cross-game character continuity** (~2 days) —
   server KV with player_id → avatar_cid; every game's player slot loads from it.
   The avatar.glb itself doesn't change; the cid is the identity.

8. **Multiplayer via WebRTC + Yjs CRDT** (~3 days) —
   simple room manager + signaling + Yjs document per game session. Voice via the
   same WebRTC datachannel.

9. **Catalogue royalty engine** (~3 days) —
   when game B reuses an asset cid created by creator A, B's revenue split sends a
   share to A automatically. ATLAS already tracks reuse via the cid graph.

10. **Optional: download `nvidia/Cosmos-Reason1-7B` weights** (~14 GB) —
    add the world-model as the **AI Director** that decides what content the player
    sees next given everything it observes. Not blocking v1; major upgrade for v3.

After steps 1–4 the **prebuilt catalogue is live** with 12+ games shipping day one.
After step 5 the **BYOG service is live**. After 6+7 every game has cross-game AI NPCs
and persistent player characters. After 8+9 the platform is a real two-sided marketplace.

---

## 10. The first-game / first-player checklist

For the platform's first paying creator + first paying player:

- [ ] Step 1 done — `SpatialBridge.so` built
- [ ] Step 2 done — `realestate_walkthrough_full` exports to HTML5 + lives at `/game/realestate-walkthrough`
- [ ] Step 3 done — same game lives on Facebook Instant Games
- [ ] Step 4 done — catalogue page lists all 12 templates; "play now" works on iPhone Pro, Quest 3, desktop Chrome
- [ ] Step 5 done — creator types "make me a chef roguelike" → playable in <5 min
- [ ] Step 6 done — at least one NPC in one prebuilt game has live AI dialog with cloned voice + amplitude lipsync
- [ ] Step 7 done — player who built avatar in live-AR app sees same character mounted in the chef-roguelike
- [ ] Step 8 done — two players in two browsers share a room in one prebuilt game; both see each other's avatars + voice flows
- [ ] Step 9 done — creator A makes an asset; creator B's BYOG flow auto-includes it via prompt match; A gets a royalty split
- [ ] Pricing + billing — per-play / subscription / IAP / FB Instant Games ad revenue all flowing
- [ ] Meta glasses test — at least one prebuilt game runs at 90 fps on Quest 3 passthrough

---

## 11. The five rules — same as every other doc

1. **cid + pass-tag everything** — assets, scenes, games, sessions. ATLAS `bin/assets`.
2. **Try T0 / T1 / T2 before any GPU heavy or NN call at runtime.** Render loop has 16 ms.
3. **Climb only on demonstrated gap.** "Cheap version doesn't answer the brief because <X>" — X names a missing axis.
4. **NN calls (T4) are creator-time, not runtime.** Exception: edge LLM for NPC dialog (scoped, bounded, async).
5. **Every climb's output is a new cid + new pass tag.** Today's expensive asset bake is tomorrow's free reuse. **And it earns its creator a royalty.**

---

## 12. Where this product is going (the long arc)

**v1** (next 4–6 weeks):
- Catalogue of 12 prebuilt templates live, FB Instant Games + slug URLs
- BYOG prompt → playable in <5 min for template-based
- Cross-game character continuity
- One NPC per game with live AI dialog

**v2** (Meta-glasses native + multiplayer):
- All catalogue games on Quest 3 passthrough at 90 fps
- WebXR-native creator UI ("build a game while standing in your living room")
- Multiplayer rooms standard across all games
- Royalty engine live across the catalogue

**v3** (Cosmos AI Director):
- `nvidia/Cosmos-Reason1-7B` as the world-model planner
- Game content adapts to observed player skill + style + mood
- audio-flamingo-2 phoneme-driven lipsync
- AI-generated cinematics on demand (LTX2.3 / Wan21 budget-bounded)

**v4** (the marketplace + cross-platform):
- Open creator marketplace with revenue splits + asset royalties
- Cross-platform identity: same player, same avatar, same friend graph across all games
- Steam + iOS native exports (Godot supports them; we just turn the flag on)
- Brand-IP integration (movies, music labels, sports teams build games with their
  characters using BYOG — the asset gen + voice clone + LLM personality stack just
  works)

**v5** (the substrate completes):
- `.bb` programs (per `BB.md`) become the universal game-state format
- gentlyOS metabolism opcodes power deterministic, replayable, verifiable gameplay
- Crystal-hashed game states enable provable speedruns / esports / NFT-grade scarcity

---

## Appendix A — paths referenced by this doc

```
/data/Projects/MySpace++/studio/
  godot/project/                            THE Godot 4.6.3 project — single source
  godot/project/project.godot               10-autoload substrate every game inherits
  godot/project/scenes/                     THE 14 prebuilt scene templates
    main.tscn
    realestate_walkthrough_full.tscn
    pump_surf.tscn  pump_surf_pipeline.tscn
    morphing_game.tscn
    forest_clearing_dawn_world_a7316b8d.tscn
    2d_pixel_platformer_2b1633b7.tscn
    stylized_2d_topdown_6bb5d96b.tscn
    planet_map.tscn
    avatar_rigged.tscn
    chain_render_wall.tscn  chain_render_wall_compiled.tscn
    asset_3d_gallery.tscn
    social_panel.tscn
  godot/project/cpp/                        SpatialBridge + IKSolver (.so NOT BUILT)
  godot/project/src/                        28 GDScript controllers + autoloads
  godot/project/export_presets.cfg          HTML5 / Web export already configured
  scene_spine.json  spine_ops.py            universal scene format + ops
  scene_to_godot.py                         spine → SceneTree (+ Three.js branch landed today)
  floorplan_to_spine.py                     2D→3D scene
  blender/mcp_server.py                     creator-time mesh build
  blender/scripts/avatar_bake.py            PBR LAYER_STACK
  passes/registry.py                        100+ inference passes
  passes/fused_depth.py                     5-channel depth fusion
  assets/_workflows/                        47 pre-authored workflows
  assets/_agents/agent_defs/                96 agents (blender_mcp, comfyui_mcp, chain_render_bridge, deepseek_mcp, infra_orchestrator)
  docs/FACEBOOK_INSTANT_GAMES_PLAYBOOK.md   distribution channel — already documented
  docs/REALTOR_VIRTUAL_TOUR_PIPELINE.md     sibling doc
  docs/LIVE_ACTION_AR_CHARACTER.md          sibling doc

/data/Projects/ATLAS/
  bin/assets                                cid'd shared asset catalogue across games
  bin/conductor                             density-math agent team for creator prompts
  bin/forge                                 backward-resolve workflow from creator intent
  bin/chain                                 loop.jsonl orchestrator
  bin/gpud + bin/gpu                        GPU governor for asset bakes

/data/Projects/MediaLab/
  studio/pipeline_ml.py                     TF-IDF + Markov + beam-search workflow predictor
  comfyui_node_db/                          indexed node registry — 38 JSONs
  studio/workflows/                         FLUX, SD3.5, character_composite, etc.
  audio/tts/kokoro/                         streaming TTS
  audio/asr/whisper/                        STT
  image/sd35-large/, image/flux-dev/        diffusion backbones
  video/wan21-t2v-14b/                      txt→vid (creator cinematics, 78 GB)

/home/tom/models/
  TencentARC_Pixal3D/                       img→3D hero (24 GB)
  stable-fast-3d/                           img→3D fast (4 GB)
  LongCat-Video-Avatar-1.5/                 character anim library bake
  Qwen3-TTS-12Hz-1.7B-CustomVoice/          NPC voice clone (3.8 GB)
  facebook_sapiens-pretrain-1b/             player body parse for AR variants
  facebook_VGGT/                            world capture for procedural generation (10 GB)
  facebook_cotracker3/                      motion tracks
  apple_DepthPro/                           depth for AR-variant games
  prs-eth_marigold-normals-v0-1/            normals
  finegrain_box_segmenter/                  art matting
  LTX2.3-Studio/                            cinematic gen (9 GB)
  Qwen_Image_Edit_2511/                     art polish (115 GB)
  gemma-4-E4B-it/                           edge LLM for NPCs (16 GB)
  Marlin-2B-ungated/                        alt edge LLM (11 GB)
  SpaceTimeGPT/                             spatiotemporal reasoning (future)

/home/tom/Projects/
  lyv-realty-ai/                            slug-URL shell — host every game's page
  rigging/                                  character rigging suite
  gently/                                   substrate (131 GB)
  zero2onez/                                orchestration

/data/Projects/gently/.consolidation/
  run19b_spatial/nvidia_Cosmos-Reason1-7B.jsonl  weights to download for AI Director
  run19_recovered/nvidia_audio-flamingo-2.jsonl  weights for true lipsync
```

---

## Appendix B — what's the same, what's different vs the sibling docs

| dimension | realtor doc | live-AR doc | this doc (games) |
|---|---|---|---|
| primary product | pre-rendered tour of a real listing | live AR character in user's real space | catalogue of playable games + BYOG service |
| scene | pre-baked from walkthrough video | real world live from device camera | pre-baked Godot scene (template or generated) |
| character | the realtor (optional avatar) | THE main thing | player + AI NPCs |
| creator | per-listing realtor capture (~25 min) | per-character creator build (~20 min) | per-game creator prompt (<5 min template / hours custom) |
| runtime device | any browser | WebXR browser, Meta glasses ideal | any browser, WebXR optional |
| runtime cost server-side | TTS during visit | TTS + LLM during conversation | TTS + LLM during NPC dialog (bounded) |
| asset reuse model | within-listing furniture catalogue | within-creator character library | **cross-game, cross-creator royalty-bearing catalogue** |
| existing workflow leveraged | `realestate.walkthrough_8f28d17e` | `photo_to_avatar_rigged.v0` | **all 47 workflows + 96 agent_defs + 14 scenes** |
| dataset byproducts | listing-side (relight, furniture removal) | encounter-side (STT, dialog, lipsync) | **game-side + cross-game asset reuse stats + retention curves** |
| limiting factor | none — pipeline ships today | none — pipeline ships today | none — **the 14 prebuilt scenes ship day one** |

**Cross-doc relationships:**
- The realtor's listing IS a published game (archviz tour template)
- The live-AR character IS the source of the cross-game player avatar
- The live-AR NPC pipeline IS what powers AI NPCs in games
- The realtor's avatar.glb plays in any game; her clients can summon her there too
- One catalogue. One asset pool. One royalty engine. Three product surfaces.

---

## Appendix C — system merkle (shared across the three docs)

`106b80ac5878c4636f0e37822f029289980568f73349350e0e6cdbb0fbd836ad`

Same scan inputs, same "what we have today" identity across the realtor / live-AR /
games docs. All three version-pin against this root. When inventory changes, re-run
the 5-agent scans, recompute, diff — affected sub-trees re-bake; everything else
stays cached. The three docs evolve together because the substrate evolves together.

---

*End of master design document.*
