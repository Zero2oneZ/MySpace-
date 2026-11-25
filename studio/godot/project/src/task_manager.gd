extends Node
## Task Manager — Rails for TaskChain execution.
## Mirrors Defold's task_manager.lua.

signal task_started(task_id: String)
signal task_ended(task_id: String, ok: bool)

var pending: Array = []
var running: Dictionary = {}

func _ready():
	print("TaskManager ready")

func enqueue(task_def: Dictionary) -> String:
	var tid = "task_%d" % (pending.size() + running.size())
	pending.append({"id": tid, "def": task_def})
	return tid

func execute_step(step: Dictionary) -> Dictionary:
	var tid = enqueue(step)
	task_started.emit(tid)
	# Simulate async work; replace with native call
	await get_tree().create_timer(0.05).timeout
	var result = {"step": step, "status": "ok", "tid": tid}
	task_ended.emit(tid, true)
	return result

func flush() -> Array:
	var out = []
	for t in pending:
		running[t.id] = t
	out.append_array(pending)
	pending.clear()
	return out
