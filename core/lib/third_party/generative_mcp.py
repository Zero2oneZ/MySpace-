#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        generative_mcp
# role:        META-CONNECTOR · GENERATIVE_FANOUT
# tier:        L0
# substrate:   single front-door for every generative modality. Does NOT call
#              external services itself — fans out to sibling connectors that
#              ARE already wired (ModelAPI, DeepSeek, ComfyUI, Replit bridge).
# storage:     ~/.cc/third_party_logs/generative_mcp_sends.jsonl + crystal chain
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.generative_mcp.active.json
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - studio_runtime when pass.engine='generative'
#   - core/cc.sh::cmd_generative_*  (future)
#   - Replit-deployed apps via the unified bridge
# outbound (FAN-OUT — every tool dispatches to a sibling):
#   - generate_text  → core/lib/model_api.py::ModelAPI.text(...)
#   - generate_code  → core/lib/model_api.py::ModelAPI.code(...)
#   - generate_card  → ModelAPI.text(...) + JSON validation + filesystem write
#   - generate_image → third_party/comfyui_mcp.py (graceful if missing)
#   - generate_3d    → TEXT-PLACEHOLDER until autonomous_modeler (Phase B.3)
#   - generate_app   → studio/mcp/replit-bridge POST /mcp/call (port 8765)
# substrate touch:
#   - reads:   nothing directly (subordinate connectors read .env / keys)
#   - writes:  inference_logger.log (tier='generative', model='generative_mcp')
#              + studio/assets/_workflows|_products|_agents/agent_defs/*.json
# ============================================================================
"""generative_mcp.py — meta-connector that fans out to other connectors.

Mirrors third_party/stripe_mcp.py / deepseek_mcp.py shape. SERVICE = "generative_mcp".
Stdlib only — urllib for the replit-bridge POST.

Tools (via send(recipient=tool_name, message=json_args, **kwargs)):
  - generate_text(prompt, max_tokens=256, cost_class='cheap')
  - generate_code(prompt, language='python', max_tokens=400)
  - generate_card(prompt, kind='workflow'|'product'|'agent_def')
  - generate_image(prompt, size='1024x1024')
  - generate_3d(prompt, max_iter=2)  — PLACEHOLDER for v1
  - generate_app(card_slug, target='replit')

Every successful call crystal-anchors via inference_logger.log:
    tier='generative'
    model='generative_mcp'
    scope=f'generative_<tool>'
The downstream sub-call's crystal_id is preserved in metadata.sub_crystal so
the fan-out chain stays traceable.

Graceful imports: every subordinate connector is loaded behind try/except.
which_tools_available() reports which tools can actually fire right now.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_PROJECT_ROOT / "core" / "lib"))

from base import ThirdPartyConnector, ConnectionConfig, SendResult  # type: ignore  # noqa: E402

EXPECTED_TOOLS = (
    "generate_text",
    "generate_code",
    "generate_card",
    "generate_image",
    "generate_3d",
    "generate_app",
)

# Where generate_card lands per kind.
KIND_DIR = {
    "workflow":  "_workflows",
    "product":   "_products",
    "agent_def": "_agents/agent_defs",
}

REPLIT_BRIDGE_URL = os.environ.get("REPLIT_BRIDGE_URL", "http://localhost:8765/mcp/call")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _http_post_json(url: str, payload: Dict[str, Any], timeout: int = 60
                     ) -> Tuple[int, Dict[str, Any]]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST",
                                    headers={"Content-Type": "application/json"})
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
    except urllib.error.URLError as e:
        return 0, {"_error": f"url_error:{e.reason}"}
    except Exception as e:
        return 0, {"_error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------------------
# Graceful subordinate imports — each behind try/except so a missing sibling
# never breaks the whole connector.
# ---------------------------------------------------------------------------

def _try_import_model_api():
    try:
        from model_api import ModelAPI  # type: ignore
        return ModelAPI, ""
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _try_import_comfyui():
    try:
        from third_party.comfyui_mcp import ComfyUIMCPConnector  # type: ignore
        return ComfyUIMCPConnector, ""
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _try_import_deepseek():
    try:
        from third_party.deepseek_mcp import DeepSeekMCPConnector  # type: ignore
        return DeepSeekMCPConnector, ""
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _try_import_blender():
    try:
        from third_party.blender_mcp import BlenderMCPConnector  # type: ignore
        return BlenderMCPConnector, ""
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _try_import_pinterest():
    try:
        from third_party.pinterest import PinterestConnector  # type: ignore
        return PinterestConnector, ""
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _try_import_hf_hub():
    try:
        from hf_hub import inference as _hf_inference  # type: ignore
        return _hf_inference, ""
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Crystal-chain logging
# ---------------------------------------------------------------------------

def _log_generative(tool: str, prompt_preview: str, output: str,
                     sub_crystal: str, latency_ms: int,
                     success: bool) -> str:
    try:
        from inference_logger import InferenceLogger  # type: ignore
        il = InferenceLogger()
        return il.log(
            original_prompt=prompt_preview[:512],
            enhanced_prompt=f"generative_mcp.{tool}",
            output_text=output[:1024],
            tier="generative",
            model="generative_mcp",
            scope=f"generative_{tool}",
            tokens_in=0,
            tokens_out=0,
            latency_ms=latency_ms,
            source_action=f"generative_mcp.{tool}",
            forward_chain_inline=sub_crystal or "",
            done_flag=success,
            rc=0 if success else 1,
        ) or ""
    except Exception as e:
        sys.stderr.write(f"warn: generative crystal log failed: {type(e).__name__}: {e}\n")
        return ""


# ---------------------------------------------------------------------------
# Connector class
# ---------------------------------------------------------------------------

class GenerativeMCPConnector(ThirdPartyConnector):
    """Meta-connector. Fans out to every other generative substrate sibling."""

    SERVICE = "generative_mcp"

    def __init__(self, config: Optional[ConnectionConfig] = None):
        if config is None:
            config = ConnectionConfig(service=self.SERVICE, name="generative_default",
                                         action="meta_fanout")
        super().__init__(config)
        self._connected = False
        # Lazily-instantiated subordinates
        self._model_api = None
        self._comfyui = None
        self._deepseek = None
        self._blender = None
        self._pinterest = None
        self._hf_inference = None
        self._import_errors: Dict[str, str] = {}

    # ---- ThirdPartyConnector lifecycle ----------------------------------

    def connect(self) -> bool:
        """Probe each subordinate import lazily. Always returns True — the
        meta-connector itself has no auth surface. Per-tool readiness is
        reported via which_tools_available()."""
        # Pre-warm imports so which_tools_available has accurate state.
        for name, fn in (
            ("model_api",  _try_import_model_api),
            ("comfyui",    _try_import_comfyui),
            ("deepseek",   _try_import_deepseek),
            ("blender",    _try_import_blender),
            ("pinterest",  _try_import_pinterest),
            ("hf_hub",     _try_import_hf_hub),
        ):
            _, err = fn()
            if err:
                self._import_errors[name] = err
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False

    def which_tools_available(self) -> Dict[str, Any]:
        """Report which subordinate connectors imported cleanly and therefore
        which tools can actually fire."""
        if not self._connected:
            self.connect()
        ModelAPI, ma_err = _try_import_model_api()
        ComfyUI, cf_err = _try_import_comfyui()
        DeepSeek, ds_err = _try_import_deepseek()
        Blender, bl_err = _try_import_blender()
        Pinterest, pn_err = _try_import_pinterest()
        hf, hf_err = _try_import_hf_hub()
        return {
            "subordinates": {
                "model_api":  {"available": ModelAPI is not None, "error": ma_err},
                "comfyui":    {"available": ComfyUI  is not None, "error": cf_err},
                "deepseek":   {"available": DeepSeek is not None, "error": ds_err},
                "blender":    {"available": Blender  is not None, "error": bl_err},
                "pinterest":  {"available": Pinterest is not None, "error": pn_err},
                "hf_hub":     {"available": hf is not None, "error": hf_err},
                "replit_bridge_url": REPLIT_BRIDGE_URL,
            },
            "tools": {
                "generate_text":  ModelAPI is not None,
                "generate_code":  ModelAPI is not None,
                "generate_card":  ModelAPI is not None,
                "generate_image": ComfyUI is not None,
                "generate_3d":    True,   # Blender MCP modeler (runtime-gated at call)
                "generate_app":   True,   # checked at call-time
            },
        }

    def history(self, limit: int = 20) -> list:
        log_path = Path.home() / ".cc" / "third_party_logs" / "generative_mcp_sends.jsonl"
        if not log_path.exists():
            return []
        try:
            lines = log_path.read_text(encoding="utf-8").splitlines()[-limit:]
            return [json.loads(ln) for ln in lines if ln.strip()]
        except Exception:
            return []

    def send(self, recipient: str, message: str = "", **kwargs) -> SendResult:
        if not self._connected:
            self.connect()
        params: Dict[str, Any] = {}
        if message:
            try:
                params = json.loads(message)
            except json.JSONDecodeError:
                params = {"prompt": message}
        params.update(kwargs)

        t0 = time.time()
        if recipient == "generate_text":
            result = self._generate_text(params)
        elif recipient == "generate_code":
            result = self._generate_code(params)
        elif recipient == "generate_card":
            result = self._generate_card(params)
        elif recipient == "generate_image":
            result = self._generate_image(params)
        elif recipient == "generate_3d":
            result = self._generate_3d(params)
        elif recipient == "generate_app":
            result = self._generate_app(params)
        else:
            return SendResult(
                success=False, service=self.SERVICE, recipient=recipient,
                message_preview="", timestamp=_now_iso(), crystal_id="",
                error=f"unknown_tool:{recipient}",
                metadata={"expected_tools": list(EXPECTED_TOOLS)},
            )

        latency_ms = int((time.time() - t0) * 1000)
        prompt_preview = str(params.get("prompt", "") or params.get("card_slug", ""))[:200]
        sub_crystal = (result.metadata or {}).get("sub_crystal", "") if result else ""
        crystal_id = _log_generative(
            recipient, prompt_preview, result.message_preview,
            sub_crystal, latency_ms, result.success,
        )

        # Patch in our crystal_id + service + final latency on the SendResult.
        result.crystal_id = crystal_id
        result.service = self.SERVICE
        result.recipient = recipient
        if not result.timestamp:
            result.timestamp = _now_iso()
        meta = dict(result.metadata or {})
        meta.setdefault("latency_ms_total", latency_ms)
        result.metadata = meta
        return result

    # ---- Tool implementations ------------------------------------------

    def _generate_text(self, p: Dict[str, Any]) -> SendResult:
        ModelAPI, err = _try_import_model_api()
        if ModelAPI is None:
            return SendResult(
                success=False, service=self.SERVICE, recipient="generate_text",
                message_preview="", timestamp=_now_iso(), crystal_id="",
                error=f"model_api_unavailable: {err}", metadata={},
            )
        prompt = str(p.get("prompt", ""))
        max_tokens = int(p.get("max_tokens", 256))
        cost_class = str(p.get("cost_class", "cheap"))
        api = self._model_api or ModelAPI()
        self._model_api = api
        r = api.text(prompt=prompt, max_tokens=max_tokens, cost_class=cost_class)
        return SendResult(
            success=bool(r.ok),
            service=self.SERVICE, recipient="generate_text",
            message_preview=(r.output or "")[:400],
            timestamp=_now_iso(),
            crystal_id="",  # filled by send()
            error="" if r.ok else (r.error or "model_api_failed"),
            metadata={
                "sub_crystal": r.crystal or "",
                "provider": r.provider,
                "model": r.model,
                "tokens_in": r.tokens_in,
                "tokens_out": r.tokens_out,
                "sub_latency_ms": r.latency_ms,
                "attempts": r.attempts,
            },
        )

    def _generate_code(self, p: Dict[str, Any]) -> SendResult:
        ModelAPI, err = _try_import_model_api()
        if ModelAPI is None:
            return SendResult(
                success=False, service=self.SERVICE, recipient="generate_code",
                message_preview="", timestamp=_now_iso(), crystal_id="",
                error=f"model_api_unavailable: {err}", metadata={},
            )
        prompt = str(p.get("prompt", ""))
        language = str(p.get("language", "python"))
        max_tokens = int(p.get("max_tokens", 400))
        api = self._model_api or ModelAPI()
        self._model_api = api
        r = api.code(prompt=prompt, language=language, max_tokens=max_tokens)
        return SendResult(
            success=bool(r.ok),
            service=self.SERVICE, recipient="generate_code",
            message_preview=(r.output or "")[:400],
            timestamp=_now_iso(),
            crystal_id="",
            error="" if r.ok else (r.error or "model_api_failed"),
            metadata={
                "sub_crystal": r.crystal or "",
                "provider": r.provider,
                "model": r.model,
                "language": language,
                "tokens_in": r.tokens_in,
                "tokens_out": r.tokens_out,
                "sub_latency_ms": r.latency_ms,
            },
        )

    def _generate_card(self, p: Dict[str, Any]) -> SendResult:
        """Ask ModelAPI for a strict JSON card, validate, write to disk."""
        ModelAPI, err = _try_import_model_api()
        if ModelAPI is None:
            return SendResult(
                success=False, service=self.SERVICE, recipient="generate_card",
                message_preview="", timestamp=_now_iso(), crystal_id="",
                error=f"model_api_unavailable: {err}", metadata={},
            )
        prompt = str(p.get("prompt", ""))
        kind = str(p.get("kind", "workflow"))
        if kind not in KIND_DIR:
            return SendResult(
                success=False, service=self.SERVICE, recipient="generate_card",
                message_preview="", timestamp=_now_iso(), crystal_id="",
                error=f"unknown_kind:{kind} (expected one of {list(KIND_DIR)})",
                metadata={},
            )

        system = (
            "You generate a single JSON document, nothing else. "
            "No prose, no markdown fences, no commentary — just one JSON object "
            f"matching the {kind} card schema. Keys must be double-quoted. "
            "Include at minimum: _schema, vm_id ('vm_mspc_001'), name, "
            "domain, category, state ('active'), version ('v0'), summary."
        )
        # Compose into the prompt as a system primer up-front.
        full_prompt = f"[system]\n{system}\n[/system]\n\n{prompt}"
        api = self._model_api or ModelAPI()
        self._model_api = api
        r = api.text(prompt=full_prompt, max_tokens=int(p.get("max_tokens", 800)),
                       cost_class="cheap")
        if not r.ok:
            return SendResult(
                success=False, service=self.SERVICE, recipient="generate_card",
                message_preview="", timestamp=_now_iso(), crystal_id="",
                error=f"model_api_failed: {r.error}",
                metadata={"sub_crystal": r.crystal or "", "attempts": r.attempts},
            )

        raw = (r.output or "").strip()
        # Strip common markdown fences if the model ignored instructions.
        if raw.startswith("```"):
            raw = raw.strip("`")
            # often ```json\n...\n```
            if raw.lower().startswith("json"):
                raw = raw[4:]
            raw = raw.strip("`").strip()
        # Slice between first '{' and matching last '}' to be forgiving.
        if "{" in raw and "}" in raw:
            start = raw.index("{")
            end = raw.rfind("}") + 1
            raw = raw[start:end]

        try:
            card = json.loads(raw)
        except json.JSONDecodeError as je:
            return SendResult(
                success=False, service=self.SERVICE, recipient="generate_card",
                message_preview=raw[:200], timestamp=_now_iso(), crystal_id="",
                error=f"invalid_json_from_model: {je}",
                metadata={"sub_crystal": r.crystal or "",
                            "raw_output_preview": raw[:400]},
            )

        crystal_short = (r.crystal or "")[:8] or hex(int(time.time() * 1000))[2:10]
        # Filesystem name; 'workflow' kind → '_workflows' dir, etc.
        dir_name = KIND_DIR[kind]
        out_dir = _PROJECT_ROOT / "studio" / "assets" / dir_name
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"generated_{crystal_short}.json"
        try:
            out_path.write_text(json.dumps(card, indent=2), encoding="utf-8")
        except OSError as oe:
            return SendResult(
                success=False, service=self.SERVICE, recipient="generate_card",
                message_preview=str(out_path), timestamp=_now_iso(), crystal_id="",
                error=f"write_failed: {oe}",
                metadata={"sub_crystal": r.crystal or "",
                            "card_preview": json.dumps(card)[:400]},
            )

        return SendResult(
            success=True, service=self.SERVICE, recipient="generate_card",
            message_preview=str(out_path),
            timestamp=_now_iso(),
            crystal_id="",
            error="",
            metadata={
                "sub_crystal": r.crystal or "",
                "kind": kind,
                "out_path": str(out_path),
                "card_name": card.get("name", ""),
                "card_keys": sorted(list(card.keys()))[:20],
            },
        )

    def _generate_image(self, p: Dict[str, Any]) -> SendResult:
        ComfyUI, err = _try_import_comfyui()
        if ComfyUI is None:
            return SendResult(
                success=False, service=self.SERVICE, recipient="generate_image",
                message_preview="", timestamp=_now_iso(), crystal_id="",
                error="comfyui_not_available",
                metadata={"import_error": err},
            )
        try:
            c = self._comfyui or ComfyUI()
            self._comfyui = c
            # Standard pattern: connect first
            try:
                c.connect()
            except Exception:
                pass
            prompt = str(p.get("prompt", ""))
            sub = None
            # Prefer the named entrypoint per task spec; fall back to send().
            if hasattr(c, "submit_workflow_and_wait"):
                sub = c.submit_workflow_and_wait("text_to_image", {"prompt": prompt})
            elif hasattr(c, "send"):
                sub = c.send("text_to_image", json.dumps({"prompt": prompt}))
            else:
                return SendResult(
                    success=False, service=self.SERVICE, recipient="generate_image",
                    message_preview="", timestamp=_now_iso(), crystal_id="",
                    error="comfyui_no_workflow_entrypoint", metadata={},
                )
        except Exception as e:
            return SendResult(
                success=False, service=self.SERVICE, recipient="generate_image",
                message_preview="", timestamp=_now_iso(), crystal_id="",
                error=f"comfyui_call_failed: {type(e).__name__}: {e}",
                metadata={},
            )

        # Normalize the sub-result: most connectors return SendResult-like.
        success = bool(getattr(sub, "success", False))
        preview = str(getattr(sub, "message_preview", "") or "")[:400]
        err_str = getattr(sub, "error", "") or ""
        meta = dict(getattr(sub, "metadata", None) or {})
        meta["sub_crystal"] = getattr(sub, "crystal_id", "") or ""
        meta["size"] = p.get("size", "1024x1024")
        return SendResult(
            success=success, service=self.SERVICE, recipient="generate_image",
            message_preview=preview, timestamp=_now_iso(),
            crystal_id="", error=err_str, metadata=meta,
        )

    # prompt-word → Blender primitive (the Claude-as-modeler v1 heuristic).
    _PRIM_WORDS = {
        "sphere": "sphere", "ball": "sphere", "globe": "sphere", "orb": "sphere",
        "cube": "cube", "box": "cube", "block": "cube",
        "cylinder": "cylinder", "tube": "cylinder", "pillar": "cylinder",
        "cone": "cone", "pyramid": "cone",
        "torus": "torus", "donut": "torus", "ring": "torus",
        "monkey": "monkey", "head": "monkey", "suzanne": "monkey",
        "plane": "plane", "floor": "plane", "ground": "plane",
    }
    _COLOR_WORDS = {
        "red": [0.85, 0.12, 0.1, 1], "green": [0.13, 0.8, 0.3, 1],
        "blue": [0.15, 0.35, 0.9, 1], "gold": [1.0, 0.78, 0.0, 1],
        "white": [0.92, 0.92, 0.92, 1], "black": [0.04, 0.04, 0.05, 1],
        "purple": [0.6, 0.2, 0.9, 1], "orange": [1.0, 0.5, 0.05, 1],
    }

    def _generate_3d(self, p: Dict[str, Any]) -> SendResult:
        """Claude-as-modeler v1: prompt → Blender mesh + material → GLB, then
        announce the asset to the Godot SSOT inbound bridge so it appears
        in-engine. Build-safe + graceful: if the Blender runtime isn't present,
        returns success=False with a clear note (no crash, no cost)."""
        import os
        import time as _t
        from pathlib import Path as _P
        prompt = str(p.get("prompt", "")).lower()
        words = set(prompt.replace(",", " ").split())
        prim = next((self._PRIM_WORDS[w] for w in words if w in self._PRIM_WORDS), "cube")
        color = next((self._COLOR_WORDS[w] for w in words if w in self._COLOR_WORDS),
                     [0.8, 0.8, 0.8, 1])
        home = _P(os.environ.get("CC_HOME", str(_P.home() / ".cc")))
        out_dir = home / "gen3d"
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = f"gen3d_{int(_t.time())}_{prim}"
        glb = out_dir / f"{stem}.glb"

        # Drive Blender via the MCP connector (reuses the stdio wrapper).
        try:
            import sys as _s
            _s.path.insert(0, str(_P(__file__).resolve().parents[1]))  # core/lib
            from third_party.base import ConnectionConfig  # type: ignore
            from third_party.blender_mcp import BlenderMCPConnector  # type: ignore
            wrapper = _P(__file__).resolve().parents[3] / "studio" / "blender" / "blender-mcp"
            cfg = ConnectionConfig(service="blender_mcp",
                                   auth={"endpoint": f"stdio://{wrapper}"})
            bl = BlenderMCPConnector(cfg)
            bl.connect()
            import json as _j
            # rig/walk prompts → animated biped armature; else a static mesh.
            # ONE composite call — each MCP send is its own one-shot Blender.
            rig = bool(words & {"walk", "rig", "rigged", "bones", "bone", "joints",
                                "skeleton", "biped", "cycle", "animate", "animated",
                                "armature", "character"})
            if rig:
                r = bl.send("rig.walk", _j.dumps({
                    "name": "GenRig", "frames": 24, "amplitude": 0.6,
                    "export_glb": str(glb)}))
            else:
                r = bl.send("model.build", _j.dumps({
                    "primitive": prim, "name": "GenAsset",
                    "base_color": color, "roughness": 0.5,
                    "export_glb": str(glb)}))
            kind = "rig_walk" if rig else "mesh"
            last = getattr(r, "metadata", {}) or {}
        except Exception as e:
            return SendResult(success=False, service=self.SERVICE, recipient="generate_3d",
                              message_preview="", timestamp=_now_iso(), crystal_id="",
                              error=f"blender_mcp_failed: {type(e).__name__}: {e}",
                              metadata={"prompt": prompt[:200], "primitive": prim})

        made = glb.exists() and glb.stat().st_size > 0
        # Announce to the Godot SSOT inbound bridge (file-based, no auth) so the
        # engine + chain see the new asset — "as it builds it gets stronger".
        if made:
            try:
                with (home / "godot_bridge.jsonl").open("a") as f:
                    f.write(_j.dumps({"ts": _t.time(), "kind": "asset_3d",
                                      "build": kind, "glb": str(glb),
                                      "primitive": prim if kind == "mesh" else "biped",
                                      "animated": kind == "rig_walk",
                                      "prompt": prompt[:200]}) + "\n")
            except Exception:
                pass
        return SendResult(
            success=made, service=self.SERVICE, recipient="generate_3d",
            message_preview=f"{prim} → {glb.name}" if made else "blender runtime unavailable",
            timestamp=_now_iso(), crystal_id="",
            error="" if made else "blender_runtime_unavailable: install nixpkgs#blender "
                                  "or set MSPC_BLENDER_BIN (asset not produced)",
            metadata={"build": kind, "primitive": prim, "color": color,
                      "glb": str(glb), "animated": kind == "rig_walk",
                      "produced": made, "blender_last": last,
                      "announced_to_ssot": made},
        )

    def _generate_app(self, p: Dict[str, Any]) -> SendResult:
        card_slug = str(p.get("card_slug", "")).strip()
        target = str(p.get("target", "replit"))
        if not card_slug:
            return SendResult(
                success=False, service=self.SERVICE, recipient="generate_app",
                message_preview="", timestamp=_now_iso(), crystal_id="",
                error="missing_card_slug", metadata={"target": target},
            )
        status, body = _http_post_json(
            REPLIT_BRIDGE_URL,
            {"tool": "generate_app",
             "args": {"workflow_card_slug": card_slug, "target": target}},
            timeout=int(p.get("timeout", 60)),
        )
        if status == 0:
            # URL/connection error — most likely the bridge isn't running.
            return SendResult(
                success=False, service=self.SERVICE, recipient="generate_app",
                message_preview="", timestamp=_now_iso(), crystal_id="",
                error="replit_bridge_not_running",
                metadata={"target": target, "bridge_url": REPLIT_BRIDGE_URL,
                            "transport_error": body.get("_error", "")},
            )
        success = 200 <= status < 300
        preview = (json.dumps(body)[:400] if isinstance(body, dict) else str(body)[:400])
        meta = {
            "target": target,
            "bridge_url": REPLIT_BRIDGE_URL,
            "http_status": status,
            "card_slug": card_slug,
            "sub_crystal": (body.get("crystal_id", "") if isinstance(body, dict) else ""),
        }
        if isinstance(body, dict):
            for k in ("app_id", "deploy_url", "deployment_id"):
                if k in body:
                    meta[k] = body[k]
        return SendResult(
            success=success, service=self.SERVICE, recipient="generate_app",
            message_preview=preview, timestamp=_now_iso(), crystal_id="",
            error="" if success else (body.get("_error", "") if isinstance(body, dict) else f"http_{status}"),
            metadata=meta,
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="generative_mcp — meta-connector smoke")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("connect")
    sub.add_parser("which", help="list available subordinate connectors + tools")
    p_text = sub.add_parser("text")
    p_text.add_argument("prompt")
    p_text.add_argument("--max-tokens", type=int, default=64)
    p_code = sub.add_parser("code")
    p_code.add_argument("prompt")
    p_code.add_argument("--language", default="python")
    p_code.add_argument("--max-tokens", type=int, default=200)
    p_card = sub.add_parser("card")
    p_card.add_argument("prompt")
    p_card.add_argument("--kind", default="workflow",
                          choices=("workflow", "product", "agent_def"))
    p_img = sub.add_parser("image")
    p_img.add_argument("prompt")
    p_app = sub.add_parser("app")
    p_app.add_argument("card_slug")
    p_app.add_argument("--target", default="replit")
    sub.add_parser("providers", help="list expected tools")

    args = ap.parse_args()
    c = GenerativeMCPConnector()

    if args.cmd == "connect":
        ok = c.connect()
        print(json.dumps({"connected": ok,
                            "import_errors": c._import_errors}, indent=2))

    elif args.cmd == "which":
        print(json.dumps(c.which_tools_available(), indent=2, default=str))

    elif args.cmd == "text":
        r = c.send("generate_text",
                    json.dumps({"prompt": args.prompt, "max_tokens": args.max_tokens}))
        print(json.dumps({"success": r.success,
                            "preview": r.message_preview[:200],
                            "crystal": r.crystal_id[:24] if r.crystal_id else "",
                            "sub_crystal": (r.metadata or {}).get("sub_crystal", "")[:24],
                            "provider": (r.metadata or {}).get("provider", ""),
                            "error": r.error}, indent=2, default=str))

    elif args.cmd == "code":
        r = c.send("generate_code",
                    json.dumps({"prompt": args.prompt,
                                  "language": args.language,
                                  "max_tokens": args.max_tokens}))
        print(json.dumps({"success": r.success,
                            "preview": r.message_preview[:200],
                            "crystal": r.crystal_id[:24] if r.crystal_id else "",
                            "error": r.error}, indent=2, default=str))

    elif args.cmd == "card":
        r = c.send("generate_card",
                    json.dumps({"prompt": args.prompt, "kind": args.kind}))
        print(json.dumps({"success": r.success,
                            "path": r.message_preview,
                            "crystal": r.crystal_id[:24] if r.crystal_id else "",
                            "card_name": (r.metadata or {}).get("card_name", ""),
                            "error": r.error}, indent=2, default=str))

    elif args.cmd == "image":
        r = c.send("generate_image", json.dumps({"prompt": args.prompt}))
        print(json.dumps({"success": r.success,
                            "preview": r.message_preview[:200],
                            "error": r.error}, indent=2, default=str))

    elif args.cmd == "app":
        r = c.send("generate_app",
                    json.dumps({"card_slug": args.card_slug, "target": args.target}))
        print(json.dumps({"success": r.success,
                            "preview": r.message_preview[:200],
                            "error": r.error,
                            "meta": r.metadata}, indent=2, default=str))

    elif args.cmd == "providers":
        print(json.dumps({"expected_tools": list(EXPECTED_TOOLS)}, indent=2))

    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
