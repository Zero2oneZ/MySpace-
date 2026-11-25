extends Node
## Chain Runner — Coordinates inference chains with crystal hashing.
## Mirrors Defold's chain_runner.lua.

signal step_completed(step_id: String, result: Dictionary)
signal chain_finished(chain_id: String, crystal: String)

var active_chains: Dictionary = {}
var chain_counter: int = 0

func _ready():
	print("ChainRunner ready")

func start_chain(chain_def: Dictionary) -> String:
	chain_counter += 1
	var cid = "chain_%d" % chain_counter
	active_chains[cid] = {
		"def": chain_def,
		"idx": 0,
		"results": [],
		"crystal": "",
	}
	_run_step(cid)
	return cid

func _run_step(cid: String):
	var chain = active_chains[cid]
	var steps = chain.def.get("steps", [])
	if chain.idx >= steps.size():
		_finalize(cid)
		return
	var step = steps[chain.idx]
	chain.idx += 1
	# Delegate to TaskManager or native extension
	var result = await TaskManager.execute_step(step)
	chain.results.append(result)
	step_completed.emit(step.get("id", "?"), result)
	_run_step(cid)

func _finalize(cid: String):
	var chain = active_chains[cid]
	var payload = {
		"def": chain.def,
		"results": chain.results,
	}
	chain.crystal = VMNavigator.crystal_hash(payload)
	chain_finished.emit(cid, chain.crystal)
	print("Chain %s finalized — crystal %s" % [cid, chain.crystal])
