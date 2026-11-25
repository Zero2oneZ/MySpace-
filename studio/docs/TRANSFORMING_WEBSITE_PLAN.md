# TRANSFORMING WEBSITE — MASTER PLAN
## Next.js 14 + React Native universal codebase that re-shapes itself into 5 vertical apps · merkle-DAG · choke points · SSR transformation states

> **Status:** v1 plan · 2026-06-02
> **Owner:** Tom Lee (Zero2oneZ)
> **Sibling docs:**
> – [`BUSINESS_BUILD_PLAN.md`](BUSINESS_BUILD_PLAN.md) — 7-box business strategy
> – [`REALTOR_VIRTUAL_TOUR_PIPELINE.md`](REALTOR_VIRTUAL_TOUR_PIPELINE.md)
> – [`LIVE_ACTION_AR_CHARACTER.md`](LIVE_ACTION_AR_CHARACTER.md)
> – [`GAMES_PLATFORM.md`](GAMES_PLATFORM.md)
> **System merkle root (shared across all sibling docs):**
> `106b80ac5878c4636f0e37822f029289980568f73349350e0e6cdbb0fbd836ad`
> **Scan merkle root for the React/Next/RN footprint (Agent R):**
> `3028ea5de63c09fc78585f224ae415d8a3809cd5ea2d599ff165885531b11119`

---

## 0. Executive thesis

**One Next.js 14 App Router shell + one React Native companion + five long-running git branches = the transforming website.** Each branch is a leaf in the merkle tree the `bin/relaunch` CLI already maintains (`realestate-tour 88293abce…`, `nft-mint 881728c78…`, `snap-filter f3aa17ff…`, `clothing-store bd5276e8…`, `game-launch 63cb0d06…`); each launch under a branch is a deeper hash that merges back into the substrate at `ATLAS by-cid` through every generated asset. The Next.js shell that becomes this transforming app already exists at `~/Projects/lyv-realty-ai/frontend/dashboard/` — we extend it, we do not fork. The React Native companion already exists at `~/Projects/lyv-realty-ai/frontend/scanner/` (pure RN 0.76.5 + Vision Camera + MLKit OCR; **not Expo**). The Rust + Axum backend at `~/Projects/lyv-realty-ai/backend/` already has half-built routes for `ar`, `glasses`, `instant_game`, `tours`, `walkthrough`, `slugs`, and `verticals` — every vertical has a lane in the backend, waiting for the shell to mount it. The transformation surface is `[branch]/launch/[slug]` — a single dynamic Next.js segment that picks colours, copy, components, and SSR state per request.

---

## 1. Substrate stack (what's already shipped)

The Explore-agent scan (`scan_merkle_root = 3028ea5de63c09fc78585f224ae415d8a3809cd5ea2d599ff165885531b11119`) confirmed the following are already live and reusable. The transforming-website plan stands on them:

**Next.js dashboard** at `~/Projects/lyv-realty-ai/frontend/dashboard/`:
- Next.js **14.2.29 + App Router**, React 18.3, TypeScript strict, `@/*` paths
- **State:** Zustand 5.0.2 with persistence (`lyv_token` in localStorage)
- **Data:** TanStack React Query 5.62 + Axios (30 s stale time, custom retry)
- **Auth:** NextAuth 4.24 + Jose JWT; password via bcrypt server-side
- **UI:** Tailwind 3.4 + Radix UI (10+ primitives) + Lucide icons; the **Lyv brand theme** is already in `tailwind.config.ts` with `lyv-purple #C896FF`, `lyv-pink #FF6B9D`, `lyv-teal #00D4AA`, `lyv-blue #4488FF`, custom shadows `glow / glow-teal / glow-pink`, custom animations `fade-in / pulse_soft`, dark-mode default
- **Charts:** Recharts 2.14 · **DnD:** react-beautiful-dnd 13 + @hello-pangea/dnd 17 · **Toast:** react-hot-toast 2.4
- **Routes already shipped:** `/dashboard/*` (CRM), `/login`, `/p/[slug]` (property profiles), `/re/[agency]/[agent]` (agent pages), `/` (landing)

**React Native scanner** at `~/Projects/lyv-realty-ai/frontend/scanner/`:
- **Pure React Native 0.76.5 + TypeScript** — *not* Expo; *not* expo-router
- **Camera:** react-native-vision-camera 4.6 · **OCR:** react-native-mlkit-ocr 1.2 (on-device, no server round-trip)
- **Navigation:** React Navigation 6.1 + Native Stack 6.4
- **Same Zustand + React Query as the dashboard** (this is the share point)
- **Native services:** geolocation, permissions, vector-icons

**Rust + Axum backend** at `~/Projects/lyv-realty-ai/backend/`:
- Axum 0.7 + Tokio + SQLx (Postgres) + Redis + JWT + bcrypt + Reqwest + multipart + WebSocket
- Modular: `src/{main,auth,db,error}.rs` + `src/{db,models,routes,services}/*.rs`
- Half-built route lanes per vertical already present (per Plan-agent analysis of `routes/mod.rs`)

**Other Next.js apps in the workspace** (potential design-language donors):
- `GentlyOS-Rusted-Metal/apps/trollz.fun` — **Next 15.5.3 + shadcn/ui + Radix** (most recent, gaming-aesthetic) → mine for component patterns
- `GentlyOS-Rusted-Metal/apps/gentlyos-io`, `zero2onez-io`, `trade-bot` — Next 14.2, simpler shells
- `MySpace++/studio/frontend/` — Vite + React 18 creative studio (matcap colour studies)
- `BusterBrowser/warp-drive/` — turbo + pnpm monorepo + shared component library (template for `packages/ui`)

**ATLAS substrate** (the cid'd merge surface):
- `bin/relaunch` defines the 5 branches and emits launches with stable merkles + per-launch dirs (`branch_merkle`, `launch_merkle`)
- `bin/factory` → FLUX-schnell + matte + cid through `bin/assets` → `cas/<cid>` + `by-pass/<pass>/` + `by-layer/<n>_<name>/`
- `bin/vidplay` serves `/launch/<slug>/` routes today (proves the static side ships); Next.js will replace this with server-rendered counterparts that have proper data access

**Gaps surfaced by Agent R**: no Stripe, no Clerk/social-auth, no Expo, no sitemap/OG-image route handlers, no analytics/Sentry, no email/notifications backend, no CI/CD manifests, no headless CMS. The plan introduces each at the choke point where it first matters (§4 below).

---

## 2. Next.js 14 App Router layout — one shell, five branches

This is the polymorphic route tree. The existing realtor dashboard stays exactly where it is at `/dashboard/*`; we widen the shell by adding a single dynamic segment `[branch]` plus per-vertical sibling route groups for the routes that diverge sharply (wallet, Stripe, walkthrough recorder). Everything under `(substrate)` is git-mergeable across branches; everything under a vertical's named directory or under `[branch]/launch/[slug]` is branch-private.

```
~/Projects/lyv-realty-ai/frontend/dashboard/src/app/
├── layout.tsx                        [SHARED]  root layout — reads branch from URL, injects theme
├── providers.tsx                     [SHARED]  React Query, NextAuth, Zustand bootstrap
├── globals.css                       [SHARED]  CSS vars (--brand, --brand-bg) consumed by theme.css
├── page.tsx                          [SHARED]  branch picker — mirrors `relaunch list`
│
├── login/                            [SHARED]  NextAuth (already shipped)
├── dashboard/                        [SHARED]  existing realtor dashboard — DO NOT TOUCH
│
├── api/
│   ├── auth/[...nextauth]/           [SHARED]  Node runtime — NextAuth needs Node crypto
│   ├── factory/                      [SHARED]  Node — proxies to bin/factory or axum
│   ├── assets/[cid]/                 [SHARED]  Edge — read-through to ATLAS by-cid; immutable cache
│   ├── relaunch/                     [SHARED]  Edge — reads launches/<slug>/LAUNCH.json
│   └── events/cid                    [SHARED]  SSE — fan-out cid:new from Redis pub/sub
│
├── (substrate)/                      [SHARED]  shell chrome — header, branch nav, footer
│   ├── components/                              ← every branch composes from here
│   └── _lib/                                    branch-resolver, merkle-loader, theme-injector
│
├── [branch]/                         [POLYMORPHIC]  /realestate-tour | /nft-mint | /snap-filter | /clothing-store | /game-launch
│   ├── layout.tsx                              loads BRANCH_DEFS[params.branch], injects theme.css
│   ├── page.tsx                                branch landing — mirrors launches/<slug>/index.html
│   ├── launch/[slug]/                          [BRANCH-PRIVATE]  per-launch routes
│   │   ├── page.tsx                            slug landing
│   │   ├── play/                               branch-specific runtime (RSC streams)
│   │   └── api/                                branch-specific server actions
│   └── @branch/                                parallel slot — branch-only UI mounts here
│
├── realestate-tour/                  [BRANCH-PRIVATE overrides]
│   ├── listing/[mls]/                          SSR (Node) — MLS data per-request
│   ├── walkthrough/[id]/                       Streaming SSR — VGGT video viewer with Suspense
│   └── billing/                                SSR (Node) — Stripe SDK
│
├── nft-mint/                         [BRANCH-PRIVATE]
│   ├── mint/[collection]/                      RSC shell + CSR island (wallet adapter needs window)
│   ├── reveal/[token]/                         ISR + on-demand revalidate (webhook fires it)
│   └── claim/                                  SSR (Node) — wallet signature verification
│
├── snap-filter/                      [BRANCH-PRIVATE]
│   ├── try/[filter]/                           Edge static shell + CSR (WebAR/Vision Camera client-only)
│   └── export/                                 SSR (Node) — zips Lens/Spark bundle
│
├── clothing-store/                   [BRANCH-PRIVATE]
│   ├── catalogue/                              ISR (5 min) — slow-changing grid
│   ├── garment/[sku]/                          ISR + on-demand revalidate on SKU change
│   └── tryon/                                  SSR (Node) + streaming Suspense — Kolors is GPU-heavy
│
└── game-launch/                      [BRANCH-PRIVATE]
    ├── play/[slug]/                            SSG — HTML+wasm fully static, edge-cacheable
    └── arcade/                                 ISR (60 s) — new scenes appear when authored
```

The polymorphic `[branch]` segment is content-addressed: each value is a branch merkle leaf (`88293abce…`, `881728c78…`, etc.). The `@branch` parallel slot lets one URL render the substrate chrome plus the branch's private leaves in the same response — that is the literal Next.js encoding of "merkle root + branch tip in one response." Routes under `realestate-tour/`, `nft-mint/`, `snap-filter/`, `clothing-store/`, `game-launch/` are the routes whose break-points (auth provider, payment rails, on-chain bindings) are heavy enough that they need their own top-level directory — those routes are branch-private and never merge back into the substrate tree directly; their outputs merge through `ATLAS by-cid` instead.

---

## 3. The merkle-DAG of build steps

Every node is a step. Every edge is a dependency. `(M)` = git-mergeable (no commitment to a vendor / runtime / contract). `(CHOKE)` = piece-of-no-return; backing out is expensive.

```
                       [SUBSTRATE ROOT  106b80ac5878c463]                     ← GIT-MERGEABLE
                                       │
        ┌──────────────────────────────┼──────────────────────────────┐
        ▼                              ▼                              ▼
   S1. ATLAS by-cid mount        S2. axum bridge route          S3. NextAuth wiring
   (read-through proxy at         (/api/factory → bin/factory   (re-use existing
    /api/assets/[cid])            or → axum /api/factory)        dashboard creds)
   (M)                            (M)                            (M)
        │                              │                              │
        └──────────────┬───────────────┴──────────────┬───────────────┘
                       ▼                              ▼
              S4. [branch] resolver               S5. theme.css injection
              (loads BRANCH.json by name           (per-merkle CSS vars
               from /data/Projects/ATLAS/           generated by bin/relaunch)
               branches/<name>/BRANCH.json)
              (M)                                 (M)
                       │
        ┌──────────┬───┴────┬────────────┬─────────────┐
        ▼          ▼        ▼            ▼             ▼
   REALESTATE   NFT-MINT  SNAP-FILTER  CLOTHING     GAME-LAUNCH
   88293abc…    881728c7… f3aa17ff…    bd5276e8…    63cb0d06…
   ─────────    ─────────  ──────────  ─────────    ───────────
   R1 MLS       N1 chain   F1 face     C1 catalog   G1 godot
      schema       choice     mesh        schema       export
      (M)        (CHOKE)     (M)         (M)         (CHOKE: scene)
       │           │          │            │             │
   R2 listing   N2 wallet  F2 alpha    C2 Kolors    G2 fb instant
      detail       provider   compose     wrapper      games SDK
      (M)        (CHOKE)     (M)        (CHOKE)      (CHOKE: FB)
       │           │          │            │             │
   R3 walk-     N3 candy   F3 anchor   C3 stripe/   G3 scene→
      through      machine    metadata    shopify      godot bake
      recorder    (CHOKE)     export       choice      (M)
      (M)         │           (M)         (CHOKE)       │
       │           ▼            │            │           ▼
   R4 stripe   N4 access-     F4 lens/    C4 avatar   G4 cid drop
      billing     grant glue     spark        upload     into godot
      (CHOKE:     to ATLAS       handoff      flow       project
       payments)  (M)            (M)         (M)        (M)
        └──────────┴─────────────┴────────────┴───────────┘
                                 │
                  S6. cid-merge back to ATLAS by-cid
                  GIT-MERGEABLE (this is the "merge")
                                 │
                  S7. cross-branch reuse (e.g. NFT trait
                  art reused as game-launch asset; same
                  cid → no re-bake, royalty triggers)
                  GIT-MERGEABLE
```

The shape is deliberate: every choke is a single branch-private node, never on the substrate spine. The merge from every branch back into substrate happens only at S6, mediated by cid, so a botched mint contract or a Kolors fork cannot corrupt the realtor dashboard. The DAG is also the **literal git topology**: `main` = substrate root + S1–S5; long-running branches = `branch/<vertical>`; each choke node lives on a sub-feature branch under its vertical.

---

## 4. Choke-point taxonomy — every piece-of-no-return + its safer alternative

**N1 — chain choice (Solana Metaplex vs Sui Move).** Commits to either Anchor Rust on-chain code + Candy Machine v3 manifest + Phantom/Backpack/Solflare adapters, **or** Sui Move modules + Display Objects + Suiet/Sui Wallet/Ethos adapters. Cascade: every `nft-mint/*` route, the access-grant glue (N4), trait-roll metadata, marketplace surfaces (Magic Eden vs BlueMove). Back-out cost: ~3 dev-weeks of rewrite + redeploy gas + reputational hit. **Safer**: build the mint UI against a `MintAdapter` interface; ship Solana first; gate Sui behind a feature flag.

**N2 — wallet provider.** Commits to a specific `WalletAdapter` library (e.g. `@solana/wallet-adapter-react`). Cascade: session lifecycle, signature-as-login, JWT bridge to existing NextAuth. Back-out cost: ~1 week. **Safer**: route every auth path through an internal `useIdentity()` hook that today returns NextAuth and tomorrow returns wallet — consumer code never changes.

**N3 — Candy Machine v3 schema commitment.** Once minted, the on-chain JSON schema (creators, collection, royalties, sequencing) is immutable. Cascade: reveal format, marketplace compatibility, secondary royalty flow. Back-out cost: **very high** — burning + re-minting destroys floor price. **Safer**: mint a 10-unit test collection on devnet first; only commit to mainnet after N4 access-grant glue works end-to-end and the bin/relaunch generated trait set passes a community sanity check.

**N4-style payments (R4 + C3) — Stripe vs crypto vs Shopify.** Commits to a webhook architecture and a refund policy. Cascade: Rust `stripe.rs` route, billing UI, tax handling, fraud flow. Back-out cost: ~1 week of webhook rewiring + customer-support pain on refunds-in-flight. **Safer**: ship `PaymentAdapter` (Stripe today; crypto / Shopify later). The Rust backend's `routes/` already has the lanes stubbed — leave them stubbed until forced. Agent R confirmed **no Stripe SDK present yet**, so this is a clean greenfield decision.

**R1 — MLS schema commitment.** Once listings flow in, the Postgres schema is hard to migrate. Cascade: dashboard queries, search index, walkthrough joining. Back-out cost: 1–2 weeks of `sqlx migrate add` cycles. **Safer**: store MLS payloads as `jsonb` in a thin shell table; promote columns to typed when query patterns settle.

**C2 — Kolors-Virtual-Try-On wrapper.** Commits to that specific model's input format (model image + garment flat) and its 5.4 GB GPU footprint. Cascade: a `bin/factory` recipe, GPU scheduling via `bin/gpud`, the avatar-upload UX. Back-out cost: medium — swapping to IDM-VTON or OOTDiffusion means re-prompting all garment-modeled images and altering the catalogue ingestion. **Safer**: hide it behind a `TryOnEngine` trait in the Rust service; Kolors is engine v1.

**G1 — Godot HTML5 export commitment.** Commits to Godot 4 WASM runtime (~25 MB per game). Cascade: every game-launch slug ships a Godot bundle. Back-out cost: low for new games, high for already-shipped ones (public URLs). **Safer**: Godot is correct here — 14 scenes already authored, native exports also possible.

**G2 — Facebook Instant Games SDK.** Commits to FB's review process and ad-network terms. Cascade: SDK init, leaderboard schema, ad placement. Back-out cost: medium — leave the SDK calls behind a `if (window.FBInstant)` guard. **Safer**: build every game-launch slug to run identically on a plain slug URL; FB Instant is an additional packaging step (the playbook is at `studio/docs/FACEBOOK_INSTANT_GAMES_PLAYBOOK.md`).

**Runtime: Edge vs Node.** Edge can't run wallet libs (need Node crypto), the Stripe SDK (HTTPS-agent assumptions), or any subprocess shell-out. Node can but is slower. Back-out cost: low — choose per-route via `export const runtime = 'edge'`. **Safer**: default Node, opt into Edge only for `/api/assets/[cid]`, `/api/relaunch`, `/api/events/cid`, and pure-static branch landings.

**State model.** Already locked: Zustand 5 in the dashboard. Stay on it; don't introduce Redux. RSC-only state is fine for server-tree data; Zustand handles the client islands.

---

## 5. SSR transformation states — every route gets exactly one

Every route in the layout (§2) is assigned exactly one of `SSG / ISR / SSR (Node) / Streaming SSR / RSC / Edge SSR / PPR / CSR-island`, with a one-line reason. The map below is the authoritative reference for choosing `runtime`, `dynamic`, `revalidate`, and Suspense boundaries.

- `/` (root branch picker) → **PPR**. Static shell of "pick a vertical" + dynamic hole for the 5 latest launches per branch. Shell ships from edge; dynamic hole streams from origin.
- `/login` → **SSR (Node)**. NextAuth needs Node crypto.
- `/dashboard/*` → **RSC + Streaming SSR** (already shipped this way; leave alone).
- `/[branch]` → **ISR, 60 s**. Branch definition only changes when `BRANCH_DEFS` does; serve cached HTML; regenerate on `relaunch list` change.
- `/[branch]/launch/[slug]` → **PPR**. Static shell (theme.css + logo from CAS) + dynamic hole for live status. Edge-renderable.
- `/realestate-tour/listing/[mls]` → **SSR (Node)**. MLS data per-request, gated by realtor identity.
- `/realestate-tour/walkthrough/[id]` → **Streaming SSR**. Video metadata server-side; player streams in via Suspense.
- `/realestate-tour/billing` → **SSR (Node)**. Stripe SDK requires Node.
- `/nft-mint/mint/[collection]` → **RSC shell + CSR island**. Wallet adapters need `window`; RSC ships chrome + collection metadata; the connect-and-mint button is `'use client'`.
- `/nft-mint/reveal/[token]` → **ISR + on-demand revalidate**. Reveal triggered by on-chain event → webhook calls `revalidatePath`. Edge-deliverable once revealed.
- `/nft-mint/claim` → **SSR (Node)**. Validates wallet signature server-side via Node crypto.
- `/snap-filter/try/[filter]` → **Edge static shell + CSR**. WebAR + Vision Camera run on-device; no server in the per-frame loop. Edge ships the shell; everything else is `'use client'`.
- `/snap-filter/export` → **SSR (Node)**. Zips the Lens/Spark bundle server-side.
- `/clothing-store/catalogue` → **ISR, 5 min**. Catalogue mutates slowly; edge.
- `/clothing-store/garment/[sku]` → **ISR + on-demand revalidate**. Edge.
- `/clothing-store/tryon` → **SSR (Node) + streaming Suspense**. Kolors-Virtual-Try-On is GPU-heavy → must hit origin; stream a placeholder + progress via Server-Sent Events through axum.
- `/game-launch/play/[slug]` → **SSG**. Slug HTML + wasm bundle is fully static once exported. Edge-cacheable.
- `/game-launch/arcade` → **ISR, 60 s**. New scenes appear when authored.
- `/api/factory` → **SSR (Node)**. Subprocess shell-out to `bin/factory` — cannot be edge.
- `/api/assets/[cid]` → **Edge SSR**. CAS is content-addressed; cache forever; serve from the closest POP.
- `/api/auth/[...nextauth]` → **SSR (Node)**.
- `/api/relaunch` → **Edge SSR**. Just reads `launches/<slug>/LAUNCH.json` — pure JSON, cacheable by slug.
- `/api/events/cid` → **SSR (Node)**. Server-Sent Events over a persistent connection; subscribes to Redis pub/sub `cid:new`.

### The transformation state machine

A single route definition for `/[branch]/launch/[slug]` serves up to **four different states** based on request traits, all decided in one route handler that inspects `headers()` + the launch's `target_surfaces`:

1. If the `slug` exists in CAS and every sub-asset is fully baked → **Edge SSG** from the by-cid mount.
2. If the `slug` exists but a sub-asset is stale → cached HTML with a **PPR** dynamic hole that streams fresh data.
3. If the visitor is signed in as the launch's owner → upgrade to **SSR (Node)** so authoring tools render server-side with realtime data.
4. If the UA is mobile and the launch is a `snap-filter` → bypass the shell and redirect to `/snap-filter/try/[filter]` running **CSR** for camera access.

That is the literal "transforming SSR" the user asked for: one route, multiple rendering states picked deterministically at request time.

---

## 6. React Native companion — extend `scanner/`, not invent Expo

**Critical correction to the Plan-agent draft:** Agent R confirmed the workspace's RN footprint is **pure React Native 0.76.5 + Vision Camera + MLKit OCR + React Navigation**, *not* Expo. The plan respects this:

```
~/Projects/lyv-realty-ai/frontend/scanner/                ← EXISTING RN 0.76.5
├── (existing scanner screens stay)
├── src/screens/
│   ├── SnapFilter/         NEW · /snap-filter/try/[filter] mirror via Vision Camera + WebAR ML
│   ├── GameLaunch/         NEW · react-native-webview hosting the Godot HTML5 export
│   ├── NftMint/            LATER · WalletConnect v2 (NOT a wallet adapter — RN-specific)
│   ├── ClothingTryon/      LATER · camera + axum Kolors endpoint
│   └── RealtorWalkthrough/ LATER · native video player
└── src/navigation/         Existing React Navigation Stack — add the new screens to the nav config
```

### What goes into `packages/` (the monorepo we introduce)

A new pnpm-workspaces monorepo at `/data/Projects/ATLAS/` (since ATLAS owns the merkle infra). The two apps symlink in:

```
/data/Projects/ATLAS/
├── apps/
│   ├── web/        → symlink to /home/tom/Projects/lyv-realty-ai/frontend/dashboard
│   └── mobile/     → symlink to /home/tom/Projects/lyv-realty-ai/frontend/scanner
├── packages/
│   ├── core/                          [SHARED] TypeScript types · BRANCH_DEFS · merkle utils · LaunchState
│   ├── api-client/                    [SHARED] Typed axum bridge — wraps Rust routes
│   ├── theme/                         [SHARED] tokens that map branch merkle → color/type (mirrors theme.css)
│   ├── ui-web/                        web-only — Radix wrappers, Tailwind classes
│   ├── ui-native/                     RN-only — primitives matching ui-web's API
│   └── adapters/
│       ├── payments-stripe/           web-only (Stripe.js)
│       ├── payments-stripe-rn/        RN-only (Stripe React Native SDK)
│       ├── wallet-web/                Phantom adapter
│       └── wallet-rn/                 WalletConnect v2
├── branches/                          [EXISTING from bin/relaunch]
├── launches/                          [EXISTING]
└── bin/                               [EXISTING] factory, relaunch, vidplay, assets
```

`packages/core` is the TypeScript mirror of `bin/relaunch`: the `BRANCH_DEFS` const transcribed line-by-line as a typed object, the `merkle()` and `slug()` helpers (SHA-256 over `JSON.stringify(o, Object.keys(o).sort())` so JS and Python compute identical hashes), the `Launch`, `BranchDef`, `LaunchState` interfaces, the `assetCid(name) → URL` resolver. Verifying parity: `pnpm --filter @atlas/core test` should print the same 16-char hashes as `bin/relaunch list`.

### Which verticals ship to RN first

Two verticals are RN-native day one because they have **no payment / no wallet / no auth round-trip**:

1. **Snap-filter** — Vision Camera + ML face mesh + alpha overlay. Maps 1:1 to `/snap-filter/try/[filter]`. No backend in the per-frame loop. Ships as a TikTok-style standalone the day Vision Camera's frame-processor plugin for MLKit Face Mesh compiles.
2. **Game-launch** — `react-native-webview` over the existing Godot HTML5 export = one screen and you ship 14 games on iOS/Android with no rewrite.

Defer the other three (`realtor-walkthrough` drags in heavy video, `nft-mint` drags in WalletConnect, `clothing-store/tryon` drags in camera-upload + Kolors round-trip) until they're earning on the web first.

---

## 7. The frictionless merge loop — git workflow that mirrors the merkle DAG

`main` is the substrate. It holds `(substrate)/`, `/api/*`, `/[branch]/` shell pieces, and `packages/*`. Five long-running branches: `branch/realestate-tour`, `branch/nft-mint`, `branch/snap-filter`, `branch/clothing-store`, `branch/game-launch`. Each rebases onto `main` weekly. Sub-feature branches per choke decision: `branch/nft-mint/choke/chain-solana`, `branch/nft-mint/choke/wallet-phantom`, `branch/clothing-store/choke/payments-stripe`. Each sub-feature has a **gate file** at `gates/<choke>.gate` that lives empty until validation passes (devnet mint succeeded; Stripe test webhook fired; Kolors output matches a golden image). A pre-merge hook on the vertical branch refuses the choke-branch merge unless its gate is filled. This is the literal mechanism for "no return only when deliberate."

`bin/relaunch tree` is the mirror of git topology. Extend it to also print the current commit SHA of each `branch/<vertical>` ref and to list the choke sub-branches with their gate status (`pending` vs `validated`). When a sub-feature lands in its vertical branch, the choke marker flips to `validated`. The tree visually becomes a literal git tree.

Cross-branch reuse triggers when a launch's CID lands in `ATLAS by-cid`. The Rust backend's `assets` route watches `inotify` on `ATLAS/by-cid/` (production: watch a Postgres `LISTEN/NOTIFY` channel). New CID → enqueue a Redis pub/sub `cid:new` event → every branch's React Query subscription picks it up via the `/api/events/cid` SSE route. Concretely: an NFT collection's character art lands in `by-cid` → the `game-launch` branch's `arcade` page shows a new entry in its "available assets" panel and a creator can drop it into a Godot scene. **No git merge needed**; the substrate's CAS is the merge surface.

---

## 8. The first five implementable steps

Each step is concrete, gated, and unblocks the next. Doing all five in order takes the plan from doc to a working end-to-end demo where a snap-filter sticker generated by FLUX-schnell appears in a Next.js shell themed by branch merkle and served via the same edge route the substrate uses.

1. **Wire `packages/core` as the typed mirror of `bin/relaunch`.** From `/data/Projects/ATLAS`, create the pnpm workspace (`pnpm init`, then `pnpm-workspace.yaml` listing `apps/*` and `packages/*`). In `packages/core/src/branches.ts`, transcribe `BRANCH_DEFS` from `bin/relaunch` line-by-line as a typed const. Add `merkle.ts` (SHA-256 with sorted-key JSON canonicalisation) so JS and Python compute identical hashes. Verify with `pnpm --filter @atlas/core test`: each branch hash matches what `bin/relaunch list` prints.

2. **Mount the `[branch]` dynamic segment in the existing dashboard.** Without forking, add `frontend/dashboard/src/app/[branch]/layout.tsx`, `/page.tsx`, and `/launch/[slug]/page.tsx`. The layout reads `BRANCH_DEFS[params.branch]` from `@atlas/core`, injects `theme.css` from the launch dir, and renders substrate chrome. Verify: `cd ~/Projects/lyv-realty-ai/frontend/dashboard && pnpm dev`, open `http://localhost:3001/snap-filter` — branch landing renders with the right theme.

3. **Bridge `/api/factory` and `/api/assets/[cid]` to the axum backend.** Two route handlers under `src/app/api/`. The factory handler proxies POST to the existing axum endpoint (or shell-execs `bin/factory` if simpler for v0; subprocess time is dominated by FLUX, so the overhead is irrelevant). The assets handler streams from `/data/Projects/ATLAS/assets/cas/<cid>.<ext>` with `Cache-Control: public, max-age=31536000, immutable` and `export const runtime = 'edge'`. Verify: `curl http://localhost:3001/api/assets/<known-cid>` returns the asset bytes.

4. **Drive a real launch through the loop end-to-end with snap-filter** (cheapest choke-free vertical). Run `python3 /data/Projects/ATLAS/bin/relaunch snap-filter --brand "Glittercat" --color "#ff66cc" --filter-idea "glittery cat ears" --tagline "test launch"`. Confirm the launch dir exists with `LAUNCH.json`, `theme.css`, `logo.svg`, `index.html`. Hit `http://localhost:3001/snap-filter/launch/snap-filter-glittercat-<merkle>` — the Next.js shell renders the launch using the same theme as `bin/vidplay` would.

5. **Wire the merge loop's first CID round-trip.** Implement `src/app/[branch]/launch/[slug]/play/page.tsx` so it POSTs the filter prompt to `/api/factory`, receives a CID, and renders `/api/assets/<cid>` in an `<img>`. Verify: end-to-end, the sticker generates, the CID lands in `ATLAS by-cid`, the Next.js page displays it from the edge route, and `bin/relaunch tree` shows the launch under the `snap-filter` branch leaf. **At this point the merkle loop is closed** — substrate root → branch leaf → launch slug → CID → back into substrate by-cid → visible to all other branches. Every subsequent vertical extends the same loop.

After step 5: the React Native scanner gets its first new screen at `apps/mobile/src/screens/SnapFilter/`, sharing `packages/core` types with the web; that's a copy-paste of the same `[filter]` UX via Vision Camera. After that: pick the next choke point that earns revenue (probably Box 4 Solana NFT per the `BUSINESS_BUILD_PLAN.md` — leverages the existing `~/Projects/NFT` PUMP ORACLE pipeline).

---

## 9. The frontend-design pass (when this plan ships)

The frontend-design skill (`frontend-design:frontend-design`) is reserved for **step 2.5** of §8 — after the `[branch]` segment renders but before the launch page goes paid. It generates the substrate's chrome components (header, branch nav, footer), the per-branch landing-page templates (5 variants), and the launch-page composition primitives (recipe cards, theme tokens consumer, CAS image renderer). The brief to that skill is fixed: build on the **existing Lyv brand theme** (`lyv-purple #C896FF`, `lyv-pink #FF6B9D`, `lyv-teal #00D4AA`, `lyv-blue #4488FF`, custom shadows, dark-mode default) extending it with per-branch overrides where the branch's `theme.css` sets `--brand` to the launch colour; produce Radix-based components compatible with the dashboard's existing dependency tree; avoid generic AI aesthetics; lean into the neon / glow language already in the Tailwind config.

---

## 10. Risks + mitigations (the new ones, on top of the BUSINESS_BUILD_PLAN risk register)

The full risk register lives in `BUSINESS_BUILD_PLAN.md §8`. The risks **specific to this transforming-website plan**:

- **Edge runtime conflicts** with subprocess shell-out. Mitigation: only `/api/assets/[cid]`, `/api/relaunch`, and pure CAS reads run on Edge. Everything that touches `bin/factory` or wallet libs is Node.
- **Polymorphic `[branch]` route mis-matches existing dashboard paths.** Mitigation: `[branch]` is matched after the literal `dashboard/`, `login/`, and `api/` segments — Next.js precedence handles this automatically, but verify with a regression test on existing dashboard routes after step 2.
- **Zustand state collisions** between substrate and branch UIs. Mitigation: each branch gets a namespaced slice (`useBranchStore<NftMintState>('nft-mint')`); the substrate's existing `lyv_token` slot is untouched.
- **React Native scanner's existing screens break** when we add `packages/core`. Mitigation: don't touch the scanner's existing nav; new screens are additive under a separate stack.
- **The dashboard's tailwind.config.ts** owns the colour palette today; adding per-branch palettes via CSS variables (not Tailwind config) keeps Tailwind purge safe.
- **CI/CD does not yet exist.** Mitigation: the very first PR after step 1 introduces a GitHub Actions workflow that runs `pnpm --filter @atlas/core test` + `pnpm --filter @atlas/web build` so subsequent merges are gated.

---

## 11. The one-page version

**Q: What are we building?** A polymorphic Next.js 14 App Router shell + an existing React Native scanner companion, both extending what's already at `~/Projects/lyv-realty-ai/`. One codebase serves 5 verticals via the `[branch]/launch/[slug]` dynamic segment.

**Q: Why does it work?** Because the substrate (root merkle `106b80ac…`) plus the 5 branch merkles (`88293abce…`, `881728c78…`, `f3aa17ff…`, `bd5276e8…`, `63cb0d06…`) are already defined in `bin/relaunch`. The Next.js App Router's dynamic segments are the literal encoding of the merkle tree. RSC + PPR + Edge cache let each transformation state ship from the right runtime.

**Q: What's the first running demo?** §8 step 5 — a snap-filter launch where FLUX-schnell generates a sticker, the CID lands in ATLAS by-cid, and the Next.js shell renders it from the edge route. 5 engineer-days to step 5 from current state.

**Q: When do we touch the design?** §9 — after step 2 (the `[branch]` mount), before step 5 (the closed CID loop). Brief the `frontend-design` skill on the Lyv brand theme already in `tailwind.config.ts`.

**Q: When do we choke on a vendor?** Never on `main`. Choke decisions live on sub-feature branches under their vertical, gated by `gates/<choke>.gate` files. Merge only after devnet/test validation.

**Q: When do we ship to React Native?** Snap-filter screen lands the same week as web step 5. Game-launch screen the week after (just `react-native-webview` over the Godot HTML5 export).

**Q: When do we earn?** Per BUSINESS_BUILD_PLAN.md — first paid customer in week 4 (the realtor pilot), full slate in week 10.

---

## Appendix A — critical files referenced

```
/data/Projects/ATLAS/
  bin/relaunch                         the merkle-tree CLI + BRANCH_DEFS
  bin/factory                          FLUX-schnell + matte + cid loop
  bin/vidplay                          current friends-only playground (proves /launch/<slug>)
  bin/assets                           CAS + by-pass + by-layer
  branches/<vertical>/BRANCH.json      stable branch merkle leaves
  launches/<slug>/                     per-launch dir (LAUNCH.json + theme.css + logo + index.html)
  templates/                           seeded factory templates (8 today)

~/Projects/lyv-realty-ai/
  frontend/dashboard/                  EXISTING Next.js 14 App Router shell — extend, don't fork
    src/app/layout.tsx                 root layout (already shipped)
    src/app/providers.tsx              React Query + Zustand bootstrap
    src/app/page.tsx                   landing
    src/app/dashboard/                 realtor CRM (DO NOT TOUCH)
    src/app/login/                     NextAuth (already shipped)
    src/app/api/                       existing api routes
    tailwind.config.ts                 Lyv brand theme (extend, don't replace)
  frontend/scanner/                    EXISTING React Native 0.76.5 — extend, don't fork
    src/screens/                       add SnapFilter + GameLaunch here
    src/navigation/                    React Navigation stack
  backend/                             EXISTING Axum Rust API
    src/routes/                        per-vertical lanes already stubbed

/data/Projects/MySpace++/studio/docs/
  BUSINESS_BUILD_PLAN.md               7-box business strategy
  REALTOR_VIRTUAL_TOUR_PIPELINE.md     vertical 1 detailed
  LIVE_ACTION_AR_CHARACTER.md          vertical 2 detailed
  GAMES_PLATFORM.md                    vertical 3 detailed
  FACEBOOK_INSTANT_GAMES_PLAYBOOK.md   game-launch G2 choke prep
  TRANSFORMING_WEBSITE_PLAN.md         <-- this doc
```

---

## Appendix B — system + scan merkles

`SYSTEM_MERKLE_ROOT  = 106b80ac5878c4636f0e37822f029289980568f73349350e0e6cdbb0fbd836ad`  (shared across all docs)
`SCAN_R_MERKLE_ROOT = 3028ea5de63c09fc78585f224ae415d8a3809cd5ea2d599ff165885531b11119`  (the React/Next/RN footprint scan that grounds this plan)

When either changes (substrate evolves, new Next.js app or RN library lands), recompute, diff sub-trees, and only re-bake what's affected. The transforming-website plan evolves through these roots; the boxes evolve through their thin wrappers.

---

*End of master plan.*
