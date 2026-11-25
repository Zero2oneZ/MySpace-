#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        task_queue
# role:        QUEUE · ASYNC_TASK_DISPATCH
# tier:        L0
# substrate:   in-memory asyncio queues + result_cache + gpu_scheduler
# engine:      asyncio; 4 pools (GPU, OLLAMA, CLOUD, DETERMINISTIC); gap-fill
# storage:     none directly (cache + crystal_log are independent)
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.task_queue.active.json
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - chat.py::cmd_full  (every chat turn that needs LLM compute)
#   - workflow_generator (per-pass dispatch when emitting --target *)
#   - forward_projector (posthoc projection jobs)
#   - core/cc.sh::cmd_queue (CLI submit/status/drain/watch)
# outbound:
#   - gpu_scheduler.try_reserve / release (GPU pool)
#   - subprocess ollama run (OLLAMA pool, max 5 concurrent)
#   - HTTP to anthropic / openai / gemini (CLOUD pool, rate-limited)
#   - result_cache.get / put (cache lookups + writes)
#   - inference_logger.log (crystal chain append per job)
# substrate touch:
#   - reads:  result_cache (lookup), gpu_scheduler (reserve)
#   - writes: result_cache (store), inference_logger (log)
# gap-fill principle:
#   - DETERMINISTIC pool runs whenever LLM pool utilization < 0.8
#   - keeps the system saturated: scans/hashes/walks fill idle slots
# ============================================================================
"""task_queue.py — async dispatcher across GPU, Ollama, Cloud, and deterministic pools.

Submission API:
    q = TaskQueue()
    asyncio.run(q.start())   # in background
    result = await q.submit(Task(kind=TaskKind.OLLAMA, agent="qwen2.5-coder:1.5b",
                                  prompt="...", input_crystal="..."))

Cache hits short-circuit dispatch. Misses route by kind to the appropriate pool,
which is bounded (Ollama=5, Cloud=rate-limited, GPU=VRAM-bounded). The
DETERMINISTIC pool is unbounded but only drains when LLM pools have headroom.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Awaitable

# Ensure sibling imports work when run as script
_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from gpu_scheduler import GPUScheduler, GPUReservation
from result_cache import ResultCache, compute_key
try:
    from inference_logger import InferenceLogger
    _HAS_LOGGER = True
except Exception:
    _HAS_LOGGER = False


# ---- defaults --------------------------------------------------------------

OLLAMA_POOL_SIZE = int(os.environ.get("CC_OLLAMA_POOL", "5"))
CLOUD_RATE_PER_MIN = {
    "claude":  int(os.environ.get("CC_CLOUD_RATE_CLAUDE", "30")),
    "openai":  int(os.environ.get("CC_CLOUD_RATE_OPENAI", "60")),
    "gemini":  int(os.environ.get("CC_CLOUD_RATE_GEMINI", "60")),
    "default": int(os.environ.get("CC_CLOUD_RATE_DEFAULT", "30")),
}
OLLAMA_TIMEOUT_S = int(os.environ.get("CC_OLLAMA_TIMEOUT", "60"))
GAP_FILL_THRESHOLD = float(os.environ.get("CC_GAP_FILL_THRESHOLD", "0.8"))


class TaskKind(str, Enum):
    GPU = "gpu"
    OLLAMA = "ollama"
    CLOUD = "cloud"
    DETERMINISTIC = "deterministic"


@dataclass
class Task:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    kind: TaskKind = TaskKind.DETERMINISTIC
    agent: str = ""              # model id or function name
    prompt: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    input_crystal: str = ""      # link to prior crystal in chain
    vram_gb: float = 0.0          # for GPU kind
    cloud_provider: str = ""      # claude | openai | gemini | ...
    fn: Optional[Callable[[], Awaitable[Any]]] = None   # for DETERMINISTIC
    priority: int = 0             # higher = sooner
    submitted_at: float = field(default_factory=time.time)
    label: str = ""


@dataclass
class TaskResult:
    task_id: str
    output: Any
    cache_key: str
    source: str                  # "cache_mem" | "cache_disk" | "computed_<kind>"
    latency_ms: int
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Rate limiter (token-bucket per provider)
# ---------------------------------------------------------------------------
class _RateLimiter:
    def __init__(self, per_minute: int):
        self.per_minute = max(1, per_minute)
        self.tokens = float(self.per_minute)
        self.last_refill = time.time()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.time()
            elapsed = now - self.last_refill
            refill = elapsed * (self.per_minute / 60.0)
            self.tokens = min(self.per_minute, self.tokens + refill)
            self.last_refill = now
            if self.tokens >= 1:
                self.tokens -= 1
                return
            need = 1 - self.tokens
            wait_s = need * (60.0 / self.per_minute)
        await asyncio.sleep(wait_s)
        # try again
        await self.acquire()


# ---------------------------------------------------------------------------
# TaskQueue
# ---------------------------------------------------------------------------
class TaskQueue:
    def __init__(
        self,
        ollama_pool_size: int = OLLAMA_POOL_SIZE,
        cloud_rates: Optional[Dict[str, int]] = None,
        cache: Optional[ResultCache] = None,
        gpu: Optional[GPUScheduler] = None,
    ):
        self.cache = cache or ResultCache()
        self.gpu = gpu or GPUScheduler()
        self._ollama_sema = asyncio.Semaphore(ollama_pool_size)
        rates = cloud_rates or CLOUD_RATE_PER_MIN
        self._cloud_limiters = {k: _RateLimiter(v) for k, v in rates.items()}
        self._det_queue: "asyncio.Queue[Task]" = asyncio.Queue()
        self._stats = {
            "submitted": 0,
            "cache_hits": 0,
            "computed_ollama": 0,
            "computed_cloud": 0,
            "computed_gpu": 0,
            "computed_deterministic": 0,
            "errors": 0,
        }
        self._ollama_inflight = 0
        self._cloud_inflight = 0
        self._gap_fill_task: Optional[asyncio.Task] = None
        if _HAS_LOGGER:
            try:
                self._crystal_logger = InferenceLogger()
            except Exception:
                self._crystal_logger = None
        else:
            self._crystal_logger = None

    # ---- lifecycle -----------------------------------------------------

    async def start(self) -> None:
        if self._gap_fill_task is None or self._gap_fill_task.done():
            self._gap_fill_task = asyncio.create_task(self._gap_fill_loop())

    async def stop(self) -> None:
        if self._gap_fill_task and not self._gap_fill_task.done():
            self._gap_fill_task.cancel()
            try:
                await self._gap_fill_task
            except asyncio.CancelledError:
                pass

    # ---- submission ----------------------------------------------------

    async def submit(self, task: Task) -> TaskResult:
        self._stats["submitted"] += 1
        cache_key = compute_key(task.agent, task.prompt, task.params, task.input_crystal)

        # Cache hit short-circuit (skip deterministic tasks; they're cheap and may have side effects)
        if task.kind != TaskKind.DETERMINISTIC:
            cached = self.cache.get(cache_key)
            if cached is not None:
                self._stats["cache_hits"] += 1
                return TaskResult(
                    task_id=task.id,
                    output=cached["result"],
                    cache_key=cache_key,
                    source=f"cache_{cached.get('source','disk')}",
                    latency_ms=0,
                )

        t0 = time.time()
        try:
            if task.kind == TaskKind.OLLAMA:
                output = await self._run_ollama(task)
                self._stats["computed_ollama"] += 1
                src = "computed_ollama"
            elif task.kind == TaskKind.CLOUD:
                output = await self._run_cloud(task)
                self._stats["computed_cloud"] += 1
                src = "computed_cloud"
            elif task.kind == TaskKind.GPU:
                output = await self._run_gpu(task)
                self._stats["computed_gpu"] += 1
                src = "computed_gpu"
            elif task.kind == TaskKind.DETERMINISTIC:
                output = await self._run_deterministic(task)
                self._stats["computed_deterministic"] += 1
                src = "computed_deterministic"
            else:
                raise ValueError(f"unknown task kind: {task.kind!r}")
        except Exception as e:
            self._stats["errors"] += 1
            return TaskResult(
                task_id=task.id,
                output=None,
                cache_key=cache_key,
                source="error",
                latency_ms=int((time.time() - t0) * 1000),
                error=str(e),
            )

        latency_ms = int((time.time() - t0) * 1000)

        # Cache + log
        if task.kind != TaskKind.DETERMINISTIC:
            self.cache.put(cache_key, output, model_id=task.agent, source=src)

        self._log_crystal(task, output, src, latency_ms)

        return TaskResult(
            task_id=task.id,
            output=output,
            cache_key=cache_key,
            source=src,
            latency_ms=latency_ms,
        )

    async def enqueue_deterministic(self, task: Task) -> None:
        """Queue a deterministic task to run during LLM-pool gaps."""
        task.kind = TaskKind.DETERMINISTIC
        await self._det_queue.put(task)

    # ---- pool runners --------------------------------------------------

    async def _run_ollama(self, task: Task) -> str:
        if not shutil.which("ollama"):
            raise RuntimeError("ollama binary not in PATH")
        async with self._ollama_sema:
            self._ollama_inflight += 1
            try:
                proc = await asyncio.create_subprocess_exec(
                    "ollama", "run", task.agent,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env={**os.environ, "OLLAMA_NO_ANIMATION": "1", "TERM": "dumb"},
                )
                try:
                    out_bytes, _err = await asyncio.wait_for(
                        proc.communicate(input=task.prompt.encode("utf-8")),
                        timeout=task.params.get("timeout", OLLAMA_TIMEOUT_S),
                    )
                except asyncio.TimeoutError:
                    proc.kill()
                    raise RuntimeError(f"ollama timeout on {task.agent}")
                return out_bytes.decode("utf-8", errors="replace")
            finally:
                self._ollama_inflight -= 1

    async def _run_cloud(self, task: Task) -> str:
        provider = task.cloud_provider or "default"
        limiter = self._cloud_limiters.get(provider, self._cloud_limiters["default"])
        await limiter.acquire()
        self._cloud_inflight += 1
        try:
            # NOTE: This module does not implement the cloud HTTP calls itself —
            # higher layers (chat.py / workflow_generator) provide a fn in task.params['fn'].
            fn = task.params.get("fn")
            if fn is None:
                raise RuntimeError("CLOUD task requires task.params['fn'] (async callable)")
            return await fn()
        finally:
            self._cloud_inflight -= 1

    async def _run_gpu(self, task: Task) -> Any:
        res: Optional[GPUReservation] = None
        # Try to reserve; if no slot, wait briefly and retry up to N times.
        for _ in range(20):
            res = self.gpu.try_reserve(task.vram_gb, task_id=task.id, label=task.label)
            if res is not None:
                break
            await asyncio.sleep(0.5)
        if res is None:
            raise RuntimeError(f"no GPU slot for {task.vram_gb} GB")
        try:
            fn = task.params.get("fn")
            if fn is None:
                raise RuntimeError("GPU task requires task.params['fn'] (async callable)")
            return await fn()
        finally:
            self.gpu.release(res)

    async def _run_deterministic(self, task: Task) -> Any:
        fn = task.fn or task.params.get("fn")
        if fn is None:
            raise RuntimeError("DETERMINISTIC task requires task.fn")
        if asyncio.iscoroutinefunction(fn):
            return await fn()
        return fn()

    # ---- gap-fill loop -------------------------------------------------

    async def _gap_fill_loop(self) -> None:
        """Drain deterministic queue when LLM pools have headroom."""
        while True:
            try:
                util_ollama = self._ollama_inflight / max(1, OLLAMA_POOL_SIZE)
                if util_ollama < GAP_FILL_THRESHOLD and not self._det_queue.empty():
                    task = await self._det_queue.get()
                    # fire-and-forget the deterministic task
                    asyncio.create_task(self.submit(task))
                await asyncio.sleep(0.2)
            except asyncio.CancelledError:
                return
            except Exception:
                # never let gap-fill take down the queue
                await asyncio.sleep(1.0)

    # ---- introspection -------------------------------------------------

    def status(self) -> Dict:
        return {
            "stats": dict(self._stats),
            "ollama_inflight": self._ollama_inflight,
            "cloud_inflight": self._cloud_inflight,
            "deterministic_queued": self._det_queue.qsize(),
            "ollama_pool_size": OLLAMA_POOL_SIZE,
            "gpu": self.gpu.status(),
            "cache": self.cache.stats(),
        }

    # ---- crystal logging -----------------------------------------------

    def _log_crystal(self, task: Task, output: Any, source: str, latency_ms: int) -> None:
        if self._crystal_logger is None:
            return
        try:
            self._crystal_logger.log(
                original_prompt=task.prompt[:8192],
                enhanced_prompt=task.prompt[:8192],
                output_text=(output if isinstance(output, str) else json.dumps(output, default=str))[:32768],
                tier="queue",
                model=task.agent,
                scope=source,
                tokens_in=len(task.prompt),
                latency_ms=latency_ms,
                rc=0,
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

def _main():
    import argparse
    ap = argparse.ArgumentParser(description="task_queue — async dispatch CLI")
    sub = ap.add_subparsers(dest="cmd")

    p_status = sub.add_parser("status")

    p_ollama = sub.add_parser("ollama", help="dispatch a single ollama task")
    p_ollama.add_argument("--agent", required=True)
    p_ollama.add_argument("--prompt", required=True)

    p_det = sub.add_parser("deterministic", help="run a deterministic sleeping task (smoke)")
    p_det.add_argument("--seconds", type=float, default=0.5)

    args = ap.parse_args()
    q = TaskQueue()

    async def run():
        await q.start()
        try:
            if args.cmd == "status":
                print(json.dumps(q.status(), indent=2))
            elif args.cmd == "ollama":
                t = Task(kind=TaskKind.OLLAMA, agent=args.agent, prompt=args.prompt)
                r = await q.submit(t)
                print(json.dumps({
                    "source": r.source, "latency_ms": r.latency_ms,
                    "cache_key": r.cache_key[:16],
                    "output_snippet": (r.output or "")[:240] if isinstance(r.output, str) else str(r.output)[:240],
                    "error": r.error,
                }, indent=2))
            elif args.cmd == "deterministic":
                async def sleep_fn():
                    await asyncio.sleep(args.seconds)
                    return f"slept {args.seconds}s"
                t = Task(kind=TaskKind.DETERMINISTIC, fn=sleep_fn, label="smoke")
                r = await q.submit(t)
                print(json.dumps({"source": r.source, "latency_ms": r.latency_ms,
                                  "output": r.output}, indent=2))
            else:
                ap.print_help()
        finally:
            await q.stop()

    asyncio.run(run())


if __name__ == "__main__":
    _main()
