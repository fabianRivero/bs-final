extends Node2D
class_name Player
## The player character: grid movement, turn handling and interaction queries.
##
## Movement is **by grid**, in the style of a top-down RPG: one press of a
## direction key moves the character exactly one tile, and that movement costs
## one tick of in-game time. The character then interpolates towards the tile
## it is heading for, which reads as a smooth step without breaking the
## determinism of the grid.
##
## [b]Consult, never decide.[/b]
##
## When the player presses the interact key, this script asks the world what is
## nearby and emits an [ActionRequest]. It does not check whether the action is
## legal â€” that is the simulation core's job. The request travels to
## `GameState`, which records the decision and advances the clock.
##
## The tile size is the one used by the world builder, so the player lands
## exactly on the grid the tiles were laid out on.

## Emitted when the player emits an action request.
signal action_requested(request: ActionRequest)

## Emitted when a movement step begins.
signal stepped(direction: Vector2i)

## Emitted when the player finishes a movement step.
signal step_finished(tile: Vector2i)

## Side of one tile, in pixels.
const TILE_SIZE: int = 32

## Number of ticks in a full in-game day. Mirrors `core.time.TICKS_PER_DAY`.
const TICKS_PER_DAY: int = 96

## Draw order of the player, above the ground and below the props.
const Z_PLAYER: int = 0

## Duration of the interpolation between two tiles, in seconds.
const STEP_DURATION: float = 0.16

## The tile the player currently stands on.
var tile: Vector2i = Vector2i.ZERO

## The tile the player is heading for, when a step is in progress.
var target_tile: Vector2i = Vector2i.ZERO

## Whether a movement step is currently being animated.
var is_moving: bool = false

## The direction of the movement currently in progress.
var facing: Vector2i = Vector2i.DOWN

## The interaction target found by the last interact query.
var interact_target: String = ""

## The sprite of the player, a placeholder shape in the F3 prototype.
var _body: Node2D = null

## The tween animating the current step.
var _step_tween: Tween = null


func _ready() -> void:
	## Build the placeholder body and place the player on the grid.
	z_index = Z_PLAYER
	_build_body()
	snap_to_tile(tile)
	set_process_unhandled_input(true)


## Build the placeholder representation of the player.
##
## The F3 prototype uses flat colours instead of art. The structure is ready
## for a real sprite: the body node is the anchor a `Sprite2D` would replace.
##
## The parts are [Polygon2D]s, not [ColorRect]s: a [Control] does not draw
## inside a [Node2D].
func _build_body() -> void:
	_body = Node2D.new()
	_body.name = "Body"
	add_child(_body)

	var shadow: Polygon2D = _make_part("Shadow", Color(0.0, 0.0, 0.0, 0.25))
	shadow.polygon = PackedVector2Array([
		Vector2.ZERO,
		Vector2(TILE_SIZE * 0.7, 0.0),
		Vector2(TILE_SIZE * 0.7, TILE_SIZE * 0.35),
		Vector2(0.0, TILE_SIZE * 0.35),
	])
	shadow.position = Vector2(TILE_SIZE * 0.15, TILE_SIZE * 0.55)

	var torso: Polygon2D = _make_part("Torso", Color(0.85, 0.32, 0.28))
	torso.polygon = PackedVector2Array([
		Vector2.ZERO,
		Vector2(TILE_SIZE * 0.6, 0.0),
		Vector2(TILE_SIZE * 0.6, TILE_SIZE * 0.6),
		Vector2(0.0, TILE_SIZE * 0.6),
	])
	torso.position = Vector2(TILE_SIZE * 0.2, TILE_SIZE * 0.15)

	var head: Polygon2D = _make_part("Head", Color(0.93, 0.81, 0.66))
	head.polygon = PackedVector2Array([
		Vector2.ZERO,
		Vector2(TILE_SIZE * 0.42, 0.0),
		Vector2(TILE_SIZE * 0.42, TILE_SIZE * 0.42),
		Vector2(0.0, TILE_SIZE * 0.42),
	])
	head.position = Vector2(TILE_SIZE * 0.29, TILE_SIZE * 0.03)


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


## Place the player on a tile without animating.
##
## @param new_tile The tile to stand on.
func snap_to_tile(new_tile: Vector2i) -> void:
	tile = new_tile
	target_tile = new_tile
	position = Vector2(new_tile.x * TILE_SIZE, new_tile.y * TILE_SIZE)
	if _body != null:
		_body.position = Vector2.ZERO


## Handle the player's input.
##
## @param event The input event to inspect.
func _unhandled_input(event: InputEvent) -> void:
	if event.is_echo():
		return
	if not event.is_pressed():
		return
	if event.is_action_pressed("move_up"):
		request_step(Vector2i.UP)
	elif event.is_action_pressed("move_down"):
		request_step(Vector2i.DOWN)
	elif event.is_action_pressed("move_left"):
		request_step(Vector2i.LEFT)
	elif event.is_action_pressed("move_right"):
		request_step(Vector2i.RIGHT)
	elif event.is_action_pressed("interact"):
		emit_interaction()


## Attempt to move one tile in a direction.
##
## The move is only refused when a step is already running; whether the tile is
## walkable is a question about the world, which the zone answers.
##
## @param direction The direction to move in.
## @return `true` when the step was started.
func request_step(direction: Vector2i) -> bool:
	if is_moving:
		return false
	facing = direction
	var next_tile: Vector2i = tile + direction
	target_tile = next_tile
	is_moving = true
	stepped.emit(direction)

	var start: Vector2 = position
	var destination: Vector2 = Vector2(next_tile.x * TILE_SIZE, next_tile.y * TILE_SIZE)
	if _step_tween != null and _step_tween.is_valid():
		_step_tween.kill()
	_step_tween = create_tween()
	_step_tween.tween_property(self, "position", destination, STEP_DURATION)
	_step_tween.tween_callback(_on_step_completed)
	return true


## Finish the current movement step.
func _on_step_completed() -> void:
	tile = target_tile
	is_moving = false
	step_finished.emit(tile)


## Return the tile in front of the player.
##
## @return The neighbouring tile the player is facing.
func facing_tile() -> Vector2i:
	return tile + facing


## Find the NPC the player would interact with.
##
## This is a **query**, not a decision: it looks at the content document and
## reports what is nearby. Whether the interaction is allowed at the current
## tick is decided by the simulation core.
##
## A dead villager is skipped: they are not at their post any more, so
## there is nobody to talk to. This mirrors `core.schedule.npc_state`, where
## the schedule of a dead NPC is not resolved.
##
## @return The id of the nearby NPC, or an empty string when there is none.
func find_interactable_npc() -> String:
	var candidate: Vector2i = facing_tile()
	var content_db: Node = AutoloadRef.content_db(self)
	if content_db == null:
		return ""
	var game_state: Node = AutoloadRef.game_state(self)
	var tick_index: int = int(game_state.tick) if game_state != null else 0
	for npc_id in content_db.npcs.keys():
		var npc: Dictionary = content_db.npcs[npc_id]
		if _is_dead(npc, tick_index):
			continue
		var npc_tile: Vector2i = npc_tile_at(npc, tick_index)
		if npc_tile == candidate or npc_tile == tile:
			return String(npc_id)
	return ""


## Check whether an NPC is dead at the given tick.
##
## The tick of the death is the tick at which the villager is **already
## gone**, so the villager is alive at `deceased_at_tick - 1` and dead at
## `deceased_at_tick`. This mirrors `core.schedule.is_dead`.
##
## @param npc The NPC document.
## @param tick_index Absolute tick index.
## @return `true` when the NPC is dead at that tick.
static func _is_dead(npc: Dictionary, tick_index: int) -> bool:
	var deceased_at_tick = npc.get("deceased_at_tick", null)
	if deceased_at_tick == null:
		return false
	return tick_index >= int(deceased_at_tick)


## Return the tile an NPC occupies at a given tick.
##
## The schedule of an NPC is a list of half-open day-tick blocks, and the
## pattern repeats every day, so the tick is normalised with `tick % 96` before
## the lookup. This mirrors `core.schedule.npc_state`.
##
## A dead villager occupies **no tile at all**: the schedule is not resolved
## for somebody who is no longer in the world, so the answer is `(-1, -1)`,
## the same value the function returns for an NPC without a schedule.
##
## @param npc The NPC document.
## @param tick_index Absolute tick index.
## @return The tile the NPC occupies, or `(-1, -1)` when it is dead or has
## no schedule.
static func npc_tile_at(npc: Dictionary, tick_index: int) -> Vector2i:
	if _is_dead(npc, tick_index):
		return Vector2i(-1, -1)
	var position_in_day: int = tick_index % TICKS_PER_DAY
	for entry in npc.get("schedule", []):
		if entry is not Dictionary:
			continue
		var start_tick: int = int(entry.get("start_tick", 0))
		var end_tick: int = int(entry.get("end_tick", 0))
		if start_tick <= position_in_day and position_in_day < end_tick:
			var tile_value = entry.get("tile", [0, 0])
			return Vector2i(int(tile_value[0]), int(tile_value[1]))
	return Vector2i(-1, -1)


## Emit the action request for the interaction the player is offering.
##
## The request is a *consult* of the world: the player says "I want to talk to
## the NPC in front of me", and the simulation core decides whether it happens.
func emit_interaction() -> void:
	interact_target = find_interactable_npc()
	if interact_target.is_empty():
		return
	var request: ActionRequest = ActionRequest.new("talk", interact_target)
	action_requested.emit(request)
