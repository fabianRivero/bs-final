# The Godot presentation layer

This document describes the Godot project of Aldermere: what it does, what it
deliberately does **not** do, and how to verify it.

The golden rule of the project applies to every line of this directory:

> **Python is the source of truth. Godot presents and captures input.**

Godot never decides the state of the world, never picks a lighting colour and
never invents a rule. It reads the exported content, draws it, and tells the
simulation core what the player did.

## The layout

```
game/
├── project.godot           InputMap, autoloads, display 960x540, gl_compatibility
├── export_presets.cfg      HTML5 preset "Compatibility"
├── autoload/
│   ├── game_state.gd       The tick, the decisions, the local derive()
│   ├── content_db.gd       Loads and caches game_content.json
│   ├── lighting.gd         Applies the lighting phase to the world
│   ├── scene_router.gd     Title <-> Game <-> Ending
│   └── autoload_ref.gd     Runtime lookup of the autoloads
├── scenes/
│   ├── title.tscn          The entry point
│   ├── game.tscn           The playable zone
│   ├── ending.tscn         The ending placeholder (F5)
│   ├── title_screen.gd     Builds the title screen in code
│   ├── game_world.gd       Builds the playable scene in code
│   └── ending_screen.gd    Builds the ending screen in code
├── world/
│   ├── zone.gd             A zone: its tiles and its walkable cells
│   ├── world_view.gd       The zones and the camera
│   └── tile_map_layer.gd   The TileMapLayer that paints the terrain
├── player/
│   ├── player.gd           Grid movement and the interaction query
│   └── action_request.gd   The offer the player makes to the world
├── npc/
│   ├── npc_agent.gd        Places an NPC according to its schedule
│   └── npc_sprite.gd       The visual part of an NPC
├── ui/
│   ├── hud.gd              Clock, tick, light phase, cycle bar
│   └── dialogue_ui.gd      The conversation panel (placeholder)
├── data/
│   └── game_content.json   The exported contract
├── assets/                 Prepared for the art assets (empty for now)
└── tests/
    ├── smoke_test.gd       The units: clock, derive, lighting, content
    ├── integration_test.gd The flow: input -> decision -> tick -> phase
    ├── scenes_test.gd      The three scenes build what they should
    ├── capture_screens.gd  Writes a screenshot per lighting phase
    └── capture_menus.gd    Writes a screenshot of the title and the ending
```

## The flow

```
input
  -> the player consults the world (is there an NPC in front of me?)
  -> the player emits an ActionRequest
  -> GameState records the decision and advances the tick
  -> GameState emits tick_changed
  -> ContentDb repositions the NPCs
  -> Lighting applies the phase of the new tick
  -> the HUD updates the clock
```

Every system **subscribes** to `tick_changed`. Nobody asks "what is in this
tick?" — the state is pushed.

## The local derivation

`autoload/game_state.gd` mirrors `core/state.py`. The flags are derived from
the decisions alone, so the derived flags do not depend on the tick, and the
GDScript derivation and the Python derivation produce the same set.

The vocabulary is the one of the Python core:

| Flag                | Raised by                                    |
|---|---|
| `decided:<kind>`   | any decision of that kind                    |
| `talked:<target>`  | a `talk` decision targeting that NPC         |
| `examined:<target>`| an `examine` decision targeting that object   |
| `visited:<zone>`   | a `move` decision into that zone             |
| `knows:symptom:<id>` | a `report_symptom` decision                |
| `<explicit>`       | the `sets_flags` key of the decision payload |

`tools/parity_check.py` compares the two implementations tick by tick in F5.

## The lighting

The phase table lives in `core/lighting.py` and is exported to the content
document. Godot applies it and never invents it.

The overlay is a `ColorRect` inside a `CanvasLayer` owned by the scene, with
the tint colour and the opacity of the phase. Opacity `0.0` is broad daylight
and opacity `1.0` is a closed night.

| Phase        | Ticks  | Clock      | Overlay rgb      | Opacity |
|---|---|---|---|---|
| `dawn_early` | 0-17   | 00:00-04:15 | (40, 50, 90)   | 0.55 |
| `dawn`       | 18-25  | 04:30-06:15 | (255, 170, 110)| 0.25 |
| `morning`    | 26-37  | 06:30-09:15 | (255, 214, 170)| 0.08 |
| `day`        | 38-65  | 09:30-16:15 | (255, 255, 255)| 0.00 |
| `afternoon`  | 66-75  | 16:30-18:45 | (255, 226, 180)| 0.06 |
| `dusk`       | 76-81  | 19:00-20:15 | (255, 150, 110)| 0.28 |
| `night`      | 82-95  | 20:30-23:45 | (40, 50, 90)   | 0.55 |

## The export

The content contract is produced by the Python side:

```bash
uv run python -m tools.export_web
```

It writes `game/data/game_content.json`, validates it against
`content.schema.WorldContent` and is deterministic: regenerating it without
content changes yields the same bytes.

## Verifying

```bash
make godot        # import the project, check that every script parses
make godot-test   # the three headless test suites
make godot-shots  # the screenshots of the seven phases (needs a display)
```

The suites can also be run one by one:

```bash
"../tools/godot/Godot_v4.7.2-stable_win64_console.exe" \
    --headless --path game --script res://tests/smoke_test.gd
```

The screenshots need a real display driver: `--headless` does not render.

## The rules the engine follows

Three Godot rules bite often, and every one of them cost a bug during F3:

1. **A `Control` under a `Node2D` does not get the viewport rect.** Its
   children keep their minimum size and stay left-aligned. A scene that holds
   UI has to be rooted on a `Control` (`title.tscn`, `ending.tscn`) or on a
   `CanvasLayer` (`hud.gd`, `dialogue_ui.gd`).
2. **A `Control` does not draw inside a `Node2D`.** Every placeholder shape
   of the prototype is a `Polygon2D`, because the player, the NPCs and the
   tiles are all `Node2D`.
3. **The draw order must be explicit.** The ground is at `z_index = -20`, the
   obstacles at `-10`, the actors at `0`. Relying on the order of
   `add_child` calls put the ground on top of the player.

## What is still a stub

| Feature | Status | Phase |
|---|---|---|
| Dialogue | the panel opens and closes, no options | F4 |
| NPC schedules | the agents follow the schedule of the content | F4 |
| Missions | not wired | F4 |
| Investigation | not wired | F4 |
| Endings | the screen is a placeholder | F5 |
| The HTML5 export | the preset is prepared, the build is not run | F5 |
| The parity check | `tools/parity_check.py` is still a stub | F5 |
| Art | flat colours, the structure is ready for a `TileSet` | F4 |
