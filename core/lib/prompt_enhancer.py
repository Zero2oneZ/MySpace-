#!/usr/bin/env python3
# ============================================================================
# AGENT CARD                                                                  =
# ----------------------------------------------------------------------------=
# name:        prompt_enhancer                                                =
# role:        ENHANCER · DETERMINISTIC_REWRITE                               =
# tier:        L0                                                             =
# substrate:   none (pure transform: text → enhanced text + delta report)    =
# engine:      Levenshtein-against-keyword-index spell fix + rule-based      =
#              structural marker injection (SCOPE/INTENT/CONSTRAINTS/OUTPUT)  =
# storage:     reads ~/.cc/chat_keyword_index.json + chat_common_typos.json   =
#              (optional overrides; falls back to DEFAULT_KEYWORDS/TYPOS)     =
# card:        studio/assets/_agents/agent_defs/                              =
#              vm_mspc_001.agents.agent_defs.prompt_enhancer.active.json      =
# ----------------------------------------------------------------------------=
# ROUTING CONNECTIONS                                                         =
# ----------------------------------------------------------------------------=
# inbound:                                                                    =
#   - chat.py::cmd_enhance  (standalone mode)                                 =
#   - chat.py::cmd_full     (step 1 of full pipeline)                         =
#   - chat.py::cmd_godot    (step 1 of Godot bridge)                          =
#   - CLI: python3 prompt_enhancer.py <prompt> [--scope] [--json] ...         =
# outbound:                                                                   =
#   - difflib.SequenceMatcher  (Levenshtein-ratio similarity, stdlib only)    =
# substrate touch:                                                            =
#   - reads:  optional ~/.cc/chat_keyword_index.json + chat_common_typos.json =
#   - writes: none                                                            =
# downstream effect:                                                          =
#   - OUTPUT marker instructs controlled models to emit <forward>...</forward>=
#     tail → forward_projector.extract_inline consumes that tail              =
# ============================================================================
"""prompt_enhancer.py — deterministic spell-fix + structural prompt enhancement.

No LLM calls here. Rule-based + small-model deterministic pipeline:
  1. Normalize whitespace and line endings.
  2. Fix common typos via dictionary + Levenshtein against a known-keyword index.
  3. Inject structural markers (SCOPE, INTENT, CONSTRAINTS, OUTPUT) if missing.
  4. Expand keyword shortcuts via chain_builder index.
  5. Return enhanced prompt + delta report.

Determinism: same input → same output, byte for byte.
"""
import json
import os
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path
from typing import List, Tuple, Dict, Optional

CC_HOME = Path(os.environ.get("CC_HOME", str(Path.home() / ".cc")))
KEYWORD_INDEX_PATH = CC_HOME / "chat_keyword_index.json"
COMMON_TYPO_PATH = CC_HOME / "chat_common_typos.json"


# ---------------------------------------------------------------------------
# Known keywords from the MySpace++ / GentlyOS ecosystem
# ---------------------------------------------------------------------------
DEFAULT_KEYWORDS = [
    "deterministic", "crystal", "hash", "blake3", "sha256", "chain", "pass",
    "opcode", "OpKind", "bb", "stack", "vm", "agent", "mcp", "scope",
    "godot", "gdextension", "spatial", "bridge", "ik", "solver",
    "inference", "model", "router", "token", "context", "prompt",
    "enhance", "spell", "fix", "chain_builder", "similarity", "keyword",
    "tesseract", "dag", "node", "edge", "walk", "navigator", "sym_indexer",
    "task_manager", "chain_runner", "main_controller", "weave", "device",
    "plan", "evaluate", "route", "compute", "gpu", "network", "droplet",
    "tenant", "user", "billing", "factory", "template", "build", "deploy",
    "wardrobe", "pinterest", "youtube", "media", "audio", "video", "image",
    "avatar", "depth", "pose", "skeleton", "bone", "mesh", "texture",
    "script", "bash", "python", "rust", "cargo", "sui", "nft", "ipfs",
]

DEFAULT_TYPOS: Dict[str, str] = {
    "deteministic": "deterministic",
    "detrministic": "deterministic",
    "dterministic": "deterministic",
    "chrystal": "crystal",
    "cyrstal": "crystal",
    "blak3": "blake3",
    "blake": "blake3",
    "opkode": "opcode",
    "opkind": "OpKind",
    "godot": "godot",
    "godo": "godot",
    "goDot": "godot",
    "infrance": "inference",
    "inferance": "inference",
    "infernce": "inference",
    "tokn": "token",
    "tkn": "token",
    "modle": "model",
    "mdl": "model",
    "enchance": "enhance",
    "enhnce": "enhance",
    "similarty": "similarity",
    "similrity": "similarity",
    "keywrd": "keyword",
    "kyword": "keyword",
    "tessract": "tesseract",
    "navigtor": "navigator",
    "indxer": "indexer",
    "mnager": "manager",
    "runer": "runner",
    "cntroller": "controller",
    "devie": "device",
    "evalute": "evaluate",
    "tenat": "tenant",
    "usr": "user",
    "bilng": "billing",
    "factry": "factory",
    "tmplate": "template",
    "bild": "build",
    "deply": "deploy",
    "wardobe": "wardrobe",
    "pintrest": "pinterest",
    "youtbe": "youtube",
    "vidio": "video",
    "audo": "audio",
    "avtar": "avatar",
    "depht": "depth",
    "poze": "pose",
    "skeletn": "skeleton",
    "bon": "bone",
    "msh": "mesh",
    "txture": "texture",
    "scrit": "script",
    "pyhton": "python",
    "pyton": "python",
    "caro": "cargo",
    "suii": "sui",
}


# ---------------------------------------------------------------------------
# Spell fixer
# ---------------------------------------------------------------------------
class SpellFixer:
    """Deterministic typo correction using dictionary + similarity."""

    def __init__(self, keywords: Optional[List[str]] = None, typos: Optional[Dict[str, str]] = None):
        self.keywords = set(keywords or self._load_keywords())
        self.typos = typos or self._load_typos()

    @staticmethod
    def _load_keywords() -> List[str]:
        if KEYWORD_INDEX_PATH.exists():
            try:
                data = json.loads(KEYWORD_INDEX_PATH.read_text())
                return data.get("keywords", DEFAULT_KEYWORDS)
            except Exception:
                pass
        return DEFAULT_KEYWORDS

    @staticmethod
    def _load_typos() -> Dict[str, str]:
        if COMMON_TYPO_PATH.exists():
            try:
                data = json.loads(COMMON_TYPO_PATH.read_text())
                return data.get("typos", DEFAULT_TYPOS)
            except Exception:
                pass
        return DEFAULT_TYPOS

    def _similarity(self, a: str, b: str) -> float:
        return SequenceMatcher(None, a.lower(), b.lower()).ratio()

    def fix_word(self, word: str) -> str:
        lw = word.lower()
        # Direct typo map
        if lw in self.typos:
            return self.typos[lw]
        # Already known
        if lw in {k.lower() for k in self.keywords}:
            return word
        # Try Levenshtein against keywords (threshold 0.75)
        best = None
        best_score = 0.0
        for kw in self.keywords:
            score = self._similarity(lw, kw)
            if score > best_score and score >= 0.75:
                best_score = score
                best = kw
        if best:
            return best
        return word

    def fix(self, text: str) -> Tuple[str, List[Tuple[str, str]]]:
        """Return (fixed_text, list_of(word, replacement))."""
        replacements = []
        tokens = re.split(r"(\s+|[.,;:!?()\[\]{}])", text)
        out = []
        for tok in tokens:
            if re.match(r"^[A-Za-z]+$", tok):
                fixed = self.fix_word(tok)
                if fixed.lower() != tok.lower():
                    replacements.append((tok, fixed))
                out.append(fixed)
            else:
                out.append(tok)
        return "".join(out), replacements


# ---------------------------------------------------------------------------
# Structural enhancer
# ---------------------------------------------------------------------------
class StructuralEnhancer:
    """Inject structural markers into freeform prompts to make them
    deterministic and scopable."""

    MARKERS = {
        "SCOPE": r"(?i)^\s*SCOPE\s*[:\-]?\s*",
        "INTENT": r"(?i)^\s*INTENT\s*[:\-]?\s*",
        "CONSTRAINTS": r"(?i)^\s*CONSTRAINTS\s*[:\-]?\s*",
        "OUTPUT": r"(?i)^\s*OUTPUT\s*[:\-]?\s*",
    }

    def enhance(self, text: str, scope_hint: str = "") -> Tuple[str, Dict]:
        """Return (enhanced_text, meta)."""
        lines = text.splitlines()
        present = {k: any(re.search(p, line) for line in lines) for k, p in self.MARKERS.items()}

        meta = {"added_markers": [], "scope_hint": scope_hint}
        additions = []

        if not present["SCOPE"]:
            additions.append(f"SCOPE: {scope_hint or 'general'}")
            meta["added_markers"].append("SCOPE")

        if not present["INTENT"]:
            # Derive intent from first sentence
            first = text.strip().split(".")[0][:80]
            additions.append(f"INTENT: {first}")
            meta["added_markers"].append("INTENT")

        if not present["CONSTRAINTS"]:
            additions.append("CONSTRAINTS: deterministic, scoped to current working directory, no external dependencies without explicit approval")
            meta["added_markers"].append("CONSTRAINTS")

        if not present["OUTPUT"]:
            additions.append(
                "OUTPUT: structured response ending with DONE. "
                "Before DONE, emit a <forward>...</forward> block containing 3-5 bullets "
                "naming the next likely steps (file paths, actions, decisions) so the next "
                "inference node can consume them as context."
            )
            meta["added_markers"].append("OUTPUT")

        if additions:
            text = "\n".join(additions) + "\n\n" + text

        return text, meta


# ---------------------------------------------------------------------------
# Prompt enhancer (orchestrator)
# ---------------------------------------------------------------------------
class PromptEnhancer:
    def __init__(self):
        self.spell = SpellFixer()
        self.struct = StructuralEnhancer()

    def enhance(self, text: str, scope_hint: str = "") -> Dict:
        """Full pipeline. Returns dict with enhanced prompt + metadata."""
        # 1. Normalize
        text = text.replace("\r\n", "\n").rstrip() + "\n"

        # 2. Spell fix
        fixed_text, spell_replacements = self.spell.fix(text)

        # 3. Structural enhancement
        enhanced_text, struct_meta = self.struct.enhance(fixed_text, scope_hint)

        # 4. Compact consecutive blank lines
        enhanced_text = re.sub(r"\n{3,}", "\n\n", enhanced_text)

        return {
            "original": text.rstrip(),
            "enhanced": enhanced_text.rstrip(),
            "replacements": spell_replacements,
            "added_markers": struct_meta["added_markers"],
            "scope_hint": scope_hint,
        }


def main():
    import argparse
    ap = argparse.ArgumentParser(description="prompt enhancer — deterministic spell-fix + structure")
    ap.add_argument("prompt", nargs="?", help="prompt text or '-' for stdin")
    ap.add_argument("--scope", default="", help="scope hint for SCOPE marker")
    ap.add_argument("--json", action="store_true", help="emit full JSON with deltas")
    ap.add_argument("--spell-only", action="store_true", help="only fix spelling")
    ap.add_argument("--struct-only", action="store_true", help="only add structure")
    args = argparse.parse_args()

    prompt = args.prompt
    if prompt == "-" or prompt is None:
        prompt = sys.stdin.read()

    enhancer = PromptEnhancer()

    if args.spell_only:
        fixed, reps = enhancer.spell.fix(prompt)
        if args.json:
            print(json.dumps({"fixed": fixed, "replacements": reps}, indent=2))
        else:
            print(fixed)
        return

    if args.struct_only:
        enhanced, meta = enhancer.struct.enhance(prompt, args.scope)
        if args.json:
            print(json.dumps({"enhanced": enhanced, "meta": meta}, indent=2))
        else:
            print(enhanced)
        return

    result = enhancer.enhance(prompt, args.scope)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(result["enhanced"])


if __name__ == "__main__":
    main()
