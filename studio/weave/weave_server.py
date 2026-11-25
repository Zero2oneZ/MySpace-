"""weave_server.py — FastAPI WebSocket relay for cross-device compute.

Runs on the droplet (or owner's box, if no droplet). Browser tabs open
webgpu_worker.html, connect to /worker/ws, register themselves as
devices, then accept routed jobs via the same socket.

Wire:
    GET   /              static webgpu_worker.html (served from this dir)
    GET   /health        relay health + counts
    WS    /worker/ws     bidirectional worker channel:
                         CLIENT → SERVER:  register / heartbeat / result
                         SERVER → CLIENT:  job / drain / hello
    GET   /devices       JSON of currently online devices (snapshot)
    GET   /plans         active PLANS
    POST  /route         body=PassSpec → returns RoutingDecision (sync)
    GET   /jobs          job queue summary

This is **scaffolding-grade** — single-process, no auth, no signing. Add
salted-token verification (auth.keys) before exposing to non-local
clients.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
STUDIO_ROOT = HERE.parent
sys.path.insert(0, str(STUDIO_ROOT))

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
    from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
except ImportError as e:
    raise ImportError(
        "weave_server needs fastapi + uvicorn — install with:\n"
        "    pip install fastapi 'uvicorn[standard]'"
    ) from e

import importlib
topology = importlib.import_module("weave.topology")
plans    = importlib.import_module("weave.plans")
routing  = importlib.import_module("weave.routing")


app = FastAPI(title="MySpace++ WEAVE relay",
              description="Cross-device compute fabric. Browser-tab "
                          "workers register here; routing decisions consult "
                          "the live topology + declarative PLANS.")


# ── In-memory channel registry ──────────────────────────────────────────────
# device_id → WebSocket (one socket per active worker)
ACTIVE: dict[str, WebSocket] = {}


# ── Static page ─────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def index():
    p = HERE / "webgpu_worker.html"
    if not p.exists():
        return HTMLResponse("<h1>webgpu_worker.html missing</h1>", status_code=500)
    return FileResponse(p, media_type="text/html")


# ── Health + admin endpoints ────────────────────────────────────────────────
@app.get("/health")
def health():
    return {
        "ok": True,
        "active_sockets": len(ACTIVE),
        "topology":       topology.snapshot()["totals"],
    }


@app.get("/devices")
def devices():
    return topology.snapshot()


@app.get("/plans")
def get_plans():
    return [p.to_dict() for p in plans.list_plans(active_only=True)]


@app.post("/route")
async def post_route(request: Request):
    spec = await request.json()
    decision = routing.decide(spec)
    return decision.to_dict()


@app.get("/jobs")
def jobs():
    # Reads from the same plan_evaluations table — the audit log doubles as
    # the recent-jobs view.
    import sqlite3
    db = sqlite3.connect(plans.DB_PATH)
    rows = db.execute(
        "SELECT ts, pass_id, file_kind, plan_id, decision FROM plan_evaluations "
        "ORDER BY eval_id DESC LIMIT 50"
    ).fetchall()
    db.close()
    out = []
    for ts, pid, fk, plan_id, decision in rows:
        try:
            d = json.loads(decision or "{}")
        except Exception:
            d = {}
        out.append({"ts": ts, "pass_id": pid, "file_kind": fk,
                    "plan_id": plan_id, "decision": d})
    return out


# ── Worker WebSocket ────────────────────────────────────────────────────────
@app.websocket("/worker/ws")
async def worker_ws(ws: WebSocket):
    await ws.accept()
    device_id: Optional[str] = None
    try:
        # Expect "register" message first.
        first = await ws.receive_json()
        if first.get("type") != "register":
            await ws.send_json({"type": "error",
                                "error": "first frame must be type=register"})
            await ws.close(); return
        body = first.get("body") or {}
        device_id = topology.register_device(
            name=body.get("name", "browser-tab"),
            kind="browser-tab",
            owner=body.get("owner"),
            capabilities=body.get("capabilities", {}),
            user_agent=body.get("user_agent", ""),
            ip=ws.client.host if ws.client else "",
        )
        # Save adapters if probe data included
        for ad in (body.get("adapters") or []):
            topology.register_adapter(
                device_id,
                vendor=ad.get("vendor", "unknown"),
                architecture=ad.get("architecture", "unknown"),
                device_label=ad.get("device_label", ""),
                is_fallback=bool(ad.get("is_fallback", False)),
                limits=ad.get("limits", {}),
                features=ad.get("features", []),
                available_memory_mb=ad.get("available_memory_mb"),
            )
        ACTIVE[device_id] = ws
        await ws.send_json({"type": "hello", "device_id": device_id,
                            "server_ts": _now()})

        # Loop: receive heartbeats / results.
        while True:
            msg = await ws.receive_json()
            mtype = msg.get("type")
            body = msg.get("body") or {}
            if mtype == "heartbeat":
                topology.heartbeat(
                    device_id,
                    status=body.get("status", "online"),
                    load_pct=float(body.get("load_pct", 0.0)),
                    free_mem_mb=body.get("free_mem_mb"),
                )
            elif mtype == "result":
                # Log the result and free the worker.
                _persist_job_result(device_id, body)
                topology.heartbeat(device_id, status="idle")
            elif mtype == "pong":
                pass
            else:
                await ws.send_json({"type": "error",
                                    "error": f"unknown frame type: {mtype}"})
    except WebSocketDisconnect:
        pass
    finally:
        if device_id:
            ACTIVE.pop(device_id, None)
            topology.heartbeat(device_id, status="offline")


# ── Job push ────────────────────────────────────────────────────────────────
@app.post("/worker/push-job")
async def push_job(request: Request):
    """Push a routed job to its assigned device.
    Body: {device_id, job: {pass_id, asset_url, params}}"""
    payload = await request.json()
    did = payload.get("device_id")
    job = payload.get("job") or {}
    if not did:
        return JSONResponse({"ok": False, "error": "device_id required"}, 400)
    sock = ACTIVE.get(did)
    if sock is None:
        return JSONResponse(
            {"ok": False, "error": f"no active worker for device {did}"}, 404)
    job_id = "job-" + uuid.uuid4().hex[:8]
    await sock.send_json({"type": "job", "job_id": job_id, "body": job})
    topology.heartbeat(did, status="busy")
    return {"ok": True, "job_id": job_id, "device_id": did}


# ── Helpers ────────────────────────────────────────────────────────────────
def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _persist_job_result(device_id: str, body: dict) -> None:
    # Future: write into a `jobs` table. For now just log via plan_evaluations
    # so the audit trail captures all routed work.
    import sqlite3
    db = sqlite3.connect(plans.DB_PATH)
    db.execute(
        "INSERT INTO plan_evaluations (plan_id, ts, fired, pass_id, "
        "                              file_kind, decision) "
        "VALUES (NULL, ?, 0, ?, ?, ?)",
        (_now(), body.get("pass_id"), body.get("file_kind"),
         json.dumps({"device_id": device_id, "result": body}, sort_keys=True)),
    )
    db.commit(); db.close()


# ── Periodic maintenance ────────────────────────────────────────────────────
@app.on_event("startup")
async def _on_startup():
    # Make sure schema + seed are present.
    plans.seed_default_plans()
    asyncio.create_task(_offline_loop())


async def _offline_loop():
    """Periodically mark stale devices offline."""
    while True:
        try:
            n = topology.mark_offline_stale()
            if n:
                print(f"[weave] flipped {n} stale devices to offline")
        except Exception as e:
            print(f"[weave] offline-sweep err: {e}")
        await asyncio.sleep(30)


if __name__ == "__main__":
    import os, uvicorn
    uvicorn.run("weave.weave_server:app",
                host="0.0.0.0", port=int(os.environ.get("PORT", 8540)),
                reload=False)
