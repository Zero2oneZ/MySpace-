extends Node3D
## asset_3d_loader — closes the generate_3d loop: fetches every GLB produced by
## generative_mcp.generate_3d from the dApp (:8520), runtime-loads each via
## GLTFDocument, and arranges them in a 3D grid. Rigged/animated assets (the
## walk cycles) auto-play their first animation. Polls for new assets.
##
## This is the "3d scene mapping" that was missing — assets were announced to
## the SSOT bridge but never instantiated in-engine. Now they are.

const BASE := "http://127.0.0.1:8520"
const SPACING := 3.0
const COLS := 5

var _http: HTTPRequest
var _busy := false
var _placed := {}      # stem -> true
var _idx := 0

func _ready() -> void:
	_http = HTTPRequest.new()
	add_child(_http)
	_setup_env()
	await _refresh()
	var t := Timer.new()
	t.wait_time = 6.0
	t.autostart = true
	add_child(t)
	t.timeout.connect(func() -> void: await _refresh())

func _setup_env() -> void:
	var cam := Camera3D.new()
	cam.position = Vector3(0, 2.5, 9)
	add_child(cam)                       # must be in-tree before look_at()
	cam.look_at(Vector3(0, 1, 0), Vector3.UP)
	var light := DirectionalLight3D.new()
	light.rotation_degrees = Vector3(-50, -35, 0)
	add_child(light)
	var env := WorldEnvironment.new()
	var e := Environment.new()
	e.background_mode = Environment.BG_COLOR
	e.background_color = Color(0.043, 0.055, 0.078)
	e.ambient_light_color = Color(0.4, 0.45, 0.55)
	e.ambient_light_energy = 0.6
	env.environment = e
	add_child(env)

func _refresh() -> void:
	if _busy:
		return
	_busy = true
	var body := await _fetch(BASE + "/dapp/api/assets3d")
	if body.is_empty():
		_busy = false
		return
	var doc = JSON.parse_string(body.get_string_from_utf8())
	if typeof(doc) != TYPE_DICTIONARY or not doc.has("assets"):
		_busy = false
		return
	for a in doc["assets"]:
		var stem := str(a.get("stem", ""))
		if stem == "" or _placed.has(stem):
			continue
		var glb := await _fetch(BASE + str(a.get("url", "")))
		if glb.is_empty():
			continue
		_spawn(stem, glb, bool(a.get("animated", false)))
		_placed[stem] = true
	_busy = false

func _fetch(url: String) -> PackedByteArray:
	var err := _http.request(url)
	if err != OK:
		return PackedByteArray()
	var r = await _http.request_completed   # [result, code, headers, body]
	if int(r[1]) != 200:
		return PackedByteArray()
	return r[3]

func _spawn(stem: String, bytes: PackedByteArray, animated: bool) -> void:
	var gdoc := GLTFDocument.new()
	var state := GLTFState.new()
	var err := gdoc.append_from_buffer(bytes, "", state)
	if err != OK:
		push_warning("asset_3d_loader: GLB parse failed for %s (err %d)" % [stem, err])
		return
	var node := gdoc.generate_scene(state)
	if node == null:
		return
	node.name = stem
	var col := _idx % COLS
	var row := _idx / COLS
	node.position = Vector3((col - (COLS - 1) / 2.0) * SPACING, 0.0, -row * SPACING)
	add_child(node)
	_idx += 1
	if animated:
		var ap := node.find_child("AnimationPlayer", true, false)
		if ap != null and ap is AnimationPlayer:
			var names := (ap as AnimationPlayer).get_animation_list()
			if names.size() > 0:
				var anim := (ap as AnimationPlayer).get_animation(names[0])
				if anim != null:
					anim.loop_mode = Animation.LOOP_LINEAR
				(ap as AnimationPlayer).play(names[0])
	print("asset_3d_loader: placed %s (animated=%s) at %s" % [stem, animated, node.position])
