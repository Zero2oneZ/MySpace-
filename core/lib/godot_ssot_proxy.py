#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        godot_ssot_proxy
# role:        SIDECAR · GODOT_SCENE_SSoT_HTTP_PROXY
# tier:        L0
# substrate:   the bearer-gated HTTP face of the Godot scene state — external
#              callers (Replit-deployed apps, dApp, Meta Quest builds, Facebook
#              Instant Games) hit this sidecar; the sidecar mediates via the
#              existing cc_bridge.gd file queue + scene snapshot/lock files
# storage:     reads/writes ~/.cc/scene_state, ~/.cc/scene_locks,
#              ~/.cc/godot_bridge.jsonl, ~/.cc/sym_index.json,
#              ~/.cc/godot_bridge_outbound.jsonl, ~/.cc/conflict_log.jsonl
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.godot_ssot_proxy.active.json
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - External apps the operator sells (Replit-deployed, dApp, Quest, etc.)
#   - Godot apps after acquiring a freetier token via the callback flow
#   - cc godot-ssot smoke tests
# outbound:
#   - freetier_gate.verify_token (bearer middleware on every endpoint)
#   - inference_logger.log (every call: tier='ssot_api', model='godot_proxy')
# substrate touch:
#   - reads:  ~/.cc/scene_state/<scene_uid>.json (snapshot files written by Godot)
#             ~/.cc/sym_index.json (symbol index)
#             ~/.cc/inference_master_chain.jsonl (chain tail)
#             ~/.cc/task_queue.json (task list)
#             ~/.cc/godot_bridge_outbound.jsonl (outbound events for SSE)
#   - writes: ~/.cc/godot_bridge.jsonl (commands; cc_bridge.gd polls this)
#             ~/.cc/scene_locks/<scene_uid>.lock (single-writer lock)
#             ~/.cc/sym_index.json (symbol writes)
#             ~/.cc/conflict_log.jsonl (lock-steal traces)
# ----------------------------------------------------------------------------
# ENDPOINTS
# ----------------------------------------------------------------------------
# GET  /healthz                          public — service health
# GET  /scene/{scene_uid}/state          read snapshot file (bearer)
# POST /scene/{scene_uid}/command        single-writer-locked append (bearer)
# GET  /symbols                          read sym_index.json (bearer)
# POST /symbols                          write to sym_index.json (bearer)
# GET  /chain/recent?n=N                 tail master crystal chain (bearer)
# GET  /tasks                            read task_queue.json (bearer)
# GET  /events                           SSE tail of bridge_outbound.jsonl (bearer)
# ============================================================================
"""godot_ssot_proxy.py — bearer-gated HTTP sidecar for Godot scene state.

Runs on 127.0.0.1:8766. Caddy on the droplet fronts this for TLS. External
callers reach scene state + commands without ever touching Godot directly;
the sidecar mediates through the existing cc_bridge.gd file-queue protocol.

Single-writer lock semantics for POST /scene/{uid}/command:
  1. fcntl LOCK_EX | LOCK_NB on ~/.cc/scene_locks/{uid}.lock
  2. Write {writer_id, acquired_at, ttl_ms} into the lock
  3. Append cc_godot_bridge_v1 packet to ~/.cc/godot_bridge.jsonl
  4. Crystal anchor the command
  5. Release lock
  6. Return {ack, crystal, packet_id}

If LOCK_NB raises BlockingIOError:
  - Read existing lock
  - If now - acquired_at < ttl_ms → 409 Conflict
  - Else → steal lock + log ConflictTrace + anchor as tier='ssot_conflict'

Every endpoint emits an InferenceRecord (tier='ssot_api', source_file=caller).

Stdlib only. No FastAPI dep.

Run:
    python3 core/lib/godot_ssot_proxy.py serve --port 8766 --bind 127.0.0.1
"""
from __future__ import annotations

import fcntl
import json
import os
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse, parse_qs

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

# freetier_gate + inference_logger are the two existing substrates we wire to.
from freetier_gate import (  # type: ignore  # noqa: E402
    verify_token,
    extract_token_from_headers,
    TokenClaims,
)


# ---------------------------------------------------------------------------
# Filesystem layout
# ---------------------------------------------------------------------------

CC_HOME = Path(os.environ.get("CC_HOME", str(Path.home() / ".cc")))
SCENE_STATE_DIR = CC_HOME / "scene_state"
SCENE_LOCKS_DIR = CC_HOME / "scene_locks"
BRIDGE_PATH = CC_HOME / "godot_bridge.jsonl"
OUTBOUND_PATH = CC_HOME / "godot_bridge_outbound.jsonl"
SYM_INDEX_PATH = CC_HOME / "sym_index.json"
TASK_QUEUE_PATH = CC_HOME / "task_queue.json"
CONFLICT_LOG_PATH = CC_HOME / "conflict_log.jsonl"
MASTER_CHAIN_PATH = CC_HOME / "inference_master_chain.jsonl"

DEFAULT_LOCK_TTL_MS = 2000
SSE_POLL_INTERVAL = 0.5
SSE_HEARTBEAT_INTERVAL = 30.0
PROTOCOL = "cc_godot_bridge_v1"


def _ensure_dirs() -> None:
    for d in (CC_HOME, SCENE_STATE_DIR, SCENE_LOCKS_DIR):
        d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Crystal anchor (every API call)
# ---------------------------------------------------------------------------

def _anchor(tier: str, scope: str, source_action: str,
            user_id: str, domain: str, output_text: str = "",
            original_prompt: str = "", enhanced_prompt: str = "") -> str:
    """Crystal-anchor an SSoT API call. Returns crystal_id ('' on logger failure)."""
    try:
        from inference_logger import InferenceLogger  # type: ignore
        il = InferenceLogger()
        return il.log(
            original_prompt=original_prompt[:512] or source_action,
            enhanced_prompt=enhanced_prompt[:512] or f"godot_ssot_proxy {scope}",
            output_text=output_text[:1024],
            tier=tier,
            model="godot_proxy",
            scope=scope,
            source_action=source_action,
            source_file=f"caller={user_id}@{domain}",
            done_flag=True,
            rc=0,
        ) or ""
    except Exception as e:
        sys.stderr.write(f"warn: ssot crystal log failed: {type(e).__name__}: {e}\n")
        return ""


# ---------------------------------------------------------------------------
# Scene snapshot / lock helpers
# ---------------------------------------------------------------------------

def _read_scene_state(scene_uid: str) -> Dict[str, Any]:
    """Read scene snapshot file; empty {} if absent or unparseable."""
    path = SCENE_STATE_DIR / f"{scene_uid}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_lock(scene_uid: str) -> Dict[str, Any]:
    """Read existing lock file; empty {} if absent or unparseable."""
    path = SCENE_LOCKS_DIR / f"{scene_uid}.lock"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _append_conflict_trace(scene_uid: str, stolen_from: Dict[str, Any],
                            new_writer_id: str, reason: str) -> None:
    """Append a ConflictTrace record (lock stolen because prev was stale)."""
    CONFLICT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": int(time.time() * 1000),
        "scene_uid": scene_uid,
        "stolen_from": stolen_from,
        "new_writer_id": new_writer_id,
        "reason": reason,
    }
    with open(CONFLICT_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, separators=(",", ":")) + "\n")


def _acquire_lock_or_describe(scene_uid: str, writer_id: str,
                                ttl_ms: int = DEFAULT_LOCK_TTL_MS
                                ) -> Tuple[Optional[Any], Optional[Dict[str, Any]]]:
    """Try to acquire single-writer flock on the scene lock file.

    Returns (lock_fd, None) on success — caller must close fd when done.
    Returns (None, conflict_info) when held by a fresh writer; conflict_info is
        {"current_writer": ..., "acquired_at": ..., "retry_after_ms": ...}.
    Stale locks (past ttl_ms) are stolen here; a ConflictTrace is appended and
    a crystal anchor (tier='ssot_conflict') will be emitted by the caller.
    """
    _ensure_dirs()
    lock_path = SCENE_LOCKS_DIR / f"{scene_uid}.lock"
    # Open r+ if it exists (preserve existing JSON until we win), else create.
    # We always use a fresh fd per request to avoid cross-thread interference.
    fd = open(lock_path, "a+", encoding="utf-8")
    try:
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        existing = _read_lock(scene_uid)
        now_ms = int(time.time() * 1000)
        acquired = int(existing.get("acquired_at", 0))
        ttl = int(existing.get("ttl_ms", DEFAULT_LOCK_TTL_MS))
        age_ms = now_ms - acquired
        if age_ms < ttl:
            # Fresh — refuse
            fd.close()
            return None, {
                "current_writer": existing.get("writer_id", "unknown"),
                "acquired_at": acquired,
                "retry_after_ms": max(1, ttl - age_ms),
            }
        # Stale — steal. We could not flock because another writer's fd kept
        # the kernel-level lock, but the writer is gone or wedged. Force-write
        # our lock + log a ConflictTrace; caller will crystal-anchor.
        _append_conflict_trace(scene_uid, existing, writer_id,
                                reason=f"stale_lock_age_{age_ms}ms>ttl_{ttl}ms")
        # Try one more time to take the kernel lock — usually succeeds because
        # holder process has died; if not, we proceed without flock (last-resort
        # steal) and overwrite the lock file content.
        try:
            fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            # Lock-without-flock: best-effort. Note this is rare and only
            # happens if the prior holder process is still alive but past TTL.
            pass
    # We hold the lock (or have force-stolen). Stamp it.
    payload = {
        "writer_id": writer_id,
        "acquired_at": int(time.time() * 1000),
        "ttl_ms": ttl_ms,
    }
    fd.seek(0)
    fd.truncate()
    fd.write(json.dumps(payload, separators=(",", ":")))
    fd.flush()
    return fd, None


def _release_lock(fd: Any) -> None:
    if fd is None:
        return
    try:
        fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
    except Exception:
        pass
    try:
        fd.close()
    except Exception:
        pass


def _append_bridge_packet(packet: Dict[str, Any]) -> None:
    """Append one cc_godot_bridge_v1 packet line to the bridge file."""
    BRIDGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(BRIDGE_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(packet, separators=(",", ":")) + "\n")


def _build_packet(scene_uid: str, action: str, payload: Dict[str, Any],
                    writer_id: str, caller: TokenClaims) -> Dict[str, Any]:
    """Construct a cc_godot_bridge_v1 packet for cc_bridge.gd."""
    return {
        "protocol": PROTOCOL,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "agent_uuid": os.environ.get("CC_AGENT_UUID", "ssot_proxy"),
        "packet_id": str(uuid.uuid4()),
        "original": f"ssot_proxy.command scene={scene_uid} action={action}",
        "enhanced": f"writer_id={writer_id} caller={caller.user_id}@{caller.domain}",
        "route": {"tier": "ssot", "model": "godot_proxy", "scope": scene_uid},
        "tokens": 0,
        "complexity": 0.0,
        "godot_action": action,
        "chain_context": f"ssot_proxy::scene={scene_uid}::writer={writer_id}",
        "ssot": {
            "scene_uid": scene_uid,
            "writer_id": writer_id,
            "payload": payload,
            "caller": {
                "user_id": caller.user_id,
                "domain": caller.domain,
                "tier": caller.tier,
            },
        },
    }


# ---------------------------------------------------------------------------
# Chain / tasks / symbols helpers
# ---------------------------------------------------------------------------

def _tail_chain(n: int) -> list:
    """Tail last n lines from inference_master_chain.jsonl as parsed records."""
    if not MASTER_CHAIN_PATH.exists():
        return []
    try:
        # Small file in practice; full read is fine. Use deque for safety.
        from collections import deque
        with open(MASTER_CHAIN_PATH, "r", encoding="utf-8") as f:
            tail = deque(f, maxlen=max(1, n))
        out = []
        for line in tail:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
        return out
    except Exception:
        return []


def _read_task_queue() -> Any:
    if not TASK_QUEUE_PATH.exists():
        return {"tasks": []}
    try:
        return json.loads(TASK_QUEUE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"tasks": [], "error": "task_queue.json unparseable"}


def _read_sym_index() -> Any:
    if not SYM_INDEX_PATH.exists():
        return {"symbols": []}
    try:
        return json.loads(SYM_INDEX_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"symbols": [], "error": "sym_index.json unparseable"}


def _write_sym_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Merge a single symbol entry into sym_index.json. Returns updated index."""
    SYM_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    idx = _read_sym_index()
    if not isinstance(idx, dict):
        idx = {"symbols": []}
    symbols = idx.setdefault("symbols", [])
    if not isinstance(symbols, list):
        symbols = []
        idx["symbols"] = symbols
    # Replace existing entry with same name+kind, else append.
    name = entry.get("name", "")
    kind = entry.get("kind", "")
    replaced = False
    for i, s in enumerate(symbols):
        if isinstance(s, dict) and s.get("name") == name and s.get("kind") == kind:
            symbols[i] = entry
            replaced = True
            break
    if not replaced:
        symbols.append(entry)
    idx["updated_at"] = int(time.time())
    SYM_INDEX_PATH.write_text(
        json.dumps(idx, sort_keys=True, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return idx


# ---------------------------------------------------------------------------
# Chain render + program-event readers (for /chain/* endpoints below)
# ---------------------------------------------------------------------------

CHAIN_RENDERS_ROOT = Path(os.path.expanduser("~/.cc/chain_renders"))
PROGRAM_EVENTS_ROOT = Path(os.path.expanduser("~/.cc/program_events"))


def _list_recent_renders(n: int) -> list:
    """Walk ~/.cc/chain_renders/<crystal_short>/manifest.json and return the N
    most recent as a compact list (no large blobs)."""
    if not CHAIN_RENDERS_ROOT.exists():
        return []
    items = []
    for d in CHAIN_RENDERS_ROOT.iterdir():
        if not d.is_dir() or d.name.startswith("_"):
            continue
        manifest_path = d / "manifest.json"
        if not manifest_path.exists():
            continue
        try:
            m = json.loads(manifest_path.read_text())
        except Exception:
            continue
        ev = m.get("event_summary") or {}
        img = m.get("image") or {}
        vid = m.get("video") or {}
        items.append({
            "crystal_short": d.name,
            "ts": float(m.get("rendered_at") or 0),
            "category": ev.get("category", ""),
            "action": ev.get("action", ""),
            "chain": ev.get("chain", ""),
            "program_name": ev.get("program_name", ""),
            "program_id": ev.get("program_id", ""),
            "signature": ev.get("signature", "")[:32],
            "image_status": img.get("status", ""),
            "video_status": vid.get("status", ""),
            "prompt_short": (m.get("prompt") or "")[:160],
            "dim": m.get("dim") or {},
            "manifest_url": f"/chain/render/{d.name}/manifest",
            "image_url": f"/chain/render/{d.name}/image"
                if img.get("status") == "rendered" else "",
            "video_url": f"/chain/render/{d.name}/video"
                if vid.get("status") == "rendered" else "",
        })
    items.sort(key=lambda x: -x["ts"])
    return items[:n]


def _read_render_manifest(crystal_short: str) -> Optional[Dict[str, Any]]:
    p = CHAIN_RENDERS_ROOT / crystal_short / "manifest.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _render_asset_path(crystal_short: str, kind: str) -> Optional[Path]:
    """kind ∈ {'image', 'video'}. Returns path if file exists."""
    if kind == "image":
        p = CHAIN_RENDERS_ROOT / crystal_short / "image.png"
    elif kind == "video":
        p = CHAIN_RENDERS_ROOT / crystal_short / "video.mp4"
    else:
        return None
    return p if p.exists() else None


def _read_watchset() -> list:
    """Read the program_registry watchset (watch=true entries) for the Godot
    visualizer's category filters."""
    try:
        from program_registry import watchset as _ws  # type: ignore
        entries = _ws()
        return [{
            "chain": e.chain,
            "program_id": e.program_id,
            "short": e.short(),
            "name": e.name,
            "category": e.category,
            "verified_at": e.verified_at,
            "source_url": e.source_url,
        } for e in entries]
    except Exception:
        return []


def _tail_program_events(n: int, program_short: str = "",
                          category: str = "") -> list:
    """Newest-first window over ~/.cc/program_events/**/*.jsonl. Filters by
    program_short (matches the per-program dir name) and/or category."""
    if not PROGRAM_EVENTS_ROOT.exists():
        return []
    rows: list = []
    for jf in PROGRAM_EVENTS_ROOT.glob("**/*.jsonl"):
        if program_short and program_short not in jf.parts:
            continue
        try:
            with jf.open() as f:
                for ln in f:
                    ln = ln.strip()
                    if not ln:
                        continue
                    try:
                        ev = json.loads(ln)
                    except Exception:
                        continue
                    if category and ev.get("category", "") != category:
                        continue
                    rows.append(ev)
        except Exception:
            continue
    rows.sort(key=lambda r: -float(r.get("ts", 0)))
    return rows[:n]


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class GodotSSoTHandler(BaseHTTPRequestHandler):
    server_version = "MySpaceGodotSSoT/0.1"

    # ---- low-level send helpers ----

    def _send_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_binary(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "public, max-age=300")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _auth(self) -> Optional[TokenClaims]:
        token = extract_token_from_headers({
            "Authorization": self.headers.get("Authorization", ""),
            "X-Freetier-Token": self.headers.get("X-Freetier-Token", ""),
        })
        return verify_token(token) if token else None

    def _require_auth(self) -> Optional[TokenClaims]:
        claims = self._auth()
        if not claims:
            self._send_json(401, {
                "error": "missing or invalid bearer token",
                "hint": "obtain via callback URL on GentlyOS.io or trollz.fun",
            })
            return None
        return claims

    def _read_json_body(self) -> Optional[Dict[str, Any]]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        raw = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError as e:
            self._send_json(400, {"error": f"bad json: {e}"})
            return None
        if not isinstance(data, dict):
            self._send_json(400, {"error": "body must be a JSON object"})
            return None
        return data

    # ---- routing ----

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/healthz":
            self._send_json(200, {"ok": True, "service": "godot_ssot"})
            return

        # Everything below requires bearer
        claims = self._require_auth()
        if not claims:
            return

        # /scene/{scene_uid}/state
        if path.startswith("/scene/") and path.endswith("/state"):
            scene_uid = path[len("/scene/"):-len("/state")].strip("/")
            if not scene_uid or "/" in scene_uid:
                self._send_json(400, {"error": "invalid scene_uid"})
                return
            state = _read_scene_state(scene_uid)
            crystal = _anchor(
                tier="ssot_api", scope=f"ssot_scene_state",
                source_action=f"GET /scene/{scene_uid}/state",
                user_id=claims.user_id, domain=claims.domain,
                output_text=json.dumps({"scene_uid": scene_uid,
                                          "keys": list(state.keys())[:32]},
                                         separators=(",", ":")),
            )
            self._send_json(200, {"scene_uid": scene_uid, "state": state,
                                     "ssot": {"crystal": crystal}})
            return

        if path == "/symbols":
            idx = _read_sym_index()
            crystal = _anchor(
                tier="ssot_api", scope="ssot_symbols",
                source_action="GET /symbols",
                user_id=claims.user_id, domain=claims.domain,
                output_text=json.dumps({"symbol_count":
                                          len(idx.get("symbols", []))
                                          if isinstance(idx, dict) else 0},
                                         separators=(",", ":")),
            )
            self._send_json(200, {"symbols": idx, "ssot": {"crystal": crystal}})
            return

        if path == "/chain/recent":
            q = parse_qs(parsed.query or "")
            try:
                n = int(q.get("n", ["10"])[0])
            except (ValueError, IndexError):
                n = 10
            n = max(1, min(n, 200))
            records = _tail_chain(n)
            crystal = _anchor(
                tier="ssot_api", scope="ssot_chain_recent",
                source_action=f"GET /chain/recent?n={n}",
                user_id=claims.user_id, domain=claims.domain,
                output_text=f"returned {len(records)} records",
            )
            self._send_json(200, {"records": records,
                                     "count": len(records),
                                     "ssot": {"crystal": crystal}})
            return

        if path == "/tasks":
            tasks = _read_task_queue()
            crystal = _anchor(
                tier="ssot_api", scope="ssot_tasks",
                source_action="GET /tasks",
                user_id=claims.user_id, domain=claims.domain,
                output_text=json.dumps({"task_count":
                                          len(tasks.get("tasks", []))
                                          if isinstance(tasks, dict) else 0},
                                         separators=(",", ":")),
            )
            self._send_json(200, {"tasks": tasks, "ssot": {"crystal": crystal}})
            return

        if path == "/events":
            self._handle_sse(claims)
            return

        # ---- chain render endpoints ----------------------------------------

        if path == "/chain/renders/recent":
            q = parse_qs(parsed.query or "")
            try:
                n = int(q.get("n", ["20"])[0])
            except (ValueError, IndexError):
                n = 20
            n = max(1, min(n, 200))
            renders = _list_recent_renders(n)
            crystal = _anchor(
                tier="ssot_api", scope="ssot_chain_renders_recent",
                source_action=f"GET /chain/renders/recent?n={n}",
                user_id=claims.user_id, domain=claims.domain,
                output_text=f"returned {len(renders)} renders",
            )
            self._send_json(200, {"renders": renders, "count": len(renders),
                                     "ssot": {"crystal": crystal}})
            return

        if path.startswith("/chain/render/") and path.endswith("/manifest"):
            crystal_short = path[len("/chain/render/"):-len("/manifest")].strip("/")
            if not crystal_short or "/" in crystal_short or len(crystal_short) > 64:
                self._send_json(400, {"error": "invalid crystal_short"})
                return
            m = _read_render_manifest(crystal_short)
            if m is None:
                self._send_json(404, {"error": "manifest not found",
                                         "crystal_short": crystal_short})
                return
            crystal = _anchor(
                tier="ssot_api", scope="ssot_render_manifest",
                source_action=f"GET /chain/render/{crystal_short}/manifest",
                user_id=claims.user_id, domain=claims.domain,
                output_text=f"served manifest for {crystal_short}",
            )
            self._send_json(200, {"manifest": m,
                                     "ssot": {"crystal": crystal}})
            return

        if path.startswith("/chain/render/") and (path.endswith("/image")
                                                    or path.endswith("/video")):
            kind = "image" if path.endswith("/image") else "video"
            crystal_short = path[len("/chain/render/"):-len(f"/{kind}")].strip("/")
            if not crystal_short or "/" in crystal_short or len(crystal_short) > 64:
                self._send_json(400, {"error": "invalid crystal_short"})
                return
            p = _render_asset_path(crystal_short, kind)
            if p is None:
                self._send_json(404, {"error": f"{kind} not found",
                                         "crystal_short": crystal_short})
                return
            try:
                body = p.read_bytes()
            except Exception as exc:
                self._send_json(500, {"error": f"read failed: {exc!r}"})
                return
            _anchor(
                tier="ssot_api", scope=f"ssot_render_{kind}",
                source_action=f"GET /chain/render/{crystal_short}/{kind}",
                user_id=claims.user_id, domain=claims.domain,
                output_text=f"served {len(body)} bytes of {kind}",
            )
            ctype = "image/png" if kind == "image" else "video/mp4"
            self._send_binary(200, ctype, body)
            return

        if path == "/chain/programs/watchset":
            entries = _read_watchset()
            crystal = _anchor(
                tier="ssot_api", scope="ssot_programs_watchset",
                source_action="GET /chain/programs/watchset",
                user_id=claims.user_id, domain=claims.domain,
                output_text=f"returned {len(entries)} watch entries",
            )
            self._send_json(200, {"watchset": entries,
                                     "count": len(entries),
                                     "ssot": {"crystal": crystal}})
            return

        if path == "/chain/events/recent":
            q = parse_qs(parsed.query or "")
            try:
                n = int(q.get("n", ["50"])[0])
            except (ValueError, IndexError):
                n = 50
            n = max(1, min(n, 500))
            program_short = q.get("program", [""])[0][:32]
            category = q.get("category", [""])[0][:48]
            events = _tail_program_events(n, program_short=program_short,
                                            category=category)
            crystal = _anchor(
                tier="ssot_api", scope="ssot_chain_events_recent",
                source_action=f"GET /chain/events/recent?n={n}&program={program_short}",
                user_id=claims.user_id, domain=claims.domain,
                output_text=f"returned {len(events)} events",
            )
            self._send_json(200, {"events": events, "count": len(events),
                                     "filter": {"program_short": program_short,
                                                  "category": category},
                                     "ssot": {"crystal": crystal}})
            return

        self._send_json(404, {"error": "not found", "path": path})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        claims = self._require_auth()
        if not claims:
            return

        # /scene/{scene_uid}/command
        if path.startswith("/scene/") and path.endswith("/command"):
            scene_uid = path[len("/scene/"):-len("/command")].strip("/")
            if not scene_uid or "/" in scene_uid:
                self._send_json(400, {"error": "invalid scene_uid"})
                return
            body = self._read_json_body()
            if body is None:
                return
            action = (body.get("action") or "").strip()
            payload = body.get("payload") or {}
            writer_id = (body.get("writer_id") or claims.user_id or "anonymous").strip()
            if not action:
                self._send_json(400, {"error": "missing 'action' in body"})
                return
            if not isinstance(payload, dict):
                self._send_json(400, {"error": "'payload' must be a JSON object"})
                return

            fd, conflict = _acquire_lock_or_describe(scene_uid, writer_id)
            stolen = conflict is None and fd is not None and _was_steal_signaled(scene_uid)
            # `_was_steal_signaled` is best-effort — _acquire_lock returns the
            # same (fd, None) on both clean acquire and stale steal; we look at
            # the conflict log tail to know if we just stole.
            if conflict is not None:
                # Held by fresh writer — 409
                crystal = _anchor(
                    tier="ssot_api", scope="ssot_command_conflict",
                    source_action=f"POST /scene/{scene_uid}/command",
                    user_id=claims.user_id, domain=claims.domain,
                    output_text=json.dumps({"conflict": conflict},
                                              separators=(",", ":")),
                )
                self._send_json(409, {
                    "error": "lock_held",
                    "current_writer": conflict["current_writer"],
                    "retry_after_ms": conflict["retry_after_ms"],
                    "ssot": {"crystal": crystal},
                })
                return

            # We hold the lock. Build + append the bridge packet.
            try:
                packet = _build_packet(scene_uid, action, payload, writer_id, claims)
                _append_bridge_packet(packet)
                if stolen:
                    _anchor(
                        tier="ssot_conflict", scope="ssot_lock_steal",
                        source_action=f"POST /scene/{scene_uid}/command (stale_steal)",
                        user_id=claims.user_id, domain=claims.domain,
                        output_text=json.dumps({"scene_uid": scene_uid,
                                                  "new_writer_id": writer_id},
                                                 separators=(",", ":")),
                    )
                crystal = _anchor(
                    tier="ssot_api", scope="ssot_command",
                    source_action=f"POST /scene/{scene_uid}/command",
                    user_id=claims.user_id, domain=claims.domain,
                    output_text=json.dumps({
                        "scene_uid": scene_uid,
                        "action": action,
                        "writer_id": writer_id,
                        "packet_id": packet["packet_id"],
                    }, separators=(",", ":")),
                )
                self._send_json(200, {
                    "ack": True,
                    "crystal": crystal,
                    "packet_id": packet["packet_id"],
                    "scene_uid": scene_uid,
                    "stale_steal": bool(stolen),
                })
            finally:
                _release_lock(fd)
            return

        if path == "/symbols":
            body = self._read_json_body()
            if body is None:
                return
            name = (body.get("name") or "").strip()
            kind = (body.get("kind") or "").strip() or "symbol"
            meta = body.get("meta") or {}
            if not name:
                self._send_json(400, {"error": "missing 'name' in body"})
                return
            if not isinstance(meta, dict):
                self._send_json(400, {"error": "'meta' must be a JSON object"})
                return
            entry = {
                "name": name,
                "kind": kind,
                "meta": meta,
                "added_by": {
                    "user_id": claims.user_id,
                    "domain": claims.domain,
                    "tier": claims.tier,
                },
                "added_at": int(time.time()),
            }
            idx = _write_sym_entry(entry)
            crystal = _anchor(
                tier="ssot_api", scope="ssot_symbols_write",
                source_action="POST /symbols",
                user_id=claims.user_id, domain=claims.domain,
                output_text=json.dumps({"name": name, "kind": kind},
                                          separators=(",", ":")),
            )
            self._send_json(200, {
                "ack": True,
                "symbol_count": (len(idx.get("symbols", []))
                                   if isinstance(idx, dict) else 0),
                "ssot": {"crystal": crystal},
            })
            return

        self._send_json(404, {"error": "not found", "path": path})

    # ---- SSE handler ----

    def _handle_sse(self, claims: TokenClaims) -> None:
        """Server-Sent Events stream over godot_bridge_outbound.jsonl.

        Tails the file every SSE_POLL_INTERVAL seconds; emits one `data:` event
        per new line. Sends `: heartbeat` every SSE_HEARTBEAT_INTERVAL seconds
        to keep proxies / browsers awake.
        """
        # SSE response headers
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError):
            return

        # Anchor the subscription open
        _anchor(
            tier="ssot_api", scope="ssot_events_open",
            source_action="GET /events (SSE open)",
            user_id=claims.user_id, domain=claims.domain,
            output_text="sse_subscription_opened",
        )

        # Start from EOF — only emit NEW outbound events
        if OUTBOUND_PATH.exists():
            try:
                start_offset = OUTBOUND_PATH.stat().st_size
            except OSError:
                start_offset = 0
        else:
            start_offset = 0

        last_heartbeat = time.time()
        offset = start_offset

        try:
            while True:
                # New bytes on file?
                if OUTBOUND_PATH.exists():
                    try:
                        size = OUTBOUND_PATH.stat().st_size
                    except OSError:
                        size = offset
                    if size > offset:
                        try:
                            with open(OUTBOUND_PATH, "r", encoding="utf-8") as f:
                                f.seek(offset)
                                chunk = f.read(size - offset)
                                offset = size
                        except OSError:
                            chunk = ""
                        if chunk:
                            for line in chunk.splitlines():
                                line = line.strip()
                                if not line:
                                    continue
                                try:
                                    self.wfile.write(f"data: {line}\n\n".encode("utf-8"))
                                    self.wfile.flush()
                                except (BrokenPipeError, ConnectionResetError):
                                    return
                    elif size < offset:
                        # File was truncated/rotated — restart at EOF.
                        offset = size

                # Heartbeat
                now = time.time()
                if now - last_heartbeat >= SSE_HEARTBEAT_INTERVAL:
                    try:
                        self.wfile.write(b": heartbeat\n\n")
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    last_heartbeat = now

                time.sleep(SSE_POLL_INTERVAL)
        except Exception:
            return

    # ---- access log ----

    def log_message(self, format: str, *args) -> None:
        if os.environ.get("SSOT_LOG", "") == "quiet":
            return
        sys.stderr.write(f"{self.address_string()} {format % args}\n")


# Best-effort steal detector: looks at conflict_log.jsonl tail and matches
# the most recent entry's timestamp to within a small window.
def _was_steal_signaled(scene_uid: str, window_ms: int = 1500) -> bool:
    if not CONFLICT_LOG_PATH.exists():
        return False
    try:
        # Read just the tail line cheaply (small file).
        last = ""
        with open(CONFLICT_LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    last = line
        if not last:
            return False
        rec = json.loads(last)
        if rec.get("scene_uid") != scene_uid:
            return False
        age_ms = int(time.time() * 1000) - int(rec.get("ts", 0))
        return 0 <= age_ms <= window_ms
    except Exception:
        return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="godot_ssot_proxy — bearer-gated scene SSoT")
    sub = ap.add_subparsers(dest="cmd")

    p_serve = sub.add_parser("serve", help="start HTTP server")
    p_serve.add_argument("--port", type=int,
                          default=int(os.environ.get("SSOT_PORT", "8766")))
    p_serve.add_argument("--bind", default="127.0.0.1")

    args = ap.parse_args()

    if args.cmd == "serve":
        _ensure_dirs()
        sys.stderr.write(
            f"godot_ssot_proxy listening on {args.bind}:{args.port}\n"
            f"  GET  /healthz                       (public)\n"
            f"  GET  /scene/{{scene_uid}}/state       (bearer)\n"
            f"  POST /scene/{{scene_uid}}/command     (bearer; single-writer lock)\n"
            f"  GET  /symbols                       (bearer)\n"
            f"  POST /symbols                       (bearer)\n"
            f"  GET  /chain/recent?n=N              (bearer)\n"
            f"  GET  /tasks                         (bearer)\n"
            f"  GET  /events                        (bearer; SSE)\n"
        )
        srv = ThreadingHTTPServer((args.bind, args.port), GodotSSoTHandler)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            srv.server_close()
    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
