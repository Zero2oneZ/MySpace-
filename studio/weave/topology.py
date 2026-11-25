"""topology.py — live device + WebGPU-adapter registry.

SQLite at studio/cache/dag/weave.sqlite. Devices register on connect,
heartbeat every N seconds, fall offline after a TTL.

A "device" is anything that can run compute: Tom's laptop (owner), the
droplet (server), a friend's laptop via SSH-tunneled wardrobe page, a
browser tab on any phone/tablet that opens webgpu_worker.html. Each
device declares 1+ WebGPU adapters (CPU fallback also accepted).

Public API:
    register_device(name, kind, owner, capabilities) → device_id
    heartbeat(device_id, status, load_pct, free_mem_mb)
    register_adapter(device_id, vendor, architecture, limits, mem_mb)
    list_online() → list[Device]
    list_offline() → list[Device]
    snapshot() → dict (used by SVG renderer + routing)
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
STUDIO_ROOT = HERE.parent
sys.path.insert(0, str(STUDIO_ROOT))
import paths  # noqa: E402

DB_PATH = Path(os.environ.get(
    "MYSPACE_WEAVE_DB", str(paths.DAG_CACHE_DIR / "weave.sqlite")))
OFFLINE_TTL_SEC = int(os.environ.get("MYSPACE_WEAVE_OFFLINE_TTL", "120"))


SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    device_id       TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    kind            TEXT NOT NULL,   -- owner | droplet | browser-tab | friend | bot
    owner           TEXT,
    capabilities    TEXT,            -- JSON
    status          TEXT NOT NULL DEFAULT 'online',  -- online | idle | busy | offline
    load_pct        REAL NOT NULL DEFAULT 0.0,
    free_mem_mb     INTEGER,
    first_seen      TEXT NOT NULL,
    last_seen       TEXT NOT NULL,
    user_agent      TEXT,
    ip              TEXT
);
CREATE INDEX IF NOT EXISTS idx_dev_status ON devices(status);
CREATE INDEX IF NOT EXISTS idx_dev_seen   ON devices(last_seen);

CREATE TABLE IF NOT EXISTS webgpu_adapters (
    adapter_id      TEXT PRIMARY KEY,
    device_id       TEXT NOT NULL,
    vendor          TEXT,
    architecture    TEXT,
    device_label    TEXT,
    is_fallback     INTEGER NOT NULL DEFAULT 0,
    limits          TEXT,            -- JSON
    features        TEXT,            -- JSON array
    available_memory_mb INTEGER,
    last_probed     TEXT,
    FOREIGN KEY (device_id) REFERENCES devices(device_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_adp_dev   ON webgpu_adapters(device_id);
"""


def _db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.execute("PRAGMA foreign_keys = ON")
    c.executescript(SCHEMA)
    return c


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ── Dataclasses ─────────────────────────────────────────────────────────────
@dataclass
class WebGpuAdapter:
    adapter_id: str
    device_id: str
    vendor: str
    architecture: str
    device_label: str = ""
    is_fallback: bool = False
    limits: dict = field(default_factory=dict)
    features: list[str] = field(default_factory=list)
    available_memory_mb: Optional[int] = None
    last_probed: Optional[str] = None


@dataclass
class Device:
    device_id: str
    name: str
    kind: str
    owner: Optional[str] = None
    capabilities: dict = field(default_factory=dict)
    status: str = "online"
    load_pct: float = 0.0
    free_mem_mb: Optional[int] = None
    first_seen: str = ""
    last_seen: str = ""
    user_agent: str = ""
    ip: str = ""
    adapters: list[WebGpuAdapter] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["adapters"] = [asdict(a) for a in self.adapters]
        return d


# ── Mutators ────────────────────────────────────────────────────────────────
def register_device(
    name: str, kind: str, *,
    owner: Optional[str] = None,
    capabilities: Optional[dict] = None,
    user_agent: Optional[str] = None,
    ip: Optional[str] = None,
) -> str:
    """Create or refresh a device row. Returns device_id."""
    if kind not in ("owner", "droplet", "browser-tab", "friend", "bot"):
        raise ValueError(f"unknown device kind: {kind}")
    did = uuid.uuid4().hex[:12]
    ts = now_iso()
    caps_json = json.dumps(capabilities or {}, sort_keys=True)
    with _db() as c:
        c.execute(
            "INSERT INTO devices (device_id, name, kind, owner, capabilities, "
            "                    status, first_seen, last_seen, user_agent, ip) "
            "VALUES (?, ?, ?, ?, ?, 'online', ?, ?, ?, ?)",
            (did, name, kind, owner, caps_json, ts, ts, user_agent or "",
             ip or ""),
        )
    return did


def heartbeat(device_id: str, *, status: str = "online",
              load_pct: float = 0.0,
              free_mem_mb: Optional[int] = None) -> bool:
    ts = now_iso()
    with _db() as c:
        r = c.execute(
            "UPDATE devices SET status=?, load_pct=?, free_mem_mb=?, "
            "                  last_seen=? WHERE device_id=?",
            (status, load_pct, free_mem_mb, ts, device_id),
        )
        return r.rowcount > 0


def register_adapter(
    device_id: str, *, vendor: str, architecture: str,
    device_label: str = "", is_fallback: bool = False,
    limits: Optional[dict] = None,
    features: Optional[list[str]] = None,
    available_memory_mb: Optional[int] = None,
) -> str:
    aid = uuid.uuid4().hex[:12]
    with _db() as c:
        c.execute(
            "INSERT INTO webgpu_adapters (adapter_id, device_id, vendor, "
            "       architecture, device_label, is_fallback, limits, "
            "       features, available_memory_mb, last_probed) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (aid, device_id, vendor, architecture, device_label,
             1 if is_fallback else 0,
             json.dumps(limits or {}, sort_keys=True),
             json.dumps(features or []),
             available_memory_mb, now_iso()),
        )
    return aid


def mark_offline_stale() -> int:
    """Flip devices whose last_seen is older than OFFLINE_TTL to status='offline'.
    Returns count flipped. Called by the relay periodically."""
    cutoff = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ",
        time.gmtime(time.time() - OFFLINE_TTL_SEC),
    )
    with _db() as c:
        r = c.execute(
            "UPDATE devices SET status='offline' "
            "WHERE last_seen < ? AND status != 'offline'",
            (cutoff,),
        )
        return r.rowcount


# ── Readers ────────────────────────────────────────────────────────────────
def _load_device(row, adapters_by_dev: dict) -> Device:
    (did, name, kind, owner, caps_json, status, load_pct, free_mem,
     first_seen, last_seen, user_agent, ip) = row
    d = Device(
        device_id=did, name=name, kind=kind, owner=owner or "",
        capabilities=json.loads(caps_json or "{}"),
        status=status, load_pct=load_pct or 0.0,
        free_mem_mb=free_mem,
        first_seen=first_seen, last_seen=last_seen,
        user_agent=user_agent or "", ip=ip or "",
    )
    d.adapters = adapters_by_dev.get(did, [])
    return d


def _all_adapters(c: sqlite3.Connection) -> dict[str, list[WebGpuAdapter]]:
    out: dict[str, list[WebGpuAdapter]] = {}
    for r in c.execute(
        "SELECT adapter_id, device_id, vendor, architecture, device_label, "
        "       is_fallback, limits, features, available_memory_mb, last_probed "
        "FROM webgpu_adapters"
    ).fetchall():
        a = WebGpuAdapter(
            adapter_id=r[0], device_id=r[1], vendor=r[2] or "",
            architecture=r[3] or "", device_label=r[4] or "",
            is_fallback=bool(r[5]),
            limits=json.loads(r[6] or "{}"),
            features=json.loads(r[7] or "[]"),
            available_memory_mb=r[8], last_probed=r[9],
        )
        out.setdefault(a.device_id, []).append(a)
    return out


def list_online() -> list[Device]:
    with _db() as c:
        rows = c.execute(
            "SELECT device_id, name, kind, owner, capabilities, status, "
            "       load_pct, free_mem_mb, first_seen, last_seen, "
            "       user_agent, ip FROM devices "
            "WHERE status IN ('online','idle','busy') ORDER BY first_seen"
        ).fetchall()
        adapters = _all_adapters(c)
    return [_load_device(r, adapters) for r in rows]


def list_offline() -> list[Device]:
    with _db() as c:
        rows = c.execute(
            "SELECT device_id, name, kind, owner, capabilities, status, "
            "       load_pct, free_mem_mb, first_seen, last_seen, "
            "       user_agent, ip FROM devices "
            "WHERE status = 'offline' ORDER BY last_seen DESC"
        ).fetchall()
        adapters = _all_adapters(c)
    return [_load_device(r, adapters) for r in rows]


def snapshot() -> dict:
    """Returns a dict suitable for embedding in the master SVG manifest
    and feeding routing.decide()."""
    mark_offline_stale()
    online = list_online()
    offline = list_offline()
    total_gpu_mem = sum(
        (a.available_memory_mb or 0)
        for d in online for a in d.adapters
        if not a.is_fallback
    )
    busy = [d for d in online if d.status == "busy"]
    idle = [d for d in online if d.status == "idle"]
    return {
        "ts":                now_iso(),
        "online":            [d.to_dict() for d in online],
        "offline":           [d.to_dict() for d in offline],
        "totals": {
            "online":         len(online),
            "offline":        len(offline),
            "idle":           len(idle),
            "busy":           len(busy),
            "total_gpu_mem_mb": total_gpu_mem,
            "device_kinds":   {k: sum(1 for d in online if d.kind == k)
                               for k in ("owner", "droplet", "browser-tab",
                                         "friend", "bot")},
        },
    }


# ── Seed (for SVG rendering + dry-runs) ─────────────────────────────────────
def seed_dev_topology() -> dict:
    """Insert 3-4 sample devices + adapters so the SVG isn't empty on first
    build. Idempotent — only inserts if devices table is empty."""
    with _db() as c:
        n = c.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
    if n > 0:
        return {"seeded": False, "had": n}

    owner = register_device(
        "tom-laptop", "owner", owner="tom",
        capabilities={"os": "NixOS", "ram_gb": 64, "cpu": "AMD Ryzen 9"},
        user_agent="cc/native",
    )
    register_adapter(owner, vendor="NVIDIA", architecture="Ada",
                     device_label="RTX 4090", limits={"maxBufferSize": 2**33},
                     features=["timestamp-query", "shader-f16"],
                     available_memory_mb=24576)

    droplet = register_device(
        "linode-droplet", "droplet", owner="tom",
        capabilities={"os": "debian-bookworm", "ram_gb": 16, "cpu": "shared-x86"},
        user_agent="myspace-relay/0.1",
    )
    register_adapter(droplet, vendor="CPU-only", architecture="x86_64",
                     device_label="software", is_fallback=True,
                     available_memory_mb=8192)

    friend = register_device(
        "jamie-mbp", "friend", owner="jamie",
        capabilities={"os": "macOS", "ram_gb": 16},
        user_agent="Chrome/127 Mac",
    )
    register_adapter(friend, vendor="Apple", architecture="m2",
                     device_label="Apple M2 (integrated)",
                     features=["shader-f16"],
                     available_memory_mb=8192)

    tab = register_device(
        "pete-tab", "browser-tab", owner="pete",
        capabilities={"browser": "Chrome 127"},
        user_agent="Chrome/127 Android",
    )
    register_adapter(tab, vendor="Qualcomm", architecture="Adreno",
                     device_label="Adreno 740 (mobile)",
                     available_memory_mb=4096)

    return {"seeded": True, "devices": 4, "adapters": 4}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("seed")
    sp.add_parser("snapshot")
    sp.add_parser("online")
    sp.add_parser("offline")
    args = ap.parse_args()

    if args.cmd == "seed":
        print(json.dumps(seed_dev_topology(), indent=2))
    elif args.cmd == "snapshot":
        print(json.dumps(snapshot(), indent=2))
    elif args.cmd == "online":
        for d in list_online():
            print(f"  {d.kind:<13} {d.name:<18} {d.status:<6} "
                  f"load={d.load_pct:5.1f}%  adapters={len(d.adapters)}")
    elif args.cmd == "offline":
        for d in list_offline():
            print(f"  {d.kind:<13} {d.name:<18} last={d.last_seen}")
