extends Node
signal plan_received(plan: Dictionary)

func fetch_plan_for_current_token():
    var token = _read_token_from_storage()
    if token == "":
        plan_received.emit({"inferred_role":"unknown","primary_face":"play_default","persona_id":"local_anon"})
        return
    var req = HTTPRequest.new()
    add_child(req)
    req.request_completed.connect(_on_plan_response)
    req.request("http://localhost:8520/dapp/api/morph_plan",
                ["Authorization: Bearer " + token, "Content-Type: application/json"],
                HTTPClient.METHOD_GET)

func _on_plan_response(result: int, code: int, _h, body: PackedByteArray):
    if code != 200:
        plan_received.emit({"inferred_role":"unknown","primary_face":"play_default"}); return
    var parsed = JSON.parse_string(body.get_string_from_utf8())
    plan_received.emit(parsed if parsed != null else {})

func _read_token_from_storage() -> String:
    if OS.has_feature("web"):
        var js = "(localStorage.getItem('mspc_freetier_token') || '')"
        return JavaScriptBridge.eval(js, true) if Engine.has_singleton("JavaScriptBridge") else ""
    var f = FileAccess.open("user://freetier_token.txt", FileAccess.READ)
    return f.get_as_text().strip_edges() if f else ""
