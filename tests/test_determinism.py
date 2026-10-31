"""Tests proving that the simulation core is deterministic.

The project invariant is: the same tick plus the same decisions always yields
the same world state. Determinism of the clock is the foundation of that
invariant, so it gets its own test module.
"""

from __future__ import annotations

from core.time import TOTAL_TICKS, advance, format_clock, to_datetime, to_tick


def _run_sequence(start: int, steps: list[int]) -> list[int]:
    """Advance the clock step by step and return the visited ticks."""
    visited = [start]
    tick = start
    for step in steps:
        tick = advance(tick, step)
        visited.append(tick)
    return visited


def test_identical_sequences_produce_identical_ticks() -> None:
    """Two runs of the same action sequence land on the same ticks."""
    steps = [1, 1, 1, 2, 5, 1, 3]
    first = _run_sequence(0, steps)
    second = _run_sequence(0, steps)
    assert first == second


def test_identical_sequences_produce_identical_clock_labels() -> None:
    """Two runs of the same action sequence produce the same clock labels."""
    steps = [1] * 20
    first = [format_clock(tick) for tick in _run_sequence(0, steps)]
    second = [format_clock(tick) for tick in _run_sequence(0, steps)]
    assert first == second


def test_sequence_is_reproducible_from_a_different_start() -> None:
    """Starting from a different tick does not change the shape of the sequence."""
    steps = [1, 2, 1]
    assert _run_sequence(10, steps) == [10, 11, 13, 14]
    assert _run_sequence(10, steps) == _run_sequence(10, steps)


def test_step_by_step_advance_equals_direct_advance() -> None:
    """Advancing one tick at a time equals advancing by the total in one go."""
    steps = [1, 1, 1, 1, 1]
    stepped = _run_sequence(0, steps)[-1]
    direct = advance(0, sum(steps))
    assert stepped == direct


def test_full_cycle_walk_is_reproducible() -> None:
    """Walking the whole cycle twice yields the same visited ticks."""
    steps = [1] * TOTAL_TICKS
    assert _run_sequence(0, steps) == _run_sequence(0, steps)
    assert _run_sequence(0, steps)[-1] == TOTAL_TICKS


def test_tick_round_trip_is_stable_across_the_cycle() -> None:
    """Converting a tick to (day, hour) and back is stable and reproducible."""
    for tick in range(TOTAL_TICKS + 1):
        day, hour, minute = to_datetime(tick)
        assert to_tick(day, hour, minute) == tick
        assert to_datetime(tick) == (day, hour, minute)
