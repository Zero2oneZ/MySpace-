#!/usr/bin/env python3
"""spine_ops — first-class node-ops on the scene spine: MASK · CUT · FLIP · REORDER.

A "piece" can be focused (mask), extracted (cut), transformed (flip), and re-sequenced (reorder) —
all pure graph transforms in the MetaXR frame, headless-verifiable, feeding back into scene_to_godot/
scene_to_blender. These are node-TYPES the dag_render scheduler runs as CPU (cheap, now). reorder is
free because only real data-deps constrain order.

  spine_ops.py demo <spine.json>
"""
import json, sys, copy

AX = {"x": 0, "y": 1, "z": 2}

def mask(spine, region=None, kind=None, id_sub=None):
    """FOCUS a node subset (a mask/view), non-destructive. region=(x_min,x_max,z_min,z_max) in MetaXR
    world coords (z is the -Z floor axis); id_sub = substring of node id."""
    def hit(n):
        if region:
            x, _, z = n["pos"]; xmn, xmx, zmn, zmx = region
            if not (xmn <= x <= xmx and zmn <= z <= zmx): return False
        if id_sub and id_sub not in n["id"]: return False
        return True
    sel = [n for n in spine["nodes"] if hit(n)]
    return {"_doc": f"MASK {len(sel)}/{len(spine['nodes'])} nodes", "frame": spine["frame"], "nodes": sel}

def cut(spine, **sel):
    """EXTRACT the masked piece as its own spine AND remove it from the source → (piece, remaining)."""
    ids = {n["id"] for n in mask(spine, **sel)["nodes"]}
    piece     = {"_doc": f"CUT piece ({len(ids)})", "frame": spine["frame"],
                 "nodes": [n for n in spine["nodes"] if n["id"] in ids]}
    remaining = {"_doc": f"CUT remainder ({len(spine['nodes'])-len(ids)})", "frame": spine["frame"],
                 "nodes": [n for n in spine["nodes"] if n["id"] not in ids]}
    return piece, remaining

def flip(spine, axis="x"):
    """MIRROR a piece across an axis: negate that coord + mirror yaw. A transform node."""
    a = AX[axis]; s = copy.deepcopy(spine)
    for n in s["nodes"]:
        n["pos"][a] = -n["pos"][a]
        if axis in ("x", "z"): n["rot_euler_deg"][1] = -n["rot_euler_deg"][1]
    s["_doc"] = f"FLIP across {axis}"; return s

def reorder(spine, order=None):
    """RE-SEQUENCE nodes (free — order is unconstrained except by real data-deps)."""
    s = dict(spine)
    s["nodes"] = list(reversed(spine["nodes"])) if order is None else [spine["nodes"][i] for i in order]
    s["_doc"] = "REORDER"; return s

if __name__ == "__main__":
    if sys.argv[1] == "demo":
        sp = json.load(open(sys.argv[2])); N = len(sp["nodes"]); FOOT_X = 18.0
        print(f"source spine: {N} nodes")
        # MASK: focus the LEFT wing (world x < 9)
        m = mask(sp, region=(0, 9, -99, 99))
        print(f"  MASK (left wing, x<9): {len(m['nodes'])} nodes focused")
        # CUT: extract the RIGHT wing (x >= 9) as its own piece
        piece, rem = cut(sp, region=(9, 99, -99, 99))
        print(f"  CUT (right wing, x>=9): piece={len(piece['nodes'])} · remaining={len(rem['nodes'])}")
        # FLIP the cut piece across X (mirror right wing → left)
        before = piece["nodes"][0]["pos"][:] if piece["nodes"] else [0,0,0]
        fl = flip(piece, "x")
        after = fl["nodes"][0]["pos"][:] if fl["nodes"] else [0,0,0]
        print(f"  FLIP piece across x: node0 pos {before} → {after}")
        # REORDER (reverse)
        ro = reorder(piece)
        print(f"  REORDER piece: first id {piece['nodes'][0]['id']} → {ro['nodes'][0]['id']}")
        out = sys.argv[2].replace(".json", ".cutflip.json")
        json.dump(fl, open(out, "w"), indent=1)
        print(f"  → saved flipped cut piece → {out.split('/')[-1]}")
