#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        result_cache
# role:        CACHE · CONTENT_ADDRESSED_RESULTS
# tier:        L0
# substrate:   ~/.cc/result_cache/ (disk JSONL + memory LRU)
# engine:      BLAKE3 key over (model_id + prompt + params + input_crystal)
# storage:     ~/.cc/result_cache/<crystal_prefix>/<crystal_id>.json
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.result_cache.active.json
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - task_queue.TaskQueue.submit (cache lookup before dispatch)
#   - forward_projector.project (cache posthoc projections)
#   - workflow_generator (cache emitted artifacts)
# outbound:
#   - blake3 (or blake2b fallback) for crystal hashing
#   - disk read/write to ~/.cc/result_cache/
# substrate touch:
#   - reads:  ~/.cc/result_cache/<prefix>/<id>.json
#   - writes: same
# ============================================================================
"""result_cache.py — content-addressed result cache for GPU + Ollama + Cloud calls.

Cache key = blake3(model_id + canonical_prompt + canonical_params + input_crystal).

Two tiers:
  * Memory LRU (default 100 entries, configurable) — fastest
  * Disk JSON at ~/.cc/result_cache/<first2chars>/<crystal>.json — survives restart

The same call (same model + same prompt + same params + same input) ALWAYS hits.
Cache is shared across task kinds — a Cloud Claude call and a local Ollama call
get separate keys because model_id differs.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from collections import OrderedDict
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional


CC_HOME = Path(os.environ.get("CC_HOME", str(Path.home() / ".cc")))
CACHE_DIR = CC_HOME / "result_cache"

try:
    import blake3 as _blake3_mod
    def _hash(data: bytes) -> str:
        return _blake3_mod.blake3(data).hexdigest()
except ImportError:
    def _hash(data: bytes) -> str:
        return hashlib.blake2b(data).hexdigest()


def compute_key(model_id: str, prompt: str, params: Optional[Dict] = None,
                input_crystal: str = "") -> str:
    """Deterministic BLAKE3 cache key."""
    params_canonical = json.dumps(params or {}, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    payload = "|".join([model_id, prompt, params_canonical, input_crystal])
    return _hash(payload.encode("utf-8"))


class ResultCache:
    """Memory + disk content-addressed cache."""

    def __init__(self, mem_capacity: int = 100, disk_root: Optional[Path] = None,
                 ttl_seconds: Optional[int] = None):
        self.mem_capacity = mem_capacity
        self.disk_root = Path(disk_root) if disk_root else CACHE_DIR
        self.disk_root.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_seconds   # None = no TTL
        self._mem: "OrderedDict[str, Dict]" = OrderedDict()
        self._lock = Lock()
        self._stats = {"hits_mem": 0, "hits_disk": 0, "misses": 0, "puts": 0, "evictions": 0}

    # ---- lookup --------------------------------------------------------

    def get(self, key: str) -> Optional[Dict]:
        with self._lock:
            # Memory tier
            if key in self._mem:
                entry = self._mem[key]
                if self._is_fresh(entry):
                    self._mem.move_to_end(key)
                    self._stats["hits_mem"] += 1
                    return entry
                # stale — evict
                self._mem.pop(key, None)

            # Disk tier
            path = self._disk_path(key)
            if path.exists():
                try:
                    entry = json.loads(path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    return None
                if not self._is_fresh(entry):
                    try:
                        path.unlink()
                    except OSError:
                        pass
                    return None
                # promote to memory
                self._mem[key] = entry
                self._mem.move_to_end(key)
                self._evict_lru_if_needed()
                self._stats["hits_disk"] += 1
                return entry

            self._stats["misses"] += 1
            return None

    # ---- write ---------------------------------------------------------

    def put(self, key: str, result: Any, model_id: str = "", source: str = "",
            ttl_seconds: Optional[int] = None) -> None:
        entry = {
            "key": key,
            "model_id": model_id,
            "source": source,
            "result": result,
            "stored_at": time.time(),
            "ttl_seconds": ttl_seconds if ttl_seconds is not None else self.ttl_seconds,
        }
        with self._lock:
            # Disk
            path = self._disk_path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(entry, ensure_ascii=True, separators=(",", ":")),
                            encoding="utf-8")
            # Memory
            self._mem[key] = entry
            self._mem.move_to_end(key)
            self._stats["puts"] += 1
            self._evict_lru_if_needed()

    # ---- stats / maintenance -------------------------------------------

    def stats(self) -> Dict:
        with self._lock:
            total_lookups = self._stats["hits_mem"] + self._stats["hits_disk"] + self._stats["misses"]
            hit_rate = (
                (self._stats["hits_mem"] + self._stats["hits_disk"]) / total_lookups
                if total_lookups else 0.0
            )
            return {
                **self._stats,
                "total_lookups": total_lookups,
                "hit_rate": round(hit_rate, 4),
                "mem_size": len(self._mem),
                "mem_capacity": self.mem_capacity,
                "disk_root": str(self.disk_root),
            }

    def clear_mem(self) -> None:
        with self._lock:
            self._mem.clear()

    # ---- internals -----------------------------------------------------

    def _disk_path(self, key: str) -> Path:
        prefix = key[:2] if len(key) >= 2 else "_"
        return self.disk_root / prefix / f"{key}.json"

    def _is_fresh(self, entry: Dict) -> bool:
        ttl = entry.get("ttl_seconds")
        if ttl is None or ttl <= 0:
            return True
        return (time.time() - entry.get("stored_at", 0)) < ttl

    def _evict_lru_if_needed(self) -> None:
        # called with lock held
        while len(self._mem) > self.mem_capacity:
            self._mem.popitem(last=False)
            self._stats["evictions"] += 1


def _main():
    import argparse, sys
    ap = argparse.ArgumentParser(description="result_cache — content-addressed cache")
    sub = ap.add_subparsers(dest="cmd")

    p_stats = sub.add_parser("stats")

    p_get = sub.add_parser("get")
    p_get.add_argument("key")

    p_put = sub.add_parser("put")
    p_put.add_argument("--model", required=True)
    p_put.add_argument("--prompt", required=True)
    p_put.add_argument("--result", required=True)

    p_key = sub.add_parser("key")
    p_key.add_argument("--model", required=True)
    p_key.add_argument("--prompt", required=True)

    args = ap.parse_args()
    cache = ResultCache()

    if args.cmd == "stats":
        print(json.dumps(cache.stats(), indent=2))
    elif args.cmd == "key":
        print(compute_key(args.model, args.prompt))
    elif args.cmd == "get":
        r = cache.get(args.key)
        if r is None:
            print(json.dumps({"hit": False}))
            sys.exit(1)
        print(json.dumps(r, indent=2))
    elif args.cmd == "put":
        k = compute_key(args.model, args.prompt)
        cache.put(k, args.result, model_id=args.model, source="cli")
        print(json.dumps({"stored": True, "key": k}))
    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
