@tool
extends EditorScript
## godot_mcp.gd — one-shot MCP dispatcher for the Godot 2D + script editors.
## Mirrors studio/blender/mcp_server.py: read ONE JSON-RPC request, act via the
## EditorInterface, write ONE response. Run headless:
##   godot --headless --editor --path <project> --script res://mcp/godot_mcp.gd
## Request/response files via env GODOT_MCP_REQ / GODOT_MCP_RES (default /tmp).
##
## DECISION (locked): this @tool driver is GDScript — the *editor-glue* exception.
## The LOGIC it generates/edits targets **C# (godot_cs)** per docs/standards.json
## (workflow_card is the deterministic source; this is the render/edit hand).
## Live script editing also runs over the built-in Godot LSP on :6005.
##
## Tool surface (the DAG-aware ops):
##   scene.open {path}              -> open a .tscn in the 2D/3D editor
##   node.list {}                   -> the scene's node tree (the scene sub-DAG)
##   node.create {parent,type,name} -> add a node (parent<-child DAG edge)
##   node.set {path,prop,value}     -> set a property
##   scene.save {}                  -> persist
##   script.write {path,body,lang}  -> write a .cs (default) / .gd script
##   material.apply {node,manifest} -> build StandardMaterial3D from a crystal manifest

func _run() -> void:
	var req_path := _env("GODOT_MCP_REQ", "/tmp/godot_mcp_req.json")
	var res_path := _env("GODOT_MCP_RES", "/tmp/godot_mcp_res.json")
	var req := _read_json(req_path)
	var method: String = req.get("method", "")
	var p: Dictionary = req.get("params", {})
	var ei := get_editor_interface()
	var result := {}
	match method:
		"scene.open":
			ei.open_scene_from_path(p.get("path", ""))
			result = {"opened": p.get("path", "")}
		"node.list":
			result = {"tree": _walk(ei.get_edited_scene_root())}
		"node.create":
			var root := ei.get_edited_scene_root()
			var parent: Node = root.get_node(p.get("parent", ".")) if root else null
			if parent:
				var n: Node = ClassDB.instantiate(p.get("type", "Node"))
				n.name = p.get("name", p.get("type", "Node"))
				parent.add_child(n)
				n.owner = root
				result = {"created": str(n.get_path())}
			else:
				result = {"error": "no edited scene / parent"}
		"node.set":
			var root2 := ei.get_edited_scene_root()
			var t: Node = root2.get_node(p.get("path", "")) if root2 else null
			if t: t.set(p.get("prop", ""), p.get("value")); result = {"set": true}
			else: result = {"error": "node not found"}
		"scene.save":
			ei.save_scene()
			result = {"saved": true}
		"script.write":
			var lang := p.get("lang", "godot_cs")
			var path: String = p.get("path", "res://src/Generated.cs")
			var f := FileAccess.open(path, FileAccess.WRITE)
			if f: f.store_string(p.get("body", "")); f.close(); result = {"wrote": path, "lang": lang}
			else: result = {"error": "cannot open " + path}
		_:
			result = {"error": "unknown method: " + method}
	_write_json(res_path, {"jsonrpc": "2.0", "id": req.get("id", 1), "result": result})

func _walk(n: Node) -> Dictionary:
	if n == null: return {}
	var kids := []
	for c in n.get_children():
		kids.append(_walk(c))
	return {"name": n.name, "type": n.get_class(), "children": kids}

func _env(k: String, d: String) -> String:
	return OS.get_environment(k) if OS.has_environment(k) else d
func _read_json(path: String) -> Dictionary:
	var f := FileAccess.open(path, FileAccess.READ)
	if f == null: return {}
	var j = JSON.parse_string(f.get_as_text()); f.close()
	return j if j is Dictionary else {}
func _write_json(path: String, obj: Dictionary) -> void:
	var f := FileAccess.open(path, FileAccess.WRITE)
	if f: f.store_string(JSON.stringify(obj)); f.close()
