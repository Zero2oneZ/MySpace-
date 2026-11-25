"""complex_dag.py — emit COMPLEX-DAG.svg: the joint operational map of
MySpace++ (Python/bash) + GentlyOS (Rust/.bb).

This is the THIRD master SVG. Where:
  - Tesseract.svg     maps STATIC knowledge (DAG-of-DAGs over the 8 sub-graphs)
  - TWINS-MASTER.svg  maps DYNAMIC runtime (sessions, DBs, WEAVE topology)
  - COMPLEX-DAG.svg   maps the JOINT operational picture across BOTH halves,
                      including the gently Rust chain + its interfaces with us.

Each node carries a `data-owned-by` attribute: 'mspc' | 'gently' | 'shared'.
Each edge carries a `data-interface` attribute when it crosses the boundary.

The SVG is the source of truth for HOW the two halves talk. Update via:
    python3 studio/tesseract/complex_dag.py
"""
from __future__ import annotations

import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDIO_ROOT = HERE.parent
sys.path.insert(0, str(STUDIO_ROOT))
import paths  # noqa: E402

SVG_NS = "http://www.w3.org/2000/svg"
CDX_NS = "https://myspace.local/complex-dag"
ET.register_namespace("", SVG_NS)
ET.register_namespace("cdx", CDX_NS)

W = 3000
H = 2200

OWN_COL = {
    "mspc":   "#7dd3fc",   # cyan — MySpace++ side
    "gently": "#fde047",   # yellow — GentlyOS side
    "shared": "#bef264",   # lime — bridge nodes
}

STATUS_COL = {
    "impl":         "#22c55e",
    "partial":      "#facc15",
    "stub":         "#fb923c",
    "placeholder":  "#94a3b8",
    "remote":       "#a78bfa",   # gently-side nodes I can't directly inspect
}


# ── helpers ──────────────────────────────────────────────────────────────────
def _g(parent, id_, label):
    return ET.SubElement(parent, f"{{{SVG_NS}}}g",
                         attrib={"id": id_, "data-layer": id_,
                                 "data-layer-label": label})


def _rect(parent, x, y, w, h, *, fill="#fff", stroke="#0f172a",
          rx=6, sw=1.5, **kw):
    return ET.SubElement(parent, f"{{{SVG_NS}}}rect", attrib={
        "x": str(x), "y": str(y), "width": str(w), "height": str(h),
        "rx": str(rx), "fill": fill, "stroke": stroke,
        "stroke-width": str(sw),
        **{k.replace("_", "-"): str(v) for k, v in kw.items()},
    })


def _t(parent, x, y, txt, *, size=12, color="#0f172a", weight="normal",
       family="system-ui, sans-serif", anchor="start"):
    e = ET.SubElement(parent, f"{{{SVG_NS}}}text", attrib={
        "x": str(x), "y": str(y),
        "font-family": family, "font-size": str(size),
        "fill": color, "font-weight": weight, "text-anchor": anchor,
    })
    e.text = txt
    return e


def _line(parent, x1, y1, x2, y2, *, stroke="#94a3b8", w=1.5, dash=None,
          **kw):
    attrib = {"x1": str(x1), "y1": str(y1), "x2": str(x2), "y2": str(y2),
              "stroke": stroke, "stroke-width": str(w),
              **{k.replace("_", "-"): str(v) for k, v in kw.items()}}
    if dash: attrib["stroke-dasharray"] = dash
    return ET.SubElement(parent, f"{{{SVG_NS}}}line", attrib=attrib)


def _arrow(parent, x1, y1, x2, y2, *, stroke="#0f172a", w=2,
           label="", labeled_y=None, interface=False):
    """Draw an arrow (line with arrow-head) and optional label."""
    dash = "6 3" if interface else None
    _line(parent, x1, y1, x2, y2, stroke=stroke, w=w, dash=dash,
          data_interface=str(interface).lower())
    # small arrowhead at (x2,y2)
    import math
    dx, dy = x2 - x1, y2 - y1
    L = math.hypot(dx, dy) or 1
    ux, uy = dx / L, dy / L
    px, py = -uy, ux  # perpendicular
    ah = 7
    aw = 4
    pts = (
        f"{x2},{y2} "
        f"{x2 - ah*ux + aw*px},{y2 - ah*uy + aw*py} "
        f"{x2 - ah*ux - aw*px},{y2 - ah*uy - aw*py}"
    )
    ET.SubElement(parent, f"{{{SVG_NS}}}polygon",
                  attrib={"points": pts, "fill": stroke,
                          "stroke": stroke})
    if label:
        lx = (x1 + x2) / 2
        ly = labeled_y or ((y1 + y2) / 2 - 4)
        _t(parent, lx, ly, label, size=10, color=stroke,
           family="ui-monospace, Menlo, monospace", anchor="middle")


def _node(parent, x, y, w, h, *, label, sub="", owned_by, status="impl",
          node_id=None):
    fill = OWN_COL.get(owned_by, "#cbd5e1")
    _rect(parent, x, y, w, h, fill=fill, stroke="#0f172a", rx=8,
          data_owned_by=owned_by,
          data_status=status,
          data_node_id=(node_id or label.lower().replace(" ", "-")))
    _t(parent, x + 10, y + 22, label, size=13, weight="bold")
    if sub:
        _t(parent, x + 10, y + 40, sub, size=10, color="#1e293b",
           family="ui-monospace, Menlo, monospace")
    # status pip in corner
    pip_col = STATUS_COL.get(status, "#94a3b8")
    ET.SubElement(parent, f"{{{SVG_NS}}}circle", attrib={
        "cx": str(x + w - 12), "cy": str(y + 12), "r": "5",
        "fill": pip_col, "stroke": "#0f172a", "stroke-width": "1",
    })


INSTRUCTIONS = """\
== COMPLEX-DAG — joint operational map of MySpace++ + GentlyOS ==

Two halves communicate through one file: studio/docs/NOTES-FOR-INFERANCE.md
This SVG visualizes WHAT each half owns + WHERE they interface.

OWNERSHIP COLOR
   cyan   = MySpace++ (this half — Python/bash/Streamlit)
   yellow = GentlyOS  (other half — Rust/.bb/crystal DAG)
   lime   = shared    (bridge files + taxonomy + .env)

STATUS PIP (corner of each node)
   green   = implemented
   yellow  = partial
   orange  = stub
   gray    = placeholder
   purple  = remote (gently-owned; I can't inspect directly)

CROSS-BOUNDARY EDGES are dashed.
Every node has data-owned-by + data-status + data-node-id attributes.

REGENERATE: python3 studio/tesseract/complex_dag.py
"""


# ── Build ────────────────────────────────────────────────────────────────────
def build(out_path: Path | None = None) -> Path:
    if out_path is None:
        out_path = paths.DOCS_ROOT / "COMPLEX-DAG.svg"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    svg = ET.Element(f"{{{SVG_NS}}}svg", attrib={
        "width": str(W), "height": str(H),
        "viewBox": f"0 0 {W} {H}", "version": "1.1",
        "data-doc-name": "COMPLEX-DAG",
        "data-built-at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })

    # ── Manifest in <metadata> ─────────────────────────────────────────────
    meta = ET.SubElement(svg, f"{{{SVG_NS}}}metadata",
                         attrib={"id": "complex-dag-manifest"})
    contract = ET.SubElement(meta, f"{{{CDX_NS}}}contract")
    contract.text = INSTRUCTIONS

    # Reciprocal cross-ref to sister's CHAIN-OPS-DAG.svg (per Q-GENTLY-003).
    # Sister already added <dag:cross-ref> pointing here; this is the mirror.
    _emit_cross_ref(meta)

    # background
    _rect(svg, 0, 0, W, H, fill="#f8fafc", stroke="#cbd5e1", rx=0)

    # ── Instructions header ────────────────────────────────────────────────
    inst = _g(svg, "layer:instructions", "Instructions")
    _rect(inst, 20, 20, 880, 280, fill="#fefce8", stroke="#facc15", rx=10)
    _t(inst, 36, 50, "COMPLEX-DAG", size=22, weight="bold")
    _t(inst, 36, 72, "joint operational map of MySpace++ + GentlyOS",
       size=12, color="#475569")
    y = 96
    for line in INSTRUCTIONS.splitlines():
        if y > 290: break
        if line.startswith("=="):
            _t(inst, 36, y, line, size=11, weight="bold", color="#7c2d12")
        elif line.startswith("   "):
            _t(inst, 56, y, line.lstrip(), size=10, color="#0f172a",
               family="ui-monospace, Menlo, monospace")
        elif line.strip():
            _t(inst, 36, y, line, size=11, weight="bold", color="#0f172a")
        y += 13

    # ── Legend ─────────────────────────────────────────────────────────────
    leg = _g(svg, "layer:legend", "Legend")
    lx, ly = 920, 20
    _rect(leg, lx, ly, 480, 280, fill="#fff", stroke="#cbd5e1", rx=10)
    _t(leg, lx + 14, ly + 22, "LEGEND", size=14, weight="bold")
    # ownership colors
    items_o = [("MySpace++ (this half)", "mspc"),
               ("GentlyOS (other half)", "gently"),
               ("Shared (bridge / taxonomy)", "shared")]
    for i, (lbl, k) in enumerate(items_o):
        cy = ly + 50 + i * 28
        _rect(leg, lx + 14, cy, 24, 18, fill=OWN_COL[k], stroke="#0f172a")
        _t(leg, lx + 46, cy + 13, lbl, size=11)
    # status pips
    items_s = [("impl",        "implemented"),
               ("partial",     "partial"),
               ("stub",        "stub"),
               ("placeholder", "placeholder"),
               ("remote",      "remote (gently — can't inspect)")]
    for i, (k, lbl) in enumerate(items_s):
        cy = ly + 50 + i * 28
        ET.SubElement(leg, f"{{{SVG_NS}}}circle", attrib={
            "cx": str(lx + 250), "cy": str(cy + 8), "r": "6",
            "fill": STATUS_COL[k], "stroke": "#0f172a",
        })
        _t(leg, lx + 264, cy + 13, lbl, size=11)

    # ── Title for the main grid ────────────────────────────────────────────
    titleg = _g(svg, "layer:title", "Title")
    _t(titleg, 1420, 50, "MASTER OPERATIONAL DAG", size=20, weight="bold")
    _t(titleg, 1420, 74, "Every operation, every interface, owned-by + status",
       size=12, color="#475569")

    # ── Three big columns: MSPC | BRIDGE | GENTLY ──────────────────────────
    LANE_TOP = 330
    LANE_BOT = 2100

    L_MSPC = (40, 1000)        # x range for MSPC column
    L_BRIDGE = (1020, 1980)    # x range for bridge column
    L_GENTLY = (2000, 2960)    # x range for gently column

    def lane_label(x0, x1, label, color, y=LANE_TOP - 26):
        _rect(svg, x0, y - 16, x1 - x0, 26, fill=color, rx=6,
              stroke="#0f172a", sw=1)
        _t(svg, (x0 + x1) // 2, y + 4, label, size=14, weight="bold",
           color="#0f172a", anchor="middle")

    lane_label(*L_MSPC, "MySpace++  ·  Python · bash · Streamlit · WEAVE", OWN_COL["mspc"])
    lane_label(*L_BRIDGE, "BRIDGE  ·  shared taxonomy + .env + proxy + opcodes", OWN_COL["shared"])
    lane_label(*L_GENTLY, "GentlyOS  ·  Rust · .bb · crystal DAG · telos-ml-tools", OWN_COL["gently"])

    # ── MSPC nodes (left lane) ─────────────────────────────────────────────
    mspc = _g(svg, "layer:mspc-nodes", "MSPC nodes")
    mspc_nodes = [
        # (label, sub, status, node_id, y)
        ("cc bash dispatcher",        "core/cc · ~130 cmd_X",            "impl", "mspc:cc", 340),
        ("Global cc.db",              "core/lib/db.py · 28 tables",      "impl", "mspc:cc_db", 410),
        ("Local .cc/local.db",        "per-project chain runs",          "impl", "mspc:local_db", 480),
        ("cc -chain runtime",         "core/lib/chain.py · | + - cc{}",  "impl", "mspc:chain", 550),
        ("studio/passes/",            "20 passes · filetype DAG · timing","impl","mspc:passes", 620),
        ("studio/passes/pieces_index","searchable cache · content-hash", "impl", "mspc:pieces", 690),
        ("studio/tesseract/",         "8 sub-DAGs · 253 nodes · 729 edges","impl","mspc:tesseract", 760),
        ("studio/weave/",             "topology + PLANS + routing",      "impl", "mspc:weave", 830),
        ("studio/weave/webgpu_worker","browser-tab compute (WebGPU)",    "impl", "mspc:webgpu", 900),
        ("studio/lucid/",             "Standard Import bridge",          "partial","mspc:lucid", 970),
        ("studio/proxy/claude_proxy", "Anthropic guest pass relay :8520","impl",  "mspc:proxy", 1040),
        ("studio/auth/keys.sqlite",   "salted mspc_* tokens",            "impl", "mspc:keys", 1110),
        ("studio/media/.tools/",      "intake + sidecar + separate",     "impl", "mspc:intake", 1180),
        ("studio/pinterest/",         "search + scrape + auto-organize", "impl", "mspc:pinterest", 1250),
        ("Streamlit apps",            "wardrobe · DAG · YT · Pinterest", "impl", "mspc:apps", 1320),
        ("Tesseract.svg",             "static knowledge — 253 nodes",    "impl", "mspc:tess_svg", 1390),
        ("TWINS-MASTER.svg",          "dynamic runtime · 12 layers",     "impl", "mspc:twins_svg", 1460),
        ("planning/path_builder.py",  "interactive walker REPL",         "impl", "mspc:pathbuilder", 1530),
        ("TABPFN_ROUTER (designed)",  "3 predictors · TabPFN + k-NN",    "placeholder","mspc:tabpfn", 1600),
        ("3D scene editor MVP",       "TODO — projects/<slug>/scene.json","placeholder","mspc:scene3d", 1670),
        ("Makeup designer MVP",       "TODO — projects/<slug>/makeup/",  "placeholder","mspc:makeup", 1740),
        ("Furniture designer MVP",    "TODO — media/Furniture/",         "stub", "mspc:furniture", 1810),
        ("Business / CRM",            "TODO — studio/business/",         "placeholder","mspc:business", 1880),
        ("App + website builder",     "TODO — studio/app_builder/",      "placeholder","mspc:appbuilder", 1950),
        ("Comms hub (inbox + msg)",   "TODO — studio/comms/",            "placeholder","mspc:comms", 2020),
    ]
    for label, sub, status, nid, ny in mspc_nodes:
        _node(mspc, L_MSPC[0] + 20, ny, L_MSPC[1] - L_MSPC[0] - 40, 56,
              label=label, sub=sub, owned_by="mspc", status=status, node_id=nid)

    # ── BRIDGE nodes (middle lane) ─────────────────────────────────────────
    br = _g(svg, "layer:bridge-nodes", "Bridge nodes")
    bridge_nodes = [
        ("planning/hf_task_evolution.jsonl", "53 opcodes · canonical · shared", "impl", "bridge:opcode_taxonomy", 350),
        (".env (mirrored)",                  "claude_guest · client_api · pintrest_api · SUI_WALLET", "impl", "bridge:env", 430),
        ("studio/docs/NOTES-FOR-INFERANCE.md", "THE comm channel · this file", "impl", "bridge:notes", 510),
        ("studio/docs/RUST-CHAIN.md",        "MySpace++'s view of gently",     "impl", "bridge:rust_chain_doc", 590),
        ("studio/docs/COMPLEX-DAG.svg",      "this SVG — joint operational map","impl","bridge:complex_dag", 670),
        ("Claude proxy (auth.keys.sqlite)",  "shared salted-token registry",   "impl", "bridge:proxy", 750),
        ("Opcode → OpKind translation",      "TBD — Q-MSPC-001 in notes",      "placeholder","bridge:opcode_to_opkind", 830),
        ("pieces_index ↔ crystal hash",      "content-hash convention TBD",    "placeholder","bridge:hash_bridge", 910),
        ("WEAVE topology (joint)",           "Rust workers + browser tabs",    "stub", "bridge:weave_joint", 990),
        ("tabpfn_examples export format",    "TBD — Q-MSPC-002 in notes",      "placeholder","bridge:training_data", 1070),
        ("MCP tool registry",                "telos-ml-tools reachable from cc",   "placeholder","bridge:mcp", 1150),
        ("Lucid embed (read-only)",          "friends · OAuth · mspc:read",    "partial","bridge:lucid_embed", 1230),
        ("Chromium-authority cookies",       "LAW_8 — gently controls",         "remote","bridge:chrome_auth", 1310),
        ("key-vault (root droplet)",         "LAW_10 — gently owns",            "remote","bridge:key_vault", 1390),
        ("crystal DAG anchor (per session)", "gently writes, mspc reads",       "placeholder","bridge:crystal_anchor", 1470),
        ("OPEN: shared sessions table",      "merge gently chats + cc.db chats","placeholder","bridge:sessions_merge", 1550),
        ("OPEN: shared agents table",        "agent_uuid namespacing across halves","placeholder","bridge:agents_merge", 1630),
    ]
    for label, sub, status, nid, ny in bridge_nodes:
        _node(br, L_BRIDGE[0] + 20, ny, L_BRIDGE[1] - L_BRIDGE[0] - 40, 56,
              label=label, sub=sub, owned_by="shared", status=status, node_id=nid)

    # ── GENTLY nodes (right lane) ──────────────────────────────────────────
    gn = _g(svg, "layer:gently-nodes", "Gently nodes")
    gently_nodes = [
        (".bb stack machine",         "7 frozen symbols · 2 value types","remote","gently:bb_runtime", 340),
        ("bb-loop (agent lifecycle)", "every turn → program.bb fragment","remote","gently:bb_loop", 410),
        ("bb-emit (UI as .bb)",       "Rust struct attrs → gui.bb",     "remote","gently:bb_emit", 480),
        ("gently-crystal",            "Crystal DAG · IPFS pin · Sui NFT","remote","gently:crystal", 550),
        ("Genesis anchor (chain[0])", "self-recognizing runtime hash",   "remote","gently:genesis", 620),
        ("Mirror-pass anti-particle", "forward ⊕ inverse · tamper-evident","remote","gently:mirror", 690),
        ("gently-metabolism",         "OpKind enum → .bb step sequence", "remote","gently:metabolism", 760),
        ("OpKind variants",           "AgentPrompt · CodieCompress · VerifyHash","remote","gently:opkind", 830),
        ("codie-engine",              "44-keyword compression · 94.7%",  "remote","gently:codie", 900),
        ("codie-v4-predict",          "TabPFN-flavored opcode router",   "remote","gently:codie_v4", 970),
        ("telos-ml-tools (MCP)",      "the inference dispatcher",        "remote","gently:telos_ml", 1040),
        ("gently-bb-struct",          "structural inversion · S-expr",   "remote","gently:bb_struct", 1110),
        ("gently-grim",               "hash-addressed dispatch · sha256","remote","gently:grim", 1180),
        ("gently-alexandria",         "5W tesseract · 384 dims · 8 faces","remote","gently:alex", 1250),
        ("gently-artisan",            "BARF retrieval · toroidal foam",  "remote","gently:artisan", 1320),
        ("telos-runtime",             "forward+mirror executor host",    "remote","gently:telos_runtime", 1390),
        ("telos-blind-vault",         "XOR split-secret · LAW_10",       "remote","gently:vault", 1460),
        ("chromium-authority",        "ALL tokens · LAW_8 · :9223",      "remote","gently:chrome_auth", 1530),
        ("Crystal DAG (Sui NFT)",     "per-session NFT mint",            "remote","gently:sui", 1600),
        ("MCP tool registry (db)",    "mcp_tools · tool_permissions",    "remote","gently:mcp_db", 1670),
        ("Open-window commit",        "SVG-active live · single commit on unplug","remote","gently:open_window", 1740),
        ("ml/inference workers",      "Rust process pool · :3090s",      "remote","gently:inference_pool", 1810),
        ("PRIME DIRECTIVE",           "USE WHAT IS BUILT · own infra",   "remote","gently:prime_dir", 1880),
        ("LAW_9 — CC hierarchy",      "every LLM is a CC instance",      "remote","gently:law9", 1950),
        ("LAW_11 — Thought Sovereignty","sha256-only to Anthropic",      "remote","gently:law11", 2020),
    ]
    for label, sub, status, nid, ny in gently_nodes:
        _node(gn, L_GENTLY[0] + 20, ny, L_GENTLY[1] - L_GENTLY[0] - 40, 56,
              label=label, sub=sub, owned_by="gently", status=status, node_id=nid)

    # ── Cross-boundary interface edges ────────────────────────────────────
    edges = _g(svg, "layer:interfaces", "Interfaces")
    # Centre points: MSPC right edge x=1000, BRIDGE left x=1020, BRIDGE right x=1980, GENTLY left x=2000
    M_RIGHT = L_MSPC[1] - 20
    BR_LEFT = L_BRIDGE[0] + 20
    BR_RIGHT = L_BRIDGE[1] - 20
    GN_LEFT = L_GENTLY[0] + 20

    # Helper: yN of MSPC node N (0-indexed), node height 56, so mid = ny + 28
    def mspc_y(i): return mspc_nodes[i][4] + 28
    def br_y(i):   return bridge_nodes[i][4] + 28
    def gn_y(i):   return gently_nodes[i][4] + 28

    # MSPC → BRIDGE edges
    cross_edges_mb = [
        (3,  0, "chain → opcode lookup"),     # cc-chain runtime → opcode taxonomy
        (4,  0, "filetype → opcode"),         # passes → opcode taxonomy
        (5,  7, "piece content_hash"),        # pieces_index → hash bridge
        (7,  8, "WEAVE writes shared topo"),  # weave/ → WEAVE joint
        (10, 5, "Claude usage logged"),       # claude_proxy → proxy/keys
        (11, 5, "tokens issued/verified"),    # keys.sqlite → proxy/keys
        (15, 4, "rendered + reflected"),      # Tesseract.svg → COMPLEX-DAG.svg
        (16, 4, "rendered + reflected"),      # TWINS-MASTER → COMPLEX-DAG
        (18, 9, "training data export"),      # TABPFN → training data
    ]
    for i, j, lbl in cross_edges_mb:
        _arrow(edges, M_RIGHT, mspc_y(i), BR_LEFT, br_y(j),
               stroke="#475569", w=1.5, label=lbl, interface=True)

    # BRIDGE → GENTLY edges
    cross_edges_bg = [
        (0,  6, "opcode → OpKind"),           # opcode taxonomy → metabolism
        (1, 16, "shared keys"),               # .env → chromium-authority
        (6,  6, "TBD opcode→OpKind shim"),    # opcode to OpKind bridge
        (7,  3, "hash convention TBD"),       # hash bridge → crystal
        (8, 15, "Rust workers register"),     # WEAVE joint → telos-runtime
        (9,  9, "shared examples"),           # tabpfn examples → codie-v4
        (10, 10, "MCP wire-up TBD"),          # MCP tool registry → telos-ml-tools
        (12, 17, "cookie relay"),             # chromium-authority bridge → chromium-authority
        (13, 16, "key client requests"),      # key vault → blind vault
        (14,  3, "anchor → crystal"),         # crystal anchor → gently-crystal
    ]
    for i, j, lbl in cross_edges_bg:
        _arrow(edges, BR_RIGHT, br_y(i), GN_LEFT, gn_y(j),
               stroke="#475569", w=1.5, label=lbl, interface=True)

    # ── MSPC internal edges (a few illustrative ones) ──────────────────────
    internal = _g(svg, "layer:mspc-internal", "MSPC internal")
    INT_LEFT_OFFSET = 4
    def mspc_left(i): return L_MSPC[0] + 20 + INT_LEFT_OFFSET
    def mspc_right(i): return L_MSPC[0] + 20 + (L_MSPC[1] - L_MSPC[0] - 40) - INT_LEFT_OFFSET
    # cc → cc.db
    _arrow(internal, mspc_left(0), mspc_y(0), mspc_left(1), mspc_y(1),
           stroke="#0369a1", w=1.2)
    # cc → chain runtime
    _arrow(internal, mspc_left(0), mspc_y(0), mspc_left(3), mspc_y(3),
           stroke="#0369a1", w=1.2)
    # passes → pieces_index
    _arrow(internal, mspc_left(4), mspc_y(4), mspc_left(5), mspc_y(5),
           stroke="#0369a1", w=1.2)
    # tesseract → tesseract.svg
    _arrow(internal, mspc_left(6), mspc_y(6), mspc_left(15), mspc_y(15),
           stroke="#0369a1", w=1.2)
    # tesseract → twins-master.svg
    _arrow(internal, mspc_left(6), mspc_y(6), mspc_left(16), mspc_y(16),
           stroke="#0369a1", w=1.2)
    # weave → tesseract (WEAVE layers in TWINS-MASTER)
    _arrow(internal, mspc_left(7), mspc_y(7), mspc_left(16), mspc_y(16),
           stroke="#0369a1", w=1.2)
    # claude_proxy → keys
    _arrow(internal, mspc_left(10), mspc_y(10), mspc_left(11), mspc_y(11),
           stroke="#0369a1", w=1.2)

    # ── GENTLY internal edges ──────────────────────────────────────────────
    gint = _g(svg, "layer:gently-internal", "Gently internal")
    def gn_left(i): return L_GENTLY[0] + 20 + INT_LEFT_OFFSET
    # bb_loop → metabolism (OpKind)
    _arrow(gint, gn_left(1), gn_y(1), gn_left(6), gn_y(6),
           stroke="#a16207", w=1.2)
    # metabolism → opkind
    _arrow(gint, gn_left(6), gn_y(6), gn_left(7), gn_y(7),
           stroke="#a16207", w=1.2)
    # bb_runtime → crystal
    _arrow(gint, gn_left(0), gn_y(0), gn_left(3), gn_y(3),
           stroke="#a16207", w=1.2)
    # crystal → genesis
    _arrow(gint, gn_left(3), gn_y(3), gn_left(4), gn_y(4),
           stroke="#a16207", w=1.2)
    # genesis → mirror
    _arrow(gint, gn_left(4), gn_y(4), gn_left(5), gn_y(5),
           stroke="#a16207", w=1.2)
    # opkind → telos-ml-tools (MCP)
    _arrow(gint, gn_left(7), gn_y(7), gn_left(10), gn_y(10),
           stroke="#a16207", w=1.2)
    # codie-engine → codie-v4
    _arrow(gint, gn_left(8), gn_y(8), gn_left(9), gn_y(9),
           stroke="#a16207", w=1.2)
    # crystal → sui
    _arrow(gint, gn_left(3), gn_y(3), gn_left(18), gn_y(18),
           stroke="#a16207", w=1.2)

    # ── Footer ─────────────────────────────────────────────────────────────
    footer = _g(svg, "layer:footer", "Footer")
    _t(footer, 20, H - 40,
       f"COMPLEX-DAG · {len(mspc_nodes)} MSPC + "
       f"{len(bridge_nodes)} BRIDGE + {len(gently_nodes)} GENTLY = "
       f"{len(mspc_nodes) + len(bridge_nodes) + len(gently_nodes)} nodes · "
       f"{len(cross_edges_mb) + len(cross_edges_bg)} cross-boundary interfaces · "
       f"built {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}",
       size=11, color="#475569")
    _t(footer, 20, H - 22,
       "Communicate updates only through studio/docs/NOTES-FOR-INFERANCE.md. "
       "Both halves regenerate this SVG when their side's nodes change.",
       size=10, color="#475569")

    ET.ElementTree(svg).write(out_path, encoding="utf-8", xml_declaration=True)
    return out_path


if __name__ == "__main__":
    out = build()
    print(f"wrote {out}  ({out.stat().st_size:,} bytes)")
