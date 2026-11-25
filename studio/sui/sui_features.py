"""sui_features.py — Extract 32-dim feature vectors from Sui DEX transactions.

Input:  Sui transaction JSON (from sui_getTransactionBlock)
Output: list[float] of length FEATURE_DIM

Usage:
    feats = extract_features(tx_json, history)
"""
from __future__ import annotations

import json
import math
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional

from sui_constants import FEATURE_DIM


def extract_features(tx_json: dict, history: list[dict]) -> list[float]:
    """Extract a 32-dim feature vector from a Sui DEX transaction."""
    f = [0.0] * FEATURE_DIM

    effects = tx_json.get("effects", {})
    tx_data = tx_json.get("transaction", {})
    gas = effects.get("gasUsed", {})
    ts = tx_json.get("timestampMs", 0) / 1000.0
    epoch = tx_json.get("epoch", "0")
    checkpoint = int(tx_json.get("checkpoint", "0"))

    # 0. price proxy (SUI per token, rough)
    f[0] = _price_proxy(tx_json)

    # 1. price change vs last tx
    f[1] = _price_change(f[0], history)

    # 2. volume proxy (gas + balance changes)
    f[2] = _volume_proxy(tx_json)

    # 3. TVL proxy (total balance changes)
    f[3] = _tvl_proxy(tx_json)

    # 4. fees (gas used)
    f[4] = _fee_proxy(gas)

    # 5-6. token reserves (balance deltas)
    deltas = _balance_deltas(effects)
    f[5] = deltas[0] if len(deltas) > 0 else 0.0
    f[6] = deltas[1] if len(deltas) > 1 else 0.0

    # 7. reserve ratio
    f[7] = f[5] / max(f[6], 1e-9) if f[6] != 0 else 0.0

    # 8. price impact (abs delta / volume)
    vol = max(f[2], 1e-9)
    f[8] = abs(f[1]) / vol if vol > 0 else 0.0

    # 9. slippage heuristic (gas / volume)
    f[9] = f[4] / vol if vol > 0 else 0.0

    # 10. fee tier (computedUnits / gasBudget)
    budget = float(gas.get("computationCost", 0))
    used = float(gas.get("computationCost", 0))
    f[10] = used / max(budget, 1.0) if budget > 0 else 0.0

    # 11. pool age in checkpoints
    f[11] = float(checkpoint)

    # 12. tx count in history for same pool
    pool = _pool_id(tx_json)
    f[12] = sum(1 for h in history if _pool_id(h) == pool)

    # 13. unique swapper count
    f[13] = len(set(_sender(h) for h in history if _pool_id(h) == pool))

    # 14-15. buy/sell ratio
    f[14], f[15] = _buy_sell_ratio(history, pool)

    # 16. price velocity (price change per second)
    f[16] = _price_velocity(f[0], f[1], history)

    # 17-18. volatility
    f[17] = _volatility(history, pool, window=60)
    f[18] = _volatility(history, pool, window=3600)

    # 19. liquidity depth (sum of abs reserves)
    f[19] = abs(f[5]) + abs(f[6])

    # 20. spread heuristic
    f[20] = abs(f[5] - f[6]) / max(f[19], 1e-9) if f[19] > 0 else 0.0

    # 21. median trade size
    sizes = [_volume_proxy(h) for h in history if _pool_id(h) == pool and _volume_proxy(h) > 0]
    f[21] = _median(sizes) if sizes else 0.0

    # 22. entropy of trade sizes
    f[22] = _entropy(sizes) if sizes else 0.0

    # 23. Gini coefficient of trade sizes
    f[23] = _gini(sizes) if sizes else 0.0

    # 24. holder concentration (HHI on senders)
    f[24] = _holder_concentration(history, pool)

    # 25. whale count (>2x median)
    med = f[21]
    f[25] = sum(1 for s in sizes if s > med * 2) if med > 0 else 0.0

    # 26. bot score heuristic
    f[26] = _bot_score(tx_json, history)

    # 27. rug pull score
    f[27] = _rug_pull_score(tx_json, history)

    # 28. creator sell pressure
    f[28] = _creator_sell_pressure(tx_json, history)

    # 29. top10 supply pct
    f[29] = _top10_supply(history, pool)

    # 30. social signal (placeholder)
    f[30] = 0.0

    # 31. composite score
    f[31] = _composite_score(f)

    return f


def _price_proxy(tx: dict) -> float:
    """Rough price proxy: sum of positive balance deltas."""
    deltas = _balance_deltas(tx.get("effects", {}))
    return sum(max(0, d) for d in deltas)


def _price_change(price: float, history: list[dict]) -> float:
    if not history:
        return 0.0
    last = _price_proxy(history[-1]) if history else 0.0
    if last == 0:
        return 0.0
    return (price - last) / max(last, 1e-9)


def _volume_proxy(tx: dict) -> float:
    deltas = _balance_deltas(tx.get("effects", {}))
    return sum(abs(d) for d in deltas)


def _tvl_proxy(tx: dict) -> float:
    deltas = _balance_deltas(tx.get("effects", {}))
    return sum(d for d in deltas if d > 0)


def _fee_proxy(gas: dict) -> float:
    return sum(float(gas.get(k, 0)) for k in ["computationCost", "storageCost", "storageRebate"])


def _balance_deltas(effects: dict) -> list[float]:
    """Extract balance changes from transaction effects."""
    deltas = []
    for change in effects.get("balanceChanges", []):
        amt = change.get("amount", "0")
        try:
            deltas.append(float(amt) / 1e9)
        except (ValueError, TypeError):
            pass
    return deltas


def _pool_id(tx: dict) -> str:
    """Heuristic: use first object ID from balanceChanges as pool ID."""
    changes = tx.get("effects", {}).get("balanceChanges", [])
    for c in changes:
        oid = c.get("owner", {}).get("ObjectOwner", "")
        if oid:
            return oid
    return ""


def _sender(tx: dict) -> str:
    return tx.get("transaction", {}).get("data", {}).get("sender", "")


def _buy_sell_ratio(history: list[dict], pool: str) -> tuple[float, float]:
    buys, sells = 0, 0
    for h in history:
        if _pool_id(h) != pool:
            continue
        deltas = _balance_deltas(h.get("effects", {}))
        net = sum(deltas)
        if net > 0:
            buys += 1
        elif net < 0:
            sells += 1
    total = buys + sells
    if total == 0:
        return 0.0, 0.0
    return buys / total, sells / total


def _price_velocity(price: float, change: float, history: list[dict]) -> float:
    if len(history) < 2:
        return 0.0
    dt = history[-1].get("timestampMs", 0) / 1000.0 - history[-2].get("timestampMs", 0) / 1000.0
    if dt <= 0:
        dt = 1.0
    return change / dt


def _volatility(history: list[dict], pool: str, window: int) -> float:
    now = time.time()
    prices = []
    for h in history:
        if _pool_id(h) != pool:
            continue
        ts = h.get("timestampMs", 0) / 1000.0
        if now - ts <= window:
            prices.append(_price_proxy(h))
    if len(prices) < 2:
        return 0.0
    mean = sum(prices) / len(prices)
    variance = sum((p - mean) ** 2 for p in prices) / len(prices)
    return math.sqrt(variance) / max(mean, 1e-9)


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


def _entropy(values: list[float]) -> float:
    if not values:
        return 0.0
    total = sum(values)
    if total == 0:
        return 0.0
    probs = [v / total for v in values if v > 0]
    return -sum(p * math.log2(p) for p in probs)


def _gini(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    cum = sum((2 * i - n + 1) * s[i] for i in range(n))
    return cum / (n * sum(s)) if sum(s) > 0 else 0.0


def _holder_concentration(history: list[dict], pool: str) -> float:
    senders = defaultdict(float)
    for h in history:
        if _pool_id(h) != pool:
            continue
        s = _sender(h)
        vol = _volume_proxy(h)
        senders[s] += vol
    total = sum(senders.values())
    if total == 0:
        return 0.0
    shares = [v / total for v in senders.values()]
    return sum(s ** 2 for s in shares)


def _bot_score(tx: dict, history: list[dict]) -> float:
    """Heuristic bot score based on tx patterns."""
    score = 0.0
    gas = tx.get("effects", {}).get("gasUsed", {})
    if float(gas.get("computationCost", 0)) > 1_000_000:
        score += 0.3
    if len(history) > 10:
        score += 0.1
    return min(1.0, score)


def _rug_pull_score(tx: dict, history: list[dict]) -> float:
    """Heuristic rug pull score."""
    deltas = _balance_deltas(tx.get("effects", {}))
    if not history or not deltas:
        return 0.0
    net = sum(deltas)
    # Large negative net = drain
    if net < -10:
        return min(1.0, abs(net) / 100.0)
    return 0.0


def _creator_sell_pressure(tx: dict, history: list[dict]) -> float:
    """Heuristic creator sell pressure."""
    if not history:
        return 0.0
    deltas = _balance_deltas(tx.get("effects", {}))
    net = sum(deltas)
    if net < 0:
        return abs(net) / max(sum(abs(d) for d in deltas), 1e-9)
    return 0.0


def _top10_supply(history: list[dict], pool: str) -> float:
    """Heuristic: share of top 10 holders."""
    if not history:
        return 0.0
    senders = defaultdict(float)
    for h in history:
        if _pool_id(h) != pool:
            continue
        s = _sender(h)
        senders[s] += _volume_proxy(h)
    total = sum(senders.values())
    if total == 0:
        return 0.0
    top10 = sum(sorted(senders.values(), reverse=True)[:10])
    return top10 / total


def _composite_score(f: list[float]) -> float:
    """Weighted composite of key features."""
    w = [
        0.05, 0.10, 0.05, 0.05, 0.05,
        0.05, 0.05, 0.02, 0.05, 0.05,
        0.02, 0.01, 0.02, 0.02, 0.05,
        0.05, 0.10, 0.05, 0.03, 0.03,
        0.02, 0.02, 0.03, 0.05, 0.03,
        0.02, 0.10, 0.10, 0.05, 0.03,
        0.00, 0.05,
    ]
    assert len(w) == FEATURE_DIM
    score = sum(a * b for a, b in zip(f, w))
    return max(0.0, min(1.0, score))


def features_to_jsonl(obj: dict) -> str:
    return json.dumps(obj, default=str)
