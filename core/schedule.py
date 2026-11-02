"""Daily schedules of the NPCs and the resolution of their state at a tick.

An NPC is somewhere, doing something, and possibly willing to talk. All three
facts are a **pure function of the tick**: ``npc_state(npc, tick)`` never
consults the world state and never mutates the schedule.

Schedule convention
-------------------
A schedule is a list of :class:`ScheduleEntry` blocks expressed in **ticks
within a single day**, so ``0`` is 00:00 and ``96`` is the end of the day.
The absolute tick is normalised with ``tick % TICKS_PER_DAY`` before the
lookup, which means the pattern of Day 2 is identical to the pattern of
Day 1. A block covers the half-open range ``[start_tick, end_tick)``: the
block that ends at 28 does **not** cover tick 28.

Blocks must not overlap. Two blocks covering the same tick would make the
state of the NPC ambiguous, so the schedule is validated when the NPC is
built and a clear error is raised when it happens.

Gaps are allowed on purpose. When no block covers the tick, the NPC is in its
*default* state: at the origin, idle and **not** interactable. A schedule may
also declare an explicit default block by using the reserved zone id
``"default"``.

Death
-----
An NPC may die. The death is a **property of the NPC**, not a decision of the
player: it is declared by the content as ``deceased_at_tick``, and it is
resolved by the very same pure function that resolves the schedule.

The tick of the death is the tick at which the NPC is **already gone**::

    deceased_at_tick = 192  ->  alive at tick 191, dead at tick 192

The comparison is therefore ``tick >= deceased_at_tick``, not
``tick > deceased_at_tick``. The convention is the one the rest of the
project uses for half-open ranges: the day of the death belongs to the death.

A dead NPC is **not at its post and not interactable**. Its tile and its
activity are *not resolved*: a dead villager is not "idle at the origin",
they are simply not in the world. So the state of a dead NPC is the default
state with ``alive=False`` and ``interactable=False``, and the schedule is
never consulted for it.

This is the whole point of the design decision D34: the player learns how
bad the illness is through the people, and the people stop being there.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

from core.time import TICKS_PER_DAY

__all__ = [
    "DEFAULT_ACTIVITY",
    "DEFAULT_ZONE",
    "Npc",
    "NpcState",
    "ScheduleEntry",
    "ScheduleOverlapError",
    "is_available",
    "is_dead",
    "npc_state",
    "validate_schedule",
]

#: Zone id reserved for the default (fallback) state of an NPC.
DEFAULT_ZONE = "default"

#: Activity reported when no schedule block covers the tick.
DEFAULT_ACTIVITY = "idle"


class ScheduleOverlapError(ValueError):
    """Raised when two schedule blocks cover the same tick of the day.

    Overlapping blocks make the state of an NPC ambiguous, which would break
    the determinism invariant of the simulation core. The problem is a content
    error, so it is reported loudly at load time instead of being resolved
    silently.
    """


@dataclass(frozen=True)
class ScheduleEntry:
    """One block of an NPC daily routine.

    Attributes:
        start_tick: First tick of the block within the day, inclusive. Must
            be in ``[0, TICKS_PER_DAY)``.
        end_tick: Tick at which the block ends, exclusive. Must be in
            ``(0, TICKS_PER_DAY]``. The block covers ``start_tick`` up to but
            not including ``end_tick``.
        zone: Id of the zone the NPC occupies during the block. The reserved
            value ``"default"`` marks the fallback block.
        tile: Tile coordinates inside the zone, as ``(x, y)``.
        activity: Activity performed during the block, e.g. ``"selling_fish"``.
            The dialogue of the NPC varies with the activity.
        interactable: Whether the player can talk to the NPC during the
            block.
    """

    start_tick: int
    end_tick: int
    zone: str
    tile: tuple[int, int]
    activity: str
    interactable: bool


@dataclass(frozen=True)
class NpcState:
    """Where an NPC is and what it is doing at a given tick.

    Attributes:
        npc_id: Id of the NPC.
        zone: Zone the NPC occupies.
        tile: Tile coordinates inside the zone.
        activity: Activity performed at that moment.
        interactable: Whether the player can interact with the NPC.
        alive: Whether the NPC is alive at that tick. A dead NPC is not at
            its post and cannot be interacted with.
    """

    npc_id: str
    zone: str
    tile: tuple[int, int]
    activity: str
    interactable: bool
    alive: bool = True


@dataclass(frozen=True)
class Npc:
    """An NPC and its daily routine.

    Attributes:
        id: Stable identifier of the NPC, e.g. ``"NPC_MARTA"``.
        name: Display name of the NPC.
        schedule: Blocks of the daily routine, ordered by ``start_tick``.
            Blocks must not overlap.
        deceased_at_tick: Absolute tick at which the NPC dies, or ``None``
            when it survives the whole cycle. The tick is **inclusive of the
            death**: the NPC is alive at ``deceased_at_tick - 1`` and already
            dead at ``deceased_at_tick``.
        death_cause: Label of the cause of the death, e.g.
            ``"plague_fever"``. It is empty while the NPC lives.
    """

    id: str
    name: str
    schedule: tuple[ScheduleEntry, ...]
    deceased_at_tick: int | None = None
    death_cause: str = ""


def _validate_entry(entry: ScheduleEntry, npc_id: str) -> None:
    """Validate the boundaries of a single schedule block.

    Args:
        entry: Block to validate.
        npc_id: Id of the owning NPC, used in the error messages.

    Raises:
        ValueError: If the block boundaries are outside the day or inverted.
    """
    if not 0 <= entry.start_tick < TICKS_PER_DAY:
        raise ValueError(
            f"schedule of {npc_id}: start_tick must be within "
            f"[0, {TICKS_PER_DAY - 1}], got {entry.start_tick}"
        )
    if not 0 < entry.end_tick <= TICKS_PER_DAY:
        raise ValueError(
            f"schedule of {npc_id}: end_tick must be within "
            f"[1, {TICKS_PER_DAY}], got {entry.end_tick}"
        )
    if entry.start_tick >= entry.end_tick:
        raise ValueError(
            f"schedule of {npc_id}: start_tick {entry.start_tick} must be "
            f"lower than end_tick {entry.end_tick}"
        )


def validate_schedule(npc: Npc) -> None:
    """Validate a whole schedule: boundaries and absence of overlaps.

    The content loader calls this when it parses a world, so that an invalid
    schedule is reported at load time instead of producing an ambiguous NPC
    state at runtime.

    Args:
        npc: NPC whose schedule is validated.

    Raises:
        ValueError: If a block boundary is invalid.
        ScheduleOverlapError: If two blocks cover the same tick.
    """
    for entry in npc.schedule:
        _validate_entry(entry, npc.id)

    ordered = sorted(npc.schedule, key=lambda item: item.start_tick)
    for previous, following in itertools.pairwise(ordered):
        if following.start_tick < previous.end_tick:
            raise ScheduleOverlapError(
                f"schedule of {npc.id} overlaps: block "
                f"[{previous.start_tick}, {previous.end_tick}) intersects block "
                f"[{following.start_tick}, {following.end_tick})"
            )


def _default_state(npc: Npc) -> NpcState:
    """Build the fallback state of an NPC.

    The default block of the schedule is used when it exists; otherwise the
    NPC is reported as idle at the origin and not interactable.

    Args:
        npc: NPC to describe.

    Returns:
        The default state of the NPC.
    """
    for entry in npc.schedule:
        if entry.zone == DEFAULT_ZONE:
            return NpcState(
                npc_id=npc.id,
                zone=entry.zone,
                tile=entry.tile,
                activity=entry.activity,
                interactable=entry.interactable,
            )
    return NpcState(
        npc_id=npc.id,
        zone=DEFAULT_ZONE,
        tile=(0, 0),
        activity=DEFAULT_ACTIVITY,
        interactable=False,
    )


def _dead_state(npc: Npc) -> NpcState:
    """Build the state of an NPC that is already dead.

    A dead NPC is **not at its post and not interactable**. Its tile and its
    activity are *not resolved*: the schedule is never consulted for
    somebody who is no longer in the world. The state is the default state
    with ``alive=False`` and ``interactable=False``, so the presentation
    layer can simply skip the NPC.

    Args:
        npc: NPC to describe.

    Returns:
        The state of the dead NPC.
    """
    default = _default_state(npc)
    return NpcState(
        npc_id=npc.id,
        zone=default.zone,
        tile=default.tile,
        activity=default.activity,
        interactable=False,
        alive=False,
    )


def is_dead(npc: Npc, tick: int) -> bool:
    """Check whether an NPC is dead at a given tick.

    The tick of the death is the tick at which the NPC is **already gone**:
    an NPC whose ``deceased_at_tick`` is ``192`` is alive at tick 191 and
    dead at tick 192.

    Args:
        npc: NPC to check.
        tick: Absolute tick index.

    Returns:
        ``True`` when the NPC is dead at that tick.

    Raises:
        TypeError: If ``tick`` is not an integer.
        ValueError: If ``tick`` is negative.
    """
    if not isinstance(tick, int) or isinstance(tick, bool):
        raise TypeError(f"tick must be an int, got {type(tick).__name__}")
    if tick < 0:
        raise ValueError(f"tick must be >= 0, got {tick}")

    if npc.deceased_at_tick is None:
        return False
    return tick >= npc.deceased_at_tick


def npc_state(npc: Npc, tick: int) -> NpcState:
    """Resolve the state of an NPC at a given tick.

    The daily pattern repeats, so the absolute tick is normalised with
    ``tick % TICKS_PER_DAY``: tick 28 and tick 124 resolve to the same state.

    A dead NPC is **not at its post and not interactable**. The tick of the
    death is the tick at which the NPC is already gone: with
    ``deceased_at_tick = 192`` the NPC is alive at tick 191 and dead at tick
    192. The tile and the activity of a dead NPC are not resolved, because
    a dead villager is not idle at the origin: they are simply not there.

    Args:
        npc: NPC whose state is resolved.
        tick: Absolute tick index.

    Returns:
        The zone, tile, activity, interactability and liveness of the NPC.

    Raises:
        TypeError: If ``tick`` is not an integer.
        ValueError: If ``tick`` is negative.

    Example:
        >>> npc_state(MARTA, 28).activity
        'selling_fish'
    """
    if not isinstance(tick, int) or isinstance(tick, bool):
        raise TypeError(f"tick must be an int, got {type(tick).__name__}")
    if tick < 0:
        raise ValueError(f"tick must be >= 0, got {tick}")

    if is_dead(npc, tick):
        return _dead_state(npc)

    position = tick % TICKS_PER_DAY
    for entry in npc.schedule:
        if entry.start_tick <= position < entry.end_tick:
            return NpcState(
                npc_id=npc.id,
                zone=entry.zone,
                tile=entry.tile,
                activity=entry.activity,
                interactable=entry.interactable,
            )
    return _default_state(npc)


def is_available(npc: Npc, tick: int) -> bool:
    """Check whether the player can interact with an NPC at a given tick.

    The answer is the interactability of the resolved state, so a dead NPC
    is never available: a dead villager is not at their post.

    Args:
        npc: NPC to check.
        tick: Absolute tick index.

    Returns:
        ``True`` when the NPC is interactable at that tick.

    Raises:
        TypeError: If ``tick`` is not an integer.
        ValueError: If ``tick`` is negative.
    """
    return npc_state(npc, tick).interactable
