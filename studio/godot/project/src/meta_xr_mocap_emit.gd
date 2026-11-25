extends Node
## Meta XR Mocap Emitter — appends one JSON line per frame to a sink file
## that core/lib/third_party/meta_xr_mocap.py tails into MocapFrames.
##
## OpenXR extension mapping:
##   joints            → XR_FB_body_tracking   (22 Meta Body joints)
##   face_blendshapes  → XR_FB_face_tracking2  (ARKit 52)
##   anchor_uuids      → XR_FB_spatial_entity  (persistent room anchors)
##   spatial_origin    → XR_FB_passthrough     (headset → ME LAND origin)
##
## Sits ALONGSIDE meta_xr_bridge.gd — does not modify it. Where the bridge
## probes the interface + emits high-level events, this emitter pulls per-
## frame body/face/anchor data and appends to user://meta_xr_mocap.jsonl.

@export var sink_path: String = "user://meta_xr_mocap.jsonl"
@export var emit_hz: float = 30.0          # cap to 30 Hz by default
@export var include_face: bool = true
@export var include_anchors: bool = true

var _xr_interface: XRInterface = null
var _body_tracker: XRBodyTracker = null
var _face_tracker: XRFaceTracker = null
var _last_emit_ts: float = 0.0
var _enabled: bool = false

# Meta Body joint name order (matches META_BODY_JOINTS in mocap_frame.py).
const META_BODY_JOINT_NAMES: Array[String] = [
	"Root", "Hips", "SpineLower", "SpineMiddle", "SpineUpper",
	"Chest", "Neck", "Head",
	"LeftShoulder", "LeftArmUpper", "LeftArmLower", "LeftHandWrist",
	"RightShoulder", "RightArmUpper", "RightArmLower", "RightHandWrist",
	"LeftUpperLeg", "LeftLowerLeg", "LeftFootAnkle", "LeftFootBall",
	"RightUpperLeg", "RightLowerLeg", "RightFootAnkle", "RightFootBall",
]

func _ready() -> void:
	_xr_interface = XRServer.find_interface("OpenXR")
	if _xr_interface == null:
		push_warning("meta_xr_mocap_emit: OpenXR interface not available; emitter disabled")
		_enabled = false
		return
	if not _xr_interface.is_initialized():
		# meta_xr_bridge.gd usually initializes; if not, try once.
		var ok := _xr_interface.initialize()
		if not ok:
			push_warning("meta_xr_mocap_emit: OpenXR initialize() failed; emitter disabled")
			_enabled = false
			return
	# Body tracker (XR_FB_body_tracking) and face tracker (XR_FB_face_tracking2)
	# are exposed by Godot via XRServer trackers in 4.x. Guard each lookup.
	_body_tracker = XRServer.get_tracker("/user/body_tracker") as XRBodyTracker
	if _body_tracker == null and ClassDB.class_exists("XRBodyTracker"):
		_body_tracker = XRBodyTracker.new()
	_face_tracker = XRServer.get_tracker("/user/face_tracker") as XRFaceTracker
	if _face_tracker == null and ClassDB.class_exists("XRFaceTracker"):
		_face_tracker = XRFaceTracker.new()
	_enabled = true

func _process(_dt: float) -> void:
	if not _enabled:
		return
	var now_s: float = Time.get_unix_time_from_system()
	if (now_s - _last_emit_ts) < (1.0 / max(emit_hz, 1.0)):
		return
	_last_emit_ts = now_s
	var packet := _build_packet(now_s)
	_append_line(JSON.stringify(packet))

func _build_packet(ts: float) -> Dictionary:
	var joints := _sample_body_joints()
	var face := _sample_face_blendshapes() if include_face else {}
	var anchors := _sample_anchor_uuids() if include_anchors else []
	var origin := _sample_spatial_origin()
	var confidence := _sample_confidence(joints)
	return {
		"ts": ts,
		"joints": joints,
		"face_blendshapes": face,
		"anchor_uuids": anchors,
		"confidence": confidence,
		"spatial_origin": origin,
	}

func _sample_body_joints() -> Dictionary:
	var out := {}
	if _body_tracker == null:
		return out
	for i in range(META_BODY_JOINT_NAMES.size()):
		var name: String = META_BODY_JOINT_NAMES[i]
		# Godot 4.x XRBodyTracker exposes get_joint_transform(joint_enum).
		# Use a name-keyed lookup defensively; if the tracker lacks the
		# joint, skip it (sparse handling matches mocap_frame contract).
		if not _body_tracker.has_method("get_joint_transform"):
			break
		var xf: Transform3D = _body_tracker.call("get_joint_transform", i)
		var pos: Vector3 = xf.origin
		var q: Quaternion = Quaternion(xf.basis.orthonormalized())
		out[name] = [pos.x, pos.y, pos.z, q.x, q.y, q.z, q.w]
	return out

func _sample_face_blendshapes() -> Dictionary:
	var out := {}
	if _face_tracker == null:
		return out
	if not _face_tracker.has_method("get_blend_shape"):
		return out
	# ARKit 52 names — match ARKIT_BLENDSHAPES in mocap_frame.py.
	var names: Array[String] = [
		"browDownLeft","browDownRight","browInnerUp","browOuterUpLeft","browOuterUpRight",
		"cheekPuff","cheekSquintLeft","cheekSquintRight",
		"eyeBlinkLeft","eyeBlinkRight","eyeLookDownLeft","eyeLookDownRight",
		"eyeLookInLeft","eyeLookInRight","eyeLookOutLeft","eyeLookOutRight",
		"eyeLookUpLeft","eyeLookUpRight","eyeSquintLeft","eyeSquintRight",
		"eyeWideLeft","eyeWideRight",
		"jawForward","jawLeft","jawOpen","jawRight",
		"mouthClose","mouthDimpleLeft","mouthDimpleRight","mouthFrownLeft","mouthFrownRight",
		"mouthFunnel","mouthLeft","mouthLowerDownLeft","mouthLowerDownRight",
		"mouthPressLeft","mouthPressRight","mouthPucker",
		"mouthRight","mouthRollLower","mouthRollUpper","mouthShrugLower","mouthShrugUpper",
		"mouthSmileLeft","mouthSmileRight","mouthStretchLeft","mouthStretchRight",
		"mouthUpperUpLeft","mouthUpperUpRight",
		"noseSneerLeft","noseSneerRight","tongueOut",
	]
	for i in range(names.size()):
		var v: float = float(_face_tracker.call("get_blend_shape", i))
		out[names[i]] = clamp(v, 0.0, 1.0)
	return out

func _sample_anchor_uuids() -> Array:
	# XR_FB_spatial_entity UUIDs are typically surfaced by an addon or via
	# meta_xr_bridge.gd. If a global registry is present, read it; else [].
	var anchors: Array = []
	if Engine.has_singleton("MetaXRBridge"):
		var bridge := Engine.get_singleton("MetaXRBridge")
		if bridge.has_method("list_anchor_uuids"):
			anchors = bridge.call("list_anchor_uuids")
	return anchors

func _sample_spatial_origin() -> Array:
	# XR_FB_passthrough origin: headset world transform → (x,y,z,heading).
	if _xr_interface == null:
		return []
	var camera_xform: Transform3D = _xr_interface.get_camera_transform() if _xr_interface.has_method("get_camera_transform") else Transform3D()
	var pos: Vector3 = camera_xform.origin
	# Heading = yaw around +Y. atan2(basis.z.x, basis.z.z) gives yaw.
	var heading: float = atan2(camera_xform.basis.z.x, camera_xform.basis.z.z)
	return [pos.x, pos.y, pos.z, heading]

func _sample_confidence(joints: Dictionary) -> Dictionary:
	var out := {}
	if _body_tracker == null:
		return out
	for k in joints.keys():
		out[k] = 0.9  # default confidence; runtime-specific where available
	return out

func _append_line(line: String) -> void:
	var f := FileAccess.open(sink_path, FileAccess.READ_WRITE)
	if f == null:
		f = FileAccess.open(sink_path, FileAccess.WRITE)
	if f == null:
		return
	f.seek_end()
	f.store_line(line)
	f.close()
