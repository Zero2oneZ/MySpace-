"""chain_event_render.py — chain event → image (sync) / video (queued) renderer.

The dispatcher answers Tom's question: "can we use a webhook on solana events
to render image and video" with YES. Two trigger paths converge here:

    (a) PUSH:  studio/endpoints/webhook/solana_webhook.py receives a
               Helius/Triton/custom JSON body, normalizes it to a ChainEvent,
               and calls render_one(event).
    (b) PULL:  tail_loop() tails our own program_monitor JSONL sink and
               renders matching events as they land. Useful when ComfyUI is
               on the same machine and you don't need an external webhook.

Output layout per render:
    ~/.cc/chain_renders/<crystal_short>/
        event.json   — the source ChainEvent
        prompt.txt   — the derived prompt (deterministic per category+action)
        image.png    — the rendered image (if ComfyUI was reachable)
        video.mp4    — placeholder; queued for HunyuanVideo via MediaLab (TODO)
        manifest.json — render metadata + crystal_id + dim_pack

Render-side determinism:
    Same (category, action) ALWAYS produces the same prompt template.
    The signature is mixed into the seed so different transactions produce
    different concrete images of the same scene archetype.

Graceful degradation:
    - ComfyUI down → status='queued', manifest still written, work resumable.
    - HunyuanVideo path → always 'queued' for now (MediaLab adapter pending).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core" / "lib"))
sys.path.insert(0, str(REPO / "core" / "lib" / "third_party"))

try:
    from inference_logger import InferenceLogger
    _LOG = InferenceLogger()
except Exception:
    _LOG = None

try:
    from dimension_pack import emit as _dim_emit
except Exception:
    _dim_emit = None

try:
    from comfyui_mcp import ComfyUIMCPConnector  # type: ignore
except Exception:
    ComfyUIMCPConnector = None  # type: ignore


def _submit_prompt_direct(base_url: str, workflow: Dict[str, Any],
                            client_id: str = "mspc-chain-render") -> Tuple[bool, str, str]:
    """Bypass comfyui_mcp.send('submit_workflow', ...) because that path
    requires a named template file. We have an inline graph — POST it
    directly to /prompt and return (ok, prompt_id, error)."""
    import urllib.request
    import urllib.error
    payload = {"prompt": workflow.get("prompt", workflow), "client_id": client_id}
    body = json.dumps(payload).encode()
    req = urllib.request.Request(f"{base_url.rstrip('/')}/prompt",
                                  data=body,
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read().decode())
        pid = resp.get("prompt_id", "")
        node_errs = resp.get("node_errors") or {}
        if node_errs:
            return False, pid, f"node_errors:{json.dumps(node_errs)[:300]}"
        return bool(pid), pid, ""
    except urllib.error.HTTPError as exc:
        return False, "", f"http_{exc.code}:{exc.read().decode()[:300]}"
    except Exception as exc:
        return False, "", f"submit_error:{exc!r}"


def _wait_and_download(base_url: str, prompt_id: str, dest_dir: Path,
                        poll_s: float = 1.0,
                        timeout_s: float = 120.0) -> Tuple[bool, str, str]:
    """Poll /history/<pid> until status=success|error, then GET /view to
    download the first image output. Returns (ok, image_path, error)."""
    import urllib.request
    import urllib.parse
    base = base_url.rstrip("/")
    t0 = time.time()
    while True:
        if time.time() - t0 > timeout_s:
            return False, "", f"timeout:{timeout_s}s"
        try:
            with urllib.request.urlopen(f"{base}/history/{prompt_id}",
                                          timeout=10) as r:
                hist = json.loads(r.read().decode())
        except Exception as exc:
            return False, "", f"history_fetch:{exc!r}"
        if prompt_id in hist:
            node = hist[prompt_id]
            st = (node.get("status") or {}).get("status_str", "")
            if st == "success":
                # find first image in outputs
                for nid, no in (node.get("outputs") or {}).items():
                    for img in (no.get("images") or []):
                        fn = img.get("filename", "")
                        if not fn:
                            continue
                        q = urllib.parse.urlencode({
                            "filename": fn,
                            "subfolder": img.get("subfolder", ""),
                            "type": img.get("type", "output"),
                        })
                        url = f"{base}/view?{q}"
                        dest = dest_dir / "image.png"
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        try:
                            with urllib.request.urlopen(url, timeout=60) as rr, \
                                    dest.open("wb") as f:
                                f.write(rr.read())
                        except Exception as exc:
                            return False, "", f"download:{exc!r}"
                        return True, str(dest), ""
                return False, "", "no_images_in_outputs"
            if st == "error":
                msgs = (node.get("status") or {}).get("messages") or []
                return False, "", f"exec_error:{json.dumps(msgs)[:300]}"
        time.sleep(poll_s)


def _substitute_template(wf: Dict[str, Any], *, prompt: str,
                          negative: str, seed: int,
                          width: int = 0, height: int = 0) -> Dict[str, Any]:
    """Walk a loaded workflow JSON dict and substitute __PROMPT__ / __NEG__ /
    __SEED__ / __WIDTH__ / __HEIGHT__ placeholders in inputs. Idempotent;
    returns the same dict mutated in-place + returned for chaining."""
    nodes = wf.get("prompt") or wf
    if not isinstance(nodes, dict):
        return wf
    for nid, node in nodes.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs") or {}
        for k, v in list(inputs.items()):
            if isinstance(v, str):
                if "__PROMPT__" in v:
                    inputs[k] = v.replace("__PROMPT__", prompt)
                elif "__NEG__" in v:
                    inputs[k] = v.replace("__NEG__", negative)
            elif isinstance(v, int):
                if k == "seed" and v == 0:
                    inputs[k] = seed
        # common seed key replacement (covers KSampler 'seed' + RandomNoise 'noise_seed')
        for sk in ("seed", "noise_seed"):
            if sk in inputs and inputs[sk] in (0, "__SEED__"):
                inputs[sk] = seed
        if width and inputs.get("width") in (0, "__WIDTH__"):
            inputs["width"] = width
        if height and inputs.get("height") in (0, "__HEIGHT__"):
            inputs["height"] = height
    return wf

OUT_ROOT = Path(os.path.expanduser("~/.cc/chain_renders"))
EVENT_ROOT = Path(os.path.expanduser("~/.cc/program_events"))


# ── prompt templates per (category, action) — deterministic by design ──

PROMPT_TEMPLATES: Dict[Tuple[str, str], str] = {
    # (category, action) → prompt template
    ("MEMECOIN_LAUNCHPAD", "create"): (
        "explosive emergence, golden vortex of particles spiraling outward, "
        "neon green crystalline core, abstract birth of a memecoin, "
        "dramatic volumetric lighting, ultra-detailed, cinematic, 8k"
    ),
    ("MEMECOIN_LAUNCHPAD", "buy"): (
        "rising tide of liquid amber, ascending arrows in fractal geometry, "
        "warm golden glow against deep purple void, abstract pump motion, "
        "ultra-detailed, cinematic, 8k"
    ),
    ("MEMECOIN_LAUNCHPAD", "sell"): (
        "cascading sapphire fragments falling through midnight sky, "
        "downward fractal motion, cold blue palette, abstract dump motion, "
        "ultra-detailed, cinematic, 8k"
    ),
    ("DEX", "buy"): (
        "vortex of cyan liquid currents converging, two streams meeting "
        "in glowing rapids, dynamic flow lines, abstract swap motion, "
        "ultra-detailed, cinematic, 8k"
    ),
    ("DEX", "sell"): (
        "vortex of crimson currents diverging, two streams separating "
        "into vapor trails, abstract reversal motion, "
        "ultra-detailed, cinematic, 8k"
    ),
    ("DEX", "swap"): (
        "twin spirals interlocking in mirror symmetry, neon teal and "
        "magenta currents, abstract exchange motion, 8k"
    ),
    ("DEX_AGGREGATOR", "other"): (
        "branching network of luminous pathways, fractal route mesh, "
        "rays of light splitting and recombining, ultra-detailed, 8k"
    ),
    ("DEX_CLMM", "other"): (
        "concentrated bands of color in a tight spectrum, glowing "
        "price-range ribbons, abstract liquidity geometry, 8k"
    ),
    ("PERPS", "order_place"): (
        "geometric grid lattice expanding into 3D space, neon orderbook, "
        "abstract leverage architecture, dark cyberpunk palette, 8k"
    ),
    ("LENDING", "borrow"): (
        "interlocking gears of liquid metal, weight and counterweight, "
        "abstract leverage motion, brass and copper palette, 8k"
    ),
    ("LENDING", "deposit"): (
        "spiraling silver river flowing into a luminous vault, abstract "
        "savings motion, cool blue palette, ultra-detailed, 8k"
    ),
    ("NFT_MARKETPLACE", "other"): (
        "crystalline gallery of floating frames, prismatic reflections, "
        "abstract collectible motion, dreamlike, 8k"
    ),
    ("CASINO", "other"): (
        "kaleidoscopic prism wheel spinning, fractal reflections of luck, "
        "neon rainbow palette against velvet black, abstract gambling motion, "
        "ultra-detailed, cinematic, 8k"
    ),
    ("MEV", "other"): (
        "ghostly arbitrage filaments threading through dark transactions, "
        "shadow currents extracting glow, abstract MEV motion, 8k"
    ),
    ("LIQUID_STAKING", "other"): (
        "luminous chain of interlocking rings, stable spiral ascending, "
        "abstract staking motion, soft pearl palette, 8k"
    ),
}

DEFAULT_PROMPT = (
    "abstract crystallized transaction signature emerging from "
    "dark blockchain substrate, geometric flow, ultra-detailed, 8k"
)

NEGATIVE_PROMPT = (
    "text, watermark, logo, blurry, lowres, deformed, glitched, oversaturated"
)


@dataclass
class RenderRequest:
    event: Dict[str, Any]
    want_image: bool = True
    want_video: bool = False
    workflow_template: Optional[str] = None
    width: int = 512  # SD1.5 native; override to 1024 for SDXL etc.
    height: int = 512
    sampler_steps: int = 20  # SD1.5 sweet spot
    wait_for_completion: bool = True
    poll_timeout_s: float = 120.0


@dataclass
class RenderResult:
    crystal_id: str
    crystal_short: str
    out_dir: str
    prompt: str
    image_status: str = "skipped"
    image_path: str = ""
    video_status: str = "skipped"
    video_path: str = ""
    error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


# ── prompt derivation ──

def derive_prompt(event: Dict[str, Any]) -> str:
    """(category, action) → archetype prompt. Same input → same prompt."""
    cat = str(event.get("category", "")).upper()
    action = str(event.get("action", "other")).lower()
    key = (cat, action)
    tmpl = PROMPT_TEMPLATES.get(key)
    if tmpl is None:
        # try category-only fallback (action='other')
        tmpl = PROMPT_TEMPLATES.get((cat, "other"))
    if tmpl is None:
        tmpl = DEFAULT_PROMPT
    # Sprinkle minimal event-specific tokens that don't change the archetype
    # but help the diffusion model produce per-event variation:
    sig = str(event.get("signature") or event.get("tx_digest") or "")[:8]
    program_name = event.get("program_name", "")
    parts = [tmpl]
    if program_name:
        parts.append(f"context: {program_name}")
    if sig:
        parts.append(f"sigil_seed: {sig}")
    return " | ".join(parts)


def derive_seed(event: Dict[str, Any]) -> int:
    """Deterministic seed from signature (so same event always renders the
    same concrete image of its archetype)."""
    sig = str(event.get("signature") or event.get("tx_digest") or
              event.get("program_id", "")) + str(event.get("ts", 0))
    digest = hashlib.sha256(sig.encode()).hexdigest()
    return int(digest[:8], 16)  # 32-bit seed for diffusion samplers


# ── inline minimal text-to-image workflow ──
# Uses SDXL Turbo if present (1-step), falls back to whatever the user has.
# Users can swap with their own template via RenderRequest.workflow_template.

DEFAULT_CHECKPOINT = os.environ.get(
    "MSPC_COMFY_CHECKPOINT", "v1-5-pruned-emaonly.safetensors")


def _minimal_t2i_workflow(prompt: str, negative: str, seed: int,
                           width: int, height: int, steps: int) -> Dict[str, Any]:
    """A 5-node minimal text-to-image graph in the format ComfyUI's /prompt
    endpoint expects: {prompt: {<node_id>: {class_type, inputs}}, client_id}.
    Default checkpoint: SD1.5 (v1-5-pruned-emaonly.safetensors) — the model
    actually present in MediaLab's ComfyUI install. Override via
    MSPC_COMFY_CHECKPOINT env or custom workflow_template path."""
    return {
        "prompt": {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": DEFAULT_CHECKPOINT},
            },
            "2": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": prompt, "clip": ["1", 1]},
            },
            "3": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": negative, "clip": ["1", 1]},
            },
            "4": {
                "class_type": "EmptyLatentImage",
                "inputs": {"width": width, "height": height, "batch_size": 1},
            },
            "5": {
                "class_type": "KSampler",
                "inputs": {
                    "model": ["1", 0],
                    "positive": ["2", 0],
                    "negative": ["3", 0],
                    "latent_image": ["4", 0],
                    "seed": seed,
                    "steps": steps,
                    "cfg": 7.0,
                    "sampler_name": "euler",
                    "scheduler": "normal",
                    "denoise": 1.0,
                },
            },
            "6": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["5", 0], "vae": ["1", 2]},
            },
            "7": {
                "class_type": "SaveImage",
                "inputs": {"images": ["6", 0], "filename_prefix": "chain_render"},
            },
        },
    }


def _load_workflow_template(path: str) -> Optional[Dict[str, Any]]:
    p = Path(path).expanduser()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


# ── crystal anchor + dim_pack on the render itself ──

def _anchor_render(event: Dict[str, Any], prompt: str,
                    image_status: str, video_status: str) -> str:
    if _LOG is None:
        return ""
    try:
        payload = json.dumps({
            "program_id": event.get("program_id"),
            "category": event.get("category"),
            "action": event.get("action"),
            "signature": event.get("signature") or event.get("tx_digest"),
            "image_status": image_status,
            "video_status": video_status,
            "prompt_short": prompt[:160],
        })
        return _LOG.log(
            original_prompt=f"chain_render:{event.get('category','')}:{event.get('action','')}",
            enhanced_prompt=payload,
            output_text=prompt,
            tier="chain_event_render",
            model="comfyui+hunyuan",
            scope=f"render:{event.get('chain','')}",
            source_action="chain_event_render.render_one",
        ) or ""
    except Exception as exc:
        print(f"[render] log anchor failed: {exc!r}", file=sys.stderr)
        return ""


def _attach_dim(event: Dict[str, Any], prompt: str, crystal_id: str) -> Dict:
    if _dim_emit is None:
        return {}
    try:
        pack = _dim_emit({
            "tier": "chain_event_render",
            "model": "comfyui+hunyuan",
            "cost_class": "expensive",  # image+video = real GPU time
            "sub_dag": "INFERENCE",
            "ts": time.time(),
            "category": event.get("category", ""),
            "action": event.get("action", ""),
            "program_id": event.get("program_id", ""),
            "prompt_short": prompt[:160],
            "signature": event.get("signature") or event.get("tx_digest", ""),
            "circle_hint": f"render:{event.get('category','')}:{event.get('action','')}",
        }, crystal_id=crystal_id)
        circle = pack.circle_motif_id
        if circle in ("", "*", None):
            circle = f"render:{event.get('category','')}:{event.get('action','')}"
        return {
            "rgba": pack.rgba,
            "vec64": pack.vector_hex_64,
            "circle": circle,
            "frame60": pack.frame_pack.get(60, 0),
        }
    except Exception:
        return {}


# ── the main entry point ──

def render_one(req: RenderRequest) -> RenderResult:
    event = req.event
    prompt = derive_prompt(event)
    seed = derive_seed(event)
    # crystal first so we can write into a stable directory
    crystal_id = _anchor_render(event, prompt, "pending", "pending")
    crystal_short = (crystal_id or "noanchor_" + str(int(time.time())))[:16]

    out_dir = OUT_ROOT / crystal_short
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "event.json").write_text(json.dumps(event, indent=2,
                                                     default=str))
    (out_dir / "prompt.txt").write_text(prompt)

    result = RenderResult(
        crystal_id=crystal_id,
        crystal_short=crystal_short,
        out_dir=str(out_dir),
        prompt=prompt,
    )

    # ── image (synchronous, ComfyUI, graceful skip) ──
    if req.want_image:
        if ComfyUIMCPConnector is None:
            result.image_status = "skipped"
            result.error = "comfyui_mcp_unimportable"
        else:
            try:
                conn = ComfyUIMCPConnector()
                if not conn.connect():
                    result.image_status = "queued_offline"
                    result.error = "comfy_not_running"
                else:
                    if req.workflow_template:
                        wf = _load_workflow_template(req.workflow_template)
                        if wf is None:
                            wf = _minimal_t2i_workflow(prompt, NEGATIVE_PROMPT,
                                                         seed, req.width,
                                                         req.height,
                                                         req.sampler_steps)
                        else:
                            # custom template — substitute placeholders so
                            # each event gets ITS prompt+seed (otherwise
                            # every render renders the template's frozen
                            # prompt — which is what made every Jupiter tile
                            # look like the original Pump.fun render).
                            _substitute_template(wf, prompt=prompt,
                                                  negative=NEGATIVE_PROMPT,
                                                  seed=seed, width=req.width,
                                                  height=req.height)
                    else:
                        wf = _minimal_t2i_workflow(prompt, NEGATIVE_PROMPT,
                                                     seed, req.width,
                                                     req.height,
                                                     req.sampler_steps)
                    base_url = getattr(conn, "_base_url", "http://localhost:8188")
                    ok, pid, err = _submit_prompt_direct(base_url, wf)
                    if not ok:
                        result.image_status = "error"
                        result.error = err or "submit_failed"
                    else:
                        result.metadata["comfy_prompt_id"] = pid
                        if not req.wait_for_completion:
                            result.image_status = "submitted"
                        else:
                            ok2, img_path, derr = _wait_and_download(
                                base_url, pid, out_dir,
                                timeout_s=req.poll_timeout_s)
                            if ok2:
                                result.image_status = "rendered"
                                result.image_path = img_path
                            else:
                                result.image_status = "submitted"
                                result.error = derr
            except Exception as exc:
                result.image_status = "error"
                result.error = repr(exc)[:200]

    # ── video (queued; MediaLab HunyuanVideo adapter not yet wired) ──
    if req.want_video:
        # Write a queue file the MediaLab worker can pick up later.
        queue_path = Path(os.path.expanduser("~/.cc/chain_renders/_video_queue.jsonl"))
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        queue_entry = {
            "ts": time.time(),
            "crystal_short": crystal_short,
            "out_dir": str(out_dir),
            "prompt": prompt,
            "seed": seed,
            "duration_s": 5,
            "model": "hunyuan-video",
            "source_event": event,
        }
        with queue_path.open("a") as f:
            f.write(json.dumps(queue_entry, default=str) + "\n")
        result.video_status = "queued"
        result.video_path = str(queue_path)

    # ── manifest ──
    dim = _attach_dim(event, prompt, crystal_id)
    manifest = {
        "crystal_id": crystal_id,
        "crystal_short": crystal_short,
        "prompt": prompt,
        "seed": seed,
        "event_summary": {k: event.get(k) for k in
                            ("chain", "program_id", "program_short",
                             "program_name", "category", "action",
                             "signature", "tx_digest", "ts")},
        "image": {"status": result.image_status, "path": result.image_path,
                    "error": result.error,
                    "comfy_prompt_id": result.metadata.get("comfy_prompt_id", "")},
        "video": {"status": result.video_status,
                    "queue_path": result.video_path},
        "dim": dim,
        "rendered_at": time.time(),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2,
                                                       default=str))
    result.metadata["manifest"] = manifest
    return result


# ── tail mode: watch the program_monitor sink ──

def _filter_match(event: Dict, allow_cats: List[str],
                   allow_actions: List[str]) -> bool:
    if allow_cats and event.get("category", "") not in allow_cats:
        return False
    if allow_actions and event.get("action", "") not in allow_actions:
        return False
    return True


def tail_loop(allow_cats: List[str] = None,
              allow_actions: List[str] = None,
              want_image: bool = True,
              want_video: bool = False,
              poll_s: float = 1.0,
              max_renders: int = 0,
              verbose: bool = False) -> int:
    """Tail every per-program JSONL file under EVENT_ROOT; on each new
    matching event, fire render_one. Returns count rendered."""
    if not EVENT_ROOT.exists():
        print("[render] no event root; nothing to tail", file=sys.stderr)
        return 0
    offsets: Dict[Path, int] = {}
    # Seed offsets to current EOF so we only render NEW events.
    for jf in EVENT_ROOT.glob("**/*.jsonl"):
        offsets[jf] = jf.stat().st_size
    rendered = 0
    try:
        while True:
            for jf in list(EVENT_ROOT.glob("**/*.jsonl")):
                start = offsets.get(jf, 0)
                cur_size = jf.stat().st_size
                if cur_size <= start:
                    continue
                with jf.open() as f:
                    f.seek(start)
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            ev = json.loads(line)
                        except Exception:
                            continue
                        if not _filter_match(ev, allow_cats or [],
                                              allow_actions or []):
                            continue
                        req = RenderRequest(event=ev, want_image=want_image,
                                              want_video=want_video)
                        res = render_one(req)
                        rendered += 1
                        if verbose:
                            print(f"[render] {res.crystal_short} "
                                  f"img={res.image_status} "
                                  f"vid={res.video_status} "
                                  f"prompt={res.prompt[:50]}",
                                  file=sys.stderr)
                        if max_renders and rendered >= max_renders:
                            return rendered
                offsets[jf] = cur_size
            time.sleep(poll_s)
    except KeyboardInterrupt:
        return rendered


# ── CLI ──

def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description="chain_event_render")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_one = sub.add_parser("one", help="render one event (from --event-file or stdin)")
    p_one.add_argument("--event-file", default="", help="path to JSON event")
    p_one.add_argument("--image", action="store_true", default=True)
    p_one.add_argument("--no-image", dest="image", action="store_false")
    p_one.add_argument("--video", action="store_true", default=False)
    p_one.add_argument("--workflow", default="", help="ComfyUI workflow template path")
    p_one.add_argument("--width", type=int, default=1024)
    p_one.add_argument("--height", type=int, default=1024)
    p_one.add_argument("--steps", type=int, default=24)

    p_tail = sub.add_parser("tail", help="tail program_monitor sink + render new events")
    p_tail.add_argument("--cat", action="append", default=[], help="allow category (repeatable)")
    p_tail.add_argument("--action", action="append", default=[], help="allow action (repeatable)")
    p_tail.add_argument("--video", action="store_true", default=False)
    p_tail.add_argument("--poll", type=float, default=1.0)
    p_tail.add_argument("--max", type=int, default=0)
    p_tail.add_argument("--verbose", action="store_true")

    p_prompt = sub.add_parser("prompt", help="show the prompt that would render for a category+action")
    p_prompt.add_argument("--cat", default="DEX")
    p_prompt.add_argument("--action", default="buy")

    p_sample = sub.add_parser("sample", help="render N synthetic events covering the template matrix")
    p_sample.add_argument("--n", type=int, default=4)
    p_sample.add_argument("--image", action="store_true", default=True)
    p_sample.add_argument("--no-image", dest="image", action="store_false")

    args = ap.parse_args(argv)

    if args.cmd == "prompt":
        ev = {"category": args.cat.upper(), "action": args.action.lower(),
              "program_name": "(sample)", "signature": "deadbeef" * 8}
        print(derive_prompt(ev))
        return 0

    if args.cmd == "one":
        if args.event_file:
            event = json.loads(Path(args.event_file).read_text())
        else:
            event = json.loads(sys.stdin.read())
        req = RenderRequest(event=event, want_image=args.image,
                              want_video=args.video,
                              workflow_template=args.workflow or None,
                              width=args.width, height=args.height,
                              sampler_steps=args.steps)
        res = render_one(req)
        print(json.dumps(asdict(res), indent=2, default=str))
        return 0 if res.error == "" else 1

    if args.cmd == "tail":
        print(f"[render] tailing {EVENT_ROOT} ...", file=sys.stderr)
        n = tail_loop(allow_cats=[c.upper() for c in args.cat],
                       allow_actions=[a.lower() for a in args.action],
                       want_image=True, want_video=args.video,
                       poll_s=args.poll, max_renders=args.max,
                       verbose=args.verbose)
        print(f"[render] rendered {n} events")
        return 0

    if args.cmd == "sample":
        # pick a representative slice of the template matrix
        samples = [
            {"category": "MEMECOIN_LAUNCHPAD", "action": "create",
             "program_name": "Pump.fun", "signature": "samplecr8" * 6,
             "chain": "solana", "ts": time.time()},
            {"category": "DEX", "action": "buy",
             "program_name": "Jupiter v6", "signature": "samplebuy" * 6,
             "chain": "solana", "ts": time.time() + 1},
            {"category": "CASINO", "action": "other",
             "program_name": "Gamba V2", "signature": "samplegmb" * 6,
             "chain": "solana", "ts": time.time() + 2},
            {"category": "MEV", "action": "other",
             "program_name": "Jito Tip Distribution", "signature": "sampleme" * 6,
             "chain": "solana", "ts": time.time() + 3},
        ][: args.n]
        for ev in samples:
            res = render_one(RenderRequest(event=ev, want_image=args.image,
                                            want_video=False))
            print(f"  {res.crystal_short} {ev['category']:20s} {ev['action']:8s} "
                  f"img={res.image_status:14s} prompt='{res.prompt[:60]}'")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
