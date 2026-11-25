"""Social Studio — cross-platform media distribution.

Upload videos, photos, audio from studio/media/ to YouTube, Telegram,
Facebook, and WhatsApp Business (official Cloud API).

Launch:
    cc -social              # via cc dispatch
    ./studio/run-social.sh  # direct
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import streamlit as st

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bootstrap, paths  # noqa: E402
bootstrap.ensure()

from auth.gate import require_login  # noqa: E402
from social.client import UploadClient  # noqa: E402

st.set_page_config(page_title="Social Studio", page_icon="📡", layout="wide")
_auth = require_login()

st.title("📡 Social Studio — distribute media")
st.caption(
    f"Upload from studio/media/ to YouTube · Telegram · Facebook · WhatsApp. "
    f"Signed in as **{_auth.user or '(solo)'}** from {_auth.ip}."
)

# ─── state ─────────────────────────────────────────────────────────────
if "social_results" not in st.session_state:
    st.session_state["social_results"] = []

# ─── file picker ───────────────────────────────────────────────────────
MEDIA_ROOT = paths.MEDIA_ROOT

# Discover media files recursively
def scan_media() -> list[Path]:
    exts = {".mp4", ".mov", ".avi", ".webm", ".mp3", ".wav", ".ogg", ".aac",
            ".jpg", ".jpeg", ".png", ".webp", ".gif", ".pdf", ".txt"}
    out: list[Path] = []
    for p in sorted(MEDIA_ROOT.rglob("*"), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.is_file() and p.suffix.lower() in exts and ".staging" not in str(p):
            out.append(p)
    return out[:200]

media_files = scan_media()

if not media_files:
    st.warning("No media files found in studio/media/. Add files or run intake.")
    st.stop()

file_labels = [str(p.relative_to(MEDIA_ROOT)) for p in media_files]
file_map = dict(zip(file_labels, media_files))

selected_label = st.selectbox("Pick a file", file_labels)
selected_path = file_map[selected_label]

# Sidecar preview
sidecar_path = selected_path.with_suffix(selected_path.suffix + ".json")
if not sidecar_path.exists():
    sidecar_path = selected_path.parent / (selected_path.stem + ".json")
sidecar: dict = {}
if sidecar_path.exists():
    try:
        sidecar = json.loads(sidecar_path.read_text())
    except Exception:
        pass

# ─── preview + metadata ──────────────────────────────────────────────
c1, c2 = st.columns([2, 3])
with c1:
    if selected_path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        st.image(str(selected_path), use_container_width=True)
    elif selected_path.suffix.lower() in {".mp4", ".mov", ".avi", ".webm"}:
        st.video(str(selected_path))
    else:
        st.write(f"`{selected_path.name}` ({selected_path.stat().st_size / 1e6:.1f} MB)")

with c2:
    st.subheader("Metadata")
    title = st.text_input("Title", value=sidecar.get("label") or sidecar.get("title") or selected_path.stem)
    description = st.text_area("Description", value=sidecar.get("description", ""), height=80)
    tags_str = st.text_input("Tags (comma-separated)", value=", ".join(sidecar.get("tags", [])))
    tags = [t.strip() for t in tags_str.split(",") if t.strip()]

# ─── platform toggles ────────────────────────────────────────────────
st.divider()
st.subheader("Platforms")

platforms: list[str] = []
row1 = st.columns(3)
with row1[0]:
    if st.toggle("YouTube", help="Needs youtube_access_token in .env"):
        platforms.append("youtube")
with row1[1]:
    if st.toggle("Telegram", help="Needs telegram_bot_token + telegram_chat_id in .env"):
        platforms.append("telegram")
with row1[2]:
    if st.toggle("Facebook", help="Needs facebook_page_token + facebook_page_id in .env"):
        platforms.append("facebook")
row2 = st.columns(3)
with row2[0]:
    if st.toggle("WhatsApp", help="Needs whatsapp_business_token + whatsapp_phone_number_id in .env"):
        platforms.append("whatsapp")
with row2[1]:
    if st.toggle("Discord", help="Needs discord_webhook_url or discord_token + channel_id in .env"):
        platforms.append("discord")
with row2[2]:
    if st.toggle("Twitch", help="Needs twitch_access_token + twitch_client_id + broadcaster_id in .env"):
        platforms.append("twitch")
row3 = st.columns(3)
with row3[0]:
    if st.toggle("OnlyFans", help="No public API — returns instructions"):
        platforms.append("onlyfans")
with row3[1]:
    if st.toggle("Twilio", help="Needs twilio_account_sid + twilio_auth_token + twilio_from_phone + twilio_to_phone in .env"):
        platforms.append("twilio")
with row3[2]:
    if st.toggle("TikTok", help="Needs tiktok_access_token + public video URL"):
        platforms.append("tiktok")

# ─── upload button ─────────────────────────────────────────────────────
st.divider()
if st.button("🚀 Upload", type="primary", use_container_width=True, disabled=not platforms):
    client = UploadClient()
    with st.spinner(f"Uploading to {', '.join(platforms)}…"):
        results = client.upload(
            selected_path,
            platforms=platforms,
            title=title,
            description=description,
            tags=tags,
        )
    st.session_state["social_results"] = results

# ─── results ───────────────────────────────────────────────────────────
results = st.session_state.get("social_results", [])
if results:
    st.divider()
    st.subheader("Results")
    for r in results:
        if r.success:
            if r.url:
                st.success(f"**{r.platform}** → [{r.url}]({r.url})")
            else:
                st.success(f"**{r.platform}** → OK (no public URL)")
        else:
            st.error(f"**{r.platform}** → {r.error}")

# ─── recent log ──────────────────────────────────────────────────────
log_path = paths.LOGS_ROOT / "social_uploads.jsonl"
if log_path.exists():
    st.divider()
    st.subheader("Recent uploads")
    lines = log_path.read_text().strip().splitlines()
    for ln in reversed(lines[-10:]):
        try:
            entry = json.loads(ln)
            icon = "✅" if entry.get("success") else "❌"
            st.write(f"{icon} {entry['ts']} · **{entry['platform']}** · `{entry['title']}`")
        except Exception:
            pass

# ─── OAuth connect section ─────────────────────────────────────────────
st.divider()
st.subheader("OAuth Connect")
st.caption("Click to connect your accounts via OAuth 2.0")

oauth_platforms = ["google", "x", "facebook", "discord", "twitch", "tiktok"]
bridge_base = os.environ.get("MYSPACE_BRIDGE_URL", "http://localhost:8765")

for plat in oauth_platforms:
    c1, c2 = st.columns([1, 3])
    with c1:
        if st.button(f"Connect {plat.title()}", key=f"oauth_{plat}"):
            try:
                import urllib.request, json
                req = urllib.request.Request(f"{bridge_base}/oauth/start/{plat}")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode())
                if "auth_url" in data:
                    import webbrowser
                    webbrowser.open(data["auth_url"])
                    st.toast(f"Opened {plat} auth in browser")
                else:
                    st.error(f"{plat}: {data.get('error', 'unknown error')}")
            except Exception as e:
                st.error(f"{plat} start failed: {e}")
    with c2:
        st.caption(f"Redirect: {bridge_base}/oauth/callback/{plat}")

# Show OAuth status
if st.button("Refresh OAuth status"):
    try:
        import urllib.request, json
        req = urllib.request.Request(f"{bridge_base}/oauth/status")
        with urllib.request.urlopen(req, timeout=10) as resp:
            tokens = json.loads(resp.read().decode())
        if tokens:
            st.json(tokens)
        else:
            st.info("No OAuth tokens stored yet.")
    except Exception as e:
        st.error(f"Status check failed: {e}")

# ─── footer ──────────────────────────────────────────────────────────
st.markdown("---")
st.caption(
    "Tip: set platform keys in .env, then reload the app. "
    "Use `cc -social` to launch this page from the terminal."
)
