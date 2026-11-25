#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        morph_chain
# role:        SUBSTRATE · CRYSTALLIZED DAG-OF-DAGS (the object-of-objects)
# tier:        L0
# substrate:   content-addressed modality-transform chains ("wheels"). One
#              pivot (genesis crystal), wheels spin on the dimension sphere,
#              parent/child = crystal_id reference (no dimension change), mirrors
#              = antithesis, jurisdiction = scope. A chain IS a morph → nests.
# storage:     ~/.cc/morph_chains/<id>.json ; crystals → inference_master_chain
# reuse:       inference_logger (prev_crystal), dimension_pack (vec/circle/wave),
#              model_registry.resolve_role, planning/hf_task_evolution.jsonl
# ----------------------------------------------------------------------------
"""morph_chain — the wheel model.

A `Morph` is one modality transform (text→image, image→video, 3d→scene, rig.walk).
A `MorphChain` is an ordered, *cyclic* set of Morphs that is itself a Morph — so
chains nest into a DAG-of-DAGs (object-of-objects). Each step crystallizes onto
the prev-linked crystal chain (the Solana-style block chain you logSubscribe);
references resolve lazily by crystal_id (fetch, don't expand) so nesting never
changes dimension. The chain round-trips: to_prompt() (language pass) and
to_objects() (OO classes with global/local scope, for Replit/codegen).

CLI:
  morph build "text->image->video" [--scope global]
  morph dag <id>        morph decompose <id> <i>     morph prompt <id>
  morph objects <id>    morph crystallize <id>       morph fetch [--since X]
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
REPO = _HERE.parents[1]
HOME = Path(os.environ.get("CC_HOME", str(Path.home() / ".cc")))
CHAINS_DIR = HOME / "morph_chains"
MASTER_CHAIN = HOME / "inference_master_chain.jsonl"
TAXONOMY = REPO / "planning" / "hf_task_evolution.jsonl"

GENESIS = "0" * 64   # the pivot (0,0,0) — every chain roots here

# Control primitives — each wheel/node is one of these (or a plain transform).
# A spinning wheel IS a `while`; its closing rim IS the loop-back. if/and/or/
# true/false make the DAG-of-DAGs an executable control-flow graph.
CONTROL = ("morph", "start", "while", "if", "and", "or", "stop", "true", "false")
_CTRL_KEYWORDS = {"start", "while", "if", "and", "or", "stop", "true", "false"}

# modality word → taxonomy uppercase token
_MOD = {"text": "TEXT", "image": "IMAGE", "img": "IMAGE", "video": "VIDEO",
        "audio": "AUDIO", "speech": "AUDIO", "3d": "3D", "mesh": "3D",
        "scene": "SCENE", "depth": "DEPTH", "pose": "POSE", "label": "LABEL",
        "embedding": "EMB", "vector": "EMB", "code": "CODE", "rig": "3D"}


# ── model resolution (which HF model/Space/connector runs this transform) ─────

def _load_taxonomy() -> List[Dict[str, Any]]:
    out = []
    if TAXONOMY.exists():
        for ln in TAXONOMY.read_text().splitlines():
            ln = ln.strip()
            if ln:
                try:
                    out.append(json.loads(ln))
                except Exception:
                    pass
    return out


_TAX_CACHE: Optional[List[Dict[str, Any]]] = None


def _tax() -> List[Dict[str, Any]]:
    global _TAX_CACHE
    if _TAX_CACHE is None:
        _TAX_CACHE = _load_taxonomy()
    return _TAX_CACHE


def _tax_task_for(frm: str, to: str) -> Optional[Dict[str, Any]]:
    fi, ti = _MOD.get(frm, frm.upper()), _MOD.get(to, to.upper())
    for t in _tax():
        ins = [str(x).upper() for x in (t.get("inputs") or [])]
        outs = [str(x).upper() for x in (t.get("outputs") or [])]
        if fi in ins and ti in outs:
            return t
    return None


def resolve_model(op: str, frm: str, to: str) -> str:
    """Pick the model_ref (HF-Space / model / connector) that runs this morph."""
    # direct connector ops first
    if op in ("rig.walk", "model.build") or frm == "rig":
        return f"blender:{op if op in ('rig.walk', 'model.build') else 'rig.walk'}"
    if to == "scene":
        return "godot:asset_gallery"
    # taxonomy exemplar (a real HF model family for this modality edge)
    t = _tax_task_for(frm, to)
    if t and t.get("exemplars"):
        return f"hf:{t['task']}:{t['exemplars'][0]}"
    # fall back to the role map / provider ladder
    try:
        from model_registry import resolve_role  # type: ignore
        role = {"image": "image", "video": "video", "audio": "speech",
                "3d": "3d", "code": "code", "text": "chat"}.get(to, "chat")
        r = resolve_role(role)
        return f"{r.get('target', 'provider')}:{r.get('provider') or r.get('connector') or r.get('endpoint') or role}"
    except Exception:
        return f"unresolved:{frm}->{to}"


# ── the object-of-objects ─────────────────────────────────────────────────────

@dataclass
class Morph:
    """One transform. A node on a wheel's rim (a point on the dimension sphere)."""
    op: str
    from_modality: str
    to_modality: str
    model_ref: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    scope: str = "global"          # jurisdiction: global | local
    control: str = "morph"         # morph|start|while|if|and|or|stop|true|false
    cond: str = ""                 # predicate for if/while (e.g. "score>0.8")
    hitl: bool = False             # human-in-the-loop decision point
    hitl_note: str = ""            # what the human decides here
    ref: str = ""                  # crystal_id of a referenced wheel (= this node IS that wheel)
    mirror_of: str = ""            # crystal_id of the wheel this mirrors
    crystal_id: str = ""           # set on crystallize()
    dim: Dict[str, Any] = field(default_factory=dict)  # dimension_pack: vec/circle/rgba/frame


@dataclass
class MorphChain:
    """A cyclic set of Morphs that is itself a Morph (chains nest → DAG-of-DAGs).
    All wheels share the pivot (GENESIS) and spin on the same dimension sphere."""
    spec: str
    morphs: List[Morph] = field(default_factory=list)
    chain_id: str = ""
    pivot: str = GENESIS
    scope: str = "global"
    control: str = "start"   # the wheel's own kind: start|while|if|and|or|stop|...
    crystal_id: str = ""

    # the chain-as-a-morph view
    @property
    def from_modality(self) -> str:
        return self.morphs[0].from_modality if self.morphs else ""

    @property
    def to_modality(self) -> str:
        return self.morphs[-1].to_modality if self.morphs else ""

    def compose(self, other: "MorphChain") -> "MorphChain":
        m = MorphChain(spec=f"{self.spec};{other.spec}",
                       morphs=self.morphs + other.morphs, scope=self.scope)
        m.chain_id = _chain_id(m.spec)
        return m


def _chain_id(spec: str) -> str:
    return "morph_" + hashlib.blake2b(spec.encode(), digest_size=6).hexdigest()


def parse_spec(spec: str, scope: str = "global") -> MorphChain:
    """Parse a wheel spec. Stages are '->'-separated. A stage that is a control
    keyword (start/while/if/and/or/stop/true/false, optionally 'if:cond') becomes
    a control node; consecutive modality stages become transform morphs between
    them. e.g. 'start -> text -> image -> if:score>0.8 -> image->video -> stop'."""
    stages = [s.strip().lower() for s in spec.replace("→", "->").split("->") if s.strip()]
    morphs: List[Morph] = []
    prev_mod: Optional[str] = None
    for s in stages:
        base, _, cond = s.partition(":")
        base = base.strip()
        if base in _CTRL_KEYWORDS:
            morphs.append(Morph(op=base, from_modality="", to_modality="",
                                control=base, cond=cond.strip(), scope=scope))
            prev_mod = None      # control node breaks the modality run
        elif base in ("model.build", "rig.walk"):
            morphs.append(Morph(op=base, from_modality=prev_mod or "text", to_modality="3d",
                                model_ref=resolve_model(base, "text", "3d"), scope=scope))
            prev_mod = "3d"
        else:  # a modality token, optionally with {params}: "image{lipsync}"
            params: Dict[str, Any] = {}
            if "{" in base and base.endswith("}"):
                base, _, pstr = base.partition("{")
                base = base.strip()
                for tok in pstr.rstrip("}").split(","):
                    tok = tok.strip()
                    if tok:
                        k, _, v = tok.partition("=")
                        params[k.strip()] = (v.strip() or True)
            if prev_mod is not None:
                op = f"{prev_mod}->{base}"
                morphs.append(Morph(op=op, from_modality=prev_mod, to_modality=base,
                                    model_ref=resolve_model(op, prev_mod, base),
                                    params=params, scope=scope))
            prev_mod = base
    # the wheel's own kind: while if it loops, else start
    wheel_control = "while" if any(m.control == "while" for m in morphs) else "start"
    mc = MorphChain(spec=spec, morphs=morphs, chain_id=_chain_id(spec),
                    scope=scope, control=wheel_control)
    mark_hitl(mc)   # auto-identify where human decisions are made
    return mc


def mark_hitl(mc: MorphChain) -> List[int]:
    """Flag the human-in-the-loop decision points — the logically-placed gates
    where a person judges/approves before the chain commits. Heuristic:
      • subjective quality gates (lipsync approve, transcript verify),
      • commitment to an expensive/irreversible modality (→video, →3d),
      • any `if` whose condition isn't machine-evaluable (a judgment call),
      • the final output (ship the controllable character).
    Returns the indices marked."""
    marked = []
    n = len(mc.morphs)
    for i, m in enumerate(mc.morphs):
        note = ""
        if m.control == "if" and not any(o in m.cond for o in "<>=") and m.cond:
            note = f"judgment: {m.cond}?"
        elif m.params.get("lipsync"):
            note = "approve face + lipsync alignment"
        elif m.op == "speech->text":
            note = "verify transcript is correct"
        elif m.to_modality == "video":
            note = "approve motion / animation before committing"
        elif m.to_modality == "3d":
            note = "approve mesh + rig — is the character controllable?"
        elif m.to_modality == "label" or "classif" in m.op:
            note = "review classification / distance result"
        elif i == n - 1 and m.control == "morph":
            note = "ship: final review before commit"
        if note:
            m.hitl = True
            m.hitl_note = note
            marked.append(i)
    return marked


def hitl_points(mc: MorphChain) -> List[Dict[str, Any]]:
    return [{"node": i, "op": m.op, "decision": m.hitl_note}
            for i, m in enumerate(mc.morphs) if m.hitl]


# ── VALIDATION GATE — the description⟂function boundary (CC-codegen safety) ────
# The IR (this MorphChain) is the DESCRIPTION plane: GUI + Claude Code may author
# and edit it. But every transform node's kernel_ref must resolve against the
# closed, vetted FUNCTION plane (kernel_registry). If any node references a
# kernel that isn't in the registry — i.e. CC tried to invent executable work —
# the gate REJECTS the IR and the evaluator refuses to run it.

def validate_ir(mc: MorphChain) -> Dict[str, Any]:
    try:
        import kernel_registry as kr  # type: ignore
    except Exception as e:
        return {"ok": False, "errors": [f"kernel_registry unavailable: {e}"]}
    errors: List[str] = []
    bound: List[Dict[str, Any]] = []
    for i, m in enumerate(mc.morphs):
        if m.control != "morph":
            bound.append({"node": i, "kind": "control", "control": m.control})
            continue
        ref = m.model_ref or m.op
        kernel = kr.resolve(ref)
        if kernel is None:
            errors.append(f"node {i}: UNRESOLVED kernel_ref '{ref}' — not in the "
                          f"vetted registry (rejected; CC may only reference kernels)")
            continue
        if not kr.type_ok(kernel, m.from_modality, m.to_modality):
            errors.append(f"node {i}: type mismatch — kernel '{kernel['id']}' "
                          f"({kernel['in_type']}→{kernel['out_type']}) can't do "
                          f"{m.from_modality}→{m.to_modality}")
            continue
        bound.append({"node": i, "kernel_ref": ref, "kernel_id": kernel["id"],
                      "archetype": kernel["archetype"], "plane": kernel["plane"]})
    ctrl = validate(mc)              # fold in the control-flow structural checks
    errors += [f"control: {e}" for e in ctrl["errors"]]
    return {"ok": not errors, "errors": errors, "bound": bound,
            "control": ctrl, "kernels_bound": sum(1 for b in bound if "kernel_id" in b)}


def validate(mc: MorphChain) -> Dict[str, Any]:
    """Structural control-flow checks. Each wheel must resolve to a valid little
    program: bounded by start/stop, if/while carry a condition, true/false are
    outcomes, and/or have ≥2 operands feeding them."""
    errs, warns = [], []
    ctrls = [m.control for m in mc.morphs]
    if mc.morphs and ctrls[0] != "start":
        warns.append("wheel does not begin with 'start' (implicit entry assumed)")
    if mc.morphs and ctrls[-1] not in ("stop", "true", "false"):
        warns.append("wheel does not end with stop/true/false (implicit stop assumed)")
    for i, m in enumerate(mc.morphs):
        if m.control in ("if", "while") and not m.cond:
            errs.append(f"node {i} '{m.control}' missing a condition (use {m.control}:<cond>)")
        if m.control == "stop" and i != len(mc.morphs) - 1:
            warns.append(f"node {i} 'stop' is not terminal")
    has_loop = "while" in ctrls
    return {"ok": not errs, "errors": errs, "warnings": warns,
            "wheel_control": mc.control, "is_loop": has_loop,
            "controls": ctrls}


# ── decompose: expand a morph to HF-Spaces level (a nested wheel by reference) ─

def decompose(mc: MorphChain, i: int) -> MorphChain:
    """Expand morph i into a sub-chain from the taxonomy's depends_on, attach it
    as a referenced wheel (morph.ref). Recursive: the result is its own wheel."""
    if not (0 <= i < len(mc.morphs)):
        raise IndexError(f"morph index {i} out of range")
    m = mc.morphs[i]
    t = _tax_task_for(m.from_modality, m.to_modality)
    deps = (t or {}).get("depends_on") or []
    # build a sub-wheel: each dependency is a stage feeding the final transform
    sub_stages = [d for d in deps] + [(t or {}).get("task", m.op)]
    sub = MorphChain(spec=" -> ".join(sub_stages) or m.op, scope=m.scope)
    prev_mod = m.from_modality
    for stage in sub_stages:
        sub.morphs.append(Morph(op=stage, from_modality=prev_mod, to_modality=m.to_modality,
                                model_ref=resolve_model(stage, prev_mod, m.to_modality),
                                scope="local"))   # sub-steps run under local jurisdiction
    sub.chain_id = _chain_id(sub.spec + ":" + m.op)
    save(sub)
    m.ref = sub.chain_id    # parent/child by reference — no dimension change
    save(mc)
    return sub


# ── crystallize: link each step onto the prev-linked crystal chain ────────────

def crystallize(mc: MorphChain) -> MorphChain:
    """Write each morph to the crystal chain (auto prev-linked = the blockchain)
    and stamp a dimension_pack (vec64/circle/rgba/frame = sphere position)."""
    try:
        from inference_logger import InferenceLogger  # type: ignore
        il = InferenceLogger()
    except Exception:
        il = None
    try:
        import dimension_pack  # type: ignore
    except Exception:
        dimension_pack = None
    last = ""
    for k, m in enumerate(mc.morphs):
        cid = ""
        if il is not None:
            try:
                cid = il.log(
                    original_prompt=mc.spec,
                    enhanced_prompt=json.dumps({"op": m.op, "model_ref": m.model_ref,
                                                "ref": m.ref, "scope": m.scope}),
                    output_text=f"{m.from_modality}->{m.to_modality}",
                    tier="morph", model=m.model_ref or m.op, scope=m.op,
                    source_action="morph_chain.crystallize", source_step=k,
                    done_flag=True,
                ) or ""
            except Exception:
                cid = ""
        m.crystal_id = cid or hashlib.blake2b(
            (mc.spec + m.op + str(k)).encode(), digest_size=32).hexdigest()
        if dimension_pack is not None:
            try:
                pack = dimension_pack.emit({"tier": "morph", "sub_dag": "MORPH",
                                            "scope": m.op, "ts": time.time()}, m.crystal_id)
                m.dim = {"vec64": getattr(pack, "vector_hex_64", ""),
                         "circle": getattr(pack, "circle_motif_id", ""),
                         "rgba": getattr(pack, "rgba", []),
                         "frame60": getattr(pack, "frame_pack", {}).get(60, 0)}
            except Exception:
                pass
        last = m.crystal_id
    mc.crystal_id = last
    save(mc)
    return mc


# ── views (UI is just placement over the one object) ──────────────────────────

def to_dag(mc: MorphChain) -> Dict[str, Any]:
    """node/edge form the studio graph + ComfyUI render. Closed cycle (wheel):
    the last morph's edge loops back to the first (the rim)."""
    nodes, edges = [], []
    n = len(mc.morphs)
    for k, m in enumerate(mc.morphs):
        nodes.append({"id": k, "op": m.op, "control": m.control, "cond": m.cond,
                      "model_ref": m.model_ref, "scope": m.scope, "ref": m.ref,
                      "crystal": m.crystal_id, "dim": m.dim})
        if k > 0:
            edges.append({"from": k - 1, "to": k, "modality": m.from_modality or "seq"})
    # the rim: a while-wheel loops back (the spin); else it just closes the wheel
    if n > 1:
        edges.append({"from": n - 1, "to": 0,
                      "kind": "loop" if mc.control == "while" else "rim",
                      "closes": True})
    # if-branches: an 'if' node guards the nodes that follow it (true/false outcomes)
    for k, m in enumerate(mc.morphs):
        if m.control == "if":
            for j in range(k + 1, n):
                if mc.morphs[j].control in ("true", "false"):
                    edges.append({"from": k, "to": j, "kind": "branch",
                                  "on": mc.morphs[j].control})
    return {"chain_id": mc.chain_id, "pivot": mc.pivot, "control": mc.control,
            "from": mc.from_modality, "to": mc.to_modality,
            "nodes": nodes, "edges": edges}


def to_prompt(mc: MorphChain) -> str:
    """Language pass: render the wheel as a paragraph-form prompt (deterministic)."""
    if not mc.morphs:
        return "An empty workflow."
    parts = [f"A workflow that begins with {mc.from_modality} and produces {mc.to_modality}, "
             f"spinning about a shared origin."]
    for k, m in enumerate(mc.morphs):
        ref = f" (which decomposes into wheel {m.ref})" if m.ref else ""
        parts.append(f"Step {k + 1}: transform {m.from_modality} into {m.to_modality} "
                     f"via {m.model_ref or m.op}{ref}, under {m.scope} jurisdiction.")
    parts.append("The chain closes on itself as a wheel and roots to the genesis pivot.")
    return " ".join(parts)


def to_objects(mc: MorphChain) -> Dict[str, Any]:
    """The OO structure: chain → class; each morph → a class with scope + methods;
    referenced wheels nest as sub-objects. This is the object-of-objects, ready
    for deploy.py / Replit codegen."""
    def _cls(name: str) -> str:
        return "".join(p.capitalize() for p in name.replace("->", "_to_").replace(".", "_").split("_")) or "Morph"

    members = []
    for m in mc.morphs:
        if m.control == "morph":
            obj = {"kind": "call", "class": _cls(m.op), "scope": m.scope,
                   "op": m.op, "model_ref": m.model_ref, "calls": []}
        elif m.control == "while":
            obj = {"kind": "loop", "while": m.cond, "scope": m.scope}     # the spinning wheel
        elif m.control == "if":
            obj = {"kind": "branch", "if": m.cond, "scope": m.scope}
        elif m.control in ("true", "false"):
            obj = {"kind": "literal", "value": m.control == "true"}
        elif m.control in ("and", "or"):
            obj = {"kind": "boolean", "op": m.control}
        elif m.control == "start":
            obj = {"kind": "entry"}
        elif m.control == "stop":
            obj = {"kind": "return"}
        else:
            obj = {"kind": m.control}
        if m.ref:
            sub = load(m.ref)
            if sub is not None:
                obj.setdefault("calls", []).append(to_objects(sub))  # nest referenced wheel
        members.append(obj)
    return {"class": _cls((mc.spec.split("->")[0] or "wheel") + "_chain"),
            "control": mc.control, "scope": mc.scope, "pivot": mc.pivot,
            "chain_id": mc.chain_id, "members": members}


# ── persistence + fetch/subscribe (logSubscribe-style) ────────────────────────

def save(mc: MorphChain) -> Path:
    CHAINS_DIR.mkdir(parents=True, exist_ok=True)
    p = CHAINS_DIR / f"{mc.chain_id}.json"
    p.write_text(json.dumps({"spec": mc.spec, "chain_id": mc.chain_id,
                             "pivot": mc.pivot, "scope": mc.scope,
                             "control": mc.control, "crystal_id": mc.crystal_id,
                             "morphs": [asdict(m) for m in mc.morphs]}, indent=2))
    return p


def load(chain_id: str) -> Optional[MorphChain]:
    p = CHAINS_DIR / f"{chain_id}.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text())
    mc = MorphChain(spec=d["spec"], chain_id=d["chain_id"], pivot=d.get("pivot", GENESIS),
                    scope=d.get("scope", "global"), control=d.get("control", "start"),
                    crystal_id=d.get("crystal_id", ""))
    mc.morphs = [Morph(**m) for m in d.get("morphs", [])]
    return mc


def fetch(since_crystal: str = "") -> List[Dict[str, Any]]:
    """logSubscribe-style: return morph crystals from the master chain after a
    given crystal (the DAG-of-DAGs is a chain you fetch, like the wallet monitor)."""
    if not MASTER_CHAIN.exists():
        return []
    out, seen_since = [], (since_crystal == "")
    for ln in MASTER_CHAIN.read_text().splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            r = json.loads(ln)
        except Exception:
            continue
        if r.get("tier") != "morph" and r.get("scope", "").find("->") < 0:
            continue
        if not seen_since:
            if r.get("crystal_id") == since_crystal:
                seen_since = True
            continue
        out.append({"crystal_id": r.get("crystal_id"), "prev": r.get("prev_crystal"),
                    "op": r.get("scope"), "model": r.get("model")})
    return out


# ── UI cards: break each morph into the UI it needs (how/when/why/choices) ────
# A host-agnostic card spec. The studio Streamlit rail (flows.predict_deck) and a
# generated ComfyUI node both render the same card. "The card of UI choices."

def _op_to_task(op: str) -> str:
    """morph op 'text->image' → HF task name 'Text-to-Image' (taxonomy key)."""
    if "->" not in op:
        return op
    a, b = op.split("->", 1)
    return f"{a.strip().title()}-to-{b.strip().title()}"


def _widgets(m: "Morph") -> List[Dict[str, Any]]:
    """The UI controls this morph needs (HOW the human steers it)."""
    w: List[Dict[str, Any]] = []
    if m.control == "if":
        w.append({"name": "condition", "widget": "text", "value": m.cond})
    elif m.control == "while":
        w += [{"name": "condition", "widget": "text", "value": m.cond},
              {"name": "max_loops", "widget": "slider", "min": 1, "max": 64, "value": 8}]
    elif m.control in ("true", "false", "and", "or", "start", "stop"):
        pass  # pure control — no inputs
    else:  # a transform morph
        # the model is a dropdown of alternatives (taxonomy exemplars for the task)
        task = _op_to_task(m.op)
        alts = []
        for t in _tax():
            if t.get("task") == task:
                alts = t.get("exemplars", [])[:6]
                break
        w.append({"name": "model", "widget": "select", "value": m.model_ref,
                  "options": alts or [m.model_ref]})
        for k, v in (m.params or {}).items():
            w.append({"name": k, "widget": "toggle" if v is True else "text", "value": v})
        w.append({"name": "scope", "widget": "select", "value": m.scope,
                  "options": ["global", "local"]})
    if m.hitl:
        w.append({"name": "decision", "widget": "buttons",
                  "options": ["approve", "redo", "reject"], "prompt": m.hitl_note})
    return w


def _why_when(mc: MorphChain, i: int) -> Dict[str, str]:
    """WHY this card is offered + WHEN it activates."""
    m = mc.morphs[i]
    if m.hitl:
        why = f"human decision: {m.hitl_note}"
    elif m.control == "if":
        why = "branch point — pick the path"
    elif m.control == "while":
        why = "loop — repeat until the condition clears"
    elif m.from_modality:
        why = f"chainable: consumes {m.from_modality}, produces {m.to_modality}"
    else:
        why = m.control
    if i == 0:
        when = "at chain start"
    elif m.control in ("true", "false"):
        when = f"on the {m.control} branch"
    elif mc.morphs[i - 1].control == "while":
        when = "each loop iteration"
    else:
        when = f"after node {i - 1} ({mc.morphs[i-1].op}) completes"
    return {"why": why, "when": when}


def to_cards(mc: MorphChain) -> List[Dict[str, Any]]:
    """Break the wheel into a deck of UI cards — one per morph."""
    cards = []
    for i, m in enumerate(mc.morphs):
        ww = _why_when(mc, i)
        kind = "decision" if m.hitl else ("control" if m.control != "morph" else "transform")
        cards.append({"node": i, "title": m.op, "kind": kind,
                      "control": m.control, "hitl": m.hitl,
                      "why": ww["why"], "when": ww["when"],
                      "widgets": _widgets(m)})
    return cards


def deck(mc: MorphChain, anchor: int) -> Dict[str, Any]:
    """The card of UI CHOICES at a focus node: the current card, plus alternative
    routes (accent siblings + chainable next steps from the top wheel). Mirrors
    the studio predict_deck — choices surfaced by the current focus."""
    if not (0 <= anchor < len(mc.morphs)):
        return {"error": "anchor out of range"}
    m = mc.morphs[anchor]
    cards = to_cards(mc)
    cur = cards[anchor]
    nbrs = neighbors(_op_to_task(m.op)) if m.control == "morph" else {}
    choices = []
    for alt in nbrs.get("accent", [])[:5]:
        choices.append({"choice": alt, "why": "accent sibling — complements this step"})
    for nxt in nbrs.get("chainable_into", [])[:5]:
        choices.append({"choice": nxt, "why": "chainable next — this output feeds it"})
    if m.hitl:
        choices = [{"choice": c, "why": m.hitl_note}
                   for c in ("approve", "redo", "reject")] + choices
    return {"anchor": anchor, "card": cur, "choices": choices}


# ── execute: spin a wheel and watch it run ────────────────────────────────────
# Motion is frame-relative: a referenced wheel SPINS in its own frame (depth+1,
# many ticks) but is a single FIXED node in the frame that references it. The
# trace makes that visible.

def _eval_cond(cond: str, ctx: Dict[str, Any], loop_index: int = 0) -> bool:
    """Evaluate a tiny 'var OP number' predicate. While-loop vars resolve to the
    loop index; unknown if-vars default truthy so the true branch is exercised."""
    if not cond:
        return True
    for op in ("<=", ">=", "==", "!=", "<", ">"):
        if op in cond:
            var, _, rhs = cond.partition(op)
            var, rhs = var.strip(), rhs.strip()
            try:
                rv = float(rhs)
            except ValueError:
                rv = 0.0
            lv = float(ctx.get(var, loop_index if loop_index or var in ("frames", "i", "n", "count") else 1.0))
            return {"<": lv < rv, ">": lv > rv, "<=": lv <= rv, ">=": lv >= rv,
                    "==": lv == rv, "!=": lv != rv}[op]
    return bool(ctx.get(cond.strip(), True))


def _run_transform(m: "Morph", live: bool) -> str:
    """A morph 'spins' = its transform fires. Dry by default (build-safe): just
    names the model_ref. --live would dispatch the connector (blender/generate)."""
    if not live:
        return f"[dry] {m.model_ref or m.op}"
    try:
        if m.model_ref.startswith("blender:") or m.to_modality == "3d":
            from model_api import _api  # type: ignore
            r = _api().connector_call("generate", "3d", {"prompt": m.op})
            return f"[live] {r.get('output') or r.get('error')}"
    except Exception as e:
        return f"[live-err] {e}"
    return f"[skipped-live] {m.model_ref or m.op}"


def execute(mc: MorphChain, context: Optional[Dict[str, Any]] = None,
            live: bool = False, max_loops: int = 3, max_steps: int = 200) -> Dict[str, Any]:
    """Walk the control flow and return a trace. start/stop bound it, `if` branches
    to true/false, `while` spins back along the rim, a referenced wheel recurses
    (inner motion = one outer fixed node)."""
    # GATE: the evaluator only runs IR that passed validation against the closed
    # kernel registry. An IR referencing an unvetted kernel never executes.
    gate = validate_ir(mc)
    if not gate["ok"]:
        return {"ok": False, "refused": True, "reason": "validation_gate",
                "errors": gate["errors"], "trace": []}
    ctx = dict(context or {})
    trace: List[Dict[str, Any]] = []
    budget = {"steps": max_steps}

    def _spin(wheel: MorphChain, depth: int, tick: List[int]) -> None:
        pc, loop_counts, last_if = 0, {}, True
        n = len(wheel.morphs)
        while 0 <= pc < n and budget["steps"] > 0:
            budget["steps"] -= 1
            tick[0] += 1
            m = wheel.morphs[pc]
            rec = {"tick": tick[0], "depth": depth, "frame": wheel.chain_id,
                   "node": pc, "control": m.control, "op": m.op}
            ctl = m.control
            if ctl == "start":
                rec["action"] = "enter"; pc += 1
            elif ctl == "stop":
                rec["action"] = "stop"; trace.append(rec); break
            elif ctl == "if":
                last_if = _eval_cond(m.cond, ctx)
                rec["action"] = f"if({m.cond}) → {last_if}"; pc += 1
            elif ctl == "true":
                taken = last_if is True
                rec["action"] = "branch:true " + ("taken" if taken else "skipped"); pc += 1
            elif ctl == "false":
                taken = last_if is False
                rec["action"] = "branch:false " + ("taken" if taken else "skipped"); pc += 1
            elif ctl in ("and", "or"):
                rec["action"] = f"boolean:{ctl}"; pc += 1
            elif ctl == "while":
                c = loop_counts.get(pc, 0)
                go = _eval_cond(m.cond, ctx, loop_index=c) and c < max_loops
                if go:
                    loop_counts[pc] = c + 1
                    rec["action"] = f"while({m.cond}) iter={c} → spin back to rim(0)"
                    trace.append(rec); pc = 0; continue
                rec["action"] = f"while({m.cond}) → exit after {c} spins"; pc += 1
            else:  # a transform morph
                if m.ref:
                    sub = load(m.ref)
                    rec["action"] = "reference → spins in its own frame (FIXED here)"
                    rec["ref"] = m.ref
                    trace.append(rec)
                    if sub is not None:
                        _spin(sub, depth + 1, tick)   # inner motion
                    pc += 1
                    continue
                if m.hitl:
                    rec["hitl"] = m.hitl_note
                    rec["action"] = f"⏸ HUMAN: {m.hitl_note} → approved · then spin: {_run_transform(m, live)}"
                else:
                    rec["action"] = f"spin: {_run_transform(m, live)}"
                pc += 1
            trace.append(rec)

    _spin(mc, 0, [0])
    # frame-relativity summary: how many ticks each frame logged
    frames: Dict[str, Dict[str, Any]] = {}
    for e in trace:
        f = frames.setdefault(e["frame"], {"depth": e["depth"], "ticks": 0})
        f["ticks"] += 1
    outer_nodes = sum(1 for e in trace if e["depth"] == 0)
    return {"chain_id": mc.chain_id, "control": mc.control, "ticks": len(trace),
            "frames": frames, "outer_frame_nodes": outer_nodes, "trace": trace,
            "relativity": "a referenced wheel logs its own motion (depth>0) yet is "
                          "one fixed node in the outer frame"}


# ── the TOP WHEEL: the whole HF task taxonomy as one wheel ────────────────────
# Every HF task is a node; categories are the wheel's sectors. Three edge kinds
# express "workflows that accent each other":
#   chainable  — outputs(A) ∩ inputs(B) ≠ ∅   (A can feed B → compose a workflow)
#   enables    — B ∈ A.enables (taxonomy)      (A unlocks B → the dependency DAG)
#   accent     — same sector + shared modality (siblings that complement each other)

# canonical sector order (matches the HF Tasks panel) → each gets an arc of the wheel
_SECTORS = ["Multimodal", "Computer Vision", "Natural Language Processing",
            "Audio", "Tabular", "Reinforcement Learning", "Other"]


def top_wheel() -> Dict[str, Any]:
    tax = _tax()
    by_task = {t["task"]: t for t in tax}
    # group into sectors + assign each task an angle on the rim
    sectors: Dict[str, List[str]] = {}
    for t in tax:
        sectors.setdefault(t.get("category", "Other"), []).append(t["task"])
    nodes = []
    n_sec = len(_SECTORS)
    for si, sec in enumerate(_SECTORS):
        tasks = sectors.get(sec, [])
        arc0 = 360.0 * si / max(1, n_sec)
        for ti, task in enumerate(tasks):
            t = by_task[task]
            ang = arc0 + (360.0 / n_sec) * (ti / max(1, len(tasks)))
            nodes.append({"task": task, "sector": sec, "angle": round(ang, 2),
                          "inputs": t.get("inputs", []), "outputs": t.get("outputs", []),
                          "exemplars": (t.get("exemplars") or [])[:3]})
    # edges
    edges = []
    for a in tax:
        ao = {str(x).upper() for x in (a.get("outputs") or [])}
        # enables (directional dependency DAG)
        for b in (a.get("enables") or []):
            if b in by_task:
                edges.append({"from": a["task"], "to": b, "kind": "enables"})
        for b in tax:
            if a["task"] == b["task"]:
                continue
            bi = {str(x).upper() for x in (b.get("inputs") or [])}
            if ao & bi:
                edges.append({"from": a["task"], "to": b["task"], "kind": "chainable",
                              "via": sorted(ao & bi)})
    # accent: same sector + shared modality (undirected complements)
    seen = set()
    for sec, tasks in sectors.items():
        for i in range(len(tasks)):
            for j in range(i + 1, len(tasks)):
                ta, tb = by_task[tasks[i]], by_task[tasks[j]]
                mods_a = {str(x).upper() for x in (ta.get("inputs", []) + ta.get("outputs", []))}
                mods_b = {str(x).upper() for x in (tb.get("inputs", []) + tb.get("outputs", []))}
                if mods_a & mods_b:
                    key = tuple(sorted((tasks[i], tasks[j])))
                    if key not in seen:
                        seen.add(key)
                        edges.append({"from": key[0], "to": key[1], "kind": "accent",
                                      "via": sorted(mods_a & mods_b)})
    return {"pivot": GENESIS, "sectors": _SECTORS,
            "counts": {"tasks": len(nodes),
                       "chainable": sum(1 for e in edges if e["kind"] == "chainable"),
                       "enables": sum(1 for e in edges if e["kind"] == "enables"),
                       "accent": sum(1 for e in edges if e["kind"] == "accent")},
            "nodes": nodes, "edges": edges}


def neighbors(task: str, kind: str = "") -> Dict[str, List[str]]:
    """Workflows/tasks that accent a given task: what it chains into, what it
    enables, and its accent-siblings. The 'relationships to workflows' surface."""
    w = top_wheel()
    out = {"chainable_into": [], "feeds_from": [], "enables": [], "enabled_by": [], "accent": []}
    for e in w["edges"]:
        if kind and e["kind"] != kind:
            continue
        if e["kind"] == "chainable":
            if e["from"] == task:
                out["chainable_into"].append(e["to"])
            if e["to"] == task:
                out["feeds_from"].append(e["from"])
        elif e["kind"] == "enables":
            if e["from"] == task:
                out["enables"].append(e["to"])
            if e["to"] == task:
                out["enabled_by"].append(e["from"])
        elif e["kind"] == "accent":
            if task in (e["from"], e["to"]):
                out["accent"].append(e["to"] if e["from"] == task else e["from"])
    return {k: sorted(set(v)) for k, v in out.items()}


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv: List[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, args = argv[0], argv[1:]

    def opt(flag, dflt=""):
        return args[args.index(flag) + 1] if flag in args and args.index(flag) + 1 < len(args) else dflt

    if cmd == "build":
        if not args:
            print("usage: build \"text->image->video\" [--scope global]"); return 2
        mc = parse_spec(args[0], scope=opt("--scope", "global"))
        save(mc)
        print(json.dumps(to_dag(mc), indent=2))
        print(f"\n[morph] chain_id={mc.chain_id}", file=sys.stderr)
        return 0
    if cmd == "run":
        if not args:
            print("usage: run <chain_id> [--live] [--max-loops N] [--json]"); return 2
        mc = load(args[0])
        if mc is None:
            print(f"no chain {args[0]}", file=sys.stderr); return 1
        res = execute(mc, live="--live" in args, max_loops=int(opt("--max-loops", "3")))
        if "--json" in args:
            print(json.dumps(res, indent=2)); return 0 if res.get("ok", True) else 7
        if res.get("refused"):
            print(f"⛔ REFUSED at the validation gate ({res['reason']}):")
            for e in res["errors"]:
                print(f"   • {e}")
            print("\n— the evaluator runs only IR bound to the vetted kernel registry.")
            return 7
        # watch it run — indent by depth so inner-wheel motion is visually nested
        print(f"▶ spinning wheel {mc.chain_id} (control={mc.control})\n")
        for e in res["trace"]:
            ind = "    " * e["depth"]
            spin = "⏸" if e.get("hitl") else ("↻" if e["control"] == "while" else ("◆" if e["control"] in ("if", "true", "false", "and", "or") else "•"))
            print(f"{e['tick']:>3} {ind}{spin} [{e['frame'][:14]}] n{e['node']} {e['control']:<6} {e['action']}")
        print(f"\n— {res['ticks']} ticks across {len(res['frames'])} frame(s); "
              f"outer frame = {res['outer_frame_nodes']} fixed nodes")
        for f, info in res["frames"].items():
            tag = "outer (fixed lattice)" if info["depth"] == 0 else f"depth {info['depth']} (in motion)"
            print(f"    {f[:14]}: {info['ticks']} ticks — {tag}")
        print(f"  ⟳ {res['relativity']}")
        return 0
    if cmd == "cards":
        if not args:
            print("usage: cards <chain_id>"); return 2
        mc = load(args[0])
        if mc is None:
            print(f"no chain {args[0]}", file=sys.stderr); return 1
        print(json.dumps(to_cards(mc), indent=2))
        return 0
    if cmd == "deck":
        if len(args) < 2:
            print("usage: deck <chain_id> <node>"); return 2
        mc = load(args[0])
        if mc is None:
            print(f"no chain {args[0]}", file=sys.stderr); return 1
        print(json.dumps(deck(mc, int(args[1])), indent=2))
        return 0
    if cmd == "hitl":
        if not args:
            print("usage: hitl <chain_id>"); return 2
        mc = load(args[0])
        if mc is None:
            print(f"no chain {args[0]}", file=sys.stderr); return 1
        pts = hitl_points(mc)
        print(json.dumps({"chain_id": mc.chain_id, "human_decisions": len(pts),
                          "points": pts}, indent=2))
        return 0
    if cmd == "validate":
        if not args:
            print("usage: validate <chain_id>"); return 2
        mc = load(args[0])
        if mc is None:
            print(f"no chain {args[0]}", file=sys.stderr); return 1
        print(json.dumps(validate(mc), indent=2))
        return 0
    if cmd == "validate-ir":
        if not args:
            print("usage: validate-ir <chain_id>"); return 2
        mc = load(args[0])
        if mc is None:
            print(f"no chain {args[0]}", file=sys.stderr); return 1
        res = validate_ir(mc)
        print(json.dumps(res, indent=2))
        return 0 if res["ok"] else 7
    if cmd in ("dag", "prompt", "objects", "crystallize"):
        if not args:
            print(f"usage: {cmd} <chain_id>"); return 2
        mc = load(args[0])
        if mc is None:
            print(f"no chain {args[0]}", file=sys.stderr); return 1
        if cmd == "dag":
            print(json.dumps(to_dag(mc), indent=2))
        elif cmd == "prompt":
            print(to_prompt(mc))
        elif cmd == "objects":
            print(json.dumps(to_objects(mc), indent=2))
        elif cmd == "crystallize":
            crystallize(mc)
            print(json.dumps({"chain_id": mc.chain_id, "crystal_id": mc.crystal_id,
                              "links": [m.crystal_id[:12] for m in mc.morphs]}, indent=2))
        return 0
    if cmd == "decompose":
        if len(args) < 2:
            print("usage: decompose <chain_id> <i>"); return 2
        mc = load(args[0])
        if mc is None:
            print(f"no chain {args[0]}", file=sys.stderr); return 1
        sub = decompose(mc, int(args[1]))
        print(json.dumps({"parent": mc.chain_id, "morph": int(args[1]),
                          "sub_wheel": sub.chain_id, "sub_dag": to_dag(sub)}, indent=2))
        return 0
    if cmd == "fetch":
        print(json.dumps(fetch(opt("--since", "")), indent=2))
        return 0
    if cmd == "top-wheel":
        print(json.dumps(top_wheel(), indent=2))
        return 0
    if cmd == "neighbors":
        if not args:
            print("usage: neighbors \"<task>\" [--kind chainable|enables|accent]"); return 2
        print(json.dumps(neighbors(args[0], kind=opt("--kind", "")), indent=2))
        return 0
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
