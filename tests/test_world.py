"""Tests for the composition root.

:class:`WorldSim` is the object the presentation layer talks to. The tests
below check that it loads the content, derives the state, consumes exactly one
tick per valid action, rejects invalid actions **without** consuming a tick
and that the same sequence of actions always produces the same world.

The provisions of the town follow the same rule as the tick: an action the
town cannot afford raises :class:`InsufficientResourcesError` and consumes
**neither** a tick nor a resource. The town also eats on its own: the daily
decay is applied exactly when the clock crosses a day boundary.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.lighting import LightState
from core.resources import ResourceSpec
from core.schedule import NpcState
from core.state import Decision, WorldState
from core.time import TICKS_PER_DAY, TOTAL_TICKS, ClockOverflowError, to_tick
from core.world import (
    InsufficientResourcesError,
    InvalidActionError,
    WorldContentError,
    WorldSim,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "minimal_world.json"

TALK_MARTA = Decision(kind="talk", target="NPC_MARTA", tick=0, payload={})
TALK_OMAR = Decision(kind="talk", target="NPC_OMAR", tick=0, payload={})
REPORT = Decision(
    kind="report_symptom",
    target="NPC_MARTA",
    tick=0,
    payload={"symptom": "SYM_FEVER"},
)

#: A resource the town can afford for a couple of actions only.
SCARCE = ResourceSpec(id="RES_FOOD", label="Food", initial=2, per_action=1, critical_at=1)


@pytest.fixture
def sim() -> WorldSim:
    """Return a simulation loaded from the minimal world fixture."""
    return WorldSim.load(FIXTURE_PATH)


def test_load_reads_the_fixture(sim: WorldSim) -> None:
    """The fixture is loaded into NPCs and zones."""
    assert sim.tick() == 0
    assert sim.decisions() == ()
    assert sim.npc("NPC_MARTA").name == "Marta"
    assert sim.zone("ZONE_PORT").name == "Harbour"


def test_load_starts_at_tick_zero_with_no_decisions(sim: WorldSim) -> None:
    """A freshly loaded simulation has not moved yet."""
    assert sim.tick() == 0
    assert sim.decisions() == ()
    assert sim.state().tick == 0


def test_state_is_derived(sim: WorldSim) -> None:
    """The state of the simulation is a derived world state."""
    state = sim.state()
    assert isinstance(state, WorldState)
    assert state.tick == 0
    assert state.flags == frozenset()


def test_npc_states_are_derived(sim: WorldSim) -> None:
    """Every NPC of the fixture has a resolved state."""
    states = sim.npc_states()
    assert set(states) == {"NPC_MARTA", "NPC_OMAR", "NPC_LENA"}
    assert all(isinstance(state, NpcState) for state in states.values())


def test_light_is_derived(sim: WorldSim) -> None:
    """The lighting of the simulation is a derived light state."""
    assert isinstance(sim.light(), LightState)
    assert sim.light().phase_id == "dawn_early"


def test_advance_consumes_exactly_one_tick(sim: WorldSim) -> None:
    """A valid action moves the clock forward by one tick."""
    sim.advance(TALK_MARTA)
    assert sim.tick() == 1
    sim.advance(TALK_MARTA)
    assert sim.tick() == 2


def test_advance_records_the_decision(sim: WorldSim) -> None:
    """A valid action is recorded in the list of decisions."""
    sim.advance(TALK_MARTA)
    assert len(sim.decisions()) == 1
    assert sim.decisions()[0].kind == "talk"
    assert sim.decisions()[0].target == "NPC_MARTA"


def test_advance_stamps_the_decision_with_the_current_tick(sim: WorldSim) -> None:
    """The simulator owns the tick of the decision, not the caller."""
    sim.advance(TALK_MARTA)
    assert sim.decisions()[0].tick == 0
    sim.advance(TALK_MARTA)
    assert sim.decisions()[1].tick == 1


def test_advance_derives_the_flags_of_the_decision(sim: WorldSim) -> None:
    """Advancing raises the flags derived from the decision."""
    sim.advance(TALK_MARTA)
    assert sim.state().has_flag("talked:NPC_MARTA")


def test_advance_returns_the_new_state(sim: WorldSim) -> None:
    """``advance`` returns the state of the new tick."""
    state = sim.advance(TALK_MARTA)
    assert state.tick == 1
    assert state == sim.state()


def test_invalid_action_does_not_consume_a_tick(sim: WorldSim) -> None:
    """A rejected action leaves the clock untouched."""
    before = sim.tick()
    with pytest.raises(InvalidActionError):
        sim.advance(TALK_OMAR)
    assert sim.tick() == before


def test_invalid_action_does_not_record_a_decision(sim: WorldSim) -> None:
    """A rejected action is not stored."""
    with pytest.raises(InvalidActionError):
        sim.advance(TALK_OMAR)
    assert sim.decisions() == ()


def test_talking_to_an_unknown_npc_is_rejected(sim: WorldSim) -> None:
    """An action targeting an unknown NPC is rejected."""
    with pytest.raises(InvalidActionError, match="unknown npc"):
        sim.advance(Decision(kind="talk", target="NPC_GHOST", tick=0, payload={}))
    assert sim.tick() == 0


def test_talking_to_a_sleeping_npc_is_rejected(sim: WorldSim) -> None:
    """An NPC that is not interactable cannot be talked to."""
    with pytest.raises(InvalidActionError, match="not interactable"):
        sim.advance(TALK_OMAR)
    assert sim.tick() == 0


def test_talking_to_an_npc_is_allowed_when_interactable(sim: WorldSim) -> None:
    """The same action is accepted once the NPC becomes interactable."""
    sim.advance_to(to_tick(1, 8, 0))
    sim.advance(TALK_OMAR)
    assert sim.tick() == to_tick(1, 8, 0) + 1
    assert sim.state().has_flag("talked:NPC_OMAR")


def test_action_without_kind_is_rejected(sim: WorldSim) -> None:
    """An action must name what it does."""
    with pytest.raises(InvalidActionError, match="non-empty kind"):
        sim.advance(Decision(kind="", target="NPC_MARTA", tick=0, payload={}))
    assert sim.tick() == 0


def test_non_decision_action_is_rejected(sim: WorldSim) -> None:
    """Only decisions can be submitted."""
    with pytest.raises(InvalidActionError, match="expected a Decision"):
        sim.advance("talk")  # type: ignore[arg-type]
    assert sim.tick() == 0


def test_the_same_sequence_produces_identical_states(sim: WorldSim) -> None:
    """Two runs of the same action sequence produce identical states."""
    first = WorldSim.load(FIXTURE_PATH)
    second = WorldSim.load(FIXTURE_PATH)

    sequence = [TALK_MARTA, TALK_MARTA, REPORT, TALK_MARTA]
    for action in sequence:
        first.advance(action)
        second.advance(action)

    assert first.state() == second.state()
    assert repr(first.state()) == repr(second.state())
    assert first.decisions() == second.decisions()
    assert first.npc_states() == second.npc_states()
    assert first.light() == second.light()


def test_the_same_sequence_produces_identical_reprs(sim: WorldSim) -> None:
    """The textual representation of the state is reproducible too."""
    sim.advance(TALK_MARTA)
    other = WorldSim.load(FIXTURE_PATH)
    other.advance(TALK_MARTA)
    assert repr(sim.state()) == repr(other.state())


def test_apply_records_a_decision_without_moving_the_clock(sim: WorldSim) -> None:
    """``apply`` is the hook for events: it does not consume a tick."""
    sim.apply(Decision(kind="event", target="EV_TEST", tick=7, payload={}))
    assert sim.tick() == 0
    assert len(sim.decisions()) == 1
    assert sim.decisions()[0].tick == 7


def test_apply_rejects_malformed_decisions(sim: WorldSim) -> None:
    """``apply`` only accepts decisions."""
    with pytest.raises(InvalidActionError, match="expected a Decision"):
        sim.apply(None)  # type: ignore[arg-type]


def test_advance_to_moves_the_clock_to_an_absolute_tick(sim: WorldSim) -> None:
    """``advance_to`` walks the clock forward to the requested tick."""
    sim.advance_to(40)
    assert sim.tick() == 40
    assert sim.state().tick == 40


def test_advance_to_rejects_ticks_in_the_past(sim: WorldSim) -> None:
    """The clock is monotonic: it never goes back."""
    sim.advance_to(40)
    with pytest.raises(ValueError, match="is in the past"):
        sim.advance_to(39)


def test_advance_past_the_cycle_raises(sim: WorldSim) -> None:
    """Advancing past the closing tick raises instead of wrapping around."""
    sim.advance_to(TOTAL_TICKS)
    with pytest.raises(ClockOverflowError):
        sim.advance(TALK_MARTA)


def test_advance_to_the_closing_tick_is_allowed(sim: WorldSim) -> None:
    """The closing tick 288 is reachable, but no action fits there."""
    sim.advance_to(TOTAL_TICKS)
    assert sim.tick() == TOTAL_TICKS


def test_state_flags_accumulate_over_the_run(sim: WorldSim) -> None:
    """Flags raised by past decisions stay active."""
    sim.advance(TALK_MARTA)
    sim.advance(REPORT)
    state = sim.state()
    assert state.has_flag("talked:NPC_MARTA")
    assert state.has_flag("knows:symptom:SYM_FEVER")
    assert state.symptoms_known() == ("SYM_FEVER",)


def test_load_rejects_a_missing_file() -> None:
    """A missing content file is reported as a content error."""
    with pytest.raises(WorldContentError, match="cannot read content file"):
        WorldSim.load(Path("does-not-exist.json"))


def test_load_rejects_invalid_json(tmp_path: Path) -> None:
    """A malformed content file is reported as a content error."""
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(WorldContentError, match="not valid JSON"):
        WorldSim.load(broken)


def test_load_rejects_a_non_object_document(tmp_path: Path) -> None:
    """A content file must contain a JSON object."""
    listy = tmp_path / "list.json"
    listy.write_text("[]", encoding="utf-8")
    with pytest.raises(WorldContentError, match="must contain a JSON object"):
        WorldSim.load(listy)


def test_load_rejects_npcs_without_an_id(tmp_path: Path) -> None:
    """Every NPC needs a stable identifier."""
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps({"npcs": [{"name": "Nobody"}]}), encoding="utf-8")
    with pytest.raises(WorldContentError, match="non-empty string id"):
        WorldSim.load(broken)


def test_load_rejects_overlapping_schedules(tmp_path: Path) -> None:
    """A content file with overlapping blocks is rejected at load time."""
    broken = tmp_path / "broken.json"
    broken.write_text(
        json.dumps(
            {
                "npcs": [
                    {
                        "id": "NPC_X",
                        "name": "X",
                        "schedule": [
                            {
                                "start_tick": 0,
                                "end_tick": 30,
                                "zone": "Z",
                                "tile": [1, 1],
                                "activity": "a",
                                "interactable": True,
                            },
                            {
                                "start_tick": 20,
                                "end_tick": 40,
                                "zone": "Z",
                                "tile": [2, 2],
                                "activity": "b",
                                "interactable": False,
                            },
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(WorldContentError, match="overlaps"):
        WorldSim.load(broken)


def test_load_rejects_a_malformed_tile(tmp_path: Path) -> None:
    """A tile must be a pair of integers."""
    broken = tmp_path / "broken.json"
    broken.write_text(
        json.dumps(
            {
                "npcs": [
                    {
                        "id": "NPC_X",
                        "name": "X",
                        "schedule": [
                            {
                                "start_tick": 0,
                                "end_tick": 30,
                                "zone": "Z",
                                "tile": [1],
                                "activity": "a",
                                "interactable": True,
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(WorldContentError, match="pair of integers"):
        WorldSim.load(broken)


def test_load_rejects_npcs_that_are_not_objects(tmp_path: Path) -> None:
    """Every NPC must be an object."""
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps({"npcs": ["NPC_X"]}), encoding="utf-8")
    with pytest.raises(WorldContentError, match="every npc must be an object"):
        WorldSim.load(broken)


def test_load_rejects_a_missing_zone_name(tmp_path: Path) -> None:
    """A zone needs a non-empty identifier."""
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps({"zones": [{"name": "Nameless"}]}), encoding="utf-8")
    with pytest.raises(WorldContentError, match="non-empty string id"):
        WorldSim.load(broken)


def test_zone_and_npc_lookup_rejects_unknown_ids(sim: WorldSim) -> None:
    """Asking for an unknown id is a programming error."""
    with pytest.raises(KeyError):
        sim.npc("NPC_GHOST")
    with pytest.raises(KeyError):
        sim.zone("ZONE_GHOST")


def test_npc_states_follow_the_schedule(sim: WorldSim) -> None:
    """The NPC states of the simulation follow the schedules."""
    sim.advance_to(to_tick(1, 7, 0))
    states = sim.npc_states()
    assert states["NPC_MARTA"].activity == "selling_fish"
    assert states["NPC_OMAR"].activity == "sleeping"
    assert states["NPC_LENA"].activity == "sorting_produce"


def _write_npc_document(tmp_path: Path, npc: dict[str, object]) -> Path:
    """Write a content document with a single NPC.

    Args:
        tmp_path: Directory to write the document into.
        npc: NPC object to serialise.

    Returns:
        The path of the written document.
    """
    path = tmp_path / "world.json"
    path.write_text(json.dumps({"npcs": [npc]}), encoding="utf-8")
    return path


def _valid_entry() -> dict[str, object]:
    """Return a valid schedule block for the malformed-content tests."""
    return {
        "start_tick": 0,
        "end_tick": 30,
        "zone": "ZONE_PORT",
        "tile": [1, 1],
        "activity": "working",
        "interactable": True,
    }


def test_load_rejects_schedule_entries_that_are_not_objects(tmp_path: Path) -> None:
    """Every schedule entry must be an object."""
    path = _write_npc_document(
        tmp_path,
        {"id": "NPC_X", "name": "X", "schedule": ["not an object"]},
    )
    with pytest.raises(WorldContentError, match="schedule entries must be objects"):
        WorldSim.load(path)


def test_load_rejects_incomplete_schedule_entries(tmp_path: Path) -> None:
    """A schedule entry must carry every required field."""
    entry = _valid_entry()
    del entry["activity"]
    path = _write_npc_document(tmp_path, {"id": "NPC_X", "name": "X", "schedule": [entry]})
    with pytest.raises(WorldContentError, match="schedule entry is missing"):
        WorldSim.load(path)


@pytest.mark.parametrize("field", ["start_tick", "end_tick"])
def test_load_rejects_non_integer_ticks(tmp_path: Path, field: str) -> None:
    """The tick boundaries of a schedule entry must be integers."""
    entry = _valid_entry()
    entry[field] = "nope"
    path = _write_npc_document(tmp_path, {"id": "NPC_X", "name": "X", "schedule": [entry]})
    with pytest.raises(WorldContentError, match="must be an integer"):
        WorldSim.load(path)


def test_load_rejects_a_non_string_zone(tmp_path: Path) -> None:
    """The zone of a schedule entry must be a string."""
    entry = _valid_entry()
    entry["zone"] = 7
    path = _write_npc_document(tmp_path, {"id": "NPC_X", "name": "X", "schedule": [entry]})
    with pytest.raises(WorldContentError, match="zone must be a string"):
        WorldSim.load(path)


def test_load_rejects_a_non_string_activity(tmp_path: Path) -> None:
    """The activity of a schedule entry must be a string."""
    entry = _valid_entry()
    entry["activity"] = 7
    path = _write_npc_document(tmp_path, {"id": "NPC_X", "name": "X", "schedule": [entry]})
    with pytest.raises(WorldContentError, match="activity must be a string"):
        WorldSim.load(path)


def test_load_rejects_a_non_boolean_interactable(tmp_path: Path) -> None:
    """The interactable flag of a schedule entry must be a boolean."""
    entry = _valid_entry()
    entry["interactable"] = "yes"
    path = _write_npc_document(tmp_path, {"id": "NPC_X", "name": "X", "schedule": [entry]})
    with pytest.raises(WorldContentError, match="interactable must be a boolean"):
        WorldSim.load(path)


def test_load_defaults_interactable_to_false(tmp_path: Path) -> None:
    """A schedule entry without the interactable flag is not interactable."""
    entry = _valid_entry()
    del entry["interactable"]
    path = _write_npc_document(tmp_path, {"id": "NPC_X", "name": "X", "schedule": [entry]})
    sim = WorldSim.load(path)
    assert sim.npc_states()["NPC_X"].interactable is False


def test_load_rejects_an_npc_without_a_name(tmp_path: Path) -> None:
    """Every NPC needs a display name."""
    path = _write_npc_document(tmp_path, {"id": "NPC_X", "schedule": []})
    with pytest.raises(WorldContentError, match="name must be a non-empty string"):
        WorldSim.load(path)


def test_load_rejects_a_schedule_that_is_not_a_list(tmp_path: Path) -> None:
    """The schedule of an NPC must be a list."""
    path = _write_npc_document(tmp_path, {"id": "NPC_X", "name": "X", "schedule": {}})
    with pytest.raises(WorldContentError, match="schedule must be a list"):
        WorldSim.load(path)


def test_load_rejects_a_npcs_field_that_is_not_a_list(tmp_path: Path) -> None:
    """The ``npcs`` field must be a list."""
    path = tmp_path / "world.json"
    path.write_text(json.dumps({"npcs": {}}), encoding="utf-8")
    with pytest.raises(WorldContentError, match="'npcs' must be a list"):
        WorldSim.load(path)


def test_load_rejects_a_zones_field_that_is_not_a_list(tmp_path: Path) -> None:
    """The ``zones`` field must be a list."""
    path = tmp_path / "world.json"
    path.write_text(json.dumps({"zones": {}}), encoding="utf-8")
    with pytest.raises(WorldContentError, match="'zones' must be a list"):
        WorldSim.load(path)


def test_load_accepts_an_empty_world(tmp_path: Path) -> None:
    """A content document without NPCs and zones is valid."""
    path = tmp_path / "world.json"
    path.write_text("{}", encoding="utf-8")
    sim = WorldSim.load(path)
    assert sim.npc_states() == {}
    assert sim.tick() == 0


def test_zone_name_defaults_to_the_zone_id(tmp_path: Path) -> None:
    """A zone without a name uses its identifier as the display name."""
    path = tmp_path / "world.json"
    path.write_text(json.dumps({"zones": [{"id": "ZONE_X"}]}), encoding="utf-8")
    sim = WorldSim.load(path)
    assert sim.zone("ZONE_X").name == "ZONE_X"


def test_load_rejects_zones_that_are_not_objects(tmp_path: Path) -> None:
    """Every zone must be an object."""
    path = tmp_path / "world.json"
    path.write_text(json.dumps({"zones": ["ZONE_X"]}), encoding="utf-8")
    with pytest.raises(WorldContentError, match="every zone must be an object"):
        WorldSim.load(path)


def test_load_rejects_a_zone_with_a_non_string_name(tmp_path: Path) -> None:
    """The name of a zone must be a string."""
    path = tmp_path / "world.json"
    path.write_text(json.dumps({"zones": [{"id": "ZONE_X", "name": 7}]}), encoding="utf-8")
    with pytest.raises(WorldContentError, match="name must be a string"):
        WorldSim.load(path)


# ----------------------------------------------------------------------
# Resources
# ----------------------------------------------------------------------


def _write_resource_document(tmp_path: Path, resources: list[dict[str, object]]) -> Path:
    """Write a content document that declares the given resources.

    The document also declares one NPC, so that the tests can perform a real
    action against it.

    Args:
        tmp_path: Directory to write the document into.
        resources: Resource documents to serialise.

    Returns:
        The path of the written document.
    """
    path = tmp_path / "world.json"
    document = {
        "npcs": [
            {
                "id": "NPC_MARTA",
                "name": "Marta",
                "schedule": [
                    {
                        "start_tick": 0,
                        "end_tick": 96,
                        "zone": "ZONE_PORT",
                        "tile": [12, 7],
                        "activity": "mending_nets",
                        "interactable": True,
                    }
                ],
            }
        ],
        "resources": resources,
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_a_world_without_resources_has_neutral_provisions(sim: WorldSim) -> None:
    """A world that declares no provisions tracks nothing."""
    assert sim.resources().amounts == {}
    assert sim.resource_specs() == ()
    assert sim.crisis() == ()


def test_advance_consumes_the_resources_of_the_action(tmp_path: Path) -> None:
    """Every action draws on the provisions of the town."""
    path = _write_resource_document(
        tmp_path,
        [{"id": "RES_FOOD", "label": "Food", "initial": 5, "per_action": 1, "critical_at": 2}],
    )
    sim = WorldSim.load(path)

    assert sim.resources().amount("RES_FOOD") == 5
    sim.advance(TALK_MARTA)
    assert sim.resources().amount("RES_FOOD") == 4
    sim.advance(TALK_MARTA)
    assert sim.resources().amount("RES_FOOD") == 3


def test_advance_consumes_the_resources_of_every_kind_of_action(tmp_path: Path) -> None:
    """Moving, talking, examining and reporting all cost the same."""
    path = _write_resource_document(
        tmp_path,
        [{"id": "RES_FOOD", "label": "Food", "initial": 10, "per_action": 2, "critical_at": 2}],
    )
    sim = WorldSim.load(path)

    sim.advance(TALK_MARTA)
    assert sim.resources().amount("RES_FOOD") == 8
    sim.advance(Decision(kind="move", target="ZONE_X", tick=0, payload={}))
    assert sim.resources().amount("RES_FOOD") == 6
    sim.advance(Decision(kind="examine", target="OBJ_X", tick=0, payload={}))
    assert sim.resources().amount("RES_FOOD") == 4
    sim.advance(REPORT)
    assert sim.resources().amount("RES_FOOD") == 2


def test_an_unaffordable_action_raises_and_consumes_no_tick(tmp_path: Path) -> None:
    """The town cannot act on provisions that do not exist."""
    path = _write_resource_document(
        tmp_path,
        [{"id": "RES_FOOD", "label": "Food", "initial": 1, "per_action": 1, "critical_at": 0}],
    )
    sim = WorldSim.load(path)

    sim.advance(TALK_MARTA)
    assert sim.tick() == 1
    assert sim.resources().amount("RES_FOOD") == 0

    with pytest.raises(InsufficientResourcesError):
        sim.advance(TALK_MARTA)

    assert sim.tick() == 1
    assert sim.resources().amount("RES_FOOD") == 0
    assert len(sim.decisions()) == 1


def test_an_unaffordable_action_is_an_invalid_action(tmp_path: Path) -> None:
    """The error inherits from the base class of the rejected actions."""
    path = _write_resource_document(
        tmp_path,
        [{"id": "RES_FOOD", "label": "Food", "initial": 1, "per_action": 1, "critical_at": 0}],
    )
    sim = WorldSim.load(path)
    sim.advance(TALK_MARTA)

    with pytest.raises(InvalidActionError):
        sim.advance(TALK_MARTA)


def test_the_provisions_are_part_of_the_derived_state(tmp_path: Path) -> None:
    """The snapshot carries the provisions as they were given to it."""
    path = _write_resource_document(
        tmp_path,
        [{"id": "RES_FOOD", "label": "Food", "initial": 3, "per_action": 1, "critical_at": 1}],
    )
    sim = WorldSim.load(path)
    sim.advance(TALK_MARTA)

    assert sim.state().resources.amount("RES_FOOD") == 2
    assert sim.state().resources == sim.resources()


def test_the_town_enters_crisis_when_a_resource_runs_low(tmp_path: Path) -> None:
    """A resource below its threshold puts the town in crisis."""
    path = _write_resource_document(
        tmp_path,
        [{"id": "RES_FOOD", "label": "Food", "initial": 2, "per_action": 1, "critical_at": 1}],
    )
    sim = WorldSim.load(path)

    assert sim.crisis() == ()
    sim.advance(TALK_MARTA)
    assert sim.crisis() == ()
    sim.advance(TALK_MARTA)
    assert sim.crisis() == ("RES_FOOD",)


def test_apply_does_not_consume_the_provisions(tmp_path: Path) -> None:
    """Events apply their effect without spending the stores."""
    path = _write_resource_document(
        tmp_path,
        [{"id": "RES_FOOD", "label": "Food", "initial": 5, "per_action": 1, "critical_at": 1}],
    )
    sim = WorldSim.load(path)

    sim.apply(Decision(kind="event", target="EV_X", tick=7, payload={}))
    assert sim.resources().amount("RES_FOOD") == 5
    assert sim.tick() == 0


def test_advance_to_does_not_consume_the_provisions(tmp_path: Path) -> None:
    """Waiting burns time without drawing on the stores."""
    path = _write_resource_document(
        tmp_path,
        [{"id": "RES_FOOD", "label": "Food", "initial": 5, "per_action": 1, "critical_at": 1}],
    )
    sim = WorldSim.load(path)

    sim.advance_to(10)
    assert sim.tick() == 10
    assert sim.resources().amount("RES_FOOD") == 5


def test_the_same_sequence_produces_identical_provisions(tmp_path: Path) -> None:
    """Two runs of the same action sequence leave the same stores behind."""
    path = _write_resource_document(
        tmp_path,
        [{"id": "RES_FOOD", "label": "Food", "initial": 4, "per_action": 1, "critical_at": 1}],
    )
    first = WorldSim.load(path)
    second = WorldSim.load(path)

    for action in (TALK_MARTA, TALK_MARTA, REPORT):
        first.advance(action)
        second.advance(action)

    assert first.resources() == second.resources()


def test_load_reads_the_resources_of_the_document(tmp_path: Path) -> None:
    """The specifications of the provisions are loaded with the world."""
    path = _write_resource_document(
        tmp_path,
        [{"id": "RES_FOOD", "label": "Food", "initial": 5, "per_action": 1, "critical_at": 2}],
    )
    sim = WorldSim.load(path)

    assert len(sim.resource_specs()) == 1
    spec = sim.resource_specs()[0]
    assert spec.id == "RES_FOOD"
    assert spec.label == "Food"
    assert spec.initial == 5
    assert spec.per_action == 1
    assert spec.critical_at == 2


def test_load_rejects_duplicated_resource_ids(tmp_path: Path) -> None:
    """Two resources cannot share an id."""
    path = _write_resource_document(
        tmp_path,
        [
            {"id": "RES_FOOD", "label": "Food", "initial": 5, "per_action": 1, "critical_at": 2},
            {"id": "RES_FOOD", "label": "Other", "initial": 5, "per_action": 1, "critical_at": 2},
        ],
    )
    with pytest.raises(WorldContentError, match="duplicated resource id"):
        WorldSim.load(path)


def test_load_rejects_a_resources_field_that_is_not_a_list(tmp_path: Path) -> None:
    """The ``resources`` field must be a list."""
    path = tmp_path / "world.json"
    path.write_text(json.dumps({"resources": {}}), encoding="utf-8")
    with pytest.raises(WorldContentError, match="'resources' must be a list"):
        WorldSim.load(path)


def test_load_rejects_a_resource_without_an_id(tmp_path: Path) -> None:
    """Every resource needs a stable identifier."""
    path = _write_resource_document(tmp_path, [{"label": "Food"}])
    with pytest.raises(WorldContentError, match="non-empty string id"):
        WorldSim.load(path)


def test_load_rejects_a_resource_with_a_non_integer_amount(tmp_path: Path) -> None:
    """The amounts of a resource must be integers."""
    path = _write_resource_document(
        tmp_path,
        [{"id": "RES_FOOD", "label": "Food", "initial": "5", "per_action": 1, "critical_at": 2}],
    )
    with pytest.raises(WorldContentError, match="initial must be an integer"):
        WorldSim.load(path)


def test_load_rejects_a_resource_with_a_negative_amount(tmp_path: Path) -> None:
    """A negative stock is not a state the simulation can represent."""
    path = _write_resource_document(
        tmp_path,
        [{"id": "RES_FOOD", "label": "Food", "initial": -5, "per_action": 1, "critical_at": 2}],
    )
    with pytest.raises(WorldContentError, match="initial must be >= 0"):
        WorldSim.load(path)


def test_load_rejects_a_resource_with_an_unreachable_threshold(tmp_path: Path) -> None:
    """A threshold above the initial amount would start in crisis."""
    path = _write_resource_document(
        tmp_path,
        [{"id": "RES_FOOD", "label": "Food", "initial": 5, "per_action": 1, "critical_at": 9}],
    )
    with pytest.raises(WorldContentError, match="critical_at"):
        WorldSim.load(path)


def test_load_rejects_resources_that_are_not_objects(tmp_path: Path) -> None:
    """Every resource must be an object."""
    path = _write_resource_document(tmp_path, ["RES_FOOD"])
    with pytest.raises(WorldContentError, match="every resource must be an object"):
        WorldSim.load(path)


def test_load_rejects_a_resource_with_a_non_string_label(tmp_path: Path) -> None:
    """The label of a resource must be a string."""
    path = _write_resource_document(
        tmp_path,
        [{"id": "RES_FOOD", "label": 7, "initial": 5, "per_action": 1, "critical_at": 2}],
    )
    with pytest.raises(WorldContentError, match="label must be a string"):
        WorldSim.load(path)


# ----------------------------------------------------------------------
# The kind of the action
# ----------------------------------------------------------------------


def test_an_action_costs_more_when_its_resource_is_critical(tmp_path: Path) -> None:
    """A resource in crisis doubles the price of the action it gates.

    The stock starts at 5 and the threshold at 3. The threshold is
    exclusive, so the stock is healthy at 3 and becomes critical at 2:
    from then on the ``"prepare_sample"`` action costs two units of fuel
    instead of one.
    """
    path = _write_resource_document(
        tmp_path,
        [
            {
                "id": "RES_FUEL",
                "label": "Fuel",
                "initial": 5,
                "per_action": 1,
                "critical_at": 3,
                "blocks_actions": ["prepare_sample"],
            }
        ],
    )
    sim = WorldSim.load(path)

    sim.advance(Decision(kind="prepare_sample", target="OBJ_X", tick=0, payload={}))
    assert sim.resources().amount("RES_FUEL") == 4
    assert sim.resources().spent_on("RES_FUEL") == 1

    sim.advance(Decision(kind="prepare_sample", target="OBJ_X", tick=0, payload={}))
    assert sim.resources().amount("RES_FUEL") == 3
    assert sim.resources().spent_on("RES_FUEL") == 2

    # At the threshold the stock is still healthy, so the action costs one.
    sim.advance(Decision(kind="prepare_sample", target="OBJ_X", tick=0, payload={}))
    assert sim.resources().amount("RES_FUEL") == 2
    assert sim.resources().spent_on("RES_FUEL") == 3

    # Below the threshold the action costs double.
    sim.advance(Decision(kind="prepare_sample", target="OBJ_X", tick=0, payload={}))
    assert sim.resources().amount("RES_FUEL") == 0
    assert sim.resources().spent_on("RES_FUEL") == 5


def test_an_action_costs_its_plain_price_when_its_resource_is_healthy(
    tmp_path: Path,
) -> None:
    """A resource above its threshold is charged its usual price."""
    path = _write_resource_document(
        tmp_path,
        [
            {
                "id": "RES_FUEL",
                "label": "Fuel",
                "initial": 4,
                "per_action": 1,
                "critical_at": 2,
                "blocks_actions": ["prepare_sample"],
            }
        ],
    )
    sim = WorldSim.load(path)

    sim.advance(Decision(kind="prepare_sample", target="OBJ_X", tick=0, payload={}))
    assert sim.resources().amount("RES_FUEL") == 3
    assert sim.resources().spent_on("RES_FUEL") == 1


def test_a_depleted_resource_refuses_the_action_it_gates(tmp_path: Path) -> None:
    """The town cannot work without the material."""
    path = _write_resource_document(
        tmp_path,
        [
            {
                "id": "RES_FUEL",
                "label": "Fuel",
                "initial": 1,
                "per_action": 1,
                "critical_at": 1,
                "blocks_actions": ["prepare_sample"],
            }
        ],
    )
    sim = WorldSim.load(path)

    sim.advance(Decision(kind="prepare_sample", target="OBJ_X", tick=0, payload={}))
    assert sim.resources().amount("RES_FUEL") == 0

    with pytest.raises(InsufficientResourcesError):
        sim.advance(Decision(kind="prepare_sample", target="OBJ_X", tick=0, payload={}))

    assert sim.tick() == 1
    assert sim.resources().amount("RES_FUEL") == 0


def test_a_depleted_resource_does_not_consume_a_tick(tmp_path: Path) -> None:
    """A refused action leaves the clock untouched."""
    path = _write_resource_document(
        tmp_path,
        [
            {
                "id": "RES_FUEL",
                "label": "Fuel",
                "initial": 0,
                "per_action": 1,
                "critical_at": 0,
                "blocks_actions": ["prepare_sample"],
            }
        ],
    )
    sim = WorldSim.load(path)

    with pytest.raises(InsufficientResourcesError):
        sim.advance(Decision(kind="prepare_sample", target="OBJ_X", tick=0, payload={}))

    assert sim.tick() == 0
    assert sim.decisions() == ()


def test_can_afford_reports_the_price_of_an_action_kind(tmp_path: Path) -> None:
    """The simulator answers the question before the action is taken."""
    path = _write_resource_document(
        tmp_path,
        [
            {
                "id": "RES_FUEL",
                "label": "Fuel",
                "initial": 2,
                "per_action": 1,
                "critical_at": 2,
                "blocks_actions": ["prepare_sample"],
            }
        ],
    )
    sim = WorldSim.load(path)

    assert sim.can_afford("prepare_sample") is True
    sim.advance(Decision(kind="prepare_sample", target="OBJ_X", tick=0, payload={}))
    # One unit left and the threshold is two: the action now costs double.
    assert sim.can_afford("prepare_sample") is False


# ----------------------------------------------------------------------
# The daily decay
# ----------------------------------------------------------------------


def _write_decaying_document(tmp_path: Path, daily_decay: int = 2) -> Path:
    """Write a content document with one decaying resource.

    Args:
        tmp_path: Directory to write the document into.
        daily_decay: Decay of the resource, per day.

    Returns:
        The path of the written document.
    """
    return _write_resource_document(
        tmp_path,
        [
            {
                "id": "RES_FOOD",
                "label": "Food",
                "initial": 20,
                "per_action": 1,
                "critical_at": 5,
                "daily_decay": daily_decay,
            }
        ],
    )


def test_the_decay_is_not_applied_before_the_first_day_boundary(tmp_path: Path) -> None:
    """The town has not eaten yet while it is still Day 1."""
    path = _write_decaying_document(tmp_path)
    sim = WorldSim.load(path)

    sim.advance_to(TICKS_PER_DAY - 1)
    assert sim.tick() == 95
    assert sim.resources().amount("RES_FOOD") == 20


@pytest.mark.parametrize(
    ("tick", "expected_day"),
    [
        (TICKS_PER_DAY, 2),
        (2 * TICKS_PER_DAY, 3),
        (3 * TICKS_PER_DAY, 4),
        (4 * TICKS_PER_DAY, 5),
        (5 * TICKS_PER_DAY, 6),
    ],
)
def test_the_decay_is_applied_exactly_at_the_day_boundary(
    tmp_path: Path,
    tick: int,
    expected_day: int,
) -> None:
    """Each day boundary applies exactly one day of decay.

    The cycle has five day boundaries inside it (ticks 96, 192, 288 and 384
    open Days 2 to 5) and a fifth one at the closing tick 480, which opens
    Day 6.
    """
    path = _write_decaying_document(tmp_path)
    sim = WorldSim.load(path)

    sim.advance_to(tick)
    crossings = tick // TICKS_PER_DAY
    assert sim.resources().amount("RES_FOOD") == 20 - 2 * crossings
    assert sim.day() == expected_day


def test_the_decay_is_applied_once_per_crossing_and_not_per_tick(tmp_path: Path) -> None:
    """Waiting for a whole day costs the town one day of provisions."""
    path = _write_decaying_document(tmp_path)
    sim = WorldSim.load(path)

    sim.advance_to(TICKS_PER_DAY)
    assert sim.resources().amount("RES_FOOD") == 18

    sim.advance_to(2 * TICKS_PER_DAY)
    assert sim.resources().amount("RES_FOOD") == 16


def test_the_closing_tick_applies_the_last_decay(tmp_path: Path) -> None:
    """The closing tick 480 opens Day 6 and applies the fifth decay."""
    path = _write_decaying_document(tmp_path)
    sim = WorldSim.load(path)

    sim.advance_to(TOTAL_TICKS)
    assert sim.tick() == 480
    assert sim.day() == 6
    assert sim.resources().amount("RES_FOOD") == 20 - 2 * 5


def test_the_day_of_the_closing_tick_is_the_sixth(tmp_path: Path) -> None:
    """The cycle opens on Day 1 and closes on Day 6."""
    path = _write_decaying_document(tmp_path)
    sim = WorldSim.load(path)

    assert sim.day() == 1
    assert sim.state().day == 1
    sim.advance_to(TOTAL_TICKS)
    assert sim.day() == 6
    assert sim.state().day == 6


def test_the_daily_spending_is_reset_at_the_day_boundary(tmp_path: Path) -> None:
    """The counter reports the spending of the current day only."""
    path = _write_decaying_document(tmp_path)
    sim = WorldSim.load(path)

    sim.advance(TALK_MARTA)
    assert sim.resources().spent_on("RES_FOOD") == 1

    sim.advance_to(TICKS_PER_DAY)
    assert sim.resources().spent_on("RES_FOOD") == 0


def test_the_daily_spending_is_reset_when_waiting_crosses_a_day(tmp_path: Path) -> None:
    """Waiting for a whole day also resets the counter."""
    path = _write_decaying_document(tmp_path)
    sim = WorldSim.load(path)

    sim.advance(TALK_MARTA)
    sim.advance_to(TICKS_PER_DAY)
    assert sim.resources().spent_on("RES_FOOD") == 0


def test_the_decay_clamps_to_zero(tmp_path: Path) -> None:
    """A town that eats more than it has ends up at zero, never below."""
    path = _write_decaying_document(tmp_path, daily_decay=9)
    sim = WorldSim.load(path)

    sim.advance_to(TOTAL_TICKS)
    assert sim.resources().amount("RES_FOOD") == 0


def test_acting_and_waiting_reach_the_same_stock(tmp_path: Path) -> None:
    """The order of the payment and the decay is deterministic.

    The action that crosses the boundary is paid at its usual price and the
    decay of the new day is applied afterwards. A player who acts on the
    last tick of a day therefore pays exactly the same as a player who
    waits for it, plus the price of the action.
    """
    path = _write_decaying_document(tmp_path)
    acting = WorldSim.load(path)
    waiting = WorldSim.load(path)

    acting.advance(TALK_MARTA)
    acting.advance_to(TICKS_PER_DAY)
    waiting.advance_to(TICKS_PER_DAY)

    # The waiting player only pays the decay, the acting player also pays
    # the price of the one action.
    assert waiting.resources().amount("RES_FOOD") == 18
    assert acting.resources().amount("RES_FOOD") == 17


# ----------------------------------------------------------------------
# Reset
# ----------------------------------------------------------------------


def test_reset_restores_the_initial_provisions(tmp_path: Path) -> None:
    """A run can be restarted without reloading the content."""
    path = _write_decaying_document(tmp_path)
    sim = WorldSim.load(path)

    sim.advance(TALK_MARTA)
    sim.advance_to(TICKS_PER_DAY)
    assert sim.resources().amount("RES_FOOD") < 20

    sim.reset()
    assert sim.resources().amount("RES_FOOD") == 20
    assert sim.resources().spent_on("RES_FOOD") == 0
    assert sim.tick() == 0
    assert sim.decisions() == ()


def test_reset_restores_the_clock_and_the_flags(tmp_path: Path) -> None:
    """The reset rewinds the whole run."""
    path = _write_decaying_document(tmp_path)
    sim = WorldSim.load(path)

    sim.advance(TALK_MARTA)
    assert sim.state().has_flag("talked:NPC_MARTA")

    sim.reset()
    assert sim.state().flags == frozenset()
    assert sim.state().tick == 0


def test_reset_keeps_the_content(tmp_path: Path) -> None:
    """The reset does not unload the world."""
    path = _write_decaying_document(tmp_path)
    sim = WorldSim.load(path)

    sim.reset()
    assert sim.npc("NPC_MARTA").name == "Marta"
    assert len(sim.resource_specs()) == 1


# ----------------------------------------------------------------------
# The new fields of the specifications
# ----------------------------------------------------------------------


def test_load_reads_the_daily_decay_of_a_resource(tmp_path: Path) -> None:
    """The decay of a resource is part of its specification."""
    path = _write_decaying_document(tmp_path, daily_decay=3)
    sim = WorldSim.load(path)

    spec = sim.resource_specs()[0]
    assert spec.daily_decay == 3


def test_load_reads_the_blocked_actions_of_a_resource(tmp_path: Path) -> None:
    """The gated actions of a resource are part of its specification."""
    path = _write_resource_document(
        tmp_path,
        [
            {
                "id": "RES_FUEL",
                "label": "Fuel",
                "initial": 8,
                "per_action": 1,
                "critical_at": 2,
                "daily_decay": 1,
                "blocks_actions": ["prepare_sample"],
            }
        ],
    )
    sim = WorldSim.load(path)

    spec = sim.resource_specs()[0]
    assert spec.blocks_actions == ("prepare_sample",)


def test_load_defaults_the_new_fields_of_a_resource(tmp_path: Path) -> None:
    """A document written before those fields existed still loads."""
    path = _write_resource_document(
        tmp_path,
        [{"id": "RES_FOOD", "label": "Food", "initial": 5, "per_action": 1, "critical_at": 2}],
    )
    sim = WorldSim.load(path)

    spec = sim.resource_specs()[0]
    assert spec.daily_decay == 0
    assert spec.blocks_actions == ()


def test_load_rejects_a_non_integer_daily_decay(tmp_path: Path) -> None:
    """The decay of a resource must be an integer."""
    path = _write_resource_document(
        tmp_path,
        [
            {
                "id": "RES_FOOD",
                "label": "Food",
                "initial": 5,
                "per_action": 1,
                "critical_at": 2,
                "daily_decay": "2",
            }
        ],
    )
    with pytest.raises(WorldContentError, match="daily_decay must be an integer"):
        WorldSim.load(path)


def test_load_rejects_a_negative_daily_decay(tmp_path: Path) -> None:
    """The town cannot consume a negative amount."""
    path = _write_resource_document(
        tmp_path,
        [
            {
                "id": "RES_FOOD",
                "label": "Food",
                "initial": 5,
                "per_action": 1,
                "critical_at": 2,
                "daily_decay": -1,
            }
        ],
    )
    with pytest.raises(WorldContentError, match="daily_decay must be >= 0"):
        WorldSim.load(path)


def test_load_rejects_a_blocked_actions_field_that_is_not_a_list(tmp_path: Path) -> None:
    """The gated actions must be a list."""
    path = _write_resource_document(
        tmp_path,
        [
            {
                "id": "RES_FOOD",
                "label": "Food",
                "initial": 5,
                "per_action": 1,
                "critical_at": 2,
                "blocks_actions": "prepare_sample",
            }
        ],
    )
    with pytest.raises(WorldContentError, match="blocks_actions must be a list of strings"):
        WorldSim.load(path)


def test_load_rejects_a_blocked_actions_field_with_a_non_string(tmp_path: Path) -> None:
    """Every gated action must be named by a string."""
    path = _write_resource_document(
        tmp_path,
        [
            {
                "id": "RES_FOOD",
                "label": "Food",
                "initial": 5,
                "per_action": 1,
                "critical_at": 2,
                "blocks_actions": [7],
            }
        ],
    )
    with pytest.raises(WorldContentError, match="blocks_actions must be a list of strings"):
        WorldSim.load(path)


def test_load_rejects_duplicated_blocked_actions(tmp_path: Path) -> None:
    """A gated action must not be listed twice."""
    path = _write_resource_document(
        tmp_path,
        [
            {
                "id": "RES_FOOD",
                "label": "Food",
                "initial": 5,
                "per_action": 1,
                "critical_at": 2,
                "blocks_actions": ["prepare_sample", "prepare_sample"],
            }
        ],
    )
    with pytest.raises(WorldContentError, match="duplicated blocked action kinds"):
        WorldSim.load(path)
