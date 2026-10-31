# Contributing

Thanks for helping with Aldermere. This file covers the short version of how
the project is built, tested and committed to.

## Getting set up

```bash
uv sync --dev
```

That is the whole setup. `uv` manages the virtualenv and installs the runtime
dependencies plus the development group. The resolved `uv.lock` is committed
on purpose, so a clean clone resolves to exactly the same versions.

## Running the tests

```bash
uv run pytest --cov --cov-report=term-missing
```

Coverage is enforced at 90 %. A change that lowers coverage below that
threshold fails CI, so please add or extend tests alongside new behaviour
rather than afterwards.

If `make` is available, `make test` does the same thing. On Windows, where
`make` is usually absent, use the direct `uv run` commands above.

## Code style

- **Ruff** is the single source of truth for linting and formatting.
  - Lint: `uv run ruff check .`
  - Check formatting: `uv run ruff format --check .`
  - Apply formatting: `uv run ruff format .`
- The configuration lives in `pyproject.toml`: line length 100, target Python
  3.14, and the rule set `E, F, I, N, UP, B, SIM, RUF`.
- Everything is written in **English**: code, docstrings, comments, content
  and documentation.
- Public functions carry type hints and a docstring that explains the
  behaviour and the invariants, not the implementation.
- The simulation core (`core/`) must not import anything from the game
  engine, and must not contain literals naming the concrete origin of the
  disease. The engine is agnostic to the premise; that is the point.

## Commit convention

Commits follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short summary>

<optional body>
```

Types in use: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `build`,
`ci`. Scopes mirror the folder they touch: `core`, `content`, `tools`, `game`,
`docs`, `ci`.

Examples:

```
feat(core): derive lighting phase from tick
fix(tools): keep simulate output stable across runs
test(core): cover the tick wrap-around boundary
ci: pin Python 3.14 in the workflow
```

## Generated content is committed

Everything produced by the build-time AI pipeline under `content/generated/`
**is committed to the repository**, together with its manifest (prompt,
model, seed and SHA-256 checksum). This is deliberate:

- the game must be playable offline, with no API key and no network access;
- reviewers must be able to see exactly what the model produced and how it
  was produced;
- regenerating with the same seed must reproduce byte-identical files, so a
  diff in the generated folder always means the content actually changed.

Never hand-edit a file in `content/generated/`: change the prompt in
`content/prompts/` or the authored data in `content/base/` and regenerate
instead.

## Pull requests

- Keep the change focused; one concern per pull request.
- Make sure `uv run pytest --cov` and `uv run ruff check .` are green locally
  before opening it.
- Describe *why* the change is needed, not only what changed.
