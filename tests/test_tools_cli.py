"""Tests for the command line tools.

The stubs for the phases that have not been implemented yet must still behave
predictably: they accept their documented arguments, print a clear message
pointing at the phase that will implement them, and exit with code 0 so that
they never break the CI pipeline.
"""

from __future__ import annotations

import pytest

from content import generate, validate
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
    """The validation stub succeeds and points at the phase that implements it."""
    exit_code = validate.main([])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PLAN.md F2" in captured.out


def test_content_generate_exits_successfully(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The generation stub succeeds and points at the phase that implements it."""
    exit_code = generate.main(["--all"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PLAN.md F2" in captured.out


def test_export_web_exits_successfully(capsys: pytest.CaptureFixture[str]) -> None:
    """The export stub succeeds and points at the phase that implements it."""
    exit_code = export_web.main([])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PLAN.md F5" in captured.out


def test_parity_check_exits_successfully(capsys: pytest.CaptureFixture[str]) -> None:
    """The parity check stub succeeds and points at the phase that implements it."""
    exit_code = parity_check.main([])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PLAN.md F5" in captured.out
