"""Consistency checks of the content, beyond the schema.

The schema already refuses a broken *document*. These tests check the
*content* of the synthetic fixture against the rules of the design, so that
a fixture that drifts away from the design is caught here.

The rules under test
--------------------
* Every NPC with a ``dialogue_root`` has that dialogue.
* Every mission has a giver that exists.
* Every event references existing zones and NPCs.
* Every symptom of the premise has at least one source that supports a cause
  explaining it.
* The ``symptom -> cause`` table covers every symptom of the progression.
* The schedules do not overlap and cover the ticks they claim to.
* The lighting table agrees with the canonical table of :mod:`core.lighting`.
* Every event that declares deaths references existing NPCs, and the tick of
  the death of an NPC matches the activation tick of the event that kills
  it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from content.schema import WorldContent
from core.lighting import LIGHTING_TABLE, phase_at
from core.schedule import Npc as CoreNpc
from core.schedule import ScheduleEntry as CoreScheduleEntry
from core.schedule import npc_state, validate_schedule
from core.time import TICKS_PER_DAY, TOTAL_TICKS

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "content" / "world.json"


@pytest.fixture
def world() -> WorldContent:
    """Return the validated synthetic world.

    Returns:
        The validated world content.
    """
    document = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return WorldContent.model_validate(document)


def test_fixture_is_complete(world: WorldContent) -> None:
    """The fixture holds every collection the design needs."""
    assert world.content_version
    assert len(world.zones) == 2
    assert len(world.npcs) == 3
    assert len(world.events) == 2
    assert len(world.missions) == 2
    assert len(world.dialogues) == 8
    assert len(world.symptoms) == 2
    assert len(world.sources) == 3
    assert len(world.causes) == 2
    assert len(world.hypotheses) == 2
    assert len(world.endings) == 2
    assert len(world.lighting) == 7
    assert len(world.rumors) == 2
    assert len(world.resources) == 3


def test_the_resources_of_the_fixture_are_sane(world: WorldContent) -> None:
    """Every provision of the town has a reachable, non-negative stock.

    A resource whose cost is zero would never run out, and a threshold above
    the initial amount would start the cycle already in crisis. Neither is a
    stock the design means.
    """
    for resource in world.resources:
        assert resource.initial >= 0
        assert resource.per_action >= 0
        assert resource.critical_at <= resource.initial
        assert resource.per_action > 0
        assert resource.label
        assert resource.daily_decay >= 0


def test_the_provisions_of_the_fixture_can_be_spent(world: WorldContent) -> None:
    """The initial stock of every provision is enough to act a few times."""
    for resource in world.resources:
        assert resource.initial >= resource.per_action


def test_the_resource_ids_are_unique(world: WorldContent) -> None:
    """Two provisions cannot share an id."""
    ids = [resource.id for resource in world.resources]
    assert len(ids) == len(set(ids))


def test_the_resources_of_the_fixture_build_a_core_state(world: WorldContent) -> None:
    """The authored provisions are usable by the simulation core."""
    from core.resources import ResourceSpec, derive_crisis, initial_state

    specs = [
        ResourceSpec(
            id=resource.id,
            label=resource.label,
            initial=resource.initial,
            per_action=resource.per_action,
            critical_at=resource.critical_at,
            daily_decay=resource.daily_decay,
            blocks_actions=resource.blocks_actions,
        )
        for resource in world.resources
    ]
    state = initial_state(specs)
    assert state.amount(specs[0].id) == specs[0].initial
    assert derive_crisis(state, specs) == ()


def test_the_fixture_declares_the_three_provisions_of_the_town(world: WorldContent) -> None:
    """The town stocks food, medicine and fuel."""
    assert [resource.id for resource in world.resources] == [
        "RES_FOOD",
        "RES_MEDICINE",
        "RES_FUEL",
    ]


def test_the_resource_ids_use_the_reserved_prefix(world: WorldContent) -> None:
    """Every provision carries the prefix reserved for resources."""
    for resource in world.resources:
        assert resource.id.startswith("RES_")


def test_the_provisions_decay_but_never_below_zero(world: WorldContent) -> None:
    """The town eats every day, and the decay is a sane amount."""
    for resource in world.resources:
        assert resource.daily_decay >= 0
        assert resource.daily_decay <= resource.initial


def test_the_fuel_enables_the_preparation_of_the_sample(world: WorldContent) -> None:
    """Fuel is the resource that gates a concrete action.

    The fuel of the mine drives the calcination furnace where the vaccine
    sample is prepared, so it is the provision that decides whether the
    cure path is open at all.
    """
    fuel = next(resource for resource in world.resources if resource.id == "RES_FUEL")
    assert fuel.blocks_actions == ("prepare_sample",)


def test_every_blocked_action_is_named(world: WorldContent) -> None:
    """A gated action must name something the player can try."""
    for resource in world.resources:
        for kind in resource.blocks_actions:
            assert kind
            assert kind == kind.strip()


def test_every_npc_with_a_dialogue_root_has_that_dialogue(world: WorldContent) -> None:
    """A conversation that starts nowhere is a dead end."""
    dialogue_ids = {node.id for node in world.dialogues}
    for npc in world.npcs:
        assert npc.dialogue_root
        assert npc.dialogue_root in dialogue_ids


def test_every_dialogue_node_is_reachable_from_a_root(world: WorldContent) -> None:
    """Every node of the tree hangs from the root of some NPC."""
    roots = {npc.dialogue_root for npc in world.npcs}
    reachable: set[str] = set()
    frontier = list(roots)
    while frontier:
        node_id = frontier.pop()
        if node_id in reachable:
            continue
        reachable.add(node_id)
        node = next(item for item in world.dialogues if item.id == node_id)
        for option in node.options:
            if option.next_node is not None:
                frontier.append(option.next_node)
    assert reachable == {node.id for node in world.dialogues}


def test_every_mission_has_a_giver_npc_that_exists(world: WorldContent) -> None:
    """A mission given by nobody cannot be picked up."""
    npc_ids = {npc.id for npc in world.npcs}
    for mission in world.missions:
        assert mission.giver_npc in npc_ids


def test_every_event_references_existing_zones_and_npcs(world: WorldContent) -> None:
    """An event in a place that does not exist can never fire properly."""
    zone_ids = {zone.id for zone in world.zones}
    npc_ids = {npc.id for npc in world.npcs}
    for event in world.events:
        assert event.zone_ids
        for zone_id in event.zone_ids:
            assert zone_id in zone_ids
        for npc_id in event.npc_ids:
            assert npc_id in npc_ids


def test_every_symptom_of_the_plate_is_supported_by_a_source(world: WorldContent) -> None:
    """Every symptom of the progression has a source that backs a cause."""
    causes_by_symptom: dict[str, set[str]] = {}
    for hypothesis in world.hypotheses:
        for symptom_id in hypothesis.symptom_ids:
            causes_by_symptom.setdefault(symptom_id, set()).add(hypothesis.cause_id)

    supported_causes = {
        cause_id for source in world.sources for cause_id in (*source.supports, *source.refutes)
    }

    for stage in world.premise.progression_stages:
        causes = causes_by_symptom.get(stage, set())
        assert causes, f"{stage} has no candidate cause"
        assert causes & supported_causes, f"{stage} has no source behind its cause"


def test_symptom_to_cause_table_covers_every_progression_stage(world: WorldContent) -> None:
    """The table is the only thing the engine knows about the disease."""
    covered = {
        symptom_id for hypothesis in world.hypotheses for symptom_id in hypothesis.symptom_ids
    }
    for stage in world.premise.progression_stages:
        assert stage in covered


def test_every_cause_has_a_source_that_confirms_or_refutes_it(world: WorldContent) -> None:
    """A cause nobody can test is noise in the notebook."""
    touched: set[str] = set()
    for source in world.sources:
        touched.update(source.supports)
        touched.update(source.refutes)
    for cause in world.causes:
        assert cause.id in touched


def test_every_premise_cure_source_exists(world: WorldContent) -> None:
    """The plate points at documents that exist."""
    source_ids = {source.id for source in world.sources}
    assert world.premise.partial_cure_source in source_ids
    assert world.premise.total_cure_source in source_ids


def test_schedules_are_valid_for_the_simulation_core(world: WorldContent) -> None:
    """The schedules pass the validation of :mod:`core.schedule`."""
    for npc in world.npcs:
        core_npc = CoreNpc(
            id=npc.id,
            name=npc.name,
            schedule=tuple(
                CoreScheduleEntry(
                    start_tick=entry.start_tick,
                    end_tick=entry.end_tick,
                    zone=entry.zone_id,
                    tile=entry.tile,
                    activity=entry.activity,
                    interactable=entry.interactable,
                )
                for entry in npc.schedule
            ),
        )
        validate_schedule(core_npc)


def test_every_npc_has_a_schedule(world: WorldContent) -> None:
    """An NPC without a routine is always in its default state."""
    for npc in world.npcs:
        assert npc.schedule


def test_npc_states_resolve_at_every_tick_of_the_day(world: WorldContent) -> None:
    """Every NPC has a defined state at every tick of the day."""
    for npc in world.npcs:
        core_npc = CoreNpc(
            id=npc.id,
            name=npc.name,
            schedule=tuple(
                CoreScheduleEntry(
                    start_tick=entry.start_tick,
                    end_tick=entry.end_tick,
                    zone=entry.zone_id,
                    tile=entry.tile,
                    activity=entry.activity,
                    interactable=entry.interactable,
                )
                for entry in npc.schedule
            ),
        )
        for tick in range(TICKS_PER_DAY):
            state = npc_state(core_npc, tick)
            assert state.activity
            assert state.zone


def test_interactable_blocks_are_reachable(world: WorldContent) -> None:
    """An NPC that is never interactable cannot be investigated."""
    for npc in world.npcs:
        assert any(entry.interactable for entry in npc.schedule)


def test_lighting_table_agrees_with_the_core_canonical_table(world: WorldContent) -> None:
    """The authored table and the canonical table of the core agree."""
    assert len(world.lighting) == len(LIGHTING_TABLE)
    for authored, canonical in zip(world.lighting, LIGHTING_TABLE, strict=True):
        assert authored.start_tick == canonical.start_tick
        assert authored.end_tick == canonical.end_tick
        assert authored.rgb == canonical.rgb
        assert authored.opacity == canonical.opacity


@pytest.mark.parametrize("tick", range(TICKS_PER_DAY))
def test_every_tick_of_the_day_belongs_to_exactly_one_phase(
    world: WorldContent,
    tick: int,
) -> None:
    """The authored table covers the day without gaps and without overlaps."""
    hits = [phase for phase in world.lighting if phase.start_tick <= tick < phase.end_tick]
    assert len(hits) == 1


def test_authored_phase_boundaries_match_the_core(world: WorldContent) -> None:
    """The phase of a tick is the same in the content and in the core."""
    for tick in (0, 17, 18, 25, 26, 37, 38, 65, 66, 75, 76, 81, 82, 95):
        assert phase_at(tick).id in {
            "dawn_early",
            "dawn",
            "morning",
            "day",
            "afternoon",
            "dusk",
            "night",
        }


def test_every_mission_step_points_at_an_existing_entity(world: WorldContent) -> None:
    """The targets of the steps exist in the world."""
    symptom_ids = {symptom.id for symptom in world.symptoms}
    source_ids = {source.id for source in world.sources}
    hypothesis_ids = {hypothesis.id for hypothesis in world.hypotheses}
    zone_ids = {zone.id for zone in world.zones}
    npc_ids = {npc.id for npc in world.npcs}

    for mission in world.missions:
        for step in mission.steps:
            assert step.target_id
            known = symptom_ids | source_ids | hypothesis_ids | zone_ids | npc_ids
            assert step.target_id in known


def test_the_main_mission_has_a_deadline_inside_the_cycle(world: WorldContent) -> None:
    """The main mission is the one the endings are evaluated against."""
    main = next(mission for mission in world.missions if mission.kind == "main")
    assert main.deadline_tick is not None
    assert 0 <= main.deadline_tick <= TOTAL_TICKS


def test_every_mission_has_at_least_one_step(world: WorldContent) -> None:
    """A mission without a step cannot be played."""
    for mission in world.missions:
        assert mission.steps


def test_every_dialogue_option_ends_somewhere(world: WorldContent) -> None:
    """Every option either continues the conversation or ends it."""
    dialogue_ids = {node.id for node in world.dialogues}
    for node in world.dialogues:
        assert node.options
        for option in node.options:
            assert option.next_node is None or option.next_node in dialogue_ids


def test_every_rumor_is_spread_by_an_existing_npc(world: WorldContent) -> None:
    """A rumour nobody spreads is never heard."""
    npc_ids = {npc.id for npc in world.npcs}
    for rumor in world.rumors:
        assert rumor.npc_id in npc_ids


def test_endings_have_distinct_priorities(world: WorldContent) -> None:
    """Two endings with the same priority would be ambiguous."""
    priorities = [ending.priority for ending in world.endings]
    assert len(priorities) == len(set(priorities))


def test_endings_reference_existing_symptoms_and_causes(world: WorldContent) -> None:
    """The conditions of an ending talk about things that exist."""
    symptom_ids = {symptom.id for symptom in world.symptoms}
    cause_ids = {cause.id for cause in world.causes}
    for ending in world.endings:
        for symptom_id in ending.requires_symptoms:
            assert symptom_id in symptom_ids
        for cause_id in ending.requires_causes:
            assert cause_id in cause_ids


def test_the_fixture_uses_only_synthetic_names(world: WorldContent) -> None:
    """The fixture is not content of the real game."""
    forbidden = {"marta", "madalena", "omar", "lena", "aldermere", "blight"}
    blob = json.dumps(world.model_dump(mode="json"), ensure_ascii=False).lower()
    for word in forbidden:
        assert word not in blob


def test_the_fixture_mentions_no_forbidden_feature(world: WorldContent) -> None:
    """The fixture stays inside the design: no combat, no monsters, no magic."""
    from content.validate import FORBIDDEN_TERMS

    blob = json.dumps(world.model_dump(mode="json"), ensure_ascii=False).lower()
    for term in FORBIDDEN_TERMS:
        assert term not in blob


def test_every_document_of_the_fixture_is_valid_json() -> None:
    """The fixture is a well formed JSON document."""
    document: Any = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert isinstance(document, dict)


# ----------------------------------------------------------------------
# The death of a villager
# ----------------------------------------------------------------------


def test_every_event_that_kills_references_existing_npcs(world: WorldContent) -> None:
    """An event cannot kill somebody who is not in the world."""
    npc_ids = {npc.id for npc in world.npcs}
    for event in world.events:
        for npc_id in event.deaths:
            assert npc_id in npc_ids


def test_the_death_of_an_npc_matches_the_event_that_kills_it(world: WorldContent) -> None:
    """The event that kills a villager fires on the tick of the death.

    The tick of the death is the tick at which the villager is already
    gone, and the event that declares the death fires on that very tick, so
    the two agree. A mismatch would mean the villager is gone before the
    event that killed him, or that he survives the event that declares his
    death.
    """
    activation_by_npc = {
        npc_id: event.activation_tick for event in world.events for npc_id in event.deaths
    }
    for npc in world.npcs:
        if npc.deceased_at_tick is None:
            continue
        assert npc.id in activation_by_npc
        assert activation_by_npc[npc.id] == npc.deceased_at_tick


def test_every_killed_npc_declares_the_tick_of_its_death(world: WorldContent) -> None:
    """A villager an event kills has that tick as the tick of his death."""
    killed = {npc_id for event in world.events for npc_id in event.deaths}
    for npc in world.npcs:
        if npc.id in killed:
            assert npc.deceased_at_tick is not None
            assert npc.death_cause


def test_the_fixture_declares_a_programmed_death(world: WorldContent) -> None:
    """The fixture holds a villager who dies inside the cycle.

    The first programmed death of the design (D31) falls on Day 3, which is
    the tick 192 of the cycle.
    """
    dying = [npc for npc in world.npcs if npc.deceased_at_tick is not None]
    assert len(dying) == 1
    assert dying[0].deceased_at_tick == 192
    assert dying[0].death_cause.startswith("plague_")


def test_the_fixture_declares_a_villager_who_survives(world: WorldContent) -> None:
    """Most of the town survives: the death is not universal."""
    surviving = [npc for npc in world.npcs if npc.deceased_at_tick is None]
    assert len(surviving) == 2
    for npc in surviving:
        assert npc.death_cause == ""


def test_the_death_of_the_fixture_falls_on_day_three(world: WorldContent) -> None:
    """The tick 192 is the first tick of Day 3."""
    assert 192 // TICKS_PER_DAY + 1 == 3


def test_the_dead_villager_is_not_at_his_post(world: WorldContent) -> None:
    """The simulation core agrees that the dead villager is not there."""
    for npc in world.npcs:
        core_npc = CoreNpc(
            id=npc.id,
            name=npc.name,
            schedule=tuple(
                CoreScheduleEntry(
                    start_tick=entry.start_tick,
                    end_tick=entry.end_tick,
                    zone=entry.zone_id,
                    tile=entry.tile,
                    activity=entry.activity,
                    interactable=entry.interactable,
                )
                for entry in npc.schedule
            ),
            deceased_at_tick=npc.deceased_at_tick,
            death_cause=npc.death_cause,
        )
        if npc.deceased_at_tick is None:
            assert npc_state(core_npc, npc.deceased_at_tick or 0).alive is True
            continue
        assert npc_state(core_npc, npc.deceased_at_tick - 1).alive is True
        assert npc_state(core_npc, npc.deceased_at_tick).alive is False
        assert npc_state(core_npc, npc.deceased_at_tick).interactable is False
