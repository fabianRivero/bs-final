"""Tests for the configurable length of the playable cycle.

The cycle length is **data**: :func:`core.time.total_ticks` turns a number of
days into a number of ticks. The tests below pin down the two properties that
make the cycle genuinely configurable:

1. **Widening the cycle does not change the daily pattern.** The schedules
   and the lighting normalise the absolute tick with ``tick % TICKS_PER_DAY``,
   so tick 28 and tick 316 resolve to the same NPC state and the same lighting
   phase. This is what makes a fifteen-day cycle a one-line change.
2. **The clock arithmetic stays exact at any length.** The round trip
   ``to_tick(*to_datetime(tick)) == tick`` holds for *every* tick of the
   default cycle and of a fifteen-day cycle.

The default cycle is five days (480 ticks). A fifteen-day cycle (1440 ticks)
is the target the design is meant to reach, so it is exercised here even
though it is not the default.
"""

from __future__ import annotations

import pytest

from core.lighting import phase_at
from core.schedule import Npc, ScheduleEntry, npc_state
from core.time import (
    CYCLE_DAYS,
    DEFAULT_CYCLE_DAYS,
    TICKS_PER_DAY,
    TOTAL_TICKS,
    ClockOverflowError,
    advance,
    day_of,
    tick_of_day,
    to_datetime,
    to_tick,
    total_ticks,
)

#: Number of days of the cycle the design is meant to reach eventually.
LONG_CYCLE_DAYS = 15


def test_total_ticks_of_the_default_cycle() -> None:
    """The default cycle lasts five days.

    The assertion is written against the constants, not against literals, so
    it keeps holding when ``CYCLE_DAYS`` is widened.
    """
    assert DEFAULT_CYCLE_DAYS == 5
    assert total_ticks(DEFAULT_CYCLE_DAYS) == DEFAULT_CYCLE_DAYS * TICKS_PER_DAY
    assert total_ticks() == CYCLE_DAYS * TICKS_PER_DAY
    assert total_ticks() == TOTAL_TICKS


def test_total_ticks_of_a_fifteen_day_cycle() -> None:
    """A fifteen-day cycle holds 1440 ticks."""
    assert total_ticks(LONG_CYCLE_DAYS) == 1440


def test_total_ticks_of_a_single_day_cycle() -> None:
    """A one-day cycle holds exactly one day of ticks."""
    assert total_ticks(1) == 96
    assert total_ticks(1) == TICKS_PER_DAY


@pytest.mark.parametrize("cycle_days", [0, -1, -15])
def test_total_ticks_rejects_non_positive_cycles(cycle_days: int) -> None:
    """A cycle must last at least one day."""
    with pytest.raises(ValueError, match="cycle_days must be >= 1"):
        total_ticks(cycle_days)


def test_total_ticks_rejects_non_integer_cycles() -> None:
    """A cycle length is an integer number of days."""
    with pytest.raises(TypeError, match="cycle_days must be an int"):
        total_ticks("15")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="cycle_days must be an int"):
        total_ticks(True)  # type: ignore[arg-type]


def test_total_ticks_scales_linearly_with_the_days() -> None:
    """Every extra day adds exactly one day of ticks."""
    for days in range(1, 31):
        assert total_ticks(days) == days * TICKS_PER_DAY


def test_the_closing_tick_of_a_long_cycle_is_reachable() -> None:
    """The last slot of a fifteen-day cycle advances to the closing tick."""
    closing = total_ticks(LONG_CYCLE_DAYS)
    assert advance(closing - 1, cycle_days=LONG_CYCLE_DAYS) == closing


def test_advancing_past_a_long_cycle_raises() -> None:
    """A long cycle is bounded exactly like the default one."""
    closing = total_ticks(LONG_CYCLE_DAYS)
    with pytest.raises(ClockOverflowError):
        advance(closing, cycle_days=LONG_CYCLE_DAYS)
    with pytest.raises(ClockOverflowError):
        advance(closing - 1, 2, cycle_days=LONG_CYCLE_DAYS)


def test_to_datetime_of_the_closing_tick_of_a_long_cycle() -> None:
    """The closing tick of a fifteen-day cycle is Day 16 at 00:00."""
    closing = total_ticks(LONG_CYCLE_DAYS)
    assert to_datetime(closing, LONG_CYCLE_DAYS) == (LONG_CYCLE_DAYS + 1, 0, 0)


def test_to_datetime_of_the_last_slot_of_a_long_cycle() -> None:
    """The last slot of a fifteen-day cycle is Day 15 at 23:45."""
    closing = total_ticks(LONG_CYCLE_DAYS)
    assert to_datetime(closing - 1, LONG_CYCLE_DAYS) == (LONG_CYCLE_DAYS, 23, 45)


def test_day_of_a_long_cycle() -> None:
    """``day_of`` counts the days of a fifteen-day cycle."""
    closing = total_ticks(LONG_CYCLE_DAYS)
    assert day_of(0, LONG_CYCLE_DAYS) == 1
    assert day_of(closing - 1, LONG_CYCLE_DAYS) == LONG_CYCLE_DAYS
    assert day_of(closing, LONG_CYCLE_DAYS) == LONG_CYCLE_DAYS + 1


def test_day_of_matches_to_datetime() -> None:
    """``day_of`` and ``to_datetime`` always agree on the day."""
    for tick in range(TOTAL_TICKS + 1):
        assert day_of(tick) == to_datetime(tick)[0]


def test_tick_of_day_normalises_inside_the_day() -> None:
    """``tick_of_day`` reduces a tick to its position within the day."""
    assert tick_of_day(0) == 0
    assert tick_of_day(28) == 28
    assert tick_of_day(95) == 95
    assert tick_of_day(96) == 0
    assert tick_of_day(316) == 28


@pytest.mark.parametrize("cycle_days", [DEFAULT_CYCLE_DAYS, LONG_CYCLE_DAYS])
def test_the_round_trip_is_exact_for_every_tick_of_the_cycle(cycle_days: int) -> None:
    """``to_tick(*to_datetime(t)) == t`` for every tick of the cycle."""
    closing = total_ticks(cycle_days)
    for tick in range(closing + 1):
        day, hour, minute = to_datetime(tick, cycle_days)
        assert to_tick(day, hour, minute, cycle_days) == tick


@pytest.mark.parametrize("cycle_days", [DEFAULT_CYCLE_DAYS, LONG_CYCLE_DAYS])
def test_the_clock_reaches_every_tick_of_the_cycle(cycle_days: int) -> None:
    """Advancing one tick at a time walks the whole cycle exactly once."""
    closing = total_ticks(cycle_days)
    tick = 0
    for _ in range(closing):
        tick = advance(tick, cycle_days=cycle_days)
        assert tick <= closing
    assert tick == closing


def test_widening_the_cycle_does_not_change_the_daily_pattern() -> None:
    """The daily pattern repeats every 96 ticks, whatever the cycle lasts.

    This is the property that makes a fifteen-day cycle a one-line change:
    the schedules and the lighting are expressed in day ticks, so the same
    moment of the day resolves to the same state three days later.
    """
    npc = Npc(
        id="NPC_PROBE",
        name="Probe",
        schedule=(
            ScheduleEntry(
                start_tick=24,
                end_tick=32,
                zone="ZONE_A",
                tile=(1, 1),
                activity="working",
                interactable=True,
            ),
        ),
    )

    base_tick = 28
    for days_later in range(0, LONG_CYCLE_DAYS):
        other_tick = base_tick + TICKS_PER_DAY * days_later
        assert npc_state(npc, other_tick) == npc_state(npc, base_tick)
        assert phase_at(other_tick) == phase_at(base_tick)


def test_the_cycle_constant_is_the_only_knob() -> None:
    """``CYCLE_DAYS`` is the single source of truth of the cycle length."""
    assert TOTAL_TICKS == CYCLE_DAYS * TICKS_PER_DAY
    assert total_ticks() == TOTAL_TICKS
    assert total_ticks(CYCLE_DAYS) == TOTAL_TICKS
