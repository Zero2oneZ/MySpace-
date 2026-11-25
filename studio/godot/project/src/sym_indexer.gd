extends Node
## Sym Indexer — Generates SYM_INDEX from symbols + metadata.
## Mirrors Defold's sym_indexer.lua.

var index: Dictionary = {}
var symbols: Array = []

func _ready():
	_load_index()
	print("SymIndexer ready — %d symbols" % symbols.size())

func _load_index():
	var path = "res://assets/data/sym_index.json"
	if FileAccess.file_exists(path):
		var f = FileAccess.open(path, FileAccess.READ)
		var parsed = JSON.parse_string(f.get_as_text())
		f.close()
		if parsed is Dictionary:
			index = parsed
			symbols = index.get("symbols", [])

func lookup(name: String) -> Dictionary:
	for sym in symbols:
		if sym.get("name", "") == name:
			return sym
	return {}

func add_symbol(name: String, meta: Dictionary) -> String:
	var sid = "sym_%d" % symbols.size()
	var entry = {"id": sid, "name": name, "meta": meta}
	symbols.append(entry)
	index["symbols"] = symbols
	return sid

func save_index(path: String = "res://assets/data/sym_index.json"):
	var f = FileAccess.open(path, FileAccess.WRITE)
	f.store_string(JSON.stringify(index, "\t"))
	f.close()
