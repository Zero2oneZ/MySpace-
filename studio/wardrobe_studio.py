"""Wardrobe Studio — background removal + virtual try-on + product mockup + image-to-3D.

Standalone Streamlit app. Run with `./run-wardrobe.sh`.

Tabs:
    1. Cutout      — drop background from any image (rembg / GrabCut fallback)
    2. Try-On      — drop a garment onto a person photo (Kolors API or local composite)
    3. Mockup      — paste a cutout onto preset/uploaded scenes with scale + position
    4. Image-to-3D — depth-map preview now, hands off to Pixal3D pipeline when wired
"""
from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import streamlit as st
from PIL import Image, ImageDraw, ImageFilter, ImageOps

HERE = Path(__file__).resolve().parent
MEDIA_DIR = HERE / "media"
OUT_DIR = HERE / "media" / "wardrobe_out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

MODELS_ROOT = HERE.parent  # /home/tom/models
PIXAL3D_DIR = MODELS_ROOT / "Pixal3D"
KOLORS_DIR = MODELS_ROOT / "Kolors-Virtual-Try-On"

# ----------------------------------------------------------------------------
# Optional heavy deps — import lazily; UI degrades gracefully if missing.
# ----------------------------------------------------------------------------

def _try(modname: str):
    try:
        return __import__(modname)
    except Exception:
        return None


# ----------------------------------------------------------------------------
# Image helpers
# ----------------------------------------------------------------------------

def pil_open(file) -> Image.Image:
    img = Image.open(file)
    img.load()
    return img


def png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def fit_within(img: Image.Image, max_side: int) -> Image.Image:
    w, h = img.size
    s = min(1.0, max_side / max(w, h))
    if s < 1.0:
        return img.resize((int(w * s), int(h * s)), Image.LANCZOS)
    return img


# ----------------------------------------------------------------------------
# Background removal
# ----------------------------------------------------------------------------

@st.cache_resource(show_spinner=False)
def _rembg_session(model: str):
    rembg = _try("rembg")
    if rembg is None:
        return None
    try:
        from rembg import new_session
        return new_session(model)
    except Exception as e:
        st.warning(f"rembg session failed for {model}: {e}")
        return None


def remove_bg_rembg(img: Image.Image, model: str = "u2net", alpha_matting: bool = False) -> Optional[Image.Image]:
    rembg = _try("rembg")
    if rembg is None:
        return None
    from rembg import remove
    sess = _rembg_session(model)
    if sess is None:
        return None
    out = remove(
        img,
        session=sess,
        alpha_matting=alpha_matting,
        alpha_matting_foreground_threshold=240,
        alpha_matting_background_threshold=10,
        alpha_matting_erode_size=10,
    )
    if isinstance(out, bytes):
        out = Image.open(io.BytesIO(out))
    return out.convert("RGBA")


def remove_bg_grabcut(img: Image.Image, iters: int = 5) -> Image.Image:
    """Fallback: OpenCV GrabCut on a centred rectangle. Decent for centred subjects."""
    cv2 = _try("cv2")
    if cv2 is None:
        # PIL-only last resort: threshold by luminance.
        gray = ImageOps.grayscale(img)
        mask = gray.point(lambda p: 255 if p < 240 else 0)
        rgba = img.convert("RGBA")
        rgba.putalpha(mask)
        return rgba

    rgb = np.array(img.convert("RGB"))
    h, w = rgb.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    bgd = np.zeros((1, 65), np.float64)
    fgd = np.zeros((1, 65), np.float64)
    pad = int(min(w, h) * 0.05)
    rect = (pad, pad, w - 2 * pad, h - 2 * pad)
    cv2.grabCut(rgb, mask, rect, bgd, fgd, iters, cv2.GC_INIT_WITH_RECT)
    fg = np.where((mask == 2) | (mask == 0), 0, 255).astype("uint8")
    rgba = np.dstack([rgb, fg])
    return Image.fromarray(rgba, "RGBA")


# ----------------------------------------------------------------------------
# Compositing
# ----------------------------------------------------------------------------

def composite(
    bg: Image.Image,
    fg_rgba: Image.Image,
    scale: float = 1.0,
    x_pct: float = 0.5,
    y_pct: float = 0.5,
    shadow: bool = True,
) -> Image.Image:
    bg = bg.convert("RGBA").copy()
    fg = fg_rgba.convert("RGBA")
    bw, bh = bg.size
    target_h = max(1, int(bh * scale))
    target_w = max(1, int(fg.size[0] * target_h / fg.size[1]))
    fg_r = fg.resize((target_w, target_h), Image.LANCZOS)
    cx = int(bw * x_pct - target_w / 2)
    cy = int(bh * y_pct - target_h / 2)

    if shadow:
        alpha = fg_r.split()[-1]
        sh = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
        sh.putalpha(alpha.point(lambda p: int(p * 0.55)))
        sh = sh.filter(ImageFilter.GaussianBlur(radius=max(4, target_h // 60)))
        bg.alpha_composite(sh, dest=(cx + max(4, target_h // 80), cy + max(6, target_h // 50)))

    bg.alpha_composite(fg_r, dest=(cx, cy))
    return bg


# ----------------------------------------------------------------------------
# Virtual try-on
# ----------------------------------------------------------------------------

def _kolors_env_ready() -> bool:
    return all(os.environ.get(k) for k in ("tryon_url", "token", "Cookie", "referer"))


def kolors_tryon(person: Image.Image, garment: Image.Image, seed: int = 0, timeout: int = 60) -> Optional[Image.Image]:
    """Call the Kolors-Virtual-Try-On remote endpoint (matches ../Kolors-Virtual-Try-On/app.py)."""
    if not _kolors_env_ready():
        return None
    import requests

    def b64(img: Image.Image) -> str:
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=92)
        return base64.b64encode(buf.getvalue()).decode("utf-8")

    url = "http://" + os.environ["tryon_url"]
    headers = {
        "Content-Type": "application/json",
        "token": os.environ["token"],
        "Cookie": os.environ["Cookie"],
        "referer": os.environ["referer"],
    }
    data = {"clothImage": b64(garment), "humanImage": b64(person), "seed": int(seed)}
    try:
        r = requests.post(url, headers=headers, data=json.dumps(data), timeout=timeout)
    except Exception as e:
        st.error(f"Kolors request failed: {e}")
        return None
    if r.status_code != 200:
        st.error(f"Kolors HTTP {r.status_code}")
        return None
    payload = r.json().get("result", {})
    if payload.get("status") != "success":
        st.error(f"Kolors status: {payload.get('status')}")
        return None
    raw = base64.b64decode(payload["result"])
    return Image.open(io.BytesIO(raw)).convert("RGB")


def local_tryon_fallback(person: Image.Image, garment: Image.Image, garment_cutout: Optional[Image.Image]) -> Image.Image:
    """When no Kolors creds: cutout the garment and composite on the person's torso area."""
    if garment_cutout is None:
        garment_cutout = remove_bg_rembg(garment, model="u2netp") or remove_bg_grabcut(garment)
    pw, ph = person.size
    # Heuristic torso placement: centered horizontally, 28%-78% vertical
    target_h = int(ph * 0.50)
    return composite(person, garment_cutout, scale=target_h / ph, x_pct=0.50, y_pct=0.55, shadow=False)


# ----------------------------------------------------------------------------
# Image-to-3D
# ----------------------------------------------------------------------------

def depth_preview(img: Image.Image) -> Image.Image:
    """Cheap pseudo-3D preview: edge-aware luminance gradient as a stand-in depth map."""
    gray = ImageOps.grayscale(img).filter(ImageFilter.GaussianBlur(2))
    edges = gray.filter(ImageFilter.FIND_EDGES)
    arr = np.array(gray, dtype=np.float32) * 0.85 + np.array(edges, dtype=np.float32) * 0.4
    arr = np.clip(arr, 0, 255).astype("uint8")
    depth = Image.fromarray(arr).convert("L")
    # Colorise (viridis-ish gradient)
    palette = []
    for i in range(256):
        t = i / 255.0
        r = int(255 * (0.267 + 0.733 * t**0.7))
        g = int(255 * (0.005 + 0.93 * t))
        b = int(255 * (0.33 + 0.67 * (1 - t) ** 1.5))
        palette.extend([r, g, b])
    depth.putpalette(palette)
    return depth.convert("RGB")


def pixal3d_launch_hint() -> str:
    if not PIXAL3D_DIR.exists():
        return f"Pixal3D not found at {PIXAL3D_DIR}"
    start = PIXAL3D_DIR / "start"
    if start.exists():
        return f"Launch: cd {PIXAL3D_DIR} && ./start"
    return f"Launch: cd {PIXAL3D_DIR} && python app.py"


# ----------------------------------------------------------------------------
# Streamlit UI
# ----------------------------------------------------------------------------

st.set_page_config(page_title="Wardrobe Studio", page_icon="🧥", layout="wide")
st.title("🧥 Wardrobe Studio")
st.caption("Cutout → Try-On → Mockup → 3D, all in one place.")

REMBG_OK = _try("rembg") is not None
KOLORS_OK = _kolors_env_ready()

with st.sidebar:
    st.subheader("Backends")
    st.write(f"rembg:    {'✅' if REMBG_OK else '❌ (using GrabCut fallback)'}")
    st.write(f"Kolors:   {'✅ remote' if KOLORS_OK else '❌ local composite fallback'}")
    st.write(f"Pixal3D:  {'✅ available' if PIXAL3D_DIR.exists() else '❌'}")
    st.markdown("---")
    rembg_model = st.selectbox(
        "rembg model",
        ["u2net", "u2netp", "u2net_human_seg", "isnet-general-use", "birefnet-general"],
        index=0,
        help="Picked on first use; downloaded to ~/.u2net/.",
    )
    alpha_matting = st.checkbox("Alpha matting (slower, cleaner edges)", value=False)
    st.markdown("---")
    st.caption("Outputs are written to `media/wardrobe_out/`.")

tab1, tab2, tab3, tab4 = st.tabs(["1 · Cutout", "2 · Try-On", "3 · Mockup", "4 · Image-to-3D"])

# ----------------------- TAB 1 — CUTOUT -----------------------
with tab1:
    st.subheader("Remove background")
    up = st.file_uploader("Image", type=["png", "jpg", "jpeg", "webp"], key="cut_up")
    col_l, col_r = st.columns(2)
    if up is not None:
        src = fit_within(pil_open(up), 1536).convert("RGB")
        with col_l:
            st.image(src, caption="Input", use_container_width=True)
        if st.button("Cut out", type="primary", key="cut_btn"):
            t0 = time.time()
            with st.spinner("Cutting…"):
                out = remove_bg_rembg(src, rembg_model, alpha_matting) if REMBG_OK else remove_bg_grabcut(src)
            dt = time.time() - t0
            if out is not None:
                with col_r:
                    st.image(out, caption=f"Cutout ({dt:.1f}s)", use_container_width=True)
                    name = OUT_DIR / f"cutout_{int(time.time())}.png"
                    name.write_bytes(png_bytes(out))
                    st.download_button("Download PNG", png_bytes(out), file_name=name.name, mime="image/png")
                    st.session_state["last_cutout"] = out
            else:
                st.error("Cutout failed.")

# ----------------------- TAB 2 — TRY-ON -----------------------
with tab2:
    st.subheader("Put a garment on a person")
    c1, c2, c3 = st.columns(3)
    with c1:
        person_up = st.file_uploader("Person photo", type=["png", "jpg", "jpeg", "webp"], key="ty_p")
    with c2:
        gar_up = st.file_uploader("Garment image", type=["png", "jpg", "jpeg", "webp"], key="ty_g")
    with c3:
        seed = st.number_input("Seed", min_value=0, max_value=999_999, value=0, step=1)
        randomize = st.checkbox("Random seed", value=True, key="ty_rand")
        prefer_remote = st.checkbox(
            "Use Kolors remote", value=KOLORS_OK,
            help="Requires tryon_url/token/Cookie/referer env vars (see ../Kolors-Virtual-Try-On/app.py)",
        )

    if person_up and gar_up:
        person = fit_within(pil_open(person_up), 1024).convert("RGB")
        garment = fit_within(pil_open(gar_up), 1024).convert("RGB")
        a, b, c = st.columns(3)
        with a:
            st.image(person, caption="Person", use_container_width=True)
        with b:
            st.image(garment, caption="Garment", use_container_width=True)
        if st.button("Run try-on", type="primary"):
            if randomize:
                import random
                seed = random.randint(0, 999_999)
                st.info(f"Seed used: {seed}")
            result = None
            if prefer_remote and KOLORS_OK:
                with st.spinner("Kolors remote try-on…"):
                    result = kolors_tryon(person, garment, seed=seed)
            if result is None:
                with st.spinner("Local composite fallback…"):
                    gar_cut = remove_bg_rembg(garment, rembg_model) if REMBG_OK else remove_bg_grabcut(garment)
                    result = local_tryon_fallback(person, garment, gar_cut)
            with c:
                st.image(result, caption="Result", use_container_width=True)
                out_path = OUT_DIR / f"tryon_{int(time.time())}.png"
                out_path.write_bytes(png_bytes(result))
                st.download_button("Download PNG", png_bytes(result), file_name=out_path.name, mime="image/png")

# ----------------------- TAB 3 — MOCKUP -----------------------
with tab3:
    st.subheader("Product mockup / ad composer")
    st.caption("Drop a cutout onto a background scene with scale + position controls.")
    m1, m2 = st.columns(2)
    with m1:
        cut_src = st.radio("Cutout source", ["Upload PNG", "Use last cutout"], horizontal=True)
        if cut_src == "Upload PNG":
            cu = st.file_uploader("Cutout (transparent PNG)", type=["png", "webp"], key="mk_cut")
            cut = pil_open(cu).convert("RGBA") if cu else None
        else:
            cut = st.session_state.get("last_cutout")
            if cut is None:
                st.info("Run Tab 1 first to produce a cutout, or upload a PNG.")
    with m2:
        bg_src = st.radio("Background source", ["Upload", "Solid color"], horizontal=True)
        if bg_src == "Upload":
            bu = st.file_uploader("Background image", type=["png", "jpg", "jpeg", "webp"], key="mk_bg")
            bg = pil_open(bu).convert("RGB") if bu else None
        else:
            hex_color = st.color_picker("Color", "#f4f1ec")
            w = st.number_input("Width", value=1280, min_value=256, max_value=4096, step=64)
            h = st.number_input("Height", value=1280, min_value=256, max_value=4096, step=64)
            bg = Image.new("RGB", (int(w), int(h)), hex_color)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        scale = st.slider("Scale", 0.05, 1.5, 0.6, 0.01)
    with c2:
        x_pct = st.slider("X %", 0.0, 1.0, 0.50, 0.01)
    with c3:
        y_pct = st.slider("Y %", 0.0, 1.0, 0.55, 0.01)
    with c4:
        shadow = st.checkbox("Drop shadow", value=True)

    if cut and bg:
        result = composite(bg, cut, scale=scale, x_pct=x_pct, y_pct=y_pct, shadow=shadow)
        st.image(result, caption="Mockup", use_container_width=True)
        out_path = OUT_DIR / f"mockup_{int(time.time())}.png"
        bytes_ = png_bytes(result)
        out_path.write_bytes(bytes_)
        st.download_button("Download PNG", bytes_, file_name=out_path.name, mime="image/png")

# ----------------------- TAB 4 — IMAGE-TO-3D -----------------------
with tab4:
    st.subheader("Image → 3D")
    st.caption(
        "Lightweight depth preview here. For real mesh/GS output, launch Pixal3D from its own venv."
    )
    up3 = st.file_uploader("Image", type=["png", "jpg", "jpeg", "webp"], key="d3_up")
    if up3:
        src = fit_within(pil_open(up3), 1024).convert("RGB")
        a, b = st.columns(2)
        with a:
            st.image(src, caption="Input", use_container_width=True)
        with b:
            depth = depth_preview(src)
            st.image(depth, caption="Depth preview (heuristic)", use_container_width=True)
            st.download_button(
                "Download depth PNG", png_bytes(depth), file_name="depth.png", mime="image/png"
            )
        with st.expander("Hand off to Pixal3D"):
            st.code(pixal3d_launch_hint(), language="bash")
            st.write(
                "Pixal3D needs its own venv (flash-attn + custom CUDA kernels). "
                "Drop the input image into its Gradio UI for a real mesh."
            )
            if PIXAL3D_DIR.exists() and st.button("Open Pixal3D dir in shell"):
                st.code(f"cd {PIXAL3D_DIR}", language="bash")

st.markdown("---")
st.caption(
    "Models referenced: rembg (U²-Net / BiRefNet), Kolors-Virtual-Try-On (remote), Pixal3D (image-to-3D)."
)
