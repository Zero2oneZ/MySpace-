#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        gpu_scheduler
# role:        SCHEDULER · VRAM_AWARE_GPU_SLOTS
# tier:        L0
# substrate:   in-memory reservation table (verifies with nvidia-smi)
# engine:      first-fit decreasing — pick least-loaded GPU with enough free VRAM
# storage:     none (state is in-memory; queries nvidia-smi on demand)
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.gpu_scheduler.active.json
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - task_queue.TaskQueue (GPU pool reservation calls)
#   - workflow_generator (per-pass vram_gb checks)
# outbound:
#   - subprocess nvidia-smi --query-gpu=memory.free --format=csv
# substrate touch:
#   - reads:  nvidia-smi output (verification only)
#   - writes: none
# ============================================================================
"""gpu_scheduler.py — VRAM-aware slot allocator across multiple GPUs.

Reserves VRAM slots without actually running anything on the GPU. The caller
holds the reservation token while their job runs, then calls release().

Verification: every minute (configurable), the scheduler queries nvidia-smi
and reconciles its in-memory reservations against actual GPU state. Drift
emits a warning but does not invalidate ongoing reservations.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from threading import Lock
from typing import Dict, List, Optional


# Default profile: 2 × RTX 3090 Ti at 24 GB each.
DEFAULT_GPU_PROFILE = [
    {"id": 0, "name": "RTX 3090 Ti", "total_vram_gb": 24.0},
    {"id": 1, "name": "RTX 3090 Ti", "total_vram_gb": 24.0},
]


@dataclass
class GPUReservation:
    rid: str
    device_id: int
    vram_gb: float
    task_id: str
    taken_at: float
    label: str = ""

    def cuda_env(self) -> Dict[str, str]:
        """Env mapping that pins a subprocess to this reservation's GPU.

        Merge into the child's environment so it only sees the assigned device:
            subprocess.Popen(argv, env={**os.environ, **res.cuda_env()})
        """
        return {"CUDA_VISIBLE_DEVICES": str(self.device_id)}


@dataclass
class GPUDevice:
    id: int
    name: str
    total_vram_gb: float
    reserved_vram_gb: float = 0.0
    reservations: Dict[str, GPUReservation] = field(default_factory=dict)

    def free_vram_gb(self) -> float:
        return max(0.0, self.total_vram_gb - self.reserved_vram_gb)

    def utilization(self) -> float:
        return self.reserved_vram_gb / self.total_vram_gb if self.total_vram_gb else 0.0


class GPUScheduler:
    """First-fit decreasing across GPU devices. Thread-safe."""

    def __init__(self, profile: Optional[List[Dict]] = None):
        profile = profile or DEFAULT_GPU_PROFILE
        self.devices: Dict[int, GPUDevice] = {
            d["id"]: GPUDevice(id=d["id"], name=d["name"], total_vram_gb=d["total_vram_gb"])
            for d in profile
        }
        self._lock = Lock()
        self._last_smi_check = 0.0

    # ---- reservation API -----------------------------------------------

    def try_reserve(self, vram_gb: float, task_id: str = "", label: str = "",
                    chrome_aware: bool = True) -> Optional[GPUReservation]:
        """Reserve vram_gb on the least-loaded GPU that can fit it. None if no slot.

        chrome_aware=True (default) consults nvidia-smi for actual free VRAM and
        uses min(reservation_free, smi_free) — accounts for Chrome's GPU process
        and any other untracked VRAM consumer."""
        with self._lock:
            if chrome_aware:
                free_by_dev = self._effective_free_vram_per_device()
            else:
                free_by_dev = {d.id: d.free_vram_gb() for d in self.devices.values()}

            candidates = sorted(
                (d for d in self.devices.values() if free_by_dev.get(d.id, 0.0) >= vram_gb),
                key=lambda d: -free_by_dev.get(d.id, 0.0),
            )
            if not candidates:
                return None
            dev = candidates[0]
            rid = uuid.uuid4().hex[:12]
            res = GPUReservation(
                rid=rid,
                device_id=dev.id,
                vram_gb=vram_gb,
                task_id=task_id or rid,
                taken_at=time.time(),
                label=label,
            )
            dev.reserved_vram_gb += vram_gb
            dev.reservations[rid] = res
            return res

    def reserve_with_env(self, vram_gb: float, task_id: str = "", label: str = "",
                         chrome_aware: bool = True):
        """try_reserve + the CUDA_VISIBLE_DEVICES env to pin a subprocess.

        Returns (reservation, env_dict) or (None, {}) if no slot. Callers that
        previously hardcoded `CUDA_VISIBLE_DEVICES=1` (ComfyUI/Hunyuan/local
        inference) should use this so both 3090 Tis are used by the least-loaded
        policy instead of always GPU 1."""
        res = self.try_reserve(vram_gb, task_id=task_id, label=label,
                               chrome_aware=chrome_aware)
        return (res, res.cuda_env()) if res else (None, {})

    def live_status(self) -> Dict:
        """status() augmented with the actual nvidia-smi snapshot per device, so
        `cc gpu-status` reflects BOTH GPUs' real used/free, not just reservations."""
        base = self.status()
        smi = self._smi_snapshot()
        for dev in base["devices"]:
            entry = (smi or {}).get(dev["id"])
            if entry:
                dev["smi_used_gb"] = round(entry["used_mb"] / 1024.0, 2)
                dev["smi_free_gb"] = round(max(0.0, dev["total_vram_gb"] - entry["used_mb"] / 1024.0), 2)
            else:
                dev["smi_used_gb"] = None
                dev["smi_free_gb"] = None
        base["nvidia_smi"] = "available" if smi is not None else "unavailable"
        return base

    def _effective_free_vram_per_device(self) -> Dict[int, float]:
        """min(reservation_free, actual_free_via_smi). Chrome-aware."""
        result = {}
        smi = self._smi_snapshot()
        for d in self.devices.values():
            reservation_free = d.free_vram_gb()
            if smi is None:
                result[d.id] = reservation_free
                continue
            entry = smi.get(d.id)
            if entry is None:
                result[d.id] = reservation_free
                continue
            actual_used_gb = entry["used_mb"] / 1024.0
            actual_free_gb = max(0.0, d.total_vram_gb - actual_used_gb)
            result[d.id] = min(reservation_free, actual_free_gb)
        return result

    def _smi_snapshot(self) -> Optional[Dict[int, Dict[str, float]]]:
        """Cached 5-second nvidia-smi snapshot."""
        now = time.time()
        if now - self._last_smi_check < 5.0 and hasattr(self, "_smi_cache"):
            return self._smi_cache
        try:
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=index,memory.used,memory.total", "--format=csv,noheader,nounits"],
                stderr=subprocess.DEVNULL, timeout=3,
            ).decode("utf-8")
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            self._smi_cache = None
            self._last_smi_check = now
            return None
        snap = {}
        for line in out.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3:
                try:
                    snap[int(parts[0])] = {"used_mb": float(parts[1]), "total_mb": float(parts[2])}
                except ValueError:
                    continue
        self._smi_cache = snap
        self._last_smi_check = now
        return snap

    def release(self, reservation: GPUReservation) -> None:
        with self._lock:
            dev = self.devices.get(reservation.device_id)
            if not dev:
                return
            existing = dev.reservations.pop(reservation.rid, None)
            if existing is None:
                return
            dev.reserved_vram_gb = max(0.0, dev.reserved_vram_gb - existing.vram_gb)

    # ---- introspection -------------------------------------------------

    def status(self) -> Dict:
        with self._lock:
            return {
                "devices": [
                    {
                        "id": d.id,
                        "name": d.name,
                        "total_vram_gb": d.total_vram_gb,
                        "reserved_vram_gb": round(d.reserved_vram_gb, 2),
                        "free_vram_gb": round(d.free_vram_gb(), 2),
                        "utilization": round(d.utilization(), 3),
                        "active_reservations": len(d.reservations),
                    }
                    for d in self.devices.values()
                ],
                "total_free_vram_gb": round(sum(d.free_vram_gb() for d in self.devices.values()), 2),
                "total_reserved_vram_gb": round(sum(d.reserved_vram_gb for d in self.devices.values()), 2),
            }

    # ---- nvidia-smi reconciliation -------------------------------------

    def verify_with_nvidia_smi(self) -> Optional[Dict]:
        """Query nvidia-smi and report actual vs. reserved VRAM. Returns None if smi unavailable."""
        try:
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=index,memory.used,memory.total", "--format=csv,noheader,nounits"],
                stderr=subprocess.DEVNULL,
                timeout=5,
            ).decode("utf-8")
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return None

        actual = {}
        for line in out.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3:
                try:
                    idx = int(parts[0])
                    used_mb = float(parts[1])
                    total_mb = float(parts[2])
                    actual[idx] = {"used_mb": used_mb, "total_mb": total_mb}
                except ValueError:
                    continue

        report = []
        with self._lock:
            for d in self.devices.values():
                a = actual.get(d.id)
                if a is None:
                    continue
                actual_used_gb = a["used_mb"] / 1024
                drift_gb = actual_used_gb - d.reserved_vram_gb
                report.append({
                    "device_id": d.id,
                    "reserved_gb": round(d.reserved_vram_gb, 2),
                    "actual_used_gb": round(actual_used_gb, 2),
                    "drift_gb": round(drift_gb, 2),
                })
        return {"per_device": report, "ts": time.time()}


def _main():
    import argparse, sys
    ap = argparse.ArgumentParser(description="gpu_scheduler — VRAM-aware slot allocator")
    sub = ap.add_subparsers(dest="cmd")

    p_status = sub.add_parser("status")
    p_status.add_argument("--live", action="store_true",
                          help="include nvidia-smi used/free per device")
    p_smi = sub.add_parser("verify")

    p_reserve = sub.add_parser("reserve")
    p_reserve.add_argument("vram_gb", type=float)
    p_reserve.add_argument("--label", default="")

    args = ap.parse_args()
    sched = GPUScheduler()

    if args.cmd == "status":
        print(json.dumps(sched.live_status() if getattr(args, "live", False)
                         else sched.status(), indent=2))
    elif args.cmd == "verify":
        rep = sched.verify_with_nvidia_smi()
        if rep is None:
            print(json.dumps({"error": "nvidia-smi not available"}), file=sys.stderr)
            sys.exit(1)
        print(json.dumps(rep, indent=2))
    elif args.cmd == "reserve":
        res = sched.try_reserve(args.vram_gb, label=args.label)
        if res is None:
            print(json.dumps({"error": "no slot available"}))
            sys.exit(1)
        print(json.dumps({"rid": res.rid, "device_id": res.device_id, "vram_gb": res.vram_gb}, indent=2))
    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
