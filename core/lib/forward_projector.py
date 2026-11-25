#!/usr/bin/env python3
# ============================================================================
# AGENT CARD                                                                  =
# ----------------------------------------------------------------------------=
# name:        forward_projector                                              =
# role:        PROJECTOR · FORWARD_CHAIN                                      =
# tier:        L0                                                             =
# substrate:   none (stateless; consumes reasoning+output, returns forward)   =
# engine:      inline-extract (regex) + posthoc-fallback (tiny model via      =
#              ollama subprocess with CSI cursor-back interpretation)         =
# storage:     none                                                           =
# card:        studio/assets/_agents/agent_defs/                              =
#              vm_mspc_001.agents.agent_defs.forward_projector.active.json    =
# ----------------------------------------------------------------------------=
# ROUTING CONNECTIONS                                                         =
# ----------------------------------------------------------------------------=
# inbound:                                                                    =
#   - chat.py::cmd_full              (post-pipeline projection)               =
#   - chat.py::cmd_godot             (Godot bridge packet projection)         =
#   - CLI: python3 forward_projector.py inline | posthoc | project            =
# outbound:                                                                   =
#   - subprocess.run(['ollama','run',<tiny_model>], input=prompt)             =
#     (only when posthoc fallback fires)                                      =
# substrate touch:                                                            =
#   - reads:  none                                                            =
#   - writes: none (projector is pure; chat.py persists the result)           =
# env vars:                                                                   =
#   - CC_TINY_MODEL       (default qwen2.5-coder:1.5b)                        =
#   - CC_FORWARD_TIMEOUT  (default 20 seconds)                                =
# ============================================================================
"""forward_projector.py — emit future-adjacent forward chains.

Two modes (always try inline first, then post-hoc fallback):

  1. INLINE  — extract <forward>...</forward> tail emitted by a controlled model.
               Cheap (regex), exact (model picked the steps itself).

  2. POSTHOC — call the tiny local model (qwen2.5-coder:1.5b via ollama) on the
               just-completed reasoning trace + output, ask for the next 3-5 likely
               steps. Bounded by timeout; graceful "" return on any failure.

Forward chains feed the NEXT inference node as context, becoming the MoE-by-retrieval
substrate. The chain is part of the InferenceRecord and hashed into the crystal chain.

Determinism: same input → same source choice. Inline is byte-exact deterministic;
post-hoc uses tiny-model with temp=0 seed=42 (best-effort reproducible).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional, Tuple

TINY_MODEL = os.environ.get("CC_TINY_MODEL", "qwen2.5-coder:1.5b")
POSTHOC_TIMEOUT_S = int(os.environ.get("CC_FORWARD_TIMEOUT", "20"))
POSTHOC_MAX_STEPS = 5

_FORWARD_RE = re.compile(r"<forward>(.*?)</forward>", re.DOTALL | re.IGNORECASE)

# CSI escape sequence pattern: ESC '[' (params) (final byte).
_CSI_RE = re.compile(r"\x1b\[([0-9;]*)([A-Za-z])")
# Fragment-then-redraw cleanup: when a non-whitespace token is followed by a newline
# and the same token (possibly extended) on the next line, drop the duplicate fragment.
_WRAP_REPEAT_RE = re.compile(r"(\S{2,})\n(\1\S*)")


def _strip_ansi(text: str) -> str:
    """Interpret common CSI sequences so the captured stdout matches what would
    have rendered on screen — not just strip codes.

    Handles:
      * \x1b[<N>D — cursor back N (pop N chars from output buffer)
      * \x1b[K    — erase to end of line (no-op since we haven't written past cursor)
      * everything else — drop the sequence silently.
    """
    if not text:
        return ""
    out: list = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch != "\x1b":
            out.append(ch)
            i += 1
            continue
        m = _CSI_RE.match(text, i)
        if not m:
            # Stray ESC — drop it.
            i += 1
            continue
        params, final = m.group(1), m.group(2)
        if final == "D":
            # Cursor back N — pop up to N chars from the buffer (without crossing newlines).
            try:
                nval = int(params) if params else 1
            except ValueError:
                nval = 1
            popped = 0
            while popped < nval and out and out[-1] != "\n":
                out.pop()
                popped += 1
        # 'K' (erase to EOL), 'm' (SGR), 'A'/'B'/'C' (cursor moves), etc. — drop.
        i = m.end()
    # Final cleanup pass: collapse any leftover wrap-fragment-then-redraw pairs.
    joined = "".join(out)
    # Apply repeatedly until stable (handles chained wraps).
    while True:
        new = _WRAP_REPEAT_RE.sub(r"\2", joined)
        if new == joined:
            break
        joined = new
    return joined


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass
class ForwardResult:
    inline: str = ""
    posthoc: str = ""
    source: str = "none"   # "inline" | "posthoc" | "both" | "none"

    def chosen(self) -> str:
        """The forward chain to feed downstream. Prefer inline; fall back to posthoc."""
        if self.inline:
            return self.inline
        return self.posthoc


def extract_inline(output_text: str) -> str:
    """Pull <forward>...</forward> body out of an output. Returns "" if absent or
    if the body is a placeholder (e.g., the literal `...` from a prompt instruction)."""
    if not output_text:
        return ""
    # Walk all matches; return the first one whose body looks like real content.
    for m in _FORWARD_RE.finditer(output_text):
        body = m.group(1).strip()
        if _is_placeholder(body):
            continue
        return body
    return ""


def _is_placeholder(body: str) -> bool:
    """Reject obviously instructional/template bodies."""
    if not body:
        return True
    # Pure ellipsis or short stubs that templates use as placeholders.
    if body in ("...", ". . .", "…"):
        return True
    if len(body) < 5:
        return True
    # No bullets, no newlines, no concrete tokens — likely a single phrase placeholder.
    if "\n" not in body and "-" not in body and "*" not in body and len(body) < 40:
        return True
    return False


def strip_inline(output_text: str) -> str:
    """Remove the <forward>...</forward> block from the output (for clean display)."""
    if not output_text:
        return ""
    return _FORWARD_RE.sub("", output_text).rstrip()


def project_posthoc(
    reasoning_trace: str,
    output_text: str,
    prev_forward: str = "",
    model: str = TINY_MODEL,
    timeout_s: int = POSTHOC_TIMEOUT_S,
) -> str:
    """Run the tiny model on the completed trace+output, ask for next N steps.
    Returns "" on any failure (missing ollama, timeout, empty response)."""
    if not shutil.which("ollama"):
        return ""

    prompt = _build_posthoc_prompt(reasoning_trace, output_text, prev_forward)

    try:
        proc = subprocess.run(
            ["ollama", "run", model],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env={
                **os.environ,
                "OLLAMA_TEMPERATURE": "0",
                "OLLAMA_SEED": "42",
                "OLLAMA_NO_ANIMATION": "1",
                "TERM": "dumb",
            },
        )
    except subprocess.TimeoutExpired:
        return ""
    except Exception:
        return ""

    out = _strip_ansi(proc.stdout or "").strip()
    if not out:
        return ""

    # If the tiny model ALSO emitted <forward>...</forward>, prefer that inner body.
    inner = extract_inline(out)
    if inner:
        return inner
    return out


def project(
    reasoning_trace: str,
    output_text: str,
    prev_forward: str = "",
    *,
    enable_posthoc: bool = True,
) -> ForwardResult:
    """Full projection: inline first, posthoc fallback. Returns ForwardResult."""
    inline = extract_inline(output_text)
    posthoc = ""
    if enable_posthoc and not inline:
        # Only spend tiny-model time when inline is absent.
        posthoc = project_posthoc(reasoning_trace, output_text, prev_forward)
    elif enable_posthoc and inline:
        # Inline already present — skip posthoc to save latency. Caller can override
        # by calling project_posthoc() directly if they want both.
        pass

    if inline and posthoc:
        source = "both"
    elif inline:
        source = "inline"
    elif posthoc:
        source = "posthoc"
    else:
        source = "none"

    return ForwardResult(inline=inline, posthoc=posthoc, source=source)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

_POSTHOC_TEMPLATE = """You are a deterministic forward-chain projector for the MySpace++ studio.
Given a completed reasoning trace and its output, predict the NEXT {max_steps} most likely
next steps the user or system will take. Be concrete: name files, actions, decisions.

Output format (strict): one bullet per step, prefixed with "- ". No prose, no preamble.
End your response with the literal token </forward>.

PRIOR FORWARD CHAIN (may be empty):
{prev_forward}

REASONING TRACE:
{reasoning_trace}

OUTPUT:
{output_text}

NEXT {max_steps} STEPS:
"""


def _build_posthoc_prompt(reasoning_trace: str, output_text: str, prev_forward: str) -> str:
    # Truncate inputs to keep tiny-model latency bounded.
    return _POSTHOC_TEMPLATE.format(
        max_steps=POSTHOC_MAX_STEPS,
        prev_forward=(prev_forward or "(none)")[:2000],
        reasoning_trace=(reasoning_trace or "(no reasoning captured)")[:4000],
        output_text=(output_text or "")[:4000],
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse
    import sys

    ap = argparse.ArgumentParser(description="forward_projector — emit future-adjacent chains")
    sub = ap.add_subparsers(dest="cmd")

    p_inline = sub.add_parser("inline", help="extract inline <forward> block")
    p_inline.add_argument("--from-stdin", action="store_true")
    p_inline.add_argument("text", nargs="?", default="")

    p_post = sub.add_parser("posthoc", help="run tiny-model post-hoc projection")
    p_post.add_argument("--reasoning", default="")
    p_post.add_argument("--output", default="")
    p_post.add_argument("--prev", default="")
    p_post.add_argument("--model", default=TINY_MODEL)
    p_post.add_argument("--timeout", type=int, default=POSTHOC_TIMEOUT_S)

    p_proj = sub.add_parser("project", help="full inline+posthoc projection")
    p_proj.add_argument("--reasoning", default="")
    p_proj.add_argument("--output", default="")
    p_proj.add_argument("--prev", default="")
    p_proj.add_argument("--no-posthoc", action="store_true")

    args = ap.parse_args()

    if args.cmd == "inline":
        text = sys.stdin.read() if args.from_stdin else args.text
        print(extract_inline(text))
    elif args.cmd == "posthoc":
        print(project_posthoc(args.reasoning, args.output, args.prev, args.model, args.timeout))
    elif args.cmd == "project":
        result = project(args.reasoning, args.output, args.prev, enable_posthoc=not args.no_posthoc)
        print(json.dumps({
            "inline": result.inline,
            "posthoc": result.posthoc,
            "source": result.source,
            "chosen": result.chosen(),
        }, indent=2))
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
