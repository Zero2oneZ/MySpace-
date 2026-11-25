#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        audio_chromatize
# role:        AUDIO · WAVEFORM → RGB + HEX "SOUND WAVE"
# tier:        L0
# substrate:   Turns any audio (a WAV file, or an amplitude array captured live
#              in the browser) into a time-series where each value carries an
#              rgba color + #hex + frame index — the same colour dimension the
#              rest of the substrate speaks (dimension_pack / frame_clock).
# storage:     ~/.cc/chroma/<stem>.{jsonl,svg}
# reuse:       dimension_pack._hsv_to_rgb · frame_clock.timestamp_to_frame
# ffmpeg:      OPTIONAL — WAV reads via stdlib `wave`; other formats need ffmpeg
# ----------------------------------------------------------------------------
"""audio_chromatize — colourise a sound wave.

Each bucket of audio (a slice of time) is reduced to a normalised amplitude in
[0,1] and mapped to a colour: quiet = cool/dark blue, loud = warm/bright red.
Every bucket gets {t, frame60, amp, rgba, hex}. Output is an append-friendly
JSONL plus a coloured-bar SVG waveform.

Two entry points:
  - chromatize_amplitudes(amps, duration_s)  — pure Python, no ffmpeg. Used by
    the live tab-capture path (browser AnalyserNode sends the amplitudes).
  - chromatize_file(path)                     — read a WAV via stdlib (or any
    format via ffmpeg if installed) → amplitudes → chromatize_amplitudes.

CLI:
  python3 core/lib/audio_chromatize.py file <audio.wav> [--buckets N] [--out-dir D]
  python3 core/lib/audio_chromatize.py amps <a.json> --duration S [--label L]
"""
from __future__ import annotations

import array
import json
import math
import os
import subprocess
import sys
import wave
from pathlib import Path
from typing import Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))  # core/lib on path
from dimension_pack import _hsv_to_rgb  # type: ignore  # noqa: E402
from frame_clock import timestamp_to_frame  # type: ignore  # noqa: E402

HOME = Path(os.environ.get("CC_HOME", str(Path.home() / ".cc")))
CHROMA_DIR = HOME / "chroma"
DEFAULT_BUCKETS = 600


# ── colour mapping ────────────────────────────────────────────────────────────

def rgba_to_hex(rgba: Sequence[float]) -> str:
    """[r,g,b,(a)] floats in [0,1] -> '#rrggbb'. Same formula as
    pump_visualizer_3d._rgba_to_hex (kept inline to avoid its heavy imports)."""
    r = max(0, min(255, int(round(rgba[0] * 255))))
    g = max(0, min(255, int(round(rgba[1] * 255))))
    b = max(0, min(255, int(round(rgba[2] * 255))))
    return f"#{r:02x}{g:02x}{b:02x}"


def amp_to_rgba(amp: float, alpha: float = 0.92) -> List[float]:
    """Normalised amplitude [0,1] -> [r,g,b,a].

    Hue sweeps blue(240°)→red(0°) as it gets louder; brightness rises with
    amplitude too, so silence is near-black and peaks are vivid.
    """
    a = max(0.0, min(1.0, amp))
    hue = 240.0 - 240.0 * a            # 240=blue (quiet) … 0=red (loud)
    sat = 0.85
    val = 0.18 + 0.78 * a
    r, g, b = _hsv_to_rgb(hue, sat, val)
    return [round(r, 4), round(g, 4), round(b, 4), round(alpha, 4)]


# ── core: amplitudes -> chromatized frames ────────────────────────────────────

def chromatize_amplitudes(amps: Sequence[float], duration_s: float,
                          normalize: bool = True) -> List[Dict]:
    """Map an amplitude series (already one-value-per-bucket) to coloured frames.

    amps need not be normalised; if `normalize`, they're scaled by the peak.
    duration_s lets us place each bucket on the timeline (→ frame60).
    """
    n = len(amps)
    if n == 0:
        return []
    peak = max((abs(float(a)) for a in amps), default=0.0) or 1.0
    scale = (1.0 / peak) if normalize else 1.0
    dt = (duration_s / n) if duration_s > 0 else 0.0
    frames: List[Dict] = []
    for i, raw in enumerate(amps):
        amp = max(0.0, min(1.0, abs(float(raw)) * scale))
        t = round(i * dt, 5)
        rgba = amp_to_rgba(amp)
        frames.append({
            "i": i,
            "t": t,
            "frame60": timestamp_to_frame(t, 60) if t >= 0 else 0,
            "amp": round(amp, 4),
            "rgba": rgba,
            "hex": rgba_to_hex(rgba),
        })
    return frames


# ── WAV reading (stdlib only) + ffmpeg fallback ───────────────────────────────

_TYPECODES = {1: "b", 2: "h", 4: "i"}  # sample width (bytes) -> array typecode


def _wav_amplitudes(path: Path, buckets: int) -> tuple[List[float], float]:
    """Read a PCM WAV with the stdlib and reduce to `buckets` peak amplitudes.
    Returns (amps_normalised_to_int_range, duration_seconds)."""
    with wave.open(str(path), "rb") as w:
        n_ch = w.getnchannels()
        width = w.getsampwidth()
        rate = w.getframerate()
        n_frames = w.getnframes()
        raw = w.readframes(n_frames)
    duration = (n_frames / rate) if rate else 0.0
    tc = _TYPECODES.get(width)
    if tc is None:  # e.g. 24-bit — let ffmpeg handle it
        raise ValueError(f"unsupported WAV sample width {width}")
    samples = array.array(tc)
    samples.frombytes(raw)
    if sys.byteorder == "big":
        samples.byteswap()
    full = float(1 << (8 * width - 1))  # max magnitude for this width
    # collapse channels to mono by taking max magnitude across channels
    mono_len = len(samples) // n_ch if n_ch else len(samples)
    if mono_len == 0:
        return [], duration
    per = max(1, mono_len // buckets)
    amps: List[float] = []
    for b in range(0, mono_len, per):
        peak = 0.0
        for j in range(b, min(b + per, mono_len)):
            base = j * n_ch
            for c in range(n_ch):
                v = abs(samples[base + c])
                if v > peak:
                    peak = v
        amps.append(peak / full)
    return amps, duration


def _ffmpeg_amplitudes(path: Path, buckets: int,
                       sr: int = 4000) -> tuple[List[float], float]:
    """Decode any format to mono s16le PCM via ffmpeg (technique from
    yt_cutter.extract_waveform) and reduce to peak buckets."""
    if not _have_ffmpeg():
        raise RuntimeError("ffmpeg not installed; only .wav inputs are supported")
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1",
         "-ar", str(sr), "-f", "s16le", "-"],
        capture_output=True)
    pcm = array.array("h")
    pcm.frombytes(proc.stdout)
    if sys.byteorder == "big":
        pcm.byteswap()
    n = len(pcm)
    duration = n / sr if sr else 0.0
    if n == 0:
        return [], duration
    per = max(1, n // buckets)
    amps = []
    for b in range(0, n, per):
        peak = 0
        for j in range(b, min(b + per, n)):
            v = abs(pcm[j])
            if v > peak:
                peak = v
        amps.append(peak / 32768.0)
    return amps, duration


def _have_ffmpeg() -> bool:
    from shutil import which
    return which("ffmpeg") is not None


def file_amplitudes(path: Path, buckets: int = DEFAULT_BUCKETS
                    ) -> tuple[List[float], float]:
    if path.suffix.lower() == ".wav":
        try:
            return _wav_amplitudes(path, buckets)
        except ValueError:
            pass  # fall through to ffmpeg for odd WAV encodings
    return _ffmpeg_amplitudes(path, buckets)


# ── SVG render ────────────────────────────────────────────────────────────────

def to_svg(frames: List[Dict], label: str = "", width: int = 1200,
           height: int = 240) -> str:
    n = len(frames) or 1
    bw = width / n
    mid = height / 2
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}" '
        f'font-family="monospace">',
        f'<rect width="{width}" height="{height}" fill="#0b0e14"/>',
    ]
    for k, fr in enumerate(frames):
        h = fr["amp"] * (mid - 6)
        x = k * bw
        parts.append(
            f'<rect x="{x:.2f}" y="{mid - h:.2f}" width="{max(bw, 0.6):.2f}" '
            f'height="{2 * h:.2f}" fill="{fr["hex"]}">'
            f'<title>t={fr["t"]}s f60={fr["frame60"]} amp={fr["amp"]} '
            f'{fr["hex"]}</title></rect>')
    if label:
        parts.append(f'<text x="12" y="20" fill="#9fb3c8" font-size="13">'
                     f'{label}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


# ── orchestration + persistence ───────────────────────────────────────────────

def _write_outputs(stem: str, frames: List[Dict], label: str) -> Dict:
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    jsonl = CHROMA_DIR / f"{stem}.jsonl"
    svg = CHROMA_DIR / f"{stem}.svg"
    with jsonl.open("w") as f:
        for fr in frames:
            f.write(json.dumps(fr, separators=(",", ":")) + "\n")
    svg.write_text(to_svg(frames, label=label or stem))
    return {
        "buckets": len(frames),
        "jsonl": str(jsonl),
        "svg": str(svg),
        "peak_hex": max(frames, key=lambda f: f["amp"])["hex"] if frames else "",
    }


def chromatize_file(path: str, buckets: int = DEFAULT_BUCKETS,
                    stem: str = "") -> Dict:
    p = Path(path)
    amps, dur = file_amplitudes(p, buckets)
    frames = chromatize_amplitudes(amps, dur)
    out = _write_outputs(stem or p.stem, frames, label=p.name)
    out["source"] = str(p)
    out["duration_s"] = round(dur, 3)
    return out


def chromatize_series(amps: Sequence[float], duration_s: float, stem: str,
                      label: str = "") -> Dict:
    """For the live path: a precomputed amplitude array (e.g. browser
    AnalyserNode) → chromatized frames + outputs. No ffmpeg involved."""
    frames = chromatize_amplitudes(amps, duration_s)
    out = _write_outputs(stem, frames, label=label or stem)
    out["duration_s"] = round(duration_s, 3)
    out["frames"] = frames  # caller may want them inline (server links to token)
    return out


# ── CLI ────────────────────────────────────────────────────────────────────────

def main(argv: List[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, args = argv[0], argv[1:]

    if cmd == "file":
        if not args:
            print("usage: file <audio> [--buckets N]", file=sys.stderr)
            return 2
        path = args[0]
        buckets = DEFAULT_BUCKETS
        i = 1
        while i < len(args):
            if args[i] == "--buckets" and i + 1 < len(args):
                buckets = int(args[i + 1]); i += 2; continue
            i += 1
        try:
            out = chromatize_file(path, buckets=buckets)
        except Exception as e:
            print(f"[chroma] {type(e).__name__}: {e}", file=sys.stderr)
            return 1
        print(json.dumps(out, indent=2))
        return 0

    if cmd == "amps":
        if not args:
            print("usage: amps <amps.json> --duration S [--label L]",
                  file=sys.stderr)
            return 2
        amps = json.loads(Path(args[0]).read_text())
        dur = 0.0
        label = ""
        stem = Path(args[0]).stem
        i = 1
        while i < len(args):
            if args[i] == "--duration" and i + 1 < len(args):
                dur = float(args[i + 1]); i += 2; continue
            if args[i] == "--label" and i + 1 < len(args):
                label = args[i + 1]; i += 2; continue
            i += 1
        out = chromatize_series(amps, dur, stem=stem, label=label)
        out.pop("frames", None)
        print(json.dumps(out, indent=2))
        return 0

    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
