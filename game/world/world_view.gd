extends Node2D
class_name WorldView
## The view of the world: it hosts the zones and keeps the camera on the player.
##
## The world view is pure presentation. It draws the zone that is currently
## loaded and follows the player; it never decides anything about the state of
## the world.

## Emitted when a zone has been loaded into the view.
signal zone_loaded(zone_id: String)

## The zone currently displayed.
var zone: AldermereZone = null

## The player the camera follows.
var player: Player = null

## The camera of the view.
var _camera: Camera2D = null


func _ready() -> void:
	## Build the camera and follow the player as soon as it appears.
	_camera = Camera2D.new()
	_camera.name = "Camera"
	_camera.zoom = Vector2.ONE * 2.0
	_camera.position_smoothing_enabled = true
	_camera.position_smoothing_speed = 8.0
	_camera.limit_smoothed = true
	add_child(_camera)
	_camera.make_current()
	if player != null:
		_follow_player()


## Make the camera follow the player.
func _follow_player() -> void:
	if _camera == null or player == null:
		return
	_camera.position = player.position
	_camera.make_current()


## Process the follow of the camera.
##
## The camera is moved to the player on every frame, so the view stays on the
## character while it walks.
func _process(_delta: float) -> void:
	if _camera == null or player == null:
		return
	_camera.position = player.position


## Load a zone into the view, replacing the zone currently shown.
##
## @param zone_data The zone document read from the content database.
## @return The zone that was loaded.
func load_zone(zone_data: Dictionary) -> AldermereZone:
	if zone != null:
		zone.queue_free()
		zone = null

	zone = AldermereZone.new()
	zone.name = "Zone"
	add_child(zone)
	zone.build(zone_data)

	_place_player_on_walkable_tile()
	zone_loaded.emit(zone.zone_id)
	return zone


## Move the player onto the first walkable tile of the zone.
##
## The player is placed near the centre of the zone, walking outwards until it
## finds a cell that is not blocked.
func _place_player_on_walkable_tile() -> void:
	if player == null or zone == null:
		return
	var size: Vector2i = zone.size_in_tiles()
	var origin: Vector2i = Vector2i(size.x / 2, size.y / 2)
	if zone.is_walkable(origin):
		player.snap_to_tile(origin)
		return
	for radius in range(1, maxi(size.x, size.y)):
		for offset_y in range(-radius, radius + 1):
			for offset_x in range(-radius, radius + 1):
				var candidate: Vector2i = origin + Vector2i(offset_x, offset_y)
				if zone.is_walkable(candidate):
					player.snap_to_tile(candidate)
					return


## Register the player the camera follows.
##
## @param new_player The player node.
func set_player(new_player: Player) -> void:
	player = new_player
	_follow_player()


## Ask the zone whether a cell can be walked on.
##
## @param cell The cell to check.
## @return `true` when the cell is walkable, or when no zone is loaded.
func is_walkable(cell: Vector2i) -> bool:
	if zone == null:
		return true
	return zone.is_walkable(cell)
