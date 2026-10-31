"""Export the simulation content into the JSON contract consumed by Godot.

Produces ``build/game_content.json`` from the authored and generated content.
The output is deterministic: regenerating it without content changes yields a
byte-identical file.

Usage:
    python -m tools.export_web
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

__all__ = ["main"]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BUILD_DIR = PROJECT_ROOT / "build"


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
    parser.parse_args(argv)

    print("tools.export_web: not implemented yet - see PLAN.md F5")
    print(f"  output dir: {BUILD_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
