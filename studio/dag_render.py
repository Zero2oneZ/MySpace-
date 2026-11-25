#!/usr/bin/env python3
"""dag_render — the whole pipeline as ONE io_hash node DAG with TYPED node-defs + a frontier scheduler
that works on what can be worked on at any given time.

NODE-TYPES (op):
  producer  run a cmd that writes a spine            (floorplan, skeleton, intent)   cpu
  mask      focus a node subset of dep's spine       region= / id_sub=               cpu
  cut       extract masked piece from dep's spine     region= / id_sub= , keep=piece|remaining   cpu
  flip      mirror dep's spine across an axis         axis=x|y|z                      cpu
  reorder   re-sequence dep's spine nodes             order=                          cpu
  engine    emit dep's spine to an engine             engine=godot|blender            cpu
  gpu       image→3D via paperdoll3d                  image=                          gpu (cache+defer)

Every node's OUTPUT is an artifact (spine .json / .gd); deps wire outputs to inputs. The scheduler
runs the READY frontier by affordability: CACHED(out exists)→reuse · cpu→now · gpu→fit?run:DEFER.
Order is free — only data-deps constrain it (so mask/cut/flip/reorder compose & reschedule freely).

  dag_render.py run
"""
import json, os, sys, subprocess
sys.path.insert(0, "/data/Projects/MySpace++/studio"); import spine_ops as ops

S = "/data/Projects/MySpace++/studio"; GENTLY = "/data/Projects/gently/data/probe_calibration"
DAGTMP = "/tmp/dag"; NEED_GB = 8.0
os.makedirs(DAGTMP, exist_ok=True)

# ── THE DAG (typed node defs). focus→cut→flip→reorder→render, + a deferred GPU node ──
DAG = {
  "floorplan": {"op":"producer", "deps":[], "out":f"{S}/scene_spine.floorplan.json",
                "cmd":["python3","floorplan_to_spine.py",f"{GENTLY}/floorplan_seed0.json",f"{S}/scene_spine.floorplan.json"]},
  "cut_wing":  {"op":"cut",     "deps":["floorplan"], "region":[9,99,-99,99], "keep":"piece"},   # right wing
  "flip_wing": {"op":"flip",    "deps":["cut_wing"],  "axis":"x"},                               # mirror to left
  "reorder":   {"op":"reorder", "deps":["flip_wing"]},
  "render":    {"op":"engine",  "deps":["reorder"],   "engine":"godot"},
  "img2glb":   {"op":"gpu",     "deps":[], "image":f"{GENTLY}/painted_orbit_seed0.png"},
}

def out_of(nid):
    n = DAG[nid]; op = n["op"]
    if op == "producer": return n["out"]
    if op == "engine":   return f"{DAGTMP}/{nid}.gd"
    if op == "gpu":      return None
    return f"{DAGTMP}/{nid}.json"                       # mask/cut/flip/reorder → a spine

def gpu_free():
    try:
        o = subprocess.run(["nvidia-smi","--query-gpu=memory.free","--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=8).stdout
        return max([float(x)/1024 for x in o.split()] or [0])
    except Exception: return 0.0

def cost(nid): return "gpu" if DAG[nid]["op"] == "gpu" else "cpu"
def cached(nid):
    o = out_of(nid); return bool(o) and os.path.exists(o)

def run(nid):
    n = DAG[nid]; op = n["op"]; out = out_of(nid)
    if op == "producer":
        return subprocess.run(n["cmd"], cwd=S, capture_output=True, text=True, timeout=300).returncode == 0
    if op in ("mask","cut","flip","reorder"):
        src = json.load(open(out_of(n["deps"][0])))     # consume parent spine
        if op == "mask":    res = ops.mask(src, region=n.get("region"), id_sub=n.get("id_sub"))
        elif op == "cut":   p, r = ops.cut(src, region=n.get("region"), id_sub=n.get("id_sub")); res = p if n.get("keep","piece")=="piece" else r
        elif op == "flip":  res = ops.flip(src, n.get("axis","x"))
        else:               res = ops.reorder(src, n.get("order"))
        json.dump(res, open(out,"w"), indent=1); return True
    if op == "engine":
        eng = "scene_to_godot.py" if n.get("engine","godot")=="godot" else "scene_to_blender.py"
        return subprocess.run(["python3", eng, out_of(n["deps"][0]), out], cwd=S, capture_output=True, text=True, timeout=120).returncode == 0
    if op == "gpu":
        r = subprocess.run(["python3","paperdoll3d.py","gen",n["image"]], cwd=S, capture_output=True, text=True, timeout=60)
        return "pending" not in r.stdout                 # pending = deferred, not done
    return False

def schedule():
    done, deferred, trace = set(), set(), []
    while True:
        frontier = [n for n in DAG if n not in done and n not in deferred and all(d in done for d in DAG[n]["deps"])]
        if not frontier: break
        progress = False
        for nid in frontier:
            if cached(nid):
                done.add(nid); trace.append(("CACHE", nid, DAG[nid]["op"], "reuse")); progress = True
            elif cost(nid) == "cpu":
                ok = run(nid); done.add(nid); trace.append(("RUN", nid, DAG[nid]["op"], "ok" if ok else "FAIL")); progress = True
            else:
                free = gpu_free()
                if free >= NEED_GB:
                    ok = run(nid); done.add(nid); trace.append(("RUN-GPU", nid, DAG[nid]["op"], f"{free:.1f}GB"))
                else:
                    deferred.add(nid); trace.append(("DEFER", nid, DAG[nid]["op"], f"gpu full {free:.1f}GB<{NEED_GB}"))
                progress = True
        if not progress: break
    return trace, done, deferred

if __name__ == "__main__":
    trace, done, deferred = schedule()
    print("── typed-node DAG · frontier schedule ──")
    for st, nid, op, msg in trace: print(f"  {st:8} {nid:11} [{op:8}] {msg}")
    print(f"\n  done: {len(done)} · deferred(GPU): {sorted(deferred) or 'none'}")
    # show the focus→cut→flip→reorder result that flowed to the engine
    last = out_of("reorder")
    if os.path.exists(last):
        d = json.load(open(last)); print(f"  pipeline piece (cut→flip→reorder): {len(d['nodes'])} nodes, e.g. {d['nodes'][0]['id']} @ {d['nodes'][0]['pos']}")
