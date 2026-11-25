#!/usr/bin/env python3
"""router.py — RoutingOperator: connects inbound events to outbound actions.

Rules live in studio/endpoints/routes/ as JSON files.
Each rule maps:
  {kind, service, tag, condition} → {action, target_service, target_recipient, template}

Actions:
  forward   → pass event to another endpoint or internal handler
  reply     → send a response back via third_party connector
  broadcast → send to all connectors with matching tag
  log       → write to chain only
  notify    → emit desktop/terminal notification
  chain     → trigger a cc -chat or cc -passes-run workflow

Determinism: rules are evaluated in priority order; first match wins.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Dict, List, Any, Callable

STUDIO_ROOT = Path(os.environ.get("STUDIO_ROOT", "/data/Projects/MySpace++/studio"))
ROUTES_ROOT = STUDIO_ROOT / "endpoints" / "routes"


def _crystal(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class RouteRule:
    """One routing decision."""
    asset_id: str = ""
    crystal: str = ""
    vm_id: str = "vm_mspc_001"
    name: str = ""              # human label
    state: str = "active"       # active | paused | archived
    version: str = "v0"
    priority: int = 0           # lower = evaluated first

    # Match conditions
    match_kind: str = "*"       # webhook, rest, telegram_bot, ...
    match_service: str = "*"    # discord, telegram, generic, ...
    match_tag: str = "*"        # inbound, alert, user_dm, build_complete, ...
    match_condition: Optional[str] = None   # optional Python expression evaluated against event.body

    # Action
    action: str = "log"         # forward | reply | broadcast | log | notify | chain
    target_service: str = ""   # for forward/reply/broadcast
    target_recipient: str = "" # for reply
    template: str = ""         # Jinja-like {{body.field}} substitution
    chain_command: str = ""    # for action=chain: e.g. "cc chat --tier tiny"

    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if not self.crystal:
            canonical = json.dumps(asdict(self), sort_keys=True, default=str).encode()
            self.crystal = _crystal(canonical)

    def matches(self, event: Any) -> bool:
        """Evaluate whether this rule matches an inbound event."""
        kind = getattr(event, "kind", "*")
        service = getattr(event, "service", "*")
        tag = getattr(event, "tag", "*")
        if self.match_kind != "*" and self.match_kind != kind:
            return False
        if self.match_service != "*" and self.match_service != service:
            return False
        if self.match_tag != "*" and self.match_tag != tag:
            return False
        if self.match_condition and hasattr(event, "body"):
            try:
                # Safer than eval — use a restricted dict
                body = event.body if isinstance(event.body, dict) else {}
                allowed = {"body": body, "tag": tag, "service": service}
                if not eval(self.match_condition, {"__builtins__": {}}, allowed):
                    return False
            except Exception:
                return False
        return True

    def save(self) -> Path:
        ROUTES_ROOT.mkdir(parents=True, exist_ok=True)
        fname = f"{self.vm_id}.route.{self.name}.{self.state}.{self.version}.json"
        path = ROUTES_ROOT / fname
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        return path


class RoutingOperator:
    """Central routing table for all inbound → outbound flows."""

    def __init__(self, routes_root: Optional[Path] = None):
        self.routes_root = routes_root or ROUTES_ROOT
        self._rules: List[RouteRule] = []
        self._handlers: Dict[str, Callable] = {}
        self._tp_manager: Optional[Any] = None  # lazy import third_party.manager

    def load_rules(self) -> "RoutingOperator":
        """Scan routes directory and load active rules sorted by priority."""
        self._rules.clear()
        if not self.routes_root.exists():
            return self
        for f in self.routes_root.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                rule = RouteRule(**data)
                if rule.state == "active":
                    self._rules.append(rule)
            except Exception:
                continue
        self._rules.sort(key=lambda r: r.priority)
        return self

    def add_handler(self, action: str, handler: Callable) -> None:
        """Register a Python callable for a given action type."""
        self._handlers[action] = handler

    def route(self, event: Any) -> List[Dict[str, Any]]:
        """Evaluate all rules against an event; execute matched actions."""
        results: List[Dict[str, Any]] = []
        matched_any = False
        for rule in self._rules:
            if not rule.matches(event):
                continue
            matched_any = True
            result = self._execute(rule, event)
            results.append({
                "rule": rule.name,
                "action": rule.action,
                "matched": True,
                "result": result,
            })
            if rule.action in ("reply", "broadcast", "chain"):
                # These are terminal — stop evaluating
                break
        if not matched_any:
            results.append({"rule": "*", "action": "drop", "matched": False, "result": "no_route_matched"})
        return results

    def _execute(self, rule: RouteRule, event: Any) -> Any:
        handler = self._handlers.get(rule.action)
        if handler:
            return handler(rule, event)
        # Built-in defaults
        if rule.action == "log":
            return self._default_log(rule, event)
        if rule.action == "forward":
            return self._default_forward(rule, event)
        if rule.action == "reply":
            return self._default_reply(rule, event)
        if rule.action == "broadcast":
            return self._default_broadcast(rule, event)
        if rule.action == "notify":
            return self._default_notify(rule, event)
        if rule.action == "chain":
            return self._default_chain(rule, event)
        return {"error": f"unknown action: {rule.action}"}

    def _default_log(self, rule: RouteRule, event: Any) -> str:
        log_dir = Path.home() / ".cc" / "routing_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "route_decisions.jsonl"
        record = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "rule": rule.name,
            "action": rule.action,
            "event_crystal": getattr(event, "crystal_id", ""),
            "tag": getattr(event, "tag", ""),
        }
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")
        return "logged"

    def _default_forward(self, rule: RouteRule, event: Any) -> str:
        return {"forward_to": rule.target_service, "template": rule.template}

    def _default_reply(self, rule: RouteRule, event: Any) -> str:
        # Lazy-import third_party to avoid circular dep
        from core.lib.third_party.manager import ThirdPartyManager
        if self._tp_manager is None:
            self._tp_manager = ThirdPartyManager().load_all()
        msg = self._render_template(rule.template, event)
        results = self._tp_manager.send(rule.target_service, rule.target_recipient, msg)
        return {"sent": len(results), "service": rule.target_service}

    def _default_broadcast(self, rule: RouteRule, event: Any) -> str:
        from core.lib.third_party.manager import ThirdPartyManager
        if self._tp_manager is None:
            self._tp_manager = ThirdPartyManager().load_all()
        msg = self._render_template(rule.template, event)
        results = self._tp_manager.send_by_tag(rule.target_service or rule.match_tag, msg)
        return {"broadcast_to": list(results.keys())}

    def _default_notify(self, rule: RouteRule, event: Any) -> str:
        msg = self._render_template(rule.template, event)
        # Write to a notify pipe that the host can watch
        notify_path = Path.home() / ".cc" / "notify_pipe.jsonl"
        with notify_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"msg": msg, "rule": rule.name, "ts": time.time()}, sort_keys=True) + "\n")
        return "notified"

    def _default_chain(self, rule: RouteRule, event: Any) -> str:
        import subprocess
        cmd = rule.chain_command
        if not cmd:
            return {"error": "chain action with no chain_command"}
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            return {"returncode": result.returncode, "stdout": result.stdout[:500], "stderr": result.stderr[:500]}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def _render_template(template: str, event: Any) -> str:
        if not template:
            return ""
        body = event.body if hasattr(event, "body") and isinstance(event.body, dict) else {}
        out = template
        for key, val in body.items():
            placeholder = f"{{{{body.{key}}}}}"
            out = out.replace(placeholder, str(val))
        # Fallback: replace {{tag}} and {{source_ip}}
        if hasattr(event, "tag"):
            out = out.replace("{{tag}}", str(event.tag))
        if hasattr(event, "source_ip"):
            out = out.replace("{{source_ip}}", str(event.source_ip))
        return out

    def add_rule(self, rule: RouteRule) -> Path:
        self._rules.append(rule)
        self._rules.sort(key=lambda r: r.priority)
        return rule.save()

    def archive_rule(self, asset_id: str) -> Optional[Path]:
        for f in self.routes_root.glob("*.json"):
            if asset_id in f.name:
                new_name = f.name.replace(".active.", ".archived.")
                dest = f.parent / new_name
                f.rename(dest)
                self.load_rules()
                return dest
        return None

    def list_rules(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": r.name,
                "priority": r.priority,
                "match": f"{r.match_kind}:{r.match_service}:{r.match_tag}",
                "action": r.action,
                "target": r.target_service or "-",
                "state": r.state,
            }
            for r in self._rules
        ]
