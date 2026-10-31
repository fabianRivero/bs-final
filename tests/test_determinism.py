"""Tests proving that the simulation core is deterministic.

The project invariant is: the same tick plus the same decisions always yields
the same world state. Determinism of the clock is the foundation of that
invariant, so it gets its own test module.

Derived state determinism
--------------------------
The clock is only half of the invariant. The *world* is derived from
``(tick, decisions)``, so the same decision sequence must also produce the
same :class:`~core.state.WorldState`, both by value (frozen dataclasses
compare by content) and textually (identical ``repr``).
"""

from __future__ import annotations

from core.state import Decision, derive
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


#: A representative decision sequence used by the determinism tests.
SEQUENCE: tuple[Decision, ...] = (
    Decision(kind="talk", target="NPC_MARTA", tick=28, payload={}),
    Decision(
        kind="report_symptom",
        target="NPC_MARTA",
        tick=29,
        payload={"symptom": "SYM_FEVER"},
    ),
    Decision(kind="move", target="ZONE_PORT", tick=30, payload={}),
    Decision(kind="examine", target="OBJ_LETTER", tick=31, payload={}),
    Decision(
        kind="talk",
        target="NPC_OMAR",
        tick=32,
        payload={"sets_flags": ["heard_symptoms_omar"]},
    ),
)


def test_state_is_pure_function_of_tick_and_decisions() -> None:
    """``derive`` returns the same state for the same inputs."""
    assert derive(tick=137, decisions=()) == derive(tick=137, decisions=())


def test_same_decision_sequence_yields_identical_state() -> None:
    """The same decision sequence yields an identical derived state."""
    first = derive(tick=137, decisions=SEQUENCE)
    second = derive(tick=137, decisions=SEQUENCE)
    assert first == second


def test_same_decision_sequence_yields_identical_repr() -> None:
    """The derived state is reproducible byte for byte."""
    first = derive(tick=137, decisions=SEQUENCE)
    second = derive(tick=137, decisions=SEQUENCE)
    assert repr(first) == repr(second)


def test_same_decision_sequence_yields_identical_flags() -> None:
    """The derived flags are reproducible and independent of the call order."""
    first = derive(tick=137, decisions=SEQUENCE)
    second = derive(tick=137, decisions=SEQUENCE)
    assert first.flags == second.flags
    assert first.flags == frozenset(
        {
            "decided:talk",
            "decided:report_symptom",
            "decided:move",
            "decided:examine",
            "talked:NPC_MARTA",
            "talked:NPC_OMAR",
            "knows:symptom:SYM_FEVER",
            "visited:ZONE_PORT",
            "examined:OBJ_LETTER",
            "heard_symptoms_omar",
        }
    )


def test_derive_is_idempotent_over_the_cycle() -> None:
    """Deriving from a derived state returns an equal state."""
    for tick in range(TOTAL_TICKS + 1):
        once = derive(tick=tick, decisions=SEQUENCE)
        twice = derive(tick=tick, decisions=once.decisions)
        assert once == twice
        assert repr(once) == repr(twice)


def test_different_ticks_yield_different_states() -> None:
    """The tick is part of the identity of the derived state."""
    assert derive(tick=10, decisions=SEQUENCE) != derive(tick=11, decisions=SEQUENCE)
