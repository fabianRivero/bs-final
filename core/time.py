"""Deterministic time arithmetic for the Aldermere simulation.

The whole game is driven by a single monotonic integer counter called a *tick*.

* One tick represents 15 minutes of in-game time.
* One day is 96 ticks (24h / 15min).
* The full playable cycle is 5 days, i.e. 480 ticks.

Tick numbering and end-of-cycle convention
------------------------------------------
Ticks are zero-based and start at the beginning of Day 1 at 00:00:

    tick 0   -> Day 1, 00:00
    tick 95  -> Day 1, 23:45   (last slot of Day 1)
    tick 96  -> Day 2, 00:00
    tick 479 -> Day 5, 23:45   (last slot of Day 5)
    tick 480 -> Day 6, 00:00   (the cycle *closing* tick)

The closing tick ``480`` is a valid instant: it is the end of the cycle, and
:meth:`to_datetime` maps it to ``(6, 0, 0)``. It is *not* a slot in which an
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

The cycle length is configurable
--------------------------------
The length of the cycle is **data, not code**: it is the number of days the
playable cycle lasts, and :func:`total_ticks` turns it into the number of
ticks. The default is :data:`DEFAULT_CYCLE_DAYS` (5 days, 480 ticks), and
:data:`CYCLE_DAYS` is the knob that changes it.

Every clock function takes an optional ``cycle_days`` argument, defaulting to
:data:`CYCLE_DAYS`. Passing it explicitly is how a longer cycle is exercised
without touching the module-level default, which keeps the default behaviour
of the whole project unchanged.

The important consequence is that the **daily pattern does not scale with the
cycle**: :data:`TICKS_PER_DAY` stays at 96, so NPC schedules
(:mod:`core.schedule`) and lighting phases (:mod:`core.lighting`) keep working
unchanged when the cycle grows. They normalise the absolute tick with
``tick % TICKS_PER_DAY``, so tick 28 and tick 316 resolve to the same state.

Widening the cycle is therefore a one-line change:

    CYCLE_DAYS = 15          # 15 days, 1440 ticks

Everything else -- the clock arithmetic, the resource system, the endings
evaluation -- follows from that single constant.

All functions in this module are pure and deterministic. Given the same
inputs they always return the same outputs, which is what makes the
"same tick + same decisions => same world" invariant of the project hold.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "CYCLE_DAYS",
    "DEFAULT_CYCLE_DAYS",
    "MINUTES_PER_TICK",
    "TICKS_PER_DAY",
    "TOTAL_TICKS",
    "ClockOverflowError",
    "ClockTime",
    "advance",
    "day_of",
    "format_clock",
    "is_past",
    "tick_of_day",
    "to_datetime",
    "to_tick",
    "total_ticks",
]

#: Number of minutes of in-game time represented by a single tick.
MINUTES_PER_TICK = 15

#: Number of ticks in a full in-game day (24h / 15min).
#:
#: This value never changes with the length of the cycle: the daily pattern
#: (NPC schedules, lighting phases) is expressed in day ticks and repeats
#: every ``TICKS_PER_DAY`` ticks, whatever the cycle lasts.
TICKS_PER_DAY = 96

#: Number of days of the default playable cycle.
#:
#: The playable cycle of Aldermere lasts five days. The value is a named
#: constant so that it can be referenced from the documentation and from the
#: tests without duplicating a literal.
DEFAULT_CYCLE_DAYS = 5

#: Number of days of the playable cycle currently in use.
#:
#: This is **the** knob of the cycle length. Changing it to 15 widens the
#: cycle to 15 days (1440 ticks) without touching the daily pattern of the
#: schedules and the lighting, which is normalised with
#: ``tick % TICKS_PER_DAY``.
CYCLE_DAYS = DEFAULT_CYCLE_DAYS

#: Number of ticks in the full playable cycle (5 days).
#:
#: Kept as a public constant for backwards compatibility: ``from core.time
#: import TOTAL_TICKS`` must keep working. It is derived from
#: :data:`CYCLE_DAYS` and :data:`TICKS_PER_DAY`, never hardcoded.
TOTAL_TICKS = CYCLE_DAYS * TICKS_PER_DAY

#: Number of ticks that fit in a single in-game hour (60 / 15).
TICKS_PER_HOUR = 60 // MINUTES_PER_TICK


class ClockOverflowError(ValueError):
    """Raised when a clock operation would move past the end of the cycle.

    The clock is monotonic and bounded. Advancing past the end of the cycle
    is a programming error rather than a gameplay state, so it raises instead
    of wrapping around silently.
    """


@dataclass(frozen=True)
class ClockTime:
    """An absolute position in the Aldermere timeline.

    Attributes:
        tick: Absolute tick index, ``0 <= tick <= total_ticks()``.
        day: Day number, starting at 1.
        hour: Hour of the day in 24h format, ``0 <= hour <= 23``.
        minute: Minute within the hour, always a multiple of
            ``MINUTES_PER_TICK``.
    """

    tick: int
    day: int
    hour: int
    minute: int


def total_ticks(cycle_days: int = CYCLE_DAYS) -> int:
    """Return the number of ticks of a cycle lasting ``cycle_days`` days.

    The cycle length is expressed in **days**, and this function is the single
    place where a day is turned into ticks. Every bound of the clock is
    derived from it, so a cycle of any length behaves consistently.

    Args:
        cycle_days: Number of days the cycle lasts. Must be at least 1.

    Returns:
        The number of ticks of the cycle: ``cycle_days * TICKS_PER_DAY``.

    Raises:
        TypeError: If ``cycle_days`` is not an integer.
        ValueError: If ``cycle_days`` is smaller than 1.

    Example:
        >>> total_ticks()
        480
        >>> total_ticks(15)
        1440
        >>> total_ticks(1)
        96
    """
    if not isinstance(cycle_days, int) or isinstance(cycle_days, bool):
        raise TypeError(f"cycle_days must be an int, got {type(cycle_days).__name__}")
    if cycle_days < 1:
        raise ValueError(f"cycle_days must be >= 1, got {cycle_days}")
    return cycle_days * TICKS_PER_DAY


def day_of(tick: int, cycle_days: int = CYCLE_DAYS) -> int:
    """Return the 1-based day number a tick belongs to.

    Args:
        tick: Absolute tick index.
        cycle_days: Length of the cycle, in days.

    Returns:
        The day of the tick, starting at 1. The closing tick of the cycle
        belongs to the day *after* the last playable day, exactly like
        :func:`to_datetime`.

    Raises:
        TypeError: If ``tick`` is not an integer.
        ValueError: If ``tick`` is negative or beyond the cycle.

    Example:
        >>> day_of(0)
        1
        >>> day_of(96)
        2
    """
    _validate_tick(tick, cycle_days)
    return tick // TICKS_PER_DAY + 1


def tick_of_day(tick: int, cycle_days: int = CYCLE_DAYS) -> int:
    """Return the position of a tick inside its own day.

    The position is normalised with ``tick % TICKS_PER_DAY``, so it is
    always in ``[0, TICKS_PER_DAY)`` and repeats every day. This is the very
    normalisation the schedules and the lighting use, which is why widening
    the cycle does not change the daily pattern.

    Args:
        tick: Absolute tick index.
        cycle_days: Length of the cycle, in days.

    Returns:
        The tick position inside the day, in ``[0, TICKS_PER_DAY)``.

    Raises:
        TypeError: If ``tick`` is not an integer.
        ValueError: If ``tick`` is negative or beyond the cycle.

    Example:
        >>> tick_of_day(0)
        0
        >>> tick_of_day(28)
        28
        >>> tick_of_day(316)
        28
    """
    _validate_tick(tick)
    return tick % TICKS_PER_DAY


def _validate_tick(tick: int, cycle_days: int = CYCLE_DAYS) -> int:
    """Ensure ``tick`` lies inside the playable cycle.

    Args:
        tick: Tick index to validate.
        cycle_days: Length of the cycle, in days.

    Returns:
        The validated tick.

    Raises:
        TypeError: If ``tick`` is not an integer.
        ValueError: If ``tick`` is negative or greater than the end of the
            cycle.
    """
    if not isinstance(tick, int) or isinstance(tick, bool):
        raise TypeError(f"tick must be an int, got {type(tick).__name__}")
    if tick < 0:
        raise ValueError(f"tick must be >= 0, got {tick}")
    limit = total_ticks(cycle_days)
    if tick > limit:
        raise ValueError(f"tick must be <= {limit}, got {tick}")
    return tick


def to_datetime(tick: int, cycle_days: int = CYCLE_DAYS) -> tuple[int, int, int]:
    """Convert a tick into a ``(day, hour, minute)`` calendar instant.

    The triple is lossless: every tick of the cycle maps to exactly one
    instant, and every instant maps back to exactly one tick.

    Args:
        tick: Tick index in ``[0, total_ticks(cycle_days)]``.
        cycle_days: Length of the cycle, in days.

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
        >>> to_datetime(480)
        (6, 0, 0)
    """
    _validate_tick(tick, cycle_days)
    day = tick // TICKS_PER_DAY + 1
    minutes_of_day = (tick % TICKS_PER_DAY) * MINUTES_PER_TICK
    hour = minutes_of_day // 60
    minute = minutes_of_day % 60
    return day, hour, minute


def to_tick(day: int, hour: int, minute: int = 0, cycle_days: int = CYCLE_DAYS) -> int:
    """Convert a ``(day, hour, minute)`` calendar instant into an absolute tick.

    This is the exact inverse of :func:`to_datetime`.

    Args:
        day: 1-based day number.
        hour: Hour of the day in 24h format, ``0 <= hour <= 23``.
        minute: Minute within the hour. Must be a multiple of
            ``MINUTES_PER_TICK`` and less than 60.
        cycle_days: Length of the cycle, in days.

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
    limit = total_ticks(cycle_days)
    if tick > limit:
        raise ValueError(
            f"day {day} at {hour:02d}:{minute:02d} is beyond the cycle end (tick {limit})"
        )
    return tick


def format_clock(tick: int, cycle_days: int = CYCLE_DAYS) -> str:
    """Render a tick as a human readable clock label.

    Args:
        tick: Tick index in ``[0, total_ticks(cycle_days)]``.
        cycle_days: Length of the cycle, in days.

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
    _validate_tick(tick, cycle_days)
    day, hour, minute = to_datetime(tick, cycle_days)
    return f"Day {day} {hour:02d}:{minute:02d}"


def is_past(tick: int, deadline: int, cycle_days: int = CYCLE_DAYS) -> bool:
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
        cycle_days: Length of the cycle, in days.

    Returns:
        ``True`` when ``tick > deadline``.

    Raises:
        ValueError: If either argument is out of range.
    """
    _validate_tick(tick, cycle_days)
    _validate_tick(deadline, cycle_days)
    return tick > deadline


def advance(tick: int, steps: int = 1, cycle_days: int = CYCLE_DAYS) -> int:
    """Move the clock forward by a number of ticks.

    Args:
        tick: Current tick index.
        steps: Number of ticks to advance. Must be a non-negative integer.
        cycle_days: Length of the cycle, in days.

    Returns:
        The new tick index.

    Raises:
        ClockOverflowError: If the resulting tick would exceed the end of the
            cycle.
        ValueError: If ``tick`` is out of range or ``steps`` is negative.

    Example:
        >>> advance(479)
        480
        >>> advance(480)
        Traceback (most recent call last):
            ...
        core.time.ClockOverflowError: cannot advance past the cycle end (tick 480)
    """
    _validate_tick(tick, cycle_days)
    if not isinstance(steps, int) or isinstance(steps, bool):
        raise TypeError(f"steps must be an int, got {type(steps).__name__}")
    if steps < 0:
        raise ValueError(f"steps must be >= 0, got {steps}")

    new_tick = tick + steps
    limit = total_ticks(cycle_days)
    if new_tick > limit:
        raise ClockOverflowError(f"cannot advance past the cycle end (tick {limit})")
    return new_tick
