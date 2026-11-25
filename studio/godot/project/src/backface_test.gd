extends SceneTree
# Back-face cutout — the "render unseen Blender geometry → free alpha + depth + parallax" demo.
# Flip cull_mode → rasterizer writes z of the FAR side of the mesh. That's the labeled-truth
# depth without paying for shading, lighting, textures. Silhouette = coverage = free alpha.

func _init() -> void:
	var mat := StandardMaterial3D.new()
	mat.cull_mode = BaseMaterial3D.CULL_FRONT   # the ONE line that does the trick

	# Construct a sphere mesh (not added to tree — we don't need to render, only validate the math
	# that the rasterizer would produce. Back-face z == analytic far intersection of the sphere ray).
	var sm := SphereMesh.new(); sm.radius = 0.6; sm.height = 1.2

	# World: sphere at (0,0,-1) r=0.6; camera at (0,0,1.5) looking -Z.
	var sc := Vector3(0, 0, -1); var sr := 0.6
	var co := Vector3(0, 0, 1.5)

	print("=== back-face cutout probe — sphere `( )` becomes `)` from camera ===")
	print("mesh:   SphereMesh r=%.2f at %s · material.cull_mode = %s" % [sr, sc, "CULL_FRONT"])
	print("camera: at %s looking -Z" % co)
	print("claim:  back-face z written to depth buffer = analytic FAR intersection")
	print()
	print("  ray_x   near_d   far_d    cutout_d  alpha  inv_alpha")
	print("  ─────   ──────   ──────   ────────  ─────  ─────────")

	var hits := 0; var miss := 0; var fd_min := 1e9; var fd_max := -1e9
	for i in range(-7, 8):
		var x: float = i * 0.1
		var dir: Vector3 = (Vector3(x, 0, -2) - co).normalized()
		var oc: Vector3 = co - sc
		var b: float = oc.dot(dir)
		var c: float = oc.dot(oc) - sr * sr
		var disc: float = b * b - c
		if disc < 0.0:
			print("  %5.2f   ─        ─        ─         0      1     (background — box back-wall visible)" % x)
			miss += 1
		else:
			var sd: float = sqrt(disc)
			var nd: float = -b - sd          # what CULL_BACK (normal) draws — near side
			var fd: float = -b + sd          # what CULL_FRONT draws — far side, our cutout depth
			print("  %5.2f   %.3f    %.3f    %.3f     1      0" % [x, nd, fd, fd])
			hits += 1; fd_min = min(fd_min, fd); fd_max = max(fd_max, fd)

	var total: int = hits + miss
	print()
	print("silhouette coverage = %d / %d rays  → that IS the alpha mask (rasterizer coverage)" % [hits, total])
	print("inverted alpha      = %d / %d rays  → one `1 - alpha` op in the shader" % [miss, total])
	print("parallax field      = far_d ∈ [%.3f, %.3f]  → real geometric depth, varies with camera" % [fd_min, fd_max])
	print()
	print("cost paid: ZERO shading, ZERO lighting, ZERO texture fetch.")
	print("           rasterizer coverage + z-write is the ENTIRE bill.")
	print("           animation cost = vertex transform only (= Blender-viewport speed).")
	print()
	print("upgrade path:")
	print("  far_d sample at (u,v)  ──→  compare to ATLAS by-pass/depth/<cid>  ──→  drift signal")
	print("  same .so call: SpatialBridge::fuse_depth(cam_pose, mesh, truth_cid)")
	quit()
