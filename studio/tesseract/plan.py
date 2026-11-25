"""plan.py — step tracker + help graph for the Tesseract.

SQLite at studio/cache/dag/tesseract_plan.sqlite. Two tables:

    steps(
        step_id PK, title, description, status (planned/in_progress/done/blocked),
        subsystem, owner, depends_on JSON, helps JSON, blocked_by JSON,
        created, completed
    )
    help_edges(step_a, step_b, kind ['enables'/'satisfies'/'unblocks'])

Public API:
    add_step(title, ...)       → step_id
    mark(step_id, status)
    list_steps(status=None)    → list[dict]
    add_help_edge(a, b, kind)
    render_mermaid()           → str (Mermaid graph for docs)
    seed_from_done_work()      → record the work this conversation has shipped
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
STUDIO_ROOT = HERE.parent
sys.path.insert(0, str(STUDIO_ROOT))
import paths   # noqa: E402

DB_PATH = paths.DAG_CACHE_DIR / "tesseract_plan.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS steps (
    step_id     TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    description TEXT,
    status      TEXT NOT NULL DEFAULT 'planned',
    subsystem   TEXT,
    owner       TEXT,
    depends_on  TEXT,
    helps       TEXT,
    blocked_by  TEXT,
    created     TEXT NOT NULL,
    completed   TEXT
);
CREATE INDEX IF NOT EXISTS idx_steps_status    ON steps(status);
CREATE INDEX IF NOT EXISTS idx_steps_subsystem ON steps(subsystem);

CREATE TABLE IF NOT EXISTS help_edges (
    step_a TEXT NOT NULL,
    step_b TEXT NOT NULL,
    kind   TEXT NOT NULL,
    PRIMARY KEY (step_a, step_b, kind)
);
"""


def _db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.executescript(SCHEMA)
    return c


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def add_step(title: str, description: str = "", *,
             status: str = "planned", subsystem: Optional[str] = None,
             owner: Optional[str] = None,
             depends_on: Optional[list[str]] = None,
             helps: Optional[list[str]] = None,
             blocked_by: Optional[list[str]] = None) -> str:
    sid = uuid.uuid4().hex[:8]
    with _db() as c:
        c.execute(
            "INSERT INTO steps (step_id, title, description, status, subsystem, "
            "                   owner, depends_on, helps, blocked_by, created) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, title, description, status, subsystem, owner,
             json.dumps(depends_on or []), json.dumps(helps or []),
             json.dumps(blocked_by or []), now_iso()),
        )
    return sid


def mark(step_id: str, status: str) -> bool:
    completed = now_iso() if status == "done" else None
    with _db() as c:
        r = c.execute(
            "UPDATE steps SET status=?, completed=COALESCE(?, completed) "
            "WHERE step_id=?", (status, completed, step_id),
        )
        return r.rowcount > 0


def list_steps(status: Optional[str] = None,
               subsystem: Optional[str] = None) -> list[dict]:
    q  = "SELECT step_id, title, description, status, subsystem, owner, " \
         "depends_on, helps, blocked_by, created, completed FROM steps"
    where: list[str] = []
    params: list = []
    if status:
        where.append("status=?"); params.append(status)
    if subsystem:
        where.append("subsystem=?"); params.append(subsystem)
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " ORDER BY created"
    with _db() as c:
        rows = c.execute(q, params).fetchall()
    return [{
        "step_id": r[0], "title": r[1], "description": r[2],
        "status":  r[3], "subsystem": r[4], "owner": r[5],
        "depends_on": json.loads(r[6] or "[]"),
        "helps":      json.loads(r[7] or "[]"),
        "blocked_by": json.loads(r[8] or "[]"),
        "created": r[9], "completed": r[10],
    } for r in rows]


def add_help_edge(step_a: str, step_b: str, kind: str = "enables") -> None:
    with _db() as c:
        c.execute(
            "INSERT OR IGNORE INTO help_edges (step_a, step_b, kind) "
            "VALUES (?, ?, ?)", (step_a, step_b, kind),
        )


def render_mermaid() -> str:
    lines = ["```mermaid", "flowchart LR"]
    for s in list_steps():
        color = {"planned": "fill:#cbd5e1", "in_progress": "fill:#facc15",
                 "done": "fill:#22c55e",     "blocked": "fill:#ef4444"}.get(s["status"], "")
        title = s["title"].replace('"', "'")[:42]
        lines.append(f"  S{s['step_id']}[\"{title}\"]:::s_{s['status']}")
        for h in s["helps"]:
            lines.append(f"  S{s['step_id']} --> S{h}")
    # Status class defs
    lines += [
        "  classDef s_planned     fill:#cbd5e1,stroke:#64748b;",
        "  classDef s_in_progress fill:#facc15,stroke:#a16207;",
        "  classDef s_done        fill:#22c55e,stroke:#15803d;",
        "  classDef s_blocked     fill:#ef4444,stroke:#991b1b;",
        "```",
    ]
    return "\n".join(lines)


def stats() -> dict:
    with _db() as c:
        rows = c.execute(
            "SELECT status, COUNT(*) FROM steps GROUP BY status"
        ).fetchall()
    return {r[0]: r[1] for r in rows}


# ── Seed: record work already shipped in this conversation ─────────────────
SEED_STEPS = [
    # (title, subsystem, status, description, helps_titles)
    ("cc bash hardening + INT/TERM traps", "inference", "done",
     "Hardened the cc terminal manager substrate.", []),
    ("MySpace++ cross-OS port",            "inference", "done",
     "install.sh / install.ps1 / Dockerfile / flake.nix.", []),
    ("Studio merge (dag_studio → studio/)", "inference", "done",
     "Physically integrated dag_studio + bundled all docs.", []),
    ("Auth gate + SSH friend onboarding",  "comms",     "done",
     "Whitelist + IP-bind + SSH port-forward grants.", []),
    ("Salted-key registry + Claude proxy", "comms",     "done",
     "Friends use Tom's keys via opaque tokens.",
     ["Auth gate + SSH friend onboarding"]),
    ("Pinterest search + auto-organize",   "search",    "done",
     "Streamlit search → fetch-url.sh → classify → sidecar.", []),
    ("YouTube cutter + vocal separation",  "render",    "done",
     "ffmpeg + demucs fallback; per-stem auto-organize.", []),
    ("Passes registry + filetype DAG",     "inference", "done",
     "20 declarative passes + per-extension import/lazy split.", []),
    ("Passes inference shims + SVG bundle", "inference", "done",
     "Default callables for every pass; layered_svg emitter.", []),
    ("Pieces searchable index",            "search",    "done",
     "SQLite pieces table for skip-if-precomputed.",
     ["Pinterest search + auto-organize"]),
    ("Import pipeline + backfill loop",    "inference", "done",
     "Heavy passes at import; backfill walks media/.", []),
    ("Tesseract Renderer scaffold",        "inference", "in_progress",
     "Master SVG + walker contract + DAG-of-DAGs.", []),

    # Placeholders for the work that's still ahead
    ("Wire real DepthPro inference",       "inference", "planned",
     "Replace passes.pass_depth pseudo-depth with apple_DepthPro.", []),
    ("Wire real CLIP-Interrogator caption", "inference", "planned",
     "Replace pass_caption cc-tiny fallback with CLIP-Interrogator.", []),
    ("Wire MediaPipe Pose keypoints",      "inference", "planned",
     "Activate pass_keypoints — currently stubbed.", []),
    ("Mesh thumbnail via Blender headless", "scene_3d",  "planned",
     "pass_mesh_thumb stub → real Blender CLI render.", []),
    ("3D scene editor MVP",                "scene_3d",  "planned",
     "Scene-graph editor consuming media/Media/3d/*.glb.", []),
    ("Makeup designer MVP",                "makeup",    "planned",
     "JSONL layer stacks on HEAD_TEMPLET.", []),
    ("Furniture designer MVP",             "furniture", "planned",
     "Room-type → furniture-bucket placement UI.", []),
    ("Business / CRM module",              "business",  "planned",
     "Placeholder per Tom's spec.", []),
    ("App + website builder",              "app_builder","planned",
     "Placeholder per Tom's spec.", []),
    ("Comms hub (inbox / messaging)",      "comms",     "planned",
     "Placeholder per Tom's spec.", []),
]


def seed_from_done_work() -> dict:
    """Idempotent — only adds steps that aren't already in the DB by title."""
    with _db() as c:
        existing = {r[0] for r in c.execute("SELECT title FROM steps")}
    added = 0
    # First pass: insert all steps, remember their IDs by title.
    title_to_id: dict[str, str] = {}
    for title, sub, status, descr, _helps in SEED_STEPS:
        if title in existing:
            with _db() as c:
                row = c.execute("SELECT step_id FROM steps WHERE title=?",
                                (title,)).fetchone()
                if row:
                    title_to_id[title] = row[0]
            continue
        sid = add_step(title, descr, status=status, subsystem=sub)
        title_to_id[title] = sid
        added += 1
    # Second pass: write help edges using the now-known IDs.
    for title, _sub, _status, _descr, helps_titles in SEED_STEPS:
        a = title_to_id.get(title)
        if not a:
            continue
        for ht in helps_titles:
            b = title_to_id.get(ht)
            if b:
                add_help_edge(a, b, kind="enables")
    return {"added": added,
            "total_in_db": sum(stats().values()),
            "by_status": stats()}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(prog="plan.py")
    sp = ap.add_subparsers(dest="cmd", required=True)

    p_add = sp.add_parser("add")
    p_add.add_argument("title")
    p_add.add_argument("--description", default="")
    p_add.add_argument("--subsystem", default=None)
    p_add.add_argument("--status", default="planned")

    p_list = sp.add_parser("list")
    p_list.add_argument("--status", default=None)
    p_list.add_argument("--subsystem", default=None)

    p_mark = sp.add_parser("mark")
    p_mark.add_argument("step_id"); p_mark.add_argument("status")

    sp.add_parser("seed")
    sp.add_parser("stats")
    sp.add_parser("mermaid")

    args = ap.parse_args()

    if args.cmd == "add":
        print(add_step(args.title, args.description,
                       status=args.status, subsystem=args.subsystem))
    elif args.cmd == "list":
        rows = list_steps(status=args.status, subsystem=args.subsystem)
        if not rows:
            print("(no steps)"); raise SystemExit
        print(f"{'id':<9} {'status':<12} {'subsystem':<14} {'title'}")
        print("-" * 90)
        for s in rows:
            print(f"{s['step_id']:<9} {s['status']:<12} {s['subsystem'] or '-':<14} {s['title']}")
    elif args.cmd == "mark":
        ok = mark(args.step_id, args.status)
        print("ok" if ok else "no such step")
    elif args.cmd == "seed":
        print(json.dumps(seed_from_done_work(), indent=2))
    elif args.cmd == "stats":
        print(json.dumps(stats(), indent=2))
    elif args.cmd == "mermaid":
        print(render_mermaid())
