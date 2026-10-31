"""Deterministic time arithmetic for the Aldermere simulation.

The whole game is driven by a single monotonic integer counter called a *tick*.

* One tick represents 15 minutes of in-game time.
* One day is 96 ticks (24h / 15min).
* The full playable cycle is 3 days, i.e. 288 ticks.

Tick numbering and end-of-cycle convention
------------------------------------------
Ticks are zero-based and start at the beginning of Day 1 at 00:00:

    tick 0   -> Day 1, 00:00
    tick 95  -> Day 1, 23:45   (last slot of Day 1)
    tick 96  -> Day 2, 00:00
    tick 287 -> Day 3, 23:45   (last slot of Day 3)
    tick 288 -> Day 4, 00:00   (the cycle *closing* tick)

The closing tick ``288`` is a valid instant: it is the end of the cycle, and
:meth:`to_datetime` maps it to ``(4, 0, 0)``. It is *not* a slot in which an
action can be taken, because :meth:`advance` refuses to move past it. There
is no silent wrap-around: advancing beyond the closing tick raises
:class:`ClockOverflowError`.

Why the calendar is a triple
----------------------------
A tick is 15 minutes wide, so **four consecutive ticks share the same
``(day, hour)`` pair**: ticks 28, 29, 30 and 31 are all 07:00 on Day 1. A
``(day, hour)`` pair is therefore lossy and cannot be inverted. The calendar
value exposed by this module is consequently the triple
``(day, hour, minute)``, where ``minute`` is always a multiple of
``MINUTES_PER_TICK``. That makes the round trip exact:

    to_tick(*to_datetime(tick)) == tick    for every tick in the cycle

This matches the canonical test suite defined in ``PLAN.md`` (section 11.3).

All functions in this module are pure and deterministic. Given the same
inputs they always return the same outputs, which is what makes the
"same tick + same decisions => same world" invariant of the project hold.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "MINUTES_PER_TICK",
    "TICKS_PER_DAY",
    "TOTAL_TICKS",
    "ClockOverflowError",
    "ClockTime",
    "advance",
    "format_clock",
    "is_past",
    "to_datetime",
    "to_tick",
]

#: Number of minutes of in-game time represented by a single tick.
MINUTES_PER_TICK = 15

#: Number of ticks in a full in-game day (24h / 15min).
TICKS_PER_DAY = 96

#: Number of ticks in the full playable cycle (3 days).
TOTAL_TICKS = 288

#: Number of ticks that fit in a single in-game hour (60 / 15).
TICKS_PER_HOUR = 60 // MINUTES_PER_TICK


class ClockOverflowError(ValueError):
    """Raised when a clock operation would move past the end of the cycle.

    The clock is monotonic and bounded. Advancing past ``TOTAL_TICKS`` is a
    programming error rather than a gameplay state, so it raises instead of
    wrapping around silently.
    """


@dataclass(frozen=True)
class ClockTime:
    """An absolute position in the Aldermere timeline.

    Attributes:
        tick: Absolute tick index, ``0 <= tick <= TOTAL_TICKS``.
        day: Day number, starting at 1.
        hour: Hour of the day in 24h format, ``0 <= hour <= 23``.
        minute: Minute within the hour, always a multiple of
            ``MINUTES_PER_TICK``.
    """

    tick: int
    day: int
    hour: int
    minute: int


def _validate_tick(tick: int) -> int:
    """Ensure ``tick`` lies inside the playable cycle.

    Args:
        tick: Tick index to validate.

    Returns:
        The validated tick.

    Raises:
        ValueError: If ``tick`` is negative or greater than ``TOTAL_TICKS``.
    """
    if not isinstance(tick, int) or isinstance(tick, bool):
        raise TypeError(f"tick must be an int, got {type(tick).__name__}")
    if tick < 0:
        raise ValueError(f"tick must be >= 0, got {tick}")
    if tick > TOTAL_TICKS:
        raise ValueError(f"tick must be <= {TOTAL_TICKS}, got {tick}")
    return tick


def to_datetime(tick: int) -> tuple[int, int, int]:
    """Convert a tick into a ``(day, hour, minute)`` calendar instant.

    The triple is lossless: every tick of the cycle maps to exactly one
    instant, and every instant maps back to exactly one tick.

    Args:
        tick: Tick index in ``[0, TOTAL_TICKS]``.

    Returns:
        Tuple ``(day, hour, minute)`` with a 1-based day, a 24h hour and a
        minute that is a multiple of ``MINUTES_PER_TICK``.

    Raises:
        ValueError: If ``tick`` is out of range.

    Example:
        >>> to_datetime(0)
        (1, 0, 0)
        >>> to_datetime(95)
        (1, 23, 45)
        >>> to_datetime(96)
        (2, 0, 0)
        >>> to_datetime(288)
        (4, 0, 0)
    """
    _validate_tick(tick)
    day = tick // TICKS_PER_DAY + 1
    minutes_of_day = (tick % TICKS_PER_DAY) * MINUTES_PER_TICK
    hour = minutes_of_day // 60
    minute = minutes_of_day % 60
    return day, hour, minute


def to_tick(day: int, hour: int, minute: int = 0) -> int:
    """Convert a ``(day, hour, minute)`` calendar instant into an absolute tick.

    This is the exact inverse of :func:`to_datetime`.

    Args:
        day: 1-based day number.
        hour: Hour of the day in 24h format, ``0 <= hour <= 23``.
        minute: Minute within the hour. Must be a multiple of
            ``MINUTES_PER_TICK`` and less than 60.

    Returns:
        The absolute tick index.

    Raises:
        ValueError: If the arguments do not describe a valid tick boundary or
            if the resulting tick falls outside the playable cycle.

    Example:
        >>> to_tick(1, 0, 0)
        0
        >>> to_tick(1, 23, 45)
        95
        >>> to_tick(3, 20, 0)
        272
    """
    if day < 1:
        raise ValueError(f"day must be >= 1, got {day}")
    if not 0 <= hour <= 23:
        raise ValueError(f"hour must be within [0, 23], got {hour}")
    if not 0 <= minute < 60:
        raise ValueError(f"minute must be within [0, 59], got {minute}")
    if minute % MINUTES_PER_TICK != 0:
        raise ValueError(f"minute must be a multiple of {MINUTES_PER_TICK}, got {minute}")

    tick = (day - 1) * TICKS_PER_DAY + (hour * 60 + minute) // MINUTES_PER_TICK
    if tick > TOTAL_TICKS:
        raise ValueError(
            f"day {day} at {hour:02d}:{minute:02d} is beyond the cycle end (tick {TOTAL_TICKS})"
        )
    return tick


def format_clock(tick: int) -> str:
    """Render a tick as a human readable clock label.

    Args:
        tick: Tick index in ``[0, TOTAL_TICKS]``.

    Returns:
        A string of the form ``"Day 1 07:15"``.

    Raises:
        ValueError: If ``tick`` is out of range.

    Example:
        >>> format_clock(0)
        'Day 1 00:00'
        >>> format_clock(29)
        'Day 1 07:15'
    """
    _validate_tick(tick)
    day, hour, minute = to_datetime(tick)
    return f"Day {day} {hour:02d}:{minute:02d}"


def is_past(tick: int, deadline: int) -> bool:
    """Check whether a tick has moved strictly beyond a deadline.

    The comparison is **exclusive** on the deadline tick: at exactly the
    deadline the deadline has *not* been exceeded yet, because the player
    still has that tick available to act. A deadline of ``168`` (Day 2, 16:00)
    is therefore still open at tick ``168`` and is exceeded from tick ``169``
    onwards.

    This matches the canonical test suite in ``PLAN.md`` (section 11.3):
    ``is_past(tick=168, deadline=168) is False``.

    Args:
        tick: Current tick index.
        deadline: Deadline tick index.

    Returns:
        ``True`` when ``tick > deadline``.

    Raises:
        ValueError: If either argument is out of range.
    """
    _validate_tick(tick)
    _validate_tick(deadline)
    return tick > deadline


def advance(tick: int, steps: int = 1) -> int:
    """Move the clock forward by a number of ticks.

    Args:
        tick: Current tick index.
        steps: Number of ticks to advance. Must be a non-negative integer.

    Returns:
        The new tick index.

    Raises:
        ClockOverflowError: If the resulting tick would exceed ``TOTAL_TICKS``.
        ValueError: If ``tick`` is out of range or ``steps`` is negative.

    Example:
        >>> advance(287)
        288
        >>> advance(288)
        Traceback (most recent call last):
            ...
        core.time.ClockOverflowError: cannot advance past the cycle end (tick 288)
    """
    _validate_tick(tick)
    if not isinstance(steps, int) or isinstance(steps, bool):
        raise TypeError(f"steps must be an int, got {type(steps).__name__}")
    if steps < 0:
        raise ValueError(f"steps must be >= 0, got {steps}")

    new_tick = tick + steps
    if new_tick > TOTAL_TICKS:
        raise ClockOverflowError(f"cannot advance past the cycle end (tick {TOTAL_TICKS})")
    return new_tick
