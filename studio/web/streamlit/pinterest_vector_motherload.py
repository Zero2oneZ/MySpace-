# GENERATED from workflow_card: pinterest_vector_motherload
# card_crystal: e2bf15622bcc5b7f6d15b10c5b3c13446c499d89701c47ba797d90e89ef1e96974766065f31b5e974fe5948d19cb49724e9033481afe927f1ad25f967911b46a
# target: streamlit
# schema: workflow_card_v0
# DO NOT EDIT BY HAND — regenerate via: cc workflow generate pinterest_vector_motherload
"""Streamlit proto for pinterest_vector_motherload."""
import streamlit as st
import json
from pathlib import Path

st.set_page_config(page_title="pinterest_vector_motherload", layout="wide")
st.title("pinterest_vector_motherload")
st.caption("Mine Pinterest for vector graphic source URLs (SVG, illustration, icon, logo, infographic). For each pin whose source_url points at fetchable vector content (github raw .svg, codepen, figma public, raw SVG endpoints), download + parse + embed every <path d='...'> via svg_vector_embed. Every harvested path becomes a crystal-anchored node in ~/.cc/svg_index.jsonl, joinable across all 5 MoE retrieval axes.")
st.code("card_crystal: e2bf15622bcc5b7f…", language="text")

st.subheader("Inputs")
with st.form("inputs"):
    categories = st.text_input("Categories", help="list[str]")
    queries_per_cat = st.text_input("Queries Per Cat", help="int")
    pins_per_query = st.text_input("Pins Per Query", help="int")
    fetch_external = st.text_input("Fetch External", help="bool")
    submit = st.form_submit_button("Run pipeline")

if submit:
    st.subheader("Passes")
    with st.expander("pass: harvest_pins — pinterest_connector [mcp] (ACTIVE)"):
        st.code("in: ['categories'] → out: pins_with_source_urls", language="text")
    with st.expander("pass: filter_vector_sources — url_filter [deterministic] (TEXT-PLACEHOLDER)"):
        st.code("in: ['pins_with_source_urls'] → out: vector_candidate_urls", language="text")
    with st.expander("pass: fetch_svg_content — url_fetcher [deterministic] (TEXT-PLACEHOLDER)"):
        st.code("in: ['vector_candidate_urls'] → out: svg_files_on_disk", language="text")
    with st.expander("pass: embed_svg_paths — svg_vector_embed [deterministic] (ACTIVE)"):
        st.code("in: ['svg_files_on_disk'] → out: svg_index_jsonl", language="text")
    with st.expander("pass: link_to_crystal_chain — inference_logger [deterministic] (TEXT-PLACEHOLDER)"):
        st.code("in: ['svg_index_jsonl'] → out: joined_chain", language="text")
    st.success("Pipeline dispatched. See ~/.cc/inference_master_chain.jsonl for crystal trace.")
