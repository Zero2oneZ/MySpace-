"""Exercise every recipe (C01-C17) and single-hop (S01-S21) through the runtime.

Mirrors app.py's `add_node` + `auto_wire` flow without Streamlit, then runs:
  validate_edges → topo_sort → run_step per node.

Run:
  python test_pipelines.py
"""
from __future__ import annotations
import sys
import time
import uuid

from nodes import NODES_BY_ID
from recipes import RECIPES, SINGLE_HOPS
from runtime import cache_key, run_step, topo_sort, validate_edges
from types_meta import types_compatible


def build_graph(chain_ids: list[str]) -> tuple[list[dict], list[dict]]:
    nodes: list[dict] = []
    for nid in chain_ids:
        spec = NODES_BY_ID[nid]
        uid = f"{nid}-{uuid.uuid4().hex[:6]}"
        params = {p["name"]: p.get("default") for p in spec["params"] if "default" in p}
        nodes.append({"uid": uid, "node_id": nid, "params": params, "status": "idle"})

    edges: list[dict] = []
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
    return nodes, edges


def run_chain(chain_ids: list[str]) -> dict:
    t0 = time.time()
    nodes, edges = build_graph(chain_ids)

    errs = validate_edges(nodes, edges)
    if errs:
        return {"ok": False, "stage": "validate", "errors": errs,
                "nodes": len(nodes), "edges": len(edges), "ms": int((time.time() - t0) * 1000)}

    unconnected = []
    for n in nodes:
        spec = NODES_BY_ID[n["node_id"]]
        for inp in spec["inputs"]:
            connected = any(e["dst_uid"] == n["uid"] and e["dst_port"] == inp["name"] for e in edges)
            if not connected:
                unconnected.append(f"{spec['name']}.{inp['name']}({inp['type']})")

    try:
        order = topo_sort(nodes, edges)
    except ValueError as exc:
        return {"ok": False, "stage": "topo", "errors": [str(exc)],
                "nodes": len(nodes), "edges": len(edges), "ms": int((time.time() - t0) * 1000)}

    outputs: dict[str, dict] = {}
    for uid in order:
        inst = next(n for n in nodes if n["uid"] == uid)
        in_inputs = {}
        for e in edges:
            if e["dst_uid"] == uid:
                in_inputs[e["dst_port"]] = outputs.get(e["src_uid"], {})
        try:
            outputs[uid] = run_step(inst["node_id"], inst["params"], in_inputs)
        except Exception as exc:
            return {"ok": False, "stage": "run",
                    "errors": [f"{NODES_BY_ID[inst['node_id']]['name']}: {exc}"],
                    "nodes": len(nodes), "edges": len(edges),
                    "ms": int((time.time() - t0) * 1000)}

    key = cache_key(nodes[-1]["node_id"], nodes[-1]["params"],
                    [e["src_uid"] for e in edges if e["dst_uid"] == nodes[-1]["uid"]])
    return {"ok": True, "stage": "done", "nodes": len(nodes), "edges": len(edges),
            "order": len(order), "unconnected": unconnected, "cache_key": key,
            "ms": int((time.time() - t0) * 1000)}


def main() -> int:
    from flows import FLOWS  # late import: keeps recipes-only runs lightweight
    suites = [
        ("Multi-hop recipes (C01-C25)", [(rid, r["chain"], r["name"]) for rid, r in RECIPES.items()]),
        ("Single-hop chains (S01-S24)", [(sid, chain, " → ".join(chain)) for sid, chain in SINGLE_HOPS.items()]),
        ("Flows (F-*)", [(f.id, f.chain, f.name) for f in FLOWS]),
    ]

    total = 0
    passed = 0
    failed: list[tuple[str, str, dict]] = []
    unconnected_summary: list[tuple[str, list[str]]] = []

    for suite_name, entries in suites:
        print(f"\n=== {suite_name} ===")
        for rid, chain, label in entries:
            total += 1
            res = run_chain(chain)
            tag = "PASS" if res["ok"] else "FAIL"
            extra = ""
            if res["ok"] and res["unconnected"]:
                extra = f"  [unconnected inputs: {len(res['unconnected'])}]"
                unconnected_summary.append((rid, res["unconnected"]))
            print(f"  [{tag}] {rid:<4} {label:<48} "
                  f"nodes={res['nodes']:>2} edges={res['edges']:>2} "
                  f"{res['ms']:>4}ms  ({res['stage']}){extra}")
            if res["ok"]:
                passed += 1
            else:
                failed.append((rid, label, res))

    print(f"\n=== Summary ===")
    print(f"  total : {total}")
    print(f"  passed: {passed}")
    print(f"  failed: {len(failed)}")

    if unconnected_summary:
        print(f"\n  Pipelines passing but with unconnected inputs ({len(unconnected_summary)}):")
        for rid, ports in unconnected_summary:
            print(f"    {rid}: {', '.join(ports)}")

    if failed:
        print(f"\n  Failure detail:")
        for rid, label, res in failed:
            print(f"    {rid} ({label}) @ {res['stage']}")
            for e in res["errors"]:
                print(f"      - {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
