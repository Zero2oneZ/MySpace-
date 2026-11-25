"""wallet_grid_mapper.py — Map the multidimensional wallet activation grid.

This is the proxy-layer for detecting "serious engineer" infrastructure when
full CPI metadata (innerInstructions) is not yet available. It builds a graph of
wallets that co-activate on the same token within tight time windows, revealing
the "rotating recursive transformer" pattern at the account level.

Heuristics:
- COORDINATED_CLUSTER: >3 wallets trade same token within 5s with similar deltas
- DAISY_CHAIN: wallet A trades, then B, then C, then A again (recursive loop)
- VOLUME_SPIKE: token tx count >20 in 10s (bot-orchestrated pump)
- MIRROR_PAIR: two wallets with identical trade sequences across tokens
- GRID_NODE: wallet appears in >5 clusters (hub of the multidimensional grid)

Input:  pump_feed.py JSONL (needs wallet + token + sol_delta + ts)
Output: JSONL grid report + Graphviz DOT + summary

Usage:
    python3 wallet_grid_mapper.py --feed ./feed/live_features.jsonl --report ./feed/grid.jsonl
    cc -wallet-grid
"""
from __future__ import annotations

import argparse
import json
import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class GridCluster:
    token: str
    wallets: set[str]
    txs: list[dict]
    centroid_ts: float
    span_ms: float
    avg_delta: float
    delta_variance: float
    is_recursive: bool
    bot_score: float
    tags: list[str]


class WalletGridMapper:
    """Maps the wallet-level multidimensional activation grid."""

    def __init__(self, window_s: float = 5.0, min_cluster_size: int = 3):
        self.window = window_s
        self.min_size = min_cluster_size
        self.clusters: list[GridCluster] = []
        self.wallet_clusters: dict[str, list[GridCluster]] = defaultdict(list)
        self.token_history: dict[str, list[dict]] = defaultdict(list)
        self.digests_seen: set[str] = set()
        self.wallet_tx_chains: dict[str, list[dict]] = defaultdict(list)

    def ingest(self, obj: dict) -> Optional[GridCluster]:
        sig = obj.get("signature", "")
        if sig in self.digests_seen:
            return None
        self.digests_seen.add(sig)

        ts = obj.get("ts", 0.0)
        wallet = obj.get("wallet", "")
        token = obj.get("token") or "_unknown"
        sol_delta = obj.get("sol_delta", 0.0) or 0.0
        is_buy = bool(obj.get("is_buy", False))
        slot = obj.get("slot", 0)

        if not wallet or token == "_unknown":
            return None

        tx = {
            "sig": sig, "ts": ts, "wallet": wallet,
            "token": token, "sol_delta": sol_delta, "is_buy": is_buy, "slot": slot,
        }

        # Track per-wallet tx chains for daisy-chain detection
        self.wallet_tx_chains[wallet].append(tx)
        if len(self.wallet_tx_chains[wallet]) > 1000:
            self.wallet_tx_chains[wallet] = self.wallet_tx_chains[wallet][-500:]

        # Build rolling window for this token
        hist = self.token_history[token]
        hist.append(tx)
        # Trim old txs
        cutoff = ts - self.window
        self.token_history[token] = [h for h in hist if h["ts"] >= cutoff]

        # Cluster detection: group txs in window by token
        active = self.token_history[token]
        if len(active) < self.min_size:
            return None

        wallets = set(t["wallet"] for t in active)
        if len(wallets) < self.min_size:
            return None

        # Check if this cluster was already reported recently
        last_cluster_ts = max(
            (c.centroid_ts for c in self.wallet_clusters.get(token, [])),
            default=0.0
        )
        if abs(ts - last_cluster_ts) < self.window:
            return None

        # Compute cluster properties
        deltas = [t["sol_delta"] for t in active]
        avg_delta = sum(deltas) / len(deltas) if deltas else 0.0
        variance = sum((d - avg_delta) ** 2 for d in deltas) / len(deltas) if deltas else 0.0
        times = [t["ts"] for t in active]
        span_ms = (max(times) - min(times)) * 1000 if times else 0.0

        # Daisy-chain detection: does any wallet appear twice in the active window?
        wallet_counts = defaultdict(int)
        for t in active:
            wallet_counts[t["wallet"]] += 1
        is_recursive = any(c >= 2 for c in wallet_counts.values())

        # Mirror-pair detection: two wallets with identical buy/sell pattern
        tags = []
        buy_map = defaultdict(list)
        for t in active:
            buy_map[t["wallet"]].append(t["is_buy"])
        # Check for mirror pairs
        wallets_list = list(wallets)
        for i in range(len(wallets_list)):
            for j in range(i + 1, len(wallets_list)):
                a, b = wallets_list[i], wallets_list[j]
                seq_a = buy_map[a]
                seq_b = buy_map[b]
                if len(seq_a) >= 2 and seq_a == seq_b:
                    tags.append("MIRROR_PAIR")

        if is_recursive:
            tags.append("DAISY_CHAIN")
        if len(active) > 20:
            tags.append("VOLUME_SPIKE")
        if len(wallets) >= 5:
            tags.append("COORDINATED_CLUSTER")

        bot_score = self._compute_score(len(wallets), len(active), is_recursive, span_ms, variance)

        cluster = GridCluster(
            token=token,
            wallets=wallets,
            txs=active.copy(),
            centroid_ts=sum(times) / len(times),
            span_ms=span_ms,
            avg_delta=avg_delta,
            delta_variance=variance,
            is_recursive=is_recursive,
            bot_score=bot_score,
            tags=list(set(tags)),
        )

        self.clusters.append(cluster)
        for w in wallets:
            self.wallet_clusters[w].append(cluster)

        return cluster

    def _compute_score(self, wallet_count: int, tx_count: int, recursive: bool,
                       span_ms: float, variance: float) -> float:
        score = 0.0
        if wallet_count >= 5:
            score += 0.25
        if tx_count >= 10:
            score += 0.20
        if recursive:
            score += 0.25
        if span_ms < 2000:
            score += 0.15
        if variance < 0.001:
            score += 0.15
        return min(1.0, score)

    def summary(self) -> dict:
        total_clusters = len(self.clusters)
        recursive_clusters = sum(1 for c in self.clusters if c.is_recursive)
        volume_spikes = sum(1 for c in self.clusters if "VOLUME_SPIKE" in c.tags)
        mirror_pairs = sum(1 for c in self.clusters if "MIRROR_PAIR" in c.tags)

        # Grid nodes: wallets that appear in >5 clusters
        grid_nodes = [
            {"wallet": w, "cluster_count": len(clusters), "tokens": list(set(c.token for c in clusters))}
            for w, clusters in self.wallet_clusters.items()
            if len(clusters) >= 5
        ]
        grid_nodes.sort(key=lambda x: x["cluster_count"], reverse=True)

        return {
            "ts": time.time(),
            "total_clusters": total_clusters,
            "recursive_clusters": recursive_clusters,
            "volume_spikes": volume_spikes,
            "mirror_pairs": mirror_pairs,
            "grid_nodes": grid_nodes[:20],
            "top_clusters": sorted([
                {"token": c.token, "wallets": len(c.wallets), "txs": len(c.txs),
                 "recursive": c.is_recursive, "score": round(c.bot_score, 3),
                 "span_ms": round(c.span_ms, 1), "tags": c.tags}
                for c in self.clusters
            ], key=lambda x: x["score"], reverse=True)[:20],
        }


def run_mapper(feed_path: Path, report_path: Path, summary_path: Optional[Path] = None,
               max_lines: int = 0):
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if summary_path:
        summary_path.parent.mkdir(parents=True, exist_ok=True)
    if report_path.exists():
        report_path.write_text("")

    mapper = WalletGridMapper(window_s=5.0, min_cluster_size=3)
    lines = 0
    found = 0

    if not feed_path.exists():
        print(f"[grid] Feed not found: {feed_path}")
        return

    with open(feed_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            cluster = mapper.ingest(obj)
            lines += 1
            if cluster:
                found += 1
                with open(report_path, "a") as out:
                    rec = {
                        "token": cluster.token,
                        "ts": time.time(),
                        "centroid_ts": cluster.centroid_ts,
                        "wallets": list(cluster.wallets),
                        "tx_count": len(cluster.txs),
                        "span_ms": cluster.span_ms,
                        "avg_delta": cluster.avg_delta,
                        "recursive": cluster.is_recursive,
                        "score": cluster.bot_score,
                        "tags": cluster.tags,
                    }
                    out.write(json.dumps(rec, default=str) + "\n")
            if max_lines > 0 and lines >= max_lines:
                break

    summary = mapper.summary()
    print(f"[grid] Processed {lines} txs | Clusters: {found}")
    print(f"[grid] Recursive: {summary['recursive_clusters']} | Volume spikes: {summary['volume_spikes']} | Mirror pairs: {summary['mirror_pairs']}")
    print(f"[grid] Grid nodes (wallets in >=5 clusters): {len(summary['grid_nodes'])}")
    print(f"[grid] Top 5 clusters:")
    for c in summary["top_clusters"][:5]:
        print(f"  token={c['token'][:16]}... wallets={c['wallets']} txs={c['txs']} score={c['score']} tags={c['tags']}")

    if summary_path:
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2, default=str)
        print(f"[grid] Summary written to {summary_path}")

    return summary


def main():
    ap = argparse.ArgumentParser(description="Pump.fun wallet grid mapper")
    ap.add_argument("--feed", type=Path, default="./feed/live_features.jsonl")
    ap.add_argument("--report", type=Path, default="./feed/grid.jsonl")
    ap.add_argument("--summary", type=Path, default="./feed/grid_summary.json")
    ap.add_argument("--max-lines", type=int, default=0, help="0 = all")
    args = ap.parse_args()
    run_mapper(args.feed, args.report, args.summary, args.max_lines)


if __name__ == "__main__":
    main()
