"""Tests for the day/night lighting.

The lighting is a pure function of the tick. The tests below prove that the
seven phases cover the 96 ticks of a day without gaps and without overlaps,
that the values stay inside their legal ranges and that the opacity
interpolation is monotonic and pure.
"""

from __future__ import annotations

import itertools

import pytest

from core.lighting import (
    LIGHTING_TABLE,
    LightingPhase,
    LightState,
    lerp_opacity,
    light_state_at,
    phase_at,
)
from core.time import TICKS_PER_DAY, TOTAL_TICKS

#: The canonical phase boundaries, taken from PLAN.md section 7.3.
EXPECTED_PHASES: tuple[tuple[str, int, int], ...] = (
    ("dawn_early", 0, 18),
    ("dawn", 18, 26),
    ("morning", 26, 38),
    ("day", 38, 66),
    ("afternoon", 66, 76),
    ("dusk", 76, 82),
    ("night", 82, 96),
)


def test_there_are_seven_phases() -> None:
    """The lighting table declares exactly seven phases."""
    assert len(LIGHTING_TABLE) == 7
    assert len(EXPECTED_PHASES) == 7


def test_phase_boundaries_match_the_plan() -> None:
    """Each phase covers the range declared in the plan."""
    for phase, (expected_id, expected_start, expected_end) in zip(
        LIGHTING_TABLE, EXPECTED_PHASES, strict=True
    ):
        assert phase.id == expected_id
        assert phase.start_tick == expected_start
        assert phase.end_tick == expected_end


def test_phases_cover_the_whole_day_without_gaps() -> None:
    """The phases start at tick 0 and chain without gaps."""
    assert LIGHTING_TABLE[0].start_tick == 0
    for previous, following in itertools.pairwise(LIGHTING_TABLE):
        assert previous.end_tick == following.start_tick


def test_phases_cover_the_whole_day_without_overlaps() -> None:
    """No two phases cover the same tick."""
    for previous, following in itertools.pairwise(LIGHTING_TABLE):
        assert previous.end_tick <= following.start_tick


def test_phases_end_at_the_end_of_the_day() -> None:
    """The last phase ends exactly at the end of the day."""
    assert LIGHTING_TABLE[-1].end_tick == TICKS_PER_DAY


@pytest.mark.parametrize("tick", range(TICKS_PER_DAY))
def test_every_tick_belongs_to_exactly_one_phase(tick: int) -> None:
    """Each tick of the day is covered by exactly one phase."""
    hits = [phase for phase in LIGHTING_TABLE if phase.start_tick <= tick < phase.end_tick]
    assert len(hits) == 1


@pytest.mark.parametrize(
    ("tick", "expected_phase"),
    [
        (0, "dawn_early"),
        (17, "dawn_early"),
        (18, "dawn"),
        (25, "dawn"),
        (26, "morning"),
        (37, "morning"),
        (38, "day"),
        (65, "day"),
        (66, "afternoon"),
        (75, "afternoon"),
        (76, "dusk"),
        (81, "dusk"),
        (82, "night"),
        (95, "night"),
    ],
)
def test_phase_boundaries(tick: int, expected_phase: str) -> None:
    """The phase boundaries are inclusive at the start and exclusive at the end."""
    assert phase_at(tick).id == expected_phase


@pytest.mark.parametrize("tick", range(TICKS_PER_DAY))
def test_light_values_are_in_range(tick: int) -> None:
    """The opacity stays in ``[0, 1]`` and every colour channel in ``[0, 255]``."""
    state = light_state_at(tick)
    assert isinstance(state, LightState)
    assert 0.0 <= state.opacity <= 1.0
    assert all(0 <= channel <= 255 for channel in state.rgb)
    assert len(state.rgb) == 3


@pytest.mark.parametrize("tick", range(TOTAL_TICKS + 1))
def test_light_is_deterministic(tick: int) -> None:
    """The lighting of a tick never changes."""
    assert light_state_at(tick) == light_state_at(tick)
    assert repr(light_state_at(tick)) == repr(light_state_at(tick))


@pytest.mark.parametrize("tick", range(TICKS_PER_DAY))
def test_phase_repeats_every_day(tick: int) -> None:
    """The daily light pattern repeats on every day of the cycle."""
    assert phase_at(tick) == phase_at(tick + TICKS_PER_DAY)
    assert phase_at(tick) == phase_at(tick + 2 * TICKS_PER_DAY)


def test_day_phase_has_no_overlay() -> None:
    """Broad daylight applies no tint at all."""
    state = light_state_at(38)
    assert state.phase_id == "day"
    assert state.opacity == 0.0
    assert state.is_day is True


def test_night_phase_is_darkest() -> None:
    """The night phases carry the strongest overlay."""
    assert light_state_at(0).opacity == 0.55
    assert light_state_at(95).opacity == 0.55
    assert light_state_at(0).is_day is False
    assert light_state_at(95).is_day is False


def test_dawn_and_dusk_are_warm_transitions() -> None:
    """The dawn and dusk tints are warm and brighter than the night tint."""
    dawn = light_state_at(18)
    dusk = light_state_at(76)
    night = light_state_at(0)
    assert dawn.rgb[0] > dawn.rgb[2]
    assert dusk.rgb[0] > dusk.rgb[2]
    assert night.rgb[2] > night.rgb[0]
    assert 0.0 < dawn.opacity < night.opacity
    assert 0.0 < dusk.opacity < night.opacity


def test_phase_at_rejects_invalid_ticks() -> None:
    """A negative tick is a programming error."""
    with pytest.raises(ValueError, match="tick must be >= 0"):
        phase_at(-1)
    with pytest.raises(TypeError, match="tick must be an int"):
        phase_at(1.5)  # type: ignore[arg-type]


def test_light_state_at_rejects_invalid_ticks() -> None:
    """A negative tick is a programming error."""
    with pytest.raises(ValueError, match="tick must be >= 0"):
        light_state_at(-1)


def test_lerp_opacity_at_the_bounds_returns_the_endpoints() -> None:
    """The interpolation returns the endpoints at ``t`` 0 and 1."""
    assert lerp_opacity(0.55, 0.0, 0.0) == 0.55
    assert lerp_opacity(0.55, 0.0, 1.0) == 0.0


def test_lerp_opacity_is_linear() -> None:
    """The interpolation is linear in ``t``."""
    assert lerp_opacity(0.0, 1.0, 0.5) == pytest.approx(0.5)
    assert lerp_opacity(0.0, 0.4, 0.25) == pytest.approx(0.1)
    assert lerp_opacity(0.4, 0.0, 0.25) == pytest.approx(0.3)


def test_lerp_opacity_is_monotonic() -> None:
    """The interpolated opacity never decreases as ``t`` grows."""
    values = [lerp_opacity(0.55, 0.0, step / 10) for step in range(11)]
    assert values == sorted(values, reverse=True)


def test_lerp_opacity_is_pure() -> None:
    """The same arguments always produce the same value."""
    assert lerp_opacity(0.3, 0.7, 0.42) == lerp_opacity(0.3, 0.7, 0.42)


def test_lerp_opacity_clamps_to_the_legal_range() -> None:
    """The result never leaves ``[0.0, 1.0]``."""
    assert lerp_opacity(-1.0, 1.0, 0.5) == 0.0
    assert lerp_opacity(1.0, -1.0, 0.5) == 0.0


def test_lerp_opacity_rejects_invalid_progress() -> None:
    """``t`` outside ``[0, 1]`` is a programming error."""
    with pytest.raises(ValueError, match=r"t must be within \[0.0, 1.0\]"):
        lerp_opacity(0.0, 1.0, 1.5)
    with pytest.raises(ValueError, match=r"t must be within \[0.0, 1.0\]"):
        lerp_opacity(0.0, 1.0, -0.1)


def test_lerp_opacity_rejects_non_numeric_arguments() -> None:
    """Non-numeric arguments are a programming error."""
    with pytest.raises(TypeError, match="prev must be a number"):
        lerp_opacity("0.0", 1.0, 0.5)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="next must be a number"):
        lerp_opacity(0.0, None, 0.5)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="t must be a number"):
        lerp_opacity(0.0, 1.0, True)  # type: ignore[arg-type]


def test_lighting_phase_is_immutable() -> None:
    """A phase cannot be mutated after creation."""
    phase = LightingPhase(id="x", start_tick=0, end_tick=1, rgb=(0, 0, 0), opacity=0.0)
    with pytest.raises(Exception):  # noqa: B017 - frozen dataclass error type
        phase.opacity = 1.0  # type: ignore[misc]


def test_light_state_is_immutable() -> None:
    """A light state cannot be mutated after creation."""
    state = light_state_at(0)
    with pytest.raises(Exception):  # noqa: B017 - frozen dataclass error type
        state.opacity = 0.0  # type: ignore[misc]


def test_transition_between_phases_is_smooth() -> None:
    """Crossing a phase boundary produces intermediate opacities."""
    previous = light_state_at(17).opacity
    following = light_state_at(18).opacity
    assert previous > following
    middle = lerp_opacity(previous, following, 0.5)
    assert following < middle < previous


def test_light_state_at_rejects_non_integer_ticks() -> None:
    """A non-integer tick is a programming error."""
    with pytest.raises(TypeError, match="tick must be an int"):
        light_state_at(1.5)  # type: ignore[arg-type]


def test_light_state_at_reports_the_phase_opacity() -> None:
    """The opacity of the state is the opacity of its phase."""
    for phase in LIGHTING_TABLE:
        state = light_state_at(phase.start_tick)
        assert state.phase_id == phase.id
        assert state.opacity == phase.opacity
        assert state.rgb == phase.rgb


def test_phase_at_refuses_a_table_with_a_hole(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A corrupted table must fail loudly instead of pretending it is daylight."""
    broken = (LightingPhase(id="night", start_tick=0, end_tick=10, rgb=(0, 0, 0), opacity=0.5),)
    monkeypatch.setattr("core.lighting.LIGHTING_TABLE", broken)
    with pytest.raises(ValueError, match="no lighting phase covers"):
        phase_at(50)
