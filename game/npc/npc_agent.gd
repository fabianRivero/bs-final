extends Node2D
class_name NpcAgent
## An NPC placed in the world according to the current tick.
##
## The agent does not own the position of the NPC: the position is a **pure
## function of the tick**, derived from the schedule of the NPC in the content
## document. The agent therefore re-reads the schedule whenever the clock
## changes and moves to the tile the schedule declares.
##
## This is the F3 placeholder. The schedules of the content document are
## already honoured, but the interaction and the dialogue are F4.
##
## [b]Death.[/b]
##
## A villager who dies stops being in the world. The agent reads the death
## from the content document, exactly like `core/schedule.py` does, and a
## dead NPC is **neither placed nor drawn**: it is not idle at the origin,
## it is simply not there. When the villager dies while the agent is on
## screen, the agent disappears.
##
## The tick of the death is the tick at which the villager is **already
## gone**: with `deceased_at_tick = 192` the villager is alive at tick 191
## and dead at tick 192.
##
## The design decision D33 forbids a counter of the dead: the player only
## sees the empty space where somebody used to stand.

## Emitted when the NPC moves to a new tile.
signal moved_to(tile: Vector2i)

## Side of one tile, in pixels.
const TILE_SIZE: int = 32

## Number of ticks in a full in-game day. Mirrors `core.time.TICKS_PER_DAY`.
const TICKS_PER_DAY: int = 96

## Draw order of the NPCs, above the ground and beside the player.
const Z_NPC: int = 0

## The id of the NPC, e.g. `"NPC_MILLER"`.
var npc_id: String = ""

## The display name of the NPC.
var display_name: String = ""

## The NPC document read from the content database.
var data: Dictionary = {}

## The tile the NPC currently stands on.
var tile: Vector2i = Vector2i.ZERO

## Whether the NPC can be interacted with at the current tick.
var is_interactable: bool = false

## Whether the NPC is alive at the current tick.
var is_alive: bool = true

## The activity the NPC performs at the current tick.
var activity: String = ""

## The sprite of the NPC, a placeholder shape in the F3 prototype.
var _body: Node2D = null


## Build the agent from its content document.
##
## @param npc_data The NPC document read from the content database.
func build(npc_data: Dictionary) -> void:
	z_index = Z_NPC
	data = npc_data
	npc_id = String(npc_data.get("id", ""))
	display_name = String(npc_data.get("name", npc_id))

	_build_body()
	var game_state: Node = AutoloadRef.game_state(self)
	refresh(int(game_state.tick) if game_state != null else 0)


## Build the placeholder representation of the NPC.
##
## The parts are [Polygon2D]s, not [ColorRect]s: a [Control] does not draw
## inside a [Node2D].
func _build_body() -> void:
	_body = Node2D.new()
	_body.name = "Body"
	add_child(_body)

	var shadow: Polygon2D = _make_part("Shadow", Color(0.0, 0.0, 0.0, 0.2))
	shadow.polygon = PackedVector2Array([
		Vector2.ZERO,
		Vector2(TILE_SIZE * 0.6, 0.0),
		Vector2(TILE_SIZE * 0.6, TILE_SIZE * 0.3),
		Vector2(0.0, TILE_SIZE * 0.3),
	])
	shadow.position = Vector2(TILE_SIZE * 0.2, TILE_SIZE * 0.6)

	var torso: Polygon2D = _make_part("Torso", Color(0.36, 0.52, 0.72))
	torso.polygon = PackedVector2Array([
		Vector2.ZERO,
		Vector2(TILE_SIZE * 0.55, 0.0),
		Vector2(TILE_SIZE * 0.55, TILE_SIZE * 0.55),
		Vector2(0.0, TILE_SIZE * 0.55),
	])
	torso.position = Vector2(TILE_SIZE * 0.22, TILE_SIZE * 0.2)

	var head: Polygon2D = _make_part("Head", Color(0.93, 0.81, 0.66))
	head.polygon = PackedVector2Array([
		Vector2.ZERO,
		Vector2(TILE_SIZE * 0.4, 0.0),
		Vector2(TILE_SIZE * 0.4, TILE_SIZE * 0.4),
		Vector2(0.0, TILE_SIZE * 0.4),
	])
	head.position = Vector2(TILE_SIZE * 0.3, TILE_SIZE * 0.08)


## Build a rectangular part of the body.
##
## @param part_name Name of the part.
## @param colour Colour of the part.
## @return The polygon, already added to the body.
func _make_part(part_name: String, colour: Color) -> Polygon2D:
	var part: Polygon2D = Polygon2D.new()
	part.name = part_name
	part.color = colour
	_body.add_child(part)
	return part


## Move the NPC to the tile its schedule declares at the given tick.
##
## A dead NPC is not placed and not drawn: the agent is hidden and the
## schedule is never consulted for it. The tick of the death is the tick at
## which the villager is already gone, so the agent disappears on that very
## tick.
##
## @param tick_index Absolute tick index.
func refresh(tick_index: int) -> void:
	if is_dead(tick_index):
		_become_dead()
		return

	is_alive = true
	visible = true
	var position_in_day: int = tick_index % TICKS_PER_DAY
	var resolved: Dictionary = _resolve_schedule(position_in_day)

	activity = String(resolved.get("activity", "idle"))
	is_interactable = bool(resolved.get("interactable", false))

	var tile_value = resolved.get("tile", [0, 0])
	var resolved_tile: Vector2i = Vector2i(int(tile_value[0]), int(tile_value[1]))
	if resolved_tile == tile and not is_moving():
		return
	tile = resolved_tile
	position = Vector2(tile.x * TILE_SIZE, tile.y * TILE_SIZE)
	moved_to.emit(tile)


## Check whether the NPC is dead at the given tick.
##
## Mirrors `core.schedule.is_dead`: the tick of the death is the tick at
## which the villager is already gone.
##
## @param tick_index Absolute tick index.
## @return `true` when the NPC is dead at that tick.
func is_dead(tick_index: int) -> bool:
	var deceased_at_tick = data.get("deceased_at_tick", null)
	if deceased_at_tick == null:
		return false
	return tick_index >= int(deceased_at_tick)


## Hide the agent because the villager is dead.
##
## The agent stops being drawn and stops being interactable. It is not
## moved to the origin: a dead villager is not idle at the origin, they are
## simply not there.
func _become_dead() -> void:
	is_alive = false
	is_interactable = false
	activity = ""
	visible = false


## Whether the NPC is currently interpolating towards a tile.
##
## @return Always `false` in the F3 prototype: the NPCs snap to their tile.
func is_moving() -> bool:
	return false


## Resolve the schedule block that covers a position inside the day.
##
## The blocks cover the half-open range `[start_tick, end_tick)`, and the daily
## pattern repeats, so the position inside the day is what matters. This
## mirrors `core.schedule.npc_state`.
##
## @param position_in_day Position inside the day, in `[0, TICKS_PER_DAY)`.
## @return The matching schedule entry, or the default state.
func _resolve_schedule(position_in_day: int) -> Dictionary:
	for entry in data.get("schedule", []):
		if entry is not Dictionary:
			continue
		var start_tick: int = int(entry.get("start_tick", 0))
		var end_tick: int = int(entry.get("end_tick", 0))
		if start_tick <= position_in_day and position_in_day < end_tick:
			return entry
	return {
		"tile": [0, 0],
		"activity": "idle",
		"interactable": false,
	}
