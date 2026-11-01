"""Build-time content generation pipeline for Aldermere.

Reads the authored content plus the prompt templates, queries the configured
LLM provider, validates the response against the content schemas and writes
versioned output to ``content/generated/``.

The pipeline is deterministic by construction:

* The authored content is hashed, and the hash is part of the manifest.
* The prompt, the model, the temperature and the **seed** take part in the
  cache key, so an unchanged regeneration costs nothing and a changed seed
  always produces a different answer.
* The manifest records the sha256 of every file it writes, so a stale file is
  detectable.

Nothing is written until every target has been produced *and* validated. A
failed run therefore never leaves half-written content behind.

Usage:
    python -m content.generate --all
    python -m content.generate --only rumors
    python -m content.generate --all --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from content.generated_schema import BUNDLE_KEYS, bundle_model
from content.llm import (
    DEFAULT_TEMPERATURE,
    LLMError,
    LLMNotConfiguredError,
    LLMProvider,
    provider_from_env,
)
from content.schema import WorldContent

__all__ = ["GenerationError", "main"]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = PROJECT_ROOT / "content" / "prompts"
BASE_DIR = PROJECT_ROOT / "content" / "base"
GENERATED_DIR = PROJECT_ROOT / "content" / "generated"

#: The generation targets, in the order they are produced.
TARGETS: tuple[str, ...] = ("rumors", "dialogue_variants", "quest_hooks", "hypotheses")

#: Default seed of the pipeline. It is fixed so that a regeneration with the
#: same content reproduces the same bytes.
DEFAULT_SEED = 20260514

#: Version of the pipeline, recorded in the manifest.
GENERATOR_VERSION = "1.0.0"

#: Name of the manifest file inside the generated directory.
MANIFEST_NAME = "manifest.json"


class GenerationError(RuntimeError):
    """Raised when a target cannot be generated.

    The message explains what failed and where, so the pipeline can be run
    again after fixing the cause.
    """


@dataclass(frozen=True)
class GeneratedTarget:
    """The outcome of generating a single target.

    Attributes:
        target: Name of the target.
        prompt_file: Path of the prompt template, relative to the project
            root.
        prompt_sha256: Hash of the prompt template.
        model: Model that produced the text.
        seed: Seed that was sent with the request.
        temperature: Sampling temperature of the request.
        source_sha256: Hash of the authored content the prompt was built from.
        output_sha256: Hash of the written file.
        generated_at: ISO-8601 UTC timestamp of the generation.
        provider: Name of the provider that produced the text.
        document: The validated document that was written.
    """

    target: str
    prompt_file: str
    prompt_sha256: str
    model: str
    seed: int
    temperature: float
    source_sha256: str
    output_sha256: str
    generated_at: str
    provider: str
    document: dict[str, Any]


def _sha256_bytes(payload: bytes) -> str:
    """Compute the sha256 digest of a byte string.

    Args:
        payload: Bytes to digest.

    Returns:
        The hexadecimal digest.
    """
    return hashlib.sha256(payload).hexdigest()


def _sha256_text(text: str) -> str:
    """Compute the sha256 digest of a text.

    Args:
        text: Text to digest.

    Returns:
        The hexadecimal digest.
    """
    return _sha256_bytes(text.encode("utf-8"))


def _sha256_file(path: Path) -> str:
    """Compute the sha256 digest of a file.

    Args:
        path: Path of the file.

    Returns:
        The hexadecimal digest.
    """
    return _sha256_bytes(path.read_bytes())


def _read_json(path: Path) -> dict[str, Any]:
    """Read a JSON object from a file.

    Args:
        path: Path of the file.

    Returns:
        The decoded document.

    Raises:
        GenerationError: If the file cannot be read or does not hold an
            object.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise GenerationError(f"cannot read {path}: {error}") from error
    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        raise GenerationError(f"{path} is not valid JSON: {error}") from error
    if not isinstance(document, dict):
        raise GenerationError(f"{path} must hold a JSON object")
    return document


def _dump_json(document: dict[str, Any]) -> str:
    """Serialise a document deterministically.

    The serialisation is stable: the keys are sorted and the indentation is
    fixed, so the same document always produces the same bytes and therefore
    the same sha256.

    Args:
        document: Document to serialise.

    Returns:
        The serialised text, with a trailing newline.
    """
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _load_base_content(
    base_dir: Path,
    *,
    allow_pending_premise: bool = False,
) -> tuple[WorldContent | None, str]:
    """Load and validate the authored content.

    Args:
        base_dir: Directory holding the authored content.
        allow_pending_premise: Whether a premise plate that still carries
            the ``TBD`` marker is tolerated. It is used by the dry run, which
            only has to explain the plan and not to build a prompt out of
            the content. A real generation always requires a complete plate.

    Returns:
        The validated world content (or ``None`` when the premise is still
        pending and that was tolerated) and the hash of the authored
        documents.

    Raises:
        GenerationError: If the authored content is missing or invalid.
    """
    documents: dict[str, Any] = {}
    for path in sorted(base_dir.glob("*.json")):
        documents[path.stem] = _read_json(path)

    merged: dict[str, Any] = {}
    for document in documents.values():
        for key, value in document.items():
            if key in merged and isinstance(value, list) and isinstance(merged[key], list):
                merged[key] = [*merged[key], *value]
            else:
                merged[key] = value

    if "premise" not in merged:
        raise GenerationError(
            f"the authored content is missing the premise plate: no document under "
            f"{base_dir} holds a 'premise' key. Write the content base before "
            f"running the pipeline."
        )

    digest = hashlib.sha256()
    for path in sorted(base_dir.glob("*.json")):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())

    try:
        world = WorldContent.model_validate(merged)
    except Exception as error:
        if allow_pending_premise and _is_pending_premise_failure(error):
            return None, digest.hexdigest()
        raise GenerationError(f"the authored content does not validate: {error}") from error

    return world, digest.hexdigest()


def _is_pending_premise_failure(error: Exception) -> bool:
    """Check whether a validation failure is only about the pending plate.

    Args:
        error: The validation error.

    Returns:
        ``True`` when every reported problem is about the ``TBD`` marker of
        the premise plate.
    """
    errors = getattr(error, "errors", None)
    if not callable(errors):
        return False
    reported = errors()
    if not reported:
        return False
    return all("unresolved marker" in str(item.get("msg", "")) for item in reported)


def _build_context(world: WorldContent, target: str) -> str:
    """Build the context block of a prompt.

    The context is plain JSON: it is deterministic, it is easy to read in the
    prompt, and it makes the hash of the authored content meaningful.

    Args:
        world: The authored world content.
        target: Name of the generation target.

    Returns:
        The context text.
    """
    payload: dict[str, Any] = {
        "content_version": world.content_version,
        "premise": world.premise.model_dump(mode="json"),
        "zones": [zone.model_dump(mode="json") for zone in world.zones],
        "npcs": [npc.model_dump(mode="json") for npc in world.npcs],
        "symptoms": [symptom.model_dump(mode="json") for symptom in world.symptoms],
        "sources": [source.model_dump(mode="json") for source in world.sources],
        "causes": [cause.model_dump(mode="json") for cause in world.causes],
        "hypotheses": [item.model_dump(mode="json") for item in world.hypotheses],
        "events": [event.model_dump(mode="json") for event in world.events],
        "dialogues": [node.model_dump(mode="json") for node in world.dialogues],
    }

    if target == "dialogue_variants":
        payload["lines_to_rewrite"] = [
            {
                "npc_id": node.speaker,
                "activity": node.activity,
                "source_line": node.text,
            }
            for node in world.dialogues
            if node.text
        ]
    elif target == "quest_hooks":
        payload["known_symptoms"] = [
            symptom.id for symptom in world.symptoms if symptom.reported_by
        ]
    elif target == "hypotheses":
        payload["verification_methods"] = sorted(
            {item.verification_method for item in world.hypotheses if item.verification_method}
        )
        payload["verification_targets"] = [
            *[zone.id for zone in world.zones],
            *[npc.id for npc in world.npcs],
            *[source.id for source in world.sources],
        ]

    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _parse_model_answer(text: str) -> dict[str, Any]:
    """Parse the answer of the model as a JSON object.

    The model sometimes wraps the JSON in a markdown fence, so the fence is
    stripped before parsing.

    Args:
        text: Raw answer of the model.

    Returns:
        The decoded document.

    Raises:
        GenerationError: If the answer does not hold a JSON object.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise GenerationError("the model answer holds no JSON object")
    try:
        document = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError as error:
        raise GenerationError(f"the model answer is not valid JSON: {error}") from error
    if not isinstance(document, dict):
        raise GenerationError("the model answer is not a JSON object")
    return document


def _check_references(target: str, document: dict[str, Any], world: WorldContent) -> None:
    """Check that the generated document only mentions existing entities.

    Args:
        target: Name of the generation target.
        document: The decoded answer of the model.
        world: The authored world content.

    Raises:
        GenerationError: If the answer mentions an unknown entity.
    """
    npc_ids = {npc.id for npc in world.npcs}
    symptom_ids = {symptom.id for symptom in world.symptoms}
    cause_ids = {cause.id for cause in world.causes}
    source_ids = {source.id for source in world.sources}
    zone_ids = {zone.id for zone in world.zones}

    def _fail(message: str) -> None:
        raise GenerationError(f"the generated {target} is inconsistent: {message}")

    items = document.get(BUNDLE_KEYS[target])
    if not isinstance(items, list):
        _fail(f"the key {BUNDLE_KEYS[target]!r} must hold a list")
        return

    for item in items:
        if not isinstance(item, dict):
            _fail("every item must be an object")
            return
        if target in {"rumors", "dialogue_variants"}:
            if item.get("npc_id") not in npc_ids:
                _fail(f"unknown npc {item.get('npc_id')!r}")
        elif target == "quest_hooks":
            if item.get("giver_npc") not in npc_ids:
                _fail(f"unknown npc {item.get('giver_npc')!r}")
        elif target == "hypotheses":
            if item.get("cause_id") not in cause_ids:
                _fail(f"unknown cause {item.get('cause_id')!r}")
            for symptom_id in item.get("symptom_ids", []):
                if symptom_id not in symptom_ids:
                    _fail(f"unknown symptom {symptom_id!r}")
            target_value = item.get("verification_target")
            known = npc_ids | zone_ids | source_ids
            if target_value and target_value not in known:
                _fail(f"unknown verification target {target_value!r}")


def _relative_to_project(path: Path) -> str:
    """Render a path relative to the project root.

    A path outside the project (a temporary directory in the test suite, for
    instance) is rendered as it is, with the native separator replaced by a
    forward slash so that the manifest stays platform independent.

    Args:
        path: Path to render.

    Returns:
        The rendered path.
    """
    try:
        relative = path.resolve().relative_to(PROJECT_ROOT)
    except ValueError:
        return str(path).replace("\\", "/")
    return str(relative).replace("\\", "/")


def _generate_target(
    target: str,
    world: WorldContent,
    source_sha256: str,
    provider: LLMProvider,
    prompts_dir: Path,
    *,
    seed: int,
    temperature: float,
) -> GeneratedTarget:
    """Generate a single target.

    Args:
        target: Name of the target.
        world: The authored world content.
        source_sha256: Hash of the authored content.
        provider: Provider used to reach the model.
        prompts_dir: Directory holding the prompt templates.
        seed: Seed sent with the request.
        temperature: Sampling temperature of the request.

    Returns:
        The generated target, with its validated document.

    Raises:
        GenerationError: If the prompt is missing, the call fails or the
            answer does not validate.
    """
    prompt_path = prompts_dir / f"{target}.txt"
    if not prompt_path.is_file():
        raise GenerationError(f"the prompt template {prompt_path} does not exist")

    template = prompt_path.read_text(encoding="utf-8")
    if "{context}" not in template:
        raise GenerationError(
            f"the prompt template {prompt_path} does not hold the {{context}} placeholder"
        )
    prompt = template.replace("{context}", _build_context(world, target))

    try:
        answer = provider.complete(prompt)
    except LLMError as error:
        raise GenerationError(f"the {target} target failed: {error}") from error

    document = _parse_model_answer(answer)
    _check_references(target, document, world)

    model = bundle_model(target)
    try:
        validated = model.model_validate(document)
    except Exception as error:
        raise GenerationError(
            f"the {target} answer does not validate against {model.__name__}: {error}"
        ) from error

    serialised = _dump_json(validated.model_dump(mode="json"))
    return GeneratedTarget(
        target=target,
        prompt_file=_relative_to_project(prompt_path),
        prompt_sha256=_sha256_file(prompt_path),
        model=getattr(provider, "model", ""),
        seed=seed,
        temperature=temperature,
        source_sha256=source_sha256,
        output_sha256=_sha256_text(serialised),
        generated_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        provider=getattr(provider, "name", ""),
        document=validated.model_dump(mode="json"),
    )


def _write_manifest(
    generated_dir: Path,
    results: Sequence[GeneratedTarget],
    source_sha256: str,
    content_version: str,
) -> Path:
    """Write the manifest of the generated content.

    Args:
        generated_dir: Directory the content is written to.
        results: The generated targets.
        source_sha256: Hash of the authored content.
        content_version: Version of the content document.

    Returns:
        Path of the written manifest.
    """
    files = [
        {
            "target": result.target,
            "path": f"content/generated/{result.target}.json",
            "prompt_file": result.prompt_file,
            "prompt_sha256": result.prompt_sha256,
            "model": result.model,
            "seed": result.seed,
            "temperature": result.temperature,
            "source_sha256": result.source_sha256,
            "output_sha256": result.output_sha256,
            "generated_at": result.generated_at,
            "provider": result.provider,
        }
        for result in results
    ]
    manifest = {
        "content_version": content_version,
        "generator_version": GENERATOR_VERSION,
        "source_sha256": source_sha256,
        "files": files,
    }
    generated_dir.mkdir(parents=True, exist_ok=True)
    path = generated_dir / MANIFEST_NAME
    path.write_bytes(_dump_json(manifest).encode("utf-8"))
    return path


def _write_results(
    generated_dir: Path,
    results: Sequence[GeneratedTarget],
    source_sha256: str,
    content_version: str,
) -> Path:
    """Write every generated file and the manifest.

    Nothing is written until every document has been produced and validated,
    so a failed run never leaves half-written content behind.

    Args:
        generated_dir: Directory the content is written to.
        results: The generated targets.
        source_sha256: Hash of the authored content.
        content_version: Version of the content document.

    Returns:
        Path of the written manifest.
    """
    generated_dir.mkdir(parents=True, exist_ok=True)
    for result in results:
        path = generated_dir / f"{result.target}.json"
        path.write_bytes(_dump_json(result.document).encode("utf-8"))
    return _write_manifest(generated_dir, results, source_sha256, content_version)


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser of the CLI.

    Returns:
        The parser.
    """
    parser = argparse.ArgumentParser(
        prog="content.generate",
        description="Generate versioned game content with the build-time LLM pipeline.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Generate every content category.",
    )
    parser.add_argument(
        "--only",
        metavar="CATEGORY",
        choices=TARGETS,
        help="Generate a single content category (for example: rumors).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"Random seed sent with the requests (default: {DEFAULT_SEED}).",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=DEFAULT_TEMPERATURE,
        help=f"Sampling temperature of the requests (default: {DEFAULT_TEMPERATURE}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the authored content and report what would be done, "
        "without calling the API.",
    )
    parser.add_argument(
        "--prompts-dir",
        type=Path,
        default=PROMPTS_DIR,
        help="Directory holding the prompt templates.",
    )
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=BASE_DIR,
        help="Directory holding the authored content JSON files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=GENERATED_DIR,
        help="Directory where generated content is written.",
    )
    return parser


def _report_plan(
    targets: Sequence[str],
    prompts_dir: Path,
    output_dir: Path,
    world: WorldContent | None,
    source_sha256: str,
    seed: int,
    temperature: float,
) -> None:
    """Print what the pipeline would do, without calling the API.

    Args:
        targets: The targets that would be generated.
        prompts_dir: Directory holding the prompt templates.
        output_dir: Directory the content would be written to.
        world: The authored world content, or ``None`` when the premise
            plate is still pending.
        source_sha256: Hash of the authored content.
        seed: Seed that would be sent with the requests.
        temperature: Sampling temperature that would be used.
    """
    print("content.generate: dry run, no API call is made.")
    print(f"  authored content sha256 : {source_sha256}")
    if world is None:
        print("  content version          : (the premise plate is still pending)")
    else:
        print(f"  content version          : {world.content_version}")
    print(f"  seed                     : {seed}")
    print(f"  temperature              : {temperature}")
    print(f"  prompts dir              : {prompts_dir}")
    print(f"  output dir               : {output_dir}")
    print(f"  targets                  : {', '.join(targets)}")
    for target in targets:
        prompt_path = prompts_dir / f"{target}.txt"
        if prompt_path.is_file():
            print(
                f"    - {target}: prompt {prompt_path.name} "
                f"(sha256 {_sha256_file(prompt_path)[:12]}...), "
                f"output {target}.json"
            )
        else:
            print(f"    - {target}: MISSING prompt {prompt_path}")


def _provider_factory(
    seed: int,
    temperature: float,
) -> Callable[[], LLMProvider]:
    """Build the factory that creates the provider.

    The provider is built lazily, right before the first request, so that a
    missing API key is reported before any work is done.

    Args:
        seed: Seed sent with the requests.
        temperature: Sampling temperature of the requests.

    Returns:
        A callable that builds the provider.
    """

    def _build() -> LLMProvider:
        return provider_from_env(seed=seed, temperature=temperature)

    return _build


def main(
    argv: list[str] | None = None,
    provider_factory: Callable[[], LLMProvider] | None = None,
) -> int:
    """Run the content generation CLI.

    Args:
        argv: Optional argument vector. Defaults to ``sys.argv[1:]``.
        provider_factory: Optional factory that builds the provider. It
            exists so that the test suite can inject a fake provider and
            exercise the pipeline without touching the network. When it is
            ``None`` the provider is built from the environment.

    Returns:
        The process exit code: ``0`` on success, ``1`` when the generation
        fails.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.all and not args.only:
        parser.error("one of --all or --only is required")

    targets: list[str] = list(TARGETS) if args.all else [args.only]

    if not args.dry_run:
        build_provider = provider_factory or _provider_factory(args.seed, args.temperature)
        try:
            provider = build_provider()
        except LLMNotConfiguredError as error:
            print(f"error: {error}", file=sys.stderr)
            print(
                "  hint: export OPENAI_API_KEY or ANTHROPIC_API_KEY before running "
                "the pipeline, for example:",
                file=sys.stderr,
            )
            print(
                "    $env:OPENAI_API_KEY = 'sk-...'   # PowerShell",
                file=sys.stderr,
            )
            print(
                "  no file was written to content/generated/",
                file=sys.stderr,
            )
            return 1

    try:
        world, source_sha256 = _load_base_content(
            args.base_dir,
            allow_pending_premise=args.dry_run,
        )
    except GenerationError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if args.dry_run:
        _report_plan(
            targets,
            args.prompts_dir,
            args.output_dir,
            world,
            source_sha256,
            args.seed,
            args.temperature,
        )
        if world is None:
            print(
                "  note: the premise plate is still pending (design decision P3). "
                "The generation needs a complete plate to build the prompt "
                "context."
            )
        return 0

    if world is None:
        print(
            "error: the authored content is not complete, so the prompt context cannot be built.",
            file=sys.stderr,
        )
        return 1

    results: list[GeneratedTarget] = []
    try:
        for target in targets:
            result = _generate_target(
                target,
                world,
                source_sha256,
                provider,
                args.prompts_dir,
                seed=args.seed,
                temperature=args.temperature,
            )
            results.append(result)
            print(f"content.generate: {target} generated ({result.output_sha256[:12]}...)")
    except GenerationError as error:
        print(f"error: {error}", file=sys.stderr)
        print("  no file was written to content/generated/", file=sys.stderr)
        return 1

    manifest_path = _write_results(
        args.output_dir,
        results,
        source_sha256,
        world.content_version,
    )
    print(f"content.generate: manifest written to {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
