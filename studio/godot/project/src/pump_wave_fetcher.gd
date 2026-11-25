extends Node
class_name PumpWaveFetcher

# GENERATED · pump_wave_fetcher v1
# Polls /dapp/api/pump_wave (port 8520) for the live WaveFrame JSON emitted by
# core/lib/pump_visualizer_3d.py and forwards it to the controller via signal.

signal wave_received(wave: Dictionary)

const URL: String = "http://localhost:8520/dapp/api/pump_wave"

var _timer: Timer
var _http: HTTPRequest


func _ready() -> void:
	_http = HTTPRequest.new()
	add_child(_http)
	_http.request_completed.connect(_on_response)
	_timer = Timer.new()
	add_child(_timer)
	_timer.timeout.connect(_fetch)


func start_polling(interval_sec: float = 2.0) -> void:
	_timer.wait_time = interval_sec
	_timer.start()
	_fetch()


func _fetch() -> void:
	var token := _read_token()
	if token == "":
		# emit empty wave so HUD doesn't break
		wave_received.emit({
			"surf_state": "no_signal",
			"bot_density_avg": 0,
			"human_inflow_score": 0,
			"ripples": []
		})
		return
	_http.request(URL, ["Authorization: Bearer " + token])


func _on_response(_result: int, code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	if code != 200:
		wave_received.emit({
			"surf_state": "no_signal",
			"bot_density_avg": 0,
			"human_inflow_score": 0,
			"ripples": []
		})
		return
	var parsed: Variant = JSON.parse_string(body.get_string_from_utf8())
	if parsed != null and parsed is Dictionary:
		wave_received.emit(parsed)
	else:
		wave_received.emit({
			"surf_state": "no_signal",
			"bot_density_avg": 0,
			"human_inflow_score": 0,
			"ripples": []
		})


func _read_token() -> String:
	if OS.has_feature("web") and Engine.has_singleton("JavaScriptBridge"):
		var js: Variant = Engine.get_singleton("JavaScriptBridge")
		return str(js.eval("(localStorage.getItem('mspc_freetier_token') || '')", true))
	var f := FileAccess.open("user://freetier_token.txt", FileAccess.READ)
	if f == null:
		return ""
	var t := f.get_as_text().strip_edges()
	f.close()
	return t
