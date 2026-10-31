"""Validate the authored and generated content of the Aldermere project.

This CLI validates every JSON document under ``content/base/`` and
``content/generated/`` against the content schemas and checks cross-document
references.

Usage:
    python -m content.validate
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

__all__ = ["main"]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASE_DIR = PROJECT_ROOT / "content" / "base"
GENERATED_DIR = PROJECT_ROOT / "content" / "generated"


def _collect_json_files(directory: Path) -> list[Path]:
    """Return every ``*.json`` file inside ``directory``, sorted for determinism."""
    if not directory.is_dir():
        return []
    return sorted(directory.rglob("*.json"))


def main(argv: list[str] | None = None) -> int:
    """Run the content validation CLI.

    Args:
        argv: Optional argument vector. Defaults to ``sys.argv[1:]``.

    Returns:
        The process exit code: ``0`` on success, ``1`` when validation fails.
    """
    parser = argparse.ArgumentParser(
        prog="content.validate",
        description="Validate authored and generated game content.",
    )
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=BASE_DIR,
        help="Directory holding the authored content JSON files.",
    )
    parser.add_argument(
        "--generated-dir",
        type=Path,
        default=GENERATED_DIR,
        help="Directory holding the generated content JSON files.",
    )
    parser.parse_args(argv)

    base_files = _collect_json_files(BASE_DIR)
    generated_files = _collect_json_files(GENERATED_DIR)

    print("content.validate: not implemented yet - see PLAN.md F2")
    print(f"  authored files found : {len(base_files)}")
    print(f"  generated files found: {len(generated_files)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
