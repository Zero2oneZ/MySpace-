"""pattern_trader.py — Paper-trade on orchestration pattern signals.

Cross-references orchestration patterns with the feed to find target tokens,
scores them with the trained MLP, and simulates buy/sell trades.

Usage:
    python3 pattern_trader.py --threshold 0.60 --hold-txs 5 --capital 10.0
    cc -pattern-trade --threshold 0.65
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent

PUMP_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
SYS_ID  = "11111111111111111111111111111111"


# ── Model loading (same as predictor) ─────────────────────────────────────────

def mat_vec_mul(W, x):
    return [sum(wi * xi for wi, xi in zip(row, x)) for row in W]

def vec_add(a, b):
    return [ai + bi for ai, bi in zip(a, b)]

def relu(v):
    return [max(0.0, x) for x in v]

def sigmoid(x):
    if x < -20:
        return 0.0
    if x > 20:
        return 1.0
    return 1.0 / (1.0 + math.exp(-x))

def forward(m, x):
    z1 = vec_add(mat_vec_mul(m["W1"], x), m["b1"])
    a1 = relu(z1)
    z2 = vec_add(mat_vec_mul(m["W2"], a1), m["b2"])
    return sigmoid(z2[0])


def extract_features(p):
    chain = p.get("chain", [])
    depth = len(chain)
    freq = p.get("freq", 0)
    interval_ms = p.get("interval_ms", 0.0)
    is_rec = 1.0 if p.get("recursive") else 0.0
    is_self = 1.0 if p.get("self_activating") else 0.0
    tags = p.get("tags", [])

    unique_nodes = len(set(chain))
    node_diversity = unique_nodes / depth if depth else 0.0
    root = chain[0] if chain else ""
    is_sys = 1.0 if root == SYS_ID else 0.0
    is_pump = 1.0 if root == PUMP_ID else 0.0
    is_token = 1.0 if root.startswith("Token") else 0.0
    is_other = 1.0 if not (is_sys or is_pump or is_token) else 0.0

    counts = {}
    for c in chain:
        counts[c] = counts.get(c, 0) + 1
    max_rep = max(counts.values()) if counts else 0
    rep_ratio = max_rep / depth if depth else 0.0

    n_tags = len(tags)
    has_deep = 1.0 if "DEEP_CHAIN" in tags else 0.0
    has_det = 1.0 if "DETERMINISTIC_GRID" in tags else 0.0
    has_hf = 1.0 if "HIGH_FREQUENCY" in tags else 0.0

    return [
        depth / 10.0,
        math.log1p(freq),
        math.log1p(interval_ms) / 10.0,
        is_rec,
        is_self,
        node_diversity,
        rep_ratio,
        is_sys,
        is_pump,
        is_token,
        is_other,
        n_tags / 5.0,
        has_deep,
        has_det,
        has_hf,
    ]


def load_model(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


# ── Feed index ────────────────────────────────────────────────────────────────

def index_feed(feed_path: Path) -> Tuple[Dict[str, List[dict]], Dict[float, List[dict]]]:
    """Index feed by token and by timestamp bucket (1-second)."""
    by_token: Dict[str, List[dict]] = defaultdict(list)
    by_ts: Dict[float, List[dict]] = defaultdict(list)
    with open(feed_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            token = o.get("token")
            ts = o.get("ts", 0.0)
            slot = o.get("slot", 0)
            if not token or slot <= 0:
                continue
            by_token[token].append(o)
            bucket = round(ts)
            by_ts[bucket].append(o)
    # Sort each token's txs by slot
    for token in by_token:
        by_token[token].sort(key=lambda x: x.get("slot", 0))
    return dict(by_token), dict(by_ts)


# ── Signal detection ─────────────────────────────────────────────────────────

def _extract_ts_from_pattern_id(pattern: dict) -> float:
    """Extract original tx timestamp from pattern_id like pat_6EF8rrec_1780104123456."""
    pid = pattern.get("pattern_id", pattern.get("id", ""))
    parts = pid.split("_")
    if len(parts) >= 3:
        try:
            return int(parts[-1]) / 1000.0
        except ValueError:
            pass
    return 0.0


def find_pattern_tokens(pattern: dict, by_ts: Dict[float, List[dict]], window_s: float = 60.0) -> List[Tuple[str, float]]:
    """Find tokens associated with a pattern by timestamp proximity.
    Uses pattern_id timestamp (the actual tx time), not the report write time.
    Returns [(token, confidence)] sorted by confidence."""
    # Prefer pattern_id timestamp over report ts (which is mapper runtime)
    ts = _extract_ts_from_pattern_id(pattern)
    if not ts:
        ts = pattern.get("ts", 0.0)
    if not ts:
        return []

    tokens = defaultdict(float)
    bucket = round(ts)
    for delta in range(-int(window_s), int(window_s) + 1):
        for tx in by_ts.get(bucket + delta, []):
            token = tx.get("token", "")
            if token:
                # Weight by inverse time distance
                dist = abs(tx.get("ts", ts) - ts)
                weight = 1.0 / (1.0 + dist)
                tokens[token] += weight

    if not tokens:
        return []
    total = sum(tokens.values())
    scored = [(t, w / total) for t, w in tokens.items()]
    scored.sort(key=lambda x: -x[1])
    return scored


# ── Paper trading ────────────────────────────────────────────────────────────

@dataclass
class Trade:
    signal_ts: float
    token: str
    entry_slot: int
    exit_slot: int
    entry_delta: float
    exit_delta: float
    predicted_score: float
    actual_score: float
    tags: List[str]
    synthetic_return: float = 0.0

    @property
    def return_pct(self) -> float:
        return self.synthetic_return


def simulate_trade(
    token: str,
    signal_ts: float,
    predicted_score: float,
    actual_score: float,
    tags: List[str],
    by_token: Dict[str, List[dict]],
    hold_txs: int = 5,
) -> Optional[Trade]:
    txs = by_token.get(token, [])
    if not txs:
        return None

    # Find the first tx at or after signal time
    entry_idx = None
    for i, tx in enumerate(txs):
        if tx.get("ts", 0) >= signal_ts:
            entry_idx = i
            break
    if entry_idx is None:
        return None

    entry_tx = txs[entry_idx]
    entry_slot = entry_tx.get("slot", 0)
    entry_delta = entry_tx.get("sol_delta", 0.0)

    # Holding window: next hold_txs transactions (including entry)
    window_end = min(entry_idx + hold_txs, len(txs))
    window = txs[entry_idx:window_end]
    exit_tx = window[-1]
    exit_slot = exit_tx.get("slot", 0)
    exit_delta = exit_tx.get("sol_delta", 0.0)

    # Synthetic return: volume trend in the window
    # Compare average sol_delta in window to entry tx
    # Positive = subsequent txs have higher volume → bullish signal
    window_deltas = [tx.get("sol_delta", 0.0) for tx in window]
    avg_window = sum(window_deltas) / len(window_deltas) if window_deltas else 0.0
    if entry_delta > 1e-9:
        net_flow = ((avg_window - entry_delta) / entry_delta) * 100.0
    else:
        net_flow = 0.0
    # Cap at +/- 200% to avoid extreme outliers from tiny entry deltas
    net_flow = max(-200.0, min(200.0, net_flow))

    return Trade(
        signal_ts=signal_ts,
        token=token,
        entry_slot=entry_slot,
        exit_slot=exit_slot,
        entry_delta=entry_delta,
        exit_delta=exit_delta,
        predicted_score=predicted_score,
        actual_score=actual_score,
        tags=tags,
        synthetic_return=net_flow,
    )


def run_trader(
    model_path: Path,
    feed_path: Path,
    patterns_path: Path,
    threshold: float = 0.60,
    hold_txs: int = 5,
    capital: float = 10.0,
    max_trades: int = 0,
):
    print(f"[trader] Loading model from {model_path}")
    model = load_model(model_path)
    print(f"[trader] Model: {model['input_dim']} → {model['hidden_dim']} → 1")

    print(f"[trader] Indexing feed: {feed_path}")
    by_token, by_ts = index_feed(feed_path)
    print(f"[trader] Tokens indexed: {len(by_token)} | TS buckets: {len(by_ts)}")

    patterns = []
    if patterns_path.exists():
        with open(patterns_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    p = json.loads(line)
                    patterns.append(p)
                except Exception:
                    pass
    print(f"[trader] Patterns loaded: {len(patterns)}")

    # Score all patterns and find those above threshold
    signals = []
    for p in patterns:
        pred = forward(model, extract_features(p))
        if pred >= threshold:
            tokens = find_pattern_tokens(p, by_ts, window_s=5.0)
            for token, conf in tokens[:2]:  # top 2 tokens per pattern
                signals.append({
                    "pattern": p,
                    "predicted": pred,
                    "token": token,
                    "token_conf": conf,
                    "ts": p.get("ts", 0.0),
                })

    print(f"[trader] Signals above {threshold}: {len(signals)}")
    if not signals:
        print("[trader] No signals to trade.")
        return

    # Deduplicate: one trade per token per 30-second window
    seen_windows: Dict[str, float] = {}
    trades: List[Trade] = []
    for sig in signals:
        token = sig["token"]
        ts = sig["ts"]
        last = seen_windows.get(token, -999)
        if ts - last < 30:
            continue
        seen_windows[token] = ts

        trade = simulate_trade(
            token=token,
            signal_ts=ts,
            predicted_score=sig["predicted"],
            actual_score=sig["pattern"].get("score", 0.0),
            tags=sig["pattern"].get("tags", []),
            by_token=by_token,
            hold_txs=hold_txs,
        )
        if trade:
            trades.append(trade)
        if max_trades and len(trades) >= max_trades:
            break

    print(f"[trader] Trades executed: {len(trades)}")
    if not trades:
        return

    # PnL summary
    total_return = sum(t.return_pct for t in trades)
    wins = sum(1 for t in trades if t.return_pct > 0)
    losses = sum(1 for t in trades if t.return_pct <= 0)
    avg_return = total_return / len(trades)
    best = max(trades, key=lambda t: t.return_pct)
    worst = min(trades, key=lambda t: t.return_pct)

    # Capital simulation
    final_capital = capital * math.prod(1 + t.return_pct / 100.0 for t in trades)

    print(f"\n{'='*60}")
    print("[trader] PnL SUMMARY")
    print(f"{'='*60}")
    print(f"Starting capital: {capital:.4f} SOL")
    print(f"Final capital:    {final_capital:.4f} SOL")
    print(f"Total return:     {((final_capital - capital) / capital * 100):.2f}%")
    print(f"Trades:           {len(trades)}")
    print(f"Wins:             {wins} ({wins/len(trades)*100:.1f}%)")
    print(f"Losses:           {losses} ({losses/len(trades)*100:.1f}%)")
    print(f"Avg return/trade: {avg_return:.2f}%")
    print(f"Best trade:       +{best.return_pct:.2f}%  token={best.token[:16]}...")
    print(f"Worst trade:      {worst.return_pct:.2f}%  token={worst.token[:16]}...")
    print(f"{'='*60}")

    # Top 10 trades
    print("\nTop 10 trades:")
    for t in sorted(trades, key=lambda x: -x.return_pct)[:10]:
        print(f"  {t.token[:20]:20s} pred={t.predicted_score:.3f} actual={t.actual_score:.3f} "
              f"entry={t.entry_delta:.6f} exit={t.exit_delta:.6f} return={t.return_pct:+.2f}%")

    # Save trades
    trades_path = HERE / "feed" / "trades.jsonl"
    with open(trades_path, "w") as f:
        for t in trades:
            rec = {
                "signal_ts": t.signal_ts,
                "token": t.token,
                "entry_slot": t.entry_slot,
                "exit_slot": t.exit_slot,
                "entry_delta": t.entry_delta,
                "exit_delta": t.exit_delta,
                "predicted_score": t.predicted_score,
                "actual_score": t.actual_score,
                "return_pct": round(t.return_pct, 4),
                "tags": t.tags,
            }
            f.write(json.dumps(rec, default=str) + "\n")
    print(f"\n[trader] Trades saved to {trades_path}")

    return trades


def main():
    ap = argparse.ArgumentParser(description="Pattern-based paper trader")
    ap.add_argument("--model", type=Path, default=HERE / "feed" / "pattern_model.json")
    ap.add_argument("--feed", type=Path, default=HERE / "feed" / "live_features.jsonl")
    ap.add_argument("--patterns", type=Path, default=HERE / "feed" / "orchestration.jsonl")
    ap.add_argument("--threshold", type=float, default=0.60)
    ap.add_argument("--hold-txs", type=int, default=5, help="How many subsequent txs to hold")
    ap.add_argument("--capital", type=float, default=10.0, help="Starting SOL capital")
    ap.add_argument("--max-trades", type=int, default=0, help="0 = unlimited")
    args = ap.parse_args()
    run_trader(
        model_path=args.model,
        feed_path=args.feed,
        patterns_path=args.patterns,
        threshold=args.threshold,
        hold_txs=args.hold_txs,
        capital=args.capital,
        max_trades=args.max_trades,
    )


if __name__ == "__main__":
    main()
