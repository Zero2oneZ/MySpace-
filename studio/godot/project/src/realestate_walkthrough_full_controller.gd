# GENERATED from workflow_card: realestate_walkthrough_full
# card_crystal: 4b5b9c4a5d3b5600c71da2e80b4346997284960d3202f11cb32ed05db348219fca89e0b61a08a18550d9d8db72d2ea8297d367804789e33bf0c239f88b3ef835
# target: godot_gd
# schema: workflow_card_v0
# DO NOT EDIT BY HAND — regenerate via: cc workflow generate realestate_walkthrough_full
extends Node3D
## The master integration card. Exercises every substrate built in this session: Pinterest harvest → SVG embed → light source extraction → frame clock alignment → spatial anchor → dat
## Summary: The master integration card. Exercises every substrate built in this session: Pinterest harvest → SVG embed → light source extraction → frame clock alignment → spatial anchor → dataset FBX selection →

@export var room_id: String = ""
@export var pinterest_category: String = ""
@export var animation_category: String = ""
@export var fps: String = ""
@export var wall_distances_m: String = ""

signal harvest_pinterest_interior_done(result)
signal embed_local_svgs_done(result)
signal extract_lights_from_shapes_done(result)
signal frame_clock_anchor_done(result)
signal spatial_anchor_room_done(result)
signal select_mixamo_idle_done(result)
signal blender_assemble_done(result)
signal comfy_render_avatar_done(result)
signal remotion_compose_done(result)
signal hf_describe_room_done(result)

const CARD_NAME: String = "realestate_walkthrough_full"
const CARD_CRYSTAL: String = "4b5b9c4a5d3b5600c71da2e80b4346997284960d3202f11cb32ed05db348219fca89e0b61a08a18550d9d8db72d2ea8297d367804789e33bf0c239f88b3ef835"
const LAYER_STACK: Dictionary = {
    "albedo": {"blend": "base", "source": "pass:embed_local_svgs", "uniform": "u_albedo"}
    "normal": {"blend": "normal_map", "source": "pass:blender_assemble", "uniform": "u_normal"}
    "ao": {"blend": "multiply", "source": "pass:blender_assemble", "uniform": "u_ao"}
    "depth": {"blend": "depth_uniform", "source": "pass:spatial_anchor_room", "uniform": "u_depth"}
    "alpha": {"blend": "alpha", "source": "literal:1.0", "uniform": "u_alpha"}
    "opacity": {"blend": "opacity", "source": "literal:1.0", "uniform": "u_opacity"}
    "emission": {"blend": "additive", "source": "pass:extract_lights_from_shapes", "uniform": "u_emission"}
}

func _ready() -> void:
    print("[realestate_walkthrough_full] booted — crystal=", CARD_CRYSTAL.substr(0, 16))
    if CCBridge != null:
        CCBridge.packet_received.connect(_on_cc_packet)
    await _run_pipeline()

func _run_pipeline() -> void:
    # pass: harvest_pinterest_interior (pinterest_connector via deterministic)
    var harvest_pinterest_interior_result = await _dispatch_pass("harvest_pinterest_interior", "pinterest_connector", "deterministic")
    emit_signal("harvest_pinterest_interior_done", harvest_pinterest_interior_result)
    # pass: embed_local_svgs (svg_vector_embed via deterministic)
    var embed_local_svgs_result = await _dispatch_pass("embed_local_svgs", "svg_vector_embed", "deterministic")
    emit_signal("embed_local_svgs_done", embed_local_svgs_result)
    # pass: extract_lights_from_shapes (light_source via deterministic)
    var extract_lights_from_shapes_result = await _dispatch_pass("extract_lights_from_shapes", "light_source", "deterministic")
    emit_signal("extract_lights_from_shapes_done", extract_lights_from_shapes_result)
    # pass: frame_clock_anchor (frame_clock via deterministic)
    var frame_clock_anchor_result = await _dispatch_pass("frame_clock_anchor", "frame_clock", "deterministic")
    emit_signal("frame_clock_anchor_done", frame_clock_anchor_result)
    # pass: spatial_anchor_room (spatial_anchor via deterministic)
    var spatial_anchor_room_result = await _dispatch_pass("spatial_anchor_room", "spatial_anchor", "deterministic")
    emit_signal("spatial_anchor_room_done", spatial_anchor_room_result)
    # pass: select_mixamo_idle (dataset_select_fbx via deterministic)
    var select_mixamo_idle_result = await _dispatch_pass("select_mixamo_idle", "dataset_select_fbx", "deterministic")
    emit_signal("select_mixamo_idle_done", select_mixamo_idle_result)
    # pass: blender_assemble (blender_mcp via blender)
    var blender_assemble_result = await _dispatch_pass("blender_assemble", "blender_mcp", "blender")
    emit_signal("blender_assemble_done", blender_assemble_result)
    # pass: comfy_render_avatar (ComfyUI via comfyui)
    var comfy_render_avatar_result = await _dispatch_pass("comfy_render_avatar", "ComfyUI", "comfyui")
    emit_signal("comfy_render_avatar_done", comfy_render_avatar_result)
    # pass: remotion_compose (remotion via remotion)
    var remotion_compose_result = await _dispatch_pass("remotion_compose", "remotion", "remotion")
    emit_signal("remotion_compose_done", remotion_compose_result)
    # pass: hf_describe_room (hf_inference via hf)
    var hf_describe_room_result = await _dispatch_pass("hf_describe_room", "hf_inference", "hf")
    emit_signal("hf_describe_room_done", hf_describe_room_result)

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
    print("[realestate_walkthrough_full] cc packet: ", packet.get("pass_id", "?"))
