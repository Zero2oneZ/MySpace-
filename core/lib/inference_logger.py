#!/usr/bin/env python3
# ============================================================================
# AGENT CARD                                                                  =
# ----------------------------------------------------------------------------=
# name:        inference_logger                                               =
# role:        SUBSTRATE · CRYSTAL_CHAIN                                      =
# tier:        L0                                                             =
# substrate:   crystal_chain (the canonical inference audit trail)            =
# engine:      append-only JSONL, blake3-chained; walked by CrystalChainCursor=
# storage:     ~/.cc/inference_master_chain.jsonl                             =
#              ~/.cc/inference_logs/session_<id>.jsonl                        =
#              ~/.cc/inference_semantic_index.json                            =
# card:        studio/assets/_agents/agent_defs/                              =
#              vm_mspc_001.agents.agent_defs.inference_logger.active.json     =
# ----------------------------------------------------------------------------=
# ROUTING CONNECTIONS                                                         =
# ----------------------------------------------------------------------------=
# inbound:                                                                    =
#   - chat.py::_log_inference        (cmd_full + cmd_godot end-of-pipeline)   =
#   - moe_router.CrystalChainCursor  (read-only walk)                         =
#   - cc inference-chain / verify / search / get  (CLI in core/cc.sh)         =
# outbound:                                                                   =
#   - blake3 (or blake2b fallback) for crystal hash                           =
# substrate touch:                                                            =
#   - reads:  self (replay for verify_chain + get_record + get_chain)         =
#   - writes: master chain JSONL + per-session log + semantic index           =
# ============================================================================
"""inference_logger.py — append-only inference audit trail with crystal hashing.

Every model call writes one JSONL row containing:
  - input prompt (original + enhanced)
  - model output text
  - chain context (file/folder/action/step coordinates)
  - route metadata (tier, model, scope, tokens)
  - timestamp, agent_uuid, correlation_id

Each row is BLAKE3 hashed → crystal_id. Crystal IDs chain into an ordered
master chain (chain of chains) that is the build-order log.

The JSONL is append-only, tamper-evident, and searchable by semantic index.

Determinism: same input + same chain → same crystal hash, byte for byte.
"""
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, List, Dict, Any

CC_HOME = Path(os.environ.get("CC_HOME", str(Path.home() / ".cc")))
INFERENCE_LOG_DIR = CC_HOME / "inference_logs"
MASTER_CHAIN_PATH = CC_HOME / "inference_master_chain.jsonl"
SEMANTIC_INDEX_PATH = CC_HOME / "inference_semantic_index.json"

# Try blake3; fall back to hashlib.blake2b
try:
    import blake3
    _HAS_BLAKE3 = True
except Exception:
    _HAS_BLAKE3 = False


def crystal_hash(data: bytes) -> str:
    """Deterministic BLAKE3 (or blake2b fallback) hash."""
    if _HAS_BLAKE3:
        return blake3.blake3(data).hexdigest()
    return hashlib.blake2b(data).hexdigest()


@dataclass
class InferenceRecord:
    """One inference call — everything needed to reproduce or audit."""
    crystal_id: str = ""           # blake3 hash of canonical JSON (set after construction)
    prev_crystal: str = ""         # hash of previous record in chain
    master_index: int = 0          # position in master chain

    # Identity
    agent_uuid: str = ""
    correlation_id: str = ""      # joint ID when both halves involved
    session_id: str = ""           # cc chat session

    # Timing
    timestamp: str = ""
    latency_ms: int = 0

    # Input
    original_prompt: str = ""
    enhanced_prompt: str = ""
    chain_context: str = ""        # rendered chain prompt

    # Route
    tier: str = ""
    model: str = ""
    scope: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    complexity: float = 0.0

    # Output
    output_text: str = ""
    done_flag: bool = False        # did model signal DONE?
    rc: int = 0                    # 0=ok, 1=fail, 2=partial

    # Reasoning + forward chain (the MoE-by-retrieval substrate)
    reasoning_trace: str = ""           # scraped CoT / tool sequence / intermediate text
    forward_chain_inline: str = ""      # extracted from <forward>...</forward> in output
    forward_chain_posthoc: str = ""     # tiny-model extrapolation when inline missing
    forward_source: str = "none"        # "inline" | "posthoc" | "both" | "none"

    # Tri-modal embedding (4D adjacent-possible substrate — added 2026-05-28)
    # All three default to empty so old chain still verifies. New records auto-populate.
    wave_emb: List[float] = None         # 64-dim DCT-II spectrum, L2-normalized
    time_vec: Dict[str, Any] = None      # forward + inverted positional encoding
    tri_modal_crystal: str = ""          # BLAKE3 over (vec || wave || time) canonical

    # Chain coordinates (exact file/folder/action/step)
    coordinates: List[Dict[str, Any]] = None

    # Source reference
    source_file: str = ""          # which file triggered this inference
    source_folder: str = ""
    source_action: str = ""
    source_step: int = 0

    def __post_init__(self):
        if self.coordinates is None:
            self.coordinates = []
        if self.wave_emb is None:
            self.wave_emb = []
        if self.time_vec is None:
            self.time_vec = {}
        if not self.timestamp:
            self.timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def canonical_json(self) -> str:
        """Deterministic JSON string for hashing. Excludes crystal_id and prev_crystal."""
        d = asdict(self)
        # Exclude chain-linking fields from hash input
        for key in ("crystal_id", "prev_crystal", "master_index"):
            d.pop(key, None)
        # Sort keys for determinism
        return json.dumps(d, sort_keys=True, ensure_ascii=True, separators=(",", ":"))

    def compute_crystal(self, prev_crystal: str = "") -> str:
        """Compute crystal hash and set prev_crystal link."""
        self.prev_crystal = prev_crystal
        canonical = self.canonical_json()
        # Include prev_crystal in hash so chain is tamper-evident
        data = (prev_crystal + "\n" + canonical).encode("utf-8")
        self.crystal_id = crystal_hash(data)
        return self.crystal_id


class InferenceLogger:
    """Append-only inference log with crystal chaining."""

    def __init__(self, log_dir: Optional[Path] = None):
        self.log_dir = log_dir or INFERENCE_LOG_DIR
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.master_chain = MASTER_CHAIN_PATH
        self._ensure_master_chain()

    def _ensure_master_chain(self) -> None:
        if not self.master_chain.exists():
            self.master_chain.parent.mkdir(parents=True, exist_ok=True)
            # Seed with genesis entry — compute crystal like any other record
            genesis = InferenceRecord(
                prev_crystal="0" * 64,
                master_index=0,
                agent_uuid="system",
                session_id="genesis",
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                original_prompt="genesis",
                enhanced_prompt="genesis",
                output_text="genesis",
                tier="genesis",
                model="genesis",
            )
            genesis.compute_crystal("0" * 64)
            self._append_raw(genesis)

    def _last_crystal(self) -> str:
        """Read last crystal_id from master chain."""
        if not self.master_chain.exists() or self.master_chain.stat().st_size == 0:
            return "0" * 64
        with open(self.master_chain, "r", encoding="utf-8") as f:
            last_line = ""
            for line in f:
                stripped = line.strip()
                if stripped:
                    last_line = stripped
            if not last_line:
                return "0" * 64
            try:
                data = json.loads(last_line)
                return data.get("crystal_id", "0" * 64)
            except Exception:
                return "0" * 64

    def _next_master_index(self) -> int:
        """Count lines in master chain for next index."""
        if not self.master_chain.exists():
            return 1
        with open(self.master_chain, "r", encoding="utf-8") as f:
            return sum(1 for _ in f) + 1

    def _append_raw(self, record: InferenceRecord) -> None:
        """Append record to master chain JSONL. Writes FULL record dict."""
        with open(self.master_chain, "a", encoding="utf-8") as f:
            line = json.dumps(asdict(record), ensure_ascii=True, separators=(",", ":"))
            f.write(line)
            f.write("\n")

    def log(
        self,
        original_prompt: str,
        enhanced_prompt: str,
        output_text: str,
        tier: str,
        model: str,
        scope: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
        complexity: float = 0.0,
        done_flag: bool = False,
        rc: int = 0,
        coordinates: Optional[List[Dict]] = None,
        source_file: str = "",
        source_folder: str = "",
        source_action: str = "",
        source_step: int = 0,
        latency_ms: int = 0,
        reasoning_trace: str = "",
        forward_chain_inline: str = "",
        forward_chain_posthoc: str = "",
        forward_source: str = "none",
    ) -> str:
        """Log one inference call. Returns crystal_id."""
        prev = self._last_crystal()
        idx = self._next_master_index()

        record = InferenceRecord(
            agent_uuid=os.environ.get("CC_AGENT_UUID", ""),
            correlation_id=os.environ.get("CC_CORRELATION_ID", ""),
            session_id=os.environ.get("CC_SESSION_ID", ""),
            master_index=idx,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            latency_ms=latency_ms,
            original_prompt=original_prompt,
            enhanced_prompt=enhanced_prompt,
            output_text=output_text,
            tier=tier,
            model=model,
            scope=scope,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            complexity=complexity,
            done_flag=done_flag,
            rc=rc,
            coordinates=coordinates or [],
            source_file=source_file,
            source_folder=source_folder,
            source_action=source_action,
            source_step=source_step,
            reasoning_trace=reasoning_trace,
            forward_chain_inline=forward_chain_inline,
            forward_chain_posthoc=forward_chain_posthoc,
            forward_source=forward_source,
        )

        # Tri-modal crystallization — graceful if module/feature unavailable.
        # Sits BEFORE compute_crystal so the tri_modal_crystal is part of the chain hash.
        try:
            import sys as _sys
            from pathlib import Path as _P
            _lib = str(_P(__file__).parent)
            if _lib not in _sys.path:
                _sys.path.insert(0, _lib)
            from tri_modal_embedder import TriModalCrystal as _TMC
            _canonical = (original_prompt + "|" + enhanced_prompt + "|" + output_text)[:4096]
            _tmc = _TMC.of(_canonical)
            record.wave_emb = _tmc.wave_emb
            record.time_vec = _tmc.time_vec
            record.tri_modal_crystal = _tmc.crystal
        except Exception:
            pass

        record.compute_crystal(prev)

        # Append to master chain
        with open(self.master_chain, "a", encoding="utf-8") as f:
            line = json.dumps(asdict(record), ensure_ascii=True, separators=(",", ":"))
            f.write(line)
            f.write("\n")

        # Also write to per-session log for easier retrieval
        session_id = record.session_id or record.agent_uuid
        session_log = self.log_dir / f"session_{session_id}.jsonl"
        with open(session_log, "a", encoding="utf-8") as f:
            f.write(line)
            f.write("\n")

        return record.crystal_id

    def get_chain(self, limit: int = 50) -> List[Dict]:
        """Read last N entries from master chain."""
        if not self.master_chain.exists():
            return []
        with open(self.master_chain, "r", encoding="utf-8") as f:
            lines = f.readlines()
        records = []
        for line in lines[-limit:]:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:
                continue
        return records

    def get_record(self, crystal_id: str) -> Optional[Dict]:
        """Find one record by crystal_id (linear scan; small file)."""
        if not self.master_chain.exists():
            return None
        with open(self.master_chain, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if data.get("crystal_id") == crystal_id:
                        return data
                except Exception:
                    continue
        return None

    def verify_chain(self) -> bool:
        """Replay entire chain and verify every hash."""
        if not self.master_chain.exists():
            return True
        prev_crystal = "0" * 64
        with open(self.master_chain, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except Exception:
                    return False
                cid = data.get("crystal_id", "")
                p_cid = data.get("prev_crystal", "")
                if p_cid != prev_crystal:
                    print(f"CHAIN BROKEN at {cid}: prev mismatch {p_cid} != {prev_crystal}", file=sys.stderr)
                    return False
                # Recompute hash
                d = dict(data)
                for key in ("crystal_id", "prev_crystal", "master_index"):
                    d.pop(key, None)
                canonical = json.dumps(d, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
                check_data = (prev_crystal + "\n" + canonical).encode("utf-8")
                check_hash = crystal_hash(check_data)
                if check_hash != cid:
                    print(f"CHAIN BROKEN at {cid}: hash mismatch {check_hash} != {cid}", file=sys.stderr)
                    return False
                prev_crystal = cid
        print(f"CHAIN OK — {prev_crystal} verified", file=sys.stderr)
        return True


# ---------------------------------------------------------------------------
# Semantic Index — keyword search over inference logs
# ---------------------------------------------------------------------------
class SemanticIndex:
    """Lightweight semantic index over inference logs.
    Maps keywords → list of crystal_ids. Updated incrementally."""

    def __init__(self, index_path: Optional[Path] = None):
        self.index_path = index_path or SEMANTIC_INDEX_PATH
        self.index: Dict[str, List[str]] = {}
        self._load()

    def _load(self) -> None:
        if self.index_path.exists():
            try:
                self.index = json.loads(self.index_path.read_text())
            except Exception:
                self.index = {}

    def save(self) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(
            json.dumps(self.index, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def index_record(self, record: Dict) -> None:
        """Extract keywords from a record and add to index."""
        crystal_id = record.get("crystal_id", "")
        if not crystal_id:
            return

        text = " ".join([
            record.get("original_prompt", ""),
            record.get("enhanced_prompt", ""),
            record.get("output_text", ""),
            record.get("reasoning_trace", ""),
            record.get("forward_chain_inline", ""),
            record.get("forward_chain_posthoc", ""),
            record.get("tier", ""),
            record.get("model", ""),
            record.get("scope", ""),
            record.get("source_file", ""),
            record.get("source_folder", ""),
            record.get("source_action", ""),
        ])

        # Simple keyword extraction
        words = set(w.lower() for w in text.split() if len(w) > 2 and w.isalnum())
        for word in words:
            self.index.setdefault(word, [])
            if crystal_id not in self.index[word]:
                self.index[word].append(crystal_id)

    def search(self, query: str, top_n: int = 10) -> List[str]:
        """Search index for crystal_ids matching query keywords."""
        words = [w.lower() for w in query.split() if len(w) > 2 and w.isalnum()]
        if not words:
            return []

        scores: Dict[str, int] = {}
        for word in words:
            for cid in self.index.get(word, []):
                scores[cid] = scores.get(cid, 0) + 1

        # Sort by score DESC, then by recency (crystal_id is hash, not timestamp — approximate by assuming later entries are later in file)
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [cid for cid, _ in ranked[:top_n]]


def main():
    import argparse
    ap = argparse.ArgumentParser(description="inference logger — crystal-chained audit trail")
    sub = ap.add_subparsers(dest="cmd")

    p_log = sub.add_parser("log", help="log one inference call")
    p_log.add_argument("--original", required=True)
    p_log.add_argument("--enhanced", required=True)
    p_log.add_argument("--output", required=True)
    p_log.add_argument("--tier", required=True)
    p_log.add_argument("--model", required=True)
    p_log.add_argument("--scope", default="narrow")
    p_log.add_argument("--tokens-in", type=int, default=0)
    p_log.add_argument("--tokens-out", type=int, default=0)
    p_log.add_argument("--complexity", type=float, default=0.0)
    p_log.add_argument("--rc", type=int, default=0)
    p_log.add_argument("--source-file", default="")
    p_log.add_argument("--source-folder", default="")
    p_log.add_argument("--source-action", default="")
    p_log.add_argument("--source-step", type=int, default=0)

    p_chain = sub.add_parser("chain", help="show last N chain entries")
    p_chain.add_argument("-n", type=int, default=10)

    p_verify = sub.add_parser("verify", help="verify chain integrity")

    p_search = sub.add_parser("search", help="semantic search over logs")
    p_search.add_argument("query", nargs="?")
    p_search.add_argument("-n", type=int, default=10)

    p_get = sub.add_parser("get", help="get record by crystal_id")
    p_get.add_argument("crystal_id")

    args = ap.parse_args()
    logger = InferenceLogger()
    idx = SemanticIndex()

    if args.cmd == "log":
        crystal = logger.log(
            original_prompt=args.original,
            enhanced_prompt=args.enhanced,
            output_text=args.output,
            tier=args.tier,
            model=args.model,
            scope=args.scope,
            tokens_in=args.tokens_in,
            tokens_out=args.tokens_out,
            complexity=args.complexity,
            rc=args.rc,
            source_file=args.source_file,
            source_folder=args.source_folder,
            source_action=args.source_action,
            source_step=args.source_step,
        )
        # Also index it
        record = logger.get_record(crystal)
        if record:
            idx.index_record(record)
            idx.save()
        print(json.dumps({"crystal_id": crystal, "status": "logged"}, indent=2))

    elif args.cmd == "chain":
        print(json.dumps(logger.get_chain(args.n), indent=2))

    elif args.cmd == "verify":
        ok = logger.verify_chain()
        print(json.dumps({"verified": ok}, indent=2))

    elif args.cmd == "search":
        results = idx.search(args.query or sys.stdin.read(), args.n)
        out = []
        for cid in results:
            rec = logger.get_record(cid)
            if rec:
                out.append({
                    "crystal_id": cid,
                    "tier": rec.get("tier"),
                    "model": rec.get("model"),
                    "snippet": rec.get("output_text", "")[:200],
                })
        print(json.dumps(out, indent=2))

    elif args.cmd == "get":
        rec = logger.get_record(args.crystal_id)
        if rec:
            print(json.dumps(rec, indent=2))
        else:
            print(json.dumps({"error": "not found"}, indent=2))
            sys.exit(1)

    else:
        ap.print_help()


if __name__ == "__main__":
    main()
