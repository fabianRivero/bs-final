"""The provisions of the town: a finite budget the player spends by acting.

Aldermere is a town under quarantine. Its people eat, they are treated, they
are moved around, and every one of those actions draws on a stock that is
finite. This module models that stock.

Design decisions
----------------
**Resources are consumed per action, not per tick.** The tick is the unit of
*time*; the resource is the unit of *effort*. A player who waits burns time
without drawing on the stores — waiting is the one action that costs nothing
but the clock — but every real action (moving, talking, examining, treating)
draws its cost from the provisions. Charging per tick would punish the
player for thinking, which is exactly the wrong incentive: the game wants the
player to spend time carefully, not to rush.

**Resources are an input of the derived state, never an output.**
:func:`core.state.derive` takes the resource state as an argument and never
mutates it. The world stays a pure function of ``(tick, decisions,
resources)``, so a save file holds three fields and nothing can drift out of
sync.

**A resource never goes negative.** When the stock is not enough to cover a
cost, the consumption is *clamped to zero* and the resource is considered
depleted. A negative stock of food is not a state the simulation can
represent: it would mean the player is owed provisions, which is the
opposite of what running out of them means. Clamping keeps the invariant
"amounts are always in ``[0, initial]``" true for the whole life of a run,
and it lets the crisis be detected without special cases.

**Immutability.** Both :class:`ResourceSpec` and :class:`ResourceState` are
frozen dataclasses. The amounts of a state are held in a
:class:`types.MappingProxyType`, a read-only view of a dictionary: it cannot
be mutated from the outside, and the dictionary it wraps is never shared with
anybody else, because :func:`consume` builds a brand new one.

All functions in this module are pure and deterministic. They never read the
system clock and never use random numbers.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

__all__ = [
    "ResourceSpec",
    "ResourceState",
    "can_afford",
    "consume",
    "derive_crisis",
    "empty_state",
    "initial_state",
]


@dataclass(frozen=True)
class ResourceSpec:
    """The definition of a provision of the town.

    A spec is **data**: it says how much the town has, what each action
    costs, and when the stock runs low enough for the town to suffer.

    Attributes:
        id: Stable identifier of the resource, e.g. ``"RES_FOOD"``.
        label: Display name of the resource.
        initial: Amount the town starts the cycle with. Must be at least 0.
        per_action: Amount consumed by a single normal action. Must be at
            least 0.
        critical_at: Amount at or below which the town suffers. A resource
            is **critical** when its amount is *strictly below* this value,
            and **depleted** when its amount has reached 0.
    """

    id: str
    label: str
    initial: int
    per_action: int
    critical_at: int

    def __post_init__(self) -> None:
        """Validate the boundaries of the spec.

        Raises:
            ValueError: If the identifiers are empty or a quantity is
                negative, or if ``critical_at`` is above ``initial``.
        """
        if not self.id:
            raise ValueError("a resource spec must have a non-empty id")
        if not self.label:
            raise ValueError(f"resource {self.id}: label must be a non-empty string")
        if self.initial < 0:
            raise ValueError(f"resource {self.id}: initial must be >= 0, got {self.initial}")
        if self.per_action < 0:
            raise ValueError(f"resource {self.id}: per_action must be >= 0, got {self.per_action}")
        if self.critical_at < 0:
            raise ValueError(
                f"resource {self.id}: critical_at must be >= 0, got {self.critical_at}"
            )
        if self.critical_at > self.initial:
            raise ValueError(
                f"resource {self.id}: critical_at {self.critical_at} must not be greater than "
                f"initial {self.initial}"
            )

    @property
    def cost(self) -> int:
        """Return the amount consumed by a single action.

        Returns:
            The per-action cost of the resource.
        """
        return self.per_action


@dataclass(frozen=True)
class ResourceState:
    """The current amount of every provision of the town.

    The state is immutable: the amounts are held in a read-only mapping, and
    every operation returns a **new** state instead of mutating this one.

    Attributes:
        amounts: Amount of every resource, keyed by resource id. The mapping
            is a :class:`types.MappingProxyType`, so it cannot be changed
            from the outside.
    """

    amounts: Mapping[str, int]

    def __post_init__(self) -> None:
        """Freeze the amounts so the state is genuinely immutable.

        Raises:
            TypeError: If the amounts are not a mapping of ints.
        """
        if not isinstance(self.amounts, Mapping):
            raise TypeError(f"amounts must be a mapping, got {type(self.amounts).__name__}")
        for resource_id, amount in self.amounts.items():
            if not isinstance(amount, int) or isinstance(amount, bool):
                raise TypeError(
                    f"resource {resource_id}: amount must be an int, got {type(amount).__name__}"
                )
            if amount < 0:
                raise ValueError(f"resource {resource_id}: amount must be >= 0, got {amount}")
        object.__setattr__(self, "amounts", MappingProxyType(dict(self.amounts)))

    def amount(self, resource_id: str) -> int:
        """Return the amount of a resource.

        Args:
            resource_id: Identifier of the resource.

        Returns:
            The amount held, or ``0`` when the resource is not tracked. An
            untracked resource holds nothing, so it behaves like an
            exhausted one as far as the amounts are concerned.
        """
        return self.amounts.get(resource_id, 0)

    def tracks(self, resource_id: str) -> bool:
        """Check whether a resource is tracked by this state.

        An untracked resource is *absent*, not *empty*. The distinction
        matters: an absent resource cannot be in crisis and is not reported
        as depleted, because the town never stocked it.

        Args:
            resource_id: Identifier of the resource.

        Returns:
            ``True`` when the state holds an amount for the resource.
        """
        return resource_id in self.amounts

    def is_critical(self, spec: ResourceSpec) -> bool:
        """Check whether a resource is in a critical state.

        A resource is critical when its amount has fallen **strictly below**
        the ``critical_at`` threshold of its spec. A resource that is not
        tracked cannot be in crisis: the town never stocked it.

        Args:
            spec: Specification of the resource to check.

        Returns:
            ``True`` when the amount is below the critical threshold.
        """
        if not self.tracks(spec.id):
            return False
        return self.amount(spec.id) < spec.critical_at

    def is_depleted(self, spec: ResourceSpec) -> bool:
        """Check whether a resource has run out.

        A resource that is not tracked is not *depleted*, it is absent: the
        town never stocked it, so there is nothing that ran out.

        Args:
            spec: Specification of the resource to check.

        Returns:
            ``True`` when the tracked amount has reached zero.
        """
        if not self.tracks(spec.id):
            return False
        return self.amount(spec.id) <= 0

    def critical_resources(self, specs: Sequence[ResourceSpec]) -> tuple[str, ...]:
        """Return the ids of the resources that have run critically low.

        The ids are sorted, so the result is stable and comparable. A
        resource is critical when its amount has fallen strictly below the
        ``critical_at`` threshold of its spec, which is the same rule as
        :meth:`is_critical`.

        Args:
            specs: Specifications of the resources of the town.

        Returns:
            The ids of the resources in critical state, sorted.
        """
        return derive_crisis(self, specs)

    def __eq__(self, other: object) -> bool:
        """Compare two states by content.

        Args:
            other: The object to compare with.

        Returns:
            ``True`` when ``other`` is a state with the same amounts.
        """
        if not isinstance(other, ResourceState):
            return NotImplemented
        return dict(self.amounts) == dict(other.amounts)

    def __hash__(self) -> int:
        """Return a hash consistent with the content equality.

        Returns:
            The hash of the sorted amounts.
        """
        return hash(tuple(sorted(self.amounts.items())))


def empty_state() -> ResourceState:
    """Return a state that tracks no resource at all.

    It is the neutral state used when a world declares no provisions, and the
    default of the optional ``resources`` argument of
    :func:`core.state.derive`.

    Returns:
        A state with no amounts.
    """
    return ResourceState(amounts=MappingProxyType({}))


def initial_state(specs: Iterable[ResourceSpec]) -> ResourceState:
    """Build the state a cycle starts with.

    Args:
        specs: Specifications of the resources of the town.

    Returns:
        A state where every resource holds its ``initial`` amount.

    Raises:
        ValueError: If two specs share the same id.
    """
    amounts: dict[str, int] = {}
    for spec in specs:
        if spec.id in amounts:
            raise ValueError(f"duplicated resource id: {spec.id}")
        amounts[spec.id] = spec.initial
    return ResourceState(amounts=MappingProxyType(amounts))


def can_afford(state: ResourceState, specs: Sequence[ResourceSpec], actions: int = 1) -> bool:
    """Check whether the town can pay for a number of actions.

    Args:
        state: Current state of the provisions.
        specs: Specifications of the resources of the town.
        actions: Number of actions the player wants to perform. Must be a
            non-negative integer.

    Returns:
        ``True`` when every resource holds enough to cover the cost of
        ``actions`` actions.

    Raises:
        TypeError: If ``actions`` is not an integer.
        ValueError: If ``actions`` is negative.
    """
    if not isinstance(actions, int) or isinstance(actions, bool):
        raise TypeError(f"actions must be an int, got {type(actions).__name__}")
    if actions < 0:
        raise ValueError(f"actions must be >= 0, got {actions}")

    return all(state.amount(spec.id) >= spec.per_action * actions for spec in specs)


def consume(
    state: ResourceState,
    specs: Sequence[ResourceSpec],
    actions: int = 1,
) -> ResourceState:
    """Consume the provisions of a number of actions.

    The function is **pure**: it never mutates the state it receives, and it
    returns a brand new one. The amounts are clamped to zero, so a resource
    that cannot cover its cost ends up depleted rather than negative. A
    negative amount would mean the town owes provisions, which is not a
    state the simulation can represent.

    Args:
        state: Current state of the provisions.
        specs: Specifications of the resources of the town.
        actions: Number of actions to pay for. Must be a non-negative
            integer.

    Returns:
        The state after the consumption.

    Raises:
        TypeError: If ``actions`` is not an integer.
        ValueError: If ``actions`` is negative.

    Example:
        >>> spec = ResourceSpec(id="RES_FOOD", label="Food", initial=3,
        ...                     per_action=1, critical_at=1)
        >>> consume(initial_state([spec]), [spec]).amounts["RES_FOOD"]
        2
    """
    if not isinstance(actions, int) or isinstance(actions, bool):
        raise TypeError(f"actions must be an int, got {type(actions).__name__}")
    if actions < 0:
        raise ValueError(f"actions must be >= 0, got {actions}")

    amounts = dict(state.amounts)
    for spec in specs:
        if spec.id not in amounts:
            # A resource the state does not track stays untracked: it was
            # never stocked, so there is nothing to spend and nothing to
            # clamp. Making it tracked with an amount of zero would turn an
            # absent resource into an exhausted one.
            continue
        remaining = amounts[spec.id] - spec.per_action * actions
        amounts[spec.id] = max(0, remaining)
    return ResourceState(amounts=MappingProxyType(amounts))


def derive_crisis(state: ResourceState, specs: Sequence[ResourceSpec]) -> tuple[str, ...]:
    """Return the resources whose exhaustion puts the town in crisis.

    A resource is in crisis when its amount has fallen **strictly below** the
    ``critical_at`` threshold of its spec. A resource that the state does not
    track is *absent*, not in crisis: the town never stocked it. The ids are
    sorted, so the result is stable and comparable.

    Args:
        state: Current state of the provisions.
        specs: Specifications of the resources of the town.

    Returns:
        The ids of the resources in crisis, sorted.
    """
    return tuple(sorted(spec.id for spec in specs if state.is_critical(spec)))
