"""program_correlator.py — asof time-window join of DOM intent ↔ on-chain truth.

Two streams in, one stream out:

    intent: ~/.cc/phantom_dom_events.jsonl
            (written by Phantom-wrapper / browser console miner; each row has
             {ts, kind, payload, source_url, ...}. If the file is missing this
             tool produces zero rows; it does NOT crash.)

    truth:  ~/.cc/program_events/<chain>/<short>/<date>.jsonl
            (written by program_monitor.py)

    out:    ~/.cc/correlations/<YYYY-MM-DD>.jsonl
            Each row: {dom_ts, dom_kind, dom_payload_short,
                       window_s, n_chain_events, top_program, top_category,
                       chain_actions: {action: count},
                       closest_lag_ms, closest_signature, closest_program}.

These rows are the training input for the bot-vs-human / chain-intent classifier
(GMM + XGBoost stack that already lives in pump_*). The point: DOM events
without a corresponding on-chain truth in the window are pure noise (lurkers,
bots reading state), while ones that DO have truth within ~5s are real intent
expressing onto chain.
"""
from __future__ import annotations

import argparse
import bisect
import collections
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core" / "lib"))

try:
    from dimension_pack import emit as _dim_emit
except Exception:
    _dim_emit = None

DOM_LOG = Path(os.path.expanduser("~/.cc/phantom_dom_events.jsonl"))
CHAIN_ROOT = Path(os.path.expanduser("~/.cc/program_events"))
OUT_ROOT = Path(os.path.expanduser("~/.cc/correlations"))


# ── data ──

@dataclass
class DomEvent:
    ts: float
    kind: str
    payload: Dict
    source_url: str = ""


@dataclass
class ChainEvent:
    ts: float
    chain: str
    program_id: str
    program_short: str
    program_name: str
    category: str
    action: str
    signature: str = ""
    tx_digest: str = ""
    raw: Dict = field(default_factory=dict)


@dataclass
class Correlation:
    dom_ts: float
    dom_kind: str
    dom_payload_short: str
    window_s: float
    n_chain_events: int
    top_program: str
    top_program_name: str
    top_category: str
    chain_actions: Dict[str, int]
    closest_lag_ms: Optional[float]
    closest_signature: str
    closest_program: str
    rgba: List[float] = field(default_factory=list)


# ── loaders ──

def _iter_jsonl(path: Path) -> Iterable[Dict]:
    if not path.exists():
        return
    try:
        with path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except Exception:
                    continue
    except Exception as exc:
        print(f"[correlator] read fail {path}: {exc}", file=sys.stderr)


def load_dom(since: float = 0.0, limit: int = 0) -> List[DomEvent]:
    out: List[DomEvent] = []
    for d in _iter_jsonl(DOM_LOG):
        ts = float(d.get("ts") or d.get("timestamp") or 0.0)
        if since and ts < since:
            continue
        out.append(DomEvent(
            ts=ts,
            kind=str(d.get("kind") or d.get("event") or "unknown"),
            payload=d.get("payload") or {},
            source_url=str(d.get("source_url") or d.get("source") or ""),
        ))
        if limit and len(out) >= limit:
            break
    out.sort(key=lambda e: e.ts)
    return out


def load_chain(since: float = 0.0) -> List[ChainEvent]:
    out: List[ChainEvent] = []
    if not CHAIN_ROOT.exists():
        return out
    for jf in sorted(CHAIN_ROOT.glob("**/*.jsonl")):
        for d in _iter_jsonl(jf):
            ts = float(d.get("ts") or 0.0)
            if since and ts < since:
                continue
            out.append(ChainEvent(
                ts=ts,
                chain=str(d.get("chain", "")),
                program_id=str(d.get("program_id", "")),
                program_short=str(d.get("program_short", "")),
                program_name=str(d.get("program_name", "")),
                category=str(d.get("category", "")),
                action=str(d.get("action", "other")),
                signature=str(d.get("signature", "")),
                tx_digest=str(d.get("tx_digest", "")),
                raw=d,
            ))
    out.sort(key=lambda e: e.ts)
    return out


# ── synthesize a stub DOM stream from chain events (for smoke when miner absent) ──

def synth_dom_from_chain(chain_events: List[ChainEvent], n: int = 50,
                          lag_min_ms: float = 50.0,
                          lag_max_ms: float = 4500.0,
                          jitter_seed: int = 17) -> List[DomEvent]:
    """For testing: pretend a Phantom DOM intent fired N..lag_ms BEFORE each of
    n chain events. Useful when the real miner isn't running yet — gives the
    correlator something to chew on so the row format can be validated."""
    import random
    rng = random.Random(jitter_seed)
    picks = rng.sample(chain_events, k=min(n, len(chain_events))) if chain_events else []
    out: List[DomEvent] = []
    for ce in picks:
        lag_s = rng.uniform(lag_min_ms, lag_max_ms) / 1000.0
        out.append(DomEvent(
            ts=ce.ts - lag_s,
            kind="signAndSendTransaction",
            payload={"intended_program": ce.program_short,
                       "intended_action": ce.action,
                       "synthetic": True},
            source_url="phantom://synth",
        ))
    out.sort(key=lambda e: e.ts)
    return out


# ── join ──

def correlate(dom: List[DomEvent], chain: List[ChainEvent],
               window_s: float = 5.0) -> List[Correlation]:
    if not chain:
        return []
    chain_ts = [c.ts for c in chain]
    out: List[Correlation] = []
    for d in dom:
        lo = bisect.bisect_left(chain_ts, d.ts - window_s)
        hi = bisect.bisect_right(chain_ts, d.ts + window_s)
        bucket = chain[lo:hi]
        if not bucket:
            out.append(Correlation(
                dom_ts=d.ts, dom_kind=d.kind,
                dom_payload_short=_short_payload(d.payload),
                window_s=window_s, n_chain_events=0,
                top_program="", top_program_name="", top_category="",
                chain_actions={}, closest_lag_ms=None,
                closest_signature="", closest_program="",
                rgba=_dim_rgba(d.kind, "none"),
            ))
            continue
        # most-followed program (frequency)
        prog_counter = collections.Counter((c.program_short, c.program_name, c.category)
                                           for c in bucket)
        (top_short, top_name, top_cat), _ = prog_counter.most_common(1)[0]
        action_counter: Dict[str, int] = collections.Counter(c.action for c in bucket)
        # closest in absolute ts
        closest = min(bucket, key=lambda c: abs(c.ts - d.ts))
        lag_ms = (closest.ts - d.ts) * 1000.0
        out.append(Correlation(
            dom_ts=d.ts, dom_kind=d.kind,
            dom_payload_short=_short_payload(d.payload),
            window_s=window_s, n_chain_events=len(bucket),
            top_program=top_short, top_program_name=top_name,
            top_category=top_cat,
            chain_actions=dict(action_counter),
            closest_lag_ms=lag_ms,
            closest_signature=closest.signature or closest.tx_digest,
            closest_program=closest.program_short,
            rgba=_dim_rgba(d.kind, top_cat),
        ))
    return out


def _short_payload(p: Dict) -> str:
    try:
        s = json.dumps(p, separators=(",", ":"))
    except Exception:
        s = str(p)
    return s[:120]


def _dim_rgba(dom_kind: str, top_cat: str) -> List[float]:
    if _dim_emit is None:
        return []
    try:
        pack = _dim_emit({
            "tier": "correlation",
            "model": dom_kind,
            "cost_class": "deterministic",
            "sub_dag": "INFERENCE" if top_cat != "none" else "RECURSIVE_WORKFLOWS",
            "ts": time.time(),
        })
        return list(pack.rgba)
    except Exception:
        return []


# ── persist ──

def persist(rows: List[Correlation]) -> Path:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    p = OUT_ROOT / f"{day}.jsonl"
    with p.open("a") as f:
        for r in rows:
            f.write(json.dumps(asdict(r), separators=(",", ":")) + "\n")
    return p


# ── reporting ──

def aggregate(rows: List[Correlation]) -> Dict:
    if not rows:
        return {"n": 0}
    lags = [r.closest_lag_ms for r in rows if r.closest_lag_ms is not None]
    matched = sum(1 for r in rows if r.n_chain_events > 0)
    cat_counter: Dict[str, int] = collections.Counter()
    action_counter: Dict[str, int] = collections.Counter()
    for r in rows:
        if r.top_category:
            cat_counter[r.top_category] += 1
        for a, n in r.chain_actions.items():
            action_counter[a] += n
    return {
        "n": len(rows),
        "matched": matched,
        "match_rate": round(matched / len(rows), 4),
        "lag_ms_mean": round(sum(lags) / len(lags), 2) if lags else None,
        "lag_ms_min": round(min(lags), 2) if lags else None,
        "lag_ms_max": round(max(lags), 2) if lags else None,
        "top_categories": dict(cat_counter.most_common(5)),
        "top_actions": dict(action_counter.most_common(10)),
    }


# ── CLI ──

def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description="program_correlator — DOM↔chain asof join")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="join DOM + chain → correlations")
    p_run.add_argument("--window", type=float, default=5.0)
    p_run.add_argument("--since", type=float, default=0.0,
                       help="seconds ago lower bound (0=all)")
    p_run.add_argument("--limit", type=int, default=0,
                       help="cap DOM rows (0=all)")
    p_run.add_argument("--synth", type=int, default=0,
                       help="synthesize N DOM rows from chain when miner absent")
    p_run.add_argument("--persist", action="store_true",
                       help="append to ~/.cc/correlations/YYYY-MM-DD.jsonl")
    p_run.add_argument("--print", type=int, default=5,
                       help="print first N correlation rows")

    p_stats = sub.add_parser("stats", help="aggregate over today's correlations")

    p_clear = sub.add_parser("clear", help="remove today's correlation file")

    args = ap.parse_args(argv)

    if args.cmd == "stats":
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        p = OUT_ROOT / f"{day}.jsonl"
        rows = [Correlation(**d) for d in _iter_jsonl(p)] if p.exists() else []
        print(json.dumps(aggregate(rows), indent=2))
        return 0

    if args.cmd == "clear":
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        p = OUT_ROOT / f"{day}.jsonl"
        if p.exists():
            p.unlink()
            print(f"[correlator] removed {p}")
        else:
            print("[correlator] nothing to clear")
        return 0

    since_ts = (time.time() - args.since) if args.since else 0.0
    chain = load_chain(since=since_ts)
    print(f"[correlator] chain events loaded: {len(chain)}", file=sys.stderr)

    dom = load_dom(since=since_ts, limit=args.limit)
    if not dom and args.synth and chain:
        dom = synth_dom_from_chain(chain, n=args.synth)
        print(f"[correlator] DOM file empty — synthesized {len(dom)} rows from chain",
              file=sys.stderr)
    else:
        print(f"[correlator] DOM events loaded: {len(dom)}", file=sys.stderr)

    rows = correlate(dom, chain, window_s=args.window)
    print(f"[correlator] correlation rows: {len(rows)}", file=sys.stderr)

    if args.persist and rows:
        path = persist(rows)
        print(f"[correlator] appended to {path}", file=sys.stderr)

    if args.print:
        for r in rows[: args.print]:
            print(json.dumps(asdict(r), separators=(",", ":")))

    print("---SUMMARY---")
    print(json.dumps(aggregate(rows), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
