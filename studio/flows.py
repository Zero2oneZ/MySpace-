"""Workflow chaining + deterministic GUI-card deck predictor.

Implements /home/tom/models/DAG-FLOW.md §2 (algorithm), §4 (flow registry),
§5 (default weights), §6 (bridge cards) and §7 (determinism contract).

Public API:
  FLOWS                — registry of named flows (DAG-FLOW.md §4)
  BRIDGES              — type-converter sub-chains (DAG-FLOW.md §6)
  KIND_WEIGHT          — default kind priors (DAG-FLOW.md §5)
  predict_deck(...)    — pure function returning ranked list of cards
  flow_for_anchor(...) — which flow step (if any) the anchor sits on
  cards_for_node(nid)  — the GUI cards a node-id contributes
  load_flow(flow_id)   — return the node-id chain for a flow
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

from nodes import NODES_BY_ID, nodes_accepting
from types_meta import types_compatible, TYPE_COERCIONS  # noqa: F401


# ─── §5 default weights ──────────────────────────────────────────────────────
KIND_WEIGHT = {
    "output": 0.95,
    "model":  0.80,
    "tool":   0.70,
    "bridge": 0.60,
    "lora":   0.30,
    "class":  0.10,
    "input":  0.05,
}

# Type → its natural output (sink) node-id
SINK_FOR_TYPE = {
    "IMG":  "OUT_IMG",
    "VID":  "OUT_VID",
    "AUD":  "OUT_AUD",
    "TXT":  "OUT_TXT",
    "MD":   "OUT_MD",
    "3D":   "OUT_3D",
    "DEPTH": "OUT_DEPTH",
    "MASK": "OUT_MASK",
    "KPTS": "OUT_KPTS",
    "EMB":  "OUT_EMB",
    "MUS":  "OUT_MUS",
}


# ─── §6 bridges ──────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Bridge:
    id: str
    src_type: str
    dst_type: str
    chain: tuple[str, ...]      # node-ids to instantiate, in order
    hint: str


BRIDGES: tuple[Bridge, ...] = (
    Bridge("BR-EMB-TXT", "EMB", "TXT", ("M_GEMMA",),       "treat embedding as context for gemma"),
    Bridge("BR-MD-TXT",  "MD",  "TXT", (),                 "MD viewer also accepts TXT"),
    Bridge("BR-TXT-MUS", "TXT", "MUS", ("M_MFLOW",),       "prompt → melodyflow"),
    Bridge("BR-TXT-AUD", "TXT", "AUD", ("M_QTTS",),        "prompt → Qwen3-TTS speech"),
    Bridge("BR-TXT-VID", "TXT", "VID", ("T_LTX",),         "prompt → LTX2.3 video"),
    Bridge("BR-IMG-VID", "IMG", "VID", ("T_LCV",),         "portrait → LongCat avatar (needs AUD)"),
    Bridge("BR-VID-TXT", "VID", "TXT", ("M_MAR",),         "video → Marlin dense caption"),
    Bridge("BR-AUD-TXT", "AUD", "TXT", ("M_UV",),          "audio → ultravox transcript"),
    Bridge("BR-PDF-TXT", "PDF", "TXT", ("T_MINE", "M_GEMMA"), "pdf → MinerU MD → gemma TXT"),
)

BRIDGES_BY_ID = {b.id: b for b in BRIDGES}
BRIDGES_FROM: dict[str, list[Bridge]] = {}
for _b in BRIDGES:
    BRIDGES_FROM.setdefault(_b.src_type, []).append(_b)


# ─── §4 flow registry ────────────────────────────────────────────────────────
@dataclass(frozen=True)
class FlowStep:
    anchor: str                 # node-id the user is on at this step
    lead: Optional[str]         # lead card id (or None if step is terminal)
    deck: tuple[str, ...] = ()  # secondary card ids (excluding lead)
    params: dict = field(default_factory=dict)   # pinned param overrides on lead


@dataclass(frozen=True)
class Flow:
    id: str
    name: str
    goal: str
    steps: tuple[FlowStep, ...]

    @property
    def chain(self) -> list[str]:
        """Flat node-id chain (for instantiation via load_recipe)."""
        seq = []
        for s in self.steps:
            if s.anchor not in seq:
                seq.append(s.anchor)
            if s.lead and s.lead not in seq:
                seq.append(s.lead)
        return seq


FLOWS: tuple[Flow, ...] = (
    Flow("F-PHOTO-3D", "Photo → 3D mesh", "image → 3D mesh", (
        FlowStep("IN_IMG",   "M_DEPTH", ("T_CLIP", "M_POSE")),
        FlowStep("M_DEPTH",  "M_PX3D",  ()),
        FlowStep("M_PX3D",   "OUT_3D",  ()),
    )),
    Flow("F-NARRATE-VIDEO", "Video → spoken summary", "VID → AUD narration", (
        FlowStep("IN_VID",   "M_MAR",   ("M_STG", "M_PEAV"), {"mode": "caption"}),
        FlowStep("M_MAR",    "M_GEMMA", ("OUT_TXT",)),
        FlowStep("M_GEMMA",  "M_QTTS",  ()),
        FlowStep("M_QTTS",   "OUT_AUD", ("T_LCV",)),
    )),
    Flow("F-AVATAR-RECAP", "Video → narrated avatar", "video → narrated talking-head", (
        FlowStep("IN_VID",   "M_MAR",   (), {"mode": "caption"}),
        FlowStep("M_MAR",    "M_GEMMA", ()),
        FlowStep("M_GEMMA",  "M_QTTS",  ()),
        FlowStep("M_QTTS",   "T_LCV",   ("IN_IMG",)),
        FlowStep("T_LCV",    "OUT_VID", ()),
    )),
    Flow("F-CAPTION-FAST", "Video → short caption", "VID → 1-line TXT", (
        FlowStep("IN_VID",   "M_STG",   ("M_MAR",)),
        FlowStep("M_STG",    "OUT_TXT", ("M_GEMMA",)),
    )),
    Flow("F-FIND-MOMENT", "Find moment in video", "VID + TXT → (start,end)", (
        FlowStep("IN_VID",   "IN_TXT",  ("M_MAR",)),
        FlowStep("IN_TXT",   "M_MAR",   (), {"mode": "find"}),
        FlowStep("M_MAR",    "OUT_TXT", ()),
    )),
    Flow("F-PDF-AUDIOBOOK", "PDF → audiobook", "PDF → AUD", (
        FlowStep("IN_PDF",   "T_MINE",  ()),
        FlowStep("T_MINE",   "M_GEMMA", ()),
        FlowStep("M_GEMMA",  "M_QTTS",  ()),
        FlowStep("M_QTTS",   "OUT_AUD", ()),
    )),
    Flow("F-VOICE-REPLY", "Voice memo → spoken reply", "AUD → AUD reply", (
        FlowStep("IN_AUD",   "M_UV",    ("T_VOX",)),
        FlowStep("M_UV",     "M_GEMMA", ()),
        FlowStep("M_GEMMA",  "M_QTTS",  ()),
        FlowStep("M_QTTS",   "OUT_AUD", ()),
    )),
    Flow("F-MOOD-MUSIC", "Image → mood music", "IMG → MUS", (
        FlowStep("IN_IMG",   "T_CLIP",  ()),
        FlowStep("T_CLIP",   "M_MFLOW", ("M_GEMMA",)),
        FlowStep("M_MFLOW",  "OUT_MUS", ()),
    )),
    Flow("F-POSE-RESTYLE", "Image → posed restyle", "IMG → IMG", (
        FlowStep("IN_IMG",   "M_POSE",  ("T_CLIP",)),
        FlowStep("M_POSE",   "T_QPOSE", ()),
        FlowStep("T_QPOSE",  "OUT_IMG", ("T_FIRE",)),
    )),
    Flow("F-T2V", "Auto-prompt → T2V", "IMG → VID", (
        FlowStep("IN_IMG",   "T_CLIP",  ()),
        FlowStep("T_CLIP",   "T_LTX",   ("M_MFLOW",)),
        FlowStep("T_LTX",    "OUT_VID", ()),
    )),
    Flow("F-VOICE-AB", "Voice A/B/C audition", "TXT → 3× AUD", (
        FlowStep("IN_TXT",   "M_QTTS",  (), {"timbre": "t1"}),
        FlowStep("M_QTTS",   "OUT_AUD", ()),
    )),
    Flow("F-SUBJECT-CUT", "Image + box → subject-only", "IMG → IMG (cut-out)", (
        FlowStep("IN_IMG",   "IN_BOX",  ("M_SEG",)),
        FlowStep("IN_BOX",   "M_SEG",   ()),
        FlowStep("M_SEG",    "T_FSWAP", ("T_VBG",)),
        FlowStep("T_FSWAP",  "OUT_IMG", ()),
    )),
)

FLOWS_BY_ID = {f.id: f for f in FLOWS}


# ─── card materialisation ────────────────────────────────────────────────────
@dataclass(frozen=True)
class Card:
    id: str                  # mirrors node-id or BR-* id
    title: str
    kind: str                # input|model|tool|lora|class|output|bridge|sink
    accepts: tuple[str, ...]
    produces: tuple[str, ...]
    weight: float
    hint: str
    chain: tuple[str, ...] = ()      # for bridges: the sub-chain to instantiate
    pinned_params: dict = field(default_factory=dict)


def _card_for_node(nid: str, weight: Optional[float] = None,
                   hint: str = "", pinned_params: Optional[dict] = None) -> Card:
    spec = NODES_BY_ID[nid]
    kind = spec["kind"]
    w = weight if weight is not None else KIND_WEIGHT.get(kind, 0.5)
    out_types = tuple(p["type"] for p in spec["outputs"])
    in_types = tuple(p["type"] for p in spec["inputs"])
    return Card(
        id=nid,
        title=spec["name"],
        kind=kind,
        accepts=in_types,
        produces=out_types,
        weight=w,
        hint=hint or _default_hint(spec),
        pinned_params=pinned_params or {},
    )


def _default_hint(spec: dict) -> str:
    ins = " ".join(p["type"] for p in spec["inputs"]) or "—"
    outs = " ".join(p["type"] for p in spec["outputs"]) or "—"
    vram = spec.get("vram_gb", 0)
    return f"{ins} → {outs} · {vram}GB"


def _card_for_bridge(b: Bridge) -> Card:
    return Card(
        id=b.id,
        title=f"{b.src_type}→{b.dst_type} bridge",
        kind="bridge",
        accepts=(b.src_type,),
        produces=(b.dst_type,),
        weight=KIND_WEIGHT["bridge"],
        hint=b.hint,
        chain=b.chain,
    )


def cards_for_node(node_id: str) -> list[Card]:
    """The static set of cards a single node-id can contribute to a deck."""
    return [_card_for_node(node_id)]


# ─── §2 deterministic algorithm ──────────────────────────────────────────────
def _downstream_uids(uid: str, edges: list[dict]) -> list[str]:
    return [e["dst_uid"] for e in edges if e["src_uid"] == uid]


def flow_for_anchor(node_id: str) -> list[tuple[Flow, FlowStep]]:
    """Every (flow, step) whose anchor matches node_id. Order: registry order."""
    hits: list[tuple[Flow, FlowStep]] = []
    for f in FLOWS:
        for s in f.steps:
            if s.anchor == node_id:
                hits.append((f, s))
    return hits


def predict_deck(
    anchor_uid: Optional[str],
    nodes: list[dict],
    edges: list[dict],
    flow_id: Optional[str] = None,
    limit: int = 12,
) -> list[Card]:
    """Pure, deterministic. See DAG-FLOW.md §2.

    anchor_uid : currently-selected instance uid (or None → use last node).
    nodes      : list of graph instances [{uid, node_id, params, status}, ...]
    edges      : list of edges [{src_uid, dst_uid, src_port, dst_port}, ...]
    flow_id    : optional active flow — its current step gets priority bonus.
    """
    if not nodes:
        # cold start: surface the natural inputs (IMG/VID/AUD/TXT/PDF first)
        seeds = ["IN_IMG", "IN_VID", "IN_AUD", "IN_TXT", "IN_PDF",
                 "IN_POSE", "IN_CAM", "IN_BOX"]
        return [_card_for_node(nid, weight=0.5, hint="start here") for nid in seeds]

    if anchor_uid is None:
        anchor = nodes[-1]
    else:
        anchor = next((n for n in nodes if n["uid"] == anchor_uid), nodes[-1])

    anchor_spec = NODES_BY_ID[anchor["node_id"]]
    produced_types = [p["type"] for p in anchor_spec["outputs"]]
    if not produced_types:
        return []

    # ── 1. direct consumers (model/tool/lora that accept any produced type)
    cards: dict[str, Card] = {}
    for t in produced_types:
        for cand in nodes_accepting(t):
            if cand["kind"] == "input":     # never re-suggest inputs as consumers
                continue
            if cand["id"] in cards:
                continue
            cards[cand["id"]] = _card_for_node(cand["id"])

    # ── 2. natural sink for each produced type
    for t in produced_types:
        sink_id = SINK_FOR_TYPE.get(t)
        if sink_id and sink_id not in cards:
            cards[sink_id] = _card_for_node(sink_id, weight=KIND_WEIGHT["output"])

    # ── 3. bridges — only if anchor has any downstream node with no matching type
    has_downstream = bool(_downstream_uids(anchor["uid"], edges))
    if has_downstream:
        # find downstream consumers' accepted types
        downstream_types: set[str] = set()
        for e in edges:
            if e["src_uid"] == anchor["uid"]:
                ds = next((n for n in nodes if n["uid"] == e["dst_uid"]), None)
                if ds:
                    for p in NODES_BY_ID[ds["node_id"]]["inputs"]:
                        downstream_types.add(p["type"])
        gap_types = downstream_types - set(produced_types)
        for t in produced_types:
            for b in BRIDGES_FROM.get(t, []):
                if b.dst_type in gap_types and b.id not in cards:
                    cards[b.id] = _card_for_bridge(b)

    # ── 4. flow overlay — boost the active flow's lead/deck for this anchor
    bonuses: dict[str, float] = {}
    pinned: dict[str, dict] = {}
    matching: list[tuple[Flow, FlowStep]] = []
    if flow_id and flow_id in FLOWS_BY_ID:
        for s in FLOWS_BY_ID[flow_id].steps:
            if s.anchor == anchor["node_id"]:
                matching.append((FLOWS_BY_ID[flow_id], s))
    matching += [hit for hit in flow_for_anchor(anchor["node_id"])
                 if (hit[0].id, hit[1].anchor) not in {(f.id, s.anchor) for f, s in matching}]

    # Flow lead must beat every passive deck card (incl. natural sinks).
    # Max possible passive score is output-kind 0.95, so lead boost must push the
    # lead strictly above that. We use 0.60 for the active flow's lead, which
    # gives min weight 0.30 (lora) + 0.60 = 0.90 floor and typically 0.80 + 0.60
    # = 1.40 — above the 0.95 output sink and above any secondary's 0.95 + 0.20.
    LEAD_BONUS_ACTIVE = 0.60
    LEAD_BONUS_PASSIVE = 0.25     # flow not active but anchor is on its step
    DECK_BONUS_ACTIVE = 0.20
    DECK_BONUS_PASSIVE = 0.10
    for f, step in matching:
        is_active = (f.id == flow_id)
        if step.lead:
            bonuses[step.lead] = max(
                bonuses.get(step.lead, 0),
                LEAD_BONUS_ACTIVE if is_active else LEAD_BONUS_PASSIVE,
            )
            if step.params:
                pinned.setdefault(step.lead, {}).update(step.params)
        for sid in step.deck:
            bonuses[sid] = max(
                bonuses.get(sid, 0),
                DECK_BONUS_ACTIVE if is_active else DECK_BONUS_PASSIVE,
            )

    # materialise any flow-recommended card not yet present (e.g. lead is a model
    # that the anchor doesn't naturally pipe into — happens with bridge-implying flows)
    for cid in list(bonuses.keys()):
        if cid in NODES_BY_ID and cid not in cards:
            cards[cid] = _card_for_node(cid)

    # ── 5. apply pinned params
    for cid, params in pinned.items():
        if cid in cards:
            c = cards[cid]
            cards[cid] = Card(
                id=c.id, title=c.title, kind=c.kind,
                accepts=c.accepts, produces=c.produces,
                weight=c.weight, hint=c.hint, chain=c.chain,
                pinned_params={**c.pinned_params, **params},
            )

    # ── 6. rank: (bonus + kind_weight) desc, then vram asc, then name asc
    def vram_of(card: Card) -> float:
        if card.id in NODES_BY_ID:
            return float(NODES_BY_ID[card.id].get("vram_gb", 0))
        # bridges: peak vram of their sub-chain
        if card.id in BRIDGES_BY_ID:
            chain = BRIDGES_BY_ID[card.id].chain
            return max((NODES_BY_ID[c].get("vram_gb", 0) for c in chain), default=0)
        return 0.0

    ranked = sorted(
        cards.values(),
        key=lambda c: (
            -(c.weight + bonuses.get(c.id, 0.0)),
            vram_of(c),
            c.title.lower(),
        ),
    )
    return ranked[:limit]


# ─── flow loading helpers ────────────────────────────────────────────────────
def load_flow(flow_id: str) -> list[str]:
    """Return the deduplicated node-id chain for a flow (for one-click load)."""
    f = FLOWS_BY_ID.get(flow_id)
    if not f:
        raise KeyError(f"unknown flow {flow_id!r}")
    return f.chain


def current_step(flow_id: str, anchor_node_id: str) -> Optional[FlowStep]:
    """The step matching this anchor, or None."""
    f = FLOWS_BY_ID.get(flow_id)
    if not f:
        return None
    for s in f.steps:
        if s.anchor == anchor_node_id:
            return s
    return None


def next_step(flow_id: str, anchor_node_id: str) -> Optional[FlowStep]:
    """The step *after* the one whose anchor matches anchor_node_id."""
    f = FLOWS_BY_ID.get(flow_id)
    if not f:
        return None
    found = False
    for s in f.steps:
        if found:
            return s
        if s.anchor == anchor_node_id:
            found = True
    return None


# ─── self-check (DAG-FLOW.md §8 round-trip assertion) ────────────────────────
def _selfcheck() -> list[str]:
    """Validate every flow against the live node manifests. Returns errors."""
    errs: list[str] = []
    for f in FLOWS:
        for s in f.steps:
            if s.anchor not in NODES_BY_ID:
                errs.append(f"{f.id}: unknown anchor {s.anchor}")
                continue
            if s.lead and s.lead not in NODES_BY_ID:
                errs.append(f"{f.id}: unknown lead {s.lead}")
                continue
            for d in s.deck:
                if d not in NODES_BY_ID:
                    errs.append(f"{f.id}: unknown deck card {d}")
            if not s.lead:
                continue
            anchor_out = {p["type"] for p in NODES_BY_ID[s.anchor]["outputs"]}
            lead_in = {p["type"] for p in NODES_BY_ID[s.lead]["inputs"]}
            kind = NODES_BY_ID[s.lead]["kind"]
            if kind in ("input", "output"):
                continue
            compatible = any(types_compatible(a, b) for a in anchor_out for b in lead_in)
            if not compatible:
                errs.append(
                    f"{f.id}: step {s.anchor}→{s.lead} type-mismatch "
                    f"({anchor_out} ∩ {lead_in} = ∅)"
                )
    return errs


if __name__ == "__main__":
    errors = _selfcheck()
    if errors:
        for e in errors:
            print("ERR:", e)
        raise SystemExit(1)
    print(f"OK · {len(FLOWS)} flows, {len(BRIDGES)} bridges, all type-valid.")
