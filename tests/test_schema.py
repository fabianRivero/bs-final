"""Tests for the pydantic content schemas.

What is under test
------------------
The content models are the gate between authored data (and the output of a
language model) and the simulation core. A model that accepts a broken
document would let a broken document reach Godot, so the validators are
tested both ways: the valid documents must be accepted, and every broken
document must be rejected **with a message that names the offending field**.

Conventions under test
----------------------
* Identifiers carry a prefix that states their type (``SYM_``, ``NPC_``...).
* Tick ranges are half-open: ``start`` is inclusive, ``end`` is exclusive.
* The ``TBD`` marker means "the design decision is still pending" and must
  be rejected by the premise plate.
* The lighting table covers the 96 ticks of a day, without gaps and without
  overlaps.
* The death of an NPC is declared by a tick **and** a cause, and the tick
  lies inside the cycle.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from content.schema import (
    DEATH_CAUSE_PREFIXES,
    Cause,
    CauseCategory,
    DialogueNode,
    DialogueOption,
    Ending,
    Event,
    Hypothesis,
    HypothesisStatus,
    LightingPhase,
    Mission,
    MissionStep,
    Npc,
    ObjectiveKind,
    Premise,
    ResourceSpec,
    Rumor,
    ScheduleEntry,
    Source,
    Symptom,
    WorldContent,
    Zone,
)
from core.time import total_ticks

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "content" / "world.json"
BASE_PREMISE_PATH = Path(__file__).parent.parent / "content" / "base" / "premise.json"

#: First tick outside the playable cycle, used by the range validators.
OUT_OF_RANGE_TICK = total_ticks() + 1


@pytest.fixture
def world_document() -> dict[str, Any]:
    """Return the synthetic world fixture as a plain dictionary.

    Returns:
        The decoded fixture document.
    """
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def valid_world(world_document: dict[str, Any]) -> WorldContent:
    """Return the validated synthetic world.

    Args:
        world_document: The raw fixture document.

    Returns:
        The validated world content.
    """
    return WorldContent.model_validate(world_document)


def _premise(**overrides: Any) -> dict[str, Any]:
    """Build a valid premise document.

    Args:
        overrides: Fields to override.

    Returns:
        The premise document.
    """
    document: dict[str, Any] = {
        "id": "PR_TEST",
        "title": "A test plate",
        "disease_name": "Test Wither",
        "symptom_signature": "Numbness in the hands.",
        "progression_stages": ["SYM_NUMBNESS"],
        "transmission_mode": "environmental exposure",
        "partial_cure_source": "SRC_HERBAL",
        "total_cure_source": "SRC_HERBAL",
        "responsible_actor": "The miller",
        "responsible_note": "A reasonable decision repeated.",
        "outcome_notes": "Four endings.",
    }
    document.update(overrides)
    return document


def _lighting_phases() -> list[dict[str, Any]]:
    """Build the canonical seven lighting phases.

    Returns:
        The phase documents.
    """
    spans = ((0, 18), (18, 26), (26, 38), (38, 66), (66, 76), (76, 82), (82, 96))
    return [
        {
            "id": f"LGT_PHASE_{index}",
            "start_tick": start,
            "end_tick": end,
            "rgb": [40, 50, 90],
            "opacity": 0.2,
            "palette_id": "day",
        }
        for index, (start, end) in enumerate(spans)
    ]


def _minimal_world(**overrides: Any) -> dict[str, Any]:
    """Build a world document that satisfies every cross-model rule.

    The document holds one symptom, one cause, one source and one hypothesis,
    which is the smallest set that passes the reference checks of
    :class:`WorldContent`.

    Args:
        overrides: Fields to override in the document.

    Returns:
        The world document.
    """
    document: dict[str, Any] = {
        "premise": _premise(),
        "symptoms": [
            {
                "id": "SYM_NUMBNESS",
                "label": "Numbness",
                "description": "Fingers go numb.",
            }
        ],
        "causes": [
            {
                "id": "CAUSE_MOULD",
                "label": "Moulded grain",
                "category": "fungus",
                "description": "Grain kept too long.",
            }
        ],
        "sources": [
            {
                "id": "SRC_HERBAL",
                "kind": "herbal",
                "title": "The herbal",
                "location": "On a shelf.",
                "supports": ["CAUSE_MOULD"],
            }
        ],
        "hypotheses": [
            {
                "id": "HYP_MOULD",
                "symptom_ids": ["SYM_NUMBNESS"],
                "cause_id": "CAUSE_MOULD",
            }
        ],
        "lighting": _lighting_phases(),
    }
    document.update(overrides)
    return document


# ----------------------------------------------------------------------
# Premise
# ----------------------------------------------------------------------


def test_valid_premise_is_accepted() -> None:
    """A complete premise plate validates."""
    premise = Premise.model_validate(_premise())
    assert premise.id == "PR_TEST"
    assert premise.progression_stages == ("SYM_NUMBNESS",)


@pytest.mark.parametrize(
    "field",
    [
        "title",
        "disease_name",
        "symptom_signature",
        "transmission_mode",
        "responsible_actor",
        "responsible_note",
        "outcome_notes",
    ],
)
def test_premise_rejects_tbd_marker(field: str) -> None:
    """A premise that still carries the TBD marker is rejected."""
    with pytest.raises(ValidationError) as error:
        Premise.model_validate(_premise(**{field: "TBD - pending design decision (P3)"}))
    assert field in str(error.value)
    assert "unresolved marker" in str(error.value)


@pytest.mark.parametrize("marker", ["TBD", "tbd", "Tbd", "TBD - pending"])
def test_premise_tbd_detection_is_case_insensitive(marker: str) -> None:
    """The TBD marker is detected whatever its case is."""
    with pytest.raises(ValidationError, match="unresolved marker"):
        Premise.model_validate(_premise(disease_name=marker))


def test_premise_accepts_words_that_merely_contain_tbd() -> None:
    """A word that merely contains the marker is not a marker."""
    premise = Premise.model_validate(_premise(disease_name="Tabby Syndrome"))
    assert premise.disease_name == "Tabby Syndrome"


def test_premise_rejects_tbd_inside_progression_stages() -> None:
    """A progression stage that is still pending is rejected."""
    with pytest.raises(ValidationError, match="unresolved marker"):
        Premise.model_validate(_premise(progression_stages=["TBD - pending design decision"]))


def test_premise_rejects_empty_progression() -> None:
    """A premise without a progression cannot drive the game."""
    with pytest.raises(ValidationError, match="at least one symptom id"):
        Premise.model_validate(_premise(progression_stages=[]))


def test_premise_rejects_unknown_field() -> None:
    """An unknown field is a typo, not a silently ignored value."""
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Premise.model_validate({**_premise(), "origin_category": "fungus"})


def test_premise_is_frozen() -> None:
    """A validated premise cannot be mutated."""
    premise = Premise.model_validate(_premise())
    with pytest.raises(ValidationError):
        premise.disease_name = "Something else"


def test_premise_requires_the_reserved_id_prefix() -> None:
    """The premise id must carry the PR_ prefix."""
    with pytest.raises(ValidationError, match="must start with 'PR_'"):
        Premise.model_validate(_premise(id="PREMISE_BLIGHT"))


# ----------------------------------------------------------------------
# Symptoms, sources, causes and hypotheses
# ----------------------------------------------------------------------


def test_valid_symptom_is_accepted() -> None:
    """A symptom with a reporter validates."""
    symptom = Symptom.model_validate(
        {
            "id": "SYM_FEVER",
            "label": "Fever",
            "description": "High temperature.",
            "source_npc": "NPC_MILLER",
            "reported_by": ["NPC_MILLER"],
            "observed_at_tick": 34,
        }
    )
    assert symptom.observed_at_tick == 34


def test_symptom_rejects_out_of_range_tick() -> None:
    """An observation tick outside the cycle is rejected."""
    with pytest.raises(ValidationError, match=r"observed_at_tick must be within"):
        Symptom.model_validate(
            {
                "id": "SYM_FEVER",
                "label": "Fever",
                "description": "High temperature.",
                "observed_at_tick": OUT_OF_RANGE_TICK,
            }
        )


def test_source_requires_a_known_kind() -> None:
    """The kind of a source is a closed vocabulary."""
    with pytest.raises(ValidationError, match="kind"):
        Source.model_validate(
            {
                "id": "SRC_BOOK",
                "kind": "newspaper",
                "title": "A paper",
                "location": "On a table.",
            }
        )


def test_source_rejects_out_of_range_readable_tick() -> None:
    """A readability tick outside the cycle is rejected."""
    with pytest.raises(ValidationError, match=r"readable_ticks must be within"):
        Source.model_validate(
            {
                "id": "SRC_BOOK",
                "kind": "book",
                "title": "A book",
                "location": "On a shelf.",
                "readable_ticks": [OUT_OF_RANGE_TICK],
            }
        )


def test_cause_requires_a_known_category() -> None:
    """The category of a cause is a closed vocabulary."""
    with pytest.raises(ValidationError, match="category"):
        Cause.model_validate(
            {
                "id": "CAUSE_MOULD",
                "label": "Mould",
                "category": "mildew",
                "description": "Something that grows.",
            }
        )


def test_cause_accepts_every_category() -> None:
    """Every category of the vocabulary is accepted."""
    for category in CauseCategory:
        cause = Cause.model_validate(
            {
                "id": "CAUSE_X",
                "label": "X",
                "category": category.value,
                "description": "Something.",
            }
        )
        assert cause.category is category


def test_hypothesis_requires_at_least_one_symptom() -> None:
    """A hypothesis that explains nothing is not a hypothesis."""
    with pytest.raises(ValidationError, match="at least one symptom id"):
        Hypothesis.model_validate(
            {
                "id": "HYP_X",
                "symptom_ids": [],
                "cause_id": "CAUSE_MOULD",
            }
        )


def test_hypothesis_status_vocabulary_is_closed() -> None:
    """The status of a hypothesis is a closed vocabulary."""
    with pytest.raises(ValidationError, match="status"):
        Hypothesis.model_validate(
            {
                "id": "HYP_X",
                "symptom_ids": ["SYM_FEVER"],
                "cause_id": "CAUSE_MOULD",
                "status": "maybe",
            }
        )


def test_hypothesis_accepts_every_status() -> None:
    """Every status of the vocabulary is accepted."""
    for status in HypothesisStatus:
        hypothesis = Hypothesis.model_validate(
            {
                "id": "HYP_X",
                "symptom_ids": ["SYM_FEVER"],
                "cause_id": "CAUSE_MOULD",
                "status": status.value,
            }
        )
        assert hypothesis.status is status


# ----------------------------------------------------------------------
# Zones and schedules
# ----------------------------------------------------------------------


def test_zone_rejects_non_positive_size() -> None:
    """A zone without area is rejected."""
    with pytest.raises(ValidationError, match="width must be > 0"):
        Zone.model_validate(
            {
                "id": "ZN_YARD",
                "name": "Yard",
                "tiles_path": "res://tiles.png",
                "width": 0,
                "height": 10,
            }
        )


def test_schedule_entry_rejects_inverted_range() -> None:
    """A block that ends before it starts is rejected."""
    with pytest.raises(ValidationError, match="must be lower than end_tick"):
        ScheduleEntry.model_validate(
            {
                "start_tick": 40,
                "end_tick": 20,
                "zone_id": "ZN_YARD",
                "tile": [1, 2],
                "activity": "idle",
            }
        )


def test_schedule_entry_rejects_end_beyond_the_day() -> None:
    """A block cannot end after the end of the day."""
    with pytest.raises(ValidationError, match=r"end_tick must be within \[1, 96\]"):
        ScheduleEntry.model_validate(
            {
                "start_tick": 40,
                "end_tick": 97,
                "zone_id": "ZN_YARD",
                "tile": [1, 2],
                "activity": "idle",
            }
        )


def test_schedule_entry_accepts_the_whole_day() -> None:
    """A block may cover the whole day."""
    entry = ScheduleEntry.model_validate(
        {
            "start_tick": 0,
            "end_tick": 96,
            "zone_id": "ZN_YARD",
            "tile": [1, 2],
            "activity": "idle",
        }
    )
    assert entry.end_tick == 96


def test_npc_rejects_overlapping_schedule_blocks() -> None:
    """Two blocks covering the same tick make the NPC state ambiguous."""
    with pytest.raises(ValidationError, match="schedule blocks overlap"):
        Npc.model_validate(
            {
                "id": "NPC_MILLER",
                "name": "The Miller",
                "schedule": [
                    {
                        "start_tick": 0,
                        "end_tick": 40,
                        "zone_id": "ZN_YARD",
                        "tile": [1, 2],
                        "activity": "sleeping",
                    },
                    {
                        "start_tick": 30,
                        "end_tick": 60,
                        "zone_id": "ZN_HALL",
                        "tile": [3, 4],
                        "activity": "reading",
                    },
                ],
            }
        )


def test_npc_accepts_adjacent_schedule_blocks() -> None:
    """Two blocks that touch but do not overlap are accepted."""
    npc = Npc.model_validate(
        {
            "id": "NPC_MILLER",
            "name": "The Miller",
            "schedule": [
                {
                    "start_tick": 0,
                    "end_tick": 40,
                    "zone_id": "ZN_YARD",
                    "tile": [1, 2],
                    "activity": "sleeping",
                },
                {
                    "start_tick": 40,
                    "end_tick": 60,
                    "zone_id": "ZN_HALL",
                    "tile": [3, 4],
                    "activity": "reading",
                },
            ],
        }
    )
    assert len(npc.schedule) == 2


def test_npc_rejects_tile_out_of_range() -> None:
    """A tile must be a pair of integers."""
    with pytest.raises(ValidationError):
        Npc.model_validate(
            {
                "id": "NPC_MILLER",
                "name": "The Miller",
                "schedule": [
                    {
                        "start_tick": 0,
                        "end_tick": 40,
                        "zone_id": "ZN_YARD",
                        "tile": [1, 2, 3],
                        "activity": "sleeping",
                    }
                ],
            }
        )


# ----------------------------------------------------------------------
# Events
# ----------------------------------------------------------------------


def test_event_rejects_out_of_range_activation_tick() -> None:
    """An event cannot fire outside the cycle."""
    with pytest.raises(ValidationError, match=r"activation_tick must be within"):
        Event.model_validate(
            {
                "id": "EV_X",
                "name": "X",
                "activation_tick": OUT_OF_RANGE_TICK,
            }
        )


def test_event_accepts_the_closing_tick() -> None:
    """The closing tick is a valid instant for an event."""
    event = Event.model_validate(
        {
            "id": "EV_X",
            "name": "X",
            "activation_tick": total_ticks(),
        }
    )
    assert event.activation_tick == total_ticks()


def test_event_rejects_a_malformed_precondition() -> None:
    """The precondition is a simple flag expression."""
    with pytest.raises(ValidationError, match="must look like 'flag:NAME'"):
        Event.model_validate(
            {
                "id": "EV_X",
                "name": "X",
                "activation_tick": 100,
                "precondition": "flags.has('x')",
            }
        )


def test_event_accepts_a_flag_precondition() -> None:
    """A well formed precondition is accepted."""
    event = Event.model_validate(
        {
            "id": "EV_X",
            "name": "X",
            "activation_tick": 100,
            "precondition": "flag:first_death_known",
        }
    )
    assert event.precondition == "flag:first_death_known"


# ----------------------------------------------------------------------
# Missions
# ----------------------------------------------------------------------


def test_main_mission_without_deadline_is_rejected() -> None:
    """A main mission without a deadline removes the pressure of the design."""
    with pytest.raises(ValidationError, match="main mission must declare a deadline_tick"):
        Mission.model_validate(
            {
                "id": "MS_MAIN",
                "title": "Main",
                "kind": "main",
                "giver_npc": "NPC_KEEPER",
                "steps": [],
            }
        )


def test_secondary_mission_without_deadline_is_accepted() -> None:
    """A side quest may have no deadline."""
    mission = Mission.model_validate(
        {
            "id": "MS_SIDE",
            "title": "Side",
            "kind": "secondary",
            "giver_npc": "NPC_KEEPER",
            "steps": [],
        }
    )
    assert mission.deadline_tick is None


def test_mission_rejects_out_of_range_deadline() -> None:
    """A deadline outside the cycle is rejected."""
    with pytest.raises(ValidationError, match=r"deadline_tick must be within"):
        Mission.model_validate(
            {
                "id": "MS_MAIN",
                "title": "Main",
                "kind": "main",
                "giver_npc": "NPC_KEEPER",
                "steps": [],
                "deadline_tick": OUT_OF_RANGE_TICK,
            }
        )


def test_mission_rejects_duplicated_step_ids() -> None:
    """Two steps of a mission cannot share an id."""
    step = {
        "id": "step_1",
        "description": "Ask around.",
        "objective_kind": "collect_symptom",
    }
    with pytest.raises(ValidationError, match="duplicated step ids"):
        Mission.model_validate(
            {
                "id": "MS_MAIN",
                "title": "Main",
                "kind": "main",
                "giver_npc": "NPC_KEEPER",
                "steps": [step, dict(step)],
                "deadline_tick": 168,
            }
        )


def test_mission_step_requires_a_known_objective_kind() -> None:
    """The objective kind is a closed vocabulary."""
    with pytest.raises(ValidationError, match="objective_kind"):
        MissionStep.model_validate(
            {
                "id": "step_1",
                "description": "Fight the rat.",
                "objective_kind": "combat",
            }
        )


def test_mission_step_accepts_every_objective_kind() -> None:
    """Every objective kind of the vocabulary is accepted."""
    for kind in ObjectiveKind:
        step = MissionStep.model_validate(
            {
                "id": "step_1",
                "description": "Do the thing.",
                "objective_kind": kind.value,
            }
        )
        assert step.objective_kind is kind


# ----------------------------------------------------------------------
# Dialogues and endings
# ----------------------------------------------------------------------


def test_dialogue_node_rejects_duplicated_option_ids() -> None:
    """Two options of a node cannot share an id."""
    option = {"id": "leave", "text": "Goodbye."}
    with pytest.raises(ValidationError, match="duplicated option ids"):
        DialogueNode.model_validate(
            {
                "id": "DL_ROOT",
                "speaker": "NPC_KEEPER",
                "text": "Hello.",
                "options": [option, dict(option)],
            }
        )


def test_dialogue_option_accepts_no_next_node() -> None:
    """An option that ends the conversation is valid."""
    option = DialogueOption.model_validate({"id": "leave", "text": "Goodbye."})
    assert option.next_node is None


def test_ending_requires_the_reserved_id_prefix() -> None:
    """The ending id must carry the END_ prefix."""
    with pytest.raises(ValidationError, match="must start with 'END_'"):
        Ending.model_validate({"id": "E_CURE", "title": "The cure"})


# ----------------------------------------------------------------------
# Lighting
# ----------------------------------------------------------------------


def test_lighting_phase_rejects_opacity_out_of_range() -> None:
    """The overlay opacity is a probability."""
    with pytest.raises(ValidationError, match=r"opacity must be within \[0.0, 1.0\]"):
        LightingPhase.model_validate(
            {
                "id": "LGT_DAY",
                "start_tick": 38,
                "end_tick": 66,
                "rgb": [255, 255, 255],
                "opacity": 1.4,
                "palette_id": "day",
            }
        )


def test_lighting_phase_rejects_channel_out_of_range() -> None:
    """Every colour channel is a byte."""
    with pytest.raises(ValidationError, match=r"rgb channels must be within \[0, 255\]"):
        LightingPhase.model_validate(
            {
                "id": "LGT_DAY",
                "start_tick": 38,
                "end_tick": 66,
                "rgb": [255, 300, 255],
                "opacity": 0.0,
                "palette_id": "day",
            }
        )


def test_lighting_phase_rejects_inverted_range() -> None:
    """A phase that ends before it starts is rejected."""
    with pytest.raises(ValidationError, match="must be lower than end_tick"):
        LightingPhase.model_validate(
            {
                "id": "LGT_DAY",
                "start_tick": 66,
                "end_tick": 38,
                "rgb": [255, 255, 255],
                "opacity": 0.0,
                "palette_id": "day",
            }
        )


def test_world_content_rejects_a_lighting_gap() -> None:
    """The lighting table must not leave a tick uncovered."""
    document = _minimal_world()
    phases = document["lighting"]
    phases[2]["start_tick"] = 27
    phases[3]["start_tick"] = 39
    with pytest.raises(ValidationError, match="leave a gap or overlap"):
        WorldContent.model_validate(document)


def test_world_content_rejects_overlapping_lighting_phases() -> None:
    """The lighting table must not cover a tick twice."""
    document = _minimal_world()
    document["lighting"][2]["end_tick"] = 30
    with pytest.raises(ValidationError, match="leave a gap or overlap"):
        WorldContent.model_validate(document)


def test_world_content_rejects_the_wrong_number_of_lighting_phases() -> None:
    """The canonical table has exactly seven phases."""
    document = _minimal_world(lighting=_lighting_phases()[:6])
    with pytest.raises(ValidationError, match="exactly 7 phases"):
        WorldContent.model_validate(document)


def test_world_content_accepts_a_complete_lighting_table() -> None:
    """Seven phases covering the whole day are accepted."""
    world = WorldContent.model_validate(_minimal_world())
    assert len(world.lighting) == 7


# ----------------------------------------------------------------------
# Rumors
# ----------------------------------------------------------------------


def test_rumor_rejects_an_inverted_window() -> None:
    """A rumour cannot be heard after it stops being spreadable."""
    with pytest.raises(ValidationError, match="must not be greater than max_tick"):
        Rumor.model_validate(
            {
                "id": "RUM_X",
                "text": "Something people say.",
                "npc_id": "NPC_KEEPER",
                "min_tick": 100,
                "max_tick": 50,
            }
        )


def test_rumor_rejects_out_of_range_tick() -> None:
    """A rumour window cannot leave the cycle."""
    with pytest.raises(ValidationError, match=r"min_tick must be within"):
        Rumor.model_validate(
            {
                "id": "RUM_X",
                "text": "Something people say.",
                "npc_id": "NPC_KEEPER",
                "min_tick": OUT_OF_RANGE_TICK,
            }
        )


# ----------------------------------------------------------------------
# Resources
# ----------------------------------------------------------------------


def test_resource_spec_accepts_a_valid_definition() -> None:
    """A provision is described by its stock, its cost and its threshold."""
    resource = ResourceSpec.model_validate(
        {
            "id": "RES_FOOD",
            "label": "Food",
            "initial": 10,
            "per_action": 1,
            "critical_at": 3,
        }
    )
    assert resource.id == "RES_FOOD"
    assert resource.initial == 10
    assert resource.per_action == 1
    assert resource.critical_at == 3


def test_resource_spec_defaults_the_new_fields() -> None:
    """A provision without the new fields says it does not decay."""
    resource = ResourceSpec.model_validate(
        {
            "id": "RES_FOOD",
            "label": "Food",
            "initial": 10,
            "per_action": 1,
            "critical_at": 3,
        }
    )
    assert resource.daily_decay == 0
    assert resource.blocks_actions == ()


def test_resource_spec_accepts_the_new_fields() -> None:
    """A provision may declare its decay and the actions it gates."""
    resource = ResourceSpec.model_validate(
        {
            "id": "RES_FUEL",
            "label": "Fuel",
            "initial": 8,
            "per_action": 1,
            "critical_at": 2,
            "daily_decay": 1,
            "blocks_actions": ["prepare_sample"],
        }
    )
    assert resource.daily_decay == 1
    assert resource.blocks_actions == ("prepare_sample",)


@pytest.mark.parametrize("field", ["initial", "per_action", "critical_at", "daily_decay"])
def test_resource_spec_rejects_negative_amounts(field: str) -> None:
    """A negative quantity is not a stock the town can hold."""
    document = {
        "id": "RES_FOOD",
        "label": "Food",
        "initial": 10,
        "per_action": 1,
        "critical_at": 3,
    }
    document[field] = -1
    with pytest.raises(ValidationError, match="must be >= 0"):
        ResourceSpec.model_validate(document)


def test_resource_spec_rejects_an_unreachable_threshold() -> None:
    """A threshold above the initial amount would start in crisis."""
    with pytest.raises(ValidationError, match="critical_at"):
        ResourceSpec.model_validate(
            {
                "id": "RES_FOOD",
                "label": "Food",
                "initial": 5,
                "per_action": 1,
                "critical_at": 9,
            }
        )


def test_resource_spec_rejects_duplicated_blocked_actions() -> None:
    """A gated action must not be listed twice."""
    with pytest.raises(ValidationError, match="duplicated kinds"):
        ResourceSpec.model_validate(
            {
                "id": "RES_FUEL",
                "label": "Fuel",
                "initial": 8,
                "per_action": 1,
                "critical_at": 2,
                "blocks_actions": ["prepare_sample", "prepare_sample"],
            }
        )


def test_resource_spec_rejects_an_empty_blocked_action() -> None:
    """A gated action must name something."""
    with pytest.raises(ValidationError, match="non-empty action kinds"):
        ResourceSpec.model_validate(
            {
                "id": "RES_FUEL",
                "label": "Fuel",
                "initial": 8,
                "per_action": 1,
                "critical_at": 2,
                "blocks_actions": [""],
            }
        )


def test_resource_spec_rejects_an_id_without_the_reserved_prefix() -> None:
    """Every provision carries the prefix reserved for resources."""
    with pytest.raises(ValidationError, match="RES_"):
        ResourceSpec.model_validate(
            {
                "id": "FOOD",
                "label": "Food",
                "initial": 10,
                "per_action": 1,
                "critical_at": 3,
            }
        )


def test_resource_spec_rejects_unknown_fields() -> None:
    """A typo in a resource definition is an error, not a silent loss."""
    with pytest.raises(ValidationError):
        ResourceSpec.model_validate(
            {
                "id": "RES_FOOD",
                "label": "Food",
                "initial": 10,
                "per_action": 1,
                "critical_at": 3,
                "per_tick": 1,
            }
        )


def test_world_content_rejects_duplicated_resource_ids(valid_world: WorldContent) -> None:
    """Two provisions cannot share an id."""
    document = valid_world.model_dump(mode="json")
    document["resources"].append(dict(document["resources"][0]))
    with pytest.raises(ValidationError, match="duplicated resources ids"):
        WorldContent.model_validate(document)


def test_world_content_accepts_resources(valid_world: WorldContent) -> None:
    """The root document carries the provisions of the town."""
    assert len(valid_world.resources) == 3
    assert valid_world.resources[0].id == "RES_FOOD"


# ----------------------------------------------------------------------
# Cross-model validation of the root document
# ----------------------------------------------------------------------


def test_world_content_rejects_duplicated_ids(valid_world: WorldContent) -> None:
    """A duplicated id inside a collection is rejected."""
    document = valid_world.model_dump(mode="json")
    document["zones"].append(dict(document["zones"][0]))
    with pytest.raises(ValidationError, match="duplicated zones ids"):
        WorldContent.model_validate(document)


def test_world_content_rejects_duplicated_npc_ids(valid_world: WorldContent) -> None:
    """A duplicated NPC id is rejected."""
    document = valid_world.model_dump(mode="json")
    document["npcs"].append(dict(document["npcs"][0]))
    with pytest.raises(ValidationError, match="duplicated npcs ids"):
        WorldContent.model_validate(document)


def test_world_content_rejects_an_unknown_dialogue_root(valid_world: WorldContent) -> None:
    """An NPC whose dialogue root does not exist is rejected."""
    document = valid_world.model_dump(mode="json")
    document["npcs"][0]["dialogue_root"] = "DL_MISSING"
    with pytest.raises(ValidationError, match="dialogue_root 'DL_MISSING' does not exist"):
        WorldContent.model_validate(document)


def test_world_content_rejects_an_unknown_mission_giver(valid_world: WorldContent) -> None:
    """A mission given by nobody is rejected."""
    document = valid_world.model_dump(mode="json")
    document["missions"][0]["giver_npc"] = "NPC_GHOST"
    with pytest.raises(ValidationError, match="giver_npc 'NPC_GHOST' does not exist"):
        WorldContent.model_validate(document)


def test_world_content_rejects_an_unknown_event_zone(valid_world: WorldContent) -> None:
    """An event in a zone that does not exist is rejected."""
    document = valid_world.model_dump(mode="json")
    document["events"][0]["zone_ids"] = ["ZN_NOWHERE"]
    with pytest.raises(ValidationError, match="references unknown zone 'ZN_NOWHERE'"):
        WorldContent.model_validate(document)


def test_world_content_rejects_an_unknown_event_npc(valid_world: WorldContent) -> None:
    """An event that involves nobody is rejected."""
    document = valid_world.model_dump(mode="json")
    document["events"][0]["npc_ids"] = ["NPC_GHOST"]
    with pytest.raises(ValidationError, match="references unknown npc 'NPC_GHOST'"):
        WorldContent.model_validate(document)


def test_world_content_rejects_a_dangling_dialogue_option(valid_world: WorldContent) -> None:
    """A dialogue option pointing at a missing node is rejected."""
    document = valid_world.model_dump(mode="json")
    document["dialogues"][0]["options"][0]["next_node"] = "DL_MISSING"
    with pytest.raises(ValidationError, match="points at unknown node 'DL_MISSING'"):
        WorldContent.model_validate(document)


def test_world_content_rejects_a_dangling_reported_symptom(
    valid_world: WorldContent,
) -> None:
    """A dialogue option reporting a missing symptom is rejected."""
    document = valid_world.model_dump(mode="json")
    document["dialogues"][0]["options"][0]["reports_symptom"] = "SYM_MISSING"
    with pytest.raises(ValidationError, match="reports unknown symptom 'SYM_MISSING'"):
        WorldContent.model_validate(document)


def test_world_content_rejects_a_hypothesis_without_a_cause(
    valid_world: WorldContent,
) -> None:
    """A hypothesis pointing at a missing cause is rejected."""
    document = valid_world.model_dump(mode="json")
    document["hypotheses"][0]["cause_id"] = "CAUSE_MISSING"
    with pytest.raises(ValidationError, match="references unknown cause 'CAUSE_MISSING'"):
        WorldContent.model_validate(document)


def test_world_content_rejects_a_source_without_a_cause(valid_world: WorldContent) -> None:
    """A source mentioning a missing cause is rejected."""
    document = valid_world.model_dump(mode="json")
    document["sources"][0]["supports"] = ["CAUSE_MISSING"]
    with pytest.raises(ValidationError, match="references unknown cause 'CAUSE_MISSING'"):
        WorldContent.model_validate(document)


def test_world_content_rejects_a_symptom_without_a_reporter(
    valid_world: WorldContent,
) -> None:
    """A symptom reported by nobody is rejected."""
    document = valid_world.model_dump(mode="json")
    document["symptoms"][0]["source_npc"] = "NPC_GHOST"
    with pytest.raises(ValidationError, match="source_npc 'NPC_GHOST' does not exist"):
        WorldContent.model_validate(document)


def test_world_content_rejects_a_schedule_in_an_unknown_zone(
    valid_world: WorldContent,
) -> None:
    """An NPC standing in a zone that does not exist is rejected."""
    document = valid_world.model_dump(mode="json")
    document["npcs"][0]["schedule"][0]["zone_id"] = "ZN_NOWHERE"
    with pytest.raises(ValidationError, match="references unknown zone 'ZN_NOWHERE'"):
        WorldContent.model_validate(document)


def test_world_content_rejects_an_unknown_premise_stage(valid_world: WorldContent) -> None:
    """A progression stage without a symptom is rejected."""
    document = valid_world.model_dump(mode="json")
    document["premise"]["progression_stages"] = ["SYM_MISSING"]
    with pytest.raises(ValidationError, match="progression stage 'SYM_MISSING' does not exist"):
        WorldContent.model_validate(document)


def test_world_content_rejects_an_unknown_premise_cure_source(
    valid_world: WorldContent,
) -> None:
    """A cure source that does not exist is rejected."""
    document = valid_world.model_dump(mode="json")
    document["premise"]["partial_cure_source"] = "SRC_MISSING"
    with pytest.raises(ValidationError, match="cure source 'SRC_MISSING' does not exist"):
        WorldContent.model_validate(document)


def test_world_content_requires_a_cause_for_every_progression_stage(
    valid_world: WorldContent,
) -> None:
    """A symptom of the progression without a cause would be a dead end."""
    document = valid_world.model_dump(mode="json")
    document["hypotheses"] = [
        hypothesis for hypothesis in document["hypotheses"] if hypothesis["id"] != "HYP_MOULD"
    ]
    with pytest.raises(ValidationError, match="no candidate cause in the symptom -> cause"):
        WorldContent.model_validate(document)


def test_world_content_requires_a_source_for_every_cause(valid_world: WorldContent) -> None:
    """A cause nobody can confirm or refute is not a hypothesis."""
    document = valid_world.model_dump(mode="json")
    for source in document["sources"]:
        source["supports"] = []
        source["refutes"] = []
    with pytest.raises(ValidationError, match="have no source that supports or refutes"):
        WorldContent.model_validate(document)


def test_world_content_rejects_an_unknown_flag_in_a_rumor(valid_world: WorldContent) -> None:
    """A rumour spread by nobody is rejected."""
    document = valid_world.model_dump(mode="json")
    document["rumors"][0]["npc_id"] = "NPC_GHOST"
    with pytest.raises(ValidationError, match="references unknown npc 'NPC_GHOST'"):
        WorldContent.model_validate(document)


def test_world_content_rejects_an_unknown_field(valid_world: WorldContent) -> None:
    """An unknown field of the root document is rejected."""
    document = valid_world.model_dump(mode="json")
    document["extra"] = True
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        WorldContent.model_validate(document)


def test_world_content_is_frozen(valid_world: WorldContent) -> None:
    """A validated world document cannot be mutated."""
    with pytest.raises(ValidationError):
        valid_world.content_version = "9.9.9"


# ----------------------------------------------------------------------
# The authored premise plate
# ----------------------------------------------------------------------


def test_authored_premise_plate_still_carries_the_tbd_marker() -> None:
    """The authored plate is deliberately incomplete until the decision P3.

    The plate exists to demonstrate that the validator rejects a pending
    design decision. Once the user takes the decision, this test is expected
    to fail and must be updated together with the plate.
    """
    document = json.loads(BASE_PREMISE_PATH.read_text(encoding="utf-8"))
    with pytest.raises(ValidationError, match="unresolved marker"):
        Premise.model_validate(document["premise"])


# ----------------------------------------------------------------------
# The death of an NPC
# ----------------------------------------------------------------------


def _npc(**overrides: Any) -> dict[str, Any]:
    """Build a valid NPC document.

    Args:
        overrides: Fields to override.

    Returns:
        The NPC document.
    """
    document: dict[str, Any] = {
        "id": "NPC_MILLER",
        "name": "The Miller",
        "schedule": [
            {
                "start_tick": 0,
                "end_tick": 96,
                "zone_id": "ZN_YARD",
                "tile": [1, 2],
                "activity": "grinding_grain",
            }
        ],
    }
    document.update(overrides)
    return document


def test_an_npc_without_a_death_is_valid() -> None:
    """A living NPC declares no death at all."""
    npc = Npc.model_validate(_npc())
    assert npc.deceased_at_tick is None
    assert npc.death_cause == ""


def test_an_npc_with_a_death_is_valid() -> None:
    """A death is a tick and a cause, and nothing else."""
    npc = Npc.model_validate(
        _npc(deceased_at_tick=192, death_cause="plague_fever"),
    )
    assert npc.deceased_at_tick == 192
    assert npc.death_cause == "plague_fever"


def test_npc_rejects_a_death_tick_out_of_range() -> None:
    """A death outside the cycle cannot happen."""
    with pytest.raises(ValidationError, match=r"deceased_at_tick must be within"):
        Npc.model_validate(_npc(deceased_at_tick=OUT_OF_RANGE_TICK, death_cause="plague_fever"))


def test_npc_rejects_a_negative_death_tick() -> None:
    """A death before the cycle opens cannot happen."""
    with pytest.raises(ValidationError, match=r"deceased_at_tick must be within"):
        Npc.model_validate(_npc(deceased_at_tick=-1, death_cause="plague_fever"))


def test_npc_accepts_the_closing_tick_as_a_death() -> None:
    """The closing tick is a valid instant, even for a death."""
    npc = Npc.model_validate(_npc(deceased_at_tick=total_ticks(), death_cause="plague_fever"))
    assert npc.deceased_at_tick == total_ticks()


def test_npc_rejects_a_cause_without_a_death() -> None:
    """There is no cause without a death."""
    with pytest.raises(ValidationError, match="requires a deceased_at_tick"):
        Npc.model_validate(_npc(death_cause="plague_fever"))


def test_npc_rejects_a_death_without_a_cause() -> None:
    """There is no death without a cause."""
    with pytest.raises(ValidationError, match="requires a death_cause"):
        Npc.model_validate(_npc(deceased_at_tick=192))


def test_npc_rejects_an_unknown_death_cause() -> None:
    """The cause of a death uses the reserved vocabulary."""
    with pytest.raises(ValidationError, match="must start with one of"):
        Npc.model_validate(_npc(deceased_at_tick=192, death_cause="bad luck"))


@pytest.mark.parametrize("cause", DEATH_CAUSE_PREFIXES)
def test_npc_accepts_every_valid_death_cause_prefix(cause: str) -> None:
    """Every kind of death of the vocabulary is accepted."""
    npc = Npc.model_validate(_npc(deceased_at_tick=192, death_cause=f"{cause}fever"))
    assert npc.death_cause == f"{cause}fever"


def test_the_death_cause_prefixes_are_not_empty() -> None:
    """The vocabulary of the causes of death is not empty."""
    assert DEATH_CAUSE_PREFIXES
    assert all(prefix for prefix in DEATH_CAUSE_PREFIXES)


# ----------------------------------------------------------------------
# The event that kills
# ----------------------------------------------------------------------


def test_event_accepts_deaths() -> None:
    """An event may declare the villagers it kills."""
    event = Event.model_validate(
        {
            "id": "EV_X",
            "name": "X",
            "activation_tick": 192,
            "deaths": ["NPC_MILLER"],
        }
    )
    assert event.deaths == ("NPC_MILLER",)


def test_event_defaults_to_no_deaths() -> None:
    """An event that kills nobody declares no death."""
    event = Event.model_validate({"id": "EV_X", "name": "X", "activation_tick": 100})
    assert event.deaths == ()


def test_world_content_rejects_an_event_that_kills_an_unknown_npc(
    valid_world: WorldContent,
) -> None:
    """An event that kills somebody who does not exist is rejected."""
    document = valid_world.model_dump(mode="json")
    document["events"][0]["deaths"] = ["NPC_GHOST"]
    with pytest.raises(ValidationError, match="kills unknown npc 'NPC_GHOST'"):
        WorldContent.model_validate(document)


def test_world_content_accepts_an_event_that_kills_a_known_npc(
    valid_world: WorldContent,
) -> None:
    """An event that kills a villager of the world is accepted."""
    document = valid_world.model_dump(mode="json")
    document["events"][0]["deaths"] = [document["npcs"][0]["id"]]
    world = WorldContent.model_validate(document)
    assert world.events[0].deaths == (document["npcs"][0]["id"],)
