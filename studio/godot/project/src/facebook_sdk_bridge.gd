extends Node
# class_name FacebookSDKBridge removed — same-name autoload already exists.
## Facebook SDK Bridge — autoload that surfaces FB JS SDK in web builds
## and emits pending_native_call signals in mobile / desktop builds
## (Android + iOS native plugins are deferred to phase 2).
##
## Reads FB_APP_ID from ProjectSettings:
##   "application/config/facebook_app_id" (string)
## If unset / empty, all calls return early with a warning.
##
## Cross-process visibility: every call (success or stub) is appended to
## ~/.cc/godot_fb_events.jsonl for the cc side to pick up:
##   { "ts": <unix>, "event": <str>, "details": {...} }

signal login_status_changed(connected: bool, user_id: String)
signal app_event_logged(event_name: String)
signal share_completed(shared: bool)
signal pending_native_call(method: String, args: Dictionary)

const EVENT_LOG_PATH := "user://godot_fb_events.jsonl"
const EVENT_LOG_GLOBAL := "~/.cc/godot_fb_events.jsonl"
const SDK_VERSION := "v18.0"

var _app_id: String = ""
var _is_web: bool = false
var _sdk_initialized: bool = false
var _logged_in: bool = false
var _user_id: String = ""

func _ready() -> void:
	_is_web = OS.has_feature("web")
	_app_id = str(ProjectSettings.get_setting("application/config/facebook_app_id", ""))
	if _app_id.is_empty():
		push_warning("FacebookSDKBridge: facebook_app_id project setting empty — bridge disabled")
		_emit_event("init_skipped", { "reason": "no_app_id" })
		return
	init()

func init() -> void:
	if _app_id.is_empty():
		push_warning("FacebookSDKBridge.init(): no app_id, skipping")
		return
	if _is_web:
		_init_web()
	else:
		_emit_event("init_native_stub", { "platform": OS.get_name() })
		pending_native_call.emit("init", { "app_id": _app_id })

func _init_web() -> void:
	if not Engine.has_singleton("JavaScriptBridge") and typeof(JavaScriptBridge) == TYPE_NIL:
		push_warning("FacebookSDKBridge: web build but JavaScriptBridge unavailable")
		_emit_event("init_web_unavailable", {})
		return

	# Inject the SDK script tag and call FB.init from a single eval.
	# The SDK loads async — we set up window.fbAsyncInit before injecting.
	var snippet := """
		(function() {
			if (window.__mspc_fb_sdk_injected) { return; }
			window.__mspc_fb_sdk_injected = true;
			window.fbAsyncInit = function() {
				FB.init({
					appId: '%s',
					cookie: true,
					xfbml: false,
					version: '%s'
				});
				window.__mspc_fb_ready = true;
			};
			var s = document.createElement('script');
			s.src = 'https://connect.facebook.net/en_US/sdk.js';
			s.async = true;
			s.defer = true;
			s.crossOrigin = 'anonymous';
			document.head.appendChild(s);
		})();
	""" % [_app_id, SDK_VERSION]
	JavaScriptBridge.eval(snippet, true)
	_sdk_initialized = true
	_emit_event("init_web_injected", { "app_id": _app_id, "sdk_version": SDK_VERSION })

# ─── public API ───────────────────────────────────────────────────

func login(scopes: Array = ["public_profile"]) -> void:
	if _app_id.is_empty():
		push_warning("FacebookSDKBridge.login(): no app_id")
		return
	var scope_str := ",".join(scopes)
	_emit_event("login_called", { "scopes": scopes })
	if _is_web and _sdk_initialized:
		var js := """
			(function() {
				if (!window.__mspc_fb_ready || typeof FB === 'undefined') { return JSON.stringify({status:'sdk_not_ready'}); }
				FB.login(function(response) {
					window.__mspc_fb_login_response = JSON.stringify(response);
				}, { scope: '%s' });
				return JSON.stringify({status:'login_dispatched'});
			})();
		""" % scope_str
		var result: Variant = JavaScriptBridge.eval(js, true)
		_emit_event("login_web_dispatched", { "result": str(result) })
		# Polling for response is left to the integrator — typically a Timer
		# reads window.__mspc_fb_login_response and calls _on_login_response.
	else:
		pending_native_call.emit("login", { "scopes": scopes })

func _on_login_response(connected: bool, user_id: String) -> void:
	_logged_in = connected
	_user_id = user_id
	login_status_changed.emit(connected, user_id)
	_emit_event("login_status_changed", { "connected": connected, "user_id": user_id })

func log_app_event(event_name: String, value: Variant = null, params: Dictionary = {}) -> void:
	if _app_id.is_empty():
		push_warning("FacebookSDKBridge.log_app_event(): no app_id")
		return
	_emit_event("app_event_logged", { "event": event_name, "value": value, "params": params })
	if _is_web and _sdk_initialized:
		var params_json := JSON.stringify(params)
		var value_js := "null"
		if value != null:
			value_js = JSON.stringify(value)
		var js := """
			(function() {
				if (typeof FB !== 'undefined' && FB.AppEvents) {
					FB.AppEvents.logEvent('%s', %s, %s);
					return 'ok';
				}
				return 'sdk_not_ready';
			})();
		""" % [event_name, value_js, params_json]
		JavaScriptBridge.eval(js, true)
	else:
		pending_native_call.emit("log_app_event", {
			"event_name": event_name, "value": value, "params": params
		})
	app_event_logged.emit(event_name)

func share_link(url: String, quote: String = "") -> void:
	if _app_id.is_empty():
		push_warning("FacebookSDKBridge.share_link(): no app_id")
		return
	_emit_event("share_called", { "url": url, "quote": quote })
	if _is_web and _sdk_initialized:
		# FB.ui share dialog. quote becomes the prefilled caption.
		var js := """
			(function() {
				if (typeof FB === 'undefined' || !FB.ui) { return 'sdk_not_ready'; }
				FB.ui({
					method: 'share',
					href: '%s',
					quote: '%s'
				}, function(response) {
					window.__mspc_fb_share_response = JSON.stringify(response || {});
				});
				return 'dispatched';
			})();
		""" % [url, quote.replace("'", "\\'")]
		JavaScriptBridge.eval(js, true)
	else:
		pending_native_call.emit("share_link", { "url": url, "quote": quote })

func _on_share_response(shared: bool) -> void:
	share_completed.emit(shared)
	_emit_event("share_completed", { "shared": shared })

func get_player_id() -> String:
	if _app_id.is_empty():
		push_warning("FacebookSDKBridge.get_player_id(): no app_id")
		return ""
	if _logged_in and not _user_id.is_empty():
		return _user_id
	# Trigger async fetch — the caller listens for login_status_changed.
	if _is_web and _sdk_initialized:
		var js := """
			(function() {
				if (typeof FB === 'undefined' || !FB.api) { return ''; }
				FB.api('/me', function(response) {
					window.__mspc_fb_me = JSON.stringify(response || {});
				});
				return 'pending';
			})();
		"""
		JavaScriptBridge.eval(js, true)
		_emit_event("player_id_requested_web", {})
	else:
		pending_native_call.emit("get_player_id", {})
	return ""

# ─── introspection helpers ────────────────────────────────────────

func is_logged_in() -> bool:
	return _logged_in

func is_web_build() -> bool:
	return _is_web

func is_sdk_initialized() -> bool:
	return _sdk_initialized

# ─── cross-process event log ──────────────────────────────────────

func _emit_event(event: String, details: Dictionary) -> void:
	var packet := {
		"ts": Time.get_unix_time_from_system(),
		"event": event,
		"details": details,
	}
	var line := JSON.stringify(packet)

	var f := FileAccess.open(EVENT_LOG_PATH, FileAccess.READ_WRITE)
	if f == null:
		f = FileAccess.open(EVENT_LOG_PATH, FileAccess.WRITE)
	if f != null:
		f.seek_end()
		f.store_line(line)
		f.close()

	var global_path := _expand_home(EVENT_LOG_GLOBAL)
	var gf := FileAccess.open(global_path, FileAccess.READ_WRITE)
	if gf == null:
		gf = FileAccess.open(global_path, FileAccess.WRITE)
	if gf != null:
		gf.seek_end()
		gf.store_line(line)
		gf.close()

func _expand_home(path: String) -> String:
	if path.begins_with("~/"):
		var home := OS.get_environment("HOME")
		if home.is_empty():
			home = OS.get_environment("USERPROFILE")
		if not home.is_empty():
			return home + path.substr(1)
	return path
