.PHONY: setup test lint format validate sim generate export clean

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
	uv run python -m tools.simulate --from 0 --to 288

generate:
	uv run python -m content.generate --all

export:
	uv run python -m tools.export_web

clean:
	uv run python -c "import shutil,pathlib; [shutil.rmtree(p, ignore_errors=True) for p in ['build','.pytest_cache']]"
