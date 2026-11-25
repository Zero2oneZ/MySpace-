"""pump_features.py — Feature extraction from raw Pump.fun transaction data.

Input:  dict from Solana getTransaction JSON
Output: 32-dim float vector ready for GPU ingestion.

Zero external dependencies — stdlib only.
"""
from __future__ import annotations

import json
import math
import time
from typing import Optional

from pump_constants import FEATURE_DIM, FEATURE_NAMES


def _safe_float(val) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(val) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


def extract_features(tx_json: dict, history: list[dict] = None) -> list[float]:
    """Convert a Pump.fun transaction + optional history into a 32-dim vector."""
    meta = tx_json.get("meta", {})
    tx = tx_json.get("transaction", {})
    msg = tx.get("message", {})
    accounts = msg.get("accountKeys", [])

    pre_balances = meta.get("preBalances", [])
    post_balances = meta.get("postBalances", [])
    pre_token_balances = meta.get("preTokenBalances", [])
    post_token_balances = meta.get("postTokenBalances", [])

    # Default feature vector
    feats = [0.0] * FEATURE_DIM

    # 0-5: Price / reserves (placeholder — requires parsing Pump curve state)
    # These come from the instruction data or simulateTransaction
    # For now we compute what we can from balances.
    sol_delta = sum(max(0, pb - pa) for pa, pb in zip(pre_balances, post_balances)) / 1e9
    token_delta = sum(
        max(0, _safe_int(ptb.get("uiTokenAmount", {}).get("amount", 0)) -
               _safe_int(pretb.get("uiTokenAmount", {}).get("amount", 0)))
        for pretb, ptb in zip(pre_token_balances, post_token_balances)
    )
    feats[0] = sol_delta / max(token_delta, 1)  # approx price
    feats[1] = sol_delta * 1_000_000  # rough mcap proxy

    # 6: total supply (from post token balances if available)
    total_supply = sum(
        _safe_int(t.get("uiTokenAmount", {}).get("amount", 0))
        for t in post_token_balances
    )
    feats[6] = total_supply

    # 7: holder count (unique mint + owner pairs)
    holders = set()
    for t in post_token_balances:
        owner = t.get("owner", "")
        mint = t.get("mint", "")
        if owner and mint:
            holders.add(f"{owner}:{mint}")
    feats[7] = float(len(holders))

    # 8-10: Transaction counts from history
    if history:
        now = time.time()
        recent_1m = [h for h in history if now - h.get("ts", 0) < 60]
        recent_5m = [h for h in history if now - h.get("ts", 0) < 300]
        recent_15m = [h for h in history if now - h.get("ts", 0) < 900]
        feats[8] = float(len(recent_1m))
        feats[9] = float(sum(1 for h in recent_1m if h.get("is_buy")))
        feats[10] = float(sum(1 for h in recent_1m if not h.get("is_buy")))
        feats[11] = sum(h.get("sol_delta", 0.0) for h in recent_1m)
        feats[12] = sum(h.get("sol_delta", 0.0) for h in recent_5m)
        feats[13] = sum(h.get("sol_delta", 0.0) for h in recent_15m)

    # 14: buy/sell ratio
    buy_count = feats[9]
    sell_count = feats[10]
    feats[14] = buy_count / max(buy_count + sell_count, 1)

    # 15-16: Price velocity / acceleration (needs history)
    if history and len(history) >= 3:
        p_now = feats[0]
        p_prev = history[-1].get("features", [0.0] * FEATURE_DIM)[0]
        p_prev2 = history[-2].get("features", [0.0] * FEATURE_DIM)[0]
        dt = max(history[-1].get("ts", now) - history[-2].get("ts", now - 1), 0.001)
        feats[15] = (p_now - p_prev) / dt
        feats[16] = (p_now - 2 * p_prev + p_prev2) / (dt * dt)

    # 17: Entropy of transaction sizes
    if history:
        sizes = [abs(h.get("sol_delta", 0.0)) for h in history if h.get("sol_delta")]
        if sizes:
            total = sum(sizes)
            probs = [s / total for s in sizes if total > 0]
            entropy = -sum(p * math.log2(p) for p in probs if p > 0)
            feats[17] = entropy

    # 18: Gini coefficient of holder balances (concentration)
    if post_token_balances:
        amounts = sorted(
            _safe_int(t.get("uiTokenAmount", {}).get("amount", 0))
            for t in post_token_balances
        )
        n = len(amounts)
        if n > 0 and sum(amounts) > 0:
            cumsum = 0
            gini = 0
            for i, a in enumerate(amounts, 1):
                cumsum += a
                gini += (2 * i - n - 1) * a
            feats[18] = gini / (n * sum(amounts))

    # 19: First buy delay (placeholder — requires tracking create time)
    # 20: Bot score (heuristic based on tx pattern)
    if history:
        rapid_tx = sum(1 for h in history if h.get("latency_ms", 9999) < 500)
        feats[20] = rapid_tx / max(len(history), 1)

    # 21-22: Creator info (placeholder — requires looking up creator from accounts)
    if accounts:
        # First account is usually fee payer / creator
        creator = accounts[0]
        # Would need RPC call to get balance — skip for now
        pass

    # 23: Graduated (requires checking if token exists on Raydium)
    # 24: Twitter mentions (placeholder)
    # 25: Dev burnt LP (placeholder)

    # 26: Top 10 % supply
    if post_token_balances:
        amounts = [
            _safe_int(t.get("uiTokenAmount", {}).get("amount", 0))
            for t in post_token_balances
        ]
        amounts.sort(reverse=True)
        top10 = sum(amounts[:10])
        total = sum(amounts)
        feats[26] = top10 / max(total, 1)

    # 27: Snipe count (tx in first few blocks after creation)
    slot = _safe_int(tx_json.get("slot"))
    if history:
        first_slot = min(
            _safe_int(h.get("slot", slot)) for h in history
        )
        feats[27] = float(sum(
            1 for h in history
            if _safe_int(h.get("slot", slot)) - first_slot <= 3
        ))

    # 28: Rug pull score (heuristic)
    if history:
        # Sudden sell spike after buy spike
        buy_5m = sum(1 for h in history if h.get("is_buy") and time.time() - h.get("ts", 0) < 300)
        sell_5m = sum(1 for h in history if not h.get("is_buy") and time.time() - h.get("ts", 0) < 300)
        if buy_5m > 5 and sell_5m > buy_5m * 2:
            feats[28] = 1.0

    # 29: Time since create
    if history:
        first_ts = min(h.get("ts", time.time()) for h in history)
        feats[29] = time.time() - first_ts

    # 30: Is mutable (placeholder — requires getAccountInfo on mint)
    # 31: Slot
    feats[31] = float(slot)

    # Clamp everything to finite range for model stability
    for i in range(FEATURE_DIM):
        if not math.isfinite(feats[i]):
            feats[i] = 0.0
        feats[i] = max(-1e9, min(1e9, feats[i]))

    return feats


def features_to_jsonl(feats: list[float], label: Optional[float] = None, meta: Optional[dict] = None) -> str:
    """Serialize a feature vector to JSONL."""
    obj = {
        "ts": time.time(),
        "features": feats,
        "label": label,
        "meta": meta or {},
    }
    return json.dumps(obj, default=str)
