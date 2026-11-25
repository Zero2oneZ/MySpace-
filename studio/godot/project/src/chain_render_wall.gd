extends Node3D
## chain_render_wall.gd — 3D wall of chain renders.
##
## Listens to ChainRenderBridge.render_arrived and spawns one TextureRect3D
## (a Sprite3D backed by the downloaded PNG) per render. Tiles are positioned
## in a spiral grid that pulls newer ones closer to camera; modulate is tinted
## by dim_pack.rgba so different categories show distinct colors.
##
## Drop this into a scene as a Node3D, add the script, and it self-populates.
## Camera is set up automatically if no other Camera3D is present.

@export var tile_size: float = 1.4
@export var tile_spacing: float = 0.4
@export var grid_cols: int = 6
@export var newest_z: float = -2.0
@export var depth_step: float = -0.8
@export var max_tiles: int = 60
@export var auto_orbit_camera: bool = true
@export var orbit_radius: float = 8.0
@export var orbit_height: float = 2.5
@export var orbit_period_s: float = 30.0

var _tiles: Array[Node3D] = []   # newest-first
var _camera: Camera3D = null
var _t: float = 0.0


func _ready() -> void:
	# Background colour so an empty wall isn't black-on-black
	var world := WorldEnvironment.new()
	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color(0.06, 0.07, 0.10)
	env.ambient_light_color = Color(0.6, 0.65, 0.8)
	env.ambient_light_energy = 0.7
	world.environment = env
	add_child(world)

	if auto_orbit_camera and get_viewport().get_camera_3d() == null:
		_camera = Camera3D.new()
		add_child(_camera)  # add to tree FIRST, THEN look_at
		_camera.position = Vector3(0, orbit_height, orbit_radius)
		_camera.look_at(Vector3.ZERO, Vector3.UP)

	# Sun
	var env_light = DirectionalLight3D.new()
	add_child(env_light)
	env_light.rotation_degrees = Vector3(-45, -45, 0)
	env_light.light_energy = 1.0

	# Connect to bridge autoload
	if Engine.has_singleton("ChainRenderBridge") or get_node_or_null("/root/ChainRenderBridge") != null:
		var br = get_node("/root/ChainRenderBridge")
		br.render_arrived.connect(_on_render_arrived)
		br.start()
		print("chain_render_wall: subscribed to ChainRenderBridge")
	else:
		push_error("chain_render_wall: ChainRenderBridge autoload not found")


func _process(delta: float) -> void:
	_t += delta
	if auto_orbit_camera and _camera != null:
		var theta = (_t / orbit_period_s) * TAU
		_camera.position = Vector3(sin(theta) * orbit_radius,
				orbit_height + sin(_t * 0.3) * 0.5,
				cos(theta) * orbit_radius)
		_camera.look_at(Vector3.ZERO, Vector3.UP)


func _on_render_arrived(crystal_short: String, image_path: String,
		manifest: Dictionary) -> void:
	print("chain_render_wall: render_arrived ", crystal_short,
			" path=", image_path,
			" cat=", manifest.get("category", "?"))
	var tile = _build_tile(crystal_short, image_path, manifest)
	if tile == null:
		push_warning("chain_render_wall: _build_tile returned null for " + crystal_short)
		return
	_tiles.push_front(tile)
	add_child(tile)
	while _tiles.size() > max_tiles:
		var old = _tiles.pop_back()
		if is_instance_valid(old):
			old.queue_free()
	_reposition_all()
	print("chain_render_wall: tile count now ", _tiles.size())


func _build_tile(crystal_short: String, image_path: String,
		manifest: Dictionary) -> Node3D:
	var img = Image.load_from_file(image_path)
	if img == null:
		push_warning("chain_render_wall: load_from_file failed ", image_path)
		return null
	var tex = ImageTexture.create_from_image(img)
	var root = Node3D.new()
	root.name = "tile_" + crystal_short

	# Backing quad (Sprite3D with shaderless modulate)
	var sprite = Sprite3D.new()
	sprite.texture = tex
	sprite.pixel_size = tile_size / max(1.0, max(img.get_width(), img.get_height()))
	# tint by dim_pack.rgba (clip alpha to 1 — opacity 0.92 looks watery)
	var dim = manifest.get("dim", {})
	var rgba = dim.get("rgba", [1.0, 1.0, 1.0, 1.0])
	if rgba is Array and rgba.size() >= 3:
		sprite.modulate = Color(rgba[0], rgba[1], rgba[2], 1.0)
	root.add_child(sprite)

	# Category label below
	var label = Label3D.new()
	label.text = "%s · %s" % [str(manifest.get("category", "?")).to_lower(),
			str(manifest.get("action", "?")).to_lower()]
	label.font_size = 30
	label.outline_size = 8
	label.position = Vector3(0, -tile_size * 0.55, 0)
	label.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	label.modulate = Color(0.9, 0.9, 1.0, 0.9)
	root.add_child(label)

	# Crystal hash micro-label
	var crystal_label = Label3D.new()
	crystal_label.text = crystal_short.substr(0, 12)
	crystal_label.font_size = 18
	crystal_label.outline_size = 4
	crystal_label.position = Vector3(0, -tile_size * 0.72, 0)
	crystal_label.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	crystal_label.modulate = Color(0.6, 0.7, 0.8, 0.7)
	root.add_child(crystal_label)

	return root


func _reposition_all() -> void:
	for i in range(_tiles.size()):
		var row = i / grid_cols
		var col = i % grid_cols
		var x = (col - (grid_cols - 1) * 0.5) * (tile_size + tile_spacing)
		var y = -(row * (tile_size + tile_spacing))
		var z = newest_z + (row * depth_step)
		var t = _tiles[i]
		if is_instance_valid(t):
			t.position = Vector3(x, y + 2.0, z)
