"""inference.py — default inference shims for every pass in the registry.

Each shim:
  - Takes the source file path (and optional kwargs) as input.
  - Times itself via passes.timing.Timer.
  - Returns a PassResult dict:
        {"ok": bool, "kind": <output_kind>, "value": ...,
         "path": str|None, "duration_ms": float, "instruction": str,
         "pass_id": str, "error": str|None}
  - Falls back to a clear PassUnavailable result when the backing tool
    (rembg, mediapipe, demucs, etc.) isn't installed.

Anything that produces a FILE writes it next to the source as
`<stem>__<pass_id>.<ext>` so we don't need to manage a separate
output dir. The import_pipeline then moves these into pieces.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

# Resolve paths consistently with the rest of the studio.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import paths  # noqa: E402

from . import timing  # noqa: E402


# ─── Helpers ─────────────────────────────────────────────────────────────────
def _ok(pass_id: str, kind: str, *, instruction: str = "",
        value: Any = None, path: str | None = None,
        duration_ms: float = 0.0) -> dict:
    return {
        "ok": True, "kind": kind, "value": value, "path": path,
        "duration_ms": duration_ms, "instruction": instruction,
        "pass_id": pass_id, "error": None,
    }


def _unavailable(pass_id: str, why: str) -> dict:
    return {
        "ok": False, "kind": None, "value": None, "path": None,
        "duration_ms": 0.0, "instruction": "",
        "pass_id": pass_id, "error": f"PassUnavailable: {why}",
    }


def _have(bin_name: str) -> bool:
    return shutil.which(bin_name) is not None


def _have_mod(name: str) -> bool:
    try:
        __import__(name); return True
    except Exception:
        return False


def _sibling(src: Path, pass_id: str, ext: str) -> Path:
    return src.with_name(f"{src.stem}__{pass_id}.{ext.lstrip('.')}")


# ─── Light: thumb + content_hash ────────────────────────────────────────────
def pass_thumb(src: Path, max_side: int = 256) -> dict:
    try:
        from PIL import Image
    except ImportError:
        return _unavailable("thumb", "PIL not installed")
    with timing.Timer("thumb", src) as t:
        out = _sibling(src, "thumb", "png")
        with Image.open(src) as im:
            im = im.convert("RGB")
            w, h = im.size
            s = min(1.0, max_side / max(w, h))
            if s < 1.0:
                im = im.resize((int(w * s), int(h * s)), Image.LANCZOS)
            im.save(out, "PNG")
    return _ok("thumb", "IMG", path=str(out),
               instruction="resize to 256px on the long edge",
               duration_ms=t.duration_ms or 0.0)


def pass_content_hash(src: Path) -> dict:
    with timing.Timer("content_hash", src) as t:
        h = hashlib.sha256()
        with open(src, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 16), b""):
                h.update(chunk)
        digest = h.hexdigest()[:16]
    return _ok("content_hash", "TXT", value=digest,
               instruction="sha256(file)[:16]",
               duration_ms=t.duration_ms or 0.0)


# ─── Heavy(-ish): mask + nobg via rembg or process.py ───────────────────────
def _process_py() -> Path:
    return paths.TOOLS_DIR / "process.py"


def pass_mask(src: Path) -> dict:
    with timing.Timer("mask", src) as t:
        out = _sibling(src, "mask", "png")
        proc = _process_py()
        if proc.exists():
            r = subprocess.run(
                ["python3", str(proc), "mask", str(src), str(out)],
                capture_output=True, text=True, timeout=120,
            )
            if r.returncode == 0 and out.exists():
                return _ok("mask", "MASK", path=str(out),
                           instruction="alpha-matte foreground subject",
                           duration_ms=t.duration_ms or 0.0)
            return _unavailable("mask",
                                f"process.py mask failed: {r.stderr[:200]}")
        return _unavailable("mask", "process.py missing at " + str(proc))


def pass_nobg(src: Path) -> dict:
    with timing.Timer("nobg", src) as t:
        out = _sibling(src, "nobg", "png")
        proc = _process_py()
        if proc.exists():
            r = subprocess.run(
                ["python3", str(proc), "bgremove", str(src), str(out)],
                capture_output=True, text=True, timeout=120,
            )
            if r.returncode == 0 and out.exists():
                return _ok("nobg", "IMG", path=str(out),
                           instruction="apply mask → RGBA subject",
                           duration_ms=t.duration_ms or 0.0)
            return _unavailable("nobg",
                                f"process.py bgremove failed: {r.stderr[:200]}")
        return _unavailable("nobg", "process.py missing")


# ─── Depth (pseudo via PIL, real DepthPro hook stubbed) ─────────────────────
def pass_depth(src: Path) -> dict:
    try:
        from PIL import Image, ImageFilter, ImageOps
    except ImportError:
        return _unavailable("depth", "PIL not installed")
    with timing.Timer("depth", src) as t:
        out = _sibling(src, "depth", "png")
        with Image.open(src) as im:
            gray = ImageOps.grayscale(im).filter(ImageFilter.GaussianBlur(2))
            edges = gray.filter(ImageFilter.FIND_EDGES)
            # Mix the two: depth = 0.85*gray + 0.4*edges → simple pseudo-depth.
            depth = Image.eval(gray, lambda v: min(int(v * 0.85), 255))
            depth_e = Image.eval(edges, lambda v: min(int(v * 0.4), 255))
            depth = Image.blend(depth.convert("L"),
                                depth_e.convert("L"), 0.5)
            depth.save(out, "PNG")
    return _ok("depth", "DEPTH", path=str(out),
               instruction="pseudo-depth via edge+luminance (PIL); "
                           "TODO hook DepthPro / Depth-Anything-v2",
               duration_ms=t.duration_ms or 0.0)


# ─── Caption + tags (cc tiny if available, else heuristic) ───────────────────
def pass_tags(src: Path) -> dict:
    """Re-use process.py's keyword classifier — fast + deterministic."""
    with timing.Timer("tags", src) as t:
        proc = _process_py()
        if proc.exists():
            r = subprocess.run(
                ["python3", str(proc), "classify", str(src)],
                capture_output=True, text=True, timeout=30,
            )
            if r.returncode == 0:
                category = r.stdout.strip()
                # Split path → tag list (Cloths/Female/Tops → 3 tags)
                tags = [seg for seg in category.split("/") if seg]
                return _ok("tags", "TXT", value=tags,
                           instruction="filename heuristic → category tags",
                           duration_ms=t.duration_ms or 0.0)
        return _unavailable("tags", "process.py missing")


def pass_caption(src: Path) -> dict:
    """Try cc tiny for a quick caption; else fall back to filename slug."""
    with timing.Timer("caption", src) as t:
        prompt = f"In one short sentence, describe the content of an image filename like '{src.name}'."
        if _have("cc"):
            r = subprocess.run(
                ["cc", "tiny", prompt],
                capture_output=True, text=True, timeout=20,
                env={**os.environ, "CC_AUTO_SCOPE": "0"},
            )
            if r.returncode == 0 and r.stdout.strip():
                txt = r.stdout.strip().splitlines()[-1][:240]
                return _ok("caption", "TXT", value=txt,
                           instruction="cc tiny one-line caption",
                           duration_ms=t.duration_ms or 0.0)
        # Fallback: filename → caption.
        slug = src.stem.replace("_", " ").replace("-", " ").strip()
        return _ok("caption", "TXT", value=slug,
                   instruction="filename slug fallback (cc tiny unavailable)",
                   duration_ms=t.duration_ms or 0.0)


# ─── Embedding (placeholder — returns deterministic zeros) ──────────────────
def pass_embedding(src: Path) -> dict:
    """Stub: writes a 512-dim zero vector to a .npy sidecar. Replace with
    real CLIP/metaclip later — the slot, sidecar path, and DAG plumbing
    are all in place."""
    with timing.Timer("embedding", src) as t:
        if not _have_mod("numpy"):
            return _unavailable("embedding", "numpy not installed")
        import numpy as np
        out = _sibling(src, "embedding", "npy")
        # Deterministic placeholder so dedup-by-embedding doesn't false-match
        # — hash the file content into the first dim so different images
        # produce different vectors at least.
        h = hashlib.sha256(src.read_bytes()).digest()
        vec = np.zeros(512, dtype=np.float32)
        for i, b in enumerate(h):
            vec[i] = (b / 255.0) - 0.5
        np.save(out, vec)
    return _ok("embedding", "EMB", path=str(out),
               instruction="512-dim float32; placeholder (sha-seeded zeros). "
                           "TODO hook real CLIP / metaclip-2-mt5.",
               duration_ms=t.duration_ms or 0.0)


# ─── Lazy passes (kept as stubs that report clearly) ────────────────────────
def pass_keypoints(src: Path) -> dict:
    if not _have_mod("mediapipe"):
        return _unavailable("keypoints", "mediapipe not installed")
    return _unavailable("keypoints", "TODO: hook MediaPipe Pose")


def pass_normal_map(src: Path) -> dict:
    try:
        from PIL import Image, ImageFilter, ImageOps
    except ImportError:
        return _unavailable("normal_map", "PIL not installed")
    with timing.Timer("normal_map", src) as t:
        out = _sibling(src, "normal_map", "png")
        with Image.open(src) as im:
            gray = ImageOps.grayscale(im).filter(ImageFilter.GaussianBlur(1))
            # Sobel-ish: PIL FIND_EDGES gets us a rough gradient.
            edges = gray.filter(ImageFilter.FIND_EDGES)
            # Build a 3-channel "normal" by repeating + biasing.
            normal = Image.merge("RGB", (
                Image.eval(edges, lambda v: min(v + 128, 255)),
                Image.eval(edges, lambda v: min(v + 128, 255)),
                Image.eval(gray,  lambda v: 255 - v // 2),
            ))
            normal.save(out, "PNG")
    return _ok("normal_map", "IMG", path=str(out),
               instruction="height→tangent-space normal (PIL, rough)",
               duration_ms=t.duration_ms or 0.0)


def pass_albedo(src: Path) -> dict:
    return _unavailable("albedo", "TODO: intrinsic-decomp model")


# ─── Video / audio ──────────────────────────────────────────────────────────
def _ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def pass_vid_thumb(src: Path) -> dict:
    ff = _ffmpeg()
    if ff is None:
        return _unavailable("vid_thumb", "ffmpeg not installed")
    with timing.Timer("vid_thumb", src) as t:
        out = _sibling(src, "vidthumb", "png")
        # Probe duration via ffprobe? Skip — just grab a 5-sec mark.
        r = subprocess.run(
            [ff, "-y", "-ss", "5", "-i", str(src), "-frames:v", "1", str(out)],
            capture_output=True, timeout=30,
        )
        if r.returncode != 0 or not out.exists():
            return _unavailable("vid_thumb", "ffmpeg failed")
    return _ok("vid_thumb", "IMG", path=str(out),
               instruction="grab frame at t=5s",
               duration_ms=t.duration_ms or 0.0)


def pass_waveform(src: Path) -> dict:
    ff = _ffmpeg()
    if ff is None:
        return _unavailable("waveform", "ffmpeg not installed")
    import array, json as _json
    with timing.Timer("waveform", src) as t:
        cmd = [ff, "-v", "error", "-i", str(src), "-vn", "-ac", "1",
               "-ar", "4000", "-f", "s16le", "-"]
        r = subprocess.run(cmd, capture_output=True, timeout=120)
        if r.returncode != 0 or not r.stdout:
            return _unavailable("waveform", "ffmpeg pcm decode failed")
        samples = array.array("h"); samples.frombytes(r.stdout)
        n = len(samples)
        buckets = 1200
        size = max(1, n // buckets)
        peaks = []
        for i in range(min(buckets, n // size)):
            chunk = samples[i * size:(i + 1) * size]
            if chunk:
                peaks.append([max(chunk) / 32768.0, min(chunk) / 32768.0])
        out = _sibling(src, "waveform", "json")
        out.write_text(_json.dumps({"sample_rate": 4000, "peaks": peaks}))
    return _ok("waveform", "TXT", path=str(out),
               instruction="bucketed peak-envelope JSON",
               duration_ms=t.duration_ms or 0.0)


# ─── Stubs (clear PassUnavailable so the pipeline continues) ────────────────
def pass_video_caption(src: Path) -> dict:
    return _unavailable("video_caption", "TODO: SpaceTimeGPT")


def pass_stems(src: Path) -> dict:
    """Reuse the existing separate.py utility."""
    sep = paths.TOOLS_DIR / "separate.py"
    if not sep.exists():
        return _unavailable("stems", "separate.py missing")
    with timing.Timer("stems", src) as t:
        out_dir = _sibling(src, "stems", "").with_suffix("")
        out_dir.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(
            ["python3", str(sep), str(src), str(out_dir)],
            capture_output=True, text=True, timeout=600,
        )
        if r.returncode != 0:
            return _unavailable("stems", f"separate.py failed: {r.stderr[:200]}")
    return _ok("stems", "AUD", path=str(out_dir),
               instruction="split into vocals/music/noise",
               duration_ms=t.duration_ms or 0.0)


def pass_speech_to_text(src: Path) -> dict:
    return _unavailable("speech_to_text", "TODO: ultravox / whisper")


def pass_mesh_thumb(src: Path) -> dict:
    return _unavailable("mesh_thumb", "TODO: Blender / Open3D render")


def pass_bbox_volume(src: Path) -> dict:
    if not _have_mod("trimesh"):
        return _unavailable("bbox_volume", "trimesh not installed")
    import trimesh
    with timing.Timer("bbox_volume", src) as t:
        try:
            m = trimesh.load(str(src), force="mesh")
            b = m.bounds.tolist() if hasattr(m, "bounds") else None
        except Exception as e:
            return _unavailable("bbox_volume", str(e))
    return _ok("bbox_volume", "TXT", value=b,
               instruction="axis-aligned bbox (min/max)",
               duration_ms=t.duration_ms or 0.0)


def pass_pdf_extract_text(src: Path) -> dict:
    if _have("pdftotext"):
        with timing.Timer("pdf_extract_text", src) as t:
            out = _sibling(src, "text", "md")
            r = subprocess.run(["pdftotext", str(src), str(out)],
                               capture_output=True, timeout=120)
            if r.returncode == 0 and out.exists():
                return _ok("pdf_extract_text", "MD", path=str(out),
                           instruction="pdftotext extraction",
                           duration_ms=t.duration_ms or 0.0)
    return _unavailable("pdf_extract_text", "TODO: MinerU; pdftotext not found")


# ─── Special: layered_svg is built by passes/svg_layers, not here ───────────
def pass_layered_svg(src: Path) -> dict:
    """The bundler — invoked AFTER every other import-time pass has run.
    Lives in svg_layers.py; we forward to it so the registry has one entry."""
    from . import svg_layers
    return svg_layers.pack_for_source(src)


# ─── Dispatch table ─────────────────────────────────────────────────────────
DISPATCH = {
    "thumb":             pass_thumb,
    "content_hash":      pass_content_hash,
    "mask":              pass_mask,
    "nobg":              pass_nobg,
    "depth":             pass_depth,
    "caption":           pass_caption,
    "tags":              pass_tags,
    "keypoints":         pass_keypoints,
    "embedding":         pass_embedding,
    "normal_map":        pass_normal_map,
    "albedo":            pass_albedo,
    "layered_svg":       pass_layered_svg,
    "vid_thumb":         pass_vid_thumb,
    "waveform":          pass_waveform,
    "video_caption":     pass_video_caption,
    "stems":             pass_stems,
    "speech_to_text":    pass_speech_to_text,
    "mesh_thumb":        pass_mesh_thumb,
    "bbox_volume":       pass_bbox_volume,
    "pdf_extract_text":  pass_pdf_extract_text,
}


def run(pass_id: str, src: Path, **kwargs) -> dict:
    fn = DISPATCH.get(pass_id)
    if fn is None:
        return _unavailable(pass_id, "no inference shim registered")
    try:
        return fn(src, **kwargs) if kwargs else fn(src)
    except Exception as e:
        return _unavailable(pass_id, f"exception: {e}")
