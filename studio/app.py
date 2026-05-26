"""Models DAG Studio — Streamlit pipeline builder.

Implements the spec in /home/tom/models/DAG-GUI.md adapted to Streamlit:
  - Palette (Inputs / Models / Tools / Loras / Class / Outputs / Recipes)
  - Card-based chain canvas with type-checked edges
  - Inspector with auto-generated param forms per node
  - Save / Load .dag.json
  - Recipe loader (C01–C17 and S01–S21)
  - Topbar Run with mock executor + per-node status

Launch:
  cd /home/tom/models/dag_studio
  streamlit run app.py
"""
from __future__ import annotations
import json
import time
import uuid
from pathlib import Path

import streamlit as st

from nodes import (
    NODES_BY_ID, nodes_by_kind, nodes_accepting, nodes_producing,
)
from recipes import RECIPES, SINGLE_HOPS
from runtime import (
    cache_key, topo_sort, validate_edges, run_step, estimate_vram,
)
from types_meta import PORT_COLORS, chip, types_compatible
from flows import (
    FLOWS, FLOWS_BY_ID, BRIDGES_BY_ID,
    predict_deck, flow_for_anchor, current_step, next_step, load_flow,
)


SAVE_DIR = Path(__file__).parent / "saved"
SAVE_DIR.mkdir(exist_ok=True)


# ─── App config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Models DAG Studio",
    page_icon="🧩",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      .block-container {padding-top: 1.2rem; padding-bottom: 4rem; max-width: 1600px;}
      .node-card {
        border: 1px solid #2a2f3a; border-radius: 10px; padding: 10px 12px;
        margin: 6px 0; background: linear-gradient(180deg,#0f1217 0%,#161a22 100%);
      }
      .node-title {font-weight: 700; font-size: 14px;}
      .node-meta  {font-size: 11px; color: #8b93a7;}
      .pill {
        display:inline-block; padding:1px 8px; border-radius:8px;
        font-size:10px; font-weight:600; margin-right:6px;
      }
      .pill-input  {background:#1e3a8a; color:#dbeafe;}
      .pill-model  {background:#7c2d12; color:#fed7aa;}
      .pill-tool   {background:#14532d; color:#bbf7d0;}
      .pill-lora   {background:#581c87; color:#e9d5ff;}
      .pill-class  {background:#3f3f46; color:#e4e4e7;}
      .pill-output {background:#0c4a6e; color:#bae6fd;}
      .status-idle    {color:#6b7280;}
      .status-queued  {color:#3b82f6;}
      .status-running {color:#eab308;}
      .status-done    {color:#10b981;}
      .status-error   {color:#ef4444;}
    </style>
    """,
    unsafe_allow_html=True,
)


# ─── Session state ───────────────────────────────────────────────────────────
def init_state():
    ss = st.session_state
    ss.setdefault("nodes", [])      # [{uid, node_id, params, status}]
    ss.setdefault("edges", [])      # [{src_uid, dst_uid, src_port, dst_port}]
    ss.setdefault("selected_uid", None)
    ss.setdefault("logs", [])
    ss.setdefault("last_run_outputs", {})
    ss.setdefault("active_flow", None)   # F-* id when user is following a flow
    ss.setdefault("show_deck", True)


init_state()


def add_node(node_id: str, position: int | None = None) -> str:
    spec = NODES_BY_ID[node_id]
    uid = f"{node_id}-{uuid.uuid4().hex[:6]}"
    params = {p["name"]: p.get("default") for p in spec["params"] if "default" in p}
    inst = {"uid": uid, "node_id": node_id, "params": params, "status": "idle"}
    if position is None:
        st.session_state.nodes.append(inst)
    else:
        st.session_state.nodes.insert(position, inst)
    return uid


def remove_node(uid: str):
    st.session_state.nodes = [n for n in st.session_state.nodes if n["uid"] != uid]
    st.session_state.edges = [
        e for e in st.session_state.edges
        if e["src_uid"] != uid and e["dst_uid"] != uid
    ]
    if st.session_state.selected_uid == uid:
        st.session_state.selected_uid = None


def move_node(uid: str, delta: int):
    ns = st.session_state.nodes
    i = next((k for k, n in enumerate(ns) if n["uid"] == uid), None)
    if i is None:
        return
    j = max(0, min(len(ns) - 1, i + delta))
    if i == j:
        return
    ns[i], ns[j] = ns[j], ns[i]


def auto_wire():
    """Heuristic: for each node, try to connect its first input to the closest
    upstream producer of a compatible type (honours TYPE_COERCIONS). Used
    after recipe-drop / move."""
    nodes = st.session_state.nodes
    edges = []
    for idx, n in enumerate(nodes):
        spec = NODES_BY_ID[n["node_id"]]
        for inp in spec["inputs"]:
            for j in range(idx - 1, -1, -1):
                up = NODES_BY_ID[nodes[j]["node_id"]]
                src_port = next(
                    (o for o in up["outputs"] if types_compatible(o["type"], inp["type"])),
                    None,
                )
                if src_port:
                    edges.append({
                        "src_uid": nodes[j]["uid"],
                        "dst_uid": n["uid"],
                        "src_port": src_port["name"],
                        "dst_port": inp["name"],
                    })
                    break
    st.session_state.edges = edges


def load_recipe(chain_ids: list[str]):
    st.session_state.nodes = []
    st.session_state.edges = []
    for nid in chain_ids:
        add_node(nid)
    auto_wire()


def instantiate_card(card_id: str, pinned_params: dict | None = None) -> list[str]:
    """Add a card (node or bridge sub-chain) to the canvas, then auto-wire.
    Returns the list of newly-added uids."""
    added: list[str] = []
    if card_id in BRIDGES_BY_ID:
        b = BRIDGES_BY_ID[card_id]
        for nid in b.chain:
            added.append(add_node(nid))
    elif card_id in NODES_BY_ID:
        uid = add_node(card_id)
        added.append(uid)
        if pinned_params:
            inst = next(n for n in st.session_state.nodes if n["uid"] == uid)
            inst["params"].update(pinned_params)
    else:
        raise ValueError(f"unknown card id {card_id!r}")
    auto_wire()
    return added


def start_flow(flow_id: str):
    """Load a flow's chain onto the canvas and mark it active."""
    chain = load_flow(flow_id)
    load_recipe(chain)
    st.session_state.active_flow = flow_id
    if st.session_state.nodes:
        st.session_state.selected_uid = st.session_state.nodes[0]["uid"]


def clear_canvas():
    st.session_state.nodes = []
    st.session_state.edges = []
    st.session_state.selected_uid = None
    st.session_state.logs = []
    st.session_state.last_run_outputs = {}


def serialize_graph() -> dict:
    return {
        "version": 1,
        "nodes": st.session_state.nodes,
        "edges": st.session_state.edges,
    }


def deserialize_graph(data: dict):
    st.session_state.nodes = data.get("nodes", [])
    st.session_state.edges = data.get("edges", [])
    for n in st.session_state.nodes:
        n.setdefault("status", "idle")


# ─── Param-form renderer ─────────────────────────────────────────────────────
def render_params(inst: dict):
    spec = NODES_BY_ID[inst["node_id"]]
    if not spec["params"]:
        st.caption("No params.")
        return
    for p in spec["params"]:
        key = f"param-{inst['uid']}-{p['name']}"
        ptype = p["type"]
        cur = inst["params"].get(p["name"], p.get("default"))
        if ptype == "int":
            inst["params"][p["name"]] = st.slider(
                p["name"], int(p["min"]), int(p["max"]), int(cur or 0), key=key,
            )
        elif ptype == "float":
            inst["params"][p["name"]] = st.slider(
                p["name"], float(p["min"]), float(p["max"]),
                float(cur if cur is not None else p.get("default", 0.0)),
                step=float(p.get("step", 0.1)), key=key,
            )
        elif ptype == "text":
            inst["params"][p["name"]] = st.text_area(
                p["name"], value=str(cur or ""), key=key, height=80,
            )
        elif ptype == "bool":
            inst["params"][p["name"]] = st.toggle(
                p["name"], value=bool(cur), key=key,
            )
        elif ptype == "enum":
            opts = p["options"]
            idx = opts.index(cur) if cur in opts else 0
            inst["params"][p["name"]] = st.selectbox(p["name"], opts, index=idx, key=key)
        elif ptype == "file":
            up = st.file_uploader(p["name"], key=key)
            if up is not None:
                inst["params"][p["name"]] = {"name": up.name, "size": up.size}


# ─── Sidebar: palette + recipes + file ───────────────────────────────────────
with st.sidebar:
    st.markdown("### 🧩 Palette")
    st.caption("Click to append to chain. Auto-wires by type.")

    kinds = [
        ("Inputs",  "input",  "pill-input"),
        ("Models",  "model",  "pill-model"),
        ("Tools",   "tool",   "pill-tool"),
        ("Loras",   "lora",   "pill-lora"),
        ("Class",   "class",  "pill-class"),
        ("Outputs", "output", "pill-output"),
    ]
    for label, kind, _pill in kinds:
        with st.expander(f"{label} ({len(nodes_by_kind(kind))})", expanded=(kind == "input")):
            for n in nodes_by_kind(kind):
                cols = st.columns([4, 1])
                with cols[0]:
                    out_types = " ".join(p["type"] for p in n["outputs"])
                    in_types = " ".join(p["type"] for p in n["inputs"])
                    st.markdown(
                        f"**{n['name']}**  \n"
                        f"<span class='node-meta'>in: {in_types or '—'} → out: {out_types or '—'} · "
                        f"{n.get('vram_gb', 0)}GB</span>",
                        unsafe_allow_html=True,
                    )
                with cols[1]:
                    if st.button("＋", key=f"add-{n['id']}", help=f"Add {n['name']}"):
                        add_node(n["id"])
                        auto_wire()
                        st.rerun()

    st.divider()
    st.markdown("### 🎯 Flows")
    st.caption("One-click deterministic workflows (DAG-FLOW.md §4).")
    active = st.session_state.active_flow
    if active:
        af = FLOWS_BY_ID[active]
        st.success(f"Active: **{af.id}** · {af.name}")
        if st.button("End flow", key="end-flow", use_container_width=True):
            st.session_state.active_flow = None
            st.rerun()
    for f in FLOWS:
        cols = st.columns([5, 1])
        with cols[0]:
            st.markdown(f"**{f.id}** — {f.name}")
            st.caption(f.goal + " · " + " → ".join(s.anchor for s in f.steps))
        with cols[1]:
            if st.button("▶", key=f"flow-{f.id}", help=f"Start {f.id}"):
                start_flow(f.id)
                st.rerun()

    st.divider()
    st.markdown("### 📋 Recipes")
    rec_tab, hop_tab = st.tabs(["Multi-hop (C01–C17)", "Single-hop (S01–S21)"])
    with rec_tab:
        for rid, r in RECIPES.items():
            cols = st.columns([5, 1])
            with cols[0]:
                st.markdown(f"**{rid}** — {r['name']}")
                st.caption(r["note"])
            with cols[1]:
                if st.button("⏎", key=f"rec-{rid}", help=f"Load {rid}"):
                    load_recipe(r["chain"])
                    st.rerun()
    with hop_tab:
        for sid, chain in SINGLE_HOPS.items():
            cols = st.columns([5, 1])
            with cols[0]:
                names = " → ".join(NODES_BY_ID[c]["name"] for c in chain)
                st.markdown(f"**{sid}**  \n<span class='node-meta'>{names}</span>",
                            unsafe_allow_html=True)
            with cols[1]:
                if st.button("⏎", key=f"hop-{sid}"):
                    load_recipe(chain)
                    st.rerun()

    st.divider()
    st.markdown("### 💾 File")
    save_name = st.text_input("Save as", value="pipeline.dag.json", key="save-name")
    sc1, sc2 = st.columns(2)
    with sc1:
        if st.button("Save", use_container_width=True):
            (SAVE_DIR / save_name).write_text(json.dumps(serialize_graph(), indent=2))
            st.toast(f"Saved → {save_name}", icon="💾")
    with sc2:
        if st.button("Clear", use_container_width=True):
            clear_canvas()
            st.rerun()

    saved_files = sorted(p.name for p in SAVE_DIR.glob("*.dag.json"))
    if saved_files:
        pick = st.selectbox("Load saved", saved_files, key="load-pick")
        if st.button("Load", use_container_width=True):
            deserialize_graph(json.loads((SAVE_DIR / pick).read_text()))
            st.rerun()

    uploaded = st.file_uploader("Import .dag.json", type=["json"], key="upload-dag")
    if uploaded is not None:
        try:
            deserialize_graph(json.loads(uploaded.read()))
            st.toast("Imported.", icon="📥")
            st.rerun()
        except Exception as exc:
            st.error(f"Bad file: {exc}")


# ─── Topbar ──────────────────────────────────────────────────────────────────
st.markdown("## 🧩 Models DAG Studio")
st.caption(
    "Build pipelines from `/home/tom/models` — see "
    "`DAG.md` (graph) and `DAG-GUI.md` (UX spec)."
)

bar = st.columns([1, 1, 1, 1, 2, 2, 4])
with bar[0]:
    run = st.button("▶ Run", type="primary", use_container_width=True)
with bar[1]:
    dry = st.button("⊕ Dry-run", use_container_width=True, help="Compute cache keys + VRAM forecast only")
with bar[2]:
    stop = st.button("■ Reset", use_container_width=True)
with bar[3]:
    rewire = st.button("⟳ Auto-wire", use_container_width=True)
with bar[4]:
    st.metric("Nodes", len(st.session_state.nodes))
with bar[5]:
    st.metric("VRAM peak", f"{estimate_vram(st.session_state.nodes):.0f} GB")
with bar[6]:
    errors = validate_edges(st.session_state.nodes, st.session_state.edges)
    if errors:
        st.error(f"⚠ {len(errors)} edge issue(s) — see Inspector")
    else:
        st.success("✓ Graph is type-valid")

if stop:
    for n in st.session_state.nodes:
        n["status"] = "idle"
    st.session_state.last_run_outputs = {}
    st.rerun()

if rewire:
    auto_wire()
    st.rerun()


# ─── Main: canvas + inspector ────────────────────────────────────────────────
canvas_col, inspector_col = st.columns([3, 2], gap="large")


with canvas_col:
    st.markdown("#### Canvas — pipeline chain")
    if not st.session_state.nodes:
        st.info("Empty canvas. Drop a recipe from the sidebar or click ＋ on a palette item to start.")
    else:
        for idx, inst in enumerate(st.session_state.nodes):
            spec = NODES_BY_ID[inst["node_id"]]
            kind = spec["kind"]
            sel = (st.session_state.selected_uid == inst["uid"])
            border = "2px solid #38bdf8" if sel else "1px solid #2a2f3a"

            with st.container():
                st.markdown(
                    f"<div class='node-card' style='border:{border}'>"
                    f"<span class='pill pill-{kind}'>{kind.upper()}</span>"
                    f"<span class='node-title'>{spec['name']}</span>"
                    f"&nbsp;<span class='node-meta'>· uid={inst['uid']}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                in_chips = "".join(chip(p["type"]) for p in spec["inputs"]) or "—"
                out_chips = "".join(chip(p["type"]) for p in spec["outputs"]) or "—"
                st.markdown(
                    f"<div class='node-meta' style='margin:-4px 0 8px 0'>"
                    f"in: {in_chips} → out: {out_chips} · "
                    f"VRAM {spec.get('vram_gb', 0)}GB · "
                    f"<span class='status-{inst['status']}'>● {inst['status']}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                ctl = st.columns([1, 1, 1, 1, 1, 5])
                with ctl[0]:
                    if st.button("▲", key=f"up-{inst['uid']}", help="Move up"):
                        move_node(inst["uid"], -1); auto_wire(); st.rerun()
                with ctl[1]:
                    if st.button("▼", key=f"dn-{inst['uid']}", help="Move down"):
                        move_node(inst["uid"], +1); auto_wire(); st.rerun()
                with ctl[2]:
                    if st.button("✎", key=f"sel-{inst['uid']}", help="Inspect"):
                        st.session_state.selected_uid = inst["uid"]; st.rerun()
                with ctl[3]:
                    if st.button("⎘", key=f"dup-{inst['uid']}", help="Duplicate"):
                        new_uid = add_node(inst["node_id"], position=idx + 1)
                        st.session_state.nodes[idx + 1]["params"] = dict(inst["params"])
                        auto_wire(); st.rerun()
                with ctl[4]:
                    if st.button("✕", key=f"rm-{inst['uid']}", help="Remove"):
                        remove_node(inst["uid"]); st.rerun()

            # flow-step badge if anchored mid-flow
            if st.session_state.active_flow:
                step = current_step(st.session_state.active_flow, inst["node_id"])
                if step:
                    nxt = next_step(st.session_state.active_flow, inst["node_id"])
                    badge = f"step on flow **{st.session_state.active_flow}**"
                    if nxt:
                        badge += f" · next → `{NODES_BY_ID[nxt.anchor]['name']}`"
                    st.markdown(
                        f"<div class='node-meta' style='color:#38bdf8;margin:-4px 0 8px 4px'>"
                        f"⌖ {badge}</div>",
                        unsafe_allow_html=True,
                    )


with inspector_col:
    st.markdown("#### Inspector")
    sel_uid = st.session_state.selected_uid
    if sel_uid is None and st.session_state.nodes:
        sel_uid = st.session_state.nodes[-1]["uid"]
    if sel_uid is None:
        st.info("No node selected.")
    else:
        inst = next((n for n in st.session_state.nodes if n["uid"] == sel_uid), None)
        if inst is None:
            st.warning("Selected node was removed.")
        else:
            spec = NODES_BY_ID[inst["node_id"]]
            st.markdown(f"**{spec['name']}**  \n"
                        f"<span class='node-meta'>kind: {spec['kind']} · "
                        f"vram: {spec.get('vram_gb', 0)}GB · "
                        f"dir: {spec.get('dir', '—')}</span>",
                        unsafe_allow_html=True)
            tabs = st.tabs(["Params", "Wiring", "Cache", "Output"])

            with tabs[0]:
                render_params(inst)

            with tabs[1]:
                st.markdown("**Inputs**")
                for inp in spec["inputs"]:
                    upstream = [
                        e for e in st.session_state.edges
                        if e["dst_uid"] == inst["uid"] and e["dst_port"] == inp["name"]
                    ]
                    if upstream:
                        u = upstream[0]
                        src = next(n for n in st.session_state.nodes if n["uid"] == u["src_uid"])
                        st.markdown(
                            f"- {chip(inp['type'])} `{inp['name']}` ← "
                            f"**{NODES_BY_ID[src['node_id']]['name']}**.{u['src_port']}",
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown(
                            f"- {chip(inp['type'])} `{inp['name']}` "
                            f"<span style='color:#ef4444'>· unconnected</span>",
                            unsafe_allow_html=True,
                        )
                st.markdown("**Outputs**")
                for out in spec["outputs"]:
                    dn = [
                        e for e in st.session_state.edges
                        if e["src_uid"] == inst["uid"] and e["src_port"] == out["name"]
                    ]
                    if dn:
                        for u in dn:
                            dst = next(n for n in st.session_state.nodes if n["uid"] == u["dst_uid"])
                            st.markdown(
                                f"- {chip(out['type'])} `{out['name']}` → "
                                f"**{NODES_BY_ID[dst['node_id']]['name']}**.{u['dst_port']}",
                                unsafe_allow_html=True,
                            )
                    else:
                        st.markdown(
                            f"- {chip(out['type'])} `{out['name']}` · terminal",
                            unsafe_allow_html=True,
                        )

            with tabs[2]:
                in_hashes = []
                for e in st.session_state.edges:
                    if e["dst_uid"] == inst["uid"]:
                        in_hashes.append(e["src_uid"])
                key = cache_key(inst["node_id"], inst["params"], in_hashes)
                st.code(key, language="text")
                st.caption("blake2b(impl, entry, params, input-uids). Same inputs → same key → no recompute.")

            with tabs[3]:
                out_data = st.session_state.last_run_outputs.get(inst["uid"])
                if out_data is None:
                    st.info("Run the pipeline to populate this node's output.")
                else:
                    st.json(out_data)


# ─── Deck — deterministic predicted next-cards (DAG-FLOW.md §2) ──────────────
st.markdown("---")
deck_col_a, deck_col_b = st.columns([4, 1])
with deck_col_a:
    st.markdown("#### 🃏 Deck — predicted cards for the current operation")
with deck_col_b:
    st.session_state.show_deck = st.toggle(
        "show deck", value=st.session_state.show_deck, key="deck-toggle"
    )

if st.session_state.show_deck:
    anchor_uid = st.session_state.selected_uid
    if anchor_uid is None and st.session_state.nodes:
        anchor_uid = st.session_state.nodes[-1]["uid"]
    deck = predict_deck(
        anchor_uid,
        st.session_state.nodes,
        st.session_state.edges,
        flow_id=st.session_state.active_flow,
        limit=12,
    )
    if not deck:
        st.caption("No predictions — anchor produces no outputs (terminal sink).")
    else:
        anchor_inst = next((n for n in st.session_state.nodes if n["uid"] == anchor_uid), None)
        anchor_label = (
            NODES_BY_ID[anchor_inst["node_id"]]["name"] if anchor_inst else "—"
        )
        st.caption(
            f"Anchored on **{anchor_label}** · "
            f"flow={st.session_state.active_flow or 'none'} · "
            f"deterministic (DAG-FLOW.md §2)"
        )
        # Lead card (first) gets full width; rest go into a 3-column grid
        lead = deck[0]
        rest = deck[1:]

        def _render_card(card, cols, idx):
            cell = cols[idx % len(cols)]
            with cell:
                pinned_tag = ""
                if card.pinned_params:
                    pinned_tag = (
                        f" <span style='color:#38bdf8'>· "
                        f"{', '.join(f'{k}={v}' for k,v in card.pinned_params.items())}"
                        f"</span>"
                    )
                kind_pill = (
                    f"<span class='pill pill-{card.kind if card.kind != 'bridge' else 'class'}'>"
                    f"{card.kind.upper()}</span>"
                )
                st.markdown(
                    f"<div class='node-card'>"
                    f"{kind_pill}"
                    f"<span class='node-title'>{card.title}</span>"
                    f"{pinned_tag}"
                    f"<div class='node-meta' style='margin-top:4px'>"
                    f"accepts: {' '.join(card.accepts) or '—'} → "
                    f"produces: {' '.join(card.produces) or '—'}<br/>"
                    f"<i>{card.hint}</i>"
                    f"</div></div>",
                    unsafe_allow_html=True,
                )
                btn_label = f"＋ add {card.title}"
                if st.button(btn_label, key=f"deck-{card.id}-{idx}", use_container_width=True):
                    instantiate_card(card.id, card.pinned_params)
                    st.rerun()

        st.markdown("**Lead card**")
        _render_card(lead, st.columns(1), 0)
        if rest:
            st.markdown("**Secondary lane**")
            grid = st.columns(3)
            for i, c in enumerate(rest):
                _render_card(c, grid, i)


# ─── Execution ───────────────────────────────────────────────────────────────
def execute(graph_nodes: list[dict], graph_edges: list[dict], dry_only: bool = False):
    errs = validate_edges(graph_nodes, graph_edges)
    if errs:
        for e in errs:
            st.error(e)
        return
    try:
        order = topo_sort(graph_nodes, graph_edges)
    except ValueError as exc:
        st.error(str(exc)); return
    placeholder = st.empty()
    progress = st.progress(0.0)
    outputs: dict[str, dict] = {}
    log = st.session_state.logs
    for k, uid in enumerate(order):
        inst = next(n for n in graph_nodes if n["uid"] == uid)
        spec = NODES_BY_ID[inst["node_id"]]
        inst["status"] = "running"
        placeholder.markdown(
            f"<span class='status-running'>● running</span> "
            f"<b>{spec['name']}</b> ({k+1}/{len(order)})",
            unsafe_allow_html=True,
        )
        t0 = time.time()
        in_inputs = {}
        for e in graph_edges:
            if e["dst_uid"] == uid:
                in_inputs[e["dst_port"]] = outputs.get(e["src_uid"], {})
        if dry_only:
            inst["status"] = "queued"
            outputs[uid] = {"dry_run": True, "key": cache_key(inst["node_id"], inst["params"], list(in_inputs))}
        else:
            try:
                outputs[uid] = run_step(inst["node_id"], inst["params"], in_inputs)
                inst["status"] = "done"
            except Exception as exc:
                inst["status"] = "error"
                log.append({"node": spec["name"], "error": str(exc)})
                st.error(f"{spec['name']}: {exc}")
                break
        dt = time.time() - t0
        log.append({"node": spec["name"], "ms": int(dt * 1000), "status": inst["status"]})
        progress.progress((k + 1) / max(len(order), 1))
    placeholder.empty()
    st.session_state.last_run_outputs = outputs
    if not dry_only:
        st.toast(f"Pipeline complete · {len(order)} nodes", icon="✅")
    else:
        st.toast("Dry-run done — cache keys computed", icon="🧮")


if run:
    execute(st.session_state.nodes, st.session_state.edges, dry_only=False)
    st.rerun()
elif dry:
    execute(st.session_state.nodes, st.session_state.edges, dry_only=True)
    st.rerun()


# ─── Bottom: job-queue / log drawer ──────────────────────────────────────────
with st.expander("📜 Job log", expanded=False):
    if not st.session_state.logs:
        st.caption("No runs yet.")
    else:
        st.dataframe(st.session_state.logs[-50:], use_container_width=True, hide_index=True)


with st.expander("🧪 Edge-validity errors", expanded=bool(errors)):
    if errors:
        for e in errors:
            st.error(e)
    else:
        st.success("All wired edges are type-compatible.")


with st.expander("ℹ Help", expanded=False):
    st.markdown(
        """
        - **Build a chain**: click ＋ on palette items, load a recipe (C01–C25 / S01–S24),
          or start a Flow (F-*) for guided next-card prediction.
        - **Flows** (DAG-FLOW.md §4): one-click multi-step workflows that activate the
          **Deck** — a deterministic predictor (§2) of the next GUI cards to drop.
          ★ lead card is shown full-width; secondary lane shows ranked alternatives.
        - **Deck** appears below the canvas; it's anchored to the currently-inspected
          node, honours TYPE_COERCIONS (MD↔TXT), and surfaces bridge cards when a
          downstream consumer expects a different type.
        - **Reorder**: ▲▼ on each card. Auto-wire re-runs after every move.
        - **Inspect**: ✎ on a card opens the Inspector — params, wiring, cache key, output.
        - **Run**: ▶ executes top-to-bottom. The runtime stub returns deterministic mocks
          until each node's venv runner is wired in `runtime.run_step`.
        - **Save / Load**: graphs persist as `.dag.json` under `dag_studio/saved/`.
        - **Round-trip with `DAG.md` / `DAG-GUI.md` / `DAG-FLOW.md`**: node ids match
          across all three; edit those files and the app picks up the changes.
        """
    )
