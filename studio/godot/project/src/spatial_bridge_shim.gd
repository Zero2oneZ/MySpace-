extends Node
# SpatialBridgeShim — pure-GDScript replacement for SpatialBridge C++ extension.
# Per AGENTIC_BUILD_MANIFEST §10 Risk 1 mitigation.
# Exposes the same callable interface as cpp/include/spatial_bridge.h
# (fuse_depth, mirror_drift, crystal_hash) without the .so dependency.

func _ready() -> void:
	print("SpatialBridgeShim ready (gdscript fallback, no .so)")

# Weighted depth fusion — same weighting as the cpp original.
# 0.6 visual + 0.3 meta + 0.1 acoustic, element-wise.
# Length follows visual; shorter inputs fall back to the visual value at index.
func fuse_depth(acoustic: PackedFloat32Array, visual: PackedFloat32Array,
				meta: PackedFloat32Array) -> PackedFloat32Array:
	var n: int = visual.size()
	var out := PackedFloat32Array()
	out.resize(n)
	for i in range(n):
		var v: float = visual[i]
		var a: float = (acoustic[i] if i < acoustic.size() else v)
		var m: float = (meta[i] if i < meta.size() else v)
		out[i] = 0.6 * v + 0.3 * m + 0.1 * a
	return out

# Mirror drift — Hamming distance over chars, normalized to [0, 1].
# The cpp version uses crystal hashes; bits-out-of-place is a fine v0 proxy.
# Accepts either Strings or Dictionaries (per header). Dictionaries are first
# canonicalized so call sites match the cpp signature.
func mirror_drift(forward, inverse) -> float:
	var f_str: String = forward if forward is String else _canonical_json(forward)
	var i_str: String = inverse if inverse is String else _canonical_json(inverse)
	var n: int = min(f_str.length(), i_str.length())
	if n == 0:
		return 1.0
	var mismatches: int = 0
	for i in range(n):
		if f_str.unicode_at(i) != i_str.unicode_at(i):
			mismatches += 1
	# Account for length skew too.
	var skew: int = abs(f_str.length() - i_str.length())
	var denom: int = max(f_str.length(), i_str.length())
	return float(mismatches + skew) / float(denom)

# Crystal hash — sha256 of canonical JSON payload, hex-encoded.
func crystal_hash(payload: Dictionary) -> String:
	var ctx := HashingContext.new()
	ctx.start(HashingContext.HASH_SHA256)
	var canonical := _canonical_json(payload)
	ctx.update(canonical.to_utf8_buffer())
	return ctx.finish().hex_encode()

# Stub for the fourth header method (physics-context vector from joints).
# Returns a flat list of per-joint magnitudes — enough for downstream callers
# that only need a deterministic vector shape.
func compute_physics_context(joints: Array) -> PackedFloat32Array:
	var out := PackedFloat32Array()
	out.resize(joints.size())
	for i in range(joints.size()):
		var j = joints[i]
		if j is Vector3:
			out[i] = (j as Vector3).length()
		else:
			out[i] = 0.0
	return out

func _canonical_json(obj) -> String:
	if obj is Dictionary:
		var keys: Array = obj.keys()
		keys.sort()
		var parts: Array = []
		for k in keys:
			parts.append("\"%s\":%s" % [str(k), _canonical_json(obj[k])])
		return "{" + ",".join(parts) + "}"
	elif obj is Array:
		var parts: Array = []
		for v in obj:
			parts.append(_canonical_json(v))
		return "[" + ",".join(parts) + "]"
	elif obj is String:
		return JSON.stringify(obj)
	else:
		return str(obj)
