"""twins.py — emit TWINS-MASTER.svg: the multi-device + multi-session
runtime view of MySpace++.

Where Tesseract.svg maps STATIC knowledge (the DAG-of-DAGs over opcodes
+ models + recipes + passes + …), TWINS-MASTER.svg maps DYNAMIC runtime
state: devices, agent sessions, database twins (global + local),
dispatch tree, ToDo lifecycle, workflow job lifecycle.

The name TWINS refers to the two-DB pattern at the heart of cc:
  - GLOBAL   ~/.cc/cc.db          one per user, shared across projects + devices
  - LOCAL    <proj>/.cc/local.db  one per project, isolated per checkout

Together they let 5-10 concurrent terminal sessions, plus friends on
other devices, work without trampling each other.

The SVG is BOTH a document (read it) and an audit checklist (every
component has a data-* attribute the operator can verify).
"""
from __future__ import annotations

import json
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDIO_ROOT = HERE.parent
sys.path.insert(0, str(STUDIO_ROOT))
import paths   # noqa: E402

SVG_NS = "http://www.w3.org/2000/svg"
TES_NS = "https://myspace.local/tesseract"
ET.register_namespace("", SVG_NS)
ET.register_namespace("twins", TES_NS)

W = 2800
H = 3200  # extended for WEAVE layers (topology, plans, queue)


# ── Visual palette ───────────────────────────────────────────────────────────
COL_BG       = "#f8fafc"
COL_BAND_BG  = "#ffffff"
COL_STROKE   = "#0f172a"
COL_MUTED    = "#475569"
COL_DEVICE   = "#bae6fd"
COL_AGENT    = "#fde68a"
COL_DB_GLOBAL = "#86efac"
COL_DB_LOCAL = "#a5b4fc"
COL_CMD      = "#fbcfe8"
COL_TODO     = "#fed7aa"
COL_JOB      = "#c4b5fd"
COL_FLOW     = "#94a3b8"

STATUS_COLOR = {
    "impl":        "#22c55e",
    "partial":     "#facc15",
    "stub":        "#fb923c",
    "placeholder": "#94a3b8",
}


# ── Helpers ──────────────────────────────────────────────────────────────────
def _g(parent, *, id_, layer_label):
    return ET.SubElement(parent, f"{{{SVG_NS}}}g",
                         attrib={"id": id_, "data-layer": id_,
                                 "data-layer-label": layer_label})


def _rect(parent, x, y, w, h, *, fill="#fff", stroke=COL_STROKE,
          rx=6, sw=1.5, **kw):
    return ET.SubElement(parent, f"{{{SVG_NS}}}rect", attrib={
        "x": str(x), "y": str(y), "width": str(w), "height": str(h),
        "rx": str(rx), "fill": fill, "stroke": stroke,
        "stroke-width": str(sw),
        **{k.replace("_", "-"): str(v) for k, v in kw.items()},
    })


def _t(parent, x, y, txt, *, size=12, color=COL_STROKE, weight="normal",
       family="system-ui, sans-serif", anchor="start"):
    e = ET.SubElement(parent, f"{{{SVG_NS}}}text", attrib={
        "x": str(x), "y": str(y),
        "font-family": family, "font-size": str(size),
        "fill": color, "font-weight": weight, "text-anchor": anchor,
    })
    e.text = txt
    return e


def _line(parent, x1, y1, x2, y2, *, stroke="#94a3b8", w=1, dash=None):
    attrib = {"x1": str(x1), "y1": str(y1), "x2": str(x2), "y2": str(y2),
              "stroke": stroke, "stroke-width": str(w)}
    if dash: attrib["stroke-dasharray"] = dash
    return ET.SubElement(parent, f"{{{SVG_NS}}}line", attrib=attrib)


def _path(parent, d, *, stroke=COL_STROKE, fill="none", w=1.5, dash=None):
    attrib = {"d": d, "stroke": stroke, "fill": fill, "stroke-width": str(w)}
    if dash: attrib["stroke-dasharray"] = dash
    return ET.SubElement(parent, f"{{{SVG_NS}}}path", attrib=attrib)


def _section_title(parent, x, y, label, n=None):
    """Section heading + optional count chip."""
    _t(parent, x, y, label, size=18, weight="bold")
    if n is not None:
        _rect(parent, x + 270, y - 16, 70, 22, fill="#0f172a", rx=11)
        _t(parent, x + 305, y + 1, str(n), size=12, color="#fff",
           weight="bold", anchor="middle")


# ── Data feeds — everything we know from the parallel agent walk ────────────

# The cc.db global tables (28 of them)
GLOBAL_TABLES = [
    ("projects",          "user-wide project registry"),
    ("todos",             "per-project todo list"),
    ("bash_scripts",      "registered shell scripts"),
    ("directory_log",     "cwd + action history"),
    ("queue",             "command queue (queued/running/done)"),
    ("current_task",      "singleton: which task is active"),
    ("meta",              "key-value metadata"),
    ("entrypoints",       "CLI entry scripts"),
    ("runs",              "command exec history + agent_uuid"),
    ("agents",            "active agent tracking (uuid+pid+cwd)"),
    ("tools",             "tool registry (name/schema/exec)"),
    ("workflows",         "workflow definitions"),
    ("workflow_runs",     "active workflow exec state"),
    ("agent_defs",        "agent prompt templates"),
    ("swarm_defs",        "swarm loop definitions"),
    ("swarm_runs",        "active swarm exec state"),
    ("swarm_run_steps",   "per-iteration step output"),
    ("phases",            "conversation phase grouping"),
    ("phase_steps",       "phase step outputs + agent_uuid"),
    ("chats",             "chat session metadata"),
    ("chain_runs",        "chain spec execution + agent_uuid"),
    ("chain_run_steps",   "chain step outputs"),
    ("capability_cards",  "opcode capability cards"),
    ("gui_cards",         "opcode GUI widget specs"),
    ("workflow_templates","Claude-authored templates"),
    ("workflow_jobs",     "template instantiation + state"),
    ("workflow_job_steps","job step exec + HITL gates"),
    ("dag_nodes",         "DAG cache: nodes"),
    ("dag_edges",         "DAG cache: edges"),
    ("dag_chains",        "DAG cache: chains + score"),
    ("dag_build_queue",   "async builder tasks"),
]

# Local DB (.cc/local.db) — currently used for chain_runs scope
LOCAL_TABLES = [
    ("chain_runs",        "(when local.db scope) chain exec"),
    ("chain_run_steps",   "per-step output (local copy)"),
    ("(future)",          "project-scoped session state"),
]

# Studio-side global SQLite caches
STUDIO_DBS = [
    ("auth/keys.sqlite",                 [("tokens", "salted-key registry"),
                                          ("usage_log", "per-call usage + cost")]),
    ("cache/dag/pieces.sqlite",          [("pieces", "computed-piece index")]),
    ("cache/dag/passes_timing.sqlite",   [("timings", "per-machine pass duration")]),
    ("cache/dag/tesseract_plan.sqlite",  [("steps", "plan steps"),
                                          ("help_edges", "step dep graph")]),
]

# cc command namespaces, grouped by area + count
CMD_NAMESPACES = [
    ("project state",     ["-setup", "-scope", "-context", "-set-project", "-list-projects"], "global"),
    ("agents + runs",     ["-agents", "-runs", "-log", "-clear-cache"], "both"),
    ("todos / tasks",     ["-plan", "-todos", "-done", "-edit-todo", "-current", "-current-set", "-current-clear", "-queue", "-run"], "global"),
    ("model dispatch",    ["py", "tiny", "bash", "claude", "claude-import", "chats", "chat-show"], "both"),
    ("chain runtime",     ["-chain", "-chain-last", "-chain-show", "-chain-list"], "local"),
    ("capability cards",  ["-cards", "-card-show", "-card-delete", "-author-cards"], "global"),
    ("GUI cards",         ["-gui-cards", "-gui-show", "-gui-delete", "-author-gui-cards"], "global"),
    ("workflow templates",["-templates", "-template-show", "-template-walk", "-template-delete", "-authorize-templates"], "global"),
    ("workflow jobs",     ["-jobs", "-job-show", "-job-last"], "local"),
    ("DAG cache",         ["-dag-bootstrap", "-dag-status", "-dag-node", "-dag-chain", "-dag-build",
                           "-dag-enqueue", "-dag-successors", "-dag-chains-from", "-dag-chains",
                           "-dag-invalidate"], "global"),
    ("studio launchers",  ["-studio", "-dag-studio", "-wardrobe", "-yt-cut", "studio"], "studio"),
    ("auth + SSH",        ["-auth-seed", "-auth-list", "-auth-grant", "-auth-revoke",
                           "-auth-status", "-auth-ssh"], "studio"),
    ("intake / media",    ["-intake", "-fetch-url"], "studio"),
    ("salted keys",       ["-keys-distribute", "-keys-list", "-keys-status",
                           "-keys-revoke", "-keys-verify", "-proxy-start"], "studio"),
    ("passes pipeline",   ["-passes-list", "-passes-dag", "-passes-run", "-passes-search",
                           "-passes-stats", "-passes-timing", "-passes-backfill"], "studio"),
    ("tesseract",         ["-tesseract-build", "-tesseract-status", "-tesseract-walk",
                           "-tesseract-identify", "-tesseract-reset", "-tesseract-project",
                           "-tesseract-plan", "-tesseract-plan-seed", "-tesseract-open"], "studio"),
    ("orchestration",     ["agent", "swarm", "tool", "workflow", "phase", "tui"], "both"),
]

# Subsystem catalogue (from tesseract/projects.py SUBSYSTEMS) — for the studio status row
SUBSYSTEMS = [
    ("scene_3d",     "3D Scene engine",        "partial"),
    ("texture",      "Texture system",         "partial"),
    ("inference",    "Inference system",       "impl"),
    ("makeup",       "Makeup design system",   "placeholder"),
    ("furniture",    "Furniture design",       "stub"),
    ("search",       "Search system",          "impl"),
    ("render",       "Inference + render",     "partial"),
    ("business",     "Business / CRM",         "placeholder"),
    ("app_builder",  "App + website builder",  "placeholder"),
    ("comms",        "Communications",         "placeholder"),
]

# Multi-device topology
DEVICES = [
    ("Tom's laptop", "local", "owner",          "scene_3d, makeup, render, search, all writers"),
    ("Droplet",      "remote", "host",          "studio apps + Claude proxy + Lucid data connector"),
    ("Friend laptop","remote", "ssh-tunnel",    "SSH forward → wardrobe; auth gate + IP bind"),
    ("Friend tablet","remote", "lucid-embed",   "Read-only Lucid embed of Tesseract; OAuth scope 'mspc:read'"),
]

# Sessions illustration (per-device)
SESSION_LANES = [
    ("term-A · feat-passes",   "agent-uuid 31b98932",  "studio + passes-backfill"),
    ("term-B · feat-tesseract","agent-uuid 7ca18131",  "tesseract-walk + identify"),
    ("term-C · maint-cleanup", "agent-uuid 4a8c846f",  "intake -mv + auth-list"),
    ("term-D · friend-jamie",  "agent-uuid (jamie's)", "wardrobe via SSH-tunnel"),
]

INSTRUCTIONS = """\
== TWINS-MASTER — multi-device + multi-session runtime view ==

Read this BEFORE running anything that touches state.

THE TWINS
  GLOBAL ~/.cc/cc.db         user-wide; 28 tables; shared across all
                              projects + devices owned by one user
  LOCAL  <proj>/.cc/local.db  per-project; chain runs + scope-specific
                              records; isolated per checkout

DISCOVERY ORDER (cc reads these in order)
  1. $CC_LOCAL_DB                  ← explicit env override
  2. $CC_SCOPE_LOCAL_DB            ← cc's own scope-walking export
  3. walk-up from cwd → .cc/local.db
  4. None → "(unscoped)" — only global is touched

SESSION ISOLATION
  Every cc invocation gets a kernel-uuid → CC_AGENT_UUID.
  Every write to runs/agents/chats/chain_runs/phase_steps tags the row
  with this UUID. 5-10 concurrent terminals cannot blur because:
    - sqlite WAL + busy_timeout=30000ms
    - PRAGMA foreign_keys = ON
    - UUIDs disambiguate writers
    - current_task is a singleton row protected by upsert

MULTI-DEVICE
  Owner (Tom's laptop)  : full read/write to global + every local.db
  Droplet               : runs the studio + proxy; can be read-only
                          if Tom prefers (CC_AUTO_SCOPE=0)
  Friend laptop         : SSH-tunneled into droplet's wardrobe (8510)
                          + IP-bound + salted token
  Friend tablet/phone   : Lucid embed (read-only OAuth scope)

TODOS vs WORKFLOW_JOBS
  todos              quick text tasks scoped to active project (global cc.db)
  workflow_jobs      template instantiation: multi-step with HITL gates
                     (local .cc/local.db OR global cc.db depending on cmd)

AGENTS vs AGENT_DEFS
  agent_defs   reusable prompt templates (cc agent define ...)
  agents       runtime claim slot — one row per CC_AGENT_UUID currently
               in flight. Auto-released on EXIT trap.

WHEN TO REGENERATE THIS DOC
  After: schema change in core/lib/db.py, new cmd_X in core/cc, new
  subsystem in tesseract/projects.py, new device class added to the
  share story.
"""


# ── Build ────────────────────────────────────────────────────────────────────
def build(out_path: Path = None) -> Path:
    if out_path is None:
        out_path = paths.DOCS_ROOT / "TWINS-MASTER.svg"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    svg = ET.Element(f"{{{SVG_NS}}}svg", attrib={
        "width": str(W), "height": str(H),
        "viewBox": f"0 0 {W} {H}", "version": "1.1",
        "data-doc-version": "1",
        "data-built-at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "data-doc-name": "TWINS-MASTER",
    })

    # Manifest in <metadata>
    meta = ET.SubElement(svg, f"{{{SVG_NS}}}metadata",
                         attrib={"id": "twins-manifest"})
    contract = ET.SubElement(meta, f"{{{TES_NS}}}contract")
    contract.text = INSTRUCTIONS

    # Background
    _rect(svg, 0, 0, W, H, fill=COL_BG, stroke="#cbd5e1", rx=0)

    # ── Layer 0 — Instructions (visible) ────────────────────────────────────
    l0 = _g(svg, id_="layer:instructions", layer_label="Instructions")
    _rect(l0, 20, 20, 900, 540, fill="#fefce8", stroke="#facc15", rx=10)
    _t(l0, 36, 50, "TWINS-MASTER", size=24, weight="bold")
    _t(l0, 36, 72, "multi-device + multi-session runtime view",
       size=13, color=COL_MUTED)
    y = 100
    for line in INSTRUCTIONS.splitlines():
        if y > 552:
            break
        if line.startswith("=="):
            _t(l0, 36, y, line, size=12, weight="bold", color="#7c2d12")
        elif line.startswith("  "):
            _t(l0, 48, y, line.lstrip(), size=11, color=COL_STROKE,
               family="ui-monospace, Menlo, monospace")
        elif line.strip():
            _t(l0, 36, y, line, size=12, weight="bold", color=COL_STROKE)
        y += 14

    # ── Layer 1 — Device topology (top-right) ───────────────────────────────
    l1 = _g(svg, id_="layer:devices", layer_label="Device topology")
    _section_title(l1, 950, 50, "DEVICES", len(DEVICES))
    dx0, dy0 = 950, 70
    cell_w, cell_h, gap = 430, 110, 10
    cols = 4
    for i, (name, kind, role, notes) in enumerate(DEVICES):
        col, row = i % cols, i // cols
        x = dx0 + col * (cell_w + gap)
        y = dy0 + row * (cell_h + gap)
        _rect(l1, x, y, cell_w, cell_h, fill=COL_DEVICE, stroke=COL_STROKE, rx=10)
        _t(l1, x + 12, y + 22, name, size=14, weight="bold")
        _t(l1, x + 12, y + 42, f"role: {role}", size=11, color=COL_MUTED)
        _t(l1, x + 12, y + 58, f"kind: {kind}", size=11, color=COL_MUTED)
        _t(l1, x + 12, y + 80, notes[:60], size=10, color=COL_STROKE)
        _t(l1, x + 12, y + 96, notes[60:120] if len(notes) > 60 else "",
           size=10, color=COL_STROKE)

    # Connection lines: friend devices → droplet → owner
    # owner laptop @ (950,70), droplet @ (1390,70), friends @ (1830,70) / (2270,70)
    _path(l1, "M 1820 125 L 1830 125", stroke="#0ea5e9", w=2)
    _path(l1, "M 2260 125 L 2270 125", stroke="#0ea5e9", w=2, dash="4 2")
    _path(l1, "M 1390 180 L 1390 198 L 950 198 L 950 180", stroke="#10b981", w=2)

    # ── Layer 2 — Sessions per device ──────────────────────────────────────
    l2 = _g(svg, id_="layer:sessions", layer_label="Sessions")
    sx0, sy0 = 950, 210
    _section_title(l2, sx0, sy0, "ACTIVE SESSION LANES (sample)", len(SESSION_LANES))
    sy = sy0 + 20
    for term, uuid, doing in SESSION_LANES:
        _rect(l2, sx0, sy, 1820, 26, fill=COL_AGENT, stroke=COL_STROKE, rx=6)
        _t(l2, sx0 + 12, sy + 17, term, size=12, weight="bold")
        _t(l2, sx0 + 400, sy + 17, uuid, size=11,
           family="ui-monospace, Menlo, monospace", color=COL_MUTED)
        _t(l2, sx0 + 800, sy + 17, "→  " + doing, size=11)
        sy += 30
    _t(l2, sx0, sy + 14,
       "Every row tagged with CC_AGENT_UUID; rows in agents/runs/chats/chain_runs carry that UUID",
       size=11, color=COL_MUTED)

    # ── Layer 3 — The Twins: GLOBAL + LOCAL databases ──────────────────────
    l3 = _g(svg, id_="layer:db-twins", layer_label="DB twins")
    _section_title(l3, 20, 600, "GLOBAL  ~/.cc/cc.db",
                   len(GLOBAL_TABLES))
    # Global DB box
    _rect(l3, 20, 620, 900, 740, fill=COL_DB_GLOBAL, stroke=COL_STROKE, rx=12)
    _t(l3, 36, 650, "scope: ONE PER USER", size=12, weight="bold", color="#14532d")
    _t(l3, 36, 668, "writer count: every cc invocation", size=11, color="#14532d")
    _t(l3, 36, 686, "concurrent safety: WAL + busy_timeout 30s + agent_uuid tagging",
       size=10, color="#14532d")

    # Tables grid (28 tables, 2 cols × 14 rows)
    cols = 2
    cell_w_g = 420; cell_h_g = 38
    for i, (tname, descr) in enumerate(GLOBAL_TABLES):
        col, row = i % cols, i // cols
        x = 36 + col * (cell_w_g + 10)
        y = 710 + row * (cell_h_g + 6)
        _rect(l3, x, y, cell_w_g, cell_h_g, fill="#ffffff", stroke="#15803d", rx=4)
        _t(l3, x + 8, y + 16, tname, size=11, weight="bold",
           family="ui-monospace, Menlo, monospace", color="#14532d")
        _t(l3, x + 8, y + 30, descr[:48], size=9, color=COL_MUTED)

    # Local DB box
    _section_title(l3, 950, 600, "LOCAL  <proj>/.cc/local.db",
                   len(LOCAL_TABLES))
    _rect(l3, 950, 620, 900, 280, fill=COL_DB_LOCAL, stroke=COL_STROKE, rx=12)
    _t(l3, 966, 650, "scope: ONE PER PROJECT", size=12, weight="bold", color="#312e81")
    _t(l3, 966, 668, "discovery: $CC_LOCAL_DB → $CC_SCOPE_LOCAL_DB → walk-up from cwd",
       size=11, color="#312e81")
    _t(l3, 966, 686, "isolation: cwd-determined; agents in different projects never touch the same file",
       size=10, color="#312e81")
    for i, (tname, descr) in enumerate(LOCAL_TABLES):
        y = 710 + i * 56
        _rect(l3, 966, y, 868, 48, fill="#ffffff", stroke="#3730a3", rx=4)
        _t(l3, 974, y + 18, tname, size=12, weight="bold",
           family="ui-monospace, Menlo, monospace", color="#312e81")
        _t(l3, 974, y + 36, descr, size=10, color=COL_MUTED)

    # Studio-side DBs
    _section_title(l3, 950, 930, "STUDIO-SIDE DBs (also global per user)",
                   sum(len(tabs) for _, tabs in STUDIO_DBS))
    _rect(l3, 950, 950, 900, 410, fill="#f0fdfa", stroke=COL_STROKE, rx=12)
    y = 980
    for path, tables in STUDIO_DBS:
        _t(l3, 970, y, path, size=12, weight="bold",
           family="ui-monospace, Menlo, monospace", color="#134e4a")
        y += 18
        for tname, descr in tables:
            _rect(l3, 990, y, 840, 32, fill="#ffffff", stroke="#0d9488", rx=4)
            _t(l3, 998, y + 14, tname, size=11, weight="bold",
               family="ui-monospace, Menlo, monospace", color="#134e4a")
            _t(l3, 998, y + 26, descr, size=9, color=COL_MUTED)
            y += 36
        y += 10

    # ── Layer 4 — cc dispatch tree ─────────────────────────────────────────
    l4 = _g(svg, id_="layer:dispatch", layer_label="cc dispatch")
    cmd_count = sum(len(cmds) for _, cmds, _ in CMD_NAMESPACES)
    _section_title(l4, 20, 1400, "cc DISPATCH TREE (every flag, grouped)", cmd_count)
    cy = 1420
    for ns, cmds, scope in CMD_NAMESPACES:
        scope_color = {"global": "#16a34a", "local": "#4f46e5",
                       "both": "#0891b2", "studio": "#a16207"}.get(scope, "#475569")
        # Namespace block
        block_h = max(36, 14 + 16 * ((len(cmds) + 6) // 7))
        _rect(l4, 20, cy, 1820, block_h, fill="#ffffff",
              stroke=scope_color, sw=1.5, rx=6)
        _t(l4, 28, cy + 18, ns, size=12, weight="bold")
        # Scope chip
        _rect(l4, 220, cy + 4, 70, 18, fill=scope_color, rx=9)
        _t(l4, 255, cy + 17, scope, size=10, color="#fff",
           weight="bold", anchor="middle")
        # Command flags
        x = 310
        y = cy + 18
        for c in cmds:
            chip_w = 8 + 7 * len(c)
            _rect(l4, x, y - 14, chip_w, 18, fill=COL_CMD,
                  stroke="#9f1239", sw=0.5, rx=8)
            _t(l4, x + 4, y, c, size=10,
               family="ui-monospace, Menlo, monospace", color="#831843")
            x += chip_w + 8
            if x > 1800:
                x = 310; y += 20
        cy += block_h + 8

    # ── Layer 5 — Subsystem status row ─────────────────────────────────────
    l5 = _g(svg, id_="layer:subsystems", layer_label="Subsystems")
    _section_title(l5, 20, cy + 30, "SUBSYSTEMS — status snapshot", len(SUBSYSTEMS))
    sy = cy + 50
    tile_w = 180
    for i, (sid, name, status) in enumerate(SUBSYSTEMS):
        x = 20 + i * (tile_w + 6)
        _rect(l5, x, sy, tile_w, 64, fill=STATUS_COLOR.get(status, "#cbd5e1"),
              stroke=COL_STROKE, rx=8)
        _t(l5, x + 10, sy + 22, name, size=11, weight="bold")
        _t(l5, x + 10, sy + 40, sid, size=10, color="#0f172a",
           family="ui-monospace, Menlo, monospace")
        _t(l5, x + 10, sy + 56, status, size=9, weight="bold", color="#0f172a")

    # ── Layer 6 — ToDo lifecycle ───────────────────────────────────────────
    l6 = _g(svg, id_="layer:todo-lifecycle", layer_label="ToDo lifecycle")
    ly = sy + 90
    _section_title(l6, 20, ly, "ToDo lifecycle (global cc.db)", 5)
    states = [
        ("cc -plan", "model decomposes → todos rows in cc.db (priority=auto)"),
        ("cc -todos", "list pending; status='open' by default"),
        ("cc -current-set <id>", "pin singleton current_task (one row)"),
        ("cc -done <id>", "mark status='done'; current_task cleared"),
        ("cc -edit-todo <id> ...", "amend text; status stays open"),
    ]
    py = ly + 24
    for i, (cmd, descr) in enumerate(states):
        x = 20 + i * 360
        _rect(l6, x, py, 350, 90, fill=COL_TODO, stroke=COL_STROKE, rx=8)
        _t(l6, x + 10, py + 24, f"({i+1}) {cmd}", size=11, weight="bold",
           family="ui-monospace, Menlo, monospace")
        _t(l6, x + 10, py + 50, descr[:48], size=10, color=COL_STROKE)
        _t(l6, x + 10, py + 66, descr[48:96] if len(descr) > 48 else "",
           size=10, color=COL_STROKE)
        # arrow
        if i < len(states) - 1:
            _path(l6, f"M {x + 350} {py + 45} L {x + 360} {py + 45}",
                  stroke=COL_FLOW, w=2)

    # ── Layer 7 — Workflow job lifecycle ───────────────────────────────────
    l7 = _g(svg, id_="layer:job-lifecycle", layer_label="workflow_jobs lifecycle")
    jy = py + 130
    _section_title(l7, 20, jy, "workflow_jobs lifecycle (template → job → steps → HITL)", 6)
    job_states = [
        ("authorize-templates", "Claude writes template into cc.db"),
        ("instantiate job",     "user picks template → row in workflow_jobs"),
        ("walk template",       "template_walker.py validates binds + GUI predictions"),
        ("execute step N",      "run inference; record output in workflow_job_steps"),
        ("HITL gate?",          "if human_checkpoint set → wait for confirm/promote"),
        ("emit final",          "passthrough opcode → status='done'"),
    ]
    py2 = jy + 24
    for i, (state, descr) in enumerate(job_states):
        x = 20 + i * 300
        _rect(l7, x, py2, 290, 90, fill=COL_JOB, stroke=COL_STROKE, rx=8)
        _t(l7, x + 10, py2 + 24, f"({i+1}) {state}", size=11, weight="bold")
        _t(l7, x + 10, py2 + 50, descr[:42], size=10, color=COL_STROKE)
        _t(l7, x + 10, py2 + 66, descr[42:84] if len(descr) > 42 else "",
           size=10, color=COL_STROKE)
        if i < len(job_states) - 1:
            _path(l7, f"M {x + 290} {py2 + 45} L {x + 300} {py2 + 45}",
                  stroke=COL_FLOW, w=2)

    # ── WEAVE layers (live topology + PLANS + queue) ───────────────────────
    weave_y_start = py2 + 130
    weave_y_end = _render_weave_layers(svg, weave_y_start)

    # ── Footer ─────────────────────────────────────────────────────────────
    footer = _g(svg, id_="layer:footer", layer_label="Footer")
    _t(footer, 20, H - 30,
       f"TWINS-MASTER · {len(GLOBAL_TABLES)} global tables · {len(LOCAL_TABLES)} local tables · "
       f"{sum(len(tabs) for _, tabs in STUDIO_DBS)} studio-side tables · "
       f"{cmd_count} cc commands · {len(DEVICES)} device classes · {len(SUBSYSTEMS)} subsystems · "
       f"WEAVE: live topology + PLANS · "
       f"built {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}",
       size=10, color=COL_MUTED)

    ET.ElementTree(svg).write(out_path, encoding="utf-8", xml_declaration=True)
    return out_path


def _render_weave_layers(svg, y_start: int) -> int:
    """Append three WEAVE layers (topology, plans, queue) to the SVG.
    Returns the y-coordinate after the last layer."""
    # Lazy + tolerant imports — if weave isn't installed in this env, skip.
    try:
        import importlib
        topology = importlib.import_module("weave.topology")
        plans    = importlib.import_module("weave.plans")
    except Exception:
        return y_start

    snap   = topology.snapshot()
    online = snap.get("online", [])
    seed_plans = plans.list_plans(active_only=False)

    # ── L8: Live compute topology ──────────────────────────────────────────
    l8 = _g(svg, id_="layer:weave-topology", layer_label="WEAVE: live topology")
    y = y_start + 30
    _section_title(l8, 20, y, "WEAVE — LIVE COMPUTE TOPOLOGY",
                   snap["totals"]["online"])
    y += 20
    _t(l8, 20, y + 4,
       f"online: {snap['totals']['online']}  "
       f"offline: {snap['totals']['offline']}  "
       f"idle: {snap['totals']['idle']}  "
       f"busy: {snap['totals']['busy']}  "
       f"total GPU mem: {snap['totals']['total_gpu_mem_mb']:,} MB",
       size=12, color=COL_MUTED, family="ui-monospace, Menlo, monospace")
    y += 28
    if not online:
        _rect(l8, 20, y, 2760, 90, fill="#fef2f2", stroke="#ef4444", rx=8)
        _t(l8, 36, y + 50,
           "no devices online — run: python3 studio/weave/topology.py seed",
           size=14, weight="bold", color="#7f1d1d")
        y += 100
    else:
        cell_w = 680; cell_h = 90; gap = 10
        cols = 4
        for i, d in enumerate(online):
            col, row = i % cols, i // cols
            x = 20 + col * (cell_w + gap)
            ty = y + row * (cell_h + gap)
            kind_color = {"owner":       "#22c55e",
                          "droplet":     "#0ea5e9",
                          "browser-tab": "#a78bfa",
                          "friend":      "#f472b6",
                          "bot":         "#94a3b8"}.get(d.get("kind"), "#cbd5e1")
            _rect(l8, x, ty, cell_w, cell_h, fill=kind_color,
                  stroke=COL_STROKE, rx=8)
            _t(l8, x + 12, ty + 22, d.get("name", "?"), size=14, weight="bold")
            _t(l8, x + 12, ty + 40,
               f"kind={d.get('kind')}  status={d.get('status')}  "
               f"load={d.get('load_pct', 0.0):.1f}%",
               size=10, family="ui-monospace, Menlo, monospace",
               color="#0f172a")
            ads = d.get("adapters", [])
            if ads:
                a = ads[0]
                _t(l8, x + 12, ty + 58,
                   f"GPU: {a.get('vendor')} {a.get('architecture')} "
                   f"({a.get('available_memory_mb') or '?'} MB)",
                   size=10, family="ui-monospace, Menlo, monospace",
                   color="#0f172a")
            _t(l8, x + 12, ty + 78,
               f"id: {d.get('device_id', '?')[:12]}   "
               f"last seen: {d.get('last_seen', '')[11:19]}Z",
               size=9, color="#1e293b",
               family="ui-monospace, Menlo, monospace")
        rows = (len(online) + cols - 1) // cols
        y += rows * (cell_h + gap) + 20

    # ── L9: PLANS ──────────────────────────────────────────────────────────
    l9 = _g(svg, id_="layer:weave-plans", layer_label="WEAVE: PLANS")
    _section_title(l9, 20, y + 14, "WEAVE — PLANS  (declarative routing rules)",
                   len(seed_plans))
    y += 34
    if not seed_plans:
        _t(l9, 20, y + 30, "no plans seeded — run: python3 studio/weave/plans.py seed",
           size=14, weight="bold", color="#7f1d1d")
        y += 60
    else:
        cell_w = 1380; cell_h = 86; gap = 10
        for i, p in enumerate(seed_plans):
            col, row = i % 2, i // 2
            x = 20 + col * (cell_w + gap)
            ty = y + row * (cell_h + gap)
            active_color = "#fde68a" if p.active else "#e5e7eb"
            _rect(l9, x, ty, cell_w, cell_h, fill=active_color,
                  stroke=COL_STROKE, rx=8)
            # priority badge
            _rect(l9, x + 8, ty + 10, 50, 22, fill="#0f172a", rx=11)
            _t(l9, x + 33, ty + 27, str(p.priority),
               size=12, color="#fff", weight="bold", anchor="middle")
            _t(l9, x + 70, ty + 22, p.name, size=13, weight="bold")
            cond_txt = json.dumps(p.condition, sort_keys=True)[:100]
            act_txt = json.dumps(p.action, sort_keys=True)[:80]
            _t(l9, x + 70, ty + 40, "if  " + cond_txt, size=10,
               family="ui-monospace, Menlo, monospace", color="#1e293b")
            _t(l9, x + 70, ty + 56, "do  " + act_txt, size=10,
               family="ui-monospace, Menlo, monospace", color="#1e293b")
            stamp = ("active · fired " + str(p.fire_count)
                     if p.active else "(disabled)")
            _t(l9, x + 70, ty + 74, stamp, size=10, weight="bold",
               color="#15803d" if p.active else "#475569")
        rows = (len(seed_plans) + 1) // 2
        y += rows * (cell_h + gap) + 18

    # ── L10: Recent job queue / decisions ──────────────────────────────────
    l10 = _g(svg, id_="layer:weave-queue", layer_label="WEAVE: queue")
    # Pull recent decisions from plan_evaluations
    import sqlite3
    db = sqlite3.connect(plans.DB_PATH)
    try:
        rows = db.execute(
            "SELECT ts, pass_id, file_kind, plan_id, decision "
            "FROM plan_evaluations WHERE fired=1 "
            "ORDER BY eval_id DESC LIMIT 12"
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    db.close()

    _section_title(l10, 20, y + 14, "WEAVE — RECENT ROUTING DECISIONS",
                   len(rows))
    y += 34
    if not rows:
        _t(l10, 20, y + 30,
           "no decisions yet — run: python3 studio/weave/routing.py --pass-id mask",
           size=12, color=COL_MUTED)
        y += 60
    else:
        # Header
        _rect(l10, 20, y, 2760, 26, fill="#0f172a", rx=4)
        for x_off, label in [(28, "TS"), (200, "PASS"), (350, "EXT"),
                             (430, "PLAN"), (700, "→ DEVICE"),
                             (1200, "REASON")]:
            _t(l10, x_off, y + 17, label, size=11, weight="bold",
               color="#fff", family="ui-monospace, Menlo, monospace")
        y += 28
        for ts, pid, fk, plan_id, decision in rows:
            try:
                d = json.loads(decision or "{}")
            except Exception:
                d = {}
            _rect(l10, 20, y, 2760, 22, fill="#fff",
                  stroke="#cbd5e1", rx=3, sw=1)
            _t(l10, 28, y + 15, ts[11:19] + "Z", size=10,
               family="ui-monospace, Menlo, monospace", color=COL_STROKE)
            _t(l10, 200, y + 15, pid or "-", size=10,
               family="ui-monospace, Menlo, monospace", color=COL_STROKE)
            _t(l10, 350, y + 15, fk or "-", size=10,
               family="ui-monospace, Menlo, monospace", color=COL_MUTED)
            _t(l10, 430, y + 15, plan_id or "-", size=10,
               family="ui-monospace, Menlo, monospace", color=COL_STROKE)
            dev = d.get("device_name", "(deferred)") if not d.get("deferred") \
                  else "(deferred)"
            _t(l10, 700, y + 15, dev, size=10, weight="bold",
               color="#15803d" if not d.get("deferred") else "#7c2d12")
            reason = (d.get("reason", "") or "")[:130]
            _t(l10, 1200, y + 15, reason, size=10, color=COL_MUTED)
            y += 24

    return y + 30


if __name__ == "__main__":
    out = build()
    print(f"wrote {out}  ({out.stat().st_size:,} bytes)")
