# Assets

This directory holds the art assets of the game. It is **prepared but empty**:
the F3 prototype draws flat coloured shapes instead of real art, and the
structure is ready for the real assets to drop in.

## Expected layout

```
assets/
├── tiles/
│   ├── mill_yard.png          # TileSet atlas for the zone ZN_YARD
│   └── village_hall.png       # TileSet atlas for the zone ZN_HALL
└── portraits/
    ├── miller.png             # Portrait of NPC_MILLER
    └── keeper.png             # Portrait of NPC_KEEPER
```

The paths of these files are already referenced by
`res://data/game_content.json` (the `tiles_path` and `portrait` fields of the
zones and the NPCs), so the content does not have to change when the art
arrives.

## How the tiles are consumed

`world/tile_map_layer.gd` is built around [TileMapLayer], the Godot 4.3+ node
that replaced the deprecated `TileMap`. Two modes are supported:

- **With a TileSet** — assign a `TileSet` to the layer and it paints real
  tiles through `set_cell`. The terrain characters of the layer select the
  atlas cell.
- **Without a TileSet** (the F3 prototype) — the layer paints one coloured
  `ColorRect` per cell, using the `TERRAIN_COLORS` table.

The terrain characters understood by the placeholder painter are the keys of
the `TERRAIN_COLORS` table of `world/tile_map_layer.gd`:

| Character | Meaning | Colour                     |
|---|---|---|
| `g`       | ground  | `(0.32, 0.42, 0.28)`       |
| `p`       | path    | `(0.52, 0.47, 0.38)`       |
| `w`       | wall    | `(0.24, 0.22, 0.26)`       |
| `x`       | prop    | `(0.38, 0.30, 0.42)`       |
| `~`       | water   | `(0.20, 0.34, 0.52)`       |

Any other character is treated as walkable ground.

## The placeholder shapes

The prototype draws its shapes with `Polygon2D`, not with `ColorRect`: a
`Control` does not draw inside a `Node2D`, and every actor of the world is a
`Node2D`. The same applies to the tiles, which are children of a
`TileMapLayer`.
