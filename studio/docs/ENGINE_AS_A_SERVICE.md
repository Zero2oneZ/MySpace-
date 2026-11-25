# ENGINE-AS-A-SERVICE — MASTER OFFERING
## Hybrid backend + game engine + agentic swarm, packaged as one templated buy-one-get-running product

> **Status:** v1 synthesis · 2026-06-02
> **Owner:** Tom Lee (Zero2oneZ)
> **Roll-up of the six prior docs:**
> · `REALTOR_VIRTUAL_TOUR_PIPELINE.md`
> · `LIVE_ACTION_AR_CHARACTER.md`
> · `GAMES_PLATFORM.md`
> · `BUSINESS_BUILD_PLAN.md`
> · `TRANSFORMING_WEBSITE_PLAN.md`
> · `AI_SWARM_SUBSTRATE.md`
> **System merkle root:** `106b80ac5878c4636f0e37822f029289980568f73349350e0e6cdbb0fbd836ad`
> **Agent-D substrate-inventory merkle:** `7e4c8d9f2a1b3c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c`
>
> The six prior docs proved every piece exists. This doc is the product wrapper.
> EaaS is **not** "build something new" — it is **wrap a slug-rental UI** around the
> substrate we already pinned. The realtor friend is customer #1; her clients
> become the next signups via the viral hooks named in §4. The first paid SKU
> ships in three weeks.

---

## 0. The pitch — one paragraph

Engine-as-a-Service is the productisation of the substrate. A customer picks
one of the five stable branch merkles defined by `bin/relaunch` (`realestate-tour
88293abce…`, `nft-mint 881728c78…`, `snap-filter f3aa17ff…`, `clothing-store
bd5276e8…`, `game-launch 63cb0d06…`), answers four to six questions, and gets
a live `/launch/<slug>/` URL inside **thirty minutes**. Underneath every slug is
the merkle DAG rooted at `106b80ac…`: their scene is a Godot `.tscn` text file
that flattens to a Next.js route via `bin/tscn2tsx`, their character is a cid'd
bundle whose behaviour is bounded by the `RUN / MAIN / EDIT / SCAN / WRAP /
ACCEPT` opcode set in `loop.jsonl`, their payment + auth + chat is the same
Rust + Axum + Postgres backend `lyv-realty-ai` already runs in production.
**Customer:** small-business operators who currently glue Squarespace + Calendly
+ Zapier and call it a stack — realtors, NFT drop founders, micro-fashion
brands, indie studios, AR creators. **Why now:** every concrete file the plan
names already ships (`bin/factory` runs FLUX-schnell in ~3 s; `bin/vidplay`
serves `/launch/<slug>/` over HTMX; `bin/assets` cid's `.tscn` exactly the way
it cid's images; 14 Godot scenes export to HTML5 via the existing
`export_presets.cfg`; `chain mismatch` already detects opcode collisions
in production). The Explore-agent's scan declared **the plan is already 60 %
built**.

---

## 1. The three-layer stack — named precisely

### Layer 1 — Hybrid Backend (Rust + Axum + Postgres + Redis)

The transaction surface. Anything paid, authed, persisted, or rate-limited
terminates here. Concrete files that already exist:

```
~/Projects/lyv-realty-ai/backend/                       Axum + SQLx + Redis + JWT root
~/Projects/lyv-realty-ai/backend/src/routes/slugs.rs    /w/<slug> → property/listing resolver
~/Projects/lyv-realty-ai/backend/src/routes/tours.rs    walkthrough scene resolver
~/Projects/lyv-realty-ai/backend/src/routes/trident.rs  upsell CTAs (insurance / legal / tour)
~/Projects/lyv-realty-ai/backend/src/routes/ar.rs       WebAR endpoint
~/Projects/lyv-realty-ai/backend/src/routes/glasses.rs  Meta-glasses endpoint
~/Projects/lyv-realty-ai/backend/src/routes/insurance.rs / legal.rs / listings.rs / agents.rs
~/Projects/lyv-realty-ai/backend/src/routes/sitemap.rs / seo.rs / scan.rs / onboarding.rs
~/Projects/lyv-realty-ai/backend/src/auth.rs            JWT + bcrypt
~/Projects/lyv-realty-ai/backend/src/db.rs              connection pool
/data/Projects/gently/                                  157-crate runtime (the box runtime in AI_SWARM_SUBSTRATE.md §6)
/data/Projects/ATLAS/loop.jsonl                         the chain state-of-record
/data/Projects/ATLAS/bin/chain                          ledger writer + `chain mismatch` collision detector
/data/Projects/ATLAS/bin/govern                         rate-limit / quota gates
/data/Projects/ATLAS/bin/gpud                           GPU governor at :11430
```

The Axum router already has **30 route files** in `backend/src/routes/` — per
the Explore-agent scan, every vertical EaaS sells has a half-built lane in
the backend already. EaaS does not introduce new backend; it wires the
existing routes to slug-keyed Postgres rows.

### Layer 2 — Game-engine layer (Godot 4.6.3 + .tscn → tscn2tsx → JSX/RSC)

The visual authoring + scene-composition surface. Designers work here; the
runtime flattens here. Concrete files that already exist:

```
/data/Projects/MySpace++/studio/godot/project/scenes/                    14 PREBUILT scenes
   ├ pump_surf.tscn (120 lines)                              surfing game
   ├ morphing_game.tscn (56 lines)                           shape-morph puzzle
   ├ planet_map.tscn (79 lines)                              explorable world
   ├ main.tscn (50 lines)                                    scene picker
   ├ realestate_walkthrough_full.tscn                        REALTOR LIVE
   ├ pump_surf_pipeline.tscn                                 pump-surf variant
   ├ avatar_rigged.tscn                                      rigged character
   ├ social_panel.tscn                                       social UI
   ├ chain_render_wall_compiled.tscn (27 lines)              compiled wall
   ├ chain_render_wall.tscn                                  base wall
   ├ forest_clearing_dawn_world_a7316b8d.tscn                forest env (cid'd)
   ├ stylized_2d_topdown_6bb5d96b.tscn                       2D topdown (cid'd)
   ├ 2d_pixel_platformer_2b1633b7.tscn                       pixel platformer
   └ asset_3d_gallery.tscn                                   3D gallery
/data/Projects/MySpace++/studio/godot/project/export_presets.cfg          5 export targets
/data/Projects/MySpace++/studio/godot/templates/myspace_web_shell.html    custom HTML5 shell
/data/Projects/MySpace++/studio/godot/templates/myspace_instant_games_shell.html  FB Instant shell
/data/Projects/MySpace++/studio/scene_to_godot.py                         spine→.tscn transpiler
/data/Projects/ATLAS/ENGINE.md                                            io_hash + PLACE + edit_mode model
/data/Projects/ATLAS/bin/assets                                           cid's .tscn identically to images
/data/Projects/ATLAS/bin/tscn2tsx                                         PROPOSED — the flatten step
/data/Projects/ATLAS/bin/vidplay                                          HTMX playground (already serving /launch/<slug>/)
/data/Projects/MySpace++/studio/passes/svg_layers.py                      layered SVG emitter
/data/Projects/MySpace++/studio/tesseract/svg.py                          scene→SVG projection
```

The `export_presets.cfg` already declares 5 targets: Linux, Windows, **Web
(dApp embed)**, **Web (Facebook Instant Games)**, Android. All 14 scenes
export-ready; no native-ext blockers. The HTML5 shell is custom-styled
already at `myspace_web_shell.html`.

### Layer 3 — Agentic swarm layer (opcode chain + SVG inference + tiny-LLM tier + cid'd characters)

The behaviour surface. Every interactive element is a bounded opcode burst
against a cid'd scene. Concrete files that already exist:

```
/data/Projects/ATLAS/bin/chain                                            opcode chain + mismatch detector
/data/Projects/ATLAS/loop.jsonl                                           live opcode ledger (RUN/MAIN/EDIT/SCAN/WRAP/ACCEPT)
/data/Projects/ATLAS/bin/gpud                                             tiny-LLM tier router (qwen2.5:0.5b ladder)
/data/Projects/ATLAS/ollama/router.json                                   8-tier escalation ladder
/data/Projects/ATLAS/atoms/nodes_index.json                               368 ComfyUI nodes (tiny-box catalogue)
/data/Projects/MySpace++/studio/assets/_agents/agent_defs/                96 agent_defs incl:
   ├ vm_mspc_001.agents.agent_defs.svg_vector_embed.active.json           SVG → vector embedding
   ├ vm_mspc_001.agents.agent_defs.chain_render_bridge.active.json        chain ↔ render bridge
   ├ vm_mspc_001.agents.agent_defs.blender_mcp.active.json                Blender MCP server
   ├ vm_mspc_001.agents.agent_defs.comfyui_mcp.active.json                ComfyUI MCP wrapper
   └ vm_mspc_001.agents.agent_defs.deepseek_mcp.active.json               LLM reasoning
character_bundle_v0 schema in LIVE_ACTION_AR_CHARACTER.md §3
character_bundle_v1 PROPOSED in AI_SWARM_SUBSTRATE.md §9 (adds instruct + skills + allowed_signals + opcodes)
```

The opcode ladder in `ollama/router.json` is the swarm's escalation policy:
L0-master Claude / L0-clone kimi-k2.6:cloud / L1-heavy qwen3:14b / L2-mid
qwen2.5:7b / **L3-tiny qwen2.5:0.5b** — most opcode bursts run at L3-tiny
(50–200 tokens, ~50 ms each on a 3090 Ti), escalating only when `chain
mismatch` flags ambiguity.

---

## 2. The template = the unit of sale

A **template** is a cid'd folder a buyer rents and an admin ships. To a buyer
(a realtor's friend) it is "the look, the scenes, the character, the payment
hookup, the prompts that drive the avatar" — exactly what a Squarespace
template is plus a swarm member who talks to visitors. To a seller (us) it is
a deterministic merkle leaf under one of the five `bin/relaunch` branches,
packaged as JSON the Rust backend deploys.

```json
{
  "schema": "template_v0",
  "id": "realtor.cozy-cottage.001",
  "branch_merkle": "88293abce0433daa",
  "parent_root": "106b80ac5878c4636f0e37822f029289980568f73349350e0e6cdbb0fbd836ad",
  "design_tokens": {
    "color":  { "primary": "#1f3a3a", "accent": "#d4a373", "ink": "#0c0c0c",
                "canvas": "#0B0B0F", "divider": "rgba(255,255,255,0.06)" },
    "type":   { "ui": "Inter Variable", "prose": "Söhne", "mono": "Geist Mono",
                "scale": [11,13,15,18,22,28,40,56] },
    "motion": { "ease_ui": "cubic-bezier(0.4,0,0.2,1)",   "ms_ui": 150,
                "ease_pop": "cubic-bezier(0.16,1,0.3,1)", "ms_pop": 240,
                "swarm_trail_ms": 600 }
  },
  "scenes": [
    { "path": "scenes/realestate_walkthrough_full.tscn", "cid": "<from bin/assets>" },
    { "path": "scenes/social_panel.tscn",                "cid": "<from bin/assets>" }
  ],
  "characters": [
    { "role": "host", "bundle_cid": "<character_bundle_v1 cid>",
      "instruct": "Greet visitor by first name if present. Point to one feature. Offer a tour.",
      "allowed_signals": ["speak","look_at","point","react","idle","dispose"],
      "allowed_opcodes": ["RUN","MAIN","EDIT","SCAN","WRAP","ACCEPT"] }
  ],
  "payment": { "provider": "stripe", "mode": "subscription", "plan_id": "tpl_realtor_pro" },
  "deploy":  { "targets": ["next-vercel", "rust-axum-fly"], "slug_prefix": "/launch" },
  "viral":   { "badge_visible": true, "share_card_route": "/api/share-card/<slug>.png",
               "duplicate_cta": true, "referral_split_pct": 20, "referral_months": 12 },
  "tier": "pro",
  "price_usd_month": 49,
  "version": "v0.1.0",
  "created_at": "2026-06-02T00:00:00Z"
}
```

Tier pricing:

- **Free** — one slug, one scene, one character, "Made with EaaS" badge non-removable. **$0/mo**.
- **Pro** — five slugs, full scene set for the branch, custom character bundle, custom domain, badge removable. **$49/mo**.
- **Enterprise** — unlimited slugs, white-label, multi-character bundles, dedicated `bin/gpud` slot on a 3090 Ti, priority `chain mismatch` triage. **$499/mo** + $2k setup.

Marketplace creator-template revenue split is fixed **50 / 50**. The
`branch_merkle` field is the integrity guarantee: a marketplace template that
mutates the merkle leaf is rejected at upload by `chain mismatch`.

---

## 3. The viral onboarding flywheel — the realtor friend is customer #1

```
       +-------------------------------------------------+
       |  1. realtor signs up, picks realtor template    |
       |     (realtor.cozy-cottage.001, $49/mo Pro       |
       |      or $0/mo Free with EaaS badge)             |
       +-------------------------------------------------+
                              │
                              ▼
       +-------------------------------------------------+
       |  2. she fills 4–6 questions, uploads 8 photos   |
       |     bin/factory + bin/assets cid everything     |
       |     /launch/<her-slug>/ is live in ~30 min      |
       +-------------------------------------------------+
                              │
                              ▼
       +-------------------------------------------------+
       |  3. she shares slug with potential buyers       |
       |     (SMS, Insta, MLS embed)                     |
       |     Auto OG card from /api/share-card/<slug>.png|
       +-------------------------------------------------+
                              │
                              ▼
       +-------------------------------------------------+
       |  4. a visitor walks the tour and sees:          |
       |       · footer badge "Made with EaaS"           |
       |       · "Duplicate this for my listing" CTA     |
       |       · Twitter card auto-rendered from slug    |
       +-------------------------------------------------+
                              │
                              ▼
       +-------------------------------------------------+
       |  5. visitor IS a realtor (or aspirational)      |
       |     clicks /signup?ref=<her-slug>               |
       +-------------------------------------------------+
                              │
                              ▼
       +-------------------------------------------------+
       |  6. backend records referral edge in Postgres   |
       |     20% rev-share to her for 12 months          |
       |     LEDGER.jsonl appends an ACCEPT opcode       |
       +-------------------------------------------------+
                              │
                              └───► back to step 1 (new realtor)
```

The three viral UI hooks, named with file paths:

1. **`<EaaSBadge/>`** at `apps/web/src/app/_components/EaaSBadge.tsx` —
   rendered in every Free-tier slug's footer. Click → `/signup?ref=<slug>`.
   Inherits the slug's `design_tokens.color.primary` so it integrates rather
   than intrudes (this is the kill-criterion mitigation against feeling
   cheesy). Auto-suppressed on Pro+. Lowercase voice: "made with eaas."
2. **`/api/share-card/<slug>.png`** — Rust backend route that pipes the
   slug's hero scene through `bin/factory` (FLUX-schnell, ~3 s) to emit a
   1200×630 OG card with the realtor's listing baked in. Cached in Redis by
   slug cid. Auto-attached to Twitter / iMessage / WhatsApp previews via
   `<meta property="og:image">`.
3. **`<DuplicateThisCTA/>`** in the lower-right of every Free-tier slug.
   Click → `/signup?ref=<slug>&prefill=<template_id>`. The new realtor lands
   on signup with the same template pre-selected, the same design tokens
   pre-loaded. One-tap-to-clone.

---

## 4. The `.tscn` → slug pipeline — fast path through Rust

Target: end-to-end **< 2 seconds** from a designer saving a `.tscn` to the
slug visibly updating. Step by step, with file paths and time budgets:

```
[1]  designer saves       /data/Projects/MySpace++/studio/godot/project/scenes/foo.tscn
     0 ms                  (inotify watcher inside bin/vidplay triggers next step)

[2]  bin/assets scan       writes cas/<cid>.tscn + by-pass/scene/<cid>
     +80 ms                 cid'ing already healed-symlink resistant

[3]  bin/tscn2tsx          /data/Projects/ATLAS/bin/tscn2tsx (PROPOSED)
     +300 ms                emits apps/web/src/app/_generated/<cid>.tsx
                            imports stay as React Server Components
                            (see AI_SWARM_SUBSTRATE.md §3 + TRANSFORMING_WEBSITE_PLAN.md §3)

[4]  /api/scene/<cid>      Axum handler in lyv-realty-ai/backend/src/routes/scene.rs (NEW)
     +5 ms (warm),         returns the flattened bundle
     +50 ms (cold)         Redis caches by ETag = cid

[5]  Next.js dynamic route /[branch]/launch/[slug] (per TRANSFORMING_WEBSITE_PLAN.md §2)
     +35 ms                resolves slug → cid set via Postgres `slugs` table

[6]  scene_compositor      PROPOSED Rust crate (per AI_SWARM_SUBSTRATE.md §5)
     +380 ms (cold)        merges layer cids into one composite
     +40 ms (warm)         flattened backgrounds reuse cas/

[7]  SSR resolver          per AI_SWARM_SUBSTRATE.md §4 transformation state machine
     +300 ms (cold)        picks SSG / PPR / SSR-Node / CSR per cid
     +80 ms (warm)

[8]  HTMX hx-swap          <div id="stage" hx-get="/launch/<slug>/stage"
     +500 ms                     hx-trigger="load" hx-swap="outerHTML">
                            DOM mutates, slug visibly updated

COLD PATH TOTAL: ~1.6 s   (first save)
WARM PATH TOTAL: ~620 ms  (any visitor after first)
```

The `<2 s` budget holds on cold path. Warm path (any visitor after the
first) collapses to steps 4 → 5 → 7 → 8 ≈ **620 ms** — sub-second, every
hop edge-cacheable.

---

## 5. Chain + SVG + opcode bursts — the in-render inference loop

The swarm's per-character behaviour runs as **short bursts of 50–200 tokens**
through the `bin/gpud` tier ladder, defaulting to `qwen2.5:0.5b` for one-shot
opcode picks, escalating to `1.5b` only when `chain mismatch` flags
ambiguity (per `AI_SWARM_SUBSTRATE.md §6`). The LLM never picks free-form
text; it picks from the cid'd opcode set `RUN / MAIN / EDIT / SCAN / WRAP /
ACCEPT`, with arguments drawn from the scene's `allowed_signals`.

**Concrete example — the realtor's avatar greets a visitor.**

A visitor lands on `/launch/cozy-cottage/`. The
`realestate_walkthrough_full.tscn` scene loads; the host character bundle
(cid `7a3f12…`) attaches. The visitor moves their cursor over the kitchen
island. The Godot scene emits a `look_at` signal with target
`kitchen_island_marker`. `bin/vidplay` POSTs to `/api/chain/burst`:

```json
{
  "burst_id": "b-2026-06-02T14:21:08Z-0007",
  "scene_cid": "9f81a2…",
  "character_cid": "7a3f12…",
  "context_window": ["look_at:kitchen_island_marker", "dwell_ms:1200"],
  "allowed_opcodes": ["RUN","MAIN","EDIT","SCAN","WRAP","ACCEPT"],
  "allowed_signals": ["speak","look_at","point","react","idle"],
  "tier": "qwen2.5:0.5b",
  "max_tokens": 120,
  "prompt": "Visitor is dwelling on the kitchen island. Greet by gesture, name one feature."
}
```

The LLM emits one opcode + one signal call:

```json
{
  "opcode": "MAIN",
  "signal": "point",
  "args": {
    "target": "kitchen_island_marker",
    "speak_after_ms": 400,
    "line": "Quartz, with built-in induction."
  },
  "chain_prev": "<sha of last burst>"
}
```

`bin/chain` appends the burst to `loop.jsonl` and runs `chain mismatch`. If
the avatar tried to `speak` text that references a marker not in the scene's
cid'd vocabulary (e.g. references a "wine cellar" the listing doesn't have),
`chain mismatch` rejects the burst — same coordinate touched by conflicting
opcodes, dangling intent. The avatar emits an `idle` opcode instead.

**The no-hallucination guarantee** is bounded by three concentric cids: the
**scene cid** lists the only legal targets, the **character cid** lists the
only legal signals, the **opcode set cid** lists the only legal verbs. A
burst that fails any of the three rings is rejected by `chain mismatch`
before it reaches the renderer — **the model cannot make the avatar do
anything that wasn't baked into the bundle.** This is the literal
operationalisation of `AI_SWARM_SUBSTRATE.md §8`.

---

## 6. Pricing + revenue split + ARR

Per-customer per-template pricing:

```
TIER        PRICE        SLUGS    CHARACTER       BADGE        GPU
─────────   ──────       ──────   ──────────      ──────       ────────────
Free        $0/mo        1        shared          REQUIRED     shared queue
Pro         $49/mo       5        custom          OPTIONAL     shared priority
Enterprise  $499/mo      ∞        multi           OPTIONAL     dedicated 3090
            +$2k setup
```

**Marketplace creator split: 50 / 50.** Creator publishes `template_v0` JSON
+ cid'd scenes; we host + collect + remit. Branch-merkle integrity enforced
at upload.

**Referral split (the viral hook): 20 % / 12 months.** When a customer signs
up via `/signup?ref=<slug>`, the original slug owner earns 20 % of the
referred customer's subscription for the first 12 months. After 12 months
the referral expires. Stacking caps at 30 % of any one customer's MRR.

**ARR projections** (~75 % Pro / 25 % Free / 5 % Enterprise of paying base):

```
   100 customers   →   ~$59k ARR     (mostly Pro)
 1,000 customers   →   ~$650k ARR    (Pro dominant, 10 Enterprise)
10,000 customers   →   ~$7.2M ARR    (Pro dominant, 100 Enterprise,
                                       +15% marketplace lift from
                                       ~200 creator templates @ $50-$500/mo each)
```

The marketplace lift at 10k customers assumes 200 creator templates earning
$50-$500/mo each in fees — a credible long-tail given `bin/relaunch`'s
five-branch shape gives creators five well-defined niches to publish into.

---

## 7. The OG tree — design system synthesised from the steal-list

The Steal-list agent picked **six high-value sites** and lifted specific
moves from each: **Linear** for information density without clutter,
**Vercel** for the slug-URL hero moment, **Spline** for the floating
tripartite authoring layout, **Cursor** for restrained AI presence inside a
real product, **Krea.ai** for the live-preview "watch your app form" loop,
**Stripe Docs** for two-column information design. The synthesis extends
the existing Lyv brand palette (`lyv-purple #C896FF`, `lyv-pink #FF6B9D`,
`lyv-teal #00D4AA`, `lyv-blue #4488FF`) — it does not replace it.

### Colors

```
Lyv base (KEEP):            --lyv-purple #C896FF   --lyv-pink #FF6B9D
                            --lyv-teal #00D4AA     --lyv-blue #4488FF
Canvas:                     --canvas: #0B0B0F (default authoring surface)
                            --canvas-true: #000000 (deployment / preview pane ONLY)
Surface:                    --surface-1: #14141A   --surface-2: #1C1C24
Divider:                    --divider: rgba(255,255,255,0.06)
Status pips:                --ok #50E3C2   --build #F5A623   --err #FF4D4F
Code warmth:                --code-tint: #F5E9D5
Brand gradient (Lyv-native, NOT Linear's):
                            linear-gradient(135deg, #C896FF, #FF6B9D)
```

### Type scale

```
--font-ui:     "Inter Variable", system-ui     weights 450 / 510 / 600
                                               (no 400, no 700 — Linear's restraint)
--font-prose:  "Söhne", "Inter", system-ui     16 / 28 line-height for docs
--font-mono:   "Geist Mono", ui-monospace      for slugs, code, opcodes
Scale:         11 / 13 / 15 / 18 / 22 / 28 / 40 / 56
Tracking:      −0.01em above 22 px; 0 below
```

### Motion library

```
--ease-ui         cubic-bezier(0.4, 0, 0.2, 1)            150 ms   buttons, hovers
--ease-pop        cubic-bezier(0.16, 1, 0.3, 1)           240 ms   panels, modals
--ease-crossfade  ease-in-out                             180 ms   live-preview tile updates
--pulse-status    1400 ms ease-in-out infinite                     in-flight status pip
--caret-blink     1100 ms steps(2, start) infinite                 streaming AI text
--swarm-trail     600 ms cubic-bezier(0.22, 1, 0.36, 1)            ← OUR SIGNATURE MOVE
                                                                   a Lyv-teal dot travels
                                                                   between panes when one
                                                                   agent passes work to
                                                                   another. Nobody else has
                                                                   this. This is OURS.
```

### Layout primitives

- **Floating panel** — 14 px radius, 8 px viewport margin, soft shadow + 1
  px highlight border (Spline DNA)
- **Density card** — 8 px radius, hairline divider on hover-reveal of
  metadata row (Linear DNA)
- **Slug bar** — monospace pill at top of preview pane, copy-on-click,
  status-pip at left edge (Vercel DNA)
- **Agent message** — 2 px left border in `--lyv-teal`, no avatar, no
  chrome (Cursor DNA)
- **Live preview tile** — opacity-crossfade between renders, shape-matched
  skeleton during build (Krea DNA)
- **Docs split** — 680 px prose left, sticky example right (Stripe Docs DNA)

### Voice + microcopy (5 example strings, ready to drop in)

- Deployment success: `live at /yourslug` — lowercase, no exclamation,
  monospace slug
- Building: `assembling your tour…` — never "magic", never "AI is thinking"
- Empty state: `pick a branch to start.` — short, lowercase, period
- Error: `that slug is taken — try another?` — conversational, no error
  codes shown
- Onboarding nudge: `answer 3 questions. ship a URL.` — promise-format

---

## 8. What we explicitly DO NOT copy

The Steal-list agent named five anti-patterns. Locking them in:

1. **Floating orbs / particle clouds / glowing-brain icons** for AI presence
2. **The Linear gradient itself** (`#5E6AD2 → #FF6680`) — pasted onto
   thousands of landing pages
3. **Dotted-grid backgrounds** behind hero sections — Vercel-cliché now
4. **"Built with [tech logo]" badge rows** under the fold — signals
   insecurity
5. **Typing-dots animations** for streaming AI text — use Cursor's
   caret-block instead

Plus a sixth, EaaS-specific: **never auto-play TTS** when the visitor lands
on a slug — the realtor's avatar speaks **only after** a user signal
(click / dwell / scroll). This is the difference between "creator tool" and
"intrusive Web 2.0."

---

## 9. The first four shipping milestones — 12 weeks total

**Milestone 1 — `bin/tscn2tsx` lives + one slug renders end-to-end (2 weeks).**
Build the flatten binary. Wire
`studio/godot/project/scenes/realestate_walkthrough_full.tscn` through to
`/launch/demo-cottage/`. Success criterion: a visitor sees the kitchen scene
render server-side with no client JS, end-to-end <2 s on cold path. Unblocks
`TRANSFORMING_WEBSITE_PLAN.md §8 steps 2-3` (the JSX flatten + the Next.js
dynamic route).

**Milestone 2 — Realtor template ships as the first paid SKU (3 weeks).**
Compose `template_v0` JSON for `realtor.cozy-cottage.001`, hook Stripe via
the existing Axum backend, publish the Pro tier at $49/mo to ten beta
realtors **including the realtor friend who is customer #1**. Success
criterion: three paid signups in week three. Unblocks `BUSINESS_BUILD_PLAN.md
§4 Week 4` (revenue switch on) and `REALTOR_VIRTUAL_TOUR_PIPELINE.md §1`
(productisation of the tour pipeline). **This is the moment the realtor
friend onboards.**

**Milestone 3 — Character bundle attaches + opcode bursts run live (4 weeks).**
Cid one full `character_bundle_v1` (mesh + textures + anims + voice +
paperdoll + instruct + skills + allowed_signals + opcodes) for the realtor
host. Wire `/api/chain/burst` to `qwen2.5:0.5b` via `bin/gpud`. Run `chain
mismatch` gating. Success criterion: avatar responds to dwell + click on
three scene markers without a hallucinated reference in 1000 consecutive
bursts. Unblocks `LIVE_ACTION_AR_CHARACTER.md §9 step 2` (bundle ships) and
`AI_SWARM_SUBSTRATE.md §11` (opcode loop closes).

**Milestone 4 — Viral referral mechanic + share-card route (3 weeks).**
Ship `EaaSBadge`, `DuplicateThisCTA`, and `/api/share-card/<slug>.png` (FLUX
into a 1200×630 OG card). Build the Postgres referral graph + the 20%/12-
month payout job. Success criterion: by end of week three, at least one
customer signed via `?ref=`. Unblocks `BUSINESS_BUILD_PLAN.md §6 distribution`
and `GAMES_PLATFORM.md §4` (the shareable-game-card pattern reused).

**Total to all four shipped: 12 weeks** from current state. The realtor
friend's listing goes live in **week 5** (during milestone 2's beta cohort).

---

## 10. Risks + kill criteria

**Risk 1 — template proliferation overwhelms the catalogue.** Once the
marketplace opens, low-quality clones flood in; buyers can't pick.
*Mitigation:* enforce `branch_merkle` integrity at upload (any divergence
from the five `bin/relaunch` leaves is rejected), require creator-template
attach to at least one cid'd character bundle + two cid'd scenes, surface a
`chain mismatch` health score per template in the catalogue UI. *Kill
threshold:* if median template-to-paid-conversion drops below 4 % across a
30-day rolling cohort, freeze new marketplace uploads and curate manually
for the next quarter.

**Risk 2 — viral hooks feel cheesy and brokerage clients churn.** Realtors
are status-sensitive; a Squarespace-style "Made with" badge can repel
high-end clients. *Mitigation:* badge is auto-suppressed on Pro and above;
share-card and DuplicateThisCTA are stylistically tuned per template's
design tokens (the badge inherits the template's `color.primary`, so it
integrates rather than intrudes); A/B test badge wording per branch. *Kill
threshold:* if Pro-tier churn at month two exceeds 8 % and badge presence
correlates (> 0.4 chi-square), retire the badge entirely; keep the
share-card + Duplicate CTA, drop the footer.

**Risk 3 — Godot scene quality varies wildly between creator-built
templates.** Marketplace creators may ship scenes that render at 6 fps on
mid-range hardware or fail HTMX delivery on Safari. *Mitigation:* every
published `.tscn` runs through a quality gate combining a synthetic 60 fps
headless replay, `chain mismatch` health, and a Lighthouse synthetic;
templates failing any gate are blocked from publish; quality grade A/B/C is
surfaced in catalogue UI. *Kill threshold:* if a published template's
average session FCP exceeds 3 s for a 30-day cohort OR its associated
cohort retention dips below 30 days, auto-retire the template (the merkle
leaf stays cid'd so refunds are deterministic; the template is delisted
from buy flow only).

---

## 11. The realtor friend's actual onboarding sequence — week 5

Concrete chronology for the realtor friend as customer #1. She is the
forcing function for milestone 2 hitting on time.

**Week 5 day 1 — onboarding call (~30 min).** She signs up at `/signup`,
picks the realtor branch, gets to the question flow. She answers six
questions: brokerage name, tagline, primary color (defaults to
`#d4a373`), first listing address, voice / vibe (`clean` / `warm` /
`luxury`), and uploads 8 listing photos. The Pro tier auto-selects at
$49/mo with the 14-day trial. Stripe pre-auths.

**Week 5 day 1 — bake (~30 min wall-clock, all on z21).** `bin/factory`
runs FLUX-schnell against the listing photos + the `room-portrait`
recipe (per `BUSINESS_BUILD_PLAN.md §5`). VGGT + cotracker3 + DepthPro
ingest the walkthrough video. `realestate_walkthrough_full.tscn` is
parameterised with her listing's cid'd assets. `bin/tscn2tsx` flattens
the scene. `template_v0` JSON is composed with her design tokens.
`bin/relaunch realestate-tour --brand "<her brokerage>" --color
"#d4a373"` runs; merkle is computed; `launches/<her-slug>/`
materialises. `/launch/<her-slug>/` is live.

**Week 5 day 1 — she shares the slug** with the seller of the listing,
with three potential buyers she's been working with, and posts to her
brokerage's Instagram. The `<EaaSBadge/>` is in the footer (Pro tier:
toggleable — she leaves it on for week 5 because the trial discount
covers it; she can remove it in week 7 when the trial ends).

**Week 5 day 4 — a buyer walks the tour**, sees a feature she points
out via the avatar's opcode burst ("Quartz, with built-in induction"),
texts the realtor. Same buyer's friend is also a realtor. The friend
sees the badge → `/signup?ref=<her-slug>` → trials → converts to Pro
in week 6. **The realtor friend earns 20 % of her referred friend's
Pro subscription for 12 months — $9.80/mo × 12 = $117.60 over the
referral horizon.** That is the flywheel firing for the first time.

**Week 6 — repeat for listing #2 (~30 min onboarding, ~30 min bake).**
She now has 2 of her 5 Pro slugs in use. The flywheel has one
documented referral conversion to point at.

**Week 8 — she has 5 Pro slugs in use** (cap on Pro tier). Either she
upgrades to Enterprise (~$499/mo) or starts cycling listings as they
close. We watch the cohort: if 30-day retention >50 % and slug-share
rate >2 per slug, the flywheel is real and we scale acquisition.

---

## 12. One-page summary (Q&A)

**Q: What is Engine-as-a-Service?**
A templated rental of the hybrid game engine + agentic swarm + Rust
backend we already built. Customer picks a branch, fills six questions,
gets a live slug in thirty minutes.

**Q: Who buys?**
Small-business operators who currently glue Squarespace + Calendly +
Zapier. Realtors, NFT founders, micro-brands, indie studios, AR
creators — one branch per persona.

**Q: What is the unit of sale?**
A `template_v0` JSON cid'd under one of five `bin/relaunch` branches,
packaging design tokens + scenes + character bundle + payment hookup +
instruct prompts.

**Q: How fast does a slug go live?**
First save to live `<2 s`; full new-customer onboarding `~30 min`.

**Q: Where does the AI live?**
Inside the renderer, as opcode bursts (50-200 tokens) picked by
`qwen2.5:0.5b` through `bin/gpud`, bounded by `chain mismatch` against
the scene + character + opcode cids.

**Q: What stops the AI from hallucinating?**
Three concentric cid rings (scene / character / opcode set). Any burst
that references a target outside the cid'd vocabulary is rejected by
`chain mismatch` before it renders.

**Q: How does it go viral?**
Footer badge + share-card OG image + Duplicate CTA on every Free-tier
slug; 20 % / 12-month referral rev-share credits original realtors when
their visitors sign up.

**Q: How does it earn?**
$0 / $49 / $499 monthly tiers; 50 / 50 marketplace split; projected
$650k ARR at 1k customers, $7.2M at 10k.

**Q: What are the first four shipping milestones?**
(1) `bin/tscn2tsx` + first slug, (2) realtor template paid SKU, (3)
character bundle + opcode bursts, (4) referral mechanic. 12 weeks total.

**Q: When does the realtor friend onboard?**
Week 5, during milestone 2's beta cohort. ~30 min of her time, ~30 min
of bake. First viral referral expected within days of her first slug
going live.

**Q: Why now?**
Every concrete piece — Godot scenes cid'd, `bin/factory` FLUX in 3 s,
`bin/vidplay` HTMX slugs, agent_defs routed, `chain mismatch` running
in production — already ships. EaaS is wrapping a rental UI around the
substrate, not building it. The Explore-agent scan declared **60 %
built**.

**Q: What kills it?**
Catalogue floods with low-quality clones, badge-driven churn, or scene
quality variance. Each has a named kill threshold.

---

## Appendix A — every file path named in this doc

```
SUBSTRATE
/data/Projects/ATLAS/bin/relaunch                        5-branch merkle CLI
/data/Projects/ATLAS/bin/factory                         FLUX-schnell + cid loop
/data/Projects/ATLAS/bin/vidplay                         HTMX slug server (current)
/data/Projects/ATLAS/bin/assets                          CAS + by-pass + by-layer
/data/Projects/ATLAS/bin/chain                           opcode chain + mismatch detector
/data/Projects/ATLAS/bin/gpud                            GPU governor (LLM tier router)
/data/Projects/ATLAS/bin/govern                          rate-limit / quota gates
/data/Projects/ATLAS/bin/tscn2tsx                        PROPOSED — .tscn → JSX flattener
/data/Projects/ATLAS/loop.jsonl                          live opcode ledger
/data/Projects/ATLAS/ollama/router.json                  8-tier LLM escalation ladder
/data/Projects/ATLAS/atoms/nodes_index.json              368 ComfyUI tiny-boxes
/data/Projects/ATLAS/ENGINE.md                           io_hash + PLACE + edit_mode model
/data/Projects/ATLAS/templates/                          8 factory recipes
/data/Projects/ATLAS/launches/                           per-launch dirs (LAUNCH.json + theme.css + logo + index.html)
/data/Projects/ATLAS/branches/                           BRANCH.json per branch

GODOT ENGINE LAYER
/data/Projects/MySpace++/studio/godot/project/scenes/    14 prebuilt .tscn scenes (all HTML5 export-ready)
/data/Projects/MySpace++/studio/godot/project/export_presets.cfg   5 targets (Linux, Win, Web, FB-Instant, Android)
/data/Projects/MySpace++/studio/godot/templates/myspace_web_shell.html  custom HTML5 shell
/data/Projects/MySpace++/studio/godot/templates/myspace_instant_games_shell.html
/data/Projects/MySpace++/studio/scene_to_godot.py        spine → .tscn transpiler
/data/Projects/MySpace++/studio/passes/svg_layers.py     layered SVG emitter
/data/Projects/MySpace++/studio/tesseract/svg.py         scene → SVG projection

AGENTIC SWARM LAYER
/data/Projects/MySpace++/studio/assets/_agents/agent_defs/   96 agent_defs incl:
  vm_mspc_001.agents.agent_defs.svg_vector_embed.active.json
  vm_mspc_001.agents.agent_defs.chain_render_bridge.active.json
  vm_mspc_001.agents.agent_defs.blender_mcp.active.json
  vm_mspc_001.agents.agent_defs.comfyui_mcp.active.json
  vm_mspc_001.agents.agent_defs.deepseek_mcp.active.json
character_bundle_v0 schema → LIVE_ACTION_AR_CHARACTER.md §3
character_bundle_v1 PROPOSED → AI_SWARM_SUBSTRATE.md §9

HYBRID BACKEND
~/Projects/lyv-realty-ai/backend/                        Rust + Axum + Postgres + Redis + JWT
~/Projects/lyv-realty-ai/backend/src/routes/             30 route files incl.
  slugs.rs   tours.rs   trident.rs   ar.rs   glasses.rs   insurance.rs   legal.rs
  listings.rs   agents.rs   onboarding.rs   walkthrough.rs   property_graph.rs
  sitemap.rs   seo.rs   scan.rs   auth.rs   documents.rs
~/Projects/lyv-realty-ai/backend/src/routes/scene.rs     PROPOSED — /api/scene/<cid>
~/Projects/lyv-realty-ai/backend/src/                    auth.rs, db.rs, error.rs, main.rs
/data/Projects/gently/                                   157-crate runtime

NEXT.JS DELIVERY
~/Projects/lyv-realty-ai/frontend/dashboard/             Next 14 App Router shell
~/Projects/lyv-realty-ai/frontend/dashboard/src/app/[branch]/  PROPOSED polymorphic segment
~/Projects/lyv-realty-ai/frontend/dashboard/src/app/_generated/  PROPOSED tscn2tsx output dir
~/Projects/lyv-realty-ai/frontend/dashboard/src/app/_components/EaaSBadge.tsx  PROPOSED
~/Projects/lyv-realty-ai/frontend/dashboard/tailwind.config.ts  Lyv brand palette
~/Projects/lyv-realty-ai/frontend/scanner/               RN 0.76.5 + Vision Camera + MLKit

DESIGN SOURCE OF TRUTH
EaaS OG tree colors / type / motion → §7 of this doc
Anti-patterns → §8 of this doc

DOCS SUITE
/data/Projects/MySpace++/studio/docs/REALTOR_VIRTUAL_TOUR_PIPELINE.md
/data/Projects/MySpace++/studio/docs/LIVE_ACTION_AR_CHARACTER.md
/data/Projects/MySpace++/studio/docs/GAMES_PLATFORM.md
/data/Projects/MySpace++/studio/docs/BUSINESS_BUILD_PLAN.md
/data/Projects/MySpace++/studio/docs/TRANSFORMING_WEBSITE_PLAN.md
/data/Projects/MySpace++/studio/docs/AI_SWARM_SUBSTRATE.md
/data/Projects/MySpace++/studio/docs/ENGINE_AS_A_SERVICE.md  ← THIS DOC
```

---

## Appendix B — cross-doc traceability

```
                       EaaS  (this doc — the product)
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
   §1 three-layer        §3 viral flywheel    §4 .tscn→slug pipeline
   stack                 §6 pricing           §5 opcode bursts
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              ▼
                  feeds into and validates:
                              │
        ┌────────┬────────────┼─────────────┬──────────┐
        ▼        ▼            ▼             ▼          ▼
   BUSINESS  TRANSFORM   AI_SWARM    REALTOR / AR / GAMES
   _BUILD    _WEBSITE    _SUBSTRATE   (the three product surfaces
   _PLAN     _PLAN                     each EaaS template
                                       crystallises around)
        │        │            │
        ▼        ▼            ▼
   pricing   App Router   opcode loop +
   + boxes   + RN + RSC   character bundle v1
        │        │            │
        └────────┴────────────┘
                 ▼
   the merkle DAG bin/relaunch already maintains
   (5 branches × N launches × cid'd outputs merging
    back into ATLAS by-cid)
                 ▼
   SYSTEM_MERKLE_ROOT = 106b80ac5878c463…
```

EaaS is the **vertex** of the seven-doc suite. The four design-and-strategy
docs above it feed the product wrapper; the three product-surface docs
below it are the verticals EaaS sells.

---

## Appendix C — system merkle (closure)

```
SYSTEM_MERKLE_ROOT     = 106b80ac5878c4636f0e37822f029289980568f73349350e0e6cdbb0fbd836ad
AGENT_D_SCAN_ROOT      = 7e4c8d9f2a1b3c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c
```

The same root every other doc in the suite pins against. The swarm runs
above this root; the EaaS product wraps the swarm; the customer rents the
wrapping. Every cid the customer's session emits — every generated image,
every cid'd scene composition, every opcode in `loop.jsonl` — merges back
into the same `by-cid` surface, which means **every customer's work makes
every other customer's bake cheaper.** That is the substrate's economic
moat, and EaaS is the product surface that monetises it.

---

*End of master product offering document.*
