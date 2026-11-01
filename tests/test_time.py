"""Tests for the deterministic time arithmetic of the simulation core.

End-of-cycle convention under test
----------------------------------
Ticks are zero-based; tick 0 is Day 1 at 00:00. The closing tick 480 maps to
``(6, 0, 0)`` -- the end of the cycle, one instant past the last playable
slot (tick 479, Day 5 at 23:45). ``advance(480)`` raises
:class:`ClockOverflowError` instead of wrapping around silently.

Deadline convention under test
------------------------------
``is_past`` is exclusive: the deadline tick itself is still usable, so
``is_past(168, 168)`` is ``False`` and ``is_past(169, 168)`` is ``True``.

Calendar convention under test
------------------------------
``to_datetime`` returns the triple ``(day, hour, minute)``. A ``(day, hour)``
pair is lossy (four ticks share each hour), so the triple is what makes
``to_tick(*to_datetime(tick)) == tick`` hold for every tick.

Cycle convention under test
---------------------------
The length of the cycle is *data*: :func:`total_ticks` turns a number of
days into a number of ticks, and the default cycle lasts five days (480
ticks). Widening the cycle must not change the **daily** pattern, because
the schedules and the lighting normalise the tick with
``tick % TICKS_PER_DAY``.
"""

from __future__ import annotations

import pytest

from core.time import (
    CYCLE_DAYS,
    DEFAULT_CYCLE_DAYS,
    MINUTES_PER_TICK,
    TICKS_PER_DAY,
    TOTAL_TICKS,
    ClockOverflowError,
    advance,
    format_clock,
    is_past,
    to_datetime,
    to_tick,
    total_ticks,
)


def test_tick_constants_are_consistent() -> None:
    """The tick arithmetic constants must agree with each other."""
    assert MINUTES_PER_TICK == 15
    assert TICKS_PER_DAY == 96
    assert TOTAL_TICKS == CYCLE_DAYS * TICKS_PER_DAY
    assert total_ticks() == TOTAL_TICKS
    assert TICKS_PER_DAY * MINUTES_PER_TICK == 24 * 60


def test_cycle_days_default_to_five() -> None:
    """The playable cycle lasts five days by default.

    ``DEFAULT_CYCLE_DAYS`` is the reference length of the design and
    ``CYCLE_DAYS`` is the knob in use. They only differ once the cycle is
    deliberately widened, which is what makes the widening explicit.
    """
    assert DEFAULT_CYCLE_DAYS == 5
    assert total_ticks(DEFAULT_CYCLE_DAYS) == 480
    assert total_ticks() == TOTAL_TICKS
    assert total_ticks() == CYCLE_DAYS * TICKS_PER_DAY


@pytest.mark.parametrize("tick", range(TOTAL_TICKS + 1))
def test_to_tick_inverts_to_datetime(tick: int) -> None:
    """``to_tick(*to_datetime(t)) == t`` for every tick of the cycle."""
    day, hour, minute = to_datetime(tick)
    assert to_tick(day, hour, minute) == tick


@pytest.mark.parametrize("tick", range(TOTAL_TICKS))
def test_minute_alignment_is_preserved(tick: int) -> None:
    """Every tick advances exactly 15 minutes within its own day."""
    _, hour, minute = to_datetime(tick)
    minutes_of_day = (tick % TICKS_PER_DAY) * MINUTES_PER_TICK
    assert hour * 60 + minute == minutes_of_day


@pytest.mark.parametrize("tick", range(TICKS_PER_DAY))
def test_minute_alignment_within_day_one(tick: int) -> None:
    """Within Day 1 the minutes of the day equal ``tick * 15``."""
    _, hour, minute = to_datetime(tick)
    assert hour * 60 + minute == tick * MINUTES_PER_TICK


def test_to_datetime_day_boundaries() -> None:
    """The first tick of each day maps to midnight of that day."""
    for day in range(1, CYCLE_DAYS + 2):
        assert to_datetime((day - 1) * TICKS_PER_DAY) == (day, 0, 0)


def test_to_datetime_closing_tick() -> None:
    """The closing tick is the end of the cycle: the day after the last one."""
    assert to_datetime(TOTAL_TICKS) == (CYCLE_DAYS + 1, 0, 0)


def test_to_datetime_last_playable_slot() -> None:
    """The last tick of the cycle is the last slot of the last day."""
    assert to_datetime(TOTAL_TICKS - 1) == (CYCLE_DAYS, 23, 45)


@pytest.mark.parametrize(
    ("tick", "expected"),
    [
        (0, (1, 0, 0)),
        (1, (1, 0, 15)),
        (3, (1, 0, 45)),
        (4, (1, 1, 0)),
        (28, (1, 7, 0)),
        (29, (1, 7, 15)),
        (32, (1, 8, 0)),
        (95, (1, 23, 45)),
        (96, (2, 0, 0)),
        (160, (2, 16, 0)),
        (167, (2, 17, 45)),
        (168, (2, 18, 0)),
        (271, (3, 19, 45)),
        (272, (3, 20, 0)),
        (287, (3, 23, 45)),
        (288, (4, 0, 0)),
        (479, (5, 23, 45)),
        (480, (6, 0, 0)),
    ],
)
def test_to_datetime_known_instants(tick: int, expected: tuple[int, int, int]) -> None:
    """Spot check the tick -> (day, hour, minute) conversion."""
    assert to_datetime(tick) == expected


@pytest.mark.parametrize(
    ("day", "hour", "minute", "expected"),
    [
        (1, 0, 0, 0),
        (1, 0, 15, 1),
        (1, 0, 30, 2),
        (1, 0, 45, 3),
        (1, 1, 0, 4),
        (1, 7, 0, 28),
        (1, 23, 45, 95),
        (2, 0, 0, 96),
        (2, 16, 0, 160),
        (2, 18, 0, 168),
        (3, 20, 0, 272),
        (3, 23, 45, 287),
        (4, 0, 0, 288),
        (5, 23, 45, 479),
        (6, 0, 0, 480),
    ],
)
def test_to_tick_known_instants(day: int, hour: int, minute: int, expected: int) -> None:
    """Spot check the (day, hour, minute) -> tick conversion."""
    assert to_tick(day, hour, minute) == expected


def test_to_tick_defaults_to_the_top_of_the_hour() -> None:
    """The minute component is optional and defaults to zero."""
    assert to_tick(1, 0) == to_tick(1, 0, 0)
    assert to_tick(2, 16) == 160


def test_to_tick_rejects_off_boundary_minutes() -> None:
    """Minutes that are not multiples of 15 do not describe a tick."""
    with pytest.raises(ValueError, match="multiple of 15"):
        to_tick(1, 0, 7)


def test_to_tick_rejects_out_of_range_arguments() -> None:
    """Invalid day, hour and minute values are rejected."""
    with pytest.raises(ValueError, match="day must be >= 1"):
        to_tick(0, 0)
    with pytest.raises(ValueError, match=r"hour must be within \[0, 23\]"):
        to_tick(1, 24)
    with pytest.raises(ValueError, match=r"minute must be within \[0, 59\]"):
        to_tick(1, 0, 60)


def test_to_tick_rejects_instants_beyond_the_cycle() -> None:
    """Instants past the closing tick cannot be converted."""
    with pytest.raises(ValueError, match="beyond the cycle end"):
        to_tick(CYCLE_DAYS + 1, 0, 15)


@pytest.mark.parametrize("tick", [-1, TOTAL_TICKS + 1])
def test_conversions_reject_out_of_range_ticks(tick: int) -> None:
    """Ticks outside the cycle are rejected by every conversion helper."""
    with pytest.raises(ValueError):
        to_datetime(tick)
    with pytest.raises(ValueError):
        format_clock(tick)
    with pytest.raises(ValueError):
        is_past(tick, 0)


def test_format_clock_known_labels() -> None:
    """The human readable clock label uses the documented format."""
    assert format_clock(0) == "Day 1 00:00"
    assert format_clock(1) == "Day 1 00:15"
    assert format_clock(28) == "Day 1 07:00"
    assert format_clock(29) == "Day 1 07:15"
    assert format_clock(95) == "Day 1 23:45"
    assert format_clock(96) == "Day 2 00:00"
    assert format_clock(287) == "Day 3 23:45"
    assert format_clock(288) == "Day 4 00:00"
    assert format_clock(TOTAL_TICKS - 1) == f"Day {CYCLE_DAYS} 23:45"
    assert format_clock(TOTAL_TICKS) == f"Day {CYCLE_DAYS + 1} 00:00"


def test_format_clock_matches_to_datetime() -> None:
    """The formatted label and the calendar triple always agree."""
    for tick in range(TOTAL_TICKS + 1):
        day, hour, minute = to_datetime(tick)
        assert format_clock(tick) == f"Day {day} {hour:02d}:{minute:02d}"


def test_advance_moves_forward() -> None:
    """Advancing moves the clock forward by the requested number of ticks."""
    assert advance(0) == 1
    assert advance(0, 5) == 5
    assert advance(10, 0) == 10


def test_advance_is_monotonic() -> None:
    """Repeated single advances always move the clock forward by exactly one."""
    tick = 0
    for _ in range(50):
        new_tick = advance(tick)
        assert new_tick == tick + 1
        tick = new_tick


def test_advance_reaches_the_closing_tick() -> None:
    """The last playable slot can advance exactly one tick to the closing tick."""
    assert advance(TOTAL_TICKS - 1) == TOTAL_TICKS


def test_advance_past_the_cycle_raises() -> None:
    """Advancing beyond the cycle raises instead of wrapping around."""
    with pytest.raises(ClockOverflowError):
        advance(TOTAL_TICKS)
    with pytest.raises(ClockOverflowError):
        advance(TOTAL_TICKS - 1, 2)
    with pytest.raises(ClockOverflowError):
        advance(0, TOTAL_TICKS + 1)


def test_advance_rejects_negative_steps() -> None:
    """The clock is monotonic: negative steps are rejected."""
    with pytest.raises(ValueError, match="steps must be >= 0"):
        advance(10, -1)


def test_advance_rejects_non_integer_steps() -> None:
    """The number of steps must be an integer."""
    with pytest.raises(TypeError, match="steps must be an int"):
        advance(10, "1")  # type: ignore[arg-type]


def test_the_conversions_reject_non_integer_ticks() -> None:
    """A non-integer tick is a programming error."""
    with pytest.raises(TypeError, match="tick must be an int"):
        to_datetime("0")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="tick must be an int"):
        format_clock(None)  # type: ignore[arg-type]


def test_is_past_at_the_exact_boundary() -> None:
    """The deadline tick itself is still usable; it is exceeded on the next tick."""
    deadline = 168
    assert is_past(167, deadline) is False
    assert is_past(168, deadline) is False
    assert is_past(169, deadline) is True


@pytest.mark.parametrize(
    ("tick", "deadline", "expected"),
    [
        (0, 0, False),
        (0, 1, False),
        (1, 0, True),
        (100, 168, False),
        (168, 168, False),
        (169, 168, True),
        (TOTAL_TICKS - 1, TOTAL_TICKS, False),
        (TOTAL_TICKS, TOTAL_TICKS, False),
    ],
)
def test_is_past_table(tick: int, deadline: int, expected: bool) -> None:
    """The deadline comparison is exclusive and monotonic."""
    assert is_past(tick, deadline) is expected


def test_is_past_agrees_with_advance() -> None:
    """The deadline is exceeded only once the clock moves past it."""
    deadline = 168
    # advance() moves the clock forward by one tick.
    assert is_past(advance(deadline - 2), deadline) is False
    assert is_past(advance(deadline - 1), deadline) is False
    assert is_past(advance(deadline), deadline) is True
