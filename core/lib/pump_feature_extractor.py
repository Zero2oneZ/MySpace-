"""
pump_feature_extractor — behavioral feature engineering for pump.fun event streams.

Consumes the JSONL output of pump_stream_ingest.py (parallel agent A) and produces a
feature DataFrame ready for GMM + XGBoost classification of bot vs human wallets.

Event shape (per JSONL line):
    {
      "ts":         <float unix seconds>,
      "signature":  <str>,
      "slot":       <int>,
      "program":    <str, e.g. "pump.fun">,
      "kind":       <"buy"|"sell">,
      "payer":      <str wallet base58>,
      "mint":       <str token mint>,
      "sol_amount": <float SOL>,
      "token_amount": <float>,
      "priority_fee_lamports": <int>,
      "jito_tip_lamports":     <int>,
      "raw_logs":   [str]
    }

Features (10 per wallet per window):
    wallet, tx_per_block, tx_per_block_var, value_entropy,
    benford_distance, funding_proximity, gas_distortion,
    jito_bundle_ratio, buy_sell_balance, unique_mints_touched,
    session_length_seconds

Polars-or-fallback:
    Tries `import polars as pl`. If absent, falls back to a tiny `_PolarsFallback`
    wrapper around a dict-of-lists that supports the minimum surface we use:
    .select(cols), .group_by(col).agg(...), .with_columns(...), .write_csv(path),
    .to_dicts(), and __len__. The fallback exists so this module smokes anywhere;
    polars remains the canonical path for downstream training joins.

Stdlib-only otherwise. Optional RPC dependency for funding_proximity (subprocess
calls `solana transaction-history --limit 1 <wallet>`); returns -1 if unreachable.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable

# ---------------------------------------------------------------------------
# Polars or fallback
# ---------------------------------------------------------------------------

try:
    import polars as pl  # type: ignore
    _POLARS_AVAILABLE = True
except ImportError:  # pragma: no cover - fallback path
    pl = None  # type: ignore
    _POLARS_AVAILABLE = False


class _PolarsFallback:
    """Minimal DataFrame-shaped wrapper used only when polars is unavailable.

    Supports the subset of the polars API exercised by this module:
        - construction from {col: [vals]} or list[dict]
        - .columns, .height, len()
        - .to_dicts()
        - .write_csv(path)
        - .select(names) -> new _PolarsFallback (subset of columns)
        - .with_columns(name=values_list) -> new _PolarsFallback
        - .filter(mask_list) -> new _PolarsFallback
    """

    def __init__(self, data: dict[str, list[Any]] | list[dict[str, Any]] | None = None):
        if data is None:
            self._cols: dict[str, list[Any]] = {}
            return
        if isinstance(data, list):
            cols: dict[str, list[Any]] = {}
            for row in data:
                for k, v in row.items():
                    cols.setdefault(k, []).append(v)
            # pad any missing keys
            n = max((len(v) for v in cols.values()), default=0)
            for k in cols:
                if len(cols[k]) < n:
                    cols[k].extend([None] * (n - len(cols[k])))
            self._cols = cols
        else:
            self._cols = {k: list(v) for k, v in data.items()}

    @property
    def columns(self) -> list[str]:
        return list(self._cols.keys())

    @property
    def height(self) -> int:
        if not self._cols:
            return 0
        return max(len(v) for v in self._cols.values())

    def __len__(self) -> int:
        return self.height

    def to_dicts(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for i in range(self.height):
            rows.append({k: self._cols[k][i] for k in self._cols})
        return rows

    def select(self, names: list[str]) -> "_PolarsFallback":
        return _PolarsFallback({k: list(self._cols.get(k, [])) for k in names})

    def with_columns(self, **kwargs: list[Any]) -> "_PolarsFallback":
        new = {k: list(v) for k, v in self._cols.items()}
        for k, v in kwargs.items():
            new[k] = list(v)
        return _PolarsFallback(new)

    def filter(self, mask: list[bool]) -> "_PolarsFallback":
        new: dict[str, list[Any]] = {}
        for k, vals in self._cols.items():
            new[k] = [v for v, m in zip(vals, mask) if m]
        return _PolarsFallback(new)

    def write_csv(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        cols = self.columns
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for i in range(self.height):
                w.writerow([self._cols[c][i] for c in cols])

    def __repr__(self) -> str:  # pragma: no cover - human-only
        head = " | ".join(self.columns)
        rows = []
        for i, r in enumerate(self.to_dicts()[:5]):
            rows.append(" | ".join(str(r[c]) for c in self.columns))
        return f"<_PolarsFallback rows={self.height}>\n{head}\n" + "\n".join(rows)


def _make_df(data: dict[str, list[Any]] | list[dict[str, Any]]) -> Any:
    """Construct a polars DataFrame if available, else _PolarsFallback."""
    if _POLARS_AVAILABLE:
        if isinstance(data, dict):
            return pl.DataFrame(data)
        return pl.DataFrame(data)
    return _PolarsFallback(data)


# ---------------------------------------------------------------------------
# Pure-stdlib feature kernels
# ---------------------------------------------------------------------------

def value_entropy(amounts: list[float], bits: bool = True) -> float:
    """Shannon entropy of the value distribution, binning by log-scale.

    Bots emit ~constant amounts -> low entropy.
    Humans emit messy organic amounts -> high entropy.

    Returns entropy in bits (log base 2) by default, nats if bits=False.
    Empty / all-zero input -> 0.0.
    """
    if not amounts:
        return 0.0
    # log10 bins of width 0.25 over positive amounts (skip non-positive)
    bin_counts: dict[int, int] = defaultdict(int)
    total = 0
    for a in amounts:
        if a is None:
            continue
        try:
            a = float(a)
        except (TypeError, ValueError):
            continue
        if a <= 0:
            continue
        b = int(math.floor(math.log10(a) / 0.25))
        bin_counts[b] += 1
        total += 1
    if total == 0:
        return 0.0
    log_fn = math.log2 if bits else math.log
    h = 0.0
    for c in bin_counts.values():
        p = c / total
        if p > 0:
            h -= p * log_fn(p)
    return h


def benford_distance(amounts: list[float]) -> float:
    """KS-style distance of first-digit distribution vs Benford's expected log10(1+1/d).

    Benford expected: P(d) = log10(1 + 1/d) for d in 1..9.
    KS distance = max |F_observed(d) - F_benford(d)| across d.

    Bots emit round amounts (0.05, 0.1, 1.0) -> leading digit collapses to {1,5} -> high KS.
    Humans emit organic amounts -> closer to Benford -> low KS.

    Returns a value in [0.0, 1.0]; empty input -> 0.0.
    """
    if not amounts:
        return 0.0
    counts = [0] * 10  # index 1..9 used
    total = 0
    for a in amounts:
        if a is None:
            continue
        try:
            a = float(a)
        except (TypeError, ValueError):
            continue
        if a <= 0:
            continue
        # scale to a leading digit in 1..9
        s = abs(a)
        while s < 1.0:
            s *= 10.0
        while s >= 10.0:
            s /= 10.0
        d = int(s)
        if 1 <= d <= 9:
            counts[d] += 1
            total += 1
    if total == 0:
        return 0.0
    # CDFs across digits 1..9
    obs_cdf = 0.0
    ben_cdf = 0.0
    ks = 0.0
    for d in range(1, 10):
        obs_cdf += counts[d] / total
        ben_cdf += math.log10(1.0 + 1.0 / d)
        diff = abs(obs_cdf - ben_cdf)
        if diff > ks:
            ks = diff
    return ks


def gas_distortion(priority_fees: list[float]) -> float:
    """std(priority_fee) / mean(priority_fee) — coefficient of variation.

    Bots set formulaic priority fees -> CV near 0.
    Humans set chaotic / mood-driven fees -> CV high.

    Empty / zero-mean input -> 0.0.
    """
    vals = [float(p) for p in priority_fees if p is not None]
    if not vals:
        return 0.0
    n = len(vals)
    mean = sum(vals) / n
    if mean == 0.0:
        return 0.0
    var = sum((v - mean) ** 2 for v in vals) / n
    std = math.sqrt(var)
    return std / mean


def jito_bundle_ratio(jito_tips: list[float]) -> float:
    """Fraction of txs with jito_tip > 0. Bots ~1.0, humans ~0.0."""
    if not jito_tips:
        return 0.0
    pos = sum(1 for t in jito_tips if t is not None and float(t) > 0)
    return pos / len(jito_tips)


def buy_sell_balance(kinds: list[str]) -> float:
    """|buys - sells| / total — bots pumping/dumping skew toward 1.0, humans mixed toward 0.0."""
    if not kinds:
        return 0.0
    buys = sum(1 for k in kinds if k == "buy")
    sells = sum(1 for k in kinds if k == "sell")
    total = buys + sells
    if total == 0:
        return 0.0
    return abs(buys - sells) / total


def tx_per_block_stats(slots: list[int]) -> tuple[float, float]:
    """Return (mean_tx_per_block, variance_tx_per_block) across the slots observed.

    Bots cluster txs at a roughly constant rate per block -> low variance.
    Humans show bursty / irregular per-block density -> high variance.
    """
    if not slots:
        return 0.0, 0.0
    counts: dict[int, int] = defaultdict(int)
    for s in slots:
        if s is None:
            continue
        counts[int(s)] += 1
    if not counts:
        return 0.0, 0.0
    vals = list(counts.values())
    n = len(vals)
    mean = sum(vals) / n
    var = sum((v - mean) ** 2 for v in vals) / n
    return mean, var


def funding_proximity_blocks(
    wallet: str,
    first_pump_slot: int,
    solana_rpc_url: str | None = None,
    _runner: Callable[[list[str]], subprocess.CompletedProcess] | None = None,
) -> int:
    """Blocks between the wallet's first ever tx and its first pump.fun buy.

    Bots are bundle-funded — their first ever tx is the funding hop a few slots before
    the first pump buy, so the delta is tiny (often < 10 slots).
    Humans use aged wallets — delta is millions of slots.

    Stub fallback returns -1 if the solana CLI is unreachable or returns junk.
    The `_runner` hook is for tests.
    """
    if not wallet or first_pump_slot is None:
        return -1
    runner = _runner or (lambda argv: subprocess.run(argv, capture_output=True, text=True, timeout=10))
    argv = ["solana", "transaction-history", "--limit", "1", wallet]
    if solana_rpc_url:
        argv.extend(["--url", solana_rpc_url])
    try:
        res = runner(argv)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return -1
    if res.returncode != 0 or not res.stdout:
        return -1
    # `solana transaction-history` prints one signature per line. The wallet's first ever
    # tx slot has to be resolved by a second confirm call — for the stub we look for
    # "Slot:" in stdout (matches `solana confirm` style output the user's CLI may pipe in).
    out = res.stdout.strip()
    first_slot: int | None = None
    for line in out.splitlines():
        line = line.strip()
        if line.lower().startswith("slot:"):
            try:
                first_slot = int(line.split(":", 1)[1].strip().split()[0])
                break
            except (ValueError, IndexError):
                continue
        # fall-back: if the line is itself an int slot
        try:
            first_slot = int(line)
            break
        except ValueError:
            continue
    if first_slot is None:
        return -1
    delta = int(first_pump_slot) - int(first_slot)
    return max(delta, 0)


# ---------------------------------------------------------------------------
# Event ingestion
# ---------------------------------------------------------------------------

def _iter_jsonl_events(paths: Iterable[Path]) -> Iterable[dict[str, Any]]:
    """Stream-decode every JSONL line from the given paths, skipping malformed rows."""
    for p in paths:
        try:
            f = open(p, "r", encoding="utf-8")
        except (FileNotFoundError, PermissionError, IsADirectoryError):
            continue
        with f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def _group_by_wallet(
    events: Iterable[dict[str, Any]],
    window_seconds: int,
) -> dict[str, list[dict[str, Any]]]:
    """Group events by `payer` wallet. Each wallet's events are sorted by ts and
    truncated to the most recent window_seconds-wide span.

    Window semantics: the window anchors at the wallet's LAST observed ts and walks
    backward window_seconds. This keeps the feature snapshot relative to the most
    recent activity per wallet, not to a global wall clock.
    """
    by_wallet: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in events:
        w = e.get("payer")
        if not w:
            continue
        by_wallet[w].append(e)
    out: dict[str, list[dict[str, Any]]] = {}
    for w, evs in by_wallet.items():
        evs.sort(key=lambda r: float(r.get("ts") or 0.0))
        last_ts = float(evs[-1].get("ts") or 0.0)
        cutoff = last_ts - float(window_seconds)
        windowed = [e for e in evs if float(e.get("ts") or 0.0) >= cutoff]
        out[w] = windowed
    return out


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------

FEATURE_COLS: list[str] = [
    "wallet",
    "tx_per_block",
    "tx_per_block_var",
    "value_entropy",
    "benford_distance",
    "funding_proximity",
    "gas_distortion",
    "jito_bundle_ratio",
    "buy_sell_balance",
    "unique_mints_touched",
    "session_length_seconds",
]


def _wallet_features(
    wallet: str,
    evs: list[dict[str, Any]],
    solana_rpc_url: str | None,
    rpc_enabled: bool,
) -> dict[str, Any]:
    """Compute the 10 features (plus the wallet label) for one wallet's window."""
    slots = [int(e["slot"]) for e in evs if e.get("slot") is not None]
    amounts = [float(e.get("sol_amount") or 0.0) for e in evs]
    priority_fees = [float(e.get("priority_fee_lamports") or 0.0) for e in evs]
    jito_tips = [float(e.get("jito_tip_lamports") or 0.0) for e in evs]
    kinds = [str(e.get("kind") or "") for e in evs]
    mints = {e.get("mint") for e in evs if e.get("mint")}
    timestamps = [float(e.get("ts") or 0.0) for e in evs]

    mean_block, var_block = tx_per_block_stats(slots)

    if rpc_enabled and slots:
        fp = funding_proximity_blocks(wallet, min(slots), solana_rpc_url)
    else:
        fp = -1

    return {
        "wallet": wallet,
        "tx_per_block": mean_block,
        "tx_per_block_var": var_block,
        "value_entropy": value_entropy(amounts, bits=True),
        "benford_distance": benford_distance(amounts),
        "funding_proximity": fp,
        "gas_distortion": gas_distortion(priority_fees),
        "jito_bundle_ratio": jito_bundle_ratio(jito_tips),
        "buy_sell_balance": buy_sell_balance(kinds),
        "unique_mints_touched": len(mints),
        "session_length_seconds": (max(timestamps) - min(timestamps)) if timestamps else 0.0,
    }


def extract_features(
    jsonl_paths: list[Path],
    window_seconds: int = 300,
    min_events_per_wallet: int = 3,
    solana_rpc_url: str | None = None,
    rpc_enabled: bool = False,
) -> Any:
    """Read N pump_stream JSONL files, group by wallet, compute behavioral features
    per wallet over the given window.

    Wallets with fewer than `min_events_per_wallet` events in the window are dropped.
    Returns a polars.DataFrame when polars is installed; a _PolarsFallback otherwise.
    """
    paths = [Path(p) for p in jsonl_paths]
    events = _iter_jsonl_events(paths)
    grouped = _group_by_wallet(events, window_seconds=window_seconds)

    rows: list[dict[str, Any]] = []
    for wallet, evs in grouped.items():
        if len(evs) < min_events_per_wallet:
            continue
        rows.append(_wallet_features(wallet, evs, solana_rpc_url, rpc_enabled))

    if not rows:
        # empty df with the right columns so downstream code can rely on schema
        empty: dict[str, list[Any]] = {c: [] for c in FEATURE_COLS}
        return _make_df(empty)
    # normalize to {col: [vals]} so polars and the fallback both get a happy shape
    cols: dict[str, list[Any]] = {c: [] for c in FEATURE_COLS}
    for r in rows:
        for c in FEATURE_COLS:
            cols[c].append(r.get(c))
    return _make_df(cols)


def to_training_csv(df: Any, output_path: Path) -> Path:
    """Write features.csv for downstream GMM + XGBoost training."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if _POLARS_AVAILABLE and not isinstance(df, _PolarsFallback):
        df.write_csv(str(output_path))
    else:
        df.write_csv(output_path)
    return output_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _df_pretty(df: Any) -> str:
    """Render a small DataFrame for terminal eyeballing — same shape under polars or fallback."""
    if _POLARS_AVAILABLE and not isinstance(df, _PolarsFallback):
        rows = df.to_dicts()
    else:
        rows = df.to_dicts()
    if not rows:
        return "<empty feature table>"
    cols = FEATURE_COLS
    header = " | ".join(cols)
    lines = [header, "-" * len(header)]
    for r in rows:
        parts: list[str] = []
        for c in cols:
            v = r.get(c)
            if isinstance(v, float):
                parts.append(f"{v:.4f}")
            else:
                parts.append(str(v))
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def _cmd_extract(args: argparse.Namespace) -> int:
    paths = [Path(p) for p in args.jsonl]
    df = extract_features(
        paths,
        window_seconds=args.window,
        min_events_per_wallet=args.min_events,
        solana_rpc_url=args.rpc,
        rpc_enabled=bool(args.rpc_enabled),
    )
    print(f"polars: {'present' if _POLARS_AVAILABLE else 'fallback (stdlib only)'}")
    print(f"wallets in feature table: {len(df)}")
    print(_df_pretty(df))
    if args.out:
        out = to_training_csv(df, Path(args.out))
        print(f"wrote {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pump_feature_extractor",
        description="Behavioral feature engineering for pump.fun event streams.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ex = sub.add_parser("extract", help="extract per-wallet features from one or more JSONL files")
    p_ex.add_argument("--jsonl", nargs="+", required=True, help="one or more JSONL paths")
    p_ex.add_argument("--window", type=int, default=300, help="window seconds (default 300)")
    p_ex.add_argument("--min-events", type=int, default=3, help="drop wallets with fewer events")
    p_ex.add_argument("--rpc", type=str, default=None, help="solana RPC URL (only used if --rpc-enabled)")
    p_ex.add_argument("--rpc-enabled", action="store_true", help="enable funding_proximity RPC queries")
    p_ex.add_argument("--out", type=str, default=None, help="write features.csv to this path")
    p_ex.set_defaults(func=_cmd_extract)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
