"""bot_forensics.py — Pump.fun bot detection + forensic analysis.

Heuristics:
- SNIPER: tx within first 3 blocks of token creation
- WASH_TRADER: same wallet buys + sells same token within 60s
- COPY_CAT: wallet copies another wallet's trade within 2s with similar amount
- MEV_BOT: high fee + same slot collision with another wallet
- SPAMMER: >10 txs in 60s from same wallet
- HIGH_FEE: fee > 0.05 SOL (bot-like priority)
- RUGGER: creator sells within 5 blocks of token creation
- LOW_QUALITY: slot==0 or fee is None (degraded RPC data)

Input:  pump_feed.py JSONL
Output: JSONL forensics report + summary stats

Usage:
    python3 bot_forensics.py --feed ./feed/live_features.jsonl --report ./feed/bots.jsonl
    cc -bot-forensics
"""
from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pump_constants import FEATURE_DIM


@dataclass
class WalletProfile:
    wallet: str
    tx_count: int = 0
    buy_count: int = 0
    sell_count: int = 0
    first_seen: float = 0.0
    last_seen: float = 0.0
    tokens_traded: set[str] = field(default_factory=set)
    avg_sol_delta: float = 0.0
    max_sol_delta: float = 0.0
    snipe_count: int = 0
    wash_count: int = 0
    copy_count: int = 0
    mev_count: int = 0
    rug_count: int = 0
    spam_count: int = 0
    high_fee_count: int = 0
    bot_score: float = 0.0
    tags: list[str] = field(default_factory=list)
    txs_60s: list[float] = field(default_factory=list)


@dataclass
class TokenProfile:
    mint: str
    create_slot: int = 0
    create_ts: float = 0.0
    tx_count: int = 0
    bot_count: int = 0
    rugged: bool = False
    graduated: bool = False


class BotForensics:
    """Analyzes Pump.fun transactions for bot patterns."""

    def __init__(self):
        self.wallets: dict[str, WalletProfile] = {}
        self.tokens: dict[str, TokenProfile] = {}
        self.recent_txs: list[dict] = []
        self.signatures_seen: set[str] = set()

    def ingest(self, obj: dict) -> Optional[dict]:
        """Ingest one transaction object. Returns forensic record if bot detected."""
        sig = obj.get("signature", "")
        if sig in self.signatures_seen:
            return None
        self.signatures_seen.add(sig)

        ts = obj.get("ts", 0.0)
        slot = obj.get("slot") or 0
        feats = obj.get("features", [])
        is_buy = bool(obj.get("is_buy", False))
        is_sell = bool(obj.get("is_sell", False))
        is_create = bool(obj.get("is_create", False))
        sol_delta = obj.get("sol_delta", 0.0) or 0.0
        fee = obj.get("fee")
        if fee is None:
            fee = obj.get("meta", {}).get("fee")
        if fee is None:
            fee = 5000
        fee = int(fee)

        wallet = obj.get("wallet") or sig[:8]
        token = obj.get("token")
        has_token = token is not None
        if not has_token:
            token = "_unknown"

        # Update profiles
        w = self.wallets.setdefault(wallet, WalletProfile(wallet=wallet))
        w.tx_count += 1
        w.last_seen = ts
        if w.first_seen == 0:
            w.first_seen = ts
        w.tokens_traded.add(token)
        if is_buy:
            w.buy_count += 1
        if is_sell:
            w.sell_count += 1
        w.avg_sol_delta = (w.avg_sol_delta * (w.tx_count - 1) + abs(sol_delta)) / w.tx_count
        w.max_sol_delta = max(w.max_sol_delta, abs(sol_delta))

        # Prune txs older than 60s for spam detection
        w.txs_60s.append(ts)
        cutoff = ts - 60
        w.txs_60s = [t for t in w.txs_60s if t > cutoff]

        t = self.tokens.setdefault(token, TokenProfile(mint=token))
        t.tx_count += 1
        if is_create:
            t.create_slot = slot
            t.create_ts = ts

        # ── Data quality gate ───────────────────────────────────────────────
        tags: list[str] = []
        low_quality = slot == 0 or fee == 5000 and sol_delta == 0
        if low_quality:
            tags.append("LOW_QUALITY")

        # ── Heuristic checks ────────────────────────────────────────────────

        # 1. SPAMMER: >10 txs in 60s
        if len(w.txs_60s) > 10:
            w.spam_count += 1
            tags.append("SPAMMER")

        # 2. HIGH_FEE: fee > 0.05 SOL (50000 lamports)
        if fee > 50000:
            w.high_fee_count += 1
            tags.append("HIGH_FEE")

        # 3. SNIPER: tx within 3 blocks of token creation (needs quality data)
        if not low_quality and t.create_slot > 0 and 0 <= slot - t.create_slot <= 3:
            w.snipe_count += 1
            tags.append("SNIPER")

        # 4. WASH_TRADER: rapid buy+sell cycle within 60s on same token
        if has_token and not low_quality and self._is_wash_trade(wallet, token, ts, is_buy, is_sell):
            w.wash_count += 1
            tags.append("WASH_TRADER")

        # 5. COPY_CAT: trade within 2s of another wallet on same token with similar amount
        if has_token and not low_quality and self._is_copy_trade(wallet, token, ts, is_buy, sol_delta):
            w.copy_count += 1
            tags.append("COPY_CAT")

        # 6. MEV_BOT: high fee + same slot collision with different wallet
        if fee > 100000 and not low_quality and self._is_mev_collision(wallet, slot):
            w.mev_count += 1
            tags.append("MEV_BOT")

        # 7. RUGGER: creator sells within 5 blocks
        if not low_quality and is_sell and t.create_slot > 0 and 0 <= slot - t.create_slot <= 5:
            w.rug_count += 1
            tags.append("RUGGER")
            t.rugged = True

        # ── BOT_SCORE composite ─────────────────────────────────────────────
        score = self._compute_bot_score(w, tags, feats)
        w.bot_score = max(w.bot_score, score)

        # Update recent txs
        self.recent_txs.append({
            "wallet": wallet, "token": token, "ts": ts,
            "is_buy": is_buy, "sol_delta": sol_delta, "slot": slot,
            "has_token": has_token,
        })
        if len(self.recent_txs) > 2000:
            self.recent_txs.pop(0)

        # Only emit record for real bot patterns (skip LOW_QUALITY-only)
        real_tags = [tag for tag in tags if tag != "LOW_QUALITY"]
        if real_tags:
            w.tags = list(set(w.tags + real_tags))
            record = {
                "ts": ts,
                "slot": slot,
                "signature": sig,
                "wallet": wallet,
                "token": token,
                "tags": real_tags,
                "bot_score": score,
                "sol_delta": sol_delta,
                "is_buy": is_buy,
                "wallet_stats": {
                    "tx_count": w.tx_count,
                    "snipe_count": w.snipe_count,
                    "wash_count": w.wash_count,
                    "copy_count": w.copy_count,
                    "mev_count": w.mev_count,
                    "rug_count": w.rug_count,
                    "spam_count": w.spam_count,
                    "high_fee_count": w.high_fee_count,
                },
            }
            return record
        return None

    def _is_wash_trade(self, wallet: str, token: str, ts: float,
                       is_buy: bool, is_sell: bool) -> bool:
        """Check if wallet had opposite trade on same token within 60s."""
        if not (is_buy or is_sell):
            return False
        for tx in reversed(self.recent_txs[-200:]):
            if (tx["wallet"] == wallet and tx["token"] == token and
                tx["has_token"] and
                abs(tx["ts"] - ts) <= 60 and
                tx["is_buy"] != is_buy):
                return True
        return False

    def _is_copy_trade(self, wallet: str, token: str, ts: float,
                       is_buy: bool, sol_delta: float) -> bool:
        """Check if another wallet traded same token within 2s with similar amount."""
        if sol_delta <= 0:
            return False
        for tx in reversed(self.recent_txs[-100:]):
            if (tx["wallet"] != wallet and tx["token"] == token and
                tx["has_token"] and
                tx["is_buy"] == is_buy and
                abs(tx["ts"] - ts) <= 2.0 and
                abs(tx["sol_delta"] - sol_delta) / max(sol_delta, 1e-9) < 0.10):
                return True
        return False

    def _is_mev_collision(self, wallet: str, slot: int) -> bool:
        """Check if another wallet had a tx in the same slot."""
        for tx in reversed(self.recent_txs[-200:]):
            if tx["wallet"] != wallet and tx["slot"] == slot and slot > 0:
                return True
        return False

    def _compute_bot_score(self, w: WalletProfile, tags: list[str], feats: list[float]) -> float:
        """Compute composite bot likelihood score 0-1."""
        score = 0.0
        if w.tx_count > 100:
            score += 0.05
        if w.spam_count >= 3:
            score += 0.25
        if w.high_fee_count >= 5:
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
        """Return aggregate forensics summary."""
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
                  "spams": w.spam_count, "high_fees": w.high_fee_count}
                 for w in self.wallets.values() if w.tags],
                key=lambda x: x["score"],
                reverse=True,
            )[:20],
            "rugged_tokens": sum(1 for t in self.tokens.values() if t.rugged),
        }


def run_forensics(feed_path: Path, report_path: Path, summary_path: Optional[Path] = None,
                  max_lines: int = 0):
    """Run forensics on a JSONL feed."""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if summary_path:
        summary_path.parent.mkdir(parents=True, exist_ok=True)

    # Truncate report
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
    print(f"[forensics] Rugged tokens: {summary['rugged_tokens']}")
    print(f"[forensics] Top 5 bots:")
    for b in summary["top_bots"][:5]:
        print(f"  {b['wallet']} score={b['score']:.2f} tags={b['tags']} txs={b['tx_count']}")

    if summary_path:
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2, default=str)
        print(f"[forensics] Summary written to {summary_path}")

    return summary


def main():
    ap = argparse.ArgumentParser(description="Pump.fun bot forensics")
    ap.add_argument("--feed", type=Path, default="./feed/live_features.jsonl")
    ap.add_argument("--report", type=Path, default="./feed/bots.jsonl")
    ap.add_argument("--summary", type=Path, default="./feed/bot_summary.json")
    ap.add_argument("--max-lines", type=int, default=0, help="0 = all")
    args = ap.parse_args()
    run_forensics(args.feed, args.report, args.summary, args.max_lines)


if __name__ == "__main__":
    main()
