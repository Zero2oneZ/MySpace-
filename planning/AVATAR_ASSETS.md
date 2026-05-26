# AVATAR_ASSETS.md — Tom's TurboSquid library as the canonical Phase-5 body kit

> Found 2026-05-26. Tom's TurboSquid purchases include a tessellated-skin
> humanoid mesh (`N001.fbx`) plus a **Mega Pack of 210 Skeleton Rigged
> animations** (FBX 2018) covering nearly every motion the avatar
> pipeline needs. This unblocks the "walks-talks" half of the avatar
> use case without any new asset work — we already own production-grade
> body + motion.

---

## The N001 character (Golden Plated Man)

A 791 KB FBX file containing a humanoid mesh with a **distinctive tessellated
polygon skin** — small gold quads tiled across the body, edge-visible.

Why this asset specifically matters for MySpace++:

1. **Distinctive without being identity-loaded.** Photoreal avatars trip
   uncanny-valley + impersonation issues. Generic mannequins are forgettable.
   The polygon-skin is **stylized but human-readable** — recognizable as a
   person, but clearly an abstraction. Great middle ground.
2. **Brand-coherent with the MySpace++ data layer.** The tessellation is
   visually the same primitive we use everywhere else: discrete
   hash-addressed cells, deterministic tiling, content-addressed faces.
   The avatar literally looks like the DAG cache rendered onto a body.
3. **Deformation-robust.** Tiled quad textures survive bone deformation
   without obvious stretching artifacts. A photoreal skin needs careful
   UV maps + normal correction; this just looks fine through any pose.
4. **Re-skinnable.** The face tiles are uniform → trivial to re-color per
   project / per user (gold default, but each MySpace++ "space" can have
   its own palette). MUI v5 theme tokens map directly to per-tile color.
5. **Lipsync-friendly.** The face has clear topological landmarks (mouth,
   eyes, jaw) that Wav2Lip / MuseTalk / SadTalker / EMO can target. The
   tile texture doesn't fight the lipsync model the way a complex
   photographic face would.
6. **Cheap.** 791 KB. Loads instantly in any 3D viewer (three.js,
   model-viewer, Blender). Streams to a browser frame without VRAM cost.

---

## The 210-animation Mega Pack

The asset bundle Tom owns includes ~210 named FBX animations covering:

### Locomotion (covers the "walks" half of walking-talking)
- `Walk`, `Walking While Texting`, `Walk In Circle`, `Walk To Stop`
- `Start Walking`, `Running`, `Jog In Circle`, `Jump`, `Jumping Down`
- `Swimming`, `Treading Water`, `Floating`, `Spin In Place`
- `Catwalk Walk`, `Catwalk Walk Start Turn 180 Right`, etc.
- `Drunk Walk`, `Drunk Idle Variation`
- `Crouch To Stand`, `Stairs` variants

### Idles + body language
- `Idle`, `Happy Idle`, `Fight Idle`, `Mma Idle`, `Old Man Idle`,
  `Soccer Idle`, `Standing Idle 02`, `Goalkeeper Idle`, `Knife Idle`,
  `Orc Idle`, `Zombie Idle`, `Drunk Idle`, `Defender`, `Defensive`

### Communication (key for talking-avatar)
- `Talking`, `Pacing And Talking On A Phone`, `Standing Arguing`,
  `Shaking Hands 1`/`2`, `Pointing Forward`, `Nervously Look Around`,
  `Look Over Shoulder`, `Beckoning`, `Yes`/`No`, `Cheering`, `Yelling`,
  `Sitting Yell`, `Standing Yell`, `Counting`, `Helping Out`

### Emotion + expression
- `Happy Idle`, `Excited`, `Angry`, `Sitting Angry`, `Disappointed`,
  `Defeated`, `Loser`, `Victory`, `Fist Pump`, `Standing Thumbs Up`,
  `Rejected`, `Terrified`, `Mutant Roaring`

### Dance (62 variants — interpretive overlay options)
- Hip Hop ×8, Salsa ×2, Samba ×2, Swing ×2, Jazz, Bellydance, Capoeira,
  Robot, Locking, Step, Wave, Tut, Slide, Snake, Booty, Northern Soul
  Spin, Chicken Dance, Hokey Pokey, Twist, Silly, Thriller Part 3,
  Maraschino, Shopping Cart, Brooklyn Uprock, Breakdance Uprock,
  Ginga Variation 3, Chapa Giratoria, Can Can, Twerk

### Combat + action
- `Fist Fight A`/`B`, `Punching Bag`, `Kick To The Groin`, `Sword Fight One`,
  `Fireball`, `Casting Spell`, `Magic Spell Casting`, `Spell Casting`,
  `Standing 2H Magic Attack 01`, `Shooting Arrow`, `Pistol Aim`,
  `Gunplay`, `Rifle Block`, `Strangling`, `Restrain`

### Daily + work actions
- `Cow Milking`, `Pick Fruit`, `Plant Tree`, `Watering`, `Picking Up Object`,
  `Lifting`, `Using A Fax Machine`, `Opening A Filing Cabinet`,
  `Opening Door Inwards`, `Searching Pockets`, `Petting Animal`,
  `Drinking Fountain`, `Drinking`, `Smoking`, `Sitting Drinking`, `Singing`,
  `Playing Drums`, `Fishing Cast`, `Paddling`, `Cooking`

### Sports
- 8 Golf variants (`Golf Bad Shot`, `Chip`, `Pre-Putt`, `Putt Victory`)
- Soccer: `Header Soccerball`, `Goalkeeper *`, `Stall Soccerball`
- Baseball: `Strike`, `Walk Out`, `On Deck`
- `Quarterback Pass`

### Sitting + transitions
- `Sitting`, `Sitting And Pointing`, `Sitting Clap`, `Sitting Disbelief`,
  `Sitting Drinking`, `Sitting Laughing`, `Sitting Yell`, `Sitting Angry`,
  `Crouch To Stand`, `Standing W_Briefcase Idle`

### Zombie / horror (memetic — useful for branded variants)
- `Zombie Idle`, `Zombie Walk`, `Zombie Kicking`, `Zombie Neck Bite`,
  `Zombie Scratch Idle`, `Zombie Stumbling`, `Zombie Agonizing`,
  `Death From Right`, `Dying`

### Other
- `Praying`, `Inspecting`, `Looking`, `Checking Dice`, `Catwalk Walk`
  variants × 5, `Goalkeeper *` ×4, `Old Man Idle`, `Salsa Dancing ×2`

**~210 motions total.** Plus ~38 accompanying `.mov` / `.mp4` preview
videos for reference.

---

## Integration with the workflow templates

These assets map directly into the templates Claude just authored:

| Template (primary opcode) | N001 / FBX asset role |
|---|---|
| `talking-head-lipsync-from-image` (Audio-Image-to-Video) | N001 head as the IMAGE input; lipsync renders onto the polygon-skinned face |
| `image-to-video-avatar-motion` (Image-to-Video) | N001 mesh + FBX motion clips drive body animation |
| `avatar-photo-to-animated-video` (Image-Text-to-Video) | Same — N001 as reference, text picks the FBX motion to overlay |
| `voice-clone-tts-pipeline` (Text-to-Speech) | Audio output feeds Audio-Image-to-Video lipsync onto N001 |
| `voice-to-text-transcription` (ASR) | Upstream of the full avatar pipeline |
| `prompted-text-generation-with-quality-loop` (Text Gen) | Picks which FBX motion to play based on dialog tone |

**The Phase-5 super-chatbot is now concretely buildable.** The user says
"make me a YouTube avatar that talks and walks." The runtime:

1. `voice-to-text-transcription` template transcribes source audio
2. `prompted-text-generation-with-quality-loop` re-writes the script + picks a
   motion intent ("walking confidently" / "dancing" / "explaining")
3. `voice-clone-tts-pipeline` synthesizes the new audio
4. The picked motion intent → FBX motion lookup → load that animation
   onto N001
5. `talking-head-lipsync-from-image` lipsyncs the new audio onto N001's
   face during the animated walk
6. Composite + render → MP4 → done

**No asset generation step.** Body + face come from the bundle. Frontier
models only touch the text/audio/face-pixel transformations.

---

## Proposed concrete additions

1. **Add an `avatar_assets` table** to global cc.db that catalogs the FBX
   library:
   ```sql
   CREATE TABLE avatar_assets(
     id TEXT PRIMARY KEY,       -- sha256[:16] of asset_path
     kind TEXT NOT NULL,        -- 'mesh' | 'motion' | 'preview'
     asset_path TEXT NOT NULL,
     name TEXT NOT NULL,
     tags TEXT,                 -- comma-separated motion semantics
     duration_s REAL,
     format TEXT,               -- 'fbx' | 'blend' | 'obj' | ...
     size_bytes INTEGER,
     created_at TEXT DEFAULT (datetime('now'))
   );
   ```
2. **A `cc -avatar-scan <dir>` command** that ingests an asset directory:
   - hash each file
   - parse the FBX header for duration
   - guess motion tags from filename ("Walking", "Dancing", "Angry", ...)
   - upsert into `avatar_assets`
3. **Update the lipsync + motion templates** to bind a `$avatar_mesh`
   and `$motion_clip` input, with model_candidates including:
   - `n001-polygon-mannequin` (default)
   - `your-uploaded-mesh.fbx`
   - generated mesh from `image-to-3d-avatar-from-photo`
4. **A "default avatar" project meta** — `cc -setup --avatar n001` sets
   the project's default mesh + motion library.

---

## Why this changes the timeline

Before today: the "walks-talks-avatar" use case in PLAN.md was speculative.
We had:
- Lipsync templates (Audio-Image-to-Video) but no canonical face
- Body-motion templates (Image-to-Video) but no canonical body
- Text-to-Video for body synthesis is still slow + expensive

After today: **the avatar use case is concrete, asset-backed, and runs on
a $1.50 frontier-API budget plus free local FBX + lipsync compute.**

The polygon-skin aesthetic is not just an art choice — it's structurally
aligned with how MySpace++ thinks. Hash-addressed cache → tile-addressed
body. The avatar IS the data model.
