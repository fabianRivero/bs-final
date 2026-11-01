"""Tests for the provisions of the town.

The resource system has three properties that the whole design leans on:

* **Purity.** Consuming resources never mutates the state it receives: it
  returns a brand new one. The world is a pure function of its inputs, and a
  save file is only reproducible if the resources behave the same way.
* **No negative amounts.** When the stock cannot cover a cost, the amount is
  clamped to zero and the resource counts as depleted. A negative amount
  would mean the town owes provisions, which is not a state the simulation
  can represent.
* **A crisis is a threshold, not a flag.** A resource is in crisis when its
  amount falls *strictly below* the ``critical_at`` threshold of its spec.
"""

from __future__ import annotations

import pytest

from core.resources import (
    ResourceSpec,
    ResourceState,
    can_afford,
    consume,
    derive_crisis,
    empty_state,
    initial_state,
)

FOOD = ResourceSpec(id="RES_FOOD", label="Food", initial=3, per_action=1, critical_at=1)
MEDICINE = ResourceSpec(id="RES_MEDICINE", label="Medicine", initial=2, per_action=2, critical_at=2)


def test_a_spec_exposes_its_cost() -> None:
    """The per-action cost is part of the specification."""
    assert FOOD.per_action == 1
    assert FOOD.cost == 1
    assert MEDICINE.cost == 2


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"id": "", "label": "X", "initial": 1, "per_action": 1, "critical_at": 0}, "non-empty id"),
        ({"id": "R", "label": "", "initial": 1, "per_action": 1, "critical_at": 0}, "non-empty"),
        ({"id": "R", "label": "X", "initial": -1, "per_action": 1, "critical_at": 0}, "initial"),
        ({"id": "R", "label": "X", "initial": 1, "per_action": -1, "critical_at": 0}, "per_action"),
        (
            {"id": "R", "label": "X", "initial": 1, "per_action": 1, "critical_at": -1},
            "critical_at",
        ),
        (
            {"id": "R", "label": "X", "initial": 1, "per_action": 1, "critical_at": 5},
            "critical_at",
        ),
    ],
)
def test_a_spec_rejects_invalid_boundaries(kwargs: dict[str, object], message: str) -> None:
    """A specification must describe a reachable, non-negative stock."""
    with pytest.raises(ValueError, match=message):
        ResourceSpec(**kwargs)  # type: ignore[arg-type]


def test_the_initial_state_holds_the_initial_amounts() -> None:
    """The cycle starts with every resource at its initial amount."""
    state = initial_state([FOOD, MEDICINE])
    assert state.amount("RES_FOOD") == 3
    assert state.amount("RES_MEDICINE") == 2
    assert dict(state.amounts) == {"RES_FOOD": 3, "RES_MEDICINE": 2}


def test_the_initial_state_rejects_duplicated_ids() -> None:
    """Two specs cannot share an id."""
    with pytest.raises(ValueError, match="duplicated resource id"):
        initial_state([FOOD, FOOD])


def test_the_empty_state_tracks_nothing() -> None:
    """A world without provisions has a neutral state."""
    state = empty_state()
    assert dict(state.amounts) == {}
    assert state.amount("RES_FOOD") == 0


def test_the_state_is_immutable() -> None:
    """The amounts of a state cannot be changed from the outside."""
    state = initial_state([FOOD])
    with pytest.raises(TypeError):
        state.amounts["RES_FOOD"] = 99  # type: ignore[index]


def test_the_state_rejects_a_non_mapping() -> None:
    """The amounts must be a mapping."""
    with pytest.raises(TypeError, match="amounts must be a mapping"):
        ResourceState(amounts=[("RES_FOOD", 3)])  # type: ignore[arg-type]


def test_the_state_rejects_a_non_integer_amount() -> None:
    """Every amount must be an integer."""
    with pytest.raises(TypeError, match="amount must be an int"):
        ResourceState(amounts={"RES_FOOD": 3.5})  # type: ignore[dict-item]


def test_the_state_rejects_a_negative_amount() -> None:
    """An amount is never negative."""
    with pytest.raises(ValueError, match="amount must be >= 0"):
        ResourceState(amounts={"RES_FOOD": -1})


def test_consuming_does_not_mutate_the_original_state() -> None:
    """Consumption is pure: the original state is left untouched."""
    state = initial_state([FOOD, MEDICINE])
    snapshot = dict(state.amounts)

    consumed = consume(state, [FOOD, MEDICINE])

    assert dict(state.amounts) == snapshot
    assert consumed is not state
    assert consumed.amount("RES_FOOD") == 2
    assert consumed.amount("RES_MEDICINE") == 0


def test_consuming_clamps_to_zero_instead_of_going_negative() -> None:
    """A resource that cannot cover its cost ends up depleted, not negative."""
    state = initial_state([FOOD])
    consumed = consume(state, [FOOD], actions=10)
    assert consumed.amount("RES_FOOD") == 0
    assert consumed.amount("RES_FOOD") >= 0


def test_consuming_depletes_a_resource() -> None:
    """A resource at zero is depleted."""
    state = initial_state([FOOD])
    consumed = consume(state, [FOOD], actions=3)
    assert consumed.is_depleted(FOOD) is True


def test_an_untracked_resource_is_absent_not_depleted() -> None:
    """A resource the town never stocked cannot have run out."""
    state = initial_state([FOOD])
    assert state.is_depleted(MEDICINE) is False
    assert state.tracks("RES_MEDICINE") is False


def test_consuming_an_untracked_resource_leaves_it_untracked() -> None:
    """Spending an absent resource does not turn it into an empty one."""
    consumed = consume(empty_state(), [FOOD])
    assert consumed.tracks("RES_FOOD") is False
    assert consumed.amount("RES_FOOD") == 0


def test_consuming_zero_actions_changes_nothing() -> None:
    """Paying for nothing costs nothing."""
    state = initial_state([FOOD])
    consumed = consume(state, [FOOD], actions=0)
    assert consumed == state


def test_consuming_rejects_a_negative_number_of_actions() -> None:
    """The number of actions must be a non-negative integer."""
    with pytest.raises(ValueError, match="actions must be >= 0"):
        consume(empty_state(), [FOOD], actions=-1)


def test_consuming_rejects_a_non_integer_number_of_actions() -> None:
    """The number of actions must be an integer."""
    with pytest.raises(TypeError, match="actions must be an int"):
        consume(empty_state(), [FOOD], actions="1")  # type: ignore[arg-type]


def test_can_afford_accepts_a_stock_that_covers_the_cost() -> None:
    """The town can pay for an action it has the stock for."""
    state = initial_state([FOOD, MEDICINE])
    assert can_afford(state, [FOOD, MEDICINE]) is True


def test_can_afford_rejects_a_stock_that_does_not_cover_the_cost() -> None:
    """The town cannot pay for an action it has no stock for."""
    state = initial_state([FOOD])
    assert can_afford(state, [FOOD, MEDICINE]) is False


def test_can_afford_takes_the_number_of_actions_into_account() -> None:
    """Two actions need twice the stock of one."""
    state = initial_state([FOOD])
    assert can_afford(state, [FOOD], actions=3) is True
    assert can_afford(state, [FOOD], actions=4) is False


def test_can_afford_rejects_invalid_numbers_of_actions() -> None:
    """The number of actions must be a non-negative integer."""
    state = initial_state([FOOD])
    with pytest.raises(ValueError, match="actions must be >= 0"):
        can_afford(state, [FOOD], actions=-1)
    with pytest.raises(TypeError, match="actions must be an int"):
        can_afford(state, [FOOD], actions=1.5)  # type: ignore[arg-type]


def test_a_resource_becomes_critical_below_its_threshold() -> None:
    """The threshold is exclusive: the amount must be strictly below it."""
    state = ResourceState(amounts={"RES_FOOD": 1})
    assert state.is_critical(FOOD) is False

    below = ResourceState(amounts={"RES_FOOD": 0})
    assert below.is_critical(FOOD) is True


def test_derive_crisis_lists_the_critical_resources() -> None:
    """The crisis holds the ids of the resources below their threshold."""
    state = ResourceState(amounts={"RES_FOOD": 0, "RES_MEDICINE": 2})
    assert derive_crisis(state, [FOOD, MEDICINE]) == ("RES_FOOD",)


def test_derive_crisis_is_sorted() -> None:
    """The crisis is stable and comparable."""
    state = ResourceState(amounts={"RES_MEDICINE": 0, "RES_FOOD": 0})
    assert derive_crisis(state, [MEDICINE, FOOD]) == ("RES_FOOD", "RES_MEDICINE")


def test_derive_crisis_is_empty_without_critical_resources() -> None:
    """A healthy town is not in crisis."""
    state = initial_state([FOOD, MEDICINE])
    assert derive_crisis(state, [FOOD, MEDICINE]) == ()


def test_critical_resources_matches_derive_crisis() -> None:
    """The two ways of asking for the crisis always agree."""
    state = ResourceState(amounts={"RES_FOOD": 0, "RES_MEDICINE": 2})
    assert state.critical_resources([FOOD, MEDICINE]) == derive_crisis(state, [FOOD, MEDICINE])


def test_an_untracked_resource_cannot_be_in_crisis() -> None:
    """A resource the town never stocked has no threshold to fall below."""
    state = empty_state()
    assert derive_crisis(state, [FOOD]) == ()
    assert state.is_critical(FOOD) is False


def test_two_states_with_the_same_amounts_are_equal() -> None:
    """The states compare by content, not by identity."""
    assert initial_state([FOOD]) == initial_state([FOOD])
    assert initial_state([FOOD]) != initial_state([FOOD, MEDICINE])


def test_a_state_is_not_equal_to_another_type() -> None:
    """Comparing a state with something else is not an error."""
    assert initial_state([FOOD]) != "RES_FOOD"


def test_a_state_is_hashable() -> None:
    """A state can be used as a key of a dictionary."""
    assert hash(initial_state([FOOD])) == hash(initial_state([FOOD]))
