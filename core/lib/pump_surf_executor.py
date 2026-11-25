#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        pump_surf_executor
# role:        EXECUTOR  PUMP_FUN_SURF_TRADING_LOOP
# tier:        L0
# substrate:   pump.fun / PumpSwap rail driver consuming XGBoost gate decisions
# storage:     ~/.cc/pump_surf_orders.jsonl
#              ~/.cc/pump_surf_daily.json
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.pump_surf_executor.active.json
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - pump_xgboost_gate (parallel agent D) emits GateDecision per window
#   - core/cc.sh::cmd_pump_surf_* (future)
# outbound:
#   - inference_logger.log (tier='trade_action', model='pump_surf')
#   - (live mode only, future) solana_mcp.transfer SOL  mint via PumpSwap
# substrate touch:
#   - reads:  PUMP_SURF_LIVE_TRADING, PUMP_SURF_MAX_SOL_PER_TRADE,
#             PUMP_SURF_MAX_SOL_PER_DAY, SOLANA_NETWORK from process env
#   - writes: ~/.cc/pump_surf_orders.jsonl, ~/.cc/pump_surf_daily.json,
#             ~/.cc/inference_master_chain.jsonl
# ============================================================================
"""pump_surf_executor.py  pump.fun "surf" trading loop with HARD DRY-RUN.

THE LAW (matches topstep_mcp pattern exactly):
    Every BUY/SELL order DEFAULTS to DRY-RUN. A real on-chain swap ONLY fires
    when ALL THREE are true:
      (1) SOLANA_NETWORK=mainnet-beta              in process env
      (2) PUMP_SURF_LIVE_TRADING=1                 in process env
      (3) confirm=True                             in the call args
    ANY missing condition  DRY-RUN regardless. No exceptions.

    Per-trade SOL cap: PUMP_SURF_MAX_SOL_PER_TRADE (default 0.1)
    Per-day  SOL cap: PUMP_SURF_MAX_SOL_PER_DAY   (default 1.0)
    Daily ledger lives in ~/.cc/pump_surf_daily.json (UTC date keyed).

Strategy (the "surf"):
    Follow large bot-driven volume on a fresh mint, ride the human-inflow wake,
    exit before the bot dumps.

    BUY when gate emits decision='surf_candidate' AND no active position AND
    daily cap not breached AND per-trade cap respected.

    SELL when active position AND any of:
      - human_inflow flatlined  (consecutive_flat_ticks >= 3)
      - bot exit imminent       (bot_prob > 0.95 AND human_inflow < 0.15)
      - hard timeout            (time-in-position > 30 minutes)

Crystal anchor:
    Every order (DRY-RUN or live) writes one InferenceRecord with
      tier='trade_action', model='pump_surf', scope='buy' | 'sell'.
    DRY-RUN flag embedded in output_text + coordinates so audit can split.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
LIVE_ENV_VAR = "PUMP_SURF_LIVE_TRADING"
LIVE_ENV_VALUE = "1"
NETWORK_ENV_VAR = "SOLANA_NETWORK"
NETWORK_LIVE_VALUE = "mainnet-beta"

CAP_PER_TRADE_ENV = "PUMP_SURF_MAX_SOL_PER_TRADE"
CAP_PER_DAY_ENV = "PUMP_SURF_MAX_SOL_PER_DAY"
DEFAULT_CAP_PER_TRADE = 0.1
DEFAULT_CAP_PER_DAY = 1.0

CC_DIR = Path.home() / ".cc"
ORDERS_LOG = CC_DIR / "pump_surf_orders.jsonl"
DAILY_LEDGER = CC_DIR / "pump_surf_daily.json"

# Exit-decision defaults
DEFAULT_EXIT = {
    "flat_tick_threshold": 3,           # consecutive windows with flat human_inflow
    "flat_entropy_eps": 0.01,           # human_inflow swing < this = "flat"
    "bot_dump_prob_threshold": 0.95,    # bot_prob above this = exit imminent
    "bot_dump_inflow_threshold": 0.15,  # human_inflow below this = no buyers left
    "hard_timeout_seconds": 30 * 60,    # 30 minutes
}


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------
@dataclass
class SurfOrder:
    ts: float
    kind: str             # 'buy' | 'sell'
    mint: str
    sol_amount: float
    target_wallet: str    # the surf-target wallet whose momentum we're following
    bot_prob: float
    human_inflow: float
    rationale: str
    dry_run: bool
    tx_signature: str     # empty in dry-run mode
    crystal: str
    error: str = ""


@dataclass
class SurfState:
    active_position: bool = False
    position_mint: str = ""
    position_sol_in: float = 0.0
    position_entry_ts: float = 0.0
    last_human_inflow: float = 0.0
    consecutive_flat_ticks: int = 0


# Stub of GateDecision (parallel agent D will emit the real type).
# We define it locally so this module imports without the gate landing first.
@dataclass
class GateDecision:
    decision: str                 # 'surf_candidate' | 'skip' | 'wait'
    mint: str = ""
    target_wallet: str = ""
    bot_prob: float = 0.0
    human_inflow: float = 0.0
    rationale: str = ""
    ts: float = 0.0


# ---------------------------------------------------------------------------
# Safety primitives
# ---------------------------------------------------------------------------
def _live_trading_enabled() -> bool:
    """All three gates open?"""
    return (os.environ.get(NETWORK_ENV_VAR, "") == NETWORK_LIVE_VALUE
            and os.environ.get(LIVE_ENV_VAR, "") == LIVE_ENV_VALUE)


def _gates_state(confirm: bool) -> Dict[str, bool]:
    return {
        "solana_network_mainnet": (
            os.environ.get(NETWORK_ENV_VAR, "") == NETWORK_LIVE_VALUE),
        "pump_surf_live_env":     (
            os.environ.get(LIVE_ENV_VAR, "") == LIVE_ENV_VALUE),
        "confirm":                bool(confirm),
    }


def _is_dry_run(confirm: bool) -> bool:
    """Strict: if ANY of the 3 conditions is missing  DRY-RUN."""
    g = _gates_state(confirm)
    return not (g["solana_network_mainnet"]
                and g["pump_surf_live_env"]
                and g["confirm"])


def _cap_per_trade() -> float:
    try:
        return float(os.environ.get(CAP_PER_TRADE_ENV) or DEFAULT_CAP_PER_TRADE)
    except (ValueError, TypeError):
        return DEFAULT_CAP_PER_TRADE


def _cap_per_day() -> float:
    try:
        return float(os.environ.get(CAP_PER_DAY_ENV) or DEFAULT_CAP_PER_DAY)
    except (ValueError, TypeError):
        return DEFAULT_CAP_PER_DAY


# ---------------------------------------------------------------------------
# Daily ledger  ~/.cc/pump_surf_daily.json
# ---------------------------------------------------------------------------
def _today_utc() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def _ensure_cc_dir() -> None:
    try:
        CC_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


def _load_daily() -> Dict[str, Any]:
    _ensure_cc_dir()
    if not DAILY_LEDGER.exists():
        return {}
    try:
        return json.loads(DAILY_LEDGER.read_text(encoding="utf-8") or "{}")
    except (OSError, json.JSONDecodeError):
        return {}


def _save_daily(data: Dict[str, Any]) -> None:
    _ensure_cc_dir()
    try:
        tmp = DAILY_LEDGER.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True),
                       encoding="utf-8")
        tmp.replace(DAILY_LEDGER)
    except OSError as e:
        sys.stderr.write(f"warn: daily ledger save failed: {e}\n")


def _daily_used_sol() -> float:
    d = _load_daily()
    today = _today_utc()
    try:
        return float(d.get(today, {}).get("sol_in", 0.0))
    except (TypeError, ValueError):
        return 0.0


def _add_daily_sol(amount: float) -> None:
    if amount <= 0:
        return
    d = _load_daily()
    today = _today_utc()
    cur = d.get(today, {"sol_in": 0.0, "trades": 0})
    try:
        cur["sol_in"] = float(cur.get("sol_in", 0.0)) + float(amount)
    except (TypeError, ValueError):
        cur["sol_in"] = float(amount)
    cur["trades"] = int(cur.get("trades", 0)) + 1
    d[today] = cur
    _save_daily(d)


# ---------------------------------------------------------------------------
# Crystal anchor
# ---------------------------------------------------------------------------
def _crystal_anchor(order: SurfOrder) -> str:
    """Append one InferenceRecord with tier='trade_action', model='pump_surf'.
    Returns crystal_id ('' on logger failure)."""
    try:
        from inference_logger import InferenceLogger  # type: ignore
        il = InferenceLogger()
        payload = {
            "kind": order.kind,
            "mint": order.mint,
            "sol_amount": order.sol_amount,
            "target_wallet": order.target_wallet,
            "bot_prob": order.bot_prob,
            "human_inflow": order.human_inflow,
            "dry_run": order.dry_run,
            "tx_signature": order.tx_signature,
            "error": order.error,
        }
        coords = [{
            "axis": "dry_run",
            "value": 1 if order.dry_run else 0,
        }]
        return il.log(
            original_prompt=f"pump_surf.{order.kind}",
            enhanced_prompt=order.rationale[:512],
            output_text=json.dumps(payload, separators=(",", ":"))[:512],
            tier="trade_action",
            model="pump_surf",
            scope=order.kind,
            tokens_in=0, tokens_out=0,
            latency_ms=0,
            source_action=f"pump_surf.{order.kind}",
            done_flag=not order.error,
            rc=0 if not order.error else 1,
            coordinates=coords,
        ) or ""
    except Exception as e:
        sys.stderr.write(f"warn: pump_surf crystal log failed: "
                         f"{type(e).__name__}: {e}\n")
        return ""


# ---------------------------------------------------------------------------
# Order persistence
# ---------------------------------------------------------------------------
def _append_order_log(order: SurfOrder) -> None:
    _ensure_cc_dir()
    try:
        with open(ORDERS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(order), separators=(",", ":")) + "\n")
    except OSError as e:
        sys.stderr.write(f"warn: order log append failed: {e}\n")


# ---------------------------------------------------------------------------
# Decision: BUY
# ---------------------------------------------------------------------------
def consider_buy(gate_decision: GateDecision,
                 current_state: SurfState,
                 recent_window: Optional[List[Dict[str, Any]]] = None,
                 confirm: bool = False) -> Optional[SurfOrder]:
    """If gate says surf_candidate, no active position, daily+per-trade caps
    not breached: emit BUY order (DRY-RUN unless live env+flag+confirm).
    Returns None if BUY is not appropriate this tick."""
    if gate_decision is None:
        return None
    if getattr(gate_decision, "decision", "") != "surf_candidate":
        return None
    if current_state.active_position:
        return None

    ts = float(getattr(gate_decision, "ts", 0.0)) or time.time()
    mint = str(getattr(gate_decision, "mint", "") or "")
    target = str(getattr(gate_decision, "target_wallet", "") or "")
    bot_prob = float(getattr(gate_decision, "bot_prob", 0.0) or 0.0)
    h_inflow = float(getattr(gate_decision, "human_inflow", 0.0) or 0.0)
    rationale = (getattr(gate_decision, "rationale", "")
                 or "bot_volume+human_inflow above surf threshold")

    # Determine sol amount  recent_window may carry a sizing hint.
    sol_amount = _cap_per_trade()
    if recent_window:
        try:
            last = recent_window[-1]
            hint = last.get("suggested_sol_in")
            if hint is not None:
                sol_amount = min(float(hint), _cap_per_trade())
        except (TypeError, ValueError, AttributeError, IndexError):
            pass

    dry_run = _is_dry_run(confirm)

    # Per-trade cap
    if sol_amount > _cap_per_trade():
        order = SurfOrder(
            ts=ts, kind="buy", mint=mint, sol_amount=sol_amount,
            target_wallet=target, bot_prob=bot_prob, human_inflow=h_inflow,
            rationale=rationale, dry_run=True, tx_signature="",
            crystal="", error="exceeds_per_trade_cap",
        )
        return order

    # Per-day cap
    if not dry_run:
        used = _daily_used_sol()
        if used + sol_amount > _cap_per_day():
            return SurfOrder(
                ts=ts, kind="buy", mint=mint, sol_amount=sol_amount,
                target_wallet=target, bot_prob=bot_prob,
                human_inflow=h_inflow, rationale=rationale,
                dry_run=True, tx_signature="", crystal="",
                error="exceeds_per_day_cap",
            )

    return SurfOrder(
        ts=ts, kind="buy", mint=mint, sol_amount=sol_amount,
        target_wallet=target, bot_prob=bot_prob, human_inflow=h_inflow,
        rationale=rationale, dry_run=dry_run, tx_signature="", crystal="",
    )


# ---------------------------------------------------------------------------
# Decision: SELL
# ---------------------------------------------------------------------------
def consider_sell(current_state: SurfState,
                  latest_human_inflow: float,
                  latest_bot_prob: float,
                  exit_thresholds: Optional[Dict[str, Any]] = None,
                  confirm: bool = False) -> Optional[SurfOrder]:
    """If active position AND any exit condition holds: emit SELL.

    Exit conditions (any one fires):
      - consecutive_flat_ticks >= flat_tick_threshold (default 3)
      - bot_prob > 0.95 AND latest_human_inflow < 0.15  (bot dump imminent)
      - time-in-position > 30 min  (hard timeout)
    """
    if not current_state.active_position:
        return None

    th = dict(DEFAULT_EXIT)
    if exit_thresholds:
        th.update(exit_thresholds)

    now = time.time()
    elapsed = now - float(current_state.position_entry_ts or now)
    reasons: List[str] = []

    # Flat-line exit
    if int(current_state.consecutive_flat_ticks) >= int(th["flat_tick_threshold"]):
        reasons.append(
            f"human_inflow_flatline:{current_state.consecutive_flat_ticks}>="
            f"{int(th['flat_tick_threshold'])}")

    # Bot dump imminent
    if (float(latest_bot_prob) > float(th["bot_dump_prob_threshold"])
            and float(latest_human_inflow) < float(th["bot_dump_inflow_threshold"])):
        reasons.append(
            f"bot_dump_imminent:bot_prob={latest_bot_prob:.2f}>"
            f"{th['bot_dump_prob_threshold']} AND human_inflow="
            f"{latest_human_inflow:.2f}<{th['bot_dump_inflow_threshold']}")

    # Hard timeout
    if elapsed > float(th["hard_timeout_seconds"]):
        reasons.append(
            f"hard_timeout:{int(elapsed)}s>{int(th['hard_timeout_seconds'])}s")

    if not reasons:
        return None

    rationale = " | ".join(reasons)
    dry_run = _is_dry_run(confirm)

    return SurfOrder(
        ts=now, kind="sell", mint=current_state.position_mint,
        sol_amount=float(current_state.position_sol_in),
        target_wallet="",
        bot_prob=float(latest_bot_prob),
        human_inflow=float(latest_human_inflow),
        rationale=rationale, dry_run=dry_run, tx_signature="",
        crystal="",
    )


# ---------------------------------------------------------------------------
# Execution: log + (future) live invocation
# ---------------------------------------------------------------------------
def execute_dryrun_or_live(order: SurfOrder) -> SurfOrder:
    """Crystal-anchor + write to ~/.cc/pump_surf_orders.jsonl.
    DRY-RUN  log + return. Live  invoke solana_mcp.transfer (future).
    Errors do not raise; they populate order.error."""
    if order is None:
        return order  # type: ignore[return-value]

    # Refuse pre-flagged cap violations  log them anyway as DRY-RUN audit.
    if order.error in ("exceeds_per_trade_cap", "exceeds_per_day_cap"):
        order.dry_run = True
        order.tx_signature = ""
        order.crystal = _crystal_anchor(order)
        _append_order_log(order)
        sys.stderr.write(
            f"REFUSED: {order.error} for {order.kind} {order.sol_amount} SOL "
            f"of mint {order.mint}\n")
        return order

    if order.dry_run:
        sys.stderr.write(
            f"DRY-RUN: would have placed {order.kind} {order.sol_amount} SOL "
            f"of mint {order.mint}\n")
        order.tx_signature = ""
        order.crystal = _crystal_anchor(order)
        _append_order_log(order)
        return order

    # Live path  not wired here per task constraints (NO touching solana_mcp).
    # The 3-gate check has already passed; future patch will call
    # solana_mcp.transfer to swap via PumpSwap. For now mark as not-implemented
    # so the audit row carries the truth.
    order.error = "live_path_not_wired:solana_mcp_invocation_out_of_scope"
    order.dry_run = True  # demote to dry-run rather than silently succeed
    order.tx_signature = ""
    order.crystal = _crystal_anchor(order)
    _append_order_log(order)
    sys.stderr.write(
        "WARN: live gates open but live execution path is not wired in this "
        "executor (out of scope: solana_mcp untouched). Demoted to DRY-RUN.\n")
    return order


# ---------------------------------------------------------------------------
# State helpers used by the surf loop
# ---------------------------------------------------------------------------
def _update_state_after_buy(state: SurfState, order: SurfOrder) -> SurfState:
    if order.error or order.kind != "buy":
        return state
    if order.dry_run:
        # Even in DRY-RUN we still track the simulated position so SELL
        # decisions can be exercised in the same run.
        pass
    state.active_position = True
    state.position_mint = order.mint
    state.position_sol_in = order.sol_amount
    state.position_entry_ts = order.ts
    state.consecutive_flat_ticks = 0
    state.last_human_inflow = order.human_inflow
    if not order.dry_run:
        _add_daily_sol(order.sol_amount)
    return state


def _update_state_after_sell(state: SurfState, order: SurfOrder) -> SurfState:
    if order.error or order.kind != "sell":
        return state
    state.active_position = False
    state.position_mint = ""
    state.position_sol_in = 0.0
    state.position_entry_ts = 0.0
    state.consecutive_flat_ticks = 0
    return state


def _update_flat_counter(state: SurfState, latest_human_inflow: float,
                         flat_eps: float = DEFAULT_EXIT["flat_entropy_eps"]
                         ) -> SurfState:
    delta = abs(float(latest_human_inflow) - float(state.last_human_inflow))
    if delta < float(flat_eps):
        state.consecutive_flat_ticks += 1
    else:
        state.consecutive_flat_ticks = 0
    state.last_human_inflow = float(latest_human_inflow)
    return state


# ---------------------------------------------------------------------------
# Surf loop  consumes gate decisions (live pipeline stub or JSONL replay)
# ---------------------------------------------------------------------------
def _read_replay(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    try:
        for ln in path.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return out


def _row_to_gate_decision(row: Dict[str, Any]) -> GateDecision:
    """Best-effort: many replay rows carry the gate decision inline.
    Fall back to constructing a 'wait' decision so the loop is safe."""
    decision = (row.get("decision")
                or row.get("gate_decision")
                or ("surf_candidate" if row.get("surf_candidate") else "wait"))
    return GateDecision(
        decision=str(decision),
        mint=str(row.get("mint", "") or ""),
        target_wallet=str(row.get("target_wallet", "") or ""),
        bot_prob=float(row.get("bot_prob", 0.0) or 0.0),
        human_inflow=float(row.get("human_inflow", 0.0) or 0.0),
        rationale=str(row.get("rationale", "") or ""),
        ts=float(row.get("ts", 0.0) or 0.0),
    )


def surf_loop(duration_seconds: int = 0,
              max_orders: int = 0,
              replay_path: Optional[str] = None,
              confirm: bool = False) -> Dict[str, Any]:
    """Read gate decisions from a JSONL replay (when replay_path given) or
    no-op when no live pipeline is wired. Maintains SurfState. Returns
    {orders_emitted, dry_run_count, live_count, refused_count}."""
    state = SurfState()
    orders_emitted = 0
    dry_run_count = 0
    live_count = 0
    refused_count = 0
    t_start = time.time()

    rows: List[Dict[str, Any]] = []
    if replay_path:
        rows = _read_replay(Path(replay_path))

    if not rows:
        # No live pipeline stub yet  return cleanly.
        return {
            "orders_emitted": 0,
            "dry_run_count": 0,
            "live_count": 0,
            "refused_count": 0,
            "note": "no replay path and no live gate pipeline wired",
        }

    for row in rows:
        if duration_seconds > 0 and (time.time() - t_start) > duration_seconds:
            break
        if max_orders > 0 and orders_emitted >= max_orders:
            break

        gd = _row_to_gate_decision(row)

        # SELL check first (so we close stale positions before opening new)
        sell = consider_sell(state,
                             latest_human_inflow=gd.human_inflow,
                             latest_bot_prob=gd.bot_prob,
                             confirm=confirm)
        if sell is not None:
            sell = execute_dryrun_or_live(sell)
            state = _update_state_after_sell(state, sell)
            orders_emitted += 1
            if sell.error:
                refused_count += 1
            elif sell.dry_run:
                dry_run_count += 1
            else:
                live_count += 1

        # Update flat counter regardless
        state = _update_flat_counter(state, gd.human_inflow)

        # BUY check
        buy = consider_buy(gd, state, recent_window=[row], confirm=confirm)
        if buy is not None:
            buy = execute_dryrun_or_live(buy)
            state = _update_state_after_buy(state, buy)
            orders_emitted += 1
            if buy.error:
                refused_count += 1
            elif buy.dry_run:
                dry_run_count += 1
            else:
                live_count += 1

    return {
        "orders_emitted": orders_emitted,
        "dry_run_count": dry_run_count,
        "live_count": live_count,
        "refused_count": refused_count,
        "state": asdict(state),
    }


# ---------------------------------------------------------------------------
# CLI  always-safe surface
# ---------------------------------------------------------------------------
def _cmd_status() -> int:
    used = _daily_used_sol()
    cap_day = _cap_per_day()
    cap_trade = _cap_per_trade()
    last_orders = _tail_orders(1)
    last = last_orders[-1] if last_orders else None
    active = bool(last and last.get("kind") == "buy"
                  and not _has_matching_sell_after(last))
    out = {
        "date_utc": _today_utc(),
        "daily_sol_used": used,
        "daily_sol_cap": cap_day,
        "daily_remaining": max(0.0, cap_day - used),
        "per_trade_cap": cap_trade,
        "live_trading_enabled": _live_trading_enabled(),
        "gates": _gates_state(False),
        "active_position": active,
        "active_mint": (last or {}).get("mint", "") if active else "",
        "orders_log": str(ORDERS_LOG),
        "daily_ledger": str(DAILY_LEDGER),
    }
    print(json.dumps(out, indent=2))
    return 0


def _tail_orders(n: int) -> List[Dict[str, Any]]:
    if not ORDERS_LOG.exists():
        return []
    try:
        lines = ORDERS_LOG.read_text(encoding="utf-8").splitlines()[-n:]
        out = []
        for ln in lines:
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
        return out
    except OSError:
        return []


def _has_matching_sell_after(buy_row: Dict[str, Any]) -> bool:
    """True iff a later sell of the same mint exists in the log."""
    if not ORDERS_LOG.exists():
        return False
    try:
        lines = ORDERS_LOG.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    seen_buy = False
    for ln in lines:
        try:
            row = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if row == buy_row:
            seen_buy = True
            continue
        if (seen_buy
                and row.get("kind") == "sell"
                and row.get("mint") == buy_row.get("mint")):
            return True
    return False


def _cmd_order_log(n: int) -> int:
    rows = _tail_orders(n)
    for r in rows:
        print(json.dumps(r, separators=(",", ":")))
    return 0


def _cmd_buy(mint: str, sol: float, target_wallet: str,
             confirm: bool, bot_prob: float, human_inflow: float) -> int:
    gd = GateDecision(
        decision="surf_candidate",
        mint=mint,
        target_wallet=target_wallet,
        bot_prob=bot_prob,
        human_inflow=human_inflow,
        rationale="cli_buy_invocation",
        ts=time.time(),
    )
    state = SurfState()
    # Inject the sizing hint by clipping sol to per-trade cap up front.
    hint_row = {"suggested_sol_in": float(sol)}
    order = consider_buy(gd, state, recent_window=[hint_row], confirm=confirm)
    if order is None:
        print(json.dumps({
            "ok": False,
            "reason": "consider_buy returned None (gate or state blocked it)",
        }, indent=2))
        return 1
    # Honor the user-supplied amount even if larger than cap  so the cap
    # check can refuse cleanly.
    order.sol_amount = float(sol)
    if order.sol_amount > _cap_per_trade():
        order.error = "exceeds_per_trade_cap"
    order = execute_dryrun_or_live(order)
    print(json.dumps({
        "ok": not order.error,
        "kind": order.kind,
        "mint": order.mint,
        "sol_amount": order.sol_amount,
        "target_wallet": order.target_wallet,
        "dry_run": order.dry_run,
        "error": order.error,
        "tx_signature": order.tx_signature,
        "crystal": order.crystal,
        "gates": _gates_state(confirm),
        "per_trade_cap": _cap_per_trade(),
    }, indent=2))
    return 0 if not order.error else 1


def _cmd_simulate(replay: str, confirm: bool) -> int:
    res = surf_loop(replay_path=replay, confirm=confirm)
    print(json.dumps(res, indent=2))
    return 0


def _main() -> int:
    ap = argparse.ArgumentParser(
        description="pump_surf_executor  surf trading loop "
                    "(DRY-RUN by default; live needs 3 gates)")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("status", help="active position + daily cap usage")

    p_log = sub.add_parser("order-log", help="tail recent orders")
    p_log.add_argument("-n", type=int, default=20)

    p_sim = sub.add_parser("simulate", help="replay a JSONL of gate decisions")
    p_sim.add_argument("--replay", required=True)
    p_sim.add_argument("--confirm", action="store_true")

    p_buy = sub.add_parser("buy", help="DRY-RUN unless 3 gates open")
    p_buy.add_argument("--mint", required=True)
    p_buy.add_argument("--sol", type=float, required=True)
    p_buy.add_argument("--target-wallet", required=True)
    p_buy.add_argument("--confirm", action="store_true")
    p_buy.add_argument("--bot-prob", type=float, default=0.7)
    p_buy.add_argument("--human-inflow", type=float, default=0.6)

    args = ap.parse_args()
    if args.cmd == "status":
        return _cmd_status()
    if args.cmd == "order-log":
        return _cmd_order_log(int(args.n))
    if args.cmd == "simulate":
        return _cmd_simulate(args.replay, bool(args.confirm))
    if args.cmd == "buy":
        return _cmd_buy(args.mint, float(args.sol), args.target_wallet,
                        bool(args.confirm),
                        float(args.bot_prob), float(args.human_inflow))
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(_main())
