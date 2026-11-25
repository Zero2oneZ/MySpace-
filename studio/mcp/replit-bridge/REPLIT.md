# Unified Bridge — Deployment Guide

> MySpace++ MCP server for multi-platform integration. Exposes browser pool, task board,
> coherence checks, code labeling, predictive actions, Discord, HuggingFace, Livepeer,
> TrollzDotFun agents, and social upload as tools through a single endpoint.

## What this gives you

- **MySpace++ internals** — 8 browser states, task board, coherence checks, SVG metadata, code labeling
- **Discord** — send messages (webhook or bot), read channel history
- **HuggingFace** — text generation, image generation via Inference API
- **Livepeer** — create live streams, get stream status
- **TrollzDotFun** — list/search all agents, MCP servers, and micro-apps
- **Social Upload** — upload media to YouTube, Telegram, Facebook, WhatsApp

## Deploy to Replit / Droplet / Local

### 1. Local development

```bash
# From /data/Projects/MySpace++/studio/mcp/replit-bridge/
nix-shell -p python313 python313Packages.fastapi python313Packages.uvicorn python313Packages.httpx

# Or if on a system with pip:
pip install -r requirements.txt

python3 server.py --local --port 8765
```

### 2. Run on droplet (idempotent deploy script)

```bash
bash /data/Projects/MySpace++/studio/mcp/replit-bridge/deploy-to-droplet.sh
```

This will:
- SSH to `root@159.89.181.146`
- Install python3 + pip + fastapi + uvicorn + httpx if missing
- Sync bridge files + data snapshot to `/opt/myspace-bridge/`
- Start/restart the bridge via pm2 on port 8765
- Smoke-test `http://159.89.181.146:8765/`

### 3. Run on Replit

Upload `server.py`, `requirements.txt`, `dashboard.html` to a Replit.

In Replit's Secrets panel, add:

```
CC_PROJECT_ROOT = /home/runner/myspace-bridge/data
REPLIT_MODE = true
```

In Replit's Shell:
```bash
pip install -r requirements.txt
python3 server.py --replit --port 8080
```

## Tools exposed

| Tool | Platform | What it does |
|------|----------|-------------|
| `myspace:query_browser_pool` | MySpace++ | Read all 8 browser SVG states |
| `myspace:check_coherence` | MySpace++ | Run chain coherence check |
| `myspace:create_task` | MySpace++ | Append task to board + JSONL |
| `myspace:predict_next_action` | MySpace++ | Predict next task to fire |
| `myspace:label_code` | MySpace++ | Tag functions, colors, deps in code |
| `myspace:preempt_action` | MySpace++ | Fire the next GO-gated task |
| `myspace:query_master_svg` | MySpace++ | Read metadata from any SVG |
| `discord:send_message` | Discord | Send message to channel (webhook or bot) |
| `discord:read_messages` | Discord | Read recent messages from channel |
| `hf:text_generation` | HuggingFace | Generate text from prompt |
| `hf:image_generation` | HuggingFace | Generate image from prompt (base64) |
| `livepeer:create_stream` | Livepeer | Create a live stream |
| `livepeer:get_stream` | Livepeer | Get stream status + playback URL |
| `trollz:list_agents` | TrollzDotFun | List all agents / MCP servers / micro-apps |
| `trollz:search_agents` | TrollzDotFun | Search agents by name or type |
| `social:upload` | Social | Upload media to YouTube/Telegram/Facebook/WhatsApp |

## MCP-compatible endpoint

Any MCP client (Replit, Claude Desktop, etc.) can call:

```
POST /mcp/call
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "hf:text_generation",
    "arguments": {
      "prompt": "Write a haiku about rust",
      "model": "mistralai/Mistral-7B-Instruct-v0.2"
    }
  },
  "id": 1
}
```

Response:
```json
{
  "jsonrpc": "2.0",
  "result": {
    "content": [
      {"type": "text", "text": "{\"generated_text\": \"...\"}"}
    ]
  },
  "id": 1
}
```

## Environment variables

| Var | Required for | Description |
|-----|-------------|-------------|
| `CC_PROJECT_ROOT` | MySpace++ tools | Path to project root (default: `/data/Projects/MySpace++`) |
| `DISCORD_WEBHOOK_URL` | discord:send_message | Discord webhook URL |
| `DISCORD_TOKEN` | discord:read_messages | Discord bot token |
| `HF_API_TOKEN` | hf:* | HuggingFace API token (optional for public models) |
| `LIVEPEER_API_KEY` | livepeer:* | Livepeer Studio API key |
| `youtube_access_token` | social:upload | YouTube OAuth token |
| `telegram_bot_token` | social:upload | Telegram Bot API token |
| `facebook_page_token` | social:upload | Facebook Graph API page token |
| `whatsapp_business_token` | social:upload | WhatsApp Business Cloud API token |

## The "before it happens" feature

The `myspace:predict_next_action` tool reads the task board, finds the first PENDING task with a GO gate, and returns it. The `myspace:preempt_action` tool goes one step further — it would actually trigger that task.

In a Replit workflow:
1. Agent calls `predict_next_action` every 30 seconds
2. If confidence > 0.8, agent calls `preempt_action`
3. Task fires automatically before the human asks for it

## Architecture

```
┌─────────────┐     HTTP/MCP      ┌──────────────────────────┐
│   Replit    │ ◄──────────────►  │  unified-bridge          │
│  (Browser)  │                   │  (FastAPI server)        │
└─────────────┘                   └──────────────────────────┘
                                          │
        ┌─────────────────────────────────┼─────────────────────────────────┐
        ▼                                 ▼                                 ▼
┌──────────────┐      ┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│ browser-pool │      │ ToDo-JobBoard│      │ MASTER-*.svg │      │  Platforms   │
│  8 SVG states│      │  .md + .jsonl│      │  metadata    │      │ Discord/HF/  │
└──────────────┘      └──────────────┘      └──────────────┘      │ Livepeer/    │
                                                                  │ Trollz/Social│
                                                                  └──────────────┘
```

## Security notes

- The bridge is read-only for most tools except `create_task`, `preempt_action`, `discord:send_message`, `social:upload`
- `create_task` appends only — never deletes or overwrites
- `preempt_action` is a stub by default — actual execution requires agent dispatch
- Bind to `127.0.0.1` locally; use `0.0.0.0` only on Replit or behind a reverse proxy
- For production: add API key auth (not implemented yet — see T-009 below)

## Future tasks

| ID | Task | Status |
|---|---|---|
| T-009 | Add API key auth to bridge | PENDING |
| T-010 | WebSocket push for real-time browser updates | PENDING |
| T-011 | Replit-side SVG renderer (convert browser states to HTML) | PENDING |
| T-012 | Bidirectional sync: Replit edits → local board | PENDING |
| T-013 | Add Telegram MCP proxy (import from TrollzDotFun telegram-mcp) | PENDING |
| T-014 | Add WhatsApp MCP proxy (import from TrollzDotFun whatsapp-mcp) | PENDING |

---

*MySpace++ Unified Bridge v0.2.0 | Built 2026-05-28*
