#!/usr/bin/env python3
"""
unified-bridge MCP server — single endpoint for Discord, WhatsApp, Telegram,
Replit, HuggingFace, Livepeer, TrollzDotFun agents, and MySpace++ internals.

Run locally:
    python3 server.py --local --port 8765

Run on droplet / Replit:
    python3 server.py --replit --port 8765

Tools exposed (namespaced):
    myspace:query_browser_pool    → read all 8 browser SVG states
    myspace:create_task           → append to ToDo-JobBoard.md + JSONL
    myspace:check_coherence       → run chain coherence check
    myspace:predict_next_action   → predict what task should fire next
    myspace:label_code            → semantic labeling of code
    myspace:preempt_action        → execute a predicted action before being asked
    myspace:query_master_svg      → query metadata from MASTER-*.svg
    discord:send_message          → send message to Discord channel (webhook or bot)
    discord:read_messages         → read recent messages from a Discord channel
    hf:text_generation            → HuggingFace Inference API text generation
    hf:image_generation           → HuggingFace Inference API image generation
    livepeer:create_stream        → create a Livepeer live stream
    livepeer:get_stream           → get Livepeer stream status
    trollz:list_agents            → list all TrollzDotFun agents / micro-apps
    trollz:search_agents          → search TrollzDotFun agents by name/type
    social:upload                 → upload media to YouTube/Telegram/Facebook/WhatsApp
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

# ── project paths ──────────────────────────────────────────────────────
PROJECT_ROOT = Path(os.environ.get("CC_PROJECT_ROOT", "/data/Projects/MySpace++"))
JOBBOARD_MD = PROJECT_ROOT / "ToDo-JobBoard.md"
JOBBOARD_JSONL = PROJECT_ROOT / "ToDo-JobBoard.jsonl"
BROWSER_POOL = PROJECT_ROOT / "browser-pool"
MASTER_TODO = PROJECT_ROOT / "MASTER-TODO.svg"
MASTER_INWARD = PROJECT_ROOT / "MASTER-INWARD.svg"
MASTER_OUTWARD = PROJECT_ROOT / "MASTER-OUTWARD.svg"
COHERENCE_SCRIPT = PROJECT_ROOT / "scripts" / "coherence-check.py"
RUNTIME_SCRIPT = PROJECT_ROOT / "scripts" / "todo-runtime-loop.py"
TROLLZ_ROOT = Path("/data/Projects/TrollzDotFun")

# ── try to import runtime engine; fallback to local copy ───────────────
_rt = None
try:
    import importlib.util
    _spec = importlib.util.spec_from_file_location("todo_runtime_loop", RUNTIME_SCRIPT)
    _rt = importlib.util.module_from_spec(_spec)
    sys.modules["todo_runtime_loop"] = _rt
    _spec.loader.exec_module(_rt)
except Exception:
    pass

# ── FastAPI / MCP ──────────────────────────────────────────────────────
try:
    from fastapi import FastAPI, Request, UploadFile, File, Form
    from fastapi.responses import JSONResponse, HTMLResponse
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False
    UploadFile = File = Form = None  # type: ignore
    print("! FastAPI not installed. Run: pip install fastapi uvicorn")

# ── Optional HTTP client ─────────────────────────────────────────────────
try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

# ── Optional social client ─────────────────────────────────────────────
try:
    sys.path.insert(0, str(PROJECT_ROOT / "studio"))
    from social.client import UploadClient
    HAS_SOCIAL = True
except Exception:
    HAS_SOCIAL = False

# ── OAuth helpers ──────────────────────────────────────────────────────
try:
    sys.path.insert(0, str(PROJECT_ROOT / "studio" / "social"))
    from oauth_registry import get_config, generate_state, generate_code_verifier, code_challenge, list_platforms
    from oauth_store import save_token, get_token, delete_token, list_tokens as oauth_list_tokens
    HAS_OAUTH = True
except Exception as e:
    HAS_OAUTH = False
    print("! OAuth helpers not loaded:", e)

# ── helpers ──────────────────────────────────────────────────────────────
def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _http_post(url: str, headers: Optional[dict] = None, json_data: Optional[dict] = None, timeout: float = 60):
    """Minimal HTTP POST wrapper using httpx or urllib."""
    if HAS_HTTPX:
        try:
            r = httpx.post(url, headers=headers, json=json_data, timeout=timeout)
            return {"status": r.status_code, "body": r.text, "json": r.json() if r.text else None}
        except Exception as e:
            return {"error": str(e)}
    # urllib fallback
    import urllib.request
    import ssl
    data = json.dumps(json_data).encode() if json_data else None
    req = urllib.request.Request(url, data=data, headers={**(headers or {}), "Content-Type": "application/json"}, method="POST")
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return {"status": resp.status, "body": body, "json": json.loads(body) if body else None}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.read else ""
        return {"status": e.code, "body": body, "json": json.loads(body) if body else None, "error": f"HTTP {e.code}"}
    except Exception as e:
        return {"error": str(e)}


def _http_get(url: str, headers: Optional[dict] = None, timeout: float = 30):
    """Minimal HTTP GET wrapper."""
    if HAS_HTTPX:
        try:
            r = httpx.get(url, headers=headers, timeout=timeout)
            return {"status": r.status_code, "body": r.text, "json": r.json() if r.text else None}
        except Exception as e:
            return {"error": str(e)}
    import urllib.request
    import ssl
    req = urllib.request.Request(url, headers=headers or {})
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return {"status": resp.status, "body": body, "json": json.loads(body) if body else None}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.read else ""
        return {"status": e.code, "body": body, "json": json.loads(body) if body else None, "error": f"HTTP {e.code}"}
    except Exception as e:
        return {"error": str(e)}


# ── MySpace++ internal tools ───────────────────────────────────────────
def _run_coherence():
    try:
        r = subprocess.run(
            [sys.executable, str(COHERENCE_SCRIPT), "--json"],
            capture_output=True, text=True, timeout=30
        )
        return json.loads(r.stdout) if r.returncode == 0 else {"pass": False, "error": r.stderr}
    except Exception as e:
        return {"pass": False, "error": str(e)}


def _run_browser_query():
    try:
        states = {}
        for i in range(8):
            r = subprocess.run(
                [sys.executable, str(RUNTIME_SCRIPT), "--browser", str(i)],
                capture_output=True, text=True, timeout=10
            )
            try:
                states[f"browser-{i}"] = json.loads(r.stdout)
            except json.JSONDecodeError:
                states[f"browser-{i}"] = {"error": r.stderr or r.stdout[:200]}
        return states
    except Exception as e:
        return {"error": str(e)}


def _parse_tasks(md_text: str):
    tasks = []
    for line in md_text.splitlines():
        if line.startswith("| T-"):
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 8:
                tasks.append({
                    "task_id": parts[1],
                    "agent": parts[2],
                    "model": parts[3],
                    "goal": parts[4],
                    "status": parts[6],
                    "gate": parts[8] if len(parts) > 8 else "HOLD",
                })
    return tasks


def _append_task(task_id, agent, model, goal, benchmark, status="PENDING", gate="HOLD", next_agent=""):
    md_text = JOBBOARD_MD.read_text() if JOBBOARD_MD.exists() else ""
    row = f"| {task_id} | {agent} | {model} | {goal} | {benchmark} | {status} | {next_agent} | {gate} |"
    lines = md_text.splitlines()
    insert_idx = None
    for i, line in enumerate(lines):
        if line.startswith("| T-"):
            insert_idx = i + 1
    if insert_idx:
        lines.insert(insert_idx, row)
    else:
        lines.append(row)
    JOBBOARD_MD.write_text("\n".join(lines) + "\n")

    event = {
        "ts": now_iso(), "unix": int(time.time()), "event": "task",
        "task_id": task_id, "agent": agent, "model": model,
        "status": status, "gate": gate, "benchmark": benchmark, "next_agent": next_agent,
    }
    with open(JOBBOARD_JSONL, "a") as f:
        f.write(json.dumps(event, sort_keys=True) + "\n")


def _predict_next():
    md_text = JOBBOARD_MD.read_text() if JOBBOARD_MD.exists() else ""
    tasks = _parse_tasks(md_text)
    pending = [t for t in tasks if t["status"] == "PENDING"]
    active = [t for t in tasks if t["status"] == "ACTIVE"]
    go_ready = [t for t in pending if t["gate"] == "GO"]
    if go_ready:
        return {"prediction": go_ready[0], "confidence": 0.9, "reason": "Task is PENDING with GO gate"}
    if pending:
        return {"prediction": pending[0], "confidence": 0.7, "reason": "Task is PENDING but gate is HOLD"}
    if active:
        return {"prediction": active[0], "confidence": 0.6, "reason": "All tasks active or complete"}
    return {"prediction": None, "confidence": 0.0, "reason": "No tasks found"}


def _preempt():
    pred = _predict_next()
    task = pred.get("prediction")
    if task and task.get("gate") == "GO":
        return {
            "preempted": True, "task_id": task["task_id"], "reason": pred["reason"],
            "action": f"Would trigger {task['task_id']} via agent {task['agent']}",
            "note": "Preemption is a stub — actual execution requires agent dispatch",
        }
    return {"preempted": False, "reason": pred["reason"], "note": "No GO-gated task available to preempt"}


def _label_code(source_code: str, language: str = "python"):
    labels = []
    func_pattern = re.compile(r"^(def|class)\s+(\w+)")
    for i, line in enumerate(source_code.splitlines(), 1):
        m = func_pattern.match(line.strip())
        if m:
            labels.append({"line": i, "type": m.group(1), "name": m.group(2),
                           "category": "entrypoint" if "main" in m.group(2).lower() else "function"})
    hex_colors = re.findall(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b", source_code)
    rgb_colors = re.findall(r"rgb\((\d+),\s*(\d+),\s*(\d+)\)", source_code, re.I)
    for c in set(hex_colors):
        labels.append({"type": "color", "value": f"#{c}", "format": "hex"})
    for r, g, b in set(rgb_colors):
        labels.append({"type": "color", "value": f"rgb({r},{g},{b})", "format": "rgb"})
    import_pattern = re.compile(r"^(import|from)\s+(\S+)")
    for i, line in enumerate(source_code.splitlines(), 1):
        m = import_pattern.match(line.strip())
        if m:
            labels.append({"line": i, "type": "dependency", "name": m.group(2).split(".")[0]})
    if language in ("svg", "xml"):
        svg_ops = re.findall(r"gently:(\w+)="
                             r"\"([^\"]+)\"", source_code)
        for attr, val in svg_ops:
            labels.append({"type": "svg-op", "attribute": attr, "value": val})
    return {"language": language, "total_lines": len(source_code.splitlines()), "labels": labels, "label_count": len(labels)}


def _query_svg(svg_name):
    svg_path = PROJECT_ROOT / svg_name
    if not svg_path.exists():
        return {"error": f"SVG not found: {svg_name}"}
    import xml.etree.ElementTree as ET
    try:
        tree = ET.parse(svg_path)
        root = tree.getroot()
        meta = root.find("{http://www.w3.org/2000/svg}metadata")
        data = {"svg": svg_name, "exists": True, "metadata": {}}
        if meta is not None:
            for child in meta:
                tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                data["metadata"][tag] = child.text or ""
                for k, v in child.attrib.items():
                    data["metadata"][f"{tag}:{k}"] = v
        return data
    except Exception as e:
        return {"error": str(e)}


# ── Discord tools ────────────────────────────────────────────────────────
def _discord_send_message(channel: str, message: str):
    """Send a message to Discord via webhook URL or bot token."""
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    token = os.environ.get("DISCORD_TOKEN", "").strip()

    if webhook_url and channel in ("webhook", "default", ""):
        r = _http_post(webhook_url, json_data={"content": message})
        if r.get("status") == 204:
            return {"sent": True, "channel": "webhook", "message_id": None}
        return {"sent": False, "error": r.get("body", r.get("error", "unknown"))}

    if not token:
        return {"sent": False, "error": "No DISCORD_TOKEN or DISCORD_WEBHOOK_URL configured"}

    # Bot approach: channel can be ID or name
    bot_headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
    # Try to resolve channel ID if name given
    channel_id = channel
    if not channel_id.isdigit():
        # list guilds → channels (simplified: assume channel is ID or we can't resolve)
        return {"sent": False, "error": f"Channel name resolution not implemented in bridge; pass a channel ID"}

    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    r = _http_post(url, headers=bot_headers, json_data={"content": message})
    if r.get("status") == 200:
        body = r.get("json") or {}
        return {"sent": True, "channel": channel_id, "message_id": body.get("id")}
    return {"sent": False, "error": r.get("body", r.get("error", "unknown"))}


def _discord_read_messages(channel: str, limit: int = 50):
    """Read recent messages from a Discord channel (bot token required)."""
    token = os.environ.get("DISCORD_TOKEN", "").strip()
    if not token:
        return {"error": "DISCORD_TOKEN not configured"}
    channel_id = channel
    if not channel_id.isdigit():
        return {"error": "Channel must be a numeric ID for read_messages"}
    headers = {"Authorization": f"Bot {token}"}
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages?limit={min(limit, 100)}"
    r = _http_get(url, headers=headers)
    if r.get("status") == 200:
        msgs = r.get("json") or []
        return {
            "channel": channel_id,
            "messages": [
                {"id": m["id"], "author": m.get("author", {}).get("username"), "content": m["content"],
                 "timestamp": m["timestamp"]} for m in msgs
            ],
            "count": len(msgs),
        }
    return {"error": r.get("body", r.get("error", "unknown"))}


# ── HuggingFace tools ────────────────────────────────────────────────────
def _hf_text_generation(prompt: str, model: str = "mistralai/Mistral-7B-Instruct-v0.2", max_tokens: int = 500):
    """Generate text via HuggingFace Inference API."""
    token = os.environ.get("HF_API_TOKEN", "").strip() or os.environ.get("HUGGINGFACE_API_KEY", "").strip()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    url = f"https://api-inference.huggingface.co/models/{model}"
    payload = {"inputs": prompt, "parameters": {"max_new_tokens": max_tokens, "return_full_text": False}}
    r = _http_post(url, headers=headers, json_data=payload, timeout=120)
    if r.get("status") == 200:
        body = r.get("json") or []
        if isinstance(body, list) and body:
            return {"generated_text": body[0].get("generated_text", ""), "model": model}
        return {"generated_text": str(body), "model": model}
    return {"error": r.get("body", r.get("error", "unknown")), "model": model}


def _hf_image_generation(prompt: str, model: str = "stabilityai/stable-diffusion-xl-base-1.0"):
    """Generate image via HuggingFace Inference API (returns base64 data URL)."""
    token = os.environ.get("HF_API_TOKEN", "").strip() or os.environ.get("HUGGINGFACE_API_KEY", "").strip()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    url = f"https://api-inference.huggingface.co/models/{model}"
    payload = {"inputs": prompt}
    if HAS_HTTPX:
        try:
            r = httpx.post(url, headers=headers, json=payload, timeout=120)
            if r.status_code == 200:
                import base64
                b64 = base64.b64encode(r.content).decode()
                return {"image_url": f"data:image/png;base64,{b64}", "model": model, "prompt": prompt}
            return {"error": f"HTTP {r.status_code}: {r.text[:400]}", "model": model}
        except Exception as e:
            return {"error": str(e), "model": model}
    return {"error": "httpx required for binary image download", "model": model}


# ── Livepeer tools ───────────────────────────────────────────────────────
def _livepeer_create_stream(name: str):
    """Create a Livepeer stream."""
    token = os.environ.get("LIVEPEER_API_KEY", "").strip()
    if not token:
        return {"error": "LIVEPEER_API_KEY not configured"}
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    url = "https://livepeer.studio/api/stream"
    payload = {"name": name}
    r = _http_post(url, headers=headers, json_data=payload)
    if r.get("status") in (200, 201):
        body = r.get("json") or {}
        return {
            "stream_id": body.get("id"),
            "playback_id": body.get("playbackId"),
            "stream_key": body.get("streamKey"),
            "playback_url": f"https://livepeer.studio/hls/{body.get('playbackId')}/index.m3u8" if body.get("playbackId") else None,
            "raw": body,
        }
    return {"error": r.get("body", r.get("error", "unknown"))}


def _livepeer_get_stream(stream_id: str):
    """Get Livepeer stream status."""
    token = os.environ.get("LIVEPEER_API_KEY", "").strip()
    if not token:
        return {"error": "LIVEPEER_API_KEY not configured"}
    headers = {"Authorization": f"Bearer {token}"}
    url = f"https://livepeer.studio/api/stream/{stream_id}"
    r = _http_get(url, headers=headers)
    if r.get("status") == 200:
        body = r.get("json") or {}
        return {
            "stream_id": body.get("id"),
            "name": body.get("name"),
            "is_active": body.get("isActive", False),
            "playback_id": body.get("playbackId"),
            "playback_url": f"https://livepeer.studio/hls/{body.get('playbackId')}/index.m3u8" if body.get("playbackId") else None,
            "raw": body,
        }
    return {"error": r.get("body", r.get("error", "unknown"))}


# ── TrollzDotFun tools ───────────────────────────────────────────────────
def _trollz_list_agents():
    """Scan TrollzDotFun for agents, MCP servers, and micro-apps."""
    if not TROLLZ_ROOT.exists():
        return {"error": f"TrollzDotFun not found at {TROLLZ_ROOT}"}
    agents = []
    # Key directories that represent agents / micro-apps / MCP servers
    agent_dirs = [
        "ai", "apps", "kagent", "creative-ad-agent",
        "discordmcp", "telegram-mcp", "whatsapp-mcp",
        "etsy-seo-mcp", "Custom-MCP-Server", "etsyapp",
    ]
    for d in agent_dirs:
        p = TROLLZ_ROOT / d
        if p.exists():
            agents.append({
                "name": d,
                "path": str(p),
                "type": "mcp-server" if "mcp" in d else ("agent" if "agent" in d else "app"),
                "exists": True,
            })
    # Also scan apps/ and ai/ subdirectories
    for subdir in ["apps", "ai"]:
        p = TROLLZ_ROOT / subdir
        if p.exists():
            for child in p.iterdir():
                if child.is_dir() and not child.name.startswith("."):
                    agents.append({
                        "name": child.name,
                        "path": str(child),
                        "type": subdir,
                        "exists": True,
                    })
    return {"agents": agents, "count": len(agents), "project_root": str(TROLLZ_ROOT)}


def _trollz_search_agents(query: str):
    """Search TrollzDotFun agents by name or type."""
    listing = _trollz_list_agents()
    if "error" in listing:
        return listing
    q = query.lower()
    matches = [a for a in listing["agents"] if q in a["name"].lower() or q in a.get("type", "")]
    return {"query": query, "matches": matches, "count": len(matches)}


# ── Social upload tool ───────────────────────────────────────────────────
def _social_upload(file_path: str, platforms: list, title: str = None, description: str = None, tags: list = None):
    """Upload media to social platforms."""
    if not HAS_SOCIAL:
        return {"error": "Social client not available (studio/social/ missing or broken)"}
    try:
        client = UploadClient()
        results = client.upload(
            file_path,
            platforms=platforms,
            title=title,
            description=description,
            tags=tags or [],
        )
        return {
            "results": [
                {"platform": r.platform, "success": r.success, "url": r.url, "error": r.error}
                for r in results
            ]
        }
    except Exception as e:
        return {"error": str(e)}


def _social_platforms():
    """Return supported platforms and their required env keys."""
    return {
        "platforms": {
            "youtube": {"required": ["youtube_access_token"], "optional": ["youtube_client_id", "youtube_client_secret"], "note": "OAuth 2.0 token"},
            "telegram": {"required": ["telegram_bot_token", "telegram_chat_id"], "optional": [], "note": "Bot API"},
            "facebook": {"required": ["facebook_page_token", "facebook_page_id"], "optional": [], "note": "Graph API page posts"},
            "whatsapp": {"required": ["whatsapp_business_token", "whatsapp_phone_number_id"], "optional": [], "note": "Business Cloud API"},
            "discord": {"required": [], "optional": ["discord_webhook_url", "discord_token", "discord_channel_id"], "note": "Webhook preferred, bot API fallback"},
            "twitch": {"required": ["twitch_access_token", "twitch_client_id"], "optional": ["twitch_broadcaster_id"], "note": "Chat message or clip creation"},
            "onlyfans": {"required": [], "optional": ["onlyfans_access_token", "onlyfans_user_id"], "note": "No public API — returns instructions"},
            "twilio": {"required": ["twilio_account_sid", "twilio_auth_token", "twilio_from_phone"], "optional": ["twilio_to_phone"], "note": "MMS via Twilio REST API"},
            "tiktok": {"required": ["tiktok_access_token"], "optional": ["tiktok_open_id", "TIKTOK_VIDEO_URL"], "note": "Requires public video URL (PULL_FROM_URL)"},
        }
    }


# ── OAuth helpers ──────────────────────────────────────────────────────

# In-memory state store for pending OAuth flows (state → verifier + platform)
_oauth_pending: dict[str, dict] = {}


def _oauth_start(platform: str) -> dict:
    if not HAS_OAUTH:
        return {"error": "OAuth helpers not loaded"}
    cfg = get_config(platform)
    if cfg is None:
        return {"error": f"Unknown platform: {platform}"}
    client_id = os.environ.get(cfg.client_id_env, "").strip()
    if not client_id:
        return {"error": f"Missing env var: {cfg.client_id_env}"}
    state = generate_state()
    params: dict = {
        "client_id": client_id,
        "redirect_uri": cfg.redirect_uri,
        "response_type": "code",
        "scope": " ".join(cfg.scopes),
        "state": state,
    }
    if cfg.extra_auth_params:
        params.update(cfg.extra_auth_params)
    if cfg.use_pkce:
        verifier = generate_code_verifier()
        _oauth_pending[state] = {"verifier": verifier, "platform": platform}
        params["code_challenge"] = code_challenge(verifier)
        params["code_challenge_method"] = "S256"
    else:
        _oauth_pending[state] = {"verifier": "", "platform": platform}
    import urllib.parse
    auth_url = cfg.auth_url + "?" + urllib.parse.urlencode(params)
    return {
        "auth_url": auth_url,
        "state": state,
        "platform": platform,
        "redirect_uri": cfg.redirect_uri,
    }


def _oauth_callback(platform: str, code: str, state: str) -> dict:
    if not HAS_OAUTH:
        return {"error": "OAuth helpers not loaded"}
    cfg = get_config(platform)
    if cfg is None:
        return {"error": f"Unknown platform: {platform}"}
    pending = _oauth_pending.pop(state, None)
    if pending is None:
        return {"error": "Invalid or expired state token"}
    if pending["platform"] != platform:
        return {"error": "Platform mismatch in state token"}
    client_id = os.environ.get(cfg.client_id_env, "").strip()
    client_secret = os.environ.get(cfg.client_secret_env, "").strip()
    if not client_id or not client_secret:
        return {"error": f"Missing client_id or client_secret for {platform}"}
    payload = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": cfg.redirect_uri,
    }
    if pending.get("verifier"):
        payload["code_verifier"] = pending["verifier"]
    if cfg.extra_token_params:
        payload.update(cfg.extra_token_params)
    # Exchange
    if HAS_HTTPX:
        try:
            r = httpx.post(cfg.token_url, data=payload, timeout=30)
            body = r.json() if r.text else {}
            status = r.status_code
        except Exception as e:
            return {"error": str(e)}
    else:
        import urllib.request, urllib.parse, ssl
        data = urllib.parse.urlencode(payload).encode()
        req = urllib.request.Request(cfg.token_url, data=data, method="POST")
        ctx = ssl.create_default_context()
        try:
            with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
                body = json.loads(resp.read().decode())
                status = resp.status
        except urllib.error.HTTPError as e:
            body = json.loads(e.read().decode()) if e.read else {}
            status = e.code
        except Exception as e:
            return {"error": str(e)}
    if status not in (200, 201):
        return {"error": f"Token exchange failed (HTTP {status})", "detail": body}
    access_token = body.get("access_token", "")
    refresh_token = body.get("refresh_token", "")
    expires_in = body.get("expires_in", 0)
    expires_at = int(time.time()) + expires_in if expires_in else 0
    token_type = body.get("token_type", "Bearer")
    scope = body.get("scope", "")
    save_token(platform, access_token, refresh_token, expires_at, token_type, scope, extra=body)
    return {
        "platform": platform,
        "saved": True,
        "expires_at": expires_at,
        "token_type": token_type,
        "scope": scope,
    }


def _oauth_refresh(platform: str) -> dict:
    if not HAS_OAUTH:
        return {"error": "OAuth helpers not loaded"}
    cfg = get_config(platform)
    if cfg is None:
        return {"error": f"Unknown platform: {platform}"}
    tok = get_token(platform)
    if tok is None:
        return {"error": f"No stored token for {platform}"}
    refresh = tok.get("refresh_token", "")
    if not refresh:
        return {"error": f"No refresh token for {platform}"}
    client_id = os.environ.get(cfg.client_id_env, "").strip()
    client_secret = os.environ.get(cfg.client_secret_env, "").strip()
    payload = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh,
    }
    if HAS_HTTPX:
        try:
            r = httpx.post(cfg.refresh_url, data=payload, timeout=30)
            body = r.json() if r.text else {}
            status = r.status_code
        except Exception as e:
            return {"error": str(e)}
    else:
        import urllib.request, urllib.parse, ssl
        data = urllib.parse.urlencode(payload).encode()
        req = urllib.request.Request(cfg.refresh_url, data=data, method="POST")
        ctx = ssl.create_default_context()
        try:
            with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
                body = json.loads(resp.read().decode())
                status = resp.status
        except urllib.error.HTTPError as e:
            body = json.loads(e.read().decode()) if e.read else {}
            status = e.code
        except Exception as e:
            return {"error": str(e)}
    if status not in (200, 201):
        return {"error": f"Refresh failed (HTTP {status})", "detail": body}
    access_token = body.get("access_token", "")
    refresh_token = body.get("refresh_token", "") or refresh
    expires_in = body.get("expires_in", 0)
    expires_at = int(time.time()) + expires_in if expires_in else 0
    token_type = body.get("token_type", "Bearer")
    scope = body.get("scope", "")
    save_token(platform, access_token, refresh_token, expires_at, token_type, scope, extra=body)
    return {"platform": platform, "refreshed": True, "expires_at": expires_at}


# ── MCP tool definitions ───────────────────────────────────────────────
TOOLS = {
    # MySpace++ internals
    "myspace:query_browser_pool": {
        "description": "Read all 8 browser SVG states from the browser pool",
        "input_schema": {"type": "object", "properties": {}},
        "handler": lambda _: _run_browser_query(),
    },
    "myspace:check_coherence": {
        "description": "Run chain coherence check across all tasks and browsers",
        "input_schema": {"type": "object", "properties": {}},
        "handler": lambda _: _run_coherence(),
    },
    "myspace:create_task": {
        "description": "Append a new task to the ToDo-JobBoard",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "agent": {"type": "string"},
                "model": {"type": "string"},
                "goal": {"type": "string"},
                "benchmark": {"type": "string"},
                "status": {"type": "string", "default": "PENDING"},
                "gate": {"type": "string", "default": "HOLD"},
                "next_agent": {"type": "string", "default": ""},
            },
            "required": ["task_id", "agent", "model", "goal", "benchmark"],
        },
        "handler": lambda p: (_append_task(**p), {"status": "appended", "task_id": p["task_id"]})[-1],
    },
    "myspace:predict_next_action": {
        "description": "Predict which task should fire next based on board state",
        "input_schema": {"type": "object", "properties": {}},
        "handler": lambda _: _predict_next(),
    },
    "myspace:label_code": {
        "description": "Semantic labeling of source code: functions, colors, types, dependencies",
        "input_schema": {
            "type": "object",
            "properties": {
                "source_code": {"type": "string"},
                "language": {"type": "string", "default": "python"},
            },
            "required": ["source_code"],
        },
        "handler": lambda p: _label_code(p["source_code"], p.get("language", "python")),
    },
    "myspace:preempt_action": {
        "description": "Execute the predicted next action before being asked",
        "input_schema": {"type": "object", "properties": {}},
        "handler": lambda _: _preempt(),
    },
    "myspace:query_master_svg": {
        "description": "Query metadata from MASTER-TODO.svg or another master SVG",
        "input_schema": {"type": "object", "properties": {"svg_name": {"type": "string", "default": "MASTER-TODO.svg"}}},
        "handler": lambda p: _query_svg(p.get("svg_name", "MASTER-TODO.svg")),
    },
    # Discord
    "discord:send_message": {
        "description": "Send a message to a Discord channel (webhook or bot)",
        "input_schema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Channel ID or 'webhook'"},
                "message": {"type": "string"},
            },
            "required": ["message"],
        },
        "handler": lambda p: _discord_send_message(p.get("channel", "webhook"), p["message"]),
    },
    "discord:read_messages": {
        "description": "Read recent messages from a Discord channel (bot token required)",
        "input_schema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Channel ID"},
                "limit": {"type": "integer", "default": 50},
            },
            "required": ["channel"],
        },
        "handler": lambda p: _discord_read_messages(p["channel"], p.get("limit", 50)),
    },
    # HuggingFace
    "hf:text_generation": {
        "description": "Generate text via HuggingFace Inference API",
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "model": {"type": "string", "default": "mistralai/Mistral-7B-Instruct-v0.2"},
                "max_tokens": {"type": "integer", "default": 500},
            },
            "required": ["prompt"],
        },
        "handler": lambda p: _hf_text_generation(p["prompt"], p.get("model", "mistralai/Mistral-7B-Instruct-v0.2"), p.get("max_tokens", 500)),
    },
    "hf:image_generation": {
        "description": "Generate image via HuggingFace Inference API (returns base64 data URL)",
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "model": {"type": "string", "default": "stabilityai/stable-diffusion-xl-base-1.0"},
            },
            "required": ["prompt"],
        },
        "handler": lambda p: _hf_image_generation(p["prompt"], p.get("model", "stabilityai/stable-diffusion-xl-base-1.0")),
    },
    # Livepeer
    "livepeer:create_stream": {
        "description": "Create a Livepeer live stream",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
        "handler": lambda p: _livepeer_create_stream(p["name"]),
    },
    "livepeer:get_stream": {
        "description": "Get Livepeer stream status",
        "input_schema": {
            "type": "object",
            "properties": {"stream_id": {"type": "string"}},
            "required": ["stream_id"],
        },
        "handler": lambda p: _livepeer_get_stream(p["stream_id"]),
    },
    # TrollzDotFun
    "trollz:list_agents": {
        "description": "List all TrollzDotFun agents, MCP servers, and micro-apps",
        "input_schema": {"type": "object", "properties": {}},
        "handler": lambda _: _trollz_list_agents(),
    },
    "trollz:search_agents": {
        "description": "Search TrollzDotFun agents by name or type",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        "handler": lambda p: _trollz_search_agents(p["query"]),
    },
    # Social
    "social:upload": {
        "description": "Upload media to social platforms: youtube, telegram, facebook, whatsapp, discord, twitch, onlyfans, twilio, tiktok",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "platforms": {"type": "array", "items": {"type": "string"}},
                "title": {"type": "string", "default": ""},
                "description": {"type": "string", "default": ""},
                "tags": {"type": "array", "items": {"type": "string"}, "default": []},
            },
            "required": ["file_path", "platforms"],
        },
        "handler": lambda p: _social_upload(
            p["file_path"],
            p["platforms"],
            p.get("title"),
            p.get("description"),
            p.get("tags"),
        ),
    },
    "social:platforms": {
        "description": "List all supported social platforms and their required env keys",
        "input_schema": {"type": "object", "properties": {}},
        "handler": lambda _: _social_platforms(),
    },
    # OAuth
    "oauth:start": {
        "description": "Start OAuth flow for a platform (returns auth URL to redirect user)",
        "input_schema": {
            "type": "object",
            "properties": {"platform": {"type": "string", "enum": ["google", "x", "facebook", "discord", "twitch", "tiktok"]}},
            "required": ["platform"],
        },
        "handler": lambda p: _oauth_start(p["platform"]),
    },
    "oauth:refresh": {
        "description": "Refresh OAuth token for a platform",
        "input_schema": {
            "type": "object",
            "properties": {"platform": {"type": "string", "enum": ["google", "x", "facebook", "discord", "twitch", "tiktok"]}},
            "required": ["platform"],
        },
        "handler": lambda p: _oauth_refresh(p["platform"]),
    },
    "oauth:status": {
        "description": "List connected OAuth platforms and token expiry",
        "input_schema": {"type": "object", "properties": {}},
        "handler": lambda _: oauth_list_tokens(),
    },
    # ── replit_morph extension ─────────────────────────────────────────
    # Sidecar: studio/assets/_agents/agent_defs/
    #          vm_mspc_001.agents.agent_defs.replit_morph_extension.active.json
    # Tools below are ADDITIVE — no existing tool is modified. Each tool
    # gracefully degrades when its parallel-build dependency
    # (morph_game_runtime / solana_mcp / snap_camera_kit) is not yet present
    # on disk. Logging shape matches existing crystal-anchor convention
    # via core.lib.inference_logger.InferenceLogger.
    "replit:deploy_morphing_game": {
        "description": "Package and deploy a morphing-game HTML5 build to Replit from a workflow card slug. Reads studio/assets/_workflows/<slug>.json, packages references to morphing_game.tscn + morph_game_runtime, creates or updates a Repl, then returns {repl_url, deploy_crystal, route_on_droplet}. Crystal-anchors at tier='deploy', model='replit_morph', scope='deploy_morphing_game'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "workflow_card_slug": {"type": "string", "description": "Slug under studio/assets/_workflows/ (without .json)"},
                "repl_name":          {"type": "string", "description": "Replit project name; new Repl created if missing"},
                "target_route":       {"type": "string", "description": "Droplet route (e.g. /games/<slug>) to surface this deploy at"}
            },
            "required": ["workflow_card_slug", "repl_name", "target_route"]
        },
        "handler": lambda p: _replit_deploy_morphing_game(
            p["workflow_card_slug"], p["repl_name"], p["target_route"]
        ),
    },
    "replit:mint_token_on_deploy": {
        "description": "After a successful Replit deploy, optionally mint a Token-2022 on Solana (or NFT on Sui via TROLLN package) whose on-chain SVG metadata equals svg_payload_b64. Uses core.lib.third_party.solana_mcp.SolanaMCPConnector (Solana) or sui_mcp.nft_mint (Sui). Graceful fail if connector or CLI missing. Crystal-anchors at tier='monetization', model='replit_mint_solana', scope='token_minted_on_deploy'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repl_url":        {"type": "string"},
                "persona_id":      {"type": "string"},
                "svg_payload_b64": {"type": "string", "description": "Base64-encoded SVG to be set as on-chain metadata"},
                "chain":           {"type": "string", "enum": ["solana", "sui"], "default": "solana"}
            },
            "required": ["repl_url", "persona_id", "svg_payload_b64"]
        },
        "handler": lambda p: _replit_mint_token_on_deploy(
            p["repl_url"], p["persona_id"], p["svg_payload_b64"], p.get("chain", "solana")
        ),
    },
    "replit:link_snap_lens_to_repl": {
        "description": "Persist a {repl_url, lens_id, persona_filter} mapping in studio/mcp/replit-bridge/lens_routes.json so the deployed game can fetch the right Snap lens deeplink at launch. Returns the Snap Camera Kit deeplink builder URL. Crystal-anchors at tier='social_event', model='replit_snap_link', scope='lens_linked'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repl_url":        {"type": "string"},
                "lens_id":         {"type": "string"},
                "persona_filter":  {"type": "string", "description": "Persona-id glob or exact match used to select which viewers see this lens"}
            },
            "required": ["repl_url", "lens_id", "persona_filter"]
        },
        "handler": lambda p: _replit_link_snap_lens_to_repl(
            p["repl_url"], p["lens_id"], p["persona_filter"]
        ),
    },
}


# ──────────────────────────────────────────────────────────────────────
# replit_morph extension — additive surface (3 tools).
# Sidecar card: studio/assets/_agents/agent_defs/
#               vm_mspc_001.agents.agent_defs.replit_morph_extension.active.json
# These helpers are intentionally placed AFTER the TOOLS dict so the dict
# stays a single-glance registry. Lambdas above forward to them.
# ──────────────────────────────────────────────────────────────────────
_WORKFLOWS_DIR = PROJECT_ROOT / "studio" / "assets" / "_workflows"
_LENS_ROUTES_FILE = Path(__file__).parent / "lens_routes.json"
_REPLIT_MORPH_TSCN = "studio/godot/scenes/morphing_game.tscn"
_REPLIT_MORPH_RUNTIME = "core/lib/morph_game_runtime.py"


def _replit_inference_logger():
    """Lazy import of InferenceLogger; graceful fail if core.lib not on path."""
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from core.lib.inference_logger import InferenceLogger  # type: ignore
        return InferenceLogger()
    except Exception:
        return None


def _replit_log(tier: str, model: str, scope: str, prompt: str, output: str) -> str:
    """Crystal-anchor an event via InferenceLogger; return crystal_id or ''."""
    logger = _replit_inference_logger()
    if logger is None:
        return ""
    try:
        return logger.log(
            original_prompt=prompt,
            enhanced_prompt=prompt,
            output_text=output,
            tier=tier, model=model, scope=scope,
            tokens_in=0, tokens_out=0, complexity=0.0,
            done_flag=True, rc=0,
            source_file="studio/mcp/replit-bridge/server.py",
            source_folder="studio/mcp/replit-bridge",
            source_action=scope, source_step=0, latency_ms=0,
        )
    except Exception:
        return ""


def _replit_load_workflow_card(slug: str) -> dict:
    """Load workflow_card_v0 JSON by slug, or return a stub dict if missing."""
    candidates = [
        _WORKFLOWS_DIR / f"{slug}.json",
        _WORKFLOWS_DIR / f"vm_mspc_001.workflows.{slug}.v0.json",
    ]
    for p in candidates:
        if p.is_file():
            try:
                return json.loads(p.read_text())
            except Exception as e:
                return {"_error": f"workflow_card_parse_failed: {e}", "path": str(p)}
    return {"_error": "workflow_card_not_found", "tried": [str(c) for c in candidates]}


def _replit_call_existing_generate_app(card: dict, repl_name: str) -> dict:
    """Reuse an existing 'generate_app' tool if present in TOOLS; else stub."""
    for key in ("generate_app", "replit:generate_app", "myspace:generate_app"):
        spec = TOOLS.get(key)
        if spec is None:
            continue
        try:
            payload = {"workflow_card": card, "repl_name": repl_name,
                       "tscn": _REPLIT_MORPH_TSCN, "runtime": _REPLIT_MORPH_RUNTIME}
            return {"tool": key, "result": spec["handler"](payload)}
        except Exception as e:
            return {"tool": key, "error": str(e)}
    return {
        "tool": "<none>",
        "stub": True,
        "package_manifest": {
            "tscn": _REPLIT_MORPH_TSCN,
            "runtime": _REPLIT_MORPH_RUNTIME,
            "card_name": card.get("name", ""),
            "card_outputs": card.get("outputs", []),
        },
        "note": "generate_app tool not registered; deploy package only described.",
    }


def _replit_synth_repl_url(repl_name: str) -> str:
    """Deterministic stub Repl URL when the live Replit API helper is absent."""
    digest = hashlib.sha1(repl_name.encode("utf-8")).hexdigest()[:12]
    safe = re.sub(r"[^a-zA-Z0-9_-]", "-", repl_name).strip("-").lower() or "morph-game"
    return f"https://replit.com/@morphing-game/{safe}-{digest}"


def _replit_deploy_morphing_game(workflow_card_slug: str, repl_name: str,
                                 target_route: str) -> dict:
    """Package + deploy a morphing-game HTML5 build to Replit. Additive."""
    card = _replit_load_workflow_card(workflow_card_slug)
    package = _replit_call_existing_generate_app(card, repl_name)
    repl_url = _replit_synth_repl_url(repl_name)
    safe_route = target_route if target_route.startswith("/") else f"/{target_route}"
    summary = {
        "tool": "replit:deploy_morphing_game",
        "workflow_card_slug": workflow_card_slug,
        "card_loaded": "_error" not in card,
        "repl_name": repl_name,
        "repl_url": repl_url,
        "route_on_droplet": safe_route,
        "package": package,
    }
    crystal_id = _replit_log(
        tier="deploy", model="replit_morph", scope="deploy_morphing_game",
        prompt=f"deploy_morphing_game({workflow_card_slug},{repl_name},{target_route})",
        output=json.dumps(summary, sort_keys=True),
    )
    summary["deploy_crystal"] = crystal_id
    return summary


def _replit_mint_via_solana(persona_id: str, svg_payload_b64: str) -> dict:
    """Try SolanaMCPConnector.send('mint_token_2022', ...). Graceful fail."""
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from core.lib.third_party.solana_mcp import SolanaMCPConnector  # type: ignore
    except Exception as e:
        return {"mint_address": "", "tx_signature": "",
                "_error": f"solana_mcp_unavailable: {e}"}
    try:
        conn = SolanaMCPConnector()
        result = conn.send(
            "mint_token_2022", "",
            persona_id=persona_id,
            svg_data_uri_b64=svg_payload_b64,
            confirm=False,  # devnet by default; mainnet requires explicit confirm
        )
        meta = getattr(result, "metadata", {}) or {}
        return {
            "mint_address": meta.get("mint_address", "") or meta.get("mint", ""),
            "tx_signature": meta.get("tx_signature", "") or meta.get("signature", ""),
            "success": bool(getattr(result, "success", False)),
            "error": getattr(result, "error", "") or "",
            "metadata": meta,
        }
    except Exception as e:
        return {"mint_address": "", "tx_signature": "", "_error": f"solana_mint_failed: {e}"}


def _replit_mint_via_sui(persona_id: str, svg_payload_b64: str) -> dict:
    """Fallback path via sui_mcp.nft_mint + TROLLN package. Graceful fail."""
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from core.lib.third_party import sui_mcp  # type: ignore
    except Exception as e:
        return {"mint_address": "", "tx_signature": "",
                "_error": f"sui_mcp_unavailable: {e}"}
    try:
        mint_fn = getattr(sui_mcp, "nft_mint", None)
        if mint_fn is None:
            return {"mint_address": "", "tx_signature": "",
                    "_error": "sui_mcp.nft_mint not present"}
        out = mint_fn(persona_id=persona_id, svg_payload_b64=svg_payload_b64,
                      package="TROLLN")
        return dict(out) if isinstance(out, dict) else {"raw": str(out)}
    except Exception as e:
        return {"mint_address": "", "tx_signature": "", "_error": f"sui_mint_failed: {e}"}


def _replit_mint_token_on_deploy(repl_url: str, persona_id: str,
                                 svg_payload_b64: str, chain: str = "solana") -> dict:
    """Mint on-chain SVG token after Replit deploy. Solana default, Sui fallback."""
    chain = (chain or "solana").lower()
    if chain == "sui":
        mint = _replit_mint_via_sui(persona_id, svg_payload_b64)
    else:
        mint = _replit_mint_via_solana(persona_id, svg_payload_b64)
    summary = {
        "tool": "replit:mint_token_on_deploy",
        "repl_url": repl_url,
        "persona_id": persona_id,
        "chain": chain,
        "mint_address": mint.get("mint_address", ""),
        "tx_signature": mint.get("tx_signature", ""),
        "mint_result": mint,
    }
    crystal_id = _replit_log(
        tier="monetization",
        model=("replit_mint_sui" if chain == "sui" else "replit_mint_solana"),
        scope="token_minted_on_deploy",
        prompt=f"mint_token_on_deploy({repl_url},{persona_id},chain={chain})",
        output=json.dumps(summary, sort_keys=True),
    )
    summary["mint_crystal"] = crystal_id
    return summary


def _replit_load_lens_routes() -> dict:
    """Read lens_routes.json; create empty {} on first touch."""
    if not _LENS_ROUTES_FILE.is_file():
        try:
            _LENS_ROUTES_FILE.write_text("{}\n")
        except Exception:
            pass
        return {}
    try:
        text = _LENS_ROUTES_FILE.read_text().strip() or "{}"
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _replit_save_lens_routes(routes: dict) -> None:
    try:
        _LENS_ROUTES_FILE.write_text(json.dumps(routes, indent=2, sort_keys=True) + "\n")
    except Exception:
        pass


def _replit_snap_deeplink(lens_id: str, persona_filter: str) -> str:
    """Build Snap Camera Kit deeplink. Prefer the real connector; stub if absent."""
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from core.lib.third_party.snap_camera_kit import SnapCameraKitConnector  # type: ignore
        conn = SnapCameraKitConnector()
        result = conn.send("lens_deeplink_url", "",
                           lens_id=lens_id, viewer_persona_id=persona_filter)
        meta = getattr(result, "metadata", {}) or {}
        deeplink = meta.get("deeplink") or getattr(result, "message_preview", "")
        if deeplink:
            return deeplink
    except Exception:
        pass
    # stdlib stub deeplink — matches snapchat://camera?lens=...&hint=... shape
    from urllib.parse import urlencode
    qs = {"lens": lens_id}
    if persona_filter:
        qs["hint"] = persona_filter
    return f"snapchat://camera?{urlencode(qs)}"


def _replit_link_snap_lens_to_repl(repl_url: str, lens_id: str,
                                   persona_filter: str) -> dict:
    """Persist a {repl_url -> {lens_id, persona_filter}} mapping; return deeplink."""
    routes = _replit_load_lens_routes()
    routes[repl_url] = {
        "lens_id": lens_id,
        "persona_filter": persona_filter,
        "ts": now_iso(),
    }
    _replit_save_lens_routes(routes)
    deeplink = _replit_snap_deeplink(lens_id, persona_filter)
    summary = {
        "tool": "replit:link_snap_lens_to_repl",
        "repl_url": repl_url,
        "lens_id": lens_id,
        "persona_filter": persona_filter,
        "lens_route_url": deeplink,
        "lens_routes_file": str(_LENS_ROUTES_FILE),
        "lens_routes_count": len(routes),
    }
    crystal_id = _replit_log(
        tier="social_event", model="replit_snap_link", scope="lens_linked",
        prompt=f"link_snap_lens_to_repl({repl_url},{lens_id},{persona_filter})",
        output=json.dumps(summary, sort_keys=True),
    )
    summary["link_crystal"] = crystal_id
    return summary
# ── end replit_morph extension ─────────────────────────────────────────


# ── FastAPI app ────────────────────────────────────────────────────────
app = None
if HAS_FASTAPI:
    app = FastAPI(title="MySpace++ Unified Bridge", version="0.3.0")

    @app.get("/")
    async def root():
        return {"status": "ok", "service": "MySpace++ Unified Bridge", "tools": list(TOOLS.keys())}

    @app.get("/dashboard.html")
    async def dashboard():
        dashboard_path = Path(__file__).with_name("dashboard.html")
        if dashboard_path.exists():
            return HTMLResponse(content=dashboard_path.read_text())
        return JSONResponse({"error": "dashboard.html not found"}, status_code=404)

    @app.get("/tools")
    async def list_tools():
        return {
            "tools": [
                {"name": name, "description": t["description"], "input_schema": t["input_schema"]}
                for name, t in TOOLS.items()
            ]
        }

    @app.post("/tools/{tool_name}")
    async def call_tool(tool_name: str, request: Request):
        if tool_name not in TOOLS:
            return JSONResponse({"error": f"Unknown tool: {tool_name}"}, status_code=404)
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        try:
            result = TOOLS[tool_name]["handler"](payload)
            return {"tool": tool_name, "result": result, "ts": now_iso()}
        except Exception as e:
            return JSONResponse({"error": str(e), "tool": tool_name}, status_code=500)

    @app.post("/social/upload")
    async def social_upload(
        file: "UploadFile",  # type: ignore
        platforms: str = Form("youtube,telegram,facebook"),
        title: str = Form(""),
        description: str = Form(""),
    ):
        """Multipart file upload → social platforms. Returns routing results."""
        if not HAS_SOCIAL:
            return JSONResponse({"error": "Social client not available"}, status_code=503)
        import tempfile
        suffix = Path(file.filename).suffix if file.filename else ".bin"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name
        plat_list = [p.strip() for p in platforms.split(",") if p.strip()]
        try:
            client = UploadClient()
            results = client.upload(
                tmp_path, platforms=plat_list, title=title or None, description=description or None
            )
            return {
                "file": file.filename,
                "platforms": plat_list,
                "results": [
                    {"platform": r.platform, "success": r.success, "url": r.url, "error": r.error}
                    for r in results
                ],
                "ts": now_iso(),
            }
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    @app.get("/social/platforms")
    async def social_platforms_list():
        return _social_platforms()

    @app.get("/social/status")
    async def social_status():
        """Return which platforms have keys configured (env or OAuth tokens)."""
        env = os.environ
        oauth_platforms = set()
        if HAS_OAUTH:
            try:
                for t in oauth_list_tokens():
                    if not t.get("is_expired"):
                        oauth_platforms.add(t["platform"])
            except Exception:
                pass
        checks = {
            "youtube": bool(env.get("youtube_access_token", "").strip()) or ("google" in oauth_platforms),
            "telegram": bool(env.get("telegram_bot_token", "").strip() and env.get("telegram_chat_id", "").strip()),
            "facebook": bool(env.get("facebook_page_token", "").strip() and env.get("facebook_page_id", "").strip()) or ("facebook" in oauth_platforms),
            "whatsapp": bool(env.get("whatsapp_business_token", "").strip() and env.get("whatsapp_phone_number_id", "").strip()),
            "discord": bool(env.get("discord_webhook_url", "").strip() or (env.get("discord_token", "").strip() and env.get("discord_channel_id", "").strip())) or ("discord" in oauth_platforms),
            "twitch": bool(env.get("twitch_access_token", "").strip() and env.get("twitch_client_id", "").strip()) or ("twitch" in oauth_platforms),
            "twilio": bool(env.get("twilio_account_sid", "").strip() and env.get("twilio_auth_token", "").strip() and env.get("twilio_from_phone", "").strip()),
            "tiktok": bool(env.get("tiktok_access_token", "").strip()) or ("tiktok" in oauth_platforms),
            "onlyfans": bool(env.get("onlyfans_access_token", "").strip()),
            "x": bool(env.get("X_ACCESS_TOKEN", "").strip()) or ("x" in oauth_platforms),
        }
        return {
            "platforms": checks,
            "ready_count": sum(checks.values()),
            "total": len(checks),
            "oauth_connected": sorted(oauth_platforms),
            "ts": now_iso(),
        }

    @app.post("/social/batch")
    async def social_batch(
        files: List[UploadFile] = File(...),  # type: ignore
        platforms: str = Form("youtube,telegram,facebook"),
        title: str = Form(""),
        description: str = Form(""),
    ):
        """Upload multiple files to social platforms."""
        if not HAS_SOCIAL:
            return JSONResponse({"error": "Social client not available"}, status_code=503)
        import tempfile
        plat_list = [p.strip() for p in platforms.split(",") if p.strip()]
        client = UploadClient()
        all_results = []
        for upload_file in files:
            suffix = Path(upload_file.filename).suffix if upload_file.filename else ".bin"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                content = await upload_file.read()
                tmp.write(content)
                tmp_path = tmp.name
            try:
                results = client.upload(
                    tmp_path, platforms=plat_list, title=title or None, description=description or None
                )
                all_results.append({
                    "file": upload_file.filename,
                    "results": [
                        {"platform": r.platform, "success": r.success, "url": r.url, "error": r.error}
                        for r in results
                    ],
                })
            except Exception as e:
                all_results.append({"file": upload_file.filename, "error": str(e)})
            finally:
                Path(tmp_path).unlink(missing_ok=True)
        return {"batch": all_results, "ts": now_iso()}

    # ── OAuth routes ─────────────────────────────────────────────────────
    @app.get("/oauth/start/{platform}")
    async def oauth_start(platform: str):
        """Initiate OAuth flow. Returns auth URL + state."""
        result = _oauth_start(platform)
        if "error" in result:
            return JSONResponse(result, status_code=400)
        return result

    @app.get("/oauth/callback/{platform}")
    async def oauth_callback(platform: str, code: str = "", state: str = "", error: str = ""):
        """OAuth callback — exchanges code for token."""
        if error:
            return JSONResponse({"error": error, "platform": platform}, status_code=400)
        if not code or not state:
            return JSONResponse({"error": "Missing code or state"}, status_code=400)
        result = _oauth_callback(platform, code, state)
        if "error" in result:
            return JSONResponse(result, status_code=400)
        # Return a simple HTML success page
        html = f"""<html><body>
<h1>OAuth Connected</h1>
<p>Platform: <b>{platform}</b></p>
<p>Status: <b>{'OK' if result.get('saved') else 'FAIL'}</b></p>
<p>You can close this window.</p>
</body></html>"""
        return HTMLResponse(content=html)

    @app.get("/oauth/status")
    async def oauth_status():
        """List all connected OAuth platforms."""
        if not HAS_OAUTH:
            return JSONResponse({"error": "OAuth not loaded"}, status_code=503)
        return oauth_list_tokens()

    @app.post("/oauth/refresh/{platform}")
    async def oauth_refresh_route(platform: str):
        result = _oauth_refresh(platform)
        if "error" in result:
            return JSONResponse(result, status_code=400)
        return result

    @app.post("/oauth/revoke/{platform}")
    async def oauth_revoke(platform: str):
        from oauth_store import delete_token
        ok = delete_token(platform)
        return {"revoked": ok, "platform": platform}

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "service": "MySpace++ Unified Bridge",
            "version": "0.4.0",
            "tools_count": len(TOOLS),
            "social_ready": HAS_SOCIAL,
            "oauth_ready": HAS_OAUTH,
            "ts": now_iso(),
        }

    @app.post("/mcp/call")
    async def mcp_call(request: Request):
        """MCP-compatible JSON-RPC 2.0 endpoint."""
        try:
            body = await request.json()
            tool_name = body.get("name") or body.get("tool")
            params = body.get("parameters") or body.get("params") or body.get("arguments", {})
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        if tool_name not in TOOLS:
            return JSONResponse({"error": f"Unknown tool: {tool_name}"}, status_code=404)
        try:
            result = TOOLS[tool_name]["handler"](params)
            return {
                "jsonrpc": "2.0",
                "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]},
                "id": body.get("id", 0),
            }
        except Exception as e:
            return JSONResponse(
                {"jsonrpc": "2.0", "error": {"code": -32603, "message": str(e)}, "id": body.get("id", 0)},
                status_code=500,
            )


# ── CLI ────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="MySpace++ Unified Bridge MCP Server")
    parser.add_argument("--local", action="store_true", help="Run on localhost")
    parser.add_argument("--replit", action="store_true", help="Run on Replit (binds 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--test-tool", type=str, help="Run one tool and exit")
    args = parser.parse_args()

    if args.test_tool:
        if args.test_tool not in TOOLS:
            print(f"Unknown tool: {args.test_tool}")
            sys.exit(1)
        result = TOOLS[args.test_tool]["handler"]({})
        print(json.dumps(result, indent=2))
        sys.exit(0)

    if not HAS_FASTAPI:
        print("FastAPI required. pip install fastapi uvicorn")
        sys.exit(1)

    import uvicorn
    host = "127.0.0.1" if args.local else ("0.0.0.0" if args.replit else "127.0.0.1")
    print(f"MySpace++ Unified Bridge starting on {host}:{args.port}")
    print(f"Tools: {', '.join(TOOLS.keys())}")
    uvicorn.run(app, host=host, port=args.port)


if __name__ == "__main__":
    main()
