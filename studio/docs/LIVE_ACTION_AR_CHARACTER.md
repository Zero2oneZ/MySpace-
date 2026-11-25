# LIVE-ACTION AR CHARACTER PIPELINE — MASTER DESIGN

> **Status:** v1 design synthesis · 2026-06-01
> **Owner:** Tom Lee (Zero2oneZ)
> **Sibling doc:** [`REALTOR_VIRTUAL_TOUR_PIPELINE.md`](REALTOR_VIRTUAL_TOUR_PIPELINE.md) — the pre-rendered tour counterpart
> **System merkle root (shared with sibling, same "what we have today"):**
> `106b80ac5878c4636f0e37822f029289980568f73349350e0e6cdbb0fbd836ad`
>
> This document covers the **live-action** / **Pokémon-Go-class** product: real-world
> camera feed + AI character rendered into the user's space, interactive in real time
> (voice, gaze, body reaction). It shares the cost ladder, the asset cache, the cid'd
> dataset model, and most of the inventory with the realtor pipeline — but flips the
> pre-render / realtime split: **the character is pre-baked, the scene is the real
> world live from the camera.**

---

## 0. The product

**Live-action AR character — a Pokémon-Go-style AI character that lives in the user's
real-world space, sees them, talks to them, reacts to them.**

Two surface forms with the same substrate:
- **Phone / WebXR browser** — instant install, anyone with iPhone-Pro / Quest / Android
- **Meta glasses (endgame)** — passthrough native, hand-tracking native, no phone friction

Three product flavors from the same engine:
1. **Collectible characters** — Pokémon-class: discover, capture, keep, return to
2. **Persistent guides** — realtor-in-listing, museum docent, retail attendant, AR tutor
3. **Custom commissions** — content-creator builds a character (art + voice + personality) and ships it as an AR object their fans can summon

The character has memory across sessions, reacts to gaze, animates lip-sync from its own
generated speech, and runs at 60 fps on-device with a sub-second voice-conversation round trip.

**The bargain we make with the user:**
- No download for v1 — open a WebXR URL
- Character appears within ~2 s
- 60 fps render, no jitter
- Voice round-trip <800 ms (you talk, they reply)
- Persistent: come back tomorrow, same character remembers you

**The bargain we make with compute:**
- Pre-render every artifact about the character (one-time, cid'd, amortizes forever)
- Realtime only the scene (camera feed), the pose (WebXR), the speech, and the LLM
- Run the LLM small + close to the edge (latency > capability for first response)

---

## 1. The cost ladder — same ladder, different choices for live

The architectural cost ladder is identical to the realtor doc. The **choice of tier per
stage shifts** because live AR has a 16 ms / frame budget and a sub-second conversation
budget, but no pre-bake budget for the scene.

| tier | technique | role in this product |
|---|---|---|
| **T0** | character.glb sitting in a Three.js scene under a WebXR-tracked anchor | character placement |
| **T1a** | back-face cutout of the character mesh — free depth + silhouette + alpha | **occlusion behind real objects** (combined with device depth) — the cheapest path to "they're really there" |
| **T1b** | matcap baked from the **location's** captured lighting | character matches the room's ambient light without runtime light sim |
| **T2a** | per-location lightmap (Blender Cycles, baked once during location bind) | photoreal-ish character lighting in known places (museum, listing) |
| **T2b** | screen-space AO on the character | grounding contact |
| **T3** | PBR forward+ on character | **premium screenshot / capture mode only** — too expensive for live 60 fps |
| **T4a** | NN delight on character art (creator build time) | character creator's source-art cleanup |
| **T4b** | img → 3D for the character mesh | **one-time character build** — TRELLIS for hero, stable-fast-3d for fast |
| **T4c** | img → video for the character ("live talking head" video gen at runtime) | **AVOID at runtime** — use a pre-baked animation library + amplitude-driven lipsync instead |

### The runtime choices that fall out

| stage | tier used | why |
|---|---|---|
| character render at 60 fps | T0 + T1a + T1b + T2b | fits in ~3 ms / frame on a phone GPU |
| character occlusion behind real chair/wall | T1a back-face cutout × device depth API | back-face z = labeled-truth depth; compose with WebXR depth or LiDAR |
| character speaks | pre-baked talk animation + amplitude-driven mouth blendshape from TTS PCM | T4c img→video is too slow + temporally unstable for live |
| character looks at user | IKSolver (SpatialBridge `solve_ccd`) on neck/eyes | analytic, deterministic, ~0.1 ms |
| character reacts to user pose | Sapiens body parse (edge) → mapped to character's response state | runs at lower FPS (10 Hz) is fine |
| character voice round-trip | STT (Whisper-tiny on edge) → LLM (Gemma/Marlin local) → TTS (Kokoro streaming) | total budget 200–800 ms |

### What we DON'T do at runtime

- ❌ Any img→3D
- ❌ Any img→video
- ❌ Any diffusion pass
- ❌ Any per-frame depth fusion
- ❌ Any cloud GPU round-trip in the render loop (only in the conversation loop)
- ❌ Server-side rendering (everything visual is client-side WebXR)

---

## 2. Asset inventory — what carries over, what's new for live

### Carried over from realtor pipeline (same models, same locations)

| capability | tool | use here |
|---|---|---|
| body parse (user pose) | **Sapiens-1b** | "the user is leaning forward / looking up" → character reacts |
| img → 3D (character build) | **stable-fast-3d** (fast) / **TRELLIS** (hero) | character mesh from art |
| matting (character art prep) | **finegrain_box_segmenter** + SAM2 | clean alpha on character source art |
| voice clone (character voice) | **Qwen3-TTS-12Hz CustomVoice** | custom character voice from a 60s sample |
| streaming TTS (talking) | **Kokoro** | low-latency speech (RTF ≈ 0.1) |
| STT (listening) | **Whisper-large-v3-turbo** (edge) or Whisper-tiny (phone) | user speech → text |
| character animation library | **LongCat-Video-Avatar-1.5** (offline bake) | idle, talk, wave, point, listen, react clips |
| img edit (character art polish) | **FLUX-dev** + **Qwen_Image_Edit_2511** + flux-bg-remove-LoRA | creator's char-art studio |
| scene spine | `scene_spine.json` + `spine_ops.py` | character + place composition |
| existing rigging pipeline | `MySpace++/studio/skeleton_to_spine.py` + `~/Projects/rigging/` | 25-joint Meta Body rig |
| existing avatar workflow | `photo_to_avatar_rigged.v0` | direct reuse for character creation |
| IK + spatial math | `SpatialBridge.cpp` (`solve_ccd`, `solve_two_bone`, `ik_delta`, `mirror_drift`) | gaze, point, reach behaviors |
| GPU governor | `bin/gpud` (cloud-first, GPU0 reserved for diffusion) | LLM + TTS routing |
| content-addressed cache | `bin/assets` | all characters + places cid'd |

### New requirements specific to live AR

| need | best fit (current) | status |
|---|---|---|
| 6DoF camera tracking on-device | **WebXR Device API** (browser native on iPhone Pro, Android Chrome, Quest browser) | use stock; no install |
| real-world depth (occlusion of character) | **WebXR Depth Sensing API** (LiDAR on iPhone Pro, depth sensor on Quest 3) + back-face cutout fallback | use stock; T1a covers the fallback |
| persistent world anchor (Pokémon stays where dropped) | WebXR Persistent Anchors (Quest 3) or **visual marker + GPS** fallback | mostly stock; fallback we wire |
| amplitude-driven mouth animation | trivial Web Audio API analyser + blendshape weight | ~30 LOC of JS |
| on-device LLM for instant first-token | **gemma-4-E4B-it** (16 GB) or **Marlin-2B-ungated** (11 GB) — both already in `/home/tom/models/` | weights live, need edge-serving |
| persistence (character memory across sessions) | server KV with character_cid + user_id key | trivial, but new wiring |
| multiplayer (your character + my character meet) | WebRTC for voice + Yjs/CRDT for character state | use stock + thin wiring |
| Meta glasses native passthrough | Quest 3 WebXR + future visionOS WebXR | stock when target arrives |

### Reusable from the realtor doc capability map

All of §2 of `REALTOR_VIRTUAL_TOUR_PIPELINE.md` applies — the back-face cutout, the
fused_depth, the scene_to_godot transpiler, the avatar_bake LAYER_STACK, the agent_defs,
the ATLAS cas+by-pass cache. Don't re-list here; this doc inherits.

### Gaps (same as realtor doc)

- IC-Light: not blocking — we pick matcap (T1b) per location, not per frame
- gsplat: not blocking — we don't render the real scene, we render through camera passthrough
- Cosmos-Reason1-7B weights: would be useful as the **character intent reasoner** (decide what the character should do next given what it sees). Currently metadata-only. Not blocking v1.
- `SpatialBridge.so` not built: blocks the IK behaviors (gaze, point). Build it (see realtor doc §9).

---

## 3. Onboarding flows — three actors

### A. Creator onboarding (character author — once per character)

```
TIME COMMITMENT:  ~20 min per character (one-time, reusable across millions of users)

  1. character_art            upload an image OR generate via FLUX with persona prompt
                               (60s, art-board UI shows iterations)
  2. matte cleanup            finegrain_box_segmenter → clean alpha
                               (10s, automated)
  3. mesh build               stable-fast-3d for fast (or TRELLIS for hero pieces)
                               (60–180s, server-side)
  4. rigging                  rig to 25-joint Meta Body (skeleton_to_spine.py)
                               (30s, automated)
  5. voice sample             60s of character speech (creator records OR uploads
                               existing voice clip) → Q3-TTS clone
                               (60s recording + 30s bake)
  6. animation library        select preset clips (idle, talk, wave, point, listen,
                               react) OR record motion via webcam (Sapiens-driven)
                               (5 min if recording; 0s if presets only)
  7. personality              system prompt + skills (what topics they can discuss,
                               what tools they can call — e.g. "tell me about this
                               listing", "show me the kitchen", "answer questions
                               about Picasso's Blue Period")
                               (5 min — creator writes the persona)
  8. preview                  spawn in creator's room via their phone, talk to it,
                               iterate on personality
                               (live)

OUTPUT: character/<cid>/ → ATLAS by-type/3d/ → permanent, reusable, cacheable
  ├─ mesh.glb              (25-joint rigged)
  ├─ voice.zip             (Q3-TTS speaker embedding)
  ├─ anims/                (idle.glb, talk.glb, wave.glb, point.glb, listen.glb, react.glb)
  ├─ personality.md        (system prompt)
  ├─ skills.json           (tool catalog)
  ├─ matcap_default.png    (neutral lighting baked from creator's reference art)
  └─ card.json             (id, name, creator, version, preview thumb, license)
```

### B. Location bind (optional — once per anchored character)

For characters bound to a specific location (museum docent, realtor in their listing,
"the dragon lives in this park"):

```
TIME COMMITMENT:  ~10 min one-time per location

  1. location walkthrough     creator walks the space with phone (same capture as
                               realtor day-1 walkthrough)
  2. SfM bake                 VGGT + cotracker3 → camera path + sparse cloud
                               (server, ~5 min)
  3. depth + normals          DepthPro + Marigold per keyframe
                               (server, ~30s per keyframe)
  4. lighting bake            extract per-region matcap probes + (optional) Blender
                               Cycles lightmap (T2a)
                               (server, ~5 min)
  5. anchor selection         creator drops "character spawn points" on the captured
                               geometry (e.g. "the dragon perches on that statue")
                               (UI, ~2 min)
  6. persistent anchor        register visual anchor or GPS+marker pair
                               (instant)

OUTPUT: place/<slug>/ → permanent
  ├─ place.glb             (low-res geometry for occlusion / collision)
  ├─ keyframes/            (per-keyframe depth + normals, cid'd in by-pass/)
  ├─ matcaps/              (per-region lighting probes)
  ├─ anchors.json          (spawn points + orientations)
  ├─ visual_anchor.png     (marker for re-localization without GPS)
  └─ card.json             (slug, name, owner, gps, anchor_id, hours)
```

### C. User encounter (the consumer flow)

```
TIME COMMITMENT:  <2 seconds from URL-open to character-visible

  1. user opens URL (or scans QR for a place)
       ↓
  2. browser asks for camera + mic permission                          (~1s, user click)
       ↓
  3. WebXR session start: 6DoF tracking + depth API + body parse        (~0.5s)
       ↓
  4. fetch character/<cid>/ from edge CDN (cached, cid'd)               (~200ms first visit, 0ms cached)
       ↓
  5. fetch place/<slug>/ if location-bound                              (~200ms, optional)
       ↓
  6. mount character in scene at anchor + idle animation starts          (instant)
       ↓
  7. character looks at user (IK on gaze via SpatialBridge)              (per frame)
       ↓
  8. user speaks → STT → LLM → TTS → character lip-syncs and replies     (~500–800 ms first-token)
       ↓
  9. session state persisted (server) → next visit, they remember        (background save)
```

---

## 4. The DAG — full ordering with tier mapping

```
                    [CHARACTER CREATION — once per character, ~20 min]
                                          │
        ┌──────────────────┬──────────────┴──────────────┬──────────────┐
        ▼                  ▼                             ▼              ▼
   character_art      voice_sample                  personality      animation
   (upload or         (60s recording)               prompt + skills  set choice
    FLUX gen)              │                             │              │
        │                  ▼                             │              │
        ▼              Q3-TTS clone                      │              │
   finegrain matte     (3.8 GB model)                    │              │
        │                  │                             │              │
        ▼                  │                             │              │
   stable-fast-3d /        │                             │              │
   TRELLIS img→mesh        │                             │              ▼
   (T4b — one-time)        │                             │         LongCat-Video-Avatar
        │                  │                             │         baking (T4c) — bake
        ▼                  │                             │         a CLIP LIBRARY OFFLINE
   skeleton_to_spine.py    │                             │         (idle, talk, wave, point,
   rig to 25-joint         │                             │          listen, react)
   Meta Body               │                             │              │
        │                  │                             │              │
        ▼                  │                             │              │
   Blender avatar_bake.py  │                             │              │
   LAYER_STACK PBR         │                             │              │
        │                  │                             │              │
        └──────┬───────────┴─────────────────────────────┴──────────────┘
               ▼
        CACHE  character/<cid>/  →  ATLAS by-type/3d/
          ├─ mesh.glb       voice.zip
          ├─ anims/         personality.md      skills.json
          ├─ matcap_default.png                 card.json
        ───── AMORTIZES ACROSS EVERY USER ENCOUNTER FOREVER ─────


                    [LOCATION BIND — optional, ~10 min once per place]
                                          │
                              walkthrough.mp4 (creator)
                                          │
        ┌─────────────────────────┬───────┴───────┬───────────────────┐
        ▼                         ▼               ▼                   ▼
   cotracker3                 VGGT           DepthPro            Marigold normals
   point tracks               cam path       per keyframe
                                          │
                              fused_depth.py (5-channel, already wired)
                                          │
                              place.glb + keyframes/depth + keyframes/normals
                                          │
        ┌─────────────────────────┬───────┴───────┬───────────────────┐
        ▼                         ▼               ▼                   ▼
   per-region                Blender         anchor              visual_anchor
   matcap probes (T1b)       Cycles          spawn points        (or GPS+marker)
                             lightmap (T2a,   (creator UI)
                             optional, hero
                             tier only)
                                          │
                              CACHE  place/<slug>/


                    [LIVE USER ENCOUNTER — per session]
                                          │
                          browser opens URL or scans QR
                                          │
        ┌──────────────────────┬──────────┴──────────┬──────────────────┐
        ▼                      ▼                     ▼                  ▼
   camera + mic          WebXR session         fetch                fetch
   permission            6DoF + depth API      character/<cid>/     place/<slug>/
                         (+ body track on      from edge CDN        (if bound)
                         Quest)                (cid'd, immutable
                                                cacheable)
                                          │
                                          ▼
                              RENDER LOOP   60 fps target — ~3 ms/frame budget
                              ───────────────────────────────────────────────
                              ┌─ camera pose ──┬─ device depth ──┬─ body pose ─┐
                              ▼                ▼                  ▼
                              place character at WebXR anchor
                              T1a back-face cutout (free silhouette + depth)
                              compose with device depth API → real-occluded
                              T1b matcap from place/<slug>/ → matches local light
                              T2b SSAO → contact shadow
                              IK gaze at user (SpatialBridge::solve_ccd)
                              play current animation clip
                              amplitude-driven mouth blendshape if speaking
                              ───────────────────────────────────────────────


                              INTERACTION LOOP   async — 200–800 ms target
                              ───────────────────────────────────────────────
                              user mic ─► Whisper-tiny (on-device)
                                          OR Whisper-large-v3-turbo (edge)
                                          → text
                                          │
                                          ▼
                              LLM   gemma-4-E4B-it OR Marlin-2B-ungated (edge)
                              ─ system prompt: character personality.md
                              ─ tools: character skills.json
                              ─ context: place card + session history
                              ─ streaming response
                                          │
                              ┌───────────┴───────────┐
                              ▼                       ▼
                              text → Kokoro stream    text → state update
                              first chunk in ~50 ms   (animation swap to "talking",
                              audio out                amplitude-driven mouth, etc.)
                                          │
                                          ▼
                              audio plays + mouth animates + clip = "talking"
                              ───────────────────────────────────────────────


                              PERSISTENCE
                              ───────────────────────────────────────────────
                              ─ session transcript      → character memory (per-user)
                              ─ user pose history       → "they walked over here"
                              ─ session state           → server KV
                              ─ Pokémon-class "drop"    → anchor + state at GPS
                              ─ multiplayer state       → Yjs CRDT room per place
                              ───────────────────────────────────────────────
```

---

## 5. Pre-render vs realtime — flipped from the realtor doc

| stage | mode | cost | cached as |
|---|---|---|---|
| character mesh (img→3D) | **pre-render** | 60–180 s once | `character/<cid>/mesh.glb` |
| character rigging | **pre-render** | 30 s once | `character/<cid>/mesh.glb` (skinned) |
| character animation library (LongCat-Video-Avatar) | **pre-render** | minutes once | `character/<cid>/anims/*.glb` |
| character voice clone (Q3-TTS) | **pre-render** | 30 s once | `character/<cid>/voice.zip` |
| character matcap (default) | **pre-render** | <1 s | `character/<cid>/matcap_default.png` |
| location geometry (VGGT) | **pre-render** (optional) | ~5 min once | `place/<slug>/place.glb` |
| location depth/normals | **pre-render** (optional) | ~30 s/keyframe | `place/<slug>/keyframes/` |
| location matcap probes | **pre-render** (optional) | ~5 min once | `place/<slug>/matcaps/` |
| location lightmap (hero only) | **pre-render** (optional) | ~5 min once | `place/<slug>/lightmap.png` |
| anchor + GPS register | **pre-render** (location-bound) | instant | `place/<slug>/anchors.json` |
| **WebXR pose** (6DoF camera) | **realtime, on-device** | ~5 ms / frame | – |
| **WebXR depth** (real-world occlusion) | **realtime, on-device** (when sensor available) | ~1 ms / frame | – |
| **body parse** (user pose for character reaction) | **realtime, on-device** Sapiens-edge or server-relayed | ~10 Hz, ~5 ms | – |
| **character render** | **realtime, on-device WebXR** | ~3 ms / frame | – |
| **IK gaze / point** | **realtime, on-device** SpatialBridge::solve_ccd | ~0.1 ms | – |
| **mic → STT** | **realtime** Whisper-tiny on-device OR Whisper-turbo at edge | ~100–200 ms / utterance | – |
| **LLM response** | **realtime, edge** Gemma/Marlin | 200–500 ms first token streaming | – |
| **TTS stream out** | **realtime** Kokoro streaming | ~50 ms first chunk, RTF ≈ 0.1 | – |
| **mouth animation** (amplitude blendshape) | **realtime, on-device** | <0.5 ms / frame | – |
| **animation clip swap** (idle ↔ talk ↔ react) | **realtime, on-device** | trivial | – |
| **session memory write** | **async** | ~10 ms per turn | server KV |

**Flipped rule for live action:**
- **Character** is pre-rendered, content-addressed, amortized across all encounters
- **Scene** is the real world — never pre-rendered, never stored, always live
- **Conversation** is realtime async; only the transcript persists (with consent)

Same architecture, opposite division of labor from the realtor doc.

---

## 6. Dataset byproducts — the "for other apps" angle

Every encounter throws off free, labeled training data. With user consent + ATLAS cid'ing:

1. **STT pairs** — user audio ↔ Whisper transcript → in-the-wild speech-recognition fine-tune
2. **Conversational pairs** — user utterance ↔ LLM response in character → character-personality fine-tune
3. **Voice-clone output ↔ source script** — pristine TTS training pairs per character voice
4. **Mouth-shape ↔ phoneme audio** — amplitude blendshape outputs aligned with Kokoro phoneme stream → lipsync model training data
5. **User pose ↔ character reaction state** — what the user did + how the character chose to respond → embodied-agent training
6. **WebXR camera trajectory** — anonymized 6DoF traces → SLAM / VIO fine-tuning
7. **Device depth ↔ pre-baked place depth** — real-world depth sensor frames aligned with VGGT-baked geometry → depth-sensor calibration / completion
8. **Visual anchor re-localizations** — anchor image + observed image at re-localize → marker detector training
9. **Character mesh ↔ source art ↔ rigged result** — img→3D→rig pipeline pairs → image-to-rigged-avatar training corpus
10. **Multiplayer state diffs** — character behaviors when other characters are present → multi-agent coordination training

> **Self-amortizing loop, same as realtor:** every encounter improves the next character;
> every new character makes the system smarter at building the one after it.

---

## 7. Architectural primitives — what makes live AR cheap

### The back-face cutout, applied to the character (not the scene)

Same trick as the realtor doc, different consumer. The character mesh runs with
`CULL_FRONT` in a secondary material pass:

- **alpha mask** = silhouette of the character against the camera image → for free
- **depth field** = back-face z-buffer → "how far inside the character are you looking"
- **inverted alpha** = `1 − coverage` → for the camera image showing through gaps in the character's silhouette
- **animation cost** = vertex transform only, viewport-cost — that's Blender wireframe speed
- **lighting cost** = matcap fetch + SSAO → ~2 ms total / frame

Proof in `/data/Projects/MySpace++/studio/godot/project/src/backface_test.gd` (run 2026-06-01).

### Device depth × back-face cutout = correct real-world occlusion

The WebXR Depth Sensing API gives a per-pixel real-world depth (LiDAR on iPhone Pro,
depth camera on Quest 3). Composing it with the character's back-face z gives:

```
foreach pixel:
  d_world = device_depth(uv)      // real-world depth at this pixel
  d_char  = char_backface_z(uv)   // character's far-z at this pixel
  if d_world < d_char_near:       // real object IN FRONT of character → discard character pixel
      discard
  else:
      draw character
```

That is the **"the character is correctly behind your couch"** effect, for ~3 ms / frame
of GPU and zero diffusion. On devices without a depth API we fall back to the back-face
cutout alone (still correct silhouette, no hard occlusion).

### Amplitude-driven mouth animation (cheap lipsync)

Pre-baked **talking** animation clip has a mouth-open blendshape range. At runtime:

```js
const analyser = audioCtx.createAnalyser()
analyser.fftSize = 256
const bins = new Uint8Array(128)
// every frame:
analyser.getByteFrequencyData(bins)
const energy = avg(bins.slice(8, 32)) / 255       // voice band ~200–600 Hz
mouth.morphTargetInfluences[OPEN] = energy
```

~30 lines of JS. Looks ~95 % as good as phoneme-driven lipsync for ~0 % the cost.
When we add the audio-flamingo-2 weights later, swap in true phoneme→viseme prediction.

### IK gaze (SpatialBridge::solve_ccd)

Two-bone analytic + CCD already exist in the C++ extension:

- Neck: `solve_two_bone(spine, neck, head, target=user_head)` → 1 IK op
- Eyes: blendshape weights from yaw/pitch → another trivial op
- Cost: <0.1 ms / frame
- Effect: the character actually looks at the user instead of staring through them

### Tiered fallback for every device

| device | tracking | depth | body | LLM | character latency |
|---|---|---|---|---|---|
| Quest 3 WebXR | native 6DoF + hands | depth API | partial (hand) | edge | <16 ms render, <500 ms voice |
| iPhone Pro Safari WebXR | ARKit 6DoF | LiDAR depth | mediapipe.js | edge | <16 ms render, <800 ms voice |
| Android Chrome WebXR | ARCore 6DoF | ARCore depth (mid-tier+) | mediapipe.js | edge | <16 ms render, <800 ms voice |
| iPhone non-Pro / older | ARKit 6DoF | back-face cutout fallback | none | edge | <16 ms render, <1000 ms voice |
| desktop browser | (no WebXR) — fallback to mouse/keyboard "windowed" character | — | mediapipe.js webcam | edge | <16 ms render, <1000 ms voice |
| Meta glasses (endgame) | native 6DoF + body + hands | native | native | edge | <11 ms render, <300 ms voice |

The pipeline ships graceful degradation — every device gets a working character, the
better the device, the more channels light up.

---

## 8. Existing pipelines we plug into (don't rebuild)

### Workflow: `photo_to_avatar_rigged.v0`
The **exact same** workflow the realtor pipeline uses for her own avatar serves the
character-creator. Difference is only the source art: realtor selfie vs character art.
Output is the same shape: rigged GLB + sprite sheet + Godot/Three.js scene file + voice
clip. **Direct reuse, no changes.**

### Workflow: `blob_to_unreal.v0` (livelink pattern)
The Unreal LiveLink pattern (`pose.jsonl` over UDP → animation blueprint) becomes the
**character behavior dispatch** pattern: server-side LLM emits `behavior.jsonl` →
WebRTC datachannel → on-device behavior interpreter → animation clip selector + IK
target setter. Same shape, swap transport.

### Existing agent_defs we wire in

| agent | role in live AR |
|---|---|
| `blender_mcp` | one-time creator-side: bake animation library, lightmap, matcap |
| `comfyui_mcp` | one-time creator-side: character art generation, matting, img→3D submission |
| `chain_render_bridge` | dev-time only — Godot in-editor preview of characters before web export |
| `deepseek_mcp` | runtime LLM (until Gemma-edge / Marlin-edge is live) |
| `infra_orchestrator` | runtime LLM/TTS GPU scheduling |
| `embedding_index` | character semantic search ("show me characters that talk like a librarian") |

### ATLAS + GentlyOS substrate (carries over)

- **`bin/assets`** → every character + place + dataset byproduct is cid'd, deduplicated
- **`bin/gpud`** → cloud-first policy, GPU0 reserved for diffusion at creator time
- **`bin/conductor`** → density-math agent team for the creator's "build this character" prompt
- **`bin/forge`** → backward-resolve "I want a character that can tour my listing" → minimal valid sub-chain

---

## 9. Implementation plan — ordered by ROI

1. **Build `SpatialBridge.so`** (~5 min) — same step as realtor doc:
   `nix-shell -p scons --run "bash build-cpp.sh"`
   Unblocks `solve_ccd` gaze, `solve_two_bone` reach, IK delta.

2. **Stand up a WebXR viewer for a single cached character.glb** (~1 day) —
   Three.js + WebXR Device API + matcap material + amplitude-blendshape lipsync. No
   server, no LLM, no STT yet — just "open URL, see character at anchor, looks at you,
   smiles when you tap." This proves the render loop fits the budget.

3. **Wire Kokoro streaming TTS → WebRTC audio** (~1 day) — same Kokoro that powers
   the realtor's narration, served over WebRTC datachannel. Character speaks pre-written
   lines first; LLM comes next.

4. **Wire on-edge Gemma-4-E4B-it as the character LLM** (~2 days) —
   weights at `/home/tom/models/gemma-4-E4B-it/`. Streaming response, character system
   prompt, skills.json tool catalog. STT (Whisper-turbo edge) on input.

5. **Build the character-creator UI** (~3 days) — single-page that walks creator
   through art → matte → 3D → rig → voice → personality → preview. Drives the
   `photo_to_avatar_rigged.v0` workflow under the hood.

6. **Persistence + multiplayer** (~3 days) —
   server KV for character memory; Yjs CRDT for shared place state. Multiplayer is
   the killer feature (your character meets mine).

7. **Optional: location bind UI + VGGT-driven place capture** (~3 days) — only for
   location-anchored characters; reuses the realtor pipeline's day-1 walkthrough
   bake.

8. **Optional: download `nvidia/Cosmos-Reason1-7B` weights** (~14 GB) —
   currently metadata-only. Cosmos = world model → drives **what the character chooses
   to do next given what it sees of the user / room**. Slots in as the "behavior
   planner" replacing the simple LLM. Not blocking v1.

9. **Optional: `nvidia/audio-flamingo-2` weights** —
   replaces amplitude-driven lipsync with true phoneme-aware viseme prediction. Not
   blocking v1, but is the obvious quality upgrade for v2.

After steps 1–4 you have a working "character speaks at you in AR" demo. Add 5 to make
it a product; add 6 to make it sticky; add 7 to unlock the realtor-in-listing flavor.

---

## 10. The first-character / first-encounter checklist

For the first paying creator's first character to ship:

- [ ] Step 1 done — `SpatialBridge.so` built (IK enabled)
- [ ] Step 2 done — WebXR viewer renders a static character.glb at 60 fps on iPhone Pro + Quest 3
- [ ] Step 3 done — Kokoro TTS streams audio with amplitude-blendshape lipsync
- [ ] Step 4 done — Whisper-edge + Gemma-edge round-trip <800 ms first token
- [ ] Step 5 done — Character-creator UI works: creator goes from a single image to a published, summonable character in <20 min
- [ ] Creator onboarding fixture: ship one test character (art → mesh → rig → voice → personality), record creator's time
- [ ] User encounter test: open URL on iPhone Pro, character appears within 2 s, holds 60 fps, voice round-trip <800 ms, occluded correctly by real chair
- [ ] Quest 3 native passthrough test (same character, no phone)
- [ ] Persistence test: leave the character for a day, come back, character remembers the last conversation
- [ ] Step 6 done — multiplayer: two phones in the same room see the same character at the same anchor, both can talk to it, character maintains coherent context
- [ ] (Optional) Step 7 done — bind the character to a real place via VGGT walkthrough; visitors find it via GPS or visual anchor
- [ ] Pricing + billing — creator publishes a character, fans pay to summon, revenue splits

---

## 11. The five rules — same as the realtor doc, restated for live

1. **cid + pass-tag everything** — characters, places, encounters. ATLAS `bin/assets` does it.
2. **Try T0 / T1 before any GPU heavy or NN call at runtime** — the render loop has 16 ms. Spend none of it on diffusion.
3. **Climb only on demonstrated gap** — "the cheap version doesn't answer the brief because <X>" — X must name a missing axis (occlusion fidelity, lighting realism, lip-sync accuracy, conversation depth).
4. **NN calls (T4) only when reuse < 3 OR no asset exists yet** — img→3D, voice clone, animation bake are all **creator-time, never runtime**. Conversation LLM is the one exception, scoped tightly to the conversation loop, never the render loop.
5. **Every climb's output is a new cid + new pass tag** — today's expensive creator-time bake is tomorrow's free user-time fetch. Across all characters, all places, all encounters.

---

## 12. Where this product is going (the long arc)

**v1** (next 4–6 weeks):
- WebXR character on phone, anchored to a room or GPS point
- Streaming TTS + edge LLM voice loop
- Pre-baked animation library + amplitude lipsync
- Single-player

**v2** (Meta-glasses native):
- Passthrough-native rendering (no phone screen lag)
- Native hand tracking → character can "see" gestures
- Native body tracking → character reacts to posture
- Spatial audio (character voice has 3D position)
- Multi-character scenes (your collected Pokémon hang out in your living room)

**v3** (the world-model upgrade):
- Cosmos-Reason1-7B as the behavior planner (character chooses what to do based on
  understood scene + user state)
- audio-flamingo-2 for true phoneme-driven lipsync
- Persistent characters wandering between users' places
- Character-to-character interaction (multi-agent coordination)

**v4** (creators as a marketplace):
- Character marketplace with revenue splits
- Location-bound characters become content products (museum's official AR docent,
  realtor's brand-aligned avatar, content-creator's character that fans pay to interact
  with)
- Cross-character continuity (the same Pokémon you raised follows you between places)

---

## Appendix A — paths referenced by this doc

```
/data/Projects/MySpace++/studio/
  passes/fused_depth.py                       reused for location bind
  passes/registry.py                          add live-action passes here
  scene_spine.json                            still the spine format
  spine_ops.py                                MASK/CUT/FLIP/REORDER on the character placement
  scene_to_godot.py                           dev-time preview path
  skeleton_to_spine.py                        character rig converter
  blender/mcp_server.py                       creator-time character bake
  blender/scripts/avatar_bake.py              LAYER_STACK PBR for character
  godot/project/cpp/                          SpatialBridge::solve_ccd (gaze IK) — NOT BUILT
  godot/project/src/avatar_rigged_controller.gd  reused as the character controller template
  godot/project/src/meta_xr_mocap_emit.gd     Quest 3 hand/body tracking
  godot/project/src/backface_test.gd          proven cheap-render primitive
  godot/project/src/depth_loop.py             cid'd depth-truth validator
  assets/_workflows/                          photo_to_avatar_rigged + blob_to_unreal patterns
  assets/_agents/agent_defs/                  blender_mcp + comfyui_mcp + chain_render_bridge

/home/tom/models/
  facebook_VGGT/                              location bind (optional)
  facebook_cotracker3/                        location bind (optional)
  apple_DepthPro/                             location bind (optional)
  prs-eth_marigold-normals-v0-1/              location bind (optional)
  TencentARC_Pixal3D/                         character img→3D (hero)
  stable-fast-3d/                             character img→3D (fast)
  facebook_sapiens-pretrain-1b/               user body parse (runtime, edge)
  Qwen3-TTS-12Hz-1.7B-CustomVoice/            character voice clone
  LongCat-Video-Avatar-1.5/                   character animation library bake
  finegrain_box_segmenter/                    character art matting
  Qwen_Image_Edit_2511/                       character art polish (creator side)
  gemma-4-E4B-it/                             edge LLM for live conversation
  Marlin-2B-ungated/                          alt edge LLM
  ultravox-v0_7-glm-4_6/                      speech-to-speech (future)
  SpaceTimeGPT/                               spatiotemporal reasoning (future)

/data/Projects/MediaLab/
  audio/tts/kokoro/                           streaming TTS (the runtime voice)
  audio/asr/whisper/                          STT at edge
  image/sd35-large/, image/flux-dev/          character art generation
  studio/pipeline_ml.py                       autonomous workflow chaining for creator

/data/Projects/ATLAS/
  bin/assets                                  character/<cid>/ + place/<slug>/ cache
  bin/gpud                                    GPU policy at creator time
  bin/conductor                               creator-side "build me a character" agent

/home/tom/Projects/
  lyv-realty-ai/                              host product for realtor-in-listing variant
  rigging/                                    character rigging suite
  zero2onez/                                  orchestration

/data/Projects/gently/.consolidation/
  run19b_spatial/nvidia_Cosmos-Reason1-7B.jsonl  weights to download for behavior planner
  run19_recovered/nvidia_audio-flamingo-2.jsonl  weights to download for true lipsync
```

---

## Appendix B — what's the same, what's different vs the realtor doc

| dimension | realtor doc | this doc |
|---|---|---|
| primary product | pre-rendered virtual tour of a real listing | live AR character in user's real space |
| scene | pre-baked from walkthrough video | live from device camera |
| character | the realtor herself, optional avatar join | THE main thing |
| pre-render budget | per listing (~30 min) | per character (~20 min, much more reusable) |
| realtime budget | none (browser renders cached splats / scene) | 16 ms / frame render + 800 ms / utterance voice |
| target device | any browser | any WebXR browser, ideally Meta glasses |
| cost ladder | same | same |
| asset cache | same (ATLAS by-pass cid'd) | same |
| dataset byproducts | listing-side (relight pairs, furniture removal) | encounter-side (STT, conversation, lipsync, behavior) |
| existing workflow reuse | `realestate.walkthrough_8f28d17e` | `photo_to_avatar_rigged.v0` |
| limiting model | none — pipeline ships today | none — pipeline ships today |

---

## Appendix C — system merkle (same as the realtor doc)

`106b80ac5878c4636f0e37822f029289980568f73349350e0e6cdbb0fbd836ad`

Same scan inputs, same "what we have today" identity. Both docs version-pin against this
root. When new tech lands (Cosmos weights, IC-Light, gsplat), re-run the 5 agent scans,
recompute the root, diff against this — affected sub-trees re-bake; everything else stays
cached.

---

*End of master design document.*
