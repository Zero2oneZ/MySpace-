"""timing.py — per-machine inference time cache.

Every pass run records (pass_id, file_kind, file_size, file_pixels,
duration_ms) into studio/cache/dag/passes_timing.sqlite. Estimates use
a rolling median (last 30 runs).

The classify_cost helper converts a duration into a LIGHT/MEDIUM/HEAVY
bucket, so over time the registry's seed cost_classes self-correct to
the actual machine.

Thresholds (configurable via env):
    LIGHT  <= 50 ms
    MEDIUM <= 500 ms
    HEAVY  > 500 ms
"""
from __future__ import annotations

import os
import sqlite3
import statistics
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

# Resolve the canonical path via Tom's paths module.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    import paths
    DB_PATH = paths.DAG_CACHE_DIR / "passes_timing.sqlite"
except ImportError:
    DB_PATH = Path.home() / ".cache" / "myspace" / "passes_timing.sqlite"


LIGHT_MAX_MS  = int(os.environ.get("MYSPACE_LIGHT_MS",  "50"))
MEDIUM_MAX_MS = int(os.environ.get("MYSPACE_MEDIUM_MS", "500"))


SCHEMA = """
CREATE TABLE IF NOT EXISTS timings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    pass_id      TEXT NOT NULL,
    file_kind    TEXT,
    file_bytes   INTEGER,
    file_pixels  INTEGER,
    duration_ms  REAL NOT NULL,
    machine_id   TEXT,
    ts           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_t_pass  ON timings(pass_id);
CREATE INDEX IF NOT EXISTS idx_t_pkind ON timings(pass_id, file_kind);
"""


def _machine_id() -> str:
    # uname-based stable-ish ID; not a security identifier.
    import platform
    return f"{platform.node()}-{platform.machine()}"


def _db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.executescript(SCHEMA)
    return c


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def record(pass_id: str, file_path: Optional[Path], duration_ms: float,
           file_kind: Optional[str] = None) -> None:
    """Persist a measurement."""
    file_bytes = file_pixels = None
    fk = file_kind
    if file_path is not None and Path(file_path).exists():
        try:
            file_bytes = Path(file_path).stat().st_size
        except OSError:
            pass
        if fk is None:
            fk = Path(file_path).suffix.lstrip(".").lower() or None
        # Best-effort pixel count for images.
        try:
            from PIL import Image
            with Image.open(file_path) as im:
                file_pixels = im.size[0] * im.size[1]
        except Exception:
            pass
    with _db() as c:
        c.execute(
            "INSERT INTO timings (pass_id, file_kind, file_bytes, file_pixels, "
            "                    duration_ms, machine_id, ts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (pass_id, fk, file_bytes, file_pixels, duration_ms,
             _machine_id(), now_iso()),
        )


def estimate(pass_id: str, file_kind: Optional[str] = None,
             file_bytes: Optional[int] = None) -> Optional[float]:
    """Rolling-median duration in ms over the last 30 runs.
    Filters by file_kind first; falls back to overall pass-id median."""
    with _db() as c:
        q = "SELECT duration_ms FROM timings WHERE pass_id = ?"
        params: list = [pass_id]
        if file_kind:
            q += " AND file_kind = ?"
            params.append(file_kind)
        q += " ORDER BY id DESC LIMIT 30"
        rows = [r[0] for r in c.execute(q, params).fetchall()]
    if not rows and file_kind:
        return estimate(pass_id, None, file_bytes)
    if not rows:
        return None
    return statistics.median(rows)


def classify_cost(duration_ms: float) -> str:
    if duration_ms <= LIGHT_MAX_MS:
        return "LIGHT"
    if duration_ms <= MEDIUM_MAX_MS:
        return "MEDIUM"
    return "HEAVY"


def summary() -> list[dict]:
    """Return one row per (pass_id, file_kind) with median+count."""
    with _db() as c:
        rows = c.execute(
            "SELECT pass_id, file_kind, COUNT(*) AS n, "
            "       AVG(duration_ms), MIN(duration_ms), MAX(duration_ms) "
            "FROM timings GROUP BY pass_id, file_kind"
        ).fetchall()
    out = []
    for pid, kind, n, avg, mn, mx in rows:
        out.append({
            "pass_id": pid, "file_kind": kind, "n": n,
            "avg_ms": round(avg, 1), "min_ms": round(mn, 1), "max_ms": round(mx, 1),
            "cost": classify_cost(avg),
        })
    return out


class Timer:
    """Context manager: `with Timer('mask', path) as t:` records on exit."""
    def __init__(self, pass_id: str, file_path: Optional[Path] = None,
                 file_kind: Optional[str] = None):
        self.pass_id = pass_id
        self.file_path = file_path
        self.file_kind = file_kind
        self.duration_ms: Optional[float] = None
        self._t0 = 0.0

    def __enter__(self):
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.duration_ms = (time.perf_counter() - self._t0) * 1000.0
        try:
            record(self.pass_id, self.file_path, self.duration_ms, self.file_kind)
        except Exception:
            pass   # best-effort — never let timing crash the pass
        return False


if __name__ == "__main__":
    rows = summary()
    if not rows:
        print("(no timing data yet)")
    else:
        print(f"{'pass':<18} {'kind':<6} {'n':<5} {'avg':<8} {'min':<8} {'max':<8} {'cost'}")
        print("-" * 70)
        for r in sorted(rows, key=lambda x: x["pass_id"]):
            print(f"{r['pass_id']:<18} {r['file_kind'] or '-':<6} "
                  f"{r['n']:<5} {r['avg_ms']:<8} {r['min_ms']:<8} "
                  f"{r['max_ms']:<8} {r['cost']}")
