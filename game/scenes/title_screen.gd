extends Control
## The title screen: the entry point of the game.
##
## The scene is minimal on purpose. Everything below the root node is built in
## code, which keeps the scene file trivial and makes the structure readable
## in one place.
##
## The root is a [Control], so its children are laid out against the whole
## viewport.

## The title of the game.
const GAME_TITLE: String = "ALDERMERE"

## The tagline shown under the title.
const TAGLINE: String = "Three days to find out what is making the village ill."

## The label holding the title.
var _title_label: Label = null

## The label holding the prompt.
var _prompt_label: Label = null

## The label holding the status of the content.
var _status_label: Label = null


func _ready() -> void:
	## Build the screen and wait for the player to start.
	_build_screen()
	_refresh_status()


## Build the layout of the title screen.
func _build_screen() -> void:
	var background: ColorRect = ColorRect.new()
	background.name = "Background"
	background.color = Color(0.07, 0.08, 0.12)
	background.set_anchors_preset(Control.PRESET_FULL_RECT)
	background.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(background)

	# The column is anchored to the whole screen, so its labels get the whole
	# width and their text is centred inside it.
	var column: VBoxContainer = VBoxContainer.new()
	column.name = "Column"
	column.set_anchors_preset(Control.PRESET_FULL_RECT)
	column.offset_left = 60
	column.offset_right = -60
	column.offset_top = 40
	column.offset_bottom = -40
	column.alignment = BoxContainer.ALIGNMENT_CENTER
	column.add_theme_constant_override("separation", 14)
	column.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(column)
	_title_label = Label.new()
	_title_label.name = "TitleLabel"
	_title_label.text = GAME_TITLE
	_title_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_title_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_title_label.add_theme_font_size_override("font_size", 54)
	_title_label.add_theme_color_override("font_color", Color(0.98, 0.87, 0.6))
	_title_label.add_theme_color_override("font_outline_color", Color(0.0, 0.0, 0.0))
	_title_label.add_theme_constant_override("outline_size", 6)
	_title_label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	column.add_child(_title_label)

	var tagline: Label = Label.new()
	tagline.name = "TaglineLabel"
	tagline.text = TAGLINE
	tagline.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	tagline.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	tagline.add_theme_font_size_override("font_size", 15)
	tagline.add_theme_color_override("font_color", Color(0.78, 0.76, 0.70))
	tagline.mouse_filter = Control.MOUSE_FILTER_IGNORE
	column.add_child(tagline)

	_prompt_label = Label.new()
	_prompt_label.name = "PromptLabel"
	_prompt_label.text = "Press SPACE to begin"
	_prompt_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_prompt_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_prompt_label.add_theme_font_size_override("font_size", 18)
	_prompt_label.add_theme_color_override("font_color", Color(0.93, 0.91, 0.85))
	_prompt_label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	column.add_child(_prompt_label)

	_status_label = Label.new()
	_status_label.name = "StatusLabel"
	_status_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_status_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_status_label.add_theme_font_size_override("font_size", 11)
	_status_label.add_theme_color_override("font_color", Color(0.55, 0.55, 0.52))
	_status_label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	column.add_child(_status_label)


## Report whether the content document was found.
func _refresh_status() -> void:
	if _status_label == null:
		return
	var content_db: Node = AutoloadRef.content_db(self)
	if content_db == null:
		_status_label.text = "content missing: run `uv run python -m tools.export_web`"
		return
	# The accessors load the document on demand, so the status is correct
	# whatever the order in which the autoloads were created.
	var zone_count: int = content_db.zones.size()
	var npc_count: int = content_db.npcs.size()
	if zone_count == 0 and npc_count == 0:
		_status_label.text = "content missing: run `uv run python -m tools.export_web`"
	else:
		_status_label.text = "content loaded: %d zones, %d npcs" % [zone_count, npc_count]


## Handle the input of the title screen.
##
## @param event The input event to inspect.
func _unhandled_input(event: InputEvent) -> void:
	if event.is_echo() or not event.is_pressed():
		return
	if event.is_action_pressed("interact") or event.is_action_pressed("advance_tick"):
		_start_game()


## Begin a run.
func _start_game() -> void:
	var game_state: Node = AutoloadRef.game_state(self)
	if game_state != null:
		game_state.reset()
	var scene_router: Node = AutoloadRef.scene_router(self)
	if scene_router != null:
		scene_router.goto_game()
