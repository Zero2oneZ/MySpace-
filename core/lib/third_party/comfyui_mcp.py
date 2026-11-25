#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        comfyui_mcp
# role:        CONNECTOR · COMFYUI_HTTP_WORKFLOW_RUNNER
# tier:        L0
# substrate:   local ComfyUI HTTP API (default http://localhost:8188)
# storage:     ~/.cc/third_party_logs/comfyui_mcp_sends.jsonl + crystal chain
#              studio/assets/_bakes/<prompt_id>/<filename>  (output renders)
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.comfyui_mcp.active.json
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - core/lib/workflow_generator (when card.surfaces.comfyui present)
#   - studio_runtime._dispatch_comfy (when pass.engine='comfyui')
#   - core/cc.sh::cmd_comfy_submit / cmd_comfy_status (via send())
# outbound:
#   - http://localhost:8188/prompt          (POST submit workflow)
#   - http://localhost:8188/history/<id>    (GET poll completion)
#   - http://localhost:8188/queue           (GET overall queue state)
#   - http://localhost:8188/view            (GET download image output)
#   - http://localhost:8188/interrupt       (POST cancel running job)
#   - http://localhost:8188/object_info     (GET node registry)
#   - http://localhost:8188/system_stats    (GET probe — used by connect())
#   - inference_logger.log (tier='comfyui', scope='comfyui_<tool>')
# substrate touch:
#   - reads:  studio/assets/_comfy_workflows/<name>.json (workflow templates)
#             COMFYUI_BASE_URL env (override default :8188)
#             CC_COMFY_INSTALL env (resolve installed path; falls back)
#   - writes: studio/assets/_bakes/<prompt_id>/<filename>
#             ~/.cc/third_party_logs/comfyui_mcp_sends.jsonl
# ============================================================================
"""comfyui_mcp.py — ComfyUI HTTP API connector + crystal-anchored workflow log.

Mirrors third_party/blender_mcp.py + third_party/deepseek_mcp.py shape exactly.
SERVICE = "comfyui_mcp". Stdlib urllib only — no requests dep.

Tools (via send(recipient=tool_name, message=json_args, **kwargs)):
  - system_stats()                                       — GET /system_stats (probe)
  - submit_workflow(template_name, inputs)               — POST /prompt
  - get_status(prompt_id)                                — GET /queue
  - get_history(prompt_id)                               — GET /history/<id>
  - download_output(prompt_id, node_id, filename)        — GET /view → save to bakes
  - interrupt()                                          — POST /interrupt
  - get_node_info()                                      — GET /object_info

Convenience wrapper:
  - submit_workflow_and_wait(template_name, inputs, timeout=300)
    → submit → poll history every 1s → return completed result (bounded).

Every successful submit_workflow → crystal-anchored via
  inference_logger.log(tier='comfyui', model='comfyui',
                       scope='comfyui_submit_workflow', ...).
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_PROJECT_ROOT / "core" / "lib"))

from base import ThirdPartyConnector, ConnectionConfig, SendResult  # type: ignore  # noqa: E402

EXPECTED_TOOLS = (
    "submit_workflow",
    "get_status",
    "get_history",
    "download_output",
    "interrupt",
    "get_node_info",
    "system_stats",
)

DEFAULT_BASE_URL = "http://localhost:8188"
DEFAULT_CLIENT_ID = "mspc"
WORKFLOW_TEMPLATE_DIR = _PROJECT_ROOT / "studio" / "assets" / "_comfy_workflows"
BAKES_DIR = _PROJECT_ROOT / "studio" / "assets" / "_bakes"

# Placeholder substitution keys honored by _load_workflow_template().
TEMPLATE_PLACEHOLDERS = ("__SEED__", "__PROMPT__", "__IMAGE_PATH__", "__STRENGTH__")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_base_url() -> str:
    """Resolve the ComfyUI HTTP base URL. Order:
       1) env COMFYUI_BASE_URL
       2) workflow_generator.COMFY_INSTALL — if it imports + the path exists,
          we still default to localhost:8188 (the install path only confirms
          the server *could* be local).
       3) DEFAULT_BASE_URL
    """
    env = os.environ.get("COMFYUI_BASE_URL", "").strip()
    if env:
        return env.rstrip("/")
    try:
        from workflow_generator import COMFY_INSTALL  # type: ignore  # noqa: F401
        # COMFY_INSTALL existing only confirms local install — URL stays default.
    except Exception:
        pass
    return DEFAULT_BASE_URL.rstrip("/")


def _http_get(url: str, timeout: int = 10) -> Tuple[int, Any]:
    """GET → (status, decoded body). Body may be dict, str, or bytes."""
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            ctype = resp.headers.get("Content-Type", "")
            if "application/json" in ctype:
                try:
                    return resp.status, json.loads(raw.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    return resp.status, {"_raw": raw.decode("utf-8", errors="replace")[:8192]}
            # Treat anything else as raw bytes — callers handle (image/video etc.)
            return resp.status, raw
    except urllib.error.HTTPError as e:
        try:
            body_txt = e.read().decode("utf-8", errors="replace")
            return e.code, {"_error": body_txt[:2048]}
        except Exception:
            return e.code, {"_error": str(e)}
    except Exception as e:
        return 0, {"_error": f"{type(e).__name__}: {e}"}


def _http_post_json(url: str, payload: Dict[str, Any], timeout: int = 30) -> Tuple[int, Any]:
    """POST application/json → (status, decoded body)."""
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, {"_raw": raw[:8192]}
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


def _http_post_empty(url: str, timeout: int = 10) -> Tuple[int, Any]:
    """POST with empty body — used for /interrupt."""
    req = urllib.request.Request(url, data=b"", method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, ({"ok": True} if not raw.strip() else
                                  (json.loads(raw) if raw.strip().startswith("{") else {"_raw": raw[:2048]}))
    except urllib.error.HTTPError as e:
        return e.code, {"_error": str(e)}
    except Exception as e:
        return 0, {"_error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------------------
# Workflow template loader
# ---------------------------------------------------------------------------

def _load_workflow_template(name: str, inputs: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    """Read studio/assets/_comfy_workflows/<name>.json and substitute placeholders.

    Substitutes the canonical TEMPLATE_PLACEHOLDERS from `inputs` dict, where the
    dict keys are placeholder names *without* the surrounding underscores
    (e.g. inputs={'SEED': 1234, 'PROMPT': 'a cat'} → __SEED__ → '1234',
    __PROMPT__ → 'a cat').

    Returns (workflow_dict, error_str). On success, error_str is empty.
    On any failure (missing dir, missing file, bad JSON), returns ({}, reason).
    """
    if not WORKFLOW_TEMPLATE_DIR.exists():
        return {}, f"workflow_template_dir_missing:{WORKFLOW_TEMPLATE_DIR}"
    tmpl_path = WORKFLOW_TEMPLATE_DIR / f"{name}.json"
    if not tmpl_path.exists():
        return {}, f"workflow_template_not_found:{tmpl_path.name}"
    try:
        raw = tmpl_path.read_text(encoding="utf-8")
    except Exception as e:
        return {}, f"workflow_template_read_failed:{type(e).__name__}:{e}"

    # Substitute placeholders as STRING substitution before JSON parse — keeps
    # the template valid JSON across types (numbers, strings, paths all OK).
    for ph in TEMPLATE_PLACEHOLDERS:
        # Strip leading/trailing underscores to derive the input key.
        key = ph.strip("_")
        if key in inputs:
            raw = raw.replace(ph, str(inputs[key]))
        elif key.lower() in inputs:
            raw = raw.replace(ph, str(inputs[key.lower()]))

    try:
        workflow = json.loads(raw)
    except json.JSONDecodeError as e:
        return {}, f"workflow_template_invalid_after_substitution:{e}"
    if not isinstance(workflow, dict):
        return {}, "workflow_template_not_object"
    return workflow, ""


# ---------------------------------------------------------------------------
# Crystal-chain logging
# ---------------------------------------------------------------------------

def _log_inference(tool: str, template_name: str, prompt_id: str,
                     latency_ms: int, status_code: int,
                     extra: Optional[Dict[str, Any]] = None) -> str:
    try:
        from inference_logger import InferenceLogger  # type: ignore
        il = InferenceLogger()
        return il.log(
            original_prompt=template_name,
            enhanced_prompt=f"comfyui.{tool}",
            output_text=prompt_id,
            tier="comfyui",
            model="comfyui",
            scope=f"comfyui_{tool}",
            latency_ms=latency_ms,
            source_action=f"comfyui.{tool}",
            done_flag=(status_code == 200),
            rc=0 if (200 <= status_code < 300) else 1,
        ) or ""
    except Exception as e:
        sys.stderr.write(f"warn: comfyui crystal log failed: {type(e).__name__}: {e}\n")
        return ""


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------

class ComfyUIMCPConnector(ThirdPartyConnector):
    """ComfyUI HTTP API connector. Probes /system_stats on connect()."""

    SERVICE = "comfyui_mcp"

    def __init__(self, config: Optional[ConnectionConfig] = None):
        if config is None:
            config = ConnectionConfig(
                service=self.SERVICE,
                name="comfyui_default",
                action="submit_workflow",
            )
        super().__init__(config)
        self._base_url: str = _resolve_base_url()
        self._client_id: str = DEFAULT_CLIENT_ID
        self._connected: bool = False
        self._connect_attempted: bool = False
        self._connect_error: str = ""

    # ---- lifecycle -------------------------------------------------

    def connect(self) -> bool:
        """Probe GET /system_stats with 2s timeout. Cached per-instance."""
        if self._connect_attempted:
            return self._connected
        self._connect_attempted = True
        status, body = _http_get(f"{self._base_url}/system_stats", timeout=2)
        if status == 200:
            self._connected = True
            self._connect_error = ""
        else:
            self._connected = False
            err = ""
            if isinstance(body, dict):
                err = body.get("_error", "") or ""
            self._connect_error = f"comfyui_not_running (status={status} {err[:120]})"
        return self._connected

    def disconnect(self) -> None:
        self._connected = False
        self._connect_attempted = False

    # ---- main op (tool invocation) ---------------------------------

    def send(self, recipient: str, message: str = "", **kwargs) -> SendResult:
        ts = time.time()
        # Probe once. If never attempted, attempt now. If attempted+failed,
        # return graceful skipped result without re-probing.
        if not self._connect_attempted:
            self.connect()
        if not self._connected:
            return SendResult(
                success=False,
                crystal_id="",
                service=self.SERVICE,
                recipient=recipient,
                message_preview="",
                timestamp=ts,
                error="comfyui_not_running",
                metadata={"base_url": self._base_url, "detail": self._connect_error},
            )

        # Parse args.
        params: Dict[str, Any] = {}
        if message:
            try:
                params = json.loads(message)
            except json.JSONDecodeError:
                params = {"raw": message}
        if isinstance(params, dict):
            params.update(kwargs)
        else:
            params = {"raw": params, **kwargs}

        t0 = time.time()
        try:
            if recipient == "system_stats":
                status, body = self._system_stats()
            elif recipient == "submit_workflow":
                status, body = self._submit_workflow(params)
            elif recipient == "get_history":
                status, body = self._get_history(params)
            elif recipient == "get_status":
                status, body = self._get_status(params)
            elif recipient == "download_output":
                status, body = self._download_output(params)
            elif recipient == "interrupt":
                status, body = self._interrupt()
            elif recipient == "get_node_info":
                status, body = self._get_node_info()
            else:
                return SendResult(
                    success=False,
                    crystal_id="",
                    service=self.SERVICE,
                    recipient=recipient,
                    message_preview="",
                    timestamp=time.time(),
                    error=f"unknown_tool:{recipient}",
                    metadata={"expected_tools": list(EXPECTED_TOOLS)},
                )
        except Exception as e:
            return SendResult(
                success=False,
                crystal_id="",
                service=self.SERVICE,
                recipient=recipient,
                message_preview="",
                timestamp=time.time(),
                error=f"{type(e).__name__}: {e}",
                metadata={"base_url": self._base_url},
            )

        latency_ms = int((time.time() - t0) * 1000)
        success = 200 <= status < 300

        # Build preview + metadata
        preview = ""
        meta: Dict[str, Any] = {"status_code": status, "latency_ms": latency_ms,
                                "base_url": self._base_url}
        prompt_id_for_log = ""

        if recipient == "submit_workflow" and success and isinstance(body, dict):
            prompt_id = body.get("prompt_id", "") or body.get("promptId", "")
            meta["prompt_id"] = prompt_id
            meta["number"] = body.get("number", "")
            meta["node_errors"] = body.get("node_errors", {})
            preview = f"prompt_id={prompt_id}"
            prompt_id_for_log = prompt_id
        elif recipient == "download_output" and success and isinstance(body, dict):
            meta["saved_path"] = body.get("saved_path", "")
            meta["bytes"] = body.get("bytes", 0)
            preview = f"saved={body.get('saved_path','')} ({body.get('bytes',0)} bytes)"
        elif isinstance(body, dict):
            preview = json.dumps(body, default=str)[:240]
        elif isinstance(body, bytes):
            preview = f"<bytes:{len(body)}>"
        else:
            preview = str(body)[:240]

        # Crystal anchor for submit_workflow successes.
        crystal_id = ""
        if recipient == "submit_workflow" and success:
            crystal_id = _log_inference(
                tool=recipient,
                template_name=str(params.get("template_name", "")),
                prompt_id=prompt_id_for_log,
                latency_ms=latency_ms,
                status_code=status,
            )

        err = ""
        if not success:
            if isinstance(body, dict):
                err = body.get("_error", "") or f"http_{status}"
            else:
                err = f"http_{status}"

        result = SendResult(
            success=success,
            crystal_id=crystal_id,
            service=self.SERVICE,
            recipient=recipient,
            message_preview=preview,
            timestamp=time.time(),
            error=err,
            metadata=meta,
        )
        return result

    def history(self, limit: int = 20) -> list:
        log_path = Path.home() / ".cc" / "third_party_logs" / f"{self.SERVICE}_sends.jsonl"
        if not log_path.exists():
            return []
        try:
            lines = log_path.read_text(encoding="utf-8").splitlines()[-limit:]
            return [json.loads(ln) for ln in lines if ln.strip()]
        except Exception:
            return []

    # ---- convenience wrapper ---------------------------------------

    def submit_workflow_and_wait(self, template_name: str, inputs: Dict[str, Any],
                                   timeout: int = 300, poll_interval: float = 1.0) -> SendResult:
        """Submit → poll get_history every `poll_interval`s → return when done.

        Bounded by `timeout` seconds. Returns the final SendResult — success=True
        when /history/<prompt_id> reports a non-empty entry with status indicating
        completion (or any non-empty record after timeout grace).
        """
        submit = self.send("submit_workflow",
                            json.dumps({"template_name": template_name, "inputs": inputs}))
        if not submit.success:
            return submit
        prompt_id = (submit.metadata or {}).get("prompt_id", "")
        if not prompt_id:
            return SendResult(
                success=False, crystal_id="",
                service=self.SERVICE, recipient="submit_workflow_and_wait",
                message_preview="", timestamp=time.time(),
                error="no_prompt_id_in_submit_response",
                metadata={"submit_metadata": submit.metadata},
            )

        deadline = time.time() + max(timeout, 1)
        last_status: Optional[SendResult] = None
        while time.time() < deadline:
            poll = self.send("get_history", json.dumps({"prompt_id": prompt_id}))
            last_status = poll
            if poll.success:
                meta = poll.metadata or {}
                # ComfyUI /history/<id> returns {} until complete, then a non-empty dict.
                if meta.get("complete"):
                    return poll
            time.sleep(max(poll_interval, 0.1))

        return last_status or SendResult(
            success=False, crystal_id="",
            service=self.SERVICE, recipient="submit_workflow_and_wait",
            message_preview="", timestamp=time.time(),
            error="timeout_waiting_for_completion",
            metadata={"prompt_id": prompt_id, "timeout_s": timeout},
        )

    # ---- tool implementations --------------------------------------

    def _system_stats(self) -> Tuple[int, Any]:
        return _http_get(f"{self._base_url}/system_stats", timeout=5)

    def _submit_workflow(self, p: Dict[str, Any]) -> Tuple[int, Any]:
        template_name = p.get("template_name", "")
        inputs = p.get("inputs", {}) or {}
        if not template_name:
            return 400, {"_error": "missing template_name"}
        workflow, err = _load_workflow_template(template_name, inputs)
        if err:
            return 400, {"_error": err}
        payload = {"prompt": workflow, "client_id": self._client_id}
        return _http_post_json(f"{self._base_url}/prompt", payload, timeout=30)

    def _get_history(self, p: Dict[str, Any]) -> Tuple[int, Any]:
        prompt_id = p.get("prompt_id", "")
        if not prompt_id:
            return 400, {"_error": "missing prompt_id"}
        status, body = _http_get(f"{self._base_url}/history/{prompt_id}", timeout=10)
        # Wrap so the caller (send/metadata) can read a `complete` flag.
        if status == 200 and isinstance(body, dict):
            complete = bool(body and body.get(prompt_id))
            wrapped = {"prompt_id": prompt_id, "complete": complete, "history": body}
            return status, wrapped
        return status, body

    def _get_status(self, p: Dict[str, Any]) -> Tuple[int, Any]:
        # Overall queue. Optionally annotate this prompt's position if given.
        prompt_id = p.get("prompt_id", "")
        status, body = _http_get(f"{self._base_url}/queue", timeout=5)
        if status == 200 and prompt_id and isinstance(body, dict):
            pos = None
            running = body.get("queue_running", []) or []
            pending = body.get("queue_pending", []) or []
            # ComfyUI queue entries are [number, prompt_id, prompt, extra, outputs]
            for i, entry in enumerate(pending):
                try:
                    if entry and entry[1] == prompt_id:
                        pos = i
                        break
                except Exception:
                    continue
            wrapped = {
                "prompt_id": prompt_id,
                "position_in_pending": pos,
                "running_count": len(running),
                "pending_count": len(pending),
                "queue": body,
            }
            return status, wrapped
        return status, body

    def _download_output(self, p: Dict[str, Any]) -> Tuple[int, Any]:
        prompt_id = p.get("prompt_id", "")
        filename = p.get("filename", "")
        if not prompt_id or not filename:
            return 400, {"_error": "missing prompt_id or filename"}
        # ComfyUI uses /view?filename=<f>&type=output (subfolder optional).
        qs = urllib.parse.urlencode({
            "filename": filename,
            "type": p.get("type", "output"),
            "subfolder": p.get("subfolder", ""),
        })
        url = f"{self._base_url}/view?{qs}"
        status, body = _http_get(url, timeout=60)
        if status != 200 or not isinstance(body, (bytes, bytearray)):
            # If JSON came back it'll be an error wrapper.
            if isinstance(body, dict):
                return status, body
            return status, {"_error": f"unexpected_body_type:{type(body).__name__}"}
        # Save to studio/assets/_bakes/<prompt_id>/<filename>
        try:
            out_dir = BAKES_DIR / prompt_id
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / Path(filename).name
            out_path.write_bytes(body)
            return status, {
                "saved_path": str(out_path),
                "bytes": len(body),
                "node_id": p.get("node_id", ""),
                "prompt_id": prompt_id,
            }
        except Exception as e:
            return 500, {"_error": f"write_failed:{type(e).__name__}:{e}"}

    def _interrupt(self) -> Tuple[int, Any]:
        return _http_post_empty(f"{self._base_url}/interrupt", timeout=5)

    def _get_node_info(self) -> Tuple[int, Any]:
        return _http_get(f"{self._base_url}/object_info", timeout=15)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="comfyui_mcp — ComfyUI HTTP connector")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("connect")
    sub.add_parser("stats", help="GET /system_stats")
    sub.add_parser("queue", help="GET /queue")
    p_hist = sub.add_parser("history", help="GET /history/<prompt_id>")
    p_hist.add_argument("prompt_id")
    p_sub = sub.add_parser("submit", help="submit workflow template")
    p_sub.add_parser_args = None  # placeholder to silence linters in some envs
    p_sub.add_argument("template_name")
    p_sub.add_argument("--inputs", default="{}", help="JSON dict of placeholders")
    sub.add_parser("interrupt")
    sub.add_parser("nodes", help="GET /object_info")
    sub.add_parser("providers", help="list expected tools + base url")

    args = ap.parse_args()
    c = ComfyUIMCPConnector()

    if args.cmd == "connect":
        ok = c.connect()
        print(json.dumps({
            "connected": ok,
            "base_url": c._base_url,
            "error": c._connect_error,
        }, indent=2))
    elif args.cmd == "stats":
        r = c.send("system_stats", "")
        print(json.dumps({"success": r.success, "preview": r.message_preview[:400],
                          "error": r.error}, indent=2))
    elif args.cmd == "queue":
        r = c.send("get_status", "")
        print(json.dumps({"success": r.success, "preview": r.message_preview[:400],
                          "error": r.error}, indent=2))
    elif args.cmd == "history":
        r = c.send("get_history", json.dumps({"prompt_id": args.prompt_id}))
        print(json.dumps({"success": r.success, "preview": r.message_preview[:400],
                          "error": r.error, "metadata": r.metadata}, indent=2))
    elif args.cmd == "submit":
        try:
            inputs = json.loads(args.inputs)
        except json.JSONDecodeError:
            inputs = {}
        r = c.send("submit_workflow", json.dumps({
            "template_name": args.template_name,
            "inputs": inputs,
        }))
        print(json.dumps({
            "success": r.success, "preview": r.message_preview[:400],
            "error": r.error, "crystal": r.crystal_id[:24] if r.crystal_id else "",
            "metadata": r.metadata,
        }, indent=2))
    elif args.cmd == "interrupt":
        r = c.send("interrupt", "")
        print(json.dumps({"success": r.success, "preview": r.message_preview[:200],
                          "error": r.error}, indent=2))
    elif args.cmd == "nodes":
        r = c.send("get_node_info", "")
        # Compress preview — node_info is HUGE
        print(json.dumps({"success": r.success, "preview_len": len(r.message_preview),
                          "error": r.error}, indent=2))
    elif args.cmd == "providers":
        print(json.dumps({
            "expected_tools": list(EXPECTED_TOOLS),
            "base_url": c._base_url,
            "template_dir": str(WORKFLOW_TEMPLATE_DIR),
            "bakes_dir": str(BAKES_DIR),
        }, indent=2))
    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
