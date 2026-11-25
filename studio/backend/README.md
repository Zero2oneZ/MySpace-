# Studio canvas backend — wiring the DAG editor to the real engine

This folds the react-flow canvas into `studio/` and replaces the mock
`runtime.run_step` with a real **dispatcher** that routes each node to the
infrastructure that already exists in this repo. Nothing about the engine is
new — the canvas just got plugged in. The only file the whole topology used to
stop at (`runtime.py:77 run_step()` mock) is now bypassed by `backend/dispatch.py`.

```
backend/
  node_map.py   node_id → {pass | role | connector}        ← the missing glue
  dispatch.py   the real run_step (passes / ai_orch / droplet), mode-switchable
  gpu_server.py z21 :8525 executor — wraps passes.inference; the box gpu_gateway tunnels to
  executor.py   graph runner: dispatch per node, synth-fallback, content-addressed artifacts
  app.py        FastAPI: /api/catalogue|recipes|flows, /api/run (SSE), /artifacts, static UI
  run-canvas.sh starts gpu_server + canvas on :8012
frontend/       the react-flow editor (moved in from models/dag_studio)
```

## Routing (what each node does today)

| Route | Nodes | Backend | State |
|---|---|---|---|
| **pass** | depth, mask, caption, keypoints, embedding, stems, speech_to_text, … (10 nodes) | `passes.inference.*` on the GPU box (`:8525`) | **real** — 20/33 passes bound; deps-missing ones report `PassUnavailable` |
| **llm** | M_GEMMA | `ai_orchestrator :8524` (ollama→claude) | real when `:8524` is up; else synth-fallback |
| **connector** | M_QIE, T_LTX, M_PX3D, … (12 gen nodes) | comfyui / blender (per `models/role_map.json`) | **pending** — connector not built yet → synth |
| **io / synth** | inputs, outputs, unmapped | — | passthrough / valid placeholder |

To light up a `pass` node fully, install its dep in the studio venv
(`LD_LIBRARY_PATH=/home/tom/miniconda3/lib .venv/bin/pip install rembg mediapipe …`)
and add a row to `node_map.NODE_PASS`.

**Generative `connector` nodes are now wired to gently** (the Rust half): the
`connector` branch in `dispatch.py` POSTs to `GENTLY_RENDER_URL` (the gently
`server/` `/api/studio/render`), which runs ComfyUI on the 3090s via the
`gently-comfy` crate and crystal-anchors each output. The 6 IMG nodes
(M_QIE/T_FIRE/T_FSWAP/T_KOLOR/T_QPOSE/T_QCAM) render real SD1.5 today; video/3D/
music return a "workflow pending" → synth-fallback until their ComfyUI templates
are authored in gently `server/src/comfy_render.rs`. Start gently:
`cd ~/Projects/gently && CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER=/run/current-system/sw/bin/gcc cargo run -p claude-terminal-server -- --port 7681` (ComfyUI must be up on :8188).

## Local vs the droplet (remote) topology — your chosen path

`dispatch.py` is env-switched so the *same code* serves dev and the public droplet:

```
STUDIO_BACKEND_MODE=local            # default: pass → http://127.0.0.1:8525 directly
STUDIO_BACKEND_MODE=remote           # pass → droplet gpu_gateway, Bearer MSPC_TOKEN
GPU_RUN_URL=https://<droplet>/gpu/run
AI_ORCH_URL=https://<droplet>/ai/
GENTLY_RENDER_URL=http://127.0.0.1:7681/api/studio/render   # gently ComfyUI render (connector nodes)
MSPC_TOKEN=mspc_client_…             # issued by auth/keys.py distribute_token()
```

Production path (matches `deploy/droplet_hub`):

```
friend browser ─▶ Caddy :443 ─▶ gpu_gateway :8523 ─(WireGuard)─▶ z21 :8525 (gpu_server.py)
                              └▶ ai_orchestrator :8524 ─▶ ollama / claude
                                    auth: auth/keys.py salted token (gpu_gateway validates Bearer)
```

To deploy: run `gpu_server.py` on z21 behind WireGuard at `:8525`, point the
droplet's `GPU_TUNNEL_PORT=8525`, add a Caddy route `/gpu/* → :8523`, and serve
this canvas with `STUDIO_BACKEND_MODE=remote`. The gpu_gateway's `validate_token`
is currently a length stub — swap it to call `auth.keys.verify_token()` before
exposing publicly.

## Run

```bash
./backend/run-canvas.sh        # → http://localhost:8012
```
