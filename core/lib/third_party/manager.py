#!/usr/bin/env python3
"""manager.py — ThirdPartyManager: one interface for all outbound platforms.

Loads configs from studio/third_party/{service}/, instantiates connectors,
routes messages by tag/tier, and logs everything append-only.

Usage:
    mgr = ThirdPartyManager()
    mgr.load_all()
    mgr.send("discord", channel_id, "Hello from cc")
    mgr.send_by_tag("broadcast", "System alert: build complete")
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Any

from .base import ConnectionConfig, SendResult, ThirdPartyConnector, THIRD_PARTY_ROOT

# Lazy imports for optional deps
_CONNECTORS: Dict[str, Any] = {}


def _import_connectors():
    global _CONNECTORS
    if _CONNECTORS:
        return
    # Try importing each connector; stub if deps missing
    try:
        from .discord import DiscordConnector
        _CONNECTORS["discord"] = DiscordConnector
    except Exception:
        pass
    try:
        from .telegram import TelegramConnector
        _CONNECTORS["telegram"] = TelegramConnector
    except Exception:
        pass
    try:
        from .whatsapp import WhatsAppConnector
        _CONNECTORS["whatsapp"] = WhatsAppConnector
    except Exception:
        pass
    try:
        from .twitter import TwitterConnector
        _CONNECTORS["twitter"] = TwitterConnector
    except Exception:
        pass
    try:
        from .facebook import FacebookConnector
        _CONNECTORS["facebook"] = FacebookConnector
    except Exception:
        pass
    # If none imported, register stubs
    for svc in ("discord", "telegram", "whatsapp", "twitter", "facebook"):
        if svc not in _CONNECTORS:
            _CONNECTORS[svc] = _StubConnector


class _StubConnector(ThirdPartyConnector):
    """Fallback connector when deps are missing — logs the attempt but does not send."""

    def connect(self) -> str:
        self._connected = True
        return "stub_connected"

    def send(self, recipient: str, message: str, **kwargs) -> SendResult:
        self._rate_limit_wait()
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        result = SendResult(
            success=False,
            crystal_id="stub_" + str(hash(recipient + message + ts)),
            service=self.SERVICE,
            recipient=recipient,
            message_preview=message[:120],
            timestamp=ts,
            error="StubConnector: install dependencies to enable real sends",
        )
        self._log_send(result)
        return result

    def history(self, thread_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        return []

    def disconnect(self) -> str:
        self._connected = False
        return "stub_disconnected"


class ThirdPartyManager:
    """Central manager for all outbound third-party connectivity."""

    def __init__(self, root: Optional[Path] = None):
        self.root = root or THIRD_PARTY_ROOT
        self._configs: Dict[str, List[ConnectionConfig]] = {}
        self._instances: Dict[str, List[ThirdPartyConnector]] = {}
        _import_connectors()

    def load_all(self) -> "ThirdPartyManager":
        """Scan studio/third_party/{service}/*.json and load active configs."""
        if not self.root.exists():
            return self
        for svc_dir in self.root.iterdir():
            if not svc_dir.is_dir():
                continue
            svc = svc_dir.name
            self._configs[svc] = []
            self._instances[svc] = []
            for f in svc_dir.glob("*.json"):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    cfg = ConnectionConfig(**data)
                    if cfg.state == "active":
                        self._configs[svc].append(cfg)
                        cls = _CONNECTORS.get(svc, _StubConnector)
                        inst = cls(cfg)
                        inst.connect()
                        self._instances[svc].append(inst)
                except Exception:
                    continue
        return self

    def services(self) -> List[str]:
        return sorted(self._configs.keys())

    def configs(self, service: Optional[str] = None) -> List[ConnectionConfig]:
        if service:
            return list(self._configs.get(service, []))
        out: List[ConnectionConfig] = []
        for lst in self._configs.values():
            out.extend(lst)
        return out

    def send(self, service: str, recipient: str, message: str, **kwargs) -> List[SendResult]:
        """Send via every active connector for a service."""
        results: List[SendResult] = []
        for inst in self._instances.get(service, []):
            results.append(inst.send(recipient, message, **kwargs))
        return results

    def send_by_tag(self, tag: str, message: str, recipient: Optional[str] = None, **kwargs) -> Dict[str, List[SendResult]]:
        """Broadcast to every active connector whose config has the tag."""
        out: Dict[str, List[SendResult]] = {}
        for svc, insts in self._instances.items():
            for inst in insts:
                if tag in inst.config.routing_tags:
                    rec = recipient or inst.config.auth.get("default_recipient", "")
                    out.setdefault(svc, []).append(inst.send(rec, message, **kwargs))
        return out

    def history(self, service: str, thread_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for inst in self._instances.get(service, []):
            out.extend(inst.history(thread_id, limit))
        return out

    def disconnect_all(self) -> None:
        for svc, insts in self._instances.items():
            for inst in insts:
                try:
                    inst.disconnect()
                except Exception:
                    pass
        self._instances.clear()

    def add_config(self, cfg: ConnectionConfig) -> Path:
        """Save a new config to disk and (if active) instantiate it."""
        path = cfg.save(self.root)
        svc = cfg.service
        if cfg.state == "active":
            self._configs.setdefault(svc, []).append(cfg)
            cls = _CONNECTORS.get(svc, _StubConnector)
            inst = cls(cfg)
            inst.connect()
            self._instances.setdefault(svc, []).append(inst)
        return path

    def archive_config(self, asset_id: str) -> Optional[Path]:
        """Change state to archived by moving the file on disk."""
        for svc_dir in self.root.iterdir():
            if not svc_dir.is_dir():
                continue
            for f in svc_dir.glob("*.json"):
                if asset_id in f.name:
                    new_name = f.name.replace(".active.", ".archived.")
                    dest = f.parent / new_name
                    f.rename(dest)
                    # Reload
                    self.load_all()
                    return dest
        return None

    def status(self) -> Dict[str, Any]:
        """Quick health check of all loaded connectors."""
        return {
            "services": {
                svc: {
                    "active_configs": len(self._configs.get(svc, [])),
                    "connected_instances": len(self._instances.get(svc, [])),
                }
                for svc in self.services()
            },
            "total_active": sum(len(v) for v in self._configs.values()),
        }
