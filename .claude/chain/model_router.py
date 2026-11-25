#!/usr/bin/env python3
"""
model_router.py — deterministic model selection based on token complexity.

Part of the .claude/ agent chain system. Computes an estimated token count and
complexity score for any task, then maps to the correct agent level (1-5).

Usage:
    python3 model_router.py --task "Refactor auth system"       # → level 4
    python3 model_router.py --task "Count lines in file.py"     # → level 1
    python3 model_router.py --estimate-tokens "long prompt..." # → token count
"""

import argparse
import json
import math
import re
import sys
from pathlib import Path

REGISTRY_PATH = Path(__file__).parent.parent / "agents" / "registry.json"

# Rough heuristic: 1 token ≈ 0.75 words (English) or ~4 chars for code
def estimate_tokens(text: str, content_type: str = "mixed") -> int:
    """Estimate token count for a given text."""
    if not text:
        return 0
    if content_type == "code":
        # Code is denser: ~3.5 chars per token
        return max(1, int(len(text) / 3.5))
    # Mixed / natural language
    words = len(text.split())
    chars = len(text)
    return max(words, int(chars / 4))


def compute_complexity(task_description: str, context_text: str = "") -> dict:
    """
    Compute complexity score (0-100) for a task.

    Factors:
    - token_volume (30%)       — how much text is involved
    - cross_file_count (25%)  — how many files are touched
    - reasoning_depth (25%)    — architectural vs mechanical
    - external_deps (20%)     — how many external systems are involved
    """
    desc = task_description.lower()
    full = (task_description + " " + context_text).lower()

    # 1. Token volume (0-30)
    total_tokens = estimate_tokens(task_description + context_text)
    if total_tokens < 500:
        token_score = 5
    elif total_tokens < 2000:
        token_score = 15
    elif total_tokens < 8000:
        token_score = 25
    elif total_tokens < 30000:
        token_score = 35
    else:
        token_score = 40

    # 2. Cross-file count (0-25)
    file_indicators = [
        "refactor", "across", "multiple files", "cross-project", "merge",
        "sync", "shared", "dependency", "module", "crate", "package"
    ]
    file_score = sum(5 for ind in file_indicators if ind in full)
    file_score = min(file_score, 25)

    # 3. Reasoning depth (0-25)
    depth_indicators = {
        "design": 8, "architecture": 10, "strategy": 10, "plan": 6,
        "review": 7, "audit": 7, "decision": 8, "choose": 5,
        "implement": 4, "write": 3, "fix": 2, "edit": 2,
        "count": 1, "list": 1, "hash": 1, "validate": 1,
        "security": 10, "compliance": 9, "legal": 9,
    }
    depth_score = sum(score for word, score in depth_indicators.items() if word in full)
    depth_score = min(depth_score, 25)

    # 4. External dependencies (0-20)
    ext_indicators = [
        "discord", "telegram", "whatsapp", "api", "mcp", "bridge",
        "droplet", "deploy", "hf:", "huggingface", "livepeer",
        "trollz", "social", "payment", "nft", "sui", "ipfs",
        "unreal", "game", "engine", "webgpu", "gpu", "cuda"
    ]
    ext_score = sum(4 for ind in ext_indicators if ind in full)
    ext_score = min(ext_score, 20)

    total = token_score + file_score + depth_score + ext_score
    return {
        "token_volume": token_score,
        "cross_file": file_score,
        "reasoning": depth_score,
        "external": ext_score,
        "total": total,
        "estimated_tokens": total_tokens,
    }


def complexity_to_level(score: int, registry: dict) -> int:
    """Map complexity score (0-100) to agent level (1-5)."""
    mapping = registry.get("routing_rules", {}).get("complexity_to_level", {})
    for range_key, level in sorted(mapping.items(), key=lambda x: int(x[0].split("_")[0])):
        low, high = map(int, range_key.split("_"))
        if low <= score <= high:
            return level
    return 5  # default to highest if out of range


def route_task(task_description: str, context_text: str = "", registry_path: Path = REGISTRY_PATH) -> dict:
    """Full routing decision for a task. Returns level, model, and reasoning."""
    registry = json.loads(registry_path.read_text())
    complexity = compute_complexity(task_description, context_text)
    level = complexity_to_level(complexity["total"], registry)
    level_str = str(level)
    agent_def = registry["levels"].get(level_str, registry["levels"]["5"])

    # Check escalation triggers
    escalation = None
    for rule in registry.get("routing_rules", {}).get("escalation_triggers", []):
        if rule["trigger"] == "security_sensitive" and any(w in task_description.lower() for w in ["security", "auth", "token", "key", "password"]):
            level = 5
            escalation = rule
            break
        if rule["trigger"] == "requires_human_flag_set" and "requires_human" in task_description.lower():
            level = 5
            escalation = rule
            break

    # Re-fetch agent def after possible escalation
    agent_def = registry["levels"].get(str(level), registry["levels"]["5"])

    return {
        "level": level,
        "agent_name": agent_def["name"],
        "model": agent_def["model"],
        "max_tokens": agent_def["max_tokens"],
        "requires_human": agent_def["requires_human"],
        "route_to": agent_def["route_to"],
        "complexity": complexity,
        "escalation": escalation,
        "can_spawn_subagents": agent_def.get("spawn_subagents", False),
        "spawn_max_level": agent_def.get("spawn_max_level", 0),
    }


def main():
    parser = argparse.ArgumentParser(description="Model router for agent chain")
    parser.add_argument("--task", type=str, help="Task description to route")
    parser.add_argument("--context", type=str, default="", help="Additional context")
    parser.add_argument("--estimate-tokens", type=str, help="Just estimate token count")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    if args.estimate_tokens:
        count = estimate_tokens(args.estimate_tokens)
        print(json.dumps({"estimated_tokens": count}) if args.json else count)
        return

    if not args.task:
        print("Usage: python3 model_router.py --task 'description' [--context 'extra']")
        sys.exit(1)

    result = route_task(args.task, args.context)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Task: {args.task}")
        print(f"Complexity: {result['complexity']['total']}/100")
        print(f"  token_volume={result['complexity']['token_volume']} cross_file={result['complexity']['cross_file']}")
        print(f"  reasoning={result['complexity']['reasoning']} external={result['complexity']['external']}")
        print(f"Estimated tokens: {result['complexity']['estimated_tokens']}")
        print(f"Routed to: Level {result['level']} ({result['agent_name']}) → {result['model']}")
        print(f"Requires human: {'YES' if result['requires_human'] else 'no'}")
        print(f"Endpoint: {result['route_to']}")
        if result['escalation']:
            print(f"Escalation: {result['escalation']['trigger']} → {result['escalation']['action']}")


if __name__ == "__main__":
    main()
