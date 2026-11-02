"""Tests for the derived world state.

The derived state is the heart of the project invariant: the world is never
stored, it is recomputed from ``(tick, decisions, resources)``. The tests
below pin down that ``derive`` is pure, deterministic and free of side
effects, and that the flag vocabulary follows from the decisions alone.

The tests of the last section pin down the fate of the **testimonies**: a
testimony the player already obtained is kept for ever, and only the
opportunity to hear it again is lost when the villager dies.
"""

from __future__ import annotations

import copy

import pytest

from core.resources import ResourceSpec, consume, empty_state, initial_state
from core.schedule import Npc, ScheduleEntry
from core.state import (
    Decision,
    WorldState,
    available_dialogues,
    derive,
    lost_testimonies,
)
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


def test_decision_sets_flag_accepts_a_single_matching_flag() -> None:
    """A ``sets_flags`` payload may be a single flag name."""
    decision = Decision(kind="talk", target="NPC_MARTA", tick=1, payload={"sets_flags": "heard"})
    assert decision.sets_flag("heard") is True
    assert decision.sets_flag("other") is False


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
    with pytest.raises(ValueError, match=rf"tick must be <= {TOTAL_TICKS}"):
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


# ----------------------------------------------------------------------
# Resources
# ----------------------------------------------------------------------


FOOD = ResourceSpec(id="RES_FOOD", label="Food", initial=3, per_action=1, critical_at=1)


def test_derive_without_resources_uses_a_neutral_state() -> None:
    """A derivation without provisions carries an empty state."""
    state = derive(0, ())
    assert dict(state.resources.amounts) == {}


def test_derive_carries_the_resources_it_receives() -> None:
    """The provisions are carried into the snapshot unchanged."""
    resources = initial_state([FOOD])
    state = derive(10, (), resources)
    assert state.resources == resources
    assert state.resources.amount("RES_FOOD") == 3


def test_derive_does_not_consume_the_resources() -> None:
    """The derivation never spends the provisions it receives."""
    resources = initial_state([FOOD])
    state = derive(10, (TALK, REPORT), resources)

    assert state.resources.amount("RES_FOOD") == 3
    assert resources.amount("RES_FOOD") == 3


def test_derive_is_deterministic_with_resources() -> None:
    """The same three inputs always produce an equal state."""
    resources = initial_state([FOOD])
    first = derive(42, (TALK, REPORT), resources)
    second = derive(42, (TALK, REPORT), resources)
    assert first == second
    assert repr(first) == repr(second)


def test_derive_with_different_resources_yields_different_states() -> None:
    """The provisions are part of the identity of the derived state."""
    full = initial_state([FOOD])
    empty = empty_state()
    assert derive(10, (), full) != derive(10, (), empty)


def test_the_flags_do_not_depend_on_the_resources() -> None:
    """The provisions raise no flag and change no flag."""
    full = initial_state([FOOD])
    empty = empty_state()
    assert derive(10, (TALK, REPORT), full).flags == derive(10, (TALK, REPORT), empty).flags


def test_the_flags_do_not_depend_on_the_tick() -> None:
    """The flag vocabulary still depends on the decisions alone."""
    resources = initial_state([FOOD])
    decisions = (TALK, REPORT, MOVE, EXAMINE)
    flags = derive(0, decisions, resources).flags
    for tick in (1, 96, 288, TOTAL_TICKS):
        assert derive(tick, decisions, resources).flags == flags


def test_the_flags_do_not_depend_on_the_resources_across_the_cycle() -> None:
    """Depleting the stores does not change the story the flags tell."""
    decisions = (TALK, REPORT)
    full = initial_state([FOOD])
    spent = consume(full, [FOOD], actions=3)

    for tick in range(0, TOTAL_TICKS + 1, 47):
        assert derive(tick, decisions, full).flags == derive(tick, decisions, spent).flags


def test_derive_accepts_a_resource_state_as_a_keyword() -> None:
    """The resources can be passed by keyword."""
    resources = initial_state([FOOD])
    assert derive(0, (), resources=resources).resources == resources


def test_the_world_state_carries_the_resources_by_default() -> None:
    """A world state built by hand defaults to a neutral resource state."""
    state = WorldState(
        tick=0,
        day=1,
        hour=0,
        minute=0,
        decisions=(),
        flags=frozenset(),
    )
    assert dict(state.resources.amounts) == {}


# ----------------------------------------------------------------------
# Testimonies and the death of their witness
# ----------------------------------------------------------------------

#: Tick at which the villager of the testimony tests dies.
DEATH_TICK = 192


def _npc(npc_id: str, deceased_at_tick: int | None = None) -> Npc:
    """Build an NPC with a full-day schedule.

    Args:
        npc_id: Id of the NPC.
        deceased_at_tick: Tick of the death, or ``None`` for a living NPC.

    Returns:
        The NPC with its schedule.
    """
    return Npc(
        id=npc_id,
        name=npc_id,
        schedule=(
            ScheduleEntry(
                start_tick=0,
                end_tick=96,
                zone="ZONE_PORT",
                tile=(1, 1),
                activity="working",
                interactable=True,
            ),
        ),
        deceased_at_tick=deceased_at_tick,
        death_cause="plague_fever" if deceased_at_tick is not None else "",
    )


DEAD_NPC = _npc("NPC_DEAD", DEATH_TICK)
LIVING_NPC = _npc("NPC_ALIVE")
NPCS = (DEAD_NPC, LIVING_NPC)


def test_a_testimony_obtained_before_the_death_is_kept() -> None:
    """What the player heard before the death stays known for ever.

    The knowledge lives in the flags of the world, and the death of the
    witness cannot take it away: the player already knows it.
    """
    talk = Decision(kind="talk", target="NPC_DEAD", tick=28, payload={})
    state = derive(DEATH_TICK, (talk,))
    assert state.has_flag("talked:NPC_DEAD")


def test_a_testimony_obtained_before_the_death_survives_the_death() -> None:
    """Deriving the state after the death still carries the testimony."""
    talk = Decision(kind="talk", target="NPC_DEAD", tick=28, payload={})
    before = derive(DEATH_TICK - 1, (talk,))
    after = derive(TOTAL_TICKS, (talk,))
    assert before.has_flag("talked:NPC_DEAD")
    assert after.has_flag("talked:NPC_DEAD")
    assert after.flags == before.flags


def test_the_death_of_an_npc_does_not_change_the_flags() -> None:
    """The death is a fact of the world, not a decision: it raises no flag."""
    talk = Decision(kind="talk", target="NPC_DEAD", tick=28, payload={})
    assert derive(DEATH_TICK - 1, (talk,)).flags == derive(TOTAL_TICKS, (talk,)).flags


def test_lost_testimonies_reports_the_villager_never_talked_to() -> None:
    """The dead villager the player never spoke to is a lost testimony."""
    state = derive(DEATH_TICK, ())
    assert lost_testimonies(state, NPCS, DEATH_TICK) == ("NPC_DEAD",)


def test_lost_testimonies_excludes_a_villager_already_talked_to() -> None:
    """A testimony already obtained is not lost when the witness dies."""
    talk = Decision(kind="talk", target="NPC_DEAD", tick=28, payload={})
    state = derive(DEATH_TICK, (talk,))
    assert lost_testimonies(state, NPCS, DEATH_TICK) == ()


def test_lost_testimonies_is_empty_before_the_death() -> None:
    """Nobody has lost anything while the villager is still alive."""
    state = derive(DEATH_TICK - 1, ())
    assert lost_testimonies(state, NPCS, DEATH_TICK - 1) == ()


def test_lost_testimonies_never_reports_a_living_villager() -> None:
    """A living villager is not a lost testimony."""
    state = derive(TOTAL_TICKS, ())
    assert lost_testimonies(state, NPCS, TOTAL_TICKS) == ("NPC_DEAD",)


def test_lost_testimonies_ignores_a_talk_without_target() -> None:
    """A talk without a target names nobody, so it saves no testimony."""
    untargeted = Decision(kind="talk", target="", tick=28, payload={})
    state = derive(DEATH_TICK, (untargeted,))
    assert lost_testimonies(state, NPCS, DEATH_TICK) == ("NPC_DEAD",)


def test_available_dialogues_excludes_the_dead() -> None:
    """A dead villager cannot be talked to any more."""
    state = derive(DEATH_TICK, ())
    assert available_dialogues(state, NPCS, DEATH_TICK) == frozenset({"NPC_ALIVE"})


def test_available_dialogues_includes_the_dead_before_their_death() -> None:
    """Before the death the villager is at their post as usual."""
    state = derive(DEATH_TICK - 1, ())
    assert available_dialogues(state, NPCS, DEATH_TICK - 1) == frozenset({"NPC_DEAD", "NPC_ALIVE"})


def test_available_dialogues_follows_the_schedule() -> None:
    """An NPC that is not interactable at that tick has no dialogue."""
    sleeping = Npc(
        id="NPC_SLEEPING",
        name="Sleeping",
        schedule=(
            ScheduleEntry(
                start_tick=0,
                end_tick=96,
                zone="ZONE_TAVERN",
                tile=(1, 1),
                activity="sleeping",
                interactable=False,
            ),
        ),
    )
    state = derive(0, ())
    assert available_dialogues(state, (sleeping,), 0) == frozenset()


def test_available_dialogues_is_empty_without_npcs() -> None:
    """A world without NPCs has no dialogue to reach."""
    state = derive(0, ())
    assert available_dialogues(state, (), 0) == frozenset()


def test_the_opportunity_is_lost_but_the_knowledge_is_kept() -> None:
    """The whole rule in one test.

    The player heard the testimony before the death, so the flag survives
    the death. But the villager is dead, so the dialogue is out of reach
    and the testimony is not reported as lost either.
    """
    talk = Decision(kind="talk", target="NPC_DEAD", tick=28, payload={})
    state = derive(DEATH_TICK, (talk,))

    assert state.has_flag("talked:NPC_DEAD")
    assert "NPC_DEAD" not in available_dialogues(state, NPCS, DEATH_TICK)
    assert lost_testimonies(state, NPCS, DEATH_TICK) == ()
