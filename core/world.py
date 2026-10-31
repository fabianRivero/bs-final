"""Composition root: load the content and expose the running simulation.

:class:`WorldSim` is the object the presentation layer talks to. It is the
only place where mutable state lives, and that state is deliberately minimal:
the current **tick** and the list of **decisions** taken so far. Everything
else -- flags, NPC positions, lighting -- is derived on demand.

That design is what makes save/load trivial: a save file only needs
``{tick, decisions}``, because the world was never stored in the first place.

The golden rule of the project holds here: Python decides, Godot only
presents and captures input. ``advance(action)`` is the single entry point
that mutates the world, and it only does so when the action is valid. An
invalid action raises :class:`InvalidActionError` and **does not consume a
tick**, which matches the rule that bumping into a wall is not an action.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.lighting import LightState, light_state_at
from core.schedule import Npc, NpcState, ScheduleEntry, npc_state, validate_schedule
from core.state import Decision, WorldState, derive
from core.time import advance

__all__ = [
    "InvalidActionError",
    "WorldContentError",
    "WorldSim",
]


class WorldContentError(ValueError):
    """Raised when a content document cannot be understood.

    The content is data authored outside the core, so a malformed document is
    a content error rather than a runtime failure. It is reported loudly at
    load time.
    """


class InvalidActionError(ValueError):
    """Raised when an action cannot be performed at the current tick.

    The action is rejected *before* the clock moves, so the tick is not
    consumed. Typical causes are talking to an NPC that is not interactable
    at that moment or targeting an unknown NPC.
    """


@dataclass(frozen=True)
class Zone:
    """A zone of the town.

    Attributes:
        id: Stable identifier of the zone.
        name: Display name of the zone.
    """

    id: str
    name: str


def _parse_tile(raw: object, npc_id: str) -> tuple[int, int]:
    """Parse a tile coordinate from the content document.

    Args:
        raw: Raw value read from the document.
        npc_id: Id of the NPC the tile belongs to, used in error messages.

    Returns:
        The tile as an ``(x, y)`` pair.

    Raises:
        WorldContentError: If the value is not a pair of integers.
    """
    if (
        not isinstance(raw, list)
        or len(raw) != 2
        or not all(isinstance(value, int) and not isinstance(value, bool) for value in raw)
    ):
        raise WorldContentError(f"npc {npc_id}: tile must be a pair of integers, got {raw!r}")
    return (int(raw[0]), int(raw[1]))


def _parse_schedule_entry(raw: object, npc_id: str) -> ScheduleEntry:
    """Parse a schedule block from the content document.

    Args:
        raw: Raw object read from the document.
        npc_id: Id of the NPC the block belongs to.

    Returns:
        The parsed schedule block.

    Raises:
        WorldContentError: If the block is malformed.
    """
    if not isinstance(raw, dict):
        raise WorldContentError(f"npc {npc_id}: schedule entries must be objects")
    missing = {"start_tick", "end_tick", "zone", "tile", "activity"} - raw.keys()
    if missing:
        raise WorldContentError(f"npc {npc_id}: schedule entry is missing {sorted(missing)}")
    start_tick = raw["start_tick"]
    end_tick = raw["end_tick"]
    if not isinstance(start_tick, int) or isinstance(start_tick, bool):
        raise WorldContentError(f"npc {npc_id}: start_tick must be an integer")
    if not isinstance(end_tick, int) or isinstance(end_tick, bool):
        raise WorldContentError(f"npc {npc_id}: end_tick must be an integer")
    zone = raw["zone"]
    if not isinstance(zone, str):
        raise WorldContentError(f"npc {npc_id}: zone must be a string")
    activity = raw["activity"]
    if not isinstance(activity, str):
        raise WorldContentError(f"npc {npc_id}: activity must be a string")
    interactable = raw.get("interactable", False)
    if not isinstance(interactable, bool):
        raise WorldContentError(f"npc {npc_id}: interactable must be a boolean")

    return ScheduleEntry(
        start_tick=int(start_tick),
        end_tick=int(end_tick),
        zone=zone,
        tile=_parse_tile(raw["tile"], npc_id),
        activity=activity,
        interactable=interactable,
    )


def _parse_npc(raw: object) -> Npc:
    """Parse an NPC from the content document.

    Args:
        raw: Raw object read from the document.

    Returns:
        The parsed NPC, with a validated schedule.

    Raises:
        WorldContentError: If the NPC is malformed or its schedule overlaps.
    """
    if not isinstance(raw, dict):
        raise WorldContentError("every npc must be an object")
    npc_id = raw.get("id")
    if not isinstance(npc_id, str) or not npc_id:
        raise WorldContentError("every npc must have a non-empty string id")
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        raise WorldContentError(f"npc {npc_id}: name must be a non-empty string")
    raw_schedule = raw.get("schedule", [])
    if not isinstance(raw_schedule, list):
        raise WorldContentError(f"npc {npc_id}: schedule must be a list")

    npc = Npc(
        id=npc_id,
        name=name,
        schedule=tuple(_parse_schedule_entry(entry, npc_id) for entry in raw_schedule),
    )
    try:
        validate_schedule(npc)
    except ValueError as error:
        raise WorldContentError(str(error)) from error
    return npc


def _parse_zone(raw: object) -> Zone:
    """Parse a zone from the content document.

    Args:
        raw: Raw object read from the document.

    Returns:
        The parsed zone.

    Raises:
        WorldContentError: If the zone is malformed.
    """
    if not isinstance(raw, dict):
        raise WorldContentError("every zone must be an object")
    zone_id = raw.get("id")
    if not isinstance(zone_id, str) or not zone_id:
        raise WorldContentError("every zone must have a non-empty string id")
    name = raw.get("name", zone_id)
    if not isinstance(name, str):
        raise WorldContentError(f"zone {zone_id}: name must be a string")
    return Zone(id=zone_id, name=name)


class WorldSim:
    """The running simulation: a tick, a list of decisions, and derivations.

    The simulator stores only the tick and the decisions. Flags, NPC states
    and lighting are recomputed on demand by :meth:`state`, :meth:`npc_states`
    and :meth:`light`, which keeps the "derived state" invariant intact.

    Attributes:
        npcs: NPCs of the world, keyed by id.
        zones: Zones of the world, keyed by id.
    """

    def __init__(self, npcs: Sequence[Npc], zones: Sequence[Zone]) -> None:
        """Build a simulation from already parsed content.

        Args:
            npcs: NPCs of the world.
            zones: Zones of the world.
        """
        self._npcs: dict[str, Npc] = {npc.id: npc for npc in npcs}
        self._zones: dict[str, Zone] = {zone.id: zone for zone in zones}
        self._tick = 0
        self._decisions: list[Decision] = []

    @classmethod
    def load(cls, path: str | Path) -> WorldSim:
        """Load the content of a world from a JSON document.

        Args:
            path: Path of the JSON document.

        Returns:
            The simulation, positioned at tick 0 with no decisions.

        Raises:
            WorldContentError: If the document is malformed or unreadable.
        """
        document = _read_document(path)
        raw_npcs = document.get("npcs", [])
        raw_zones = document.get("zones", [])
        if not isinstance(raw_npcs, list):
            raise WorldContentError("'npcs' must be a list")
        if not isinstance(raw_zones, list):
            raise WorldContentError("'zones' must be a list")

        npcs = [_parse_npc(raw) for raw in raw_npcs]
        zones = [_parse_zone(raw) for raw in raw_zones]
        return cls(npcs=npcs, zones=zones)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def tick(self) -> int:
        """Return the current tick.

        Returns:
            The tick the simulation is positioned at.
        """
        return self._tick

    def decisions(self) -> tuple[Decision, ...]:
        """Return the decisions taken so far.

        Returns:
            The decisions, in chronological order.
        """
        return tuple(self._decisions)

    def state(self) -> WorldState:
        """Return the derived state of the world.

        Returns:
            The world state at the current tick.
        """
        return derive(self._tick, self._decisions)

    def npc_states(self) -> dict[str, NpcState]:
        """Return the state of every NPC at the current tick.

        Returns:
            The NPC states, keyed by NPC id.
        """
        return {npc_id: npc_state(npc, self._tick) for npc_id, npc in self._npcs.items()}

    def light(self) -> LightState:
        """Return the lighting of the world at the current tick.

        Returns:
            The light state at the current tick.
        """
        return light_state_at(self._tick)

    def npc(self, npc_id: str) -> Npc:
        """Return an NPC by id.

        Args:
            npc_id: Id of the NPC.

        Returns:
            The NPC.

        Raises:
            KeyError: If no NPC has that id.
        """
        return self._npcs[npc_id]

    def zone(self, zone_id: str) -> Zone:
        """Return a zone by id.

        Args:
            zone_id: Id of the zone.

        Returns:
            The zone.

        Raises:
            KeyError: If no zone has that id.
        """
        return self._zones[zone_id]

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def advance(self, action: Decision) -> WorldState:
        """Record a decision and move the clock forward by one tick.

        The action is validated **before** the clock moves. An invalid action
        raises :class:`InvalidActionError` and leaves the tick untouched, so
        a rejected input never costs time.

        Args:
            action: Decision taken by the player. Its ``tick`` field is
                ignored: the simulator stamps the decision with the current
                tick.

        Returns:
            The derived world state at the new tick.

        Raises:
            InvalidActionError: If the action is not valid at the current
                tick.
            ClockOverflowError: If the cycle has already been closed.
        """
        self._validate_action(action)
        new_tick = advance(self._tick)
        decision = Decision(
            kind=action.kind,
            target=action.target,
            tick=self._tick,
            payload=dict(action.payload),
        )
        self._decisions.append(decision)
        self._tick = new_tick
        return self.state()

    def _validate_action(self, action: Decision) -> None:
        """Check that an action can be performed at the current tick.

        Args:
            action: Decision to validate.

        Raises:
            InvalidActionError: If the action is malformed or not allowed.
        """
        if not isinstance(action, Decision):
            raise InvalidActionError(f"expected a Decision, got {type(action).__name__}")
        if not action.kind:
            raise InvalidActionError("the action must have a non-empty kind")

        if action.kind == "talk":
            npc = self._npcs.get(action.target)
            if npc is None:
                raise InvalidActionError(f"unknown npc: {action.target!r}")
            if not npc_state(npc, self._tick).interactable:
                raise InvalidActionError(
                    f"{action.target} is not interactable at tick {self._tick}"
                )

    def apply(self, decision: Decision) -> WorldState:
        """Record a decision without moving the clock.

        This is the hook used by events and missions, which apply their
        effect at the tick they trigger. It is not the player-facing entry
        point; that is :meth:`advance`.

        Args:
            decision: Decision to record.

        Returns:
            The derived world state after recording the decision.

        Raises:
            InvalidActionError: If the decision is malformed.
        """
        if not isinstance(decision, Decision):
            raise InvalidActionError(f"expected a Decision, got {type(decision).__name__}")
        self._decisions.append(decision)
        return self.state()

    def advance_to(self, tick: int) -> WorldState:
        """Move the clock forward to an absolute tick.

        Args:
            tick: Absolute tick to reach.

        Returns:
            The derived world state at that tick.

        Raises:
            ValueError: If the tick is outside the playable cycle or in the
                past.
            ClockOverflowError: If the cycle would be closed past its end.
        """
        if tick < self._tick:
            raise ValueError(f"tick {tick} is in the past (current tick is {self._tick})")
        while self._tick < tick:
            self._tick = advance(self._tick)
        return self.state()


def _read_document(path: str | Path) -> dict[str, Any]:
    """Read and parse a JSON content document.

    Args:
        path: Path of the document.

    Returns:
        The parsed document.

    Raises:
        WorldContentError: If the file cannot be read or is not a JSON object.
    """
    file_path = Path(path)
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError as error:
        raise WorldContentError(f"cannot read content file {file_path}: {error}") from error
    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        raise WorldContentError(f"content file {file_path} is not valid JSON: {error}") from error
    if not isinstance(document, dict):
        raise WorldContentError(f"content file {file_path} must contain a JSON object")
    return document
