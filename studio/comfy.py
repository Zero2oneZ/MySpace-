#!/usr/bin/env python3
"""comfy — the real ComfyUI submission conduit: POST /prompt → poll /history → fetch output.

The reusable GPU-job pipe that the paper-doll's GPU leaves submit through (image-gen, image→3D).
Workflows are ComfyUI API-format dicts {node_id: {class_type, inputs}}. Outputs are fetched via /view.

  comfy.py test     # prove the conduit end-to-end with a no-model EmptyImage→SaveImage job
"""
import json, sys, time, uuid, urllib.request, urllib.parse

COMFY = "http://localhost:8188"

def _post(path, body):
    req = urllib.request.Request(COMFY+path, json.dumps(body).encode(), {"Content-Type":"application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())

def _get(path):
    return json.loads(urllib.request.urlopen(COMFY+path, timeout=30).read())

def submit(workflow, timeout=600, poll=1.5):
    """Queue a workflow, poll till done, return {ok, prompt_id, outputs}."""
    cid = uuid.uuid4().hex
    pid = _post("/prompt", {"prompt": workflow, "client_id": cid}).get("prompt_id")
    if not pid: return {"ok": False, "error": "no prompt_id (validation failed)"}
    waited = 0.0
    while waited < timeout:
        h = _get(f"/history/{pid}")
        if pid in h:
            st = h[pid].get("status", {})
            return {"ok": st.get("status_str") != "error", "prompt_id": pid,
                    "outputs": h[pid].get("outputs", {}), "status": st}
        time.sleep(poll); waited += poll
    return {"ok": False, "prompt_id": pid, "error": "timeout"}

def fetch(out_ref, dest):
    """Download one output file ref {filename, subfolder, type} via /view → dest."""
    q = urllib.parse.urlencode({"filename": out_ref["filename"], "subfolder": out_ref.get("subfolder",""),
                                "type": out_ref.get("type","output")})
    data = urllib.request.urlopen(f"{COMFY}/view?{q}", timeout=120).read()
    open(dest, "wb").write(data); return dest

if __name__ == "__main__" and sys.argv[1:] == ["test"]:
    wf = {"1": {"class_type": "EmptyImage", "inputs": {"width": 128, "height": 128, "batch_size": 1, "color": 8421504}},
          "2": {"class_type": "SaveImage",  "inputs": {"images": ["1", 0], "filename_prefix": "conduit_test"}}}
    r = submit(wf, timeout=60)
    print("submit:", {k: r[k] for k in ("ok","prompt_id","error") if k in r})
    imgs = (r.get("outputs", {}).get("2", {}) or {}).get("images", [])
    if imgs:
        p = fetch(imgs[0], "/tmp/conduit_test.png")
        import os; print(f"CONDUIT OK → fetched {p} ({os.path.getsize(p)} bytes) — /prompt→/history→/view round-trip works")
    else:
        print("no image output:", r.get("status"))
