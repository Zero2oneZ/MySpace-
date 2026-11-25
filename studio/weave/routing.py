"""routing.py — decide where a pass should run, given live topology + PLANS.

Public API:
    decide(pass_spec) → RoutingDecision

Workflow:
    1. Build evaluation context from topology.snapshot() + pass_spec
    2. Evaluate every active plan in priority order (plans.evaluate())
    3. Take the first fired plan; record + return its action
    4. If no plan fires, fall back to the default (owner)
    5. Resolve target_device from the action (route_to/least-loaded/etc.)
    6. Persist the decision via plans.fire()
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
STUDIO_ROOT = HERE.parent
sys.path.insert(0, str(STUDIO_ROOT))

import importlib
try:
    topology = importlib.import_module("weave.topology")
    plans    = importlib.import_module("weave.plans")
except ImportError:
    from . import topology, plans   # type: ignore


@dataclass
class RoutingDecision:
    pass_id:          str
    file_kind:        str
    device_id:        Optional[str] = None    # None if deferred / not yet resolved
    device_name:      Optional[str] = None
    plan_id:          Optional[str] = None
    action:           dict = field(default_factory=dict)
    batched_with:     list[str] = field(default_factory=list)
    deferred:         bool = False
    reason:           str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ── Resolvers ───────────────────────────────────────────────────────────────
def _resolve_device(target: str, snapshot: dict) -> Optional[dict]:
    online = snapshot.get("online", [])
    if not online:
        return None
    if target == "owner":
        return next((d for d in online if d["kind"] == "owner"), None)
    if target == "droplet":
        return next((d for d in online if d["kind"] == "droplet"), None)
    if target == "browser-tab":
        return next((d for d in online if d["kind"] == "browser-tab"
                     and d["status"] in ("online", "idle")), None)
    if target == "any-idle":
        return next((d for d in online if d["status"] == "idle"), None)
    if target == "least-loaded":
        return min(online, key=lambda d: d.get("load_pct", 0.0))
    return None


# ── Main decide() ──────────────────────────────────────────────────────────
def decide(pass_spec: dict, *, persist: bool = True) -> RoutingDecision:
    """Pass a dict like:
        {"id": "mask", "cost_class": "HEAVY",
         "import_time": True, "file_kind": "jpg", "file_bytes": 400_000}
    Returns a RoutingDecision."""
    snap = topology.snapshot()
    ctx = plans.build_ctx(pass_spec=pass_spec, snapshot=snap)
    evaluations = plans.evaluate(ctx)

    # First-fired plan wins (plans already sorted by priority ascending)
    first_fired = next((p for p, fired in evaluations if fired), None)

    if first_fired is None:
        decision = RoutingDecision(
            pass_id=pass_spec.get("id", "?"),
            file_kind=pass_spec.get("file_kind", "?"),
            device_id=None, device_name=None, plan_id=None,
            reason="no plan matched (should be impossible — p007 catch-all)",
        )
        return decision

    action = first_fired.action
    decision = RoutingDecision(
        pass_id=pass_spec.get("id", "?"),
        file_kind=pass_spec.get("file_kind", "?"),
        plan_id=first_fired.plan_id,
        action=action,
    )

    if action.get("defer"):
        decision.deferred = True
        decision.reason = first_fired.description or "deferred per plan"
    elif "route_to" in action:
        primary = _resolve_device(action["route_to"], snap)
        if primary is None and action.get("fallback_to"):
            primary = _resolve_device(action["fallback_to"], snap)
        if primary is None:
            decision.deferred = True
            decision.reason = (
                f"no device matched route_to={action['route_to']} "
                f"or fallback_to={action.get('fallback_to')}"
            )
        else:
            decision.device_id = primary["device_id"]
            decision.device_name = primary["name"]
            decision.reason = first_fired.description or first_fired.name

    if persist:
        plans.fire(first_fired.plan_id,
                   pass_id=decision.pass_id,
                   file_kind=decision.file_kind,
                   decision=decision.to_dict())
    return decision


if __name__ == "__main__":
    import argparse, json
    ap = argparse.ArgumentParser()
    ap.add_argument("--pass-id", default="mask")
    ap.add_argument("--cost-class", default="HEAVY",
                    choices=["LIGHT", "MEDIUM", "HEAVY"])
    ap.add_argument("--import-time", action="store_true")
    ap.add_argument("--file-kind", default="jpg")
    ap.add_argument("--file-bytes", type=int, default=400_000)
    ap.add_argument("--no-persist", action="store_true")
    args = ap.parse_args()

    spec = {
        "id":          args.pass_id,
        "cost_class":  args.cost_class,
        "import_time": args.import_time,
        "file_kind":   args.file_kind,
        "file_bytes":  args.file_bytes,
    }
    d = decide(spec, persist=not args.no_persist)
    print(json.dumps(d.to_dict(), indent=2))
