# BUSINESS BUILD PLAN — SUBSTRATE → BOXES → SHIP

> **Status:** v1 plan · 2026-06-01
> **Owner:** Tom Lee (Zero2oneZ)
> **Sibling design docs:**
> – [`REALTOR_VIRTUAL_TOUR_PIPELINE.md`](REALTOR_VIRTUAL_TOUR_PIPELINE.md)
> – [`LIVE_ACTION_AR_CHARACTER.md`](LIVE_ACTION_AR_CHARACTER.md)
> – [`GAMES_PLATFORM.md`](GAMES_PLATFORM.md)
> **System merkle root (shared, "what we have today"):**
> `106b80ac5878c4636f0e37822f029289980568f73349350e0e6cdbb0fbd836ad`
>
> The three design docs prove **the same substrate ships three products**. This doc
> turns that into a **business build plan**: how we block-and-box the substrate so it
> ships as **seven distinct revenue streams** — realtor SaaS, AR character app, games
> platform, **Solana NFT site, Sui NFT site, Facebook free-to-play, Steam free-to-play**
> — and what order to build them in so each downstream box ships fastest.
>
> The style / branding phase comes **after** the pipes are proven; never before.

---

## 0. Executive thesis

> **One substrate. Seven boxes. Three revenue models. Zero re-implementation.**

Everything in the three sibling docs is the substrate. The substrate is built **once**
and **content-addressed** (every artifact gets a cid via ATLAS). Each box below is a
**packaging variant** of the substrate — same renderer, same asset cache, same AI NPCs,
same player avatars, different distribution channel and different monetization SDK.

The blocking rule that makes this work: **no box gets a private fork of the substrate.**
Every box is a thin wrapper. If a box wants something the substrate doesn't have, the
substrate gets it (and every other box benefits for free).

Capital efficiency target: **substrate cost ≤ 1× engineer-quarter; each box ≤ 2
engineer-weeks of unique work.** That ratio is how a single team ships seven product
lines.

---

## 1. The substrate — what we build once

This is everything inside the three design docs collapsed to the **shared core**. None
of the boxes ship until this is done. None of the boxes need it re-done after.

| substrate piece | source-of-truth doc | done-when |
|---|---|---|
| Godot 4.6.3 + `bin/godot` wrapper + `engine.env.path` | this repo | already ✓ |
| `SpatialBridge.so` built (`fuse_depth`, `solve_ccd`, `solve_two_bone`, IK) | all three | `nix-shell -p scons --run "bash build-cpp.sh"` |
| Passes registry (`passes/registry.py`) with named workflows | realtor §9 + games §9 | registry entries committed |
| ATLAS `bin/assets` cid'd cache + `by-pass/` view | all three | already ✓ + healed-symlink fix landed today |
| `scene_spine.json` + `spine_ops.py` + `scene_to_godot.py` (+ Three.js branch) | all three | already ✓ |
| `photo_to_avatar_rigged.v0` workflow | live-AR + games | already authored ✓ |
| Blender + `avatar_bake.py` LAYER_STACK | all three | already ✓ |
| ComfyUI MCP + `pipeline_ml.py` workflow predictor | all three | already wired ✓ |
| VGGT + cotracker3 wrapped as ComfyUI nodes | realtor + games | one creator-side day |
| Q3-TTS clone endpoint + Kokoro streaming endpoint | live-AR + games | one day each |
| Gemma-4-E4B-it edge LLM stand-up | live-AR + games | two days |
| Whisper-large-v3-turbo STT endpoint | live-AR + games | half a day |
| WebXR viewer for one cached character.glb | live-AR | one day |
| Godot HTML5 export pipeline (one make target per scene) | games | one day |
| lyv-realty-ai slug-URL shell wired to game/listing/character endpoints | all three | one day (shell already exists, just wire routes) |
| Server KV for cross-product state (avatar_cid, session, royalty) | all three | one day |
| WebRTC + Yjs CRDT multiplayer | live-AR + games | three days |
| `bin/gpud` cloud-first GPU governor | substrate | already ✓ |
| `bin/conductor` density-math agent team | substrate | already ✓ |
| `bin/forge` backward-resolve workflow | substrate | already ✓ |
| `bin/chain` loop.jsonl orchestrator | substrate | already ✓ |

**Substrate budget:** ~3–4 weeks engineer-time. Most of the line items already exist
and just need wiring; the truly-new ones (VGGT nodes, edge LLM, WebXR viewer,
multiplayer) are individually small.

---

## 2. The seven boxes — per-box brief

Each box: what it ships, where it ships, how it earns, what's unique vs the substrate.

### Box 1 — Realtor SaaS  (B2B, premium)

**What it is:** per-listing virtual-tour platform + AI realtor avatar (the sibling
realtor doc + live-AR character doc combined for this customer).
**Where:** slug URLs via lyv-realty-ai shell · optional Meta-glasses WebXR build for
luxury listings.
**Who pays:** real-estate agents per listing or subscription.
**Revenue model:** $99–$499 per listing flat + tier upgrade for live-AR avatar +
optional "premium photoreal" addon that flips T2a Cycles bake on.
**Unique work over substrate:** MLS metadata ingestion, agent dashboard, billing
plumbing.
**Build estimate over substrate:** ~1 week.

### Box 2 — Live AR Character App  (B2C, consumable / collectible)

**What it is:** Pokémon-Go-class AI character app. Users summon characters,
characters talk back, characters travel between locations.
**Where:** WebXR URL (iPhone Pro, Quest 3, Android Chrome). PWA wrapper for "install
to home screen." Native Meta Quest browser entry. Future visionOS native.
**Who pays:**
  – B2C consumers (~$1 per summon, monthly subscription, character-pack IAP)
  – B2B creators (revenue split on their published characters)
**Revenue model:** freemium core + IAP cosmetic / character packs + creator revenue
split.
**Unique work over substrate:** character marketplace, AR anchor persistence, the
creator publishing flow, Apple Pay / Google Pay / Stripe integration.
**Build estimate over substrate:** ~1.5 weeks.

### Box 3 — Games Platform (Prebuilt catalogue + BYOG)  (two-sided marketplace)

**What it is:** the 12 prebuilt scenes shipping as published games + the BYOG
prompt-to-game creator service.
**Where:** slug URLs · Facebook Instant Games · embedded iframe · WebXR.
**Who pays:**
  – Players (per-play OR season pass OR cosmetic IAP)
  – Creators (subscription for BYOG service, plus royalty back when their assets are
    reused in other creators' games)
  – Platform takes a fee on every transaction
**Revenue model:** marketplace fee + asset royalty engine + creator subscription.
**Unique work over substrate:** catalogue UI, BYOG creator UI, royalty engine.
**Build estimate over substrate:** ~2 weeks.

### Box 4 — Solana NFT Site  (crypto consumer)

**What it is:** an NFT collection on Solana where each token is a **summonable
character + a game-unlock pass.** Owning the NFT lets the wallet holder summon that
character into the live-AR app **AND** play the game theme it unlocks. **Reuses the
existing PUMP ORACLE NFT pipeline at `~/Projects/NFT`** (per memory: keystone
`oracle_gen.py` → live signal → Metaplex mint).
**Where:** Solana via Metaplex Token Metadata + Candy Machine v3.
**Who pays:** mint buyers + secondary-market royalty payers.
**Revenue model:** primary mint sale (10k–25k editions × $5–$50 mint) + 5 % royalty
on every secondary sale (Magic Eden, Tensor).
**Unique work over substrate:** Metaplex mint contract, mint front-end, wallet
auth, on-chain → off-chain glue (NFT mint event → server KV grants the holder access
to character + game).
**Build estimate over substrate:** ~1 week (PUMP ORACLE pipeline already proves this
shape).

### Box 5 — Sui NFT Site  (crypto consumer, alt-chain)

**What it is:** **same content as Box 4**, ported to Sui. Each NFT is a Sui Display
Object backed by a Sui Move module that gates the same character + game unlock. Lets
us capture the Sui ecosystem without re-creating the asset pipeline.
**Where:** Sui chain · Sui-native marketplaces (BlueMove, Souffl3, OriginByte).
**Who pays:** Sui-native mint buyers.
**Revenue model:** same as Box 4 (mint + secondary royalty).
**Unique work over substrate:** Sui Move module for the Display Object + capability
guard, mint frontend (TypeScript Sui SDK), wallet integration (Sui Wallet, Suiet,
Ethos).
**Build estimate over substrate:** ~2 weeks (new chain, new SDK, but the content is
identical to Box 4 — so the pipeline payload is free).

### Box 6 — Facebook Free-to-Play Game  (mass casual)

**What it is:** pick the top performer from Box 3's catalogue, package it as a
Facebook Instant Games title, monetize via FB ads + IAP.
**Where:** facebook.com/instantgames + Messenger games tray.
**Who pays:** FB ad network + IAP buyers (FB Payments).
**Revenue model:** rewarded video ads + interstitials + cosmetic IAP.
**Unique work over substrate:** FB Instant Games SDK integration (the
`FACEBOOK_INSTANT_GAMES_PLAYBOOK.md` in this docs/ already walks the path), FB friend
graph hooks, FB leaderboard.
**Build estimate over substrate:** ~1 week.

### Box 7 — Steam Free-to-Play Game  (PC gamer)

**What it is:** the same scene Box 6 ships, exported as a Godot **native** Linux +
Windows binary, published as Free-to-Play on Steam with cosmetic IAP and a season
pass.
**Where:** Steam.
**Who pays:** Steam IAP buyers + season-pass holders + (eventually) DLC buyers.
**Revenue model:** cosmetic IAP + battle-pass + DLC content drops generated via BYOG.
**Unique work over substrate:** Steamworks SDK integration (achievements, friends,
cloud saves, IAP), Steam build pipeline + branch management, Steam Direct submission +
review (~2 weeks of waiting after work is done).
**Build estimate over substrate:** ~2 weeks engineering + 2 weeks Steam review.

### (Future) Box 8 — Meta Glasses Native

**What it is:** the live-AR character app and select game scenes shipped as a
native Quest 3 / Quest Pro app with passthrough rendering at 90 fps.
**Where:** Meta Quest Store.
**Revenue model:** premium app + IAP, mirrors Box 2.
**Build estimate:** ~3 weeks (Meta Quest Store submission + native build target).
**Status:** roadmap only; v2.

---

## 3. The dependency graph — which boxes share which substrate pieces

```
                          SUBSTRATE
                       (built once, used by all)
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
    rendering             asset cache           AI runtime
    (Godot HTML5 +        (ATLAS by-cid)        (Q3-TTS + Kokoro +
     three.js + back-                            Whisper + Gemma)
     face cutout)
        │                     │                     │
        └────────┬────────────┴────────┬────────────┘
                 │                     │
                 ▼                     ▼
            character             scene
            pipeline              pipeline
            (photo_to_avatar      (scene_spine + scene_to_godot
             _rigged.v0)           + floorplan_to_spine)
                 │                     │
                 └──────────┬──────────┘
                            ▼
                     boxes consume

  Box 1  Realtor SaaS        ◄── character + scene + AI runtime
  Box 2  Live AR Character   ◄── character + AI runtime + WebXR + AR anchor
  Box 3  Games Platform      ◄── character + scene + AI runtime + 14 prebuilt scenes + BYOG planner
  Box 4  Solana NFT          ◄── character + scene + Box 2 / Box 3 access grant + Metaplex mint
  Box 5  Sui NFT             ◄── same as Box 4 + Sui Move module
  Box 6  FB Instant Game     ◄── one scene from Box 3 + FB SDK
  Box 7  Steam F2P Game      ◄── one scene from Box 3 + Steamworks SDK
  Box 8  Meta Glasses native ◄── Box 2 + Box 3 + native Quest build target
```

**Substrate work isolates 100 % of the cross-box risk.** A new box never needs a
substrate edit it can't reuse; every substrate edit benefits every box.

---

## 4. The build order — chronological with dependencies

Weeks are **engineer-weeks**. Single full-time engineer baseline. Parallelizable where
boxes don't share unique work.

```
WEEK 0 — substrate (foundation, blocks everything)
  Days 1–2  build SpatialBridge.so + registry entries + bin/assets healing
  Days 3–5  VGGT + cotracker3 wrapped as ComfyUI nodes
  WEEKEND   Kokoro streaming endpoint verified live (already wired in MediaLab)

WEEK 1 — substrate (runtime AI layer)
  Days 1–2  Q3-TTS streaming endpoint
  Day 3     Whisper-turbo edge STT endpoint
  Days 4–5  Gemma-4-E4B-it edge LLM stand-up + character system-prompt harness

WEEK 2 — substrate (transport + persistence)
  Days 1–2  WebXR viewer for one cached character.glb on iPhone Pro + Quest 3
  Days 3–4  Server KV for avatar_cid + session + royalty ledger
  Day 5     Godot HTML5 export pipeline (one make target per scene) — exports the 14 scenes

WEEK 3 — substrate (multiplayer + lyv-realty-ai routes)
  Days 1–3  WebRTC + Yjs CRDT multiplayer scaffold
  Days 4–5  lyv-realty-ai shell routes: /listing/<slug>, /character/<cid>, /game/<cid>

══════════════ SUBSTRATE COMPLETE — every box now unblocks ══════════════

WEEK 4 — Box 1 (Realtor SaaS) — pilot revenue
  Days 1–3  MLS metadata ingestion + agent dashboard
  Days 4–5  Billing plumbing (Stripe) + first-listing pilot with realtor friend
  GOAL: first paid listing live by EOW. First revenue.

WEEK 5 — Box 2 (Live AR Character) — second product, parallelizes
  Days 1–3  Character marketplace UI + AR anchor persistence
  Days 4–5  Creator publishing flow + Stripe / Apple Pay / Google Pay
  PARALLEL: substrate tweaks fall out of Box 1 production load

WEEK 6 — Box 3 (Games Platform) — third product, leverages Box 2 character
  Days 1–2  Catalogue page (the 14 scenes as published games via Week 2 export)
  Days 3–5  BYOG creator UI driving bin/conductor + bin/forge + ComfyUI

WEEK 7 — Box 3 cont. + Box 6 (FB Instant Games)
  Days 1–2  Royalty engine ledger + asset-cid reuse tracking
  Days 3–5  FB Instant Games packaging script (playbook drives) + first FB title
            (pick top performer from Box 3 catalogue)
  GOAL: by EOW, FB Instant Games title live

WEEK 8 — Box 4 (Solana NFT) — leverages existing PUMP ORACLE NFT pipeline
  Days 1–2  Metaplex Candy Machine v3 setup
  Days 3–4  Mint front-end + wallet auth (Phantom, Backpack, Solflare)
  Day 5     NFT-hold → access-grant glue (mint event → server KV)
  GOAL: pre-mint allowlist open by EOW

WEEK 9 — Box 5 (Sui NFT) — port Box 4 to Sui
  Days 1–3  Sui Move module for Display Object + capability guard
  Days 4–5  Mint frontend (Sui SDK) + wallet integration (Sui Wallet, Suiet, Ethos)
  GOAL: Sui pre-mint allowlist open

WEEK 10 — Box 7 (Steam F2P) — substrate now drives native too
  Days 1–3  Steamworks SDK integration (achievements, friends, cloud saves, IAP)
  Days 4–5  Steam build pipeline + Steam Direct submission
  WAITING : ~2 weeks Steam review (parallel with Week 11+ work)

WEEK 11–12 — STYLE PASS — only after every pipe is proven
  All seven boxes get their brand + visual identity polished by a designer.
  Substrate doesn't change; only theming, typography, color, voice copy, marketing.

WEEK 13+ — Iterate based on revenue + retention data; box 8 (Meta glasses) on deck.
```

**Parallelization adds boxes for free.** A single engineer hits the timeline above.
A two-engineer team can split Weeks 4–10 so Boxes 1+4 ship by Week 5, Boxes 2+5 by
Week 6, Boxes 3+6+7 by Week 9 — full slate shipping in ~6 weeks instead of 10.

---

## 5. Per-box revenue model summary

| box | unit economics | break-even per unit | scaling plan |
|---|---|---|---|
| 1 Realtor SaaS | $99–$499 / listing | ~5 listings to cover one engineer-month | direct sales to brokerages |
| 2 Live AR Character | $1/summon + $5–$25 character packs + 5%/turn LLM cost | ~500 users / month for break-even | virality + creator marketplace |
| 3 Games Platform | $0.05–$0.50 / play + asset royalty fees + creator subs | ~10,000 plays / month | content network effect + FB-Instant cross-promotion |
| 4 Solana NFT | 10k mints × $5 = $50k floor / mint event + 5% on secondary | one mint covers a quarter of substrate | utility-bound NFT (= access to Box 2/3); secondary market grows with user base |
| 5 Sui NFT | similar to Box 4 | similar | Sui has hungry NFT buyers, less saturated than Solana |
| 6 FB Instant Game | $0.001–$0.01 / impression + IAP | high volume game; ~1M MAU target | FB's recommendation algo + cross-promo with other Box 6 titles |
| 7 Steam F2P | $0–$15 cosmetic IAP + season pass | ~5,000 daily active for steady revenue | Steam discoverability + content drops via BYOG |

**Cross-box revenue compound:**
- A character generated for Box 2 sells as an NFT in Box 4/5, **and** unlocks a game in Box 6/7
- Same player avatar from Box 2 travels into Box 3 games — that's the retention engine
- BYOG creator in Box 3 sees their assets reused → royalty in Boxes 4–7

**One asset, multiple revenue events** is the unit-economics killer feature. The
ATLAS by-cid model is what makes it auditable.

---

## 6. The style / branding phase (Week 11–12 + ongoing)

**Hard rule: no styling work before pipes are proven.** Painting unfinished walls is
the most expensive thing a small team can do. After Week 10, each box gets:

| box | brand direction (designer brief) |
|---|---|
| Realtor | trust + premium + minimalist white-space; subtle gold accents; serif headers; Mapbox-style polish |
| Live AR Character | playful + Pokémon-Go-energy; bright color blocks; rounded mascot illustrations; pop-art accents |
| Games Platform | vibrant + creator-first; itch.io-meets-Roblox aesthetic; modular cards; loud category tags |
| Solana NFT | crypto-native + degen-friendly; dark theme; neon accents; pixel/lo-fi character art; Solana brand-purple use |
| Sui NFT | crypto-native + premium-feeling; aqua/teal palette per Sui brand; cleaner type than Box 4; slightly more "tech" |
| FB Instant | bright + mass-market; soft pastels; emoji-forward; copy in 6th-grade language; lots of social-proof badges |
| Steam F2P | gamer-aesthetic; darker UI; achievement-style ribbons; lore-forward; trailer-quality key art |

**Substrate stays untouched during the style pass.** Designer touches:
- HTML/CSS templates in lyv-realty-ai shell
- Godot scene materials (matcap art-direction)
- Character creator UI theme
- Marketing pages
- Mint pages (NFT boxes)
- Store-page assets (FB / Steam / Quest)

Engineer-time during style phase: ~10 % of an engineer for designer support. The rest
of engineering goes to **Week 13+ iteration** (kill underperforming boxes, double down
on winners).

---

## 7. Capital + resource plan

### Minimum team (lean)

| role | weeks 0–10 | weeks 11+ | hire by |
|---|---|---|---|
| Engineer #1 (Tom) | 100 % substrate + boxes | 80 % iteration + 20 % designer support | – |
| Designer (contract or part-time) | 0 % until Week 11 | 100 % style pass for 2–3 weeks, then ad-hoc | Week 10 |
| Realtor friend (Box 1 customer #1) | piloting from Week 4 | – | exists ✓ |

### Comfortable team (2 engineers + designer + community)

| role | scope |
|---|---|
| Engineer #1 | substrate + Boxes 2, 3, 6, 7 (rendering / game logic side) |
| Engineer #2 | Boxes 1, 4, 5 (data / blockchain side) |
| Designer | brand identity + UI for all boxes (Week 11+, hired earlier if needed) |
| Community manager | NFT mint + creator marketplace community (from Week 7) |

### Compute footprint (already paid for)

| resource | use | notes |
|---|---|---|
| z21 (dual RTX 3090 Ti) | creator-time asset bakes via `bin/gpud` | governor reserves GPU0 for diffusion |
| Cloud GPU on-demand | overflow + production LLM inference at edge | use bin/gpud cloud-first policy; ~$500 / month buffer |
| Edge CDN (Cloudflare / Fastly) | static bundles for slug URLs + Godot HTML5 builds | ~$50 / month |
| Server KV (Redis / Postgres / SQLite) | cross-product state + royalty ledger | ~$100 / month |
| TURN server (multiplayer fallback) | WebRTC fallback for restrictive networks | ~$50 / month |

**Monthly compute floor:** ~$700. **Variable upside:** asset gen during BYOG creator
sessions + LLM during high-traffic NPC dialog moments. Bounded by `bin/gpud`.

### One-shot capex (already incurred)

- Models on disk: ~200 GB across `/home/tom/models/` and `/data/Projects/MediaLab/`
- Code: ~3 GB across MySpace++ / ATLAS / lyv-realty-ai / gently
- The 14 prebuilt Godot scenes
- 47 ComfyUI workflows + 96 agent_defs

**Translation:** the substrate is already paid for in time + downloads. Going to market
is a labor-only cost.

---

## 8. Risks + mitigations

| risk | impact | mitigation |
|---|---|---|
| `SpatialBridge.so` build fails on this NixOS | substrate stuck at Week 0 | already validated `scons` runs via `nix-shell -p scons`; if godot-cpp 4.3-stable clone fails, fall back to GDScript-only IK (slower but ships) |
| Edge LLM latency > 800 ms first token | Box 2 + Box 3 + Box 6 + Box 7 degrade | tier down to Marlin-2B (11 GB) which is smaller / faster; or use a smaller Gemma variant |
| Q3-TTS quality below realtor expectations | Box 1 customer churn | Kokoro is the fallback voice (already wired in MediaLab); ship Box 1 with Kokoro, upgrade to Q3-TTS later |
| Facebook policy rejection (Box 6) | Box 6 doesn't ship | the `FACEBOOK_INSTANT_GAMES_PLAYBOOK.md` is built around their policy; lower risk than starting blind |
| Steam review delay (Box 7) | timeline slip 2–4 weeks | Steam approval is parallel time; do not block other boxes on it |
| Solana mint network congestion | mint fails / mints at wrong price | PUMP ORACLE pipeline at `~/Projects/NFT` already battle-tested; reuse its priority-fee logic |
| Sui ecosystem still nascent | Box 5 secondary market is thin | accept lower Sui revenue at launch; the cost to ship Sui is low (~2 weeks) so the box pays for itself even at small volume; bonus is brand presence in a less-saturated chain |
| Realtor friend's first listing exposes a substrate bug | Week 4 slip | this is the **whole point** of piloting Box 1 first — bugs in Box 1 fix the substrate for every other box. Plan a Day-12 substrate-bug-fix buffer. |
| BYOG generates a copyright-violating asset | platform liability | mandatory creator-side reference upload + LLM-side prompt filter at submission time; clear ToS that creators own their outputs |
| Cosmos / audio-flamingo never gets weights | v3 upgrades blocked | both are optional polish; v1 ships without them; v2 ships without them; v3 buys them when revenue justifies |

---

## 9. Milestone gates — go / no-go per box

Before declaring a box "shipped," it must clear these gates. If a box can't, kill it
or down-tier it; the substrate isn't the question.

### Gate set (one for every box)

| gate | passes when |
|---|---|
| **G0 Substrate** | the corresponding substrate items in §1 are done |
| **G1 Tech pilot** | one full end-to-end run from input to deliverable in dev |
| **G2 First paying user** | one external user completes the loop and pays (or commits to pay) |
| **G3 Retention** | 30-day retention curve has been measured for that box's cohort |
| **G4 Unit economics** | break-even per unit modeled and validated |
| **G5 Brand** | designer style pass landed |
| **G6 Channel-fit** | meets channel-specific policy / quality bar (FB Instant policy, Steam Direct, Solana / Sui marketplace requirements) |

A box passes "ship" when **G0, G1, G2, G6** are green. **G3, G4, G5** are iteration
gates and don't block first ship.

---

## 10. Success metrics per box (90-day post-launch)

| box | leading metric | lagging metric | kill threshold (if below at 90 days) |
|---|---|---|---|
| 1 Realtor | listings / week | $ ARR | <5 paid listings |
| 2 Live AR Character | DAUs × summons / session | LTV per user | <500 paid summons / month |
| 3 Games Platform | plays / week + BYOG submissions / week | royalty $ / week | <1,000 plays + <10 BYOG submissions |
| 4 Solana NFT | floor price + secondary volume | royalty $ / quarter | mint sells out → 90-day floor below 0.5× mint |
| 5 Sui NFT | same as Box 4 | same as Box 4 | same as Box 4 |
| 6 FB Instant | DAU + ad eCPM | $ / DAU / month | <10,000 DAU |
| 7 Steam F2P | DAU + cosmetic IAP rate | $ / DAU / month | <1,000 DAU |

**Decision principle: kill a box, never the substrate.** If three boxes underperform
in the same 90 days, the substrate still earns from the other four. The boxes are
options; the substrate is the asset.

---

## 11. The five rules — same architecture, restated for the business

These are the rules that keep "one substrate, seven boxes" from devolving into "seven
forks of half a substrate." Memorize them.

1. **cid + pass-tag everything.** Assets, scenes, characters, transactions, royalty
   events. ATLAS `bin/assets` is the audit ledger.
2. **Try T0 / T1 / T2 before any GPU heavy or NN call at runtime.** Free output beats
   $0.10 of NN. Margin lives in this rule.
3. **Climb only on demonstrated gap.** "The cheap version doesn't answer the brief
   because <X>" — and X must name a missing axis.
4. **NN calls (T4) are creator-time, not runtime.** Exception: edge LLM for dialog,
   scoped + bounded + async. **All other diffusion / video-gen is creator-time bake.**
5. **Every climb's output is a new cid + new pass tag.** Today's expensive asset is
   tomorrow's free reuse. Across all seven boxes. **And it earns its creator a royalty.**

---

## 12. The one-page version

**Q: What are we building?**
A substrate that ships seven products: realtor SaaS, AR character app, games platform,
Solana NFT, Sui NFT, FB Instant game, Steam F2P game.

**Q: Why does it work?**
Because the substrate is the product. Each box is a thin wrapper. The cid'd asset
cache means every asset earns across every box.

**Q: How long until first revenue?**
Week 4 — Box 1 with the realtor friend.

**Q: How long until full slate ships?**
Single engineer: Week 10. Two engineers + community: Week 6.

**Q: What does each box cost?**
Substrate: 3–4 engineer-weeks (mostly already paid for). Each box thereafter:
1–2 engineer-weeks of unique work over the substrate.

**Q: What's the highest-risk dependency?**
SpatialBridge.so build → IK + physics across every box. Mitigation: GDScript fallback
ships even if `.so` build is blocked.

**Q: When do we style?**
Week 11+. After every pipe is proven. Never before.

**Q: When do we kill a box?**
At 90 days post-launch if the box's kill threshold isn't met. Substrate stays.

---

## Appendix A — cross-doc traceability

```
substrate_piece                            → required_by_boxes              source_doc
─────────────────────────────────────────────────────────────────────────────────────
SpatialBridge.so (fuse_depth, IK)          → 1, 2, 3, 6, 7, (8)            realtor §9
ATLAS by-cid asset cache                   → all                            all three
photo_to_avatar_rigged.v0 workflow         → 1, 2, 3, 4, 5, 6, 7, (8)      live-AR §8
VGGT + cotracker3 ComfyUI nodes            → 1, 3 (for location bind),       realtor §9
                                              2 (for AR location bind)
Q3-TTS streaming endpoint                  → 1, 2, 3, 6, 7, (8)            live-AR §9
Kokoro streaming endpoint                  → 1, 2, 3, 6, 7                 live-AR §9 (already wired in MediaLab)
Gemma-4-E4B-it edge LLM                    → 2, 3, 6, 7, (8)               live-AR §9
Whisper-turbo STT                          → 2, 3, 6, 7, (8)               live-AR §9
WebXR viewer + AR anchor                   → 2, (8)                         live-AR §9
Godot HTML5 export pipeline                → 3, 6, (Realtor archviz tour)   games §9
lyv-realty-ai slug shell                   → 1, 2, 3                       all three
Server KV (avatar / session / royalty)     → all                            this doc §1
WebRTC + Yjs multiplayer                   → 2, 3, 6, 7, (8)               live-AR §9, games §9
14 prebuilt scenes                         → 3, 6, 7                       games §2
Facebook Instant Games packaging           → 6                              games §9
Steamworks SDK + native export             → 7                              this doc §2
Metaplex Candy Machine                     → 4                              this doc §2 (ref: PUMP ORACLE memory)
Sui Move module + Display Object           → 5                              this doc §2
```

---

## Appendix B — system merkle (shared across all four docs)

`106b80ac5878c4636f0e37822f029289980568f73349350e0e6cdbb0fbd836ad`

This is the same root pinned in the realtor / live-AR / games docs. All four docs
evolve together because the substrate evolves together.

**Reproducibility check:**
```python
import hashlib
roots = sorted([
    '02fb3f4a58640943c83ad46119db8c79e4c3e51af0755f882a54247f043cec58',  # NVIDIA hunt
    '35ea5dbeafe7d04603af2626dcf7cac09608f38cc8dd2797e0282728dd1820f4',  # /home/tom/models
    'a03f1b0d76d6c5a23bad0deca0cf4b1cf86565cd22fa393d940fa34e491a282f',  # ATLAS + ~/Projects
    'c6080116f228e8d846262f10bc5e51e99a2553c1d5e825577414081ffabb2c1f',  # MySpace++/studio
    'fabaee3b12db77e11cdbcff7b6fa5bc5d33b959c740adf5944351ac3897f65f7',  # MediaLab
])
print(hashlib.sha256(''.join(roots).encode()).hexdigest())
# → 106b80ac5878c4636f0e37822f029289980568f73349350e0e6cdbb0fbd836ad
```

When inventory changes, recompute the root, diff sub-trees, only affected sub-trees
re-bake. Everything else stays cached. The substrate evolves through this root; the
boxes evolve through their thin wrappers.

---

## Appendix C — what the four-doc set proves

| doc | proves |
|---|---|
| `REALTOR_VIRTUAL_TOUR_PIPELINE.md` | the pre-rendered tour pipeline + dataset byproducts |
| `LIVE_ACTION_AR_CHARACTER.md` | the live AR character pipeline + cross-game avatar model |
| `GAMES_PLATFORM.md` | the catalogue + BYOG creator service |
| **`BUSINESS_BUILD_PLAN.md`** (this doc) | **the seven-box business strategy that ships the substrate as seven products in order** |

The order across the four docs is:
1. **What we render** — back-face cutout + cost ladder (across all three design docs)
2. **What we produce** — the substrate (this doc §1)
3. **What we ship** — the seven boxes (this doc §2)
4. **When we ship them** — Week 0 → Week 10+ (this doc §4)
5. **How we earn** — per-box revenue (this doc §5)
6. **How we polish** — style phase (this doc §6)
7. **How we know** — gates + metrics (this doc §9, §10)

---

*End of business build plan.*
