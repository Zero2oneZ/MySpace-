#!/usr/bin/env python3
# ============================================================================
# AGENT CARD                                                                  =
# ----------------------------------------------------------------------------=
# name:        token_router                                                   =
# role:        ROUTER · TOKEN_BUDGET_ROUTING                                  =
# tier:        L0                                                             =
# substrate:   studio/models/registry.json (via model_registry, read-only)   =
# engine:      tiktoken cl100k_base bucket → tier → ModelRegistry lookup     =
# storage:     none directly (model_registry handles the registry I/O)       =
# card:        studio/assets/_agents/agent_defs/                              =
#              vm_mspc_001.agents.agent_defs.token_router.active.json         =
# ----------------------------------------------------------------------------=
# ROUTING CONNECTIONS                                                         =
# ----------------------------------------------------------------------------=
# inbound:                                                                    =
#   - chat.py::cmd_full     (step 3: tier resolution)                         =
#   - chat.py::cmd_godot    (route + downward_dispatch)                       =
#   - chat.py::cmd_route    (standalone routing)                              =
#   - chat.py::cmd_downward (downward_dispatch from parent tier)              =
# outbound:                                                                   =
#   - model_registry.ModelRegistry.find_for_tier (name resolution)           =
#   - tiktoken.get_encoding('cl100k_base') (when available)                   =
# substrate touch:                                                            =
#   - reads:  studio/models/registry.json (transitively via model_registry)   =
#   - writes: none                                                            =
# tier buckets:                                                               =
#   - tiny   ≤ 4k    medium 4k-32k    large 32k-128k    epic > 128k           =
# non-overriding:                                                             =
#   - MoE expert matches do NOT change routing decisions; routing is purely  =
#     token-bucket. Smartness from MoE comes via prompt enrichment, not       =
#     model selection.                                                        =
# ============================================================================
"""token_router.py — deterministic token counting + model selection by scope budget.

Reads from studio/models/registry.json for canonical model lists.
Hierarchical dispatch:
  · tiny   (≤4k tokens)  → fast local model, narrow scope, single operation
  · medium (4k–32k)      → local medium model, multi-step chain, cross-pass context
  · large  (32k–128k)    → frontier model, broad scope, synthesis, downward dispatch
  · epic   (>128k)       → frontier model with chain-of-thought, generates sub-plans

Determinism: same prompt + same config = same model selection, byte-for-byte.
"""
import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Dict, Tuple

# Try tiktoken for exact counts; fall back to deterministic char heuristic.
try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")
    _HAS_TIKTOKEN = True
except Exception:
    _ENC = None
    _HAS_TIKTOKEN = False


CC_HOME = Path(os.environ.get("CC_HOME", str(Path.home() / ".cc")))
CONFIG_PATH = CC_HOME / "chat_model_router.json"

# Import model registry for canonical model resolution
_LIB = Path(__file__).parent.resolve()
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))
from model_registry import ModelRegistry, ModelCard


@dataclass
class ModelTier:
    name: str
    model_id: str
    token_min: int
    token_max: int
    complexity_max: float   # 0.0–1.0; higher complexity can push up a tier
    scope: str            # narrow | medium | broad | epic
    blind_to: List[str]   # tier names this tier must NOT see outputs from
    description: str


def _default_tier_model(tier: str) -> str:
    """Resolve default model for a tier from the canonical registry."""
    reg = ModelRegistry()
    models = reg.by_tier(tier)
    if models:
        # Prefer local for tiny/medium, cloud for large/epic
        for m in models:
            if tier in ("tiny", "medium") and m.is_local:
                return m.name
            if tier in ("large", "epic") and m.is_cloud:
                return m.name
        return models[0].name
    # Fallback to env vars
    return {
        "tiny": os.environ.get("CC_TINY_MODEL", "qwen2.5-coder:1.5b"),
        "medium": os.environ.get("CC_MODEL", "qwen3-coder-next:latest"),
        "large": os.environ.get("CC_CLOUD_MODEL", "claude-sonnet-4-6"),
        "epic": os.environ.get("CC_EPIC_MODEL", "claude-opus-4-7"),
    }.get(tier, "qwen2.5-coder:1.5b")


DEFAULT_TIERS: List[ModelTier] = [
    ModelTier(
        name="tiny",
        model_id=_default_tier_model("tiny"),
        token_min=0,
        token_max=4096,
        complexity_max=0.4,
        scope="narrow",
        blind_to=["medium", "large", "epic"],
        description="Fast local model for single-step classification, spell-fix, token count",
    ),
    ModelTier(
        name="medium",
        model_id=_default_tier_model("medium"),
        token_min=4097,
        token_max=32768,
        complexity_max=0.7,
        scope="medium",
        blind_to=["large", "epic"],
        description="Local model for multi-step chains, cross-pass context, GUI prediction",
    ),
    ModelTier(
        name="large",
        model_id=_default_tier_model("large"),
        token_min=32769,
        token_max=131072,
        complexity_max=0.95,
        scope="broad",
        blind_to=["epic"],
        description="Frontier model for synthesis, architecture design, audit",
    ),
    ModelTier(
        name="epic",
        model_id=_default_tier_model("epic"),
        token_min=131073,
        token_max=999999,
        complexity_max=1.0,
        scope="epic",
        blind_to=[],
        description="Highest-capability model; generates sub-plans and dispatches downward",
    ),
]


class TokenCounter:
    """Deterministic token counter. Same text → same count every time."""

    @staticmethod
    def count(text: str) -> int:
        if _HAS_TIKTOKEN and _ENC is not None:
            return len(_ENC.encode(text))
        # Deterministic fallback: chars/4 averaged across cl100k_base calibration.
        # This is a conservative over-estimate to avoid truncation.
        return max(1, len(text) // 3)

    @staticmethod
    def count_file(path: Path) -> int:
        return TokenCounter.count(path.read_text(encoding="utf-8"))


class ComplexityScorer:
    """Heuristic complexity score 0.0–1.0 based on prompt structure."""

    @staticmethod
    def score(text: str) -> float:
        s = 0.0
        lines = text.splitlines()
        words = text.split()

        # Length factor (diminishing returns after 2k words)
        s += min(len(words) / 2000.0, 0.25)

        # Structural depth: nested braces, indentation levels
        max_indent = max((len(line) - len(line.lstrip())) for line in lines if line.strip()) if lines else 0
        s += min(max_indent / 20.0, 0.15)

        # Vocabulary diversity (type/token ratio proxy)
        unique = len(set(w.lower() for w in words))
        if words:
            ttr = unique / len(words)
            s += min(ttr * 0.3, 0.2)

        # Presence of cross-references, file paths, opcodes
        if re.search(r"[A-Za-z_]+\.[A-Za-z_]+", text):
            s += 0.1
        if re.search(r"(opcode|OpKind|\.bb|crystal|hash|chain)", text, re.I):
            s += 0.1
        if re.search(r"(`[^`]+`|```)", text):
            s += 0.05

        return min(s, 1.0)


class ModelRouter:
    """Deterministic router: given a prompt, returns (tier_name, model_id, scope)."""

    def __init__(self, tiers: Optional[List[ModelTier]] = None):
        self.tiers = tiers or self._load_or_default()

    @staticmethod
    def _load_or_default() -> List[ModelTier]:
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text())
                return [ModelTier(**t) for t in data.get("tiers", [])]
            except Exception:
                pass
        return DEFAULT_TIERS

    def save(self) -> None:
        CC_HOME.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            json.dumps({"tiers": [asdict(t) for t in self.tiers]}, indent=2),
            encoding="utf-8",
        )

    def route(self, prompt: str, override_tier: Optional[str] = None) -> Tuple[str, str, str]:
        """Return (tier_name, model_id, scope)."""
        if override_tier:
            for t in self.tiers:
                if t.name == override_tier:
                    return t.name, t.model_id, t.scope
            raise ValueError(f"unknown tier: {override_tier}")

        tokens = TokenCounter.count(prompt)
        complexity = ComplexityScorer.score(prompt)

        # Walk tiers from smallest to largest; pick the first that fits token budget.
        # If complexity pushes us up, check next tier that can handle both.
        chosen = self.tiers[0]
        for t in self.tiers:
            if tokens <= t.token_max and complexity <= t.complexity_max:
                chosen = t
                break
            elif tokens <= t.token_max:
                chosen = t

        return chosen.name, chosen.model_id, chosen.scope

    def list_tiers(self) -> List[Dict]:
        return [asdict(t) for t in self.tiers]

    def downward_dispatch(self, tier_name: str, sub_prompt: str) -> Tuple[str, str, str]:
        """Given a higher-tier result, dispatch a sub-prompt to a lower tier
        that is NOT blind to the origin."""
        origin = next((t for t in self.tiers if t.name == tier_name), None)
        if not origin:
            raise ValueError(f"unknown origin tier: {tier_name}")

        tokens = TokenCounter.count(sub_prompt)
        complexity = ComplexityScorer.score(sub_prompt)

        # Find the largest tier that fits AND is NOT in origin.blind_to
        # (i.e., the origin can see its outputs, or it's the same tier)
        candidates = [t for t in self.tiers if t.name not in origin.blind_to]
        chosen = candidates[0]
        for t in candidates:
            if tokens <= t.token_max and complexity <= t.complexity_max:
                chosen = t
                break
            elif tokens <= t.token_max:
                chosen = t

        return chosen.name, chosen.model_id, chosen.scope


def main():
    import argparse
    ap = argparse.ArgumentParser(description="token router — deterministic model selection")
    ap.add_argument("prompt", nargs="?", help="prompt text or '-' for stdin")
    ap.add_argument("--count-only", action="store_true", help="only print token count")
    ap.add_argument("--complexity", action="store_true", help="only print complexity score")
    ap.add_argument("--tier", help="override tier selection")
    ap.add_argument("--downward-from", help="downward dispatch from this tier")
    ap.add_argument("--list", action="store_true", help="list configured tiers")
    args = ap.parse_args()

    router = ModelRouter()

    if args.list:
        print(json.dumps(router.list_tiers(), indent=2))
        return

    prompt = args.prompt
    if prompt == "-" or prompt is None:
        prompt = sys.stdin.read()

    if args.count_only:
        print(TokenCounter.count(prompt))
        return
    if args.complexity:
        print(f"{ComplexityScorer.score(prompt):.4f}")
        return

    if args.downward_from:
        tier, model, scope = router.downward_dispatch(args.downward_from, prompt)
    else:
        tier, model, scope = router.route(prompt, override_tier=args.tier)

    out = {
        "tier": tier,
        "model": model,
        "scope": scope,
        "tokens": TokenCounter.count(prompt),
        "complexity": round(ComplexityScorer.score(prompt), 4),
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
