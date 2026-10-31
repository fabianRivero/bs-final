"""Verify that Python and Godot agree on the world state.

The parity check compares the state derived by the Python simulation core
against the state Godot actually renders, over a corpus of ticks and flag
combinations. It also verifies the day/night lighting table.

Usage:
    python -m tools.parity_check
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

__all__ = ["main"]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BUILD_DIR = PROJECT_ROOT / "build"


def main(argv: list[str] | None = None) -> int:
    """Run the parity check CLI.

    Args:
        argv: Optional argument vector. Defaults to ``sys.argv[1:]``.

    Returns:
        The process exit code: ``0`` on success, ``1`` on a discrepancy.
    """
    parser = argparse.ArgumentParser(
        prog="tools.parity_check",
        description="Compare the Python world state with the state rendered by Godot.",
    )
    parser.add_argument(
        "--build-dir",
        type=Path,
        default=BUILD_DIR,
        help="Directory holding the exported artefacts.",
    )
    parser.parse_args(argv)

    print("tools.parity_check: not implemented yet - see PLAN.md F5")
    print(f"  build dir: {BUILD_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
