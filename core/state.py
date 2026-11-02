"""The derived state of the world.

The world is never stored. It is a **pure function** of three inputs:

    WorldState = derive(tick, decisions, resources)

``tick`` says *when* it is; ``decisions`` says *what the player chose``;
``resources`` says *what the town has left*. Everything else -- which flags
are active, which symptoms the player knows, which NPCs have already been
spoken to -- is recomputed from those inputs on every call.

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

============================  ==========================================
Flag                         Raised by
============================  ==========================================
``decided:<kind>``           any decision of that kind
``talked:<target>``          a ``"talk"`` decision targeting that NPC
``examined:<target>``        an ``"examine"`` decision targeting that object
``knows:symptom:<id>``       a ``"report_symptom"`` decision
``visited:<zone>``           a ``"move"`` decision into that zone
============================  ==========================================

A decision may also raise an explicit flag through its payload, using the
``"sets_flags"`` key, which is how content-driven flags enter the world
without the core needing to know what they mean.

Resources are an input, not an output
-------------------------------------
The provisions of the town are **consumed by the simulator**, not derived by
it. :func:`derive` receives them and copies them into the snapshot, but it
never spends them: a derivation that mutated the provisions would break the
purity of the world and would make a save file impossible to reproduce.

The consequence is that the flags still depend **only** on the decisions.
The resource state is carried along, but it raises no flag and never
influences the vocabulary: the story of what the player did and the story
of what the town has left are two separate threads.

Testimonies and the death of their witness
------------------------------------------
The illness and the investigation compete for the same resource: the people
who know things are the people who get ill, and the people who get ill stop
being there. So the death of a villager is not an arbitrary punishment: it
is the loss of the testimony that villager carried.

The rule the whole design rests on is:

    **A testimony that was obtained is kept forever. What is lost is the
    opportunity.**

Why the two are not symmetric. A testimony the player already heard is
**knowledge**. It lives in the flags of the world, it was derived from the
decisions, and the death of the witness cannot take it away: the player
already knows it. Deriving it again from the same decisions would produce
the same knowledge, and taking it away would mean rewriting the past, which
would break the purity of :func:`derive` and make a save file
unreproducible.

The **opportunity**, on the other hand, is a question about the *present*:
can the player still walk up to this villager and ask? That depends on the
clock, on the schedule and on whether the villager is still alive. It is
recomputed on demand by :func:`available_dialogues`, and the testimonies
that were never taken are reported by :func:`lost_testimonies`.

This is why :func:`derive` does not change for the death of an NPC. The
death is a fact of the world (it lives in the content, see
:mod:`core.schedule`), and the knowledge the player already holds is a fact
of the decisions. Neither of them is a flag the other one could erase.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from core.resources import ResourceState, empty_state
from core.schedule import Npc, is_dead, npc_state
from core.time import to_datetime, total_ticks

__all__ = [
    "Decision",
    "WorldState",
    "available_dialogues",
    "derive",
    "lost_testimonies",
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
        day: Day number of the snapshot, starting at 1. The cycle opens on
            Day 1 and the closing tick 480 belongs to **Day 6**, the day
            after the last playable one, exactly like
            :func:`core.time.to_datetime`.
        hour: Hour of the day, in 24h format.
        minute: Minute within the hour.
        decisions: Decisions taken so far, in chronological order.
        flags: Active flags, derived from the decisions.
        resources: Provisions of the town at this point of the run. The
            snapshot carries them as they were given to :func:`derive`: the
            derivation never spends them.
    """

    tick: int
    day: int
    hour: int
    minute: int
    decisions: tuple[Decision, ...]
    flags: frozenset[str]
    resources: ResourceState = field(default_factory=empty_state)

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
    limit = total_ticks()
    if tick > limit:
        raise ValueError(f"tick must be <= {limit}, got {tick}")
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


def derive(
    tick: int,
    decisions: Sequence[Decision],
    resources: ResourceState | None = None,
) -> WorldState:
    """Derive the world state from a tick, the decisions taken and the stock.

    The function is **pure**: it does not mutate its arguments, does not read
    the system clock, does not touch the filesystem and does not use random
    numbers. The same inputs always produce an equal state.

    The provisions of the town are an **input**, not an output. The
    derivation carries them into the snapshot but never spends them: the
    simulator is the only component allowed to consume resources, because
    consumption depends on *what the player did*, and the derivation only
    knows *what the player did* in the shape of the decisions.

    The flags still depend on the decisions alone. The resource state never
    raises a flag and never changes the flag vocabulary, so widening the
    cycle or depleting the stores cannot alter the story the flags tell.

    Args:
        tick: Tick the state describes, in ``[0, total_ticks()]``.
        decisions: Decisions taken so far, in chronological order.
        resources: Provisions of the town. When omitted, a neutral state
            that tracks nothing is used.

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
        resources=resources if resources is not None else empty_state(),
    )


def _talked_targets(state: WorldState) -> frozenset[str]:
    """Return the ids of the NPCs the player already talked to.

    Args:
        state: The derived world state.

    Returns:
        The ids of the NPCs that were the target of a ``"talk"`` decision.
    """
    return frozenset(decision.target for decision in state.decisions_of("talk") if decision.target)


def available_dialogues(
    state: WorldState,
    npcs: Sequence[Npc],
    tick: int,
) -> frozenset[str]:
    """Return the ids of the NPCs whose dialogue can still be reached.

    A dialogue is reachable when the NPC is **alive** and **interactable**
    at that tick, following its schedule. A dead NPC is not at their post,
    so their dialogue is out of reach forever.

    The distinction matters because of the design decision D34: the
    testimony the player **already obtained** is kept (it lives in the flags
    of the state, and the death of the witness cannot erase what the player
    already knows), but the **opportunity** to hear it again is lost. This
    function reports exactly that opportunity.

    Args:
        state: The derived world state. It is the context the query is
            answered in: the same set of NPCs may be reachable in one run
            and not in another, because the world is derived from the
            decisions. The reachability of a dialogue does not depend on the
            decisions today, but the signature keeps the query honest: it
            answers about a *state*, not about the content in the void.
        npcs: The NPCs of the world.
        tick: Absolute tick index.

    Returns:
        The ids of the NPCs that can be talked to at that tick.
    """
    del state
    available: set[str] = set()
    for npc in npcs:
        if is_dead(npc, tick):
            continue
        if npc_state(npc, tick).interactable:
            available.add(npc.id)
    return frozenset(available)


def lost_testimonies(
    state: WorldState,
    npcs: Sequence[Npc],
    tick: int,
) -> tuple[str, ...]:
    """Return the testimonies that were lost because a villager died.

    A testimony is lost when the villager who carried it **died** and the
    player **never talked to them**. There is no one left to ask, and no
    note was ever taken: the opportunity is gone.

    The testimony of a villager the player **did** talk to is not lost, even
    though the villager is dead: the player already knows it. The knowledge
    lives in the flags of the world, and it is not a possession of the
    villager, so the death of the villager cannot take it away.

    The rule is deliberately asymmetric, and that asymmetry is the whole
    design: the illness and the investigation compete for the same
    resource, and losing a testimony is not an arbitrary punishment. It is
    simply that the neighbour is no longer there.

    Args:
        state: The derived world state, used to read the decisions taken.
        npcs: The NPCs of the world.
        tick: Absolute tick index.

    Returns:
        The ids of the dead NPCs the player never talked to, sorted.
    """
    talked = _talked_targets(state)
    return tuple(sorted(npc.id for npc in npcs if is_dead(npc, tick) and npc.id not in talked))
