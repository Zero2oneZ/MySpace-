# REALTOR VIRTUAL TOUR PIPELINE — MASTER DESIGN

> **Status:** v1 design synthesis · 2026-06-01
> **Owner:** Tom Lee (Zero2oneZ)
> **System merkle root (capture of "what we have today"):**
> `106b80ac5878c4636f0e37822f029289980568f73349350e0e6cdbb0fbd836ad`
>
> This document is the single source of truth for the realtor virtual-tour product:
> the cost model, the asset inventory, the onboarding flow, the DAG, the pre-render
> vs realtime split, and the dataset byproducts. It supersedes ad-hoc design notes
> and is the input to every implementation task that follows.

---

## 0. The product

For a realtor friend onboarding to a per-listing virtual-tour service. From her phone
+ ~25 minutes per listing she gets a billable slug-page URL with a logged-in walkthrough
that her clients can join, in which her own AI-cloned avatar can drop in and narrate live.
Target output surface: **browser → WebGL → WebXR → Meta glasses**.

**The bargain we make with the realtor:**
- One-time onboarding: ~10 minutes (selfie, 360° spin video, voice sample, optional outfit)
- Per listing: two phone walkthroughs (~25 minutes total) + colored mats + light markers
- We give back: a billable URL within ~30 minutes wall-clock

**The bargain we make with compute:**
- Pre-render every artifact that depends on geometry (per listing, once)
- Realtime only what depends on the visitor (camera, furniture toggle, conversation)
- Cache every byproduct as a content-addressed cid → every future listing is faster

---

## 1. The cost ladder — the architectural foundation

All rendering decisions for this product are made by climbing this ladder until the output
brief is met. Climb only when a tier below cannot deliver. **Free output beats $0.10 of NN
inference every time.**

| tier | technique | cost | what you get | what you don't |
|---|---|---|---|---|
| **T0** | symlinked image + layered planes (ATLAS + three.js scene.json) | ~free | composite, layer order | no depth, no parallax |
| **T1a** | **back-face cutout** of Blender mesh (`CULL_FRONT`) | rasterizer only | silhouette + real depth + parallax — **free alpha** | flat-shaded |
| **T1b** | matcap sphere-mapped fake light | 1 texture fetch | "lit" look from a fixed lightprobe | non-reactive to scene |
| **T2a** | baked lightmap (one offline Blender Cycles pass) | ~free at runtime | photoreal-ish static lighting | doesn't move with lights |
| **T2b** | screen-space AO + bent normals | <1 ms | contact shadows | no direct light |
| **T2c** | **T1a + T1b + T2b combined (archviz sweet spot)** | ~1–2 ms/frame | looks 3D for ~3 % the cost of T3 | not real PBR |
| **T3** | Forward+ PBR with shadows (Godot default) | 5–15 ms/frame | real light, real shadow | needs proper UVs/PBR |
| **T4a** | NN delight (Marigold-delight, IC-Light) | seconds, one-shot | identity preserved | non-temporal |
| **T4b** | img → 3D mesh (TRELLIS, stable-fast-3d, Hunyuan3D) | seconds–minutes, one-time | **reusable asset forever** | upfront cost, lossy |
| **T4c** | img → video (HunyuanVideo, Wan, LTX, Mochi) | minutes per clip | direct deliverable frames | not reusable, expensive |

### The two light scenarios — direct answer

| reuse count | winner | why |
|---|---|---|
| 1 shot, no future change | **T4a delight** | one diffusion pass, done |
| 2–3 shots, same content | toss-up | depends on subject complexity |
| ≥3 shots OR camera/pose/light change | **T4b rebuild → T1/T2 re-render** | bake amortizes; future renders are rasterizer-cost only |
| video (temporal) | **T4b rebuild** always | per-frame delight is temporally unstable |

Break-even ≈ **3 outputs**. Past that, rebuild + cheap re-render beats per-output diffusion.

### img → 3D vs img → video — when?

- **img → 3D** if the deliverable is *content* (will be reused across cameras / lights / poses). Bake once, cheap forever.
- **img → video** if the deliverable is *the video itself* and it will never be re-shot.
- Both is wasteful unless the video itself becomes a 3D reference.

### The architectural collapse

The **back-face cutout** technique (`material.cull_mode = CULL_FRONT`) earns T1a most of what
T3 pays for in archviz: silhouette, depth, parallax — all as **byproducts of rasterizer
coverage**, no shading, no lighting, no texture fetch. Add T1b matcap + T2b SSAO and you
hit "PBR-archviz look" with budget that runs on a phone.

**Render in the cheap tier; generate in the expensive tier; cache the boundary.** This is
the entire architecture. ATLAS `by-pass/` is the cache. `SpatialBridge::fuse_depth()` is
the validator. Godot back-face cutout is the cheap-tier renderer. Blender headless is the
geometry generator. ComfyUI / diffusion is the asset generator.

---

## 2. Asset inventory — capability map

Result of 5 parallel deterministic scans across `/home/tom/models/`, `/data/Projects/MediaLab/`,
`/data/Projects/MySpace++/studio/`, NVIDIA-model hunt, and `/data/Projects/ATLAS/` + `~/Projects/`.
Each scan emitted a merkle root; the system root over the sorted scan roots is
`106b80ac5878c4636f0e37822f029289980568f73349350e0e6cdbb0fbd836ad`.

### Scan merkle roots (inputs to the system root)

```
A (/home/tom/models)         = 35ea5dbeafe7d04603af2626dcf7cac09608f38cc8dd2797e0282728dd1820f4
B (MediaLab)                 = fabaee3b12db77e11cdbcff7b6fa5bc5d33b959c740adf5944351ac3897f65f7
C (MySpace++/studio)         = c6080116f228e8d846262f10bc5e51e99a2553c1d5e825577414081ffabb2c1f
D (NVIDIA hunt)              = 02fb3f4a58640943c83ad46119db8c79e4c3e51af0755f882a54247f043cec58
E (ATLAS + ~/Projects)       = a03f1b0d76d6c5a23bad0deca0cf4b1cf86565cd22fa393d940fa34e491a282f
SYSTEM ROOT                  = 106b80ac5878c4636f0e37822f029289980568f73349350e0e6cdbb0fbd836ad
                               = sha256(sorted(scan roots) concatenated)
```

### Capability ↔ tool map

| capability | best tool we own | location | status |
|---|---|---|---|
| video → camera path + sparse geom | **facebook_VGGT** (10 GB) | `/home/tom/models/facebook_VGGT` | weights live ✓ |
| video → point tracks | **cotracker3** (407 MB) | `/home/tom/models/facebook_cotracker3` | live ✓ |
| img → metric depth | **apple_DepthPro** (1.9 GB) | `/home/tom/models/apple_DepthPro` | live ✓ |
| img → normals | **Marigold-normals** (15 GB) | `/home/tom/models/prs-eth_marigold-normals-v0-1` | live ✓ |
| multi-channel depth fusion (5-ch: visual + acoustic RT60 + CLIP + anthropometric) | `passes/fused_depth.py` | `MySpace++/studio/passes/fused_depth.py` | **already wired** ✓ |
| img → 3D mesh (production) | **TRELLIS / TencentARC_Pixal3D** (24 GB) | `/home/tom/models/TencentARC_Pixal3D` | live ✓ |
| img → 3D mesh (fast lightweight) | **stable-fast-3d** (4 GB) | `/home/tom/models/stable-fast-3d` | live ✓ |
| body pose + dense normals | **Sapiens-1b** (4.5 GB) | `/home/tom/models/facebook_sapiens-pretrain-1b` | live ✓ |
| matting / object isolation | **finegrain_box_segmenter** + SAM2 via Impact-Pack | `/home/tom/models/` + MediaLab | live ✓ |
| video bg removal | video-background-removal | `/home/tom/models/` | live ✓ |
| img2img inpaint (greenscreen swap) | **FLUX-dev** + **Qwen_Image_Edit_2511** + flux-bg-remove-LoRA | MediaLab + `/home/tom/models` | wired ✓ |
| img → video | **LTX2.3-Studio** (9 GB) + **Wan2.1-T2V-14B** (78 GB) | `/home/tom/models` + MediaLab | live ✓ |
| avatar animation | **LongCat-Video-Avatar-1.5** | `/home/tom/models/` | live ✓ |
| voice clone | **Qwen3-TTS-12Hz CustomVoice** (3.8 GB) | `/home/tom/models/` | live ✓ |
| streaming TTS | **Kokoro** | `MediaLab/audio/tts/kokoro` | wired ✓ |
| STT | **Whisper-large-v3-turbo** | `MediaLab/audio/asr/whisper` | wired ✓ |
| scene spine + ops | `scene_spine.json` + `spine_ops.py` (MASK / CUT / FLIP / REORDER) | `MySpace++/studio/` | **already wired** ✓ |
| floorplan → 3D scene | `floorplan_to_spine.py` | `MySpace++/studio/` | **already wired** ✓ |
| scene → Godot transpile | `scene_to_godot.py` | `MySpace++/studio/` | **already wired** ✓ |
| Godot realestate walkthrough scene | `realestate_walkthrough_full_controller.gd` + workflow `realestate.walkthrough_8f28d17e.v0` | `MySpace++/studio/...` | **already authored** ✓ |
| Blender PBR bake | `avatar_bake.py` / `realestate_walkthrough_full_bake.py` | `MySpace++/studio/blender/scripts/` | live ✓ |
| Blender MCP control | `blender/mcp_server.py` | `MySpace++/studio/blender/` | live ✓ |
| ComfyUI MCP control | comfyui_mcp agent + ML workflow predictor (TF-IDF + Markov beam search) | MediaLab + studio agent_defs | live ✓ |
| content-addressed asset store | `bin/assets` (cas + by-type + by-layer + by-pass) | `/data/Projects/ATLAS/bin/assets` | live ✓ |
| Godot scene-camera back-face cutout proof | `src/backface_test.gd` + `src/depth_loop.py` | `MySpace++/studio/godot/project/src/` | **proven 2026-06-01** ✓ |
| wardrobe / paperdoll | `paperdoll3d.py` + `wardrobe_studio.py` | `MySpace++/studio/` | live ✓ |
| real estate product shell (Rust + Next.js, photo→3D tours, MLS-aware) | **lyv-realty-ai** (10 GB) | `~/Projects/lyv-realty-ai` | **already a product** ✓ |
| GPU governor (cloud-first, GPU0-reserved-for-diffusion) | `bin/gpud` + `ollama/governor.py` | ATLAS | live ✓ |
| orchestration | **gently** (131 GB) + ATLAS conductor / chain | both | live ✓ |
| SpatialBridge native ext (`fuse_depth`, `mirror_drift`, IK) | header + sources present | `MySpace++/studio/godot/project/cpp/` | **`.so` NOT BUILT** ⚠ |
| 96 agent_defs + 47 workflows pre-authored | `assets/_agents/` + `assets/_workflows/` | `MySpace++/studio/assets/` | inventoried ✓ |

### What's NOT here

| gap | impact | workaround |
|---|---|---|
| IC-Light / DiLightNet | can't strip & replace photo light | (a) Marigold-normals + albedo + SH relight in three.js · (b) Blender Cycles lightmap (T2a) · (c) T1a back-face cutout + T1b matcap |
| gsplat / OpenSplat / nerfstudio | no native Gaussian-splat trainer | VGGT mesh → T1a back-face cutout replaces splat at ~3 % the cost; cloud-side splat on-demand for premium tier |
| COLMAP / Meshroom | no SfM photogrammetry | VGGT covers it natively + faster |
| **nvidia/Cosmos-Reason1-7B weights** | currently metadata-only at `gently/.consolidation/run19b_spatial/nvidia_Cosmos-Reason1-7B.jsonl` (~457 KB tensor catalog, no weights) — this is the "new NVIDIA model" referenced | download from HF when needed; Cosmos = spatial-reasoning world model → camera-path planner / room-layout reasoner. Not blocking v1. |
| nvidia/audio-flamingo-2 weights | metadata-only | download on demand; audio-visual sync. Not blocking v1. |
| `SpatialBridge.so` not compiled | C++ extension that does `fuse_depth`, `mirror_drift`, IK | `nix-shell -p scons --run "bash build-cpp.sh"` — one-time ~500 MB godot-cpp clone + minutes of compile |

---

## 3. The realtor's friend onboarding — her actual journey

```
ONBOARDING (one-time per realtor, ~10 minutes of her time):
  1. selfie + Leonardo (T-/A-pose) photo                          → 30 s phone snap
  2. 360° spin video of herself (15 s, hold phone steady)         → phone
  3. voice sample (60 s reading provided script)                  → phone mic
  4. preferred outfit / brand logo upload                         → optional

PER LISTING (~25 minutes of her time, across two visits):

  Day 1 — FURNISHED walk-through (10 min):
    walk through every room with phone, 30 fps, slow steady pan
    purpose: capture furniture-in-place + lighting state

  Day 2 — EMPTY + STAGING CUES walk-through (15 min):
    walk through the SAME rooms now empty
    drop GREEN MATS    where she'd place furniture
    drop COLORED MATS  for edge cases (each color = a specific intent —
                         e.g. red = "TV here", blue = "bed here", yellow = "art here")
    place WHITE GREENSCREEN PAPER over TVs / pictures / mirrors
    place LIGHT-COLOR DOTS where she wants light sources
    purpose: capture empty geometry + her placement design + her light intent

  SHE STOPS. Server-side bake runs (~30 min on z21 dual 3090 Ti):
    → slug page goes live
    → realtor avatar can join any visitor any time
    → billable link delivered
```

**Time from end-of-capture to billable URL:** ~30 min wall-clock.
**Realtor's hands-on time per listing:** ~25 min.
**Onboarding (one-time):** ~10 min.

---

## 4. The DAG — full ordering with tier mapping

```
                       [ONBOARDING — once per realtor]
                                       │
        ┌──────────────────┬───────────┴───────────┬──────────────┐
        leonardo_pose     360_spin_video         voice_sample    outfit_ref
        (selfie)          (15 s)                 (60 s)          (optional)
        │                 │                      │               │
        ▼ Sapiens         ▼ VGGT + cotracker3    ▼               ▼
        (pose+normals)    (multi-view face/body) Q3-TTS clone    wardrobe_studio
        │                 │                      │ (3.8 GB)      paperdoll3d
        │                 │                      │
        └────────┬────────┘                      │
                 ▼                               │
        TRELLIS / Pixal3D (img→mesh)             │
        + Blender avatar_bake.py (PBR            │
          LAYER_STACK: albedo, normal,           │
          AO, roughness, metallic)               │
                 │                               │
                 └────────┬──────────────────────┘
                          ▼
                  CACHE  avatar/<realtor_cid>/  →  ATLAS by-type/3d/
                    ├─ avatar.glb        (rigged, 25-joint Meta Body)
                    ├─ voice.zip         (Q3-TTS speaker embedding)
                    ├─ anim_idle.glb     (LongCat-Video-Avatar baked)
                    └─ outfit_paperdoll/ (wardrobe layers)
                  ───── AMORTIZES ACROSS EVERY FUTURE LISTING ─────


                       [PER LISTING — day 1 furnished]
                                       │
                          walkthrough.mp4 (10 min, 30 fps)
                                       │
        ┌─────────────────────────┬────┴────────────────────────┐
        ▼                         ▼                             ▼
   cotracker3                  VGGT                       per-frame:
   point tracks                camera path + sparse        DepthPro → depth
                               cloud                       Marigold → normals
                                                                 │
                                       ▼                         ▼
                              fused_depth.py
                              (5-channel, already wired)
                                       │
                                       ▼
                          furnished.{mesh|cutout}.glb
                          + camera_path.json
                          + per_frame_depth/  (cid'd, by-pass/depth/)
                                       │
                                       ▼
                  SAM2 (Impact-Pack) — segment furniture per frame
                                       │
                                       ▼
                  per-instance img→3D
                    fast tier  → stable-fast-3d
                    heavy tier → TRELLIS (edge cases / hero pieces)
                                       │
                                       ▼
                  FURNITURE CATALOG  →  ATLAS by-type/3d/<cid>.glb
                  ───── GROWS MONOTONICALLY — REUSABLE FOREVER ─────


                       [PER LISTING — day 2 empty + staging cues]
                                       │
                  walkthrough.mp4 + colored mats + light markers
                                       │
                  same SfM/depth pipeline as day 1
                  REGISTER cameras against day-1 path → alignment
                                       │
        ┌───────────────────┬──────────┴──────────────┬──────────────────┐
        ▼                   ▼                         ▼                  ▼
   empty_room.glb     greenscreen mats           colored mats        light markers
                      → finegrain matte          → SAM mask          → SAM mask
                      → placement_zones.json     → intent_overlay    → light_rigs.json
                                                   (color → action)
                                       │
                                       ▼
                  PAIRS EXTRACTED (the dataset gold):
                    ─ furnished/empty same view    (relight + furniture-removal training)
                    ─ with/without object per zone (staging-AI training)
                    ─ greenscreen-pic / actual-art (inpaint training pairs)
                                       │
                                       ▼
                  CACHE  listing/<slug>/ →
                    ├─ empty.glb
                    ├─ furnished.glb
                    ├─ furniture_refs.json   (refs into shared catalog)
                    ├─ placement_zones.json
                    ├─ light_rigs.json
                    ├─ scene.json            (ATLAS spine, via floorplan_to_spine)
                    └─ datasets/{pairs,inpaint,staging}/   ← PROVENANCE GOLD


                       [BAKE — once per listing]
                                       │
        ┌───────────────────┬──────────┴──────────────┬──────────────────┐
        ▼                   ▼                         ▼                  ▼
   T1a back-face       T2a lightmap bake         T1b matcap         T0  scene.json
   cutout (proven      (Blender Cycles            probe from photo  + .tscn
   2026-06-01)         one offline pass)                            (scene_to_godot.py)
                                       │
                                       ▼
                          FREE-TIER render bundle
                                       │
                                       ▼
                          Next.js build (lyv-realty-ai shell)
                            ├─ /listing/<slug>      → splat/cutout viewer
                            ├─ /listing/<slug>/api  → state sync (Yjs / WebRTC)
                            └─ /agent/<realtor_cid> → avatar join endpoint
                          bundle target: <3 MB shell + lazy splats


                       [RUNTIME — per visitor]
                                       │
                          browser / Meta-glasses (WebXR)
                                       │
        ┌───────────────────┬──────────┴──────────────┬──────────────────┐
        ▼                   ▼                         ▼                  ▼
   three.js scene      furniture toggle          realtor joins       WebRTC
   (T0 + T1a + T2c)    (instance swap from       (Kokoro stream-TTS  visitor ↔ realtor
                       cached catalog)            with Q3-TTS clone   voice
                                                   embedding)
                                       │
                                       ▼
                          RUNTIME COST PER VISITOR:
                            GPU: zero on server (all rendering browser-side)
                            CPU: TTS stream while realtor speaks (~50 ms / chunk)
                            BW : splat/mesh once at load + audio while talking
```

---

## 5. Pre-render vs realtime — explicit split

| stage | mode | cost | cached as |
|---|---|---|---|
| video → camera path + geometry (VGGT + cotracker3) | **pre-render** | ~5 min / listing, 1 GPU | `furnished.glb`, `empty.glb` |
| fused_depth per keyframe | **pre-render** | ~30 s / keyframe | `per_frame_depth/*.png` (cid'd, `by-pass/depth/`) |
| SAM2 furniture isolation + img→3D | **pre-render** | ~2 min × ~15 pieces = ~30 min | `furniture/<cid>.glb` (shared catalog) |
| greenscreen matting + intent overlay | **pre-render** | ~10 s / frame × keyframes | `placement_zones.json`, `light_rigs.json` |
| relight pair extraction (datasets) | **pre-render byproduct** | free with SfM | `datasets/<listing>/pairs/` |
| Blender lightmap bake (T2a) | **pre-render** | ~2–5 min / listing | `lightmap.png` |
| back-face cutout proxy meshes (T1a) | **pre-render** | ~10 s | symlinked into `engine/three/` |
| scene.json spine | **pre-render** | <1 s | ATLAS-pattern |
| Next.js bundle | **pre-render (build)** | once per release | static |
| three.js scene runtime | **realtime, browser** | client GPU only | – |
| splat / mesh rendering | **realtime, browser** | client GPU | – |
| avatar join (realtor) | **realtime, edge** | Kokoro TTS ~50 ms / chunk + LongCat anim cached | streamed |
| live narration TTS | **realtime, server** | Q3-TTS RTF ≈ 0.3 | streamed |
| furniture stage toggle | **realtime, browser** | instance swap (zero re-fetch) | – |
| WebRTC visitor ↔ realtor | **realtime, P2P** | TURN server only | – |

**Rule:** everything that depends on the listing's geometry is **pre-rendered once and content-addressed**. Everything that depends on the visitor's choices (camera, furniture variant, conversation) is **realtime browser-side**. **Nothing renders server-side at visit time.**

---

## 6. Dataset byproducts — the "for other apps" angle

Every listing throws off these for free. Each becomes a labeled training dataset for the
next model we build, and ATLAS auto-cids + auto-deduplicates them across listings:

1. **Furnished / empty image pairs at registered camera poses** → relight model training (replaces the IC-Light gap)
2. **Furniture-present / furniture-absent per zone** → furniture-removal + interior-staging model training
3. **Multi-view captures with VGGT camera path** → splat / NeRF training corpus (for when gsplat lands)
4. **SAM2 masks per furniture instance** → fine-grained segmentation training
5. **Greenscreen-pic / actual-art-on-wall pairs** → inpaint training pairs
6. **Light-marker location / observed shadow direction pairs** → light estimation training
7. **Realtor voice clip → spoken phrases dataset** → voice clone fine-tuning
8. **Sapiens body parse / Q3-TTS audio aligned** → lipsync training (closes the audio-flamingo-2 gap)
9. **floorplan_to_spine outputs aligned with VGGT rooms** → floorplan-from-walkthrough training
10. **scene.json spines per listing** → scene-layout LLM corpus

> **The self-amortizing loop:** each future listing makes every future model better, and
> each better model makes the next listing faster. The pipeline pays for its own R&D.

---

## 7. Architectural primitives (proven this session)

### Back-face cutout — the free-depth trick

Flipping `material.cull_mode = CULL_FRONT` causes the rasterizer to draw **back-faces** instead of
front-faces. Side effects (all free byproducts of rasterizer coverage):

| signal | what it is | cost |
|---|---|---|
| **alpha (silhouette)** | "did any back-face exist on this ray?" — answered by rasterizer coverage | **free** |
| **inverted alpha** | `1 − coverage` — one ALU op | **free** |
| **depth (hole depth)** | z of the back-face along the ray = distance from camera-plane to where the mesh's normal terminates inward | **free** — z-buffer already wrote it |
| **parallax** | per-pixel depth × camera_dx — geometrically correct | **free** |
| **animation** | vertex transform only; no shading, lighting, texture sample | **viewport-cost** = Blender wireframe nav |

Per-engine knob:
- **Godot:** `BaseMaterial3D.cull_mode = CULL_FRONT`
- **Three.js:** `material.side = THREE.BackSide`
- **Blender:** `Backface Culling = OFF` on the back-only pass

Proof in `MySpace++/studio/godot/project/src/backface_test.gd` (run via
`bin/godot --headless --path . -s src/backface_test.gd`):

```
sphere at (0,0,-1) r=0.6, camera at (0,0,1.5):
  ray_x=0.0  →  near_d=1.900  far_d=3.100  (cutout depth)  ← far - near = 2r ✓
  ray_x=0.7  →  near_d=2.106  far_d=2.797                  ← grazes the limb
  parallax field: far_d ∈ [2.797, 3.100] smoothly with x — REAL geometric depth
```

### Truth-depth loop — the cid'd validator

`MySpace++/studio/godot/project/src/depth_loop.py` bakes the analytic back-face far-d field as a
uint16 PNG, files it via `bin/assets scan`, then samples it back at the same ray positions
to compute drift vs analytic. End-to-end result (ran 2026-06-01):

- `by-pass/depth/sphere.6a8f49fb.png` filed, cid'd, deduplicated by ATLAS
- 15/15 sample drifts within ±0.0022 (quantization noise of uint16 over the depth range)
- Same downstream consumes Blender Cycles depth pass / Comfy depth model / Marigold

**The wires are proven:**
`scene-camera → analytic back-face far_d → PNG bake → cid → by-pass/depth/ → uv-sample → drift`

That is the closed loop between **the unseen layer (back-face geometry)** and **labeled
truth (a cid'd depth bake)**. The same loop validates VGGT-from-walkthrough against
DepthPro per-frame, against Blender lightmap UV, against any future depth source. Drift
becomes a deterministic mirror_drift / fuse_depth signal — the integrity contract for
every geometry-bearing artifact in the pipeline.

---

## 8. Existing pipelines we plug into (don't rebuild)

From `MySpace++/studio/assets/_workflows/` and `assets/_agents/`:

### Workflow: `photo_to_avatar_rigged.v0`
```
Input: photo.jpg [+ voice_clip.wav + style_ref.png]
  → mediapipe + finegrain_box_segmenter   (mask)
  → apple_DepthPro                         (depth.npz, meters)
  → blender avatar_bake.py                 (LAYER_STACK: albedo, normal, AO, metallic, roughness)
  → scene_to_godot.py                      (avatar_rigged_controller.gd)
Output: rigged_mesh.gltf (40 MB) | sprite_sheet.png (5 MB) | godot_scene.tscn (12 KB) | voice_synth.wav (3 MB) | alignment_crystal (sha256)
```
**Direct reuse for realtor onboarding.** No changes needed.

### Workflow: `blob_to_unreal.v0` (VR streaming pattern)
```
Input: blob_snapshot.png
  → HunyuanVideo (i2v) via ComfyUI         (video.mp4)
  → MediaPipe Holistic walk + remap        (pose.jsonl in Meta Body)
  → mocap_rig_anchor + alignment check     (animation_crystal)
  → Unreal LiveLink UDP (port 11111)       (live stream into UE5 Animation Blueprint)
Output: live_link_session
```
**Pattern reuse for realtor-joins-tour.** Swap Unreal target for Godot/three.js.

### Workflow: `realestate.walkthrough_8f28d17e.v0`
```
Input: floorplan.svg/png [+ property photos]
  → floorplan_to_spine.py (spine_ops MASK / FLIP)  →  scene_spine.floorplan.json
  → blender realestate_walkthrough_full_bake.py    →  photorealistic frames per waypoint
  → scene_to_godot.py + realestate_walkthrough_full_controller.gd  →  Godot tour scene
Output: walkthrough.tscn + render_series + camera_path.json
```
**The realtor pipeline IS this workflow upgraded** with day-1 / day-2 capture, fused_depth,
furniture catalog, and the back-face cutout render tier.

### Fused-depth pipeline (5 sensors)
```
image.jpg [+ audio.wav + scene_context.json]
  visual        → apple_DepthPro            → depth_norm
  acoustic      → echo time + RT60 rooms    → distance prior
  semantic      → CLIP encoder              → depth μ, σ prior
  anthropometric → known object sizes       → scale factor
  fusion        → fused_depth.py           → 0.6·visual + 0.3·meta + 0.1·acoustic
Output: fused_depth.npz {depth H×W meters, confidence, room_dims, intrinsics, normals, histogram}
```
**Already wired.** Realtor pipeline feeds it walkthrough keyframes.

### Existing agents we wire in
| agent | role |
|---|---|
| `blender_mcp` | scene assembly via JSON-RPC (`mesh.*`, `material.*`, `light.*`, `render.image`, `bone.*`) |
| `comfyui_mcp` | submit workflows → poll → download outputs into `studio/assets/_bakes/<prompt_id>/` |
| `chain_render_bridge` | Godot autoload polls render proxy (port 8766) → emits `render_arrived`, `event_arrived` signals |
| `deepseek_mcp` | LLM reasoning for the scene-layout / camera-path planner (until Cosmos lands) |
| `infra_orchestrator` | GPU scheduler with vram_gb constraints — already aware of dual 3090 Ti |
| `embedding_index` | semantic search over ATLAS-cid'd assets for catalog reuse |

---

## 9. Implementation plan — ordered by ROI

1. **Build `SpatialBridge.so`** (~5 min):
   `nix-shell -p scons --run "bash /data/Projects/MySpace++/studio/godot/project/build-cpp.sh"`
   Unblocks `fuse_depth`, `mirror_drift`, IK inside the Godot engine. One-time ~500 MB godot-cpp clone.

2. **Register `realestate.full_listing.v1` in `passes/registry.py`** (~50 LOC of Python):
   Adds the DAG above as one named workflow. Composes already-existing passes (`vggt`, `cotracker3`, `depthpro`, `marigold_normals`, `fused_depth`, `sam2`, `stable_fast_3d`, `trellis`, `blender_bake`, `scene_to_godot`). Vram and GPU scheduling falls out of the existing registry.

3. **Wire VGGT + cotracker3 as ComfyUI custom nodes** (~1 day each):
   Weights are on disk; need node-pack wrappers so they appear in the ComfyUI graph. Once present, the ML workflow predictor (`pipeline_ml.py`) can autonomously chain them.

4. **Stand up Q3-TTS streaming endpoint** (~1 day):
   Kokoro is already wired in MediaLab; mirror that wrapper for Q3-TTS. Add WebRTC audio relay.

5. **Bake the empty/furnished pair extractor** in lyv-realty-ai (~1 day):
   `diff(furnished_view, empty_view) → SAM2 → stable-fast-3d → ATLAS file`. The dataset byproducts (#1, #2, #4 above) fall out automatically.

6. **Optional: download `nvidia/Cosmos-Reason1-7B` weights** (~14 GB):
   Currently metadata-only at `gently/.consolidation/run19b_spatial/`. Cosmos = world model → camera-path planner / room-layout reasoner. Slots in as the "scene intent" inference; not blocking v1.

After steps 1 + 2 the realtor chain runs end-to-end against a test listing. After steps 3 + 4 it
ships. Step 5 turns it into a dataset factory. Step 6 is the upgrade.

---

## 10. The realtor-friend critical-path checklist

For the first paying client:

- [ ] Step 1 done — `SpatialBridge.so` built
- [ ] Step 2 done — `realestate.full_listing.v1` registered + dry-run on synthetic input passes
- [ ] Step 3 done — VGGT + cotracker3 wrapped as ComfyUI nodes
- [ ] Step 4 done — Q3-TTS streaming endpoint up
- [ ] Realtor onboarding fixture: she ships selfie + 360 spin + voice + outfit (record her time)
- [ ] Day-1 walkthrough of test property + cache verification (`avatar/<her_cid>/` populated; furnished.glb cid'd)
- [ ] Day-2 walkthrough with mats + light markers (`empty.glb`, `placement_zones.json`, `light_rigs.json` cid'd)
- [ ] Auto-bake (Blender lightmap T2a + back-face cutout T1a + scene.json + Godot/three transpile)
- [ ] Slug URL goes live in lyv-realty-ai (`/listing/<slug>`)
- [ ] Realtor joins live (her avatar mounts, Q3-TTS clone speaks her words, Sapiens drives lipsync)
- [ ] WebXR mode tested on Meta glasses
- [ ] Billing-ready link delivered to client

---

## 11. The five rules we don't relitigate per asset

1. **cid + pass-tag the input first.** ATLAS `bin/assets` already does this.
2. **Try T0 / T1 before any GPU heavy or NN call.** Free output beats $0.10 inference.
3. **Climb only on demonstrated gap.** "Cheap version doesn't answer the brief because <X>" — and X must name a missing axis (camera, light, pose, prompt).
4. **NN calls (T4) only when reuse < 3 OR no geometry exists yet.** Otherwise bake to mesh and re-render in T1 / T2 forever.
5. **Every climb's output is a new cid + new pass tag.** The DAG is self-amortizing: today's expensive output is tomorrow's free input.

---

## Appendix A — paths referenced by this doc

```
/data/Projects/MySpace++/studio/
  passes/fused_depth.py                  5-channel depth fusion
  passes/registry.py                     pass scheduler (100+ passes)
  scene_spine.json                       canonical spine root
  scene_spine.floorplan.json             realtor floorplan variant
  scene_spine.skeleton.json              25-joint Meta Body rig
  scene_to_godot.py                      spine → Godot transpile
  floorplan_to_spine.py                  floorplan → 3D scene
  spine_ops.py                           MASK / CUT / FLIP / REORDER
  blender/mcp_server.py                  Blender JSON-RPC server
  blender/scripts/avatar_bake.py         LAYER_STACK PBR bake
  blender/scripts/realestate_walkthrough_full_bake.py
  godot/project/project.godot            Godot 4.6.3 project
  godot/project/scenes/realestate_walkthrough_full.tscn
  godot/project/src/realestate_walkthrough_full_controller.gd
  godot/project/src/chain_render_bridge.gd  render proxy autoload
  godot/project/src/backface_test.gd     proven 2026-06-01
  godot/project/src/depth_loop.py        truth-loop closure 2026-06-01
  godot/project/cpp/                     SpatialBridge + IKSolver (.so NOT BUILT)
  assets/_workflows/                     47 pre-authored workflows
  assets/_agents/agent_defs/             96 pre-authored agents

/home/tom/models/
  facebook_VGGT/                         multi-view geometry (10 GB)
  facebook_cotracker3/                   point tracks (407 MB)
  apple_DepthPro/                        metric depth (1.9 GB)
  prs-eth_marigold-normals-v0-1/         normals (15 GB)
  TencentARC_Pixal3D/                    TRELLIS img→3D (24 GB)
  stable-fast-3d/                        fast img→3D (4 GB)
  facebook_sapiens-pretrain-1b/          body parse (4.5 GB)
  Qwen3-TTS-12Hz-1.7B-CustomVoice/       voice clone (3.8 GB)
  LongCat-Video-Avatar-1.5/              avatar animation
  LTX2.3-Studio/                         img→video (9 GB)
  finegrain_box_segmenter/               matting
  Qwen_Image_Edit_2511/                  heavy img2img inpaint (115 GB)

/data/Projects/MediaLab/
  image/sd35-large/, image/flux-dev/     diffusion backbones
  video/wan21-t2v-14b/                   txt→video (78 GB)
  audio/tts/kokoro/                      streaming TTS (wired)
  audio/asr/whisper/                     STT
  studio/workflows/                      ComfyUI workflow JSONs
  studio/pipeline_ml.py                  TF-IDF + Markov workflow predictor
  comfyui_node_db/                       indexed node registry

/data/Projects/ATLAS/
  bin/assets                             CAS + by-type/ + by-layer/ + by-pass/
  bin/conductor                          density-math agent team assembly
  bin/chain                              loop.jsonl orchestrator
  bin/gpud + bin/gpu                     GPU governor + CLI
  bin/forge                              backward-resolved workflow builder

/home/tom/Projects/
  lyv-realty-ai/                         Rust + Next.js real-estate AI (10 GB) — THE SHELL
  gently/                                spine agent runtime (131 GB)
  zero2onez/                             agent orchestration
  rigging/                               avatar rigging suite

/data/Projects/gently/.consolidation/
  run19b_spatial/nvidia_Cosmos-Reason1-7B.jsonl   METADATA ONLY — weights not downloaded
  run19_recovered/nvidia_audio-flamingo-2.jsonl   METADATA ONLY — weights not downloaded
```

---

## Appendix B — system merkle inputs

```
Inputs to SYSTEM_MERKLE_ROOT (sorted lexicographically, concatenated, sha256):

02fb3f4a58640943c83ad46119db8c79e4c3e51af0755f882a54247f043cec58  ← D (NVIDIA hunt)
35ea5dbeafe7d04603af2626dcf7cac09608f38cc8dd2797e0282728dd1820f4  ← A (/home/tom/models)
a03f1b0d76d6c5a23bad0deca0cf4b1cf86565cd22fa393d940fa34e491a282f  ← E (ATLAS + ~/Projects)
c6080116f228e8d846262f10bc5e51e99a2553c1d5e825577414081ffabb2c1f  ← C (MySpace++/studio)
fabaee3b12db77e11cdbcff7b6fa5bc5d33b959c740adf5944351ac3897f65f7  ← B (MediaLab)

SYSTEM_MERKLE_ROOT
  = sha256(sorted scan roots concatenated)
  = 106b80ac5878c4636f0e37822f029289980568f73349350e0e6cdbb0fbd836ad

Reproducibility:
  python3 -c "
  import hashlib
  roots = sorted([
      '02fb3f4a58640943c83ad46119db8c79e4c3e51af0755f882a54247f043cec58',
      '35ea5dbeafe7d04603af2626dcf7cac09608f38cc8dd2797e0282728dd1820f4',
      'a03f1b0d76d6c5a23bad0deca0cf4b1cf86565cd22fa393d940fa34e491a282f',
      'c6080116f228e8d846262f10bc5e51e99a2553c1d5e825577414081ffabb2c1f',
      'fabaee3b12db77e11cdbcff7b6fa5bc5d33b959c740adf5944351ac3897f65f7',
  ])
  print(hashlib.sha256(''.join(roots).encode()).hexdigest())
  "
```

When the system state changes (new model arrives, weights download, workflow lands), re-run
the 5 scan agents → compute new root → diff against this. Any sub-tree whose hash changes
is the one whose downstream artifacts need to be re-baked. Everything else stays cached.

---

*End of master design document.*
