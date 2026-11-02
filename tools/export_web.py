"""Export the simulation content into the JSON contract consumed by Godot.

Produces ``game/data/game_content.json`` from the authored and generated
content. The output is deterministic: regenerating it without content changes
yields a byte-identical file.

The exported document is the **single contract** between the Python simulation
core and the Godot presentation layer. It carries:

* the content documents themselves (premise, zones, NPCs, symptoms, sources,
  causes, hypotheses, events, missions, dialogues, endings, rumors);
* the **lighting table**, copied from :mod:`core.lighting`, so Godot applies
  the phases Python decided on;
* the **clock constants**, copied from :mod:`core.time`, so Godot formats the
  clock exactly like Python does;
* the **resources**, copied from the content document, so Godot can display
  the provisions of the town and mirror their consumption.

Usage:
    python -m tools.export_web
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from core.lighting import LIGHTING_TABLE
from core.time import CYCLE_DAYS, MINUTES_PER_TICK, TICKS_PER_DAY, TOTAL_TICKS

__all__ = [
    "GAME_CONTENT_PATH",
    "GAME_DATA_DIR",
    "build_document",
    "main",
    "validate_document",
    "write_document",
]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BUILD_DIR = PROJECT_ROOT / "build"

#: Directory of the Godot project that consumes the exported document.
GAME_DATA_DIR = PROJECT_ROOT / "game" / "data"

#: Path of the exported document inside the Godot project.
GAME_CONTENT_PATH = GAME_DATA_DIR / "game_content.json"

#: Path of the synthetic fixture used as the source content of the prototype.
FIXTURE_PATH = PROJECT_ROOT / "tests" / "fixtures" / "content" / "world.json"


def _load_source_content() -> dict[str, Any]:
    """Load the content document that is exported.

    The prototype exports the synthetic fixture, which is a valid content
    document validated by ``content.schema``. The authored content under
    ``content/base`` is still a work in progress, so it is not used yet.

    Returns:
        The parsed content document.

    Raises:
        FileNotFoundError: If the fixture is missing.
        ValueError: If the fixture is not a JSON object.
    """
    if not FIXTURE_PATH.exists():
        raise FileNotFoundError(f"content fixture is missing: {FIXTURE_PATH}")
    document = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"content fixture must hold a JSON object: {FIXTURE_PATH}")
    return document


def _lighting_document() -> list[dict[str, Any]]:
    """Build the lighting table of the exported document.

    The table is copied from :mod:`core.lighting`, which is the single source
    of truth for the phases. The ids are prefixed with ``LGT_`` to match the
    convention of ``content.schema``, and a ``palette_id`` is derived from the
    phase id so a palette can be selected per phase.

    Returns:
        The lighting phases, ordered by ``start_tick``.
    """
    document: list[dict[str, Any]] = []
    for phase in LIGHTING_TABLE:
        document.append(
            {
                "id": f"LGT_{phase.id.upper()}",
                "phase_id": phase.id,
                "start_tick": phase.start_tick,
                "end_tick": phase.end_tick,
                "rgb": list(phase.rgb),
                "opacity": phase.opacity,
                "palette_id": phase.id,
            }
        )
    return document


def build_document(source: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the document that Godot consumes.

    The document is the content itself plus the two tables that Python owns and
    Godot must not re-invent: the lighting phases and the clock constants.
    The resources of the town are part of the content document and travel
    with it, so Godot can display them and mirror their consumption.

    Args:
        source: The content document to export. When omitted, the synthetic
            fixture of ``tests/fixtures/content/world.json`` is used.

    Returns:
        The exported document, ready to be serialised.
    """
    content: dict[str, Any] = dict(source) if source is not None else _load_source_content()

    content["lighting"] = _lighting_document()
    content["resources"] = _resources_document(content.get("resources", []))
    content["clock"] = {
        "minutes_per_tick": MINUTES_PER_TICK,
        "ticks_per_day": TICKS_PER_DAY,
        "cycle_days": CYCLE_DAYS,
        "total_ticks": TOTAL_TICKS,
    }
    content.setdefault("content_version", "0.0.0")
    return content


def _resources_document(raw_resources: object) -> list[dict[str, Any]]:
    """Build the resources section of the exported document.

    The resources are declared in the content document, so they are copied
    verbatim. The section is normalised to a list of plain objects, and it is
    always present, even when the town stocks nothing: Godot then knows the
    shape of the contract instead of guessing it.

    Every resource is exported with the fields the presentation layer needs
    to mirror the simulation: ``initial``, ``per_action``, ``critical_at``,
    ``daily_decay`` and ``blocks_actions``. The last two are the ones the
    GDScript mirror of ``core/resources.py`` needs to reproduce the daily
    decay and the cost multiplier of a critical resource.

    Args:
        raw_resources: The ``resources`` field of the content document.

    Returns:
        The resource documents, in the order they were declared.

    Raises:
        ValueError: If the field is not a list.
    """
    if not isinstance(raw_resources, list):
        raise ValueError("the 'resources' field must be a list")

    document: list[dict[str, Any]] = []
    for raw in raw_resources:
        if not isinstance(raw, dict):
            raise ValueError("every resource must be an object")
        blocks = raw.get("blocks_actions", [])
        if not isinstance(blocks, list) or not all(isinstance(kind, str) for kind in blocks):
            raise ValueError("the 'blocks_actions' field must be a list of strings")
        document.append(
            {
                "id": str(raw.get("id", "")),
                "label": str(raw.get("label", raw.get("id", ""))),
                "initial": int(raw.get("initial", 0)),
                "per_action": int(raw.get("per_action", 0)),
                "critical_at": int(raw.get("critical_at", 0)),
                "daily_decay": int(raw.get("daily_decay", 0)),
                "blocks_actions": list(blocks),
            }
        )
    return document


def validate_document(document: dict[str, Any]) -> None:
    """Check that the exported document is a valid content document.

    The exported document carries two keys that the content schema does not
    know about: ``clock`` and the ``phase_id`` of every lighting phase. They
    are stripped before the validation, so what is validated is exactly the
    content the simulation core understands.

    Args:
        document: The exported document.

    Raises:
        ValueError: If the document does not validate against the schema.
    """
    from content.schema import WorldContent

    validated: dict[str, Any] = {key: value for key, value in document.items() if key != "clock"}
    phases: list[dict[str, Any]] = []
    for phase in validated.get("lighting", []):
        stripped = {key: value for key, value in phase.items() if key != "phase_id"}
        phases.append(stripped)
    validated["lighting"] = phases

    try:
        WorldContent.model_validate(validated)
    except Exception as error:
        raise ValueError(
            f"the exported document is not a valid content document: {error}"
        ) from error


def write_document(document: dict[str, Any], path: Path = GAME_CONTENT_PATH) -> Path:
    """Write the exported document to disk.

    The output is deterministic: the same document always produces the same
    bytes, so the exported file can be committed and diffed.

    Args:
        document: The document to write.
        path: Destination of the document.

    Returns:
        The path the document was written to.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(document, indent=2, ensure_ascii=False, sort_keys=False)
    path.write_text(text + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    """Run the export CLI.

    Args:
        argv: Optional argument vector. Defaults to ``sys.argv[1:]``.

    Returns:
        The process exit code: ``0`` on success, ``1`` when the export fails.
    """
    parser = argparse.ArgumentParser(
        prog="tools.export_web",
        description="Export the game content to the Godot JSON contract.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=BUILD_DIR,
        help="Directory where the exported artefacts are written.",
    )
    parser.add_argument(
        "--game-content",
        type=Path,
        default=GAME_CONTENT_PATH,
        help="Destination of the JSON contract consumed by the Godot project.",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=FIXTURE_PATH,
        help="Content document to export.",
    )
    arguments = parser.parse_args(argv)

    print("tools.export_web: exporting the content contract to Godot")

    try:
        source: dict[str, Any] = json.loads(arguments.source.read_text(encoding="utf-8"))
        if not isinstance(source, dict):
            raise ValueError("the content document must hold a JSON object")
        document = build_document(source)
        validate_document(document)
        written = write_document(document, arguments.game_content)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"  source:     {arguments.source}")
    print(f"  content:    {written}")
    print(f"  lighting:   {len(document['lighting'])} phases")
    print(f"  resources:  {len(document['resources'])} provisions")
    for resource in document["resources"]:
        blocks = resource["blocks_actions"]
        blocked = ", ".join(blocks) if blocks else "-"
        print(
            f"    - {resource['id']:<14} {resource['label']:<10}"
            f" initial {resource['initial']:>3}"
            f"  per_action {resource['per_action']}"
            f"  critical_at {resource['critical_at']}"
            f"  daily_decay {resource['daily_decay']}"
            f"  blocks [{blocked}]"
        )
    print(
        f"  clock:      {MINUTES_PER_TICK} min/tick, {TICKS_PER_DAY} ticks/day, "
        f"{CYCLE_DAYS} days, {TOTAL_TICKS} ticks"
    )

    # The HTML5 export and its presets are still part of the later phases.
    print("tools.export_web: the HTML5 export itself is still part of PLAN.md F5")

    return 0


if __name__ == "__main__":
    sys.exit(main())
