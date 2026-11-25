#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        model_api
# role:        GATEWAY · UNIFIED_PROPRIETARY_MODEL_API
# tier:        L0
# substrate:   the single proprietary API surface external apps reach (after
#              passing through freetier_gate token verification)
# storage:     crystal-anchored InferenceRecord per call (tier='model_api')
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - Replit-deployed apps using their freetier token
#   - dApp /buy or other authenticated UI calls
#   - cc model-api curl smoke
#   - studio_runtime when pass.engine='model_api'
# outbound:
#   - cloud_providers.pick → ranked candidates
#   - deepseek_mcp.send  (OpenAI-compat cheap tier)
#   - hf_hub.inference   (HF router fallback)
#   - freetier_gate.require_token (bearer middleware)
#   - inference_logger.log (tier='model_api', model='<resolved provider>')
# substrate touch:
#   - reads:   none directly (router/connectors read .env)
#   - writes:  crystal chain + ~/.cc/model_api/log.jsonl
# ----------------------------------------------------------------------------
# ENDPOINTS
# ----------------------------------------------------------------------------
# POST /v1/text/generate    OpenAI-shape chat completion (default DeepSeek)
# POST /v1/code/generate    routes to code-specialist (deepseek-coder)
# POST /v1/embed            embeddings (placeholder until embed provider lands)
# GET  /v1/providers        list active providers visible to this caller
# GET  /v1/healthz          200 if server healthy
# All POST endpoints require bearer freetier token (any domain).
# ============================================================================
"""model_api.py — the unified, token-gated model API.

Class-level API (for in-process use, no HTTP):
    api = ModelAPI()
    out = api.text("Hello", max_tokens=64)

HTTP server (port 8521):
    python3 core/lib/model_api.py serve --port 8521
    curl -X POST http://localhost:8521/v1/text/generate \
        -H "Authorization: Bearer <freetier_token>" \
        -d '{"prompt":"Hello","max_tokens":64}'

Every successful call crystal-anchors via inference_logger with:
    tier='model_api'
    model='<resolved provider>.<model>'
    scope='<modality>'  # text|code|embed
    chain_context='model_api_<modality>_<provider>'
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from cloud_providers import PROVIDERS, ProviderSpec, pick, get as get_provider  # type: ignore  # noqa: E402
from freetier_gate import verify_token, extract_token_from_headers, TokenClaims  # type: ignore  # noqa: E402


# ---------------------------------------------------------------------------
# Result shape
# ---------------------------------------------------------------------------

@dataclass
class GenerateResult:
    ok: bool
    provider: str = ""
    model: str = ""
    output: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    crystal: str = ""
    error: str = ""
    attempts: List[Dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Crystal anchor
# ---------------------------------------------------------------------------

def _log_call(modality: str, provider: str, model: str,
                prompt_preview: str, output: str,
                tokens_in: int, tokens_out: int, latency_ms: int,
                user_id: str, domain: str, success: bool) -> str:
    try:
        from inference_logger import InferenceLogger  # type: ignore
        il = InferenceLogger()
        return il.log(
            original_prompt=prompt_preview[:512],
            enhanced_prompt=f"model_api.{modality} via {provider}/{model}",
            output_text=output[:1024],
            tier="model_api", model=f"{provider}/{model}",
            scope=f"model_api_{modality}",
            tokens_in=tokens_in, tokens_out=tokens_out, latency_ms=latency_ms,
            source_action=f"model_api.{modality}",
            source_file=f"caller={user_id}@{domain}",
            done_flag=success,
            rc=0 if success else 1,
        ) or ""
    except Exception as e:
        sys.stderr.write(f"warn: model_api crystal log failed: {type(e).__name__}: {e}\n")
        return ""


# ---------------------------------------------------------------------------
# ModelAPI — class for in-process use
# ---------------------------------------------------------------------------

class ModelAPI:
    """Unified model API. Routes per call based on cloud_providers.pick().

    Caller identity (user_id, domain) is optional for in-process use; the
    HTTP server passes the verified TokenClaims so the chain records the
    actual caller."""

    def __init__(self) -> None:
        self._deepseek = None      # lazy
        self._hf_hub = None        # lazy

    # ---- modality methods ----

    def text(self, prompt: str, max_tokens: int = 256, temperature: float = 0.0,
              cost_class: str = "cheap", caller: Optional[TokenClaims] = None,
              system: str = "", model_hint: Optional[str] = None) -> GenerateResult:
        return self._chat_like(prompt, max_tokens, temperature, cost_class,
                                  caller, system, model_hint, family="chat", modality="text")

    def code(self, prompt: str, language: str = "python",
              max_tokens: int = 400, temperature: float = 0.0,
              cost_class: str = "cheap", caller: Optional[TokenClaims] = None,
              model_hint: Optional[str] = None) -> GenerateResult:
        system = f"You are an expert {language} engineer. Output only code, no markdown fences."
        return self._chat_like(prompt, max_tokens, temperature, cost_class,
                                  caller, system, model_hint, family="code", modality="code")

    def embed(self, text: str, model_hint: Optional[str] = None,
                caller: Optional[TokenClaims] = None) -> GenerateResult:
        # v1: only deepseek embed implemented; placeholder for other providers
        cands = pick(family="embed", cost_class="cheap")
        if not cands:
            return GenerateResult(ok=False, error="no embed provider configured")
        spec = get_provider(model_hint) if model_hint else cands[0]
        if not spec or "embed" not in spec.families:
            spec = cands[0]
        # only deepseek wired today
        if spec.kind != "openai_compat" or "deepseek" not in spec.name:
            return GenerateResult(ok=False, provider=spec.name,
                                     error="embed only implemented for deepseek in v1")
        t0 = time.time()
        ds = self._ds_connector()
        if not ds:
            return GenerateResult(ok=False, error="deepseek connector unavailable")
        result = ds.send("embed", json.dumps({"model": "deepseek-chat", "input": text}))
        latency_ms = int((time.time() - t0) * 1000)
        out = result.message_preview if result.success else ""
        crystal = _log_call(
            "embed", spec.name, spec.name.split("-")[0],
            text, out, result.metadata.get("tokens_in", 0), 0, latency_ms,
            (caller.user_id if caller else "anonymous"),
            (caller.domain if caller else "in_process"),
            result.success,
        )
        return GenerateResult(
            ok=result.success, provider=spec.name, model=spec.name,
            output=out, latency_ms=latency_ms, crystal=crystal,
            tokens_in=result.metadata.get("tokens_in", 0), tokens_out=0,
            error=result.error,
            attempts=[{"provider": spec.name, "status": "ok" if result.success else "error",
                        "error": result.error}],
        )

    # ---- internal: chat-shaped dispatch ----

    def _chat_like(self, prompt: str, max_tokens: int, temperature: float,
                     cost_class: str, caller: Optional[TokenClaims], system: str,
                     model_hint: Optional[str], family: str, modality: str
                     ) -> GenerateResult:
        cands = pick(family=family, cost_class=cost_class)
        if model_hint:
            forced = get_provider(model_hint)
            if forced and forced.is_active:
                cands = (forced,) + tuple(c for c in cands if c.name != model_hint)

        if not cands:
            return GenerateResult(ok=False, error="no candidate providers active for this request")

        attempts: List[Dict[str, Any]] = []
        for spec in cands[:4]:  # cap at 4 fallback attempts
            t0 = time.time()
            try:
                if spec.kind == "openai_compat" and "deepseek" in spec.name:
                    out, t_in, t_out, err = self._call_deepseek(spec, prompt, max_tokens,
                                                                   temperature, system)
                elif spec.kind == "hf_router":
                    out, t_in, t_out, err = self._call_hf_router(spec, prompt, max_tokens,
                                                                    temperature, system)
                else:
                    err = f"kind={spec.kind} not yet wired"
                    out, t_in, t_out = "", 0, 0
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
                out, t_in, t_out = "", 0, 0
            latency_ms = int((time.time() - t0) * 1000)

            status = "ok" if (not err and out) else "error"
            attempts.append({
                "provider": spec.name, "status": status,
                "latency_ms": latency_ms, "error": err,
            })

            if status == "ok":
                crystal = _log_call(
                    modality, spec.name, spec.name.split(":", 1)[-1].split("-", 1)[0],
                    prompt, out, t_in, t_out, latency_ms,
                    (caller.user_id if caller else "anonymous"),
                    (caller.domain if caller else "in_process"),
                    True,
                )
                return GenerateResult(
                    ok=True, provider=spec.name, model=spec.name,
                    output=out, tokens_in=t_in, tokens_out=t_out,
                    latency_ms=latency_ms, crystal=crystal,
                    attempts=attempts,
                )

        # All candidates failed
        last_err = attempts[-1]["error"] if attempts else "no attempts made"
        return GenerateResult(
            ok=False, error=f"all {len(attempts)} providers failed; last: {last_err}",
            attempts=attempts,
        )

    # ---- per-kind callers ----

    def _ds_connector(self):
        if self._deepseek is not None:
            return self._deepseek
        try:
            sys.path.insert(0, str(_HERE))
            from third_party.deepseek_mcp import DeepSeekMCPConnector  # type: ignore
            c = DeepSeekMCPConnector()
            c.connect()
            self._deepseek = c
            return c
        except Exception:
            return None

    def _connector(self, attr: str, module: str, cls: str):
        """Lazily instantiate + connect a third_party connector (cached on self).
        Mirrors _ds_connector. Returns the connector or None."""
        existing = getattr(self, attr, None)
        if existing is not None:
            return existing
        try:
            sys.path.insert(0, str(_HERE))
            mod = __import__(f"third_party.{module}", fromlist=[cls])
            c = getattr(mod, cls)()
            try:
                c.connect()
            except Exception:
                pass  # read-only / dry-run tools still work without a live connect
            setattr(self, attr, c)
            return c
        except Exception:
            return None

    def connector_call(self, family: str, tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatch a tool call to twitter/topstep/generative and normalize the
        SendResult to a dict. Connectors own their own crystal logging + safety
        rails (TopStep stays dry-run unless confirm + TOPSTEP_LIVE_TRADING)."""
        table = {
            "twitter":    ("_twitter", "twitter", "TwitterConnector"),
            "trade":      ("_topstep", "topstep_mcp", "TopStepMCPConnector"),
            "generate":   ("_generative", "generative_mcp", "GenerativeMCPConnector"),
        }
        if family not in table:
            return {"ok": False, "error": f"unknown connector family: {family}"}
        conn = self._connector(*table[family])
        if conn is None:
            return {"ok": False, "error": f"{family} connector unavailable"}
        recipient = f"generate_{tool}" if family == "generate" else tool
        try:
            res = conn.send(recipient, json.dumps(args))
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        return {
            "ok": bool(getattr(res, "success", False)),
            "service": getattr(res, "service", family),
            "tool": tool,
            "output": getattr(res, "message_preview", ""),
            "metadata": getattr(res, "metadata", {}) or {},
            "crystal": getattr(res, "crystal_id", ""),
            "error": getattr(res, "error", None),
        }

    def _call_deepseek(self, spec: ProviderSpec, prompt: str, max_tokens: int,
                         temperature: float, system: str
                         ) -> Tuple[str, int, int, str]:
        ds = self._ds_connector()
        if not ds:
            return "", 0, 0, "deepseek connector unavailable"
        model_name = (spec.name if spec.name in
                        ("deepseek-chat", "deepseek-coder", "deepseek-reasoner")
                        else "deepseek-chat")
        msg = json.dumps({
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system,
        })
        result = ds.send("chat_complete", msg)
        if result.success:
            return (result.message_preview,
                     result.metadata.get("tokens_in", 0),
                     result.metadata.get("tokens_out", 0),
                     "")
        return "", 0, 0, result.error or "deepseek call failed"

    def _call_hf_router(self, spec: ProviderSpec, prompt: str, max_tokens: int,
                          temperature: float, system: str
                          ) -> Tuple[str, int, int, str]:
        if self._hf_hub is None:
            try:
                from hf_hub import inference as _hf_inference  # type: ignore
                self._hf_hub = _hf_inference
            except Exception:
                return "", 0, 0, "hf_hub unavailable"
        provider_name = spec.name.split(":", 1)[1] if ":" in spec.name else spec.name
        model = "moonshotai/Kimi-K2-Instruct"  # default; caller could override via model_hint
        r = self._hf_hub(model=model, prompt=prompt, provider=provider_name,
                           max_tokens=max_tokens, temperature=temperature,
                           system=system, fallback=False, timeout=30)
        if getattr(r, "status_code", 0) == 200 and not getattr(r, "error", ""):
            return (r.output_text or "", r.prompt_tokens, r.completion_tokens, "")
        return "", 0, 0, getattr(r, "error", "hf call failed")


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

_API_SINGLETON: Optional[ModelAPI] = None


def _api() -> ModelAPI:
    global _API_SINGLETON
    if _API_SINGLETON is None:
        _API_SINGLETON = ModelAPI()
    return _API_SINGLETON


class ModelAPIHandler(BaseHTTPRequestHandler):
    server_version = "MySpaceModelAPI/0.1"

    def _send(self, status: int, payload: Any, content_type: str = "application/json") -> None:
        if isinstance(payload, (dict, list)):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        elif isinstance(payload, str):
            body = payload.encode("utf-8")
        else:
            body = str(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _auth(self) -> Optional[TokenClaims]:
        token = extract_token_from_headers({
            "Authorization": self.headers.get("Authorization", ""),
            "X-Freetier-Token": self.headers.get("X-Freetier-Token", ""),
        })
        return verify_token(token) if token else None

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/v1/healthz":
            self._send(200, {"ok": True, "service": "model_api", "version": "0.1"})
            return
        if path == "/v1/providers":
            claims = self._auth()
            if not claims:
                self._send(401, {"error": "missing or invalid bearer token",
                                    "hint": "obtain via callback URL on GentlyOS.io or trollz.fun"})
                return
            from cloud_providers import list_active
            specs = [
                {"name": p.name, "kind": p.kind, "tier": p.tier,
                 "families": list(p.families), "endpoint_host": p.endpoint.split("//", 1)[-1].split("/", 1)[0],
                 "cost_per_million_in": p.cost_per_million_in,
                 "cost_per_million_out": p.cost_per_million_out}
                for p in list_active()
            ]
            self._send(200, {"providers": specs, "caller": {"user_id": claims.user_id,
                                                                  "domain": claims.domain,
                                                                  "tier": claims.tier}})
            return
        self._send(404, {"error": "not found"})

    # families exposed as POST /v1/<family>/<tool> → ModelAPI.connector_call
    _CONNECTOR_FAMILIES = ("twitter", "trade", "generate")

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        fixed = ("/v1/text/generate", "/v1/code/generate", "/v1/embed", "/v1/trade_surf")
        seg = path.strip("/").split("/")  # ['v1','twitter','post']
        is_connector = len(seg) == 3 and seg[0] == "v1" and seg[1] in self._CONNECTOR_FAMILIES
        if path not in fixed and not is_connector:
            self._send(404, {"error": "not found"})
            return

        claims = self._auth()
        if not claims:
            self._send(401, {"error": "missing or invalid bearer token",
                                "hint": "obtain via callback URL"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        body_raw = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        try:
            req = json.loads(body_raw)
        except json.JSONDecodeError as e:
            self._send(400, {"error": f"bad json: {e}"})
            return

        # Connector passthrough: /v1/{twitter,trade,generate}/<tool>
        if is_connector:
            family, tool = seg[1], seg[2]
            out = _api().connector_call(family, tool, req if isinstance(req, dict) else {})
            self._send(200 if out.get("ok") else 502, out)
            return

        # Trade surf route — different request shape than chat endpoints
        if path == "/v1/trade_surf":
            self._do_trade_surf(req, claims)
            return

        # OpenAI-compatible shape: support either {prompt} or {messages}
        prompt = req.get("prompt") or ""
        if not prompt and "messages" in req:
            try:
                prompt = req["messages"][-1].get("content", "")
            except (KeyError, IndexError, TypeError):
                prompt = ""
        if not prompt:
            self._send(400, {"error": "either 'prompt' or 'messages' is required"})
            return

        max_tokens = int(req.get("max_tokens", 256))
        temperature = float(req.get("temperature", 0.0))
        cost_class = req.get("cost_class", "cheap")
        model_hint = req.get("model") or req.get("model_hint")
        system = req.get("system", "")

        api = _api()
        if path == "/v1/text/generate":
            result = api.text(prompt, max_tokens, temperature, cost_class,
                                caller=claims, system=system, model_hint=model_hint)
        elif path == "/v1/code/generate":
            language = req.get("language", "python")
            result = api.code(prompt, language, max_tokens, temperature,
                                cost_class, caller=claims, model_hint=model_hint)
        else:  # /v1/embed
            result = api.embed(prompt, model_hint=model_hint, caller=claims)

        if not result.ok:
            self._send(502, {"error": result.error, "attempts": result.attempts})
            return

        # OpenAI-shaped success
        self._send(200, {
            "id": f"mspc_{result.crystal[:24]}" if result.crystal else "mspc_unknown",
            "object": "chat.completion" if path != "/v1/embed" else "embedding",
            "created": int(time.time()),
            "model": result.model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": result.output},
                "finish_reason": "stop",
            }] if path != "/v1/embed" else None,
            "usage": {
                "prompt_tokens": result.tokens_in,
                "completion_tokens": result.tokens_out,
                "total_tokens": result.tokens_in + result.tokens_out,
            },
            "mspc": {
                "provider": result.provider,
                "latency_ms": result.latency_ms,
                "crystal": result.crystal,
                "caller": {"user_id": claims.user_id, "domain": claims.domain, "tier": claims.tier},
                "attempts": result.attempts,
            },
        })

    # ---- /v1/trade_surf — pump.fun ML stack (gate → surf → optional explain) ----

    def _do_trade_surf(self, req: Dict[str, Any], claims: TokenClaims) -> None:
        t_start = time.time()
        stages: List[Dict[str, Any]] = []

        wallet_features = req.get("wallet_features") or {}
        context = req.get("context") or {}
        explain = bool(req.get("explain", False))
        live_trading = bool(req.get("live_trading", False))

        if not isinstance(wallet_features, dict) or "wallet" not in wallet_features:
            self._send(400, {"error": "wallet_features.wallet is required"})
            return

        human_inflow_score = float(context.get("human_inflow_score", 0.0))
        active_position = bool(context.get("active_position", False))
        recent_window_seconds = int(context.get("recent_window_seconds", 60))

        # ---- Optional feature recompute (degrade gracefully) ----
        # extract_features takes JSONL stream paths, not a wallet. We never
        # have those here, so we always trust caller features. The import is
        # still attempted just to record stage visibility for diagnostics.
        try:
            from pump_feature_extractor import extract_features  # type: ignore  # noqa: F401
            stages.append({"stage": "feature_extract", "skipped": True,
                            "reason": "trusting_caller_features"})
        except Exception:
            pass

        # ---- GMM classifier (optional, soft) ----
        gmm_label: Optional[str] = None
        gmm_bot_prob_hint: Optional[float] = None
        try:
            from pump_gmm_classifier import classify_wallet  # type: ignore
            t0 = time.time()
            try:
                gmm_out = classify_wallet(wallet_features)
                # ClusterAssignment dataclass: .cluster_label .bot_probability
                gmm_label = getattr(gmm_out, "cluster_label", None) or \
                                getattr(gmm_out, "label", None)
                gp = getattr(gmm_out, "bot_probability", None)
                if gp is not None:
                    gmm_bot_prob_hint = float(gp)
                stages.append({"stage": "gmm_classify",
                                "duration_ms": int((time.time() - t0) * 1000),
                                "label": gmm_label})
            except Exception as e:
                stages.append({"stage": "gmm_classify", "skipped": True,
                                "error": f"{type(e).__name__}: {e}"})
        except Exception:
            pass

        # ---- XGBoost gate (HARD requirement) ----
        try:
            from pump_xgboost_gate import gate as xgb_gate  # type: ignore
        except Exception as e:
            self._send(503, {"error": "pump_xgboost_gate not built yet",
                              "detail": f"{type(e).__name__}: {e}"})
            return

        t0 = time.time()
        try:
            # Real signature: gate(wallet_feature_row, human_cluster_inflow_score, model_path=None)
            gate_out = xgb_gate(wallet_features, human_inflow_score)
        except Exception as e:
            self._send(500, {"error": f"gate execution failed: {type(e).__name__}: {e}"})
            return
        stages.append({"stage": "gate", "duration_ms": int((time.time() - t0) * 1000)})

        # GateDecision dataclass: wallet, decision, bot_probability, human_inflow_score, reason, crystal
        gate_decision_label = str(getattr(gate_out, "decision", "") or "hold")
        bot_probability = float(getattr(gate_out, "bot_probability", 0.0) or 0.0)
        gate_reason = str(getattr(gate_out, "reason", "") or "")

        # ---- Surf executor (HARD requirement) ----
        try:
            from pump_surf_executor import (  # type: ignore
                consider_buy, consider_sell,
                SurfState as _SurfState,
                GateDecision as _ExecGateDecision,
            )
        except Exception as e:
            self._send(503, {"error": "pump_surf_executor not built yet",
                              "detail": f"{type(e).__name__}: {e}"})
            return

        # Map xgboost.GateDecision  surf_executor.GateDecision (different shapes).
        target_mint = str(wallet_features.get("target_mint")
                           or wallet_features.get("mint") or "")
        target_wallet = str(wallet_features.get("wallet", "") or "")
        exec_gd = _ExecGateDecision(
            decision=gate_decision_label,
            mint=target_mint,
            target_wallet=target_wallet,
            bot_prob=bot_probability,
            human_inflow=human_inflow_score,
            rationale=gate_reason,
            ts=time.time(),
        )

        # Build SurfState from context (active_position drives buy vs sell).
        surf_state = _SurfState(
            active_position=active_position,
            position_mint=str(context.get("position_mint", "") or ""),
            position_sol_in=float(context.get("position_sol_in", 0.0) or 0.0),
            position_entry_ts=float(context.get("position_entry_ts", 0.0) or 0.0),
            last_human_inflow=float(context.get("last_human_inflow", 0.0) or 0.0),
            consecutive_flat_ticks=int(context.get("consecutive_flat_ticks", 0) or 0),
        )

        decision = "hold"
        would_buy: Optional[Dict[str, Any]] = None
        would_sell: Optional[Dict[str, Any]] = None

        if active_position:
            t0 = time.time()
            try:
                sell_order = consider_sell(
                    surf_state, human_inflow_score, bot_probability,
                    confirm=False,  # live_trading still enforces 3-gate safety
                )
                stages.append({"stage": "consider_sell",
                                "duration_ms": int((time.time() - t0) * 1000)})
                if sell_order is not None:
                    would_sell = {
                        "mint": getattr(sell_order, "mint", ""),
                        "sol_amount": getattr(sell_order, "sol_amount", 0.0),
                        "rationale": getattr(sell_order, "rationale", ""),
                        "dry_run": getattr(sell_order, "dry_run", True),
                    }
                # Sell paths fold into the new-surf 'decision': remain 'hold' for a
                # surf candidate slot since we're closing rather than entering.
                decision = "hold"
            except Exception as e:
                stages.append({"stage": "consider_sell",
                                "error": f"{type(e).__name__}: {e}"})
                decision = "hold"
        else:
            # consider_buy only emits when gate.decision == 'surf_candidate'.
            t0 = time.time()
            try:
                buy_order = consider_buy(
                    exec_gd, surf_state, recent_window=None,
                    confirm=False,  # executor's 3-gate safety still wins
                )
                stages.append({"stage": "consider_buy",
                                "duration_ms": int((time.time() - t0) * 1000)})
                if buy_order is not None:
                    decision = "surf_candidate"
                    would_buy = {
                        "sol_amount": float(getattr(buy_order, "sol_amount", 0.0)),
                        "target_mint": str(getattr(buy_order, "mint", "")),
                        "rationale": str(getattr(buy_order, "rationale", "")),
                        "dry_run": bool(getattr(buy_order, "dry_run", True)),
                    }
                    err = getattr(buy_order, "error", "")
                    if err:
                        would_buy["error"] = err
                else:
                    # No order emitted by surf_executor — reflect gate decision.
                    decision = gate_decision_label if gate_decision_label in (
                        "abort", "hold", "surf_candidate") else "hold"
            except Exception as e:
                stages.append({"stage": "consider_buy",
                                "error": f"{type(e).__name__}: {e}"})
                decision = "abort"

        # ---- Optional natural-language explanation via deepseek-chat ----
        natural_explanation = ""
        if explain:
            t0 = time.time()
            try:
                sys_prompt = (
                    "You are a trading signal explainer. Given pump.fun wallet features "
                    "and a gate decision, produce a 2-3 sentence plain-English rationale "
                    "focused on bot-vs-human signatures (tx cadence, value entropy, "
                    "benford distance, jito bundles, funding proximity) and why the "
                    "surf/abort/hold decision follows."
                )
                explain_prompt = json.dumps({
                    "wallet_features": wallet_features,
                    "bot_probability": bot_probability,
                    "human_inflow_score": human_inflow_score,
                    "decision": decision,
                    "gate_reason": gate_reason,
                    "gmm_label": gmm_label,
                    "gmm_bot_prob_hint": gmm_bot_prob_hint,
                }, ensure_ascii=False)
                api = _api()
                ex_result = api.text(explain_prompt, max_tokens=200, temperature=0.2,
                                       cost_class="cheap", caller=claims,
                                       system=sys_prompt, model_hint="deepseek-chat")
                if ex_result.ok:
                    natural_explanation = ex_result.output
                else:
                    natural_explanation = f"[explanation unavailable: {ex_result.error}]"
                stages.append({"stage": "explain_deepseek",
                                "duration_ms": int((time.time() - t0) * 1000)})
            except Exception as e:
                stages.append({"stage": "explain_deepseek",
                                "error": f"{type(e).__name__}: {e}"})
                natural_explanation = f"[explanation failed: {type(e).__name__}]"

        latency_ms = int((time.time() - t_start) * 1000)

        # ---- Crystal anchor ----
        try:
            output_summary = (f"decision={decision} bot_prob={bot_probability:.3f} "
                                f"human_inflow={human_inflow_score:.3f}")
            from inference_logger import InferenceLogger  # type: ignore
            il = InferenceLogger()
            crystal = il.log(
                original_prompt=json.dumps({"wallet": wallet_features.get("wallet", ""),
                                              "explain": explain,
                                              "live_trading": live_trading})[:512],
                enhanced_prompt=f"model_api.trade_surf gate→{decision}",
                output_text=output_summary[:1024],
                tier="model_api", model="trade_surf",
                scope="/v1/trade_surf",
                tokens_in=0, tokens_out=0, latency_ms=latency_ms,
                source_action="model_api.trade_surf",
                source_file=f"caller={claims.user_id}@{claims.domain}",
                done_flag=True,
                rc=0,
            ) or ""
        except Exception as e:
            sys.stderr.write(f"warn: trade_surf crystal log failed: "
                              f"{type(e).__name__}: {e}\n")
            crystal = ""

        resp: Dict[str, Any] = {
            "id": f"mspc_{crystal[:24]}" if crystal else "mspc_unknown",
            "object": "trade_surf.decision",
            "decision": decision,
            "bot_probability": bot_probability,
            "human_inflow_score": human_inflow_score,
            "would_buy": would_buy,
            "would_sell": would_sell,
            "mspc": {
                "latency_ms": latency_ms,
                "crystal": crystal,
                "caller": {"user_id": claims.user_id, "domain": claims.domain,
                              "tier": claims.tier},
                "stages": stages,
            },
        }
        if explain:
            resp["natural_explanation"] = natural_explanation

        self._send(200, resp)

    def log_message(self, format: str, *args) -> None:
        if os.environ.get("MODEL_API_LOG", "") == "quiet":
            return
        sys.stderr.write(f"{self.address_string()} {format % args}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="model_api — unified gated model API")
    sub = ap.add_subparsers(dest="cmd")

    p_serve = sub.add_parser("serve", help="start HTTP server")
    p_serve.add_argument("--port", type=int,
                          default=int(os.environ.get("MSPC_MODEL_API_PORT", "8521")))
    p_serve.add_argument("--bind", default="127.0.0.1")

    p_text = sub.add_parser("text", help="in-process text generate smoke")
    p_text.add_argument("prompt")
    p_text.add_argument("--max-tokens", type=int, default=128)
    p_text.add_argument("--cost-class", default="cheap")
    p_text.add_argument("--model", default=None, help="provider name hint")

    p_code = sub.add_parser("code", help="in-process code generate smoke")
    p_code.add_argument("prompt")
    p_code.add_argument("--language", default="python")
    p_code.add_argument("--max-tokens", type=int, default=200)

    args = ap.parse_args()

    if args.cmd == "serve":
        sys.stderr.write(
            f"model_api listening on {args.bind}:{args.port}\n"
            f"  POST /v1/text/generate · /v1/code/generate · /v1/embed (bearer required)\n"
            f"  GET  /v1/providers (bearer required) · /v1/healthz (public)\n"
        )
        srv = ThreadingHTTPServer((args.bind, args.port), ModelAPIHandler)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            srv.shutdown()

    elif args.cmd == "text":
        api = ModelAPI()
        result = api.text(args.prompt, max_tokens=args.max_tokens,
                            cost_class=args.cost_class, model_hint=args.model)
        print(json.dumps(asdict(result), indent=2))

    elif args.cmd == "code":
        api = ModelAPI()
        result = api.code(args.prompt, language=args.language,
                            max_tokens=args.max_tokens)
        print(json.dumps(asdict(result), indent=2))

    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
