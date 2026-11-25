#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        hf_hub
# role:        CONNECTOR · HUGGINGFACE_HUB + 19_INFERENCE_PROVIDERS
# tier:        L0
# substrate:   cloud routing to ~1M+ models + ~200k datasets via unified API
# engine:      HF Hub REST + Inference Providers (OpenAI-compatible)
# storage:     studio/hf_hub/ (per-call logs + cached responses)
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.hf_hub.active.json
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - task_queue.CLOUD pool — every HF inference call routes here
#   - studio_runtime._dispatch_cloud — when card pass.engine='cloud' and provider='hf'
#   - model_installer (extends for live cloud capacity)
# outbound:
#   - HTTPS to huggingface.co (Hub API) + provider gateway
#   - 19 cloud providers via single OpenAI-compatible endpoint
#   - inference_logger.log (every call → crystal chain entry with tier='hf_cloud')
# substrate touch:
#   - reads:  $HF_TOKEN from env, ~/.cache/huggingface/token, .env
#   - writes: studio/hf_hub/log.jsonl + result_cache entries
# the unified surface:
#   - One API spans 19 providers (Groq, Cerebras, SambaNova, Together AI,
#     Fireworks, Replicate, Cohere, Hyperbolic, fal, Novita, DeepInfra,
#     Featherless, Zai, Nscale, Scaleway, Public AI, OVHcloud, HF Inference,
#     WaveSpeed). Same prompt → fan to any/all → ensemble or fastest-first.
# ============================================================================
"""hf_hub.py — Hugging Face Hub + Inference Providers unified connector.

Three capabilities in one module:

  search_models / get_model_card / list_datasets
        Browse HF's ~1M+ models and ~200k datasets via Hub API.

  inference(provider, model, prompt, **kwargs)
        Unified OpenAI-compatible call. The provider arg picks the gateway;
        any failure falls back across the provider list in priority order.

  stream_dataset(dataset_id, split, limit)
        hf-mount-style streaming — pull samples without downloading the
        whole dataset. Extends our datasets_index substrate to the cloud.

Free tier in spirit: most providers have generous free quotas. The router
picks the cheapest/fastest available per call (configurable). Each inference
crystals into the chain so MoE retrieval can find prior similar HF calls
without re-spending tokens.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


try:
    import blake3 as _blake3_mod
    def _hash(data: bytes) -> str:
        return _blake3_mod.blake3(data).hexdigest()
except ImportError:
    def _hash(data: bytes) -> str:
        return hashlib.blake2b(data).hexdigest()


HF_API_ROOT = "https://huggingface.co/api"
HF_INFERENCE_ROUTER = "https://router.huggingface.co/v1"   # OpenAI-compatible


# The 19 inference providers — ordered by typical priority (speed-first).
INFERENCE_PROVIDERS = (
    "groq",            # very fast
    "cerebras",        # extremely fast
    "fireworks-ai",
    "together",
    "novita",
    "deepinfra",
    "fal-ai",
    "hyperbolic",
    "sambanova",
    "nscale",
    "featherless-ai",
    "scaleway",
    "replicate",
    "cohere",
    "zai-org",
    "public-ai",
    "ovhcloud",
    "wavespeed",
    "hf-inference",    # canonical HF endpoint
)


def _load_token() -> str:
    """Look for HF token in env, ~/.cache/huggingface/token, then .env."""
    tok = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN") or ""
    if tok:
        return tok
    cache_token = Path.home() / ".cache" / "huggingface" / "token"
    if cache_token.exists():
        try:
            return cache_token.read_text(encoding="utf-8").strip()
        except OSError:
            pass
    # .env fallback (don't read whole file; just grep the key)
    env_path = Path("/data/Projects/MySpace++/.env")
    if env_path.exists():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith(("HF_TOKEN=", "HUGGINGFACE_TOKEN=")):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            pass
    return ""


def _http_get(url: str, headers: Optional[Dict[str, str]] = None,
              timeout: int = 20) -> Tuple[int, Dict[str, Any]]:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            data = resp.read().decode("utf-8", errors="replace")
            try:
                return status, json.loads(data)
            except json.JSONDecodeError:
                return status, {"_raw": data[:8192]}
    except urllib.error.HTTPError as e:
        return e.code, {"_error": str(e), "_url": url}
    except Exception as e:
        return 0, {"_error": f"{type(e).__name__}: {e}", "_url": url}


def _http_post(url: str, payload: Dict[str, Any],
               headers: Optional[Dict[str, str]] = None,
               timeout: int = 60) -> Tuple[int, Dict[str, Any]]:
    data = json.dumps(payload).encode("utf-8")
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            txt = resp.read().decode("utf-8", errors="replace")
            try:
                return status, json.loads(txt)
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
# 1. Hub search / model card / dataset list
# ---------------------------------------------------------------------------

@dataclass
class HFModelRef:
    model_id: str
    pipeline_tag: str = ""
    tags: List[str] = field(default_factory=list)
    downloads: int = 0
    likes: int = 0
    private: bool = False


def search_models(query: str, limit: int = 20, task: Optional[str] = None,
                   library: Optional[str] = None) -> List[HFModelRef]:
    """Search HF Hub for models. Returns lightweight refs (no weights downloaded)."""
    params = {"search": query, "limit": str(limit)}
    if task:
        params["filter"] = task
    url = f"{HF_API_ROOT}/models?" + urllib.parse.urlencode(params)
    headers = _auth_headers()
    status, body = _http_get(url, headers)
    if status != 200 or not isinstance(body, list):
        return []
    refs = []
    for m in body:
        if not isinstance(m, dict):
            continue
        refs.append(HFModelRef(
            model_id=m.get("id", ""),
            pipeline_tag=m.get("pipeline_tag") or "",
            tags=list(m.get("tags", [])),
            downloads=int(m.get("downloads", 0) or 0),
            likes=int(m.get("likes", 0) or 0),
            private=bool(m.get("private", False)),
        ))
    return refs


def get_model_card(model_id: str) -> Dict[str, Any]:
    """Fetch the model card JSON for a given model_id."""
    url = f"{HF_API_ROOT}/models/{model_id}"
    status, body = _http_get(url, _auth_headers())
    if status != 200:
        return {"_error": True, "status": status, "body": body}
    return body if isinstance(body, dict) else {"_raw": body}


def list_datasets(query: str = "", limit: int = 20) -> List[Dict[str, Any]]:
    """List HF datasets matching query (lightweight refs)."""
    params = {"search": query, "limit": str(limit)} if query else {"limit": str(limit)}
    url = f"{HF_API_ROOT}/datasets?" + urllib.parse.urlencode(params)
    status, body = _http_get(url, _auth_headers())
    if status != 200 or not isinstance(body, list):
        return []
    return [
        {
            "id": d.get("id", ""),
            "downloads": int(d.get("downloads", 0) or 0),
            "tags": list(d.get("tags", [])),
        }
        for d in body if isinstance(d, dict)
    ]


def _auth_headers() -> Dict[str, str]:
    tok = _load_token()
    if tok:
        return {"Authorization": f"Bearer {tok}"}
    return {}


# ---------------------------------------------------------------------------
# 2. Inference router (19 providers via unified OpenAI-compatible API)
# ---------------------------------------------------------------------------

@dataclass
class InferenceResult:
    provider: str
    model: str
    output_text: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    status_code: int = 0
    error: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)
    crystal: str = ""


def inference(model: str,
               prompt: str,
               provider: Optional[str] = None,
               max_tokens: int = 256,
               temperature: float = 0.0,
               system: str = "",
               fallback: bool = True,
               try_providers: Optional[List[str]] = None,
               timeout: int = 60) -> InferenceResult:
    """Single inference call through the HF Inference Provider router.

    If provider is None or fails and fallback=True, walks INFERENCE_PROVIDERS
    in order and returns the first success. Logs every attempt to result_cache.
    """
    tok = _load_token()
    if not tok:
        return InferenceResult(
            provider=provider or "unknown", model=model,
            error="no HF_TOKEN — set env HF_TOKEN or write ~/.cache/huggingface/token",
            status_code=401,
        )

    providers_to_try: List[str] = (try_providers or
                                    ([provider] if provider else []) +
                                    list(INFERENCE_PROVIDERS))
    # Dedupe while preserving order
    seen: set = set()
    ordered = []
    for p in providers_to_try:
        if p and p not in seen:
            ordered.append(p); seen.add(p)

    headers = {"Authorization": f"Bearer {tok}",
                "Content-Type": "application/json"}

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    last_error = ""
    for p in ordered:
        t0 = time.time()
        # The unified router takes provider via the model path:
        # POST router.huggingface.co/v1/chat/completions with {model: "<provider>/<model>"}
        # OR plain model+provider param. Use the simpler model-path form.
        payload = {
            "model": model if "/" in model else f"{p}/{model}",
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        # If model already contains "/" (e.g., "moonshotai/Kimi-K2-Instruct"), keep as-is;
        # the provider is selected via the X-Provider header on the unified router.
        if "/" in model:
            headers["X-HF-Provider"] = p
            payload["model"] = model

        status, body = _http_post(
            f"{HF_INFERENCE_ROUTER}/chat/completions",
            payload=payload, headers=headers, timeout=timeout,
        )
        latency_ms = int((time.time() - t0) * 1000)

        # Success path: OpenAI-style choices array
        if status == 200 and isinstance(body, dict) and "choices" in body:
            try:
                text = body["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError):
                text = json.dumps(body)[:8192]
            usage = body.get("usage") or {}
            result = InferenceResult(
                provider=p, model=model,
                output_text=text,
                prompt_tokens=int(usage.get("prompt_tokens", 0)),
                completion_tokens=int(usage.get("completion_tokens", 0)),
                latency_ms=latency_ms,
                status_code=status,
                raw=body,
            )
            result.crystal = _compute_inference_crystal(p, model, prompt, text, max_tokens, temperature)
            _log_inference_call(result)
            return result

        last_error = (body.get("_error") if isinstance(body, dict) else "") or str(status)
        if not fallback:
            return InferenceResult(
                provider=p, model=model,
                status_code=status, latency_ms=latency_ms,
                error=last_error, raw=body if isinstance(body, dict) else {},
            )

    return InferenceResult(
        provider="exhausted", model=model,
        error=f"all {len(ordered)} providers failed; last error: {last_error}",
        status_code=0,
    )


def _compute_inference_crystal(provider: str, model: str, prompt: str,
                                 output: str, max_tokens: int, temperature: float) -> str:
    canonical = json.dumps({
        "provider": provider, "model": model,
        "prompt": prompt, "output": output,
        "max_tokens": max_tokens, "temperature": temperature,
    }, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return _hash(canonical.encode("utf-8"))


def _log_inference_call(result: InferenceResult) -> None:
    """Append a one-line JSONL entry per call into studio/hf_hub/log.jsonl."""
    try:
        log_dir = Path("/data/Projects/MySpace++/studio/hf_hub")
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "log.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "provider": result.provider, "model": result.model,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "latency_ms": result.latency_ms,
                "status": result.status_code,
                "crystal": result.crystal[:32],
                "output_preview": (result.output_text or "")[:160],
                "error": result.error,
            }, ensure_ascii=True, separators=(",", ":")) + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# 3. Dataset streaming (no full download)
# ---------------------------------------------------------------------------

def stream_dataset(dataset_id: str, split: str = "train",
                    limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    """Stream rows from a HF dataset via the rows API. Returns up to `limit` examples
    without downloading the parquet shard."""
    url = (f"{HF_API_ROOT}/datasets/{dataset_id}/parquet/default/{split}/0.parquet"
            f"?offset={offset}&length={limit}")
    # Alternative: use the dataset-viewer rows API
    rows_url = (f"https://datasets-server.huggingface.co/rows"
                 f"?dataset={urllib.parse.quote(dataset_id, safe='')}"
                 f"&config=default&split={split}&offset={offset}&length={limit}")
    status, body = _http_get(rows_url, _auth_headers(), timeout=30)
    if status != 200 or not isinstance(body, dict):
        return []
    rows = body.get("rows") or []
    return [r.get("row", r) if isinstance(r, dict) else {"_raw": r} for r in rows]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main():
    import argparse
    ap = argparse.ArgumentParser(description="hf_hub — HF Hub + 19-provider inference")
    sub = ap.add_subparsers(dest="cmd")

    p_search = sub.add_parser("search-models")
    p_search.add_argument("query")
    p_search.add_argument("--limit", type=int, default=10)
    p_search.add_argument("--task", default=None)

    p_card = sub.add_parser("model-card")
    p_card.add_argument("model_id")

    p_ds = sub.add_parser("list-datasets")
    p_ds.add_argument("--query", default="")
    p_ds.add_argument("--limit", type=int, default=10)

    p_inf = sub.add_parser("infer")
    p_inf.add_argument("model")
    p_inf.add_argument("prompt")
    p_inf.add_argument("--provider", default=None)
    p_inf.add_argument("--max-tokens", type=int, default=256)
    p_inf.add_argument("--temperature", type=float, default=0.0)
    p_inf.add_argument("--no-fallback", action="store_true")

    p_stream = sub.add_parser("stream-dataset")
    p_stream.add_argument("dataset_id")
    p_stream.add_argument("--split", default="train")
    p_stream.add_argument("--limit", type=int, default=5)

    p_prov = sub.add_parser("providers", help="list the 19 known inference providers")

    args = ap.parse_args()

    if args.cmd == "search-models":
        refs = search_models(args.query, limit=args.limit, task=args.task)
        print(json.dumps([asdict(r) for r in refs], indent=2))

    elif args.cmd == "model-card":
        card = get_model_card(args.model_id)
        # Trim large fields for human display
        for k in ("siblings", "config"):
            if k in card and isinstance(card[k], list) and len(card[k]) > 5:
                card[k] = card[k][:5] + ["...(truncated)"]
        print(json.dumps(card, indent=2)[:4000])

    elif args.cmd == "list-datasets":
        ds = list_datasets(args.query, limit=args.limit)
        print(json.dumps(ds, indent=2))

    elif args.cmd == "infer":
        result = inference(
            model=args.model, prompt=args.prompt, provider=args.provider,
            max_tokens=args.max_tokens, temperature=args.temperature,
            fallback=not args.no_fallback,
        )
        print(json.dumps({
            "provider": result.provider, "model": result.model,
            "status": result.status_code, "latency_ms": result.latency_ms,
            "tokens_in": result.prompt_tokens, "tokens_out": result.completion_tokens,
            "output_preview": (result.output_text or "")[:600],
            "error": result.error, "crystal": result.crystal[:32],
        }, indent=2))

    elif args.cmd == "stream-dataset":
        rows = stream_dataset(args.dataset_id, split=args.split, limit=args.limit)
        print(json.dumps(rows, indent=2)[:4000])

    elif args.cmd == "providers":
        print(json.dumps({"count": len(INFERENCE_PROVIDERS), "providers": list(INFERENCE_PROVIDERS)},
                          indent=2))

    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
