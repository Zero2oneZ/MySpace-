#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        cloud_providers
# role:        REGISTRY · UNIFIED_PROVIDER_TAXONOMY
# tier:        L0
# substrate:   the single source of truth for "what providers exist + their
#              cost / latency / tier metadata"
# storage:     in-memory tuple (no DB); rebuilt every import
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - core/lib/model_api.py (reads PROVIDERS, calls pick_provider)
#   - core/lib/router_policy.py (when Phase 1 #57 lands)
#   - studio_runtime._dispatch_cloud (reads spec by name)
# outbound:
#   - none (pure data layer)
# substrate touch:
#   - reads: keys.upstream_key(name) to check whether the provider's auth is present
# ----------------------------------------------------------------------------
# KIND vocabulary
# ----------------------------------------------------------------------------
#   hf_router               19 providers behind router.huggingface.co/v1
#   openai_compat           direct OpenAI-shape REST (DeepSeek, future Together direct)
#   hf_inference_endpoint   one persistent deployed model (per-data endpoint)
#   local_ollama            local Ollama server
#   local_gpu               local CUDA / direct torch / diffusers
#   browser_ws              chromium WebGPU worker via weave fabric (placeholder)
#   droplet_http            DigitalOcean droplet remote dispatch (placeholder)
#   zerogpu_space           HF Spaces with @spaces.GPU(...)  (placeholder)
# ============================================================================
"""cloud_providers.py — the provider taxonomy.

`ProviderSpec` is the canonical row. `PROVIDERS` is the immutable tuple of all
specs. Three convenience lookups:

  get(name)        -> ProviderSpec | None
  list_by_tier(t)  -> Tuple[ProviderSpec, ...]
  pick(...)        -> Tuple[ProviderSpec, ...]   ranked candidates for a request

model_api.py reads this registry once on import and consults `pick()` per call.
router_policy.py (when Phase 1 lands) will subsume `pick()` with full decision
tree; for v1, pick() returns a sensible fallback ladder.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple


_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent


# ---------------------------------------------------------------------------
# Spec
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProviderSpec:
    """Single immutable row in the provider taxonomy.

    `key_env` may be one of:
      - empty string  → no auth needed
      - env-var name (string) → require that env var to be non-empty
      - "_NONE_"      → explicitly no auth, but distinguishable from missing
    """
    name: str
    kind: str
    endpoint: str
    key_env: str = ""                 # which env var unlocks it (or "" if free)
    cost_per_million_in: float = 0.0   # USD per 1M input tokens (0 = free or n/a)
    cost_per_million_out: float = 0.0  # USD per 1M output tokens
    max_context: int = 0               # tokens; 0 = unknown
    rate_limit_per_minute: int = 0     # 0 = unknown / no client-side limit
    tier: str = "free"                 # free | cheap | fast | premium
    priority_speed: int = 50           # higher = picked first when latency matters
    priority_cost: int = 50            # higher = picked first when cost matters
    families: Tuple[str, ...] = ("chat",)   # text | embed | image | audio | 3d | code | chat
    supports_streaming: bool = True
    notes: str = ""

    @property
    def is_active(self) -> bool:
        """Auth check — does the env var that unlocks this provider exist + non-empty?"""
        if not self.key_env or self.key_env == "_NONE_":
            return True
        try:
            sys.path.insert(0, str(_PROJECT_ROOT / "studio"))
            from auth.keys import load_env  # type: ignore
            env = load_env()
        except Exception:
            env = dict(os.environ)
        return bool(env.get(self.key_env, "").strip())


# ---------------------------------------------------------------------------
# PROVIDERS — the canonical registry
# ---------------------------------------------------------------------------

PROVIDERS: Tuple[ProviderSpec, ...] = (
    # ---- direct OpenAI-compatible (live: DeepSeek) ----
    ProviderSpec(
        name="deepseek-chat",
        kind="openai_compat",
        endpoint="https://api.deepseek.com/v1",
        key_env="DEEPSEEK_API_KEY",
        cost_per_million_in=0.27,
        cost_per_million_out=1.10,
        max_context=128_000,
        rate_limit_per_minute=60,
        tier="cheap",
        priority_speed=70,
        priority_cost=90,
        families=("chat", "text"),
        notes="LIVE. Default cheap-tier general-purpose chat.",
    ),
    ProviderSpec(
        name="deepseek-coder",
        kind="openai_compat",
        endpoint="https://api.deepseek.com/v1",
        key_env="DEEPSEEK_API_KEY",
        cost_per_million_in=0.27,
        cost_per_million_out=1.10,
        max_context=64_000,
        rate_limit_per_minute=60,
        tier="cheap",
        priority_speed=70,
        priority_cost=90,
        families=("code", "text"),
        notes="LIVE. Specialized code-completion variant of deepseek.",
    ),
    ProviderSpec(
        name="deepseek-reasoner",
        kind="openai_compat",
        endpoint="https://api.deepseek.com/v1",
        key_env="DEEPSEEK_API_KEY",
        cost_per_million_in=0.55,
        cost_per_million_out=2.19,
        max_context=64_000,
        rate_limit_per_minute=30,
        tier="cheap",
        priority_speed=40,
        priority_cost=75,
        families=("chat", "text"),
        notes="LIVE. R1-style chain-of-thought; slower but stronger reasoning.",
    ),

    # ---- HuggingFace router (19 partner providers, picked by name) ----
    ProviderSpec(
        name="hf:groq",
        kind="hf_router",
        endpoint="https://router.huggingface.co/v1",
        key_env="HF_TOKEN",
        tier="fast",
        priority_speed=95,
        priority_cost=70,
        families=("chat", "text"),
        notes="LIVE via hf_hub. Sub-second first-token. Free tier generous.",
    ),
    ProviderSpec(
        name="hf:cerebras",
        kind="hf_router",
        endpoint="https://router.huggingface.co/v1",
        key_env="HF_TOKEN",
        tier="fast",
        priority_speed=98,
        priority_cost=60,
        families=("chat", "text"),
        notes="LIVE via hf_hub. Fastest tokens/sec available.",
    ),
    ProviderSpec(
        name="hf:fireworks-ai",
        kind="hf_router",
        endpoint="https://router.huggingface.co/v1",
        key_env="HF_TOKEN",
        tier="fast",
        priority_speed=85,
        priority_cost=65,
        families=("chat", "text", "code"),
        notes="LIVE via hf_hub. Large-context strong.",
    ),
    ProviderSpec(
        name="hf:together",
        kind="hf_router",
        endpoint="https://router.huggingface.co/v1",
        key_env="HF_TOKEN",
        tier="cheap",
        priority_speed=75,
        priority_cost=80,
        families=("chat", "text", "code"),
        notes="LIVE via hf_hub.",
    ),
    ProviderSpec(
        name="hf:novita",
        kind="hf_router",
        endpoint="https://router.huggingface.co/v1",
        key_env="HF_TOKEN",
        tier="cheap",
        priority_speed=60,
        priority_cost=80,
        families=("chat", "text"),
        notes="LIVE via hf_hub.",
    ),
    ProviderSpec(
        name="hf:deepinfra",
        kind="hf_router",
        endpoint="https://router.huggingface.co/v1",
        key_env="HF_TOKEN",
        tier="cheap",
        priority_speed=70,
        priority_cost=85,
        families=("chat", "text"),
        notes="LIVE via hf_hub. Often hosts DeepSeek mirrors.",
    ),
    ProviderSpec(
        name="hf:hf-inference",
        kind="hf_router",
        endpoint="https://router.huggingface.co/v1",
        key_env="HF_TOKEN",
        tier="free",
        priority_speed=50,
        priority_cost=99,
        families=("chat", "text"),
        notes="LIVE via hf_hub. Canonical HF fallback (most generous free tier).",
    ),

    # ---- placeholders for Phase 4 of plan (not yet wired) ----
    ProviderSpec(
        name="zerogpu",
        kind="zerogpu_space",
        endpoint="https://huggingface.co/spaces/{namespace}/{space}",
        key_env="HF_TOKEN",
        tier="free",
        priority_speed=30,
        priority_cost=99,
        families=("chat", "image", "embed"),
        rate_limit_per_minute=20,
        notes="PLACEHOLDER (Phase 4 C.1). Free A100 hours via HF Spaces.",
    ),
    ProviderSpec(
        name="droplet",
        kind="droplet_http",
        endpoint="http://127.0.0.1:8081",
        key_env="DROPLET_REMOTE_BASE_URL",
        tier="cheap",
        priority_speed=20,
        priority_cost=95,
        families=("chat", "text"),
        rate_limit_per_minute=20,
        notes="PLACEHOLDER (Phase 4 C.2). DO droplet CPU fallback over WireGuard.",
    ),
    ProviderSpec(
        name="browser",
        kind="browser_ws",
        endpoint="ws://127.0.0.1:8767/worker/dispatch",
        key_env="_NONE_",
        tier="free",
        priority_speed=10,
        priority_cost=99,
        families=("embed", "text"),
        notes="PLACEHOLDER (Phase 4 C.3). Chromium WebGPU workers via weave.",
    ),
    ProviderSpec(
        name="ollama-local",
        kind="local_ollama",
        endpoint="http://127.0.0.1:11434/v1",
        key_env="_NONE_",
        tier="free",
        priority_speed=55,
        priority_cost=99,
        families=("chat", "text", "code"),
        notes="LIVE if Ollama is running locally.",
    ),
    ProviderSpec(
        name="hf-endpoint:default",
        kind="hf_inference_endpoint",
        endpoint="https://<endpoint_name>.<region>.aws.endpoints.huggingface.cloud/v1",
        key_env="HF_TOKEN",
        tier="cheap",
        priority_speed=80,
        priority_cost=70,
        families=("chat", "embed"),
        notes="PLACEHOLDER (Phase D.6). Per-data deployed endpoint; one per modality.",
    ),
)


HF_INFERENCE_SPECS: Tuple[ProviderSpec, ...] = tuple(
    p for p in PROVIDERS if p.kind == "hf_router"
)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get(name: str) -> Optional[ProviderSpec]:
    for p in PROVIDERS:
        if p.name == name:
            return p
    return None


def list_by_tier(tier: str) -> Tuple[ProviderSpec, ...]:
    return tuple(p for p in PROVIDERS if p.tier == tier)


def list_by_family(family: str) -> Tuple[ProviderSpec, ...]:
    return tuple(p for p in PROVIDERS if family in p.families)


def list_by_kind(kind: str) -> Tuple[ProviderSpec, ...]:
    return tuple(p for p in PROVIDERS if p.kind == kind)


def list_active() -> Tuple[ProviderSpec, ...]:
    return tuple(p for p in PROVIDERS if p.is_active)


# ---------------------------------------------------------------------------
# pick() — v1 simplified fallback ladder
# ---------------------------------------------------------------------------

def pick(family: str = "chat",
          cost_class: str = "cheap",
          latency_budget_ms: Optional[int] = None,
          require_streaming: bool = False,
          must_run_local: bool = False,
          only_active: bool = True) -> Tuple[ProviderSpec, ...]:
    """Return a ranked list of candidate providers. Caller iterates and tries
    each until one succeeds. v1 logic — Phase 1 #57 router_policy.choose will
    subsume this with full decision tree."""
    cands: List[ProviderSpec] = [p for p in PROVIDERS if family in p.families]
    if only_active:
        cands = [p for p in cands if p.is_active]
    if must_run_local:
        cands = [p for p in cands if p.kind in ("local_ollama", "local_gpu", "browser_ws")]
    if require_streaming:
        cands = [p for p in cands if p.supports_streaming]

    if latency_budget_ms is not None and latency_budget_ms <= 800:
        # Fast lane — pin to fast tier
        cands = [p for p in cands if p.tier == "fast"]
        cands.sort(key=lambda p: -p.priority_speed)
        return tuple(cands)

    # Tier-aware ranking
    tier_order = {
        "free":    ["free", "cheap", "fast", "premium"],
        "cheap":   ["cheap", "free", "fast", "premium"],
        "fast":    ["fast", "cheap", "free", "premium"],
        "premium": ["premium", "fast", "cheap", "free"],
    }.get(cost_class, ["cheap", "free", "fast", "premium"])

    def rank_key(p: ProviderSpec) -> Tuple[int, int]:
        tier_rank = tier_order.index(p.tier) if p.tier in tier_order else 99
        # Within same tier, prefer cheaper-or-faster depending on class
        secondary = (-p.priority_cost if cost_class in ("free", "cheap")
                       else -p.priority_speed)
        return (tier_rank, secondary)

    cands.sort(key=rank_key)
    return tuple(cands)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> None:
    import argparse
    import json
    ap = argparse.ArgumentParser(description="cloud_providers — taxonomy registry")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("list", help="list all providers")
    sub.add_parser("active", help="list providers whose auth env is present")
    p_get = sub.add_parser("get")
    p_get.add_argument("name")
    p_pick = sub.add_parser("pick")
    p_pick.add_argument("--family", default="chat")
    p_pick.add_argument("--cost-class", default="cheap",
                          choices=["free", "cheap", "fast", "premium"])
    p_pick.add_argument("--latency-budget-ms", type=int, default=None)
    p_pick.add_argument("--limit", type=int, default=8)
    sub.add_parser("stats", help="summary counts by tier + kind")

    args = ap.parse_args()

    def _to_dict(p: ProviderSpec) -> dict:
        return {
            "name": p.name, "kind": p.kind, "endpoint": p.endpoint,
            "tier": p.tier, "families": list(p.families),
            "cost_per_million_in": p.cost_per_million_in,
            "cost_per_million_out": p.cost_per_million_out,
            "priority_speed": p.priority_speed,
            "priority_cost": p.priority_cost,
            "is_active": p.is_active,
            "notes": p.notes,
        }

    if args.cmd == "list":
        print(json.dumps([_to_dict(p) for p in PROVIDERS], indent=2))

    elif args.cmd == "active":
        print(json.dumps([_to_dict(p) for p in list_active()], indent=2))

    elif args.cmd == "get":
        p = get(args.name)
        if p:
            print(json.dumps(_to_dict(p), indent=2))
        else:
            print(json.dumps({"error": "not found"}))

    elif args.cmd == "pick":
        cands = pick(family=args.family, cost_class=args.cost_class,
                       latency_budget_ms=args.latency_budget_ms)
        out = [_to_dict(p) for p in cands[: args.limit]]
        print(json.dumps({"ranked_candidates": out, "total": len(cands)}, indent=2))

    elif args.cmd == "stats":
        tiers: dict = {}
        kinds: dict = {}
        active = 0
        for p in PROVIDERS:
            tiers[p.tier] = tiers.get(p.tier, 0) + 1
            kinds[p.kind] = kinds.get(p.kind, 0) + 1
            if p.is_active:
                active += 1
        print(json.dumps({
            "total_providers": len(PROVIDERS),
            "active": active,
            "by_tier": tiers,
            "by_kind": kinds,
        }, indent=2))

    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
