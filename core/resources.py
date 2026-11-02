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

**The town eats every day.** A resource may declare a ``daily_decay``: the
amount the town itself consumes when a day passes. The mine of Aldermere is
closed, so nothing comes in and the stores fall on their own: the food goes
down even when the player does nothing at all. The decay is applied when the
clock **crosses a day boundary** (from tick 95 to tick 96, and so on), never
per tick. Charging it per tick would punish the player for thinking, and it
would make the arithmetic of a day meaningless: one decay per crossing, no
matter how many ticks the crossing took.

**A critical resource costs more, not less.** A resource whose amount fell
*strictly below* its ``critical_at`` threshold is in crisis. The crisis is
not a wall: the action is still possible, but it costs **twice** as much,
because the town is short of everything and has to make do with worse
material, walk further, work longer. A resource that is **depleted** (its
amount reached zero) blocks the actions it declares in ``blocks_actions``:
those actions fail with :class:`core.world.InsufficientResourcesError`.

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
from dataclasses import dataclass, field
from types import MappingProxyType

__all__ = [
    "CRITICAL_COST_MULTIPLIER",
    "ResourceSpec",
    "ResourceState",
    "apply_daily_decay",
    "can_afford",
    "consume",
    "derive_crisis",
    "empty_state",
    "initial_state",
    "reset_spent_today",
]

#: Multiplier applied to the cost of the actions a critical resource blocks.
#:
#: When a resource is in crisis, the actions it gates cost twice as much:
#: the town is short of everything and has to make do with worse material,
#: walk further and work longer. A depleted resource does not become
#: cheaper or more expensive: it blocks the action altogether.
CRITICAL_COST_MULTIPLIER = 2


@dataclass(frozen=True)
class ResourceSpec:
    """The definition of a provision of the town.

    A spec is **data**: it says how much the town has, what each action
    costs, when the stock runs low enough for the town to suffer, how much
    the town consumes on its own every day, and which actions the stock
    gates.

    The three provisions of Aldermere are designed against the arithmetic of
    the cycle (**480 ticks, 5 days**). The numbers below are the ones the
    shipped content uses, and the reasoning behind each of them is spelled
    out in the docstring of :func:`apply_daily_decay` and in the README of
    the repository.

    Attributes:
        id: Stable identifier of the resource, e.g. ``"RES_FOOD"``.
        label: Display name of the resource.
        initial: Amount the town starts the cycle with. Must be at least 0.
        per_action: Amount consumed by a single normal action. Must be at
            least 0.
        critical_at: Amount at or below which the town suffers. A resource
            is **critical** when its amount is *strictly below* this value,
            and **depleted** when its amount has reached 0.
        daily_decay: Amount the town consumes on its own when a day passes.
            Must be at least 0. The decay is applied when the clock crosses
            a day boundary, never per tick.
        blocks_actions: Kinds of action the resource gates. When the
            resource is depleted, an action of one of these kinds cannot be
            performed at all. When the resource is merely critical, such an
            action costs ``CRITICAL_COST_MULTIPLIER`` times its usual price.
    """

    id: str
    label: str
    initial: int
    per_action: int
    critical_at: int
    daily_decay: int = 0
    blocks_actions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate the boundaries of the spec.

        Raises:
            ValueError: If the identifiers are empty or a quantity is
                negative, or if ``critical_at`` is above ``initial``, or if
                ``blocks_actions`` holds a duplicated kind.
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
        if self.daily_decay < 0:
            raise ValueError(
                f"resource {self.id}: daily_decay must be >= 0, got {self.daily_decay}"
            )
        duplicated = _duplicated_kinds(self.blocks_actions)
        if duplicated:
            raise ValueError(f"resource {self.id}: duplicated blocked action kinds {duplicated}")
        for kind in self.blocks_actions:
            if not kind:
                raise ValueError(
                    f"resource {self.id}: a blocked action kind must be a non-empty string"
                )

    @property
    def cost(self) -> int:
        """Return the amount consumed by a single action.

        Returns:
            The per-action cost of the resource.
        """
        return self.per_action

    def blocks(self, kind: str) -> bool:
        """Check whether the resource gates an action of the given kind.

        Args:
            kind: Kind of action, e.g. ``"prepare_sample"``.

        Returns:
            ``True`` when the resource declares that kind in
            ``blocks_actions``.
        """
        return kind in self.blocks_actions


@dataclass(frozen=True)
class ResourceState:
    """The current amount of every provision of the town.

    The state is immutable: the amounts are held in a read-only mapping, and
    every operation returns a **new** state instead of mutating this one.

    Attributes:
        amounts: Amount of every resource, keyed by resource id. The mapping
            is a :class:`types.MappingProxyType`, so it cannot be changed
            from the outside.
        spent_today: Amount spent since the beginning of the current day,
            keyed by resource id. It exists so the HUD can show the shape of
            a day at a glance ("food 24 -> 18, -6 today"). It is reset when
            the clock crosses a day boundary, and it does not include the
            decay: the decay is the town eating on its own, not the player
            spending.
    """

    amounts: Mapping[str, int]
    spent_today: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Freeze the amounts so the state is genuinely immutable.

        Raises:
            TypeError: If the amounts are not a mapping of ints.
            ValueError: If an amount is negative.
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
        if not isinstance(self.spent_today, Mapping):
            raise TypeError(f"spent_today must be a mapping, got {type(self.spent_today).__name__}")
        for resource_id, amount in self.spent_today.items():
            if not isinstance(amount, int) or isinstance(amount, bool):
                raise TypeError(
                    f"resource {resource_id}: spent_today must be an int, "
                    f"got {type(amount).__name__}"
                )
            if amount < 0:
                raise ValueError(f"resource {resource_id}: spent_today must be >= 0, got {amount}")
        object.__setattr__(self, "amounts", MappingProxyType(dict(self.amounts)))
        object.__setattr__(self, "spent_today", MappingProxyType(dict(self.spent_today)))

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

    def spent_on(self, resource_id: str) -> int:
        """Return the amount spent on a resource since the day started.

        Args:
            resource_id: Identifier of the resource.

        Returns:
            The amount spent today, or ``0`` when the resource is not
            tracked or nothing was spent on it.
        """
        return self.spent_today.get(resource_id, 0)

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
        return dict(self.amounts) == dict(other.amounts) and dict(self.spent_today) == dict(
            other.spent_today
        )

    def __hash__(self) -> int:
        """Return a hash consistent with the content equality.

        Returns:
            The hash of the sorted amounts and of the sorted daily spending.
        """
        return hash((tuple(sorted(self.amounts.items())), tuple(sorted(self.spent_today.items()))))


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

    The daily spending starts empty: the cycle begins at the beginning of
    Day 1, so nothing has been spent yet.

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
    return ResourceState(amounts=MappingProxyType(amounts), spent_today=MappingProxyType({}))


def _duplicated_kinds(kinds: Sequence[str]) -> tuple[str, ...]:
    """Return the action kinds that appear more than once.

    Args:
        kinds: The kinds to inspect.

    Returns:
        The duplicated kinds, sorted and without duplicates.
    """
    seen: set[str] = set()
    duplicates: set[str] = set()
    for kind in kinds:
        if kind in seen:
            duplicates.add(kind)
        seen.add(kind)
    return tuple(sorted(duplicates))


def _cost_of(state: ResourceState, spec: ResourceSpec, kind: str | None) -> int:
    """Return the price of one action for a resource.

    The price depends on the state of the resource. A resource that is in
    crisis makes the actions it gates cost ``CRITICAL_COST_MULTIPLIER``
    times more: the town is short of everything and has to make do with
    worse material. A resource that gates nothing is always charged its
    plain price, however low its amount is.

    Args:
        state: Current state of the provisions.
        spec: Specification of the resource.
        kind: Kind of action the player wants to perform, or ``None`` when
            the kind is not known.

    Returns:
        The amount the action costs of that resource.
    """
    if kind is None or not spec.blocks(kind):
        return spec.per_action
    if state.is_critical(spec):
        return spec.per_action * CRITICAL_COST_MULTIPLIER
    return spec.per_action


def _is_blocked(state: ResourceState, spec: ResourceSpec, kind: str | None) -> bool:
    """Check whether a depleted resource blocks an action.

    A resource that reached zero cannot pay for anything any more. The
    actions it gates are therefore refused outright: the town cannot work
    without the material.

    Args:
        state: Current state of the provisions.
        spec: Specification of the resource.
        kind: Kind of action the player wants to perform, or ``None`` when
            the kind is not known.

    Returns:
        ``True`` when the action cannot be performed at all.
    """
    if kind is None or not spec.blocks(kind):
        return False
    return state.is_depleted(spec)


def can_afford(
    state: ResourceState,
    specs: Sequence[ResourceSpec],
    actions: int = 1,
    kind: str | None = None,
) -> bool:
    """Check whether the town can pay for a number of actions.

    When ``kind`` is given, the check accounts for the two extra rules of
    the system:

    * an action whose kind is gated by a **depleted** resource cannot be
      performed at all, whatever the other resources hold;
    * an action whose kind is gated by a **critical** resource costs
      ``CRITICAL_COST_MULTIPLIER`` times as much of that resource.

    With ``kind=None`` the function behaves exactly as it did before: every
    resource is charged its plain per-action price, and a resource the state
    does not track is charged as if it held nothing.

    Args:
        state: Current state of the provisions.
        specs: Specifications of the resources of the town.
        actions: Number of actions the player wants to perform. Must be a
            non-negative integer.
        kind: Kind of action the player wants to perform, e.g.
            ``"prepare_sample"``. ``None`` when the kind is not known.

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

    if kind is None:
        # The historical behaviour: every resource is charged its plain
        # per-action price, tracked or not.
        return all(state.amount(spec.id) >= spec.per_action * actions for spec in specs)

    for spec in specs:
        if not state.tracks(spec.id):
            # A resource the state does not track is *absent*, not empty:
            # the town never stocked it, so it cannot block an action and
            # it cannot be charged for one. This mirrors :func:`consume`,
            # which leaves an untracked resource untracked.
            continue
        if _is_blocked(state, spec, kind):
            return False
    return all(
        state.amount(spec.id) >= _cost_of(state, spec, kind) * actions
        for spec in specs
        if state.tracks(spec.id)
    )


def consume(
    state: ResourceState,
    specs: Sequence[ResourceSpec],
    actions: int = 1,
    kind: str | None = None,
) -> ResourceState:
    """Consume the provisions of a number of actions.

    The function is **pure**: it never mutates the state it receives, and it
    returns a brand new one. The amounts are clamped to zero, so a resource
    that cannot cover its cost ends up depleted rather than negative. A
    negative amount would mean the town owes provisions, which is not a
    state the simulation can represent.

    When ``kind`` is given, the price of the action follows the same two
    rules as :func:`can_afford`: a resource that gates the action and is in
    crisis is charged ``CRITICAL_COST_MULTIPLIER`` times its usual price.
    The amount actually spent is recorded in ``spent_today``, so the HUD can
    show how the day is going.

    Args:
        state: Current state of the provisions.
        specs: Specifications of the resources of the town.
        actions: Number of actions to pay for. Must be a non-negative
            integer.
        kind: Kind of action being paid for, e.g. ``"prepare_sample"``.
            ``None`` when the kind is not known.

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
    spent = dict(state.spent_today)
    for spec in specs:
        if spec.id not in amounts:
            # A resource the state does not track stays untracked: it was
            # never stocked, so there is nothing to spend and nothing to
            # clamp. Making it tracked with an amount of zero would turn an
            # absent resource into an exhausted one.
            continue
        cost = _cost_of(state, spec, kind) * actions
        remaining = amounts[spec.id] - cost
        amounts[spec.id] = max(0, remaining)
        if cost > 0:
            spent[spec.id] = spent.get(spec.id, 0) + cost
    return ResourceState(amounts=MappingProxyType(amounts), spent_today=MappingProxyType(spent))


def apply_daily_decay(
    state: ResourceState,
    specs: Sequence[ResourceSpec],
    days: int = 1,
) -> ResourceState:
    """Apply the decay the town suffers when days pass.

    The function is **pure**: it never mutates the state it receives, and it
    returns a brand new one. The amounts are clamped to zero, so a resource
    that cannot cover the decay ends up depleted rather than negative.

    The decay is the town eating and heating itself on its own. It is
    applied when the clock **crosses a day boundary**, never per tick: one
    crossing is one day, no matter how many ticks it took.

    The daily spending is **not** touched: the decay is the town eating, not
    the player spending, and the HUD reports the two separately.

    The shipped provisions are designed against the arithmetic of the cycle
    (**480 ticks, 5 days**), and every number below exists because of that
    arithmetic:

    ``RES_FOOD`` -- ``initial 24``, ``per_action 1``, ``critical_at 6``,
    ``daily_decay 2``.

        The mine is closed, so nothing enters the town and the town eats
        every day: ``24 - 4 * 2 = 16`` left after four day boundaries
        (ticks 96, 192, 288 and 384) and nothing at all by the end of the
        cycle. A player who acts 40 to 60 times spends 40 to 60 units, so
        the food is *low but never empty* for a careful player, and an
        explorer who wanders for 60 actions ends up with 24 spent and 8
        eaten, which is below the critical threshold of 6 only in the last
        days. The threshold of 6 is roughly two days of decay, so the
        player is warned before the town starts to starve.

    ``RES_MEDICINE`` -- ``initial 10``, ``per_action 1``, ``critical_at 3``,
    ``daily_decay 1``.

        The mine stores the only stock of the medicine and the only
        antitoxin, and the mine is closed, so the town treats what it has
        and loses a little every day. Ten units at one per action is ten
        treatments: enough to see the illness through, not enough to treat
        everybody. Below 3 the remaining doses cannot cover the sick, which
        is the point at which the cure path becomes a race.

    ``RES_FUEL`` -- ``initial 8``, ``per_action 1``, ``critical_at 2``,
    ``daily_decay 1``.

        The oil of the mine drives the calcination furnace where the
        vaccine sample is prepared and the gas lamp of the hospital where
        the sick are kept. It is not a generic expense: it is the resource
        that **enables a concrete action**, the ``"prepare_sample"`` one.
        Eight units is eight preparations, so the sample can be prepared
        twice over before the stores run dry, and below 2 the furnace
        cannot be kept alight.

    Args:
        state: Current state of the provisions.
        specs: Specifications of the resources of the town.
        days: Number of days that passed. Must be a non-negative integer.

    Returns:
        The state after the decay was applied.

    Raises:
        TypeError: If ``days`` is not an integer.
        ValueError: If ``days`` is negative.
    """
    if not isinstance(days, int) or isinstance(days, bool):
        raise TypeError(f"days must be an int, got {type(days).__name__}")
    if days < 0:
        raise ValueError(f"days must be >= 0, got {days}")

    amounts = dict(state.amounts)
    for spec in specs:
        if spec.id not in amounts:
            continue
        amounts[spec.id] = max(0, amounts[spec.id] - spec.daily_decay * days)
    return ResourceState(
        amounts=MappingProxyType(amounts),
        spent_today=MappingProxyType(dict(state.spent_today)),
    )


def reset_spent_today(state: ResourceState) -> ResourceState:
    """Clear the daily spending of a state.

    The function is **pure**: it never mutates the state it receives, and it
    returns a brand new one with the same amounts and an empty daily
    spending. The simulator calls it when the clock crosses a day boundary.

    Args:
        state: Current state of the provisions.

    Returns:
        The state with the daily spending cleared.
    """
    return ResourceState(
        amounts=MappingProxyType(dict(state.amounts)),
        spent_today=MappingProxyType({}),
    )


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
