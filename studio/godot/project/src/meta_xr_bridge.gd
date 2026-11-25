extends Node
# class_name MetaXRBridge removed — the same name is already an autoload
# singleton in project.godot so declaring class_name shadowed it and
# raised "Class X hides an autoload singleton" at parse time.
## Meta XR Bridge — autoload for OpenXR / Meta Quest integration.
##
## Probes the OpenXR interface on _ready. If unavailable, stays in stub
## mode and returns sane defaults from every method. If available, queries
## XR_FB_passthrough + XR_EXT_hand_tracking features and surfaces signals
## for ready / passthrough / hand tracking / controller input events.
##
## Cross-process visibility: each significant event is appended to
## ~/.cc/godot_xr_events.jsonl as a JSON object:
##   { "ts": <unix>, "event": <str>, "scene_uid": <str>, "details": {...} }
##
## Required env / project settings (read elsewhere, not here):
##   META_QUEST_APP_ID, META_QUEST_API_KEY  — used by deployment / linking,
##   not by runtime XR probing.

signal xr_ready(interface_name: String)
signal passthrough_available(yes: bool)
signal hand_tracking_available(yes: bool)
signal controller_input(side: String, button: String, pressed: bool)

const EVENT_LOG_PATH := "user://godot_xr_events.jsonl"
const EVENT_LOG_GLOBAL := "~/.cc/godot_xr_events.jsonl"

var _xr_interface: XRInterface = null
var _xr_available: bool = false
var _passthrough_supported: bool = false
var _hand_tracking_supported: bool = false
var _passthrough_active: bool = false
var _hand_tracking_active: bool = false
var _scene_uid: String = ""

func _ready() -> void:
	_scene_uid = "meta_xr_bridge_%d" % Time.get_unix_time_from_system()
	_probe_openxr()

func _probe_openxr() -> void:
	var iface := XRServer.find_interface("OpenXR")
	if iface == null:
		_xr_available = false
		print("OpenXR interface unavailable; meta_xr_bridge in stub mode")
		_emit_event("xr_stub_mode", { "reason": "openxr_interface_null" })
		return

	_xr_interface = iface
	if not _xr_interface.is_initialized():
		var ok := _xr_interface.initialize()
		if not ok:
			_xr_available = false
			print("OpenXR present but initialize() failed; staying in stub mode")
			_emit_event("xr_init_failed", {})
			return

	_xr_available = true
	# Wire the interface up to the main viewport so XR rendering kicks in.
	var vp := get_viewport()
	if vp != null:
		vp.use_xr = true

	_detect_features()
	xr_ready.emit(_xr_interface.get_name())
	_emit_event("xr_ready", {
		"interface": _xr_interface.get_name(),
		"passthrough": _passthrough_supported,
		"hand_tracking": _hand_tracking_supported,
	})

func _detect_features() -> void:
	if _xr_interface == null:
		return

	# Godot 4.x OpenXRInterface exposes typed helpers for these extensions.
	# Guard each call — older 4.x builds may not have every method.
	if _xr_interface is OpenXRInterface:
		var oxr: OpenXRInterface = _xr_interface
		if oxr.has_method("is_passthrough_supported"):
			_passthrough_supported = oxr.is_passthrough_supported()
		elif oxr.has_method("is_extension_supported"):
			_passthrough_supported = oxr.is_extension_supported("XR_FB_passthrough")

		if oxr.has_method("is_hand_tracking_supported"):
			_hand_tracking_supported = oxr.is_hand_tracking_supported()
		elif oxr.has_method("is_extension_supported"):
			_hand_tracking_supported = oxr.is_extension_supported("XR_EXT_hand_tracking")
	else:
		# Unknown interface flavor — best effort: no features.
		_passthrough_supported = false
		_hand_tracking_supported = false

	passthrough_available.emit(_passthrough_supported)
	hand_tracking_available.emit(_hand_tracking_supported)

# ─── public methods ───────────────────────────────────────────────

func enable_passthrough() -> bool:
	if not _xr_available or not _passthrough_supported:
		print("meta_xr_bridge: enable_passthrough() in stub mode → false")
		_emit_event("passthrough_enable_stub", {})
		return false
	if _xr_interface is OpenXRInterface and _xr_interface.has_method("start_passthrough"):
		var ok: bool = _xr_interface.start_passthrough()
		_passthrough_active = ok
		_emit_event("passthrough_enabled", { "ok": ok })
		return ok
	_emit_event("passthrough_enable_unsupported_method", {})
	return false

func disable_passthrough() -> void:
	if not _xr_available or not _passthrough_supported:
		print("meta_xr_bridge: disable_passthrough() in stub mode")
		_emit_event("passthrough_disable_stub", {})
		return
	if _xr_interface is OpenXRInterface and _xr_interface.has_method("stop_passthrough"):
		_xr_interface.stop_passthrough()
		_passthrough_active = false
		_emit_event("passthrough_disabled", {})

func start_hand_tracking() -> bool:
	if not _xr_available or not _hand_tracking_supported:
		print("meta_xr_bridge: start_hand_tracking() in stub mode → false")
		_emit_event("hand_tracking_start_stub", {})
		return false
	_hand_tracking_active = true
	_emit_event("hand_tracking_started", {})
	return true

func get_controller_position(side: String) -> Vector3:
	if not _xr_available:
		return Vector3.ZERO
	# Look up the tracker on XRServer. Standard names: "left_hand" / "right_hand".
	var tracker_name := "left_hand" if side.to_lower() == "left" else "right_hand"
	var tracker := XRServer.get_tracker(tracker_name)
	if tracker == null:
		return Vector3.ZERO
	if tracker.has_method("get_pose"):
		var pose: XRPose = tracker.get_pose("default")
		if pose != null:
			return pose.transform.origin
	return Vector3.ZERO

func emit_controller_input(side: String, button: String, pressed: bool) -> void:
	# Hook other scripts can call from XRController3D button signals.
	controller_input.emit(side, button, pressed)
	_emit_event("controller_input", { "side": side, "button": button, "pressed": pressed })

# ─── introspection helpers ────────────────────────────────────────

func is_xr_available() -> bool:
	return _xr_available

func is_passthrough_supported() -> bool:
	return _passthrough_supported

func is_hand_tracking_supported() -> bool:
	return _hand_tracking_supported

# ─── cross-process event log ──────────────────────────────────────

func _emit_event(event: String, details: Dictionary) -> void:
	var packet := {
		"ts": Time.get_unix_time_from_system(),
		"event": event,
		"scene_uid": _scene_uid,
		"details": details,
	}
	var line := JSON.stringify(packet)

	# Write to user:// first (sandboxed, always works).
	var f := FileAccess.open(EVENT_LOG_PATH, FileAccess.READ_WRITE)
	if f == null:
		f = FileAccess.open(EVENT_LOG_PATH, FileAccess.WRITE)
	if f != null:
		f.seek_end()
		f.store_line(line)
		f.close()

	# Also try the global ~/.cc path (best effort — may fail in sandboxed builds).
	var global_path := _expand_home(EVENT_LOG_GLOBAL)
	var gf := FileAccess.open(global_path, FileAccess.READ_WRITE)
	if gf == null:
		gf = FileAccess.open(global_path, FileAccess.WRITE)
	if gf != null:
		gf.seek_end()
		gf.store_line(line)
		gf.close()

func _expand_home(path: String) -> String:
	if path.begins_with("~/"):
		var home := OS.get_environment("HOME")
		if home.is_empty():
			home = OS.get_environment("USERPROFILE")
		if not home.is_empty():
			return home + path.substr(1)
	return path

func emit_mocap_frame(joints: Dictionary, face: Dictionary,
		anchor_uuids: Array) -> void:
	## Append one MocapFrame JSON line to ~/.cc/meta_xr_mocap.jsonl
	## (the sink the Python MetaXRMocapAdapter tails).
	var ts = Time.get_unix_time_from_system()
	var line = JSON.stringify({
		"ts": ts,
		"joints": joints,
		"face_blendshapes": face,
		"anchor_uuids": anchor_uuids,
		"source_id": "meta_xr_quest3",
		"capture_method": "meta_xr_body",
	})
	var sink_path = OS.get_environment("HOME") + "/.cc/meta_xr_mocap.jsonl"
	var f = FileAccess.open(sink_path, FileAccess.READ_WRITE)
	if f == null:
		f = FileAccess.open(sink_path, FileAccess.WRITE)
	if f == null:
		return
	f.seek_end()
	f.store_line(line)
	f.close()

func list_known_anchors() -> Array:
	## Return XR_FB_spatial_entity UUIDs currently known to the runtime.
	## Stub for now — wiring to the actual XRAnchor3D tree happens after
	## the spatial_anchor.py + this autoload meet.
	return []
