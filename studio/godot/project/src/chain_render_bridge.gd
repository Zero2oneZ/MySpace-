extends Node
## chain_render_bridge.gd — Godot autoload that pulls chain renders + events
## from the godot_ssot_proxy sidecar (:8766) and emits signals.
##
## Wires into the existing cc_bridge.gd autoload pattern. Polls instead of SSE
## (HTTPRequest in Godot 4 doesn't do streaming well; for that we already have
## cc_bridge.gd file-tail; this is the HTTP face).
##
## Endpoints consumed (see core/lib/godot_ssot_proxy.py):
##   GET /chain/renders/recent?n=20
##   GET /chain/render/<crystal_short>/manifest
##   GET /chain/render/<crystal_short>/image        (image/png)
##   GET /chain/render/<crystal_short>/video        (video/mp4)
##   GET /chain/programs/watchset
##   GET /chain/events/recent?n=N&program=X&category=Y
##
## All require Authorization: Bearer <freetier_token>. Get one via:
##   cc freetier-issue --user-id godot_local --domain GentlyOS.io
##
## Signals fired:
##   render_arrived(crystal_short, image_path, manifest)  — when a new render
##                                                          finishes downloading
##   event_arrived(event_dict)                            — per fresh chain event
##   watchset_loaded(entries)                              — on first successful poll
##   bridge_offline(error)                                 — on connect failure
##
## Usage from a scene (e.g. chain_render_wall.gd):
##   ChainRenderBridge.render_arrived.connect(_on_render)
##   ChainRenderBridge.start()                            — begins polling

signal render_arrived(crystal_short: String, image_path: String, manifest: Dictionary)
signal event_arrived(event: Dictionary)
signal watchset_loaded(entries: Array)
signal bridge_offline(error: String)

@export var proxy_base_url: String = "http://127.0.0.1:8766"
@export var bearer_token: String = ""  # required; set from project settings
                                         # or env at startup
@export var poll_interval_s: float = 3.0
@export var image_cache_dir: String = "user://chain_render_cache"
@export var verbose: bool = true
@export var ring_max: int = 50

# Internal state
var _poll_timer: Timer
var _seen_crystals: Dictionary = {}  # crystal_short → true (de-dup)
var _ring: Array = []                 # most-recent-first
var _http_renders: HTTPRequest
var _http_image: HTTPRequest
var _http_events: HTTPRequest
var _http_watchset: HTTPRequest
var _pending_image: String = ""        # crystal_short of in-flight image fetch
var _pending_manifest: Dictionary = {}
var _last_event_ts: float = 0.0
var _started: bool = false


# ── lifecycle ───────────────────────────────────────────────────────────────

func _ready() -> void:
	# Resolve token from env if @export var is empty (handy for dev).
	if bearer_token.is_empty():
		bearer_token = OS.get_environment("MSPC_GODOT_BEARER")
	if bearer_token.is_empty():
		var dev_path = OS.get_environment("HOME") + "/.cc/godot_dev_token.txt"
		if FileAccess.file_exists(dev_path):
			var f = FileAccess.open(dev_path, FileAccess.READ)
			bearer_token = f.get_as_text().strip_edges()
			f.close()
	if verbose:
		print("ChainRenderBridge: ready, proxy=", proxy_base_url,
				" token=", "set" if not bearer_token.is_empty() else "MISSING")

	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(image_cache_dir))

	_http_renders = HTTPRequest.new()
	_http_image = HTTPRequest.new()
	_http_events = HTTPRequest.new()
	_http_watchset = HTTPRequest.new()
	add_child(_http_renders)
	add_child(_http_image)
	add_child(_http_events)
	add_child(_http_watchset)
	_http_renders.request_completed.connect(_on_renders_completed)
	_http_image.request_completed.connect(_on_image_completed)
	_http_events.request_completed.connect(_on_events_completed)
	_http_watchset.request_completed.connect(_on_watchset_completed)


func start() -> void:
	if _started:
		return
	_started = true
	# Initial pulls
	_poll_watchset()
	_poll_renders()
	_poll_events()
	# Cyclic poller
	_poll_timer = Timer.new()
	_poll_timer.wait_time = poll_interval_s
	_poll_timer.autostart = true
	_poll_timer.timeout.connect(_on_poll)
	add_child(_poll_timer)


func stop() -> void:
	_started = false
	if _poll_timer != null:
		_poll_timer.stop()
		_poll_timer.queue_free()
		_poll_timer = null


func _on_poll() -> void:
	_poll_renders()
	_poll_events()


# ── HTTP poll: /chain/renders/recent ────────────────────────────────────────

func _poll_renders() -> void:
	var url = proxy_base_url + "/chain/renders/recent?n=20"
	var headers = _auth_headers()
	var err = _http_renders.request(url, headers)
	if err != OK and verbose:
		push_warning("ChainRenderBridge: renders request failed code=%d" % err)


func _on_renders_completed(_result: int, code: int, _hdrs: PackedStringArray,
		body: PackedByteArray) -> void:
	if code != 200:
		emit_signal("bridge_offline", "renders HTTP %d" % code)
		if verbose:
			print("ChainRenderBridge: renders HTTP ", code, " body=",
					body.get_string_from_utf8().substr(0, 200))
		return
	var json = JSON.new()
	if json.parse(body.get_string_from_utf8()) != OK:
		push_error("ChainRenderBridge: bad JSON on /chain/renders/recent")
		return
	var data = json.data
	var renders = data.get("renders", [])
	for r in renders:
		var cs = r.get("crystal_short", "")
		if cs.is_empty() or _seen_crystals.has(cs):
			continue
		# Only download images that finished rendering server-side
		if r.get("image_status", "") != "rendered":
			continue
		_seen_crystals[cs] = true
		# Cache hit?
		var cached_path = "%s/%s.png" % [image_cache_dir, cs]
		if FileAccess.file_exists(cached_path):
			_emit_render(cs, ProjectSettings.globalize_path(cached_path), r)
			continue
		# Fetch image (sequential — one at a time to avoid HTTPRequest reuse)
		if _pending_image.is_empty():
			_fetch_image(cs, r)


func _fetch_image(crystal_short: String, manifest_summary: Dictionary) -> void:
	_pending_image = crystal_short
	_pending_manifest = manifest_summary
	var url = proxy_base_url + "/chain/render/" + crystal_short + "/image"
	var err = _http_image.request(url, _auth_headers())
	if err != OK:
		_pending_image = ""
		push_warning("ChainRenderBridge: image request failed code=%d" % err)


func _on_image_completed(_result: int, code: int, _hdrs: PackedStringArray,
		body: PackedByteArray) -> void:
	var cs = _pending_image
	var manifest = _pending_manifest
	_pending_image = ""
	_pending_manifest = {}
	if cs.is_empty():
		return
	if code != 200:
		push_warning("ChainRenderBridge: image HTTP %d for %s" % [code, cs])
		return
	var dest = "%s/%s.png" % [image_cache_dir, cs]
	var f = FileAccess.open(dest, FileAccess.WRITE)
	if f == null:
		push_error("ChainRenderBridge: cannot open cache file ", dest)
		return
	f.store_buffer(body)
	f.close()
	_emit_render(cs, ProjectSettings.globalize_path(dest), manifest)


func _emit_render(crystal_short: String, image_path: String,
		manifest: Dictionary) -> void:
	# Ring buffer
	_ring.push_front({"crystal_short": crystal_short, "image_path": image_path,
			"manifest": manifest, "ts": Time.get_unix_time_from_system()})
	while _ring.size() > ring_max:
		_ring.pop_back()
	if verbose:
		print("ChainRenderBridge: render_arrived ", crystal_short,
				" cat=", manifest.get("category", ""),
				" act=", manifest.get("action", ""))
	emit_signal("render_arrived", crystal_short, image_path, manifest)


# ── HTTP poll: /chain/events/recent ─────────────────────────────────────────

func _poll_events() -> void:
	var url = proxy_base_url + "/chain/events/recent?n=50"
	var err = _http_events.request(url, _auth_headers())
	if err != OK and verbose:
		push_warning("ChainRenderBridge: events request failed code=%d" % err)


func _on_events_completed(_result: int, code: int, _hdrs: PackedStringArray,
		body: PackedByteArray) -> void:
	if code != 200:
		return
	var json = JSON.new()
	if json.parse(body.get_string_from_utf8()) != OK:
		return
	var data = json.data
	var events = data.get("events", [])
	# Emit only events newer than last seen ts
	var newest_seen = _last_event_ts
	for ev in events:
		var ts = float(ev.get("ts", 0.0))
		if ts > _last_event_ts:
			emit_signal("event_arrived", ev)
			if ts > newest_seen:
				newest_seen = ts
	_last_event_ts = newest_seen


# ── HTTP poll: /chain/programs/watchset (one-shot at startup) ───────────────

func _poll_watchset() -> void:
	var url = proxy_base_url + "/chain/programs/watchset"
	var err = _http_watchset.request(url, _auth_headers())
	if err != OK and verbose:
		push_warning("ChainRenderBridge: watchset request failed code=%d" % err)


func _on_watchset_completed(_result: int, code: int, _hdrs: PackedStringArray,
		body: PackedByteArray) -> void:
	if code != 200:
		return
	var json = JSON.new()
	if json.parse(body.get_string_from_utf8()) != OK:
		return
	var entries = json.data.get("watchset", [])
	if verbose:
		print("ChainRenderBridge: watchset loaded n=", entries.size())
	emit_signal("watchset_loaded", entries)


# ── helpers ─────────────────────────────────────────────────────────────────

func _auth_headers() -> PackedStringArray:
	if bearer_token.is_empty():
		return PackedStringArray([])
	return PackedStringArray([
		"Authorization: Bearer " + bearer_token,
		"X-Client: godot-chain-render-bridge",
	])


func get_recent() -> Array:
	return _ring.duplicate()
