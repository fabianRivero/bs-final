"""Simulation core. This package is the single source of truth for world state.

The core follows the dependency direction of ``PLAN.md`` (section 9.3):

    time      -> (nothing)
    resources -> (nothing)
    lighting  -> time
    schedule  -> time
    state     -> time, resources
    world     -> state, lighting, schedule, resources, time

Lower modules never import higher ones, and no module here ever imports
Godot. The state of the world is never stored: it is derived from
``(tick, decisions, resources)`` on demand.
"""

from core.lighting import (
    LIGHTING_TABLE,
    LightingPhase,
    LightState,
    lerp_opacity,
    light_state_at,
    phase_at,
)
from core.resources import (
    CRITICAL_COST_MULTIPLIER,
    ResourceSpec,
    ResourceState,
    apply_daily_decay,
    can_afford,
    consume,
    derive_crisis,
    empty_state,
    initial_state,
    reset_spent_today,
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
    CYCLE_DAYS,
    DEFAULT_CYCLE_DAYS,
    MINUTES_PER_TICK,
    TICKS_PER_DAY,
    TOTAL_TICKS,
    ClockOverflowError,
    ClockTime,
    advance,
    day_of,
    format_clock,
    is_past,
    tick_of_day,
    to_datetime,
    to_tick,
    total_ticks,
)
from core.world import (
    InsufficientResourcesError,
    InvalidActionError,
    WorldContentError,
    WorldSim,
)

__all__ = [
    "CRITICAL_COST_MULTIPLIER",
    "CYCLE_DAYS",
    "DEFAULT_ACTIVITY",
    "DEFAULT_CYCLE_DAYS",
    "DEFAULT_ZONE",
    "LIGHTING_TABLE",
    "MINUTES_PER_TICK",
    "TICKS_PER_DAY",
    "TOTAL_TICKS",
    "ClockOverflowError",
    "ClockTime",
    "Decision",
    "InsufficientResourcesError",
    "InvalidActionError",
    "LightState",
    "LightingPhase",
    "Npc",
    "NpcState",
    "ResourceSpec",
    "ResourceState",
    "ScheduleEntry",
    "ScheduleOverlapError",
    "WorldContentError",
    "WorldSim",
    "WorldState",
    "advance",
    "apply_daily_decay",
    "can_afford",
    "consume",
    "day_of",
    "derive",
    "derive_crisis",
    "empty_state",
    "format_clock",
    "initial_state",
    "is_available",
    "is_past",
    "lerp_opacity",
    "light_state_at",
    "npc_state",
    "phase_at",
    "reset_spent_today",
    "tick_of_day",
    "to_datetime",
    "to_tick",
    "total_ticks",
    "validate_schedule",
]
