extends Node3D
class_name MorphingGameController

const FACE_TO_SCENE = {
    "play_realtor":   "res://scenes/realestate_walkthrough_full.tscn",
    "play_buyer":     "res://scenes/avatar_rigged.tscn",
    "play_gamer":     "res://scenes/planet_map.tscn",
    "play_developer": "res://scenes/main.tscn",
    "play_default":   "res://scenes/main.tscn",
}

var current_plan: Dictionary = {}

func _ready():
    var loader = ScenePlanLoader
    loader.plan_received.connect(_on_plan_received)
    loader.fetch_plan_for_current_token()

func _on_plan_received(plan: Dictionary):
    current_plan = plan
    _apply_persona_styling(plan)
    _swap_primary_scene(plan.get("primary_face", "play_default"))
    _hud_update(plan)

func _swap_primary_scene(face_id: String):
    var path = FACE_TO_SCENE.get(face_id, "res://scenes/main.tscn")
    if not ResourceLoader.exists(path):
        push_warning("scene missing: " + path); return
    var packed = load(path) as PackedScene
    if not packed: return
    var slot = $SubViewportContainer/SubViewport/PrimarySceneSlot
    for c in slot.get_children(): c.queue_free()
    slot.add_child(packed.instantiate())

func _apply_persona_styling(plan: Dictionary):
    var accent_hex = plan.get("custom_css_vars", {}).get("--accent", "#4caf50")
    var c = Color(accent_hex)
    $HUD/AccentRect.color = c

func _hud_update(plan: Dictionary):
    $HUD/PersonaLabel.text = "persona: " + plan.get("persona_id", "?")
    $HUD/RoleLabel.text = "role: " + plan.get("inferred_role", "?")
    $HUD/DebugInfo.text = "scene: " + plan.get("primary_face", "?")
