# GENERATED from workflow_card: realestate_walkthrough_full
# card_crystal: 4b5b9c4a5d3b5600c71da2e80b4346997284960d3202f11cb32ed05db348219fca89e0b61a08a18550d9d8db72d2ea8297d367804789e33bf0c239f88b3ef835
# target: streamlit
# schema: workflow_card_v0
# DO NOT EDIT BY HAND — regenerate via: cc workflow generate realestate_walkthrough_full
"""Streamlit proto for realestate_walkthrough_full."""
import streamlit as st
import json
from pathlib import Path

st.set_page_config(page_title="realestate_walkthrough_full", layout="wide")
st.title("realestate_walkthrough_full")
st.caption("The master integration card. Exercises every substrate built in this session: Pinterest harvest \u2192 SVG embed \u2192 light source extraction \u2192 frame clock alignment \u2192 spatial anchor \u2192 dataset FBX selection \u2192 Blender MCP modeling \u2192 ComfyUI render \u2192 Remotion video compose \u2192 Godot scene + GDExtension. The friend's real-estate walkthrough rendered as a fully-determined chain of crystal-anchored passes.")
st.code("card_crystal: 4b5b9c4a5d3b5600…", language="text")

st.subheader("Inputs")
with st.form("inputs"):
    room_id = st.text_input("Room Id", help="string")
    # required: room_id
    pinterest_category = st.text_input("Pinterest Category", help="string")
    animation_category = st.text_input("Animation Category", help="string")
    fps = st.text_input("Fps", help="int")
    wall_distances_m = st.text_input("Wall Distances M", help="list[float]")
    submit = st.form_submit_button("Run pipeline")

if submit:
    st.subheader("Passes")
    with st.expander("pass: harvest_pinterest_interior — pinterest_connector [deterministic] (ACTIVE)"):
        st.code("in: [] → out: pinterest_pins", language="text")
    with st.expander("pass: embed_local_svgs — svg_vector_embed [deterministic] (ACTIVE)"):
        st.code("in: [] → out: svg_index", language="text")
    with st.expander("pass: extract_lights_from_shapes — light_source [deterministic] (ACTIVE)"):
        st.code("in: ['svg_index'] → out: light_field", language="text")
    with st.expander("pass: frame_clock_anchor — frame_clock [deterministic] (ACTIVE)"):
        st.code("in: [] → out: frame_anchor", language="text")
    with st.expander("pass: spatial_anchor_room — spatial_anchor [deterministic] (ACTIVE)"):
        st.code("in: [] → out: room_anchor", language="text")
    with st.expander("pass: select_mixamo_idle — dataset_select_fbx [deterministic] (ACTIVE)"):
        st.code("in: [] → out: rigged_fbx", language="text")
    with st.expander("pass: blender_assemble — blender_mcp [blender] (IN-FLIGHT)"):
        st.code("in: ['rigged_fbx', 'light_field', 'room_anchor', 'frame_anchor'] → out: blender_scene", language="text")
    with st.expander("pass: comfy_render_avatar — ComfyUI [comfyui] (IN-FLIGHT)"):
        st.code("in: ['rigged_fbx', 'light_field'] → out: avatar_frames", language="text")
    with st.expander("pass: remotion_compose — remotion [remotion] (IN-FLIGHT)"):
        st.code("in: ['avatar_frames', 'blender_scene', 'frame_anchor'] → out: walkthrough_video", language="text")
    with st.expander("pass: hf_describe_room — hf_inference [hf] (ACTIVE)"):
        st.code("in: ['room_anchor', 'light_field'] → out: room_caption", language="text")
    st.success("Pipeline dispatched. See ~/.cc/inference_master_chain.jsonl for crystal trace.")
