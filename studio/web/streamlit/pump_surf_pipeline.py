# GENERATED from workflow_card: pump_surf_pipeline
# card_crystal: 0dbb685dc6f60af4ac9c1026124cb36d2ceddf16ca55fb6f34301cbd8199177c31a77cdb7bad5e9a5f30551866ddf1cf7869112f262e75c966e2d8cbae9931e1
# target: streamlit
# schema: workflow_card_v0
# DO NOT EDIT BY HAND — regenerate via: cc workflow generate pump_surf_pipeline
"""Streamlit proto for pump_surf_pipeline."""
import streamlit as st
import json
from pathlib import Path

st.set_page_config(page_title="pump_surf_pipeline", layout="wide")
st.title("pump_surf_pipeline")
st.caption("End-to-end pump.fun behavioral-classifier + surf-executor pipeline. Streams Solana RPC logs (pump_stream_ingest) \u2192 extracts per-wallet behavioral features over a sliding window (pump_feature_extractor) \u2192 assigns GMM cluster + bot signature (pump_gmm_classifier) \u2192 applies the XGB binary gate against the human-inflow tide (pump_xgboost_gate) \u2192 routes the surviving GateDecisions through the surf executor (pump_surf_executor, DRY-RUN by default). Every pass anchors a trace_crystal; the final wave_frame_json + decisions feed the Streamlit live panel, the Godot pump_surf.tscn dashboard, and the /dapp/pump_surf route. The bot_density / human_inflow split rides the emission layer as additive sub-layers, mirroring the realestate light_field convention.")
st.code("card_crystal: 0dbb685dc6f60af4…", language="text")

st.subheader("Inputs")
with st.form("inputs"):
    rpc_wss = st.text_input("Rpc Wss", help="string")
    duration_seconds = st.text_input("Duration Seconds", help="int")
    live_trading_confirm = st.text_input("Live Trading Confirm", help="bool")
    submit = st.form_submit_button("Run pipeline")

if submit:
    st.subheader("Passes")
    with st.expander("pass: ingest_stream — pump_stream_ingest [deterministic] (ACTIVE)"):
        st.code("in: [] → out: raw_events_jsonl", language="text")
    with st.expander("pass: extract_features — pump_feature_extractor [deterministic] (ACTIVE)"):
        st.code("in: ['raw_events_jsonl'] → out: features_csv", language="text")
    with st.expander("pass: gmm_classify — pump_gmm_classifier [deterministic] (ACTIVE)"):
        st.code("in: ['features_csv'] → out: gmm_labels_csv", language="text")
    with st.expander("pass: xgb_gate — pump_xgboost_gate [deterministic] (ACTIVE)"):
        st.code("in: ['features_csv', 'gmm_labels_csv'] → out: gate_decisions", language="text")
    with st.expander("pass: surf_decision_loop — pump_surf_executor [deterministic] (ACTIVE)"):
        st.code("in: ['gate_decisions'] → out: surf_orders", language="text")
    st.success("Pipeline dispatched. See ~/.cc/inference_master_chain.jsonl for crystal trace.")
