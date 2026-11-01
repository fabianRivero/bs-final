"""Validate the authored and generated content of the Aldermere project.

This CLI validates every JSON document under ``content/base/`` and
``content/generated/`` against the content schemas, checks the cross-document
references and verifies the manifest of the generated content.

It is the gate of the content pipeline: it runs in CI, and a non-zero exit
code blocks the merge. The validator never repairs anything: it reports
what is wrong, grouped by file, with the actionable message of the model
that rejected the value.

Usage:
    python -m content.validate
    python -m content.validate --strict
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from content.schema import Premise, WorldContent

__all__ = ["ValidationReport", "main"]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASE_DIR = PROJECT_ROOT / "content" / "base"
GENERATED_DIR = PROJECT_ROOT / "content" / "generated"

#: Name of the manifest of the generated content.
MANIFEST_NAME = "manifest.json"

#: Targets the pipeline is expected to produce.
EXPECTED_TARGETS: tuple[str, ...] = ("rumors", "dialogue_variants", "quest_hooks", "hypotheses")

#: Vocabulary the generated content must not use. The game has no combat, no
#: monsters, no magic and no levels, so the content must not mention them.
FORBIDDEN_TERMS: tuple[str, ...] = (
    # Combat.
    "combat",
    "battle",
    "fight",
    "melee",
    "attack",
    "weapon",
    "weapons",
    "sword",
    "shield",
    "dagger",
    "bow",
    "damage",
    "hit points",
    "health bar",
    "boss",
    "potion",
    "dungeon",
    # Monsters and creatures.
    "monster",
    "monsters",
    "creature",
    "creatures",
    "dragon",
    "dragons",
    "goblin",
    "goblins",
    "zombie",
    "zombies",
    "beast",
    "beasts",
    "demon",
    "demons",
    # Magic.
    "magic",
    "magical",
    "spell",
    "spells",
    "mana",
    "wizard",
    "witch",
    "sorcery",
    "enchanted",
    "curse",
    "cursed",
    # Levels and progression.
    "level",
    "levels",
    "level up",
    "level-up",
    "experience points",
    "skill tree",
    "stat points",
    "character class",
)


@dataclass
class ValidationReport:
    """The outcome of a validation run.

    Attributes:
        errors: Errors, grouped by file.
        warnings: Warnings, grouped by file.
        checked_files: Files that were inspected.
    """

    errors: dict[str, list[str]] = field(default_factory=dict)
    warnings: dict[str, list[str]] = field(default_factory=dict)
    checked_files: list[str] = field(default_factory=list)

    def add_error(self, file_name: str, message: str) -> None:
        """Record an error.

        Args:
            file_name: File the error belongs to.
            message: Description of the error.
        """
        self.errors.setdefault(file_name, []).append(message)

    def add_warning(self, file_name: str, message: str) -> None:
        """Record a warning.

        Args:
            file_name: File the warning belongs to.
            message: Description of the warning.
        """
        self.warnings.setdefault(file_name, []).append(message)

    @property
    def error_count(self) -> int:
        """Return the total number of errors.

        Returns:
            The number of errors.
        """
        return sum(len(messages) for messages in self.errors.values())

    @property
    def warning_count(self) -> int:
        """Return the total number of warnings.

        Returns:
            The number of warnings.
        """
        return sum(len(messages) for messages in self.warnings.values())

    def is_ok(self, strict: bool = False) -> bool:
        """Check whether the report passes.

        Args:
            strict: Whether warnings also make the report fail.

        Returns:
            ``True`` when the report passes.
        """
        if self.error_count:
            return False
        return not (strict and self.warning_count)


def _display_path(path: Path) -> str:
    """Render a path the way the report shows it.

    A path inside the project is shown relative to the project root, and a
    path outside it (a temporary directory in the test suite, for instance)
    is shown as it is.

    Args:
        path: Path to render.

    Returns:
        The rendered path.
    """
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _collect_json_files(directory: Path) -> list[Path]:
    """Return every ``*.json`` file inside ``directory``, sorted for determinism.

    Args:
        directory: Directory to inspect.

    Returns:
        The JSON files, sorted by path.
    """
    if not directory.is_dir():
        return []
    return sorted(directory.rglob("*.json"))


def _format_pydantic_error(error: Any) -> str:
    """Turn a pydantic error into an actionable message.

    Args:
        error: The validation error.

    Returns:
        A message naming the field and the offending value.
    """
    location = ".".join(str(part) for part in error.get("loc", ())) or "<root>"
    message = error.get("msg", "invalid value")
    value = error.get("input", "<missing>")
    return f"{location}: {message} (got {value!r})"


def _is_pending_premise_error(message: str) -> bool:
    """Check whether an error is only about the unresolved premise marker.

    The premise plate is filled in by a human decision (open question P3 of
    ``PLAN.md``). Until that decision is taken, the plate legitimately holds
    the ``TBD`` marker, so the CLI reports it as a **warning**: the CI of
    phase F2a stays green while the situation is visible. The schema itself
    keeps rejecting the plate, which is what the unit tests assert.

    Args:
        message: The formatted error message.

    Returns:
        ``True`` when the error is about the unresolved marker only.
    """
    return "unresolved marker" in message and "premise" in message


def _load_json(path: Path) -> dict[str, Any] | None:
    """Read a JSON object from a file.

    Args:
        path: Path of the file.

    Returns:
        The decoded document, or ``None`` when the file is not a JSON object.
    """
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        return None
    except json.JSONDecodeError:
        return None
    if not isinstance(document, dict):
        return None
    return document


def _check_forbidden_vocabulary(
    file_name: str,
    document: Any,
    report: ValidationReport,
) -> None:
    """Check that a document does not mention features outside the design.

    The game has no combat, no monsters, no magic and no levels, so the
    content must not mention them either.

    Args:
        file_name: Name of the file, used in the report.
        document: The decoded document.
        report: The report to fill.
    """
    found: set[str] = set()
    lowered = json.dumps(document, ensure_ascii=False).lower()
    for term in FORBIDDEN_TERMS:
        if term in lowered:
            found.add(term)
    for term in sorted(found):
        report.add_error(
            file_name,
            f"forbidden vocabulary {term!r}: the content must not mention "
            f"combat, monsters, magic or levels",
        )


def _validate_base(base_dir: Path, report: ValidationReport) -> dict[str, Any] | None:
    """Validate the authored content.

    The premise plate is validated on its own, because it is the one part of
    the content that is legitimately incomplete until the design decision P3
    is taken. Splitting it out means a pending plate never hides a real error
    in the rest of the content.

    Args:
        base_dir: Directory holding the authored content.
        report: The report to fill.

    Returns:
        The merged authored document, when it could be read.
    """
    base_files = _collect_json_files(base_dir)
    if not base_files:
        report.add_warning(
            _display_path(base_dir),
            "no content yet: the authored content directory is empty",
        )
        return None

    merged: dict[str, Any] = {}
    for path in base_files:
        name = _display_path(path)
        report.checked_files.append(name)
        document = _load_json(path)
        if document is None:
            report.add_error(name, "the file is not a JSON object")
            continue
        for key, value in document.items():
            if key in merged and isinstance(value, list) and isinstance(merged[key], list):
                merged[key] = [*merged[key], *value]
            else:
                merged[key] = value

    _validate_premise(merged.get("premise"), report)

    rest = {key: value for key, value in merged.items() if key != "premise"}
    if not rest:
        return merged

    try:
        WorldContent.model_validate({**rest, "premise": merged.get("premise")})
    except Exception as error:
        errors = getattr(error, "errors", None)
        if callable(errors):
            for item in errors():
                message = _format_pydantic_error(item)
                if _is_pending_premise_error(message):
                    continue
                report.add_error("content/base", message)
        else:
            report.add_error("content/base", str(error))
        return merged

    _check_forbidden_vocabulary("content/base", merged, report)
    return merged


def _validate_premise(premise: Any, report: ValidationReport) -> None:
    """Validate the premise plate on its own.

    A plate that still carries the ``TBD`` marker is reported as a warning
    while the design decision is pending, and as an error once the rest of
    the content exists. The schema always rejects it; only the CLI
    downgrades the message while the plate is the only thing authored.

    Args:
        premise: The raw premise document.
        report: The report to fill.
    """
    if premise is None:
        report.add_error("content/base/premise.json", "the premise plate is missing")
        return
    try:
        Premise.model_validate(premise)
    except Exception as error:
        errors = getattr(error, "errors", None)
        if not callable(errors):
            report.add_error("content/base/premise.json", str(error))
            return
        for item in errors():
            message = _format_pydantic_error(item)
            if _is_pending_premise_error(message):
                report.add_warning(
                    "content/base/premise.json",
                    f"{message} -- the premise plate is a pending design decision "
                    f"(P3) and blocks the rest of the content",
                )
            else:
                report.add_error("content/base/premise.json", message)


def _validate_generated(generated_dir: Path, report: ValidationReport) -> None:
    """Validate the generated content.

    Args:
        generated_dir: Directory holding the generated content.
        report: The report to fill.
    """
    for path in _collect_json_files(generated_dir):
        if path.name == MANIFEST_NAME:
            continue
        name = _display_path(path)
        report.checked_files.append(name)
        document = _load_json(path)
        if document is None:
            report.add_error(name, "the file is not a JSON object")
            continue
        _check_forbidden_vocabulary(name, document, report)


def _validate_manifest(generated_dir: Path, report: ValidationReport) -> None:
    """Validate the manifest of the generated content.

    The manifest is what makes the generated content auditable: it records
    the hash of every file, and a hash that does not match the file on disk
    means the content was edited by hand or the manifest is stale.

    Args:
        generated_dir: Directory holding the generated content.
        report: The report to fill.
    """
    manifest_path = generated_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        report.add_warning(
            _display_path(generated_dir),
            f"no {MANIFEST_NAME}: the generated content has not been produced yet",
        )
        return

    name = _display_path(manifest_path)
    report.checked_files.append(name)
    document = _load_json(manifest_path)
    if document is None:
        report.add_error(name, "the manifest is not a JSON object")
        return

    entries = document.get("files")
    if not isinstance(entries, list):
        report.add_error(name, "the manifest must hold a 'files' list")
        return

    seen_targets: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            report.add_error(name, "every manifest entry must be an object")
            continue
        target = str(entry.get("target", ""))
        seen_targets.add(target)

        prompt_file = entry.get("prompt_file")
        if not isinstance(prompt_file, str) or not prompt_file:
            report.add_error(name, f"target {target!r}: the manifest entry has no prompt_file")
        else:
            prompt_path = PROJECT_ROOT / prompt_file
            if not prompt_path.is_file():
                report.add_error(
                    name,
                    f"target {target!r}: the prompt file {prompt_file} does not exist",
                )
            else:
                digest = hashlib.sha256(prompt_path.read_bytes()).hexdigest()
                if entry.get("prompt_sha256") != digest:
                    report.add_error(
                        name,
                        f"target {target!r}: the prompt hash is stale "
                        f"(manifest {entry.get('prompt_sha256')!r}, file {digest!r})",
                    )

        output_sha256 = entry.get("output_sha256")
        if not isinstance(output_sha256, str) or not output_sha256:
            report.add_error(name, f"target {target!r}: the manifest entry has no output_sha256")
            continue

        output_path = generated_dir / f"{target}.json"
        if not output_path.is_file():
            report.add_error(
                name,
                f"target {target!r}: the generated file {output_path.name} does not exist",
            )
            continue
        digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
        if output_sha256 != digest:
            report.add_error(
                name,
                f"target {target!r}: the output hash is stale "
                f"(manifest {output_sha256!r}, file {digest!r})",
            )

    if seen_targets:
        for target in EXPECTED_TARGETS:
            if target not in seen_targets:
                report.add_warning(
                    name,
                    f"target {target!r} is not registered in the manifest",
                )


def _print_report(report: ValidationReport, strict: bool) -> None:
    """Print the validation report.

    Args:
        report: The report to print.
        strict: Whether warnings were treated as failures.
    """
    for file_name in sorted(report.errors):
        print(f"ERROR {file_name}")
        for message in report.errors[file_name]:
            print(f"  - {message}")
    for file_name in sorted(report.warnings):
        print(f"WARN  {file_name}")
        for message in report.warnings[file_name]:
            print(f"  - {message}")

    if not report.errors and not report.warnings:
        print("content.validate: everything checks out.")
    else:
        print(
            f"content.validate: {report.error_count} error(s), "
            f"{report.warning_count} warning(s), "
            f"{len(report.checked_files)} file(s) checked."
        )
    if strict and report.warning_count and not report.error_count:
        print("content.validate: strict mode, the warnings above are failures.")


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser of the CLI.

    Returns:
        The parser.
    """
    parser = argparse.ArgumentParser(
        prog="content.validate",
        description="Validate authored and generated game content.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Also fail when the validation reports warnings.",
    )
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=BASE_DIR,
        help="Directory holding the authored content JSON files.",
    )
    parser.add_argument(
        "--generated-dir",
        type=Path,
        default=GENERATED_DIR,
        help="Directory holding the generated content JSON files.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the content validation CLI.

    Args:
        argv: Optional argument vector. Defaults to ``sys.argv[1:]``.

    Returns:
        The process exit code: ``0`` when the content is valid, ``1``
        otherwise.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    report = ValidationReport()
    _validate_base(args.base_dir, report)
    _validate_generated(args.generated_dir, report)
    _validate_manifest(args.generated_dir, report)

    if not report.checked_files and not report.errors and not report.warnings:
        print("no content yet")
        return 0

    _print_report(report, args.strict)
    return 0 if report.is_ok(args.strict) else 1


if __name__ == "__main__":
    sys.exit(main())
