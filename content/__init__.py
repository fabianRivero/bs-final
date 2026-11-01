"""Game content package: schemas, authored data, generation and validation.

The package is the *data* layer of the project. It owns:

* :mod:`content.schema` -- the pydantic models every content document is
  validated against.
* :mod:`content.generated_schema` -- the models that constrain what the
  language model is allowed to write.
* :mod:`content.llm` -- the abstracted LLM client and its on-disk cache.
* :mod:`content.generate` -- the build-time generation pipeline.
* :mod:`content.validate` -- the validator that gates the content in CI.
"""

from __future__ import annotations

from content.schema import (
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
    MissionKind,
    MissionStep,
    Npc,
    ObjectiveKind,
    Premise,
    Rumor,
    ScheduleEntry,
    Source,
    SourceKind,
    Symptom,
    WorldContent,
    Zone,
)

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
    "Rumor",
    "ScheduleEntry",
    "Source",
    "SourceKind",
    "Symptom",
    "WorldContent",
    "Zone",
]
