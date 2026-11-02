"""Tests for the daily schedules of the NPCs.

The state of an NPC is a pure function of the tick. The tests below pin down
the three acceptance instants (07:00, 16:00 and 23:00), the repetition of the
daily pattern, the behaviour outside the schedule and the rejection of
overlapping blocks.

The tests of the last section pin down the **irreversible death** of an NPC:
a dead villager is not at their post, not interactable and not resolved
against their schedule.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.schedule import (
    DEFAULT_ZONE,
    Npc,
    ScheduleEntry,
    ScheduleOverlapError,
    is_available,
    is_dead,
    npc_state,
)
from core.time import TICKS_PER_DAY, TOTAL_TICKS, to_tick

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "minimal_world.json"


def _load_fixture() -> dict[str, object]:
    """Read the minimal world fixture."""
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _npc_from_fixture(npc_id: str) -> Npc:
    """Build an NPC from the minimal world fixture.

    Args:
        npc_id: Id of the NPC to build.

    Returns:
        The NPC with its schedule.

    Raises:
        KeyError: If the fixture does not contain that NPC.
    """
    document = _load_fixture()
    for raw in document["npcs"]:  # type: ignore[index]
        if raw["id"] == npc_id:
            return Npc(
                id=raw["id"],
                name=raw["name"],
                schedule=tuple(
                    ScheduleEntry(
                        start_tick=entry["start_tick"],
                        end_tick=entry["end_tick"],
                        zone=entry["zone"],
                        tile=(entry["tile"][0], entry["tile"][1]),
                        activity=entry["activity"],
                        interactable=entry["interactable"],
                    )
                    for entry in raw["schedule"]
                ),
            )
    raise KeyError(npc_id)


MARTA = _npc_from_fixture("NPC_MARTA")
OMAR = _npc_from_fixture("NPC_OMAR")
LENA = _npc_from_fixture("NPC_LENA")

TICK_0700 = to_tick(1, 7, 0)
TICK_1600 = to_tick(1, 16, 0)
TICK_2300 = to_tick(1, 23, 0)


def test_marta_is_selling_fish_at_seven() -> None:
    """At 07:00 Marta is at the harbour, selling fish, and can be talked to."""
    state = npc_state(MARTA, TICK_0700)
    assert state.zone == "ZONE_PORT"
    assert state.tile == (12, 7)
    assert state.activity == "selling_fish"
    assert state.interactable is True


def test_marta_is_resting_at_sixteen() -> None:
    """At 16:00 Marta has moved on to repairing the boat."""
    state = npc_state(MARTA, TICK_1600)
    assert state.zone == "ZONE_PORT"
    assert state.tile == (13, 7)
    assert state.activity == "repairing_boat"
    assert state.interactable is True


def test_marta_is_not_interactable_at_night() -> None:
    """At 23:00 nobody in the fixture is interactable."""
    state = npc_state(MARTA, TICK_2300)
    assert state.zone == "ZONE_TAVERN"
    assert state.activity == "resting"
    assert state.interactable is False


def test_omar_is_selling_bread_at_seven() -> None:
    """At 07:00 Omar is asleep in the tavern."""
    state = npc_state(OMAR, TICK_0700)
    assert state.zone == "ZONE_TAVERN"
    assert state.activity == "sleeping"
    assert state.interactable is False


def test_omar_is_delivering_bread_at_sixteen() -> None:
    """At 16:00 Omar is delivering bread in the market."""
    state = npc_state(OMAR, TICK_1600)
    assert state.zone == "ZONE_MARKET"
    assert state.tile == (5, 3)
    assert state.activity == "delivering_bread"
    assert state.interactable is True


def test_omar_is_not_interactable_at_night() -> None:
    """At 23:00 Omar is resting and cannot be talked to."""
    state = npc_state(OMAR, TICK_2300)
    assert state.interactable is False


def test_lena_is_tallying_cargo_at_seven() -> None:
    """At 07:00 Lena is sorting produce in the market."""
    state = npc_state(LENA, TICK_0700)
    assert state.zone == "ZONE_MARKET"
    assert state.activity == "sorting_produce"
    assert state.interactable is True


def test_lena_is_greeting_customers_at_sixteen() -> None:
    """At 16:00 Lena is back in the market, greeting customers."""
    state = npc_state(LENA, TICK_1600)
    assert state.zone == "ZONE_MARKET"
    assert state.tile == (7, 4)
    assert state.activity == "greeting_customers"
    assert state.interactable is True


def test_lena_is_not_interactable_at_night() -> None:
    """At 23:00 Lena has closed the market stall."""
    state = npc_state(LENA, TICK_2300)
    assert state.activity == "closing_up"
    assert state.interactable is False


def test_no_npc_is_interactable_at_night() -> None:
    """The acceptance criterion: nobody is interactable at 23:00."""
    for npc in (MARTA, OMAR, LENA):
        assert is_available(npc, TICK_2300) is False


@pytest.mark.parametrize("npc", [pytest.param(MARTA, id="marta"), pytest.param(OMAR, id="omar")])
def test_schedule_repeats_every_day(npc: Npc) -> None:
    """The daily pattern repeats: tick 28 and tick 124 resolve identically."""
    assert npc_state(npc, 28) == npc_state(npc, 28 + TICKS_PER_DAY)
    assert npc_state(npc, 28) == npc_state(npc, 28 + 2 * TICKS_PER_DAY)


@pytest.mark.parametrize("npc", [pytest.param(MARTA, id="marta"), pytest.param(OMAR, id="omar")])
def test_schedule_repeats_for_every_tick_of_the_day(npc: Npc) -> None:
    """For every tick of a day, the state three days later is the same."""
    for tick in range(TICKS_PER_DAY):
        assert npc_state(npc, tick) == npc_state(npc, tick + 3 * TICKS_PER_DAY)


def test_is_available_agrees_with_npc_state() -> None:
    """``is_available`` is the interactability of the resolved state."""
    for tick in range(TICKS_PER_DAY):
        assert is_available(MARTA, tick) == npc_state(MARTA, tick).interactable


def test_schedule_block_end_is_exclusive() -> None:
    """A block covers its start tick but not its end tick."""
    assert npc_state(MARTA, 52).activity == "eating"
    assert npc_state(MARTA, 51).activity == "selling_fish"


def test_npc_outside_its_schedule_falls_back_to_the_default() -> None:
    """Without a covering block the NPC is idle and not interactable."""
    npc = Npc(
        id="NPC_GAP",
        name="Gap",
        schedule=(
            ScheduleEntry(
                start_tick=10,
                end_tick=20,
                zone="ZONE_PORT",
                tile=(1, 1),
                activity="working",
                interactable=True,
            ),
        ),
    )
    state = npc_state(npc, 0)
    assert state.zone == DEFAULT_ZONE
    assert state.activity == "idle"
    assert state.interactable is False


def test_explicit_default_block_is_used_as_the_fallback() -> None:
    """A schedule may declare its own default block."""
    npc = Npc(
        id="NPC_DEFAULT",
        name="Default",
        schedule=(
            ScheduleEntry(
                start_tick=10,
                end_tick=20,
                zone="ZONE_PORT",
                tile=(1, 1),
                activity="working",
                interactable=True,
            ),
            ScheduleEntry(
                start_tick=0,
                end_tick=1,
                zone=DEFAULT_ZONE,
                tile=(0, 0),
                activity="off_screen",
                interactable=False,
            ),
        ),
    )
    state = npc_state(npc, 50)
    assert state.zone == DEFAULT_ZONE
    assert state.activity == "off_screen"
    assert state.interactable is False


def test_npc_state_rejects_negative_ticks() -> None:
    """A negative tick is a programming error."""
    with pytest.raises(ValueError, match="tick must be >= 0"):
        npc_state(MARTA, -1)


def test_npc_state_rejects_non_integer_ticks() -> None:
    """A non-integer tick is a programming error."""
    with pytest.raises(TypeError, match="tick must be an int"):
        npc_state(MARTA, 1.5)  # type: ignore[arg-type]


def test_overlapping_schedule_blocks_are_rejected() -> None:
    """Two blocks covering the same tick make the state ambiguous."""
    npc = Npc(
        id="NPC_OVERLAP",
        name="Overlap",
        schedule=(
            ScheduleEntry(
                start_tick=0,
                end_tick=30,
                zone="ZONE_PORT",
                tile=(1, 1),
                activity="working",
                interactable=True,
            ),
            ScheduleEntry(
                start_tick=20,
                end_tick=40,
                zone="ZONE_MARKET",
                tile=(2, 2),
                activity="resting",
                interactable=False,
            ),
        ),
    )
    with pytest.raises(ScheduleOverlapError, match="overlaps"):
        from core.schedule import validate_schedule

        validate_schedule(npc)


def test_back_to_back_schedule_blocks_are_allowed() -> None:
    """Blocks that touch without overlapping are valid."""
    npc = Npc(
        id="NPC_ADJACENT",
        name="Adjacent",
        schedule=(
            ScheduleEntry(
                start_tick=0,
                end_tick=20,
                zone="ZONE_PORT",
                tile=(1, 1),
                activity="working",
                interactable=True,
            ),
            ScheduleEntry(
                start_tick=20,
                end_tick=40,
                zone="ZONE_MARKET",
                tile=(2, 2),
                activity="resting",
                interactable=False,
            ),
        ),
    )
    from core.schedule import validate_schedule

    validate_schedule(npc)


def test_schedule_blocks_must_stay_inside_the_day() -> None:
    """A block outside the day boundaries is rejected."""
    npc = Npc(
        id="NPC_OUT_OF_RANGE",
        name="Out of range",
        schedule=(
            ScheduleEntry(
                start_tick=0,
                end_tick=TICKS_PER_DAY + 1,
                zone="ZONE_PORT",
                tile=(1, 1),
                activity="working",
                interactable=True,
            ),
        ),
    )
    from core.schedule import validate_schedule

    with pytest.raises(ValueError, match="end_tick must be within"):
        validate_schedule(npc)


def test_inverted_schedule_blocks_are_rejected() -> None:
    """A block whose end precedes its start is rejected."""
    npc = Npc(
        id="NPC_INVERTED",
        name="Inverted",
        schedule=(
            ScheduleEntry(
                start_tick=30,
                end_tick=20,
                zone="ZONE_PORT",
                tile=(1, 1),
                activity="working",
                interactable=True,
            ),
        ),
    )
    from core.schedule import validate_schedule

    with pytest.raises(ValueError, match="must be lower than end_tick"):
        validate_schedule(npc)


def test_fixture_schedules_do_not_overlap() -> None:
    """The schedules of the fixture are valid."""
    from core.schedule import validate_schedule

    for npc in (MARTA, OMAR, LENA):
        validate_schedule(npc)


def test_npc_state_carries_the_npc_id() -> None:
    """The resolved state identifies the NPC it belongs to."""
    assert npc_state(MARTA, 0).npc_id == "NPC_MARTA"


def test_schedule_blocks_must_start_inside_the_day() -> None:
    """A block starting outside the day is rejected."""
    npc = Npc(
        id="NPC_BAD_START",
        name="Bad start",
        schedule=(
            ScheduleEntry(
                start_tick=TICKS_PER_DAY,
                end_tick=TICKS_PER_DAY + 10,
                zone="ZONE_PORT",
                tile=(1, 1),
                activity="working",
                interactable=True,
            ),
        ),
    )
    from core.schedule import validate_schedule

    with pytest.raises(ValueError, match="start_tick must be within"):
        validate_schedule(npc)


# ----------------------------------------------------------------------
# The irreversible death of an NPC
# ----------------------------------------------------------------------

#: Tick at which the villager of the death tests dies. It is the first tick
#: of Day 3, which is where the first programmed death of the design (D31)
#: falls.
DEATH_TICK = 192


def _dying_npc(deceased_at_tick: int | None = DEATH_TICK) -> Npc:
    """Build an NPC that dies at the given tick.

    The NPC is the miller of the fixture: it has a full schedule, so the
    tests can check that a dead NPC does not fall back to it.

    Args:
        deceased_at_tick: Tick of the death, or ``None`` for an immortal NPC.

    Returns:
        The NPC with its schedule and its death.
    """
    return Npc(
        id="NPC_DYING",
        name="The Dying",
        schedule=(
            ScheduleEntry(
                start_tick=0,
                end_tick=96,
                zone="ZONE_PORT",
                tile=(12, 7),
                activity="working",
                interactable=True,
            ),
        ),
        deceased_at_tick=deceased_at_tick,
        death_cause="plague_fever" if deceased_at_tick is not None else "",
    )


DYING = _dying_npc()


def test_an_npc_is_alive_the_tick_before_its_death() -> None:
    """The tick of the death is the tick at which the NPC is already gone."""
    assert npc_state(DYING, DEATH_TICK - 1).alive is True


def test_an_npc_is_dead_on_the_tick_of_its_death() -> None:
    """``deceased_at_tick`` is inclusive: the NPC is dead on that very tick."""
    assert npc_state(DYING, DEATH_TICK).alive is False


def test_a_dead_npc_is_not_interactable_on_any_tick() -> None:
    """A dead villager is not at their post, so nobody can talk to them."""
    for tick in (DEATH_TICK, DEATH_TICK + 1, TOTAL_TICKS):
        assert npc_state(DYING, tick).interactable is False
        assert is_available(DYING, tick) is False


def test_a_dead_npc_falls_back_to_the_default_state() -> None:
    """The schedule of a dead NPC is not resolved: they are simply not there."""
    state = npc_state(DYING, DEATH_TICK)
    assert state.zone == DEFAULT_ZONE
    assert state.tile == (0, 0)
    assert state.activity == "idle"
    assert state.alive is False


def test_a_dead_npc_does_not_keep_its_schedule() -> None:
    """The activity of a dead NPC is not the one its schedule declares."""
    assert npc_state(DYING, DEATH_TICK - 1).activity == "working"
    assert npc_state(DYING, DEATH_TICK).activity != "working"


def test_is_dead_reflects_the_resolution_of_the_state() -> None:
    """``is_dead`` agrees with the liveness of the resolved state."""
    for tick in range(0, TOTAL_TICKS + 1, 7):
        assert is_dead(DYING, tick) == (not npc_state(DYING, tick).alive)


def test_is_dead_is_false_before_the_tick_of_the_death() -> None:
    """The villager is alive up to the tick before the death."""
    assert is_dead(DYING, DEATH_TICK - 1) is False


def test_is_dead_is_true_on_and_after_the_tick_of_the_death() -> None:
    """The death is irreversible: it stays true for the rest of the cycle."""
    assert is_dead(DYING, DEATH_TICK) is True
    assert is_dead(DYING, DEATH_TICK + 1) is True
    assert is_dead(DYING, TOTAL_TICKS) is True


def test_an_npc_without_a_death_survives_the_whole_cycle() -> None:
    """An NPC with no death date lives until the end of the cycle."""
    immortal = _dying_npc(deceased_at_tick=None)
    assert immortal.deceased_at_tick is None
    assert immortal.death_cause == ""
    assert npc_state(immortal, TOTAL_TICKS - 1).alive is True
    assert is_dead(immortal, TOTAL_TICKS - 1) is False


def test_an_npc_without_a_death_is_alive_on_the_closing_tick() -> None:
    """The closing tick is a valid instant: the villager is still there."""
    immortal = _dying_npc(deceased_at_tick=None)
    assert npc_state(immortal, TOTAL_TICKS).alive is True
    assert is_dead(immortal, TOTAL_TICKS) is False


def test_a_living_npc_is_still_interactable_on_the_closing_tick() -> None:
    """A living NPC keeps its schedule until the closing tick."""
    immortal = _dying_npc(deceased_at_tick=None)
    assert npc_state(immortal, TOTAL_TICKS).interactable is True
    assert npc_state(immortal, TOTAL_TICKS).activity == "working"


def test_is_dead_rejects_negative_ticks() -> None:
    """A negative tick is a programming error."""
    with pytest.raises(ValueError, match="tick must be >= 0"):
        is_dead(DYING, -1)


def test_is_dead_rejects_non_integer_ticks() -> None:
    """A non-integer tick is a programming error."""
    with pytest.raises(TypeError, match="tick must be an int"):
        is_dead(DYING, 1.5)  # type: ignore[arg-type]


def test_a_dead_npc_is_not_at_its_post() -> None:
    """The zone of a dead NPC is not the one its schedule declares."""
    assert npc_state(DYING, DEATH_TICK - 1).zone == "ZONE_PORT"
    assert npc_state(DYING, DEATH_TICK).zone != "ZONE_PORT"
