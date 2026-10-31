"""Tests for the derived world state.

The derived state is the heart of the project invariant: the world is never
stored, it is recomputed from ``(tick, decisions)``. The tests below pin down
that ``derive`` is pure, deterministic and free of side effects, and that the
flag vocabulary follows from the decisions alone.
"""

from __future__ import annotations

import copy

import pytest

from core.state import Decision, WorldState, derive
from core.time import TOTAL_TICKS

TALK = Decision(kind="talk", target="NPC_MARTA", tick=28, payload={})
REPORT = Decision(
    kind="report_symptom",
    target="NPC_MARTA",
    tick=29,
    payload={"symptom": "SYM_FEVER"},
)
MOVE = Decision(kind="move", target="ZONE_PORT", tick=30, payload={})
EXAMINE = Decision(kind="examine", target="OBJ_LETTER", tick=31, payload={})


def test_derive_returns_a_world_state() -> None:
    """``derive`` always returns a world state, even with no decisions."""
    state = derive(0, ())
    assert isinstance(state, WorldState)
    assert state.tick == 0
    assert state.decisions == ()
    assert state.flags == frozenset()


def test_derive_exposes_the_calendar_triple() -> None:
    """The derived state carries day, hour and minute of the tick."""
    state = derive(28, ())
    assert (state.day, state.hour, state.minute) == (1, 7, 0)
    state = derive(288, ())
    assert (state.day, state.hour, state.minute) == (4, 0, 0)


def test_derive_is_deterministic() -> None:
    """The same tick and decisions always produce an equal state."""
    decisions = (TALK, REPORT, MOVE)
    first = derive(42, decisions)
    second = derive(42, decisions)
    assert first == second
    assert repr(first) == repr(second)


def test_derive_is_idempotent() -> None:
    """Deriving twice from the same inputs changes nothing."""
    decisions = (TALK,)
    once = derive(10, decisions)
    twice = derive(10, once.decisions)
    assert once == twice


def test_derive_does_not_mutate_its_inputs() -> None:
    """The decisions passed to ``derive`` are left untouched."""
    decisions = [TALK, REPORT]
    snapshot = copy.deepcopy(decisions)
    state = derive(5, decisions)
    assert decisions == snapshot
    assert state.decisions is not decisions
    assert isinstance(state.decisions, tuple)


def test_derive_does_not_mutate_the_payload_of_a_decision() -> None:
    """The payload of a decision is copied, not shared, by the derived state."""
    payload = {"symptom": "SYM_FEVER", "sets_flags": ["heard_symptoms"]}
    decision = Decision(kind="report_symptom", target="NPC_MARTA", tick=1, payload=payload)
    state = derive(2, (decision,))
    payload["symptom"] = "SYM_MUTATED"
    assert state.symptoms_known() == ("SYM_FEVER",)


def test_derive_derives_the_decided_flag() -> None:
    """Any decision raises the generic ``decided`` flag of its kind."""
    state = derive(28, (TALK,))
    assert state.has_flag("decided:talk")
    assert not state.has_flag("decided:examine")


def test_derive_derives_the_talked_flag() -> None:
    """Talking to an NPC raises ``talked:<npc>``."""
    state = derive(28, (TALK,))
    assert state.has_flag("talked:NPC_MARTA")
    assert not state.has_flag("talked:NPC_OMAR")


def test_derive_derives_the_examined_flag() -> None:
    """Examining an object raises ``examined:<object>``."""
    state = derive(31, (EXAMINE,))
    assert state.has_flag("examined:OBJ_LETTER")


def test_derive_derives_the_visited_flag() -> None:
    """Moving into a zone raises ``visited:<zone>``."""
    state = derive(30, (MOVE,))
    assert state.has_flag("visited:ZONE_PORT")


def test_derive_derives_the_known_symptom_flag() -> None:
    """Reporting a symptom raises ``knows:symptom:<symptom>``."""
    state = derive(29, (REPORT,))
    assert state.has_flag("knows:symptom:SYM_FEVER")
    assert not state.has_flag("knows:symptom:SYM_RASH")


def test_derive_derives_explicit_flags_from_the_payload() -> None:
    """A decision may raise explicit flags through ``sets_flags``."""
    decision = Decision(
        kind="talk",
        target="NPC_MARTA",
        tick=28,
        payload={"sets_flags": ["heard_symptoms_marta"]},
    )
    state = derive(28, (decision,))
    assert state.has_flag("heard_symptoms_marta")


def test_derive_accepts_a_single_explicit_flag_as_a_string() -> None:
    """``sets_flags`` may be a single string instead of a list."""
    decision = Decision(
        kind="examine",
        target="OBJ_LETTER",
        tick=31,
        payload={"sets_flags": "letter_read"},
    )
    state = derive(31, (decision,))
    assert state.has_flag("letter_read")


def test_decision_sets_flag_reports_explicit_flags() -> None:
    """``Decision.sets_flag`` inspects the explicit flag payload."""
    decision = Decision(kind="talk", target="NPC_MARTA", tick=1, payload={"sets_flags": ["a", "b"]})
    assert decision.sets_flag("a") is True
    assert decision.sets_flag("b") is True
    assert decision.sets_flag("c") is False
    assert TALK.sets_flag("a") is False


def test_has_flag_reports_unknown_flags() -> None:
    """Unknown flags are simply absent."""
    state = derive(0, ())
    assert state.has_flag("nothing") is False


def test_decisions_of_filters_by_kind() -> None:
    """``decisions_of`` returns the decisions of one kind, in order."""
    decisions = (TALK, REPORT, EXAMINE, Decision(kind="talk", target="NPC_OMAR", tick=32))
    state = derive(32, decisions)
    talks = state.decisions_of("talk")
    assert len(talks) == 2
    assert [decision.target for decision in talks] == ["NPC_MARTA", "NPC_OMAR"]
    assert state.decisions_of("move") == ()


def test_symptoms_known_lists_the_reported_symptoms() -> None:
    """``symptoms_known`` returns the sorted symptom ids without duplicates."""
    other = Decision(
        kind="report_symptom", target="NPC_OMAR", tick=33, payload={"symptom": "SYM_RASH"}
    )
    state = derive(33, (REPORT, other, REPORT))
    assert state.symptoms_known() == ("SYM_FEVER", "SYM_RASH")


def test_symptoms_known_ignores_decisions_without_symptom() -> None:
    """A report without a symptom id contributes nothing."""
    broken = Decision(kind="report_symptom", target="NPC_OMAR", tick=34, payload={})
    state = derive(34, (broken,))
    assert state.symptoms_known() == ()
    assert not state.has_flag("knows:symptom:None")


def test_symptoms_known_is_empty_without_reports() -> None:
    """Without reported symptoms the player knows nothing."""
    state = derive(0, (TALK, MOVE))
    assert state.symptoms_known() == ()


def test_derive_keeps_the_decisions_in_order() -> None:
    """The derived state preserves the chronological order of the decisions."""
    decisions = (TALK, REPORT, EXAMINE)
    state = derive(35, decisions)
    assert state.decisions == decisions
    assert [decision.tick for decision in state.decisions] == [28, 29, 31]


def test_world_state_is_immutable() -> None:
    """The derived state cannot be mutated after creation."""
    state = derive(0, ())
    with pytest.raises(Exception):  # noqa: B017 - frozen dataclass error type
        state.tick = 5  # type: ignore[misc]


def test_derive_rejects_out_of_range_ticks() -> None:
    """Ticks outside the playable cycle are rejected."""
    with pytest.raises(ValueError, match="tick must be >= 0"):
        derive(-1, ())
    with pytest.raises(ValueError, match="tick must be <= 288"):
        derive(TOTAL_TICKS + 1, ())


def test_derive_rejects_non_integer_ticks() -> None:
    """A non-integer tick is a programming error."""
    with pytest.raises(TypeError, match="tick must be an int"):
        derive("0", ())  # type: ignore[arg-type]


def test_derive_rejects_malformed_decisions() -> None:
    """Only ``Decision`` instances can be part of the derivation."""
    with pytest.raises(TypeError, match="expected a Decision"):
        derive(0, ({"kind": "talk"},))  # type: ignore[arg-type]


def test_derive_accepts_any_sequence_of_decisions() -> None:
    """Lists and tuples of decisions behave identically."""
    assert derive(3, [TALK]) == derive(3, (TALK,))


def test_decision_rejects_a_non_mapping_payload() -> None:
    """The payload of a decision must be a mapping."""
    with pytest.raises(TypeError, match="payload must be a dict"):
        Decision(kind="talk", target="NPC_MARTA", tick=1, payload=["a"])  # type: ignore[arg-type]


def test_decision_payload_is_copied_on_construction() -> None:
    """The payload of a decision is copied, so it cannot change afterwards."""
    payload = {"symptom": "SYM_FEVER"}
    decision = Decision(kind="report_symptom", target="NPC_MARTA", tick=1, payload=payload)
    payload["symptom"] = "SYM_MUTATED"
    assert decision.payload["symptom"] == "SYM_FEVER"


def test_decision_payload_defaults_to_an_empty_mapping() -> None:
    """A decision without payload carries an empty mapping."""
    decision = Decision(kind="talk", target="NPC_MARTA", tick=1)
    assert decision.payload == {}
    assert decision.sets_flag("anything") is False


def test_decision_sets_flag_ignores_an_unusable_payload() -> None:
    """A ``sets_flags`` payload that is not a string or a collection is ignored."""
    decision = Decision(kind="talk", target="NPC_MARTA", tick=1, payload={"sets_flags": 42})
    assert decision.sets_flag("anything") is False


def test_decision_sets_flag_accepts_a_tuple_of_flags() -> None:
    """A ``sets_flags`` payload may be any collection of names."""
    decision = Decision(kind="talk", target="NPC_MARTA", tick=1, payload={"sets_flags": ("a", "b")})
    assert decision.sets_flag("a") is True
    assert decision.sets_flag("b") is True
    assert decision.sets_flag("c") is False


def test_derive_ignores_a_report_without_symptom() -> None:
    """A report without a symptom id raises no symptom flag."""
    broken = Decision(kind="report_symptom", target="NPC_MARTA", tick=1, payload={})
    state = derive(1, (broken,))
    assert state.has_flag("decided:report_symptom")
    assert state.symptoms_known() == ()


def test_derive_ignores_a_talk_without_target() -> None:
    """A talk without a target raises no ``talked`` flag."""
    untargeted = Decision(kind="talk", target="", tick=1, payload={})
    state = derive(1, (untargeted,))
    assert state.has_flag("decided:talk")
    assert not state.has_flag("talked:")


def test_derive_ignores_an_examine_without_target() -> None:
    """An examine without a target raises no ``examined`` flag."""
    untargeted = Decision(kind="examine", target="", tick=1, payload={})
    state = derive(1, (untargeted,))
    assert state.has_flag("decided:examine")
    assert not state.has_flag("examined:")


def test_derive_ignores_a_move_without_target() -> None:
    """A move without a target raises no ``visited`` flag."""
    untargeted = Decision(kind="move", target="", tick=1, payload={})
    state = derive(1, (untargeted,))
    assert state.has_flag("decided:move")
    assert not state.has_flag("visited:")
