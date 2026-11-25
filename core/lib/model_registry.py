#!/usr/bin/env python3
# ============================================================================
# AGENT CARD                                                                  =
# ----------------------------------------------------------------------------=
# name:        model_registry                                                 =
# role:        REGISTRY · MODEL_LOOKUP                                        =
# tier:        L0                                                             =
# substrate:   studio/models/registry.json (read-only consumer)              =
# engine:      stateless dataclass-backed query (ModelCard); loads lazily    =
# storage:     reads studio/models/registry.json only — writes nothing       =
# card:        studio/assets/_agents/agent_defs/                              =
#              vm_mspc_001.agents.agent_defs.model_registry.active.json       =
# ----------------------------------------------------------------------------=
# ROUTING CONNECTIONS                                                         =
# ----------------------------------------------------------------------------=
# inbound:                                                                    =
#   - token_router.ModelRouter  (imports ModelRegistry + ModelCard for       =
#                                tier → model resolution)                     =
#   - chat.py                   (transitively via token_router)              =
#   - forward_projector         (CC_TINY_MODEL picks default from registry)  =
# outbound:                                                                   =
#   - std json + pathlib  (no subprocess, no network)                         =
# substrate touch:                                                            =
#   - reads:  studio/models/registry.json                                     =
#   - writes: none                                                            =
# produced by:                                                                =
#   - model_installer.py (writes the registry this module reads)              =
# ============================================================================
"""model_registry.py — deterministic model registry interface.

Reads studio/models/registry.json and provides:
  - lookup by name, brand, category, subtype, tag
  - tier resolution (tiny/medium/large/epic)
  - VRAM budgeting and quantization selection
  - deterministic model selection for token_router
"""
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Dict, Any

STUDIO_ROOT = Path(__file__).parent.parent.parent / "studio"
REGISTRY_PATH = STUDIO_ROOT / "models" / "registry.json"
ROLE_MAP_PATH = STUDIO_ROOT / "models" / "role_map.json"


def load_role_map() -> Dict[str, Any]:
    """task_kind → routing target ('models plugged in where they belong').
    Returns {} if the map is missing so callers fall back to defaults."""
    try:
        return json.loads(ROLE_MAP_PATH.read_text())
    except Exception:
        return {}


def resolve_role(task_kind: str) -> Dict[str, Any]:
    """Return the routing target for a task kind (chat/code/image/3d/tweet/...).

    Unknown kinds fall back to the map's default_role (chat). The returned dict
    carries target=provider|connector|endpoint plus the specifics model_api or a
    connector dispatcher needs. Pure data — no network, no model load."""
    m = load_role_map()
    roles = m.get("roles", {})
    if task_kind in roles:
        return {"role": task_kind, **roles[task_kind]}
    default = m.get("default_role", "chat")
    return {"role": default, **roles.get(default, {"target": "provider", "provider": "deepseek-chat", "family": "chat", "cost_class": "cheap"})}


@dataclass
class ModelCard:
    asset_id: str
    crystal: str
    vm_id: str
    brand: str
    category: str
    subtype: str
    name: str
    display_name: str
    context_window: int
    quantization: str
    vram_gb: float
    state: str
    version: str
    path: str
    tags: List[str]

    @property
    def tier(self) -> str:
        """Resolve tier from tags."""
        for t in ("tiny", "medium", "large", "epic"):
            if t in self.tags:
                return t
        return "medium"

    @property
    def is_local(self) -> bool:
        return "local" in self.tags

    @property
    def is_cloud(self) -> bool:
        return "cloud" in self.tags


class ModelRegistry:
    """Deterministic model registry."""

    def __init__(self, registry_path: Optional[Path] = None):
        self.registry_path = registry_path or REGISTRY_PATH
        self._models: List[ModelCard] = []
        self._load()

    def _load(self) -> None:
        if not self.registry_path.exists():
            return
        data = json.loads(self.registry_path.read_text())
        for m in data.get("models", []):
            self._models.append(ModelCard(**m))

    def save(self) -> None:
        data = {
            "_schema": "model_registry_v1",
            "last_updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "models": [self._card_to_dict(m) for m in self._models],
        }
        self.registry_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @staticmethod
    def _card_to_dict(m: ModelCard) -> dict:
        return {
            "asset_id": m.asset_id,
            "crystal": m.crystal,
            "vm_id": m.vm_id,
            "brand": m.brand,
            "category": m.category,
            "subtype": m.subtype,
            "name": m.name,
            "display_name": m.display_name,
            "context_window": m.context_window,
            "quantization": m.quantization,
            "vram_gb": m.vram_gb,
            "state": m.state,
            "version": m.version,
            "path": m.path,
            "tags": m.tags,
        }

    def all(self) -> List[ModelCard]:
        return [m for m in self._models if m.state == "active"]

    def by_name(self, name: str) -> Optional[ModelCard]:
        for m in self.all():
            if m.name == name:
                return m
        return None

    def by_brand(self, brand: str) -> List[ModelCard]:
        return [m for m in self.all() if m.brand == brand]

    def by_category(self, category: str) -> List[ModelCard]:
        return [m for m in self.all() if m.category == category]

    def by_subtype(self, subtype: str) -> List[ModelCard]:
        return [m for m in self.all() if m.subtype == subtype]

    def by_tag(self, tag: str) -> List[ModelCard]:
        return [m for m in self.all() if tag in m.tags]

    def by_tier(self, tier: str) -> List[ModelCard]:
        return [m for m in self.all() if m.tier == tier]

    def resolve_for_tokens(self, tokens: int, prefer_local: bool = True) -> Optional[ModelCard]:
        """Pick the best active model for a given token count."""
        candidates = self.all()
        if prefer_local:
            candidates = [c for c in candidates if c.is_local] + [c for c in candidates if c.is_cloud]
        else:
            candidates = [c for c in candidates if c.is_cloud] + [c for c in candidates if c.is_local]

        for c in candidates:
            if tokens <= c.context_window:
                return c
        # Fallback: largest context window
        if candidates:
            return max(candidates, key=lambda x: x.context_window)
        return None

    def vram_budget(self, available_gb: float) -> List[ModelCard]:
        """Return all models that fit in available VRAM."""
        return [m for m in self.all() if m.vram_gb <= available_gb]

    def list_brands(self) -> List[str]:
        return sorted({m.brand for m in self._models})

    def list_categories(self) -> List[str]:
        return sorted({m.category for m in self._models})

    def list_subtypes(self) -> List[str]:
        return sorted({m.subtype for m in self._models})

    def list_tags(self) -> List[str]:
        tags: set = set()
        for m in self._models:
            tags.update(m.tags)
        return sorted(tags)


def main():
    import argparse
    import time
    ap = argparse.ArgumentParser(description="model registry — deterministic model lookup")
    ap.add_argument("--list", action="store_true", help="list all active models")
    ap.add_argument("--by-brand", help="filter by brand")
    ap.add_argument("--by-category", help="filter by category")
    ap.add_argument("--by-subtype", help="filter by subtype")
    ap.add_argument("--by-tag", help="filter by tag")
    ap.add_argument("--by-tier", help="filter by tier")
    ap.add_argument("--resolve-tokens", type=int, help="resolve model for token count")
    ap.add_argument("--vram-budget", type=float, help="filter by available VRAM (GB)")
    ap.add_argument("--name", help="lookup specific model by name")
    ap.add_argument("--json", action="store_true", help="output as JSON")
    args = ap.parse_args()

    reg = ModelRegistry()

    if args.name:
        m = reg.by_name(args.name)
        if m:
            print(json.dumps(ModelRegistry._card_to_dict(m), indent=2))
        else:
            print(json.dumps({"error": "not found"}, indent=2))
        return

    models = reg.all()
    if args.by_brand:
        models = [m for m in models if m.brand == args.by_brand]
    if args.by_category:
        models = [m for m in models if m.category == args.by_category]
    if args.by_subtype:
        models = [m for m in models if m.subtype == args.by_subtype]
    if args.by_tag:
        models = [m for m in models if args.by_tag in m.tags]
    if args.by_tier:
        models = [m for m in models if m.tier == args.by_tier]
    if args.vram_budget is not None:
        models = [m for m in models if m.vram_gb <= args.vram_budget]

    if args.resolve_tokens:
        m = reg.resolve_for_tokens(args.resolve_tokens)
        if m:
            print(json.dumps(ModelRegistry._card_to_dict(m), indent=2))
        else:
            print(json.dumps({"error": "no model fits"}, indent=2))
        return

    if args.json:
        print(json.dumps([ModelRegistry._card_to_dict(m) for m in models], indent=2))
    else:
        print(f"{'NAME':30} {'BRAND':12} {'CATEGORY':16} {'SUBTYPE':10} {'TIER':8} {'CTX':8} {'VRAM':6}")
        print("-" * 90)
        for m in models:
            print(f"{m.name:30} {m.brand:12} {m.category:16} {m.subtype:10} {m.tier:8} {m.context_window:8} {m.vram_gb:6.1f}")


if __name__ == "__main__":
    main()
