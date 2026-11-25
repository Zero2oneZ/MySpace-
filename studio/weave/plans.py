"""plans.py — declarative routing rules.

A PLAN is a (condition, action, priority) triple. Conditions reference
the live topology snapshot + the pass-spec being routed. Actions tell
the router where to send work.

Plans are stored both as constants in this file (the seed set) and as
rows in weave.sqlite.plans (user-editable overrides). The SVG renderer
shows every active plan in the PLANS layer of TWINS-MASTER.svg.

Condition DSL (intentionally tiny):

    {"all": [<cond>, <cond>, ...]}     all must be true
    {"any": [<cond>, <cond>, ...]}     any must be true
    {"not": <cond>}                     negation
    {"<field>": "<value>"}              equality
    {"<field>": {"gt": N}}              numeric comparison (gt|gte|lt|lte|ne)
    {"<field>": {"in": [...]}}          membership
    {"<field>": {"contains": "x"}}      substring (for strings + arrays)

Fields available at evaluation time:
    pass.id              the pass being routed (e.g. "mask", "depth")
    pass.cost_class      "LIGHT" | "MEDIUM" | "HEAVY"
    pass.import_time     bool
    pass.file_kind       ext like "jpg"
    pass.file_bytes      int
    topology.n_online    int
    topology.n_idle      int
    topology.n_busy      int
    topology.total_gpu_mem_mb  int
    topology.has_owner   bool
    topology.has_droplet bool
    topology.n_browser_tabs    int
    owner.load_pct       float
    owner.free_mem_mb    int
    owner.on_battery     bool (capabilities)

Action DSL:
    {"route_to": "owner"|"droplet"|"any-idle"|"least-loaded"|"browser-tab"}
    {"defer": true}                        push to a delayed queue
    {"batch_with_others": int}             batch with up to N other jobs
    {"fallback_to": "owner"}               if primary route fails

See SEED_PLANS for examples.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

HERE = Path(__file__).resolve().parent
STUDIO_ROOT = HERE.parent
sys.path.insert(0, str(STUDIO_ROOT))
import paths   # noqa: E402

import importlib
try:
    topology = importlib.import_module("weave.topology")
except ImportError:
    from . import topology   # type: ignore

DB_PATH = topology.DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS plans (
    plan_id     TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    condition   TEXT NOT NULL,   -- JSON
    action      TEXT NOT NULL,   -- JSON
    priority    INTEGER NOT NULL DEFAULT 100,
    active      INTEGER NOT NULL DEFAULT 1,
    seeded      INTEGER NOT NULL DEFAULT 0,
    created     TEXT NOT NULL,
    last_fired  TEXT,
    fire_count  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_plans_prio  ON plans(priority);
CREATE INDEX IF NOT EXISTS idx_plans_active ON plans(active);

CREATE TABLE IF NOT EXISTS plan_evaluations (
    eval_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id    TEXT,
    ts         TEXT NOT NULL,
    fired      INTEGER NOT NULL,
    pass_id    TEXT,
    file_kind  TEXT,
    decision   TEXT,    -- JSON RoutingDecision
    FOREIGN KEY (plan_id) REFERENCES plans(plan_id)
);
CREATE INDEX IF NOT EXISTS idx_pe_ts   ON plan_evaluations(ts);
CREATE INDEX IF NOT EXISTS idx_pe_plan ON plan_evaluations(plan_id);
"""


def _db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.executescript(SCHEMA)
    return c


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class Plan:
    plan_id: str
    name: str
    description: str = ""
    condition: dict = field(default_factory=dict)
    action: dict = field(default_factory=dict)
    priority: int = 100
    active: bool = True
    fire_count: int = 0
    last_fired: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


# ── Seed plans ──────────────────────────────────────────────────────────────
SEED_PLANS: list[Plan] = [
    Plan(
        plan_id="p001-heavy-to-owner",
        name="Heavy passes → owner GPU when available",
        description="If the owner is online with a real GPU adapter, "
                    "heavy passes go there.",
        condition={"all": [
            {"pass.cost_class": "HEAVY"},
            {"topology.has_owner": True},
            {"owner.load_pct": {"lt": 80}},
        ]},
        action={"route_to": "owner", "fallback_to": "droplet"},
        priority=10,  # higher priority (lower number)
    ),
    Plan(
        plan_id="p002-heavy-overflow-droplet",
        name="Heavy overflow → droplet if owner saturated",
        description="If owner.load_pct ≥ 80, send heavy to droplet "
                    "(CPU-only fallback is slow but doesn't block owner).",
        condition={"all": [
            {"pass.cost_class": "HEAVY"},
            {"owner.load_pct": {"gte": 80}},
            {"topology.has_droplet": True},
        ]},
        action={"route_to": "droplet"},
        priority=15,
    ),
    Plan(
        plan_id="p003-light-batch-tabs",
        name="LIGHT passes batched on browser tabs",
        description="Browser-tab workers can run many LIGHT passes "
                    "(thumb, content-hash) in a single batch — cheap and "
                    "spreads load.",
        condition={"all": [
            {"pass.cost_class": "LIGHT"},
            {"topology.n_browser_tabs": {"gte": 1}},
        ]},
        action={"route_to": "browser-tab",
                "batch_with_others": 50,
                "fallback_to": "owner"},
        priority=20,
    ),
    Plan(
        plan_id="p004-medium-least-loaded",
        name="MEDIUM passes → least-loaded device",
        description="Medium passes balance — pick whichever device has "
                    "the most free capacity.",
        condition={"all": [
            {"pass.cost_class": "MEDIUM"},
            {"topology.n_online": {"gte": 2}},
        ]},
        action={"route_to": "least-loaded", "fallback_to": "owner"},
        priority=30,
    ),
    Plan(
        plan_id="p005-defer-lazy-on-battery",
        name="Defer lazy passes when owner on battery",
        description="If owner reports on_battery and pass is lazy (non-import), "
                    "defer until plugged in.",
        condition={"all": [
            {"pass.import_time": False},
            {"owner.on_battery": True},
        ]},
        action={"defer": True},
        priority=25,
    ),
    Plan(
        plan_id="p006-friend-low-priority-queue",
        name="Friends get low-priority lazy work",
        description="Friend browser-tabs are nice-to-have workers; only "
                    "give them lazy/optional jobs, never the import-time path.",
        condition={"all": [
            {"pass.import_time": False},
            {"topology.n_browser_tabs": {"gte": 1}},
        ]},
        action={"route_to": "browser-tab"},
        priority=40,
    ),
    Plan(
        plan_id="p007-default-owner",
        name="Default → owner",
        description="Catch-all: if no specific plan fires, run on the "
                    "owner device. Lowest priority (highest number).",
        condition={"all": []},   # always true
        action={"route_to": "owner"},
        priority=999,
    ),
    Plan(
        plan_id="p008-no-online-defer",
        name="Defer if nothing is online",
        description="Edge case: no devices online → defer the job rather "
                    "than crash. Set when the relay shuts down briefly.",
        condition={"topology.n_online": {"lt": 1}},
        action={"defer": True},
        priority=5,   # very high priority — preempts everything
    ),
]


# ── Mutators ────────────────────────────────────────────────────────────────
def seed_default_plans() -> dict:
    """Idempotent — only inserts a seed plan if its plan_id isn't already present."""
    inserted = 0
    with _db() as c:
        existing = {r[0] for r in c.execute("SELECT plan_id FROM plans").fetchall()}
        for p in SEED_PLANS:
            if p.plan_id in existing:
                continue
            c.execute(
                "INSERT INTO plans (plan_id, name, description, condition, "
                "                  action, priority, active, seeded, created) "
                "VALUES (?, ?, ?, ?, ?, ?, 1, 1, ?)",
                (p.plan_id, p.name, p.description,
                 json.dumps(p.condition, sort_keys=True),
                 json.dumps(p.action, sort_keys=True),
                 p.priority, now_iso()),
            )
            inserted += 1
    return {"inserted": inserted, "total_seed": len(SEED_PLANS)}


def list_plans(active_only: bool = True) -> list[Plan]:
    where = "WHERE active=1" if active_only else ""
    with _db() as c:
        rows = c.execute(
            f"SELECT plan_id, name, description, condition, action, "
            f"       priority, active, fire_count, last_fired FROM plans "
            f"{where} ORDER BY priority"
        ).fetchall()
    return [
        Plan(plan_id=r[0], name=r[1], description=r[2] or "",
             condition=json.loads(r[3] or "{}"),
             action=json.loads(r[4] or "{}"),
             priority=r[5], active=bool(r[6]),
             fire_count=r[7], last_fired=r[8])
        for r in rows
    ]


def disable_plan(plan_id: str) -> bool:
    with _db() as c:
        r = c.execute("UPDATE plans SET active=0 WHERE plan_id=?", (plan_id,))
        return r.rowcount > 0


def fire(plan_id: str, *, pass_id: str, file_kind: str,
         decision: dict) -> None:
    """Record that a plan fired and stamp it on the audit log."""
    with _db() as c:
        c.execute(
            "INSERT INTO plan_evaluations (plan_id, ts, fired, pass_id, "
            "                              file_kind, decision) "
            "VALUES (?, ?, 1, ?, ?, ?)",
            (plan_id, now_iso(), pass_id, file_kind,
             json.dumps(decision, sort_keys=True)),
        )
        c.execute(
            "UPDATE plans SET fire_count = fire_count + 1, last_fired = ? "
            "WHERE plan_id = ?", (now_iso(), plan_id),
        )


# ── Condition evaluator ─────────────────────────────────────────────────────
_CMP = {
    "gt":  lambda a, b: a is not None and a > b,
    "gte": lambda a, b: a is not None and a >= b,
    "lt":  lambda a, b: a is not None and a < b,
    "lte": lambda a, b: a is not None and a <= b,
    "ne":  lambda a, b: a != b,
    "eq":  lambda a, b: a == b,
}


def _lookup(field_path: str, ctx: dict) -> Any:
    """'topology.n_online' → ctx['topology']['n_online']"""
    cur: Any = ctx
    for part in field_path.split("."):
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _eval_node(node: Any, ctx: dict) -> bool:
    if isinstance(node, dict):
        if "all" in node:
            return all(_eval_node(c, ctx) for c in node["all"]) or len(node["all"]) == 0
        if "any" in node:
            return any(_eval_node(c, ctx) for c in node["any"])
        if "not" in node:
            return not _eval_node(node["not"], ctx)
        # field-comparison or equality
        if len(node) == 1:
            (key, val), = node.items()
            actual = _lookup(key, ctx)
            if isinstance(val, dict):
                # operator dict like {"gt": 50}
                for op, target in val.items():
                    fn = _CMP.get(op)
                    if fn is None:
                        return False
                    if op in ("gt", "gte", "lt", "lte"):
                        try:
                            if not fn(float(actual) if actual is not None else None,
                                     float(target)):
                                return False
                        except (ValueError, TypeError):
                            return False
                    elif op == "in":
                        if actual not in target:
                            return False
                    elif op == "contains":
                        if not actual or target not in actual:
                            return False
                    elif op in ("eq", "ne"):
                        if not fn(actual, target):
                            return False
                return True
            return actual == val
    return False


def evaluate(ctx: dict) -> list[tuple[Plan, bool]]:
    """Evaluate every active plan against ctx. Returns list of (plan, fired)
    in priority order. The router takes the first fired."""
    plans = list_plans(active_only=True)
    return [(p, _eval_node(p.condition, ctx)) for p in plans]


def build_ctx(*, pass_spec: dict, snapshot: Optional[dict] = None) -> dict:
    """Construct the evaluator context for one routing decision."""
    snap = snapshot or topology.snapshot()
    online = snap.get("online", [])
    owner = next((d for d in online if d.get("kind") == "owner"), None)
    return {
        "pass": pass_spec,
        "topology": {
            "n_online":         snap["totals"]["online"],
            "n_idle":           snap["totals"]["idle"],
            "n_busy":           snap["totals"]["busy"],
            "n_browser_tabs":   snap["totals"]["device_kinds"]["browser-tab"],
            "has_owner":        any(d.get("kind") == "owner" for d in online),
            "has_droplet":      any(d.get("kind") == "droplet" for d in online),
            "total_gpu_mem_mb": snap["totals"]["total_gpu_mem_mb"],
        },
        "owner": {
            "load_pct":     (owner or {}).get("load_pct", 0.0),
            "free_mem_mb":  (owner or {}).get("free_mem_mb"),
            "on_battery":   (owner or {}).get("capabilities", {}).get("on_battery", False),
        },
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("seed")
    sp.add_parser("list")
    p_e = sp.add_parser("evaluate")
    p_e.add_argument("--pass-id", default="mask")
    p_e.add_argument("--cost-class", default="HEAVY")
    p_e.add_argument("--import-time", action="store_true")
    p_e.add_argument("--file-kind", default="jpg")
    p_e.add_argument("--file-bytes", type=int, default=400_000)
    args = ap.parse_args()

    if args.cmd == "seed":
        print(json.dumps(seed_default_plans(), indent=2))
    elif args.cmd == "list":
        for p in list_plans(active_only=False):
            flag = "ACTIVE" if p.active else "off"
            print(f"  [{p.priority:>3}] {flag:<6} {p.plan_id} — {p.name}")
            print(f"        action: {json.dumps(p.action)}")
            print(f"        fired:  {p.fire_count} times")
    elif args.cmd == "evaluate":
        ctx = build_ctx(pass_spec={
            "id": args.pass_id,
            "cost_class": args.cost_class,
            "import_time": args.import_time,
            "file_kind": args.file_kind,
            "file_bytes": args.file_bytes,
        })
        print(json.dumps({"ctx": ctx, "evaluations": [
            {"plan_id": p.plan_id, "fired": fired, "action": p.action}
            for p, fired in evaluate(ctx)
        ]}, indent=2))
