extends Control
## The ending screen.
##
## The ending of a run is evaluated in F5, when the mission and the ending
## tables of the simulation core are wired to the engine. This screen is the
## placeholder that shows where the run ended.
##
## The root is a [Control], so its children are laid out against the whole
## viewport.

## The label holding the title of the ending.
var _title_label: Label = null

## The label holding the closing text.
var _text_label: Label = null

## The label holding the prompt.
var _prompt_label: Label = null


func _ready() -> void:
	## Build the screen and report where the run ended.
	_build_screen()
	_refresh()


## Build the layout of the ending screen.
func _build_screen() -> void:
	var background: ColorRect = ColorRect.new()
	background.name = "Background"
	background.color = Color(0.05, 0.05, 0.08)
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
	_title_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_title_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_title_label.add_theme_font_size_override("font_size", 42)
	_title_label.add_theme_color_override("font_color", Color(0.98, 0.87, 0.6))
	_title_label.add_theme_color_override("font_outline_color", Color(0.0, 0.0, 0.0))
	_title_label.add_theme_constant_override("outline_size", 5)
	_title_label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	column.add_child(_title_label)

	_text_label = Label.new()
	_text_label.name = "TextLabel"
	_text_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_text_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_text_label.add_theme_font_size_override("font_size", 15)
	_text_label.add_theme_color_override("font_color", Color(0.85, 0.83, 0.78))
	_text_label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	column.add_child(_text_label)

	_prompt_label = Label.new()
	_prompt_label.name = "PromptLabel"
	_prompt_label.text = "Press SPACE to return to the title"
	_prompt_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_prompt_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_prompt_label.add_theme_font_size_override("font_size", 13)
	_prompt_label.add_theme_color_override("font_color", Color(0.55, 0.55, 0.52))
	_prompt_label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	column.add_child(_prompt_label)


## Report the state the run ended in.
func _refresh() -> void:
	if _title_label != null:
		_title_label.text = "ENDING SCREEN"
	if _text_label != null:
		_text_label.text = "Ending screen — implemented in F5"


## Handle the input of the ending screen.
##
## @param event The input event to inspect.
func _unhandled_input(event: InputEvent) -> void:
	if event.is_echo() or not event.is_pressed():
		return
	if event.is_action_pressed("interact") or event.is_action_pressed("advance_tick"):
		var scene_router: Node = AutoloadRef.scene_router(self)
		if scene_router != null:
			scene_router.goto_title()
