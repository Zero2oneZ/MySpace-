extends Node
# IKShim — pure-GDScript replacement for IKSolver C++ extension.
# Per AGENTIC_BUILD_MANIFEST §10 Risk 1 mitigation.
# Exposes the same callable interface as cpp/include/ik_solver.h
# (solve_two_bone, solve_ccd, ik_delta) without the .so dependency.

func _ready() -> void:
	print("IKShim ready (gdscript fallback, no .so)")

# Two-bone analytic IK (law of cosines).
# p_root: shoulder/hip, p_mid: elbow/knee (current pose for plane hint),
# p_end: wrist/ankle (current pose, returned as 'end' when reachable),
# p_target: goal world position.
# Returns Dictionary { "mid": Vector3, "end": Vector3, "angle_a": float, "angle_b": float }
func solve_two_bone(root: Vector3, mid: Vector3, end: Vector3, target: Vector3,
					bone_len_a: float, bone_len_b: float) -> Dictionary:
	var d := root.distance_to(target)
	var max_reach := bone_len_a + bone_len_b - 0.0001
	var clamped_d: float = clamp(d, 0.0001, max_reach)
	# Law of cosines: angle at root between bone_a and root→target line.
	var cos_a: float = (bone_len_a * bone_len_a + clamped_d * clamped_d - bone_len_b * bone_len_b) / (2.0 * bone_len_a * clamped_d)
	cos_a = clamp(cos_a, -1.0, 1.0)
	var angle_a: float = acos(cos_a)
	# Interior angle at mid joint.
	var cos_b: float = (bone_len_a * bone_len_a + bone_len_b * bone_len_b - clamped_d * clamped_d) / (2.0 * bone_len_a * bone_len_b)
	cos_b = clamp(cos_b, -1.0, 1.0)
	var angle_b: float = acos(cos_b)
	# Build a stable plane from current pose.
	var forward := (target - root).normalized()
	if forward.length() < 0.0001:
		forward = Vector3.FORWARD
	var pose_dir := (mid - root)
	var up := Vector3.ZERO
	if pose_dir.length() > 0.0001:
		up = pose_dir.normalized().cross(forward).normalized()
	if up.length() < 0.001:
		up = Vector3.UP.cross(forward).normalized()
	if up.length() < 0.001:
		up = Vector3.RIGHT.cross(forward).normalized()
	var perp := forward.cross(up).normalized()
	# Mid is bone_len_a from root, rotated angle_a away from forward in the plane.
	var mid_pos := root + forward * (bone_len_a * cos_a) + perp * (bone_len_a * sin(angle_a))
	# If unreachable, target collapses to the reachable extent on the forward line.
	var end_pos := target
	if d > max_reach:
		end_pos = root + forward * (bone_len_a + bone_len_b)
	return {"mid": mid_pos, "end": end_pos, "angle_a": angle_a, "angle_b": angle_b}

# Cyclic Coordinate Descent IK over an N-joint chain.
# chain: Array of Vector3 (joint positions, root first), target: Vector3.
# Returns updated Array of Vector3 (same length as input).
func solve_ccd(chain: Array, target: Vector3, iterations: int = 10) -> Array:
	if chain.size() < 2:
		return chain
	var pts: Array = chain.duplicate()
	var n: int = pts.size()
	for it in range(iterations):
		# Walk from second-to-last joint back to root; rotate each toward target.
		for j in range(n - 2, -1, -1):
			var joint: Vector3 = pts[j]
			var to_end: Vector3 = pts[n - 1] - joint
			var to_target: Vector3 = target - joint
			if to_end.length() < 0.0001 or to_target.length() < 0.0001:
				continue
			var from_v := to_end.normalized()
			var to_v := to_target.normalized()
			# Guard near-parallel / near-antiparallel cases.
			var dot_v: float = clamp(from_v.dot(to_v), -1.0, 1.0)
			if dot_v > 0.99999:
				continue
			var axis := from_v.cross(to_v)
			var q: Quaternion
			if axis.length() < 0.00001:
				# 180° flip — pick any orthogonal axis.
				var fallback := from_v.cross(Vector3.UP)
				if fallback.length() < 0.0001:
					fallback = from_v.cross(Vector3.RIGHT)
				q = Quaternion(fallback.normalized(), PI)
			else:
				q = Quaternion(from_v, to_v)
			# Apply rotation to all downstream joints around the current joint.
			for k in range(j + 1, n):
				pts[k] = joint + q * (pts[k] - joint)
	return pts

# Strain metric — how far the solved end drifted from the controller's intent.
func ik_delta(controller_goal: Vector3, solver_result: Vector3) -> float:
	return controller_goal.distance_to(solver_result)
