"""bot_forensics.py — Sui DEX bot detection + forensic analysis.

Heuristics:
- SNIPER: tx within first 3 checkpoints of pool creation
- WASH_TRADER: same wallet swaps back within 60s
- COPY_CAT: wallet copies another wallet's swap within 2s
- MEV_BOT: high gas + same checkpoint collision
- SPAMMER: >10 txs in 60s from same wallet
- HIGH_GAS: gas > 0.05 SUI (bot-like priority)
- RUGGER: creator sells large % within 5 checkpoints of create

Input:  sui_feed.py JSONL
Output: JSONL forensics report + summary stats

Usage:
    python3 bot_forensics.py --feed ./feed/live_features.jsonl --report ./feed/bots.jsonl
    cc -sui-bot-forensics
"""
from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from sui_constants import FEATURE_DIM


@dataclass
class WalletProfile:
    wallet: str
    tx_count: int = 0
    swap_count: int = 0
    first_seen: float = 0.0
    last_seen: float = 0.0
    pools_traded: set[str] = field(default_factory=set)
    avg_gas: float = 0.0
    max_gas: float = 0.0
    snipe_count: int = 0
    wash_count: int = 0
    copy_count: int = 0
    mev_count: int = 0
    rug_count: int = 0
    spam_count: int = 0
    high_gas_count: int = 0
    bot_score: float = 0.0
    tags: list[str] = field(default_factory=list)
    txs_60s: list[float] = field(default_factory=list)


@dataclass
class PoolProfile:
    pool_id: str
    create_checkpoint: str = ""
    create_ts: float = 0.0
    tx_count: int = 0
    bot_count: int = 0
    rugged: bool = False


class BotForensics:
    """Analyzes Sui DEX transactions for bot patterns."""

    def __init__(self):
        self.wallets: dict[str, WalletProfile] = {}
        self.pools: dict[str, PoolProfile] = {}
        self.recent_txs: list[dict] = []
        self.digests_seen: set[str] = set()

    def ingest(self, obj: dict) -> Optional[dict]:
        digest = obj.get("digest", "")
        if digest in self.digests_seen:
            return None
        self.digests_seen.add(digest)

        ts = obj.get("ts", 0.0)
        ckpt = obj.get("checkpoint", "")
        feats = obj.get("features", [])
        gas = obj.get("gas", {})
        gas_total = sum(float(gas.get(k, 0)) for k in ["computationCost", "storageCost"])
        gas_total -= float(gas.get("storageRebate", 0))
        deltas = obj.get("balance_deltas", [])
        net_delta = sum(deltas) if deltas else 0.0
        is_swap = abs(net_delta) > 0.001

        wallet = obj.get("sender", "")[:16] or digest[:16]
        pool = obj.get("pool_id", "") or "_unknown"
        has_pool = pool != "_unknown"

        w = self.wallets.setdefault(wallet, WalletProfile(wallet=wallet))
        w.tx_count += 1
        w.last_seen = ts
        if w.first_seen == 0:
            w.first_seen = ts
        w.pools_traded.add(pool)
        if is_swap:
            w.swap_count += 1
        w.avg_gas = (w.avg_gas * (w.tx_count - 1) + gas_total) / w.tx_count
        w.max_gas = max(w.max_gas, gas_total)

        w.txs_60s.append(ts)
        cutoff = ts - 60
        w.txs_60s = [t for t in w.txs_60s if t > cutoff]

        p = self.pools.setdefault(pool, PoolProfile(pool_id=pool))
        p.tx_count += 1
        # Heuristic: first tx on pool = creation
        if p.create_checkpoint == "":
            p.create_checkpoint = ckpt
            p.create_ts = ts

        tags: list[str] = []
        low_quality = ckpt == "0" or ckpt == ""
        if low_quality:
            tags.append("LOW_QUALITY")

        if len(w.txs_60s) > 10:
            w.spam_count += 1
            tags.append("SPAMMER")

        if gas_total > 0.05:
            w.high_gas_count += 1
            tags.append("HIGH_GAS")

        # SNIPER
        if not low_quality and p.create_checkpoint and ckpt != "":
            try:
                if 0 <= int(ckpt) - int(p.create_checkpoint) <= 3:
                    w.snipe_count += 1
                    tags.append("SNIPER")
            except ValueError:
                pass

        # WASH_TRADER
        if has_pool and not low_quality and self._is_wash_trade(wallet, pool, ts, net_delta):
            w.wash_count += 1
            tags.append("WASH_TRADER")

        # COPY_CAT
        if has_pool and not low_quality and self._is_copy_trade(wallet, pool, ts, net_delta):
            w.copy_count += 1
            tags.append("COPY_CAT")

        # MEV_BOT
        if gas_total > 0.1 and not low_quality and self._is_mev_collision(wallet, ckpt):
            w.mev_count += 1
            tags.append("MEV_BOT")

        # RUGGER
        if not low_quality and net_delta < -1.0 and p.create_checkpoint and ckpt != "":
            try:
                if 0 <= int(ckpt) - int(p.create_checkpoint) <= 5:
                    w.rug_count += 1
                    tags.append("RUGGER")
                    p.rugged = True
            except ValueError:
                pass

        score = self._compute_bot_score(w, tags, feats)
        w.bot_score = max(w.bot_score, score)

        self.recent_txs.append({
            "wallet": wallet, "pool": pool, "ts": ts,
            "net_delta": net_delta, "checkpoint": ckpt,
            "has_pool": has_pool,
        })
        if len(self.recent_txs) > 2000:
            self.recent_txs.pop(0)

        real_tags = [tag for tag in tags if tag != "LOW_QUALITY"]
        if real_tags:
            w.tags = list(set(w.tags + real_tags))
            record = {
                "ts": ts,
                "checkpoint": ckpt,
                "digest": digest,
                "wallet": wallet,
                "pool": pool,
                "tags": real_tags,
                "bot_score": score,
                "gas_total": gas_total,
                "wallet_stats": {
                    "tx_count": w.tx_count,
                    "snipe_count": w.snipe_count,
                    "wash_count": w.wash_count,
                    "copy_count": w.copy_count,
                    "mev_count": w.mev_count,
                    "rug_count": w.rug_count,
                    "spam_count": w.spam_count,
                    "high_gas_count": w.high_gas_count,
                },
            }
            return record
        return None

    def _is_wash_trade(self, wallet: str, pool: str, ts: float, net_delta: float) -> bool:
        if abs(net_delta) < 0.001:
            return False
        for tx in reversed(self.recent_txs[-200:]):
            if (tx["wallet"] == wallet and tx["pool"] == pool and
                tx["has_pool"] and abs(tx["ts"] - ts) <= 60 and
                tx["net_delta"] * net_delta < 0):
                return True
        return False

    def _is_copy_trade(self, wallet: str, pool: str, ts: float, net_delta: float) -> bool:
        if abs(net_delta) < 0.001:
            return False
        for tx in reversed(self.recent_txs[-100:]):
            if (tx["wallet"] != wallet and tx["pool"] == pool and
                tx["has_pool"] and abs(tx["ts"] - ts) <= 2.0 and
                abs(tx["net_delta"] - net_delta) / max(abs(net_delta), 1e-9) < 0.10):
                return True
        return False

    def _is_mev_collision(self, wallet: str, ckpt: str) -> bool:
        for tx in reversed(self.recent_txs[-200:]):
            if tx["wallet"] != wallet and tx["checkpoint"] == ckpt and ckpt != "":
                return True
        return False

    def _compute_bot_score(self, w: WalletProfile, tags: list[str], feats: list[float]) -> float:
        score = 0.0
        if w.tx_count > 100:
            score += 0.05
        if w.spam_count >= 3:
            score += 0.25
        if w.high_gas_count >= 5:
            score += 0.15
        if w.snipe_count > 5:
            score += 0.20
        if w.wash_count > 3:
            score += 0.25
        if w.copy_count > 5:
            score += 0.20
        if w.mev_count > 2:
            score += 0.15
        if w.rug_count > 0:
            score += 0.30
        if len(feats) > 20:
            bot_feat = feats[20] if len(feats) > 20 else 0
            score += bot_feat * 0.1
        return min(1.0, score)

    def summary(self) -> dict:
        total_wallets = len(self.wallets)
        bot_wallets = sum(1 for w in self.wallets.values() if w.tags)
        total_txs = sum(w.tx_count for w in self.wallets.values())
        bot_txs = sum(w.tx_count for w in self.wallets.values() if w.tags)
        tag_counts: dict[str, int] = defaultdict(int)
        for w in self.wallets.values():
            for t in w.tags:
                tag_counts[t] += 1
        return {
            "ts": time.time(),
            "total_wallets": total_wallets,
            "bot_wallets": bot_wallets,
            "bot_wallet_pct": round(bot_wallets / max(total_wallets, 1) * 100, 2),
            "total_txs": total_txs,
            "bot_txs": bot_txs,
            "bot_tx_pct": round(bot_txs / max(total_txs, 1) * 100, 2),
            "tag_counts": dict(tag_counts),
            "top_bots": sorted(
                [{"wallet": w.wallet, "score": w.bot_score, "tags": w.tags,
                  "tx_count": w.tx_count, "snipes": w.snipe_count,
                  "spams": w.spam_count, "high_gas": w.high_gas_count}
                 for w in self.wallets.values() if w.tags],
                key=lambda x: x["score"],
                reverse=True,
            )[:20],
            "rugged_pools": sum(1 for p in self.pools.values() if p.rugged),
        }


def run_forensics(feed_path: Path, report_path: Path, summary_path: Optional[Path] = None,
                  max_lines: int = 0):
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if summary_path:
        summary_path.parent.mkdir(parents=True, exist_ok=True)
    if report_path.exists():
        report_path.write_text("")
    forensics = BotForensics()
    lines_processed = 0
    bots_found = 0
    if not feed_path.exists():
        print(f"[forensics] Feed not found: {feed_path}")
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
            record = forensics.ingest(obj)
            lines_processed += 1
            if record:
                bots_found += 1
                with open(report_path, "a") as out:
                    out.write(json.dumps(record, default=str) + "\n")
            if max_lines > 0 and lines_processed >= max_lines:
                break
    summary = forensics.summary()
    print(f"[forensics] Processed {lines_processed} txs | Bots: {bots_found} | "
          f"Bot wallets: {summary['bot_wallets']}/{summary['total_wallets']} "
          f"({summary['bot_wallet_pct']}%)")
    print(f"[forensics] Tag counts: {summary['tag_counts']}")
    print(f"[forensics] Rugged pools: {summary['rugged_pools']}")
    print(f"[forensics] Top 5 bots:")
    for b in summary["top_bots"][:5]:
        print(f"  {b['wallet']} score={b['score']:.2f} tags={b['tags']} txs={b['tx_count']}")
    if summary_path:
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2, default=str)
        print(f"[forensics] Summary written to {summary_path}")
    return summary


def main():
    ap = argparse.ArgumentParser(description="Sui DEX bot forensics")
    ap.add_argument("--feed", type=Path, default="./feed/live_features.jsonl")
    ap.add_argument("--report", type=Path, default="./feed/bots.jsonl")
    ap.add_argument("--summary", type=Path, default="./feed/bot_summary.json")
    ap.add_argument("--max-lines", type=int, default=0, help="0 = all")
    args = ap.parse_args()
    run_forensics(args.feed, args.report, args.summary, args.max_lines)


if __name__ == "__main__":
    main()
