# Consolidation Proposal — Two Tesseracts + Rust Chain → One System

**Created:** 2026-05-26
**Pair files:**
- `/data/Projects/MySpace++/MASTER-INFERENCE.svg` (new — HOW the chain runs)
- `/data/Projects/MySpace++/studio/docs/Tesseract.svg` (sister — WHAT exists; 253 nodes, 8 DAGs, 729 edges)
- `/data/Projects/MySpace++/GENTLY-TESSERACT.svg` (reference snapshot of my generic 7-layer template)

---

## TL;DR

Two SVGs, one chain. The existing Tesseract.svg (sister Claude's) is the **inventory** — what nodes / passes / models / subsystems / project-types exist in MySpace++. MASTER-INFERENCE.svg is the **scheduler** — how the rust chain rotates inference across layers per visit, which surfaces render, who can see what. They cross-reference: the inference SVG names node-UIDs that resolve into the Tesseract SVG. The walker.py contract enforces consistency.

The Lucid design pattern is borrowed (custom shapes + formulas + scopes + MCP-style connectors + data actions) and re-hosted on the droplet. No Lucid SaaS bill, no document lock-in.

The browser becomes the runtime extension. Every visit = chain step. Cookies = cache key. SVG response is the full UI. HTMX swaps fragments. No SPA, no separate landing/admin/tools pages, no ads, no logins.

---

## What's already there

### Sister Claude's MySpace++ Tesseract

| Piece | Path | What it does |
|---|---|---|
| Master SVG | `studio/docs/Tesseract.svg` | 253 nodes across 8 source DAGs, 729 edges, ~120KB |
| Walker contract | `studio/tesseract/walker.py` | 3-req enforcer: `identify(uid, neighbors, subjects)` |
| Inventory builder | `studio/tesseract/inventory.py` | Discovers nodes from opcode/model/recipe/flow/pass/template/subsystem/project_type sources |
| Project types | `studio/tesseract/projects.py` | 9 project types × 10 subsystems switchboard |
| SVG emitter | `studio/tesseract/svg.py` | Re-builds the master SVG from sources |
| Plan tracker | `studio/tesseract/plan.py` | Steps + help graph |
| Auth gate | `studio/auth/gate.py` + `keys.sqlite` | Salted keys, scope-restricted clients |
| Lucid bridge | `studio/lucid/standard_import.py` + `studio/docs/Tesseract.lucid-si.json` | Tesseract → Lucid Standard Import JSON converter (348KB output) |

### My new layer

| Piece | Path | What it does |
|---|---|---|
| Master scheduler SVG | `MASTER-INFERENCE.svg` | Request lifecycle, layer rotation, stacked HTMX view, chain DB as ACL, visitor-aware rendering, Lucid pattern map |
| Generic template snapshot | `GENTLY-TESSERACT.svg` | My original 7-layer Tesseract template from `/data/Projects/gently/templates/tesseract/master.svg` — kept for reference only |
| This document | `CONSOLIDATION.md` | The unification plan |

### Backing rust runtime (already shipped)

| Crate | What it does |
|---|---|
| `gently-runtime` | `Predict / Execute / Terminate` traits + `run(chain)` — the 8-LOC axiom |
| `bb-runtime-adapter` | Wraps `gently-bb` as `Execute` slot |
| `codie-v4-predict` | Predict slot — ollama HTTP + template-fallback |
| `gently-svg-layers` | SVG-as-Layer-DAG parser/executor |
| `gently-hf-dispatch` | `local:` / `hf://model_id/layer` dispatcher |
| `gently-inference-budget` | Per-visit pipeline router (Draft/Standard/Cinematic/Realtime) |
| `gently-probe` | Visitor classification → activation_hex |
| `gently-bw-patterns` | Black-and-white pattern lib (IF/SWITCH eval primitives) |
| Run #20 spatial stack | scene_circle / god_box / capsule rig / 3-point orbit / walk_cycle / hex lens / painter |

---

## The two-SVG architecture

```
                              ┌─────────────────────────────────────┐
                              │  visitor opens any MySpace++ URL    │
                              └──────────────────┬──────────────────┘
                                                 │
                                                 ▼
                              ┌─────────────────────────────────────┐
   gently-probe ──────────►  │  rust chain step: extend(visit)    │
   activation_hex             │  predict → which subsystem fires   │
                              │  execute → run that pass            │
                              │  terminate → seal crystal hash      │
                              └──────────┬──────────────────┬───────┘
                                         │                  │
                       WHAT exists ◄─────┘                  └─────► HOW it runs
                                                                    
              ┌──────────────────────────┐         ┌───────────────────────────┐
              │ studio/docs/Tesseract.svg │         │ MASTER-INFERENCE.svg      │
              │ 253 nodes, 8 DAGs         │         │ request lifecycle         │
              │ walker.py 3-req contract  │         │ layer rotation            │
              │ project-type switchboard  │         │ stacked HTMX view         │
              │ subsystem status colors   │         │ visitor budget routing    │
              │ Lucid SI export ready     │         │ chain DB = ACL            │
              └──────────────┬───────────┘         └────────────┬──────────────┘
                             │                                  │
                             └──────────────┬───────────────────┘
                                            ▼
                              ┌──────────────────────────┐
                              │ stacked SVG response      │
                              │ HTMX hx-swap fragments    │
                              │ landing / tools / admin / │
                              │ tesseract — all in ONE    │
                              └──────────────────────────┘
                                            │
                                            ▼
                              ┌──────────────────────────┐
                              │ browser cooks chromium     │
                              │ juice (JS/WebGL/CSS)       │
                              │ caches via cookie crystal  │
                              └──────────────────────────┘
```

The two SVGs are NOT redundant. They have orthogonal responsibilities:

| Concern | Sister Tesseract.svg | MASTER-INFERENCE.svg |
|---|---|---|
| Inventory of nodes | ✓ | references only |
| Walker contract enforcement | ✓ (Python) | (delegated to walker.py) |
| Project-type switchboard | ✓ | references only |
| Subsystem status colors | ✓ | references only |
| Request lifecycle | — | ✓ |
| Layer rotation policy | — | ✓ |
| Stacked HTMX view | — | ✓ |
| Visitor budget routing | — | ✓ |
| Chain-database = ACL | — | ✓ |
| Lucid design pattern map | — | ✓ |

The new SVG points into the existing one for "what exists" — never duplicates that data.

---

## The Lucid pattern — borrowed, not bought

Per `/home/tom/Datasets/_intake/LUCID_API_RESEARCH.md` and sister Claude's mapping work, here is what we **take** vs **skip** from Lucid:

### Take (design pattern only, droplet-hosted)

| Lucid concept | Our droplet equivalent | Where it lives |
|---|---|---|
| Custom `.shape` files | SVG `<g>` with `mspc:*` data attrs | `Tesseract.svg` + `MASTER-INFERENCE.svg` |
| Formula language (IF/SWITCH/RGB/ATTRIBUTES) | JS inline OR server-side via `gently-svg-layers` + `gently-bw-patterns` | New: `studio/runtime/formulas.rs` (~80 LOC) |
| Data connectors (`dataActions` manifest) | Rust chain endpoints (`/walk/identify`, `/chain/run`, `/pass/run`, `/pieces/search`) | New: `studio/runtime/server.rs` (~300 LOC) |
| Scope-restricted OAuth (READ/WRITE/ADMIN/AGENT) | Salted keys in `studio/auth/keys.sqlite` + `gate.py` | Already exists |
| Webhook event payloads | Rust chain self-extension via crystal hashes | Already exists (the axiom) |
| MCP server pattern | JSON-over-HTTP at `/mcp/` reading MASTER-INFERENCE.svg | New: `studio/runtime/mcp.rs` (~150 LOC) |
| CLI scaffolder (`npx lucid-package create-...`) | `cc -tesseract-*` family of commands | Already exists per `TESSERACT.md` |
| Standard Import JSON | `studio/lucid/standard_import.py` → `Tesseract.lucid-si.json` | Already exists (348KB output) |

### Skip (the SaaS bill, the vendor lock-in)

- No Lucid document hosting (we host our own SVGs)
- No Lucid editor runtime (we render via HTMX)
- No Pro tier subscription ($9.95/mo per user)
- No webhook retry/HMAC infra (the rust chain self-extends; no external callback needed)
- No multiplayer CRDT (single-visitor sessions; agent merges via walker contract)
- No iframe embed tokens (the SVG IS the surface; no embedding)

### What this buys us

- **Sovereignty:** every byte on the droplet, no third-party JS, no external auth
- **Determinism:** rust chain crystal hashes mean re-runs are byte-identical
- **Performance:** SVG inline + browser cache + cookie-keyed responses = sub-second first paint
- **Privacy:** no analytics beacon, no email collection, no consent gates
- **Cost:** $5/mo droplet vs $9.95/user/mo Lucid Pro × N users

---

## Five consolidation moves (also encoded as Layer 7 in MASTER-INFERENCE.svg)

### M1 — Unified walker contract (~150 LOC, first)

**Goal:** one `identify()` function works against both SVGs.

- Add a fourth required field to the walker contract: `chain_hash` (which chain sequence populated this node)
- Port `walker.py` logic into `gently-svg-layers::walker` (Rust)
- Keep Python walker as the CLI / agent-facing surface; Rust walker as the server-side validator
- Both read/write the same `<metadata>` manifest format

**Files:**
- `crates/gently-svg-layers/src/walker.rs` (new)
- `studio/tesseract/walker.py` (add `chain_hash` field)
- `studio/docs/Tesseract.svg` + `MASTER-INFERENCE.svg` both gain `walk-chain-hash` attr per node

**Unlock:** same agents work both SVGs; chain provenance is auditable.

### M2 — Rust chain as web handler (~300 LOC, second)

**Goal:** the runtime IS the HTTP server. No Flask/FastAPI mediator.

- Axum (or Tide) wrapper around `gently_runtime::run()`
- Routes:
  - `GET /` → renders `MASTER-INFERENCE.svg` with visitor-scoped layer enables
  - `GET /api/svg/:layer_id` → returns one `<g>` fragment for hx-swap
  - `POST /api/walk/identify` → calls walker contract
  - `POST /api/chain/run` → extends chain, returns crystal hash + SVG diff
  - `GET /api/tesseract/status` → returns walker status JSON

**Files:**
- `crates/myspace-server/Cargo.toml` (new)
- `crates/myspace-server/src/main.rs` (new, ~300 LOC)
- `studio/runtime/templates/` — Jinja-style SVG fragment templates

**Unlock:** browser visit = chain step; HTMX endpoints exist; everything serves from one rust binary.

### M3 — Visitor probe + budget routing (~200 LOC, third)

**Goal:** same chain serves anon / user / admin differently — automatically.

- `gently-probe::classify(headers, cookies, ip)` → `ActivationHex` (12-bit mask over layers)
- `gently-inference-budget::route(activation_hex, scope)` → `QualityTarget` (Draft / Standard / Cinematic / Realtime)
- Cookie `mspc_visitor_crystal` holds the visitor's chain hash (cache key)
- Returning visitor: cache hit, instant render
- Cold visit: chain extends, browser cooks the new juice

**Files:**
- `crates/gently-probe/src/lib.rs` (extend)
- `crates/gently-inference-budget/src/lib.rs` (extend)
- `crates/myspace-server/src/visitor.rs` (new)

**Unlock:** rendering automatically adapts to who's looking, no a/b config.

### M4 — Stacked SVG renderer (~250 LOC, fourth)

**Goal:** one HTML page, all surfaces inside.

- `index.html` is a 20-line shell that loads `MASTER-INFERENCE.svg` inline
- All `<g>` groups carry `gently:visibility="visitor|user|admin|agent"` attrs
- Server filters out groups the visitor's scope can't reach BEFORE response
- Click any node → `hx-get="/api/svg/{layer_id}"` → server returns `<g>` fragment → `hx-swap="outerHTML"` replaces in place
- No client-side routing; the URL bar drives `hx-push-url`

**Files:**
- `studio/runtime/templates/index.html` (new, 20 lines)
- `crates/myspace-server/src/render.rs` (new, ~250 LOC)
- `MASTER-INFERENCE.svg` gains `gently:visibility` attrs per `<g>`

**Unlock:** landing / tools / admin / tesseract all on one page; no SPA framework needed.

### M5 — Auth gate integration (~100 LOC, fifth)

**Goal:** the existing `studio/auth/keys.sqlite` + `gate.py` become the rust chain's ACL surface.

- `gently-auth-gate` crate wraps `keys.sqlite` (sqlx)
- Salted key in URL bearer OR cookie OR HTTP header
- Key → scope → reachable nodes (read from `keys.sqlite`)
- Chain step records visit + scope + node_uid
- No login form needed — friend invites magic-link a salted key

**Files:**
- `crates/gently-auth-gate/Cargo.toml` (new)
- `crates/gently-auth-gate/src/lib.rs` (new, ~100 LOC, wraps `keys.sqlite`)
- `crates/myspace-server/src/main.rs` adds middleware

**Unlock:** zero-login auth working end-to-end on droplet; phishing surface = nil.

---

## Concrete next steps (this order)

1. **Read sister Claude's `studio/docs/LUCID_INTEGRATION.md`** (14KB, not yet opened) to align with their 4-layer plan.
2. **Read `studio/tesseract/inventory.py`** to see how the 253 nodes are sourced.
3. **Read `studio/lucid/standard_import.py`** to see what their Lucid export emits — confirm our droplet-side renderer can produce the same payload.
4. **Add `chain_hash` to walker.py contract** (M1, smallest first move).
5. **Scaffold `crates/myspace-server/`** (M2).
6. **Wire `gently-probe` + `gently-inference-budget` into the server** (M3).
7. **Build the stacked HTMX renderer** (M4).
8. **Integrate `keys.sqlite`** (M5).

Once M1-M5 are done, MASTER-INFERENCE.svg becomes the operational scheduler. Tesseract.svg stays as the inventory. The rust chain serves both via one HTTP binary.

---

## Risks + mitigations

| Risk | Mitigation |
|---|---|
| Walker contract divergence (Py vs Rust) | Shared schema in `Tesseract.svg <metadata>`; both impls read/write same XML. Cross-impl determinism test (like `cross_impl_determinism.rs` from the runtime MVP). |
| Cookie crystal collision | Use BLAKE3 over `(visitor_ip, ua_class, path, chain_hash)` — 64-hex is enough entropy. |
| Visitor probe leaks PII | Probe never stores raw IP — only `ip_as_class` (CIDR /24 hash). |
| Stacked SVG file size grows | Lazy-load `<g>` fragments via hx-get; only above-fold groups inline. |
| Layer rotation starves a subsystem | `gently-inference-budget` tracks per-subsystem call count; rotation policy includes round-robin + budget weights. |
| Lucid pattern drift if Lucid changes their SDK | We froze the pattern in MASTER-INFERENCE.svg. If Lucid changes, we don't care — we never imported their runtime. |

---

## Status flag

- [x] MASTER-INFERENCE.svg created in MySpace++ root
- [x] GENTLY-TESSERACT.svg snapshot copied for reference
- [x] CONSOLIDATION.md written (this file)
- [ ] Sister Claude's `LUCID_INTEGRATION.md` read for full alignment
- [ ] M1-M5 implementation (per phase, gated by user approval)

**Awaiting:** Tom's review of MASTER-INFERENCE.svg + this proposal before any M1+ code is written.
