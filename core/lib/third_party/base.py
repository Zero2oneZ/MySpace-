#!/usr/bin/env python3
"""base.py — abstract base for all outbound third-party connectors.

Every connector implements:
  - connect()   → validate auth, return config hash
  - send()      → dispatch message, return crystal_id of the send log
  - history()   → paginated fetch of conversation/thread history
  - disconnect() → graceful close

Config files live at:
  studio/third_party/{service}/
    vm_mspc_001.{service}.{action}.{name}.{state}.{version}.json
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
THIRD_PARTY_ROOT = STUDIO_ROOT / "third_party"


def _crystal(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class ConnectionConfig:
    """Deterministic config for any outbound connection."""
    asset_id: str = ""
    crystal: str = ""
    vm_id: str = "vm_mspc_001"
    service: str = ""           # discord, telegram, whatsapp, twitter, facebook...
    action: str = "connect"     # connect, send, listen, webhook
    name: str = ""              # human-readable label
    state: str = "active"       # active | paused | archived
    version: str = "v0"
    auth: Dict[str, Any] = None   # token, api_key, session_cookie, etc.
    limits: Dict[str, Any] = None  # rate_limit, burst, cooldown_seconds
    routing_tags: List[str] = None  # tiny, medium, epic, broadcast, dm, thread
    created_at: str = ""

    def __post_init__(self):
        if self.auth is None:
            self.auth = {}
        if self.limits is None:
            self.limits = {"requests_per_minute": 60, "burst": 10}
        if self.routing_tags is None:
            self.routing_tags = []
        if not self.created_at:
            self.created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if not self.crystal:
            self._compute_crystal()

    def _compute_crystal(self) -> None:
        canonical = json.dumps(asdict(self), sort_keys=True, default=str).encode()
        self.crystal = _crystal(canonical)

    def save(self, root: Optional[Path] = None) -> Path:
        root = root or THIRD_PARTY_ROOT
        dir_path = root / self.service
        dir_path.mkdir(parents=True, exist_ok=True)
        fname = f"{self.vm_id}.{self.service}.{self.action}.{self.name}.{self.state}.{self.version}.json"
        path = dir_path / fname
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        return path


@dataclass
class SendResult:
    success: bool
    crystal_id: str
    service: str
    recipient: str
    message_preview: str
    timestamp: str
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class ThirdPartyConnector(ABC):
    """Abstract outbound connector."""

    SERVICE: str = ""

    def __init__(self, config: ConnectionConfig):
        self.config = config
        self._connected = False
        self._last_send_ts: float = 0.0

    @abstractmethod
    def connect(self) -> str:
        """Validate credentials, return crystal hash of connection event."""
        ...

    @abstractmethod
    def send(self, recipient: str, message: str, **kwargs) -> SendResult:
        """Send a message. Returns SendResult with crystal_id."""
        ...

    @abstractmethod
    def history(self, thread_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Fetch recent messages from a thread/channel/conversation."""
        ...

    @abstractmethod
    def disconnect(self) -> str:
        """Graceful disconnect, return crystal hash."""
        ...

    def _rate_limit_wait(self) -> None:
        rpm = self.config.limits.get("requests_per_minute", 60)
        interval = 60.0 / max(rpm, 1)
        now = time.time()
        elapsed = now - self._last_send_ts
        if elapsed < interval:
            time.sleep(interval - elapsed)
        self._last_send_ts = time.time()

    def _log_send(self, result: SendResult) -> None:
        """Append-only JSONL log of every outbound send."""
        log_dir = Path.home() / ".cc" / "third_party_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{self.SERVICE}_sends.jsonl"
        record = {
            "crystal_id": result.crystal_id,
            "service": self.SERVICE,
            "recipient": result.recipient,
            "preview": result.message_preview,
            "success": result.success,
            "timestamp": result.timestamp,
            "error": result.error,
            "metadata": result.metadata,
        }
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True, default=str) + "\n")
