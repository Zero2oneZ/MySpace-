#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        deepseek_mcp
# role:        CONNECTOR · DEEPSEEK_CHEAP_TIER_INFERENCE
# tier:        L0
# substrate:   OpenAI-compatible inference at api.deepseek.com (cheap: ~$0.27/M)
# storage:     ~/.cc/third_party_logs/deepseek_sends.jsonl + crystal chain
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.deepseek_mcp.active.json
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - core/lib/model_api.py (D.1 — unified model API; cheap-tier rail)
#   - core/lib/router_policy (when cost_class='cheap' wins)
#   - core/lib/third_party/generative_mcp.py generate_code (uses deepseek-coder)
#   - core/cc.sh::cmd_deepseek_test  /  cmd_deepseek_code
#   - studio_runtime._dispatch_cloud (when pass.provider_family='deepseek')
# outbound:
#   - https://api.deepseek.com/v1/chat/completions
#   - https://api.deepseek.com/v1/embeddings
#   - https://api.deepseek.com/v1/models
#   - inference_logger.log (tier='inference', model='deepseek-<variant>')
# substrate touch:
#   - reads:  DEEPSEEK_API_KEY or INFERENCE_API_KEY via keys.upstream_key('deepseek')
#   - reads:  DEEPSEEK_BASE_URL or INFERENCE_BASE_URL env (default api.deepseek.com)
#   - writes: send_log entries + crystal chain inference records
# ----------------------------------------------------------------------------
# MODELS
# ----------------------------------------------------------------------------
#   deepseek-chat       — general purpose (default)
#   deepseek-coder      — code completion / generation
#   deepseek-reasoner   — chain-of-thought reasoning
# All ~$0.27/M input · $1.10/M output (months of work on Tom's ~$20)
# ============================================================================
"""deepseek_mcp.py — DeepSeek OpenAI-compatible inference connector.

Mirrors third_party/stripe_mcp.py shape exactly. SERVICE = "deepseek".
Stdlib only — no `openai` python SDK dep. POST application/json.

Tools (via send(recipient=tool_name, message=json_args, **kwargs)):
  - chat_complete(model, messages, max_tokens, temperature, stream=False)
  - embed(model, input)
  - models_list()

Every successful call crystal-anchors via inference_logger.log(tier='inference').
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_PROJECT_ROOT / "core" / "lib"))

from base import ThirdPartyConnector, ConnectionConfig, SendResult  # type: ignore  # noqa: E402

EXPECTED_TOOLS = ("chat_complete", "embed", "models_list")
DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
KNOWN_MODELS = ("deepseek-chat", "deepseek-coder", "deepseek-reasoner")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_api_key() -> str:
    """Resolve DeepSeek key via keys.upstream_key('deepseek')."""
    try:
        sys.path.insert(0, str(_PROJECT_ROOT / "studio"))
        from auth.keys import upstream_key  # type: ignore
        k = upstream_key("deepseek")
        if k:
            return k
    except Exception:
        pass
    return os.environ.get("DEEPSEEK_API_KEY", "") or os.environ.get("INFERENCE_API_KEY", "")


def _load_base_url() -> str:
    """Resolve DeepSeek base URL — env override, then default."""
    return (
        os.environ.get("DEEPSEEK_BASE_URL", "")
        or os.environ.get("INFERENCE_BASE_URL", "")
        or DEFAULT_BASE_URL
    )


def _http_post_json(url: str, payload: Dict[str, Any], headers: Dict[str, str],
                     timeout: int = 60) -> tuple[int, Dict[str, Any]]:
    body = json.dumps(payload).encode("utf-8")
    hdrs = {"Content-Type": "application/json"}
    hdrs.update(headers)
    req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            txt = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(txt)
            except json.JSONDecodeError:
                return resp.status, {"_raw": txt[:8192]}
    except urllib.error.HTTPError as e:
        try:
            body_txt = e.read().decode("utf-8", errors="replace")
            if body_txt.strip().startswith("{"):
                return e.code, json.loads(body_txt)
            return e.code, {"_error": body_txt[:2048]}
        except Exception:
            return e.code, {"_error": str(e)}
    except Exception as e:
        return 0, {"_error": f"{type(e).__name__}: {e}"}


def _http_get(url: str, headers: Dict[str, str], timeout: int = 30) -> tuple[int, Dict[str, Any]]:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            txt = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(txt)
            except json.JSONDecodeError:
                return resp.status, {"_raw": txt[:8192]}
    except urllib.error.HTTPError as e:
        return e.code, {"_error": str(e)}
    except Exception as e:
        return 0, {"_error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------------------
# Crystal-chain logging
# ---------------------------------------------------------------------------

def _log_inference(tool: str, model: str, prompt_preview: str, output: str,
                     tokens_in: int, tokens_out: int, latency_ms: int,
                     status_code: int) -> str:
    try:
        from inference_logger import InferenceLogger  # type: ignore
        il = InferenceLogger()
        return il.log(
            original_prompt=prompt_preview[:512],
            enhanced_prompt=f"deepseek.{tool}",
            output_text=output[:1024],
            tier="inference", model=f"deepseek/{model}",
            scope=f"deepseek_{tool}",
            tokens_in=tokens_in, tokens_out=tokens_out, latency_ms=latency_ms,
            source_action=f"deepseek.{tool}",
            done_flag=(status_code == 200),
            rc=0 if status_code == 200 else 1,
        ) or ""
    except Exception as e:
        sys.stderr.write(f"warn: deepseek crystal log failed: {type(e).__name__}: {e}\n")
        return ""


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------

class DeepSeekMCPConnector(ThirdPartyConnector):
    """DeepSeek OpenAI-compatible REST connector."""

    SERVICE = "deepseek"

    def __init__(self, config: Optional[ConnectionConfig] = None):
        if config is None:
            config = ConnectionConfig(service=self.SERVICE, name="deepseek_default", action="cheap_inference")
        super().__init__(config)
        self._api_key = ""
        self._base_url = ""
        self._connected = False

    def connect(self) -> bool:
        self._api_key = _load_api_key()
        self._base_url = _load_base_url().rstrip("/")
        if not self._api_key:
            return False
        # smoke: GET /v1/models (cheap; just verifies auth)
        status, _ = _http_get(
            f"{self._base_url}/models",
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=10,
        )
        # Some providers don't expose /models but still accept chat — accept 200 or 404 as "auth works"
        self._connected = status in (200, 404)
        return self._connected

    def disconnect(self) -> None:
        self._connected = False

    def send(self, recipient: str, message: str = "", **kwargs) -> SendResult:
        if not self._connected and not self.connect():
            return SendResult(
                success=False, service=self.SERVICE, recipient=recipient,
                message_preview="", timestamp=time.time(),
                error="deepseek_not_connected (missing DEEPSEEK_API_KEY / INFERENCE_API_KEY?)",
                metadata={},
            )

        params: Dict[str, Any] = {}
        if message:
            try:
                params = json.loads(message)
            except json.JSONDecodeError:
                params = {"prompt": message}
        params.update(kwargs)

        t0 = time.time()
        if recipient == "chat_complete":
            status, body = self._chat_complete(params)
        elif recipient == "embed":
            status, body = self._embed(params)
        elif recipient == "models_list":
            status, body = self._models_list()
        else:
            return SendResult(
                success=False, service=self.SERVICE, recipient=recipient,
                message_preview="", timestamp=time.time(),
                error=f"unknown_tool:{recipient}",
                metadata={"expected_tools": list(EXPECTED_TOOLS)},
            )

        latency_ms = int((time.time() - t0) * 1000)
        success = 200 <= status < 300

        # Extract tokens + output preview
        tokens_in = 0
        tokens_out = 0
        output_text = ""
        model_name = params.get("model", "deepseek-chat")

        if recipient == "chat_complete" and success:
            usage = body.get("usage", {}) or {}
            tokens_in = int(usage.get("prompt_tokens", 0))
            tokens_out = int(usage.get("completion_tokens", 0))
            try:
                output_text = body["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError):
                output_text = json.dumps(body)[:1024]
        elif recipient == "embed" and success:
            usage = body.get("usage", {}) or {}
            tokens_in = int(usage.get("prompt_tokens", 0))
            try:
                output_text = f"embedding_dim={len(body['data'][0]['embedding'])}"
            except (KeyError, IndexError, TypeError):
                output_text = json.dumps(body)[:256]

        prompt_preview = ""
        if recipient == "chat_complete":
            try:
                prompt_preview = params["messages"][-1]["content"]
            except (KeyError, IndexError, TypeError):
                prompt_preview = json.dumps(params.get("messages", ""))[:200]
        elif recipient == "embed":
            prompt_preview = str(params.get("input", ""))[:200]
        else:
            prompt_preview = recipient

        crystal_id = _log_inference(recipient, model_name, prompt_preview,
                                       output_text, tokens_in, tokens_out,
                                       latency_ms, status)

        preview = output_text[:200] if output_text else (body.get("_error", "") or str(body)[:200])

        return SendResult(
            success=success, service=self.SERVICE, recipient=recipient,
            message_preview=preview, timestamp=time.time(),
            crystal_id=crystal_id,
            error="" if success else (body.get("_error", "") or f"http_{status}"),
            metadata={
                "status_code": status, "latency_ms": latency_ms,
                "model": model_name, "tokens_in": tokens_in, "tokens_out": tokens_out,
                "finish_reason": (body.get("choices", [{}])[0].get("finish_reason", "")
                                    if success and recipient == "chat_complete" else ""),
            },
        )

    def history(self, limit: int = 20) -> list:
        log_path = Path.home() / ".cc" / "third_party_logs" / "deepseek_sends.jsonl"
        if not log_path.exists():
            return []
        try:
            lines = log_path.read_text(encoding="utf-8").splitlines()[-limit:]
            return [json.loads(ln) for ln in lines if ln.strip()]
        except Exception:
            return []

    # ---- Tool implementations ----------------------------------------

    def _auth_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    def _chat_complete(self, p: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
        payload = {
            "model": p.get("model", "deepseek-chat"),
            "messages": p.get("messages") or [
                {"role": "user", "content": p.get("prompt", "")}
            ],
            "max_tokens": int(p.get("max_tokens", 256)),
            "temperature": float(p.get("temperature", 0.0)),
            "stream": False,
        }
        if p.get("system"):
            # Prepend a system message if provided
            payload["messages"] = [{"role": "system", "content": p["system"]}] + list(payload["messages"])
        return _http_post_json(f"{self._base_url}/chat/completions",
                                 payload, self._auth_headers())

    def _embed(self, p: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
        payload = {
            "model": p.get("model", "deepseek-chat"),
            "input": p.get("input", ""),
        }
        return _http_post_json(f"{self._base_url}/embeddings",
                                 payload, self._auth_headers())

    def _models_list(self) -> tuple[int, Dict[str, Any]]:
        return _http_get(f"{self._base_url}/models", self._auth_headers())


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="deepseek_mcp — DeepSeek inference connector")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("connect")
    sub.add_parser("models", help="list available models")
    p_chat = sub.add_parser("chat", help="one-shot chat completion")
    p_chat.add_argument("prompt")
    p_chat.add_argument("--model", default="deepseek-chat",
                          help="deepseek-chat | deepseek-coder | deepseek-reasoner")
    p_chat.add_argument("--max-tokens", type=int, default=200)
    p_chat.add_argument("--temperature", type=float, default=0.0)
    p_chat.add_argument("--system", default="")
    p_code = sub.add_parser("code", help="shortcut: deepseek-coder")
    p_code.add_argument("prompt")
    p_code.add_argument("--language", default="python")
    p_code.add_argument("--max-tokens", type=int, default=400)
    sub.add_parser("providers", help="list expected tools + known models")

    args = ap.parse_args()
    c = DeepSeekMCPConnector()

    if args.cmd == "connect":
        ok = c.connect()
        print(json.dumps({
            "connected": ok,
            "base_url": c._base_url,
            "has_key": bool(c._api_key),
        }, indent=2))

    elif args.cmd == "models":
        c.connect()
        r = c.send("models_list", "")
        print(json.dumps({"success": r.success, "models": r.message_preview[:500],
                            "error": r.error}, indent=2))

    elif args.cmd == "chat":
        c.connect()
        msg = json.dumps({
            "model": args.model,
            "messages": [{"role": "user", "content": args.prompt}],
            "max_tokens": args.max_tokens,
            "temperature": args.temperature,
            "system": args.system,
        })
        r = c.send("chat_complete", msg)
        print(json.dumps({
            "success": r.success,
            "model": r.metadata.get("model", ""),
            "tokens_in": r.metadata.get("tokens_in", 0),
            "tokens_out": r.metadata.get("tokens_out", 0),
            "latency_ms": r.metadata.get("latency_ms", 0),
            "finish_reason": r.metadata.get("finish_reason", ""),
            "crystal": r.crystal_id[:24] if r.crystal_id else "",
            "output": r.message_preview,
            "error": r.error,
        }, indent=2))

    elif args.cmd == "code":
        c.connect()
        system = f"You are an expert {args.language} engineer. Output only code, no markdown fences."
        msg = json.dumps({
            "model": "deepseek-coder",
            "messages": [{"role": "user", "content": args.prompt}],
            "max_tokens": args.max_tokens,
            "temperature": 0.0,
            "system": system,
        })
        r = c.send("chat_complete", msg)
        print(json.dumps({
            "success": r.success,
            "tokens_in": r.metadata.get("tokens_in", 0),
            "tokens_out": r.metadata.get("tokens_out", 0),
            "latency_ms": r.metadata.get("latency_ms", 0),
            "crystal": r.crystal_id[:24] if r.crystal_id else "",
            "code": r.message_preview,
            "error": r.error,
        }, indent=2))

    elif args.cmd == "providers":
        print(json.dumps({
            "expected_tools": list(EXPECTED_TOOLS),
            "known_models": list(KNOWN_MODELS),
            "default_base_url": DEFAULT_BASE_URL,
        }, indent=2))

    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
