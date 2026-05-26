"""Pipeline runtime: topo-sort, type-check, content-addressed cache, mock exec.

Real subprocess execution is delegated to each node-dir's venv (see DAG-GUI.md
§3 phase 3). Until those are wired, `run_step` returns a deterministic stub so
the GUI is fully driveable end-to-end.
"""
from __future__ import annotations
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from nodes import NODES_BY_ID
from types_meta import types_compatible

CACHE_DIR = Path.home() / ".cache" / "dag-studio"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def cache_key(node_id: str, params: dict, input_hashes: list[str]) -> str:
    spec = NODES_BY_ID[node_id]
    payload = json.dumps({
        "impl": spec.get("dir", node_id),
        "entry": spec.get("entry"),
        "params": params,
        "inputs": input_hashes,
    }, sort_keys=True, default=str)
    return hashlib.blake2b(payload.encode(), digest_size=16).hexdigest()


def topo_sort(nodes: list[dict], edges: list[dict]) -> list[str]:
    """Kahn's algorithm. nodes: [{uid, node_id, params}], edges: [{src_uid, dst_uid}]."""
    incoming: dict[str, set[str]] = {n["uid"]: set() for n in nodes}
    outgoing: dict[str, set[str]] = {n["uid"]: set() for n in nodes}
    for e in edges:
        incoming[e["dst_uid"]].add(e["src_uid"])
        outgoing[e["src_uid"]].add(e["dst_uid"])
    ready = [u for u, ins in incoming.items() if not ins]
    order = []
    while ready:
        u = ready.pop(0)
        order.append(u)
        for v in list(outgoing[u]):
            outgoing[u].discard(v)
            incoming[v].discard(u)
            if not incoming[v]:
                ready.append(v)
    if len(order) != len(nodes):
        raise ValueError("cycle detected in graph")
    return order


def validate_edges(nodes: list[dict], edges: list[dict]) -> list[str]:
    """Return human-readable errors for any type-mismatched or missing edges."""
    errs = []
    uid_to_spec = {n["uid"]: NODES_BY_ID[n["node_id"]] for n in nodes}
    for e in edges:
        src = uid_to_spec.get(e["src_uid"])
        dst = uid_to_spec.get(e["dst_uid"])
        if not src or not dst:
            errs.append(f"dangling edge {e}")
            continue
        src_out = next((p for p in src["outputs"] if p["name"] == e.get("src_port", src["outputs"][0]["name"])), None)
        dst_in = next((p for p in dst["inputs"] if p["name"] == e.get("dst_port", dst["inputs"][0]["name"])), None)
        if not src_out or not dst_in:
            errs.append(f"unknown port on edge {e}")
            continue
        if not types_compatible(src_out["type"], dst_in["type"]):
            errs.append(
                f"type mismatch: {src['name']}.{src_out['name']}={src_out['type']} → "
                f"{dst['name']}.{dst_in['name']}={dst_in['type']}"
            )
    return errs


def run_step(node_id: str, params: dict, inputs: dict[str, Any]) -> dict[str, Any]:
    """Mock executor — replace with subprocess dispatch to per-node venvs."""
    spec = NODES_BY_ID[node_id]
    out = {}
    for p in spec["outputs"]:
        out[p["name"]] = {
            "type": p["type"],
            "stub": True,
            "from": spec["name"],
            "ts": time.time(),
        }
    return out


def estimate_vram(nodes: list[dict]) -> float:
    """Sum of VRAM for the heaviest node (since scheduler serializes GPU work)."""
    peaks = [NODES_BY_ID[n["node_id"]].get("vram_gb", 0) for n in nodes]
    return max(peaks) if peaks else 0.0
