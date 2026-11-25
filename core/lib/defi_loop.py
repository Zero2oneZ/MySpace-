#!/usr/bin/env python3
# ============================================================================
# AGENT CARD                                                                  =
# ----------------------------------------------------------------------------=
# name:        defi_loop                                                      =
# role:        PRIMITIVE · CANONICAL_DEFI_LEVERAGE_LOOP                       =
# tier:        L0                                                             =
# substrate:   on-chain lending loop on Sui USDC (deposit → borrow → repeat)  =
# storage:     ~/.cc/inference_master_chain.jsonl (tier='defi_loop')          =
# card:        studio/assets/_agents/agent_defs/                              =
#              vm_mspc_001.agents.agent_defs.defi_loop.active.json            =
# ----------------------------------------------------------------------------=
# ROUTING CONNECTIONS                                                         =
# ----------------------------------------------------------------------------=
# inbound:                                                                    =
#   - CLI (this file's __main__)                                              =
#   - future: cc -defi-loop-run                                               =
# outbound:                                                                   =
#   - third_party.sui_mcp.SuiMCPConnector.send('lend_pool_deposit', ...)      =
#   - third_party.sui_mcp.SuiMCPConnector.send('lend_pool_borrow', ...)       =
#   - inference_logger.InferenceLogger().log (per-step + loop-complete)       =
# substrate touch:                                                            =
#   - reads:  SUI_LENDING_PACKAGE_ID presence (via sui_mcp failure surface)   =
#   - writes: crystal-chained loop records (tier='defi_loop')                 =
# ----------------------------------------------------------------------------=
# SAFETY RAILS                                                                =
# ----------------------------------------------------------------------------=
#   - target_leverage > 5.0           → reject before iteration 0             =
#   - target_leverage > 2.0 AND live  → require confirm_above_2x=True         =
#   - dry_run=True is the DEFAULT — every LoopStep records dry_run=True       =
#   - any sui failure → halt loop with stop_reason='error'                    =
#   - SUI_LENDING_PACKAGE_ID absent → halt iteration 0 (stop='lending_disabled')=
#   - projected health-factor < safety_ltv → stop_reason='health_low'         =
# ============================================================================
"""defi_loop.py — canonical leveraged-lending loop primitive on Sui USDC.

Phase A.5 of the lively-enchanting-parrot plan. Pure orchestrator: composes
existing sui_mcp.lend_pool_deposit / lend_pool_borrow into a deterministic
loop and crystal-anchors every step.

The mechanic
------------
Starting from base USDC collateral C0, target leverage L, safe LTV s:
  iteration 0: deposit C0
  iteration i: borrow B_i = (collateral_i) * s
               deposit B_i as new collateral
               collateral_{i+1} = collateral_i + B_i (cumulative)
               total_borrow_{i+1} = total_borrow_i + B_i
               leverage = collateral_{i+1} / C0
  stop when leverage >= L or i == max_iters or health drops

Determinism
-----------
- All amounts are integer micro-units (1 USDC = 1_000_000 micro).
- safety_ltv is rounded into the borrow amount via integer multiply/divide.
- The final LoopResult.crystal is BLAKE3 over canonical JSON of
  [asdict(s) for s in steps] — deterministic byte-for-byte across runs.
- DRY-RUN is the default and is recorded in every LoopStep.

Safety
------
- Hard cap: target_leverage > 5.0 rejected before the loop starts.
- Soft cap: target_leverage > 2.0 with live=True requires
  confirm_above_2x=True; otherwise rejected.
- Any deposit or borrow that returns success=False halts the loop with
  stop_reason='error' (or 'lending_disabled' if iteration 0 fails due to
  missing SUI_LENDING_PACKAGE_ID — detected from the sui_mcp error string).

CLI
---
  python3 core/lib/defi_loop.py run --pool-id 0xPOOL --collateral-usdc 100 \
      --leverage 2.0 --max-iters 4 --dry-run

Stdlib only: subprocess + json + hashlib (blake3 via inference_logger when
available — falls back to hashlib.blake2b).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
USDC_MICRO_PER_UNIT: int = 1_000_000
HARD_CAP_LEVERAGE: float = 5.0
SOFT_CAP_LEVERAGE: float = 2.0
SUI_LENDING_DISABLED_MARKER: str = "SUI_LENDING_PACKAGE_ID not set"
DEFAULT_TARGET_LEVERAGE: float = 3.0
DEFAULT_SAFETY_LTV: float = 0.65
DEFAULT_MAX_ITERS: int = 8


# ---------------------------------------------------------------------------
# Crystal hashing (blake3 with hashlib.blake2b fallback)
# ---------------------------------------------------------------------------
try:
    import blake3 as _blake3  # type: ignore
    _HAS_BLAKE3 = True
except Exception:  # pragma: no cover - fallback path
    _HAS_BLAKE3 = False


def _crystal_hash(data: bytes) -> str:
    """Deterministic BLAKE3 (or blake2b fallback) hex digest."""
    if _HAS_BLAKE3:
        return _blake3.blake3(data).hexdigest()
    return hashlib.blake2b(data).hexdigest()


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------
@dataclass
class LoopStep:
    """One iteration of the loop (one deposit + one borrow, or the genesis deposit)."""
    iteration: int = 0
    action: str = ""                            # 'deposit' or 'borrow'
    amount_micro: int = 0
    cumulative_collateral_micro: int = 0
    cumulative_borrow_micro: int = 0
    current_leverage: float = 1.0
    estimated_health_factor: float = 1.0
    crystal: str = ""
    tx_digest: str = ""
    dry_run: bool = True
    error: str = ""


@dataclass
class LoopResult:
    """Full result of one loop run."""
    target_leverage: float = 0.0
    achieved_leverage: float = 1.0
    iterations_run: int = 0
    stop_reason: str = ""                       # see VALID_STOP_REASONS
    steps: List[LoopStep] = field(default_factory=list)
    total_collateral_micro: int = 0
    total_borrow_micro: int = 0
    started_at: str = ""
    ended_at: str = ""
    crystal: str = ""


# Valid stop_reason values (for documentation; not enforced).
VALID_STOP_REASONS = (
    "target_reached",
    "max_iters",
    "health_low",
    "lending_disabled",
    "leverage_above_hard_cap",
    "leverage_above_2x_requires_confirm",
    "error",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _safe_log(logger, **kwargs) -> str:
    """Crystal-anchor via inference_logger; never raise into the loop."""
    if logger is None:
        return ""
    try:
        return logger.log(**kwargs) or ""
    except Exception as e:
        sys.stderr.write(
            f"warn: defi_loop crystal log failed: {type(e).__name__}: {e}\n"
        )
        return ""


def _get_logger():
    """Lazy import; returns InferenceLogger() or None if unavailable."""
    try:
        _here = Path(__file__).resolve().parent
        if str(_here) not in sys.path:
            sys.path.insert(0, str(_here))
        from inference_logger import InferenceLogger  # type: ignore
        return InferenceLogger()
    except Exception:
        return None


def _get_sui_connector():
    """Lazy import sui_mcp.SuiMCPConnector; returns instance or None."""
    try:
        _here = Path(__file__).resolve().parent
        _third_party = _here / "third_party"
        for p in (str(_here), str(_third_party)):
            if p not in sys.path:
                sys.path.insert(0, p)
        from third_party.sui_mcp import SuiMCPConnector  # type: ignore
        return SuiMCPConnector()
    except Exception as e:
        sys.stderr.write(
            f"warn: defi_loop sui_mcp import failed: {type(e).__name__}: {e}\n"
        )
        return None


def _result_error(reason: str) -> Dict[str, Any]:
    """Build a synthetic sui_mcp-shaped error dict for dry-run / blocked paths."""
    return {"error": reason, "success": False}


def _steps_crystal(steps: List[LoopStep]) -> str:
    """BLAKE3 (or blake2b) over canonical JSON of all steps."""
    payload = json.dumps(
        [asdict(s) for s in steps],
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _crystal_hash(payload)


# ---------------------------------------------------------------------------
# Core: run_loop
# ---------------------------------------------------------------------------
def run_loop(
    pool_id: str,
    base_collateral_micro: int,
    target_leverage: float = DEFAULT_TARGET_LEVERAGE,
    safety_ltv: float = DEFAULT_SAFETY_LTV,
    max_iters: int = DEFAULT_MAX_ITERS,
    dry_run: bool = True,
    confirm_above_2x: bool = False,
) -> LoopResult:
    """Execute the canonical DeFi leverage loop on Sui USDC.

    Defaults are safe: dry_run=True, target_leverage=3.0, safety_ltv=0.65,
    max_iters=8.

    Safety rails:
        - target_leverage > 5.0 → rejected immediately (hard cap).
        - target_leverage > 2.0 AND dry_run=False AND confirm_above_2x is
          not True → rejected with stop_reason='leverage_above_2x_requires_confirm'.
        - SUI_LENDING_PACKAGE_ID absent → halt iteration 0 with
          stop_reason='lending_disabled' and a clean error message.
        - Any deposit or borrow returning success=False halts the loop.
        - Projected health factor below safety_ltv → stop_reason='health_low'.

    Args:
        pool_id: Lending pool object id (Sui address).
        base_collateral_micro: Starting collateral in USDC micro-units.
        target_leverage: Desired collateral/base ratio. Default 3.0.
        safety_ltv: Max loan-to-value per iteration (0..1). Default 0.65.
        max_iters: Iteration cap. Default 8.
        dry_run: If True, skip sui_mcp calls; record dry_run=True on every
            step. Default True.
        confirm_above_2x: Required to leverage above 2x when dry_run=False.

    Returns:
        LoopResult with all step records, totals, and the loop crystal.
    """
    started_at = _now_iso()
    result = LoopResult(
        target_leverage=float(target_leverage),
        achieved_leverage=1.0,
        iterations_run=0,
        stop_reason="",
        steps=[],
        total_collateral_micro=0,
        total_borrow_micro=0,
        started_at=started_at,
        ended_at="",
        crystal="",
    )

    logger = _get_logger()

    # ---- pre-flight safety rails ----------------------------------------
    if base_collateral_micro <= 0:
        step = LoopStep(
            iteration=0, action="deposit", amount_micro=0,
            cumulative_collateral_micro=0, cumulative_borrow_micro=0,
            current_leverage=1.0, estimated_health_factor=0.0,
            dry_run=dry_run, error="base_collateral_micro_must_be_positive",
        )
        step.crystal = _crystal_hash(json.dumps(asdict(step), sort_keys=True).encode())
        result.steps.append(step)
        result.stop_reason = "error"
        result.ended_at = _now_iso()
        result.crystal = _steps_crystal(result.steps)
        return result

    if not (0.0 < safety_ltv < 1.0):
        step = LoopStep(
            iteration=0, action="deposit", amount_micro=0,
            cumulative_collateral_micro=0, cumulative_borrow_micro=0,
            current_leverage=1.0, estimated_health_factor=0.0,
            dry_run=dry_run, error=f"safety_ltv_out_of_range:{safety_ltv}",
        )
        step.crystal = _crystal_hash(json.dumps(asdict(step), sort_keys=True).encode())
        result.steps.append(step)
        result.stop_reason = "error"
        result.ended_at = _now_iso()
        result.crystal = _steps_crystal(result.steps)
        return result

    if target_leverage > HARD_CAP_LEVERAGE:
        # Hard cap — refuse before any work.
        step = LoopStep(
            iteration=0, action="deposit", amount_micro=0,
            cumulative_collateral_micro=base_collateral_micro,
            cumulative_borrow_micro=0,
            current_leverage=1.0, estimated_health_factor=1.0,
            dry_run=dry_run,
            error=(
                f"target_leverage_{target_leverage}_above_hard_cap_"
                f"{HARD_CAP_LEVERAGE}"
            ),
        )
        step.crystal = _crystal_hash(json.dumps(asdict(step), sort_keys=True).encode())
        result.steps.append(step)
        result.stop_reason = "leverage_above_hard_cap"
        result.ended_at = _now_iso()
        result.crystal = _steps_crystal(result.steps)
        _safe_log(
            logger,
            original_prompt=f"defi_loop refuse hard_cap leverage={target_leverage}",
            enhanced_prompt=json.dumps({
                "pool_id": pool_id,
                "target_leverage": target_leverage,
                "hard_cap": HARD_CAP_LEVERAGE,
            }),
            output_text=json.dumps({"stop_reason": "leverage_above_hard_cap"}),
            tier="defi_loop", model="sui_lending",
            scope="loop_refuse_hard_cap",
            done_flag=False, rc=1,
        )
        return result

    if target_leverage > SOFT_CAP_LEVERAGE and not dry_run and confirm_above_2x is not True:
        # Soft cap — leveraged real money above 2x requires explicit confirm.
        step = LoopStep(
            iteration=0, action="deposit", amount_micro=0,
            cumulative_collateral_micro=base_collateral_micro,
            cumulative_borrow_micro=0,
            current_leverage=1.0, estimated_health_factor=1.0,
            dry_run=dry_run,
            error=(
                f"target_leverage_{target_leverage}_above_soft_cap_"
                f"{SOFT_CAP_LEVERAGE}_requires_confirm_above_2x"
            ),
        )
        step.crystal = _crystal_hash(json.dumps(asdict(step), sort_keys=True).encode())
        result.steps.append(step)
        result.stop_reason = "leverage_above_2x_requires_confirm"
        result.ended_at = _now_iso()
        result.crystal = _steps_crystal(result.steps)
        _safe_log(
            logger,
            original_prompt=(
                f"defi_loop refuse soft_cap leverage={target_leverage} live"
            ),
            enhanced_prompt=json.dumps({
                "pool_id": pool_id,
                "target_leverage": target_leverage,
                "soft_cap": SOFT_CAP_LEVERAGE,
                "confirm_above_2x": bool(confirm_above_2x),
            }),
            output_text=json.dumps({
                "stop_reason": "leverage_above_2x_requires_confirm",
            }),
            tier="defi_loop", model="sui_lending",
            scope="loop_refuse_soft_cap",
            done_flag=False, rc=1,
        )
        return result

    # ---- sui connector --------------------------------------------------
    sui = None if dry_run else _get_sui_connector()
    if not dry_run and sui is not None:
        try:
            sui.connect()
        except Exception:
            pass

    # ---- iteration 0: seed deposit --------------------------------------
    cumulative_collateral = int(base_collateral_micro)
    cumulative_borrow = 0

    seed_step = LoopStep(
        iteration=0, action="deposit",
        amount_micro=int(base_collateral_micro),
        cumulative_collateral_micro=cumulative_collateral,
        cumulative_borrow_micro=cumulative_borrow,
        current_leverage=1.0,
        estimated_health_factor=1.0,
        dry_run=dry_run,
    )

    if dry_run:
        seed_step.crystal = _safe_log(
            logger,
            original_prompt=(
                f"defi_loop seed deposit pool_id={pool_id} amount_micro="
                f"{base_collateral_micro} (DRY-RUN)"
            ),
            enhanced_prompt=json.dumps({
                "pool_id": pool_id,
                "amount_micro": int(base_collateral_micro),
                "dry_run": True,
            }),
            output_text=json.dumps({
                "iteration": 0, "action": "deposit",
                "cumulative_collateral_micro": cumulative_collateral,
            }),
            tier="defi_loop", model="sui_lending",
            scope="loop_step_0",
            done_flag=True, rc=0,
        ) or _crystal_hash(json.dumps(asdict(seed_step), sort_keys=True).encode())
        result.steps.append(seed_step)
        result.iterations_run = 1
    else:
        # Live seed deposit.
        if sui is None:
            seed_step.error = "sui_mcp_unavailable"
            seed_step.crystal = _crystal_hash(
                json.dumps(asdict(seed_step), sort_keys=True).encode()
            )
            result.steps.append(seed_step)
            result.stop_reason = "error"
            result.iterations_run = 1
            result.ended_at = _now_iso()
            result.total_collateral_micro = cumulative_collateral
            result.total_borrow_micro = cumulative_borrow
            result.crystal = _steps_crystal(result.steps)
            return result

        send_result = sui.send(
            "lend_pool_deposit",
            json.dumps({
                "pool_id": pool_id,
                "amount": int(base_collateral_micro),
            }),
        )
        if not getattr(send_result, "success", False):
            err = getattr(send_result, "error", "") or "unknown_deposit_error"
            seed_step.error = err
            seed_step.crystal = (
                getattr(send_result, "crystal_id", "")
                or _crystal_hash(json.dumps(asdict(seed_step), sort_keys=True).encode())
            )
            result.steps.append(seed_step)
            result.iterations_run = 1
            # Detect missing lending package → clean lending_disabled stop.
            if SUI_LENDING_DISABLED_MARKER in err:
                result.stop_reason = "lending_disabled"
            else:
                result.stop_reason = "error"
            result.ended_at = _now_iso()
            result.total_collateral_micro = cumulative_collateral
            result.total_borrow_micro = cumulative_borrow
            result.crystal = _steps_crystal(result.steps)
            _safe_log(
                logger,
                original_prompt=(
                    f"defi_loop seed deposit FAILED pool_id={pool_id}"
                ),
                enhanced_prompt=json.dumps({
                    "pool_id": pool_id,
                    "amount_micro": int(base_collateral_micro),
                }),
                output_text=json.dumps({
                    "stop_reason": result.stop_reason, "error": err,
                }),
                tier="defi_loop", model="sui_lending",
                scope="loop_step_0",
                done_flag=False, rc=1,
            )
            return result

        seed_step.tx_digest = (
            getattr(send_result, "metadata", {}) or {}
        ).get("digest", "") or ""
        seed_step.crystal = (
            getattr(send_result, "crystal_id", "")
            or _crystal_hash(json.dumps(asdict(seed_step), sort_keys=True).encode())
        )
        result.steps.append(seed_step)
        result.iterations_run = 1

    # ---- main loop: borrow → deposit ------------------------------------
    # We iterate at most max_iters borrow→deposit pairs (one borrow + one
    # re-deposit per iteration). The seed deposit above counts as iteration 0.
    stop_reason = ""
    for i in range(1, int(max_iters) + 1):
        # Compute the max safe borrow at current collateral.
        borrow_amt = (cumulative_collateral * int(safety_ltv * 1_000_000)) // 1_000_000
        if borrow_amt <= 0:
            stop_reason = "health_low"
            break

        # Projected post-borrow health factor (collateral / total_debt).
        # If we'd push effective LTV (debt/collateral) above safety_ltv we
        # refuse this iteration.
        projected_debt = cumulative_borrow + borrow_amt
        projected_health = (
            float(cumulative_collateral) / float(projected_debt)
            if projected_debt > 0 else float("inf")
        )
        projected_ltv = (
            float(projected_debt) / float(cumulative_collateral)
            if cumulative_collateral > 0 else 1.0
        )
        # Health is healthy when health >= 1/safety_ltv (i.e. ltv <= safety_ltv).
        if projected_ltv > safety_ltv + 1e-9:
            stop_reason = "health_low"
            break

        # ---- BORROW step ------------------------------------------------
        borrow_step = LoopStep(
            iteration=i, action="borrow",
            amount_micro=int(borrow_amt),
            cumulative_collateral_micro=cumulative_collateral,
            cumulative_borrow_micro=cumulative_borrow + int(borrow_amt),
            current_leverage=(
                float(cumulative_collateral) / float(base_collateral_micro)
            ),
            estimated_health_factor=projected_health,
            dry_run=dry_run,
        )

        if dry_run:
            borrow_step.crystal = _safe_log(
                logger,
                original_prompt=(
                    f"defi_loop iter={i} borrow {borrow_amt} micro (DRY-RUN)"
                ),
                enhanced_prompt=json.dumps({
                    "pool_id": pool_id,
                    "collateral": cumulative_collateral,
                    "borrow": int(borrow_amt),
                    "dry_run": True,
                }),
                output_text=json.dumps({
                    "iteration": i, "action": "borrow",
                    "cumulative_borrow_micro": cumulative_borrow + int(borrow_amt),
                }),
                tier="defi_loop", model="sui_lending",
                scope=f"loop_step_{i}_borrow",
                done_flag=True, rc=0,
            ) or _crystal_hash(json.dumps(asdict(borrow_step), sort_keys=True).encode())
        else:
            send_result = sui.send(
                "lend_pool_borrow",
                json.dumps({
                    "pool_id": pool_id,
                    "collateral": int(cumulative_collateral),
                    "borrow": int(borrow_amt),
                }),
            )
            if not getattr(send_result, "success", False):
                err = getattr(send_result, "error", "") or "unknown_borrow_error"
                borrow_step.error = err
                borrow_step.crystal = (
                    getattr(send_result, "crystal_id", "")
                    or _crystal_hash(
                        json.dumps(asdict(borrow_step), sort_keys=True).encode()
                    )
                )
                result.steps.append(borrow_step)
                result.iterations_run += 1
                stop_reason = (
                    "lending_disabled"
                    if SUI_LENDING_DISABLED_MARKER in err
                    else "error"
                )
                break
            borrow_step.tx_digest = (
                getattr(send_result, "metadata", {}) or {}
            ).get("digest", "") or ""
            borrow_step.crystal = (
                getattr(send_result, "crystal_id", "")
                or _crystal_hash(
                    json.dumps(asdict(borrow_step), sort_keys=True).encode()
                )
            )

        result.steps.append(borrow_step)
        cumulative_borrow += int(borrow_amt)

        # ---- RE-DEPOSIT step (the borrowed amount becomes new collateral) -
        deposit_step = LoopStep(
            iteration=i, action="deposit",
            amount_micro=int(borrow_amt),
            cumulative_collateral_micro=cumulative_collateral + int(borrow_amt),
            cumulative_borrow_micro=cumulative_borrow,
            current_leverage=(
                float(cumulative_collateral + int(borrow_amt))
                / float(base_collateral_micro)
            ),
            estimated_health_factor=(
                float(cumulative_collateral + int(borrow_amt))
                / float(cumulative_borrow)
                if cumulative_borrow > 0 else float("inf")
            ),
            dry_run=dry_run,
        )

        if dry_run:
            deposit_step.crystal = _safe_log(
                logger,
                original_prompt=(
                    f"defi_loop iter={i} re-deposit {borrow_amt} micro (DRY-RUN)"
                ),
                enhanced_prompt=json.dumps({
                    "pool_id": pool_id,
                    "amount_micro": int(borrow_amt),
                    "dry_run": True,
                }),
                output_text=json.dumps({
                    "iteration": i, "action": "deposit",
                    "cumulative_collateral_micro": (
                        cumulative_collateral + int(borrow_amt)
                    ),
                }),
                tier="defi_loop", model="sui_lending",
                scope=f"loop_step_{i}_deposit",
                done_flag=True, rc=0,
            ) or _crystal_hash(json.dumps(asdict(deposit_step), sort_keys=True).encode())
        else:
            send_result = sui.send(
                "lend_pool_deposit",
                json.dumps({
                    "pool_id": pool_id,
                    "amount": int(borrow_amt),
                }),
            )
            if not getattr(send_result, "success", False):
                err = getattr(send_result, "error", "") or "unknown_deposit_error"
                deposit_step.error = err
                deposit_step.crystal = (
                    getattr(send_result, "crystal_id", "")
                    or _crystal_hash(
                        json.dumps(asdict(deposit_step), sort_keys=True).encode()
                    )
                )
                result.steps.append(deposit_step)
                result.iterations_run += 1
                stop_reason = (
                    "lending_disabled"
                    if SUI_LENDING_DISABLED_MARKER in err
                    else "error"
                )
                break
            deposit_step.tx_digest = (
                getattr(send_result, "metadata", {}) or {}
            ).get("digest", "") or ""
            deposit_step.crystal = (
                getattr(send_result, "crystal_id", "")
                or _crystal_hash(
                    json.dumps(asdict(deposit_step), sort_keys=True).encode()
                )
            )

        result.steps.append(deposit_step)
        cumulative_collateral += int(borrow_amt)
        result.iterations_run += 1

        # Check target leverage.
        current_leverage = (
            float(cumulative_collateral) / float(base_collateral_micro)
        )
        if current_leverage >= target_leverage:
            stop_reason = "target_reached"
            break

    # Loop exit — figure out stop_reason if not set.
    if not stop_reason:
        stop_reason = "max_iters"

    # ---- finalize -------------------------------------------------------
    result.stop_reason = stop_reason
    result.total_collateral_micro = cumulative_collateral
    result.total_borrow_micro = cumulative_borrow
    result.achieved_leverage = (
        float(cumulative_collateral) / float(base_collateral_micro)
    )
    result.ended_at = _now_iso()
    result.crystal = _steps_crystal(result.steps)

    # Final crystal-anchor summarizing the loop.
    _safe_log(
        logger,
        original_prompt=(
            f"defi_loop complete pool_id={pool_id} "
            f"target={target_leverage} achieved={result.achieved_leverage:.4f} "
            f"iters={result.iterations_run} stop={result.stop_reason}"
        ),
        enhanced_prompt=json.dumps({
            "pool_id": pool_id,
            "base_collateral_micro": int(base_collateral_micro),
            "target_leverage": float(target_leverage),
            "safety_ltv": float(safety_ltv),
            "max_iters": int(max_iters),
            "dry_run": bool(dry_run),
            "confirm_above_2x": bool(confirm_above_2x),
        }),
        output_text=json.dumps({
            "iterations_run": result.iterations_run,
            "stop_reason": result.stop_reason,
            "achieved_leverage": result.achieved_leverage,
            "total_collateral_micro": result.total_collateral_micro,
            "total_borrow_micro": result.total_borrow_micro,
            "loop_crystal": result.crystal,
        }),
        tier="defi_loop", model="sui_lending",
        scope="loop_complete",
        done_flag=(stop_reason in ("target_reached", "max_iters")),
        rc=0 if stop_reason in ("target_reached", "max_iters") else 1,
    )

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _pretty_print(result: LoopResult) -> None:
    """Compact human-readable summary + JSON tail."""
    out = {
        "stop_reason": result.stop_reason,
        "iterations_run": result.iterations_run,
        "target_leverage": result.target_leverage,
        "achieved_leverage": round(result.achieved_leverage, 6),
        "total_collateral_micro": result.total_collateral_micro,
        "total_borrow_micro": result.total_borrow_micro,
        "started_at": result.started_at,
        "ended_at": result.ended_at,
        "loop_crystal": (result.crystal or "")[:24],
        "steps": [
            {
                "iter": s.iteration,
                "act": s.action,
                "amt_micro": s.amount_micro,
                "col_micro": s.cumulative_collateral_micro,
                "borrow_micro": s.cumulative_borrow_micro,
                "lev": round(s.current_leverage, 4),
                "hf": (
                    "inf"
                    if s.estimated_health_factor == float("inf")
                    else round(s.estimated_health_factor, 4)
                ),
                "dry": s.dry_run,
                "err": s.error,
                "crystal": (s.crystal or "")[:16],
                "tx": (s.tx_digest or "")[:16],
            }
            for s in result.steps
        ],
    }
    print(json.dumps(out, indent=2, default=str))


def _main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="defi_loop — canonical leveraged-lending loop on Sui USDC"
    )
    sub = ap.add_subparsers(dest="cmd")

    p_run = sub.add_parser("run", help="run the loop")
    p_run.add_argument("--pool-id", required=True)
    p_run.add_argument(
        "--collateral-usdc", type=float, required=True,
        help="In USDC (multiplied by 1e6 to micro-units)",
    )
    p_run.add_argument(
        "--leverage", type=float, default=DEFAULT_TARGET_LEVERAGE,
        help=f"Target leverage (default {DEFAULT_TARGET_LEVERAGE})",
    )
    p_run.add_argument(
        "--max-iters", type=int, default=DEFAULT_MAX_ITERS,
        help=f"Iteration cap (default {DEFAULT_MAX_ITERS})",
    )
    p_run.add_argument(
        "--safety-ltv", type=float, default=DEFAULT_SAFETY_LTV,
        help=f"Max safe LTV per iteration (default {DEFAULT_SAFETY_LTV})",
    )
    p_run.add_argument(
        "--dry-run", action="store_true", default=True,
        help="DEFAULT — record dry_run=True on every step",
    )
    p_run.add_argument(
        "--live", action="store_true",
        help=(
            "Override --dry-run (still gated by --confirm for leverage > 2x)"
        ),
    )
    p_run.add_argument(
        "--confirm", action="store_true",
        help="Required when --live and leverage > 2.0",
    )

    args = ap.parse_args(argv)

    if args.cmd != "run":
        ap.print_help()
        return 0

    base_micro = int(round(args.collateral_usdc * USDC_MICRO_PER_UNIT))
    dry_run = not bool(args.live)
    result = run_loop(
        pool_id=args.pool_id,
        base_collateral_micro=base_micro,
        target_leverage=float(args.leverage),
        safety_ltv=float(args.safety_ltv),
        max_iters=int(args.max_iters),
        dry_run=dry_run,
        confirm_above_2x=bool(args.confirm),
    )
    _pretty_print(result)
    # exit non-zero on hard refusals so shell pipelines can detect them
    bad = {
        "leverage_above_hard_cap",
        "leverage_above_2x_requires_confirm",
        "error",
    }
    return 1 if result.stop_reason in bad else 0


if __name__ == "__main__":
    sys.exit(_main())
