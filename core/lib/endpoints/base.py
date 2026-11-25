#!/usr/bin/env python3
"""base.py — abstract base for all inbound endpoint listeners.

Every listener implements:
  - start()    → bind port/route, return crystal_id of startup event
  - stop()     → unbind, return crystal_id
  - receive()  → process one inbound event, return ReceiveEvent
  - health()   → return {status, uptime_ms, events_received}

Config files live at:
  studio/endpoints/{kind}/
    vm_mspc_001.{kind}.{service}.{name}.{state}.{version}.json
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Dict, List, Any

STUDIO_ROOT = Path(os.environ.get("STUDIO_ROOT", "/data/Projects/MySpace++/studio"))
ENDPOINTS_ROOT = STUDIO_ROOT / "endpoints"


def _crystal(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class EndpointConfig:
    """Deterministic config for any inbound endpoint."""
    asset_id: str = ""
    crystal: str = ""
    vm_id: str = "vm_mspc_001"
    kind: str = ""              # webhook, rest, telegram_bot, discord_bot, mcp_bridge
    service: str = ""           # discord, telegram, generic, internal
    name: str = ""              # human-readable label
    state: str = "active"       # active | paused | archived
    version: str = "v0"
    bind: Dict[str, Any] = None   # host, port, path, method, ssl_cert
    auth: Dict[str, Any] = None   # token_header, secret, hmac_key, whitelist_ips
    routing: Dict[str, Any] = None  # default_tag, fallback_service, priority
    limits: Dict[str, Any] = None   # max_body_mb, rate_limit, timeout_seconds
    created_at: str = ""

    def __post_init__(self):
        if self.bind is None:
            self.bind = {"host": "0.0.0.0", "port": 8080, "path": "/", "method": "POST"}
        if self.auth is None:
            self.auth = {}
        if self.routing is None:
            self.routing = {"default_tag": "inbound", "priority": 0}
        if self.limits is None:
            self.limits = {"max_body_mb": 10, "rate_limit": 100, "timeout_seconds": 30}
        if not self.created_at:
            self.created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if not self.crystal:
            self._compute_crystal()

    def _compute_crystal(self) -> None:
        canonical = json.dumps(asdict(self), sort_keys=True, default=str).encode()
        self.crystal = _crystal(canonical)

    def save(self, root: Optional[Path] = None) -> Path:
        root = root or ENDPOINTS_ROOT
        dir_path = root / self.kind
        dir_path.mkdir(parents=True, exist_ok=True)
        fname = f"{self.vm_id}.{self.kind}.{self.service}.{self.name}.{self.state}.{self.version}.json"
        path = dir_path / fname
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        return path


@dataclass
class ReceiveEvent:
    crystal_id: str
    endpoint_asset_id: str
    timestamp: str
    source_ip: str
    headers: Dict[str, str]
    body: Any
    tag: str               # routing tag extracted from body or headers
    matched_route: Optional[str] = None
    forwarded_to: List[str] = None
    processed: bool = False
    error: Optional[str] = None

    def __post_init__(self):
        if self.forwarded_to is None:
            self.forwarded_to = []


class EndpointListener(ABC):
    """Abstract inbound listener."""

    KIND: str = ""
    SERVICE: str = ""

    def __init__(self, config: EndpointConfig):
        self.config = config
        self._running = False
        self._start_ts: float = 0.0
        self._events_received = 0

    @abstractmethod
    def start(self) -> str:
        """Bind and begin accepting connections. Returns crystal_id."""
        ...

    @abstractmethod
    def stop(self) -> str:
        """Unbind and stop. Returns crystal_id."""
        ...

    @abstractmethod
    def receive(self, raw_request: Any) -> ReceiveEvent:
        """Process one inbound payload into a ReceiveEvent."""
        ...

    def health(self) -> Dict[str, Any]:
        return {
            "status": "running" if self._running else "stopped",
            "uptime_ms": int((time.time() - self._start_ts) * 1000) if self._running else 0,
            "events_received": self._events_received,
            "kind": self.KIND,
            "service": self.SERVICE,
            "asset_id": self.config.asset_id,
        }

    def _log_receive(self, event: ReceiveEvent) -> None:
        """Append-only JSONL log of every inbound event."""
        log_dir = Path.home() / ".cc" / "endpoint_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{self.KIND}_{self.SERVICE}_events.jsonl"
        record = {
            "crystal_id": event.crystal_id,
            "endpoint_asset_id": event.endpoint_asset_id,
            "timestamp": event.timestamp,
            "source_ip": event.source_ip,
            "tag": event.tag,
            "matched_route": event.matched_route,
            "forwarded_to": event.forwarded_to,
            "processed": event.processed,
            "error": event.error,
        }
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True, default=str) + "\n")
        self._events_received += 1
