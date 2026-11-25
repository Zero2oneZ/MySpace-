extends Node3D
class_name PlanetMapController
# planet_map_controller.gd — drives the social-graph planet scene.
#
# Responsibilities:
#   1. Fetch graph (players + friendships) from friend_graph_fetcher.
#   2. Place a small colored sphere at each player's (lat, lon).
#   3. Draw a curved great-circle "arc" mesh between every friendship pair.
#   4. Slowly orbit the camera around the planet.
#   5. Update HUD label with connected count.
#
# Attached to the root node of scenes/planet_map.tscn.

var connected_players: Array = []  # [{player_id, lat, lon, name, picture_url}, ...]
var friendships: Array = []         # [{player_a, player_b}, ...]
var sphere_radius: float = 5.0

# Cached so _build_edges can map id -> Vector3 without re-traversing children.
var _pos_by_id: Dictionary = {}


func _ready() -> void:
	_fetch_data()
	_paint_earth()
	_build_nodes()
	_build_edges()
	_update_hud()
	_spin_camera()


func _fetch_data() -> void:
	var fetcher = preload("res://src/friend_graph_fetcher.gd").new()
	var result: Dictionary = fetcher.fetch_for_current_player("local")
	connected_players = result.get("players", [])
	friendships = result.get("friendships", [])


func _paint_earth() -> void:
	# Apply a stylized blue/green unlit material to the Earth sphere so we
	# don't depend on an imported texture for v1.
	var earth: MeshInstance3D = $Earth
	if earth == null:
		return
	var mat := StandardMaterial3D.new()
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_PER_PIXEL
	mat.albedo_color = Color(0.18, 0.42, 0.62)         # deep ocean blue
	mat.metallic = 0.05
	mat.roughness = 0.85
	mat.rim_enabled = true
	mat.rim = 0.4
	mat.rim_tint = 0.5
	earth.material_override = mat


func _build_nodes() -> void:
	var container: Node3D = $Earth/PlayerNodes
	if container == null:
		push_error("[planet_map] missing $Earth/PlayerNodes")
		return
	var helper = preload("res://src/geo_to_xyz.gd").new()
	_pos_by_id.clear()
	for p in connected_players:
		var lat: float = float(p.get("lat", 0.0))
		var lon: float = float(p.get("lon", 0.0))
		var pos: Vector3 = helper.lat_lon_to_xyz(lat, lon, sphere_radius * 1.01)
		var node: MeshInstance3D = _make_player_sphere(p)
		node.transform.origin = pos
		container.add_child(node)
		_pos_by_id[str(p.get("player_id", ""))] = pos


func _build_edges() -> void:
	var container: Node3D = $Earth/FriendEdges
	if container == null:
		push_error("[planet_map] missing $Earth/FriendEdges")
		return
	var helper = preload("res://src/geo_to_xyz.gd").new()
	for f in friendships:
		var a_id: String = str(f.get("player_a", ""))
		var b_id: String = str(f.get("player_b", ""))
		if not _pos_by_id.has(a_id) or not _pos_by_id.has(b_id):
			continue
		var a: Vector3 = _pos_by_id[a_id]
		var b: Vector3 = _pos_by_id[b_id]
		var pts: Array = helper.great_circle_arc_lifted(a, b, 24, 0.06)
		var edge_mesh := _make_arc_mesh(pts)
		edge_mesh.name = "Edge_%s_%s" % [a_id, b_id]
		container.add_child(edge_mesh)


func _make_arc_mesh(points: Array) -> MeshInstance3D:
	# Build a thin polyline as an ImmediateMesh (LINE_STRIP). Lightweight,
	# no per-edge CSGCylinder allocation. Color: soft cyan, unlit.
	var mi := MeshInstance3D.new()
	var im := ImmediateMesh.new()
	var mat := StandardMaterial3D.new()
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	mat.albedo_color = Color(0.55, 0.92, 1.0, 0.9)
	mat.vertex_color_use_as_albedo = false
	mat.cull_mode = BaseMaterial3D.CULL_DISABLED

	im.surface_begin(Mesh.PRIMITIVE_LINE_STRIP, mat)
	for p in points:
		im.surface_add_vertex(p)
	im.surface_end()

	mi.mesh = im
	return mi


func _make_player_sphere(p: Dictionary) -> MeshInstance3D:
	var m := MeshInstance3D.new()
	var sm := SphereMesh.new()
	sm.radius = 0.08
	sm.height = 0.16
	m.mesh = sm
	var mat := StandardMaterial3D.new()
	# Stable per-player color from the id hash so it doesn't reshuffle on refresh.
	var id_str: String = str(p.get("player_id", "?"))
	var hue: float = float(id_str.hash() % 1000) / 1000.0
	mat.albedo_color = Color.from_hsv(hue, 0.7, 0.95)
	mat.emission_enabled = true
	mat.emission = mat.albedo_color
	mat.emission_energy_multiplier = 0.6
	m.material_override = mat
	m.name = "Player_" + id_str
	return m


func _update_hud() -> void:
	var label: Label = get_node_or_null("HUD/Label")
	if label != null:
		label.text = "Connected players: %d" % connected_players.size()


func _spin_camera() -> void:
	# Slow infinite orbit of the camera around the Y axis for ambience.
	var cam: Camera3D = get_node_or_null("Camera3D")
	if cam == null:
		return
	var t := create_tween()
	t.set_loops(0)            # 0 = infinite
	t.set_trans(Tween.TRANS_LINEAR)
	t.tween_property(cam, "rotation:y", cam.rotation.y + PI * 2.0, 60.0)
