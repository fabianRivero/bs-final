"""Pydantic models describing every content document of the Aldermere project.

The whole game is data. The simulation core owns the *rules*, and this module
owns the *shape* of the data those rules are fed. Every JSON document under
``content/base/`` and ``content/generated/`` is validated against the models
defined here before anything else in the project is allowed to read it.

Why the models are strict
-------------------------
Every model uses ``ConfigDict(extra="forbid", frozen=True)``:

* ``extra="forbid"`` turns a typo into a validation error instead of a silently
  ignored field. Content is authored by hand *and* produced by an LLM, so
  silent data loss is a real hazard.
* ``frozen=True`` makes the validated documents immutable, which is the same
  guarantee the simulation core gives to its own dataclasses: content must
  never change behind the back of the code that reads it.

Why the engine is agnostic
--------------------------
The engine never knows what the disease actually is. It only knows that a
symptom may correspond to a cause, and that a cause may be confirmed or
refuted by a source. The concrete origin lives entirely in the *premise
plate* (:class:`Premise`), which is data, not code. That is why
:class:`Premise` is the only model that mentions the disease by name, and why
the cross-model validators of :class:`WorldContent` check *structure* (does
every reference resolve?) rather than *meaning* (does this symptom make
sense for this illness?).

Identifier conventions
----------------------
Every id carries a prefix that states its type, so a reference can be read
without opening the file that defines it:

=============  ======================================================
Prefix         Entity
=============  ======================================================
``PR_``        Premise plate
``ZN_``        Zone
``NPC_``       NPC
``EV_``        Event
``MS_``        Mission
``DL_``        Dialogue node
``SYM_``       Symptom
``SRC_``       Source
``HYP_``       Hypothesis
``END_``       Ending
``LGT_``       Lighting phase
``CAUSE_``     Cause
``RES_``       Resource (provision of the town)
=============  ======================================================

Tick conventions
----------------
The project counts time in ticks of 15 minutes
(:mod:`core.time`). Two kinds of tick appear in the content:

* *Absolute* ticks, in ``[0, TOTAL_TICKS]``, used by events, mission
  deadlines, rumor windows and symptom observations.
* *Day ticks*, in ``[0, TICKS_PER_DAY]``, used by NPC schedules and lighting
  phases. A schedule block repeats every day, so its range is normalised with
  ``tick % TICKS_PER_DAY``.

Half-open ranges
----------------
Every range in the content is **half-open**: ``start`` is inclusive and
``end`` is exclusive. This mirrors the convention already used by
:mod:`core.schedule` and :mod:`core.lighting`, so the same tick never belongs
to two blocks.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.time import TICKS_PER_DAY, total_ticks

__all__ = [
    "Cause",
    "CauseCategory",
    "DialogueNode",
    "DialogueOption",
    "Ending",
    "Event",
    "Hypothesis",
    "HypothesisStatus",
    "LightingPhase",
    "Mission",
    "MissionKind",
    "MissionStep",
    "Npc",
    "ObjectiveKind",
    "Premise",
    "ResourceSpec",
    "Rumor",
    "ScheduleEntry",
    "Source",
    "SourceKind",
    "Symptom",
    "WorldContent",
    "Zone",
]

#: Marker that flags an unresolved design decision inside authored content.
TBD_MARKER = "TBD"

#: Pattern that matches the ``TBD`` marker as a word or as a prefix.
#:
#: ``TBD`` alone, ``tbd`` alone and ``TBD — pending design decision`` all
#: match. ``TBDx`` does not, because the marker is only a marker when it
#: stands on its own or opens a phrase.
_TBD_PATTERN = re.compile(r"\btbd\b", re.IGNORECASE)

#: Prefix required by every id of a given entity type.
ID_PREFIXES: Mapping[str, str] = {
    "premise": "PR_",
    "zone": "ZN_",
    "npc": "NPC_",
    "event": "EV_",
    "mission": "MS_",
    "dialogue": "DL_",
    "symptom": "SYM_",
    "source": "SRC_",
    "hypothesis": "HYP_",
    "ending": "END_",
    "lighting": "LGT_",
    "cause": "CAUSE_",
}

#: Number of lighting phases the canonical table is made of.
LIGHTING_PHASE_COUNT = 7


class SourceKind(StrEnum):
    """Kind of document that can confirm or refute a cause."""

    BOOK = "book"
    HERBAL = "herbal"
    JOURNAL = "journal"
    REGISTRY = "registry"
    OBSERVATION = "observation"


class CauseCategory(StrEnum):
    """Category of a candidate cause.

    The categories are deliberately generic: the engine compares causes
    structurally, and the concrete origin of the illness only selects which
    rows of the hypothesis table are plausible.
    """

    FUNGUS = "fungus"
    BACTERIUM = "bacterium"
    MINERAL = "mineral"
    TOXIN = "toxin"
    CONTAGION = "contagion"
    OTHER = "other"


class HypothesisStatus(StrEnum):
    """State of a hypothesis in the player's notebook."""

    PENDING = "pending"
    SUPPORTED = "supported"
    REFUTED = "refuted"


class MissionKind(StrEnum):
    """Kind of mission, which decides how its deadline is interpreted."""

    MAIN = "main"
    SECONDARY = "secondary"
    EXPLORATION = "exploration"


class ObjectiveKind(StrEnum):
    """Kind of step inside a mission."""

    COLLECT_SYMPTOM = "collect_symptom"
    CONSULT_SOURCE = "consult_source"
    FORMULATE_HYPOTHESIS = "formulate_hypothesis"
    VERIFY = "verify"
    ACT = "act"


class StrictModel(BaseModel):
    """Base class for every content model.

    Attributes:
        model_config: Strict, immutable configuration shared by all models.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


def _has_tbd(text: str) -> bool:
    """Check whether a string carries the unresolved-decision marker.

    Args:
        text: String to inspect.

    Returns:
        ``True`` when the string contains the ``TBD`` marker as a word or as
        a prefix of a phrase, ignoring case.
    """
    return _TBD_PATTERN.search(text) is not None


def _check_no_tbd(value: str, field_name: str) -> None:
    """Reject a string that still carries the ``TBD`` marker.

    Args:
        value: String to inspect.
        field_name: Name of the field, used in the error message.

    Raises:
        ValueError: If the string carries the marker.
    """
    if _has_tbd(value):
        raise ValueError(
            f"{field_name} still contains the unresolved marker {TBD_MARKER!r}: {value!r}. "
            f"Resolve the design decision before committing the content."
        )


def _validate_id_prefix(value: str, kind: str, field_name: str) -> None:
    """Check that an id carries the prefix reserved for its entity type.

    Args:
        value: Identifier to check.
        kind: Key of the entity type in :data:`ID_PREFIXES`.
        field_name: Name of the field, used in the error message.

    Raises:
        ValueError: If the prefix does not match the entity type.
    """
    prefix = ID_PREFIXES[kind]
    if not value.startswith(prefix):
        raise ValueError(
            f"{field_name} must start with {prefix!r} (the prefix reserved for "
            f"{kind} ids), got {value!r}"
        )


def _duplicate_ids(items: Iterable[Any], kind: str) -> list[str]:
    """Return the ids that appear more than once in a collection.

    Args:
        items: Objects exposing an ``id`` attribute.
        kind: Key of the entity type in :data:`ID_PREFIXES`.

    Returns:
        The duplicated ids, sorted and without duplicates.
    """
    seen: set[str] = set()
    duplicates: set[str] = set()
    for item in items:
        identifier = item.id
        if identifier in seen:
            duplicates.add(identifier)
        seen.add(identifier)
    del kind
    return sorted(duplicates)


class Premise(StrictModel):
    """The premise plate: what the illness is, in data form.

    The engine does not know what the disease is; it knows the *plate*. Every
    field that names the concrete origin is filled in by a human decision
    (open question P3 of ``PLAN.md``) and is only ever used to write text or
    to select plausible rows of the hypothesis table.

    Attributes:
        id: Identifier of the plate, e.g. ``"PR_BLIGHT"``.
        title: Human readable title of the plate.
        disease_name: Name of the disease as it appears in the game text.
        symptom_signature: Short description of the signature symptom.
        progression_stages: Ids of the symptoms that mark the progression of
            the disease, from the earliest to the most severe.
        transmission_mode: How the disease spreads, described in words.
        partial_cure_source: Id of the source that documents a partial cure.
        total_cure_source: Id of the source that documents a total cure.
        responsible_actor: Who is responsible for the practice that caused
            the outbreak.
        responsible_note: The nuance of that responsibility.
        outcome_notes: Notes on the possible outcomes of the story.
    """

    id: str
    title: str
    disease_name: str
    symptom_signature: str
    progression_stages: tuple[str, ...]
    transmission_mode: str
    partial_cure_source: str
    total_cure_source: str
    responsible_actor: str
    responsible_note: str
    outcome_notes: str

    @field_validator("id")
    @classmethod
    def _check_id_prefix(cls, value: str) -> str:
        """Check the identifier prefix.

        Args:
            value: Identifier to check.

        Returns:
            The validated identifier.

        Raises:
            ValueError: If the prefix is wrong.
        """
        _validate_id_prefix(value, "premise", "premise.id")
        return value

    @field_validator(
        "title",
        "disease_name",
        "symptom_signature",
        "transmission_mode",
        "responsible_actor",
        "responsible_note",
        "outcome_notes",
    )
    @classmethod
    def _check_no_tbd(cls, value: str) -> str:
        """Reject any string that still carries the ``TBD`` marker.

        Args:
            value: String to check.

        Returns:
            The validated string.

        Raises:
            ValueError: If the marker is present.
        """
        _check_no_tbd(value, "premise")
        return value

    @field_validator("progression_stages")
    @classmethod
    def _check_stages_not_empty(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Reject an empty progression and any stage that is still pending.

        Args:
            value: Stage ids to check.

        Returns:
            The validated stage ids.

        Raises:
            ValueError: If the progression is empty or a stage carries the
                ``TBD`` marker.
        """
        if not value:
            raise ValueError("premise.progression_stages must list at least one symptom id")
        for stage in value:
            _check_no_tbd(stage, "premise.progression_stages")
        return value


class Symptom(StrictModel):
    """A symptom that can be reported by an NPC or found in a source.

    Attributes:
        id: Identifier of the symptom, e.g. ``"SYM_FEVER"``.
        label: Short name shown in the notebook.
        description: What the symptom looks like.
        source_npc: Id of the NPC that first reported the symptom, if any.
        reported_by: Ids of every NPC that reported the symptom.
        observed_at_tick: Absolute tick at which the symptom was observed.
    """

    id: str
    label: str
    description: str
    source_npc: str | None = None
    reported_by: tuple[str, ...] = ()
    observed_at_tick: int | None = None

    @field_validator("id")
    @classmethod
    def _check_id_prefix(cls, value: str) -> str:
        """Check the identifier prefix.

        Args:
            value: Identifier to check.

        Returns:
            The validated identifier.

        Raises:
            ValueError: If the prefix is wrong.
        """
        _validate_id_prefix(value, "symptom", "symptom.id")
        return value

    @field_validator("observed_at_tick")
    @classmethod
    def _check_tick(cls, value: int | None) -> int | None:
        """Check that the observation tick lies inside the cycle.

        Args:
            value: Tick to check.

        Returns:
            The validated tick.

        Raises:
            ValueError: If the tick is out of range.
        """
        if value is None:
            return None
        if not 0 <= value <= total_ticks():
            raise ValueError(
                f"symptom.observed_at_tick must be within [0, {total_ticks()}], got {value}"
            )
        return value


class Source(StrictModel):
    """A document that can confirm or refute a candidate cause.

    Attributes:
        id: Identifier of the source, e.g. ``"SRC_BOTANY"``.
        kind: Kind of document.
        title: Title of the document.
        location: Where the document can be consulted, described in words.
        supports: Ids of the causes the document supports.
        refutes: Ids of the causes the document refutes.
        readable_ticks: Absolute ticks at which the document can be read.
    """

    id: str
    kind: SourceKind
    title: str
    location: str
    supports: tuple[str, ...] = ()
    refutes: tuple[str, ...] = ()
    readable_ticks: tuple[int, ...] = ()

    @field_validator("id")
    @classmethod
    def _check_id_prefix(cls, value: str) -> str:
        """Check the identifier prefix.

        Args:
            value: Identifier to check.

        Returns:
            The validated identifier.

        Raises:
            ValueError: If the prefix is wrong.
        """
        _validate_id_prefix(value, "source", "source.id")
        return value

    @field_validator("readable_ticks")
    @classmethod
    def _check_ticks(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        """Check that every readability tick lies inside the cycle.

        Args:
            value: Ticks to check.

        Returns:
            The validated ticks.

        Raises:
            ValueError: If a tick is out of range.
        """
        for tick in value:
            if not 0 <= tick <= total_ticks():
                raise ValueError(
                    f"source.readable_ticks must be within [0, {total_ticks()}], got {tick}"
                )
        return value


class Cause(StrictModel):
    """A candidate cause of the symptoms.

    Attributes:
        id: Identifier of the cause, e.g. ``"CAUSE_CULTIVATED"``.
        label: Short name shown in the notebook.
        category: Category of the cause.
        description: What the cause is, described in words.
    """

    id: str
    label: str
    category: CauseCategory
    description: str

    @field_validator("id")
    @classmethod
    def _check_id_prefix(cls, value: str) -> str:
        """Check the identifier prefix.

        Args:
            value: Identifier to check.

        Returns:
            The validated identifier.

        Raises:
            ValueError: If the prefix is wrong.
        """
        _validate_id_prefix(value, "cause", "cause.id")
        return value


class Hypothesis(StrictModel):
    """A link between a set of symptoms and a candidate cause.

    This is the structural heart of the investigation loop: the engine
    compares the symptoms the player collected with ``symptom_ids`` and reads
    ``status`` from here. Nothing in the engine knows the name of the illness.

    Attributes:
        id: Identifier of the hypothesis, e.g. ``"HYP_CULTIVATED"``.
        symptom_ids: Ids of the symptoms that support the hypothesis.
        cause_id: Id of the cause the hypothesis points at.
        status: Whether the hypothesis is pending, supported or refuted.
        verification_method: How the hypothesis can be verified.
        verification_target: Id of the NPC, zone or object used to verify it.
    """

    id: str
    symptom_ids: tuple[str, ...]
    cause_id: str
    status: HypothesisStatus = HypothesisStatus.PENDING
    verification_method: str = ""
    verification_target: str = ""

    @field_validator("id")
    @classmethod
    def _check_id_prefix(cls, value: str) -> str:
        """Check the identifier prefix.

        Args:
            value: Identifier to check.

        Returns:
            The validated identifier.

        Raises:
            ValueError: If the prefix is wrong.
        """
        _validate_id_prefix(value, "hypothesis", "hypothesis.id")
        return value

    @field_validator("symptom_ids")
    @classmethod
    def _check_symptoms_not_empty(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Reject a hypothesis that is not attached to any symptom.

        Args:
            value: Symptom ids to check.

        Returns:
            The validated symptom ids.

        Raises:
            ValueError: If the list is empty.
        """
        if not value:
            raise ValueError("hypothesis.symptom_ids must list at least one symptom id")
        return value


class Zone(StrictModel):
    """A zone of the town.

    Attributes:
        id: Identifier of the zone, e.g. ``"ZN_PLAZA"``.
        name: Display name of the zone.
        tiles_path: Path of the tile map that backs the zone.
        width: Width of the zone in tiles.
        height: Height of the zone in tiles.
        is_interior: Whether the zone is indoors.
        ambient: Ambient light description of the zone.
    """

    id: str
    name: str
    tiles_path: str
    width: int
    height: int
    is_interior: bool = False
    ambient: str = ""

    @field_validator("id")
    @classmethod
    def _check_id_prefix(cls, value: str) -> str:
        """Check the identifier prefix.

        Args:
            value: Identifier to check.

        Returns:
            The validated identifier.

        Raises:
            ValueError: If the prefix is wrong.
        """
        _validate_id_prefix(value, "zone", "zone.id")
        return value

    @field_validator("width", "height")
    @classmethod
    def _check_size(cls, value: int, info: Any) -> int:
        """Check that a dimension is strictly positive.

        Args:
            value: Dimension to check.
            info: Validation context, used to name the offending field.

        Returns:
            The validated dimension.

        Raises:
            ValueError: If the dimension is not positive.
        """
        field_name = info.field_name or "zone size"
        if value <= 0:
            raise ValueError(f"zone.{field_name} must be > 0, got {value}")
        return value


class ScheduleEntry(StrictModel):
    """One block of an NPC daily routine.

    The block covers the half-open day-tick range ``[start_tick, end_tick)``,
    which is the convention already used by :mod:`core.schedule`.

    Attributes:
        start_tick: First tick of the block within the day, inclusive.
        end_tick: Tick at which the block ends, exclusive.
        zone_id: Id of the zone the NPC occupies during the block.
        tile: Tile coordinates inside the zone, as ``(x, y)``.
        activity: Activity performed during the block.
        interactable: Whether the player can talk to the NPC during the block.
    """

    start_tick: int
    end_tick: int
    zone_id: str
    tile: tuple[int, int]
    activity: str
    interactable: bool = True

    @model_validator(mode="after")
    def _check_range(self) -> Self:
        """Check the boundaries of the block.

        Returns:
            The validated entry.

        Raises:
            ValueError: If the range is inverted or outside the day.
        """
        if not 0 <= self.start_tick < TICKS_PER_DAY:
            raise ValueError(
                f"schedule entry start_tick must be within [0, {TICKS_PER_DAY - 1}], "
                f"got {self.start_tick}"
            )
        if not 0 < self.end_tick <= TICKS_PER_DAY:
            raise ValueError(
                f"schedule entry end_tick must be within [1, {TICKS_PER_DAY}], got {self.end_tick}"
            )
        if self.start_tick >= self.end_tick:
            raise ValueError(
                f"schedule entry start_tick {self.start_tick} must be lower than "
                f"end_tick {self.end_tick}"
            )
        return self


class Npc(StrictModel):
    """An inhabitant of the town and its daily routine.

    Attributes:
        id: Identifier of the NPC, e.g. ``"NPC_MARTA"``.
        name: Display name of the NPC.
        role: Role of the NPC in the town.
        schedule: Blocks of the daily routine, ordered by ``start_tick``.
        dialogue_root: Id of the dialogue node the conversation starts at.
        portrait: Path of the portrait asset.
    """

    id: str
    name: str
    role: str = ""
    schedule: tuple[ScheduleEntry, ...] = ()
    dialogue_root: str = ""
    portrait: str | None = None

    @field_validator("id")
    @classmethod
    def _check_id_prefix(cls, value: str) -> str:
        """Check the identifier prefix.

        Args:
            value: Identifier to check.

        Returns:
            The validated identifier.

        Raises:
            ValueError: If the prefix is wrong.
        """
        _validate_id_prefix(value, "npc", "npc.id")
        return value

    @model_validator(mode="after")
    def _check_schedule_has_no_overlap(self) -> Self:
        """Check that no two schedule blocks cover the same tick.

        Overlapping blocks would make the state of the NPC ambiguous, which
        breaks the determinism invariant of the simulation core.

        Returns:
            The validated NPC.

        Raises:
            ValueError: If two blocks overlap.
        """
        ordered = sorted(self.schedule, key=lambda entry: entry.start_tick)
        for previous, following in itertools.pairwise(ordered):
            if following.start_tick < previous.end_tick:
                raise ValueError(
                    f"npc {self.id}: schedule blocks overlap: "
                    f"[{previous.start_tick}, {previous.end_tick}) intersects "
                    f"[{following.start_tick}, {following.end_tick})"
                )
        return self


class Event(StrictModel):
    """A scheduled event that mutates the world.

    Attributes:
        id: Identifier of the event, e.g. ``"EV_HARBOR_CLOSURE"``.
        name: Display name of the event.
        activation_tick: Absolute tick at which the event fires.
        zone_ids: Ids of the zones the event takes place in.
        npc_ids: Ids of the NPCs involved in the event.
        description: What the event does, described in words.
        effects: Free-form payload describing the effects of the event.
        sets_flags: Flags raised by the event.
        precondition: Optional condition of the form ``"flag:NAME"`` that
            must hold for the event to fire.
    """

    id: str
    name: str
    activation_tick: int
    zone_ids: tuple[str, ...] = ()
    npc_ids: tuple[str, ...] = ()
    description: str = ""
    effects: Mapping[str, Any] = Field(default_factory=dict)
    sets_flags: tuple[str, ...] = ()
    precondition: str | None = None

    @field_validator("id")
    @classmethod
    def _check_id_prefix(cls, value: str) -> str:
        """Check the identifier prefix.

        Args:
            value: Identifier to check.

        Returns:
            The validated identifier.

        Raises:
            ValueError: If the prefix is wrong.
        """
        _validate_id_prefix(value, "event", "event.id")
        return value

    @field_validator("activation_tick")
    @classmethod
    def _check_tick(cls, value: int) -> int:
        """Check that the activation tick lies inside the cycle.

        Args:
            value: Tick to check.

        Returns:
            The validated tick.

        Raises:
            ValueError: If the tick is out of range.
        """
        if not 0 <= value <= total_ticks():
            raise ValueError(
                f"event.activation_tick must be within [0, {total_ticks()}], got {value}"
            )
        return value

    @field_validator("precondition")
    @classmethod
    def _check_precondition(cls, value: str | None) -> str | None:
        """Check the shape of the precondition expression.

        Args:
            value: Precondition to check.

        Returns:
            The validated precondition.

        Raises:
            ValueError: If the precondition is not a ``"flag:NAME"`` expression.
        """
        if value is None:
            return None
        if not re.fullmatch(r"flag:[A-Za-z0-9_]+", value):
            raise ValueError(f"event.precondition must look like 'flag:NAME', got {value!r}")
        return value


class MissionStep(StrictModel):
    """One step of a mission.

    Attributes:
        id: Identifier of the step, unique inside its mission.
        description: What the player has to do.
        objective_kind: Kind of objective the step represents.
        target_id: Id of the symptom, source, hypothesis or NPC the step is
            about.
        requires_flags: Flags that must be active for the step to be active.
        sets_flags: Flags raised when the step completes.
    """

    id: str
    description: str
    objective_kind: ObjectiveKind
    target_id: str = ""
    requires_flags: tuple[str, ...] = ()
    sets_flags: tuple[str, ...] = ()


class Mission(StrictModel):
    """A mission, made of an ordered chain of steps.

    Attributes:
        id: Identifier of the mission, e.g. ``"MS_MAIN"``.
        title: Display title of the mission.
        kind: Kind of mission.
        giver_npc: Id of the NPC that gives the mission.
        steps: Steps of the mission, in order.
        deadline_tick: Absolute tick at which the mission expires.
        reward_flags: Flags granted when the mission completes.
    """

    id: str
    title: str
    kind: MissionKind
    giver_npc: str
    steps: tuple[MissionStep, ...] = ()
    deadline_tick: int | None = None
    reward_flags: tuple[str, ...] = ()

    @field_validator("id")
    @classmethod
    def _check_id_prefix(cls, value: str) -> str:
        """Check the identifier prefix.

        Args:
            value: Identifier to check.

        Returns:
            The validated identifier.

        Raises:
            ValueError: If the prefix is wrong.
        """
        _validate_id_prefix(value, "mission", "mission.id")
        return value

    @field_validator("deadline_tick")
    @classmethod
    def _check_tick(cls, value: int | None) -> int | None:
        """Check that the deadline lies inside the cycle.

        Args:
            value: Deadline to check.

        Returns:
            The validated deadline.

        Raises:
            ValueError: If the deadline is out of range.
        """
        if value is None:
            return None
        if not 0 <= value <= total_ticks():
            raise ValueError(
                f"mission.deadline_tick must be within [0, {total_ticks()}], got {value}"
            )
        return value

    @model_validator(mode="after")
    def _check_main_mission_has_deadline(self) -> Self:
        """Check that a main mission declares a deadline.

        The main mission is the one the endings are evaluated against, so a
        main mission without a deadline would silently remove the pressure
        the whole design depends on.

        Returns:
            The validated mission.

        Raises:
            ValueError: If a main mission has no deadline.
        """
        if self.kind is MissionKind.MAIN and self.deadline_tick is None:
            raise ValueError(f"mission {self.id}: a main mission must declare a deadline_tick")
        return self

    @model_validator(mode="after")
    def _check_step_ids_are_unique(self) -> Self:
        """Check that the step ids are unique inside the mission.

        Returns:
            The validated mission.

        Raises:
            ValueError: If two steps share an id.
        """
        duplicates = _duplicate_ids(self.steps, "mission")
        if duplicates:
            raise ValueError(f"mission {self.id}: duplicated step ids {duplicates}")
        return self


class DialogueOption(StrictModel):
    """A choice the player can pick in a dialogue node.

    Attributes:
        id: Identifier of the option, unique inside its node.
        text: Text shown to the player.
        requires_flags: Flags that must be active for the option to appear.
        sets_flags: Flags raised when the option is chosen.
        next_node: Id of the node the conversation moves to.
        reports_symptom: Id of the symptom reported when the option is chosen.
    """

    id: str
    text: str
    requires_flags: tuple[str, ...] = ()
    sets_flags: tuple[str, ...] = ()
    next_node: str | None = None
    reports_symptom: str | None = None


class DialogueNode(StrictModel):
    """One node of a dialogue tree.

    Attributes:
        id: Identifier of the node, e.g. ``"DL_MARTA_ROOT"``.
        speaker: Id of the NPC who speaks the node.
        text: Text of the node.
        options: Choices offered in the node.
        activity: Activity the node applies to, used to vary the text.
    """

    id: str
    speaker: str = ""
    text: str = ""
    options: tuple[DialogueOption, ...] = ()
    activity: str | None = None

    @field_validator("id")
    @classmethod
    def _check_id_prefix(cls, value: str) -> str:
        """Check the identifier prefix.

        Args:
            value: Identifier to check.

        Returns:
            The validated identifier.

        Raises:
            ValueError: If the prefix is wrong.
        """
        _validate_id_prefix(value, "dialogue", "dialogue.id")
        return value

    @model_validator(mode="after")
    def _check_option_ids_are_unique(self) -> Self:
        """Check that the option ids are unique inside the node.

        Returns:
            The validated node.

        Raises:
            ValueError: If two options share an id.
        """
        duplicates = _duplicate_ids(self.options, "dialogue")
        if duplicates:
            raise ValueError(f"dialogue node {self.id}: duplicated option ids {duplicates}")
        return self


class Ending(StrictModel):
    """A final ending of the story.

    The endings are evaluated in priority order, the lowest ``priority``
    winning. The condition of an ending is expressed with flags, symptoms and
    causes, so the same table works for any premise plate.

    Attributes:
        id: Identifier of the ending, e.g. ``"END_CURE"``.
        title: Display title of the ending.
        text: Closing text of the ending.
        priority: Evaluation priority; the lowest value is evaluated first.
        requires_flags: Flags involved in the condition.
        requires_all_of: Whether every flag of ``requires_flags`` is needed.
        requires_absent_flags: Flags that must *not* be active.
        requires_symptoms: Ids of the symptoms that must be known.
        requires_causes: Ids of the causes that must be identified.
    """

    id: str
    title: str
    text: str = ""
    priority: int = 0
    requires_flags: tuple[str, ...] = ()
    requires_all_of: bool = True
    requires_absent_flags: tuple[str, ...] = ()
    requires_symptoms: tuple[str, ...] = ()
    requires_causes: tuple[str, ...] = ()

    @field_validator("id")
    @classmethod
    def _check_id_prefix(cls, value: str) -> str:
        """Check the identifier prefix.

        Args:
            value: Identifier to check.

        Returns:
            The validated identifier.

        Raises:
            ValueError: If the prefix is wrong.
        """
        _validate_id_prefix(value, "ending", "ending.id")
        return value


class LightingPhase(StrictModel):
    """One phase of the daily light cycle.

    The phase covers the half-open day-tick range ``[start_tick, end_tick)``,
    exactly like the canonical table of :mod:`core.lighting`.

    Attributes:
        id: Identifier of the phase, e.g. ``"LGT_DAWN"``.
        start_tick: First tick of the phase within the day, inclusive.
        end_tick: Tick at which the phase ends, exclusive.
        rgb: Tint colour of the overlay, one value per channel.
        opacity: Opacity of the overlay, in ``[0.0, 1.0]``.
        palette_id: Identifier of the tile palette used in the phase.
    """

    id: str
    start_tick: int
    end_tick: int
    rgb: tuple[int, int, int]
    opacity: float
    palette_id: str

    @field_validator("id")
    @classmethod
    def _check_id_prefix(cls, value: str) -> str:
        """Check the identifier prefix.

        Args:
            value: Identifier to check.

        Returns:
            The validated identifier.

        Raises:
            ValueError: If the prefix is wrong.
        """
        _validate_id_prefix(value, "lighting", "lighting.id")
        return value

    @field_validator("rgb")
    @classmethod
    def _check_rgb(cls, value: tuple[int, int, int]) -> tuple[int, int, int]:
        """Check that every colour channel is in ``[0, 255]``.

        Args:
            value: Colour to check.

        Returns:
            The validated colour.

        Raises:
            ValueError: If a channel is out of range.
        """
        for channel in value:
            if not 0 <= channel <= 255:
                raise ValueError(
                    f"lighting phase rgb channels must be within [0, 255], got {value}"
                )
        return value

    @field_validator("opacity")
    @classmethod
    def _check_opacity(cls, value: float) -> float:
        """Check that the opacity is a probability.

        Args:
            value: Opacity to check.

        Returns:
            The validated opacity.

        Raises:
            ValueError: If the opacity is out of range.
        """
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"lighting phase opacity must be within [0.0, 1.0], got {value}")
        return value

    @model_validator(mode="after")
    def _check_range(self) -> Self:
        """Check the boundaries of the phase.

        Returns:
            The validated phase.

        Raises:
            ValueError: If the range is inverted or outside the day.
        """
        if not 0 <= self.start_tick < TICKS_PER_DAY:
            raise ValueError(
                f"lighting phase start_tick must be within [0, {TICKS_PER_DAY - 1}], "
                f"got {self.start_tick}"
            )
        if not 0 < self.end_tick <= TICKS_PER_DAY:
            raise ValueError(
                f"lighting phase end_tick must be within [1, {TICKS_PER_DAY}], got {self.end_tick}"
            )
        if self.start_tick >= self.end_tick:
            raise ValueError(
                f"lighting phase start_tick {self.start_tick} must be lower than "
                f"end_tick {self.end_tick}"
            )
        return self


class Rumor(StrictModel):
    """A piece of town talk the player can overhear.

    Attributes:
        id: Identifier of the rumor.
        text: Text of the rumor.
        npc_id: Id of the NPC who spreads the rumor.
        min_tick: First absolute tick at which the rumor can be heard.
        max_tick: Last absolute tick at which the rumor can be heard.
        sets_flags: Flags raised when the rumor is heard.
    """

    id: str
    text: str
    npc_id: str
    min_tick: int = 0
    max_tick: int = total_ticks()
    sets_flags: tuple[str, ...] = ()

    @field_validator("min_tick", "max_tick")
    @classmethod
    def _check_tick(cls, value: int, info: Any) -> int:
        """Check that a tick lies inside the cycle.

        Args:
            value: Tick to check.
            info: Validation context, used to name the offending field.

        Returns:
            The validated tick.

        Raises:
            ValueError: If the tick is out of range.
        """
        field_name = info.field_name or "rumor tick"
        if not 0 <= value <= total_ticks():
            raise ValueError(f"rumor.{field_name} must be within [0, {total_ticks()}], got {value}")
        return value

    @model_validator(mode="after")
    def _check_window(self) -> Self:
        """Check that the hearing window is not inverted.

        Returns:
            The validated rumor.

        Raises:
            ValueError: If ``min_tick`` is greater than ``max_tick``.
        """
        if self.min_tick > self.max_tick:
            raise ValueError(
                f"rumor {self.id}: min_tick {self.min_tick} must not be greater than "
                f"max_tick {self.max_tick}"
            )
        return self


class ResourceSpec(StrictModel):
    """A provision of the town that the player spends by acting.

    The provisions are the pressure of the second half of the game: every
    action draws on a finite stock, and a stock that runs low puts the town
    in crisis. The engine knows nothing about *what* is being stocked; it
    only knows the amounts and the costs.

    Attributes:
        id: Identifier of the resource, e.g. ``"RES_FOOD"``.
        label: Display name of the resource.
        initial: Amount the town starts the cycle with. Must be at least 0.
        per_action: Amount consumed by a single action. Must be at least 0.
        critical_at: Amount at or below which the town suffers. A resource
            is in crisis when its amount falls **strictly below** this
            value.
    """

    id: str
    label: str
    initial: int
    per_action: int
    critical_at: int

    @field_validator("initial", "per_action", "critical_at")
    @classmethod
    def _check_not_negative(cls, value: int, info: Any) -> int:
        """Check that a quantity is not negative.

        Args:
            value: Quantity to check.
            info: Validation context, used to name the offending field.

        Returns:
            The validated quantity.

        Raises:
            ValueError: If the quantity is negative.
        """
        field_name = info.field_name or "resource amount"
        if value < 0:
            raise ValueError(f"resource.{field_name} must be >= 0, got {value}")
        return value

    @model_validator(mode="after")
    def _check_critical_threshold(self) -> Self:
        """Check that the critical threshold is reachable.

        A threshold above the initial amount would mean the resource is
        already in crisis when the cycle starts, which is never what the
        content means.

        Returns:
            The validated specification.

        Raises:
            ValueError: If ``critical_at`` is greater than ``initial``.
        """
        if self.critical_at > self.initial:
            raise ValueError(
                f"resource {self.id}: critical_at {self.critical_at} must not be greater "
                f"than initial {self.initial}"
            )
        return self


class WorldContent(StrictModel):
    """The root document of the whole game.

    Attributes:
        premise: The premise plate.
        zones: Zones of the town.
        npcs: Inhabitants of the town.
        events: Scheduled events.
        missions: Missions of the story.
        dialogues: Dialogue nodes.
        symptoms: Symptoms that can be collected.
        sources: Documents that can be consulted.
        causes: Candidate causes of the symptoms.
        hypotheses: Links between symptoms and causes.
        endings: Final endings of the story.
        lighting: Lighting phases of the daily cycle.
        rumors: Pieces of town talk.
        resources: Provisions of the town that the player spends by acting.
        content_version: Version of the content document.
    """

    premise: Premise
    zones: tuple[Zone, ...] = ()
    npcs: tuple[Npc, ...] = ()
    events: tuple[Event, ...] = ()
    missions: tuple[Mission, ...] = ()
    dialogues: tuple[DialogueNode, ...] = ()
    symptoms: tuple[Symptom, ...] = ()
    sources: tuple[Source, ...] = ()
    causes: tuple[Cause, ...] = ()
    hypotheses: tuple[Hypothesis, ...] = ()
    endings: tuple[Ending, ...] = ()
    lighting: tuple[LightingPhase, ...] = ()
    rumors: tuple[Rumor, ...] = ()
    resources: tuple[ResourceSpec, ...] = ()
    content_version: str = "0.0.0"

    # ------------------------------------------------------------------
    # Cross-model validation
    # ------------------------------------------------------------------

    @model_validator(mode="after")
    def _check_unique_ids(self) -> Self:
        """Check that every collection holds unique ids.

        Returns:
            The validated document.

        Raises:
            ValueError: If a collection holds a duplicated id.
        """
        collections: Sequence[tuple[str, Sequence[Any]]] = (
            ("zones", self.zones),
            ("npcs", self.npcs),
            ("events", self.events),
            ("missions", self.missions),
            ("dialogues", self.dialogues),
            ("symptoms", self.symptoms),
            ("sources", self.sources),
            ("causes", self.causes),
            ("hypotheses", self.hypotheses),
            ("endings", self.endings),
            ("lighting", self.lighting),
            ("rumors", self.rumors),
            ("resources", self.resources),
        )
        for name, items in collections:
            duplicates = _duplicate_ids(items, name)
            if duplicates:
                raise ValueError(f"world content: duplicated {name} ids {duplicates}")
        return self

    @model_validator(mode="after")
    def _check_references(self) -> Self:
        """Check that every cross-document reference resolves.

        Returns:
            The validated document.

        Raises:
            ValueError: If a reference points at something that does not
                exist.
        """
        zone_ids = {zone.id for zone in self.zones}
        npc_ids = {npc.id for npc in self.npcs}
        dialogue_ids = {node.id for node in self.dialogues}
        symptom_ids = {symptom.id for symptom in self.symptoms}
        source_ids = {source.id for source in self.sources}
        cause_ids = {cause.id for cause in self.causes}
        hypothesis_ids = {hypothesis.id for hypothesis in self.hypotheses}

        for npc in self.npcs:
            if npc.dialogue_root and npc.dialogue_root not in dialogue_ids:
                raise ValueError(
                    f"npc {npc.id}: dialogue_root {npc.dialogue_root!r} does not exist"
                )
            for entry in npc.schedule:
                if entry.zone_id not in zone_ids:
                    raise ValueError(
                        f"npc {npc.id}: schedule references unknown zone {entry.zone_id!r}"
                    )

        for mission in self.missions:
            if mission.giver_npc not in npc_ids:
                raise ValueError(
                    f"mission {mission.id}: giver_npc {mission.giver_npc!r} does not exist"
                )

        for event in self.events:
            for zone_id in event.zone_ids:
                if zone_id not in zone_ids:
                    raise ValueError(f"event {event.id}: references unknown zone {zone_id!r}")
            for npc_id in event.npc_ids:
                if npc_id not in npc_ids:
                    raise ValueError(f"event {event.id}: references unknown npc {npc_id!r}")

        for symptom in self.symptoms:
            if symptom.source_npc is not None and symptom.source_npc not in npc_ids:
                raise ValueError(
                    f"symptom {symptom.id}: source_npc {symptom.source_npc!r} does not exist"
                )
            for reporter in symptom.reported_by:
                if reporter not in npc_ids:
                    raise ValueError(
                        f"symptom {symptom.id}: reported_by references unknown npc {reporter!r}"
                    )

        for hypothesis in self.hypotheses:
            for symptom_id in hypothesis.symptom_ids:
                if symptom_id not in symptom_ids:
                    raise ValueError(
                        f"hypothesis {hypothesis.id}: references unknown symptom {symptom_id!r}"
                    )
            if hypothesis.cause_id not in cause_ids:
                raise ValueError(
                    f"hypothesis {hypothesis.id}: references unknown cause {hypothesis.cause_id!r}"
                )

        for source in self.sources:
            for cause_id in (*source.supports, *source.refutes):
                if cause_id not in cause_ids:
                    raise ValueError(f"source {source.id}: references unknown cause {cause_id!r}")

        for node in self.dialogues:
            for option in node.options:
                if option.next_node is not None and option.next_node not in dialogue_ids:
                    raise ValueError(
                        f"dialogue node {node.id}: option {option.id!r} points at "
                        f"unknown node {option.next_node!r}"
                    )
                if option.reports_symptom is not None and (
                    option.reports_symptom not in symptom_ids
                ):
                    raise ValueError(
                        f"dialogue node {node.id}: option {option.id!r} reports unknown "
                        f"symptom {option.reports_symptom!r}"
                    )

        for rumor in self.rumors:
            if rumor.npc_id not in npc_ids:
                raise ValueError(f"rumor {rumor.id}: references unknown npc {rumor.npc_id!r}")

        for premise_stage in self.premise.progression_stages:
            if premise_stage not in symptom_ids:
                raise ValueError(
                    f"premise {self.premise.id}: progression stage {premise_stage!r} does not exist"
                )

        for source_ref in (
            self.premise.partial_cure_source,
            self.premise.total_cure_source,
        ):
            if source_ref not in source_ids:
                raise ValueError(
                    f"premise {self.premise.id}: cure source {source_ref!r} does not exist"
                )

        del hypothesis_ids
        return self

    @model_validator(mode="after")
    def _check_symptom_to_cause_coverage(self) -> Self:
        """Check that every symptom of the progression has a candidate cause.

        The ``symptom -> cause`` table is the only thing the investigation
        engine knows about the disease. A symptom of the progression without
        a cause would be a dead end for the player.

        Returns:
            The validated document.

        Raises:
            ValueError: If a symptom of the progression has no cause.
        """
        covered: set[str] = set()
        for hypothesis in self.hypotheses:
            covered.update(hypothesis.symptom_ids)
        missing = [stage for stage in self.premise.progression_stages if stage not in covered]
        if missing:
            raise ValueError(
                f"world content: symptoms {missing} of the premise progression have "
                f"no candidate cause in the symptom -> cause table"
            )
        return self

    @model_validator(mode="after")
    def _check_every_cause_has_a_source(self) -> Self:
        """Check that every cause is confirmed or refuted by some source.

        A cause nobody can confirm or refute is not a hypothesis: it would be
        noise in the notebook.

        Returns:
            The validated document.

        Raises:
            ValueError: If a cause has neither a supporting nor a refuting
                source.
        """
        covered: set[str] = set()
        for source in self.sources:
            covered.update(source.supports)
            covered.update(source.refutes)
        missing = [cause.id for cause in self.causes if cause.id not in covered]
        if missing:
            raise ValueError(
                f"world content: causes {missing} have no source that supports or refutes them"
            )
        return self

    @model_validator(mode="after")
    def _check_lighting_covers_the_day(self) -> Self:
        """Check that the lighting table covers the 96 ticks of a day.

        Every tick must belong to exactly one phase: no gaps and no overlaps.

        Returns:
            The validated document.

        Raises:
            ValueError: If the table has a gap, an overlap or the wrong
                number of phases.
        """
        if len(self.lighting) != LIGHTING_PHASE_COUNT:
            raise ValueError(
                f"world content: the lighting table must hold exactly "
                f"{LIGHTING_PHASE_COUNT} phases, got {len(self.lighting)}"
            )
        ordered = sorted(self.lighting, key=lambda phase: phase.start_tick)
        expected_start = 0
        for phase in ordered:
            if phase.start_tick != expected_start:
                raise ValueError(
                    f"world content: lighting phases leave a gap or overlap at tick "
                    f"{expected_start}: phase {phase.id!r} starts at {phase.start_tick}"
                )
            expected_start = phase.end_tick
        if expected_start != TICKS_PER_DAY:
            raise ValueError(
                f"world content: the lighting table must cover the {TICKS_PER_DAY} ticks "
                f"of a day, it covers {expected_start}"
            )
        return self
