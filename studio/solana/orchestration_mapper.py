"""orchestration_mapper.py — Map recursive smart-contract activation patterns.

Detects "serious engineer" bot infrastructure:
- Self-activating contracts (contract calls itself via CPI)
- Rotating recursive transformers (A→B→C→A cycles)
- Cross-program invocation (CPI) chains
- Deterministic instruction sequences repeating across slots
- Multidimensional grid activation (same bytecode, different accounts, same timestamp)
- Pump.fun as launchpad → connected contracts across Raydium, Jupiter, etc.

Input:  pump_feed.py JSONL (with innerInstructions + logMessages)
Output: JSONL orchestration map + SVG graph + cycle report

Usage:
    python3 orchestration_mapper.py --feed ./feed/live_features.jsonl --report ./feed/orchestration.jsonl
    cc -orchestration-map
"""
from __future__ import annotations

import argparse
import json
import math
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pump_constants import PUMP_PROGRAM_ID


@dataclass
class ContractNode:
    program_id: str
    calls: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    called_by: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    activation_times: list[float] = field(default_factory=list)
    instruction_hashes: list[str] = field(default_factory=list)
    unique_accounts: set[str] = field(default_factory=set)
    tx_count: int = 0
    self_call_count: int = 0
    depth_max: int = 0


@dataclass
class Cycle:
    nodes: list[str]
    frequency: int = 0
    first_seen: float = 0.0
    last_seen: float = 0.0
    avg_slot_delta: float = 0.0


@dataclass
class OrchestrationPattern:
    """A detected deterministic recursive pattern."""
    pattern_id: str
    root_contract: str
    chain: list[str]
    is_recursive: bool
    is_self_activating: bool
    depth: int
    frequency: int
    avg_interval_ms: float
    bot_score: float
    tags: list[str]


class OrchestrationMapper:
    """Maps the deterministic self-activating recursive contract grid."""

    def __init__(self):
        self.contracts: dict[str, ContractNode] = {}
        self.cycles: list[Cycle] = []
        self.patterns: list[OrchestrationPattern] = []
        self.signatures_seen: set[str] = set()
        self.temporal_chains: dict[str, list[dict]] = defaultdict(list)

    def ingest(self, obj: dict) -> Optional[OrchestrationPattern]:
        sig = obj.get("signature", "")
        if sig in self.signatures_seen:
            return None
        self.signatures_seen.add(sig)

        slot = obj.get("slot", 0)
        ts = obj.get("ts", 0.0)
        meta = obj.get("meta", {})
        inner_ixs = meta.get("innerInstructions", [])
        logs = meta.get("logMessages", [])
        account_keys = meta.get("accountKeys", [])

        # Build CPI call graph from inner instructions
        call_chain: list[str] = []
        for ix_group in inner_ixs:
            for ix in ix_group.get("instructions", []):
                pid = self._resolve_program_id(ix, account_keys)
                if pid and pid != "_unknown":
                    call_chain.append(pid)

        # Also extract program IDs from log messages (fallback)
        if not call_chain:
            call_chain = self._extract_from_logs(logs)

        if not call_chain:
            return None

        # Build graph edges
        for i, caller in enumerate(call_chain):
            node = self.contracts.setdefault(caller, ContractNode(program_id=caller))
            node.tx_count += 1
            node.activation_times.append(ts)
            node.unique_accounts.update(self._extract_accounts(obj))
            node.depth_max = max(node.depth_max, len(call_chain))

            if i + 1 < len(call_chain):
                callee = call_chain[i + 1]
                node.calls[callee] += 1
                callee_node = self.contracts.setdefault(callee, ContractNode(program_id=callee))
                callee_node.called_by[caller] += 1

            # Detect self-call (contract calls itself via CPI)
            if i > 0 and caller == call_chain[i - 1]:
                node.self_call_count += 1

        # Detect cycles in this call chain
        cycle = self._detect_cycle(call_chain, ts, slot)
        if cycle:
            self.cycles.append(cycle)

        # Build temporal chain keyed by root contract
        root = call_chain[0] if call_chain else ""
        self.temporal_chains[root].append({
            "sig": sig, "chain": call_chain, "ts": ts, "slot": slot,
        })
        # Trim
        if len(self.temporal_chains[root]) > 10000:
            self.temporal_chains[root] = self.temporal_chains[root][-5000:]

        # Pattern detection: deterministic recursive grid
        pattern = self._detect_pattern(root, call_chain, ts, slot)
        if pattern:
            self.patterns.append(pattern)
            return pattern
        return None

    def _resolve_program_id(self, ix: dict, account_keys: list[str]) -> str:
        """Resolve program ID from instruction using accountKeys lookup."""
        idx = ix.get("programIdIndex")
        if isinstance(idx, int) and 0 <= idx < len(account_keys):
            return account_keys[idx]
        # Fallback: try to find a base58 program ID in ix data
        data = ix.get("data", "")
        for word in data.split():
            if 32 <= len(word) <= 44 and word[0].isalnum():
                return word
        return "_unknown"

    def _extract_from_logs(self, logs: list[str]) -> list[str]:
        """Extract program IDs from log messages."""
        pids = []
        for line in logs:
            # "Program <id> invoke [N]"
            m = re.search(r"Program\s+([A-Za-z0-9]{32,44})\s+invoke", line)
            if m:
                pids.append(m.group(1))
        return pids

    def _extract_accounts(self, obj: dict) -> set[str]:
        """Extract all account keys from tx."""
        accts = set()
        tx = obj.get("transaction", {})
        msg = tx.get("message", {})
        for a in msg.get("accountKeys", []):
            if isinstance(a, str):
                accts.add(a)
            elif isinstance(a, dict):
                accts.add(a.get("pubkey", ""))
        return accts

    def _detect_cycle(self, chain: list[str], ts: float, slot: int) -> Optional[Cycle]:
        """Detect if chain contains a cycle (e.g., A→B→C→A)."""
        seen = {}
        for i, node in enumerate(chain):
            if node in seen:
                # Cycle found
                cycle_nodes = chain[seen[node]:i]
                if len(cycle_nodes) >= 2:
                    return Cycle(
                        nodes=cycle_nodes,
                        frequency=1,
                        first_seen=ts,
                        last_seen=ts,
                        avg_slot_delta=0.0,
                    )
            seen[node] = i
        return None

    def _detect_pattern(self, root: str, chain: list[str], ts: float, slot: int) -> Optional[OrchestrationPattern]:
        """Detect deterministic recursive self-activating patterns."""
        if not root or not chain:
            return None

        # Is this a recursive chain?
        is_recursive = chain[0] == chain[-1] and len(chain) > 2

        # Is there a self-activating node?
        is_self_activating = any(
            chain[i] == chain[i + 1] for i in range(len(chain) - 1)
        )

        # Depth
        depth = len(chain)

        # Frequency: how many times has this exact chain appeared?
        hist = self.temporal_chains.get(root, [])
        freq = sum(1 for h in hist if h["chain"] == chain)

        # Interval analysis
        intervals = []
        same_chain_txs = [h for h in hist if h["chain"] == chain]
        for i in range(1, len(same_chain_txs)):
            dt = same_chain_txs[i]["ts"] - same_chain_txs[i - 1]["ts"]
            intervals.append(dt)
        avg_interval = sum(intervals) / len(intervals) if intervals else 0.0

        # Bot score: higher if deterministic, recursive, fast, frequent
        score = 0.0
        if is_recursive:
            score += 0.35
        if is_self_activating:
            score += 0.25
        if freq > 5:
            score += 0.20
        if avg_interval > 0 and avg_interval < 2.0:
            score += 0.15
        if depth > 3:
            score += 0.05
        score = min(1.0, score)

        tags = []
        if is_recursive:
            tags.append("RECURSIVE_TRANSFORMER")
        if is_self_activating:
            tags.append("SELF_ACTIVATING")
        if freq > 10:
            tags.append("DETERMINISTIC_GRID")
        if avg_interval > 0 and avg_interval < 1.0:
            tags.append("HIGH_FREQUENCY")
        if depth >= 4:
            tags.append("DEEP_CHAIN")

        if score > 0.3:
            return OrchestrationPattern(
                pattern_id=f"pat_{root[:8]}_{int(ts*1000)}",
                root_contract=root,
                chain=chain,
                is_recursive=is_recursive,
                is_self_activating=is_self_activating,
                depth=depth,
                frequency=freq,
                avg_interval_ms=avg_interval * 1000,
                bot_score=score,
                tags=tags,
            )
        return None

    def summary(self) -> dict:
        total_contracts = len(self.contracts)
        self_activating = sum(1 for c in self.contracts.values() if c.self_call_count > 0)
        recursive_cycles = len([c for c in self.cycles if len(c.nodes) >= 3])
        high_freq_patterns = len([p for p in self.patterns if "HIGH_FREQUENCY" in p.tags])
        deep_chains = len([p for p in self.patterns if "DEEP_CHAIN" in p.tags])

        # Top orchestrators by tx count + self-call ratio
        top = sorted(
            [{"program_id": c.program_id,
              "tx_count": c.tx_count,
              "self_calls": c.self_call_count,
              "unique_accounts": len(c.unique_accounts),
              "calls_out": dict(c.calls)}
             for c in self.contracts.values()],
            key=lambda x: x["tx_count"] + x["self_calls"] * 10,
            reverse=True,
        )[:20]

        return {
            "ts": time.time(),
            "total_contracts": total_contracts,
            "self_activating_contracts": self_activating,
            "recursive_cycles": recursive_cycles,
            "high_freq_patterns": high_freq_patterns,
            "deep_chains": deep_chains,
            "patterns": [
                {"id": p.pattern_id, "root": p.root_contract, "chain": p.chain,
                 "recursive": p.is_recursive, "self_activating": p.is_self_activating,
                 "depth": p.depth, "freq": p.frequency,
                 "interval_ms": round(p.avg_interval_ms, 2),
                 "score": round(p.bot_score, 3), "tags": p.tags}
                for p in self.patterns
            ],
            "top_orchestrators": top,
        }


def run_mapper(feed_path: Path, report_path: Path, summary_path: Optional[Path] = None,
               max_lines: int = 0):
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if summary_path:
        summary_path.parent.mkdir(parents=True, exist_ok=True)
    if report_path.exists():
        report_path.write_text("")

    mapper = OrchestrationMapper()
    lines = 0
    found = 0

    if not feed_path.exists():
        print(f"[mapper] Feed not found: {feed_path}")
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
            pat = mapper.ingest(obj)
            lines += 1
            if pat:
                found += 1
                with open(report_path, "a") as out:
                    rec = {
                        "pattern_id": pat.pattern_id,
                        "ts": time.time(),
                        "root": pat.root_contract,
                        "chain": pat.chain,
                        "recursive": pat.is_recursive,
                        "self_activating": pat.is_self_activating,
                        "depth": pat.depth,
                        "freq": pat.frequency,
                        "interval_ms": pat.avg_interval_ms,
                        "score": pat.bot_score,
                        "tags": pat.tags,
                    }
                    out.write(json.dumps(rec, default=str) + "\n")
            if max_lines > 0 and lines >= max_lines:
                break

    summary = mapper.summary()
    print(f"[mapper] Processed {lines} txs | Patterns: {found}")
    print(f"[mapper] Contracts: {summary['total_contracts']} | "
          f"Self-activating: {summary['self_activating_contracts']} | "
          f"Recursive cycles: {summary['recursive_cycles']} | "
          f"High-freq: {summary['high_freq_patterns']} | "
          f"Deep chains: {summary['deep_chains']}")
    print(f"[mapper] Top 5 orchestrators:")
    for o in summary["top_orchestrators"][:5]:
        print(f"  {o['program_id'][:16]}... txs={o['tx_count']} self={o['self_calls']} "
              f"accounts={o['unique_accounts']} out={len(o['calls_out'])}")

    if summary_path:
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2, default=str)
        print(f"[mapper] Summary written to {summary_path}")

    return summary


def main():
    ap = argparse.ArgumentParser(description="Pump.fun orchestration pattern mapper")
    ap.add_argument("--feed", type=Path, default="./feed/live_features.jsonl")
    ap.add_argument("--report", type=Path, default="./feed/orchestration.jsonl")
    ap.add_argument("--summary", type=Path, default="./feed/orchestration_summary.json")
    ap.add_argument("--max-lines", type=int, default=0, help="0 = all")
    args = ap.parse_args()
    run_mapper(args.feed, args.report, args.summary, args.max_lines)


if __name__ == "__main__":
    main()
