extends Object
# friend_graph_fetcher.gd — pulls the social graph for the current player
# from the dApp HTTP API (single-tenant, 127.0.0.1:8520) and falls back
# to a hardcoded seed when the endpoint is unreachable or not yet wired.
#
# Phase-1 (this file): synchronous fallback only. The dApp endpoint
#   GET /dapp/api/social_graph?player_id=<id>
# is being added by the dapp_server agent — once it's live, set
# `use_http = true` and pass a `player_id`.
#
# Schema returned (both paths):
#   {
#     "players":     [ {player_id, name, lat, lon, picture_url}, ... ],
#     "friendships": [ {player_a, player_b}, ... ]
#   }
#
# Consumed by planet_map_controller.gd.

const DAPP_BASE := "http://127.0.0.1:8520"
const ENDPOINT  := "/dapp/api/social_graph"

var use_http: bool = false   # flip to true once the dApp endpoint exists
var http_timeout_ms: int = 1500


func fetch_for_current_player(player_id: String = "local") -> Dictionary:
	# v1: try HTTP if enabled, otherwise return the local seed graph.
	if use_http:
		var fetched = _try_http_sync(player_id)
		if fetched != null:
			return fetched
		push_warning("[friend_graph_fetcher] HTTP fetch failed; returning seed data.")
	return _seed_graph()


func _try_http_sync(player_id: String):
	# Stdlib synchronous HTTP via HTTPRequest is tricky in pure Object;
	# we use HTTPClient directly which is happy outside the scene tree.
	var http := HTTPClient.new()
	var err := http.connect_to_host("127.0.0.1", 8520)
	if err != OK:
		return null
	# Spin until connected (bounded).
	var spins := 0
	while http.get_status() in [HTTPClient.STATUS_CONNECTING, HTTPClient.STATUS_RESOLVING]:
		http.poll()
		OS.delay_msec(10)
		spins += 1
		if spins > 100:
			return null
	if http.get_status() != HTTPClient.STATUS_CONNECTED:
		return null

	var path := "%s?player_id=%s" % [ENDPOINT, player_id.uri_encode()]
	err = http.request(HTTPClient.METHOD_GET, path, ["Accept: application/json"])
	if err != OK:
		return null

	spins = 0
	while http.get_status() == HTTPClient.STATUS_REQUESTING:
		http.poll()
		OS.delay_msec(10)
		spins += 1
		if spins > 200:
			return null

	if not http.has_response():
		return null
	if http.get_response_code() != 200:
		return null

	var body := PackedByteArray()
	while http.get_status() == HTTPClient.STATUS_BODY:
		http.poll()
		var chunk := http.read_response_body_chunk()
		if chunk.size() > 0:
			body.append_array(chunk)
	var text := body.get_string_from_utf8()
	var parsed = JSON.parse_string(text)
	if typeof(parsed) != TYPE_DICTIONARY:
		return null
	# Normalize shape — accept either {players, friendships} or {graph: {...}}
	if parsed.has("graph") and typeof(parsed["graph"]) == TYPE_DICTIONARY:
		parsed = parsed["graph"]
	if not (parsed.has("players") and parsed.has("friendships")):
		return null
	return parsed


func _seed_graph() -> Dictionary:
	# Static seed: 5 well-known cities, 5 friendships in a small-world shape.
	# Tom can hot-swap this for real data by flipping `use_http = true`.
	return {
		"players": [
			{"player_id": "local", "name": "You",   "lat": 40.7,    "lon": -74.0,  "picture_url": ""},   # NYC
			{"player_id": "f1",    "name": "Alice", "lat": 48.85,   "lon": 2.35,   "picture_url": ""},   # Paris
			{"player_id": "f2",    "name": "Bob",   "lat": 35.68,   "lon": 139.76, "picture_url": ""},   # Tokyo
			{"player_id": "f3",    "name": "Cleo",  "lat": -33.87,  "lon": 151.21, "picture_url": ""},   # Sydney
			{"player_id": "f4",    "name": "Dax",   "lat": 37.77,   "lon": -122.42,"picture_url": ""}    # SF
		],
		"friendships": [
			{"player_a": "local", "player_b": "f1"},
			{"player_a": "local", "player_b": "f2"},
			{"player_a": "f1",    "player_b": "f3"},
			{"player_a": "f2",    "player_b": "f4"},
			{"player_a": "local", "player_b": "f4"}
		]
	}
