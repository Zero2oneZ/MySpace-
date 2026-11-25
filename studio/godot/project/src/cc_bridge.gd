extends Node
## CC Bridge — receives deterministic chat packets from `cc chat --godot`
## and dispatches them into the Godot studio.
##
## Packet protocol: cc_godot_bridge_v1
## {
##   "protocol": "cc_godot_bridge_v1",
##   "timestamp": "...",
##   "agent_uuid": "...",
##   "original": "user raw prompt",
##   "enhanced": "spell-fixed + structured + chain context",
##   "route": {"tier": "tiny|medium|large|epic", "model": "...", "scope": "..."},
##   "tokens": 1234,
##   "complexity": 0.45,
##   "godot_action": "spatial_pipeline|run_chain|task_queue|index_symbols|build_gdext|noop",
##   "chain_context": "..."
## }

signal packet_received(packet: Dictionary)
signal action_dispatched(action: String, packet: Dictionary)
signal slice_requested(subject: String, slice_prompt: String, tier: String)

@export var bridge_pipe_path: String = "res://.cc/godot_bridge.jsonl"
@export var poll_interval_ms: int = 500

var _poll_timer: Timer
var _last_mtime: int = 0
var _packet_queue: Array = []

func _ready():
	print("CC Bridge ready — watching ", bridge_pipe_path)
	_poll_timer = Timer.new()
	_poll_timer.wait_time = poll_interval_ms / 1000.0
	_poll_timer.autostart = true
	_poll_timer.timeout.connect(_on_poll)
	add_child(_poll_timer)

func _on_poll():
	var file = FileAccess.open(bridge_pipe_path, FileAccess.READ)
	if file == null:
		return  # no packets yet
	var content = file.get_as_text()
	file.close()

	var lines = content.split("\n", false)
	for line in lines:
		line = line.strip_edges()
		if line.is_empty():
			continue
		var ok = _ingest_line(line)
		if ok:
			# truncate consumed line from file (append-only JSONL)
			pass

func _ingest_line(line: String) -> bool:
	var json = JSON.new()
	var err = json.parse(line)
	if err != OK:
		push_error("CC Bridge: invalid JSON: ", line.substr(0, 80))
		return false

	var packet = json.data
	if typeof(packet) != TYPE_DICTIONARY:
		push_error("CC Bridge: packet is not a dict")
		return false
	if packet.get("protocol", "") != "cc_godot_bridge_v1":
		push_error("CC Bridge: unknown protocol: ", packet.get("protocol", "?"))
		return false

	_packet_queue.append(packet)
	packet_received.emit(packet)
	_dispatch_action(packet)
	return true

func _dispatch_action(packet: Dictionary):
	var action = packet.get("godot_action", "noop")
	var route = packet.get("route", {})
	var tier = route.get("tier", "tiny")
	var scope = route.get("scope", "narrow")

	print("CC Bridge dispatch: action=%s tier=%s scope=%s tokens=%d" % [
		action, tier, scope, packet.get("tokens", 0)
	])

	action_dispatched.emit(action, packet)

	match action:
		"spatial_pipeline":
			_dispatch_spatial(packet)
		"run_chain":
			_dispatch_chain(packet)
		"task_queue":
			_dispatch_task(packet)
		"index_symbols":
			_dispatch_index(packet)
		"build_gdext":
			_dispatch_build(packet)
		"social_upload":
			_dispatch_social(packet)
		_:
			print("CC Bridge: noop for action ", action)

func _dispatch_spatial(packet: Dictionary):
	## Trigger spatial inference pipeline via SpatialBridge native extension.
	# MainController is a scene-tree node, NOT an autoload — look it up
	# safely so this script parses even when the node isn't present.
	var mc = get_node_or_null("/root/Main") if get_node_or_null("/root/Main") else null
	if mc == null or not mc.has_method("get_spatial") or mc.call("get_spatial") == null:
		push_warning("CC Bridge: MainController / SpatialBridge not available")
		return
	var sb = mc.call("get_spatial")
	var depth_context = sb.compute_physics_context("demo_room")
	print("CC Bridge: spatial depth context = ", depth_context)
	# Mirror-pass validation: compute crystal hash of the operation
	var crystal = sb.crystal_hash(depth_context)
	print("CC Bridge: spatial crystal = ", crystal)

func _dispatch_chain(packet: Dictionary):
	## Start a VM chain via ChainRunner.
	var chain = {
		"id": "cc_chat_" + str(Time.get_unix_time_from_system()),
		"steps": [
			{"id": "load_vm", "vm": "walkthrough"},
			{"id": "navigate", "step": "room_1"},
			{"id": "infer", "model": "DepthPro"},
		]
	}
	ChainRunner.start_chain(chain)

func _dispatch_task(packet: Dictionary):
	## Queue a task via TaskManager.
	TaskManager.queue_task("cc_chat_task", "process chat packet", { "packet": packet })
	TaskManager.flush_queue()

func _dispatch_index(packet: Dictionary):
	## Index keywords from the packet into SymIndexer.
	var text = packet.get("enhanced", "")
	var words = text.split(" ")
	for word in words:
		word = word.strip_edges().to_lower()
		if word.length() > 3 and word.is_valid_identifier():
			# add_symbol(name: String, meta: Dictionary) — 2 args, not 3.
			SymIndexer.add_symbol(word, {
				"kind": "chat_keyword",
				"packet_id": packet.get("timestamp", ""),
			})
	SymIndexer.save_index()

func _dispatch_build(packet: Dictionary):
	## Trigger GDExtension build.
	print("CC Bridge: requesting GDExtension build via OS.execute")
	var output = []
	var rc = OS.execute("bash", ["-c", "cd " + ProjectSettings.globalize_path("res://") + " && bash cpp/build_gdext.sh"], output, true)
	print("CC Bridge: build rc=", rc, " output=", output)

func _dispatch_social(packet: Dictionary):
	## Trigger social upload via SocialClient.
	if SocialClient == null:
		push_warning("CC Bridge: SocialClient autoload not available")
		return
	var platforms = packet.get("social_platforms", [])
	var file_path = packet.get("social_file_path", "")
	var caption = packet.get("social_caption", "")
	if typeof(platforms) == TYPE_STRING:
		platforms = platforms.split(",")
	if file_path.is_empty():
		push_warning("CC Bridge: social_upload missing social_file_path")
		return
	print("CC Bridge: social upload platforms=", platforms, " file=", file_path)
	SocialClient.upload(PackedStringArray(platforms), file_path, caption)

## Public API for other Godot scripts to inject packets programmatically.
func inject_packet(packet: Dictionary) -> bool:
	if packet.get("protocol", "") != "cc_godot_bridge_v1":
		push_error("CC Bridge: inject_packet requires cc_godot_bridge_v1 protocol")
		return false
	_packet_queue.append(packet)
	packet_received.emit(packet)
	_dispatch_action(packet)
	return true

## Downward dispatch: request a lower-tier slice for a specific subject.
## Emits slice_requested signal; the main controller or another script
## should connect to this and forward the slice to the appropriate worker.
func request_slice(subject: String, slice_prompt: String, from_tier: String):
	print("CC Bridge: requesting slice for subject=%s from_tier=%s" % [subject, from_tier])
	slice_requested.emit(subject, slice_prompt, from_tier)

## Get the next unprocessed packet (FIFO).
func pop_packet() -> Dictionary:
	if _packet_queue.is_empty():
		return {}
	return _packet_queue.pop_front()

func queue_size() -> int:
	return _packet_queue.size()
