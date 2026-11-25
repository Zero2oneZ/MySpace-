extends Control
## SocialPanel — UI for the MySpace++ social bridge.
##
## Add this as a child of a CanvasLayer (or any UI root). It provides:
## - File picker
## - Caption/title input
## - Per-platform upload buttons (YouTube, Telegram, Facebook, WhatsApp,
##   Discord, Twitch, TikTok, X, Twilio, OnlyFans, Livepeer)
## - OAuth connect buttons (Google, X, Facebook, Discord, Twitch, TikTok)
## - Status readout
##
## Usage: instance scenes/social_panel.tscn under your UI layer.

@onready var _status_label: Label
@onready var _caption_edit: LineEdit
@onready var _file_label: Label
var _selected_file: String = ""

func _ready():
	# Layout: anchored top-right, 400x700
	size = Vector2(400, 700)
	anchor_left = 1.0
	anchor_right = 1.0
	anchor_top = 0.0
	anchor_bottom = 0.0
	offset_left = -420
	offset_top = 20
	offset_right = -20
	offset_bottom = 720
	grow_horizontal = Control.GROW_DIRECTION_BEGIN

	# Title
	var title := Label.new()
	title.text = "Social Bridge"
	title.position = Vector2(0, 0)
	title.size = Vector2(400, 30)
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	add_child(title)

	# File picker
	var file_btn := Button.new()
	file_btn.text = "Pick File..."
	file_btn.position = Vector2(0, 40)
	file_btn.size = Vector2(400, 30)
	file_btn.pressed.connect(_on_pick_file)
	add_child(file_btn)

	_file_label = Label.new()
	_file_label.text = "No file selected"
	_file_label.position = Vector2(0, 75)
	_file_label.size = Vector2(400, 20)
	add_child(_file_label)

	# Caption
	var cap_label := Label.new()
	cap_label.text = "Caption / Title:"
	cap_label.position = Vector2(0, 100)
	cap_label.size = Vector2(400, 20)
	add_child(cap_label)

	_caption_edit = LineEdit.new()
	_caption_edit.text = ""
	_caption_edit.position = Vector2(0, 125)
	_caption_edit.size = Vector2(400, 30)
	add_child(_caption_edit)

	# Platform buttons
	var platforms := [
		["YouTube", "youtube"], ["Telegram", "telegram"], ["Facebook", "facebook"],
		["WhatsApp", "whatsapp"], ["Discord", "discord"], ["Twitch", "twitch"],
		["TikTok", "tiktok"], ["X / Twitter", "x"], ["Twilio", "twilio"],
		["OnlyFans", "onlyfans"], ["Livepeer", "livepeer"]
	]
	var grid := GridContainer.new()
	grid.columns = 2
	grid.position = Vector2(0, 170)
	grid.size = Vector2(400, 300)
	add_child(grid)

	for p in platforms:
		var plat: String = p[1]
		var btn := Button.new()
		btn.text = p[0]
		btn.size = Vector2(190, 30)
		btn.pressed.connect(func(): _on_upload(plat))
		grid.add_child(btn)

	# CLI quick actions
	var cli_label := Label.new()
	cli_label.text = "Dev CLI:"
	cli_label.position = Vector2(0, 480)
	cli_label.size = Vector2(400, 20)
	add_child(cli_label)

	var cli_grid := GridContainer.new()
	cli_grid.columns = 4
	cli_grid.position = Vector2(0, 505)
	cli_grid.size = Vector2(400, 40)
	add_child(cli_grid)

	var clis := ["x me", "discord me", "telegram me", "livepeer streams"]
	for c in clis:
		var parts: PackedStringArray = c.split(" ")
		var btn := Button.new()
		btn.text = c
		btn.size = Vector2(95, 30)
		btn.pressed.connect(func(): SocialClient.cli(parts[0], parts.slice(1)))
		cli_grid.add_child(btn)

	# OAuth connect buttons
	var oauth_label := Label.new()
	oauth_label.text = "OAuth Connect:"
	oauth_label.position = Vector2(0, 555)
	oauth_label.size = Vector2(400, 20)
	add_child(oauth_label)

	var oauth_grid := GridContainer.new()
	oauth_grid.columns = 3
	oauth_grid.position = Vector2(0, 580)
	oauth_grid.size = Vector2(400, 60)
	add_child(oauth_grid)

	var oauth_plats := ["google", "x", "facebook", "discord", "twitch", "tiktok"]
	for plat in oauth_plats:
		var btn := Button.new()
		btn.text = plat.capitalize()
		btn.size = Vector2(130, 28)
		btn.pressed.connect(func(): SocialClient.oauth_start(plat))
		oauth_grid.add_child(btn)

	# Status
	_status_label = Label.new()
	_status_label.text = "Status: idle"
	_status_label.position = Vector2(0, 650)
	_status_label.size = Vector2(400, 40)
	_status_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	add_child(_status_label)

	# Wire signals
	if SocialClient != null:
		SocialClient.upload_finished.connect(_on_upload_finished)
		SocialClient.cli_finished.connect(_on_cli_finished)
		SocialClient.status_ready.connect(_on_status_ready)
		SocialClient.get_status()

func _on_pick_file():
	var dialog := FileDialog.new()
	dialog.file_mode = FileDialog.FILE_MODE_OPEN_FILE
	dialog.access = FileDialog.ACCESS_FILESYSTEM
	dialog.size = Vector2(800, 600)
	dialog.file_selected.connect(func(path: String):
		_selected_file = path
		_file_label.text = path.get_file()
		dialog.queue_free()
	)
	dialog.canceled.connect(func(): dialog.queue_free())
	add_child(dialog)
	dialog.popup_centered()

func _on_upload(platform: String):
	if _selected_file.is_empty():
		_status_label.text = "Error: no file selected"
		return
	var caption := _caption_edit.text
	_status_label.text = "Uploading to %s..." % platform
	SocialClient.upload([platform], _selected_file, caption)

func _on_upload_finished(platforms: String, ok: bool, detail: Dictionary):
	_status_label.text = "Upload to %s: %s" % [platforms, "OK" if ok else "FAIL"]

func _on_cli_finished(cli_name: String, ok: bool, stdout: String):
	_status_label.text = "CLI %s: %s | %s" % [cli_name, "OK" if ok else "FAIL", stdout.substr(0, 80)]

func _on_status_ready(status: Dictionary):
	var ready_count := 0
	if status.has("ready"):
		for v in status["ready"]:
			ready_count += 1
	_status_label.text = "Bridge ready platforms: %d" % ready_count
