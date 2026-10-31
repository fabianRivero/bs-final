"""Day/night lighting derived from the tick.

The town must look different at 03:00, at 07:00, at 13:00 and at 21:00. The
light is therefore a **pure function of the tick**, exactly like everything
else in the simulation core: Python decides the phase, the tint colour and the
overlay opacity, and Godot only applies them.

Strategy
--------
The project uses *tile palettes plus a tint overlay* (``PLAN.md`` section 7.2):
a full ``ColorRect`` is drawn on top of the world and tinted with the phase
colour. Opacity ``0.0`` means "no overlay at all" (broad daylight) and
opacity ``1.0`` means "fully blacked out". This module owns the data and the
derivation; it never picks art assets and never touches the engine.

The phase table
---------------
Seven phases cover the 96 ticks of a day **without gaps and without
overlaps**. Every tick belongs to exactly one phase. The canonical table is
the one declared in ``PLAN.md`` (section 7.3):

    phase id     ticks      clock range      overlay rgb        opacity
    -----------  ---------  ---------------  ----------------  --------
    dawn_early   0 - 17    00:00 - 04:15    (40, 50, 90)      0.55
    dawn         18 - 25   04:30 - 06:15    (255, 170, 110)   0.25
    morning      26 - 37   06:30 - 09:15    (255, 214, 170)   0.08
    day          38 - 65   09:30 - 16:15    (255, 255, 255)   0.00
    afternoon    66 - 75   16:30 - 18:45    (255, 226, 180)   0.06
    dusk         76 - 81   19:00 - 20:15    (255, 150, 110)   0.28
    night        82 - 95   20:30 - 23:45    (40, 50, 90)      0.55

The ``start_tick`` of a phase is inclusive and its ``end_tick`` is exclusive,
which is the same convention used by the NPC schedules in
:mod:`core.schedule`.

Opacity interpolation
----------------------
Jumping from one phase to the next would make the tint pop. The engine
therefore interpolates linearly over a transition window, and the same
interpolation is exported to Godot as a table. :func:`lerp_opacity` is the
pure function that computes it, so Python and Godot can be compared exactly
by ``tools/parity_check.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.time import TICKS_PER_DAY

__all__ = [
    "LIGHTING_TABLE",
    "LightState",
    "LightingPhase",
    "lerp_opacity",
    "light_state_at",
    "phase_at",
]


@dataclass(frozen=True)
class LightingPhase:
    """One phase of the daily light cycle.

    Attributes:
        id: Stable identifier of the phase, e.g. ``"dawn"``.
        start_tick: First tick of the phase *within the day*, inclusive.
            Always in ``[0, TICKS_PER_DAY)``.
        end_tick: Tick at which the phase ends, exclusive. May equal
            ``TICKS_PER_DAY`` for the last phase of the day.
        rgb: Tint colour applied to the overlay, one value per channel in
            ``[0, 255]``.
        opacity: Opacity of the overlay, in ``[0.0, 1.0]``. ``0.0`` means no
            overlay at all.
    """

    id: str
    start_tick: int
    end_tick: int
    rgb: tuple[int, int, int]
    opacity: float


@dataclass(frozen=True)
class LightState:
    """The lighting of the world at a given tick.

    Attributes:
        phase_id: Identifier of the phase that contains the tick.
        rgb: Tint colour of the overlay.
        opacity: Opacity of the overlay, in ``[0.0, 1.0]``.
        is_day: ``True`` when the phase counts as daylight, i.e. when the
            overlay is negligible. Used by the HUD to pick a light icon.
    """

    phase_id: str
    rgb: tuple[int, int, int]
    opacity: float
    is_day: bool


#: The canonical seven-phase lighting table.
#:
#: The phases are ordered by ``start_tick`` and cover ``[0, TICKS_PER_DAY)``
#: without gaps or overlaps. The invariants are asserted by the test suite.
LIGHTING_TABLE: tuple[LightingPhase, ...] = (
    LightingPhase(id="dawn_early", start_tick=0, end_tick=18, rgb=(40, 50, 90), opacity=0.55),
    LightingPhase(id="dawn", start_tick=18, end_tick=26, rgb=(255, 170, 110), opacity=0.25),
    LightingPhase(id="morning", start_tick=26, end_tick=38, rgb=(255, 214, 170), opacity=0.08),
    LightingPhase(id="day", start_tick=38, end_tick=66, rgb=(255, 255, 255), opacity=0.00),
    LightingPhase(id="afternoon", start_tick=66, end_tick=76, rgb=(255, 226, 180), opacity=0.06),
    LightingPhase(id="dusk", start_tick=76, end_tick=82, rgb=(255, 150, 110), opacity=0.28),
    LightingPhase(id="night", start_tick=82, end_tick=96, rgb=(40, 50, 90), opacity=0.55),
)

#: Phases whose overlay is negligible enough to count as plain daylight.
_DAY_PHASE_IDS = frozenset({"day"})


def _normalise_tick(tick: int) -> int:
    """Reduce a tick to its position inside the current day.

    Args:
        tick: Absolute tick index.

    Returns:
        The tick position inside the day, in ``[0, TICKS_PER_DAY)``.

    Raises:
        TypeError: If ``tick`` is not an integer.
        ValueError: If ``tick`` is negative.
    """
    if not isinstance(tick, int) or isinstance(tick, bool):
        raise TypeError(f"tick must be an int, got {type(tick).__name__}")
    if tick < 0:
        raise ValueError(f"tick must be >= 0, got {tick}")
    return tick % TICKS_PER_DAY


def phase_at(tick: int) -> LightingPhase:
    """Return the lighting phase that contains a tick.

    The phase pattern repeats every day, so the tick is normalised with
    ``tick % TICKS_PER_DAY`` before the lookup: tick 28 and tick 124 belong
    to the same phase.

    Args:
        tick: Absolute tick index.

    Returns:
        The phase whose half-open range ``[start_tick, end_tick)`` contains
        the normalised tick.

    Raises:
        TypeError: If ``tick`` is not an integer.
        ValueError: If ``tick`` is negative.

    Example:
        >>> phase_at(0).id
        'dawn_early'
        >>> phase_at(95).id
        'night'
    """
    position = _normalise_tick(tick)
    for phase in LIGHTING_TABLE:
        if phase.start_tick <= position < phase.end_tick:
            return phase
    # Unreachable while the table covers the whole day; kept as a guard
    # against a corrupted table, because a missing phase must never be
    # silently treated as daylight.
    raise ValueError(f"no lighting phase covers tick position {position}")


def light_state_at(tick: int) -> LightState:
    """Derive the lighting of the world at a tick.

    Args:
        tick: Absolute tick index.

    Returns:
        The light state of the tick: phase identifier, tint colour, overlay
        opacity and whether the phase counts as daylight.

    Raises:
        TypeError: If ``tick`` is not an integer.
        ValueError: If ``tick`` is negative.

    Example:
        >>> light_state_at(38).phase_id
        'day'
        >>> light_state_at(38).opacity
        0.0
    """
    phase = phase_at(tick)
    return LightState(
        phase_id=phase.id,
        rgb=phase.rgb,
        opacity=phase.opacity,
        is_day=phase.id in _DAY_PHASE_IDS,
    )


def lerp_opacity(prev: float, next: float, t: float) -> float:
    """Interpolate linearly between two overlay opacities.

    This is the transition used when the clock crosses a phase boundary: the
    engine blends the previous opacity towards the next one over a short
    window. The same function is exported to Godot so that both sides compute
    bit-identical values.

    Args:
        prev: Opacity at the beginning of the transition.
        next: Opacity at the end of the transition.
        t: Progress of the transition, in ``[0.0, 1.0]``.

    Returns:
        The interpolated opacity, clamped to ``[0.0, 1.0]``.

    Raises:
        TypeError: If any argument is not a number.
        ValueError: If ``t`` is outside ``[0.0, 1.0]``.

    Example:
        >>> lerp_opacity(0.55, 0.0, 0.0)
        0.55
        >>> lerp_opacity(0.55, 0.0, 1.0)
        0.0
    """
    for name, value in (("prev", prev), ("next", next), ("t", t)):
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise TypeError(f"{name} must be a number, got {type(value).__name__}")
    if not 0.0 <= t <= 1.0:
        raise ValueError(f"t must be within [0.0, 1.0], got {t}")

    blended = prev + (next - prev) * t
    return min(1.0, max(0.0, blended))
