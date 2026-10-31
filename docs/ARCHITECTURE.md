# Architecture

This document is a condensed map of how Aldermere is put together. It is
deliberately short: the authoritative planning document is `PLAN.md` (kept
outside this repository), and this file only records the structure that the
code actually follows.

## The golden rule

> **Python is the source of truth. Godot presents and captures input.**

Everything else in the project derives from that sentence.

- Godot **never** decides the state of the world. It asks "what is in tick
  137?" and draws it.
- Godot **never** invents rules. If a rule is not in the exported JSON, the
  rule does not exist in the game.
- Every mutation of the world goes through the tick. `advance()` in Python is
  the only thing that can move the clock.
- All content — premise, zones, NPCs, schedules, events, missions, dialogues,
  conditions, endings and lighting phases — is **never** written in GDScript.
  It lives in JSON authored and validated by Python.

## Data flow

```
  BUILD TIME (outside the game, zero runtime cost)
  ================================================

     content/prompts/*.txt  +  content/base/*.json
                 |
                 v
       content/generate.py ---> content/llm.py ---> LLM API
                 |                       |
                 |                  (disk cache)
                 v
       content/schema.py  --validate-->  content/generated/*.json
            (pydantic)                  + content/generated/manifest.json
                                        (version, prompt, model, seed, sha256)
                 |
                 |  git commit: generated content is versioned
                 v

  RUNTIME (the game)
  ==================

     +-------------------------------------------------------------+
     |  SIMULATION CORE  (pure Python, no engine imports)          |
     |                                                             |
     |   time.py         tick <-> (day, HH:MM), advance, deadlines |
     |   lighting.py     light_state_at(tick) -> phase/rgb/opacity |
     |   schedule.py     npc_state(npc, tick)                      |
     |   events.py       events_between(tick_prev, tick)           |
     |   state.py        WorldState = f(tick, decisions)            |
     |   missions.py     mission_state = f(state)                   |
     |   dialogue.py     resolve_node(node, state)                 |
     |   investigation.py symptoms, sources, hypotheses            |
     |   endings.py      endings.evaluate(state) -> EndingId       |
     |   world.py        composition root: WorldSim                 |
     +-------------------------------------------------------------+
                 |
                  |  tools/export_web.py
                  v
         build/game_content.json        <-- the single contract
                 |
                 v
     +-------------------------------------------------------------+
     |  GODOT 4.6  (presentation + input only)                      |
     |                                                             |
     |   content_loader.gd  loads and parses the JSON               |
     |   world_view.gd      draws tiles, colliders, camera          |
     |   tile_map.gd        one TileMapLayer per zone              |
     |   lighting.gd        applies the tint overlay               |
     |   npc_agent.gd       positions NPCs from the derived state   |
     |   dialogue_ui.gd     shows dialogue, reports symptoms        |
     |   player.gd          grid movement, emits ActionRequest     |
     |   hud.gd             clock, day, tick, light phase, goals   |
     |   save_manager.gd    writes {tick, decisions, player_tile}   |
     +-------------------------------------------------------------+
                 |
                 |  optional: HTTPRequest to a local proxy (tools/serve.py)
                 v
              LLM API  (the API key never leaves the Python process)
```

## Why the state is derived

The world state is **not stored**. It is a pure function:

```
WorldState = derive(tick, decisions)
```

`tick` says *when* it is; `decisions` says *what the player chose*. Nothing
else. Everything else — where each NPC stands, which dialogue lines are
available, which mission step is active, which lighting phase applies, whether
a deadline has passed — is recomputed from those two inputs.

This has three consequences that the rest of the project depends on:

1. **Save/load is trivial.** A save file only needs `{tick, decisions,
   player_tile}`. Reloading reconstructs the exact same world, because the
   world was never stored in the first place.
2. **Determinism is testable.** The same tick plus the same decisions always
   yields the same state, which is what the test suite asserts.
3. **There is a single place where rules live.** Because no rule is written
   twice, Python and Godot cannot drift apart in their reasoning; they can
   only disagree about *rendering* the same derived state, and that is exactly
   what `tools/parity_check.py` verifies.

The trade-off is honest and worth stating: deriving the state on every tick
costs CPU. The mitigation is that the derived values are a small, fixed set
per tick, and the plan allows pre-computing them into a table if profiling
ever shows it matters.

## Module responsibilities

| Module | Responsibility | Must not do |
|---|---|---|
| `core/time.py` | Tick arithmetic, clock formatting, deadline comparison | Decide events or content |
| `core/lighting.py` | Derive the lighting phase, colour and overlay opacity for a tick | Choose art palettes or Godot effects |
| `core/schedule.py` | Resolve the state of an NPC at a given tick | Talk to the player |
| `core/events.py` | Detect events between two ticks and compute their effect | Write to disk |
| `core/state.py` | Define the derived `WorldState` and `derive(tick, decisions)` | Store mutable state |
| `core/missions.py` | Derive the state of every mission | Grant rewards directly |
| `core/dialogue.py` | Resolve a dialogue node given flags and the tick | Decide the next mission |
| `core/investigation.py` | Record symptoms and sources, derive hypotheses, verify them | Contain literals of the concrete cause |
| `core/endings.py` | Evaluate the final ending | Mutate the world or restart the run |
| `core/world.py` | Composition root: load the content, expose `WorldSim` | Depend on pydantic at runtime |
| `content/schema.py` | Pydantic models for the whole content document | Generate content |
| `content/generate.py` | Build-time pipeline: prompts to LLM to validated output | Run inside the game |
| `content/llm.py` | Abstracted LLM client with an on-disk cache | Be called from Godot |
| `tools/simulate.py` | CLI: simulate a tick range, dump state, list events | — |
| `tools/export_web.py` | Serialise the content to `build/game_content.json` and drive the HTML5 export | Depend on the LLM API |
| `tools/parity_check.py` | Compare the Python state with what Godot renders | Write into the content |

## Dependency direction

Dependencies are strict and acyclic. Lower modules never import higher ones.

```
time      -> (nothing)
lighting  -> time
schedule  -> time
events    -> time, state
state     -> time, schedule, events
missions  -> state
dialogue  -> state
investigation -> state, missions
endings   -> state, missions, investigation
world     -> state, missions, dialogue, investigation, endings, content.schema

content.generate -> content.llm, content.schema
tools.export_web -> world, content.schema
```

## The derived state, concretely

Phase F1 implemented the first four modules of the map above. The shape of the
derived state is already fixed, and the rest of the phases must follow it.

### `core/state.py`

```python
derive(tick: int, decisions: Sequence[Decision]) -> WorldState
```

`WorldState` is a frozen dataclass holding `tick`, the calendar triple
(`day`, `hour`, `minute`), the `decisions` tuple and the derived `flags`
frozenset. The flag vocabulary is derived from the decisions themselves, so
no rule lives in two places:

| Flag | Raised by |
|---|---|
| `decided:<kind>` | any decision of that kind |
| `talked:<target>` | a `talk` decision targeting that NPC |
| `examined:<target>` | an `examine` decision targeting that object |
| `visited:<zone>` | a `move` decision into that zone |
| `knows:symptom:<id>` | a `report_symptom` decision |
| `<explicit>` | the `sets_flags` key of the decision payload |

Helpers: `has_flag(name)`, `decisions_of(kind)`, `symptoms_known()`.

### `core/schedule.py`

`npc_state(npc, tick)` normalises the tick with `tick % TICKS_PER_DAY`, so the
daily pattern repeats on every day of the cycle. Schedule blocks cover the
half-open range `[start_tick, end_tick)` and must not overlap; an overlapping
schedule raises `ScheduleOverlapError` at load time. When no block covers the
tick the NPC falls back to its default state (idle, not interactable), unless
the schedule declares an explicit `default` block.

### `core/lighting.py`

Seven phases cover the 96 ticks of a day without gaps and without overlaps:

| Phase | Ticks | Clock | Overlay rgb | Opacity |
|---|---|---|---|---|
| `dawn_early` | 0-17 | 00:00-04:15 | (40, 50, 90) | 0.55 |
| `dawn` | 18-25 | 04:30-06:15 | (255, 170, 110) | 0.25 |
| `morning` | 26-37 | 06:30-09:15 | (255, 214, 170) | 0.08 |
| `day` | 38-65 | 09:30-16:15 | (255, 255, 255) | 0.00 |
| `afternoon` | 66-75 | 16:30-18:45 | (255, 226, 180) | 0.06 |
| `dusk` | 76-81 | 19:00-20:15 | (255, 150, 110) | 0.28 |
| `night` | 82-95 | 20:30-23:45 | (40, 50, 90) | 0.55 |

`lerp_opacity(prev, next, t)` is the pure interpolation used to blend the
overlay across a phase boundary; it is exported to Godot so both sides
compute bit-identical values.

### `core/world.py`

`WorldSim` is the composition root. It stores **only** the tick and the list
of decisions; `state()`, `npc_states()` and `light()` recompute everything
else on demand. `advance(action)` validates the action *before* moving the
clock: an invalid action raises `InvalidActionError` and does **not** consume
a tick. `apply(decision)` is the hook for events, which record their effect
without moving the clock.


## The Godot boundary

Godot is allowed to: read the exported JSON, draw it, and emit player
actions. Godot is not allowed to: compute the time, decide events, evaluate
hypotheses, complete missions, or pick lighting colours.

That restriction is mechanically checkable. A grep for time or rule keywords
inside `game/` must only ever match presentation code:

```bash
grep -rn "hour\|day\|deadline" game/
```

Anything beyond the HUD clock is a violation of the golden rule.
