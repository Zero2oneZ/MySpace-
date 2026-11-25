# Droplet Hub Architecture · MySpace++ Multi-Service Deployment

**Owner**: Tom Lee (Zero2oneZ) | **IP Confidential**
**Droplet**: 159.89.181.146 (DigitalOcean) | **WireGuard**: z21 ↔ droplet
**Local GPU**: Dual RTX 3090 Ti (24 GB each) — GPU 1 preferred for inference

---

## What this deploy bundle ships

| Service | Port | Bind | Purpose | Status |
|---------|------|------|---------|--------|
| `mspc-callback` | 8540 | 127.0.0.1 | freetier callback — terms/policies/token issuance | ✅ existing |
| `mspc-model-api` | 8521 | 127.0.0.1 | proprietary unified model API | ✅ existing |
| `mspc-solana-feed` | 8522 | 127.0.0.1 | Pump.fun transaction feed + orchestration mapper | 🆕 NEW |
| `mspc-pattern-dashboard` | 8767 | 127.0.0.1 | Pattern Intelligence Dashboard (Tailwind + Chart.js) | 🆕 NEW |
| `mspc-mcp-host` | 8091 | 127.0.0.1 | MCP endpoint for web services + public tools | 🆕 NEW |
| `mspc-gpu-gateway` | 8523 | 127.0.0.1 | Tunnel authorized users to local GPU inference | 🆕 NEW |
| `mspc-hf-sync` | — | cron | Push feed data to HuggingFace Datasets + buckets | 🆕 NEW |
| `mspc-replit-sync` | — | cron | Data dump + scheduled code generation to Replit | 🆕 NEW |
| `mspc-ai-orchestrator` | 8524 | 127.0.0.1 | Ollama + Claude + cc centralized AI hub | 🆕 NEW |
| `mspc-smart-contract-gen` | 8526 | 127.0.0.1 | Web UI: generate Sui/Solana smart contracts + AI content | 🆕 NEW |

**Caddy reverse proxy** (`:80`/`:443`) routes by Host + Path to all loopback services.

---

## Port Map (complete)

| Port | Service | Access | Auth |
|------|---------|--------|------|
| 443 | Caddy TLS | public | — |
| 80 | Caddy ACME + redirect | public | — |
| 3100 | gently-watchdog-mcp | droplet only | internal |
| 8521 | mspc-model-api | loopback | Bearer token |
| 8522 | mspc-solana-feed | loopback | — |
| 8523 | mspc-gpu-gateway | loopback | SSH tunnel + friend-token |
| 8524 | mspc-ai-orchestrator | loopback | Bearer token |
| 8526 | mspc-smart-contract-gen | loopback | — |
| 8540 | mspc-callback | loopback | — |
| 8767 | mspc-pattern-dashboard | loopback | — |
| 8091 | mspc-mcp-host | loopback | Bearer token (tools) |

---

## Public Surface (Caddy)

### trollz.fun — product front
```
/terms/*              → 127.0.0.1:8540  (callback)
/v1/*                 → 127.0.0.1:8521  (model API)
/healthz             → 127.0.0.1:8540
/patterns/*           → 127.0.0.1:8767  (pattern dashboard)      🆕
/mcp/*               → 127.0.0.1:8091  (MCP host)              🆕
/tools/*             → 127.0.0.1:8526  (free public tools)     🆕
/generate/*          → 127.0.0.1:8526  (smart contract + AI gen) 🆕
/gpu/*               → 127.0.0.1:8523  (GPU gateway, token-gated) 🆕
/play/*              → /opt/mspc-public/games (static)
```

### GentlyOS.io — developer front
```
/endpoint/freetier/*  → 127.0.0.1:8540
/v1/*                 → 127.0.0.1:8521
/patterns/*           → 127.0.0.1:8767                         🆕
/mcp/*               → 127.0.0.1:8091                          🆕
/tools/*             → 127.0.0.1:8526                          🆕
/gpu/*               → 127.0.0.1:8523                          🆕
/healthz             → 127.0.0.1:8540
```

---

## Data Flow Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  LOCAL (z21 · Dual RTX 3090 Ti)                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                       │
│  │ pump_feed.py │  │ GPU trainer  │  │ Ollama +     │                       │
│  │ (live feed)  │  │ (PyTorch)    │  │ Claude API   │                       │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘                       │
│         │                 │                  │                              │
│         └─────────────────┴──────────────────┘                              │
│                           │                                                 │
│                    WireGuard tunnel                                         │
│                           │                                                 │
└───────────────────────────┼─────────────────────────────────────────────────┘
                            │
┌───────────────────────────┼─────────────────────────────────────────────────┐
│  DROPLET (159.89.181.146) │                                                  │
│                           ▼                                                  │
│  ┌────────────────────────────────────────────────────────────┐             │
│  │ Caddy (:443)                                               │             │
│  │  ├── /terms/*  → callback (:8540)                         │             │
│  │  ├── /v1/*     → model_api (:8521)                        │             │
│  │  ├── /patterns/* → dashboard (:8767)  🆕                  │             │
│  │  ├── /mcp/*    → mcp_host (:8091)    🆕                  │             │
│  │  ├── /tools/*  → smart_contract_gen (:8526)  🆕         │             │
│  │  ├── /gpu/*    → gpu_gateway (:8523)   🆕               │             │
│  │  └── /play/*   → static files                             │             │
│  └────────────────────────────────────────────────────────────┘             │
│                           │                                                  │
│  ┌────────────────────────┼────────────────────────┐                        │
│  │                        │                        │                        │
│  ▼                        ▼                        ▼                        │
│ ┌──────────┐    ┌──────────────┐    ┌──────────────────┐                  │
│ │Solana Feed│    │ Pattern      │    │ MCP Host         │                  │
│ │(:8522)   │───▶│ Dashboard    │    │ (:8091)          │                  │
│ │ (also    │    │ (:8767)      │    │  · tools expose  │                  │
│ │  hits    │    │  (reads      │    │  · stdio bridge  │                  │
│ │  RPC)    │    │   feed +     │    │  · HTTP SSE      │                  │
│ └──────────┘    │   model)     │    └──────────────────┘                  │
│                 └──────────────┘                                             │
│                           │                                                  │
│  ┌────────────────────────┼────────────────────────┐                        │
│  │                        │                        │                        │
│  ▼                        ▼                        ▼                        │
│ ┌──────────┐    ┌──────────────┐    ┌──────────────────┐                  │
│ │HF Sync   │    │ Replit Sync  │    │ AI Orchestrator  │                  │
│ │(cron)    │    │ (cron)       │    │ (:8524)          │                  │
│ │push to   │    │  · data dump  │    │  · Ollama proxy  │                  │
│ │datasets  │    │  · codegen   │    │  · Claude proxy  │                  │
│ └──────────┘    └──────────────┘    │  · cc dispatch   │                  │
│                                      └──────────────────┘                  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## GPU Gateway (special access)

The local GPU (RTX 3090 Ti) is NOT exposed directly. Instead:

1. Droplet runs `mspc-gpu-gateway` on `:8523`
2. Local machine maintains a WireGuard tunnel to the droplet
3. Local machine runs a `gpu_bridge.py` that:
   - Listens on the WireGuard interface for inference requests
   - Validates friend-token from the request
   - Runs inference on GPU 1
   - Returns results back through the tunnel
4. Caddy routes `/gpu/*` → `:8523` with Bearer token auth
5. Only friends with valid `keys.sqlite` tokens can access

**Security**: GPU never exposed to public internet. All traffic through WireGuard tunnel. Friend-token required.

---

## HuggingFace Data Sync

```python
# Runs as cron job on droplet every 6 hours
# 1. Reads latest feed data from SQLite
# 2. Formats as HuggingFace Dataset
# 3. Pushes to HF Hub via hugginface_hub
# 4. Also syncs to S3-compatible bucket (DO Spaces)
```

**Dataset**: `zero2onez/solana-pump-patterns`
- Columns: signature, slot, wallet, token, features[32], is_buy, is_sell, is_create, sol_delta, fee, meta_json
- Updated: every 6 hours
- License: CC-BY-SA 4.0 (public research)

---

## Replit Sync

```bash
# Runs as cron job on droplet every 24 hours
# 1. Dumps SQLite → JSONL
# 2. rsyncs to Replit project
# 3. Triggers Replit's scheduled workflow
# 4. Replit auto-codes based on data patterns
```

---

## Free Public Tools (traffic generation)

### `/tools/pattern-explorer`
- Input: Solana token address
- Output: Real-time pattern analysis (no ML — pure stats)
- Rate limit: 10 req/min per IP

### `/tools/token-risk-score`
- Input: token address + optional wallet
- Output: Bot activity score, rug pull probability, cluster detection
- Rate limit: 5 req/min per IP

### `/tools/smart-contract-generator`
- Input: natural language description
- Output: Sui Move or Solana Rust contract scaffold
- Rate limit: 3 req/min per IP

### `/generate/landing-page`
- Input: product description + style
- Output: HTML+HTMX landing page (AI-generated)
- Rate limit: 2 req/min per IP

---

## AI Orchestrator (centralized)

The droplet runs `mspc-ai-orchestrator` which is a thin proxy:

1. **Ollama**: Local models served through the droplet via WireGuard tunnel
2. **Claude**: Routes to Anthropic API with key rotation
3. **cc**: Runs `cc tiny` (qwen, free, local) or `cc claude` (Claude Code)

This gives the droplet a single AI endpoint that fans out to multiple backends.

---

## Deploy

```bash
cd /data/Projects/MySpace++/studio/deploy/droplet_hub/

# Dry-run first:
./deploy.sh

# Real deploy:
DRY_RUN=0 ./deploy.sh
```

---

## Files in this directory

| File | Purpose |
|------|---------|
| `ARCHITECTURE.md` | this file |
| `Caddyfile.droplet` | complete Caddy reverse-proxy config |
| `deploy.sh` | rsync + ssh deploy script |
| `mspc-solana-feed.service` | systemd unit for Solana feed |
| `mspc-pattern-dashboard.service` | systemd unit for dashboard |
| `mspc-mcp-host.service` | systemd unit for MCP host |
| `mspc-gpu-gateway.service` | systemd unit for GPU gateway |
| `mspc-ai-orchestrator.service` | systemd unit for AI hub |
| `mspc-smart-contract-gen.service` | systemd unit for contract generator |
| `mspc-hf-sync.timer` | systemd timer for HF sync |
| `mspc-replit-sync.timer` | systemd timer for Replit sync |
| `scripts/` | helper scripts (hf_sync.py, replit_sync.py, gpu_bridge.py) |
