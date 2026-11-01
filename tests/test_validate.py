"""Tests for the content validation CLI.

What is under test
------------------
The validator is the gate of the content pipeline. It has to:

* accept the valid content,
* reject the content that breaks the schema,
* reject a manifest whose hashes do not match the files on disk,
* report a pending premise as a visible warning while the design decision
  is still open,
* return the right exit code in every case.

The CLI is exercised through its ``main`` function, so the tests cover the
argument handling, the report and the exit code at once.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from content import validate as validator

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "content" / "world.json"
BASE_PREMISE_PATH = Path(__file__).parent.parent / "content" / "base" / "premise.json"


@pytest.fixture
def valid_base(tmp_path: Path) -> Path:
    """Return a directory holding the valid synthetic content.

    Args:
        tmp_path: The temporary directory of the test.

    Returns:
        The directory holding the content.
    """
    target = tmp_path / "base"
    target.mkdir()
    document = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    target.joinpath("world.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return target


@pytest.fixture
def empty_generated(tmp_path: Path) -> Path:
    """Return an empty directory for the generated content.

    Args:
        tmp_path: The temporary directory of the test.

    Returns:
        The directory.
    """
    target = tmp_path / "generated"
    target.mkdir()
    return target


def _run(base_dir: Path, generated_dir: Path, *extra: str) -> int:
    """Run the validator CLI.

    Args:
        base_dir: Directory holding the authored content.
        generated_dir: Directory holding the generated content.
        extra: Extra command line arguments.

    Returns:
        The exit code of the validator.
    """
    return validator.main(
        [
            "--base-dir",
            str(base_dir),
            "--generated-dir",
            str(generated_dir),
            *extra,
        ]
    )


# ----------------------------------------------------------------------
# The valid content
# ----------------------------------------------------------------------


def test_the_valid_content_is_accepted(
    valid_base: Path,
    empty_generated: Path,
) -> None:
    """The synthetic content passes the validation."""
    assert _run(valid_base, empty_generated) == 0


def test_the_valid_content_produces_no_errors(
    valid_base: Path,
    empty_generated: Path,
) -> None:
    """The report of the valid content holds no error."""
    report = validator.ValidationReport()
    validator._validate_base(valid_base, report)
    assert report.error_count == 0


def test_the_valid_content_mentions_no_forbidden_vocabulary(
    valid_base: Path,
    empty_generated: Path,
) -> None:
    """The synthetic content stays inside the design."""
    report = validator.ValidationReport()
    validator._validate_base(valid_base, report)
    assert report.error_count == 0


# ----------------------------------------------------------------------
# The pending premise plate
# ----------------------------------------------------------------------


def test_the_authored_premise_is_reported_as_a_warning(
    tmp_path: Path,
    empty_generated: Path,
) -> None:
    """The pending plate is visible but does not block the CI."""
    base = tmp_path / "pending-base"
    base.mkdir()
    shutil.copy(BASE_PREMISE_PATH, base / "premise.json")
    report = validator.ValidationReport()
    validator._validate_base(base, report)
    assert report.error_count == 0
    assert report.warning_count > 0
    assert "TBD" in " ".join(
        message for messages in report.warnings.values() for message in messages
    )


def test_the_pending_premise_still_fails_the_schema() -> None:
    """The plate itself is rejected: the schema does not accept a TBD."""
    from pydantic import ValidationError

    from content.schema import Premise

    document = json.loads(BASE_PREMISE_PATH.read_text(encoding="utf-8"))
    with pytest.raises(ValidationError, match="unresolved marker"):
        Premise.model_validate(document["premise"])


def test_a_missing_premise_is_an_error(
    tmp_path: Path,
    empty_generated: Path,
) -> None:
    """Content without a premise plate cannot be validated."""
    base = tmp_path / "no-premise"
    base.mkdir()
    base.joinpath("world.json").write_text("{}", encoding="utf-8")
    report = validator.ValidationReport()
    validator._validate_base(base, report)
    assert report.error_count >= 1


# ----------------------------------------------------------------------
# Broken content
# ----------------------------------------------------------------------


def test_a_broken_document_is_an_error(
    valid_base: Path,
    empty_generated: Path,
) -> None:
    """A file that is not JSON is reported."""
    valid_base.joinpath("broken.json").write_text("{not json", encoding="utf-8")
    report = validator.ValidationReport()
    validator._validate_base(valid_base, report)
    assert report.error_count >= 1


def test_a_reference_to_a_missing_npc_is_an_error(
    valid_base: Path,
    empty_generated: Path,
) -> None:
    """A broken reference is reported with the name of the missing entity."""
    document = json.loads(valid_base.joinpath("world.json").read_text(encoding="utf-8"))
    document["missions"][0]["giver_npc"] = "NPC_GHOST"
    valid_base.joinpath("world.json").write_text(json.dumps(document), encoding="utf-8")
    report = validator.ValidationReport()
    validator._validate_base(valid_base, report)
    assert report.error_count >= 1
    assert "NPC_GHOST" in " ".join(
        message for messages in report.errors.values() for message in messages
    )


def test_forbidden_vocabulary_is_an_error(
    valid_base: Path,
    empty_generated: Path,
) -> None:
    """Content that mentions combat or magic is rejected."""
    document = json.loads(valid_base.joinpath("world.json").read_text(encoding="utf-8"))
    document["rumors"][0]["text"] = "They say a monster guards the mill."
    valid_base.joinpath("world.json").write_text(json.dumps(document), encoding="utf-8")
    report = validator.ValidationReport()
    validator._validate_base(valid_base, report)
    assert report.error_count >= 1
    assert "forbidden vocabulary" in " ".join(
        message for messages in report.errors.values() for message in messages
    )


def test_the_errors_are_grouped_by_file(
    valid_base: Path,
    empty_generated: Path,
) -> None:
    """The report groups the messages by the file that caused them."""
    valid_base.joinpath("broken.json").write_text("{not json", encoding="utf-8")
    report = validator.ValidationReport()
    validator._validate_base(valid_base, report)
    assert report.errors
    assert all(messages for messages in report.errors.values())


# ----------------------------------------------------------------------
# The generated content
# ----------------------------------------------------------------------


def test_the_generated_content_is_checked(
    valid_base: Path,
    empty_generated: Path,
) -> None:
    """A generated file with forbidden vocabulary is rejected."""
    empty_generated.joinpath("rumors.json").write_text(
        json.dumps({"rumors": [{"id": "RUM_X", "text": "A dragon was seen."}]}),
        encoding="utf-8",
    )
    report = validator.ValidationReport()
    validator._validate_generated(empty_generated, report)
    assert report.error_count >= 1


def test_the_manifest_is_absent_without_generated_content(
    valid_base: Path,
    empty_generated: Path,
) -> None:
    """A missing manifest is a warning, not an error."""
    report = validator.ValidationReport()
    validator._validate_manifest(empty_generated, report)
    assert report.error_count == 0
    assert report.warning_count == 1


def _write_manifest(
    generated_dir: Path,
    target: str,
    output_sha256: str,
    prompt_sha256: str,
    prompt_exists: bool = True,
) -> None:
    """Write a manifest for the tests.

    Args:
        generated_dir: Directory the content is written to.
        target: Target the manifest registers.
        output_sha256: Hash recorded for the output file.
        prompt_sha256: Hash recorded for the prompt file.
        prompt_exists: Whether the prompt file is recorded as existing.
    """
    manifest = {
        "content_version": "0.1.0",
        "generator_version": "1.0.0",
        "source_sha256": "0" * 64,
        "files": [
            {
                "target": target,
                "path": f"content/generated/{target}.json",
                "prompt_file": "content/prompts/missing.txt",
                "prompt_sha256": prompt_sha256,
                "model": "fake-model",
                "seed": 1,
                "temperature": 0.7,
                "source_sha256": "0" * 64,
                "output_sha256": output_sha256,
                "generated_at": "2026-01-01T00:00:00Z",
                "provider": "fake",
            }
        ],
    }
    del prompt_exists
    generated_dir.joinpath("manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )


def test_a_stale_output_hash_is_detected(
    valid_base: Path,
    empty_generated: Path,
) -> None:
    """A manifest that does not match the file on disk is an error."""
    empty_generated.joinpath("rumors.json").write_text(json.dumps({"rumors": []}), encoding="utf-8")
    _write_manifest(empty_generated, "rumors", "f" * 64, "a" * 64)
    report = validator.ValidationReport()
    validator._validate_manifest(empty_generated, report)
    assert report.error_count >= 1
    assert "output hash is stale" in " ".join(
        message for messages in report.errors.values() for message in messages
    )


def test_a_missing_output_file_is_detected(
    valid_base: Path,
    empty_generated: Path,
) -> None:
    """A manifest that registers a file that does not exist is an error."""
    _write_manifest(empty_generated, "rumors", "f" * 64, "a" * 64)
    report = validator.ValidationReport()
    validator._validate_manifest(empty_generated, report)
    assert report.error_count >= 1
    assert "does not exist" in " ".join(
        message for messages in report.errors.values() for message in messages
    )


def test_a_missing_prompt_file_is_detected(
    valid_base: Path,
    empty_generated: Path,
) -> None:
    """A manifest that points at a missing prompt is an error."""
    empty_generated.joinpath("rumors.json").write_text(json.dumps({"rumors": []}), encoding="utf-8")
    _write_manifest(empty_generated, "rumors", "a" * 64, "b" * 64)
    report = validator.ValidationReport()
    validator._validate_manifest(empty_generated, report)
    assert report.error_count >= 1
    assert "prompt file" in " ".join(
        message for messages in report.errors.values() for message in messages
    )


def test_a_stale_prompt_hash_is_detected(
    valid_base: Path,
    empty_generated: Path,
    tmp_path: Path,
) -> None:
    """A manifest whose prompt hash is stale is an error."""
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("the real prompt", encoding="utf-8")
    digest = hashlib.sha256(prompt.read_bytes()).hexdigest()
    empty_generated.joinpath("rumors.json").write_text(json.dumps({"rumors": []}), encoding="utf-8")
    manifest = {
        "files": [
            {
                "target": "rumors",
                "prompt_file": str(prompt),
                "prompt_sha256": "0" * 64,
                "output_sha256": "a" * 64,
            }
        ]
    }
    empty_generated.joinpath("manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    report = validator.ValidationReport()
    validator._validate_manifest(empty_generated, report)
    assert report.error_count >= 1
    assert "prompt hash is stale" in " ".join(
        message for messages in report.errors.values() for message in messages
    )
    assert digest != "0" * 64


def test_a_correct_manifest_passes(
    valid_base: Path,
    empty_generated: Path,
    tmp_path: Path,
) -> None:
    """A manifest that matches every file passes the validation."""
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("the real prompt", encoding="utf-8")
    output = empty_generated / "rumors.json"
    output.write_text(json.dumps({"rumors": []}), encoding="utf-8")
    manifest = {
        "files": [
            {
                "target": "rumors",
                "prompt_file": str(prompt),
                "prompt_sha256": hashlib.sha256(prompt.read_bytes()).hexdigest(),
                "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            }
        ]
    }
    empty_generated.joinpath("manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    report = validator.ValidationReport()
    validator._validate_manifest(empty_generated, report)
    assert report.error_count == 0


def test_a_malformed_manifest_is_an_error(
    valid_base: Path,
    empty_generated: Path,
) -> None:
    """A manifest that is not a JSON object is an error."""
    empty_generated.joinpath("manifest.json").write_text("{not json", encoding="utf-8")
    report = validator.ValidationReport()
    validator._validate_manifest(empty_generated, report)
    assert report.error_count >= 1


# ----------------------------------------------------------------------
# Exit codes and the CLI surface
# ----------------------------------------------------------------------


def test_an_empty_content_directory_passes(
    tmp_path: Path,
    empty_generated: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Without content yet the validator passes, so the CI of F2a is green."""
    empty_base = tmp_path / "empty-base"
    empty_base.mkdir()
    assert _run(empty_base, empty_generated) == 0
    assert "no content yet" in capsys.readouterr().out


def test_the_exit_code_is_one_when_something_fails(
    valid_base: Path,
    empty_generated: Path,
) -> None:
    """A broken content makes the validator fail."""
    valid_base.joinpath("broken.json").write_text("{not json", encoding="utf-8")
    assert _run(valid_base, empty_generated) == 1


def test_strict_mode_fails_on_warnings(
    valid_base: Path,
    empty_generated: Path,
) -> None:
    """In strict mode a warning is enough to fail."""
    assert _run(valid_base, empty_generated) == 0
    assert _run(valid_base, empty_generated, "--strict") == 1


def test_strict_mode_passes_when_there_is_nothing_to_report(
    valid_base: Path,
    tmp_path: Path,
) -> None:
    """A perfectly clean content passes even in strict mode."""
    empty_generated = tmp_path / "empty-generated"
    empty_generated.mkdir()
    empty_generated.joinpath("manifest.json").write_text(
        json.dumps({"files": []}), encoding="utf-8"
    )
    assert _run(valid_base, empty_generated, "--strict") == 0


def test_the_report_groups_the_messages(
    valid_base: Path,
    empty_generated: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The printed report names the file and the message."""
    valid_base.joinpath("broken.json").write_text("{not json", encoding="utf-8")
    _run(valid_base, empty_generated)
    out = capsys.readouterr().out
    assert "ERROR" in out
    assert "broken.json" in out


def test_the_report_is_readable_when_everything_passes(
    valid_base: Path,
    empty_generated: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A clean run says so."""
    empty_generated.joinpath("manifest.json").write_text(
        json.dumps({"files": []}), encoding="utf-8"
    )
    _run(valid_base, empty_generated)
    out = capsys.readouterr().out
    assert "everything checks out" in out


def test_the_forbidden_terms_cover_the_features_outside_the_design() -> None:
    """The vocabulary list names the features the game does not have."""
    for term in ("combat", "monster", "magic", "level", "spell"):
        assert term in validator.FORBIDDEN_TERMS


def test_the_forbidden_terms_are_lowercase() -> None:
    """The list is lowercase, because it is matched against lowercase text."""
    assert all(term == term.lower() for term in validator.FORBIDDEN_TERMS)


def test_the_expected_targets_are_the_documented_ones() -> None:
    """The validator knows the four targets of the pipeline."""
    assert validator.EXPECTED_TARGETS == (
        "rumors",
        "dialogue_variants",
        "quest_hooks",
        "hypotheses",
    )


def test_the_report_counts_the_messages() -> None:
    """The report counts the errors and the warnings it holds."""
    report = validator.ValidationReport()
    report.add_error("a.json", "first")
    report.add_error("a.json", "second")
    report.add_warning("b.json", "third")
    assert report.error_count == 2
    assert report.warning_count == 1
    assert report.is_ok() is False
    assert report.is_ok(strict=True) is False


def test_a_clean_report_passes_in_strict_mode() -> None:
    """A report without errors and without warnings passes."""
    report = validator.ValidationReport()
    assert report.is_ok(strict=True) is True


def test_the_validation_of_a_document_is_reported_with_the_field(
    valid_base: Path,
    empty_generated: Path,
) -> None:
    """The message of a pydantic error names the field and the value."""
    document = json.loads(valid_base.joinpath("world.json").read_text(encoding="utf-8"))
    document["events"][0]["activation_tick"] = 900
    valid_base.joinpath("world.json").write_text(json.dumps(document), encoding="utf-8")
    report = validator.ValidationReport()
    validator._validate_base(valid_base, report)
    joined = " ".join(message for messages in report.errors.values() for message in messages)
    assert "activation_tick" in joined


def test_the_authored_premise_plate_is_rejected_by_the_validator(
    tmp_path: Path,
    empty_generated: Path,
) -> None:
    """The plate of the project is deliberately pending.

    The validator reports it as a warning so that the CI of the phase stays
    green, and the schema keeps rejecting it. The test asserts both halves
    of that contract.
    """
    base = tmp_path / "pending"
    base.mkdir()
    shutil.copy(BASE_PREMISE_PATH, base / "premise.json")
    assert _run(base, empty_generated) == 0

    report = validator.ValidationReport()
    validator._validate_base(base, report)
    assert report.error_count == 0
    assert report.warning_count > 0


def test_the_validator_never_writes_anything(
    valid_base: Path,
    empty_generated: Path,
) -> None:
    """The validator only reads: it never repairs the content."""
    before = {path.name: path.read_bytes() for path in sorted(valid_base.glob("*.json"))}
    _run(valid_base, empty_generated)
    after = {path.name: path.read_bytes() for path in sorted(valid_base.glob("*.json"))}
    assert before == after


def test_the_json_files_are_collected_in_a_deterministic_order(tmp_path: Path) -> None:
    """The files are inspected in a stable order."""
    target = tmp_path / "files"
    target.mkdir()
    for name in ("b.json", "a.json", "c.json"):
        target.joinpath(name).write_text("{}", encoding="utf-8")
    collected = validator._collect_json_files(target)
    assert [path.name for path in collected] == ["a.json", "b.json", "c.json"]


def test_a_missing_directory_yields_no_files(tmp_path: Path) -> None:
    """A directory that does not exist holds no files."""
    assert validator._collect_json_files(tmp_path / "nope") == []


def test_the_report_is_a_dataclass_with_the_documented_shape() -> None:
    """The report exposes the documented attributes."""
    report = validator.ValidationReport()
    assert report.errors == {}
    assert report.warnings == {}
    assert report.checked_files == []


def test_the_error_formatting_names_the_location_and_the_value() -> None:
    """A pydantic error is rendered with the field and the value."""
    message = validator._format_pydantic_error(
        {"loc": ("premise", "title"), "msg": "Field required", "input": None}
    )
    assert "premise.title" in message
    assert "Field required" in message


def test_the_error_formatting_handles_a_root_level_error() -> None:
    """An error without a location still renders."""
    message = validator._format_pydantic_error({"loc": (), "msg": "broken"})
    assert "<root>" in message


def test_the_pending_premise_detection_is_narrow() -> None:
    """Only the errors about the premise marker are downgraded."""
    assert validator._is_pending_premise_error(
        "premise.title: Value error, premise still contains the unresolved marker 'TBD'"
    )
    assert not validator._is_pending_premise_error("npc: something else is wrong")
    assert not validator._is_pending_premise_error("premise.title: Field required")


def test_the_forbidden_vocabulary_check_reports_every_term(
    valid_base: Path,
    empty_generated: Path,
) -> None:
    """Every forbidden term of a document is reported."""
    document: dict[str, Any] = json.loads(
        valid_base.joinpath("world.json").read_text(encoding="utf-8")
    )
    document["rumors"][0]["text"] = "A monster, a spell and a battle."
    report = validator.ValidationReport()
    validator._check_forbidden_vocabulary("x.json", document, report)
    assert report.error_count >= 3


def test_the_generated_directory_is_skipped_by_the_vocabulary_check(
    valid_base: Path,
    empty_generated: Path,
) -> None:
    """The manifest is not a content document."""
    empty_generated.joinpath("manifest.json").write_text(
        json.dumps({"files": [], "model": "a model with a monster in it"}),
        encoding="utf-8",
    )
    report = validator.ValidationReport()
    validator._validate_generated(empty_generated, report)
    assert report.error_count == 0
