"""Tests for the composition root.

:class:`WorldSim` is the object the presentation layer talks to. The tests
below check that it loads the content, derives the state, consumes exactly one
tick per valid action, rejects invalid actions **without** consuming a tick
and that the same sequence of actions always produces the same world.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.lighting import LightState
from core.schedule import NpcState
from core.state import Decision, WorldState
from core.time import TOTAL_TICKS, ClockOverflowError, to_tick
from core.world import InvalidActionError, WorldContentError, WorldSim

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "minimal_world.json"

TALK_MARTA = Decision(kind="talk", target="NPC_MARTA", tick=0, payload={})
TALK_OMAR = Decision(kind="talk", target="NPC_OMAR", tick=0, payload={})
REPORT = Decision(
    kind="report_symptom",
    target="NPC_MARTA",
    tick=0,
    payload={"symptom": "SYM_FEVER"},
)


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
