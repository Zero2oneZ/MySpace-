#!/usr/bin/env python3
"""registry.py — EndpointRegistry: single source of truth for all inbound endpoints.

Mirrors model_registry.py pattern:
  - scan studio/endpoints/{kind}/ for config JSONs
  - build runtime index
  - provide lookup by kind, service, tag, state
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import List, Optional, Dict, Any

STUDIO_ROOT = Path(os.environ.get("STUDIO_ROOT", "/data/Projects/MySpace++/studio"))
ENDPOINTS_ROOT = STUDIO_ROOT / "endpoints"
REGISTRY_PATH = ENDPOINTS_ROOT / "registry.json"


class EndpointRegistry:
    """Deterministic endpoint registry."""

    def __init__(self, root: Optional[Path] = None, registry_path: Optional[Path] = None):
        self.root = root or ENDPOINTS_ROOT
        self.registry_path = registry_path or REGISTRY_PATH
        self._entries: List[Dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if self.registry_path.exists():
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
            self._entries = data.get("endpoints", [])

    def sync(self) -> Dict[str, int]:
        """Rebuild registry by scanning disk."""
        self._entries.clear()
        if not self.root.exists():
            return {"endpoints": 0, "kinds": 0}
        kinds = set()
        for kind_dir in self.root.iterdir():
            if not kind_dir.is_dir() or kind_dir.name == "routes":
                continue
            kinds.add(kind_dir.name)
            for f in kind_dir.glob("*.json"):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    entry = {
                        "asset_id": data.get("asset_id", f.name),
                        "crystal": data.get("crystal", ""),
                        "kind": data.get("kind", kind_dir.name),
                        "service": data.get("service", ""),
                        "name": data.get("name", ""),
                        "state": data.get("state", "active"),
                        "version": data.get("version", "v0"),
                        "path": str(f.relative_to(self.root)),
                        "routing_tags": data.get("routing_tags", []),
                    }
                    self._entries.append(entry)
                except Exception:
                    continue
        self._save()
        return {"endpoints": len(self._entries), "kinds": len(kinds)}

    def _save(self) -> None:
        data = {
            "_schema": "endpoint_registry_v1",
            "last_updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "endpoints": self._entries,
        }
        self.registry_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def list(self, kind: Optional[str] = None, service: Optional[str] = None, state: Optional[str] = None, tag: Optional[str] = None) -> List[Dict[str, Any]]:
        out = []
        for e in self._entries:
            if kind and e.get("kind") != kind:
                continue
            if service and e.get("service") != service:
                continue
            if state and e.get("state") != state:
                continue
            if tag and tag not in e.get("routing_tags", []):
                continue
            out.append(e)
        return out

    def by_name(self, name: str) -> Optional[Dict[str, Any]]:
        for e in self._entries:
            if e.get("name") == name:
                return e
        return None

    def by_asset_id(self, asset_id: str) -> Optional[Dict[str, Any]]:
        for e in self._entries:
            if e.get("asset_id") == asset_id:
                return e
        return None
