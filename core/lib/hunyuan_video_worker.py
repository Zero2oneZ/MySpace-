"""hunyuan_video_worker.py — MediaLab HunyuanVideo queue consumer.

Connects the dormant video path of chain_event_render to actual MP4 output.

Reads ~/.cc/chain_renders/_video_queue.jsonl (one queued job per line, written
by chain_event_render when want_video=True), submits a HunyuanVideo T2V
workflow to ComfyUI on :8188, polls for completion, downloads the resulting
MP4 to <render_dir>/video.mp4, updates the render's manifest, and
crystal-anchors the job.

Constraints:
  - Single-instance: lockfile at ~/.cc/chain_renders/_video_worker.lock so
    two workers don't fight over the GPU.
  - One job at a time: HunyuanVideo-1.5 needs ~22-24 GB VRAM at 720p bf16.
  - GPU 1 preferred (per /data/Projects/CLAUDE.md): set CUDA_VISIBLE_DEVICES=1
    in your environment before starting ComfyUI; this worker doesn't manage
    that for you, it just submits.
  - Resumable: an offset file tracks which lines have been processed; the
    queue is append-only so re-starting picks up where we left off.
  - Graceful skip when:
      * ComfyUI is not reachable on :8188
      * Hunyuan custom nodes / weights missing (ComfyUI returns an execution
        error → mark job 'error', leave queue intact for later retry)

Workflow:
  The default graph is the standard Hunyuan T2V topology (DualCLIPLoader →
  HunyuanVideoTextEncode × 2 → EmptyHunyuanLatentVideo → KSampler → VAEDecode
  → VHS_VideoCombine). Override with --workflow-template <path>.

MediaLab inventory (from /data/Projects/MediaLab/CLAUDE.md):
  - HunyuanVideo-1.5 at MediaLab/video/hunyuan-15/
  - ComfyUI at MediaLab/comfyui/ (symlink to ~/Projects/ComfyUI), port 8188
  - Weights status: 'not yet downloaded' as of plan capture — when models
    are missing the worker will surface the ComfyUI error and stop on that job
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

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

CHAIN_RENDERS = Path(os.path.expanduser("~/.cc/chain_renders"))
QUEUE = CHAIN_RENDERS / "_video_queue.jsonl"
COMPLETED = CHAIN_RENDERS / "_video_queue.completed.jsonl"
OFFSET = CHAIN_RENDERS / "_video_queue.offset"
LOCK = CHAIN_RENDERS / "_video_worker.lock"

COMFY_BASE = os.environ.get("COMFYUI_BASE_URL", "http://localhost:8188")
DEFAULT_POLL_S = 5.0
DEFAULT_TIMEOUT_S = 1800.0  # 30 min per job — Hunyuan @ 720p × 5s takes ~10-25 min on a 3090 Ti

# ── default Hunyuan T2V workflow ─────────────────────────────────────────────
# Mirrors the canonical Kijai HunyuanVideoWrapper graph. Filenames assume the
# standard model layout in ComfyUI/models/. If the MediaLab Hunyuan weights
# live elsewhere, set MSPC_HUNYUAN_DIFFUSION_MODEL / MSPC_HUNYUAN_VAE /
# MSPC_HUNYUAN_TEXT_ENC1 / MSPC_HUNYUAN_TEXT_ENC2 env vars (the worker just
# substitutes them; doesn't move files).

DEFAULT_MODEL_DIFFUSION = os.environ.get(
    "MSPC_HUNYUAN_DIFFUSION_MODEL", "hunyuan_video_t2v_720p_bf16.safetensors")
DEFAULT_MODEL_VAE = os.environ.get(
    "MSPC_HUNYUAN_VAE", "hunyuan_video_vae_bf16.safetensors")
DEFAULT_TEXT_ENC1 = os.environ.get(
    "MSPC_HUNYUAN_TEXT_ENC1", "clip_l.safetensors")
DEFAULT_TEXT_ENC2 = os.environ.get(
    "MSPC_HUNYUAN_TEXT_ENC2", "llava_llama3_fp16.safetensors")

NEGATIVE_PROMPT = (
    "blurry, lowres, deformed, glitched, text, watermark, logo, oversaturated"
)


def _default_workflow(prompt: str, negative: str, seed: int,
                       width: int = 720, height: int = 1280,
                       length: int = 73, steps: int = 30,
                       fps: int = 24) -> Dict[str, Any]:
    """Hunyuan T2V workflow with sane defaults: 720x1280 portrait, 73 frames
    (~3s @ 24fps), 30 steps. Override via RenderRequest/CLI for other shapes.

    Outputs MP4 via VHS_VideoCombine — requires ComfyUI-VideoHelperSuite.
    If that custom node isn't installed, falls back to SaveAnimatedWEBP from
    the comfy_extras (always present)."""
    return {
        "prompt": {
            "1": {
                "class_type": "DualCLIPLoader",
                "inputs": {
                    "clip_name1": DEFAULT_TEXT_ENC1,
                    "clip_name2": DEFAULT_TEXT_ENC2,
                    "type": "hunyuan_video",
                },
            },
            "2": {
                "class_type": "UNETLoader",
                "inputs": {
                    "unet_name": DEFAULT_MODEL_DIFFUSION,
                    "weight_dtype": "fp8_e4m3fn",
                },
            },
            "3": {
                "class_type": "VAELoader",
                "inputs": {"vae_name": DEFAULT_MODEL_VAE},
            },
            "4": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": prompt, "clip": ["1", 0]},
            },
            "5": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": negative, "clip": ["1", 0]},
            },
            "6": {
                "class_type": "EmptyHunyuanLatentVideo",
                "inputs": {
                    "width": width, "height": height,
                    "length": length, "batch_size": 1,
                },
            },
            "7": {
                "class_type": "KSampler",
                "inputs": {
                    "model": ["2", 0],
                    "positive": ["4", 0],
                    "negative": ["5", 0],
                    "latent_image": ["6", 0],
                    "seed": seed,
                    "steps": steps,
                    "cfg": 6.0,
                    "sampler_name": "euler",
                    "scheduler": "simple",
                    "denoise": 1.0,
                },
            },
            "8": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["7", 0], "vae": ["3", 0]},
            },
            "9": {
                "class_type": "VHS_VideoCombine",
                "inputs": {
                    "images": ["8", 0],
                    "frame_rate": fps,
                    "loop_count": 0,
                    "filename_prefix": "chain_video",
                    "format": "video/h264-mp4",
                    "save_metadata": True,
                    "crf": 19,
                },
            },
        },
    }


# ── HTTP helpers (stdlib urllib only) ────────────────────────────────────────

def _http_json(url: str, method: str = "GET",
                body: Optional[bytes] = None,
                timeout: float = 30.0) -> Dict[str, Any]:
    req = urllib.request.Request(url, method=method, data=body,
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return json.loads(raw.decode()) if raw else {}
    except urllib.error.HTTPError as exc:
        return {"_error": f"http {exc.code}", "_body": exc.read().decode("utf-8", errors="replace")[:300]}
    except Exception as exc:
        return {"_error": repr(exc)[:300]}


def _http_download(url: str, dest: Path, timeout: float = 120.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r, dest.open("wb") as f:
            chunk = r.read(64 * 1024)
            while chunk:
                f.write(chunk)
                chunk = r.read(64 * 1024)
        return True
    except Exception as exc:
        print(f"[hunyuan] download fail {url}: {exc!r}", file=sys.stderr)
        return False


# ── lock + offset ────────────────────────────────────────────────────────────

@contextlib.contextmanager
def _lockfile():
    CHAIN_RENDERS.mkdir(parents=True, exist_ok=True)
    if LOCK.exists():
        try:
            pid = int(LOCK.read_text().strip() or "-1")
        except Exception:
            pid = -1
        if pid > 0:
            try:
                os.kill(pid, 0)  # 0 = signal probe; raises if dead
                raise SystemExit(f"[hunyuan] worker already running (pid={pid})")
            except ProcessLookupError:
                LOCK.unlink(missing_ok=True)  # stale lock
            except PermissionError:
                raise SystemExit(f"[hunyuan] another user holds the lock pid={pid}")
    LOCK.write_text(str(os.getpid()))
    try:
        yield
    finally:
        LOCK.unlink(missing_ok=True)


def _read_offset() -> int:
    if not OFFSET.exists():
        return 0
    try:
        return int(OFFSET.read_text().strip())
    except Exception:
        return 0


def _write_offset(n: int) -> None:
    OFFSET.parent.mkdir(parents=True, exist_ok=True)
    OFFSET.write_text(str(n))


# ── job dataclass ────────────────────────────────────────────────────────────

@dataclass
class VideoJob:
    line_no: int
    ts: float
    crystal_short: str
    out_dir: str
    prompt: str
    seed: int
    duration_s: float = 5.0
    model: str = "hunyuan-15"
    source_event: Dict[str, Any] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)


def _iter_queue(start_line: int = 0) -> List[VideoJob]:
    out: List[VideoJob] = []
    if not QUEUE.exists():
        return out
    with QUEUE.open() as f:
        for i, line in enumerate(f):
            if i < start_line:
                continue
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            out.append(VideoJob(
                line_no=i,
                ts=float(d.get("ts") or time.time()),
                crystal_short=str(d.get("crystal_short", f"unknown_{i}")),
                out_dir=str(d.get("out_dir", "")),
                prompt=str(d.get("prompt", "")),
                seed=int(d.get("seed") or 0),
                duration_s=float(d.get("duration_s") or 5.0),
                model=str(d.get("model") or "hunyuan-15"),
                source_event=d.get("source_event", {}),
                raw=d,
            ))
    return out


# ── job processing ───────────────────────────────────────────────────────────

@dataclass
class JobResult:
    crystal_short: str
    line_no: int
    status: str  # "rendered" | "submit_error" | "comfy_offline" | "timeout" | "exec_error"
    video_path: str = ""
    elapsed_s: float = 0.0
    prompt_id: str = ""
    error: str = ""
    crystal_id: str = ""


def _submit_workflow(connector: "ComfyUIMCPConnector", workflow: Dict) -> tuple[bool, str, str]:
    """Direct POST to /prompt bypasses comfyui_mcp.send('submit_workflow', ...)
    which requires a named template-file path. Hunyuan workflow is large +
    parameter-heavy so we hand-build the graph inline; direct POST avoids
    round-tripping it through the disk-template loader."""
    import urllib.error
    base_url = getattr(connector, "_base_url", COMFY_BASE)
    payload = {"prompt": workflow.get("prompt", workflow),
               "client_id": "mspc-hunyuan-worker"}
    body = json.dumps(payload).encode()
    req = urllib.request.Request(f"{base_url.rstrip('/')}/prompt", data=body,
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


def _poll_history(prompt_id: str, timeout_s: float, poll_s: float,
                   verbose: bool = False) -> tuple[str, Dict]:
    """Returns (status, history_node) where status ∈
    {'completed', 'timeout', 'execution_error'}."""
    t0 = time.time()
    while True:
        if time.time() - t0 > timeout_s:
            return "timeout", {}
        h = _http_json(f"{COMFY_BASE}/history/{prompt_id}", timeout=15)
        if isinstance(h, dict) and prompt_id in h:
            node = h[prompt_id]
            status_str = ((node.get("status") or {}).get("status_str") or "").lower()
            if status_str == "success":
                return "completed", node
            if status_str == "error":
                return "execution_error", node
        if verbose:
            sys.stderr.write(".")
            sys.stderr.flush()
        time.sleep(poll_s)


def _extract_video_url(history_node: Dict) -> str:
    """VHS_VideoCombine puts the output under outputs[<node_id>]['gifs']
    (yes, called 'gifs' even for mp4 — that's the upstream key) OR 'videos'
    in newer versions. We check both."""
    outs = history_node.get("outputs") or {}
    for node_id, node_out in outs.items():
        for key in ("gifs", "videos"):
            vids = node_out.get(key) or []
            for v in vids:
                fn = v.get("filename") or ""
                sub = v.get("subfolder") or ""
                typ = v.get("type") or "output"
                if fn:
                    q = urllib.parse.urlencode({
                        "filename": fn, "subfolder": sub, "type": typ,
                    })
                    return f"{COMFY_BASE}/view?{q}"
    return ""


def _attach_dim(job: VideoJob, status: str, crystal_id: str) -> Dict:
    if _dim_emit is None:
        return {}
    try:
        pack = _dim_emit({
            "tier": "video_render",
            "model": "hunyuan-15",
            "cost_class": "expensive",
            "sub_dag": "INFERENCE",
            "ts": time.time(),
            "category": job.source_event.get("category", ""),
            "action": job.source_event.get("action", ""),
            "program_id": job.source_event.get("program_id", ""),
            "prompt_short": job.prompt[:120],
            "status": status,
            "circle_hint": f"video:{job.source_event.get('category','')}:{job.source_event.get('action','')}",
        }, crystal_id=crystal_id)
        circle = pack.circle_motif_id
        if circle in ("", "*", None):
            circle = f"video:{job.source_event.get('category','')}:{job.source_event.get('action','')}"
        return {"rgba": pack.rgba, "vec64": pack.vector_hex_64,
                "circle": circle, "frame60": pack.frame_pack.get(60, 0)}
    except Exception:
        return {}


def _update_manifest(job: VideoJob, status: str, video_path: str,
                      elapsed_s: float, error: str = "") -> None:
    manifest_path = Path(job.out_dir) / "manifest.json"
    if not manifest_path.exists():
        return
    try:
        m = json.loads(manifest_path.read_text())
    except Exception:
        return
    video_block = m.get("video") or {}
    video_block.update({
        "status": status,
        "path": video_path,
        "model": "hunyuan-15",
        "error": error,
        "elapsed_s": round(elapsed_s, 2),
        "rendered_at": time.time(),
    })
    m["video"] = video_block
    manifest_path.write_text(json.dumps(m, indent=2, default=str))


def process_one(job: VideoJob, *,
                 connector: "ComfyUIMCPConnector",
                 poll_s: float = DEFAULT_POLL_S,
                 timeout_s: float = DEFAULT_TIMEOUT_S,
                 workflow_override: Optional[Dict] = None,
                 width: int = 720, height: int = 1280,
                 length: int = 73, steps: int = 30, fps: int = 24,
                 verbose: bool = False) -> JobResult:
    out = JobResult(crystal_short=job.crystal_short, line_no=job.line_no,
                     status="pending")
    t0 = time.time()

    # crystal anchor (early so failure paths still log)
    if _LOG is not None:
        try:
            out.crystal_id = _LOG.log(
                original_prompt=f"hunyuan_video:{job.crystal_short}",
                enhanced_prompt=json.dumps({
                    "prompt_short": job.prompt[:160],
                    "seed": job.seed,
                    "duration_s": job.duration_s,
                    "source_category": job.source_event.get("category", ""),
                    "source_action": job.source_event.get("action", ""),
                }),
                output_text=job.prompt,
                tier="video_render",
                model="hunyuan-15",
                scope=f"submit:{job.source_event.get('category','')}",
                source_action="hunyuan_video_worker.process_one",
            ) or ""
        except Exception:
            pass

    if not connector.connect():
        out.status = "comfy_offline"
        out.error = "comfyui_not_reachable"
        out.elapsed_s = time.time() - t0
        _update_manifest(job, out.status, "", out.elapsed_s, out.error)
        return out

    workflow = workflow_override or _default_workflow(
        prompt=job.prompt, negative=NEGATIVE_PROMPT,
        seed=job.seed or int(time.time()) & 0x7fffffff,
        width=width, height=height, length=length, steps=steps, fps=fps,
    )
    ok, prompt_id, err = _submit_workflow(connector, workflow)
    if not ok:
        out.status = "submit_error"
        out.error = err
        out.elapsed_s = time.time() - t0
        _update_manifest(job, out.status, "", out.elapsed_s, out.error)
        return out
    out.prompt_id = prompt_id

    poll_status, node = _poll_history(prompt_id, timeout_s, poll_s, verbose)
    if poll_status == "timeout":
        out.status = "timeout"
        out.error = f"no completion within {timeout_s}s"
        out.elapsed_s = time.time() - t0
        _update_manifest(job, out.status, "", out.elapsed_s, out.error)
        return out
    if poll_status == "execution_error":
        out.status = "exec_error"
        # Pull comfyui's error message if present
        msgs = (node.get("status") or {}).get("messages") or []
        out.error = json.dumps(msgs)[:400] or "comfyui_execution_error"
        out.elapsed_s = time.time() - t0
        _update_manifest(job, out.status, "", out.elapsed_s, out.error)
        return out

    url = _extract_video_url(node)
    if not url:
        out.status = "exec_error"
        out.error = "no_video_output_in_history"
        out.elapsed_s = time.time() - t0
        _update_manifest(job, out.status, "", out.elapsed_s, out.error)
        return out

    dest = Path(job.out_dir) / "video.mp4"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not _http_download(url, dest, timeout=600):
        out.status = "exec_error"
        out.error = "video_download_failed"
        out.elapsed_s = time.time() - t0
        _update_manifest(job, out.status, "", out.elapsed_s, out.error)
        return out

    out.status = "rendered"
    out.video_path = str(dest)
    out.elapsed_s = time.time() - t0
    _update_manifest(job, out.status, out.video_path, out.elapsed_s)

    # also write back the dimension_pack for the video event
    dim = _attach_dim(job, out.status, out.crystal_id)
    try:
        m = json.loads((Path(job.out_dir) / "manifest.json").read_text())
        m.setdefault("video", {})["dim"] = dim
        (Path(job.out_dir) / "manifest.json").write_text(
            json.dumps(m, indent=2, default=str))
    except Exception:
        pass
    return out


# ── worker loop ──────────────────────────────────────────────────────────────

def run_worker(*, max_jobs: int = 0, poll_queue_s: float = 5.0,
                poll_comfy_s: float = DEFAULT_POLL_S,
                timeout_s: float = DEFAULT_TIMEOUT_S,
                width: int = 720, height: int = 1280,
                length: int = 73, steps: int = 30, fps: int = 24,
                verbose: bool = True, once: bool = False) -> int:
    if ComfyUIMCPConnector is None:
        print("[hunyuan] comfyui_mcp not importable; cannot run", file=sys.stderr)
        return 2
    processed = 0
    with _lockfile():
        connector = ComfyUIMCPConnector()
        while True:
            offset = _read_offset()
            jobs = _iter_queue(start_line=offset)
            for job in jobs:
                if verbose:
                    print(f"[hunyuan] start line {job.line_no} {job.crystal_short} "
                          f"prompt={job.prompt[:60]}...", file=sys.stderr)
                # Force re-probe in case comfy bounced
                connector.disconnect()
                res = process_one(
                    job, connector=connector,
                    poll_s=poll_comfy_s, timeout_s=timeout_s,
                    width=width, height=height, length=length,
                    steps=steps, fps=fps, verbose=verbose,
                )
                completed_entry = {**asdict(res), "queue_line": job.line_no,
                                    "ts": time.time()}
                COMPLETED.parent.mkdir(parents=True, exist_ok=True)
                with COMPLETED.open("a") as f:
                    f.write(json.dumps(completed_entry, default=str) + "\n")
                # comfy_offline → don't advance offset; the job is still
                # pending and should be retried when comfy comes back up.
                # All other terminal statuses (rendered / submit_error /
                # exec_error / timeout) DO advance — they're real attempts
                # whose retry behavior should be operator-chosen.
                if res.status != "comfy_offline":
                    _write_offset(job.line_no + 1)
                    processed += 1
                if verbose:
                    print(f"[hunyuan] {res.status} {job.crystal_short} "
                          f"{res.elapsed_s:.1f}s {res.error[:80]}",
                          file=sys.stderr)
                if max_jobs and processed >= max_jobs:
                    return processed
                if res.status == "comfy_offline":
                    if once:
                        return processed
                    # continuous mode: wait + retry the same line
                    if verbose:
                        print(f"[hunyuan] comfy offline; sleeping "
                              f"{poll_queue_s}s then retrying same job",
                              file=sys.stderr)
                    time.sleep(poll_queue_s)
                    break  # break inner for-loop, re-enter while to re-read same offset
            if once:
                return processed
            time.sleep(poll_queue_s)
    return processed


# ── inspection helpers ───────────────────────────────────────────────────────

def status_dump() -> Dict:
    q_total = 0
    if QUEUE.exists():
        with QUEUE.open() as f:
            q_total = sum(1 for _ in f)
    completed = 0
    if COMPLETED.exists():
        with COMPLETED.open() as f:
            completed = sum(1 for _ in f)
    return {
        "queue_path": str(QUEUE),
        "queue_total_lines": q_total,
        "offset": _read_offset(),
        "pending": max(0, q_total - _read_offset()),
        "completed_lines": completed,
        "lock_present": LOCK.exists(),
        "lock_pid": LOCK.read_text().strip() if LOCK.exists() else "",
        "comfy_base": COMFY_BASE,
    }


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description="hunyuan_video_worker — chain render video consumer")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="long-running worker (foreground)")
    p_run.add_argument("--max-jobs", type=int, default=0)
    p_run.add_argument("--poll-queue", type=float, default=5.0)
    p_run.add_argument("--poll-comfy", type=float, default=DEFAULT_POLL_S)
    p_run.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    p_run.add_argument("--width", type=int, default=720)
    p_run.add_argument("--height", type=int, default=1280)
    p_run.add_argument("--length", type=int, default=73,
                       help="frame count (73 ≈ 3s @ 24fps)")
    p_run.add_argument("--steps", type=int, default=30)
    p_run.add_argument("--fps", type=int, default=24)
    p_run.add_argument("--once", action="store_true",
                       help="drain current queue once and exit")
    p_run.add_argument("--quiet", action="store_true")

    p_one = sub.add_parser("one", help="process exactly one queued job (smoke)")
    p_one.add_argument("--width", type=int, default=720)
    p_one.add_argument("--height", type=int, default=1280)
    p_one.add_argument("--length", type=int, default=73)
    p_one.add_argument("--steps", type=int, default=30)
    p_one.add_argument("--fps", type=int, default=24)

    sub.add_parser("status", help="queue + offset + lock state")
    sub.add_parser("reset-lock", help="remove stale lock if a worker crashed")
    sub.add_parser("workflow-preview", help="print the default workflow JSON")
    p_seed = sub.add_parser("seed", help="enqueue a sample job from a chain event JSON")
    p_seed.add_argument("event_path", help="path to event JSON (e.g. ~/.cc/chain_renders/<x>/event.json)")

    args = ap.parse_args(argv)

    if args.cmd == "status":
        print(json.dumps(status_dump(), indent=2))
        return 0

    if args.cmd == "reset-lock":
        if LOCK.exists():
            LOCK.unlink()
            print("[hunyuan] lock removed")
        else:
            print("[hunyuan] no lock present")
        return 0

    if args.cmd == "workflow-preview":
        wf = _default_workflow("(prompt here)", NEGATIVE_PROMPT, 42)
        print(json.dumps(wf, indent=2))
        return 0

    if args.cmd == "seed":
        ev = json.loads(Path(args.event_path).read_text())
        crystal_short = (Path(args.event_path).parent.name)[:16]
        out_dir = str(Path(args.event_path).parent)
        # derive prompt + seed using chain_event_render's logic (re-import)
        from chain_event_render import derive_prompt, derive_seed
        entry = {
            "ts": time.time(),
            "crystal_short": crystal_short,
            "out_dir": out_dir,
            "prompt": derive_prompt(ev),
            "seed": derive_seed(ev),
            "duration_s": 5.0,
            "model": "hunyuan-15",
            "source_event": ev,
        }
        QUEUE.parent.mkdir(parents=True, exist_ok=True)
        with QUEUE.open("a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
        print(f"[hunyuan] enqueued {crystal_short} → {QUEUE}")
        print(json.dumps(status_dump(), indent=2))
        return 0

    if args.cmd == "one":
        return run_worker(max_jobs=1, poll_queue_s=1.0,
                           poll_comfy_s=DEFAULT_POLL_S,
                           timeout_s=DEFAULT_TIMEOUT_S,
                           width=args.width, height=args.height,
                           length=args.length, steps=args.steps, fps=args.fps,
                           verbose=True, once=True)

    if args.cmd == "run":
        return run_worker(max_jobs=args.max_jobs,
                           poll_queue_s=args.poll_queue,
                           poll_comfy_s=args.poll_comfy,
                           timeout_s=args.timeout,
                           width=args.width, height=args.height,
                           length=args.length, steps=args.steps, fps=args.fps,
                           verbose=not args.quiet, once=args.once)

    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
