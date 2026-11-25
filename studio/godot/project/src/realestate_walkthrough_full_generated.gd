
# GENERATED from workflow_card: realestate_walkthrough_full
# card_crystal: 4b5b9c4a5d3b5600c71da2e80b4346997284960d3202f11cb32ed05db348219fca89e0b61a08a18550d9d8db72d2ea8297d367804789e33bf0c239f88b3ef835
# target: godot_gd
# schema: workflow_card_v0
# DO NOT EDIT BY HAND — regenerate via: cc workflow generate realestate_walkthrough_full
extends Node3D
## realestate_walkthrough_full — auto-generated from workflow_card_v0
##
## Category : realestate
## State    : active
## Version  : v0
## Crystal  : 4b5b9c4a5d3b5600c71da2e8…
##
## Summary  : The master integration card. Exercises every substrate built in this session: Pinterest harvest → SVG embed → light source extraction → frame clock alignment → spatial anchor → dataset FBX selection → Blender MCP modeling → ComfyUI render →
##
## Pipeline walks `_passes` in order. Each pass dispatches via
## `_dispatch_pass(pass)`, switching on `pass.engine`:
##   comfyui  → ChainRunner.fire_comfy_workflow()
##   mcp      → CCBridge.dispatch() (task_queue enqueue)
##   blender  → POST /webhook/blender   (stub today)
##   other    → push_warning + ""
## A `pass_completed(pass_id, crystal)` signal fires per pass.

# ── exports (inputs from card) ───────────────────────────────────────────────
@export var room_id: String = "demo_room_001"
@export var pinterest_category: String = "interior"
@export var animation_category: String = "idle"
@export var fps: int = 60
@export var wall_distances_m: Array = [4.5, 5.0, 4.5, 5.0, 2.4]  # raw type: list[float]


# ── signals (outputs from card + universal pass marker) ──────────────────────
signal godot_scene_ready(payload)
signal remotion_video_ready(payload)
signal blender_bake_ready(payload)
signal spriteforge_sheet_ready(payload)
signal trace_crystal_ready(payload)
signal pass_completed(pass_id: String, crystal: String)

# ── constants ────────────────────────────────────────────────────────────────
const CARD_NAME: String = "realestate_walkthrough_full"
const CARD_CRYSTAL: String = "4b5b9c4a5d3b5600c71da2e80b4346997284960d3202f11cb32ed05db348219fca89e0b61a08a18550d9d8db72d2ea8297d367804789e33bf0c239f88b3ef835"

# ── internal pass list (mirrors card.passes[]) ───────────────────────────────
var _passes: Array = []

func _ready() -> void:
	_passes = [
		{
			"id":     "harvest_pinterest_interior",
			"agent":  "pinterest_connector",
			"engine": "deterministic",
			"in":     [],
			"out":    "pinterest_pins",
			"tier":   "cheap",
			"status": "ACTIVE",
		},
		{
			"id":     "embed_local_svgs",
			"agent":  "svg_vector_embed",
			"engine": "deterministic",
			"in":     [],
			"out":    "svg_index",
			"tier":   "cheap",
			"status": "ACTIVE",
		},
		{
			"id":     "extract_lights_from_shapes",
			"agent":  "light_source",
			"engine": "deterministic",
			"in":     ["svg_index"],
			"out":    "light_field",
			"tier":   "cheap",
			"status": "ACTIVE",
		},
		{
			"id":     "frame_clock_anchor",
			"agent":  "frame_clock",
			"engine": "deterministic",
			"in":     [],
			"out":    "frame_anchor",
			"tier":   "deterministic",
			"status": "ACTIVE",
		},
		{
			"id":     "spatial_anchor_room",
			"agent":  "spatial_anchor",
			"engine": "deterministic",
			"in":     [],
			"out":    "room_anchor",
			"tier":   "deterministic",
			"status": "ACTIVE",
		},
		{
			"id":     "select_mixamo_idle",
			"agent":  "dataset_select_fbx",
			"engine": "deterministic",
			"in":     [],
			"out":    "rigged_fbx",
			"tier":   "cheap",
			"status": "ACTIVE",
		},
		{
			"id":     "blender_assemble",
			"agent":  "blender_mcp",
			"engine": "blender",
			"in":     ["rigged_fbx", "light_field", "room_anchor", "frame_anchor"],
			"out":    "blender_scene",
			"tier":   "medium",
			"status": "IN-FLIGHT",
		},
		{
			"id":     "comfy_render_avatar",
			"agent":  "ComfyUI",
			"engine": "comfyui",
			"in":     ["rigged_fbx", "light_field"],
			"out":    "avatar_frames",
			"tier":   "large",
			"status": "IN-FLIGHT",
		},
		{
			"id":     "remotion_compose",
			"agent":  "remotion",
			"engine": "remotion",
			"in":     ["avatar_frames", "blender_scene", "frame_anchor"],
			"out":    "walkthrough_video",
			"tier":   "medium",
			"status": "IN-FLIGHT",
		},
		{
			"id":     "hf_describe_room",
			"agent":  "hf_inference",
			"engine": "hf",
			"in":     ["room_anchor", "light_field"],
			"out":    "room_caption",
			"tier":   "cheap",
			"status": "ACTIVE",
		},
	]
	print("[", CARD_NAME, "] booted — crystal=", CARD_CRYSTAL.substr(0, 16),
			" passes=", _passes.size())
	if Engine.has_singleton("CCBridge") or CCBridge != null:
		CCBridge.packet_received.connect(_on_cc_packet)


# ── pipeline driver ──────────────────────────────────────────────────────────

func run_pipeline() -> void:
	## Walk `_passes` in order. Emits `pass_completed(pass_id, crystal)` per pass.
	for p in _passes:
		var crystal: String = await _dispatch_pass(p)
		emit_signal("pass_completed", String(p.get("id", "?")), crystal)


# ── per-pass dispatch (engine switch) ────────────────────────────────────────

func _dispatch_pass(p: Dictionary) -> String:
	## Returns a crystal hash string (may be empty if engine unsupported).
	var engine: String = String(p.get("engine", ""))
	var pass_id: String = String(p.get("id", "?"))
	match engine:
		"comfyui":
			# Production: hand off to ChainRunner which posts the workflow JSON
			# to the local ComfyUI install and returns the run crystal.
			if ChainRunner != null and ChainRunner.has_method("fire_comfy_workflow"):
				return await ChainRunner.fire_comfy_workflow(CARD_NAME, pass_id, p)
			push_warning("[%s] comfyui pass '%s' has no ChainRunner.fire_comfy_workflow" % [CARD_NAME, pass_id])
			return ""
		"mcp", "deterministic", "hf", "remotion", "diffusers", "spriteforge":
			# Generic enqueue path — task_queue routes by agent/engine.
			if CCBridge != null:
				var packet := {
					"protocol":     "cc_godot_bridge_v1",
					"card_crystal": CARD_CRYSTAL,
					"pass_id":      pass_id,
					"agent":        String(p.get("agent", "")),
					"engine":       engine,
					"in":           p.get("in", []),
					"out":          String(p.get("out", "")),
				}
				var result = await CCBridge.dispatch(packet)
				if typeof(result) == TYPE_DICTIONARY:
					return String(result.get("crystal", ""))
				return ""
			push_warning("[%s] %s pass '%s' has no CCBridge" % [CARD_NAME, engine, pass_id])
			return ""
		"blender":
			# Stub: forward to Blender MCP via the (planned) webhook endpoint.
			# When the bridge wires in, this becomes an HTTPRequest to /webhook/blender.
			var http := HTTPRequest.new()
			add_child(http)
			var url := "http://127.0.0.1:8766/webhook/blender"
			var body := JSON.stringify({
				"card_crystal": CARD_CRYSTAL,
				"pass_id": pass_id,
				"agent":   String(p.get("agent", "")),
				"in":      p.get("in", []),
				"out":     String(p.get("out", "")),
			})
			var err := http.request(url, ["Content-Type: application/json"], HTTPClient.METHOD_POST, body)
			if err != OK:
				push_warning("[%s] blender pass '%s' http err=%d" % [CARD_NAME, pass_id, err])
				http.queue_free()
				return ""
			var done = await http.request_completed
			http.queue_free()
			# done = [result, code, headers, body_bytes]
			if done.size() >= 4 and int(done[1]) == 200:
				var parsed := JSON.parse_string(PackedByteArray(done[3]).get_string_from_utf8())
				if typeof(parsed) == TYPE_DICTIONARY:
					return String(parsed.get("crystal", ""))
			return ""
		_:
			push_warning("[%s] unsupported engine '%s' for pass '%s'" % [CARD_NAME, engine, pass_id])
			return ""


# ── cc bridge sink ───────────────────────────────────────────────────────────

func _on_cc_packet(packet: Dictionary) -> void:
	# Side-channel inbound from the cc terminal — surface as a pass_completed
	# event if the packet's card_crystal matches ours.
	if String(packet.get("card_crystal", "")) != CARD_CRYSTAL:
		return
	emit_signal("pass_completed",
			String(packet.get("pass_id", "?")),
			String(packet.get("crystal", "")))


# ── layer_stack vocabulary (queryable from GDScript) ─────────────────────────
# Mirrors the workflow_card's `layer_stack[]`. Drives shader uniforms,
# Blender material sockets, SpriteForge layers, ComfyUI mix nodes — same
# names everywhere (architectural invariant #3).
var _layer_stack: Array = [
	{
		"name":           "albedo",
		"source":         "pass:embed_local_svgs",
		"blend":          "base",
		"target_uniform": "u_albedo",
	},
	{
		"name":           "normal",
		"source":         "pass:blender_assemble",
		"blend":          "normal_map",
		"target_uniform": "u_normal",
	},
	{
		"name":           "ao",
		"source":         "pass:blender_assemble",
		"blend":          "multiply",
		"target_uniform": "u_ao",
	},
	{
		"name":           "depth",
		"source":         "pass:spatial_anchor_room",
		"blend":          "depth_uniform",
		"target_uniform": "u_depth",
	},
	{
		"name":           "alpha",
		"source":         "literal:1.0",
		"blend":          "alpha",
		"target_uniform": "u_alpha",
	},
	{
		"name":           "opacity",
		"source":         "literal:1.0",
		"blend":          "opacity",
		"target_uniform": "u_opacity",
	},
	{
		"name":           "emission",
		"source":         "pass:extract_lights_from_shapes",
		"blend":          "additive",
		"target_uniform": "u_emission",
	},
]
