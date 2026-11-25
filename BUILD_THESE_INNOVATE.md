# BUILD_THESE_INNOVATE.md

> **Strategic roadmap — every external channel that feeds the chain × every product the chain can ship × the MCP tools that connect them.**
>
> Owner: Tom Lee · Substrate: MySpace++ + GentlyOS · Chain: TensorChain (own blockchain) · IP: CONFIDENTIAL
>
> Reading order: §1 vision → §2 top-value stack → §3 MCP universe → §4 product DAG → §5 product cards → §6 the doc-to-DAG pattern → §7 monetization → §8 substrate-reuse matrix.

---

## §1 — Vision in one paragraph

Every external service that has users + messages + media is an **input lane** into the crystal chain. Every game engine, marketplace, and social platform is an **output lane** out of the chain. The chain itself is `studio_runtime` + `ops_dag` + `hf_hub` + `task_queue` + `inference_logger` already running today. **MCP tools** become the unified driver layer between Claude/Kimi/DeepSeek/our-chain and every external service, so any agent can drive any service through one protocol. **TensorChain** (Tom's blockchain) is the settlement layer for assets, NFTs, smart contracts, micro-payments, and royalty splits. Top value ships first — real-estate walkthrough — because the substrate already exercises every component it needs; everything else stacks on top.

---

## §2 — Top-value stack (ship-first)

Ordered by `value / effort` ratio. Each one is a marketable product, not a side experiment.

| # | Product | Time-to-MVP | Recurring Revenue | What's Already Built |
|---|---|---|---|---|
| **1** | Real-estate walkthrough w/ 3D + agent-automated realtor↔client chat | days | $999/run + monthly subs | `realestate_walkthrough_full.v0.json` card runs end-to-end today; just needs realtor chat agent |
| **2** | Digital avatar NFT + smart contract on TensorChain | weeks | mint fee + royalty | avatar_rigged scene + ParserCursor + Godot project + Mixamo 19 FBX selected |
| **3** | SVG/XML inference app (the parser engine as a product) | days | API + per-call | `svg_vector_embed`, `parser_cursor`, energy_inversion, multi_layer_hex all live |
| **4** | Slug-pages-as-a-service (advertisement OR private avatar gamified controller) | weeks | $5–50/mo per slug | workflow_generator → 7 surfaces; need slug router + auth |
| **5** | AI agents-as-asset for Unreal/Unity/Roblox marketplaces | weeks | $10–300 per asset | studio_runtime card → engine-specific export already designed |
| **6** | Twitch/Discord/streaming overlays + bot apps | days | $5/mo per channel | hf_hub for inference; just need Twitch + Discord MCP wired |
| **7** | Realtor agent (sub-product of #1, sellable standalone) | days | $99/mo per agent | spatial_anchor + room sig + chat agent over hf_hub |
| **8** | Trading bot via TopstepX (futures scalper) | weeks | profit-share | trade-blob/ at /data/Projects/ already has 581-file Python scalper |
| **9** | Crypto ATM as a game asset (Unity/Unreal plugin) | weeks | per-install + tx fee | TensorChain smart-contract + Godot/Unity bridge |
| **10** | LivePeer streaming platform with peer-routed AI agents | weeks | per-minute | weave fabric + browser pool + ZeroGPU |

**Reality check**: #1, #3, #6, #7 can ship within 2 weeks because their substrate is already running. The rest stack on the work in [[lively-enchanting-parrot]] plan.

---

## §3 — MCP tool universe

One MCP server per external service. Same protocol, any agent can drive any service. Already live: `blender-mcp` (stdio JSON-RPC). Coming: `godot-mcp` (task #31).

### 3.1 Communications layer (chat + DM + groups)

| MCP | State | Tools to expose | Free? |
|---|---|---|---|
| `discord-mcp`     | stub connector exists; wrap as MCP | `send_dm`, `post_channel`, `slash_cmd_register`, `voice_join`, `bot_status`, `game_invite` | yes (bot token) |
| `telegram-mcp`    | stub connector exists | `send_msg`, `send_media`, `inline_bot_query`, `channel_post`, `webapp_open` | yes |
| `whatsapp-mcp`    | stub connector exists | `send_msg`, `send_media`, `group_create`, `broadcast`, `business_catalog` | Business API only (paid) |
| `facebook-mcp`    | stub connector exists | `page_post`, `messenger_send`, `ad_create`, `pixel_event`, `graph_query` | API key |
| `instagram-mcp`   | piggyback off facebook | `feed_post`, `story_post`, `reel_publish`, `dm_send`, `creator_studio` | via FB Graph |
| `twitter-mcp`     | stub connector exists | `tweet`, `thread`, `dm`, `spaces_create`, `list_subscribe`, `community_post` | API tier |
| `tiktok-mcp`      | NEW | `video_upload`, `creator_dm`, `effect_publish`, `live_chat_listen` | API access required |
| `youtube-mcp`     | NEW | `video_upload`, `live_chat`, `comment_post`, `playlist_manage`, `caption_set`, `super_chat_listen` | API quota free |
| `twitch-mcp`      | NEW | `chat_send`, `clip_create`, `predictions_open`, `bits_listen`, `eventsub_subscribe`, `extension_publish` | OAuth, free |
| `kick-mcp`        | NEW | `chat_send`, `stream_status`, `subscriber_listen` | free, scraper-based until API |
| `onlyfans-mcp`    | NEW | `mass_dm`, `welcome_msg`, `tip_listen`, `subscription_event`, `vault_post` | scrape-only; gate by user OAuth |

### 3.2 Media + dataset layer

| MCP | State | Tools | Free? |
|---|---|---|---|
| `pinterest-mcp`    | connector live; wrap as MCP | `search`, `pin_create`, `board_create`, `harvest_board` | API + scrape |
| `huggingface-mcp`  | `hf_hub.py` is the bridge; expose via MCP | `search_models`, `model_card`, `infer`, `stream_dataset`, `space_call` | yes |
| `hf-datasets-mcp`  | subset of above | `list`, `stream_rows`, `mount` (via hf-mount) | yes |
| `comfyui-mcp`      | placeholder | `submit_workflow`, `node_register`, `embed_run` | yes (local) |
| `replicate-mcp`    | via hf-providers | already routes through `hf_hub` | paid |
| `tensorchain-mcp`  | NEW (Tom's chain) | `mint_nft`, `deploy_contract`, `tx_broadcast`, `query_balance`, `royalty_split`, `escrow_settle` | TensorChain |

### 3.3 Game/dev/asset layer

| MCP | State | Tools | Free? |
|---|---|---|---|
| `godot-mcp`         | task #31 — design phase | `scene_load`, `node_add`, `script_eval`, `texture_set`, `export_target`, `playtest_start` | yes |
| `unreal-mcp`        | community exists; wrap | `actor_spawn`, `bp_compile`, `material_set`, `level_load`, `nanite_status`, `metahuman_drive` | yes (UE5 plugin) |
| `unity-mcp`         | NEW | `scene_open`, `prefab_create`, `script_attach`, `build_target`, `assetbundle_pack` | yes |
| `roblox-studio-mcp` | NEW | `asset_upload`, `script_publish`, `model_publish`, `team_create_join`, `marketplace_list` | OAuth, free |
| `blender-mcp`       | LIVE | `mesh.create`, `material.set`, `light.add`, `render.image`, `bone.set_rotation`, `python.exec` | yes |

### 3.4 Trading / commerce layer

| MCP | State | Tools | Free? |
|---|---|---|---|
| `topstepx-mcp`     | trade-blob has the SDK; wrap as MCP | `account_status`, `order_market`, `order_limit`, `positions`, `bracket_attach`, `pnl_intraday` | acct required |
| `stripe-mcp`       | NEW (for slug-pages revenue) | `payment_intent`, `subscription_create`, `webhook_route` | yes |
| `coinbase-mcp`     | NEW (off-ramp from TensorChain) | `wallet_balance`, `tx_send`, `price_quote`, `swap_route` | yes |

### 3.5 Streaming / live layer

| MCP | State | Tools | Free? |
|---|---|---|---|
| `livepeer-mcp`     | NEW | `stream_create`, `transcode_route`, `webhook_listen`, `multistream_target` | yes |
| `obs-mcp`          | NEW (OBS WebSocket) | `scene_switch`, `source_visible`, `audio_mix`, `replay_buffer` | yes |
| `restream-mcp`     | NEW | `channel_link`, `multicast`, `chat_unify` | free tier |

### 3.6 Infra / scrape layer

| MCP | State | Tools | Free? |
|---|---|---|---|
| `replit-mcp`        | NEW | `repl_create`, `deploy`, `secret_set`, `console_run` | free tier |
| `chromium-mcp`      | weave/webgpu_worker.html already serves this | `goto`, `screenshot`, `extract`, `webgpu_compute` | yes (own browsers) |
| `nounproject-mcp`   | planned in [[lively-enchanting-parrot]] | `search`, `harvest`, `icon_meta` | 5k/mo free |

---

## §4 — Product DAG (the logical pattern)

Every product is a DAG of `(MCP_inputs → substrate → MCP_outputs → monetization_channel)`. Same shape, different node fills.

### 4.1 Universal product DAG template

```
        ┌──────────────────────────────────────────────────────────┐
        │                  PRODUCT DAG TEMPLATE                     │
        └──────────────────────────────────────────────────────────┘

  INPUT MCPs           SUBSTRATE                  OUTPUT MCPs         MONETIZATION
  ──────────           ─────────                  ───────────         ────────────
  pinterest-mcp ─┐                                                    ┌─ slug page
  noun-mcp      ─┤                                                    │  ($5–50/mo)
  hf-mcp        ─┼─► workflow_card ──► studio_runtime ──► surfaces ──┤
  topstepx-mcp  ─┤        │              │                            ├─ marketplace
  twitch-mcp    ─┤        │              ├─► hf_hub.inference         │  ($10–300)
  godot/unreal  ─┘        │              │      19 providers + zerogpu│
                          │              │                            ├─ NFT mint
                          ▼              ├─► task_queue              │  (TensorChain)
                    ops_dag DAG          │      4 pools + cache       │
                          │              │                            ├─ API per-call
                          ▼              ├─► inference_logger        │  ($/1k tokens)
                    InferenceRecord     │      crystal chain         │
                          │              │                            └─ subscription
                          ▼              └─► workflow_generator      
                    layer_stack_emb           7 surfaces             
                    (multi-layer hex)
```

### 4.2 Real-estate walkthrough DAG (top-value product #1)

```
  pinterest-mcp ─► [harvest interior]
  noun-mcp ─────► [harvest icons]                            ┌─► streamlit surface
  blender-mcp ──► [3D scene assembly]                        │   (lead-capture site)
                                                              │
  realtor chat:                                                ├─► godot .tscn + .gd
  discord/whatsapp/      ┌──► spatial_anchor (room)            │   (interactive walkthrough)
  telegram ──────────────┼──► light_source (emission)          │
                          ├──► svg_vector_embed (icons)         ├─► comfyui workflow
                          ├──► frame_clock (60fps)              │   (avatar render)
                          ├──► studio_runtime                   │
                          │                                      ├─► remotion .mp4
                          └──► hf_hub.inference ─► caption       │   (video tour)
                               (Kimi K2 via Groq, ~5s)           │
                                                                  ├─► twilio SMS lead
                                                                  │   capture
                                                                  │
                                                                  └─► TensorChain
                                                                      smart contract
                                                                      (escrow $999)

  Monetization: $999/walkthrough + $99/mo realtor agent subscription
```

### 4.3 Digital avatar NFT DAG (top-value product #2)

```
  user photo upload ────► [photo_to_avatar_rigged card]
                             │
                             ├─► Mixamo idle FBX (already 19 on disk)
                             ├─► flux_2_klein face swap (LoRA on disk)
                             │
                             ▼
                          rigged GLB + thumbnail PNG
                             │
                             ├─► comfyui-mcp (3 render passes: front/side/back)
                             ├─► blender-mcp (poly count reduction)
                             │
                             ▼
                          IPFS pin (via hf-mount or pinata)
                             │
                             ▼
                          tensorchain-mcp.mint_nft({ipfs_uri, attributes, royalty_bps})
                             │
                             ▼
                          NFT lands in wallet → twitter-mcp posts → discord-mcp
                          announces

  Monetization: mint fee ($25–100) + 5% royalty on secondary sales
```

### 4.4 Slug-pages-as-a-service DAG

```
  user signs up via stripe-mcp ─► slug allocated (e.g., myspace.fun/cosmic-cat)
                                       │
                                       ├──── advertisement mode ─────────────────┐
                                       │     (pinterest harvest + hf caption +    │
                                       │      noun-mcp icons + ad placeholders)    │
                                       │                                            │
                                       └──── private avatar mode ─────────────────┤
                                             (rigged NFT + Godot WebGL export +     │
                                              gamified controller + cc_node          │
                                              recursive labeling)                    │
                                                                                      │
                                       ┌──────────────────────────────────────────────┘
                                       ▼
                                  workflow_generator → streamlit + godot HTML5 export
                                       │
                                       ▼
                                  Hosted at slug.myspace.fun (Caddy → DO droplet)
                                       │
                                       ▼
                              twitch/youtube/discord embed-ready
                                       │
                                       ▼
                              tracking → InferenceRecord per pageview
                              → monetization analytics via topstepx-style P&L
                                view

  Monetization: $5/mo (basic ad) → $50/mo (private gamified) → $500/mo (commerce)
```

### 4.5 SVG/XML inference app DAG (the parser engine as a sellable API)

```
  customer POST /infer
    body: {svg_or_xml: "..."}
                             │
                             ▼
                       parser_cursor.parse → CursorNode tree
                             │
                             ├─► svg_vector_embed.geometry_crystal
                             ├─► sentence_chain (XML tag text)
                             ├─► multi_layer_hex.pack (8 slots)
                             │
                             ▼
                       moe_router.find_neighbors (5 axes)
                             │
                             ▼
                       hf_hub.inference (interpret semantically)
                             │
                             ▼
                       response: {tree, embeddings, semantic_label, similar_files}

  Monetization: $0.001/call free tier; $5/1k calls; $99/mo unlimited; private deploy $500/mo
```

### 4.6 AI agent as Unreal/Unity/Roblox asset DAG

```
  asset_card.json describes:
    - personality (kimi K2 system prompt)
    - knowledge corpus (which crystal-chain records to attach)
    - voice (speech-to-speech HF)
    - look (digital avatar NFT or generic mesh)
                             │
                             ▼
                       studio_runtime → packages:
                             │
       ┌─────────────────────┼─────────────────────┐
       │                     │                     │
       ▼                     ▼                     ▼
   .uasset (Unreal)    .unitypackage         .rbxm (Roblox)
   + cpp plugin        + C# wrapper          + Lua script
       │                     │                     │
       │                     │                     │
       ▼                     ▼                     ▼
   Unreal Marketplace   Unity Asset Store    Roblox Marketplace
   ($30–300)            ($30–300)            (Robux + DevEx)

  Each instance phones home via hf_hub.inference (low-cost DeepSeek tier).
  Royalty + usage tracked on TensorChain.

  Monetization: per-asset purchase + per-call inference markup (sticky API revenue)
```

### 4.7 Twitch/Discord overlay+bot DAG

```
  channel_owner installs cc-overlay (one binary)
                             │
                             ▼
                  twitch-mcp.eventsub.subscribe (chat, bits, follows, predictions)
                  discord-mcp.bot.online
                             │
                             ▼
                  every event → InferenceRecord(tier='live_event')
                             │
                             ▼
                  hf_hub.inference (free Groq tier mostly) generates:
                    - chat moderation suggestions
                    - automatic clip captions
                    - subscriber thank-you messages
                    - prediction reactions
                             │
                             ▼
                  obs-mcp.scene_switch (when goal reached)
                  twitch-mcp.clip_create (highlight moments)

  Monetization: $5/mo per channel; $25/mo with custom voice; $99/mo with sponsor
                ad insertion via TensorChain bid-based ad market
```

---

## §5 — Per-product cards (one-page specs)

Each product gets a card in `studio/assets/_products/<slug>.product.v0.json` with this schema:

```json
{
  "_schema": "product_card_v0",
  "vm_id": "vm_mspc_001",
  "name": "<slug>",
  "tagline": "<one line>",
  "value_tier": 1-10,
  "ttm_days": <int>,
  "monthly_recurring_usd": [low, mid, high],
  "input_mcps": ["pinterest-mcp", "noun-mcp", "..."],
  "substrate_uses": ["studio_runtime", "spatial_anchor", "..."],
  "output_surfaces": ["streamlit", "godot_html5", "..."],
  "monetization_channels": ["stripe_subscription", "tensorchain_nft", "..."],
  "depends_on_phases": ["phase1", "phase2"],
  "status": "ACTIVE | DESIGN | TEXT-PLACEHOLDER"
}
```

10 product cards to drop (one per row in §2). Each is one-page — substrate-anchored, monetization-anchored, dependency-aware.

---

## §6 — The doc-to-DAG pattern (turning ANY product idea into substrate)

Given any product description (a paragraph in this doc, a Notion note, a Discord message), apply this transform:

```
STEP 1: Identify INPUTS (where data comes from)
   → match against §3 MCP table → list MCP servers needed

STEP 2: Identify SUBSTRATE (what chain capabilities apply)
   → match against existing modules (svg_vector_embed, spatial_anchor,
     hf_hub, workflow_generator, etc.)
   → if missing: add to [[lively-enchanting-parrot]] plan

STEP 3: Identify OUTPUTS (where the product ships)
   → match against output surfaces (streamlit, godot, unreal, mcp_target)
   → workflow_generator already emits 7 surface types

STEP 4: Identify MONETIZATION
   → subscription / per-call / NFT mint / royalty / asset sale / data sale

STEP 5: Compose the DAG
   → INPUT_MCPs ──► workflow_card.passes ──► OUTPUT_MCPs ──► monetization
   → write to studio/assets/_products/<slug>.product.v0.json
   → write to studio/assets/_workflows/<slug>.workflow.v0.json

STEP 6: ops_dag.build picks up new product + workflow → auto-DAG generated
   → tesseract rebuild surfaces the new product in the master SVG
   → dialectic_walker establishes is/is-not/becoming for the new node

STEP 7: Smoke test via cc studio-run <workflow_slug>
   → 9 of 10 passes should run in --dry-run; failed substrate → ops_dag bug
```

This pattern is **the logical pattern** Tom asked for. Every future product idea passes through this transform. The DAG falls out automatically.

---

## §7 — Monetization channels (where the money is)

| Channel | Mechanism | Tax / Latency | Suited for |
|---|---|---|---|
| Stripe subscription | $5–500/mo recurring | 2.9%+30¢, instant | slug-pages, agents, overlays |
| One-time sale | Unreal/Unity/Roblox marketplaces | 30% platform cut, weekly payout | game asset MCPs |
| NFT mint | TensorChain on-chain | gas fee, instant settlement | avatar NFTs, digital scarcity |
| NFT royalty | TensorChain on-chain | 5–10% on secondary | sticky long-tail income |
| API per-call | $0.001–$0.05 per request | Stripe metered, instant | SVG/XML inference app |
| Profit-share | TopstepX trading P&L split | weekly settlement | trading bot subscribers |
| Ad placement | Slug-page bid market on TensorChain | per-impression on-chain | advertisement slugs |
| Per-stream minute | LivePeer transcoding markup | per-minute on-chain | livestream platform |
| Custom build | Whitelabel deploy | $5k–50k flat | enterprise real-estate, realtor cos |

**The compounding play**: every product feeds the chain (more InferenceRecords) → moe_router gets smarter (more retrieval depth) → cache hit rate climbs → marginal inference cost trends to zero → margin expands forever.

---

## §8 — Substrate-reuse matrix

| Product | studio_runtime | hf_hub | spatial_anchor | svg_vector_embed | parser_cursor | tensorchain | blender_mcp | godot_mcp |
|---|---|---|---|---|---|---|---|---|
| Real-estate walkthrough     | ✓ | ✓ | ✓ | ✓ |   | ✓ (escrow) | ✓ | ✓ (#31) |
| Digital avatar NFT          | ✓ | ✓ |   | ✓ |   | ✓ (mint) | ✓ | ✓ (#31) |
| SVG/XML inference app       | ✓ | ✓ |   | ✓ | ✓ |   |   |   |
| Slug pages                  | ✓ | ✓ |   | ✓ |   | ✓ (ads) |   | ✓ (#31) |
| AI agent asset              | ✓ | ✓ |   |   |   | ✓ (royalty) | ✓ | ✓ (#31) |
| Twitch/Discord overlays     |   | ✓ |   |   |   |   |   |   |
| Realtor chat agent          | ✓ | ✓ | ✓ |   |   |   |   |   |
| Trading bot (TopstepX)      | ✓ | ✓ |   |   |   |   |   |   |
| Crypto ATM game asset       | ✓ |   |   |   |   | ✓ (core) |   | ✓ (#31) |
| LivePeer platform           | ✓ | ✓ |   |   |   | ✓ (per-min) |   |   |

**Read this matrix top-down**: every product reuses `studio_runtime` and `hf_hub`. The chain spine pays back across all 10 products. **Build the spine once, ship the products forever.**

---

## §9 — Sequencing (in alignment with [[lively-enchanting-parrot]] phases)

```
WEEK 1-2  (Phase 1 of plan)    multi_layer_hex + cloud_providers + router_policy + doc_parser
                                ┌──► Unblocks: SVG/XML inference app  (Product #3)
                                └──► Unblocks: Twitch/Discord overlays (Product #6)

WEEK 3-4  (Phase 2 of plan)    DeepSeek + Noun Project + harvest_loop
                                ┌──► Unblocks: Slug pages (advert mode) (Product #4)
                                └──► Boosts: Real-estate walkthrough caption quality

WEEK 5-6  (Phase 3 of plan)    Godot self-labeling + scene_chain + cc_button
                                ┌──► Unblocks: AI agent asset for Godot (Product #5)
                                └──► Unblocks: Slug pages (private avatar) (Product #4)

WEEK 7-8  (Phase 4 of plan)    ZeroGPU + DO droplet + browser_pool + #31 MCP↔Godot
                                ┌──► Unblocks: All MCP-driven products
                                └──► Unblocks: LivePeer streaming (Product #10)

WEEK 9-10 (new phase: MCP tools)
                                godot-mcp · twitch-mcp · youtube-mcp · discord-mcp
                                tensorchain-mcp · topstepx-mcp wrap as MCP

WEEK 11-12 (PRODUCT LAUNCHES)
                                Real-estate walkthrough live with first 3 realtor clients
                                SVG/XML inference API on api.myspace.fun
                                Slug pages public beta with 50 users
                                First Unreal/Unity asset listed
```

**End of quarter**: 4 products live, 6 more 1–2 weeks from launch. Recurring revenue from 3 channels. ChainRecord index past 10k records → MoE-by-retrieval starts to outperform DeepSeek on internal use cases.

---

## §10 — Hard rules

1. **No duplication.** Every product reuses the spine — `studio_runtime`, `hf_hub`, `task_queue`, `inference_logger`. If a product needs a new module, add to [[lively-enchanting-parrot]] plan FIRST, then build.

2. **TensorChain is the settlement layer.** No Sui, no Ethereum L1 fees, no Solana. Tom owns the chain.

3. **MCP is the agent protocol.** Every external service that survives more than one product gets a dedicated MCP server. One protocol, many tools, any agent (Claude / Kimi / DeepSeek / local).

4. **Crystal-anchor every transaction.** NFT mint, smart-contract call, API charge, ad bid — every monetization event becomes an InferenceRecord with crystal hash. The chain doubles as audit trail for revenue.

5. **Top-value first.** Real-estate walkthrough goes live in week 1–2 because the substrate is already running. Everything else stacks on top.

6. **The 6-layer trace.** Every user interaction (Godot click, Discord message, API call, NFT mint, ad view) leaves a 6-layer trace in the chain (noun_crystal / sym_indexer_label / scene_uid / function_signature / cc_event / inference_record). Same shape across all 10 products.

7. **Free lane first.** 80%+ of inference rides the free lane (ZeroGPU + browser pool + Groq + cache). Paid lane (DeepSeek + Claude) reserved for premium product features. Margin expands as chain grows.

---

## §11 — The recursion

Every product in this doc, when shipped, **produces more chain data**. More chain data → smarter MoE retrieval → better products. The doc itself is parsed by `doc_parser` → ingested into ops_dag → walked by dialectic_walker → suggests new products. **This doc rewrites itself as the chain grows.**

That's the whole game.

[ end of BUILD_THESE_INNOVATE.md — Owner: Tom Lee (Zero2oneZ) — All IP Confidential ]
