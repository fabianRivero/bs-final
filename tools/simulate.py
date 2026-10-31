"""Simulate the Aldermere clock and print a day/hour table.

This CLI is the read-only window into the simulation core: it walks the tick
range requested on the command line and prints, for every tick, the day, the
24h clock and the derived in-game time slot. It is the reference output used
to sanity check the tick arithmetic by hand.

Usage:
    python -m tools.simulate --from 0 --to 288
    python -m tools.simulate --from 96 --to 110 --format csv
"""

from __future__ import annotations

import argparse
import sys

from core.time import (
    TOTAL_TICKS,
    format_clock,
    to_datetime,
)

__all__ = ["main", "simulate"]


def simulate(start: int, end: int) -> list[dict[str, int | str]]:
    """Build the simulation table for the inclusive tick range ``[start, end]``.

    Args:
        start: First tick of the range.
        end: Last tick of the range (inclusive).

    Returns:
        One record per tick, with the keys ``tick``, ``day``, ``hour``,
        ``minute`` and ``clock``.

    Raises:
        ValueError: If the range is inverted or falls outside the cycle.
    """
    if start < 0 or end > TOTAL_TICKS:
        raise ValueError(f"tick range must stay within [0, {TOTAL_TICKS}]")
    if start > end:
        raise ValueError(f"start ({start}) must not be greater than end ({end})")

    records: list[dict[str, int | str]] = []
    for tick in range(start, end + 1):
        day, hour, minute = to_datetime(tick)
        records.append(
            {
                "tick": tick,
                "day": day,
                "hour": hour,
                "minute": minute,
                "clock": format_clock(tick),
            }
        )
    return records


def _render_table(records: list[dict[str, int | str]]) -> str:
    """Render the simulation records as a fixed width text table."""
    header = f"{'tick':>5}  {'day':>3}  {'hour':>4}  {'clock':>12}"
    separator = "-" * len(header)
    lines = [header, separator]
    for record in records:
        lines.append(
            f"{record['tick']:>5}  {record['day']:>3}  "
            f"{int(record['hour']):02d}:{int(record['minute']):02d}  "
            f"{record['clock']:>12}"
        )
    return "\n".join(lines)


def _render_csv(records: list[dict[str, int | str]]) -> str:
    """Render the simulation records as CSV."""
    lines = ["tick,day,hour,minute,clock"]
    for record in records:
        lines.append(
            f"{record['tick']},{record['day']},{record['hour']},"
            f"{record['minute']},{record['clock']}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Run the simulation CLI.

    Args:
        argv: Optional argument vector. Defaults to ``sys.argv[1:]``.

    Returns:
        The process exit code: ``0`` on success, ``2`` on invalid arguments.
    """
    parser = argparse.ArgumentParser(
        prog="tools.simulate",
        description="Simulate the Aldermere clock over a range of ticks.",
    )
    parser.add_argument(
        "--from",
        dest="start",
        type=int,
        default=0,
        help="First tick of the simulated range (default: 0).",
    )
    parser.add_argument(
        "--to",
        dest="end",
        type=int,
        default=TOTAL_TICKS,
        help=f"Last tick of the simulated range, inclusive (default: {TOTAL_TICKS}).",
    )
    parser.add_argument(
        "--format",
        choices=("table", "csv"),
        default="table",
        help="Output format (default: table).",
    )
    args = parser.parse_args(argv)

    try:
        records = simulate(args.start, args.end)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    if args.format == "csv":
        print(_render_csv(records))
    else:
        print(_render_table(records))

    print(f"\n{len(records)} ticks simulated (cycle: {TOTAL_TICKS} ticks).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
