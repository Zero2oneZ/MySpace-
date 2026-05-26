"""separate.py — split an audio file into vocals / music / noise stems.

Two backends, tried in order of quality:

1. demucs (best — ~4 stems: vocals, drums, bass, other → grouped to vocals+music)
2. ffmpeg karaoke trick (center-channel extract for vocal-like band; very rough)

Usage:
    separate.py <audio_in> <out_dir>
        # writes <out_dir>/vocals.wav, music.wav, noise.wav (best-effort)

Returns paths via stdout JSON for the caller (yt_cutter, etc).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def _have(bin_name: str) -> bool:
    return shutil.which(bin_name) is not None


def _have_python_mod(mod: str) -> bool:
    try:
        __import__(mod); return True
    except Exception:
        return False


def separate_demucs(audio_in: Path, out_dir: Path) -> dict:
    """Use demucs (htdemucs by default). Produces 4 stems → we reshape into
    vocals.wav + music.wav (drums+bass+other mixed). Noise gets a copy of
    the residual (lowpassed 'other' as a noise proxy)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    # demucs expects `python -m demucs.separate`
    work = out_dir / "_demucs_work"
    work.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "-m", "demucs.separate",
        "-n", "htdemucs",
        "--out", str(work),
        str(audio_in),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"demucs failed: {r.stderr[-400:]}")
    # demucs output path: <work>/htdemucs/<basename>/<stem>.wav
    stem_dir = work / "htdemucs" / audio_in.stem
    if not stem_dir.exists():
        # Sometimes wrapped in single quotes / different basename — find it.
        candidates = list(work.rglob("vocals.wav"))
        if not candidates:
            raise RuntimeError("demucs ran but no vocals.wav found")
        stem_dir = candidates[0].parent
    vocals = stem_dir / "vocals.wav"
    music_out = out_dir / "music.wav"
    vocals_out = out_dir / "vocals.wav"
    noise_out = out_dir / "noise.wav"
    # Mix drums + bass + other → music.
    drums  = stem_dir / "drums.wav"
    bass   = stem_dir / "bass.wav"
    other  = stem_dir / "other.wav"
    mix_inputs = [p for p in (drums, bass, other) if p.exists()]
    if not mix_inputs:
        shutil.copy(vocals, vocals_out)
        return {"vocals": str(vocals_out), "music": "", "noise": ""}
    # ffmpeg amix into music.wav
    cmd_mix = ["ffmpeg", "-y"]
    for p in mix_inputs:
        cmd_mix += ["-i", str(p)]
    cmd_mix += ["-filter_complex",
                f"amix=inputs={len(mix_inputs)}:dropout_transition=2",
                "-c:a", "pcm_s16le", str(music_out)]
    subprocess.run(cmd_mix, check=True, capture_output=True)
    shutil.copy(vocals, vocals_out)
    # Noise = highpassed 'other' (>5 kHz) as a coarse noise proxy.
    if other.exists():
        subprocess.run([
            "ffmpeg", "-y", "-i", str(other),
            "-af", "highpass=f=5000,volume=0.7",
            "-c:a", "pcm_s16le", str(noise_out),
        ], check=True, capture_output=True)
    shutil.rmtree(work, ignore_errors=True)
    return {"vocals": str(vocals_out),
            "music":  str(music_out),
            "noise":  str(noise_out) if noise_out.exists() else ""}


def separate_ffmpeg(audio_in: Path, out_dir: Path) -> dict:
    """Pure ffmpeg fallback. Uses pan/sidechain tricks for a rough split:
        vocals = center-channel extract (assumes vocals are panned middle)
        music  = L+R minus center
        noise  = highpassed residual (>5 kHz)
    Quality is mediocre — use demucs when available."""
    out_dir.mkdir(parents=True, exist_ok=True)
    vocals_out = out_dir / "vocals.wav"
    music_out  = out_dir / "music.wav"
    noise_out  = out_dir / "noise.wav"
    # Vocals = (L+R)/2 (center)
    subprocess.run([
        "ffmpeg", "-y", "-i", str(audio_in),
        "-af", "pan=mono|c0=0.5*c0+0.5*c1",
        "-c:a", "pcm_s16le", str(vocals_out),
    ], check=True, capture_output=True)
    # Music = (L-R)/2 (side)
    subprocess.run([
        "ffmpeg", "-y", "-i", str(audio_in),
        "-af", "pan=stereo|c0=c0-c1|c1=c1-c0",
        "-c:a", "pcm_s16le", str(music_out),
    ], check=True, capture_output=True)
    # Noise = highpassed mono
    subprocess.run([
        "ffmpeg", "-y", "-i", str(audio_in),
        "-af", "pan=mono|c0=0.5*c0+0.5*c1,highpass=f=5000,volume=0.7",
        "-c:a", "pcm_s16le", str(noise_out),
    ], check=True, capture_output=True)
    return {"vocals": str(vocals_out),
            "music":  str(music_out),
            "noise":  str(noise_out)}


def separate(audio_in: Path, out_dir: Path) -> dict:
    """Pick the best available backend."""
    if not audio_in.exists():
        raise FileNotFoundError(audio_in)
    if not _have("ffmpeg"):
        raise RuntimeError("ffmpeg not found — required for separation")
    if _have_python_mod("demucs"):
        try:
            return {"backend": "demucs", **separate_demucs(audio_in, out_dir)}
        except Exception as e:
            print(f"[separate] demucs failed ({e}); falling back to ffmpeg",
                  file=sys.stderr)
    return {"backend": "ffmpeg-fallback", **separate_ffmpeg(audio_in, out_dir)}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: separate.py <audio_in> <out_dir>", file=sys.stderr)
        sys.exit(2)
    out = separate(Path(sys.argv[1]), Path(sys.argv[2]))
    print(json.dumps(out, indent=2))
