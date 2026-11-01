"""Tests for the command line tools.

The stubs for the phases that have not been implemented yet must still behave
predictably: they accept their documented arguments, print a clear message
pointing at the phase that will implement them, and exit with code 0 so that
they never break the CI pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from content import generate, validate
from core.lighting import LIGHTING_TABLE
from core.time import MINUTES_PER_TICK, TICKS_PER_DAY, TOTAL_TICKS
from tools import export_web, parity_check, simulate


def test_simulate_returns_one_record_per_tick() -> None:
    """The simulation table covers the requested range inclusively."""
    records = simulate.simulate(0, 10)
    assert len(records) == 11
    assert [record["tick"] for record in records] == list(range(11))


def test_simulate_record_content() -> None:
    """Each record carries the tick, the calendar and the clock label."""
    first = simulate.simulate(0, 0)[0]
    assert first == {
        "tick": 0,
        "day": 1,
        "hour": 0,
        "minute": 0,
        "clock": "Day 1 00:00",
    }


def test_simulate_full_cycle() -> None:
    """The whole cycle is 289 instants, from tick 0 to the closing tick."""
    records = simulate.simulate(0, 288)
    assert len(records) == 289
    assert records[-1]["clock"] == "Day 4 00:00"


@pytest.mark.parametrize(
    ("start", "end"),
    [(-1, 10), (0, 289), (10, 5)],
)
def test_simulate_rejects_invalid_ranges(start: int, end: int) -> None:
    """Ranges outside the cycle, or inverted, are rejected."""
    with pytest.raises(ValueError):
        simulate.simulate(start, end)


def test_simulate_cli_prints_a_table(capsys: pytest.CaptureFixture[str]) -> None:
    """The CLI prints the table and reports how many ticks were simulated."""
    exit_code = simulate.main(["--from", "0", "--to", "5"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "tick" in captured.out
    assert "Day 1 00:00" in captured.out
    assert "6 ticks simulated" in captured.out


def test_simulate_cli_csv_output(capsys: pytest.CaptureFixture[str]) -> None:
    """The CLI can emit the same data as CSV."""
    exit_code = simulate.main(["--from", "0", "--to", "2", "--format", "csv"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.splitlines()[0] == "tick,day,hour,minute,clock"
    assert captured.out.splitlines()[1] == "0,1,0,0,Day 1 00:00"


def test_simulate_cli_reports_invalid_ranges(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An invalid range produces a clean error, not a traceback."""
    exit_code = simulate.main(["--from", "10", "--to", "5"])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "error:" in captured.err


def test_content_validate_exits_successfully(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The validation CLI validates the content and reports the outcome.

    The authored content of the project carries a deliberately pending
    premise plate, so the CLI reports it as a warning and still succeeds:
    the phase F2a CI stays green while the design decision is open.
    """
    exit_code = validate.main([])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "content.validate" in captured.out


def test_content_generate_dry_run_exits_successfully(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The generation CLI reports what it would do without calling the API."""
    exit_code = generate.main(["--all", "--dry-run"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "dry run" in captured.out
    assert "rumors" in captured.out


def test_export_web_exits_successfully(capsys: pytest.CaptureFixture[str]) -> None:
    """The export succeeds and points at the phase that implements the HTML5 build."""
    exit_code = export_web.main([])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PLAN.md F5" in captured.out


def test_export_web_writes_the_game_contract(tmp_path: Path) -> None:
    """The export writes the JSON contract the Godot project consumes."""
    destination = tmp_path / "game_content.json"
    exit_code = export_web.main(["--game-content", str(destination)])
    assert exit_code == 0
    assert destination.exists()

    document = json.loads(destination.read_text(encoding="utf-8"))
    assert document["content_version"] == "0.1.0-fixture"
    assert len(document["zones"]) == 2
    assert len(document["npcs"]) == 2


def test_export_web_carries_the_lighting_table(tmp_path: Path) -> None:
    """The exported lighting table is the one of ``core.lighting``."""
    destination = tmp_path / "game_content.json"
    export_web.main(["--game-content", str(destination)])
    document = json.loads(destination.read_text(encoding="utf-8"))

    phases = document["lighting"]
    assert len(phases) == len(LIGHTING_TABLE)
    for phase, expected in zip(phases, LIGHTING_TABLE, strict=True):
        assert phase["phase_id"] == expected.id
        assert phase["start_tick"] == expected.start_tick
        assert phase["end_tick"] == expected.end_tick
        assert phase["rgb"] == list(expected.rgb)
        assert phase["opacity"] == expected.opacity


def test_export_web_carries_the_clock_constants(tmp_path: Path) -> None:
    """The exported clock constants are the ones of ``core.time``."""
    destination = tmp_path / "game_content.json"
    export_web.main(["--game-content", str(destination)])
    document = json.loads(destination.read_text(encoding="utf-8"))

    assert document["clock"]["minutes_per_tick"] == MINUTES_PER_TICK
    assert document["clock"]["ticks_per_day"] == TICKS_PER_DAY
    assert document["clock"]["total_ticks"] == TOTAL_TICKS


def test_export_web_is_deterministic(tmp_path: Path) -> None:
    """Regenerating the contract without content changes yields the same bytes."""
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    export_web.main(["--game-content", str(first)])
    export_web.main(["--game-content", str(second)])
    assert first.read_bytes() == second.read_bytes()


def test_export_web_document_validates_against_the_schema() -> None:
    """The exported document is a valid content document."""
    document = export_web.build_document()
    export_web.validate_document(document)


def test_export_web_rejects_an_invalid_document() -> None:
    """A document that breaks the schema is reported, not exported."""
    document = export_web.build_document()
    document["zones"] = [{"id": "ZN_BROKEN"}]
    with pytest.raises(ValueError):
        export_web.validate_document(document)


def test_parity_check_exits_successfully(capsys: pytest.CaptureFixture[str]) -> None:
    """The parity check stub succeeds and points at the phase that implements it."""
    exit_code = parity_check.main([])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PLAN.md F5" in captured.out
