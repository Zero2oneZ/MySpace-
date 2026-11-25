"""DAG Studio backend — FastAPI.

Serves the catalogue / recipes / flows (single source of truth = the existing
nodes.py / recipes.py / flows.py), runs graphs with the real executor, streams
per-node status over SSE, and serves output artifacts.

Run:
    cd /home/tom/models/dag_studio
    .venv/bin/python -m uvicorn backend.app:app --reload --port 8011
"""
from __future__ import annotations

import json
import queue
import sys
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nodes import NODES  # noqa: E402
from recipes import RECIPES, SINGLE_HOPS  # noqa: E402
from types_meta import PORT_COLORS, TYPE_GLYPH, TYPE_COERCIONS  # noqa: E402
from backend.executor import (  # noqa: E402
    run_graph, CACHE_ROOT,
)
from backend.node_map import route_for  # noqa: E402

# route kind -> label shown on the node card
_ROUTE_LABEL = {"pass": "pass", "role": "llm", "connector": "pending",
                "input": "io", "output": "io", "none": "synth"}

try:
    from flows import FLOWS  # noqa: E402
except Exception:
    FLOWS = ()

SAVE_DIR = ROOT / "saved"
SAVE_DIR.mkdir(exist_ok=True)

app = FastAPI(title="DAG Studio")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


# ─── catalogue ────────────────────────────────────────────────────────────────
def _node_dto(n: dict) -> dict:
    return {
        "id": n["id"],
        "name": n["name"],
        "kind": n["kind"],
        "dir": n.get("dir"),
        "entry": n.get("entry"),
        "vram_gb": n.get("vram_gb", 0),
        "cpu_only": n.get("cpu_only", False),
        "uses": n.get("uses"),
        "inputs": n["inputs"],
        "outputs": n["outputs"],
        "params": n["params"],
        "adapter": _ROUTE_LABEL.get(route_for(n["id"])[0], "synth"),
    }


@app.get("/api/catalogue")
def catalogue():
    return {
        "nodes": [_node_dto(n) for n in NODES],
        "port_colors": PORT_COLORS,
        "type_glyph": TYPE_GLYPH,
        "coercions": {k: list(v) for k, v in TYPE_COERCIONS.items()},
    }


@app.get("/api/recipes")
def recipes():
    return {
        "multi": [
            {"id": rid, "name": r["name"], "note": r.get("note", ""), "chain": r["chain"]}
            for rid, r in RECIPES.items()
        ],
        "single": [{"id": sid, "chain": chain} for sid, chain in SINGLE_HOPS.items()],
    }


@app.get("/api/flows")
def flows():
    out = []
    for f in FLOWS:
        out.append({
            "id": f.id, "name": getattr(f, "name", f.id),
            "goal": getattr(f, "goal", ""),
            "steps": [getattr(s, "anchor", None) for s in getattr(f, "steps", [])],
        })
    return out


# ─── saved graphs ─────────────────────────────────────────────────────────────
@app.get("/api/graphs")
def list_graphs():
    return [p.name for p in sorted(SAVE_DIR.glob("*.dag.json"))]


@app.get("/api/graphs/{name}")
def load_graph(name: str):
    f = SAVE_DIR / name
    if not f.exists():
        raise HTTPException(404, "no such graph")
    return json.loads(f.read_text())


class GraphDoc(BaseModel):
    nodes: list[dict]
    edges: list[dict]


@app.post("/api/graphs/{name}")
def save_graph(name: str, doc: GraphDoc):
    if not name.endswith(".dag.json"):
        name += ".dag.json"
    (SAVE_DIR / name).write_text(json.dumps(doc.model_dump(), indent=2))
    return {"saved": name}


# ─── run + SSE ────────────────────────────────────────────────────────────────
_RUNS: dict[str, queue.Queue] = {}


class RunReq(BaseModel):
    nodes: list[dict]
    edges: list[dict]


@app.post("/api/run")
def start_run(req: RunReq):
    run_id = uuid.uuid4().hex[:12]
    q: queue.Queue = queue.Queue()
    _RUNS[run_id] = q

    def emit(ev: dict):
        q.put(ev)

    def worker():
        try:
            run_graph(req.nodes, req.edges, emit)
        finally:
            q.put({"event": "_eof"})

    threading.Thread(target=worker, daemon=True).start()
    return {"run_id": run_id}


@app.get("/api/run/{run_id}/stream")
def stream_run(run_id: str):
    q = _RUNS.get(run_id)
    if q is None:
        raise HTTPException(404, "no such run")

    def gen():
        while True:
            ev = q.get()
            if ev.get("event") == "_eof":
                yield "event: eof\ndata: {}\n\n"
                break
            yield f"data: {json.dumps(ev)}\n\n"
        _RUNS.pop(run_id, None)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# ─── artifacts ────────────────────────────────────────────────────────────────
@app.get("/artifacts/{key}/{filename}")
def artifact(key: str, filename: str):
    f = CACHE_ROOT / key / filename
    if not f.exists():
        raise HTTPException(404, "no such artifact")
    return FileResponse(f)


@app.get("/api/health")
def health():
    return {"ok": True}


# ─── static frontend (built) ──────────────────────────────────────────────────
# Mounted LAST so explicit /api and /artifacts routes take precedence.
_DIST = ROOT / "frontend" / "dist"
if _DIST.exists():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="static")
