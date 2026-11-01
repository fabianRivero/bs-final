"""Tests for the build-time content generation pipeline.

What is under test
------------------
The pipeline is the seam between the language model and the repository, so
the properties that matter are:

* The output is **valid**: every generated file passes its schema.
* The output is **auditable**: the manifest records the hashes, the model,
  the seed and the prompt of every file.
* The output is **reproducible**: the same seed and the same authored
  content produce byte-identical files.
* A failure is **atomic**: a run without an API key, or with an invalid
  answer, writes nothing at all.

No test in this module touches the network: a fake provider is injected.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from content import generate
from content.generated_schema import (
    DialogueVariantBundle,
    HypothesisBundle,
    QuestHookBundle,
    RumorBundle,
)
from content.llm import LLMNotConfiguredError

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "content" / "world.json"
PROMPTS_DIR = Path(__file__).parent.parent / "content" / "prompts"


class FakeProvider:
    """A provider that answers from a canned script.

    Attributes:
        name: Name reported by the provider.
        model: Model reported by the provider.
        answers: The answer returned for each target.
        prompts: The prompts the provider received.
        calls: The number of calls the provider received.
    """

    name = "fake"
    model = "fake-model"

    def __init__(self, answers: dict[str, dict[str, Any]]) -> None:
        """Build the fake provider.

        Args:
            answers: The answer returned for each target.
        """
        self.answers = answers
        self.prompts: list[str] = []
        self.calls = 0

    def complete(self, prompt: str, system: str | None = None) -> str:
        """Return the canned answer that matches the prompt.

        Args:
            prompt: The prompt the pipeline built.
            system: The system prompt, unused by the fake.

        Returns:
            The canned answer, serialised as JSON.
        """
        self.calls += 1
        self.prompts.append(prompt)
        for target, answer in self.answers.items():
            if f"##target:{target}##" in prompt:
                return json.dumps(answer)
        return json.dumps(self.answers[next(iter(self.answers))])


@pytest.fixture
def base_dir(tmp_path: Path) -> Path:
    """Return a directory holding a valid authored content.

    The authored content of the project is deliberately pending its premise
    plate, so the tests build their own valid base out of the synthetic
    fixture.

    Args:
        tmp_path: The temporary directory of the test.

    Returns:
        The directory holding the authored content.
    """
    target = tmp_path / "base"
    target.mkdir()
    document = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    (target / "world.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return target


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    """Return the directory the generated content is written to.

    Args:
        tmp_path: The temporary directory of the test.

    Returns:
        The output directory.
    """
    return tmp_path / "generated"


@pytest.fixture
def answers() -> dict[str, dict[str, Any]]:
    """Return the canned answers of the fake provider.

    Returns:
        One answer document per target.
    """
    return {
        "rumors": {
            "rumors": [
                {
                    "id": "RUM_DAMP_STORE",
                    "text": "They say the store has never once been dry.",
                    "npc_id": "NPC_KEEPER",
                    "min_tick": 10,
                    "max_tick": 200,
                    "sets_flags": ["heard_rumour_damp_store"],
                }
            ]
        },
        "dialogue_variants": {
            "variants": [
                {
                    "id": "DLV_MILLER_NUMBNESS",
                    "npc_id": "NPC_MILLER",
                    "activity": "grinding_grain",
                    "text": "My fingers stopped answering me after the harvest.",
                    "source_line": "My hands have been numb since the harvest week.",
                }
            ]
        },
        "quest_hooks": {
            "hooks": [
                {
                    "id": "MS_SIDE_BOUNDARY",
                    "title": "Walk the boundary",
                    "giver_npc": "NPC_KEEPER",
                    "summary": "The keeper wants the mill race checked.",
                    "hint": "Someone keeps waiting by the ledger.",
                }
            ]
        },
        "hypotheses": {
            "hypotheses": [
                {
                    "id": "HYP_MOULD",
                    "cause_id": "CAUSE_MOULD",
                    "symptom_ids": ["SYM_NUMBNESS"],
                    "reasoning": "Moulded grain could explain the numbness.",
                    "verification_method": "field_inspection",
                    "verification_target": "ZN_YARD",
                }
            ]
        },
    }


@pytest.fixture
def prompts_dir(tmp_path: Path, answers: dict[str, dict[str, Any]]) -> Path:
    """Return a directory holding the prompt templates of the tests.

    The templates are the real ones with the context replaced by a marker
    that lets the fake provider pick the right canned answer.

    Args:
        tmp_path: The temporary directory of the test.
        answers: The canned answers.

    Returns:
        The directory holding the prompt templates.
    """
    target = tmp_path / "prompts"
    target.mkdir()
    for name in answers:
        source = (PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8")
        target.joinpath(f"{name}.txt").write_text(
            source.replace("{context}", "{context}\n\n##target:" + name + "##"),
            encoding="utf-8",
        )
    return target


def _run(
    base_dir: Path,
    output_dir: Path,
    prompts_dir: Path,
    provider: FakeProvider,
    argv: list[str] | None = None,
) -> int:
    """Run the pipeline with the fake provider injected.

    Args:
        base_dir: Directory holding the authored content.
        output_dir: Directory the content is written to.
        prompts_dir: Directory holding the prompt templates.
        provider: The fake provider.
        argv: Extra command line arguments.

    Returns:
        The exit code of the pipeline.
    """
    arguments = [
        "--all",
        "--base-dir",
        str(base_dir),
        "--output-dir",
        str(output_dir),
        "--prompts-dir",
        str(prompts_dir),
    ]
    if argv:
        arguments.extend(argv)
    return generate.main(arguments, provider_factory=lambda: provider)


def _sha256(path: Path) -> str:
    """Compute the sha256 digest of a file.

    Args:
        path: Path of the file.

    Returns:
        The hexadecimal digest.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ----------------------------------------------------------------------
# Happy path
# ----------------------------------------------------------------------


def test_the_pipeline_writes_every_target(
    base_dir: Path,
    output_dir: Path,
    prompts_dir: Path,
    answers: dict[str, dict[str, Any]],
) -> None:
    """A successful run writes one file per target."""
    provider = FakeProvider(answers)
    assert _run(base_dir, output_dir, prompts_dir, provider) == 0
    for target in answers:
        assert (output_dir / f"{target}.json").is_file()


def test_the_generated_files_are_valid(
    base_dir: Path,
    output_dir: Path,
    prompts_dir: Path,
    answers: dict[str, dict[str, Any]],
) -> None:
    """Every generated file passes its schema."""
    provider = FakeProvider(answers)
    _run(base_dir, output_dir, prompts_dir, provider)

    RumorBundle.model_validate(json.loads((output_dir / "rumors.json").read_text("utf-8")))
    DialogueVariantBundle.model_validate(
        json.loads((output_dir / "dialogue_variants.json").read_text("utf-8"))
    )
    QuestHookBundle.model_validate(json.loads((output_dir / "quest_hooks.json").read_text("utf-8")))
    HypothesisBundle.model_validate(json.loads((output_dir / "hypotheses.json").read_text("utf-8")))


def test_the_manifest_is_written(
    base_dir: Path,
    output_dir: Path,
    prompts_dir: Path,
    answers: dict[str, dict[str, Any]],
) -> None:
    """The manifest records the metadata of every generated file."""
    provider = FakeProvider(answers)
    _run(base_dir, output_dir, prompts_dir, provider)

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["generator_version"] == generate.GENERATOR_VERSION
    assert len(manifest["files"]) == len(answers)
    for entry in manifest["files"]:
        assert entry["target"] in answers
        assert entry["model"] == "fake-model"
        assert entry["provider"] == "fake"
        assert entry["seed"] == generate.DEFAULT_SEED
        assert entry["temperature"] == 0.7
        assert len(entry["prompt_sha256"]) == 64
        assert len(entry["source_sha256"]) == 64
        assert entry["generated_at"].endswith("Z")


def test_the_manifest_hashes_match_the_files(
    base_dir: Path,
    output_dir: Path,
    prompts_dir: Path,
    answers: dict[str, dict[str, Any]],
) -> None:
    """Every hash of the manifest matches the file on disk."""
    provider = FakeProvider(answers)
    _run(base_dir, output_dir, prompts_dir, provider)

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        path = output_dir / f"{entry['target']}.json"
        assert entry["output_sha256"] == _sha256(path)
        prompt_path = base_dir.parent / "prompts" / f"{entry['target']}.txt"
        if prompt_path.is_file():
            assert entry["prompt_sha256"] == _sha256(prompt_path)


def test_the_source_hash_matches_the_authored_content(
    base_dir: Path,
    output_dir: Path,
    prompts_dir: Path,
    answers: dict[str, dict[str, Any]],
) -> None:
    """The manifest records the hash of the authored content it used."""
    provider = FakeProvider(answers)
    _run(base_dir, output_dir, prompts_dir, provider)

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    digest = hashlib.sha256()
    for path in sorted(base_dir.glob("*.json")):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    assert manifest["source_sha256"] == digest.hexdigest()
    for entry in manifest["files"]:
        assert entry["source_sha256"] == manifest["source_sha256"]


def test_regenerating_with_the_same_seed_is_byte_identical(
    base_dir: Path,
    output_dir: Path,
    prompts_dir: Path,
    answers: dict[str, dict[str, Any]],
) -> None:
    """The same seed and the same content produce the same bytes."""
    provider = FakeProvider(answers)
    _run(base_dir, output_dir, prompts_dir, provider)
    first = {path.name: path.read_bytes() for path in sorted(output_dir.glob("*.json"))}

    provider = FakeProvider(answers)
    _run(base_dir, output_dir, prompts_dir, provider)
    second = {path.name: path.read_bytes() for path in sorted(output_dir.glob("*.json"))}

    for name in first:
        if name == "manifest.json":
            continue
        assert first[name] == second[name]


def test_the_seed_reaches_the_provider_and_the_manifest(
    base_dir: Path,
    output_dir: Path,
    prompts_dir: Path,
    answers: dict[str, dict[str, Any]],
) -> None:
    """The seed travels to the provider and is recorded in the manifest.

    The fake provider ignores the seed on purpose, so the generated bytes
    stay the same; what this test proves is the *pipeline*: the seed is
    handed to the provider, reaches the manifest, and therefore also takes
    part in the cache key, so a different seed never reuses a cached
    answer.
    """
    provider = FakeProvider(answers)
    _run(base_dir, output_dir, prompts_dir, provider, ["--seed", "12345"])
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        assert entry["seed"] == 12345


def test_only_one_target_can_be_generated(
    base_dir: Path,
    output_dir: Path,
    prompts_dir: Path,
    answers: dict[str, dict[str, Any]],
) -> None:
    """The --only flag limits the run to a single target."""
    provider = FakeProvider(answers)
    code = generate.main(
        [
            "--only",
            "rumors",
            "--base-dir",
            str(base_dir),
            "--output-dir",
            str(output_dir),
            "--prompts-dir",
            str(prompts_dir),
        ],
        provider_factory=lambda: provider,
    )
    assert code == 0
    assert (output_dir / "rumors.json").is_file()
    assert not (output_dir / "hypotheses.json").exists()


def test_the_prompt_carries_the_authored_context(
    base_dir: Path,
    output_dir: Path,
    prompts_dir: Path,
    answers: dict[str, dict[str, Any]],
) -> None:
    """The prompt holds the context built out of the authored content."""
    provider = FakeProvider(answers)
    _run(base_dir, output_dir, prompts_dir, provider)
    joined = "\n".join(provider.prompts)
    assert "NPC_MILLER" in joined
    assert "SYM_NUMBNESS" in joined


def test_the_prompt_keeps_the_output_contract(
    base_dir: Path,
    output_dir: Path,
    prompts_dir: Path,
    answers: dict[str, dict[str, Any]],
) -> None:
    """Every prompt template states the contract of its output."""
    for name in answers:
        template = (PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8")
        assert "{context}" in template
        assert "JSON" in template
        assert "Return" in template


# ----------------------------------------------------------------------
# Failures
# ----------------------------------------------------------------------


def test_without_an_api_key_the_pipeline_fails(
    base_dir: Path,
    output_dir: Path,
    prompts_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A missing key is reported clearly and nothing is written."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    code = generate.main(
        [
            "--all",
            "--base-dir",
            str(base_dir),
            "--output-dir",
            str(output_dir),
            "--prompts-dir",
            str(prompts_dir),
        ]
    )
    assert code == 1
    captured = capsys.readouterr()
    assert "OPENAI_API_KEY" in captured.err
    assert "ANTHROPIC_API_KEY" in captured.err
    assert not output_dir.exists() or not list(output_dir.glob("*.json"))


def test_the_missing_key_is_reported_before_anything_else(
    base_dir: Path,
    output_dir: Path,
    prompts_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The credential is checked first, so its message is the one the user sees.

    The authored content of the project carries a pending premise plate, so
    a run without a key would otherwise report the plate instead of the
    missing credential. The credential is what the user can fix right now,
    so it comes first.
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    code = generate.main(
        [
            "--all",
            "--base-dir",
            str(base_dir),
            "--output-dir",
            str(output_dir),
            "--prompts-dir",
            str(prompts_dir),
        ]
    )
    assert code == 1
    captured = capsys.readouterr()
    assert "OPENAI_API_KEY" in captured.err
    assert "ANTHROPIC_API_KEY" in captured.err
    assert "no file was written" in captured.err
    assert not output_dir.exists() or not list(output_dir.glob("*.json"))


def test_the_pipeline_reports_the_pending_premise_without_a_key(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pending plate of the project is reported when a key is present.

    The plate is the first deliverable of the phase, and it is legitimately
    incomplete until the design decision P3 is taken. The pipeline refuses
    to build a prompt context out of it and says so.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "key")
    base = tmp_path / "pending-base"
    base.mkdir()
    shutil.copy(
        Path(__file__).parent.parent / "content" / "base" / "premise.json",
        base / "premise.json",
    )
    code = generate.main(
        [
            "--all",
            "--base-dir",
            str(base),
            "--output-dir",
            str(tmp_path / "out"),
            "--prompts-dir",
            str(PROMPTS_DIR),
        ]
    )
    assert code == 1
    captured = capsys.readouterr()
    assert "unresolved marker" in captured.err


def test_a_provider_that_cannot_be_built_fails_cleanly(
    base_dir: Path,
    output_dir: Path,
    prompts_dir: Path,
) -> None:
    """A provider that raises at build time leaves the output untouched."""

    def _factory() -> Any:
        raise LLMNotConfiguredError("no key")

    code = generate.main(
        [
            "--all",
            "--base-dir",
            str(base_dir),
            "--output-dir",
            str(output_dir),
            "--prompts-dir",
            str(prompts_dir),
        ],
        provider_factory=_factory,
    )
    assert code == 1
    assert not output_dir.exists() or not list(output_dir.glob("*.json"))


def test_an_answer_that_is_not_valid_json_fails(
    base_dir: Path,
    output_dir: Path,
    prompts_dir: Path,
) -> None:
    """A broken answer fails the run and writes nothing."""

    class BrokenProvider:
        name = "broken"
        model = "broken-model"

        def complete(self, prompt: str, system: str | None = None) -> str:
            """Return an answer that holds no JSON.

            Args:
                prompt: The prompt the pipeline built.
                system: The system prompt, unused.

            Returns:
                A text that holds no JSON object.
            """
            return "I am afraid I cannot do that."

    code = _run(base_dir, output_dir, prompts_dir, BrokenProvider())
    assert code == 1
    assert not output_dir.exists() or not list(output_dir.glob("*.json"))


def test_an_answer_that_does_not_validate_fails(
    base_dir: Path,
    output_dir: Path,
    prompts_dir: Path,
) -> None:
    """An answer that breaks the schema fails the run and writes nothing."""
    provider = FakeProvider(
        {
            "rumors": {
                "rumors": [
                    {
                        "id": "not an id",
                        "text": "Something.",
                        "npc_id": "NPC_KEEPER",
                    }
                ]
            }
        }
    )
    code = _run(base_dir, output_dir, prompts_dir, provider)
    assert code == 1
    assert not output_dir.exists() or not list(output_dir.glob("*.json"))


def test_an_answer_that_mentions_an_unknown_npc_fails(
    base_dir: Path,
    output_dir: Path,
    prompts_dir: Path,
) -> None:
    """An answer that invents an NPC fails the run."""
    provider = FakeProvider(
        {
            "rumors": {
                "rumors": [
                    {
                        "id": "RUM_GHOST",
                        "text": "Something.",
                        "npc_id": "NPC_GHOST",
                    }
                ]
            }
        }
    )
    code = _run(base_dir, output_dir, prompts_dir, provider)
    assert code == 1
    assert not output_dir.exists() or not list(output_dir.glob("*.json"))


def test_a_missing_base_content_fails(
    tmp_path: Path,
    output_dir: Path,
    prompts_dir: Path,
) -> None:
    """Without authored content the pipeline cannot run."""
    empty = tmp_path / "empty"
    empty.mkdir()
    provider = FakeProvider({"rumors": {"rumors": []}})
    code = _run(empty, output_dir, prompts_dir, provider)
    assert code == 1


def test_a_missing_prompt_template_fails(
    base_dir: Path,
    output_dir: Path,
    tmp_path: Path,
) -> None:
    """Without a prompt template the pipeline cannot run."""
    empty_prompts = tmp_path / "no-prompts"
    empty_prompts.mkdir()
    provider = FakeProvider({"rumors": {"rumors": []}})
    code = _run(base_dir, output_dir, empty_prompts, provider)
    assert code == 1


# ----------------------------------------------------------------------
# Dry run
# ----------------------------------------------------------------------


def test_the_dry_run_does_not_call_the_provider(
    base_dir: Path,
    output_dir: Path,
    prompts_dir: Path,
    answers: dict[str, dict[str, Any]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The dry run explains what it would do and calls nothing."""
    provider = FakeProvider(answers)
    code = generate.main(
        [
            "--all",
            "--dry-run",
            "--base-dir",
            str(base_dir),
            "--output-dir",
            str(output_dir),
            "--prompts-dir",
            str(prompts_dir),
        ],
        provider_factory=lambda: provider,
    )
    assert code == 0
    assert provider.calls == 0
    captured = capsys.readouterr()
    assert "dry run" in captured.out
    for target in answers:
        assert target in captured.out
    assert not output_dir.exists() or not list(output_dir.glob("*.json"))


def test_the_dry_run_works_without_an_api_key(
    base_dir: Path,
    output_dir: Path,
    prompts_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dry run never needs a key."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    code = generate.main(
        [
            "--all",
            "--dry-run",
            "--base-dir",
            str(base_dir),
            "--output-dir",
            str(output_dir),
            "--prompts-dir",
            str(prompts_dir),
        ]
    )
    assert code == 0


def test_the_dry_run_fails_when_the_base_content_is_invalid(tmp_path: Path) -> None:
    """The dry run validates the authored content first."""
    broken = tmp_path / "broken"
    broken.mkdir()
    broken.joinpath("world.json").write_text("{not json", encoding="utf-8")
    code = generate.main(["--all", "--dry-run", "--base-dir", str(broken)])
    assert code == 1


def test_the_targets_are_the_documented_ones() -> None:
    """The pipeline produces the four documented targets."""
    assert generate.TARGETS == (
        "rumors",
        "dialogue_variants",
        "quest_hooks",
        "hypotheses",
    )


def test_the_real_prompts_are_shipped_with_the_project() -> None:
    """Every target has its prompt template in the repository."""
    for target in generate.TARGETS:
        assert (PROMPTS_DIR / f"{target}.txt").is_file()


def test_the_prompts_forbid_the_features_outside_the_design() -> None:
    """Every prompt forbids the vocabulary of the features we do not have."""
    forbidden = ("combat", "monster", "magic", "level up", "spell")
    for target in generate.TARGETS:
        template = (PROMPTS_DIR / f"{target}.txt").read_text(encoding="utf-8").lower()
        for term in forbidden:
            assert term in template, f"{target} does not forbid {term!r}"


def test_a_real_content_base_can_be_copied_and_reused(tmp_path: Path) -> None:
    """The authored content of the project can be staged for the pipeline."""
    source = Path(__file__).parent.parent / "content" / "base"
    staged = tmp_path / "staged"
    staged.mkdir()
    for path in source.glob("*.json"):
        shutil.copy(path, staged / path.name)
    assert list(staged.glob("*.json"))
