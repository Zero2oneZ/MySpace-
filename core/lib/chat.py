#!/usr/bin/env python3
# ============================================================================
# AGENT CARD                                                                  =
# ----------------------------------------------------------------------------=
# name:        chat_gateway                                                   =
# role:        GATEWAY · DETERMINISTIC_CHAT                                   =
# tier:        L0                                                             =
# substrate:   none (gateway; touches all three substrates via helpers)      =
# engine:      stateless orchestrator over the deterministic pipeline        =
# storage:     none directly (helpers write to crystal chain + user_graph)   =
# card:        studio/assets/_agents/agent_defs/                              =
#              vm_mspc_001.agents.agent_defs.chat_gateway.active.json         =
# ----------------------------------------------------------------------------=
# ROUTING CONNECTIONS                                                         =
# ----------------------------------------------------------------------------=
# inbound:                                                                    =
#   - core/cc.sh::cmd_chat        (bash dispatcher, all modes)                =
#   - CLI: python3 chat.py <enhance|route|chain|full|downward|godot>          =
# outbound (in pipeline order):                                               =
#   - inference_logger (read prev_forward via _read_prev_forward)             =
#   - user_graph       (predict via _user_graph_predict)                      =
#   - moe_router       (retrieve via _moe_find_experts)                       =
#   - prompt_enhancer  (PromptEnhancer.enhance)                               =
#   - chain_builder    (ChainAssembler + ChainSlicer + PromptRenderer)        =
#   - token_router     (ModelRouter.route + ComplexityScorer)                 =
#   - forward_projector(project — inline + posthoc fallback)                  =
#   - inference_logger (log via _log_inference → crystal_id)                  =
#   - user_graph       (record via _user_graph_record → turn_uuid)            =
# substrate touch:                                                            =
#   - reads:  all three (crystal chain tail, user_graph index, moe index)     =
#   - writes: all three (crystal chain, user_graph, semantic_index)           =
# env vars:                                                                   =
#   - CC_SCOPE_CWD, CC_FORWARD_POSTHOC, CC_AGENT_UUID, CC_CORRELATION_ID,     =
#     CC_SESSION_ID, CC_TIMESTAMP                                             =
# ============================================================================
"""chat.py — deterministic chat gateway for cc.

Usage (called from cc bash script):
    python3 chat.py enhance   <prompt>         # spell-fix + structure
    python3 chat.py route     <prompt>         # token count + model selection
    python3 chat.py chain     <prompt>         # assemble + render workspace chain
    python3 chat.py full      <prompt>         # enhance + assemble chain + route + slice
    python3 chat.py downward  <tier> <prompt>  # dispatch sub-prompt downward
    python3 chat.py godot     <prompt>         # emit Godot bridge packet JSON

Determinism: every subcommand with the same input produces the same JSON output.
"""
import json
import os
import sys
from pathlib import Path

# Ensure lib/ is on path for imports
_LIB = Path(__file__).parent.resolve()
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from token_router import ModelRouter, TokenCounter, ComplexityScorer
from prompt_enhancer import PromptEnhancer
from chain_builder import ChainAssembler, ChainSlicer, PromptRenderer, ChainEntry, ChainNode
from inference_logger import InferenceLogger, SemanticIndex
from forward_projector import (
    project as project_forward,
    extract_inline as extract_forward_inline,
    _is_placeholder as _forward_is_placeholder,
)
from user_graph import UserGraph, UserGraphIndex
from moe_router import CrystalChainCursor, MoERouter


def _moe_find_experts(prompt: str, k: int = 5):
    """Retrieve top-k matching past experts. Returns (matches_list_for_json, prior_block_text)."""
    try:
        cursor = CrystalChainCursor()
        if cursor.open() != 0:
            return [], ""
        router = MoERouter.build_from(cursor)
        matches = router.find_experts(prompt, k=k)
        prior = router.summarize_for_prompt(matches, max_chars=1500)
        return [
            {
                "crystal_id": m.crystal_id,
                "score": m.score,
                "fit_ratio": m.fit_ratio,
                "matched_ngrams": m.matched_ngrams,
                "tier": m.tier,
                "model": m.model,
                "scope": m.scope,
                "timestamp": m.timestamp,
                "forward_source": m.forward_source,
                "forward_chain": m.forward_chain[:600],
                "original_prompt": m.original_prompt[:200],
            }
            for m in matches
        ], prior
    except Exception:
        return [], ""


def _user_graph_predict(words: str, k: int = 5) -> list:
    """Return top-k user-graph predictions for incoming words. Empty list on any error."""
    try:
        g = UserGraph()
        if g.open() != 0:
            return []
        idx = UserGraphIndex.build_from(g)
        preds = idx.predict_next(words, k)
        return [
            {
                "turn_uuid": p.turn_uuid,
                "score": p.score,
                "matched_ngrams": p.matched_ngrams,
                "words": p.words,
                "forward_chain": p.forward_chain,
                "tier": p.tier,
                "timestamp": p.timestamp,
                "chain_crystal": p.chain_crystal,
            }
            for p in preds
        ]
    except Exception:
        return []


def _user_graph_record(
    words: str,
    enhanced: str,
    chain_crystal: str,
    tier: str,
    produced_chain: dict,
    forward_chain: str,
) -> str:
    """Append this turn to the user graph. Returns turn_uuid (or "" on failure)."""
    try:
        g = UserGraph()
        g.open()
        return g.record_turn(
            user=os.environ.get("USER", "anon"),
            words=words,
            prompt=enhanced,
            chain_crystal=chain_crystal,
            tier=tier,
            produced_chain=produced_chain,
            forward_chain=forward_chain,
        )
    except Exception:
        return ""


def _read_prev_forward() -> str:
    """Look up the most recent NON-placeholder forward chain from the crystal log."""
    try:
        logger = InferenceLogger()
        chain = logger.get_chain(limit=20)
    except Exception:
        return ""
    for rec in reversed(chain):
        inline = rec.get("forward_chain_inline") or ""
        posthoc = rec.get("forward_chain_posthoc") or ""
        if inline and not _forward_is_placeholder(inline):
            return inline
        if posthoc and not _forward_is_placeholder(posthoc):
            return posthoc
    return ""


def _posthoc_enabled() -> bool:
    """Posthoc projection is opt-in (default off) since it adds ~10s per turn.
    Enable with CC_FORWARD_POSTHOC=1. Inline extraction always runs (free)."""
    return os.environ.get("CC_FORWARD_POSTHOC", "").strip() not in ("", "0", "false", "no")


def cmd_enhance(prompt: str) -> None:
    enhancer = PromptEnhancer()
    result = enhancer.enhance(prompt, scope_hint=os.environ.get("CC_SCOPE_CWD", ""))
    print(json.dumps(result, indent=2))


def cmd_route(prompt: str, tier_override: str = "") -> None:
    router = ModelRouter()
    tier, model, scope = router.route(prompt, override_tier=tier_override or None)
    out = {
        "tier": tier,
        "model": model,
        "scope": scope,
        "tokens": TokenCounter.count(prompt),
        "complexity": round(ComplexityScorer.score(prompt), 4),
    }
    print(json.dumps(out, indent=2))


def cmd_chain(prompt: str) -> None:
    """Assemble the master workspace chain and render it.
    The prompt is used as a scope hint to filter relevant entries."""
    assembler = ChainAssembler()
    root = assembler.assemble(scope_hint=prompt)
    renderer = PromptRenderer()
    out = {
        "master_chain": _node_to_dict(root),
        "rendered": renderer.render(root, mode="full"),
        "coordinates": renderer.render(root, mode="coordinates_only"),
        "instructions": renderer.render(root, mode="instructions_only"),
        "total_tokens": root.total_tokens(),
        "total_steps": root.total_steps(),
    }
    print(json.dumps(out, indent=2))


def cmd_full(prompt: str) -> None:
    """The full deterministic pipeline with workspace-coordinate chains:
        1. Spell-fix + structural enhancement
        2. Assemble master chain from all known entries
        3. Render full chain prompt
        4. Token count + complexity
        5. Model routing by total chain size
        6. Slice chain for the routed tier
        7. If epic/large, generate downward dispatch slices with exact coordinates
    """
    enhancer = PromptEnhancer()
    router = ModelRouter()
    assembler = ChainAssembler()
    slicer = ChainSlicer()
    renderer = PromptRenderer()

    # 0a. Pull the previous turn's forward chain — the "incoming node consumer".
    prev_forward = _read_prev_forward()
    # 0b. Predict next turn from user's chain-of-thought graph (XMLParser-shaped).
    user_predictions = _user_graph_predict(prompt, k=5)
    # 0c. MoE retrieval: find past experts whose n-grams overlap this prompt.
    moe_experts, moe_prior_block = _moe_find_experts(prompt, k=5)

    # 1. Enhance
    enhanced = enhancer.enhance(prompt, scope_hint=os.environ.get("CC_SCOPE_CWD", ""))
    enhanced_text = enhanced["enhanced"]

    # 1b. Inject prior forward chain + MoE expert priors as context (if present).
    if moe_prior_block:
        enhanced_text = moe_prior_block + "\n\n" + enhanced_text
    if prev_forward:
        enhanced_text = (
            "PRIOR FORWARD CHAIN (from last turn — consume as context):\n"
            + prev_forward
            + "\n\n"
            + enhanced_text
        )

    # 2. Assemble master chain
    root = assembler.assemble(scope_hint=enhanced_text)
    master_render = renderer.render(root, mode="full")
    master_tokens = TokenCounter.count(master_render)

    # 3. Route based on master chain size
    tier, model, scope = router.route(master_render)
    complexity = ComplexityScorer.score(master_render)

    # 4. Slice for the routed tier
    slices = slicer.slice_by_tier(root, tier)

    # 5. Downward dispatch if tier is large or epic
    downward = []
    if tier in ("large", "epic"):
        for target_tier in ("medium", "tiny"):
            dslices = slicer.downward_slice(root, tier, target_tier)
            for slc in dslices:
                slc_render = renderer.render(slc, mode="full")
                stier, smodel, sscope = router.downward_dispatch(tier, slc_render)
                downward.append({
                    "target_tier": target_tier,
                    "slice_tier": stier,
                    "slice_model": smodel,
                    "slice_scope": sscope,
                    "slice_name": slc.name,
                    "slice_steps": slc.total_steps(),
                    "slice_tokens": TokenCounter.count(slc_render),
                    "slice_prompt": slc_render,
                    "entries": [_entry_to_dict(e) for e in slc.entries],
                })

    out = {
        "original": enhanced["original"],
        "enhanced": enhanced_text,
        "replacements": enhanced["replacements"],
        "added_markers": enhanced["added_markers"],
        "master_chain": {
            "total_tokens": master_tokens,
            "total_steps": root.total_steps(),
            "weight": root.weight,
            "rendered": master_render,
        },
        "route": {
            "tier": tier,
            "model": model,
            "scope": scope,
        },
        "tokens": master_tokens,
        "complexity": round(complexity, 4),
        "slices": [
            {
                "name": slc.name,
                "tier": tier,
                "steps": slc.total_steps(),
                "tokens": TokenCounter.count(renderer.render(slc, mode="full")),
                "entries": [_entry_to_dict(e) for e in slc.entries],
            }
            for slc in slices
        ],
        "downward_dispatch": downward,
    }

    # Project the forward chain (inline always; posthoc only when enabled).
    reasoning_trace = enhanced_text + "\n\n---\n\n" + master_render
    fwd = project_forward(
        reasoning_trace=reasoning_trace,
        output_text=json.dumps(out),
        prev_forward=prev_forward,
        enable_posthoc=_posthoc_enabled(),
    )
    out["forward_chain"] = {
        "inline": fwd.inline,
        "posthoc": fwd.posthoc,
        "source": fwd.source,
        "chosen": fwd.chosen(),
        "prev": prev_forward,
    }
    out["user_graph_prediction"] = user_predictions
    out["moe_experts"] = moe_experts
    out["moe_prior_block_chars"] = len(moe_prior_block)

    # Log to crystal chain first to get the crystal_id, then record to user_graph
    # with the crystal_id as a backlink.
    crystal_id = _log_inference(
        original=prompt,
        enhanced=enhanced_text,
        output=json.dumps(out),
        tier=tier,
        model=model,
        scope=scope,
        tokens_in=master_tokens,
        complexity=complexity,
        rc=0,
        coordinates=[_entry_to_dict(e) for child in root.children for e in child.entries],
        reasoning_trace=reasoning_trace,
        forward_chain_inline=fwd.inline,
        forward_chain_posthoc=fwd.posthoc,
        forward_source=fwd.source,
    )
    turn_uuid = _user_graph_record(
        words=prompt,
        enhanced=enhanced_text,
        chain_crystal=crystal_id,
        tier=tier,
        produced_chain=_node_to_dict(root),
        forward_chain=fwd.chosen(),
    )
    out["user_graph_turn_uuid"] = turn_uuid
    out["crystal_id"] = crystal_id
    print(json.dumps(out, indent=2))


def cmd_downward(tier: str, prompt: str) -> None:
    router = ModelRouter()
    assembler = ChainAssembler()
    slicer = ChainSlicer()
    renderer = PromptRenderer()

    root = assembler.assemble(scope_hint=prompt)
    slices = slicer.downward_slice(root, tier, tier)  # slice to a lower tier

    # Route each slice
    routed_slices = []
    for slc in slices:
        slc_render = renderer.render(slc, mode="full")
        stier, smodel, sscope = router.downward_dispatch(tier, slc_render)
        routed_slices.append({
            "tier": stier,
            "model": smodel,
            "scope": sscope,
            "name": slc.name,
            "steps": slc.total_steps(),
            "tokens": TokenCounter.count(slc_render),
            "prompt": slc_render,
            "entries": [_entry_to_dict(e) for e in slc.entries],
        })

    out = {
        "from_tier": tier,
        "slices": routed_slices,
    }
    print(json.dumps(out, indent=2))


def cmd_godot(prompt: str) -> None:
    """Emit a JSON packet that Godot's cc_bridge.gd can consume.
    Includes the master chain with exact file/folder/action/step coordinates."""
    enhancer = PromptEnhancer()
    router = ModelRouter()
    assembler = ChainAssembler()
    slicer = ChainSlicer()
    renderer = PromptRenderer()

    prev_forward = _read_prev_forward()
    user_predictions = _user_graph_predict(prompt, k=5)
    moe_experts, moe_prior_block = _moe_find_experts(prompt, k=5)

    enhanced = enhancer.enhance(prompt, scope_hint="godot_studio")
    enhanced_text = enhanced["enhanced"]
    if moe_prior_block:
        enhanced_text = moe_prior_block + "\n\n" + enhanced_text
    if prev_forward:
        enhanced_text = (
            "PRIOR FORWARD CHAIN (from last turn — consume as context):\n"
            + prev_forward
            + "\n\n"
            + enhanced_text
        )

    # Assemble chain scoped to Godot
    root = assembler.assemble(scope_hint=enhanced_text)
    master_render = renderer.render(root, mode="full")
    tier, model, scope = router.route(master_render)

    # Derive godot_action from keywords + chain entries
    keywords = {w.lower() for w in enhanced_text.split()}
    godot_action = "noop"
    if any(k in keywords for k in ("spatial", "depth", "pose", "ik", "skeleton", "bone")):
        godot_action = "spatial_pipeline"
    elif any(k in keywords for k in ("chain", "runner", "vm", "navigate")):
        godot_action = "run_chain"
    elif any(k in keywords for k in ("task", "queue", "flush")):
        godot_action = "task_queue"
    elif any(k in keywords for k in ("sym", "index", "symbol")):
        godot_action = "index_symbols"
    elif any(k in keywords for k in ("build", "compile", "gdext", "scons")):
        godot_action = "build_gdext"

    # Build coordinate list for Godot
    coordinates = []
    for child in root.children:
        for e in child.entries:
            coordinates.append(_entry_to_dict(e))

    # Slice for tiny tier (what Godot's local worker would receive)
    tiny_slices = slicer.slice_by_tier(root, "tiny")
    tiny_coords = []
    for slc in tiny_slices:
        for e in slc.entries:
            tiny_coords.append(_entry_to_dict(e))

    packet = {
        "protocol": "cc_godot_bridge_v1",
        "timestamp": os.environ.get("CC_TIMESTAMP", ""),
        "agent_uuid": os.environ.get("CC_AGENT_UUID", ""),
        "original": enhanced["original"],
        "enhanced": enhanced_text,
        "route": {"tier": tier, "model": model, "scope": scope},
        "tokens": TokenCounter.count(master_render),
        "complexity": round(ComplexityScorer.score(master_render), 4),
        "godot_action": godot_action,
        "master_chain": _node_to_dict(root),
        "coordinates": coordinates,
        "tiny_slices": tiny_coords,
    }

    # Forward projection — Godot bridge consumes this to predict next action.
    reasoning_trace = enhanced_text + "\n\n---\n\n" + master_render
    fwd = project_forward(
        reasoning_trace=reasoning_trace,
        output_text=json.dumps(packet),
        prev_forward=prev_forward,
        enable_posthoc=_posthoc_enabled(),
    )
    packet["forward_chain"] = {
        "inline": fwd.inline,
        "posthoc": fwd.posthoc,
        "source": fwd.source,
        "chosen": fwd.chosen(),
        "prev": prev_forward,
    }
    packet["user_graph_prediction"] = user_predictions
    packet["moe_experts"] = moe_experts
    packet["moe_prior_block_chars"] = len(moe_prior_block)

    crystal_id = _log_inference(
        original=prompt,
        enhanced=enhanced_text,
        output=json.dumps(packet),
        tier=tier,
        model=model,
        scope=scope,
        tokens_in=TokenCounter.count(master_render),
        complexity=ComplexityScorer.score(master_render),
        rc=0,
        coordinates=coordinates,
        reasoning_trace=reasoning_trace,
        forward_chain_inline=fwd.inline,
        forward_chain_posthoc=fwd.posthoc,
        forward_source=fwd.source,
    )
    turn_uuid = _user_graph_record(
        words=prompt,
        enhanced=enhanced_text,
        chain_crystal=crystal_id,
        tier=tier,
        produced_chain=_node_to_dict(root),
        forward_chain=fwd.chosen(),
    )
    packet["user_graph_turn_uuid"] = turn_uuid
    packet["crystal_id"] = crystal_id
    print(json.dumps(packet, indent=2))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log_inference(
    original: str,
    enhanced: str,
    output: str,
    tier: str,
    model: str,
    scope: str,
    tokens_in: int = 0,
    complexity: float = 0.0,
    rc: int = 0,
    coordinates: list[dict] | None = None,
    reasoning_trace: str = "",
    forward_chain_inline: str = "",
    forward_chain_posthoc: str = "",
    forward_source: str = "none",
) -> str:
    """Log one inference call to the crystal chain. Returns crystal_id."""
    logger = InferenceLogger()
    crystal = logger.log(
        original_prompt=original,
        enhanced_prompt=enhanced,
        output_text=output,
        tier=tier,
        model=model,
        scope=scope,
        tokens_in=tokens_in,
        complexity=complexity,
        rc=rc,
        coordinates=coordinates,
        reasoning_trace=reasoning_trace,
        forward_chain_inline=forward_chain_inline,
        forward_chain_posthoc=forward_chain_posthoc,
        forward_source=forward_source,
    )
    # Also index for semantic search
    idx = SemanticIndex()
    rec = logger.get_record(crystal)
    if rec:
        idx.index_record(rec)
        idx.save()
    return crystal


def _entry_to_dict(e: ChainEntry) -> dict:
    return {
        "step": e.step,
        "file": e.file,
        "folder": e.folder,
        "action": e.action,
        "instruction": e.instruction,
        "scope": e.scope,
        "weight": e.weight,
        "tokens": e.tokens,
        "depends_on": e.depends_on,
        "crystal": e.crystal,
    }


def _node_to_dict(n: ChainNode) -> dict:
    return {
        "name": n.name,
        "scope": n.scope,
        "weight": n.weight,
        "steps": n.total_steps(),
        "tokens": n.total_tokens(),
        "entries": [_entry_to_dict(e) for e in n.entries],
        "children": [_node_to_dict(c) for c in n.children],
    }


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: chat.py <enhance|route|chain|full|downward|godot> [args...]"}), file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd == "enhance":
        prompt = " ".join(args) if args else sys.stdin.read()
        cmd_enhance(prompt)
    elif cmd == "route":
        prompt = " ".join(args) if args else sys.stdin.read()
        tier_override = os.environ.get("CC_CHAT_TIER", "")
        cmd_route(prompt, tier_override)
    elif cmd == "chain":
        prompt = " ".join(args) if args else sys.stdin.read()
        cmd_chain(prompt)
    elif cmd == "full":
        prompt = " ".join(args) if args else sys.stdin.read()
        cmd_full(prompt)
    elif cmd == "downward":
        if len(args) < 2:
            print(json.dumps({"error": "usage: chat.py downward <tier> <prompt>"}), file=sys.stderr)
            sys.exit(1)
        cmd_downward(args[0], " ".join(args[1:]))
    elif cmd == "godot":
        prompt = " ".join(args) if args else sys.stdin.read()
        cmd_godot(prompt)
    else:
        print(json.dumps({"error": f"unknown command: {cmd}"}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
