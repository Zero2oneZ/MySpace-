#!/usr/bin/env python3
"""paperdoll3d — image→3D as a PAPER DOLL with GPU caching + delay tolerance.

Nested dolls (same recursive law as Godot Node⊂Scene⊂Node / conductor AgentScope / io_hash PLACE):
    Image(cid)  ⊂  Img2GLB(GPU op)  ⊂  GLB(cid)  ⊂  ScenePlace(spine node)

The GPU leaf (ComfyUI Hunyuan3D-v2 on :8188) is:
  • CACHED by io_hash — same image+op → reuse the cached GLB, NO GPU call.
  • DELAY-TOLERANT — GPU full → enqueue PENDING (return a handle), drain when a card frees.
Reuses: the conductor's nvidia-smi VRAM-fit check, the chain's pending→done status, content-addressed cache.

  paperdoll3d.py gen <image>   ·   drain   ·   status
"""
import json, sys, os, hashlib, shutil, subprocess, urllib.request

STUDIO = "/data/Projects/MySpace++/studio"
CACHE  = f"{STUDIO}/cache3d"; QUEUE = f"{CACHE}/queue.jsonl"
CHAIN  = "/data/Projects/ATLAS/bin/chain"
NEED_GB = 8.0                                              # image→3D VRAM footprint
COMFY  = "http://localhost:8188"
PIXAL3D_URL = os.environ.get("PIXAL3D_URL", "http://localhost:7860")   # Pixal3D (TRELLIS) gradio app

def cid(path):                                            # content id of the input (cache key seed)
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(65536), b""): h.update(b)
    return h.hexdigest()[:16]

def io_hash(*parts): return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

def gpu_free_gb():
    try:
        out = subprocess.run(["nvidia-smi","--query-gpu=memory.free","--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=8).stdout
        return [float(x)/1024 for x in out.split()]
    except Exception: return []

def log(op, what):
    try: subprocess.run([CHAIN,"add","main",what,"paperdoll3d"],
                        env={**os.environ,"ATLAS_OPCODE":op,"ATLAS_AGENT_ID":"paperdoll3d","PWD":STUDIO},
                        capture_output=True, cwd=STUDIO, timeout=10)
    except Exception: pass

def enqueue(rec):
    os.makedirs(CACHE, exist_ok=True)
    with open(QUEUE,"a") as f: f.write(json.dumps(rec)+"\n")

import shutil
sys.path.insert(0, STUDIO)
COMFY_INPUT = "/data/Projects/ComfyUI/input"

def _hunyuan_ckpt():                                       # is a Hunyuan3D checkpoint installed?
    import comfy as cf
    try: oi = cf._get("/object_info")
    except Exception: return None
    ck = oi.get("ImageOnlyCheckpointLoader",{}).get("input",{}).get("required",{}).get("ckpt_name")
    opts = ck[0] if isinstance(ck, list) and ck else []
    return next((c for c in (opts or []) if any(t in str(c).lower() for t in ("hunyuan","hy3d","3d"))), None)

def comfy_hunyuan3d(image, out_glb):
    """REAL GPU op — Hunyuan3D-v2 image→mesh through the verified ComfyUI conduit. Gated: ckpt + GPU."""
    import comfy as cf
    ckpt = _hunyuan_ckpt()
    if not ckpt:
        raise NotImplementedError("hunyuan3d checkpoint not installed (ComfyUI/models/checkpoints) — flux only")
    os.makedirs(COMFY_INPUT, exist_ok=True)
    name = "pd3d_" + os.path.basename(image); shutil.copy(image, os.path.join(COMFY_INPUT, name))
    wf = {  # the grounded 9-node Hunyuan3D-v2 image→mesh graph (schemas from /object_info)
      "ckpt": {"class_type":"ImageOnlyCheckpointLoader","inputs":{"ckpt_name":ckpt}},
      "img":  {"class_type":"LoadImage","inputs":{"image":name}},
      "cve":  {"class_type":"CLIPVisionEncode","inputs":{"clip_vision":["ckpt",1],"image":["img",0],"crop":"center"}},
      "cond": {"class_type":"Hunyuan3Dv2Conditioning","inputs":{"clip_vision_output":["cve",0]}},
      "lat":  {"class_type":"EmptyLatentHunyuan3Dv2","inputs":{"resolution":3072,"batch_size":1}},
      "samp": {"class_type":"KSampler","inputs":{"model":["ckpt",0],"seed":0,"steps":30,"cfg":5.0,
               "sampler_name":"euler","scheduler":"normal","positive":["cond",0],"negative":["cond",1],
               "latent_image":["lat",0],"denoise":1.0}},
      "vox":  {"class_type":"VAEDecodeHunyuan3D","inputs":{"samples":["samp",0],"vae":["ckpt",2],
               "num_chunks":8000,"octree_resolution":256}},
      "mesh": {"class_type":"VoxelToMeshBasic","inputs":{"voxel":["vox",0],"threshold":0.6}},
      "save": {"class_type":"SaveGLB","inputs":{"mesh":["mesh",0],"filename_prefix":"pd3d"}},
    }
    r = cf.submit(wf, timeout=600)
    if not r.get("ok"): raise RuntimeError(f"hunyuan3d failed: {r.get('error') or r.get('status')}")
    for node_out in r.get("outputs",{}).values():          # find the SaveGLB file ref + fetch
        for key in ("3d","gltf","glb","meshes","result"):
            if node_out.get(key): cf.fetch(node_out[key][0], out_glb); return out_glb
    raise RuntimeError("hunyuan3d: no mesh output in history")

def _pixal_up():
    try: urllib.request.urlopen(PIXAL3D_URL + "/config", timeout=2); return True
    except Exception: return False

def pixal3d_gen(image, out_glb):
    """PRIMARY image→3D — Pixal3D (TRELLIS) via its gradio API. Gated: app running + GPU.
    Pipeline: /preprocess → generate_3d(image, seed, resolution) → extract_glb_api(state, decimation, tex)."""
    if not _pixal_up():
        raise NotImplementedError("Pixal3D not running — start: /home/tom/models/Pixal3D/start (needs a free GPU)")
    try:
        from gradio_client import Client, handle_file
    except Exception:
        raise NotImplementedError("gradio_client missing — wire ready, dep absent (use Pixal3D env or pip install)")
    c = Client(PIXAL3D_URL)
    pre   = c.predict(handle_file(image), api_name="/preprocess")
    state = c.predict(pre, 0, 512, api_name="/generate_3d")
    res   = c.predict(state, 50000, 1024, api_name="/extract_glb_api")
    src = res["path"] if isinstance(res, dict) else (res[0] if isinstance(res, (list, tuple)) else res)
    shutil.copy(src, out_glb); return out_glb

def gpu_gen(image, out):                                   # try Pixal3D first, Hunyuan3D fallback
    reasons = []
    for op in (pixal3d_gen, comfy_hunyuan3d):
        try: return op(image, out)
        except NotImplementedError as e: reasons.append(str(e))
    raise NotImplementedError(" ; ".join(reasons) or "no image→3D backend")

def img2glb(image):                                       # the GPU doll: cache → fit? run : defer
    os.makedirs(CACHE, exist_ok=True)
    h = io_hash(cid(image), "hunyuan3dv2")
    out = f"{CACHE}/{h}.glb"
    if os.path.exists(out):
        log("CACHE", f"hit {h} ({os.path.basename(image)})")
        return {"status":"cached", "hash":h, "glb":out, "embedded":{"layer":"image","path":image,"cid":h}}
    free = max(gpu_free_gb() or [0])
    if free >= NEED_GB:
        try:
            gpu_gen(image, out); log("GPU", f"gen {h}")           # Pixal3D → Hunyuan3D fallback
            return {"status":"done", "hash":h, "glb":out, "embedded":{"layer":"image","path":image,"cid":h}}
        except NotImplementedError as e:
            return {"status":"blocked", "hash":h, "reason":str(e)}
    enqueue({"hash":h, "image":image, "op":"hunyuan3dv2", "out":out})
    log("DEFER", f"pending {h} — gpu full ({free:.1f}GB<{NEED_GB})")
    return {"status":"pending", "hash":h, "reason":f"gpu full ({free:.1f}GB free < {NEED_GB} needed)"}

def paperdoll(image):                                     # the nested doll: Image ⊂ Img2GLB ⊂ GLB ⊂ ScenePlace
    g = img2glb(image)
    if g["status"] in ("cached","done"):                  # GLB ready → wrap in a ScenePlace doll → spine node
        node = {"id": f"asset_{g['hash']}", "glb": g["glb"], "pos":[0,0,0],
                "rot_euler_deg":[0,0,0], "scale":[1,1,1], "edit_mode":"link"}
        spine = {"_doc": f"paperdoll3d: image→GLB(cached) placed. source={os.path.basename(image)}",
                 "frame":"MetaXR", "nodes":[node]}
        sp = f"{STUDIO}/scene_spine.asset3d.json"; json.dump(spine, open(sp,"w"), indent=1)
        return {"layer":"scene_place", "spine":sp, "embedded":{"layer":"glb", **g}}
    return {"layer":"img2glb(pending)", **g}              # deferred — placement happens after drain

def drain():
    if not os.path.exists(QUEUE): print("queue empty"); return
    free = max(gpu_free_gb() or [0]); jobs = [json.loads(l) for l in open(QUEUE) if l.strip()]
    print(f"drain: {len(jobs)} pending · {free:.1f}GB free (need {NEED_GB})")
    if free < NEED_GB: print("  GPU still full — staying queued (delay-tolerant)"); return
    kept = []
    for j in jobs:
        try: comfy_hunyuan3d(j["image"], j["out"]); log("GPU", f"drained {j['hash']}"); print(f"  ✓ {j['hash']}")
        except Exception as e: kept.append(j); print(f"  … {j['hash']} still blocked: {e}")
    open(QUEUE,"w").write("".join(json.dumps(j)+"\n" for j in kept))

def status():
    cached = [f for f in os.listdir(CACHE) if f.endswith(".glb")] if os.path.isdir(CACHE) else []
    q = [json.loads(l) for l in open(QUEUE)] if os.path.exists(QUEUE) else []
    print(f"cache3d: {len(cached)} cached GLBs · queue: {len(q)} pending · gpu free: {[round(x,1) for x in gpu_free_gb()]}GB")

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "gen":   print(json.dumps(paperdoll(sys.argv[2]), indent=1))
    elif cmd == "drain": drain()
    else: status()
