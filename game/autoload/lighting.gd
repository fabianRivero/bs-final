extends Node
## Autoload that applies the day/night lighting phase to the world.
##
## The lighting is a **pure function of the tick**: Python owns the phase
## table, the tint colour and the overlay opacity, and Godot only *applies*
## them. The phase table is exported to `res://data/game_content.json` and read
## from there, so the two sides can never drift apart.
##
## [b]Strategy.[/b]
##
## A full-screen `ColorRect` is drawn on top of the world and tinted with the
## phase colour. Opacity `0.0` means "no overlay at all" (broad daylight) and
## opacity `1.0` means "fully blacked out". This is the same strategy the
## simulation core documents in `core/lighting.py`.
##
## The overlay is created in code so the scene files stay minimal and the
## z-order is explicit: the overlay sits above the world and below the HUD.

## Emitted whenever the lighting phase changes.
signal lighting_changed(phase_id: String, tint: Color, opacity: float)

## Name of the node that carries the tint overlay.
const OVERLAY_NAME: String = "LightingOverlay"

## Name of the canvas layer that carries the tint overlay.
const OVERLAY_LAYER_NAME: String = "LightingLayer"

## Number of ticks in a full in-game day. Mirrors `core.time.TICKS_PER_DAY`.
const TICKS_PER_DAY: int = 96

## The overlay rectangle, created lazily on the first application.
var _overlay: ColorRect = null

## The canvas layer that carries the overlay.
var _overlay_layer: CanvasLayer = null

## The current phase id, e.g. `"dawn_early"`.
var current_phase_id: String = ""

## The current tint colour, taken verbatim from the phase table.
var current_tint: Color = Color.WHITE

## The current overlay opacity, in `[0.0, 1.0]`.
var current_opacity: float = 0.0


func _ready() -> void:
	## Subscribe to the clock and paint the very first phase.
	AutoloadRef.register("Lighting", self)
	var game_state: Node = AutoloadRef.game_state(self)
	if game_state != null:
		game_state.tick_changed.connect(_on_tick_changed)
		apply_phase(int(game_state.tick))
	else:
		apply_phase(0)


## Return the lighting phase that contains a tick.
##
## The daily pattern repeats, so the tick is normalised with `tick % 96` before
## the lookup: tick 28 and tick 124 belong to the same phase. This mirrors
## `core.lighting.phase_at`.
##
## @param tick_index Absolute tick index.
## @return The phase document, or an empty dictionary when the table is
##         unavailable.
func phase_at(tick_index: int) -> Dictionary:
	var position: int = tick_index % TICKS_PER_DAY
	var content_db: Node = AutoloadRef.content_db(self)
	if content_db == null:
		return {}
	for phase in content_db.lighting_phases:
		var start_tick: int = int(phase.get("start_tick", 0))
		var end_tick: int = int(phase.get("end_tick", 0))
		if start_tick <= position and position < end_tick:
			return phase
	return {}


## Return the normalised phase id of a phase document.
##
## The content document identifies the phases with the prefixed ids of
## `content.schema` (`LGT_DAWN_EARLY`), while the simulation core uses the bare
## ids (`dawn_early`). The exported document carries the bare id in the
## `phase_id` field, and this helper prefers it. The prefix is stripped as a
## fallback, for a document that only carries the prefixed id.
##
## @param phase The phase document.
## @return The bare phase id.
static func phase_name(phase: Dictionary) -> String:
	var bare: String = String(phase.get("phase_id", ""))
	if not bare.is_empty():
		return bare
	var raw: String = String(phase.get("id", ""))
	if raw.begins_with("LGT_"):
		return raw.substr(4).to_lower()
	return raw.to_lower()


## Apply the lighting phase of a tick to the world overlay.
##
## @param tick_index Absolute tick index.
## @return The phase document that was applied.
func apply_phase(tick_index: int) -> Dictionary:
	var phase: Dictionary = phase_at(tick_index)
	if phase.is_empty():
		return {}

	var rgb: Array = phase.get("rgb", [255, 255, 255])
	current_phase_id = phase_name(phase)
	current_tint = Color(
		float(rgb[0]) / 255.0,
		float(rgb[1]) / 255.0,
		float(rgb[2]) / 255.0,
		1.0
	)
	current_opacity = float(phase.get("opacity", 0.0))
	_ensure_overlay()
	_paint_overlay()
	lighting_changed.emit(current_phase_id, current_tint, current_opacity)
	return phase


## Create the overlay rectangle if it does not exist yet.
##
## The overlay lives in a [CanvasLayer] above the world, so it covers the
## whole viewport whatever the camera of the world does. The layer is added to
## the **anchor scene**, because a scene owns the view it is showing.
##
## The layer is created lazily: the autoload enters the tree before the first
## scene does, and there is nothing to tint at that point.
##
## @param anchor The scene the overlay belongs to.
func _ensure_overlay(anchor: Node = null) -> void:
	if _overlay != null and is_instance_valid(_overlay):
		return
	var host: Node = _resolve_host(anchor)
	if host == null:
		return

	_overlay_layer = CanvasLayer.new()
	_overlay_layer.name = OVERLAY_LAYER_NAME
	_overlay_layer.layer = 5
	host.add_child(_overlay_layer)

	_overlay = ColorRect.new()
	_overlay.name = OVERLAY_NAME
	_overlay.color = Color.WHITE
	_overlay.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_overlay.set_anchors_preset(Control.PRESET_FULL_RECT)
	_overlay_layer.add_child(_overlay)


## Return the node the overlay has to be attached to.
##
## The current scene of the tree is the first choice. When there is none — a
## scene that was added by hand rather than through the scene router — the
## anchor is used instead.
##
## @param anchor The scene that asked for the overlay.
## @return The node the overlay is attached to, or `null` when there is none.
func _resolve_host(anchor: Node = null) -> Node:
	if not is_inside_tree():
		return null
	var tree: SceneTree = get_tree()
	if tree == null:
		return null
	if tree.current_scene != null:
		return tree.current_scene
	if anchor != null and is_instance_valid(anchor):
		return anchor
	return null


## Rebuild the overlay on the current scene.
##
## The scene router swaps the whole scene tree between the title, the game and
## the ending, so the overlay has to be rebuilt every time the scene changes.
## The scenes call this after they are built.
##
## @param anchor The scene the overlay belongs to.
func refresh_overlay(anchor: Node = null) -> void:
	if _overlay_layer != null and is_instance_valid(_overlay_layer):
		_overlay_layer.queue_free()
	_overlay_layer = null
	_overlay = null
	_ensure_overlay(anchor)
	_paint_overlay()


## Push the current tint and opacity onto the overlay rectangle.
func _paint_overlay() -> void:
	if _overlay == null or not is_instance_valid(_overlay):
		return
	_overlay.color = Color(current_tint.r, current_tint.g, current_tint.b, current_opacity)


## React to a tick change published by the game state.
##
## @param tick_index The new tick.
## @param _state The derived world state at the new tick.
func _on_tick_changed(tick_index: int, _state: Dictionary) -> void:
	apply_phase(tick_index)
