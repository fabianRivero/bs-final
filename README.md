# Aldermere

[![CI](https://github.com/fabianRivero/bs-final/actions/workflows/ci.yml/badge.svg)](https://github.com/fabianRivero/bs-final/actions/workflows/ci.yml)

> **Repository:** https://github.com/fabianRivero/bs-final

> **Note on language.** The assignment brief for this project is written in
> Spanish, but the project itself is developed entirely in English: the game
> content, the source code, the documentation and this README. Only the
> planning document (`PLAN.md`, kept outside this repository) is in Spanish.
> The section headings below are the English equivalents of the six literal
> sub-points required by the assignment, so that the correspondence stays
> unambiguous for the reviewer.

A top-down investigation RPG about understanding a disease before it becomes
an epidemic.

---

## Description

**Aldermere** is a tile-based, top-down role-playing game with no combat, no
levels and no experience points. The player arrives at a small coastal
fishing town where a deadly disease has already taken its first victims. The
only way out is to understand what the disease is, how it spreads and how it
can be stopped. The game is deliberately about *investigation*, not about
fighting: the core verb is **asking questions**, and the progression system is
**knowledge**.

Time is the protagonist. The world advances in discrete **ticks of 15
minutes** of in-game time, and every single valid action — walking one tile,
talking to a neighbour, reading a book, examining the harbour — costs exactly
one tick. A full day is 96 ticks and the entire playable cycle is **3 days =
288 ticks**, which maps to a real playtime of roughly 15 to 25 minutes. The
tick is discrete and strictly monotonic: it never moves backwards, and there
is no explicit "wait" button, because waiting *is* doing something else.

The town lives on a schedule. Every NPC in Aldermere — the baker, the
fisher, the harbourmaster, the widow of the previous doctor — follows a daily
routine of schedule blocks that place them in a zone, at a tile, doing an
activity, with a matching dialogue variant. If the player speaks to the
fisher Marta at 11:00 she is selling fish and tells a certain story; at 16:00
she is repairing her boat and tells a different one. If the player misses the
baker's window before 09:30, that testimony is simply gone for this run. This
creates pressure without a single combat encounter.

The disease leaves behind symptoms. Talking to the sick neighbours yields
symptoms with their origin and the tick at which they were reported; reading
the botany handbook, the herbalist's notes, the previous doctor's journal and
the town registry yields sources that support or refute those symptoms. From
that evidence the player formulates hypotheses in the notebook and then
verifies them in the field. The engine only knows about a generic
`symptom -> candidate causes` table and a generic
`cause -> sources that confirm or refute` table: it never hardcodes what the
disease actually is. That is what makes it possible to change the premise
without touching a line of Python.

The game has **four final endings**, evaluated deterministically at the moment
the player resolves the main quest or at the closing tick, whichever comes
first: **The Cure** (the correct hypothesis is verified and the total remedy is
administered in time), **The Containment** (the disease is slowed but not
stopped), **The Well-Meant Mistake** (a remedy is given on a refuted
hypothesis) and **The Silent Village** (nothing was done; failure is a
first-class ending, not a timeout). The run ends on the ending that was
reached. The cycle is never restarted.

The technical rule that shapes everything is a single sentence: **Python is
the source of truth. Godot presents and captures input.** The entire
simulation — clock, schedules, events, missions, hypotheses, lighting and
endings — lives in pure Python with no dependency on the game engine, and is
covered by tests. Godot 4.6 renders the state that Python derives and sends
player actions back. Godot never decides anything: if a rule is not in the
exported JSON, the rule does not exist in the game.

AI is used where it genuinely earns its place, and always at **build time**.
Prompts plus the authored content are fed to an LLM during the content
pipeline; the response is validated against a schema and written to
`content/generated/` with its version, prompt and SHA-256 checksum, and that
generated content is committed to the repository. The result is a reproducible
game whose narrative richness does not depend on an API call at runtime. The
one runtime AI feature under consideration — an assistant that proposes
hypotheses with its reasoning — is strictly bounded: it may only propose
candidates from the game's own table, it never writes flags, and the game
defaults to **offline mode** so that the whole demo is playable without an API
key.

---

## Tech Stack

| Layer | Technology | Version | Why |
|---|---|---|---|
| Game engine | Godot Engine | 4.7.2-stable | Mature 2D tilemap rendering, frictionless HTML5 export, typed GDScript. |
| Game scripting | GDScript | 4.7 | Pairs natively with the engine, no extra build chain. |
| Simulation core | Python | 3.14 | Business logic that is testable independently of the engine. |
| Data validation | Pydantic | 2.x | Typed models that validate content JSON in CI and in the generator. |
| Schema validation | jsonschema | 4.x | Second, independent layer that validates the JSON Godot consumes. |
| Tests | pytest | 8.x | De-facto standard; coverage reporting through `pytest-cov`. |
| Environment manager | uv | 0.13.x | Modern replacement for `pip` + `venv`: `uv sync`, `uv run`. |
| Linting / formatting | Ruff | 0.8+ | Fast, single binary, `ruff check` plus `ruff format`. |
| Build-time LLM | OpenAI or Anthropic API | gpt-4o-mini / claude-sonnet | Punctual use in the content pipeline, hidden behind `content/llm.py`. |
| CI | GitHub Actions | — | Tests, coverage, lint and content validation on every push. |
| Deployment | GitHub Pages | — | Static HTML5 build of the Godot project, publicly playable. |
| Assets | Kenney.nl / LPC (CC0) + Google Fonts (OFL) | — | Licences allow commercial use and redistribution without friction. |
| Lighting | Tile palettes + tint overlay | — | ~80 % of the day/night effect for ~20 % of the work. |
| Version control | Git | 2.55+ | Tracked in the project; the public remote lives at https://github.com/fabianRivero/bs-final |

---

## Getting Started

### Prerequisites

| Tool | Version | Required | Notes |
|---|---|---|---|
| Python | 3.14+ | Yes | The simulation core targets 3.14. |
| uv | 0.13+ | Yes | Manages the virtualenv and dependencies. |
| Godot Engine | 4.6-stable | Optional | Only needed to run the playable client. |
| Node.js | 20+ | Optional | Only needed if the HTML5 export template is regenerated. |
| Make | any | Optional | `make` is not installed by default on Windows; see below. |

### Install

```bash
uv sync --dev
```

This creates `.venv/`, installs the runtime dependencies (`pydantic`,
`jsonschema`) and the development group (`pytest`, `pytest-cov`, `ruff`), and
writes the resolved `uv.lock` (which is committed on purpose, so that CI and
local installs resolve identically).

### Run the tests

```bash
uv run pytest --cov --cov-report=term-missing
```

Coverage is enforced at **90 %** (`[tool.coverage.report] fail_under = 90`),
and the same threshold is a blocking gate in CI.

### Run the simulation CLI

```bash
uv run python -m tools.simulate --from 0 --to 288
```

It prints the day/hour table for every tick of the cycle and is the reference
output for the tick arithmetic. `--format csv` emits the same data as CSV.

### Run the game

```bash
godot --path game/
```

The playable client reads `build/game_content.json`. Until that artefact is
generated (planned in F3), the Godot side is a placeholder.

### Run the Godot tests

The Godot layer has its own headless test suites, written in GDScript:

```bash
godot --headless --path game --script res://tests/smoke_test.gd
godot --headless --path game --script res://tests/integration_test.gd
godot --headless --path game --script res://tests/scenes_test.gd
```

They cover the calendar, the local derivation, the lighting table, the
content contract and the flow from input to tick. The `Makefile` wraps them
as `make godot-test`.

The screenshots need a real display driver; `--headless` does not render:

```bash
godot --path game --script res://tests/capture_screens.gd
```

They are written to `user://screenshots`, one per lighting phase.

### Regenerate the AI content

The build-time pipeline turns the prompt templates and the authored content
into validated JSON under `content/generated/`. It needs an API key; without
one it refuses to run and writes nothing.

```bash
export OPENAI_API_KEY="sk-..."        # or ANTHROPIC_API_KEY
export ALDERMERE_LLM_MODEL="gpt-4o-mini"   # optional, this is the default

uv run python -m content.generate --all            # the four targets
uv run python -m content.generate --only rumors    # a single target
uv run python -m content.generate --all --seed 20260514   # reproducible run
uv run python -m content.generate --all --dry-run  # show what it would do
```

Two properties are guaranteed by the pipeline and asserted by the test suite:

- **Reproducible.** The seed, the model, the temperature and the prompt take
  part in the request, so the same seed over the same authored content
  produces byte-identical files. The seed is also part of the cache key, so a
  different seed never reuses a cached answer.
- **Free to re-run.** Answers are cached on disk under `.cache/llm/`, keyed by
  a digest of the request. Regenerating without changing anything makes no
  API call at all.

Every written file is recorded in `content/generated/manifest.json` together
with the prompt, the model, the seed and the SHA-256 of the input and the
output, so `content.validate` can prove that the committed content is exactly
what the pipeline produced.

### Windows notes

`make` is not available by default on Windows, and the `Makefile` is not a
requirement of any tool in the project. Every target has a direct equivalent
that works in any shell:

| Makefile target | Direct command (Windows / PowerShell / bash) |
|---|---|
| `make setup` | `uv sync --dev` |
| `make test` | `uv run pytest --cov --cov-report=term-missing` |
| `make lint` | `uv run ruff check .` then `uv run ruff format --check .` |
| `make format` | `uv run ruff format .` |
| `make validate` | `uv run python -m content.validate` |
| `make sim` | `uv run python -m tools.simulate --from 0 --to 288` |
| `make generate` | `uv run python -m content.generate --all` |
| `make export` | `uv run python -m tools.export_web` |
| `make clean` | `uv run python -c "import shutil,pathlib; [shutil.rmtree(p, ignore_errors=True) for p in ['build','.pytest_cache']]"` |

If `uv` is installed but the shell has not picked it up yet, refresh `PATH` in
PowerShell:

```powershell
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
```

---

## Project Structure

```
final-project-aldermere/
├── core/                  # Simulation core: the single source of truth for world state
│   ├── time.py            # Deterministic tick arithmetic, clock formatting, deadlines
│   ├── state.py           # Derived world state: WorldState = derive(tick, decisions)
│   ├── schedule.py        # NPC daily routines: where each villager is at a given tick
│   ├── lighting.py        # Day/night cycle: phase, tint colour and overlay opacity
│   ├── world.py           # Composition root: WorldSim, the player-facing API
│   └── __init__.py        # Public exports of the core constants and helpers
├── content/               # Game content: authored data, generated data, prompts
│   ├── base/              # Hand-authored content JSON (premise, zones, npcs, events, ...)
│   ├── generated/         # LLM-generated content, versioned and committed
│   ├── prompts/           # Plain-text prompt templates for the build-time pipeline
│   ├── schema.py          # Pydantic models for the whole content document
│   ├── generated_schema.py# Narrower models: what the LLM is allowed to write
│   ├── llm.py             # Abstracted LLM client with an on-disk cache
│   ├── validate.py        # CLI: validate authored and generated content
│   └── generate.py        # CLI: run the build-time LLM content pipeline
├── tools/                 # Command line tools that drive the project
│   ├── simulate.py        # CLI: simulate a tick range and print the day/hour table
│   ├── export_web.py      # CLI: export the content contract to Godot and build for web
│   └── parity_check.py    # CLI: compare the Python state with what Godot renders
├── game/                  # Godot 4.7 project: scenes, tilesets, GDScript (presentation only)
│   ├── autoload/          # GameState, ContentDB, Lighting, SceneRouter
│   ├── scenes/            # title, game, ending
│   ├── world/ player/ npc/ ui/
│   ├── data/              # game_content.json, exported from Python
│   └── tests/             # Headless GDScript test suites
├── tests/                 # pytest suite for the simulation core and the tooling
│   ├── test_time.py       # Exhaustive tick arithmetic tests (all 288 ticks)
│   ├── test_state.py      # Derived state, flag vocabulary and purity guarantees
│   ├── test_schedule.py   # NPC routines, availability and schedule validation
│   ├── test_lighting.py   # The seven lighting phases cover the day without gaps
│   ├── test_world.py      # WorldSim: advance, invalid actions, determinism
│   ├── test_schema.py     # Content schema validation and its failure modes
│   ├── test_content_consistency.py # Cross references between content collections
│   ├── test_llm.py        # LLM client, provider selection and cache behaviour
│   ├── test_generate.py   # The build-time pipeline and its reproducibility
│   ├── test_validate.py   # The validator CLI and the manifest checks
│   ├── test_vocabulary.py # Generated content cannot mention out-of-scope features
│   ├── test_determinism.py# The same input sequence always yields the same state
│   ├── test_tools_cli.py  # Contract tests for the command line entry points
│   └── fixtures/          # Sample JSON fixtures used by the test suite
├── game/                  # Godot 4.6 project: scenes, tilesets, GDScript (presentation only)
├── docs/                  # Project documentation (architecture, prompts, walkthrough)
├── build/                 # Build artefacts, including the game_content.json contract
├── .github/workflows/     # Continuous integration definition
├── pyproject.toml         # Project metadata, dependencies and tool configuration
├── Makefile               # Convenience targets (see the command table above)
└── uv.lock                # Resolved dependency versions, committed on purpose
```

| Folder | Responsibility |
|---|---|
| `core/` | The simulation: tick arithmetic, schedules, events, missions, investigation, endings. Pure Python, no engine dependency. |
| `content/` | The data: the premise plate, symptoms, sources, zones, NPCs, events, missions, dialogues, lighting phases. |
| `tools/` | The command line entry points: simulate, validate, generate, export and parity-check the content. |
| `tests/` | The pytest suite that proves the simulation is deterministic and correct. |
| `game/` | The Godot 4.6 client: scenes, tilesets and GDScript that present state and capture input. |
| `docs/` | Written documentation: architecture, prompt catalogue, reference walkthrough. |
| `build/` | Generated artefacts, including the `game_content.json` contract read by Godot. |

---

## Main Features

- **Deterministic time engine.** A monotonic tick counter of 15-minute steps,
  96 ticks per day and 288 ticks per cycle, with pure conversion helpers
  between ticks and calendar instants, inclusive deadline comparisons and an
  explicit `ClockOverflowError` instead of silent wrap-around.
- **Derived world state.** The world is never stored. `WorldState` is a pure
  function of `(tick, decisions)`, so a save file only needs the tick, the
  player's decisions and the position, and reloading reconstructs exactly the
  same world. The derivation is guaranteed side-effect free: the same inputs
  always produce an equal state.
- **NPC schedules.** Every villager owns a list of schedule blocks that
  resolve to a zone, a tile, an activity and an interactable flag as a pure
  function of the current tick, so the town genuinely follows a daily routine.
  The routine repeats every in-game day, and an NPC outside their schedule is
  simply not interactable.
- **Scheduled events.** World-changing events fire exactly once when the
  clock reaches their activation tick and their precondition holds: the first
  death becoming known, the outbreak being acknowledged, the harbour closing,
  the public meeting on the plaza.
- **Day/night lighting cycle.** Seven lighting phases cover the 96 ticks of a
  day with no gaps and no overlaps. The phase, the tint colour and the
  overlay opacity are derived in Python and exported as data; Godot only
  applies them. Opacity is interpolated between phases so the light never
  pops.
- **Two implementations, one vocabulary.** The derivation of the world state
  exists twice: once in Python, where it is covered by the test suite, and
  once in GDScript, where the client needs it to answer the player
  immediately. Both produce exactly the same flags from the same decisions,
  and `tools/parity_check.py` compares them tick by tick. The duplication is
  deliberately small and mechanically verified instead of hidden.
- **A playable client.** The Godot layer boots into a title screen, renders
  the town on a tile grid, moves the character one cell at a time, advances
  the clock on every step, and drives the HUD, the NPC placement and the
  lighting from a single `tick_changed` signal. It has its own headless
  test suites and a screenshot harness that captures the seven lighting
  phases.
- **Investigation loop.** Symptoms are reported by neighbours with their
  origin and tick, sources are consulted and can support or refute candidate
  causes, hypotheses are written in the notebook with a
  `pending / supported / refuted` state, and the field verification step
  closes the loop against the premise plate.
- **Four final endings.** The cure, the containment, the well-meant mistake
  and the silent village, evaluated by deterministic priority rules. Failure
  is a designed ending, not an absence of one, and the run never restarts.
- **Save/load by tick and decisions.** A save file stores only the tick, the
  player's decisions and the position, because the world state is derived
  rather than stored. Reloading reconstructs the exact same world.
- **Build-time AI for content.** The pipeline reads the prompt templates and
  the authored content, queries the configured LLM provider, validates the
  response against the content schemas and writes the result to
  `content/generated/` together with a manifest recording the prompt, the
  model, the seed and the SHA-256 checksum of every file. Regenerating with
  the same seed reproduces byte-identical files, and all generated content
  is committed to the repository.
- **Offline AI mode by default.** The game is fully playable without an API
  key. Live diagnosis, if enabled, is an opt-in toggle that may only propose
  candidates from the game's own table and can never write flags or
  conditions; the API key stays in the Python process and never reaches the
  client.

---

## Test Credentials

**N/A (no authentication system).**

Aldermere is a single-player, offline game. There is no login screen, no user
account, no password and no server-side session. The game runs entirely
locally from the exported client, and the save file lives on the player's own
machine (`user://savegame.json`).

This is stated explicitly here so that a reviewer does not read the absence of
credentials as an oversight: there is genuinely nothing to authenticate
against. The only credentials that exist anywhere in the project are the
optional API keys used at **build time** by the content generator
(`OPENAI_API_KEY` / `ANTHROPIC_API_KEY`, declared in `.env.example` and
excluded from version control by `.gitignore`). Those keys are not required to
install, test, build or play the game.

---

## License

MIT. The full text lives in the `LICENSE` file at the root of the repository.

## Acknowledgements

- **Kenney.nl** and the **LPC** asset libraries for the tile and sprite art
  used by the Godot client (CC0).
- **Google Fonts** for the UI typeface (SIL Open Font License).
- The **Python**, **uv**, **pytest** and **Ruff** open-source communities, and
  the **Godot Engine** contributors.
- The reviewers of the "Máster de Desarrollo con IA" programme, whose brief
  defined the six points this README is structured around.
