"""Composition root: load the content and expose the running simulation.

:class:`WorldSim` is the object the presentation layer talks to. It is the
only place where mutable state lives, and that state is deliberately minimal:
the current **tick**, the list of **decisions** taken so far and the
**provisions** of the town. Everything else -- flags, NPC positions,
lighting -- is derived on demand.

That design is what makes save/load trivial: a save file only needs
``{tick, decisions, resources}``, because the world was never stored in the
first place.

The golden rule of the project holds here: Python decides, Godot only
presents and captures input. ``advance(action)`` is the single entry point
that mutates the world, and it only does so when the action is valid. An
invalid action raises :class:`InvalidActionError` and **does not consume a
tick**, which matches the rule that bumping into a wall is not an action.

An action the town cannot afford raises :class:`InsufficientResourcesError`
and consumes **neither** a tick nor a resource: the player is not allowed to
act on provisions that do not exist.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.lighting import LightState, light_state_at
from core.resources import (
    ResourceSpec,
    ResourceState,
    can_afford,
    consume,
    derive_crisis,
    initial_state,
)
from core.schedule import Npc, NpcState, ScheduleEntry, npc_state, validate_schedule
from core.state import Decision, WorldState, derive
from core.time import advance

__all__ = [
    "InsufficientResourcesError",
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
    """Base class of the errors raised when an action cannot be performed.

    The action is rejected *before* the clock moves, so the tick is not
    consumed. Typical causes are talking to an NPC that is not interactable
    at that moment or targeting an unknown NPC.
    """


class InsufficientResourcesError(InvalidActionError):
    """Raised when the town cannot pay for an action.

    Like :class:`InvalidActionError`, the action is rejected **before** the
    clock moves, so neither the tick nor the provisions are consumed. The
    town cannot act on stores that do not exist.
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


def _parse_resource_spec(raw: object) -> ResourceSpec:
    """Parse a resource specification from the content document.

    Args:
        raw: Raw object read from the document.

    Returns:
        The parsed specification.

    Raises:
        WorldContentError: If the specification is malformed.
    """
    if not isinstance(raw, dict):
        raise WorldContentError("every resource must be an object")
    resource_id = raw.get("id")
    if not isinstance(resource_id, str) or not resource_id:
        raise WorldContentError("every resource must have a non-empty string id")
    label = raw.get("label", resource_id)
    if not isinstance(label, str):
        raise WorldContentError(f"resource {resource_id}: label must be a string")

    amounts: dict[str, int] = {}
    for field_name in ("initial", "per_action", "critical_at"):
        value = raw.get(field_name)
        if not isinstance(value, int) or isinstance(value, bool):
            raise WorldContentError(f"resource {resource_id}: {field_name} must be an integer")
        amounts[field_name] = value

    try:
        return ResourceSpec(
            id=resource_id,
            label=label,
            initial=amounts["initial"],
            per_action=amounts["per_action"],
            critical_at=amounts["critical_at"],
        )
    except ValueError as error:
        raise WorldContentError(str(error)) from error


class WorldSim:
    """The running simulation: a tick, a list of decisions and the provisions.

    The simulator stores only the tick, the decisions and the resource
    state. Flags, NPC states and lighting are recomputed on demand by
    :meth:`state`, :meth:`npc_states` and :meth:`light`, which keeps the
    "derived state" invariant intact.

    Attributes:
        npcs: NPCs of the world, keyed by id.
        zones: Zones of the world, keyed by id.
    """

    def __init__(
        self,
        npcs: Sequence[Npc],
        zones: Sequence[Zone],
        resource_specs: Sequence[ResourceSpec] = (),
    ) -> None:
        """Build a simulation from already parsed content.

        Args:
            npcs: NPCs of the world.
            zones: Zones of the world.
            resource_specs: Provisions of the town. The simulation starts
                with every resource at its ``initial`` amount.
        """
        self._npcs: dict[str, Npc] = {npc.id: npc for npc in npcs}
        self._zones: dict[str, Zone] = {zone.id: zone for zone in zones}
        self._resource_specs: tuple[ResourceSpec, ...] = tuple(resource_specs)
        self._tick = 0
        self._decisions: list[Decision] = []
        self._resources: ResourceState = initial_state(self._resource_specs)

    @classmethod
    def load(cls, path: str | Path) -> WorldSim:
        """Load the content of a world from a JSON document.

        The optional ``resources`` field of the document declares the
        provisions of the town. When it is absent, the world has no
        provisions at all and no action costs anything.

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
        raw_resources = document.get("resources", [])
        if not isinstance(raw_npcs, list):
            raise WorldContentError("'npcs' must be a list")
        if not isinstance(raw_zones, list):
            raise WorldContentError("'zones' must be a list")
        if not isinstance(raw_resources, list):
            raise WorldContentError("'resources' must be a list")

        npcs = [_parse_npc(raw) for raw in raw_npcs]
        zones = [_parse_zone(raw) for raw in raw_zones]
        resources = [_parse_resource_spec(raw) for raw in raw_resources]
        seen: set[str] = set()
        for spec in resources:
            if spec.id in seen:
                raise WorldContentError(f"duplicated resource id: {spec.id}")
            seen.add(spec.id)
        return cls(npcs=npcs, zones=zones, resource_specs=resources)

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

    def resources(self) -> ResourceState:
        """Return the provisions of the town.

        Returns:
            The current resource state.
        """
        return self._resources

    def resource_specs(self) -> tuple[ResourceSpec, ...]:
        """Return the specifications of the provisions of the town.

        Returns:
            The resource specs, in the order they were declared.
        """
        return self._resource_specs

    def crisis(self) -> tuple[str, ...]:
        """Return the resources whose exhaustion puts the town in crisis.

        Returns:
            The ids of the resources in crisis, sorted.
        """
        return derive_crisis(self._resources, self._resource_specs)

    def state(self) -> WorldState:
        """Return the derived state of the world.

        Returns:
            The world state at the current tick.
        """
        return derive(self._tick, self._decisions, self._resources)

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
        """Record a decision, spend the provisions and move the clock forward.

        The action is validated **before** anything moves. An invalid action
        raises :class:`InvalidActionError` and leaves the tick untouched, so
        a rejected input never costs time. An action the town cannot afford
        raises :class:`InsufficientResourcesError` and leaves **both** the
        tick and the provisions untouched: the player cannot act on stores
        that do not exist.

        The resources are consumed **per action**, not per tick. Waiting
        advances the clock without drawing on the provisions, but every real
        action pays its cost.

        Args:
            action: Decision taken by the player. Its ``tick`` field is
                ignored: the simulator stamps the decision with the current
                tick.

        Returns:
            The derived world state at the new tick.

        Raises:
            InvalidActionError: If the action is not valid at the current
                tick.
            InsufficientResourcesError: If the town cannot pay for the
                action.
            ClockOverflowError: If the cycle has already been closed.
        """
        self._validate_action(action)
        self._validate_resources()
        new_tick = advance(self._tick)
        decision = Decision(
            kind=action.kind,
            target=action.target,
            tick=self._tick,
            payload=dict(action.payload),
        )
        self._decisions.append(decision)
        self._tick = new_tick
        self._resources = consume(self._resources, self._resource_specs)
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

    def _validate_resources(self) -> None:
        """Check that the town can pay for one more action.

        Raises:
            InsufficientResourcesError: If a resource does not hold enough
                to cover the cost of a single action.
        """
        if can_afford(self._resources, self._resource_specs):
            return
        exhausted = tuple(
            spec.id
            for spec in self._resource_specs
            if self._resources.amount(spec.id) < spec.per_action
        )
        raise InsufficientResourcesError(
            f"the town cannot afford this action: {', '.join(exhausted)}"
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
