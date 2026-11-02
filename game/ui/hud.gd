extends CanvasLayer
class_name Hud
## The heads-up display: the clock, the tick, the light phase and the cycle bar.
##
## The HUD is pure presentation. It reads the derived state published by
## `GameState` and the phase published by `Lighting`; it never computes a
## calendar instant or picks a colour itself.
##
## It subscribes to the `tick_changed` signal, so it never asks "what is in
## this tick?" — the state is pushed to it.
##
## The HUD is a [CanvasLayer], so it always covers the whole viewport whatever
## the camera of the world does. Inside it, a full-rect [Control] holds the
## panels.

## Emitted when the player toggles the help overlay.
signal help_toggled(is_open: bool)

## Number of ticks in the full playable cycle. Mirrors `core.time.TOTAL_TICKS`.
const TOTAL_TICKS: int = 480

## The label showing the clock, e.g. `"Day 1 07:15"`.
var clock_label: Label = null

## The label showing the current tick.
var tick_label: Label = null

## The label showing the current lighting phase.
var phase_label: Label = null

## The bar showing the progress of the cycle.
var cycle_bar: ProgressBar = null

## The label showing the number of decisions taken.
var decision_label: Label = null

## The row showing the provisions of the town.
var resource_row: HBoxContainer = null

## The panel holding the help text.
var help_panel: PanelContainer = null

## The full-rect control holding the panels of the HUD.
var _root: Control = null

## Whether the help overlay is open.
var _is_help_open: bool = false

## Colour of a provision that is in a healthy state.
const COLOR_HEALTHY: Color = Color(0.95, 0.93, 0.85)

## Colour of a provision that fell below its critical threshold.
const COLOR_CRITICAL: Color = Color(0.92, 0.42, 0.38)

## Colour of a provision that ran out.
const COLOR_DEPLETED: Color = Color(0.72, 0.24, 0.22)

## Colour of the amount spent today.
const COLOR_SPENT: Color = Color(0.62, 0.60, 0.54)


func _ready() -> void:
	## Build the HUD and subscribe to the clock.
	layer = 10
	_build_hud()
	var game_state: Node = AutoloadRef.game_state(self)
	if game_state != null:
		game_state.tick_changed.connect(_on_tick_changed)
		game_state.decisions_changed.connect(_on_decisions_changed)
		_rebuild_resource_row()
		_on_tick_changed(int(game_state.tick), game_state.state())
		_on_decisions_changed(game_state.decisions)
	else:
		_on_tick_changed(0, {})
		_on_decisions_changed([])


## Build the layout of the HUD.
func _build_hud() -> void:
	name = "Hud"

	_root = Control.new()
	_root.name = "Root"
	_root.set_anchors_preset(Control.PRESET_FULL_RECT)
	_root.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(_root)

	var panel: PanelContainer = PanelContainer.new()
	panel.name = "ClockPanel"
	panel.set_anchors_preset(Control.PRESET_TOP_LEFT)
	panel.position = Vector2(12, 12)
	panel.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_root.add_child(panel)

	var row: HBoxContainer = HBoxContainer.new()
	row.name = "Row"
	row.add_theme_constant_override("separation", 18)
	panel.add_child(row)

	clock_label = _make_label("Day 1 00:00", 20)
	clock_label.name = "ClockLabel"
	row.add_child(clock_label)

	phase_label = _make_label("dawn_early", 13)
	phase_label.name = "PhaseLabel"
	row.add_child(phase_label)

	tick_label = _make_label("tick 0 / 480", 13)
	tick_label.name = "TickLabel"
	row.add_child(tick_label)

	decision_label = _make_label("decisions 0", 13)
	decision_label.name = "DecisionLabel"
	row.add_child(decision_label)

	var bar_panel: PanelContainer = PanelContainer.new()
	bar_panel.name = "CyclePanel"
	bar_panel.set_anchors_preset(Control.PRESET_TOP_LEFT)
	bar_panel.position = Vector2(12, 62)
	bar_panel.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_root.add_child(bar_panel)

	cycle_bar = ProgressBar.new()
	cycle_bar.name = "CycleBar"
	cycle_bar.min_value = 0
	cycle_bar.max_value = TOTAL_TICKS
	cycle_bar.value = 0
	cycle_bar.show_percentage = false
	cycle_bar.custom_minimum_size = Vector2(320, 10)
	bar_panel.add_child(cycle_bar)

	# The provisions of the town: one label per resource, in a single row.
	var resource_panel: PanelContainer = PanelContainer.new()
	resource_panel.name = "ResourcePanel"
	resource_panel.set_anchors_preset(Control.PRESET_TOP_LEFT)
	resource_panel.position = Vector2(12, 84)
	resource_panel.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_root.add_child(resource_panel)

	resource_row = HBoxContainer.new()
	resource_row.name = "ResourceRow"
	resource_row.add_theme_constant_override("separation", 14)
	resource_panel.add_child(resource_row)

	help_panel = PanelContainer.new()
	help_panel.name = "HelpPanel"
	help_panel.set_anchors_preset(Control.PRESET_TOP_RIGHT)
	help_panel.position = Vector2(-250, 12)
	help_panel.visible = false
	help_panel.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_root.add_child(help_panel)

	var help_label: Label = _make_label(
		"WASD / arrows  move (1 tick)\nSPACE  interact\nE  wait one tick\nH  this help",
		12
	)
	help_label.name = "HelpLabel"
	help_panel.add_child(help_label)


## Build a label with the given text and size.
##
## @param text The text of the label.
## @param font_size Size of the font, in pixels.
## @return The label.
func _make_label(text: String, font_size: int) -> Label:
	var label: Label = Label.new()
	label.text = text
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", Color(0.95, 0.93, 0.85))
	label.add_theme_color_override("font_outline_color", Color(0.0, 0.0, 0.0))
	label.add_theme_constant_override("outline_size", 3)
	label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	return label


## Update the HUD from a new derived state.
##
## @param tick_index The new tick.
## @param _state The derived world state at the new tick.
func _on_tick_changed(tick_index: int, _state: Dictionary) -> void:
	var game_state: Node = AutoloadRef.game_state(self)
	if clock_label != null and game_state != null:
		clock_label.text = game_state.format_clock(tick_index)
	if tick_label != null:
		tick_label.text = "tick %d / %d" % [tick_index, TOTAL_TICKS]
	if cycle_bar != null:
		cycle_bar.value = tick_index
	if phase_label != null:
		# The phase is read from the lighting autoload for *this* tick, so the
		# label never lags behind the clock whatever the order in which the
		# listeners of `tick_changed` are called.
		var lighting: Node = AutoloadRef.lighting(self)
		if lighting != null:
			var phase: Dictionary = lighting.phase_at(tick_index)
			if not phase.is_empty():
				phase_label.text = lighting.phase_name(phase)
			else:
				phase_label.text = lighting.current_phase_id
	_refresh_resources()


## Build one label per resource of the town.
##
## The HUD never computes an amount itself: it reads the provisions the
## simulation core published.
func _rebuild_resource_row() -> void:
	if resource_row == null:
		return
	for child in resource_row.get_children():
		child.queue_free()

	var game_state: Node = AutoloadRef.game_state(self)
	if game_state == null:
		return

	var ids: Array = game_state.resources.keys()
	ids.sort()
	for resource_id in ids:
		var spec: Dictionary = game_state.resources[resource_id]
		var label: Label = _make_label("%s 0" % String(spec.get("label", resource_id)), 13)
		label.name = "Resource_%s" % String(resource_id)
		resource_row.add_child(label)

		var spent: Label = _make_label("", 12)
		spent.name = "Spent_%s" % String(resource_id)
		spent.add_theme_color_override("font_color", COLOR_SPENT)
		resource_row.add_child(spent)


## Refresh the amount shown by every resource label.
##
## A resource in crisis is shown in red and a resource that ran out in a
## darker red, so the player sees the town running out without reading a
## number. The amount spent today is shown next to the stock, so the shape
## of the day is visible at a glance.
func _refresh_resources() -> void:
	if resource_row == null:
		return
	var game_state: Node = AutoloadRef.game_state(self)
	if game_state == null:
		return

	for child in resource_row.get_children():
		if not (child is Label):
			continue
		var label: Label = child
		var node_name: String = label.name
		if node_name.begins_with("Spent_"):
			continue
		var resource_id: String = node_name.replace("Resource_", "")
		var spec: Dictionary = game_state.resources.get(resource_id, {})
		if spec.is_empty():
			continue
		var amount: int = int(game_state.resource_amount(resource_id))
		label.text = "%s %d" % [String(spec.get("label", resource_id)), amount]

		var state: String = String(game_state.resource_state(resource_id))
		if state == "depleted":
			label.add_theme_color_override("font_color", COLOR_DEPLETED)
		elif state == "critical":
			label.add_theme_color_override("font_color", COLOR_CRITICAL)
		else:
			label.add_theme_color_override("font_color", COLOR_HEALTHY)

		var spent_label: Label = resource_row.get_node_or_null("Spent_%s" % resource_id)
		if spent_label != null:
			var spent: int = int(game_state.resource_spent_today(resource_id))
			if spent > 0:
				spent_label.text = "-%d today" % spent
			else:
				spent_label.text = ""


## Update the decision counter.
##
## @param decision_list The decisions taken so far.
func _on_decisions_changed(decision_list: Array) -> void:
	if decision_label != null:
		decision_label.text = "decisions %d" % decision_list.size()


## Handle the input of the HUD.
##
## @param event The input event to inspect.
func _unhandled_input(event: InputEvent) -> void:
	if event.is_echo() or not event.is_pressed():
		return
	if event.is_action_pressed("toggle_help"):
		toggle_help()


## Open or close the help overlay.
func toggle_help() -> void:
	_is_help_open = not _is_help_open
	if help_panel != null:
		help_panel.visible = _is_help_open
	help_toggled.emit(_is_help_open)
