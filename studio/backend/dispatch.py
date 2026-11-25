"""dispatch.py — the real run_step.

Replaces runtime.run_step's mock. Routes each node to the right real backend:

    pass  node -> z21 GPU server :8525            (depth/mask/caption/keypoints/…)
                  (in remote mode: droplet gpu_gateway:8523, Bearer token, WireGuard→z21)
    role  node -> ai_orchestrator :8524           (gemma/LLM text; ollama→claude)
    input node -> yields its file path / text so downstream passes have something to read
    output     -> passthrough of upstream
    connector/none -> returns {"routed": False} so the caller can synth-fallback

Mode + targets are env-configured (so the same code serves local dev and the
public droplet topology):
    STUDIO_BACKEND_MODE = local | remote          (default: local)
    GPU_RUN_URL   (default local  http://127.0.0.1:8525/run)
    AI_ORCH_URL   (default local  http://127.0.0.1:8524/)
    MSPC_TOKEN    (remote only; sent as Bearer to gpu_gateway)
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Any

from backend.node_map import route_for

MODE = os.environ.get("STUDIO_BACKEND_MODE", "local")
GPU_RUN_URL = os.environ.get("GPU_RUN_URL", "http://127.0.0.1:8525/run")
AI_ORCH_URL = os.environ.get("AI_ORCH_URL", "http://127.0.0.1:8524/")
# gently Rust render backend (ComfyUI on the 3090s) — the sister-project endpoint
# for generative connector nodes (comfyui/blender). Remote → droplet gpu_gateway → z21.
GENTLY_RENDER_URL = os.environ.get("GENTLY_RENDER_URL", "http://127.0.0.1:7681/api/studio/render")
MSPC_TOKEN = os.environ.get("MSPC_TOKEN", "")

# port type -> viewer kind (for the canvas Viewer)
KIND = {"IMG": "image", "DEPTH": "image", "MASK": "image", "KPTS": "image",
        "VID": "video", "AUD": "audio", "MUS": "audio", "TXT": "text",
        "MD": "text", "EMB": "embedding", "3D": "mesh"}


def _post(url: str, payload: dict, token: str = "") -> dict:
    data = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode())


def _upstream_path(inputs: dict) -> str | None:
    for a in inputs.values():
        if a and a.get("path"):
            return a["path"]
    return None


def _upstream_text(inputs: dict) -> str:
    parts = []
    for a in inputs.values():
        if a and a.get("value"):
            parts.append(str(a["value"]))
    return "\n".join(parts)


def run_step(node_id: str, params: dict, inputs: dict[str, Any]) -> dict:
    """Returns an artifact dict: {routed, type, kind, path?, value?, engine, ms, error?}."""
    kind, target = route_for(node_id)
    t0 = time.time()

    if kind == "input":
        # IN_TXT carries text; file inputs carry a path the GPU server can read.
        val = params.get("text")
        path = params.get("file")
        if isinstance(path, dict):
            path = path.get("path") or path.get("name")
        return {"routed": True, "engine": "input", "kind": "text" if val else "file",
                "value": val, "path": path, "ms": 0}

    if kind == "output":
        up = next((a for a in inputs.values() if a), {})
        return {"routed": True, "engine": "output", **{k: up.get(k) for k in
                ("kind", "path", "value", "type")}, "ms": 0}

    if kind == "pass":
        src = _upstream_path(inputs)
        token = MSPC_TOKEN if MODE == "remote" else ""
        res = _post(GPU_RUN_URL, {"node_id": node_id, "params": params,
                                  "input_path": src}, token)
        ms = int((time.time() - t0) * 1000)
        if not res.get("ok"):
            return {"routed": True, "engine": "pass", "error": res.get("error"),
                    "pass_id": res.get("pass_id"), "ms": ms}
        ok_kind = {"MASK": "image", "DEPTH": "image", "KPTS": "image",
                   "EMB": "embedding", "TXT": "text", "AUD": "audio"}.get(
                       res.get("kind"), "json")
        return {"routed": True, "engine": "pass", "pass_id": res.get("pass_id"),
                "kind": ok_kind, "type": res.get("kind"), "path": res.get("path"),
                "value": res.get("value"), "ms": ms}

    if kind == "role":
        prompt = (params.get("prompt") or params.get("system") or "") + "\n" + _upstream_text(inputs)
        url = AI_ORCH_URL
        res = _post(url, {"prompt": prompt.strip(), "backend": target.get("backend", "auto"),
                          "max_tokens": int(params.get("max_tokens", 1024))})
        ms = int((time.time() - t0) * 1000)
        return {"routed": True, "engine": "role", "kind": "text", "type": "TXT",
                "value": res.get("response", ""), "ms": ms}

    if kind == "connector":
        # generative nodes → gently Rust render backend (ComfyUI on the 3090s)
        try:
            res = _post(GENTLY_RENDER_URL,
                        {"node_id": node_id, "params": params,
                         "input_path": _upstream_path(inputs)},
                        MSPC_TOKEN if MODE == "remote" else "")
        except Exception as exc:  # gently down/unreachable → synth-fallback
            return {"routed": False, "engine": "connector", "connector": target,
                    "note": f"gently render unreachable: {exc}", "ms": 0}
        if not res.get("ok"):           # workflow pending / failed → synth-fallback
            return {"routed": False, "engine": "connector", "connector": target,
                    "note": res.get("error"), "ms": 0}
        ms = int((time.time() - t0) * 1000)
        # gently already returns the viewer-kind ("image"/"video"/...) in `kind`
        return {"routed": True, "engine": "comfyui", "pass_id": res.get("pass_id"),
                "kind": res.get("kind", "json"),
                "type": res.get("type"), "path": res.get("path"),
                "value": res.get("value"), "crystal_cid": res.get("crystal_cid"),
                "ms": ms}

    # truly unmapped node -> tell caller to synth
    return {"routed": False, "engine": kind, "connector": target, "ms": 0}
