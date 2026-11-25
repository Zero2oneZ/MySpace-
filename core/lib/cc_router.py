#!/usr/bin/env python3
"""cc_router — route context + text to the cc/claude-code substrate.

The dispatch fabric for workflow_card execution. Three modes:

    tiny    → subprocess `cc tiny <prompt>`     (deterministic, free, Ollama)
    claude  → subprocess `cc claude <prompt>`   (Claude Code one-shot, deeper)
    none    → no LLM call (returns empty)

Why cc, not deepseek (or any HTTP API):
    1. cc tracks every call in ~/.cc/cc.db — same substrate the user lives in.
    2. tiny is local + deterministic + free — no quota, no latency to the cloud.
    3. claude (one-shot) goes through `cc claude` which already wires preamble
       + transcripts + project context. Calling the binary directly would
       lose all of that.

The router lets a workflow_card declare per-pass `swap_mode`: one zone can
go deep (claude) while siblings stay LL-cheap (tiny). The structured wiring
of the card stays coherent — only the *node implementation* swaps.

CLI:
    python3 core/lib/cc_router.py tiny  "summarize the chain in 1 line"
    python3 core/lib/cc_router.py claude "refactor X carefully"
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── locate cc ────────────────────────────────────────────────────────────────

def _find_cc() -> str:
    """Discover the cc binary. Falls back to bare 'cc' if nothing found."""
    candidates = [
        os.environ.get("CC_BIN"),
        "/home/tom/bin/cc",
        "/home/tom/Projects/gently-cc/cc",
        "/usr/local/bin/cc",
    ]
    for c in candidates:
        if c and Path(c).exists() and os.access(c, os.X_OK):
            return c
    found = shutil.which("cc")
    return found or "cc"


CC_BIN = _find_cc()


# ── RouteResult ──────────────────────────────────────────────────────────────

class RouteResult:
    __slots__ = ("ok", "output", "mode", "error", "returncode", "elapsed_ms")

    def __init__(self, ok: bool, output: str = "", mode: str = "none",
                 error: str = "", returncode: int = 0, elapsed_ms: int = 0):
        self.ok = ok
        self.output = output
        self.mode = mode
        self.error = error
        self.returncode = returncode
        self.elapsed_ms = elapsed_ms

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok, "output": self.output, "mode": self.mode,
            "error": self.error, "returncode": self.returncode,
            "elapsed_ms": self.elapsed_ms,
        }


# ── single-call routing ──────────────────────────────────────────────────────

VALID_MODES = ("tiny", "claude", "claude_code", "none")


def route(prompt: str, mode: str = "tiny",
          context: Optional[Dict[str, Any]] = None,
          timeout_s: int = 120) -> RouteResult:
    """Route a prompt + optional context through the cc dispatcher.

    `context` is JSON-serialized as a fenced block prefixed to the prompt
    so the model receives both the structured frame AND the natural-language
    request in the same turn. Same prompt for every node; per-pass context
    via this dict; per-pass model via `mode`.
    """
    import time
    mode = (mode or "none").lower()
    if mode == "none":
        return RouteResult(ok=True, mode="none")
    if mode not in VALID_MODES:
        return RouteResult(ok=False, mode=mode, error=f"unknown mode: {mode}")

    full = prompt
    if context:
        ctx_blob = json.dumps(context, indent=2, default=str)
        full = f"# context\n```json\n{ctx_blob}\n```\n\n# request\n{prompt}"

    if mode == "tiny":
        cmd = [CC_BIN, "tiny", full]
    elif mode in ("claude", "claude_code"):
        cmd = [CC_BIN, "claude", full]
    else:
        return RouteResult(ok=False, mode=mode, error=f"unhandled mode: {mode}")

    t0 = time.time()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_s
        )
    except subprocess.TimeoutExpired:
        return RouteResult(ok=False, mode=mode,
                           error=f"timeout after {timeout_s}s",
                           elapsed_ms=int((time.time() - t0) * 1000))
    except FileNotFoundError:
        return RouteResult(ok=False, mode=mode,
                           error=f"cc binary not found: {CC_BIN}")
    except Exception as e:
        return RouteResult(ok=False, mode=mode,
                           error=f"{type(e).__name__}: {e}")
    elapsed_ms = int((time.time() - t0) * 1000)
    ok = result.returncode == 0
    return RouteResult(
        ok=ok,
        output=(result.stdout or "").strip(),
        mode=mode,
        error=(result.stderr or "").strip() if not ok else "",
        returncode=result.returncode,
        elapsed_ms=elapsed_ms,
    )


# ── broadcast: route to every pass in a card ─────────────────────────────────

def broadcast(prompt: str, scope: List[str], passes: List[Dict[str, Any]],
              parent_chain: Optional[List[str]] = None,
              sibling_window: int = 3,
              tiny_timeout_s: int = 30,
              claude_timeout_s: int = 120) -> List[Dict[str, Any]]:
    """For each pass, route the prompt + per-pass context through that pass's
    `swap_mode`. Same higher-level prompt for everyone; the model + context
    differ per pass.

    Each pass is returned with `routed_output` populated (empty string if
    swap_mode='none' or the route failed). Later passes see a rolling window
    of the most recent `sibling_window` outputs so the chain can carry forward
    context without exploding the prompt budget.

    A pass can override its mode with `swap_mode`. Tom's principle: same
    higher-level connection, different element. Replaceability without
    breaking the wiring.
    """
    enriched: List[Dict[str, Any]] = []
    sibling_outputs: List[Dict[str, str]] = []
    parent_chain = parent_chain or []

    for p in passes:
        mode = p.get("swap_mode", "tiny")
        if mode == "none":
            enriched.append(dict(p, routed_output="", routed_mode="none"))
            continue

        kernel_ref = p.get("kernel_ref", "")
        agent = p.get("agent", "")
        in_type = p.get("in", "")
        out_type = p.get("out", "")

        ctx = {
            "user_prompt": prompt,
            "compose_scope": scope,
            "this_pass": {
                "id":         p.get("id", ""),
                "kernel_ref": kernel_ref,
                "agent":      agent,
                "engine":     p.get("engine", ""),
                "in_type":    in_type,
                "out_type":   out_type,
                "tier":       p.get("tier", ""),
            },
            "parent_chain":     parent_chain[-3:],
            "sibling_outputs":  sibling_outputs[-sibling_window:],
        }

        pass_prompt = (
            f"You are workflow node `{p.get('id','')}` running the kernel `{kernel_ref}`. "
            f"Given the user prompt above, describe in ONE sentence the concrete action "
            f"you would take. No preamble. No explanation. Just the action."
        )

        timeout = claude_timeout_s if mode in ("claude", "claude_code") else tiny_timeout_s
        result = route(pass_prompt, mode=mode, context=ctx, timeout_s=timeout)

        out_text = result.output if result.ok else ""
        enriched.append(dict(
            p,
            routed_output=out_text,
            routed_mode=result.mode,
            routed_elapsed_ms=result.elapsed_ms,
            routed_ok=result.ok,
        ))
        if result.ok and out_text:
            sibling_outputs.append({
                "pass_id": p.get("id", ""),
                "output": out_text[:240],
            })
    return enriched


# ── helpers for callers ──────────────────────────────────────────────────────

def health_check() -> Dict[str, Any]:
    """Quick: are tiny + claude actually reachable?"""
    t = route("ping. reply with the single word PONG.", mode="tiny", timeout_s=20)
    c_avail = shutil.which("claude") is not None
    return {
        "cc_bin":   CC_BIN,
        "tiny": {"ok": t.ok, "output": t.output[:80], "elapsed_ms": t.elapsed_ms},
        "claude_on_path": c_avail,
        "modes_available": [m for m in VALID_MODES
                            if (m == "tiny" and t.ok) or
                               (m in ("claude", "claude_code") and c_avail) or
                               m == "none"],
    }


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv: List[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(json.dumps({
            "usage": "cc_router <mode> <prompt>",
            "modes": list(VALID_MODES),
            "tools": ["route", "broadcast", "health_check"],
        }, indent=2))
        return 1
    if argv[0] == "health":
        print(json.dumps(health_check(), indent=2))
        return 0
    mode = argv[0]
    prompt = " ".join(argv[1:])
    if not prompt:
        print("usage: cc_router <mode> <prompt>", file=sys.stderr)
        return 1
    result = route(prompt, mode=mode)
    print(json.dumps(result.as_dict(), indent=2))
    return 0 if result.ok else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
