# WEAVE — cross-device compute fabric

> Companion to `TWINS-MASTER.{svg,md}` and `TESSERACT.md`. Where TWINS coordinates *sessions*
> and the Tesseract maps *static knowledge*, WEAVE coordinates **runtime compute** —
> distributing inference across every device that opens the master SVG.
>
> Single source of truth: `TWINS-MASTER.svg` (now 100K, 12 layers — three new ones are
> WEAVE's: topology, plans, queue).

---

## 1 · The thesis

Friends open a URL. Their browser tab probes WebGPU. They become a worker on Tom's compute network. No installs, no SSH keys, no Lucid account, no Docker image — just Chromium 113+ and a click.

Each tab declares its capabilities (vendor, architecture, memory, fallback flag). The TWINS-MASTER.svg shows the current roster. When a pass needs to run, the WEAVE router consults declarative **PLANS** (rules like *"HEAVY passes → owner GPU, fall back to droplet"*) and picks where to send it. Results flow back through the same WebSocket.

The whole thing is bound to the master SVG: every active device, every plan, every recent routing decision is a layer in the SVG. Any agent (Claude, codex, friend, Tom) reads the SVG and knows the current state.

---

## 2 · The model — three concrete tables

```
weave.sqlite        (lives in studio/cache/dag/weave.sqlite)
├── devices                 every node, online or offline
│     device_id PK · name · kind · owner · capabilities JSON
│     status (online|idle|busy|offline) · load_pct · free_mem_mb
│     first_seen · last_seen · user_agent · ip
├── webgpu_adapters         WebGPU adapter per device (1-N)
│     adapter_id PK · device_id FK · vendor · architecture
│     device_label · is_fallback · limits JSON · features
│     available_memory_mb · last_probed
├── plans                   the declarative routing rules
│     plan_id PK · name · description
│     condition JSON · action JSON · priority · active · fire_count
└── plan_evaluations        audit log of every routing decision
      eval_id PK · plan_id FK · ts · fired
      pass_id · file_kind · decision JSON
```

This is **fifth** in the studio's SQLite family — joining `keys.sqlite`, `pieces.sqlite`, `passes_timing.sqlite`, `tesseract_plan.sqlite`. All five are global-per-user (no per-project version).

---

## 3 · Device kinds

| Kind | Source | What it can run |
|---|---|---|
| `owner` | Tom's primary laptop | Heavy ML inference (24GB+ GPU); ground truth writer for everything |
| `droplet` | Linode / DigitalOcean / etc. | Lighter passes; orchestration; always-on relay; CPU-only fallback |
| `browser-tab` | Any Chromium 113+ tab opening `webgpu_worker.html` | LIGHT + MEDIUM passes via WebGPU/WebNN; perfect for fan-out |
| `friend` | A friend's laptop with the wardrobe app open | Same as browser-tab + identity bound to their salted token |
| `bot` | Headless agent (Claude / codex / a script) | Anything its host machine can do |

`browser-tab` is the magic kind. Anyone can become one by clicking a link.

---

## 4 · The PLANS DSL

PLANS are JSON dicts stored both as constants in `studio/weave/plans.py SEED_PLANS` and as rows in `weave.sqlite.plans` (user-editable). The condition is evaluated against a context built from the live topology + the pass spec being routed.

### Condition syntax

```json
{"all": [<cond>, <cond>, ...]}     // logical AND (empty = always true)
{"any": [<cond>, <cond>, ...]}     // logical OR
{"not": <cond>}                     // negation
{"<field>": "<value>"}              // equality
{"<field>": {"gt": 50}}             // gt | gte | lt | lte | ne | eq
{"<field>": {"in": ["a","b"]}}      // membership
{"<field>": {"contains": "x"}}      // substring (string or array)
```

### Available fields

```
pass.id                      "mask" | "depth" | …
pass.cost_class              "LIGHT" | "MEDIUM" | "HEAVY"
pass.import_time             bool
pass.file_kind               "jpg" | …
pass.file_bytes              int

topology.n_online            int
topology.n_idle              int
topology.n_busy              int
topology.n_browser_tabs      int
topology.has_owner           bool
topology.has_droplet         bool
topology.total_gpu_mem_mb    int

owner.load_pct               float
owner.free_mem_mb            int
owner.on_battery             bool (from capabilities.on_battery)
```

### Action syntax

```json
{"route_to": "owner" | "droplet" | "any-idle" | "least-loaded" | "browser-tab"}
{"defer": true}                          // push to a delayed queue
{"batch_with_others": 50}                // batch with up to N other jobs
{"fallback_to": "<device-kind>"}         // if primary route fails
```

### Seed plans (priority ASCending = higher priority)

| # | Priority | Plan | Action |
|---|---|---|---|
| p008 | 5 | If nothing is online → defer | `{"defer": true}` |
| p001 | 10 | HEAVY + owner online + owner.load<80 | `{route_to:"owner", fallback:"droplet"}` |
| p002 | 15 | HEAVY + owner saturated → droplet | `{route_to:"droplet"}` |
| p003 | 20 | LIGHT + ≥1 browser tab → batch on tabs | `{route_to:"browser-tab", batch_with_others:50, fallback:"owner"}` |
| p005 | 25 | lazy + owner on battery → defer | `{"defer": true}` |
| p004 | 30 | MEDIUM + ≥2 online → least-loaded | `{route_to:"least-loaded", fallback:"owner"}` |
| p006 | 40 | lazy + browser tabs available → tabs | `{route_to:"browser-tab"}` |
| p007 | 999 | catch-all → owner | `{route_to:"owner"}` |

First fired plan wins. Add overrides via `cc -weave-plans` (TODO) or directly via SQL.

---

## 5 · A concrete routing trace

```
$ cc -weave-seed                        # 4 devices + 8 plans seeded
$ cc -weave-route mask HEAVY --import-time
{
  "pass_id": "mask",
  "file_kind": "jpg",
  "device_id": "1f281d02b3f3",
  "device_name": "tom-laptop",
  "plan_id": "p001-heavy-to-owner",
  "action": {"route_to": "owner", "fallback_to": "droplet"},
  "deferred": false,
  "reason": "If the owner is online with a real GPU adapter, heavy passes go there."
}

$ cc -weave-route thumb LIGHT --import-time
{
  "device_name": "pete-tab",
  "plan_id": "p003-light-batch-tabs",
  "action": {"route_to": "browser-tab", "batch_with_others": 50, "fallback_to": "owner"},
  "reason": "Browser-tab workers can run many LIGHT passes in a single batch …"
}

$ cc -weave-jobs                        # the audit log
ts                     pass_id        ext   plan_id                    dev
2026-05-26T20:03:28Z   thumb          jpg   p003-light-batch-tabs      pete-tab
2026-05-26T20:03:28Z   mask           jpg   p001-heavy-to-owner        tom-laptop
2026-05-26T20:03:11Z   mask           jpg   p008-no-online-defer       (deferred)
```

The same decisions appear in **TWINS-MASTER.svg** layer 10 (WEAVE: queue) so any reader of the SVG sees current routing state.

---

## 6 · The browser worker (webgpu_worker.html)

Opens `webgpu_worker.html` in any Chromium 113+ tab. The page:

1. **Probes WebGPU** — `navigator.gpu.requestAdapter({ powerPreference: "high-performance" })`. Captures vendor, architecture, limits, features. Falls back to `isFallbackAdapter=true` if no real GPU.
2. **Opens a WebSocket** to `/worker/ws` on whatever origin served the page (the droplet's relay, typically `http://droplet:8540/`).
3. **Sends `register`** with: name, owner, capabilities, adapters. The relay creates a `devices` row + adapter rows + responds with `{type:"hello", device_id}`.
4. **Heartbeats every 15s** with status + load + free memory. The relay marks any device whose last_seen is > 120s old as `offline`.
5. **On `job` frames**, runs the work (today: stub sleep + canned result; future: transformers.js / WebGPU shader / WebNN). Posts `result` back.

The page is **8 KB of vanilla JS** with no build step. Open the HTML directly with a `file://` URL during development; in production serve it from `/` on the relay.

The contract is simple enough that other runtimes (mobile native shells, Electron, Deno servers) can implement it without modification.

---

## 7 · The WebSocket relay (weave_server.py)

FastAPI, runs on port 8540 (configurable via `PORT`):

```
GET   /              static webgpu_worker.html
GET   /health        relay + topology counts
GET   /devices       full topology.snapshot()
GET   /plans         active PLANS
POST  /route         body=PassSpec → routing decision (sync)
GET   /jobs          recent plan_evaluations
WS    /worker/ws     bidirectional worker channel
POST  /worker/push-job  push a routed job to its assigned device
```

On startup the relay seeds plans (idempotent) and starts a background loop that marks stale devices offline every 30s.

**Auth + signing are TODO.** Today the relay accepts any connection. Before exposing to public internet:
- Validate `X-Mspc-Token` (the salted-token registry from `auth/keys.py`) on every endpoint
- Sign job payloads with HMAC so workers can verify the relay is legit
- Use TLS termination at the front

---

## 8 · The Chromium WebGPU story (why this works)

Why Chromium? Three reasons:

1. **WebGPU is finally stable** in Chrome/Edge 113+. The API surface is consistent enough that one worker page works everywhere.
2. **WebNN** (Web Neural Network API) is shipping behind a flag in Chrome 121+. When it lands, our shim can call native model APIs directly — no transformers.js bundle needed.
3. **Wide reach**. Every friend already has Chromium installed. Mobile counts: Adreno GPUs on Android phones can run our LIGHT passes; iPad WebGPU exists too. Phones become workers.

The relay doesn't care which Chromium variant. Chrome, Edge, Brave, Arc, Vivaldi — all good. Safari is fine if your friend is on macOS — Safari's WebGPU shipped in Tech Preview 215.

---

## 9 · WebGPU work, today vs eventually

### Today (scaffolding)

`webgpu_worker.html` runs a **stub** job: sleep 200-600 ms, return `{stub: true}`. That's enough to exercise the routing + audit pipeline end-to-end without writing real WebGPU shaders.

### Eventually

Three concrete inference paths:

| Backend | What runs | Status |
|---|---|---|
| **transformers.js** | small models (CLIP, SAM, MiDaS, Florence2) | Most mature; npm-installable; works in CPU + WebGPU modes |
| **WebGPU shaders direct** | tiny custom ops (image resize, normal-map gen, color conversions) | Direct WGSL compute pipelines — fast, no model needed |
| **WebNN** | accelerated CV models via OS-level backend (DirectML / CoreML / TFLite) | Shipping behind flag; will replace transformers.js for simple ops |

Each gets wired into `runJob()` in the worker page based on the `pass_id`. For example: `pass_id="mask"` → `transformers.js SAM` model; `pass_id="thumb"` → vanilla canvas API resize.

---

## 10 · How it ties back to TWINS-MASTER

`TWINS-MASTER.svg` is the **single document** everyone reads. Three new layers render WEAVE state:

| Layer | What |
|---|---|
| **L8 weave-topology** | Every online device with kind/status/load/GPU. Updates whenever the SVG is rebuilt (`python3 studio/tesseract/twins.py`). |
| **L9 weave-plans** | All 8 PLANS with priority + condition + action + fire count. Reorder / disable via DB and re-render to update. |
| **L10 weave-queue** | The last 12 routing decisions from `plan_evaluations`. Acts as a live "what just happened" view. |

Because the SVG carries the manifest in `<metadata>`, any consumer (browser, Claude via MCP, Lucid via the data-connector path) sees the same picture. **No state divergence is possible** — the SVG is regenerated from the same SQLite tables that drive routing.

---

## 11 · CLI surface

```
cc -weave-seed              # seed 4 sample devices + 8 plans
cc -weave-status            # one-line totals (online / offline / idle / busy / GPU mem)
cc -weave-devices           # online devices with kind / status / load
cc -weave-plans             # active plans with priority + action + fire count
cc -weave-route <pass-id> [LIGHT|MEDIUM|HEAVY] [--import-time]
                            # decide where this pass would run + log it
cc -weave-jobs              # last 20 routing decisions (audit log)
cc -weave-reset             # drop devices table (fresh start for testing)
cc -weave-server-start      # boot the WebSocket relay on port 8540
```

Add `cc -weave-server-start` to your boot scripts on the droplet and the network is live.

---

## 12 · Security model (what's done, what's needed)

| Concern | Done | Needed |
|---|---|---|
| **Friends know who they are** | salted-token registry (`auth/keys.py`) | wire `X-Mspc-Token` into `/worker/ws` register frame |
| **Workers can't impersonate** | — | sign worker registration with friend's token |
| **Relay can't lie to workers** | — | sign job payloads with HMAC (master key from `.env`) |
| **No untrusted code execution** | worker page only runs pre-shipped shaders | TODO: signed model whitelist for transformers.js |
| **Network in transit** | — | TLS at the front (Caddy / nginx / Traefik in front of port 8540) |
| **Audit log** | every routing decision recorded in `plan_evaluations` | rotate / archive after N days |
| **Rate limiting** | `claude_proxy.py` rate-limits per token; same pattern needed for `/worker/ws` | port the rate limiter |

The worker page is **content-only** (no eval, no Function constructor, no untrusted imports). The only attack surface for friends → owner is the relay's `register` + `result` frames. Once those are token-validated + signed, the network is friend-safe.

---

## 13 · Deployment plan

### Local-only (today)

```bash
cc -weave-seed                       # seed
cc -weave-status                     # confirm
cc -weave-server-start               # port 8540
# open  http://localhost:8540/  in a browser tab → become a worker
```

### Droplet (the production target)

1. Add `weave` profile to `docker-compose.yml` (next to `studio-wardrobe`, `studio-dag`, etc.)
2. New `studio-weave` service runs `cc -weave-server-start` inside the studio Dockerfile
3. Expose port 8540 (or behind TLS)
4. Friends visit `https://droplet.tom/weave/` → become workers
5. The owner's box subscribes to the relay's WebSocket to hear about new workers; routes locally when the owner is offline

### Mobile-friendly

`webgpu_worker.html` is responsive. Friends with iPad Pro / Pixel 8 / Samsung S24 already have WebGPU. A friend opens the URL and their phone is now in the compute fabric. Phones provide LIGHT and MEDIUM passes — enough to spread thumb / hash / segmentation work across many devices.

---

## 14 · How it composes with prior work

WEAVE doesn't replace anything. It **layers on top** of:

| Layer | Role |
|---|---|
| `passes/` | What can run (the registry of 20 passes) |
| `pieces_index` | What's already been computed (dedup) |
| `timing` | How long things take (per-machine) |
| **`weave/`** | **Where to run it next (the routing layer)** |
| `tesseract/walker` | Verify what's been done (the audit) |

The 6-step inference loop from `NOTES-FOR-INFERANCE.md` gets a small refinement:

```
1. CHECK    pieces_index.search()                  ← already done?
2. PLAN     filetype_dag.plan_for(ext)             ← which passes?
3. ROUTE    weave.routing.decide(pass_spec)        ← NEW: where?
4. RUN      via routed device (local or remote)
5. RECORD   pieces_index.upsert()
6. WALK     tesseract.walker.identify()
7. SYNC     update TWINS-MASTER.svg
```

Step 3 is new. Steps 1, 2, 5, 6, 7 are unchanged.

---

## 15 · Files

```
studio/weave/
├── __init__.py                17 lines · package marker (lazy imports)
├── topology.py                250 lines · devices + adapters + heartbeat + offline TTL
├── plans.py                   285 lines · seed plans + condition DSL + evaluator
├── routing.py                 110 lines · decide() function
├── weave_server.py            160 lines · FastAPI WebSocket relay (port 8540)
└── webgpu_worker.html         195 lines · browser-side compute worker

studio/cache/dag/weave.sqlite   the runtime registry (4 tables)
studio/docs/WEAVE.md            this file
studio/docs/TWINS-MASTER.svg    now 100K with three WEAVE layers (L8/L9/L10)
```

---

## 16 · What's next

In rough order of payoff:

1. **Real inference paths** — wire `transformers.js` into `runJob()` for at least one pass (suggest: `mask` via SAM-Tiny).
2. **Token auth** — gate `/worker/ws` register frames behind `auth.keys.verify_token()`.
3. **Job push API** — wire `cc -passes-run` to call `weave.routing.decide()` + then `POST /worker/push-job`.
4. **Result harvesting** — when a worker reports a result, write the actual piece file + index entry. Today it only logs to `plan_evaluations`.
5. **TLS** — Caddy reverse-proxy in front for the public surface.
6. **Persistent queue** — today the queue is just the last-fired-plan audit. Add a real `jobs` table with status (queued/assigned/running/done/failed).
7. **Capability-aware routing** — let plans say `{require_feature: "shader-f16"}` and the router only picks devices that have it.
8. **Cost-aware routing** — use `passes/timing.sqlite` medians to predict job duration, schedule accordingly.

---

The SVG is the document. The SQLite is the truth. The relay is the courier. The browser is the worker. The PLANS decide. **No single piece is special — any of them can be replaced without breaking the rest.** That's the architectural win.
