"""Pydantic models describing the build-time content pipeline output.

The models of this module are the **contract** between the language model and
the repository. The model may only write text: every identifier, flag,
symptom and cause it mentions has to exist in the authored content, and the
cross-model validators below enforce exactly that.

This is the mechanism that keeps the AI from degrading the system: the
generated output is validated against these models *before* it is written to
disk, so an invalid answer fails the pipeline instead of reaching Godot.

The models are deliberately separate from the ones in :mod:`content.schema`:
the authored content describes the *structure* of the game, while the
generated content describes *variations* on top of it.
"""

from __future__ import annotations

import re
from typing import Self

from pydantic import Field, field_validator, model_validator

from content.schema import StrictModel
from core.time import total_ticks

__all__ = [
    "DialogueVariant",
    "DialogueVariantBundle",
    "GeneratedHypothesis",
    "GeneratedRumor",
    "HypothesisBundle",
    "QuestHook",
    "QuestHookBundle",
    "RumorBundle",
]

_ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


class _GeneratedModel(StrictModel):
    """Base class of the generated models, with a shared id policy."""

    @field_validator("id", check_fields=False)
    @classmethod
    def _check_id_shape(cls, value: str) -> str:
        """Check that an identifier is an upper-case slug.

        Args:
            value: Identifier to check.

        Returns:
            The validated identifier.

        Raises:
            ValueError: If the identifier is not an upper-case slug.
        """
        if not _ID_PATTERN.fullmatch(value):
            raise ValueError(
                f"generated id must be an upper-case slug such as 'RUM_HARBOUR', got {value!r}"
            )
        return value


class GeneratedRumor(_GeneratedModel):
    """A piece of town talk produced by the language model.

    Attributes:
        id: Stable identifier of the rumour.
        text: Text of the rumour.
        npc_id: Id of the NPC who spreads the rumour.
        min_tick: Earliest absolute tick at which the rumour can be heard.
        max_tick: Latest absolute tick at which the rumour can be heard.
        sets_flags: Flags raised when the rumour is heard.
    """

    id: str
    text: str
    npc_id: str
    min_tick: int = 0
    max_tick: int = total_ticks()
    sets_flags: tuple[str, ...] = ()

    @field_validator("min_tick", "max_tick")
    @classmethod
    def _check_tick(cls, value: int, info: object) -> int:
        """Check that a tick lies inside the cycle.

        Args:
            value: Tick to check.
            info: Validation context, used to name the offending field.

        Returns:
            The validated tick.

        Raises:
            ValueError: If the tick is out of range.
        """
        field_name = getattr(info, "field_name", None) or "tick"
        if not 0 <= value <= total_ticks():
            raise ValueError(f"rumor.{field_name} must be within [0, {total_ticks()}], got {value}")
        return value

    @model_validator(mode="after")
    def _check_window(self) -> Self:
        """Check that the hearing window is not inverted.

        Returns:
            The validated rumour.

        Raises:
            ValueError: If ``min_tick`` is greater than ``max_tick``.
        """
        if self.min_tick > self.max_tick:
            raise ValueError(
                f"rumor {self.id}: min_tick {self.min_tick} must not be greater "
                f"than max_tick {self.max_tick}"
            )
        return self


class RumorBundle(_GeneratedModel):
    """The bundle of rumours produced for the ``rumors`` target.

    Attributes:
        rumors: The generated rumours.
    """

    rumors: tuple[GeneratedRumor, ...] = ()

    @model_validator(mode="after")
    def _check_ids_are_unique(self) -> Self:
        """Check that no two rumours share an id.

        Returns:
            The validated bundle.

        Raises:
            ValueError: If two rumours share an id.
        """
        identifiers = [rumor.id for rumor in self.rumors]
        duplicates = sorted({item for item in identifiers if identifiers.count(item) > 1})
        if duplicates:
            raise ValueError(f"duplicated rumour ids {duplicates}")
        return self


class DialogueVariant(_GeneratedModel):
    """A rewritten version of a dialogue line.

    Attributes:
        id: Stable identifier of the variant.
        npc_id: Id of the NPC who speaks the line.
        activity: Activity the line belongs to.
        text: The rewritten line.
        source_line: The original line that was rewritten.
    """

    id: str
    npc_id: str
    activity: str | None = None
    text: str
    source_line: str


class DialogueVariantBundle(_GeneratedModel):
    """The bundle of dialogue variants produced for the ``dialogue_variants`` target.

    Attributes:
        variants: The generated variants.
    """

    variants: tuple[DialogueVariant, ...] = ()

    @model_validator(mode="after")
    def _check_ids_are_unique(self) -> Self:
        """Check that no two variants share an id.

        Returns:
            The validated bundle.

        Raises:
            ValueError: If two variants share an id.
        """
        identifiers = [variant.id for variant in self.variants]
        duplicates = sorted({item for item in identifiers if identifiers.count(item) > 1})
        if duplicates:
            raise ValueError(f"duplicated dialogue variant ids {duplicates}")
        return self


class QuestHook(_GeneratedModel):
    """The narrative hook of an optional side quest.

    Attributes:
        id: Stable identifier of the side quest.
        title: Short title of the side quest.
        giver_npc: Id of the NPC who proposes the side quest.
        summary: What the player is asked to do.
        hint: A short nudge the player can read in the world.
    """

    id: str
    title: str
    giver_npc: str
    summary: str
    hint: str


class QuestHookBundle(_GeneratedModel):
    """The bundle of hooks produced for the ``quest_hooks`` target.

    Attributes:
        hooks: The generated hooks.
    """

    hooks: tuple[QuestHook, ...] = ()

    @model_validator(mode="after")
    def _check_ids_are_unique(self) -> Self:
        """Check that no two hooks share an id.

        Returns:
            The validated bundle.

        Raises:
            ValueError: If two hooks share an id.
        """
        identifiers = [hook.id for hook in self.hooks]
        duplicates = sorted({item for item in identifiers if identifiers.count(item) > 1})
        if duplicates:
            raise ValueError(f"duplicated quest hook ids {duplicates}")
        return self


class GeneratedHypothesis(_GeneratedModel):
    """A candidate cause proposed by the language model.

    Attributes:
        id: Stable identifier of the proposal.
        cause_id: Id of the candidate cause.
        symptom_ids: Ids of the symptoms the candidate explains.
        reasoning: Why the candidate fits the collected symptoms.
        verification_method: How the player could check the candidate.
        verification_target: Id of what the player should examine.
    """

    id: str
    cause_id: str
    symptom_ids: tuple[str, ...]
    reasoning: str
    verification_method: str = ""
    verification_target: str = ""

    @model_validator(mode="after")
    def _check_symptoms_are_not_empty(self) -> Self:
        """Check that the proposal explains at least one symptom.

        Returns:
            The validated proposal.

        Raises:
            ValueError: If no symptom is listed.
        """
        if not self.symptom_ids:
            raise ValueError(f"hypothesis proposal {self.id} must explain at least one symptom")
        return self


class HypothesisBundle(_GeneratedModel):
    """The bundle of proposals produced for the ``hypotheses`` target.

    Attributes:
        hypotheses: The generated proposals.
    """

    hypotheses: tuple[GeneratedHypothesis, ...] = ()

    @model_validator(mode="after")
    def _check_ids_are_unique(self) -> Self:
        """Check that no two proposals share an id.

        Returns:
            The validated bundle.

        Raises:
            ValueError: If two proposals share an id.
        """
        identifiers = [proposal.id for proposal in self.hypotheses]
        duplicates = sorted({item for item in identifiers if identifiers.count(item) > 1})
        if duplicates:
            raise ValueError(f"duplicated hypothesis proposal ids {duplicates}")
        return self


#: The bundle model used for each generation target.
BUNDLE_MODELS: dict[str, type[StrictModel]] = {
    "rumors": RumorBundle,
    "dialogue_variants": DialogueVariantBundle,
    "quest_hooks": QuestHookBundle,
    "hypotheses": HypothesisBundle,
}


def bundle_model(target: str) -> type[StrictModel]:
    """Return the bundle model of a generation target.

    Args:
        target: Name of the generation target.

    Returns:
        The pydantic model that validates the output of the target.

    Raises:
        KeyError: If the target is unknown.
    """
    return BUNDLE_MODELS[target]


#: The key of the bundle that holds the items of each target.
BUNDLE_KEYS: dict[str, str] = {
    "rumors": "rumors",
    "dialogue_variants": "variants",
    "quest_hooks": "hooks",
    "hypotheses": "hypotheses",
}


#: Re-exported so that the pipeline can build an empty document easily.
EMPTY_BUNDLE: dict[str, Field] = Field(default_factory=dict)
