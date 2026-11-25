#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        pump_visualizer_3d
# role:        ENGINE · WAVE_FIELD_RENDERER · PUMP_FUN_3D_VIZ
# tier:        L0
# substrate:   ~/.cc/pump_waves/<crystal_short>.json  (one file per WaveFrame)
# storage:     ~/.cc/pump_waves/*.json + crystal anchors via inference_logger
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.pump_visualizer_3d.active.json
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - dApp HTTP GET /dapp/api/pump_wave (serves the latest WaveFrame JSON)
#   - Godot pump_surf_godot_scene (sibling agent G) reads the JSON contract
#   - core/cc.sh::cmd_pump_wave_build (future CLI driver)
# outbound:
#   - inference_logger.log (tier='visualization', model='pump_visualizer_3d',
#     scope='wave_frame_built'); writes WaveFrame JSON to ~/.cc/pump_waves/
# substrate touch:
#   - reads:  events JSONL produced by pump_stream_ingest + per-wallet gate
#             decisions dict produced by the GMM/XGBoost classifier
#   - writes: ~/.cc/pump_waves/<crystal_short>.json + master chain entry
# ----------------------------------------------------------------------------
# TOOLS / API
# ----------------------------------------------------------------------------
#   build_wave_frame(events, gate_decisions, window_seconds=60) -> WaveFrame
#   serialize_wave(wave, output_path=None) -> str (JSON)
#   render_svg_preview(wave, output_path=None) -> Path
#   Ripple, WaveFrame dataclasses
# ============================================================================
"""pump_visualizer_3d — Python-side 3D wave field renderer.

Consumes pump.fun stream events + GMM/XGBoost classifications and emits a
`WaveFrame` JSON consumable by the Godot pump_surf_godot_scene (sibling agent
G). Each transaction becomes a "ripple" in 3D space:

    X axis: time         (most recent on the right)
    Y axis: tx amplitude (sol_amount, log-scaled)
    Z axis: bot_probability (0=human green, 1=bot red)

Color derives from the gate decision (bot/human/surf_target). Particles flagged
`is_surf_target=True` when the gate decision was `surf_candidate`.

# Color mapping (RGBA in [0,1])
    bot     (bp >= 0.7)         -> red    [1.0, 0.2, 0.2, 0.8]
    human   (bp <= 0.3)         -> green  [0.2, 1.0, 0.4, 0.8]
    mid     (0.3 < bp < 0.7)    -> orange interpolation between green and red
    surf    (decision=='surf_candidate', always overrides) -> gold
                                  [1.0, 0.85, 0.0, 1.0]

# surf_state derivation
    abort           when bot_density_avg > 0.85 and human_inflow_score < 0.20
    exit_imminent   when active_position and human_inflow_score < 0.10
    surf_candidate  when bot_density_avg > 0.65 and human_inflow_score > 0.35
    no_signal       otherwise

# Crystal anchor
Every successful build_wave_frame crystal-anchors via inference_logger:
    tier='visualization', model='pump_visualizer_3d',
    scope='wave_frame_built',
    output_text='{"ripple_count": N, "surf_state": <state>, ...}'
WaveFrame JSON is persisted to ~/.cc/pump_waves/<crystal_short>.json.

# Stdlib only
json + math + dataclasses + pathlib + xml.etree.ElementTree + argparse + time.
NO numpy, NO matplotlib, NO svgwrite — Godot does the 3D, we do the data.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

# xml.etree for the SVG preview render — stdlib, no external dep
from xml.etree import ElementTree as ET


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Color palette — RGBA in [0,1], matches the Godot scene's material constants.
COLOR_BOT: List[float] = [1.0, 0.2, 0.2, 0.8]      # red
COLOR_HUMAN: List[float] = [0.2, 1.0, 0.4, 0.8]    # green
COLOR_SURF: List[float] = [1.0, 0.85, 0.0, 1.0]    # gold (overrides)
COLOR_BG: str = "#0b0d12"                          # SVG bg (deep slate)
COLOR_AXIS: str = "#1f2532"                        # SVG axis grid

# Thresholds for the categorical bands. Boundaries are inclusive on the
# bot/human ends so the interp band is strictly (0.3, 0.7).
BP_BOT_THRESHOLD: float = 0.7
BP_HUMAN_THRESHOLD: float = 0.3

# surf_state derivation thresholds (locked — Godot side keys off them too)
ABORT_BOT_DENSITY: float = 0.85
ABORT_HUMAN_INFLOW: float = 0.20
CANDIDATE_BOT_DENSITY: float = 0.65
CANDIDATE_HUMAN_INFLOW: float = 0.35
EXIT_HUMAN_INFLOW: float = 0.10

# Substrate
DEFAULT_OUT_DIR = Path.home() / ".cc" / "pump_waves"

# Inference logger path (graceful if absent — see _log_anchor)
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))


# ---------------------------------------------------------------------------
# Canonical dataclasses (JSON contract with Godot)
# ---------------------------------------------------------------------------


@dataclass
class Ripple:
    """One transaction rendered as a 3D ripple particle.

    All numeric axes are normalized to [0,1] so the Godot scene can apply its
    own world-space scaling without re-deriving the window bounds.
    """
    ts: float                       # original event timestamp (unix seconds)
    x: float                        # 0..1 normalized time position
    y: float                        # 0..1 normalized log(amount)
    z: float                        # 0..1 == bot_probability
    color_rgba: List[float] = field(default_factory=lambda: [1.0, 1.0, 1.0, 1.0])
    intensity: float = 0.0          # 0..1 (priority_fee normalized to window)
    is_surf_target: bool = False
    wallet: str = ""
    mint: str = ""
    kind: str = ""                  # 'buy' | 'sell'


@dataclass
class WaveFrame:
    """A window of pump.fun activity rendered as a wave field for Godot.

    The `crystal` field is the blake3-anchored chain id returned by
    inference_logger.log; downstream callers can reference it to dedupe or
    join with the master chain.
    """
    captured_at: float
    window_seconds: int
    ripples: List[Ripple] = field(default_factory=list)
    bot_density_avg: float = 0.0       # 0..1 — overall bot prevalence
    human_inflow_score: float = 0.0    # 0..1 — companion signal for exec
    surf_state: str = "no_signal"      # no_signal|surf_candidate|exit_imminent|abort
    crystal: str = ""


# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------


def _interp_color(bp: float) -> List[float]:
    """Linearly interpolate green->red across the mid band (0.3 < bp < 0.7)."""
    # Clamp the interp window to its actual interior so the endpoints align
    # with the categorical bands.
    lo, hi = BP_HUMAN_THRESHOLD, BP_BOT_THRESHOLD
    if bp <= lo:
        return list(COLOR_HUMAN)
    if bp >= hi:
        return list(COLOR_BOT)
    t = (bp - lo) / (hi - lo)
    r = COLOR_HUMAN[0] + (COLOR_BOT[0] - COLOR_HUMAN[0]) * t
    g = COLOR_HUMAN[1] + (COLOR_BOT[1] - COLOR_HUMAN[1]) * t
    b = COLOR_HUMAN[2] + (COLOR_BOT[2] - COLOR_HUMAN[2]) * t
    a = COLOR_HUMAN[3] + (COLOR_BOT[3] - COLOR_HUMAN[3]) * t
    return [round(r, 4), round(g, 4), round(b, 4), round(a, 4)]


def _color_for(bp: float, is_surf: bool) -> List[float]:
    """surf_target color always overrides bot/human/interp."""
    if is_surf:
        return list(COLOR_SURF)
    return _interp_color(bp)


def _rgba_to_hex(rgba: List[float]) -> str:
    """[r,g,b,a] floats -> '#rrggbb' (drop alpha for SVG fill)."""
    r = max(0, min(255, int(round(rgba[0] * 255))))
    g = max(0, min(255, int(round(rgba[1] * 255))))
    b = max(0, min(255, int(round(rgba[2] * 255))))
    return f"#{r:02x}{g:02x}{b:02x}"


# ---------------------------------------------------------------------------
# Aggregate scoring
# ---------------------------------------------------------------------------


def _bot_density(gate_decisions: Dict[str, Dict[str, Any]]) -> float:
    """Mean of all wallets' bot_probability in this window. Missing -> 0.0."""
    if not gate_decisions:
        return 0.0
    vals: List[float] = []
    for g in gate_decisions.values():
        if not isinstance(g, dict):
            continue
        bp = g.get("bot_probability")
        if bp is None:
            continue
        try:
            vals.append(float(bp))
        except (TypeError, ValueError):
            continue
    return round(sum(vals) / len(vals), 4) if vals else 0.0


def _human_inflow(gate_decisions: Dict[str, Dict[str, Any]]) -> float:
    """Mean of all wallets' human_inflow_score in this window.

    Defined per-wallet by the GMM/XGBoost gate (not derived here). We average
    so the WaveFrame carries one window-level companion signal for the surf
    executor — independent of bot_density so the two-axis state table works.
    """
    if not gate_decisions:
        return 0.0
    vals: List[float] = []
    for g in gate_decisions.values():
        if not isinstance(g, dict):
            continue
        hi = g.get("human_inflow_score")
        if hi is None:
            continue
        try:
            vals.append(float(hi))
        except (TypeError, ValueError):
            continue
    return round(sum(vals) / len(vals), 4) if vals else 0.0


def _derive_surf_state(bot_density_avg: float,
                        human_inflow_score: float,
                        active_position: bool = False) -> str:
    """Locked state table — see module docstring.

    Order matters: abort first (most dangerous), then exit_imminent (we're
    holding and humans are leaving), then surf_candidate (entry signal).
    """
    if bot_density_avg > ABORT_BOT_DENSITY and human_inflow_score < ABORT_HUMAN_INFLOW:
        return "abort"
    if active_position and human_inflow_score < EXIT_HUMAN_INFLOW:
        return "exit_imminent"
    if bot_density_avg > CANDIDATE_BOT_DENSITY and human_inflow_score > CANDIDATE_HUMAN_INFLOW:
        return "surf_candidate"
    return "no_signal"


# ---------------------------------------------------------------------------
# Crystal anchor (graceful if inference_logger absent)
# ---------------------------------------------------------------------------


def _log_anchor(ripple_count: int, surf_state: str,
                  bot_density_avg: float, human_inflow_score: float,
                  window_seconds: int) -> str:
    """Crystal-anchor one WaveFrame build via inference_logger. Best-effort:
    returns the chain crystal id, or '' on failure (e.g. logger absent).
    """
    try:
        from inference_logger import InferenceLogger  # type: ignore
        il = InferenceLogger()
        summary = {
            "ripple_count": ripple_count,
            "surf_state": surf_state,
            "bot_density_avg": bot_density_avg,
            "human_inflow_score": human_inflow_score,
            "window_seconds": window_seconds,
        }
        return il.log(
            original_prompt=f"pump_visualizer_3d.build_wave_frame window={window_seconds}s",
            enhanced_prompt=f"ripples={ripple_count} surf_state={surf_state}",
            output_text=json.dumps(summary, separators=(",", ":")),
            tier="visualization",
            model="pump_visualizer_3d",
            scope="wave_frame_built",
            source_action="pump_visualizer_3d.build_wave_frame",
            source_file=__file__,
            done_flag=True,
            rc=0,
        ) or ""
    except Exception as e:
        sys.stderr.write(
            f"warn: pump_visualizer_3d crystal log failed: {type(e).__name__}: {e}\n"
        )
        return ""


def _persist_wave(wave: WaveFrame, out_dir: Path = DEFAULT_OUT_DIR) -> Optional[Path]:
    """Write ~/.cc/pump_waves/<crystal_short>.json — best-effort, returns path
    or None on failure. crystal_short = first 16 hex chars of crystal id;
    falls back to a timestamp if the crystal id is empty (logger unavailable).
    """
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        if wave.crystal:
            tag = wave.crystal[:16]
        else:
            tag = f"nochain_{int(wave.captured_at)}"
        path = out_dir / f"{tag}.json"
        path.write_text(serialize_wave(wave))
        return path
    except Exception as e:
        sys.stderr.write(
            f"warn: pump_visualizer_3d persist failed: {type(e).__name__}: {e}\n"
        )
        return None


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def build_wave_frame(events: List[Dict[str, Any]],
                      gate_decisions: Dict[str, Dict[str, Any]],
                      window_seconds: int = 60,
                      active_position: bool = False,
                      now: Optional[float] = None) -> WaveFrame:
    """Take a window of stream events + per-wallet gate decisions; build a
    WaveFrame.

    Args:
        events:           list of pump_stream_ingest event dicts (see schema
                          in pump_stream_ingest.PumpEvent)
        gate_decisions:   wallet -> {decision, bot_probability,
                          human_inflow_score, ...} from GMM/XGBoost gate
        window_seconds:   width of the time window for normalization
        active_position:  True when the surf executor is currently holding a
                          position — drives 'exit_imminent' derivation
        now:              override the wall-clock anchor (defaults to time())

    Returns:
        WaveFrame with normalized ripples + derived signals + crystal anchor.
    """
    captured_at = float(now) if now is not None else time.time()

    # Window bounds
    t_lo = captured_at - float(window_seconds)
    t_hi = captured_at

    # First pass: collect log-amount and fee ranges for normalization.
    # We log-scale amounts so a 0.01 SOL tx and a 5 SOL tx render on a
    # comparable Y axis. log1p keeps zero-amount events from blowing up the
    # log; we add eps to be safe.
    eps = 1e-9
    log_amounts: List[float] = []
    fees: List[int] = []
    for ev in events:
        ts = _safe_float(ev.get("ts"), 0.0)
        if not (t_lo <= ts <= t_hi):
            continue
        amt = _safe_float(ev.get("sol_amount"), 0.0)
        log_amounts.append(math.log1p(max(amt, 0.0) + eps))
        try:
            fees.append(int(ev.get("priority_fee_lamports") or 0))
        except (TypeError, ValueError):
            fees.append(0)

    amt_min = min(log_amounts) if log_amounts else 0.0
    amt_max = max(log_amounts) if log_amounts else 1.0
    amt_span = (amt_max - amt_min) or 1.0  # avoid div-by-zero on flat window
    fee_min = min(fees) if fees else 0
    fee_max = max(fees) if fees else 1
    fee_span = float(fee_max - fee_min) or 1.0

    # Second pass: build ripples.
    ripples: List[Ripple] = []
    for ev in events:
        ts = _safe_float(ev.get("ts"), 0.0)
        if not (t_lo <= ts <= t_hi):
            continue

        wallet = str(ev.get("payer") or "")
        gate = gate_decisions.get(wallet) or {}
        bp = _safe_float(gate.get("bot_probability"), 0.0)
        bp = max(0.0, min(1.0, bp))
        is_surf = (str(gate.get("decision") or "") == "surf_candidate")

        # X: time position in window, 0=oldest, 1=newest
        x = (ts - t_lo) / float(window_seconds)
        x = max(0.0, min(1.0, x))

        # Y: log-scaled amount, normalized to window's [amt_min, amt_max]
        amt = _safe_float(ev.get("sol_amount"), 0.0)
        log_amt = math.log1p(max(amt, 0.0) + eps)
        y = (log_amt - amt_min) / amt_span
        y = max(0.0, min(1.0, y))

        # Z: bot probability, already in [0,1]
        z = bp

        # Intensity: priority_fee normalized to window
        try:
            fee = int(ev.get("priority_fee_lamports") or 0)
        except (TypeError, ValueError):
            fee = 0
        intensity = (fee - fee_min) / fee_span if fee_span else 0.0
        intensity = max(0.0, min(1.0, intensity))

        ripples.append(Ripple(
            ts=ts,
            x=round(x, 4),
            y=round(y, 4),
            z=round(z, 4),
            color_rgba=_color_for(bp, is_surf),
            intensity=round(intensity, 4),
            is_surf_target=is_surf,
            wallet=wallet,
            mint=str(ev.get("mint") or ""),
            kind=str(ev.get("kind") or ""),
        ))

    bot_density_avg = _bot_density(gate_decisions)
    human_inflow_score = _human_inflow(gate_decisions)
    surf_state = _derive_surf_state(
        bot_density_avg, human_inflow_score, active_position=active_position,
    )

    crystal = _log_anchor(
        ripple_count=len(ripples),
        surf_state=surf_state,
        bot_density_avg=bot_density_avg,
        human_inflow_score=human_inflow_score,
        window_seconds=window_seconds,
    )

    wave = WaveFrame(
        captured_at=captured_at,
        window_seconds=window_seconds,
        ripples=ripples,
        bot_density_avg=bot_density_avg,
        human_inflow_score=human_inflow_score,
        surf_state=surf_state,
        crystal=crystal,
    )

    _persist_wave(wave)
    return wave


# ---------------------------------------------------------------------------
# Serialize
# ---------------------------------------------------------------------------


def serialize_wave(wave: WaveFrame, output_path: Optional[Path] = None) -> str:
    """Emit JSON. Godot scene reads this via HTTP GET /dapp/api/pump_wave.

    The JSON contract is asdict(WaveFrame); each ripple is asdict(Ripple).
    Stable key ordering inside dicts (Python 3.7+ insertion order).
    """
    payload = asdict(wave)
    text = json.dumps(payload, separators=(",", ":"))
    if output_path is not None:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
    return text


# ---------------------------------------------------------------------------
# SVG preview (top-down 2D projection)
# ---------------------------------------------------------------------------


def render_svg_preview(wave: WaveFrame,
                        output_path: Optional[Path] = None,
                        width: int = 800,
                        height: int = 400) -> Path:
    """Stdlib SVG render of the wave as a top-down 2D projection.

    Layout:
        - X (horizontal) = time (ripple.x * width, with a small margin)
        - Y (vertical)   = amount (1 - ripple.y) * height (top = high amount)
        - Z (color)      = ripple.color_rgba (alpha encoded in opacity)
        - radius         = 3 + intensity * 5 (so high-fee tx pop)

    Header annotates surf_state + bot_density_avg + human_inflow_score so the
    preview is usable in dApp panels and emails without a legend.
    """
    margin = 24
    plot_w = width - 2 * margin
    plot_h = height - 2 * margin

    svg = ET.Element("svg", {
        "xmlns": "http://www.w3.org/2000/svg",
        "width": str(width),
        "height": str(height),
        "viewBox": f"0 0 {width} {height}",
    })

    # Background
    ET.SubElement(svg, "rect", {
        "x": "0", "y": "0", "width": str(width), "height": str(height),
        "fill": COLOR_BG,
    })

    # Axis frame
    ET.SubElement(svg, "rect", {
        "x": str(margin), "y": str(margin),
        "width": str(plot_w), "height": str(plot_h),
        "fill": "none", "stroke": COLOR_AXIS, "stroke-width": "1",
    })

    # Gridlines (4 horizontal, 4 vertical — visual anchor for the eye)
    for i in range(1, 4):
        gy = margin + (plot_h * i / 4)
        ET.SubElement(svg, "line", {
            "x1": str(margin), "y1": f"{gy:.1f}",
            "x2": str(width - margin), "y2": f"{gy:.1f}",
            "stroke": COLOR_AXIS, "stroke-width": "0.5",
        })
        gx = margin + (plot_w * i / 4)
        ET.SubElement(svg, "line", {
            "x1": f"{gx:.1f}", "y1": str(margin),
            "x2": f"{gx:.1f}", "y2": str(height - margin),
            "stroke": COLOR_AXIS, "stroke-width": "0.5",
        })

    # Ripples — sort so surf_target ripples render last (on top)
    sorted_ripples = sorted(wave.ripples, key=lambda r: (r.is_surf_target, r.intensity))
    for r in sorted_ripples:
        cx = margin + r.x * plot_w
        cy = margin + (1.0 - r.y) * plot_h
        radius = 3.0 + r.intensity * 5.0
        if r.is_surf_target:
            radius += 1.5  # bump surf targets so they read instantly
        fill = _rgba_to_hex(r.color_rgba)
        opacity = max(0.0, min(1.0, r.color_rgba[3] if len(r.color_rgba) >= 4 else 1.0))
        circle = ET.SubElement(svg, "circle", {
            "cx": f"{cx:.1f}", "cy": f"{cy:.1f}",
            "r": f"{radius:.1f}",
            "fill": fill,
            "fill-opacity": f"{opacity:.2f}",
        })
        if r.is_surf_target:
            circle.set("stroke", "#ffffff")
            circle.set("stroke-width", "1.5")

    # Header text — surf_state + signals
    header = (
        f"surf_state: {wave.surf_state}   |   "
        f"bot_density: {wave.bot_density_avg:.2f}   |   "
        f"human_inflow: {wave.human_inflow_score:.2f}   |   "
        f"ripples: {len(wave.ripples)}"
    )
    t = ET.SubElement(svg, "text", {
        "x": str(margin),
        "y": str(margin - 8),
        "fill": "#cfd6e2",
        "font-family": "ui-monospace, Menlo, Consolas, monospace",
        "font-size": "11",
    })
    t.text = header

    # Axis labels
    xlabel = ET.SubElement(svg, "text", {
        "x": str(width // 2),
        "y": str(height - 6),
        "fill": "#5a6378",
        "text-anchor": "middle",
        "font-family": "ui-monospace, Menlo, Consolas, monospace",
        "font-size": "10",
    })
    xlabel.text = f"time -> ({wave.window_seconds}s window, newest on right)"

    ylabel = ET.SubElement(svg, "text", {
        "x": "12", "y": str(height // 2),
        "fill": "#5a6378",
        "text-anchor": "middle",
        "font-family": "ui-monospace, Menlo, Consolas, monospace",
        "font-size": "10",
        "transform": f"rotate(-90 12 {height // 2})",
    })
    ylabel.text = "log(sol_amount) ->"

    # Serialize
    out = Path(output_path) if output_path else Path("/tmp/pump_wave_preview.svg")
    out.parent.mkdir(parents=True, exist_ok=True)
    # ET.tostring uses bytes by default; encode with xml decl for legibility
    xml_bytes = ET.tostring(svg, encoding="utf-8", xml_declaration=True)
    out.write_bytes(xml_bytes)
    return out


# ---------------------------------------------------------------------------
# JSONL loading helpers (CLI side)
# ---------------------------------------------------------------------------


def _load_events(path: Path) -> List[Dict[str, Any]]:
    """Read pump_stream_ingest JSONL — one event per line."""
    events: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def _load_gates(path: Path) -> Dict[str, Dict[str, Any]]:
    """Read gate decisions JSON — wallet -> decision dict."""
    text = Path(path).read_text(encoding="utf-8")
    obj = json.loads(text)
    if not isinstance(obj, dict):
        raise SystemExit(f"gates file {path} is not a JSON object")
    return obj


def _load_wave(path: Path) -> WaveFrame:
    """Reconstitute a WaveFrame from a previously serialized JSON file."""
    obj = json.loads(Path(path).read_text(encoding="utf-8"))
    ripples = [Ripple(**r) for r in obj.get("ripples", [])]
    return WaveFrame(
        captured_at=obj.get("captured_at", 0.0),
        window_seconds=obj.get("window_seconds", 60),
        ripples=ripples,
        bot_density_avg=obj.get("bot_density_avg", 0.0),
        human_inflow_score=obj.get("human_inflow_score", 0.0),
        surf_state=obj.get("surf_state", "no_signal"),
        crystal=obj.get("crystal", ""),
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_build(args: argparse.Namespace) -> int:
    events_path = Path(args.events)
    if not events_path.exists():
        sys.stderr.write(f"error: events file not found: {events_path}\n")
        return 2
    events = _load_events(events_path)

    gates: Dict[str, Dict[str, Any]] = {}
    if args.gates:
        gates_path = Path(args.gates)
        if not gates_path.exists():
            sys.stderr.write(f"error: gates file not found: {gates_path}\n")
            return 2
        gates = _load_gates(gates_path)

    wave = build_wave_frame(
        events=events,
        gate_decisions=gates,
        window_seconds=int(args.window),
        active_position=bool(args.active_position),
    )

    out_path = Path(args.out) if args.out else None
    text = serialize_wave(wave, output_path=out_path)

    summary = {
        "ripple_count": len(wave.ripples),
        "surf_state": wave.surf_state,
        "bot_density_avg": wave.bot_density_avg,
        "human_inflow_score": wave.human_inflow_score,
        "crystal": wave.crystal,
        "out": str(out_path) if out_path else None,
        "bytes": len(text),
    }
    print(json.dumps(summary, separators=(",", ":")))
    return 0


def _cmd_preview(args: argparse.Namespace) -> int:
    wave_path = Path(args.wave)
    if not wave_path.exists():
        sys.stderr.write(f"error: wave file not found: {wave_path}\n")
        return 2
    wave = _load_wave(wave_path)
    out_path = Path(args.out) if args.out else None
    path = render_svg_preview(wave, output_path=out_path)
    print(json.dumps({"svg": str(path), "ripples": len(wave.ripples),
                       "surf_state": wave.surf_state}, separators=(",", ":")))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pump_visualizer_3d",
        description="Pump.fun stream -> WaveFrame JSON for Godot 3D scene.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pb = sub.add_parser("build", help="build a WaveFrame JSON")
    pb.add_argument("--events", required=True, help="JSONL events from pump_stream_ingest")
    pb.add_argument("--gates", default="", help="JSON wallet->gate decision (optional)")
    pb.add_argument("--window", type=int, default=60, help="window seconds (default 60)")
    pb.add_argument("--out", default="", help="output WaveFrame JSON path")
    pb.add_argument("--active-position", action="store_true",
                    dest="active_position",
                    help="set when surf executor holds an open position")
    pb.set_defaults(func=_cmd_build)

    pp = sub.add_parser("preview", help="render SVG preview of a WaveFrame")
    pp.add_argument("wave", help="WaveFrame JSON path")
    pp.add_argument("--out", default="", help="output SVG path (default /tmp)")
    pp.set_defaults(func=_cmd_preview)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
