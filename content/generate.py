"""Build-time content generation pipeline for Aldermere.

Reads the authored content plus the prompt templates, queries the configured
LLM provider, validates the response against the content schemas and writes
versioned output to ``content/generated/``.

Usage:
    python -m content.generate --all
    python -m content.generate --only rumors
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

__all__ = ["main"]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = PROJECT_ROOT / "content" / "prompts"
GENERATED_DIR = PROJECT_ROOT / "content" / "generated"


def main(argv: list[str] | None = None) -> int:
    """Run the content generation CLI.

    Args:
        argv: Optional argument vector. Defaults to ``sys.argv[1:]``.

    Returns:
        The process exit code: ``0`` on success, ``1`` when generation fails.
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
        help="Generate a single content category (for example: rumors).",
    )
    parser.add_argument(
        "--prompts-dir",
        type=Path,
        default=PROMPTS_DIR,
        help="Directory holding the prompt templates.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=GENERATED_DIR,
        help="Directory where generated content is written.",
    )
    parser.parse_args(argv)

    print("content.generate: not implemented yet - see PLAN.md F2")
    print(f"  prompts dir : {PROMPTS_DIR}")
    print(f"  output dir  : {GENERATED_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
