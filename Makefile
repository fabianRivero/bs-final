.PHONY: setup test lint format validate sim generate export godot godot-test godot-shots clean

# Path of the portable Godot binary used by the game targets.
GODOT ?= ../tools/godot/Godot_v4.7.2-stable_win64_console.exe

setup:
	uv sync --dev

test:
	uv run pytest --cov --cov-report=term-missing

lint:
	uv run ruff check . && uv run ruff format --check .

format:
	uv run ruff format .

validate:
	uv run python -m content.validate

sim:
	uv run python -m tools.simulate --from 0 --to 480

generate:
	uv run python -m content.generate --all

export:
	uv run python -m tools.export_web

# Import the Godot project and check that every script parses.
godot:
	"$(GODOT)" --headless --editor --path game --quit-after 60

# Run the three headless test suites of the Godot project.
godot-test:
	"$(GODOT)" --headless --path game --script res://tests/smoke_test.gd
	"$(GODOT)" --headless --path game --script res://tests/integration_test.gd
	"$(GODOT)" --headless --path game --script res://tests/scenes_test.gd

# Capture the screenshots of the seven lighting phases. Needs a display.
godot-shots:
	"$(GODOT)" --path game --script res://tests/capture_screens.gd --rendering-driver opengl3
	"$(GODOT)" --path game --script res://tests/capture_menus.gd --rendering-driver opengl3

clean:
	uv run python -c "import shutil,pathlib; [shutil.rmtree(p, ignore_errors=True) for p in ['build','.pytest_cache']]"
