# AI SWARM SUBSTRATE — the ultimate goal
## Tiny boxes · Godot composing them · SSR morphing them · SVG vectorising them · opcodes bounding them · hashes binding them

> **Status:** v1 unification · 2026-06-02
> **Owner:** Tom Lee (Zero2oneZ)
> **Sibling docs (these all roll up into this one):**
> – `BUSINESS_BUILD_PLAN.md` · 7-box business strategy
> – `REALTOR_VIRTUAL_TOUR_PIPELINE.md` · `LIVE_ACTION_AR_CHARACTER.md` · `GAMES_PLATFORM.md` · the three product surfaces
> – `TRANSFORMING_WEBSITE_PLAN.md` · the Next.js + RN polymorphic shell
> **System merkle root (shared across the suite):**
> `106b80ac5878c4636f0e37822f029289980568f73349350e0e6cdbb0fbd836ad`
>
> This document is the unifying vision. Every other doc in the suite is a slice
> of this one: the realtor / AR / games docs describe specific surfaces of the
> swarm; the business plan describes how it earns; the transforming-website
> plan describes the delivery shell. **This doc names the ultimate goal:**
>
> *Own an AI swarm where every behaviour is a tiny content-addressed box with
> its own route, every scene is a composition of boxes authored visually in
> Godot, every render is a morphable SSR that reconstructs itself at runtime,
> every UI is vectorised SVG cheap enough for tiny models to manipulate, every
> action is a bounded opcode that cannot hallucinate outside the scene's code,
> and every character / object / instruction is baked into the same hash so
> behaviour is deterministic and interactive without fear.*

---

## 0. The ultimate goal in one paragraph

What we are building, taking every piece of the substrate together: a network
of **tiny content-addressed boxes** — Godot scenes, ComfyUI nodes, Rust crates,
ATLAS pass scripts, GDScript signal handlers — each with its own route, its
own typed signal surface, and its own cid. **Godot is the composer** — its
node-and-scene model lets us assemble these boxes visually, inject new ones at
runtime, flatten a settled composition to a background texture, and overlay
fresh independent layers on top. **The Next.js shell flattens those Godot
compositions to JSX and morphs SSR per request** — same scene cid, different
runtime state machine, different SSR mode (SSG / ISR / Streaming / RSC / Edge
/ PPR / CSR) chosen on the fly. **SVG is the vectorised I/O for the LLM tier
of the swarm** — a tree of typed paths with attributes that tiny models can
manipulate cheaply, that the existing `passes/svg_layers.py` and
`tesseract/svg.py` modules already produce, and that the `svg_vector_embed`
agent_def already routes. **Rust crates are the in-game runtime that holds
the box graph** — `gently`'s 157 crates are the existence proof. **HTMX is the
morph delivery mechanism** — every `hx-swap` is a layer injection, every
`hx-target` is a CanvasLayer, perfectly mirroring Godot's runtime composition.
**Opcodes are the bounded AI action surface** — `RUN / MAIN / EDIT / SCAN /
WRAP / ACCEPT` already in `loop.jsonl` are the only verbs a swarm member can
emit, and `chain mismatch` is the existing collision detector. **Every
character, object, and instruction is hashed into the same cid space** — so a
tiny LLM controlling behaviour inside a Godot scene cannot hallucinate beyond
the scene's vocabulary, because the vocabulary is the cid'd opcode set and
the scene is the safety rail. The swarm is owned because every part of it
content-addresses back to a root we already pinned (`106b80ac…`), and grows
without diverging because every new box is cid-merged back into the same
substrate.

---

## 1. The seven pieces that compose

The substrate is already complete enough to name the seven pieces precisely.
Each piece is a thing we own today; the swarm is the way we wire them.

The **first piece** is the tiny box: a unit of behaviour with a typed signal
surface, a cid identity, and a small action space. ComfyUI nodes are tiny
boxes (368 of them already indexed in `atoms/nodes_index.json`). Godot scenes
are tiny boxes (14 prebuilt in `studio/godot/project/scenes/`). ATLAS pass
scripts in `MySpace++/studio/passes/` (including `svg_layers.py` and
`fused_depth.py` and the 100+ in `passes/registry.py`) are tiny boxes. Rust
crates in `gently/` are tiny boxes. Agent defs in
`studio/assets/_agents/agent_defs/` (96 of them, including
`svg_vector_embed`, `blender_mcp`, `comfyui_mcp`, `chain_render_bridge`,
`deepseek_mcp`, `infra_orchestrator`) are tiny boxes with explicit MCP
routes. Every one of these has a cid in the ATLAS cas/ and a route either
under `/api/box/<cid>` or via an MCP server endpoint.

The **second piece** is Godot's scene-and-node model as the composer.
Godot's `.tscn` files are text — `format=3`, `[ext_resource]` for imports,
`[node name=… type=… parent=…]` for the tree, `[connection signal=… from=…
to=…]` for events. They're diff-able, mergeable, and cid-able by `bin/assets`
exactly the same way every other asset is. Scenes instance other scenes
(composition), scenes can extend other scenes (inheritance), CanvasLayers
order them in z-space, and `add_child` injects a new scene at runtime.

The **third piece** is the morphing server-side render. The
`TRANSFORMING_WEBSITE_PLAN.md` §5 transformation state machine — one route,
four possible SSR states picked per request — is what makes the swarm's
runtime composition visible on the web. The same composition (same cid set)
can re-render as SSG when fully baked, PPR when partially stale, SSR-Node
when the visitor owns the scene, and CSR-redirect when the device is mobile.
The route's renderer optimises itself.

The **fourth piece** is SVG as the LLM's I/O format. SVG is a tree of typed
elements with attributes — topologically identical to Godot scenes and React
components. It's infinite-scale, GPU-cheap, AI-cheap (a sticker is ~200
tokens of `<path d="…">`), and we already produce it: `passes/svg_layers.py`
emits layered SVG, `tesseract/svg.py` does scene-to-SVG, the
`svg_vector_embed` agent_def consumes SVG and emits vector embeddings (the
substrate has been doing this since at least the morph_engine work). For a
tiny LLM, manipulating SVG is constrained enough that hallucination has
nowhere to go — the model picks from a small grammar of path operations,
checked against the cid'd scene.

The **fifth piece** is the Rust crate runtime that holds the box graph in
memory. `gently/` is the proof of existence — 157 crates already organised
into the CORE / INTELLIGENCE / RUNTIME / IDENTITY / FACE / CHAIN domains per
its `REGISTRY.md`. Each crate is a tiny box with a typed API. The crates
expose routes to the Axum backend at `~/Projects/lyv-realty-ai/backend/`,
which expose routes to the Next.js shell, which serves the flattened Godot
scenes. The chain from Rust-tiny-box → HTTP route → JSX-flattened scene is
unbroken.

The **sixth piece** is HTMX as the morph delivery. HTMX is the JS-free way
to deliver a swarm member's output to the browser: every `hx-get` is a
pull from a tiny box's route, every `hx-swap` is a CanvasLayer replacement,
every `hx-target` is the DOM equivalent of `get_node($"Layer/UI")`. The
existing `bin/vidplay` is HTMX-based; the existing `lyv-realty-ai/dashboard`
uses React Query polling for the same purpose. The two co-exist cleanly —
React for the substrate shell, HTMX for swarm-member outputs streamed in.

The **seventh piece** is the opcode-bounded AI action surface. The `bin/chain`
tool already maintains a typed loop in `loop.jsonl` with columns `seq, ts,
session, status, folder, function, tool, opcode, vis, hash, prev, what`.
The opcodes seen in production are `RUN / MAIN / EDIT / SCAN / WRAP / ACCEPT`,
each with a fixed semantic (`RUN` = subprocess exec, `MAIN` = top-of-tree
work, `EDIT` = file change, `SCAN` = read-only audit, `WRAP` = density
escalation, `ACCEPT` = density commit). `chain mismatch` already detects
opcode collisions — same coordinate touched by conflicting opcodes, on-screen
/ off-screen disagreement, dangling intent. That collision detector is the
swarm's no-hallucination guarantee: a tiny LLM picks an opcode from a finite
list; the chain refuses opcodes that conflict with the scene's cid'd state;
the scene's behaviour stays inside its code.

---

## 2. The tiny box — merkle leaf + route + signal surface

Every box has three faces. Its **identity face** is a cid computed by
`bin/assets` over its content (scene `.tscn`, ComfyUI workflow JSON, Rust
crate `Cargo.toml`+sources, agent_def JSON, pass script). Its **transport
face** is a route: ComfyUI nodes have `POST /prompt` with a node-specific
input schema, agent_defs have an MCP endpoint, Rust crates have Axum
handlers, Godot scenes have a Next.js dynamic route at
`/api/scene/<cid>`. Its **signal face** is the typed list of events it can
emit and the typed list of inputs it accepts; in Godot this is literal
`signal` declarations on the scene's root script, in ComfyUI it's the
input/output port types, in agent_defs it's the JSON-RPC method list, in
Rust crates it's the trait signature.

The swarm is "owned" because these three faces are the same identity at
three levels of abstraction: a Godot scene cid → its compiled JSX cid → its
served HTML cid. Move the scene `.tscn` on disk, and `bin/assets scan` heals
the cid → the JSX rebuilds with the same hash → the HTML re-serves with the
same hash. Owners can audit; consumers can verify; no centralised registry
is needed.

The smallest meaningful tiny box in the swarm right now is a single ComfyUI
node — the `KSampler` for FLUX-schnell is one cid'd JSON workflow, with one
route (`/api/factory` already proxies to it), one signal (`SaveImage` emits a
filename + subfolder), and one fixed schema. A FLUX-schnell box runs in ~3
seconds on a 3090 Ti and emits a cid'd PNG. From the swarm's point of view,
it's a unit of work and a unit of output.

The biggest meaningful tiny box is a full character bundle (the
`character_bundle_v0` schema in `LIVE_ACTION_AR_CHARACTER.md` §3). A
character bundle is a cid over (mesh + textures + animation library + voice
clone + paperdoll layers + staging metadata). It exposes routes for
loading, summoning into a scene, animating, speaking, posing. Its signals
are `speak`, `look_at`, `point`, `react`, `idle`, `dispose`. Its action
space is bounded by the animation library it shipped with, so an LLM
controlling it cannot make it do something it wasn't baked for — the box
is the safety rail.

---

## 3. Godot as the visual composer — inject / flatten / inject

The user's framing — "Godot injects nodes, builds them, allows you to
flatten them into a background, and inject new nodes that act independent
of the whole" — is literally what `CanvasLayer` plus `add_child` plus
`get_viewport().get_texture()` do in Godot 4. A scene starts with a base
`CanvasLayer` at z=0 — the background. Runtime code calls
`add_child(packed_scene.instantiate())` on a child layer, injecting a new
tiny box without touching the background. When the user is done with the
background's content, the runtime calls `var snap =
get_viewport().get_texture(); var tex = TextureRect.new(); tex.texture =
snap; bg_layer.queue_free(); flat_layer.add_child(tex)` — the background is
flattened to a single texture, freeing all its nodes, and new layers can be
injected on top that depend only on the texture, not on the deleted node
tree. This is exactly the back-face cutout / labeled-truth trick from the
realtor doc applied to live composition: once a layer is settled, freeze it
to pixels, build new layers on top against the frozen depth.

In the swarm: every flattened background gets its own cid (a hash of the
texture), and the new layers reference it by cid. The composition graph
remains the merkle DAG. Tiny boxes added to the new layers have their own
cids that depend on the flattened-background cid + their own content. When
the same composition is requested again, `bin/assets find <bg-cid>` returns
the cached texture; no re-render needed; the swarm gets faster the more it
plays. This is how the substrate amortises itself.

The 14 prebuilt Godot scenes are 14 starting compositions. The
`scene_to_godot.py` transpiler emits PackedScene structures from the
`scene_spine.json` format. The proposed `bin/tscn2tsx` (from the prior
turn) flattens any `.tscn` to JSX so the Next.js shell can render it. Inject
/ flatten / inject works equally well on either side: Godot at authoring
time, Next.js with Suspense + portals at render time, both addressed by
the same cid.

---

## 4. Morphing SSR — same cid, different runtime, different render

The transforming-website plan's §5 already declares the rule: one route
serves up to four SSR states depending on request traits. The swarm
extension is that the state is chosen **per cid in the composition**, not
per route. A composition is a list of cids
`[bg_cid, ui_cid, modal_cid, hud_cid]`. The renderer asks each cid which
state it prefers (settled scenes prefer SSG / Edge; live data prefers RSC /
Streaming SSR; wallet-needing prefers CSR-island; subprocess-needing
prefers SSR-Node) and composes the route response from the per-cid
choices. The result is a literal **runtime SSR reconstruction** — the same
URL, same composition cid set, different SSR pipeline depending on which
cids are warm in cache, which are stale, which need fresh subprocess work,
and which need client `window`. The Next.js shell stays unchanged; the
choice machinery lives in a tiny resolver in `(substrate)/_lib/` that reads
the cid manifest and returns the chosen state per request.

"Optimisation at runtime" is then concrete: the resolver tracks a hit-miss
ledger per cid; cids that are consistently warm in the edge cache get
promoted to SSG; cids that are consistently stale get demoted to SSR-Node
with shorter cache TTLs; cids that are touched once and not again get
flagged for eviction. The swarm tunes itself; the renderer is the
controller; the cid graph is the state. This is the same density math
`bin/conductor` does for LLM tier selection, applied to render targets.

---

## 5. SVG as vectorised inference shell — the no-hallucination story

SVG is the ideal I/O format for the tiny LLM tier of the swarm because it
satisfies three constraints simultaneously: it's a tree of typed elements
(matches Godot scenes + React component tree), it's text (token-cheap,
diff-able, cid-able), and it's infinite scale (renders perfectly at every
resolution, GPU-cheap because it's vector). A FLUX-schnell sticker is ~30 KB
PNG; the same shape as SVG is ~2 KB of `<path d="M…Z">` operations. For a
tiny model deciding "tilt the cat ears 10° left because the user nodded,"
manipulating the SVG path is a 10-token edit. Manipulating the PNG is
impossible without re-generating; the swarm's tiny tier cannot do it.

The substrate already has the pipes. `passes/svg_layers.py` produces
layered SVGs from scene compositions. `tesseract/svg.py` (under the
tesseract module) emits scene-to-SVG transformations — that's the 4D
projection logic feeding 2D vector output. The `svg_vector_embed` agent_def
takes an SVG and emits a vector embedding (this is how SVG enters the
semantic search index in `ssot.index.jsonl`). The launches directory is
already shipping SVG logos (`launches/nft-mint-pixelwolves-85f4a8/logo.svg`
from the PIL fallback in `bin/relaunch`). The five DAG SVGs in
`studio/docs/` (`COMPLEX-DAG.svg`, `LOOP-FOUR-DAG.svg`, `Tesseract.svg`,
`TWINS-MASTER.svg`) prove the format is already a first-class artifact.

The no-hallucination guarantee follows from constraining the LLM's
vocabulary to the SVG element grammar plus a bounded set of opcodes. A
tiny model controlling a character's SVG cannot emit `<script>` because
it's not in the grammar; cannot emit invalid attribute values because the
parser rejects them; cannot drift the path beyond what the cid'd template
allows because the template is a code-bound `Path<T>` enum. The character's
behaviour space is the union of (allowed opcodes × allowed SVG mutations),
which is a small, enumerable set. There is nowhere to hallucinate to.

---

## 6. Rust crates as the box runtime

The runtime that holds the swarm in memory is Rust. `gently/` already
proves this — 157 crates organised by domain. The `BUSINESS_BUILD_PLAN.md`
and `TRANSFORMING_WEBSITE_PLAN.md` both depend on the lyv-realty-ai Axum
backend, which is exactly this pattern: typed crates with strict
boundaries, exposed as HTTP routes, talking to Postgres + Redis. The swarm
runtime is the same shape: each crate owns one tiny-box class (the
`character_bundle` crate owns characters; the `factory` crate proxies
FLUX-schnell; the `svg_paths` crate owns SVG mutations; the
`opcode_chain` crate owns the loop.jsonl writer and the mismatch detector;
the `cid_cas` crate owns the by-pass/by-layer/by-name views).

When a swarm member fires (FLUX-schnell generates an image, an LLM emits
an opcode, a character speaks a line), the firing happens through the
crate's typed API. The crate validates the firing (the type system + cid
checks + opcode safety check). The crate writes to `loop.jsonl` (via the
opcode_chain crate). The crate emits the output as a new cid via the
cid_cas crate. Another crate watching for that cid receives it (Redis
pub/sub `cid:new`). The swarm's coordination is the Rust type system, the
loop.jsonl log, and the cid cas — all three already exist.

---

## 7. HTMX as the morph delivery — UI without a build step

HTMX is JS-free, runs as `<script src="https://unpkg.com/htmx.org">`,
and lets every swarm-member output land in the DOM via attribute-level
declarations: `hx-get`, `hx-post`, `hx-trigger`, `hx-target`, `hx-swap`,
`hx-include`. `bin/vidplay` already runs entirely on HTMX. The swarm's
delivery model on the page is: every CanvasLayer in a Godot scene
flattens to an HTMX-target div with a unique `id`; the layer's content is
served from the corresponding cid route; `hx-swap="innerHTML"` replaces
the layer's content when the swarm fires; `hx-swap="afterbegin"` injects
a new node on top; `hx-trigger="sse:cid:new from:body"` listens to the
SSE channel for new cid arrivals. This is the runtime-injection version
of Godot's `add_child` directly in the DOM, with no React build step
required and with the same cid addressing.

React and HTMX co-exist cleanly in the same Next.js shell. React owns the
substrate chrome and the authored components (the dashboard, the wallet
form, the Stripe billing). HTMX owns the swarm-member output streams — the
parts of the page that arrive incrementally from tiny boxes firing on the
server. The `(substrate)/components/` are React; the `[branch]/play/`
content is HTMX-target divs that receive cid'd fragments. Both render
under the same Next.js layout; the choice per layer is local.

---

## 8. Opcode-bound AI — the safety rail that already exists

The `bin/chain` tool already maintains the swarm's action vocabulary in
`loop.jsonl`. Each entry is a row of `seq, ts, session, status, folder,
function, tool, opcode, vis, hash, prev, what`. The opcodes are a closed
set: `RUN` (subprocess), `MAIN` (top-of-tree commit), `EDIT` (file change),
`SCAN` (read-only audit), `WRAP` (density escalation, agent climbs a tier),
`ACCEPT` (density commit, agent finds its place). The recent tail of
loop.jsonl shows the pattern is alive in production: `41 RUN + 9 MAIN` in
the last 50 entries, exactly what you'd expect from an active session.

For the swarm, this set is the LLM's action surface. A tiny model
controlling a character inside a Godot scene does not pick from "any text
the model could emit." It picks from the opcode set, restricted further by
the scene's allowed-signals list. The mapping is:

- a character that should look toward the user → `SCAN target=user pose →
  opcode=MAIN signal=look_at`
- a character that should speak the line "welcome to my shop" → `opcode=RUN
  tool=q3_tts text="welcome to my shop"`
- a character that should fetch a new outfit option → `opcode=SCAN
  by-type/clothing → opcode=EDIT add_child=outfit_cid`
- a character that should escalate to a bigger model for a hard decision →
  `opcode=WRAP tier_up=L2-mid`

If the scene doesn't declare a `look_at` signal, the tiny model cannot emit
`opcode=MAIN signal=look_at` — the validator rejects it. If two opcodes
collide on the same coordinate (the character tries to walk and sit
simultaneously), `chain mismatch` flags it. The character cannot hallucinate
beyond its scene's vocabulary because the scene is code-bound and the
vocabulary is the cid'd opcode set. **Customisation is allowed; hallucination
is not.** The swarm member is interactive but constrained.

---

## 9. Hash binding — character + instruct + object in the same cid space

The `character_bundle_v0` schema (`LIVE_ACTION_AR_CHARACTER.md` §3) already
binds mesh + textures + animation library + voice clone + paperdoll layers
+ staging metadata into one cid. The swarm extension is to also bind the
**instruct prompt** (the LLM's system message for this character) and the
**object parameters** (what the character can interact with and how) into
the same hash. The bundle becomes:

```
character_bundle_v1 = sha256(
   mesh_cid + textures_cid + anims_cid + voice_cid +
   paperdoll_cid + staging_cid +
   instruct_prompt + skills_list + allowed_signals +
   bound_objects[] + opcode_vocabulary
)
```

When you load a character by cid, you load all of those things together,
deterministically. The instruct prompt is the persona, the skills_list is
what tools the LLM can call, the allowed_signals is the scene-bound action
surface, the bound_objects is the set of cid'd items the character can
manipulate, and the opcode_vocabulary is the closed action set the LLM
picks from. None of these can drift independently — they share the cid.
The character that ships today as cid `abc…` is the same character
tomorrow because all of its parts are baked into `abc…`. A new outfit
becomes a new cid; the old cid still references the old outfit. There is
no "the character changed" — there is only "a new cid for the new
character." That is the hash-binding promise.

For interaction without fear of hallucination: every interaction is a
function of (current scene cid, allowed signal, opcode, character cid).
All four are bounded sets. The tiny LLM picks from a finite product. The
state transition is logged to loop.jsonl with the new cid. If the new cid
is already in the cas, the transition is cached; if not, it's a new
unique state the swarm can re-visit later. The swarm grows monotonically,
deterministically, traceably.

---

## 10. The merkle stack — visualising the unification

```
            [SUBSTRATE ROOT  106b80ac5878c463]
                            │
        ┌───────────────────┼───────────────────┐
        │                                       │
   tiny-box layer:                       runtime layer:
   ├ ComfyUI nodes (368 indexed)         ├ Rust crates (gently 157)
   ├ Godot scenes (.tscn cid'd)          ├ Axum routes (lyv-realty-ai backend)
   ├ Pass scripts (registry.py)          ├ ATLAS bin tools (40+ binaries)
   ├ Agent defs (96 JSONs)               └ ollama tier ladder (router.json)
   ├ Character bundles (character_bundle_v1)
   └ SVG assets (svg_layers.py + tesseract/svg.py)
        │
        ▼
   composition layer (Godot):
   ├ scene_spine.json (universal spine format)
   ├ scene_to_godot.py (spine → .tscn)
   ├ bin/tscn2tsx (proposed — .tscn → JSX/TSX)
   ├ CanvasLayer / @branch parallel slot (layer model)
   └ inject / flatten / inject (runtime composition)
        │
        ▼
   delivery layer (Next.js + HTMX + React Native):
   ├ Next.js 14 App Router shell ([branch]/launch/[slug])
   ├ HTMX morph targets (per-layer hx-swap)
   ├ React Three Fiber (3D scenes flattened)
   ├ RN scanner (Vision Camera + MLKit) — extends, doesn't fork
   └ SSR transformation state machine (one route, four states)
        │
        ▼
   AI swarm layer (the ultimate goal):
   ├ opcode chain (loop.jsonl: RUN / MAIN / EDIT / SCAN / WRAP / ACCEPT)
   ├ chain mismatch (collision detector)
   ├ density escalation (conductor: tiny → mid → heavy → cloud)
   ├ cid'd LLM personas (instruct + skills bound to character cid)
   ├ SVG as tiny-LLM I/O grammar
   └ scene-bound action space (no-hallucination guarantee)
        │
        ▼
   merge surface (the substrate root, again):
        every cid'd output from any layer above
        re-merges into ATLAS by-cid / by-pass / by-layer
        and becomes available to every other branch / launch / scene
                            │
            [SUBSTRATE ROOT  106b80ac5878c463]   ← closure
```

The picture is a closed loop. New work enters as tiny boxes (top), composes
through Godot, delivers through Next.js + HTMX, gets controlled by the AI
swarm under opcode bounds, and merges back into the substrate cid surface
(bottom = top). The merkle is the swarm's identity; the swarm is the cid
graph in motion.

---

## 11. First runnable demo — the smallest end-to-end swarm act

Take one Godot scene (`scenes/social_panel.tscn` is the simplest — a pure
UI scene), one ComfyUI workflow (`flux-schnell-txt2img.json`), one
character bundle (any of the cid'd avatars in `assets/_workflows/avatar.*`),
one SVG template (synthesise one fresh: a 200×200 sticker frame), and one
opcode chain (just `RUN → EDIT → ACCEPT`). The demo:

The user opens `http://localhost:3001/snap-filter/play/glittercat-demo` (one
of the existing launches). The Next.js shell flattens
`social_panel.tscn` to JSX and renders it. An HTMX target div listens for
SSE events on `/api/events/cid`. A tiny LLM (qwen2.5:0.5b through the
gpud router) reads the scene's signal list — `[generate_sticker,
swap_outfit, speak_line]` — and the user's input ("make me a sticker that
says hi"). It picks `opcode=RUN tool=factory recipe=quick prompt="a sticker
that says hi in glittery cat ears style"`. `bin/factory` runs FLUX-schnell,
matte, cid the PNG, writes a share record. The cid arrives on the SSE
channel. HTMX swaps the new sticker into the layer. The character's voice
clone (Q3-TTS) speaks "here you go!" via amplitude-blendshape lipsync. The
opcode chain commits: `MAIN scene=social_panel cid=<new_state_cid>`. The
new cid is now in by-cid; any other branch's launch can use the sticker
without re-running FLUX.

That is one round of swarm activity, fully end-to-end, with every piece
of the seven (§1) participating. It runs on today's substrate; nothing
new needs to be invented, only wired. The wiring sequence is:

1. Generate one stable `character_bundle_v1` for the demo character (lift
   the existing photo_to_avatar_rigged workflow with the added instruct
   prompt + opcode vocabulary; this is a 50-line JSON addition).
2. Implement the SSE channel at `/api/events/cid` (Node runtime route handler
   that subscribes to a watch on `assets/cas/`).
3. Implement `bin/tscn2tsx` to flatten `social_panel.tscn` to JSX (the
   ~300-line transpiler from the prior turn).
4. Add the HTMX `hx-trigger="sse:cid:new from:body"` and `hx-swap` markup
   into the flattened JSX target div.
5. Wire a tiny-LLM opcode picker that posts the chosen opcode to
   `bin/chain add main "<opcode> <args>" --json`.

Done in ~3 engineer-days from current state. After that, every additional
swarm member is a new tiny box added to the same wiring — no architectural
change.

---

## 12. The one-page version

**Q: What is the ultimate goal?**
Own an AI swarm where every behaviour is a tiny cid'd box with its own
route, every scene is a composition of boxes authored in Godot, every
render is a morphable SSR that reconstructs at runtime, every UI is
vectorised SVG, every action is a bounded opcode that cannot hallucinate
beyond the scene's code, every character is hash-bound to its instruct +
skills + objects, and the merkle root closes the loop.

**Q: What's the safety guarantee?**
The tiny LLM picks from a finite product: (current scene cid × allowed
signal list × opcode vocabulary × bound object cids). There is no out-of-
band action. `chain mismatch` rejects opcode collisions. The scene is the
code-bound safety rail.

**Q: What is "morphing SSR"?**
The Next.js route resolves the SSR state per-cid in the composition (SSG /
ISR / SSR / Streaming / RSC / Edge / PPR / CSR), not per-route. Same URL,
different per-cid render strategy chosen at request time. Settled cids go
to Edge SSG; live cids go to Streaming SSR; subprocess cids go to SSR-Node.
The renderer tunes itself.

**Q: Why SVG?**
Because a tiny LLM can manipulate it cheaply (path-level edits ~10 tokens),
the substrate already produces it (`passes/svg_layers.py`, `tesseract/svg.py`,
`svg_vector_embed` agent_def), and it scales infinitely without GPU cost.

**Q: How does Godot inject / flatten / inject?**
`add_child(packed_scene.instantiate())` injects. `get_viewport().get_texture()`
flattens. `queue_free()` releases. New layers `add_child` on top. Cid the
flattened texture so the next composition starts from a cached background.

**Q: When does the demo run?**
Around 3 engineer-days from current state — wire the SSE channel, the
tscn2tsx transpiler, the opcode picker, and one character_bundle_v1. After
that, every new swarm member is a tiny box on the same wiring.

---

## Appendix A — every piece named in this doc, with paths

```
TINY BOX REGISTRY
  /data/Projects/ATLAS/atoms/nodes_index.json           368 ComfyUI nodes
  /data/Projects/ATLAS/atoms/models.json                26 LLM models
  /data/Projects/ATLAS/atoms/tools.json                 MCP tool toggles
  /data/Projects/ATLAS/atoms/flows.json                 visual pipeline catalogue
  /data/Projects/ATLAS/atoms/agents.json                agent roles
  /data/Projects/MySpace++/studio/assets/_agents/agent_defs/    96 agents (incl. svg_vector_embed)
  /data/Projects/MySpace++/studio/assets/_workflows/    47 workflows
  /data/Projects/MySpace++/studio/godot/project/scenes/ 14 prebuilt Godot scenes
  /data/Projects/MySpace++/studio/passes/registry.py    100+ inference passes
  /data/Projects/MySpace++/studio/passes/svg_layers.py  SVG layer producer

CHAIN + OPCODES
  /data/Projects/ATLAS/bin/chain                        loop.jsonl writer + mismatch detector
  /data/Projects/ATLAS/loop.jsonl                       opcode chain (RUN/MAIN/EDIT/SCAN/WRAP/ACCEPT)
  /data/Projects/ATLAS/.chain/                          per-folder local copies

PROMPTING + ROUTER
  /data/Projects/ATLAS/bin/conductor                    density-math agent team assembly
  /data/Projects/ATLAS/bin/forge                        backward-resolve workflow from goal
  /data/Projects/ATLAS/bin/gpud                         GPU governor :11430
  /data/Projects/ATLAS/ollama/router.json               8-tier escalation ladder

GODOT COMPOSITION
  /data/Projects/MySpace++/studio/scene_spine.json      universal spine format
  /data/Projects/MySpace++/studio/scene_to_godot.py     spine → .tscn
  /data/Projects/MySpace++/studio/godot/project/        the Godot 4.6.3 project
  (proposed) /data/Projects/ATLAS/bin/tscn2tsx          .tscn → JSX/TSX transpiler

NEXT.JS DELIVERY
  ~/Projects/lyv-realty-ai/frontend/dashboard/          Next 14 App Router shell
  ~/Projects/lyv-realty-ai/frontend/scanner/            RN 0.76.5 + Vision Camera + MLKit
  ~/Projects/lyv-realty-ai/backend/                     Axum + SQLx + Redis + JWT
  /data/Projects/ATLAS/bin/vidplay                      HTMX playground (current)
  /data/Projects/ATLAS/bin/relaunch                     merkle-tree branch CLI

SVG WORK
  /data/Projects/MySpace++/studio/passes/svg_layers.py  layered SVG producer
  /data/Projects/MySpace++/studio/tesseract/svg.py      4D → 2D SVG projection
  /data/Projects/MySpace++/studio/assets/_agents/agent_defs/vm_mspc_001.agents.agent_defs.svg_vector_embed.active.json
  /data/Projects/ATLAS/fn/gently__gently-face-svg.html  gently face SVG mount
  /data/Projects/MySpace++/studio/docs/*.svg            5 DAG diagrams in this docs/

HASH BINDING
  character_bundle_v0 schema in LIVE_ACTION_AR_CHARACTER.md §3
  (proposed) character_bundle_v1 adds instruct + skills + allowed_signals
                                  + bound_objects + opcode_vocabulary
```

---

## Appendix B — system merkle (closure)

`SYSTEM_MERKLE_ROOT = 106b80ac5878c4636f0e37822f029289980568f73349350e0e6cdbb0fbd836ad`

The same root the five sibling docs pin against. The swarm IS the substrate
in motion; the merkle root is the substrate at rest. Every cid the swarm
emits merges back into this root. Every cid the swarm reads comes from this
root. The closure is total: the swarm is owned because the root is owned,
and the root is owned because we computed it, persisted it, and re-prove it
every time the inventory changes.

---

*End of unification document.*
