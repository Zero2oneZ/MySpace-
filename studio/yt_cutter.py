"""YouTube time-slider cut editor with audio waveform.

Paste a YouTube URL, the video is downloaded and its audio waveform is rendered
as a Plotly chart. Click-drag a box on the waveform to clamp a start/end window
(or use the slider / number inputs). Cut & Save writes:
    - the trimmed video to <project>/media/video/
    - the trimmed audio (wav) to <project>/media/sound/
"""
from __future__ import annotations

import array
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st


PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

import bootstrap, paths  # noqa: E402  -- canonical layout
bootstrap.ensure()

MEDIA_DIR  = paths.MEDIA_ROOT
VIDEO_DIR  = paths.VIDEO_DIR
SOUND_DIR  = paths.SOUNDS_DIR
VOCALS_DIR = paths.VOCALS_DIR
MUSIC_DIR  = paths.MUSIC_DIR
NOISE_DIR  = paths.NOISE_DIR
CACHE_DIR  = paths.YTDLP_CACHE_DIR

# Also expose media/.tools/ for the separate.py + sidecar.py utilities.
sys.path.insert(0, str(paths.TOOLS_DIR))


def _find_ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    for cand in (
        Path.home() / ".nix-profile/bin/ffmpeg",
        Path("/run/current-system/sw/bin/ffmpeg"),
    ):
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)
    matches = sorted(Path("/nix/store").glob("*-ffmpeg*/bin/ffmpeg"), reverse=True)
    if matches:
        return str(matches[0])
    return "ffmpeg"


FFMPEG = _find_ffmpeg()
YT_DLP = shutil.which("yt-dlp") or str(PROJECT_DIR / ".venv/bin/yt-dlp")

WAVE_BUCKETS = 1200          # number of horizontal pixels in the waveform
WAVE_SAMPLE_RATE = 4000      # PCM sample rate fed to numpy-less peak reducer


@dataclass
class VideoInfo:
    video_id: str
    title: str
    duration: float
    uploader: str
    path: Path
    thumbnail: str | None


def _safe_slug(text: str, max_len: int = 60) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_")
    return text[:max_len] or "clip"


def _fmt_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds - (h * 3600 + m * 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:06.3f}"
    return f"{m:02d}:{s:06.3f}"


def fetch_metadata(url: str) -> dict:
    out = subprocess.run(
        [YT_DLP, "-J", "--no-warnings", "--no-playlist", url],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return json.loads(out.stdout)


def download_video(url: str, status_box) -> VideoInfo:
    meta = fetch_metadata(url)
    vid = meta["id"]
    target = CACHE_DIR / f"{vid}.mp4"
    if not target.exists():
        status_box.info(f"Downloading {meta.get('title', vid)} …")
        cmd = [
            YT_DLP,
            "-f",
            "bv*[ext=mp4][height<=1080]+ba[ext=m4a]/b[ext=mp4]/best",
            "--merge-output-format", "mp4",
            "--no-playlist",
            "-o", str(target),
            url,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0 or not target.exists():
            raise RuntimeError(
                f"yt-dlp failed: {proc.stderr.strip()[-600:] or proc.stdout.strip()[-600:]}"
            )
    return VideoInfo(
        video_id=vid,
        title=meta.get("title", vid),
        duration=float(meta.get("duration") or 0.0),
        uploader=meta.get("uploader", ""),
        path=target,
        thumbnail=meta.get("thumbnail"),
    )


# ─── Waveform extraction (no numpy) ────────────────────────────────────────

@st.cache_data(show_spinner=False)
def extract_waveform(video_path_str: str, buckets: int = WAVE_BUCKETS) -> dict:
    """Return {'times': [...], 'peaks_pos': [...], 'peaks_neg': [...]}.

    Decodes the audio to mono s16le PCM at WAVE_SAMPLE_RATE via ffmpeg,
    then reduces to ``buckets`` min/max envelope using pure-python.
    """
    video_path = Path(video_path_str)
    cmd = [
        FFMPEG, "-v", "error",
        "-i", str(video_path),
        "-vn",
        "-ac", "1",
        "-ar", str(WAVE_SAMPLE_RATE),
        "-f", "s16le",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError(
            f"ffmpeg audio decode failed: {proc.stderr[-600:].decode(errors='replace')}"
        )
    samples = array.array("h")
    samples.frombytes(proc.stdout)
    n = len(samples)
    if n == 0:
        return {"times": [], "peaks_pos": [], "peaks_neg": []}
    buckets = max(50, min(buckets, n))
    bucket_size = max(1, n // buckets)
    peaks_pos = []
    peaks_neg = []
    times = []
    for i in range(buckets):
        s = i * bucket_size
        e = s + bucket_size if i < buckets - 1 else n
        chunk = samples[s:e]
        if not chunk:
            peaks_pos.append(0.0); peaks_neg.append(0.0); times.append(s / WAVE_SAMPLE_RATE)
            continue
        hi = max(chunk); lo = min(chunk)
        peaks_pos.append(hi / 32768.0)
        peaks_neg.append(lo / 32768.0)
        times.append((s + (e - s) / 2) / WAVE_SAMPLE_RATE)
    return {"times": times, "peaks_pos": peaks_pos, "peaks_neg": peaks_neg}


def build_waveform_figure(wave: dict, dur: float, start: float, end: float) -> go.Figure:
    times = wave["times"]
    pos = wave["peaks_pos"]
    neg = wave["peaks_neg"]
    fig = go.Figure()
    # Filled envelope: upper trace then lower trace (with fill='tonexty').
    fig.add_trace(go.Scatter(
        x=times, y=pos, mode="lines",
        line=dict(width=0.5, color="#7dd3fc"),
        hoverinfo="skip", showlegend=False,
    ))
    fig.add_trace(go.Scatter(
        x=times, y=neg, mode="lines",
        line=dict(width=0.5, color="#7dd3fc"),
        fill="tonexty", fillcolor="rgba(125,211,252,0.55)",
        hoverinfo="skip", showlegend=False,
    ))
    # Selection band
    if end > start:
        fig.add_vrect(
            x0=start, x1=end,
            fillcolor="rgba(250, 204, 21, 0.25)",
            line_width=0, layer="below",
        )
    fig.add_vline(x=start, line=dict(color="#22c55e", width=2))
    fig.add_vline(x=end, line=dict(color="#ef4444", width=2))

    fig.update_layout(
        height=240,
        margin=dict(l=10, r=10, t=10, b=30),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(15,23,42,0.6)",
        dragmode="select",
        selectdirection="h",
        xaxis=dict(
            range=[0, dur],
            title="seconds",
            color="#cbd5e1", gridcolor="rgba(148,163,184,0.15)",
            zeroline=False,
        ),
        yaxis=dict(
            range=[-1.05, 1.05],
            color="#cbd5e1", gridcolor="rgba(148,163,184,0.10)",
            zeroline=True, zerolinecolor="rgba(148,163,184,0.3)",
            showticklabels=False,
        ),
    )
    return fig


# ─── Cutters ───────────────────────────────────────────────────────────────

def cut_video(src: Path, start: float, end: float, out_path: Path, reencode: bool) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if reencode:
        cmd = [
            FFMPEG, "-y",
            "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
            "-i", str(src),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            str(out_path),
        ]
    else:
        cmd = [
            FFMPEG, "-y",
            "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
            "-i", str(src),
            "-c", "copy",
            "-avoid_negative_ts", "make_zero",
            str(out_path),
        ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg (video) failed:\n{proc.stderr[-1200:]}")


def cut_audio(src: Path, start: float, end: float, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        FFMPEG, "-y",
        "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
        "-i", str(src),
        "-vn",
        "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
        str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg (audio) failed:\n{proc.stderr[-1200:]}")


# ─── UI ────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="YouTube Cutter", page_icon="🎬", layout="wide")

# ─── friend-scoped auth gate (must come before any other UI) ────────────────
try:
    from auth.gate import require_login
    _auth = require_login()
except Exception as _e:
    st.error(f"Auth gate failed to load: {_e}")
    st.stop()

st.title("🎬 YouTube Cutter — waveform edit")
st.caption(
    f"Video → `{VIDEO_DIR.relative_to(PROJECT_DIR)}` · "
    f"Audio → `{SOUND_DIR.relative_to(PROJECT_DIR)}` · "
    f"cache `{CACHE_DIR.relative_to(PROJECT_DIR)}` · "
    f"signed in as **{_auth.user or '(solo)'}** from {_auth.ip}"
)

with st.sidebar:
    st.subheader("Source")
    url = st.text_input("YouTube URL", placeholder="https://www.youtube.com/watch?v=…")
    load_btn = st.button("Load video", type="primary", use_container_width=True)
    if st.button("Clear cache", use_container_width=True):
        for f in CACHE_DIR.glob("*"):
            try: f.unlink()
            except Exception: pass
        st.session_state.pop("video", None)
        st.cache_data.clear()
        st.success("Cache cleared.")
    st.divider()
    st.subheader("Output folders")
    st.code(str(VIDEO_DIR))
    st.code(str(SOUND_DIR))
    st.subheader("Recent video clips")
    for p in sorted(VIDEO_DIR.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)[:6]:
        st.write(f"• `{p.name}`")
    st.subheader("Recent audio clips")
    for p in sorted(SOUND_DIR.glob("*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)[:6]:
        st.write(f"• `{p.name}`")

status = st.empty()

if load_btn and url.strip():
    try:
        with st.spinner("Fetching metadata + downloading…"):
            info = download_video(url.strip(), status)
        st.session_state["video"] = info
        st.session_state.pop(f"range_{info.video_id}", None)
        status.success(f"Loaded: {info.title}  ·  {_fmt_time(info.duration)}")
    except Exception as e:
        status.error(str(e))

info: VideoInfo | None = st.session_state.get("video")

if info is None:
    st.info("Paste a YouTube URL on the left and click **Load video** to begin.")
    st.stop()

dur = max(0.1, info.duration or 0.0)
state_key = f"range_{info.video_id}"
if state_key not in st.session_state:
    st.session_state[state_key] = (0.0, min(dur, 30.0))
start, end = st.session_state[state_key]

# ── Layout: video on left, controls on right ────────────────────────────
c1, c2 = st.columns([3, 2], gap="large")

with c1:
    st.subheader(info.title)
    st.caption(f"{info.uploader}  ·  duration {_fmt_time(dur)}")
    video_bytes = info.path.read_bytes() if info.path.stat().st_size < 80_000_000 else None
    if video_bytes is not None:
        st.video(video_bytes, start_time=int(start))
    else:
        st.video(str(info.path), start_time=int(start))

with c2:
    st.subheader("Cut window")
    rng = st.slider(
        "Range (seconds)",
        min_value=0.0, max_value=float(dur),
        value=st.session_state[state_key],
        step=0.1,
        key=f"slider_{info.video_id}",
    )
    if rng != st.session_state[state_key]:
        st.session_state[state_key] = rng
        start, end = rng

    sub_a, sub_b = st.columns(2)
    with sub_a:
        start_fine = st.number_input(
            "Start (sec)", min_value=0.0, max_value=float(dur),
            value=float(start), step=0.05, format="%.3f",
            key=f"start_fine_{info.video_id}",
        )
    with sub_b:
        end_fine = st.number_input(
            "End (sec)", min_value=0.0, max_value=float(dur),
            value=float(end), step=0.05, format="%.3f",
            key=f"end_fine_{info.video_id}",
        )
    if (start_fine, end_fine) != (start, end):
        start = max(0.0, min(start_fine, dur))
        end = max(start + 0.05, min(end_fine, dur))
        st.session_state[state_key] = (start, end)

    dur_cut = max(0.0, end - start)
    st.metric("Clip length", _fmt_time(dur_cut), f"{start:.2f}s → {end:.2f}s")

# ── Waveform with box-select to clamp the cut window ────────────────────
st.subheader("Audio waveform")
st.caption("Click-drag a box across the waveform to clamp the cut window. "
           "Green line = start · Red line = end · Yellow band = selection.")

try:
    wave = extract_waveform(str(info.path))
except Exception as e:
    st.error(f"Could not build waveform: {e}")
    wave = {"times": [], "peaks_pos": [], "peaks_neg": []}

if wave["times"]:
    fig = build_waveform_figure(wave, dur, start, end)
    sel = st.plotly_chart(
        fig,
        use_container_width=True,
        key=f"wave_{info.video_id}",
        on_select="rerun",
        selection_mode=("box",),
        config={"displayModeBar": False, "scrollZoom": False},
    )
    # Streamlit returns a dict-like with selection.box[].x = [x0, x1]
    try:
        boxes = (sel or {}).get("selection", {}).get("box", []) or []
        if boxes:
            xs = boxes[0].get("x") or []
            if len(xs) >= 2:
                x0 = max(0.0, min(float(min(xs)), dur))
                x1 = max(0.0, min(float(max(xs)), dur))
                if x1 - x0 >= 0.05 and (x0, x1) != (start, end):
                    st.session_state[state_key] = (x0, x1)
                    st.rerun()
    except Exception:
        pass

# ── Output controls ─────────────────────────────────────────────────────
st.divider()
o1, o2, o3 = st.columns([2, 2, 1])
default_name = f"{_safe_slug(info.title)}_{int(start)}-{int(end)}"
with o1:
    out_stem = st.text_input("Output filename (no extension)", value=default_name,
                             key=f"name_{info.video_id}")
with o2:
    reencode = st.toggle(
        "Frame-accurate re-encode (video)",
        value=True,
        help="On = exact start/end (re-encodes). Off = fast copy, may snap to nearest keyframe.",
    )
    save_audio = st.toggle("Also save audio (.wav)", value=True)
with o3:
    st.write("")
    cut_btn = st.button("✂️  Cut & Save", type="primary",
                        use_container_width=True, disabled=dur_cut < 0.1)

if cut_btn:
    video_out = VIDEO_DIR / f"{out_stem}.mp4"
    if video_out.exists():
        video_out = VIDEO_DIR / f"{out_stem}_{int(time.time())}.mp4"
    audio_out = SOUND_DIR / f"{video_out.stem}.wav"
    try:
        with st.spinner(f"Cutting video → {video_out.name}"):
            cut_video(info.path, start, end, video_out, reencode)
        msgs = [f"Saved video → `{video_out}` ({video_out.stat().st_size/1e6:.1f} MB)"]
        # Write sidecar for the cut video.
        try:
            import sidecar
            sidecar.write(video_out,
                sha=sidecar.content_sha(video_out),
                source_url=url, source_kind="youtube",
                category="Media/Video",
                label=out_stem, description=f"YouTube cut [{start:.2f}-{end:.2f}]",
                tags=["youtube", "cut"],
            )
        except Exception:
            pass
        if save_audio:
            with st.spinner(f"Extracting audio → {audio_out.name}"):
                cut_audio(info.path, start, end, audio_out)
            msgs.append(f"Saved audio → `{audio_out}` ({audio_out.stat().st_size/1e6:.1f} MB)")
            # Stash the audio path so the separation block below can find it.
            st.session_state["yt_last_audio"] = str(audio_out)
            st.session_state["yt_last_video"] = str(video_out)
            st.session_state["yt_last_url"]   = url
            st.session_state["yt_last_stem"]  = video_out.stem
        st.success("  \n".join(msgs))
        with open(video_out, "rb") as fh:
            st.download_button(
                "Download video clip", data=fh.read(),
                file_name=video_out.name, mime="video/mp4",
                use_container_width=True,
            )
        if save_audio and audio_out.exists():
            with open(audio_out, "rb") as fh:
                st.download_button(
                    "Download audio clip", data=fh.read(),
                    file_name=audio_out.name, mime="audio/wav",
                    use_container_width=True,
                )
    except Exception as e:
        st.error(str(e))

# ─── Confirm + separate: split vocals / music / noise ────────────────────────
last_audio = st.session_state.get("yt_last_audio")
if last_audio and Path(last_audio).exists():
    st.markdown("---")
    st.subheader("Confirm + separate vocals / music / noise")
    st.caption(
        "Pick the cut above. On confirm we run the audio through a stem "
        "separator (demucs if installed, else an ffmpeg karaoke fallback). "
        "Each stem lands in `studio/media/Media/Sounds/{Vocals,Music,Noise}/` "
        "with a sidecar JSON linking it back to the source."
    )
    if st.button("✅  Confirm + separate", type="primary"):
        try:
            import separate as sep
            import sidecar
            audio_path = Path(last_audio)
            stem = st.session_state.get("yt_last_stem", audio_path.stem)
            url  = st.session_state.get("yt_last_url", "")
            tmp_out = CACHE_DIR / f"_separate_{stem}"
            tmp_out.mkdir(parents=True, exist_ok=True)
            with st.spinner("Separating stems (this can take a minute)…"):
                stems = sep.separate(audio_path, tmp_out)
            # Move each stem into its taxonomy dir + write sidecar.
            placed = {}
            for kind, src_str in stems.items():
                if kind == "backend" or not src_str:
                    continue
                src = Path(src_str)
                if not src.exists():
                    continue
                dest_dir = {
                    "vocals": VOCALS_DIR,
                    "music":  MUSIC_DIR,
                    "noise":  NOISE_DIR,
                }.get(kind)
                if dest_dir is None:
                    continue
                dest = dest_dir / f"{stem}_{kind}.wav"
                src.replace(dest)
                placed[kind] = str(dest)
                try:
                    sidecar.write(dest,
                        sha=sidecar.content_sha(dest),
                        source_url=url, source_kind="youtube-separated",
                        category=f"Media/Sounds/{kind.capitalize()}",
                        label=f"{stem} — {kind}",
                        description=f"Separated from YouTube cut {stem} via {stems.get('backend','?')}",
                        tags=["youtube", "separated", kind],
                        uses=["sample"],
                    )
                except Exception:
                    pass
            backend = stems.get("backend", "?")
            st.success(
                "Separated via " + backend + ":  \n"
                + "  \n".join(f"- **{k}** → `{v}`" for k, v in placed.items())
            )
        except Exception as e:
            st.error(f"Separation failed: {e}")
