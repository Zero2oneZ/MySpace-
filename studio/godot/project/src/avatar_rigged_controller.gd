# GENERATED from workflow_card: photo_to_avatar_rigged
# card_crystal: 04c7865e2553a0eed117aa75dd95ec7e45eec7ef8ee024d7a61612aa3891e673daa68368ec54a7fcdbac34ec605c746c076c0d90cddc5cc2dab7361b0074fb6b
# target: godot_gd
# schema: workflow_card_v0
# DO NOT EDIT BY HAND — regenerate via: cc workflow generate photo_to_avatar_rigged
extends Node3D
## Single photo (+ optional voice clip) → fully rigged avatar with sprite sheet + Godot scene. References real models in /home/tom/models. The flagship workflow that proves the four-s
## Summary: Single photo (+ optional voice clip) → fully rigged avatar with sprite sheet + Godot scene. References real models in /home/tom/models. The flagship workflow that proves the four-surface generation.

@export var photo: String = ""
@export var voice_clip: String = ""
@export var style_ref: String = ""

signal depth_done(result)
signal normals_done(result)
signal pose_done(result)
signal lift_3d_done(result)
signal faceswap_lock_done(result)
signal bake_pbr_done(result)
signal tts_synth_done(result)
signal sprite_compose_done(result)

const CARD_NAME: String = "photo_to_avatar_rigged"
const CARD_CRYSTAL: String = "04c7865e2553a0eed117aa75dd95ec7e45eec7ef8ee024d7a61612aa3891e673daa68368ec54a7fcdbac34ec605c746c076c0d90cddc5cc2dab7361b0074fb6b"
const LAYER_STACK: Dictionary = {
    "albedo": {"blend": "base", "source": "pass:bake_pbr", "uniform": "u_albedo"}
    "normal": {"blend": "normal_map", "source": "pass:bake_pbr", "uniform": "u_normal"}
    "ao": {"blend": "multiply", "source": "pass:bake_pbr", "uniform": "u_ao"}
    "depth": {"blend": "depth_uniform", "source": "pass:depth", "uniform": "u_depth"}
    "alpha": {"blend": "alpha", "source": "pass:faceswap_lock", "uniform": "u_alpha"}
    "opacity": {"blend": "opacity", "source": "literal:1.0", "uniform": "u_opacity"}
}

func _ready() -> void:
    print("[photo_to_avatar_rigged] booted — crystal=", CARD_CRYSTAL.substr(0, 16))
    if CCBridge != null:
        CCBridge.packet_received.connect(_on_cc_packet)
    await _run_pipeline()

func _run_pipeline() -> void:
    # pass: depth (apple_DepthPro via diffusers)
    var depth_result = await _dispatch_pass("depth", "apple_DepthPro", "diffusers")
    emit_signal("depth_done", depth_result)
    # pass: normals (marigold_normals via diffusers)
    var normals_result = await _dispatch_pass("normals", "marigold_normals", "diffusers")
    emit_signal("normals_done", normals_result)
    # pass: pose (qwen_anypose via diffusers)
    var pose_result = await _dispatch_pass("pose", "qwen_anypose", "diffusers")
    emit_signal("pose_done", pose_result)
    # pass: lift_3d (Pixal3D via diffusers)
    var lift_3d_result = await _dispatch_pass("lift_3d", "Pixal3D", "diffusers")
    emit_signal("lift_3d_done", lift_3d_result)
    # pass: faceswap_lock (Flux2_Klein_FaceSwap via comfyui)
    var faceswap_lock_result = await _dispatch_pass("faceswap_lock", "Flux2_Klein_FaceSwap", "comfyui")
    emit_signal("faceswap_lock_done", faceswap_lock_result)
    # pass: bake_pbr (blender_pbr_bake via blender)
    var bake_pbr_result = await _dispatch_pass("bake_pbr", "blender_pbr_bake", "blender")
    emit_signal("bake_pbr_done", bake_pbr_result)
    # pass: tts_synth (Qwen3_TTS_CustomVoice via diffusers)
    var tts_synth_result = await _dispatch_pass("tts_synth", "Qwen3_TTS_CustomVoice", "diffusers")
    emit_signal("tts_synth_done", tts_synth_result)
    # pass: sprite_compose (spriteforge_mcp via mcp)
    var sprite_compose_result = await _dispatch_pass("sprite_compose", "spriteforge_mcp", "mcp")
    emit_signal("sprite_compose_done", sprite_compose_result)

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
    print("[photo_to_avatar_rigged] cc packet: ", packet.get("pass_id", "?"))
