# GENERATED from workflow_card: pump_surf_pipeline
# card_crystal: 0dbb685dc6f60af4ac9c1026124cb36d2ceddf16ca55fb6f34301cbd8199177c31a77cdb7bad5e9a5f30551866ddf1cf7869112f262e75c966e2d8cbae9931e1
# target: godot_gd
# schema: workflow_card_v0
# DO NOT EDIT BY HAND — regenerate via: cc workflow generate pump_surf_pipeline
extends Node3D
## End-to-end pump.fun behavioral-classifier + surf-executor pipeline. Streams Solana RPC logs (pump_stream_ingest) → extracts per-wallet behavioral features over a sliding window (pu
## Summary: End-to-end pump.fun behavioral-classifier + surf-executor pipeline. Streams Solana RPC logs (pump_stream_ingest) → extracts per-wallet behavioral features over a sliding window (pump_feature_extractor

@export var rpc_wss: String = ""
@export var duration_seconds: String = ""
@export var live_trading_confirm: String = ""

signal ingest_stream_done(result)
signal extract_features_done(result)
signal gmm_classify_done(result)
signal xgb_gate_done(result)
signal surf_decision_loop_done(result)

const CARD_NAME: String = "pump_surf_pipeline"
const CARD_CRYSTAL: String = "0dbb685dc6f60af4ac9c1026124cb36d2ceddf16ca55fb6f34301cbd8199177c31a77cdb7bad5e9a5f30551866ddf1cf7869112f262e75c966e2d8cbae9931e1"
const LAYER_STACK: Dictionary = {
    "albedo": {"blend": "base", "source": "pass:gmm_classify", "uniform": "u_albedo"}
    "normal": {"blend": "normal_map", "source": "pass:extract_features", "uniform": "u_normal"}
    "ao": {"blend": "multiply", "source": "pass:gmm_classify", "uniform": "u_ao"}
    "depth": {"blend": "depth_uniform", "source": "pass:xgb_gate", "uniform": "u_depth"}
    "alpha": {"blend": "alpha", "source": "pass:xgb_gate", "uniform": "u_alpha"}
    "opacity": {"blend": "opacity", "source": "literal:1.0", "uniform": "u_opacity"}
    "emission": {"blend": "additive", "source": "pass:xgb_gate", "uniform": "u_emission"}
}

func _ready() -> void:
    print("[pump_surf_pipeline] booted — crystal=", CARD_CRYSTAL.substr(0, 16))
    if CCBridge != null:
        CCBridge.packet_received.connect(_on_cc_packet)
    await _run_pipeline()

func _run_pipeline() -> void:
    # pass: ingest_stream (pump_stream_ingest via deterministic)
    var ingest_stream_result = await _dispatch_pass("ingest_stream", "pump_stream_ingest", "deterministic")
    emit_signal("ingest_stream_done", ingest_stream_result)
    # pass: extract_features (pump_feature_extractor via deterministic)
    var extract_features_result = await _dispatch_pass("extract_features", "pump_feature_extractor", "deterministic")
    emit_signal("extract_features_done", extract_features_result)
    # pass: gmm_classify (pump_gmm_classifier via deterministic)
    var gmm_classify_result = await _dispatch_pass("gmm_classify", "pump_gmm_classifier", "deterministic")
    emit_signal("gmm_classify_done", gmm_classify_result)
    # pass: xgb_gate (pump_xgboost_gate via deterministic)
    var xgb_gate_result = await _dispatch_pass("xgb_gate", "pump_xgboost_gate", "deterministic")
    emit_signal("xgb_gate_done", xgb_gate_result)
    # pass: surf_decision_loop (pump_surf_executor via deterministic)
    var surf_decision_loop_result = await _dispatch_pass("surf_decision_loop", "pump_surf_executor", "deterministic")
    emit_signal("surf_decision_loop_done", surf_decision_loop_result)

func _dispatch_pass(pass_id: String, agent: String, engine: String) -> Variant:
    # Dispatches via CCBridge → task_queue → appropriate pool.
    if CCBridge == null: return null
    var packet := {
        "protocol": "cc_godot_bridge_v1",
        "card_crystal": CARD_CRYSTAL,
        "pass_id": pass_id,
        "agent": agent,
        "engine": engine,
    }
    return await CCBridge.dispatch(packet)

func _on_cc_packet(packet: Dictionary) -> void:
    print("[pump_surf_pipeline] cc packet: ", packet.get("pass_id", "?"))
