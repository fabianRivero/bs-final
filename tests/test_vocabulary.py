"""Vocabulary test: the content must not mention the features we do not have.

Why this test exists
--------------------
The design of the project is explicit (``PLAN.md``, section 2.2): there is no
combat, no monsters, no magic and no levels. The player investigates a
disease; that is the whole game.

Two things can break that promise:

* A human author writing a line that drifts into "the monster in the mill".
* A language model generating a rumour about a dragon, because that is what
  language models tend to write when they are asked for dramatic content.

The second risk is the real one, which is why the check lives in the test
suite and runs over the generated content as well.

How the check works
-------------------
Every text of a content document is scanned, lowercased, and searched for
the forbidden terms. The terms are matched as plain substrings on purpose:
"wizard" and "wizards" are both caught, and the vocabulary of the game
(medical, agricultural, administrative) does not collide with the list.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from content.schema import WorldContent
from content.validate import FORBIDDEN_TERMS

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "content" / "world.json"
PROMPTS_DIR = Path(__file__).parent.parent / "content" / "prompts"


def _texts_of(document: Any) -> list[str]:
    """Collect every human readable string of a document.

    The keys are skipped: only the values are read, because a key is an
    identifier and an identifier never mentions a feature.

    Args:
        document: The decoded document.

    Returns:
        Every string found in the document.
    """
    found: list[str] = []
    if isinstance(document, str):
        found.append(document)
    elif isinstance(document, dict):
        for value in document.values():
            found.extend(_texts_of(value))
    elif isinstance(document, list):
        for value in document:
            found.extend(_texts_of(value))
    return found


@pytest.fixture
def fixture_document() -> dict[str, Any]:
    """Return the synthetic world fixture.

    Returns:
        The decoded fixture document.
    """
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_the_valid_fixture_uses_no_forbidden_vocabulary(
    fixture_document: dict[str, Any],
) -> None:
    """The synthetic content stays inside the design."""
    blob = json.dumps(fixture_document, ensure_ascii=False).lower()
    for term in FORBIDDEN_TERMS:
        assert term not in blob, f"the fixture mentions the forbidden term {term!r}"


@pytest.mark.parametrize(
    "text",
    [
        "A monster was seen in the mill yard.",
        "The villagers cast a spell to break the curse.",
        "The guard drew his sword against the raiders.",
        "The healer gained three levels of insight.",
        "The beast drank the potion of courage.",
        "The fight for the harbour was brutal.",
        "The dragon took the whole harvest.",
        "A goblin stole the town records.",
    ],
)
def test_forbidden_text_is_detected(text: str) -> None:
    """Every kind of forbidden mention is caught."""
    lowered = text.lower()
    hits = [term for term in FORBIDDEN_TERMS if term in lowered]
    assert hits, f"the forbidden text {text!r} was not detected"


@pytest.mark.parametrize(
    "text",
    [
        "The miller says his hands have been numb since the harvest.",
        "The keeper writes every death in the register.",
        "She asked about the rash on her arms.",
        "The herbal lists a remedy for the numbness.",
        "They have been walking the boundary since dawn.",
        "He noticed a pale rash on the forearms of the workers.",
    ],
)
def test_allowed_text_is_not_flagged(text: str) -> None:
    """The vocabulary of the game is not flagged."""
    lowered = text.lower()
    hits = [term for term in FORBIDDEN_TERMS if term in lowered]
    assert not hits, f"the allowed text {text!r} was flagged as {hits}"


def test_the_generated_content_of_the_project_is_clean() -> None:
    """The generated content shipped with the project is clean."""
    generated_dir = Path(__file__).parent.parent / "content" / "generated"
    for path in sorted(generated_dir.glob("*.json")):
        if path.name == "manifest.json":
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        blob = json.dumps(document, ensure_ascii=False).lower()
        for term in FORBIDDEN_TERMS:
            assert term not in blob, f"{path.name} mentions the forbidden term {term!r}"


def test_the_prompt_templates_forbid_the_same_vocabulary() -> None:
    """Every prompt tells the model which words it must not use."""
    forbidden_in_prompts = (
        "combat",
        "monster",
        "magic",
        "spell",
        "level up",
    )
    for path in sorted(PROMPTS_DIR.glob("*.txt")):
        template = path.read_text(encoding="utf-8").lower()
        for term in forbidden_in_prompts:
            assert term in template, f"{path.name} does not forbid {term!r}"


def test_the_prompt_templates_hold_the_output_contract() -> None:
    """Every prompt states that the answer is strict JSON."""
    for path in sorted(PROMPTS_DIR.glob("*.txt")):
        template = path.read_text(encoding="utf-8")
        assert "Return a single JSON object" in template
        assert "Output contract" in template


def test_the_prompt_templates_hold_the_context_placeholder() -> None:
    """Every prompt has the placeholder the pipeline fills."""
    for path in sorted(PROMPTS_DIR.glob("*.txt")):
        assert "{context}" in path.read_text(encoding="utf-8")


def test_the_validated_fixture_holds_no_forbidden_vocabulary(
    fixture_document: dict[str, Any],
) -> None:
    """The validated model holds no forbidden term either."""
    world = WorldContent.model_validate(fixture_document)
    blob = json.dumps(world.model_dump(mode="json"), ensure_ascii=False).lower()
    for term in FORBIDDEN_TERMS:
        assert term not in blob


def test_the_forbidden_terms_are_lowercase() -> None:
    """The list is lowercase, because the scan lowercases the text."""
    assert all(term == term.lower() for term in FORBIDDEN_TERMS)


def test_the_forbidden_terms_have_no_duplicates() -> None:
    """The list holds no duplicated term."""
    assert len(FORBIDDEN_TERMS) == len(set(FORBIDDEN_TERMS))


def test_the_forbidden_terms_cover_the_four_feature_families() -> None:
    """The list covers combat, monsters, magic and levels."""
    combat = {"combat", "battle", "weapon", "damage"}
    monsters = {"monster", "creature", "dragon", "beast"}
    magic = {"magic", "spell", "mana", "wizard"}
    levels = {"level", "level-up", "experience points", "skill tree"}
    assert combat <= set(FORBIDDEN_TERMS)
    assert monsters <= set(FORBIDDEN_TERMS)
    assert magic <= set(FORBIDDEN_TERMS)
    assert levels <= set(FORBIDDEN_TERMS)


def test_the_text_extraction_finds_the_strings() -> None:
    """The scanner reaches the strings nested in a document."""
    document = {
        "a": "a monster",
        "b": [{"c": "a spell"}, 3, None],
        "d": 42,
    }
    found = _texts_of(document)
    assert "a monster" in found
    assert "a spell" in found
    assert len(found) == 2
