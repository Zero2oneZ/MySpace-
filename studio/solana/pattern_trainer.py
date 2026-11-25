"""pattern_trainer.py — Pure-Python MLP for orchestration pattern scoring.

Zero dependencies (stdlib only). Trains on orchestration_summary.json patterns
to predict bot_score from structural chain features.

Usage:
    python3 pattern_trainer.py --epochs 2000 --lr 0.01
"""
from __future__ import annotations

import argparse
import json
import math
import random
import time
from pathlib import Path
from typing import List, Tuple

HERE = Path(__file__).resolve().parent

# ── Pure-Python tensor ops (enough for a tiny MLP) ───────────────────────────

def mat_vec_mul(W: List[List[float]], x: List[float]) -> List[float]:
    return [sum(wi * xi for wi, xi in zip(row, x)) for row in W]

def vec_add(a: List[float], b: List[float]) -> List[float]:
    return [ai + bi for ai, bi in zip(a, b)]

def vec_sub(a: List[float], b: List[float]) -> List[float]:
    return [ai - bi for ai, bi in zip(a, b)]

def vec_scale(a: List[float], s: float) -> List[float]:
    return [ai * s for ai in a]

def relu(v: List[float]) -> List[float]:
    return [max(0.0, x) for x in v]

def relu_deriv(v: List[float]) -> List[float]:
    return [1.0 if x > 0.0 else 0.0 for x in v]

def sigmoid(x: float) -> float:
    if x < -20:
        return 0.0
    if x > 20:
        return 1.0
    return 1.0 / (1.0 + math.exp(-x))

def mse_loss(y: float, y_hat: float) -> Tuple[float, float]:
    err = y_hat - y
    return err * err, 2.0 * err

# ── Feature extraction ────────────────────────────────────────────────────────

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

    # Structural features
    unique_nodes = len(set(chain))
    node_diversity = unique_nodes / depth if depth else 0.0

    # Root program type one-hot
    root = chain[0] if chain else ""
    is_sys = 1.0 if root == SYS_ID else 0.0
    is_pump = 1.0 if root == PUMP_ID else 0.0
    is_token = 1.0 if root.startswith("Token") else 0.0
    is_other = 1.0 if not (is_sys or is_pump or is_token) else 0.0

    # Max repetition ratio
    counts = {}
    for c in chain:
        counts[c] = counts.get(c, 0) + 1
    max_rep = max(counts.values()) if counts else 0
    rep_ratio = max_rep / depth if depth else 0.0

    # Tag counts
    n_tags = len(tags)
    has_deep = 1.0 if "DEEP_CHAIN" in tags else 0.0
    has_det = 1.0 if "DETERMINISTIC_GRID" in tags else 0.0
    has_hf = 1.0 if "HIGH_FREQUENCY" in tags else 0.0

    feats = [
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
    return feats

# ── MLP ───────────────────────────────────────────────────────────────────────

class TinyMLP:
    def __init__(self, input_dim: int, hidden_dim: int, seed: int = 42):
        rng = random.Random(seed)
        def init_mat(rows: int, cols: int) -> List[List[float]]:
            scale = math.sqrt(2.0 / cols)
            return [[rng.gauss(0, scale) for _ in range(cols)] for _ in range(rows)]
        def init_vec(dim: int) -> List[float]:
            return [0.0] * dim
        self.W1 = init_mat(hidden_dim, input_dim)
        self.b1 = init_vec(hidden_dim)
        self.W2 = init_mat(1, hidden_dim)
        self.b2 = [0.0]

    def forward(self, x: List[float]) -> Tuple[float, List[float], List[float]]:
        z1 = vec_add(mat_vec_mul(self.W1, x), self.b1)
        a1 = relu(z1)
        z2 = vec_add(mat_vec_mul(self.W2, a1), self.b2)
        out = sigmoid(z2[0])
        return out, a1, z1

    def predict(self, x: List[float]) -> float:
        out, _, _ = self.forward(x)
        return out

# ── Training ─────────────────────────────────────────────────────────────────

def _extract_ts(pattern: dict) -> float:
    """Extract timestamp from pattern_id like pat_6EF8rrec_1780104123456."""
    pid = pattern.get("id", "")
    parts = pid.split("_")
    if len(parts) >= 3:
        try:
            return int(parts[-1]) / 1000.0
        except ValueError:
            pass
    return 0.0

def train_mlp(
    patterns: List[dict],
    epochs: int = 2000,
    lr: float = 0.01,
    hidden: int = 16,
    seed: int = 42,
    verbose: int = 200,
    order: str = "shuffle",
) -> Tuple[TinyMLP, float, float]:
    # Prepare data with timestamps
    data = [(extract_features(p), p.get("score", 0.0), _extract_ts(p)) for p in patterns]

    if order == "shuffle":
        rng = random.Random(seed)
        rng.shuffle(data)
    elif order == "forward":
        data.sort(key=lambda x: x[2])  # oldest first
    elif order == "backward":
        data.sort(key=lambda x: -x[2])  # newest first
    else:
        raise ValueError(f"Unknown order: {order}")

    # Strip timestamps
    data = [(x, y) for x, y, _ in data]
    n = len(data)
    n_train = int(n * 0.8)
    train = data[:n_train]
    test = data[n_train:]

    input_dim = len(train[0][0])
    mlp = TinyMLP(input_dim, hidden, seed)

    for epoch in range(1, epochs + 1):
        total_loss = 0.0
        for x, y in train:
            out, a1, z1 = mlp.forward(x)
            loss, dloss = mse_loss(y, out)
            total_loss += loss

            dz2 = [dloss * out * (1.0 - out)]
            dW2 = [[dz2[0] * a for a in a1]]
            db2 = dz2[:]

            da1 = vec_scale(mlp.W2[0], dz2[0])
            dz1 = [dai * di for dai, di in zip(da1, relu_deriv(z1))]
            dW1 = [[dz1[i] * x[j] for j in range(input_dim)] for i in range(hidden)]
            db1 = dz1[:]

            for i in range(hidden):
                for j in range(input_dim):
                    mlp.W1[i][j] -= lr * dW1[i][j] / len(train)
                mlp.b1[i] -= lr * db1[i] / len(train)
            for j in range(hidden):
                mlp.W2[0][j] -= lr * dW2[0][j] / len(train)
            mlp.b2[0] -= lr * db2[0] / len(train)

        if epoch % verbose == 0:
            train_mse = sum((mlp.predict(x) - y) ** 2 for x, y in train) / len(train)
            test_mse = sum((mlp.predict(x) - y) ** 2 for x, y in test) / len(test)
            print(f"[epoch {epoch:4d}] train_mse={train_mse:.5f} test_mse={test_mse:.5f}")

    train_mse = sum((mlp.predict(x) - y) ** 2 for x, y in train) / len(train)
    test_mse = sum((mlp.predict(x) - y) ** 2 for x, y in test) / len(test)
    print(f"\nFinal order={order:10s} train_mse={train_mse:.5f} test_mse={test_mse:.5f}")
    return mlp, train_mse, test_mse

# ── Main ────────────────────────────────────────────────────────────────────

def save_model(mlp: TinyMLP, path: Path) -> None:
    model = {
        "W1": mlp.W1,
        "b1": mlp.b1,
        "W2": mlp.W2,
        "b2": mlp.b2,
        "input_dim": len(mlp.W1[0]),
        "hidden_dim": len(mlp.W1),
    }
    with open(path, "w") as f:
        json.dump(model, f, indent=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--feed", type=Path, default=HERE / "feed" / "orchestration_summary.json")
    ap.add_argument("--epochs", type=int, default=2000)
    ap.add_argument("--lr", type=float, default=0.01)
    ap.add_argument("--hidden", type=int, default=16)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=HERE / "feed" / "pattern_model.json")
    ap.add_argument("--order", type=str, default="shuffle", choices=["shuffle", "forward", "backward"])
    ap.add_argument("--compare", action="store_true", help="Run shuffle + forward + backward and compare")
    args = ap.parse_args()

    with open(args.feed) as f:
        summary = json.load(f)
    patterns = summary.get("patterns", [])
    if len(patterns) < 20:
        print(f"[trainer] Not enough patterns ({len(patterns)}), need >=20")
        return

    print(f"[trainer] Patterns: {len(patterns)} | Features: ~{len(extract_features(patterns[0]))}")

    orders = ["shuffle", "forward", "backward"] if args.compare else [args.order]
    results = {}

    for order in orders:
        print(f"\n{'='*50}")
        print(f"[trainer] Training with order={order}")
        print(f"{'='*50}")
        mlp, train_mse, test_mse = train_mlp(
            patterns, epochs=args.epochs, lr=args.lr, hidden=args.hidden, seed=args.seed, order=order
        )
        results[order] = {"train_mse": train_mse, "test_mse": test_mse, "mlp": mlp}

    if args.compare:
        print(f"\n{'='*50}")
        print("[trainer] COMPARISON")
        print(f"{'='*50}")
        print(f"{'Order':<12} {'Train MSE':<12} {'Test MSE':<12} {'Test Rank'}")
        ranked = sorted(results.items(), key=lambda x: x[1]["test_mse"])
        for rank, (order, res) in enumerate(ranked, 1):
            print(f"{order:<12} {res['train_mse']:<12.5f} {res['test_mse']:<12.5f} #{rank}")
        best_order = ranked[0][0]
        print(f"\n[trainer] Best order: {best_order} (test_mse={ranked[0][1]['test_mse']:.5f})")
        best_mlp = results[best_order]["mlp"]
    else:
        best_mlp = results[args.order]["mlp"]

    save_model(best_mlp, args.out)
    print(f"[trainer] Model saved to {args.out}")

    # Predict on a few
    print("\nSample predictions:")
    for p in patterns[:5]:
        feats = extract_features(p)
        pred = best_mlp.predict(feats)
        print(f"  score={p['score']:.3f} pred={pred:.3f} tags={p.get('tags', [])}")


if __name__ == "__main__":
    main()
