extends TileMapLayer
class_name AldermereTileMapLayer
## A tile map layer that knows how to paint itself from plain colour data.
##
## The F3 prototype has no art assets, so the tiles are drawn as flat coloured
## cells. The class is nevertheless built around [TileMapLayer], the Godot 4.3+
## node that replaces the deprecated `TileMap`, so that dropping a real
## `TileSet` in later is a matter of assigning `tile_set` and calling
## [method TileMapLayer.set_cell] instead of rebuilding the layer.
##
## When a `TileSet` with an atlas source is assigned, the layer paints real
## tiles. Otherwise it falls back to coloured rectangles, which keeps the
## prototype playable without any binary asset.

## Colours used to paint the placeholder tiles, keyed by the terrain character.
##
## The keys are the characters of the terrain rows, so a row is read as it is
## written.
const TERRAIN_COLORS: Dictionary = {
	"g": Color(0.32, 0.42, 0.28),
	"p": Color(0.52, 0.47, 0.38),
	"w": Color(0.24, 0.22, 0.26),
	"x": Color(0.38, 0.30, 0.42),
	"~": Color(0.20, 0.34, 0.52),
}

## The colour used for a character that is not in the table.
const DEFAULT_TERRAIN_COLOR: Color = Color(0.32, 0.42, 0.28)

## Side of one tile, in pixels.
const TILE_SIZE: int = 32

## The terrain layout of the layer, one entry per row.
##
## The characters are the keys of [constant TERRAIN_COLORS]; anything else is
## treated as walkable ground.
@export var terrain_rows: Array[String] = []

## Whether the cells of this layer block movement.
@export var is_obstacle_layer: bool = false


## Paint the layer.
##
## With a `TileSet` assigned, the layer paints real tiles. Without one, it
## draws a coloured rectangle per cell, which is the placeholder used by the
## F3 prototype.
func paint() -> void:
	clear()
	for row_index in range(terrain_rows.size()):
		var row: String = terrain_rows[row_index]
		for column_index in range(row.length()):
			var terrain: String = row[column_index]
			var cell: Vector2i = Vector2i(column_index, row_index)
			if tile_set != null:
				_set_cell_with_tileset(cell)
			else:
				_add_placeholder_cell(cell, terrain)

## Paint a single cell with the tiles of the assigned tile set.
##
## @param cell Coordinates of the cell.
func _set_cell_with_tileset(cell: Vector2i) -> void:
	if tile_set == null:
		return
	var source_id: int = tile_set.get_source_id(0)
	if source_id < 0:
		return
	set_cell(cell, source_id, Vector2i.ZERO)


## Add a coloured placeholder for a cell.
##
## The placeholder is a [Polygon2D], not a [ColorRect]: a [Control] does not
## draw inside a [Node2D], and a [TileMapLayer] is a [Node2D].
##
## @param cell Coordinates of the cell.
## @param terrain The terrain name of the cell.
func _add_placeholder_cell(cell: Vector2i, terrain: String) -> void:
	var colour: Color = TERRAIN_COLORS.get(terrain, DEFAULT_TERRAIN_COLOR)
	var quad: Polygon2D = Polygon2D.new()
	quad.name = "Cell_%d_%d" % [cell.x, cell.y]
	quad.color = colour
	quad.polygon = PackedVector2Array([
		Vector2.ZERO,
		Vector2(TILE_SIZE, 0.0),
		Vector2(TILE_SIZE, TILE_SIZE),
		Vector2(0.0, TILE_SIZE),
	])
	quad.position = Vector2(cell.x * TILE_SIZE, cell.y * TILE_SIZE)
	add_child(quad)
