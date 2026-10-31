"""The derived state of the world.

The world is never stored. It is a **pure function** of two inputs:

    WorldState = derive(tick, decisions)

``tick`` says *when* it is; ``decisions`` says *what the player chose*.
Everything else -- which flags are active, which symptoms the player knows,
which NPCs have already been spoken to -- is recomputed from those two
inputs on every call.

This module owns:

* :class:`Decision` -- an immutable record of a player action.
* :class:`WorldState` -- the immutable derived snapshot.
* :func:`derive` -- the pure function that builds it.
* The flag vocabulary, which is derived from the decisions themselves so that
  no rule lives in two places.

Flag vocabulary
---------------
Flags are named strings. The derivation sets them from the decisions that
have been taken:

===========================  ==========================================
Flag                         Raised by
===========================  ==========================================
``decided:<kind>``           any decision of that kind
``talked:<target>``          a ``"talk"`` decision targeting that NPC
``examined:<target>``        an ``"examine"`` decision targeting that object
``knows:symptom:<id>``       a ``"report_symptom"`` decision
``visited:<zone>``           a ``"move"`` decision into that zone
===========================  ==========================================

A decision may also raise an explicit flag through its payload, using the
``"sets_flags"`` key, which is how content-driven flags enter the world
without the core needing to know what they mean.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from core.time import TOTAL_TICKS, to_datetime

__all__ = [
    "Decision",
    "WorldState",
    "derive",
]


@dataclass(frozen=True)
class Decision:
    """An action taken by the player.

    The payload is copied on construction so that a decision can never be
    changed behind the back of the derived state: the world must be a
    function of immutable inputs.

    Attributes:
        kind: Kind of action, e.g. ``"talk"``, ``"examine"``,
            ``"report_symptom"``. The kind drives the derived flags.
        target: Id of the NPC or object the action refers to. May be empty
            for actions that do not target anything.
        tick: Tick at which the decision was taken.
        payload: Extra data of the decision, e.g. the id of the reported
            symptom. The payload must contain hashable values only when the
            decision itself is used as a dictionary key.
    """

    kind: str
    target: str
    tick: int
    payload: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Copy the payload so the decision is genuinely immutable.

        Raises:
            TypeError: If the payload is not a mapping.
        """
        if not isinstance(self.payload, dict):
            raise TypeError(f"payload must be a dict, got {type(self.payload).__name__}")
        object.__setattr__(self, "payload", dict(self.payload))

    def sets_flag(self, name: str) -> bool:
        """Check whether the decision explicitly raises a flag.

        Args:
            name: Name of the flag.

        Returns:
            ``True`` when the flag is listed in the ``"sets_flags"`` payload.
        """
        explicit = self.payload.get("sets_flags")
        if isinstance(explicit, str):
            return explicit == name
        if isinstance(explicit, Iterable):
            return name in explicit
        # A payload that is neither a string nor a collection raises no flag.
        return False


@dataclass(frozen=True)
class WorldState:
    """An immutable snapshot of the derived world.

    Attributes:
        tick: Tick the snapshot describes.
        day: Day number of the snapshot, starting at 1.
        hour: Hour of the day, in 24h format.
        minute: Minute within the hour.
        decisions: Decisions taken so far, in chronological order.
        flags: Active flags, derived from the decisions.
    """

    tick: int
    day: int
    hour: int
    minute: int
    decisions: tuple[Decision, ...]
    flags: frozenset[str]

    def has_flag(self, name: str) -> bool:
        """Check whether a flag is active.

        Args:
            name: Name of the flag.

        Returns:
            ``True`` when the flag is active.
        """
        return name in self.flags

    def decisions_of(self, kind: str) -> tuple[Decision, ...]:
        """Return every decision of a given kind.

        Args:
            kind: Kind of decision to filter by.

        Returns:
            The matching decisions, in chronological order.
        """
        return tuple(decision for decision in self.decisions if decision.kind == kind)

    def symptoms_known(self) -> tuple[str, ...]:
        """Return the ids of the symptoms the player knows about.

        Returns:
            The symptom ids, sorted and without duplicates.
        """
        symptoms = {
            str(decision.payload["symptom"])
            for decision in self.decisions
            if decision.kind == "report_symptom" and "symptom" in decision.payload
        }
        return tuple(sorted(symptoms))


def _validate_tick(tick: int) -> int:
    """Ensure a tick lies inside the playable cycle.

    Args:
        tick: Tick index to validate.

    Returns:
        The validated tick.

    Raises:
        TypeError: If ``tick`` is not an integer.
        ValueError: If ``tick`` is negative or beyond the closing tick.
    """
    if not isinstance(tick, int) or isinstance(tick, bool):
        raise TypeError(f"tick must be an int, got {type(tick).__name__}")
    if tick < 0:
        raise ValueError(f"tick must be >= 0, got {tick}")
    if tick > TOTAL_TICKS:
        raise ValueError(f"tick must be <= {TOTAL_TICKS}, got {tick}")
    return tick


def _flag_for_decision(decision: Decision) -> tuple[str, ...]:
    """Compute the flags raised by a single decision.

    Args:
        decision: Decision to inspect.

    Returns:
        The names of the flags raised by the decision.
    """
    flags = [f"decided:{decision.kind}"]

    if decision.kind == "talk" and decision.target:
        flags.append(f"talked:{decision.target}")
    elif decision.kind == "examine" and decision.target:
        flags.append(f"examined:{decision.target}")
    elif decision.kind == "report_symptom":
        symptom = decision.payload.get("symptom")
        if symptom is not None:
            flags.append(f"knows:symptom:{symptom}")
    elif decision.kind == "move" and decision.target:
        flags.append(f"visited:{decision.target}")

    explicit = decision.payload.get("sets_flags")
    if isinstance(explicit, str):
        flags.append(explicit)
    elif isinstance(explicit, Iterable):
        flags.extend(str(name) for name in explicit)

    return tuple(flags)


def derive(tick: int, decisions: Sequence[Decision]) -> WorldState:
    """Derive the world state from a tick and the decisions taken.

    The function is **pure**: it does not mutate its arguments, does not read
    the system clock, does not touch the filesystem and does not use random
    numbers. The same inputs always produce an equal state.

    Args:
        tick: Tick the state describes, in ``[0, TOTAL_TICKS]``.
        decisions: Decisions taken so far, in chronological order.

    Returns:
        The derived world state.

    Raises:
        TypeError: If ``tick`` is not an integer or a decision is malformed.
        ValueError: If ``tick`` is outside the playable cycle.

    Example:
        >>> derive(0, ()).flags
        frozenset()
    """
    _validate_tick(tick)
    ordered = tuple(decisions)
    for decision in ordered:
        if not isinstance(decision, Decision):
            raise TypeError(f"expected a Decision, got {type(decision).__name__}")

    day, hour, minute = to_datetime(tick)

    flags: set[str] = set()
    for decision in ordered:
        flags.update(_flag_for_decision(decision))

    return WorldState(
        tick=tick,
        day=day,
        hour=hour,
        minute=minute,
        decisions=ordered,
        flags=frozenset(flags),
    )
