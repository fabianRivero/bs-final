extends Node2D
class_name AldermereZone
## A playable zone of the town.
##
## A zone owns the tiles of a part of the world and knows which of its cells
## can be walked on. It answers the question "can the player stand there?",
## which is a **query about the world**, not a rule: the decision of whether an
## action happens still belongs to the simulation core.
##
## The F3 prototype ships a single playable zone. The zone reads its size from
## the content document and lays out a placeholder layout, so the structure
## survives the arrival of the real art assets.

## Emitted when the zone finishes building its tiles.
signal zone_built(zone_id: String)

## Side of one tile, in pixels.
const TILE_SIZE: int = 32

## Draw order of the ground layer.
const Z_GROUND: int = -20

## Draw order of the obstacle layer.
const Z_OBSTACLE: int = -10

## The id of the zone, e.g. `"ZN_YARD"`.
var zone_id: String = ""

## The display name of the zone.
var zone_name: String = ""

## The zone document read from the content database.
var data: Dictionary = {}

## The ground layer of the zone.
var ground_layer: AldermereTileMapLayer = null

## The obstacle layer of the zone.
var obstacle_layer: AldermereTileMapLayer = null

## The cells that block movement, keyed by their coordinates.
var _blocked: Dictionary = {}


## Build the zone from its content document.
##
## @param zone_data The zone document read from the content database.
func build(zone_data: Dictionary) -> void:
	data = zone_data
	zone_id = String(zone_data.get("id", ""))
	zone_name = String(zone_data.get("name", zone_id))

	ground_layer = AldermereTileMapLayer.new()
	ground_layer.name = "Ground"
	ground_layer.z_index = Z_GROUND
	ground_layer.terrain_rows = _default_terrain()
	ground_layer.paint()
	add_child(ground_layer)

	obstacle_layer = AldermereTileMapLayer.new()
	obstacle_layer.name = "Obstacles"
	obstacle_layer.z_index = Z_OBSTACLE
	obstacle_layer.is_obstacle_layer = true
	obstacle_layer.terrain_rows = _default_terrain()
	obstacle_layer.paint()
	add_child(obstacle_layer)

	_recompute_blocked_cells()
	zone_built.emit(zone_id)


## Return the default terrain layout of the zone.
##
## The layout is derived from the size declared in the content document, so a
## different zone gets a different shape without touching the code.
##
## @return The terrain rows of the zone.
func _default_terrain() -> Array[String]:
	var width: int = int(data.get("width", 20))
	var height: int = int(data.get("height", 14))
	var rows: Array[String] = []

	for row_index in range(height):
		var row: String = ""
		for column_index in range(width):
			var border: bool = (
				row_index == 0
				or column_index == 0
				or row_index == height - 1
				or column_index == width - 1
			)
			var path: bool = row_index == height / 2 or column_index == width / 2
			if border:
				row += "w"
			elif path:
				row += "p"
			else:
				row += "g"
		rows.append(row)
	return rows


## Recompute the set of cells that block movement.
##
## A cell blocks movement when the obstacle layer paints a wall or a prop on
## it, or when the ground layer paints water.
func _recompute_blocked_cells() -> void:
	_blocked.clear()
	if obstacle_layer == null:
		return
	for row_index in range(obstacle_layer.terrain_rows.size()):
		var row: String = obstacle_layer.terrain_rows[row_index]
		for column_index in range(row.length()):
			var terrain: String = row[column_index]
			if terrain == "w" or terrain == "x":
				_blocked[Vector2i(column_index, row_index)] = true


## Check whether a cell can be walked on.
##
## @param cell The cell to check.
## @return `true` when the player may stand on the cell.
func is_walkable(cell: Vector2i) -> bool:
	if _blocked.has(cell):
		return false
	if ground_layer == null:
		return true
	if cell.y < 0 or cell.y >= ground_layer.terrain_rows.size():
		return false
	var row: String = ground_layer.terrain_rows[cell.y]
	if cell.x < 0 or cell.x >= row.length():
		return false
	return row[cell.x] != "w"


## Return the size of the zone, in tiles.
##
## @return A vector holding the width and the height of the zone.
func size_in_tiles() -> Vector2i:
	return Vector2i(
		int(data.get("width", 0)),
		int(data.get("height", 0))
	)
