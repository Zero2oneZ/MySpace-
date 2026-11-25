"""Real graph executor for DAG Studio.

Responsibilities
----------------
- topo-sort the graph (reuses runtime.topo_sort / validate_edges)
- content-addressed cache under ~/.cache/dag-studio/<cache_key>/
- per-node execution via an *adapter*:
    * if a real adapter is registered AND the model dir is provisioned
      (has a .venv) -> run the real model (subprocess into that venv)
    * otherwise -> the synth renderer writes a *valid, viewable* artifact of
      the correct port type (PNG / WAV / TXT / OBJ / JSON / GIF) so the whole
      pipeline + viewers work end-to-end today. Swap any node to its true model
      by dropping an adapter in adapters/ + creating the model's venv.
- GPU mutex: nodes with cpu_only=False are serialized (single-GPU-safe);
  cpu_only nodes may overlap. (We run sequentially in topo order here, but the
  lock is honoured so a future thread-pool stays correct.)
- emits status events through a callback so the API can stream them (SSE).

Artifacts are written under the cache dir and served by the API at /artifacts.
"""
from __future__ import annotations

import json
import math
import shutil
import struct
import sys
import threading
import time
import wave
from pathlib import Path
from typing import Any, Callable

# import the existing catalogue (parent dir of backend/)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nodes import NODES_BY_ID, MODELS_ROOT  # noqa: E402
from runtime import cache_key, topo_sort, validate_edges  # noqa: E402
from backend import dispatch  # noqa: E402  — the real run_step (passes / ai_orch / droplet)

CACHE_ROOT = Path.home() / ".cache" / "dag-studio"
CACHE_ROOT.mkdir(parents=True, exist_ok=True)

_GPU_LOCK = threading.Lock()

# default output port -> port type, used to pick what artifact to synthesize
def _primary_out_type(spec: dict) -> str | None:
    outs = spec.get("outputs", [])
    return outs[0]["type"] if outs else None


# ─── synth renderers: produce real, valid, viewable files per port type ───────
def _synth_png(path: Path, label: str, sub: str, accent: str):
    from PIL import Image, ImageDraw
    W, H = 768, 512
    img = Image.new("RGB", (W, H), (14, 16, 22))
    d = ImageDraw.Draw(img)
    # gradient bar
    for x in range(W):
        t = x / W
        d.line([(x, 0), (x, 10)], fill=_lerp((34, 211, 238), (16, 185, 129), t))
    ar, ag, ab = _hex(accent)
    d.rectangle([24, 60, W - 24, H - 60], outline=(ar, ag, ab), width=3)
    d.text((40, 90), label, fill=(235, 238, 240))
    d.text((40, 120), sub, fill=(139, 147, 167))
    d.text((40, H - 90), "synth preview · provision adapter for real output",
           fill=(120, 120, 130))
    img.save(path)


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _hex(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _synth_wav(path: Path, seconds: float = 2.0, freq: float = 220.0):
    rate = 16000
    n = int(rate * seconds)
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(n):
            v = int(12000 * math.sin(2 * math.pi * freq * i / rate)
                    * math.exp(-3 * i / n))  # decaying tone
            frames += struct.pack("<h", v)
        w.writeframes(bytes(frames))


def _synth_gif(path: Path, label: str, accent: str):
    from PIL import Image, ImageDraw
    frames = []
    ar, ag, ab = _hex(accent)
    for k in range(12):
        img = Image.new("RGB", (480, 320), (14, 16, 22))
        d = ImageDraw.Draw(img)
        x = 40 + k * 32
        d.ellipse([x, 130, x + 60, 190], fill=(ar, ag, ab))
        d.text((20, 20), label, fill=(235, 238, 240))
        frames.append(img)
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=80, loop=0)


def _synth_obj(path: Path):
    # unit cube
    verts = [(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
             (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]
    faces = [(1, 2, 3, 4), (5, 6, 7, 8), (1, 2, 6, 5),
             (2, 3, 7, 6), (3, 4, 8, 7), (4, 1, 5, 8)]
    lines = ["# synth cube"]
    lines += [f"v {x} {y} {z}" for x, y, z in verts]
    lines += ["f " + " ".join(map(str, f)) for f in faces]
    path.write_text("\n".join(lines))


def synth_render(spec: dict, params: dict, outdir: Path, accent: str) -> dict:
    """Write a valid placeholder artifact of the node's primary output type."""
    t = _primary_out_type(spec)
    name = spec["name"]
    if t in ("IMG", "DEPTH", "MASK", "KPTS"):
        f = outdir / "out.png"
        _synth_png(f, name, f"{t} · {params}"[:80], accent)
        return {"type": t, "filename": f.name, "kind": "image"}
    if t == "VID":
        f = outdir / "out.gif"
        _synth_gif(f, name, accent)
        return {"type": t, "filename": f.name, "kind": "video"}
    if t in ("AUD", "MUS"):
        f = outdir / "out.wav"
        _synth_wav(f, freq=330 if t == "MUS" else 220)
        return {"type": t, "filename": f.name, "kind": "audio"}
    if t in ("TXT", "MD"):
        f = outdir / ("out.md" if t == "MD" else "out.txt")
        body = params.get("prompt") or params.get("text") or ""
        f.write_text(f"# {name}\n\n{body}\n\n(synth output · {t})\n")
        return {"type": t, "filename": f.name, "kind": "text"}
    if t == "3D":
        f = outdir / "out.obj"
        _synth_obj(f)
        return {"type": t, "filename": f.name, "kind": "mesh"}
    if t == "EMB":
        f = outdir / "out.json"
        f.write_text(json.dumps({"dim": 8, "vector": [round(math.sin(i), 4) for i in range(8)]}))
        return {"type": t, "filename": f.name, "kind": "embedding"}
    # sinks / unknown
    f = outdir / "out.json"
    f.write_text(json.dumps({"node": name, "params": params, "note": "no output port"}))
    return {"type": t or "NONE", "filename": f.name, "kind": "json"}


# ─── adapter registry (real models plug in here) ──────────────────────────────
# An adapter is: fn(spec, params, inputs, outdir) -> artifact dict
# (same shape as synth_render's return). Register real ones in adapters/.
ADAPTERS: dict[str, Callable[..., dict]] = {}


def register(node_id: str):
    def deco(fn):
        ADAPTERS[node_id] = fn
        return fn
    return deco


def is_provisioned(spec: dict) -> bool:
    """A node can run for real iff it has a registered adapter and its model
    dir contains a .venv."""
    if spec["id"] not in ADAPTERS:
        return False
    d = spec.get("dir")
    if not d:
        return False
    return (MODELS_ROOT / d / ".venv").exists()


def adapter_status(spec: dict) -> str:
    if spec["id"] in ADAPTERS:
        return "real" if is_provisioned(spec) else "needs-venv"
    return "synth"


# load real adapters (best-effort; they self-register via @register)
try:  # noqa: SIM105
    from . import adapters  # noqa: F401
except Exception:
    try:
        import adapters  # noqa: F401
    except Exception:
        pass


# ─── execution ────────────────────────────────────────────────────────────────
def _node_cache_key(inst: dict, edges: list[dict]) -> str:
    in_uids = sorted(e["src_uid"] for e in edges if e["dst_uid"] == inst["uid"])
    return cache_key(inst["node_id"], inst["params"], in_uids)


_EXT = {"image": "png", "video": "mp4", "audio": "wav", "text": "txt",
        "mesh": "obj", "embedding": "npy", "json": "json", "file": "bin"}


def _materialize(d: dict, spec: dict, outdir: Path, accent: str) -> dict:
    """Turn a dispatch result into a served artifact under outdir.
    Keeps `path` = the real source file so downstream passes can read it."""
    kind = d.get("kind") or "json"
    src = d.get("path")
    val = d.get("value")
    if d.get("error"):
        fn = "error.json"
        (outdir / fn).write_text(json.dumps({"error": d["error"], "pass_id": d.get("pass_id")}))
        return {"type": d.get("type"), "filename": fn, "kind": "json",
                "path": None, "value": None}
    if src and Path(src).exists():
        ext = Path(src).suffix.lstrip(".") or _EXT.get(kind, "bin")
        fn = f"out.{ext}"
        try:
            shutil.copy(src, outdir / fn)
        except OSError:
            fn = "ref.json"
            (outdir / fn).write_text(json.dumps({"path": src}))
            kind = "json"
        return {"type": d.get("type"), "filename": fn, "kind": kind,
                "path": src, "value": val}
    if val is not None:
        fn = "out.txt"
        (outdir / fn).write_text(str(val))
        return {"type": d.get("type") or "TXT", "filename": fn, "kind": "text",
                "path": str(outdir / fn), "value": val}
    # routed input with nothing yet (e.g. unset file param) — synth a placeholder
    art = synth_render(spec, {}, outdir, accent)
    art["path"] = str(outdir / art["filename"])
    return art


def run_graph(nodes: list[dict], edges: list[dict],
              emit: Callable[[dict], None]) -> dict:
    """Execute the graph in topo order. `emit` receives event dicts:
       {event: node|done|error, ...}. Returns final outputs map."""
    errs = validate_edges(nodes, edges)
    if errs:
        emit({"event": "error", "errors": errs})
        return {}
    try:
        order = topo_sort(nodes, edges)
    except ValueError as exc:
        emit({"event": "error", "errors": [str(exc)]})
        return {}

    by_uid = {n["uid"]: n for n in nodes}
    outputs: dict[str, dict] = {}
    total = len(order)
    emit({"event": "start", "total": total, "order": order})

    for i, uid in enumerate(order):
        inst = by_uid[uid]
        spec = NODES_BY_ID[inst["node_id"]]
        key = _node_cache_key(inst, edges)
        outdir = CACHE_ROOT / key
        accent = "#22d3ee"
        from types_meta import PORT_COLORS
        ot = _primary_out_type(spec)
        accent = PORT_COLORS.get(ot, "#22d3ee")

        emit({"event": "node", "uid": uid, "status": "running",
              "index": i, "total": total, "cache_key": key,
              "name": spec["name"]})
        t0 = time.time()

        # cache hit?
        meta_f = outdir / "artifact.json"
        if meta_f.exists():
            art = json.loads(meta_f.read_text())
            outputs[uid] = art
            emit({"event": "node", "uid": uid, "status": "cached",
                  "cache_key": key, "artifact": art,
                  "ms": int((time.time() - t0) * 1000)})
            continue

        outdir.mkdir(parents=True, exist_ok=True)
        # gather inputs (artifacts of upstream nodes)
        inputs = {}
        for e in edges:
            if e["dst_uid"] == uid:
                inputs[e["dst_port"]] = outputs.get(e["src_uid"])

        try:
            # try the REAL dispatcher (passes / ai_orch / droplet); synth-fallback
            # for unrouted nodes (connectors pending) or an unreachable backend.
            lock = _GPU_LOCK if not spec.get("cpu_only") else None
            try:
                if lock:
                    lock.acquire()
                d = dispatch.run_step(inst["node_id"], inst["params"], inputs)
            except Exception as dexc:  # noqa: BLE001 — backend down/unreachable
                d = {"routed": False, "error": f"dispatch: {dexc}"}
            finally:
                if lock:
                    lock.release()

            if d and d.get("routed"):
                art = _materialize(d, spec, outdir, accent)
                art["engine"] = d.get("engine", "real")
                if d.get("error"):
                    art["error"] = d["error"]
                if d.get("pass_id"):
                    art["pass_id"] = d["pass_id"]
            else:
                art = synth_render(spec, inst["params"], outdir, accent)
                art["engine"] = "synth"
                if d and d.get("error"):
                    art["note"] = d["error"]
            art["url"] = f"/artifacts/{key}/{art['filename']}"
            art["cache_key"] = key
            meta_f.write_text(json.dumps(art))
            outputs[uid] = art
            emit({"event": "node", "uid": uid,
                  "status": "error" if art.get("error") else "done",
                  "cache_key": key, "artifact": art,
                  "ms": int((time.time() - t0) * 1000)})
        except Exception as exc:  # noqa: BLE001
            emit({"event": "node", "uid": uid, "status": "error",
                  "cache_key": key, "error": str(exc)})
            emit({"event": "error", "errors": [f"{spec['name']}: {exc}"]})
            return outputs

    emit({"event": "done", "outputs": outputs})
    return outputs
