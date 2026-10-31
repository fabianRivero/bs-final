"""Simulation core. This package is the single source of truth for world state.

The core follows the dependency direction of ``PLAN.md`` (section 9.3):

    time      -> (nothing)
    lighting  -> time
    schedule  -> time
    state     -> time
    world     -> state, lighting, schedule, time

Lower modules never import higher ones, and no module here ever imports
Godot. The state of the world is never stored: it is derived from
``(tick, decisions)`` on demand.
"""

from core.lighting import (
    LIGHTING_TABLE,
    LightingPhase,
    LightState,
    lerp_opacity,
    light_state_at,
    phase_at,
)
from core.schedule import (
    DEFAULT_ACTIVITY,
    DEFAULT_ZONE,
    Npc,
    NpcState,
    ScheduleEntry,
    ScheduleOverlapError,
    is_available,
    npc_state,
    validate_schedule,
)
from core.state import Decision, WorldState, derive
from core.time import (
    MINUTES_PER_TICK,
    TICKS_PER_DAY,
    TOTAL_TICKS,
    ClockOverflowError,
    ClockTime,
    advance,
    format_clock,
    is_past,
    to_datetime,
    to_tick,
)
from core.world import InvalidActionError, WorldContentError, WorldSim

__all__ = [
    "DEFAULT_ACTIVITY",
    "DEFAULT_ZONE",
    "LIGHTING_TABLE",
    "MINUTES_PER_TICK",
    "TICKS_PER_DAY",
    "TOTAL_TICKS",
    "ClockOverflowError",
    "ClockTime",
    "Decision",
    "InvalidActionError",
    "LightState",
    "LightingPhase",
    "Npc",
    "NpcState",
    "ScheduleEntry",
    "ScheduleOverlapError",
    "WorldContentError",
    "WorldSim",
    "WorldState",
    "advance",
    "derive",
    "format_clock",
    "is_available",
    "is_past",
    "lerp_opacity",
    "light_state_at",
    "npc_state",
    "phase_at",
    "to_datetime",
    "to_tick",
    "validate_schedule",
]
