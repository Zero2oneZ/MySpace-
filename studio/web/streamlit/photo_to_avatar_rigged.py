
# GENERATED from workflow_card: photo_to_avatar_rigged
# card_crystal: 04c7865e2553a0eed117aa75dd95ec7e45eec7ef8ee024d7a61612aa3891e673daa68368ec54a7fcdbac34ec605c746c076c0d90cddc5cc2dab7361b0074fb6b
# target: streamlit
# schema: workflow_card_v0
# DO NOT EDIT BY HAND — regenerate via: cc workflow generate photo_to_avatar_rigged
"""Streamlit prototype for photo_to_avatar_rigged (avatar)."""

import json
import time
from pathlib import Path

import streamlit as st


# ---------------------------------------------------------------------------
# Page chrome
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="photo_to_avatar_rigged",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("photo_to_avatar_rigged")
st.caption("category: **avatar**  ·  state: **active**  ·  version: **v0**")

st.write("Single photo (+ optional voice clip) \u2192 fully rigged avatar with sprite sheet + Godot scene. References real models in /home/tom/models. The flagship workflow that proves the four-surface generation.")

st.code("card_crystal: 04c7865e2553a0eed117aa75…", language="text")

st.divider()


# ---------------------------------------------------------------------------
# Sidebar — layer_stack (hypershade vocabulary)
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("layer_stack")
    st.caption("Hypershade / Photoshop vocabulary — drives Godot uniforms, Blender sockets, ComfyUI mix nodes.")
    layer_rows = [
        {
            "name":   "albedo",
            "source": "pass:bake_pbr",
            "blend":  "base",
            "uniform": "u_albedo",
        },
        {
            "name":   "normal",
            "source": "pass:bake_pbr",
            "blend":  "normal_map",
            "uniform": "u_normal",
        },
        {
            "name":   "ao",
            "source": "pass:bake_pbr",
            "blend":  "multiply",
            "uniform": "u_ao",
        },
        {
            "name":   "depth",
            "source": "pass:depth",
            "blend":  "depth_uniform",
            "uniform": "u_depth",
        },
        {
            "name":   "alpha",
            "source": "pass:faceswap_lock",
            "blend":  "alpha",
            "uniform": "u_alpha",
        },
        {
            "name":   "opacity",
            "source": "literal:1.0",
            "blend":  "opacity",
            "uniform": "u_opacity",
        },
    ]
    if layer_rows:
        st.dataframe(layer_rows, hide_index=True, use_container_width=True)
    else:
        st.info("No layer_stack declared on this card.")

    st.divider()
    st.subheader("surfaces")
    surface_keys = [
        "streamlit",
        "godot",
        "blender",
        "spriteforge",
        "comfyui",
    ]
    for sk in surface_keys:
        st.markdown(f"- `{sk}`")


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
st.subheader("Inputs")

inputs_state = {}

with st.form("workflow_inputs"):
    inputs_state["photo"] = st.file_uploader(
        "Photo  (required)",
        type=["png", "jpg", "jpeg", "webp"],
        help="type: image/jpeg|png \u00b7 max_mb=25",
        key="in_photo",
    )
    inputs_state["voice_clip"] = st.file_uploader(
        "Voice Clip",
        type=["wav", "mp3", "flac", "ogg"],
        help="type: audio/wav|mp3 \u00b7 max_mb=50",
        key="in_voice_clip",
    )
    inputs_state["style_ref"] = st.file_uploader(
        "Style Ref",
        type=["png", "jpg", "jpeg", "webp"],
        help="type: image|workflow_ref",
        key="in_style_ref",
    )

    submit = st.form_submit_button("Execute pipeline", type="primary", use_container_width=True)


# ---------------------------------------------------------------------------
# Pipeline execution — pass-by-pass progress via st.status
# ---------------------------------------------------------------------------
PASSES = [
    {
        "id":     "depth",
        "agent":  "apple_DepthPro",
        "engine": "diffusers",
        "in":     ["photo"],
        "out":    "depth_map",
        "status": "ACTIVE",
        "model_path": "/home/tom/models/apple_DepthPro",
        "tier":   "medium",
        "vram_gb": 4,
    },
    {
        "id":     "normals",
        "agent":  "marigold_normals",
        "engine": "diffusers",
        "in":     ["photo"],
        "out":    "normal_map",
        "status": "ACTIVE",
        "model_path": "/home/tom/models/prs-eth_marigold-normals-v0-1",
        "tier":   "medium",
        "vram_gb": 6,
    },
    {
        "id":     "pose",
        "agent":  "qwen_anypose",
        "engine": "diffusers",
        "in":     ["photo"],
        "out":    "pose_landmarks",
        "status": "ACTIVE",
        "model_path": "/home/tom/models/Qwen-Edit-AnyPose",
        "tier":   "medium",
    },
    {
        "id":     "lift_3d",
        "agent":  "Pixal3D",
        "engine": "diffusers",
        "in":     ["photo", "depth_map", "normal_map"],
        "out":    "mesh_3d_raw",
        "status": "ACTIVE",
        "model_path": "/home/tom/models/TencentARC_Pixal3D",
        "tier":   "large",
        "vram_gb": 16,
    },
    {
        "id":     "faceswap_lock",
        "agent":  "Flux2_Klein_FaceSwap",
        "engine": "comfyui",
        "in":     ["photo", "mesh_3d_raw"],
        "out":    "identity_locked_albedo",
        "status": "IN-FLIGHT",
        "model_path": "/home/tom/models/Flux2-Klein-Face-Swap",
        "tier":   "large",
        "vram_gb": 18,
    },
    {
        "id":     "bake_pbr",
        "agent":  "blender_pbr_bake",
        "engine": "blender",
        "in":     ["mesh_3d_raw", "identity_locked_albedo", "normal_map", "depth_map"],
        "out":    ["albedo_baked", "normal_baked", "ao_baked"],
        "status": "IN-FLIGHT",
        "tier":   "medium",
    },
    {
        "id":     "tts_synth",
        "agent":  "Qwen3_TTS_CustomVoice",
        "engine": "diffusers",
        "in":     ["voice_clip"],
        "out":    "voice_synth",
        "status": "ACTIVE",
        "model_path": "/home/tom/models/Qwen3-TTS-12Hz-1.7B-CustomVoice",
        "tier":   "medium",
        "vram_gb": 4,
        "optional": True,
    },
    {
        "id":     "sprite_compose",
        "agent":  "spriteforge_mcp",
        "engine": "mcp",
        "in":     ["albedo_baked", "normal_baked", "ao_baked"],
        "out":    "sprite_sheet",
        "status": "ACTIVE",
        "tier":   "medium",
    },
]


def _run_pass(p):
    """Stub dispatch — real generator wires this into ~/.cc/inference_master_chain.jsonl."""
    time.sleep(0.25)
    return {
        "pass_id": p["id"],
        "agent":   p["agent"],
        "engine":  p["engine"],
        "status":  p["status"],
        "out":     p["out"],
    }


pipeline_results = {}

if submit:
    st.subheader("Execution")

    # Validate required inputs
    required_missing = [
        "photo",
    ]
    missing = [k for k in required_missing if not inputs_state.get(k)]
    if missing:
        st.error(f"Missing required inputs: {', '.join(missing)}")
        st.stop()

    for p in PASSES:
        label = f"pass: {p['id']} — {p['agent']} [{p['engine']}] ({p['status']})"
        with st.status(label, expanded=False) as status:
            st.write(f"in:  {p['in']}")
            st.write(f"out: {p['out']}")
            if p.get("optional"):
                st.caption("(optional pass)")
            if p["status"] == "STUB":
                status.update(label=label + "  — SKIPPED (stub)", state="error")
                continue
            result = _run_pass(p)
            pipeline_results[p["id"]] = result
            status.update(
                label=label + "  — done",
                state="complete" if p["status"] == "ACTIVE" else "running",
            )

    st.success("Pipeline dispatched. Trace at ~/.cc/inference_master_chain.jsonl")


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------
with st.expander("Outputs", expanded=bool(pipeline_results)):
    st.markdown("**rigged_mesh**  ·  type: `gltf|fbx`")
    _out_payload = pipeline_results.get("rigged_mesh")
    if _out_payload:
        st.json(_out_payload)
    else:
        st.caption("_(no payload yet)_")
    st.markdown("---")
    st.markdown("**sprite_sheet**  ·  type: `png_atlas+manifest`")
    _out_payload = pipeline_results.get("sprite_sheet") or {}
    _out_path = _out_payload.get("artifact_path")
    if _out_path and Path(_out_path).exists():
        st.image(_out_path, caption="sprite_sheet")
    else:
        st.caption("_(no artifact yet — run pipeline)_")
    st.markdown("---")
    st.markdown("**godot_scene**  ·  type: `tscn`")
    _out_payload = pipeline_results.get("godot_scene")
    if _out_payload:
        st.json(_out_payload)
    else:
        st.caption("_(no payload yet)_")
    st.markdown("---")
    st.markdown("**voice_synth**  ·  type: `audio/wav`")
    _out_payload = pipeline_results.get("voice_synth") or {}
    _out_path = _out_payload.get("artifact_path")
    if _out_path and Path(_out_path).exists():
        st.audio(_out_path)
    else:
        st.caption("_(no audio artifact yet)_")
    st.markdown("---")


# ---------------------------------------------------------------------------
# Footer — depends_on crystals
# ---------------------------------------------------------------------------
st.divider()
st.caption("**depends_on** — upstream crystal hashes this card references")
DEPENDS_ON = [
]
if DEPENDS_ON:
    for dep in DEPENDS_ON:
        st.code(dep, language="text")
else:
    st.caption("_(no upstream crystal dependencies)_")

st.caption(
    "card: `vm_mspc_001` · `photo_to_avatar_rigged` · `v0`  ·  "
    "schema: `workflow_card_v0`  ·  card_crystal: `04c7865e2553a0ee…`"
)
