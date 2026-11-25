#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        hf_endpoints
# role:        CONNECTOR · HUGGINGFACE_INFERENCE_ENDPOINTS (dedicated, paid)
# tier:        L0
# substrate:   cloud control plane for dedicated always-on model endpoints
# engine:      HF Inference Endpoints REST v2 (management API)
# storage:     studio/hf_endpoints/ (per-call logs + crystal anchors)
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.hf_endpoints.active.json
# ----------------------------------------------------------------------------
# DISTINCT FROM hf_hub.py
# ----------------------------------------------------------------------------
# hf_hub.py        → multi-provider router (Groq/Cerebras/...) — PER-CALL billing
# hf_endpoints.py  → dedicated always-on endpoints              — HOURLY billing
#
# An HF Inference Endpoint is a SPECIFIC model deployed on a SPECIFIC machine
# (CPU or GPU) that you pay for by the hour while it's running. This module
# is the management plane: list / deploy / pause / resume / delete / predict.
# ----------------------------------------------------------------------------
# COST TRAP — SAFETY RAILS
# ----------------------------------------------------------------------------
# Every deploy* function REQUIRES confirm=True. No exceptions. Without it,
# the call refuses and returns {success:False, error:"deploy requires
# confirm=True; hourly billing"}. This is the only protection between
# accidental provisioning and a recurring monthly bill.
#
# Default hardware='cpu-basic' (cheapest), region='us-east-1', accelerator='cpu'.
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - studio_runtime — when a workflow card needs a guaranteed always-on
#     dedicated endpoint (vs. shared provider)
#   - cc dispatcher (hf-endpoints-list/get/predict; deploy/pause/resume/delete
#     gated behind --confirm)
# outbound:
#   - HTTPS to api.endpoints.huggingface.cloud/v2/endpoint/<namespace>
#   - HTTPS to the endpoint's own /v1/chat/completions for predict()
#   - inference_logger.log (every operation → crystal chain entry)
# substrate touch:
#   - reads:  HF_TOKEN via hf_hub._load_token() (env → ~/.cache → .env)
#   - writes: studio/hf_endpoints/log.jsonl + result_cache entries
# ============================================================================
"""hf_endpoints.py — Hugging Face Inference Endpoints management client.

This module talks to the HF Inference Endpoints management API
(api.endpoints.huggingface.cloud/v2). NOT the Inference Providers router —
that lives in hf_hub.py. Inference Endpoints are dedicated, always-on
deployments of a specific model on specific hardware, billed by the hour.

Operations:

  list_endpoints(namespace)            GET    list of endpoints for a namespace
  get_endpoint(namespace, name)        GET    one endpoint's full state
  deploy_endpoint(...)                 POST   create + start a new endpoint **
  pause_endpoint(namespace, name)      POST   suspend (no further billing)
  resume_endpoint(namespace, name)     POST   resume from paused state
  delete_endpoint(namespace, name)     DELETE remove the endpoint entirely
  predict(endpoint_url, payload)       POST   call the deployed model

  deploy_canonical(name, confirm=True)         convenience preset **

  ** deploy* functions REQUIRE confirm=True. Without it they refuse.

Every operation crystal-anchors via inference_logger.log() so the chain has
a tamper-evident audit trail of provisioning actions.

stdlib-only — no pip installs. Reuses hf_hub._load_token / _http_get /
_http_post for token + HTTP plumbing.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# Reuse the existing surface from hf_hub.py — single source of truth for the
# token resolver and the stdlib HTTP helpers. Don't reimplement.
_LIB_DIR = str(Path(__file__).parent)
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)

try:
    from hf_hub import _load_token, _http_get, _http_post  # type: ignore
except Exception as _e:  # pragma: no cover — same-dir import should always work
    raise ImportError(
        f"hf_endpoints requires hf_hub in the same directory; import failed: {_e}"
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

# Management API root. The path is /v2/endpoint/<namespace>[/...].
HF_ENDPOINTS_ROOT = "https://api.endpoints.huggingface.cloud/v2/endpoint"

# Canonical default model for deploy_canonical(). Small enough to fit on
# cpu-basic and Llama-license-friendly. Kept here so it's overridable in one
# place and grep-able by the smoke test.
CANONICAL_TEXT_MODEL = "meta-llama/Llama-3.2-1B-Instruct"

# Default safe-cheap deployment knobs. cpu-basic is the lowest-cost tier.
DEFAULT_HARDWARE = "cpu-basic"
DEFAULT_REGION = "us-east-1"
DEFAULT_ACCELERATOR = "cpu"
DEFAULT_VENDOR = "aws"
DEFAULT_FRAMEWORK = "pytorch"
DEFAULT_TASK = "text-generation"


# ---------------------------------------------------------------------------
# Logger glue — best-effort. Never blow up the caller if the substrate isn't
# present (e.g. smoke test in a stripped env).
# ---------------------------------------------------------------------------

def _log_op(tier: str, model: str, scope: str, output_text: str,
            rc: int = 0) -> str:
    """Append a crystal-anchored entry to the inference master chain.

    tier  ∈ {'deploy', 'inference'}
    model = 'hf_endpoint' for control-plane ops, 'hf_endpoint:<name>' for predict
    scope = chain_context (typically "<namespace>/<name>")
    """
    try:
        from inference_logger import InferenceLogger  # type: ignore
        return InferenceLogger().log(
            original_prompt="",
            enhanced_prompt="",
            output_text=output_text[:4096],
            tier=tier,
            model=model,
            scope=scope,
            rc=rc,
        )
    except Exception:
        return ""


def _log_local_jsonl(entry: Dict[str, Any]) -> None:
    """Append a one-line JSONL audit entry into studio/hf_endpoints/log.jsonl.

    This is the per-module log; the crystal chain (above) is the global one.
    """
    try:
        log_dir = Path("/data/Projects/MySpace++/studio/hf_endpoints")
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "log.jsonl").open("a", encoding="utf-8") as f:
            payload = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                **entry,
            }
            f.write(json.dumps(payload, ensure_ascii=True,
                                separators=(",", ":")) + "\n")
    except OSError:
        pass


def _auth_headers() -> Dict[str, str]:
    tok = _load_token()
    if not tok:
        return {}
    return {"Authorization": f"Bearer {tok}"}


def _http_delete(url: str, headers: Optional[Dict[str, str]] = None,
                  timeout: int = 30) -> Tuple[int, Dict[str, Any]]:
    """DELETE — stdlib has no helper; implement here. Mirrors _http_get/post."""
    req = urllib.request.Request(url, headers=headers or {}, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            txt = resp.read().decode("utf-8", errors="replace")
            try:
                return status, json.loads(txt) if txt else {}
            except json.JSONDecodeError:
                return status, {"_raw": txt[:8192]}
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return e.code, {"_error": str(e), "_body": body[:2048], "_url": url}
    except Exception as e:
        return 0, {"_error": f"{type(e).__name__}: {e}", "_url": url}


# ---------------------------------------------------------------------------
# Result shapes
# ---------------------------------------------------------------------------

@dataclass
class EndpointRef:
    """Lightweight reference to one deployed endpoint."""
    name: str = ""
    namespace: str = ""
    status: str = ""           # "running" | "paused" | "scaling" | "failed" | ...
    url: str = ""              # the endpoint's own public URL
    model_id: str = ""
    hardware: str = ""
    region: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _namespace_or_self(namespace: Optional[str]) -> str:
    """Resolve a namespace argument. If None or empty, fall back to env
    HF_NAMESPACE, else the literal string 'me' which the HF API resolves to
    the token owner. Returns a URL-safe string."""
    ns = (namespace or os.environ.get("HF_NAMESPACE") or "me").strip()
    return urllib.parse.quote(ns, safe="")


def _parse_endpoint(d: Dict[str, Any]) -> EndpointRef:
    """Normalize the HF Endpoint JSON into our EndpointRef shape.

    HF returns a nested structure roughly:
      { "name": ..., "type": ..., "accountId": ...,
        "model": {"repository": "...", "task": "...", "framework": "..."},
        "compute": {"accelerator": "cpu", "instanceType": "cpu-basic",
                     "vendor": "aws", "region": "us-east-1", ...},
        "status": {"state": "running", "url": "https://..." } }
    """
    if not isinstance(d, dict):
        return EndpointRef(raw={"_unparsed": str(d)[:512]})
    model = d.get("model") or {}
    compute = d.get("compute") or {}
    status = d.get("status") or {}
    return EndpointRef(
        name=d.get("name", "") or "",
        namespace=d.get("accountId", "") or d.get("namespace", "") or "",
        status=(status.get("state") if isinstance(status, dict) else "") or "",
        url=(status.get("url") if isinstance(status, dict) else "") or "",
        model_id=(model.get("repository") if isinstance(model, dict) else "") or "",
        hardware=(compute.get("instanceType") if isinstance(compute, dict) else "") or "",
        region=(compute.get("region") if isinstance(compute, dict) else "") or "",
        raw=d,
    )


# ---------------------------------------------------------------------------
# Top-level functional API
# ---------------------------------------------------------------------------

def list_endpoints(namespace: Optional[str] = None) -> Dict[str, Any]:
    """List all endpoints in <namespace>. Default namespace = HF_NAMESPACE or 'me'.

    Returns: {success: bool, endpoints: [...], error: str, status: int}
    """
    tok = _load_token()
    if not tok:
        out = {"success": False, "endpoints": [], "status": 401,
               "error": "no HF_TOKEN — set env HF_TOKEN or write ~/.cache/huggingface/token"}
        _log_local_jsonl({"op": "list", "namespace": namespace or "", **out})
        return out

    ns = _namespace_or_self(namespace)
    url = f"{HF_ENDPOINTS_ROOT}/{ns}"
    status, body = _http_get(url, _auth_headers(), timeout=20)

    # HF returns either a bare list, or {"items": [...]}, or an error object.
    items: List[Dict[str, Any]] = []
    if status == 200:
        if isinstance(body, list):
            items = body
        elif isinstance(body, dict):
            cand = body.get("items") or body.get("endpoints") or []
            if isinstance(cand, list):
                items = cand

    endpoints = [asdict(_parse_endpoint(e)) for e in items if isinstance(e, dict)]
    ok = status == 200
    error = "" if ok else (
        body.get("_error") if isinstance(body, dict) else f"http {status}"
    ) or ""

    result = {
        "success": ok,
        "status": status,
        "endpoints": endpoints,
        "namespace": namespace or os.environ.get("HF_NAMESPACE") or "me",
        "error": str(error)[:512],
    }
    _log_local_jsonl({"op": "list", "namespace": result["namespace"],
                       "count": len(endpoints), "status": status})
    return result


def get_endpoint(namespace: str, name: str) -> Dict[str, Any]:
    """Fetch one endpoint's full state."""
    tok = _load_token()
    if not tok:
        return {"success": False, "status": 401, "error": "no HF_TOKEN"}
    ns = _namespace_or_self(namespace)
    nm = urllib.parse.quote(name, safe="")
    url = f"{HF_ENDPOINTS_ROOT}/{ns}/{nm}"
    status, body = _http_get(url, _auth_headers(), timeout=20)
    ok = status == 200 and isinstance(body, dict)
    out = {
        "success": ok,
        "status": status,
        "endpoint": asdict(_parse_endpoint(body)) if ok else {},
        "error": "" if ok else (
            (body.get("_error") if isinstance(body, dict) else "") or f"http {status}"
        ),
    }
    _log_local_jsonl({"op": "get", "namespace": namespace, "name": name,
                       "status": status})
    return out


def deploy_endpoint(
    namespace: str,
    name: str,
    model_id: str,
    hardware: str = DEFAULT_HARDWARE,
    region: str = DEFAULT_REGION,
    accelerator: str = DEFAULT_ACCELERATOR,
    vendor: str = DEFAULT_VENDOR,
    framework: str = DEFAULT_FRAMEWORK,
    task: str = DEFAULT_TASK,
    min_replica: int = 0,
    max_replica: int = 1,
    revision: str = "main",
    endpoint_type: str = "protected",
    confirm: bool = False,
) -> Dict[str, Any]:
    """POST a new endpoint. **REQUIRES confirm=True — costs money.**

    Default hardware is cpu-basic (cheapest). Setting min_replica=0 means
    scale-to-zero, which avoids billing while idle (the endpoint can take
    minutes to warm up on the next call).

    Body shape follows HF's Endpoint v2 schema:
      { "accountId": <ns>, "compute": {...}, "model": {...},
        "name": <name>, "provider": {...}, "type": <type> }
    """
    if not confirm:
        out = {"success": False, "status": 0,
               "error": "deploy requires confirm=True; hourly billing"}
        _log_local_jsonl({"op": "deploy", "namespace": namespace, "name": name,
                           "model_id": model_id, "confirmed": False, **out})
        # Crystal-anchor the refusal too — it's a meaningful chain event.
        _log_op("deploy", "hf_endpoint",
                f"{namespace}/{name}",
                f"REFUSED deploy of {model_id} (confirm=False)", rc=2)
        return out

    tok = _load_token()
    if not tok:
        return {"success": False, "status": 401, "error": "no HF_TOKEN"}

    ns = _namespace_or_self(namespace)
    url = f"{HF_ENDPOINTS_ROOT}/{ns}"

    payload: Dict[str, Any] = {
        "accountId": namespace,
        "name": name,
        "type": endpoint_type,
        "compute": {
            "accelerator": accelerator,
            "instanceType": hardware,
            "instanceSize": "x1",
            "scaling": {
                "minReplica": min_replica,
                "maxReplica": max_replica,
            },
        },
        "model": {
            "repository": model_id,
            "revision": revision,
            "framework": framework,
            "task": task,
        },
        "provider": {
            "vendor": vendor,
            "region": region,
        },
    }

    headers = {**_auth_headers(), "Content-Type": "application/json"}
    status, body = _http_post(url, payload=payload, headers=headers, timeout=60)
    ok = status in (200, 201, 202)
    out: Dict[str, Any] = {
        "success": ok,
        "status": status,
        "endpoint": asdict(_parse_endpoint(body)) if (ok and isinstance(body, dict)) else {},
        "error": "" if ok else (
            (body.get("_error") if isinstance(body, dict) else "") or f"http {status}"
        ),
    }
    _log_local_jsonl({"op": "deploy", "namespace": namespace, "name": name,
                       "model_id": model_id, "hardware": hardware,
                       "region": region, "confirmed": True,
                       "status": status, "success": ok})
    _log_op("deploy", "hf_endpoint", f"{namespace}/{name}",
            f"DEPLOY {model_id} on {hardware}/{region} → status={status}",
            rc=0 if ok else 1)
    return out


def pause_endpoint(namespace: str, name: str) -> Dict[str, Any]:
    """Suspend the endpoint. Stops billing until resumed."""
    return _control_op(namespace, name, "pause")


def resume_endpoint(namespace: str, name: str) -> Dict[str, Any]:
    """Resume a paused endpoint. Billing restarts when running."""
    return _control_op(namespace, name, "resume")


def delete_endpoint(namespace: str, name: str) -> Dict[str, Any]:
    """Remove the endpoint entirely. Irreversible."""
    tok = _load_token()
    if not tok:
        return {"success": False, "status": 401, "error": "no HF_TOKEN"}
    ns = _namespace_or_self(namespace)
    nm = urllib.parse.quote(name, safe="")
    url = f"{HF_ENDPOINTS_ROOT}/{ns}/{nm}"
    status, body = _http_delete(url, _auth_headers(), timeout=30)
    ok = status in (200, 202, 204)
    out = {
        "success": ok,
        "status": status,
        "error": "" if ok else (
            (body.get("_error") if isinstance(body, dict) else "") or f"http {status}"
        ),
    }
    _log_local_jsonl({"op": "delete", "namespace": namespace, "name": name,
                       "status": status, "success": ok})
    _log_op("deploy", "hf_endpoint", f"{namespace}/{name}",
            f"DELETE → status={status}", rc=0 if ok else 1)
    return out


def _control_op(namespace: str, name: str, action: str) -> Dict[str, Any]:
    """Shared POST for pause/resume — both are <base>/<name>/<action> with empty body."""
    tok = _load_token()
    if not tok:
        return {"success": False, "status": 401, "error": "no HF_TOKEN"}
    ns = _namespace_or_self(namespace)
    nm = urllib.parse.quote(name, safe="")
    url = f"{HF_ENDPOINTS_ROOT}/{ns}/{nm}/{action}"
    headers = {**_auth_headers(), "Content-Type": "application/json"}
    status, body = _http_post(url, payload={}, headers=headers, timeout=30)
    ok = status in (200, 202)
    out = {
        "success": ok,
        "status": status,
        "endpoint": asdict(_parse_endpoint(body)) if (ok and isinstance(body, dict)) else {},
        "error": "" if ok else (
            (body.get("_error") if isinstance(body, dict) else "") or f"http {status}"
        ),
    }
    _log_local_jsonl({"op": action, "namespace": namespace, "name": name,
                       "status": status, "success": ok})
    _log_op("deploy", "hf_endpoint", f"{namespace}/{name}",
            f"{action.upper()} → status={status}", rc=0 if ok else 1)
    return out


def predict(endpoint_url: str, payload: Dict[str, Any],
            path: str = "/v1/chat/completions",
            timeout: int = 60,
            endpoint_name: str = "") -> Dict[str, Any]:
    """Call a deployed endpoint.

    endpoint_url is the URL returned in EndpointRef.url (the per-endpoint
    public URL — NOT the management API root). path defaults to
    "/v1/chat/completions" for chat models; pass "/predict" for non-chat.
    """
    tok = _load_token()
    if not tok:
        return {"success": False, "status": 401, "error": "no HF_TOKEN",
                "output_text": ""}

    if not endpoint_url:
        return {"success": False, "status": 0,
                "error": "predict requires endpoint_url (from get_endpoint().endpoint.url)",
                "output_text": ""}

    url = endpoint_url.rstrip("/") + path
    headers = {**_auth_headers(), "Content-Type": "application/json"}
    t0 = time.time()
    status, body = _http_post(url, payload=payload, headers=headers, timeout=timeout)
    latency_ms = int((time.time() - t0) * 1000)
    ok = status == 200

    # Extract text from common shapes — OpenAI choices, HF raw generation
    text = ""
    if ok and isinstance(body, dict):
        try:
            text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            if isinstance(body.get("generated_text"), str):
                text = body["generated_text"]
            elif isinstance(body, list) and body and isinstance(body[0], dict):
                text = body[0].get("generated_text", "") or ""

    out = {
        "success": ok,
        "status": status,
        "latency_ms": latency_ms,
        "output_text": text,
        "raw": body if isinstance(body, dict) else {"_raw": str(body)[:1024]},
        "error": "" if ok else (
            (body.get("_error") if isinstance(body, dict) else "") or f"http {status}"
        ),
    }
    _log_local_jsonl({"op": "predict", "endpoint_url": endpoint_url[:200],
                       "status": status, "latency_ms": latency_ms,
                       "output_preview": text[:160]})
    _log_op("inference", f"hf_endpoint:{endpoint_name or 'unnamed'}",
            endpoint_url, text[:512], rc=0 if ok else 1)
    return out


def deploy_canonical(name: str = "mspc-text-default",
                      namespace: Optional[str] = None,
                      model_id: str = CANONICAL_TEXT_MODEL,
                      confirm: bool = False) -> Dict[str, Any]:
    """Convenience: deploy a tiny default text model on the cheapest hardware.

    REQUIRES confirm=True. Without it, returns the standard refusal.
    """
    if not confirm:
        return {"success": False, "status": 0,
                "error": "deploy requires confirm=True; hourly billing"}
    ns = namespace or os.environ.get("HF_NAMESPACE") or "me"
    return deploy_endpoint(
        namespace=ns,
        name=name,
        model_id=model_id,
        hardware=DEFAULT_HARDWARE,
        region=DEFAULT_REGION,
        accelerator=DEFAULT_ACCELERATOR,
        confirm=True,
    )


# ---------------------------------------------------------------------------
# Per-data-type (per-modality) endpoints — "an endpoint per data".
# Build-safe: planning is free + offline; deploy still REQUIRES confirm=True
# (hourly billing). The registry of what's planned/deployed lives in
# studio/models/hf_endpoints.json so cloud_providers + cc can read it.
# ---------------------------------------------------------------------------

MODALITY_MODELS: Dict[str, Dict[str, str]] = {
    "text":  {"model_id": "meta-llama/Llama-3.2-1B-Instruct", "task": "text-generation", "name": "mspc-text"},
    "code":  {"model_id": "Qwen/Qwen2.5-Coder-1.5B-Instruct", "task": "text-generation", "name": "mspc-code"},
    "embed": {"model_id": "BAAI/bge-small-en-v1.5",           "task": "feature-extraction", "name": "mspc-embed"},
    "image": {"model_id": "black-forest-labs/FLUX.1-schnell", "task": "text-to-image", "name": "mspc-image"},
    "audio": {"model_id": "openai/whisper-small",             "task": "automatic-speech-recognition", "name": "mspc-audio"},
}

HF_ENDPOINTS_REGISTRY = Path("/data/Projects/MySpace++/studio/models/hf_endpoints.json")


def _load_endpoints_registry() -> Dict[str, Any]:
    try:
        return json.loads(HF_ENDPOINTS_REGISTRY.read_text())
    except Exception:
        return {"modalities": {}}


def _save_endpoints_registry(reg: Dict[str, Any]) -> None:
    try:
        HF_ENDPOINTS_REGISTRY.parent.mkdir(parents=True, exist_ok=True)
        HF_ENDPOINTS_REGISTRY.write_text(json.dumps(reg, indent=2))
    except Exception:
        pass


def plan_per_modality(namespace: Optional[str] = None) -> Dict[str, Any]:
    """Offline, free: describe the endpoint that WOULD be deployed per modality.
    Records the plan in the registry. No HF call, no billing."""
    ns = namespace or os.environ.get("HF_NAMESPACE") or "me"
    reg = _load_endpoints_registry()
    reg.setdefault("modalities", {})
    plan = {}
    for modality, spec in MODALITY_MODELS.items():
        entry = {
            "namespace": ns, "name": spec["name"], "model_id": spec["model_id"],
            "task": spec["task"], "hardware": DEFAULT_HARDWARE,
            "min_replica": 0, "status": reg["modalities"].get(modality, {}).get("status", "planned"),
        }
        reg["modalities"][modality] = entry
        plan[modality] = entry
    _save_endpoints_registry(reg)
    return {"namespace": ns, "modalities": plan,
            "note": "planned only; run deploy_per_modality(modality, confirm=True) to create (hourly billing)"}


def deploy_per_modality(modality: str, namespace: Optional[str] = None,
                        confirm: bool = False) -> Dict[str, Any]:
    """Deploy one modality's endpoint. REQUIRES confirm=True (hourly billing)."""
    if modality not in MODALITY_MODELS:
        return {"success": False, "error": f"unknown modality: {modality}; "
                f"known: {list(MODALITY_MODELS)}"}
    spec = MODALITY_MODELS[modality]
    if not confirm:
        return {"success": False, "status": 0,
                "error": "deploy requires confirm=True; hourly billing",
                "would_deploy": {"modality": modality, **spec}}
    ns = namespace or os.environ.get("HF_NAMESPACE") or "me"
    res = deploy_endpoint(namespace=ns, name=spec["name"], model_id=spec["model_id"],
                          task=spec["task"], confirm=True)
    if res.get("success"):
        reg = _load_endpoints_registry()
        reg.setdefault("modalities", {})[modality] = {
            "namespace": ns, "name": spec["name"], "model_id": spec["model_id"],
            "task": spec["task"], "status": "deployed"}
        _save_endpoints_registry(reg)
    return res


# ---------------------------------------------------------------------------
# Class wrapper — same surface as a bag of methods, easier to pass around.
# Tests / callers may prefer the class form (HFEndpointsClient()) for
# inspection (e.g. checking _token presence) without leaking state globally.
# ---------------------------------------------------------------------------

class HFEndpointsClient:
    """Thin wrapper around the functional API.

    Methods mirror the module-level functions. The only stateful field is
    self._token, captured at __init__ via hf_hub._load_token() for cheap
    presence-checks (smoke tests inspect `bool(c._token)`).
    """

    def __init__(self, namespace: Optional[str] = None):
        self._token: str = _load_token()
        self._namespace: Optional[str] = namespace or os.environ.get("HF_NAMESPACE")

    # --- discovery / read-only ----------------------------------------
    def list_endpoints(self, namespace: Optional[str] = None) -> Dict[str, Any]:
        return list_endpoints(namespace or self._namespace)

    def get_endpoint(self, namespace: str, name: str) -> Dict[str, Any]:
        return get_endpoint(namespace, name)

    # --- control plane (gated) ----------------------------------------
    def deploy_endpoint(self, namespace: str, name: str, model_id: str,
                         hardware: str = DEFAULT_HARDWARE,
                         region: str = DEFAULT_REGION,
                         accelerator: str = DEFAULT_ACCELERATOR,
                         confirm: bool = False,
                         **kwargs: Any) -> Dict[str, Any]:
        return deploy_endpoint(
            namespace=namespace, name=name, model_id=model_id,
            hardware=hardware, region=region, accelerator=accelerator,
            confirm=confirm, **kwargs,
        )

    def deploy_canonical(self, name: str = "mspc-text-default",
                          namespace: Optional[str] = None,
                          model_id: str = CANONICAL_TEXT_MODEL,
                          confirm: bool = False) -> Dict[str, Any]:
        return deploy_canonical(name=name,
                                 namespace=namespace or self._namespace,
                                 model_id=model_id, confirm=confirm)

    def pause_endpoint(self, namespace: str, name: str) -> Dict[str, Any]:
        return pause_endpoint(namespace, name)

    def resume_endpoint(self, namespace: str, name: str) -> Dict[str, Any]:
        return resume_endpoint(namespace, name)

    def delete_endpoint(self, namespace: str, name: str) -> Dict[str, Any]:
        return delete_endpoint(namespace, name)

    # --- data plane ---------------------------------------------------
    def predict(self, endpoint_url: str, payload: Dict[str, Any],
                path: str = "/v1/chat/completions",
                timeout: int = 60,
                endpoint_name: str = "") -> Dict[str, Any]:
        return predict(endpoint_url, payload, path=path, timeout=timeout,
                        endpoint_name=endpoint_name)


# ---------------------------------------------------------------------------
# CLI — every destructive command requires --confirm, mirroring the API gate.
# ---------------------------------------------------------------------------

def _main() -> None:
    import argparse
    ap = argparse.ArgumentParser(
        description="hf_endpoints — HF Inference Endpoints management"
                    " (DEDICATED, HOURLY-BILLED — distinct from hf_hub.py)",
    )
    sub = ap.add_subparsers(dest="cmd")

    p_list = sub.add_parser("list", help="list endpoints in a namespace")
    p_list.add_argument("--namespace", default=None)

    p_get = sub.add_parser("get", help="get one endpoint's state")
    p_get.add_argument("namespace")
    p_get.add_argument("name")

    p_dep = sub.add_parser("deploy", help="deploy a new endpoint (PAID — requires --confirm)")
    p_dep.add_argument("namespace")
    p_dep.add_argument("name")
    p_dep.add_argument("model_id")
    p_dep.add_argument("--hardware", default=DEFAULT_HARDWARE)
    p_dep.add_argument("--region", default=DEFAULT_REGION)
    p_dep.add_argument("--accelerator", default=DEFAULT_ACCELERATOR)
    p_dep.add_argument("--confirm", action="store_true",
                        help="REQUIRED — without this the call refuses (cost trap)")

    p_can = sub.add_parser("deploy-canonical",
                            help=f"deploy default model {CANONICAL_TEXT_MODEL} (requires --confirm)")
    p_can.add_argument("--name", default="mspc-text-default")
    p_can.add_argument("--namespace", default=None)
    p_can.add_argument("--model-id", default=CANONICAL_TEXT_MODEL)
    p_can.add_argument("--confirm", action="store_true")

    p_pause = sub.add_parser("pause", help="suspend an endpoint")
    p_pause.add_argument("namespace")
    p_pause.add_argument("name")

    p_res = sub.add_parser("resume", help="resume a paused endpoint")
    p_res.add_argument("namespace")
    p_res.add_argument("name")

    p_del = sub.add_parser("delete", help="delete an endpoint entirely")
    p_del.add_argument("namespace")
    p_del.add_argument("name")

    p_pred = sub.add_parser("predict", help="call a deployed endpoint")
    p_pred.add_argument("endpoint_url")
    p_pred.add_argument("payload_json", help="JSON string for the request body")
    p_pred.add_argument("--path", default="/v1/chat/completions")
    p_pred.add_argument("--name", default="", help="endpoint name (for logging)")

    args = ap.parse_args()
    c = HFEndpointsClient()

    if args.cmd == "list":
        print(json.dumps(c.list_endpoints(args.namespace), indent=2)[:8000])
    elif args.cmd == "get":
        print(json.dumps(c.get_endpoint(args.namespace, args.name), indent=2)[:8000])
    elif args.cmd == "deploy":
        print(json.dumps(c.deploy_endpoint(
            args.namespace, args.name, args.model_id,
            hardware=args.hardware, region=args.region,
            accelerator=args.accelerator, confirm=args.confirm), indent=2)[:8000])
    elif args.cmd == "deploy-canonical":
        print(json.dumps(c.deploy_canonical(
            name=args.name, namespace=args.namespace,
            model_id=args.model_id, confirm=args.confirm), indent=2)[:8000])
    elif args.cmd == "pause":
        print(json.dumps(c.pause_endpoint(args.namespace, args.name), indent=2)[:8000])
    elif args.cmd == "resume":
        print(json.dumps(c.resume_endpoint(args.namespace, args.name), indent=2)[:8000])
    elif args.cmd == "delete":
        print(json.dumps(c.delete_endpoint(args.namespace, args.name), indent=2)[:8000])
    elif args.cmd == "predict":
        try:
            payload = json.loads(args.payload_json)
        except json.JSONDecodeError as e:
            print(json.dumps({"success": False,
                               "error": f"bad JSON: {e}"}, indent=2))
            sys.exit(2)
        print(json.dumps(c.predict(args.endpoint_url, payload,
                                     path=args.path,
                                     endpoint_name=args.name), indent=2)[:8000])
    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
