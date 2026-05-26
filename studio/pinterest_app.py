"""pinterest_app.py — Streamlit page for searching Pinterest + auto-saving
the picks into studio/media/ with sidecar metadata.

Launch:
    cc -pinterest             # via cc dispatch
    ./studio/run-pinterest.sh # direct (writes its own port)
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import streamlit as st

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from auth.gate import require_login  # noqa: E402
from pinterest.client import PinterestClient, PinResult  # noqa: E402

# Sidecar tooling
sys.path.insert(0, str(HERE / "media" / ".tools"))
import sidecar  # noqa: E402

MEDIA_ROOT = HERE / "media"
PROCESS_PY = MEDIA_ROOT / ".tools" / "process.py"


st.set_page_config(page_title="Pinterest Search", page_icon="📌", layout="wide")
_auth = require_login()

st.title("📌 Pinterest Search → Media")
st.caption(
    f"Search Pinterest, save picks, auto-classify into studio/media/. "
    f"Signed in as **{_auth.user or '(solo)'}** from {_auth.ip}."
)


# ─── state ─────────────────────────────────────────────────────────────
if "pin_results" not in st.session_state:
    st.session_state["pin_results"] = []
if "pin_query" not in st.session_state:
    st.session_state["pin_query"] = ""


# ─── search controls ───────────────────────────────────────────────────
col_q, col_n, col_btn = st.columns([5, 1, 1])
with col_q:
    query = st.text_input("Search Pinterest",
                          value=st.session_state["pin_query"],
                          placeholder="red dress, mid-century chair, …")
with col_n:
    limit = st.number_input("Limit", min_value=1, max_value=50, value=15, step=1)
with col_btn:
    st.write("")
    if st.button("Search", type="primary", use_container_width=True):
        try:
            with st.spinner("Searching Pinterest…"):
                c = PinterestClient()
                st.session_state["pin_results"] = c.search(query, limit=int(limit))
                st.session_state["pin_query"] = query
        except Exception as e:
            st.error(f"Search failed: {e}")


# ─── intake side panel ────────────────────────────────────────────────
with st.sidebar:
    st.subheader("Intake options")
    bg_remove = st.checkbox("Background remove on save", value=True)
    use_label = st.selectbox(
        "Mark this asset as", ["sample", "training", "mask",
                               "3d-input", "reference", "unspecified"],
        index=0,
    )
    custom_label = st.text_input("Override label",
                                 placeholder="leave blank to use pin title")
    custom_dest  = st.text_input("Override category",
                                 placeholder="e.g. Cloths/Female/Tops")
    st.markdown("---")
    st.caption(
        "Pins auto-route through `studio/media/.tools/process.py` for "
        "category detection, optional bg-remove, and sidecar metadata."
    )


# ─── results grid ──────────────────────────────────────────────────────
results: list[PinResult] = st.session_state["pin_results"]

if results:
    st.markdown(f"**{len(results)} results** for `{st.session_state['pin_query']}`")
    cols_per_row = 4
    rows = [results[i:i + cols_per_row] for i in range(0, len(results), cols_per_row)]
    for row in rows:
        cols = st.columns(cols_per_row)
        for col, pin in zip(cols, row):
            with col:
                try:
                    st.image(pin.image_url, use_container_width=True,
                             caption=(pin.title or pin.description)[:80])
                except Exception:
                    st.write(f"(image unavailable: {pin.pin_id})")
                if st.button("Save", key=f"save_{pin.pin_id}"):
                    try:
                        c = PinterestClient()
                        with st.spinner("Downloading + classifying…"):
                            result = c.download_pin(
                                pin,
                                dest_subpath=custom_dest or None,
                                bg_remove=bg_remove,
                            )
                            # Write sidecar with rich metadata.
                            label = custom_label or pin.title or pin.description[:50] or "pinterest"
                            descr = pin.description or pin.title or ""
                            # Find the landed file: best-effort scan in the
                            # category dir, or trust result['path'] for local.
                            if result.get("mode") == "local":
                                landed = Path(result["path"])
                                if landed.exists():
                                    sidecar.write(landed,
                                        sha=sidecar.content_sha(landed),
                                        source_url=pin.source_url or pin.image_url,
                                        source_kind="pinterest",
                                        category=custom_dest or "",
                                        label=label, description=descr,
                                        tags=pin.tags + ([use_label] if use_label != "unspecified" else []),
                                        uses=[use_label] if use_label != "unspecified" else [],
                                    )
                        st.success(f"Saved: {label}")
                    except Exception as e:
                        st.error(f"Save failed: {e}")
elif st.session_state["pin_query"]:
    st.info("No results.")
else:
    st.info("Enter a query above to search Pinterest.")


# ─── footer: tip + intake links ────────────────────────────────────────
st.markdown("---")
st.caption(
    "Tip: anything you save lands under `studio/media/<category>/` with a "
    "`.json` sidecar containing label, description, source, tags, and `uses`. "
    "Use `cc -intake <file>` to classify any other file you drop into the tree."
)
