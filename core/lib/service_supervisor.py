#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        service_supervisor
# role:        ORCHESTRATION · BRING EVERYTHING UP (local services + connectors)
# tier:        L0
# substrate:   One command to start every local service and report the status
#              of every external connector (Sui · Stripe · TensorChain ·
#              Telegram · Discord · Facebook · Snapchat · X). Health-checks
#              before spawning so it is idempotent; never double-starts.
# storage:     logs → /tmp/mspc_<service>.log ; reads <repo>/.env for keys
# reuse:       third_party.manager.ThirdPartyManager (loaded-connector status)
# ----------------------------------------------------------------------------
"""service_supervisor — `cc up` / `cc up-status` / `cc down`.

Local services are HTTP servers we start + health-check. Connectors are the
external integrations whose readiness is determined by whether their keys are
present in .env. Nothing here is destructive: `up` only starts what is down,
`down` only stops the services it knows about.

CLI:
  python3 core/lib/service_supervisor.py up        [--dry-run] [--only a,b]
  python3 core/lib/service_supervisor.py status     [--json]
  python3 core/lib/service_supervisor.py down       [--only a,b]
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

REPO = Path(__file__).resolve().parents[2]
ENV_FILE = REPO / ".env"
PY = sys.executable or "python3"

# ── local services (start + health-check) ────────────────────────────────────
# argv is relative to REPO; port/healthz drive the readiness probe.
SERVICES: List[Dict] = [
    {"name": "dapp",        "argv": ["studio/dapp/server.py"],
     "env": {"MSPC_DAPP_PORT": "8520", "MSPC_DAPP_LOG": "quiet"},
     "port": 8520, "healthz": "/dapp/healthz",
     "note": "wallet-map + streams + dApp surface"},
    {"name": "model_api",   "argv": ["core/lib/model_api.py", "serve"],
     "port": 8521, "healthz": "/v1/healthz",
     "note": "unified gated model API"},
    {"name": "callback",    "argv": ["studio/endpoints/freetier_callback/server.py"],
     "env": {"FREETIER_PORT": "8540"},
     "port": 8540, "healthz": "/healthz",
     "note": "free-tier terms+token callback"},
    {"name": "mcp_bridge",  "argv": ["studio/mcp/replit-bridge/server.py"],
     "port": 8765, "healthz": "/health",
     "note": "social/MCP bridge (Godot SocialClient talks here)"},
    {"name": "godot_ssot",  "argv": ["core/lib/godot_ssot_proxy.py", "serve", "--port", "8766"],
     "port": 8766, "healthz": "/v1/health",
     "note": "Godot single-source-of-truth proxy"},
]

# ── external connectors: any non-empty key ⇒ configured/ready ─────────────────
CONNECTORS: Dict[str, Dict] = {
    "sui":         {"keys": ["SUI_WALLET"], "kind": "crypto"},
    "tensorchain": {"keys": ["TENSORCHAIN_RPC", "SUI_WALLET"], "kind": "crypto"},
    "stripe":      {"keys": ["STRIPE_SECRET_KEY"], "kind": "payments"},
    "telegram":    {"keys": ["TELEGRAM_BOT_TOKEN", "telegram_bot_token"], "kind": "social"},
    "discord":     {"keys": ["DISCORD_BOT_TOKEN"], "kind": "social"},
    "facebook":    {"keys": ["facebook_page_token", "FACEBOOK_ACCESS_TOKEN", "FACEBOOK_PAGE_TOKEN"], "kind": "social"},
    "snapchat":    {"keys": ["SNAPCHAT_CLIENT_ID", "SNAP_CLIENT_ID"], "kind": "social"},
    "twitter":     {"keys": ["X_API_KEY", "X_API_BEARER_TOKEN"], "kind": "social"},
}


# ── env ───────────────────────────────────────────────────────────────────────

def load_env() -> Dict[str, str]:
    env: Dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    # process env wins (lets you override without editing .env)
    merged = {**env, **{k: v for k, v in os.environ.items() if k in env or k.isupper()}}
    return merged


# ── probes ────────────────────────────────────────────────────────────────────

def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.6) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def is_up(svc: Dict) -> bool:
    port, hz = svc["port"], svc.get("healthz")
    if not _port_open(port):
        return False
    if not hz:
        return True
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{hz}", timeout=2) as r:
            return r.status < 500
    except urllib.error.HTTPError:
        return True  # responding (even 4xx) ⇒ listening
    except Exception:
        return _port_open(port)  # listening but healthz path may differ


def start_one(svc: Dict, base_env: Dict[str, str]) -> str:
    if is_up(svc):
        return "already-up"
    script = REPO / svc["argv"][0]
    if not script.exists():
        return f"missing:{svc['argv'][0]}"
    env = {**os.environ, **base_env, **svc.get("env", {})}
    log = open(f"/tmp/mspc_{svc['name']}.log", "ab")
    try:
        subprocess.Popen([PY, *svc["argv"]], cwd=str(REPO), env=env,
                         stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                         start_new_session=True)  # detach from cc's process group
    except Exception as e:
        return f"spawn-error:{e}"
    # wait briefly for health
    for _ in range(20):
        time.sleep(0.4)
        if is_up(svc):
            return "started"
    return "started-unhealthy"


def stop_one(svc: Dict) -> str:
    pat = svc["argv"][0]
    rc = subprocess.run(["pkill", "-f", pat], capture_output=True).returncode
    return "stopped" if rc == 0 else "not-running"


# ── connector status ──────────────────────────────────────────────────────────

def connector_status(env: Dict[str, str]) -> Dict[str, Dict]:
    out: Dict[str, Dict] = {}
    for name, spec in CONNECTORS.items():
        present = [k for k in spec["keys"] if (env.get(k) or "").strip()]
        out[name] = {
            "kind": spec["kind"],
            "configured": bool(present),
            "via_key": present[0] if present else "",
        }
    # best-effort: how many connector configs the ThirdPartyManager actually loaded
    try:
        sys.path.insert(0, str(REPO / "core" / "lib"))
        from third_party.manager import ThirdPartyManager  # type: ignore
        loaded = set(ThirdPartyManager().load_all().services())
        for name in out:
            out[name]["loaded"] = name in loaded
    except Exception:
        pass
    return out


# ── orchestration ──────────────────────────────────────────────────────────────

def _filter(only: Optional[str]) -> List[Dict]:
    if not only:
        return SERVICES
    want = {s.strip() for s in only.split(",")}
    return [s for s in SERVICES if s["name"] in want]


def cmd_up(dry_run: bool, only: Optional[str]) -> int:
    env = load_env()
    print(f"[up] repo={REPO}")
    for svc in _filter(only):
        if dry_run:
            state = "UP" if is_up(svc) else "down→would-start"
        else:
            state = start_one(svc, env)
        mark = "✓" if state in ("already-up", "started", "UP") else \
               ("…" if "would" in state else "✗")
        print(f"  {mark} {svc['name']:11s} :{svc['port']:<5} {state:18s} {svc['note']}")
    _print_connectors(env)
    return 0


def cmd_status(as_json: bool) -> int:
    env = load_env()
    svc_status = [{"name": s["name"], "port": s["port"], "up": is_up(s),
                   "note": s["note"]} for s in SERVICES]
    conns = connector_status(env)
    if as_json:
        print(json.dumps({"services": svc_status, "connectors": conns}, indent=2))
        return 0
    print("SERVICES")
    for s in svc_status:
        print(f"  {'✓ up  ' if s['up'] else '✗ down'} {s['name']:11s} :{s['port']:<5} {s['note']}")
    _print_connectors(env)
    return 0


def cmd_down(only: Optional[str]) -> int:
    for svc in _filter(only):
        print(f"  {svc['name']:11s} {stop_one(svc)}")
    return 0


def _print_connectors(env: Dict[str, str]) -> None:
    conns = connector_status(env)
    ready = [n for n, c in conns.items() if c["configured"]]
    miss = [n for n, c in conns.items() if not c["configured"]]
    print(f"CONNECTORS  ({len(ready)}/{len(conns)} configured)")
    for name, c in conns.items():
        mark = "✓" if c["configured"] else "·"
        loaded = " loaded" if c.get("loaded") else ""
        via = f" via {c['via_key']}" if c["configured"] else "  (no key in .env)"
        print(f"  {mark} {name:11s} [{c['kind']:8s}]{via}{loaded}")
    if miss:
        print(f"  → to enable {', '.join(miss)}: set their keys in {ENV_FILE}")


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv: List[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, args = argv[0], argv[1:]
    only = None
    for i, a in enumerate(args):
        if a == "--only" and i + 1 < len(args):
            only = args[i + 1]
    if cmd == "up":
        return cmd_up("--dry-run" in args, only)
    if cmd == "status":
        return cmd_status("--json" in args)
    if cmd == "down":
        return cmd_down(only)
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
