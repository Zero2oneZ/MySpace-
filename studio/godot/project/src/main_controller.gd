extends Node
## Main controller — boots the studio, wires autoloads, and dispatches to native.

@onready var spatial: Node = null
@onready var ik: Node = null

## Accessors used by autoloads (e.g. CCBridge) that reach MainController via the
## scene tree (get_node("/root/Main")). Return the native bridges or null when
## the GDExtension isn't compiled, so callers degrade gracefully.
func get_spatial() -> Node:
	return spatial

func get_ik() -> Node:
	return ik

func _ready():
	print("MainController booting MySpace++ Studio...")
	print("VMs: %d | Symbols: %d" % [VMNavigator.list_vms().size(), SymIndexer.symbols.size()])

	# Try to load native extension classes if compiled
	if ClassDB.class_exists("SpatialBridge"):
		spatial = ClassDB.instantiate("SpatialBridge")
		spatial.name = "SpatialBridge"
		add_child(spatial)
		print("Native SpatialBridge loaded")
	else:
		print("SpatialBridge not compiled yet — run build-cpp.sh")

	if ClassDB.class_exists("IKSolver"):
		ik = ClassDB.instantiate("IKSolver")
		ik.name = "IKSolver"
		add_child(ik)
		print("Native IKSolver loaded")
	else:
		print("IKSolver not compiled yet — run build-cpp.sh")

	# Wire CC Bridge signals
	if CCBridge != null:
		CCBridge.packet_received.connect(_on_cc_packet)
		CCBridge.slice_requested.connect(_on_cc_slice)
		print("CC Bridge wired to MainController")
	else:
		push_warning("CC Bridge autoload not available")

	# Wire SocialClient signals
	if SocialClient != null:
		SocialClient.upload_finished.connect(_on_social_upload)
		SocialClient.cli_finished.connect(_on_social_cli)
		SocialClient.status_ready.connect(_on_social_status)
		print("SocialClient wired to MainController")
	else:
		push_warning("SocialClient autoload not available")

	# Instance social UI panel under UI CanvasLayer
	var ui := get_parent().get_node_or_null("UI")
	if ui != null:
		var panel := preload("res://scenes/social_panel.tscn").instantiate()
		ui.add_child(panel)
		print("SocialPanel added to UI")
	else:
		push_warning("UI CanvasLayer not found — SocialPanel not added")

func run_demo_chain():
	var chain = {
		"id": "demo",
		"steps": [
			{"id": "load_vm", "vm": "walkthrough"},
			{"id": "navigate", "step": "room_1"},
			{"id": "infer", "model": "DepthPro"},
		]
	}
	ChainRunner.start_chain(chain)

func run_chat_packet_demo():
	## Demo: simulate receiving a chat packet from `cc chat --godot`
	var demo_packet = {
		"protocol": "cc_godot_bridge_v1",
		"timestamp": Time.get_datetime_string_from_system(true, true),
		"agent_uuid": "demo-uuid-001",
		"original": "build spatial pipeline for room 1",
		"enhanced": "SCOPE: godot_studio\nINTENT: build spatial pipeline for room 1\nCONSTRAINTS: deterministic, scoped to current working directory, no external dependencies without explicit approval\nOUTPUT: structured response ending with DONE\n\nbuild spatial pipeline for room 1\n\n# Chain context (auto-expanded from keywords)\n- godot -> (has_component) -> spatial_bridge\n- godot -> (has_component) -> ik_solver\n- spatial_bridge -> (computes) -> physics_context\n- spatial_bridge -> (computes) -> depth_fusion",
		"route": {"tier": "medium", "model": "qwen3-coder-next:latest", "scope": "medium"},
		"tokens": 342,
		"complexity": 0.52,
		"godot_action": "spatial_pipeline",
		"chain_context": "# Chain context (auto-expanded from keywords)\n- godot -> (has_component) -> spatial_bridge\n- spatial_bridge -> (computes) -> physics_context"
	}
	CCBridge.inject_packet(demo_packet)

func _on_cc_packet(packet: Dictionary):
	print("MainController received CC packet: tier=%s action=%s" % [
		packet.get("route", {}).get("tier", "?"),
		packet.get("godot_action", "?")
	])
	# Update UI label if available
	var ui = get_node_or_null("UI/Label")
	if ui != null and ui is Label:
		ui.text = "CC: %s | %s | %d tokens" % [
			packet.get("route", {}).get("tier", "?"),
			packet.get("godot_action", "?"),
			packet.get("tokens", 0)
		]

func _on_cc_slice(subject: String, slice_prompt: String, from_tier: String):
	print("MainController slice request: subject=%s from_tier=%s" % [subject, from_tier])
	# Store slice as a task for lower-tier workers
	TaskManager.queue_task("cc_slice_%s" % subject, slice_prompt, {
		"subject": subject,
		"from_tier": from_tier,
		"slice_prompt": slice_prompt
	})

func _on_social_upload(platforms: String, ok: bool, detail: Dictionary):
	print("MainController social upload: platforms=%s ok=%s detail=%s" % [platforms, ok, detail])
	var ui = get_node_or_null("UI/SocialLabel")
	if ui != null and ui is Label:
		ui.text = "Social [%s]: %s" % [platforms, "OK" if ok else "FAIL"]

func _on_social_cli(cli_name: String, ok: bool, stdout: String):
	print("MainController social CLI: cli=%s ok=%s stdout=%s" % [cli_name, ok, stdout.substr(0, 200)])

func _on_social_status(status: Dictionary):
	print("MainController social status: ", status)
