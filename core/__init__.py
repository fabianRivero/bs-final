"""Simulation core. This package is the single source of truth for world state."""

from core.time import (
    MINUTES_PER_TICK,
    TICKS_PER_DAY,
    TOTAL_TICKS,
    ClockOverflowError,
    advance,
    format_clock,
    is_past,
    to_datetime,
    to_tick,
)

__all__ = [
    "MINUTES_PER_TICK",
    "TICKS_PER_DAY",
    "TOTAL_TICKS",
    "ClockOverflowError",
    "advance",
    "format_clock",
    "is_past",
    "to_datetime",
    "to_tick",
]
