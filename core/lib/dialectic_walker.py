#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        dialectic_walker
# role:        SUBSTRATE · BACKWARD_DIALECTICAL_CLOSURE
# tier:        L0
# substrate:   ~/.cc/dialectic_chain.jsonl — IS / IS-NOT / BECOMING per step
# engine:      reverse chain walk + cross-axis antithesis + transition gradient
# storage:     ~/.cc/dialectic_chain.jsonl (ParserCursor-compatible)
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.dialectic_walker.active.json
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - CLI: cc dialectic-walk (when wired)
#   - (planned) chat.py — every new chat turn appends a dialectic step
# outbound:
#   - inference_logger  (reads the master chain)
#   - tri_modal_embedder (wave / time axes for antithesis)
#   - sentence_chain     (syntactic antithesis)
#   - energy_inversion   (the negation lens — antipodal vectors)
#   - transition_field   (measurement-first becoming)
#   - frame_clock        (FPS-quantized time alignment)
# substrate touch:
#   - reads:  ~/.cc/inference_master_chain.jsonl
#   - writes: ~/.cc/dialectic_chain.jsonl
# the dialectic:
#   IS         the record at step n (thesis — what present is)
#   IS-NOT     antithesis across 5 axes (vector/wave/time/sentence/svg)
#   BECOMING   gradient toward step n+1 (synthesis — what emerges)
#   present = present_record    anchor point of the walk (latest)
# ============================================================================
"""dialectic_walker.py — the chain reads itself backwards and forward at once.

For each record n in the crystal chain (walking from latest to oldest), compute:

  IS           the record itself (thesis)
                 - vector_emb, wave_emb, time_vec, sentence_emb (when present)
                 - crystal, prev_crystal, forward_chain

  IS-NOT       the antithesis across every measurable axis (negation)
                 - is_not_wave    = -wave_emb (energy_inversion)
                 - is_not_time    = forward-flipped time_vec
                 - is_not_sentence_emb = -sentence_emb of the prompt
                 - is_not_vector_overlap = past records with MINIMUM n-gram overlap
                 - is_not_crystal = blake3 over the negated bundle

  BECOMING     the measured transition n → n+1 (synthesis from what followed)
                 - position_delta, value_delta, frame_delta
                 - velocity_magnitude, color_velocity
                 - flow_signature (DCT) — joins wave axis
                 - direction in embedding space
                 - becoming_crystal

The output (~/.cc/dialectic_chain.jsonl) is a parallel chain. Walk it forward
and the trajectory IS / IS-NOT / BECOMING reads as a complete dialectical
account of how the chain evolved — anchored to the present (the last record).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from inference_logger import InferenceLogger
from energy_inversion import invert_vec


try:
    import blake3 as _blake3_mod
    def _hash(data: bytes) -> str:
        return _blake3_mod.blake3(data).hexdigest()
except ImportError:
    def _hash(data: bytes) -> str:
        return hashlib.blake2b(data).hexdigest()


CC_HOME = Path(os.environ.get("CC_HOME", str(Path.home() / ".cc")))
DIALECTIC_CHAIN_PATH = CC_HOME / "dialectic_chain.jsonl"


# ---------------------------------------------------------------------------
# DialecticalStep — IS · IS-NOT · BECOMING
# ---------------------------------------------------------------------------

@dataclass
class DialecticalStep:
    step_index: int                              # position in the reverse walk (0 = latest = present)
    chain_index: int                              # original master_index

    # IS — the present at this step
    present_crystal: str = ""
    present_tier: str = ""
    present_model: str = ""
    present_timestamp: str = ""
    present_prompt_preview: str = ""
    present_wave_norm: float = 0.0
    present_has_wave: bool = False
    present_has_time: bool = False

    # IS-NOT — the antithesis across measurable axes
    is_not_wave: List[float] = field(default_factory=list)
    is_not_time_forward: List[float] = field(default_factory=list)
    is_not_sentence_preview: str = ""
    is_not_vector_overlap_count: int = 0
    is_not_crystal: str = ""

    # BECOMING — measured transition to step n+1 (when not the latest)
    becoming_delta_seconds: float = 0.0
    becoming_value_delta_magnitude: float = 0.0
    becoming_velocity: float = 0.0
    becoming_color_velocity: float = 0.0
    becoming_flow_sig_head: List[float] = field(default_factory=list)
    becoming_target_crystal: str = ""
    becoming_crystal: str = ""

    # Crystal linking the triad
    crystal: str = ""
    prev_step_crystal: str = ""           # link backward (toward older)
    next_step_crystal: str = ""           # link forward (toward present)

    def to_compact_dict(self) -> Dict[str, Any]:
        return {
            "step_index": self.step_index,
            "chain_index": self.chain_index,
            "present": {
                "crystal":    self.present_crystal[:16],
                "tier":       self.present_tier,
                "model":      self.present_model,
                "timestamp":  self.present_timestamp,
                "prompt":     self.present_prompt_preview,
                "has_wave":   self.present_has_wave,
                "has_time":   self.present_has_time,
            },
            "is_not": {
                "wave_head":            [round(x, 4) for x in self.is_not_wave[:6]],
                "time_forward_head":    [round(x, 4) for x in self.is_not_time_forward[:6]],
                "vector_overlap_count": self.is_not_vector_overlap_count,
                "sentence_preview":     self.is_not_sentence_preview,
                "crystal":              self.is_not_crystal[:16],
            },
            "becoming": {
                "delta_seconds":        round(self.becoming_delta_seconds, 4),
                "value_delta_magnitude": round(self.becoming_value_delta_magnitude, 4),
                "velocity":             round(self.becoming_velocity, 4),
                "color_velocity":       round(self.becoming_color_velocity, 4),
                "flow_sig_head":        [round(x, 4) for x in self.becoming_flow_sig_head],
                "target_crystal":       self.becoming_target_crystal[:16],
                "crystal":              self.becoming_crystal[:16],
            },
            "crystal":           self.crystal[:32],
            "prev_step_crystal": self.prev_step_crystal[:16],
            "next_step_crystal": self.next_step_crystal[:16],
        }


# ---------------------------------------------------------------------------
# Walker
# ---------------------------------------------------------------------------

class DialecticWalker:
    """Walks the crystal chain backwards, emitting DialecticalSteps."""

    def __init__(self, chain_path: Optional[Path] = None,
                 out_path: Optional[Path] = None):
        self.chain_path = chain_path or (CC_HOME / "inference_master_chain.jsonl")
        self.out_path = out_path or DIALECTIC_CHAIN_PATH

    # ---- IS-NOT derivation -------------------------------------------------

    def _is_not_wave(self, present_wave: List[float]) -> List[float]:
        """Antipodal of the wave embedding — the 'frequency content absent from present'."""
        if not present_wave:
            return []
        return invert_vec(present_wave)

    def _is_not_time_forward(self, time_vec: Dict[str, Any]) -> List[float]:
        """Forward-flipped time vector — sin(t) → -sin(t), cos(t) unchanged."""
        forward = time_vec.get("forward") if isinstance(time_vec, dict) else None
        if not forward:
            return []
        return invert_vec(forward)

    def _is_not_sentence_preview(self, present_prompt: str) -> str:
        """Best-effort negation of the prompt's syntactic shape — flip key markers."""
        if not present_prompt:
            return ""
        flips = [
            ("must",   "must not"), ("should",  "should not"),
            ("will",   "will not"), ("can",     "cannot"),
            (" is ",   " is not "), (" are ",   " are not "),
            (" do ",   " do not "), (" does ",  " does not "),
            ("build",  "deconstruct"), ("create", "destroy"),
            ("add",    "remove"), ("show",   "hide"),
            ("more",   "less"), ("forward", "backward"),
        ]
        out = present_prompt[:200]
        for src, dst in flips:
            out = out.replace(src, dst)
        return out

    def _is_not_vector_overlap_count(self, present_prompt: str,
                                       all_records: List[Dict[str, Any]]) -> int:
        """How many other records share ZERO n-grams with this one — proxy for
        'how unique is this content'. High count = present is common (lots of
        opposites). Low count = present is rare."""
        try:
            from moe_router import _extract_ngrams  # type: ignore
        except ImportError:
            return 0
        present_grams = {h for _, h in _extract_ngrams(present_prompt)}
        if not present_grams:
            return 0
        count = 0
        for r in all_records:
            other = r.get("original_prompt") or ""
            if not other or other == present_prompt:
                continue
            other_grams = {h for _, h in _extract_ngrams(other)}
            if not (present_grams & other_grams):
                count += 1
        return count

    def _compute_is_not_crystal(self,
                                 present_crystal: str,
                                 is_not_wave: List[float],
                                 is_not_time_forward: List[float],
                                 is_not_sentence_preview: str,
                                 is_not_vector_overlap_count: int) -> str:
        canonical = json.dumps({
            "of_crystal": present_crystal,
            "wave_inv_first6":  [round(x, 5) for x in is_not_wave[:6]],
            "time_inv_first6":  [round(x, 5) for x in is_not_time_forward[:6]],
            "sentence_inv":     is_not_sentence_preview[:200],
            "overlap_zero":     is_not_vector_overlap_count,
        }, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        return _hash(canonical.encode("utf-8"))

    # ---- BECOMING derivation ----------------------------------------------

    def _becoming(self,
                  present_record: Dict[str, Any],
                  next_record: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Measure the transition from present → next (the synthesis)."""
        if next_record is None:
            return {
                "delta_seconds": 0.0, "value_delta_magnitude": 0.0,
                "velocity": 0.0, "color_velocity": 0.0,
                "flow_sig_head": [], "target_crystal": "",
            }

        # Time delta — try epoch via timestamp str → seconds, else 0
        def _ts(rec: Dict[str, Any]) -> float:
            ts = rec.get("timestamp", "")
            if isinstance(ts, (int, float)):
                return float(ts)
            try:
                # ISO 8601 stripped of Z
                from datetime import datetime
                ts_clean = ts.replace("Z", "+00:00") if isinstance(ts, str) else str(ts)
                return datetime.fromisoformat(ts_clean).timestamp()
            except Exception:
                return 0.0

        t_present = _ts(present_record)
        t_next = _ts(next_record)
        dt = t_next - t_present

        # Value delta — wave_emb delta if both have wave_embs
        p_wave = present_record.get("wave_emb") or []
        n_wave = next_record.get("wave_emb") or []
        value_delta = []
        if p_wave and n_wave:
            m = min(len(p_wave), len(n_wave))
            value_delta = [n_wave[i] - p_wave[i] for i in range(m)]
        value_mag = math.sqrt(sum(x*x for x in value_delta)) if value_delta else 0.0

        velocity = abs(value_mag / dt) if dt != 0 else 0.0

        # Flow signature head — DCT of the value_delta magnitudes (use a 16-step
        # rolling magnitude sequence as a tiny signature head)
        # Pure-Python tiny DCT-II on the first 16 abs(value_delta)
        mags16 = [abs(x) for x in value_delta[:16]]
        # pad to 16
        while len(mags16) < 16:
            mags16.append(0.0)
        # tiny normalized DCT
        def _mini_dct(samples: List[float], n: int = 8) -> List[float]:
            N = len(samples)
            if N == 0:
                return [0.0] * n
            out = []
            for k in range(min(n, N)):
                s = sum(samples[j] * math.cos(math.pi * (j + 0.5) * k / N) for j in range(N))
                out.append(s * (math.sqrt(1.0/N) if k == 0 else math.sqrt(2.0/N)))
            while len(out) < n:
                out.append(0.0)
            norm = math.sqrt(sum(x*x for x in out))
            if norm > 1e-12:
                out = [x / norm for x in out]
            return out
        flow_head = _mini_dct(mags16, n=8)

        # Color velocity — proxy via L2 norm of first 3 dims of value_delta as RGB-ish
        color_velocity = abs(math.sqrt(sum(x*x for x in value_delta[:3])) / dt) if (dt != 0 and value_delta) else 0.0

        return {
            "delta_seconds":         dt,
            "value_delta_magnitude": value_mag,
            "velocity":              velocity,
            "color_velocity":        color_velocity,
            "flow_sig_head":         flow_head,
            "target_crystal":        next_record.get("crystal_id", ""),
        }

    def _compute_becoming_crystal(self, becoming: Dict[str, Any],
                                    present_crystal: str) -> str:
        canonical = json.dumps({
            "from_crystal":   present_crystal,
            "target_crystal": becoming.get("target_crystal", ""),
            "dt_rounded":     round(becoming.get("delta_seconds", 0.0), 3),
            "value_mag":      round(becoming.get("value_delta_magnitude", 0.0), 5),
            "flow_sig_head":  [round(x, 5) for x in becoming.get("flow_sig_head", [])],
        }, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        return _hash(canonical.encode("utf-8"))

    # ---- step crystal ----------------------------------------------------

    def _compute_step_crystal(self, step: DialecticalStep) -> str:
        canonical = json.dumps({
            "present_crystal":  step.present_crystal,
            "is_not_crystal":   step.is_not_crystal,
            "becoming_crystal": step.becoming_crystal,
            "step_index":       step.step_index,
        }, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        return _hash(canonical.encode("utf-8"))

    # ---- main walk -------------------------------------------------------

    def walk(self, write: bool = True) -> List[DialecticalStep]:
        """Reverse-walk the chain and emit DialecticalSteps. Returns list newest→oldest."""
        logger = InferenceLogger()
        chain = logger.get_chain(limit=10_000)
        # Exclude the genesis record (model=='genesis')
        chain = [r for r in chain if (r.get("model") or "") != "genesis"]
        if not chain:
            return []

        # Reverse: latest (present) first
        rev = list(reversed(chain))

        steps: List[DialecticalStep] = []
        prev_step_crystal = ""

        for i, present_rec in enumerate(rev):
            # The "next" in time is the previous in rev (newer chain index)
            # Actually rev is newest→oldest, so the SUCCESSOR of present_rec in time
            # is the record that came after it in the chain — which is at rev[i-1].
            # For becoming (synthesis) we want the record that FOLLOWED present_rec.
            successor = rev[i - 1] if i > 0 else None
            # Conceptually: rev[0] is the latest, has NO successor (it's the present anchor).
            # But rev[i] for i>0 has rev[i-1] as its successor.
            # We anchor the dialectic walk to the present (rev[0]). The present has
            # no "becoming" — it IS becoming. Set successor to None for i==0.
            # NOTE: rev[i].becoming = transition from rev[i] → rev[i-1] (i.e., the next moment).
            #       so we want successor = rev[i-1].
            # Wait — i=0 is the LATEST. There's nothing after it. Successor is None.
            #         i=1 is the second-latest; successor is rev[0].
            # That gives every record (except the present) a measurable becoming.
            if i == 0:
                successor = None
            else:
                successor = rev[i - 1]

            wave = present_rec.get("wave_emb") or []
            time_vec = present_rec.get("time_vec") or {}
            prompt = present_rec.get("original_prompt") or ""

            is_not_wave = self._is_not_wave(wave)
            is_not_time = self._is_not_time_forward(time_vec)
            is_not_sentence = self._is_not_sentence_preview(prompt)
            is_not_overlap_count = self._is_not_vector_overlap_count(prompt, chain)
            is_not_crystal = self._compute_is_not_crystal(
                present_rec.get("crystal_id", ""),
                is_not_wave, is_not_time, is_not_sentence, is_not_overlap_count,
            )

            becoming = self._becoming(present_rec, successor)
            becoming_crystal = self._compute_becoming_crystal(becoming, present_rec.get("crystal_id", ""))

            step = DialecticalStep(
                step_index=i,
                chain_index=present_rec.get("master_index", -1),
                present_crystal=present_rec.get("crystal_id", ""),
                present_tier=present_rec.get("tier", ""),
                present_model=present_rec.get("model", ""),
                present_timestamp=present_rec.get("timestamp", ""),
                present_prompt_preview=(prompt or "")[:120],
                present_wave_norm=math.sqrt(sum(x*x for x in wave)) if wave else 0.0,
                present_has_wave=bool(wave),
                present_has_time=bool(time_vec),
                is_not_wave=is_not_wave,
                is_not_time_forward=is_not_time,
                is_not_sentence_preview=is_not_sentence,
                is_not_vector_overlap_count=is_not_overlap_count,
                is_not_crystal=is_not_crystal,
                becoming_delta_seconds=becoming["delta_seconds"],
                becoming_value_delta_magnitude=becoming["value_delta_magnitude"],
                becoming_velocity=becoming["velocity"],
                becoming_color_velocity=becoming["color_velocity"],
                becoming_flow_sig_head=becoming["flow_sig_head"],
                becoming_target_crystal=becoming["target_crystal"],
                becoming_crystal=becoming_crystal,
                prev_step_crystal=prev_step_crystal,
            )
            step.crystal = self._compute_step_crystal(step)
            steps.append(step)

            prev_step_crystal = step.crystal

        # Fill next_step_crystal (link backward through the walk = forward through time)
        for i in range(len(steps) - 1):
            steps[i + 1].next_step_crystal = steps[i].crystal

        if write:
            self._write_chain(steps)
        return steps

    def _write_chain(self, steps: List[DialecticalStep]) -> None:
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.out_path, "w", encoding="utf-8") as f:
            # Chain root
            f.write(json.dumps({
                "type": "element", "name": "chain", "depth": 0,
                "attributes": {
                    "schema": "dialectic_chain_v0",
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "step_count": len(steps),
                    "anchor": "present" if steps else "",
                    "anchor_crystal": steps[0].present_crystal if steps else "",
                },
            }, sort_keys=True, ensure_ascii=True, separators=(",", ":")) + "\n")
            for step in steps:
                f.write(json.dumps({
                    "type": "element", "name": "dialectic_step", "depth": 1, "parent": "chain",
                    "attributes": {
                        "step_index":       step.step_index,
                        "chain_index":      step.chain_index,
                        "present_crystal":  step.present_crystal,
                        "is_not_crystal":   step.is_not_crystal,
                        "becoming_crystal": step.becoming_crystal,
                        "crystal":          step.crystal,
                        "prev_step_crystal":step.prev_step_crystal,
                        "next_step_crystal":step.next_step_crystal,
                        "becoming_velocity": round(step.becoming_velocity, 6),
                        "is_not_overlap_count": step.is_not_vector_overlap_count,
                    },
                    "data": {
                        "tier":  step.present_tier,
                        "model": step.present_model,
                        "ts":    step.present_timestamp,
                        "prompt_preview":          step.present_prompt_preview,
                        "is_not_sentence_preview": step.is_not_sentence_preview,
                        "is_not_wave_head":        [round(x, 5) for x in step.is_not_wave[:6]],
                        "is_not_time_head":        [round(x, 5) for x in step.is_not_time_forward[:6]],
                        "becoming_flow_sig_head":  [round(x, 5) for x in step.becoming_flow_sig_head],
                        "becoming_value_delta_mag": round(step.becoming_value_delta_magnitude, 5),
                        "becoming_delta_seconds":  round(step.becoming_delta_seconds, 3),
                    },
                }, sort_keys=True, ensure_ascii=True, separators=(",", ":")) + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main():
    import argparse
    ap = argparse.ArgumentParser(description="dialectic_walker — IS / IS-NOT / BECOMING")
    sub = ap.add_subparsers(dest="cmd")

    p_walk = sub.add_parser("walk", help="reverse-walk the crystal chain + emit dialectic_chain.jsonl")
    p_walk.add_argument("--no-write", action="store_true")

    p_summary = sub.add_parser("summary", help="walk + print a compact summary")

    p_step = sub.add_parser("step", help="show one DialecticalStep at index")
    p_step.add_argument("index", type=int)

    args = ap.parse_args()
    walker = DialecticWalker()

    if args.cmd == "walk":
        steps = walker.walk(write=not args.no_write)
        print(json.dumps({
            "steps":          len(steps),
            "anchor_present": steps[0].present_crystal[:16] if steps else "",
            "oldest":         steps[-1].present_crystal[:16] if steps else "",
            "out_path":       str(walker.out_path),
        }, indent=2))

    elif args.cmd == "summary":
        steps = walker.walk(write=False)
        print(f"=== dialectic walk · {len(steps)} steps (present → past) ===\n")
        for s in steps[:20]:
            arrow = "←" if s.becoming_target_crystal else " "
            print(f"  [step {s.step_index:>2}] {s.present_crystal[:12]} {arrow} "
                  f"v={s.becoming_velocity:>7.3f}  "
                  f"⊘={s.is_not_vector_overlap_count:>2}  "
                  f"| {s.present_prompt_preview[:60]}")
        if len(steps) > 20:
            print(f"  ... and {len(steps) - 20} more steps")

    elif args.cmd == "step":
        steps = walker.walk(write=False)
        if not (0 <= args.index < len(steps)):
            print(json.dumps({"error": f"index out of range; have {len(steps)} steps"}))
            return
        print(json.dumps(steps[args.index].to_compact_dict(), indent=2))

    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
