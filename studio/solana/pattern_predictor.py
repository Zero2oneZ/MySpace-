"""pattern_predictor.py — Real-time inference on orchestration patterns.

Loads a pure-Python MLP from pattern_model.json and scores live patterns
from orchestration.jsonl or stdin.

Usage:
    python3 pattern_predictor.py --model ./feed/pattern_model.json --feed ./feed/orchestration.jsonl
    tail -f ./feed/orchestration.jsonl | python3 pattern_predictor.py --model ./feed/pattern_model.json --stream
    cc -pattern-predict --threshold 0.60
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import List

HERE = Path(__file__).resolve().parent

PUMP_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
SYS_ID  = "11111111111111111111111111111111"


def extract_features(pattern: dict) -> List[float]:
    chain = pattern.get("chain", [])
    depth = len(chain)
    freq = pattern.get("freq", 0)
    interval_ms = pattern.get("interval_ms", 0.0)
    is_rec = 1.0 if pattern.get("recursive") else 0.0
    is_self = 1.0 if pattern.get("self_activating") else 0.0
    tags = pattern.get("tags", [])

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


def mat_vec_mul(W: List[List[float]], x: List[float]) -> List[float]:
    return [sum(wi * xi for wi, xi in zip(row, x)) for row in W]


def vec_add(a: List[float], b: List[float]) -> List[float]:
    return [ai + bi for ai, bi in zip(a, b)]


def relu(v: List[float]) -> List[float]:
    return [max(0.0, x) for x in v]


def sigmoid(x: float) -> float:
    if x < -20:
        return 0.0
    if x > 20:
        return 1.0
    return 1.0 / (1.0 + math.exp(-x))


def forward(W1, b1, W2, b2, x: List[float]) -> float:
    z1 = vec_add(mat_vec_mul(W1, x), b1)
    a1 = relu(z1)
    z2 = vec_add(mat_vec_mul(W2, a1), b2)
    return sigmoid(z2[0])


def load_model(path: Path) -> dict:
    with open(path) as f:
        m = json.load(f)
    return m


def predict(model: dict, pattern: dict) -> float:
    feats = extract_features(pattern)
    return forward(model["W1"], model["b1"], model["W2"], model["b2"], feats)


def score_stream(model: dict, threshold: float = 0.0):
    """Read JSONL from stdin, score each pattern, print if above threshold."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            pat = json.loads(line)
        except Exception:
            continue
        score = predict(model, pat)
        if score >= threshold:
            rec = {
                "ts": pat.get("ts", 0),
                "pattern_id": pat.get("pattern_id", pat.get("id", "")),
                "root": pat.get("root", pat.get("root_contract", "")),
                "depth": len(pat.get("chain", [])),
                "tags": pat.get("tags", []),
                "predicted_score": round(score, 4),
            }
            print(json.dumps(rec, default=str))
            sys.stdout.flush()


def score_file(model: dict, feed_path: Path, threshold: float = 0.0):
    """Score all patterns in a JSONL file."""
    scored = []
    with open(feed_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                pat = json.loads(line)
            except Exception:
                continue
            score = predict(model, pat)
            if score >= threshold:
                scored.append({
                    "pattern_id": pat.get("pattern_id", pat.get("id", "")),
                    "root": pat.get("root", pat.get("root_contract", "")),
                    "predicted_score": round(score, 4),
                    "tags": pat.get("tags", []),
                })
    scored.sort(key=lambda x: x["predicted_score"], reverse=True)
    print(f"[predictor] Patterns above threshold {threshold}: {len(scored)}")
    for s in scored[:20]:
        print(f"  {s['pattern_id'][:20]:20s} root={s['root'][:16]:16s} score={s['predicted_score']:.3f} tags={s['tags']}")
    return scored


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", type=Path, default=HERE / "feed" / "pattern_model.json")
    ap.add_argument("--feed", type=Path, default=None)
    ap.add_argument("--threshold", type=float, default=0.5, help="Only output patterns with predicted score >= N")
    ap.add_argument("--stream", action="store_true", help="Read JSONL from stdin")
    args = ap.parse_args()

    model = load_model(args.model)
    print(f"[predictor] Model loaded: {model['input_dim']} → {model['hidden_dim']} → 1")

    if args.stream:
        score_stream(model, args.threshold)
    elif args.feed:
        score_file(model, args.feed, args.threshold)
    else:
        # Default: score the live orchestration report
        default_feed = HERE / "feed" / "orchestration.jsonl"
        if default_feed.exists():
            score_file(model, default_feed, args.threshold)
        else:
            print(f"[predictor] No feed found. Use --feed or --stream.")


if __name__ == "__main__":
    main()
