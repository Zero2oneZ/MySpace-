extends Node
## VM Navigator — Graph-walking oracle for the VM registry.
## Mirrors Defold's vm_navigator.lua in Godot GDScript.
## Loads vm_registry.json and provides graph traversal + crystal hashing.

var registry: Dictionary = {}
var current_vm: String = ""

func _ready():
	_load_registry()
	print("VMNavigator ready — %d VMs loaded" % registry.size())

func _load_registry():
	var path = "res://assets/data/vm_registry.json"
	if FileAccess.file_exists(path):
		var f = FileAccess.open(path, FileAccess.READ)
		var txt = f.get_as_text()
		f.close()
		var parsed = JSON.parse_string(txt)
		if parsed is Dictionary:
			registry = parsed
	else:
		push_warning("vm_registry.json not found — using empty registry")

func list_vms() -> Array:
	return registry.keys()

func get_vm(vm_id: String) -> Dictionary:
	return registry.get(vm_id, {})

func walk(vm_id: String, step: String) -> Dictionary:
	var vm = get_vm(vm_id)
	var steps = vm.get("steps", [])
	for s in steps:
		if s.get("id", "") == step:
			return s
	return {}

func crystal_hash(data: Dictionary) -> String:
	var json = JSON.stringify(data)
	var ctx = HashingContext.new()
	ctx.start(HashingContext.HASH_SHA256)
	ctx.update(json.to_utf8_buffer())
	return ctx.finish().hex_encode()
