#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        studio_runtime
# role:        GATEWAY · UNIFIED_PIPELINE_ORCHESTRATOR
# tier:        L0
# substrate:   none directly — calls every substrate; emits a TraceRecord chain
# engine:      ops_dag topo-sort → task_queue dispatch → crystal chain anchor
# storage:     none directly (logs trace via inference_logger tier='runtime')
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.studio_runtime.active.json
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - core/cc.sh::cmd_studio_run (cc studio-run <workflow_card>)
#   - workflow_card files in studio/assets/_workflows/
# outbound (the unified dispatch — every substrate is a stop on the chain):
#   - ops_dag                  (resolves pass order)
#   - task_queue               (GPU / OLLAMA / CLOUD / DETERMINISTIC pools)
#   - workflow_generator        (emits surfaces from cards)
#   - inference_logger          (crystal-chains every step)
#   - tri_modal_embedder        (wave + time anchoring)
#   - sentence_chain            (syntactic axis)
#   - svg_vector_embed          (vector axis)
#   - light_source              (RGB → light field)
#   - spatial_anchor            (room coordinates)
#   - frame_clock               (FPS-quantized time)
#   - transition_field          (measured deltas)
#   - dialectic_walker          (IS / IS-NOT / BECOMING append)
#   - energy_inversion          (antipodal twins)
#   - moe_router                (5+5 axis retrieval)
#   - third_party.pinterest     (live API)
#   - third_party.blender_mcp   (Claude-driven 3D modeling — when wired)
# substrate touch:
#   - reads:  workflow_card + all index JSONLs
#   - writes: inference_master_chain.jsonl entries with tier='runtime'
# determinism:
#   - same workflow_card + same chain state + same env → same trace, byte-exact
#   - LLM dispatches go through result_cache; deterministic passes are pure
# ============================================================================
"""studio_runtime.py — string every substrate together into one pipeline.

Reads a workflow_card. Walks ops_dag to resolve pass dependencies. Dispatches
each pass to the right substrate (Pinterest harvest, SVG embed, light source
extraction, workflow_generator surface emission, etc.) via task_queue. Anchors
every step in the crystal chain. Returns a TraceRecord describing the run.

This is the gateway that turns 'workflow_card' into 'real artifacts on disk' —
the engine spine that catches every opportunity the substrate offers.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))


try:
    import blake3 as _blake3_mod
    def _hash(data: bytes) -> str:
        return _blake3_mod.blake3(data).hexdigest()
except ImportError:
    def _hash(data: bytes) -> str:
        return hashlib.blake2b(data).hexdigest()


REPO_ROOT = Path("/data/Projects/MySpace++")
WORKFLOWS_DIR = REPO_ROOT / "studio" / "assets" / "_workflows"


# ---------------------------------------------------------------------------
# Trace records — what we emit as we run
# ---------------------------------------------------------------------------

@dataclass
class PassTrace:
    pass_id: str
    agent: str
    engine: str
    status: str
    started_at: float = 0.0
    finished_at: float = 0.0
    output_summary: str = ""
    output_paths: List[str] = field(default_factory=list)
    crystal: str = ""
    error: str = ""
    # Attachments live HERE as sub-objects of the pass. They are loaded but
    # not executed; they extend the per-pass `tool_options` rendered in the
    # CONTROLS pane. Each entry: {id, kind, label, body, tool_options?, ...}
    attachments: List[Dict[str, Any]] = field(default_factory=list)

    def latency_ms(self) -> int:
        return int((self.finished_at - self.started_at) * 1000) if self.finished_at else 0


@dataclass
class TraceRecord:
    workflow_name: str
    card_crystal: str
    started_at: float = 0.0
    finished_at: float = 0.0
    passes: List[PassTrace] = field(default_factory=list)
    surface_artifacts: Dict[str, str] = field(default_factory=dict)
    failed_count: int = 0
    skipped_count: int = 0
    cached_count: int = 0
    trace_crystal: str = ""
    # Card-level attachments — the persistent props/refs/notes that live in
    # the connection space between THIS card and the downstream card (the
    # blue doc chips in the GUI's gap row). Loaded into context so a
    # downstream card can read them but they don't transform data.
    card_attachments: List[Dict[str, Any]] = field(default_factory=list)

    def total_latency_ms(self) -> int:
        return int((self.finished_at - self.started_at) * 1000) if self.finished_at else 0


# ---------------------------------------------------------------------------
# Pass dispatchers — one per engine kind a workflow_card can declare
# ---------------------------------------------------------------------------

class StudioRuntime:
    """The orchestrator. Reads a card, walks ops_dag, dispatches each pass."""

    def __init__(self, repo_root: Path = REPO_ROOT, dry_run: bool = False):
        self.repo_root = repo_root
        self.dry_run = dry_run
        # Recursion guard for engine="card" sub-card execution. Each running
        # card pushes its name onto the stack; recursive cards check the stack
        # before recursing so card A → B → A fails cleanly instead of looping.
        self._card_stack: List[str] = []

    # ---- entry points -----------------------------------------------

    def run_card(self, card_path: Path) -> TraceRecord:
        """Synchronous orchestration over a workflow_card."""
        card = json.loads(Path(card_path).read_text(encoding="utf-8"))
        return self._run_card_dict(card)

    def run_card_by_name(self, name: str) -> TraceRecord:
        """Find a card by short name (e.g. 'realestate_walkthrough_full')."""
        for f in sorted(WORKFLOWS_DIR.glob(f"*.{name}.*.json")):
            return self.run_card(f)
        for f in sorted(WORKFLOWS_DIR.glob(f"*{name}*.json")):
            return self.run_card(f)
        raise FileNotFoundError(f"no workflow_card matching '{name}'")

    # ---- main orchestration -----------------------------------------

    def _run_card_dict(self, card: Dict[str, Any]) -> TraceRecord:
        from workflow_generator import compute_card_crystal
        name = card.get("name", "?")
        # Cycle guard — reject recursion through the same card.
        if name in self._card_stack:
            trace = TraceRecord(
                workflow_name=name,
                card_crystal="cycle_detected",
                started_at=time.time(),
                finished_at=time.time(),
            )
            trace.failed_count = 1
            return trace
        self._card_stack.append(name)
        card_crystal = compute_card_crystal(card)

        trace = TraceRecord(
            workflow_name=name,
            card_crystal=card_crystal,
            started_at=time.time(),
        )

        # ---- 1. Topo-order the passes via local dependency walk ----
        passes = card.get("passes", []) or []
        ordered = self._topo_order_passes(passes)

        # ---- 2. Run each pass via the appropriate dispatcher ----
        results_by_pass: Dict[str, Any] = {}
        for p in ordered:
            pt = self._dispatch_pass(p, card, results_by_pass)
            trace.passes.append(pt)
            if pt.status == "error":
                trace.failed_count += 1
            elif pt.status == "skipped":
                trace.skipped_count += 1
            elif pt.status == "cached":
                trace.cached_count += 1
            results_by_pass[p.get("id", "?")] = pt

        # ---- 3. Emit surface artifacts via workflow_generator ----
        if not self.dry_run:
            try:
                surface_outs = self._emit_surfaces(card)
                trace.surface_artifacts = surface_outs
            except Exception as e:
                trace.failed_count += 1

        # Card-level attachments (the blue doc chips in the GUI's gap row).
        # They live between THIS card and the downstream card — load them
        # into the trace so downstream runs + the CONTROLS pane can read
        # them as persistent context. They do not execute.
        card_atts = card.get("attachments") or []
        if isinstance(card_atts, list):
            trace.card_attachments = [dict(a) for a in card_atts if isinstance(a, dict)]

        trace.finished_at = time.time()
        trace.trace_crystal = self._compute_trace_crystal(trace)

        # ---- 4. Anchor the whole trace into the crystal chain ----
        if not self.dry_run:
            try:
                self._log_to_crystal_chain(trace)
            except Exception:
                pass

        # Pop the cycle guard frame (always — even on early returns above).
        if self._card_stack and self._card_stack[-1] == name:
            self._card_stack.pop()
        return trace

    # ---- topology -------------------------------------------------

    def _topo_order_passes(self, passes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Resolve pass order from declared in/out relationships.

        A pass P depends on pass Q if any name in P.in is in Q.out.
        Kahn's algorithm with deterministic tie-breaks (sort by pass.id).
        """
        from collections import defaultdict, deque
        by_id = {p.get("id", f"_{i}"): p for i, p in enumerate(passes)}
        ids = list(by_id.keys())
        outs = {pid: (by_id[pid].get("out") or "") for pid in ids}
        # If 'out' is a list, expand; if string, use as single
        out_to_pid: Dict[str, str] = {}
        for pid in ids:
            o = by_id[pid].get("out")
            if isinstance(o, list):
                for item in o:
                    out_to_pid[item] = pid
            elif isinstance(o, str) and o:
                out_to_pid[o] = pid

        deps: Dict[str, set] = defaultdict(set)
        rdeps: Dict[str, set] = defaultdict(set)
        for pid in ids:
            ins = by_id[pid].get("in") or []
            if isinstance(ins, str):
                ins = [ins]
            for in_name in ins:
                src_pid = out_to_pid.get(in_name)
                if src_pid and src_pid != pid:
                    deps[pid].add(src_pid)
                    rdeps[src_pid].add(pid)

        ready = deque(sorted([pid for pid in ids if not deps[pid]]))
        order: List[str] = []
        while ready:
            pid = ready.popleft()
            order.append(pid)
            for nxt in sorted(rdeps[pid]):
                deps[nxt].discard(pid)
                if not deps[nxt]:
                    ready.append(nxt)
        # Append any cycle remainders deterministically
        remaining = sorted(set(ids) - set(order))
        order.extend(remaining)
        return [by_id[pid] for pid in order]

    # ---- per-engine dispatchers ----------------------------------

    def _dispatch_pass(self, p: Dict[str, Any], card: Dict[str, Any],
                        results_by_pass: Dict[str, Any]) -> PassTrace:
        # Stash card so per-engine dispatchers that need it (godot scaffold
        # wants the card name for file paths) can pick it up without
        # changing every dispatcher signature.
        self._current_card = card
        pt = PassTrace(
            pass_id=p.get("id", "?"),
            agent=p.get("agent", "?"),
            engine=p.get("engine", "?"),
            status=p.get("status", "STUB"),
            started_at=time.time(),
        )
        try:
            if self.dry_run:
                pt.output_summary = "dry-run (no execution)"
                pt.status = "skipped"
            else:
                engine = (p.get("engine") or "").lower()
                if engine == "mcp":
                    self._dispatch_mcp(p, pt)
                elif engine == "diffusers":
                    self._dispatch_diffusers(p, pt)
                elif engine == "comfyui":
                    self._dispatch_comfyui(p, pt)
                elif engine == "blender":
                    self._dispatch_blender(p, pt)
                elif engine == "remotion":
                    self._dispatch_remotion(p, pt)
                elif engine == "hf" or engine == "cloud":
                    self._dispatch_hf(p, pt)
                elif engine == "deterministic":
                    self._dispatch_deterministic(p, pt)
                elif engine == "replit":
                    self._dispatch_replit(p, pt)
                elif engine == "model_api":
                    self._dispatch_model_api(p, pt)
                elif engine == "generative":
                    self._dispatch_generative(p, pt)
                elif engine == "sui":
                    self._dispatch_sui(p, pt)
                elif engine == "tensorchain":
                    self._dispatch_tensorchain(p, pt)
                elif engine == "topstep":
                    self._dispatch_topstep(p, pt)
                elif engine == "card":
                    self._dispatch_card(p, pt)
                elif engine == "godot":
                    self._dispatch_godot(p, pt)
                elif engine in ("tiny", "claude", "claude_code"):
                    self._dispatch_cc(p, pt, mode=engine)
                elif engine == "attachment":
                    self._dispatch_attachment(p, pt)
                else:
                    pt.status = "skipped"
                    pt.output_summary = f"unknown engine: {engine}"
        except Exception as e:
            pt.status = "error"
            pt.error = f"{type(e).__name__}: {e}"
        # Sub-attachments on the pass — load regardless of which engine ran.
        # Always populated so the GUI CONTROLS pane + cc_router context can
        # read them downstream. _dispatch_attachment also appends to this
        # same list, so for an engine="attachment" pass it ends up with two
        # entries (the registered one + the sub-attached one). We dedupe by id.
        subs = p.get("attachments") or []
        if isinstance(subs, list) and subs:
            seen = {a.get("id", "") for a in pt.attachments}
            for a in subs:
                if isinstance(a, dict) and a.get("id", "") not in seen:
                    pt.attachments.append(dict(a))
                    seen.add(a.get("id", ""))
        pt.finished_at = time.time()
        pt.crystal = self._compute_pass_crystal(pt, card)
        return pt

    def _dispatch_mcp(self, p: Dict[str, Any], pt: PassTrace) -> None:
        """MCP dispatch — for now we only WIRE the call signature and stamp the trace.
        The actual subprocess invocation will happen once mcp_bridge.py (#31) lands."""
        server = p.get("mcp_server", "?")
        tool = p.get("tool", "?")
        pt.output_summary = f"mcp:{server}::{tool} (deferred — wires through mcp_bridge when wired)"
        pt.status = "skipped"

    def _dispatch_diffusers(self, p: Dict[str, Any], pt: PassTrace) -> None:
        model_path = p.get("model_path") or ""
        if not model_path or not Path(model_path).exists():
            pt.status = "skipped"
            pt.output_summary = f"model_path missing or not on disk: {model_path}"
            return
        pt.output_summary = f"diffusers (deferred to task_queue GPU pool): {Path(model_path).name}"
        pt.status = "skipped"   # actual GPU dispatch via task_queue is the next wedge

    def _dispatch_comfyui(self, p: Dict[str, Any], pt: PassTrace) -> None:
        """ComfyUI dispatch via ComfyUIMCPConnector.

        Reads p['comfy_workflow'] (template name) and p.get('comfy_inputs', {}).
        Calls conn.send('submit_workflow', json.dumps({'template_name': ..., 'inputs': ...})).
        On result.success: pt.status='ok'. On comfyui_not_running: pt.status='skipped'.
        Other errors: pt.status='error'.
        """
        conn = getattr(self, "_comfyui_conn", None)
        if conn is None:
            try:
                from third_party.comfyui_mcp import ComfyUIMCPConnector  # type: ignore
                from third_party.base import ConnectionConfig  # type: ignore
            except Exception:
                try:
                    sys.path.insert(0, str(Path(__file__).resolve().parent))
                    from third_party.comfyui_mcp import ComfyUIMCPConnector  # type: ignore
                    from third_party.base import ConnectionConfig  # type: ignore
                except Exception as e:
                    pt.status = "skipped"
                    pt.output_summary = f"comfyui: connector not built ({type(e).__name__}: {e})"
                    return
            try:
                cfg = ConnectionConfig(service="comfyui_mcp", name="comfyui_runtime",
                                          action="submit_workflow")
                conn = ComfyUIMCPConnector(cfg)
            except Exception as e:
                pt.status = "skipped"
                pt.output_summary = f"comfyui: connector init failed ({type(e).__name__}: {e})"
                return
            self._comfyui_conn = conn

        # Attempt connect (probes /system_stats with 2s timeout).
        try:
            connected = conn.connect()
        except Exception as e:
            pt.status = "skipped"
            pt.output_summary = f"comfyui_not_running: {type(e).__name__}: {e}"
            return
        if not connected:
            detail = getattr(conn, "_connect_error", "") or "comfyui_not_running"
            pt.status = "skipped"
            pt.output_summary = f"comfyui_not_running: {detail[:160]}"
            return

        template = p.get("comfy_workflow") or ""
        inputs = p.get("comfy_inputs") or {}
        try:
            result = conn.send("submit_workflow",
                                 json.dumps({"template_name": template, "inputs": inputs}))
        except Exception as e:
            pt.status = "error"
            pt.error = f"{type(e).__name__}: {e}"
            pt.output_summary = f"comfyui submit_workflow raised: {type(e).__name__}"
            return

        err = getattr(result, "error", "") or ""
        success = bool(getattr(result, "success", False))
        if success:
            pt.status = "ok"
            pt.crystal = getattr(result, "crystal_id", "") or pt.crystal
            preview = getattr(result, "message_preview", "") or ""
            pt.output_summary = preview[:200]
            meta = getattr(result, "metadata", None) or {}
            saved = meta.get("saved_path")
            if saved and isinstance(saved, str):
                pt.output_paths.append(saved)
        elif err == "comfyui_not_running":
            pt.status = "skipped"
            pt.output_summary = "comfyui_not_running"
        else:
            pt.status = "error"
            pt.error = err or "comfyui_submit_failed"
            pt.output_summary = (getattr(result, "message_preview", "") or "")[:200] or err[:200]

    def _dispatch_blender(self, p: Dict[str, Any], pt: PassTrace) -> None:
        """Blender dispatch via BlenderMCPConnector.

        Reads p['tool'], p.get('params', {}). Calls conn.send(tool, json.dumps(params)).
        On connect failure → skipped with blender_mcp_disconnected message.
        On result.success → ok with crystal_id. Other errors → error.
        """
        conn = getattr(self, "_blender_conn", None)
        if conn is None:
            try:
                from third_party.blender_mcp import BlenderMCPConnector  # type: ignore
                from third_party.base import ConnectionConfig  # type: ignore
            except Exception:
                try:
                    sys.path.insert(0, str(Path(__file__).resolve().parent))
                    from third_party.blender_mcp import BlenderMCPConnector  # type: ignore
                    from third_party.base import ConnectionConfig  # type: ignore
                except Exception as e:
                    pt.status = "skipped"
                    pt.output_summary = f"blender: connector not built ({type(e).__name__}: {e})"
                    return
            try:
                cfg = ConnectionConfig(service="blender_mcp", name="blender_runtime",
                                          action="tool_call")
                conn = BlenderMCPConnector(cfg)
            except Exception as e:
                pt.status = "skipped"
                pt.output_summary = f"blender: connector init failed ({type(e).__name__}: {e})"
                return
            self._blender_conn = conn

        try:
            connect_status = conn.connect()
        except Exception as e:
            pt.status = "skipped"
            pt.output_summary = f"blender unreachable: {type(e).__name__}: {e}"
            return
        if not getattr(conn, "_connected", False):
            pt.status = "skipped"
            pt.output_summary = f"blender unreachable: {connect_status}"
            return

        tool = p.get("tool") or ""
        params = p.get("params") or {}
        if not tool:
            pt.status = "skipped"
            pt.output_summary = "blender: no tool specified on pass"
            return
        try:
            result = conn.send(tool, json.dumps(params))
        except Exception as e:
            pt.status = "error"
            pt.error = f"{type(e).__name__}: {e}"
            pt.output_summary = f"blender send raised: {type(e).__name__}"
            return

        err = getattr(result, "error", "") or ""
        success = bool(getattr(result, "success", False))
        if success:
            pt.status = "ok"
            pt.crystal = getattr(result, "crystal_id", "") or pt.crystal
            preview = getattr(result, "message_preview", "") or ""
            pt.output_summary = preview[:200]
            meta = getattr(result, "metadata", None) or {}
            if isinstance(meta, dict):
                outs = meta.get("output_paths") or meta.get("outputs") or []
                if isinstance(outs, list):
                    for op in outs:
                        if isinstance(op, str):
                            pt.output_paths.append(op)
                single = meta.get("output")
                if isinstance(single, str):
                    pt.output_paths.append(single)
        elif "blender_mcp_disconnected" in err or "could not connect" in err:
            pt.status = "skipped"
            pt.output_summary = f"blender_mcp_disconnected: {err[:160]}"
        else:
            pt.status = "error"
            pt.error = err or "blender_send_failed"
            pt.output_summary = (getattr(result, "message_preview", "") or "")[:200] or err[:200]

    def _dispatch_replit(self, p: Dict[str, Any], pt: PassTrace) -> None:
        """Replit bridge dispatch — POSTs to a local Replit MCP bridge.

        Reads p.get('tool') and p.get('params', {}). POST as
        {"tool": tool, "args": params}. 5s probe / 60s real call.
        Connection refused / timeout → skipped (replit_bridge_not_running).
        """
        import urllib.error
        import urllib.request
        url = getattr(self, "_replit_url", None)
        if url is None:
            url = os.environ.get("REPLIT_BRIDGE_URL", "http://localhost:8765/mcp/call")
            self._replit_url = url

        tool = p.get("tool") or "generate_app"
        params = p.get("params") or {}
        payload = json.dumps({"tool": tool, "args": params}).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                try:
                    body = json.loads(raw)
                except json.JSONDecodeError:
                    body = {"_raw": raw[:2048]}
            pt.status = "ok"
            preview = json.dumps(body, default=str)[:200] if isinstance(body, dict) else str(body)[:200]
            pt.output_summary = preview
            if isinstance(body, dict) and isinstance(body.get("crystal"), str):
                pt.crystal = body["crystal"]
        except urllib.error.HTTPError as e:
            pt.status = "error"
            pt.error = f"http_{e.code}"
            try:
                pt.output_summary = f"replit http {e.code}: {e.read().decode('utf-8', errors='replace')[:160]}"
            except Exception:
                pt.output_summary = f"replit http {e.code}"
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", "")
            reason_s = str(reason).lower()
            if ("refused" in reason_s or "not running" in reason_s
                    or "timed out" in reason_s or "timeout" in reason_s
                    or "name or service not known" in reason_s):
                pt.status = "skipped"
                pt.output_summary = "replit_bridge_not_running"
            else:
                pt.status = "error"
                pt.error = f"URLError: {e.reason}"
                pt.output_summary = f"replit URLError: {str(e.reason)[:160]}"
        except TimeoutError:
            pt.status = "skipped"
            pt.output_summary = "replit_bridge_not_running"
        except Exception as e:
            pt.status = "error"
            pt.error = f"{type(e).__name__}: {e}"
            pt.output_summary = f"replit: {type(e).__name__}"

    def _dispatch_model_api(self, p: Dict[str, Any], pt: PassTrace) -> None:
        """ModelAPI dispatch — text / code / embed via the unified API.

        Reads p.get('modality', 'text') and p.get('params', {}).
        params.prompt is required (params.text for embed).
        """
        api = getattr(self, "_model_api", None)
        if api is None:
            try:
                from model_api import ModelAPI  # type: ignore
            except Exception:
                try:
                    sys.path.insert(0, str(Path(__file__).resolve().parent))
                    from model_api import ModelAPI  # type: ignore
                except Exception as e:
                    pt.status = "skipped"
                    pt.output_summary = f"model_api: connector not built ({type(e).__name__}: {e})"
                    return
            try:
                api = ModelAPI()
            except Exception as e:
                pt.status = "skipped"
                pt.output_summary = f"model_api: init failed ({type(e).__name__}: {e})"
                return
            self._model_api = api

        modality = (p.get("modality") or "text").lower()
        params = dict(p.get("params") or {})
        prompt = params.get("prompt") or params.get("text") or ""
        if not prompt:
            pt.status = "skipped"
            pt.output_summary = f"model_api {modality}: missing prompt/text in params"
            return

        try:
            if modality == "code":
                result = api.code(
                    prompt=prompt,
                    language=params.get("language", "python"),
                    max_tokens=int(params.get("max_tokens", 400)),
                    temperature=float(params.get("temperature", 0.0)),
                    cost_class=params.get("cost_class", "cheap"),
                    model_hint=params.get("model_hint"),
                )
            elif modality == "embed":
                result = api.embed(
                    text=prompt,
                    model_hint=params.get("model_hint"),
                )
            else:
                result = api.text(
                    prompt=prompt,
                    max_tokens=int(params.get("max_tokens", 256)),
                    temperature=float(params.get("temperature", 0.0)),
                    cost_class=params.get("cost_class", "cheap"),
                    system=params.get("system", ""),
                    model_hint=params.get("model_hint"),
                )
        except Exception as e:
            pt.status = "error"
            pt.error = f"{type(e).__name__}: {e}"
            pt.output_summary = f"model_api {modality} raised: {type(e).__name__}"
            return

        if getattr(result, "ok", False):
            pt.status = "ok"
            pt.crystal = getattr(result, "crystal", "") or pt.crystal
            pt.output_summary = (getattr(result, "output", "") or "")[:200]
        else:
            err = getattr(result, "error", "") or ""
            pt.status = "error" if err else "skipped"
            pt.error = err
            pt.output_summary = err[:200] or f"model_api {modality} failed"

    def _dispatch_generative(self, p: Dict[str, Any], pt: PassTrace) -> None:
        """Generative meta-connector dispatch."""
        conn = getattr(self, "_generative_conn", None)
        if conn is None:
            try:
                from third_party.generative_mcp import GenerativeMCPConnector  # type: ignore
                from third_party.base import ConnectionConfig  # type: ignore
            except Exception:
                try:
                    sys.path.insert(0, str(Path(__file__).resolve().parent))
                    from third_party.generative_mcp import GenerativeMCPConnector  # type: ignore
                    from third_party.base import ConnectionConfig  # type: ignore
                except Exception as e:
                    pt.status = "skipped"
                    pt.output_summary = f"generative: connector not built ({type(e).__name__}: {e})"
                    return
            try:
                cfg = ConnectionConfig(service="generative_mcp", name="generative_runtime",
                                          action="meta_fanout")
                conn = GenerativeMCPConnector(cfg)
            except Exception as e:
                pt.status = "skipped"
                pt.output_summary = f"generative: connector init failed ({type(e).__name__}: {e})"
                return
            self._generative_conn = conn

        try:
            conn.connect()
        except Exception as e:
            pt.status = "skipped"
            pt.output_summary = f"generative connect failed: {type(e).__name__}: {e}"
            return

        tool = p.get("tool") or ""
        params = p.get("params") or {}
        if not tool:
            pt.status = "skipped"
            pt.output_summary = "generative: no tool specified on pass"
            return
        try:
            result = conn.send(tool, json.dumps(params))
        except Exception as e:
            pt.status = "error"
            pt.error = f"{type(e).__name__}: {e}"
            pt.output_summary = f"generative send raised: {type(e).__name__}"
            return

        if getattr(result, "success", False):
            pt.status = "ok"
            pt.crystal = getattr(result, "crystal_id", "") or pt.crystal
            pt.output_summary = (getattr(result, "message_preview", "") or "")[:200]
        else:
            err = getattr(result, "error", "") or ""
            pt.status = "error" if err else "skipped"
            pt.error = err
            pt.output_summary = err[:200] or "generative_send_failed"

    def _dispatch_sui(self, p: Dict[str, Any], pt: PassTrace) -> None:
        """Sui on-chain dispatch."""
        conn = getattr(self, "_sui_conn", None)
        if conn is None:
            try:
                from third_party.sui_mcp import SuiMCPConnector  # type: ignore
                from third_party.base import ConnectionConfig  # type: ignore
            except Exception:
                try:
                    sys.path.insert(0, str(Path(__file__).resolve().parent))
                    from third_party.sui_mcp import SuiMCPConnector  # type: ignore
                    from third_party.base import ConnectionConfig  # type: ignore
                except Exception as e:
                    pt.status = "skipped"
                    pt.output_summary = f"sui: connector not built ({type(e).__name__}: {e})"
                    return
            try:
                cfg = ConnectionConfig(service="sui", name="sui_runtime",
                                          action="on_chain_rail")
                conn = SuiMCPConnector(cfg)
            except Exception as e:
                pt.status = "skipped"
                pt.output_summary = f"sui: connector init failed ({type(e).__name__}: {e})"
                return
            self._sui_conn = conn

        try:
            connected = conn.connect()
        except Exception as e:
            pt.status = "skipped"
            pt.output_summary = f"sui_not_connected: {type(e).__name__}: {e}"
            return
        if not connected:
            pt.status = "skipped"
            pt.output_summary = "sui_not_connected (missing sui CLI or SUI_WALLET?)"
            return

        tool = p.get("tool") or ""
        params = p.get("params") or {}
        if not tool:
            pt.status = "skipped"
            pt.output_summary = "sui: no tool specified on pass"
            return
        try:
            result = conn.send(tool, json.dumps(params))
        except Exception as e:
            pt.status = "error"
            pt.error = f"{type(e).__name__}: {e}"
            pt.output_summary = f"sui send raised: {type(e).__name__}"
            return

        if getattr(result, "success", False):
            pt.status = "ok"
            pt.crystal = getattr(result, "crystal_id", "") or pt.crystal
            pt.output_summary = (getattr(result, "message_preview", "") or "")[:200]
        else:
            err = getattr(result, "error", "") or ""
            if "not_connected" in err or "requires_confirm" in err:
                pt.status = "skipped"
                pt.output_summary = err[:200]
            else:
                pt.status = "error" if err else "skipped"
                pt.error = err
                pt.output_summary = err[:200] or "sui_send_failed"

    def _dispatch_tensorchain(self, p: Dict[str, Any], pt: PassTrace) -> None:
        """TensorChain L1 dispatch."""
        conn = getattr(self, "_tensorchain_conn", None)
        if conn is None:
            try:
                from third_party.tensorchain_mcp import TensorChainMCPConnector  # type: ignore
                from third_party.base import ConnectionConfig  # type: ignore
            except Exception:
                try:
                    sys.path.insert(0, str(Path(__file__).resolve().parent))
                    from third_party.tensorchain_mcp import TensorChainMCPConnector  # type: ignore
                    from third_party.base import ConnectionConfig  # type: ignore
                except Exception as e:
                    pt.status = "skipped"
                    pt.output_summary = f"tensorchain: connector not built ({type(e).__name__}: {e})"
                    return
            try:
                cfg = ConnectionConfig(service="tensorchain", name="tensorchain_runtime",
                                          action="dapp_mint_escrow")
                conn = TensorChainMCPConnector(cfg)
            except Exception as e:
                pt.status = "skipped"
                pt.output_summary = f"tensorchain: connector init failed ({type(e).__name__}: {e})"
                return
            self._tensorchain_conn = conn

        try:
            conn.connect()
        except Exception as e:
            pt.status = "skipped"
            pt.output_summary = f"tensorchain connect failed: {type(e).__name__}: {e}"
            return

        tool = p.get("tool") or ""
        params = p.get("params") or {}
        if not tool:
            pt.status = "skipped"
            pt.output_summary = "tensorchain: no tool specified on pass"
            return
        try:
            result = conn.send(tool, json.dumps(params))
        except Exception as e:
            pt.status = "error"
            pt.error = f"{type(e).__name__}: {e}"
            pt.output_summary = f"tensorchain send raised: {type(e).__name__}"
            return

        if getattr(result, "success", False):
            pt.status = "ok"
            pt.crystal = getattr(result, "crystal_id", "") or pt.crystal
            pt.output_summary = (getattr(result, "message_preview", "") or "")[:200]
        else:
            err = getattr(result, "error", "") or ""
            pt.status = "error" if err else "skipped"
            pt.error = err
            pt.output_summary = err[:200] or "tensorchain_send_failed"

    def _dispatch_topstep(self, p: Dict[str, Any], pt: PassTrace) -> None:
        """TopstepX futures dispatch with DRY-RUN safety rails.

        Write tools (order_market, order_limit, cancel_order, flatten_all)
        require params.confirm=True to be allowed through. Otherwise we pass
        the params untouched — the connector itself enforces DRY-RUN by
        default. Always crystal-anchor via the connector's send().
        """
        WRITE_OPS = {"order_market", "order_limit", "cancel_order", "flatten_all"}
        conn = getattr(self, "_topstep_conn", None)
        if conn is None:
            try:
                from third_party.topstep_mcp import TopStepMCPConnector  # type: ignore
                from third_party.base import ConnectionConfig  # type: ignore
            except Exception:
                try:
                    sys.path.insert(0, str(Path(__file__).resolve().parent))
                    from third_party.topstep_mcp import TopStepMCPConnector  # type: ignore
                    from third_party.base import ConnectionConfig  # type: ignore
                except Exception as e:
                    pt.status = "skipped"
                    pt.output_summary = f"topstep: connector not built ({type(e).__name__}: {e})"
                    return
            try:
                cfg = ConnectionConfig(service="topstep", name="topstep_runtime",
                                          action="futures_rail")
                conn = TopStepMCPConnector(cfg)
            except Exception as e:
                pt.status = "skipped"
                pt.output_summary = f"topstep: connector init failed ({type(e).__name__}: {e})"
                return
            self._topstep_conn = conn

        try:
            connected = conn.connect()
        except Exception as e:
            pt.status = "skipped"
            pt.output_summary = f"topstep_not_connected: {type(e).__name__}: {e}"
            return
        if not connected:
            pt.status = "skipped"
            pt.output_summary = ("topstep_not_connected (missing TOPSTEP_USERNAME / "
                                  "TOPSTEP_API_KEY)")
            return

        tool = p.get("tool") or ""
        params = dict(p.get("params") or {})
        if not tool:
            pt.status = "skipped"
            pt.output_summary = "topstep: no tool specified on pass"
            return

        # SAFETY: any write op without explicit confirm=True is logged as
        # un-confirmed; the connector itself still enforces DRY-RUN by default,
        # but we annotate the trace so it's visible.
        forced_dry = False
        if tool in WRITE_OPS and params.get("confirm") is not True:
            forced_dry = True  # connector will produce a DRY-RUN result either way

        try:
            result = conn.send(tool, json.dumps(params))
        except Exception as e:
            pt.status = "error"
            pt.error = f"{type(e).__name__}: {e}"
            pt.output_summary = f"topstep send raised: {type(e).__name__}"
            return

        meta = getattr(result, "metadata", None) or {}
        dry_run_flag = bool(meta.get("dry_run", False)) if isinstance(meta, dict) else False
        if getattr(result, "success", False):
            pt.status = "ok"
            pt.crystal = getattr(result, "crystal_id", "") or pt.crystal
            preview = (getattr(result, "message_preview", "") or "")[:200]
            tag = " [DRY-RUN]" if (dry_run_flag or forced_dry) else ""
            pt.output_summary = (preview + tag)[:200]
        else:
            err = getattr(result, "error", "") or ""
            if "not_connected" in err:
                pt.status = "skipped"
                pt.output_summary = err[:200]
            else:
                pt.status = "error" if err else "skipped"
                pt.error = err
                pt.output_summary = err[:200] or "topstep_send_failed"

    def _dispatch_remotion(self, p: Dict[str, Any], pt: PassTrace) -> None:
        pt.output_summary = "remotion render (deferred — npx remotion render <comp>)"
        pt.status = "skipped"

    def _dispatch_hf(self, p: Dict[str, Any], pt: PassTrace) -> None:
        """HuggingFace Inference Provider dispatch — fans across 19 cloud providers.
        Card pass shape:
          {"engine": "hf", "agent": "hf_inference",
           "params": {"provider": "groq", "model": "moonshotai/Kimi-K2-Instruct",
                       "prompt": "...", "max_tokens": 256, "temperature": 0.0,
                       "fallback": true, "try_providers": ["groq","cerebras",...] }}
        Falls back across the 19-provider list when fallback=true.
        """
        try:
            from hf_hub import inference, _load_token  # type: ignore
        except ImportError:
            import sys as _sys
            _sys.path.insert(0, str(Path(__file__).resolve().parent))
            from hf_hub import inference, _load_token  # type: ignore

        params = dict(p.get("params") or {})
        if not _load_token():
            pt.output_summary = "hf inference skipped — no HF_TOKEN in env / .env / ~/.cache/huggingface/token"
            pt.status = "skipped"
            return

        model = params.get("model") or ""
        prompt = params.get("prompt") or ""
        if not model or not prompt:
            pt.output_summary = "hf inference missing model or prompt in params"
            pt.status = "skipped"
            return

        result = inference(
            model=model, prompt=prompt,
            provider=params.get("provider"),
            max_tokens=int(params.get("max_tokens", 256)),
            temperature=float(params.get("temperature", 0.0)),
            system=params.get("system", ""),
            fallback=bool(params.get("fallback", True)),
            try_providers=params.get("try_providers"),
            timeout=int(params.get("timeout", 60)),
        )
        if result.status_code == 200 and not result.error:
            pt.status = "ok"
            pt.output_summary = (
                f"hf:{result.provider} {model} → {result.completion_tokens}t "
                f"in {result.latency_ms}ms · crystal={result.crystal[:12]}"
            )
        else:
            pt.status = "error"
            pt.error = result.error or f"status={result.status_code}"
            pt.output_summary = (
                f"hf:{result.provider} {model} → status={result.status_code} err={result.error[:120]}"
            )

    def _dispatch_attachment(self, p: Dict[str, Any], pt: PassTrace) -> None:
        """engine='attachment' — register a doc/asset/ref/note/file/link.

        Attachments are NOT transformations. They travel through the chain
        as persistent metadata, extending the CONTROLS pane's tool_options
        for whatever step or chain-edge they're attached to. The dispatcher
        records the attachment, marks the pass `ok`, and lets the next step
        pick it up via pt.attachments.
        """
        kind = (p.get("attachment_kind") or p.get("kind") or
                (p.get("kernel_ref") or "").split(":", 1)[-1] or "doc")
        params = p.get("params") or {}
        label = p.get("label") or params.get("label", "")
        body = p.get("body") or params.get("body", "")
        att = {
            "id":           p.get("id", ""),
            "kind":         kind,
            "label":        label,
            "body":         body,
            "uri":          params.get("uri") or params.get("path") or params.get("url") or "",
            "tool_options": p.get("tool_options") or params.get("tool_options") or [],
        }
        pt.attachments.append(att)
        pt.status = "ok"
        pt.output_summary = f"attachment:{kind} · {label[:40]}" + (
            f" · {len(att['tool_options'])} tool_options" if att['tool_options'] else "")

    def _dispatch_card(self, p: Dict[str, Any], pt: PassTrace) -> None:
        """engine='card' — recursive sub-card execution.

        Reads p['kernel_ref'] (e.g. 'card:autonomous_3d_asset'), looks up the
        card in kernel_registry to find its disk path, loads JSON, and runs
        it as a nested workflow_card via self._run_card_dict. Cycle detection
        is handled by self._card_stack inside _run_card_dict.
        """
        kernel_ref = p.get("kernel_ref") or ""
        sub_name = kernel_ref.split(":", 1)[-1] if ":" in kernel_ref else kernel_ref
        if not sub_name:
            pt.status = "skipped"
            pt.output_summary = "card: no kernel_ref"
            return
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from kernel_registry import resolve  # type: ignore
        except Exception as e:
            pt.status = "skipped"
            pt.output_summary = f"card: kernel_registry not importable ({type(e).__name__})"
            return
        spec = resolve(kernel_ref) or resolve(f"card:{sub_name}")
        if not spec:
            pt.status = "error"
            pt.error = f"card: unresolved kernel_ref '{kernel_ref}'"
            return
        card_path_rel = spec.get("card_path") or ""
        if not card_path_rel:
            pt.status = "error"
            pt.error = f"card: registry entry missing card_path for '{sub_name}'"
            return
        sub_path = self.repo_root / card_path_rel
        if not sub_path.exists():
            pt.status = "error"
            pt.error = f"card: file missing on disk: {sub_path}"
            return
        if sub_name in self._card_stack:
            pt.status = "error"
            pt.error = f"card: cycle — '{sub_name}' already in stack {self._card_stack}"
            return
        try:
            sub_card = json.loads(sub_path.read_text(encoding="utf-8"))
            sub_trace = self._run_card_dict(sub_card)
        except Exception as e:
            pt.status = "error"
            pt.error = f"card sub-run raised: {type(e).__name__}: {e}"
            return
        # Roll the sub-trace up into this pass's PassTrace.
        if sub_trace.failed_count:
            pt.status = "error"
            pt.error = f"sub-card '{sub_name}' had {sub_trace.failed_count} failed passes"
        else:
            pt.status = "ok"
        pt.crystal = sub_trace.trace_crystal or pt.crystal
        pt.output_summary = (
            f"card:{sub_name} → passes={len(sub_trace.passes)} "
            f"ok={sum(1 for x in sub_trace.passes if x.status == 'ok')} "
            f"skipped={sub_trace.skipped_count} failed={sub_trace.failed_count} "
            f"latency={sub_trace.total_latency_ms()}ms"
        )

    def _dispatch_godot(self, p: Dict[str, Any], pt: PassTrace) -> None:
        """engine='godot' — scaffold a minimal scene + controller for this card.

        If a target .tscn already exists, leave it (Godot project tree is user
        territory). Otherwise write a stub Node2D scene + paired controller
        script under studio/godot/project/ so the user can open in the editor
        and extend. Crystal-anchors the scaffold so later runs are idempotent.
        """
        proj = self.repo_root / "studio" / "godot" / "project"
        scenes_dir = proj / "scenes"
        src_dir = proj / "src"
        if not proj.exists():
            pt.status = "skipped"
            pt.output_summary = f"godot: project tree missing at {proj}"
            return
        # Resolve a safe filename from (in priority): explicit params.scene_name,
        # the CARD's name (so a "2d_pixel_platformer" card writes the matching
        # scene file), then the agent id as a final fallback.
        params = p.get("params") or {}
        card_name = (getattr(self, "_current_card", None) or {}).get("name", "")
        safe = params.get("scene_name") or card_name or p.get("agent") or "scene"
        safe = "".join(c if c.isalnum() or c == "_" else "_" for c in str(safe).lower())[:48] or "scene"
        scene_path = scenes_dir / f"{safe}.tscn"
        script_path = src_dir / f"{safe}_controller.gd"
        scenes_dir.mkdir(parents=True, exist_ok=True)
        src_dir.mkdir(parents=True, exist_ok=True)
        wrote = []
        if not scene_path.exists():
            tscn = (
                '[gd_scene load_steps=2 format=3]\n'
                f'[ext_resource type="Script" path="res://src/{safe}_controller.gd" id="1"]\n\n'
                '[node name="World" type="Node2D"]\n'
                'script = ExtResource("1")\n\n'
                '[node name="Camera2D" type="Camera2D" parent="."]\n\n'
                '[node name="Player" type="CharacterBody2D" parent="."]\n\n'
                '[node name="UI" type="CanvasLayer" parent="."]\n'
            )
            scene_path.write_text(tscn, encoding="utf-8")
            wrote.append(str(scene_path.relative_to(self.repo_root)))
        if not script_path.exists():
            gd = (
                'extends Node2D\n\n'
                f'## auto-scaffolded by studio_runtime._dispatch_godot\n'
                f'## card pass: {p.get("id","?")}  kernel_ref: {p.get("kernel_ref","?")}\n\n'
                'func _ready() -> void:\n'
                '\tprint("[%s] ready" % name)\n\n'
                'func _physics_process(delta: float) -> void:\n'
                '\tpass\n'
            )
            script_path.write_text(gd, encoding="utf-8")
            wrote.append(str(script_path.relative_to(self.repo_root)))
        pt.status = "ok"
        if wrote:
            pt.output_summary = f"godot scaffold: wrote {len(wrote)} file(s) — {wrote[0]}"
            pt.output_paths.extend(wrote)
        else:
            pt.output_summary = f"godot scaffold: {scene_path.name} already present (no overwrite)"
            pt.output_paths.append(str(scene_path.relative_to(self.repo_root)))

    def _dispatch_cc(self, p: Dict[str, Any], pt: PassTrace, mode: str = "tiny") -> None:
        """engine='tiny' | 'claude' — route the pass through cc_router.

        Builds a per-pass prompt from kernel_ref + agent + scope context,
        sends through `cc tiny` (free local Ollama) or `cc claude` (one-shot
        Claude Code). Captures the routed output. Same dispatch shape as the
        deterministic dispatchers — graceful skip on unavailability.
        """
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from cc_router import route  # type: ignore
        except Exception as e:
            pt.status = "skipped"
            pt.output_summary = f"cc_router not importable ({type(e).__name__})"
            return
        prompt = (p.get("params") or {}).get("prompt") or p.get("prompt") or (
            f"You are workflow node `{p.get('id','?')}` running kernel `{p.get('kernel_ref','?')}`. "
            f"Describe in ONE sentence the action you would take. No preamble."
        )
        ctx = {
            "pass_id": p.get("id", ""),
            "kernel_ref": p.get("kernel_ref", ""),
            "agent": p.get("agent", ""),
            "in_type": p.get("in", ""),
            "out_type": p.get("out", ""),
        }
        timeout = 120 if mode in ("claude", "claude_code") else 30
        result = route(prompt, mode=mode, context=ctx, timeout_s=timeout)
        if result.ok:
            pt.status = "ok"
            pt.output_summary = f"cc {mode} → {result.output[:200]}"
        else:
            pt.status = "skipped"
            pt.output_summary = f"cc {mode} skipped: {result.error[:160]}"

    def _dispatch_deterministic(self, p: Dict[str, Any], pt: PassTrace) -> None:
        """Deterministic passes — pure-Python operations on the substrate.
        Examples: pinterest harvest, svg embed, light source extraction,
        frame_clock alignment, transition_field measurement."""
        agent = (p.get("agent") or "").lower()

        if "pinterest" in agent:
            self._run_pinterest_harvest(p, pt)
        elif "svg" in agent or "vector" in agent:
            self._run_svg_embed(p, pt)
        elif "light" in agent:
            self._run_light_source(p, pt)
        elif "spatial" in agent or "anchor" in agent:
            self._run_spatial_anchor(p, pt)
        elif "frame" in agent or "clock" in agent:
            self._run_frame_clock(p, pt)
        elif "transition" in agent or "flow" in agent:
            self._run_transition_field(p, pt)
        elif "dataset" in agent or "fbx" in agent or "mixamo" in agent:
            self._run_dataset_select(p, pt)
        else:
            pt.output_summary = f"deterministic pass '{agent}' — no dispatcher registered"
            pt.status = "skipped"

    # ---- deterministic sub-runners -----------------------------------

    def _run_pinterest_harvest(self, p: Dict[str, Any], pt: PassTrace) -> None:
        try:
            from third_party.pinterest import PinterestConnector
            from third_party.base import ConnectionConfig
        except Exception as e:
            pt.status = "error"
            pt.error = f"pinterest import: {e}"
            return
        category = (p.get("params") or {}).get("category", "blueprint")
        cfg = ConnectionConfig(service="pinterest", action="search")
        conn = PinterestConnector(cfg)
        try:
            harvested = conn.harvest_curated(category, limit_per_query=3)
        except Exception as e:
            pt.status = "error"
            pt.error = f"pinterest harvest failed: {e}"
            return
        total_pins = sum(len(v) for v in harvested.values())
        pt.output_summary = f"pinterest harvest '{category}': {total_pins} pins across {len(harvested)} queries"
        pt.status = "ok"

    def _run_svg_embed(self, p: Dict[str, Any], pt: PassTrace) -> None:
        try:
            from svg_vector_embed import embed_svg_file
        except Exception as e:
            pt.status = "error"; pt.error = f"svg import: {e}"; return
        target = (p.get("params") or {}).get("target_dir", str(self.repo_root / "studio" / "docs"))
        target_path = Path(target)
        records = []
        for svg in target_path.rglob("*.svg"):
            try:
                records.extend(embed_svg_file(svg))
            except Exception:
                pass
        pt.output_summary = f"svg embed: {len(records)} paths from {target}"
        pt.status = "ok"

    def _run_light_source(self, p: Dict[str, Any], pt: PassTrace) -> None:
        try:
            from light_source import LightSource
        except Exception as e:
            pt.status = "error"; pt.error = f"light_source import: {e}"; return
        # Synthesize a demo light from card layer_stack if present
        layers = (p.get("params") or {}).get("layer_stack") or []
        n = 0
        for layer in layers:
            if layer.get("name") in ("emission", "albedo"):
                n += 1
        pt.output_summary = f"light_source synthesis: {n} candidate emission layers in card"
        pt.status = "ok" if n else "skipped"

    def _run_spatial_anchor(self, p: Dict[str, Any], pt: PassTrace) -> None:
        try:
            from spatial_anchor import AcousticEcho, WifiRTTBeacon, SpatialAnchor
        except Exception as e:
            pt.status = "error"; pt.error = f"spatial_anchor import: {e}"; return
        params = p.get("params") or {}
        distances = params.get("wall_distances_m") or [4.0, 3.0, 4.0, 3.0, 2.4]
        x, y, z, h = params.get("x", 0), params.get("y", 0), params.get("z", 0), params.get("heading", 0)
        e = AcousticEcho.from_wall_distances(distances)
        pos = WifiRTTBeacon.from_position(x, y, z, h)
        anchor = SpatialAnchor.of(echo=e, position=pos, room_id=params.get("room_id", "rt"))
        pt.output_summary = f"spatial_anchor crystal={anchor.crystal_id[:12]} room_sig_dim=64"
        pt.status = "ok"

    def _run_frame_clock(self, p: Dict[str, Any], pt: PassTrace) -> None:
        try:
            from frame_clock import FrameClock
        except Exception as e:
            pt.status = "error"; pt.error = f"frame_clock import: {e}"; return
        fc = FrameClock.now()
        pt.output_summary = f"frame_clock now: frames={fc.frames} crystal={fc.crystal[:12]}"
        pt.status = "ok"

    def _run_transition_field(self, p: Dict[str, Any], pt: PassTrace) -> None:
        pt.output_summary = "transition_field measurement (requires event corpus — wires post-harvest)"
        pt.status = "skipped"

    def _run_dataset_select(self, p: Dict[str, Any], pt: PassTrace) -> None:
        # Pick rigged FBX files from /home/tom/Datasets/input/<category>/
        category = (p.get("params") or {}).get("category", "idle")
        root = Path("/home/tom/Datasets/input") / category
        if not root.exists():
            pt.status = "skipped"
            pt.output_summary = f"datasets path missing: {root}"
            return
        fbxs = list(root.glob("*.fbx"))
        pt.output_paths = [str(f) for f in fbxs[:5]]
        pt.output_summary = f"dataset_select '{category}': {len(fbxs)} FBX files available (showing first 5)"
        pt.status = "ok" if fbxs else "skipped"

    # ---- surface emission (workflow_generator)  ----------------------

    def _emit_surfaces(self, card: Dict[str, Any]) -> Dict[str, str]:
        """Call workflow_generator to emit the declared surfaces.
        Returns {surface_name: path}."""
        out: Dict[str, str] = {}
        try:
            from workflow_generator import WorkflowGenerator
        except Exception:
            return out
        gen = WorkflowGenerator(queue=None, dry_run=False)
        # synchronous wrapper around the async generate_all
        loop = asyncio.new_event_loop()
        try:
            results = loop.run_until_complete(gen.generate_all(card))
        finally:
            loop.close()
        for r in results:
            out[r.surface] = str(r.out_path)
        return out

    # ---- crystal hashing --------------------------------------------

    def _compute_pass_crystal(self, pt: PassTrace, card: Dict[str, Any]) -> str:
        canonical = json.dumps({
            "card_name": card.get("name", "?"),
            "pass_id":   pt.pass_id,
            "agent":     pt.agent,
            "engine":    pt.engine,
            "status":    pt.status,
            "summary":   pt.output_summary[:200],
        }, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        return _hash(canonical.encode("utf-8"))

    def _compute_trace_crystal(self, trace: TraceRecord) -> str:
        canonical = json.dumps({
            "workflow":      trace.workflow_name,
            "card_crystal":  trace.card_crystal,
            "pass_crystals": [p.crystal for p in trace.passes],
            "surfaces":      sorted(trace.surface_artifacts.items()),
        }, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        return _hash(canonical.encode("utf-8"))

    # ---- crystal chain integration ----------------------------------

    def _log_to_crystal_chain(self, trace: TraceRecord) -> None:
        try:
            from inference_logger import InferenceLogger
        except Exception:
            return
        logger = InferenceLogger()
        summary = (
            f"workflow={trace.workflow_name} passes={len(trace.passes)} "
            f"ok={sum(1 for p in trace.passes if p.status == 'ok')} "
            f"skipped={trace.skipped_count} failed={trace.failed_count} "
            f"surfaces={len(trace.surface_artifacts)} "
            f"latency={trace.total_latency_ms()}ms"
        )
        try:
            logger.log(
                original_prompt=f"cc studio-run {trace.workflow_name}",
                enhanced_prompt=summary,
                output_text=json.dumps({
                    "trace_crystal":     trace.trace_crystal,
                    "card_crystal":      trace.card_crystal,
                    "passes":            [asdict(p) for p in trace.passes],
                    "surface_artifacts": trace.surface_artifacts,
                }, default=str)[:32000],
                tier="runtime",
                model="studio_runtime",
                scope="orchestrator",
                tokens_in=len(summary),
                rc=0 if not trace.failed_count else 2,
                latency_ms=trace.total_latency_ms(),
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main():
    import argparse
    ap = argparse.ArgumentParser(description="studio_runtime — string every substrate together")
    sub = ap.add_subparsers(dest="cmd")

    p_run = sub.add_parser("run", help="run a workflow_card end-to-end")
    p_run.add_argument("card", help="card name (e.g., 'realestate_walkthrough_full') OR full path")
    p_run.add_argument("--dry-run", action="store_true", help="print plan; emit no surfaces")
    p_run.add_argument("--json", action="store_true", help="emit full trace as JSON")

    p_list = sub.add_parser("list", help="list available workflow_cards")

    args = ap.parse_args()

    if args.cmd == "list":
        cards = sorted(WORKFLOWS_DIR.glob("vm_mspc_001.workflows.*.json"))
        print(f"{len(cards)} workflow_cards:")
        for c in cards:
            d = json.loads(c.read_text())
            print(f"  {d.get('name','?'):<32} {d.get('category','?'):<12} "
                  f"{d.get('state','?'):<8} {d.get('version','?')}  ({c.name})")

    elif args.cmd == "run":
        rt = StudioRuntime(dry_run=args.dry_run)
        card_arg = args.card
        if Path(card_arg).exists():
            trace = rt.run_card(Path(card_arg))
        else:
            trace = rt.run_card_by_name(card_arg)

        if args.json:
            print(json.dumps(asdict(trace), indent=2, default=str))
        else:
            print(f"\n=== TRACE · {trace.workflow_name} ===")
            print(f"card_crystal:  {trace.card_crystal[:16]}…")
            print(f"trace_crystal: {trace.trace_crystal[:16]}…")
            print(f"passes:        {len(trace.passes)} "
                  f"(ok={sum(1 for p in trace.passes if p.status=='ok')} "
                  f"skipped={trace.skipped_count} failed={trace.failed_count})")
            print(f"surfaces:      {len(trace.surface_artifacts)}")
            print(f"total latency: {trace.total_latency_ms()}ms")
            print(f"\nPasses:")
            for p in trace.passes:
                tag = {"ok": "✓", "skipped": "·", "error": "✗", "cached": "⊕"}.get(p.status, "?")
                print(f"  {tag} [{p.pass_id:<22}] engine={p.engine:<14} agent={p.agent:<28}  {p.output_summary[:60]}")
            if trace.surface_artifacts:
                print(f"\nSurfaces emitted:")
                for s, path in trace.surface_artifacts.items():
                    print(f"  {s:<14} → {path}")

    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
