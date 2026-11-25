extends Node
## SocialClient — Godot autoload for MySpace++ social bridge.
##
## Talks to the local MCP bridge (localhost:8765) via HTTPRequest nodes.
## Falls back to OS.execute("cc", ["-social-dev", ...]) for CLI ops not
## yet exposed as REST endpoints.
##
## Usage from any GDScript:
##   SocialClient.upload(["youtube"], "/path/to.mp4", "My video")
##   SocialClient.discord_send("#general", "hello world")
##   SocialClient.youtube_upload("/path/to.mp4", "Title", "Description")

signal upload_finished(platforms: String, ok: bool, detail: Dictionary)
signal batch_finished(ok: bool, detail: Dictionary)
signal cli_finished(cli_name: String, ok: bool, stdout: String)
signal status_ready(status: Dictionary)

const BRIDGE := "http://localhost:8765"
const UPLOAD_URL := BRIDGE + "/social/upload"
const BATCH_URL := BRIDGE + "/social/batch"
const STATUS_URL := BRIDGE + "/social/status"
const PLATFORMS_URL := BRIDGE + "/social/platforms"
const MCP_URL := BRIDGE + "/mcp/call"

var _pool: Array[HTTPRequest] = []
var _pool_size := 4

func _ready():
	for i in _pool_size:
		var r := HTTPRequest.new()
		r.name = "SocialHTTP_%d" % i
		add_child(r)
		_pool.append(r)
	print("SocialClient ready — bridge=%s" % BRIDGE)

func _req() -> HTTPRequest:
	for r in _pool:
		if r.get_http_client_status() == HTTPClient.STATUS_DISCONNECTED:
			return r
	# Pool saturated — return the first and let Godot queue internally
	return _pool[0]

func _post_json(url: String, body: Dictionary, callback: Callable) -> void:
	var r := _req()
	var json := JSON.stringify(body)
	var err := r.request(url, ["Content-Type: application/json"], HTTPClient.METHOD_POST, json)
	if err != OK:
		callback.call(false, "HTTP request start failed: %d" % err, {})
		return
	var cb := func(result: int, response_code: int, _headers: PackedStringArray, body_bytes: PackedByteArray):
		var txt := body_bytes.get_string_from_utf8()
		var data := {}
		if not txt.is_empty():
			var p := JSON.new()
			if p.parse(txt) == OK:
				data = p.data
		callback.call(response_code >= 200 and response_code < 300, txt, data)
	r.request_completed.connect(cb, CONNECT_ONE_SHOT)

func _get_json(url: String, callback: Callable) -> void:
	var r := _req()
	var err := r.request(url)
	if err != OK:
		callback.call(false, "HTTP GET start failed: %d" % err, {})
		return
	var cb := func(result: int, response_code: int, _headers: PackedStringArray, body_bytes: PackedByteArray):
		var txt := body_bytes.get_string_from_utf8()
		var data := {}
		if not txt.is_empty():
			var p := JSON.new()
			if p.parse(txt) == OK:
				data = p.data
		callback.call(response_code >= 200 and response_code < 300, txt, data)
	r.request_completed.connect(cb, CONNECT_ONE_SHOT)

## ── Core upload API ─────────────────────────────────────────────────────────

func upload(platforms: PackedStringArray, file_path: String, caption: String = "", metadata: Dictionary = {}) -> void:
	var body := {
		"platforms": Array(platforms),
		"file_path": file_path,
		"caption": caption,
		"metadata": metadata
	}
	_post_json(UPLOAD_URL, body, func(ok: bool, _txt: String, data: Dictionary):
		upload_finished.emit(",".join(platforms), ok, data if ok else {"error": _txt})
	)

func batch_upload(files: Array) -> void:
	## files: Array of Dicts: [{"file_path": "...", "caption": "...", "platforms": ["youtube"]}]
	_post_json(BATCH_URL, {"files": files}, func(ok: bool, _txt: String, data: Dictionary):
		batch_finished.emit(ok, data if ok else {"error": _txt})
	)

## ── Status / introspection ────────────────────────────────────────────────

func get_status(callback: Callable = Callable()) -> void:
	_get_json(STATUS_URL, func(ok: bool, _txt: String, data: Dictionary):
		status_ready.emit(data if ok else {})
		if callback.is_valid():
			callback.call(ok, data)
	)

func get_platforms(callback: Callable) -> void:
	_get_json(PLATFORMS_URL, func(ok: bool, _txt: String, data: Dictionary):
		callback.call(ok, data if ok else {})
	)

## ── MCP tool calls (any tool exposed by the bridge) ───────────────────────

func mcp_call(tool: String, params: Dictionary, callback: Callable = Callable()) -> void:
	var body := {
		"jsonrpc": "2.0",
		"id": str(randi()),
		"method": "tools/call",
		"params": {
			"name": tool,
			"arguments": params
		}
	}
	_post_json(MCP_URL, body, func(ok: bool, _txt: String, data: Dictionary):
		var result := {}
		if ok and data.has("result"):
			result = data["result"]
		elif data.has("error"):
			result = {"error": data["error"]}
		else:
			result = {"raw": _txt}
		if callback.is_valid():
			callback.call(ok, result)
	)

## ── CLI fallback (spawns Python CLIs via cc dispatcher) ────────────────────

func cli(cli_name: String, args: PackedStringArray, callback: Callable = Callable()) -> void:
	var output := []
	var cmd := "cc -social-dev %s %s" % [cli_name, " ".join(args)]
	var rc := OS.execute("bash", ["-c", cmd], output, true)
	var ok := rc == 0
	var stdout := "\n".join(output)
	cli_finished.emit(cli_name, ok, stdout)
	if callback.is_valid():
		callback.call(ok, stdout)

func cli_raw(python_script: String, args: PackedStringArray, callback: Callable = Callable()) -> void:
	var output := []
	var rc := OS.execute("python3", [python_script] + Array(args), output, true)
	var ok := rc == 0
	var stdout := "\n".join(output)
	cli_finished.emit(python_script.get_file().get_basename(), ok, stdout)
	if callback.is_valid():
		callback.call(ok, stdout)

## ── Convenience wrappers per platform ──────────────────────────────────────

func youtube_upload(file_path: String, title: String, desc: String = "", tags: PackedStringArray = []) -> void:
	upload(["youtube"], file_path, title, {"description": desc, "tags": Array(tags)})

func telegram_send(chat_id: String, text: String, file_path: String = "") -> void:
	if file_path.is_empty():
		mcp_call("social:upload", {"platforms": ["telegram"], "caption": text})  # bridge handles text-only
	else:
		upload(["telegram"], file_path, text)

func discord_send(channel_id: String, text: String, file_path: String = "") -> void:
	if file_path.is_empty():
		mcp_call("discord:send_message", {"channel_id": channel_id, "content": text})
	else:
		upload(["discord"], file_path, text)

func facebook_post(page_id: String, message: String, file_path: String = "") -> void:
	if file_path.is_empty():
		mcp_call("social:upload", {"platforms": ["facebook"], "caption": message})
	else:
		upload(["facebook"], file_path, message)

func whatsapp_send(phone: String, text: String, file_path: String = "") -> void:
	if file_path.is_empty():
		mcp_call("social:upload", {"platforms": ["whatsapp"], "caption": text})
	else:
		upload(["whatsapp"], file_path, text)

func twitch_message(channel: String, text: String) -> void:
	mcp_call("social:upload", {"platforms": ["twitch"], "caption": text, "channel": channel})

func tiktok_upload(file_path: String, title: String) -> void:
	upload(["tiktok"], file_path, title)

func twitter_tweet(text: String, file_path: String = "") -> void:
	if file_path.is_empty():
		cli("x", ["tweet", text])
	else:
		upload(["x"], file_path, text)

func twilio_send(to: String, text: String, media_url: String = "") -> void:
	mcp_call("social:upload", {"platforms": ["twilio"], "caption": text, "to": to, "media_url": media_url})

func onlyfans_upload(file_path: String, caption: String = "") -> void:
	upload(["onlyfans"], file_path, caption)

## ── Livepeer helpers ──────────────────────────────────────────────────────

func livepeer_create_stream(name: String) -> void:
	mcp_call("livepeer:create_stream", {"name": name})

func livepeer_get_stream(stream_id: String, callback: Callable) -> void:
	mcp_call("livepeer:get_stream", {"stream_id": stream_id}, callback)

## ── Raw dev-kit helpers for each CLI ─────────────────────────────────────

func x_cli(args: PackedStringArray, callback: Callable = Callable()) -> void:
	cli("x", args, callback)

func discord_cli(args: PackedStringArray, callback: Callable = Callable()) -> void:
	cli("discord", args, callback)

func telegram_cli(args: PackedStringArray, callback: Callable = Callable()) -> void:
	cli("telegram", args, callback)

func facebook_cli(args: PackedStringArray, callback: Callable = Callable()) -> void:
	cli("facebook", args, callback)

func snapchat_cli(args: PackedStringArray, callback: Callable = Callable()) -> void:
	cli("snapchat", args, callback)

func livepeer_cli(args: PackedStringArray, callback: Callable = Callable()) -> void:
	cli("livepeer", args, callback)

func games_cli(args: PackedStringArray, callback: Callable = Callable()) -> void:
	cli("games", args, callback)

## ── OAuth helpers ───────────────────────────────────────────────────────────

func oauth_start(platform: String) -> void:
	## Initiate OAuth flow and open browser.
	_get_json(BRIDGE + "/oauth/start/" + platform, func(ok: bool, _txt: String, data: Dictionary):
		if ok and data.has("auth_url"):
			print("SocialClient: opening OAuth URL for ", platform)
			OS.shell_open(data["auth_url"])
		else:
			push_warning("SocialClient OAuth start failed: " + _txt)
	)

func oauth_refresh(platform: String, callback: Callable = Callable()) -> void:
	_post_json(BRIDGE + "/oauth/refresh/" + platform, {}, func(ok: bool, _txt: String, data: Dictionary):
		if callback.is_valid():
			callback.call(ok, data)
	)

func oauth_status(callback: Callable = Callable()) -> void:
	_get_json(BRIDGE + "/oauth/status", func(ok: bool, _txt: String, data: Dictionary):
		if callback.is_valid():
			callback.call(ok, data if ok else {})
	)

func oauth_revoke(platform: String, callback: Callable = Callable()) -> void:
	_post_json(BRIDGE + "/oauth/revoke/" + platform, {}, func(ok: bool, _txt: String, data: Dictionary):
		if callback.is_valid():
			callback.call(ok, data)
	)
