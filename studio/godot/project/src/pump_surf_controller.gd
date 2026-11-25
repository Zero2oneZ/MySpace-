extends Node3D
class_name PumpSurfController

# GENERATED · pump_surf_controller v1
# Renders pump.fun live transaction WaveFrames as 3D ripples in a hex grid.
# Subscribes to PumpWaveFetcher.wave_received; rebuilds ripple meshes per frame.

var ripple_meshes: Array[MeshInstance3D] = []
var fetcher: PumpWaveFetcher


func _ready() -> void:
	fetcher = PumpWaveFetcher.new()
	add_child(fetcher)
	fetcher.wave_received.connect(_on_wave)
	fetcher.start_polling(2.0)  # every 2 seconds


func _on_wave(wave: Dictionary) -> void:
	_clear_ripples()
	for r in wave.get("ripples", []):
		_spawn_ripple(r)
	_update_hud(wave)


func _clear_ripples() -> void:
	for m in ripple_meshes:
		if is_instance_valid(m):
			m.queue_free()
	ripple_meshes.clear()
	for c in $SurfTargetAnchors.get_children():
		c.queue_free()


func _spawn_ripple(r: Dictionary) -> void:
	var m := MeshInstance3D.new()
	var s := SphereMesh.new()
	s.radius = 0.1 + 0.2 * float(r.get("intensity", 0))
	s.height = s.radius * 2.0
	m.mesh = s

	var mat := StandardMaterial3D.new()
	var col: Array = r.get("color_rgba", [1, 1, 1, 1])
	mat.albedo_color = Color(col[0], col[1], col[2], col[3])
	if bool(r.get("is_surf_target", false)):
		mat.emission_enabled = true
		mat.emission = Color(col[0], col[1], col[2])
		mat.emission_energy_multiplier = 2.5
	m.material_override = mat

	# Map normalized x/y/z to scene coords
	var x := (float(r.get("x", 0.5)) - 0.5) * 20.0
	var y := (float(r.get("y", 0.5)) - 0.5) * 8.0
	var z := (float(r.get("z", 0.5)) - 0.5) * 12.0
	m.transform.origin = Vector3(x, y, z)

	$WaveField.add_child(m)
	ripple_meshes.append(m)

	if bool(r.get("is_surf_target", false)):
		var marker := MeshInstance3D.new()
		marker.mesh = TorusMesh.new()
		marker.transform.origin = m.transform.origin
		marker.scale = Vector3(0.4, 0.4, 0.4)
		var mm := StandardMaterial3D.new()
		mm.albedo_color = Color(1.0, 0.85, 0.0)
		mm.emission_enabled = true
		mm.emission = Color(1.0, 0.85, 0.0)
		mm.emission_energy_multiplier = 4.0
		marker.material_override = mm
		$SurfTargetAnchors.add_child(marker)


func _update_hud(wave: Dictionary) -> void:
	var ss: String = str(wave.get("surf_state", "no_signal"))
	$HUD/SurfStateLabel.text = ss.to_upper()
	$HUD/BotDensityBar.value = float(wave.get("bot_density_avg", 0)) * 100.0
	$HUD/HumanInflowBar.value = float(wave.get("human_inflow_score", 0)) * 100.0
	$HUD/AbortOverlay.color = Color(1, 0, 0, 0.25) if ss == "abort" else Color(0, 0, 0, 0)
