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

Two more rules were added with the concrete resource system of the town:

* **The town eats every day.** A resource may declare a ``daily_decay``,
  which is applied when the clock crosses a day boundary and never per tick.
* **A crisis costs more, a shortage stops the work.** A *critical* resource
  doubles the price of the actions it gates; a *depleted* one refuses them
  outright.
"""

from __future__ import annotations

import pytest

from core.resources import (
    CRITICAL_COST_MULTIPLIER,
    ResourceSpec,
    ResourceState,
    apply_daily_decay,
    can_afford,
    consume,
    derive_crisis,
    empty_state,
    initial_state,
    reset_spent_today,
)

FOOD = ResourceSpec(id="RES_FOOD", label="Food", initial=3, per_action=1, critical_at=1)
MEDICINE = ResourceSpec(id="RES_MEDICINE", label="Medicine", initial=2, per_action=2, critical_at=2)

#: A resource that gates one concrete action.
FUEL = ResourceSpec(
    id="RES_FUEL",
    label="Fuel",
    initial=4,
    per_action=1,
    critical_at=2,
    daily_decay=1,
    blocks_actions=("prepare_sample",),
)


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
    assert consumed.amounts == state.amounts
    assert consumed.spent_today == state.spent_today


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


# ----------------------------------------------------------------------
# Daily decay
# ----------------------------------------------------------------------


def test_a_spec_defaults_to_no_daily_decay() -> None:
    """A resource that does not decay says so."""
    assert FOOD.daily_decay == 0
    assert FOOD.blocks_actions == ()


def test_the_daily_decay_lowers_the_amount() -> None:
    """The town eats on its own when a day passes."""
    state = initial_state([FUEL])
    decayed = apply_daily_decay(state, [FUEL], days=1)
    assert decayed.amount("RES_FUEL") == 3


def test_the_daily_decay_applies_once_per_day() -> None:
    """Two days of decay cost two days of provisions."""
    state = initial_state([FUEL])
    decayed = apply_daily_decay(state, [FUEL], days=2)
    assert decayed.amount("RES_FUEL") == 2


def test_the_daily_decay_clamps_to_zero() -> None:
    """A decay larger than the stock leaves nothing, never a negative."""
    state = initial_state([FUEL])
    decayed = apply_daily_decay(state, [FUEL], days=99)
    assert decayed.amount("RES_FUEL") == 0
    assert decayed.amount("RES_FUEL") >= 0


def test_the_daily_decay_does_not_mutate_the_original_state() -> None:
    """The decay is pure: the original state is left untouched."""
    state = initial_state([FUEL])
    snapshot = dict(state.amounts)
    apply_daily_decay(state, [FUEL], days=1)
    assert dict(state.amounts) == snapshot


def test_the_daily_decay_leaves_an_untracked_resource_untracked() -> None:
    """Spending an absent resource does not turn it into an empty one."""
    decayed = apply_daily_decay(empty_state(), [FUEL])
    assert decayed.tracks("RES_FUEL") is False


def test_the_daily_decay_rejects_a_negative_number_of_days() -> None:
    """The number of days must be a non-negative integer."""
    with pytest.raises(ValueError, match="days must be >= 0"):
        apply_daily_decay(initial_state([FUEL]), [FUEL], days=-1)


def test_the_daily_decay_rejects_a_non_integer_number_of_days() -> None:
    """The number of days must be an integer."""
    with pytest.raises(TypeError, match="days must be an int"):
        apply_daily_decay(initial_state([FUEL]), [FUEL], days=1.5)  # type: ignore[arg-type]


def test_zero_days_of_decay_change_nothing() -> None:
    """A day that did not pass costs nothing."""
    state = initial_state([FUEL])
    decayed = apply_daily_decay(state, [FUEL], days=0)
    assert decayed.amounts == state.amounts


def test_a_spec_rejects_a_negative_daily_decay() -> None:
    """The town cannot consume a negative amount."""
    with pytest.raises(ValueError, match="daily_decay must be >= 0"):
        ResourceSpec(
            id="RES_FUEL",
            label="Fuel",
            initial=4,
            per_action=1,
            critical_at=2,
            daily_decay=-1,
        )


def test_a_spec_rejects_duplicated_blocked_kinds() -> None:
    """A gated action kind must not be listed twice."""
    with pytest.raises(ValueError, match="duplicated blocked action kinds"):
        ResourceSpec(
            id="RES_FUEL",
            label="Fuel",
            initial=4,
            per_action=1,
            critical_at=2,
            blocks_actions=("prepare_sample", "prepare_sample"),
        )


def test_a_spec_rejects_an_empty_blocked_kind() -> None:
    """A gated action kind must name something."""
    with pytest.raises(ValueError, match="non-empty string"):
        ResourceSpec(
            id="RES_FUEL",
            label="Fuel",
            initial=4,
            per_action=1,
            critical_at=2,
            blocks_actions=("",),
        )


def test_a_spec_reports_whether_it_blocks_a_kind() -> None:
    """The spec knows the actions it gates."""
    assert FUEL.blocks("prepare_sample") is True
    assert FUEL.blocks("talk") is False


# ----------------------------------------------------------------------
# The critical multiplier
# ----------------------------------------------------------------------


def test_a_critical_resource_doubles_the_price_of_the_action_it_gates() -> None:
    """A resource in crisis makes the action it gates cost twice as much."""
    state = ResourceState(amounts={"RES_FUEL": 1})
    assert state.is_critical(FUEL) is True
    consumed = consume(state, [FUEL], kind="prepare_sample")
    assert consumed.amount("RES_FUEL") == 0
    assert consumed.spent_on("RES_FUEL") == 2


def test_a_critical_resource_does_not_double_the_price_of_other_actions() -> None:
    """The multiplier only applies to the actions the resource gates."""
    state = ResourceState(amounts={"RES_FUEL": 1})
    consumed = consume(state, [FUEL], kind="talk")
    assert consumed.amount("RES_FUEL") == 0
    assert consumed.spent_on("RES_FUEL") == 1


def test_a_healthy_resource_keeps_its_plain_price() -> None:
    """A resource above its threshold is charged its usual price."""
    state = ResourceState(amounts={"RES_FUEL": 3})
    assert state.is_critical(FUEL) is False
    consumed = consume(state, [FUEL], kind="prepare_sample")
    assert consumed.amount("RES_FUEL") == 2
    assert consumed.spent_on("RES_FUEL") == 1


def test_the_multiplier_is_the_documented_constant() -> None:
    """The multiplier is a named constant of the module."""
    assert CRITICAL_COST_MULTIPLIER == 2


def test_can_afford_accounts_for_the_critical_multiplier() -> None:
    """A stock that only covers the plain price cannot pay a crisis action."""
    state = ResourceState(amounts={"RES_FUEL": 1})
    assert can_afford(state, [FUEL], kind="talk") is True
    assert can_afford(state, [FUEL], kind="prepare_sample") is False


def test_can_afford_accepts_a_critical_stock_that_covers_the_multiplier() -> None:
    """Two units cover the doubled price of a crisis action."""
    state = ResourceState(amounts={"RES_FUEL": 2})
    assert can_afford(state, [FUEL], kind="prepare_sample") is True


def test_the_old_signature_of_can_afford_behaves_as_before() -> None:
    """Without a kind, the price is the plain per-action price."""
    state = ResourceState(amounts={"RES_FUEL": 1})
    assert can_afford(state, [FUEL]) is True
    assert can_afford(state, [FUEL], actions=1) is True


def test_the_old_signature_of_consume_behaves_as_before() -> None:
    """Without a kind, the consumption is the plain per-action cost."""
    state = ResourceState(amounts={"RES_FUEL": 1})
    consumed = consume(state, [FUEL])
    assert consumed.amount("RES_FUEL") == 0
    assert consumed.spent_on("RES_FUEL") == 1


# ----------------------------------------------------------------------
# The blocked actions
# ----------------------------------------------------------------------


def test_a_depleted_resource_blocks_the_action_it_gates() -> None:
    """The town cannot work without the material."""
    state = ResourceState(amounts={"RES_FUEL": 0})
    assert can_afford(state, [FUEL], kind="prepare_sample") is False


def test_a_depleted_resource_stops_every_action_it_pays_for() -> None:
    """A depleted resource cannot pay for any action at all."""
    state = ResourceState(amounts={"RES_FUEL": 0})
    assert can_afford(state, [FUEL], kind="talk") is False
    assert can_afford(state, [FOOD], kind="talk") is True


def test_a_depleted_resource_blocks_the_action_even_with_stock_to_spare() -> None:
    """One empty resource is enough to stop the action it gates."""
    state = ResourceState(amounts={"RES_FUEL": 0, "RES_FOOD": 9})
    assert can_afford(state, [FUEL, FOOD], kind="prepare_sample") is False


def test_an_untracked_resource_blocks_nothing() -> None:
    """A resource the town never stocked cannot stop anything."""
    assert can_afford(empty_state(), [FUEL], kind="prepare_sample") is True


# ----------------------------------------------------------------------
# The daily spending
# ----------------------------------------------------------------------


def test_the_initial_state_spends_nothing() -> None:
    """The cycle starts at the beginning of Day 1."""
    assert dict(initial_state([FOOD]).spent_today) == {}


def test_consuming_records_the_daily_spending() -> None:
    """The HUD needs to know how much the day cost."""
    state = initial_state([FOOD])
    consumed = consume(state, [FOOD])
    assert consumed.spent_on("RES_FOOD") == 1
    assert consumed.spent_today["RES_FOOD"] == 1


def test_the_daily_spending_accumulates_over_the_day() -> None:
    """Every action of the day adds to the same counter."""
    state = initial_state([FOOD])
    consumed = consume(consume(state, [FOOD]), [FOOD])
    assert consumed.spent_on("RES_FOOD") == 2


def test_the_daily_spending_is_reset_at_the_day_boundary() -> None:
    """The counter reports the spending of the current day only."""
    state = consume(initial_state([FOOD]), [FOOD])
    assert state.spent_on("RES_FOOD") == 1
    assert reset_spent_today(state).spent_on("RES_FOOD") == 0


def test_resetting_the_daily_spending_keeps_the_amounts() -> None:
    """The reset clears the counter, not the stores."""
    state = consume(initial_state([FOOD]), [FOOD])
    reset = reset_spent_today(state)
    assert reset.amount("RES_FOOD") == state.amount("RES_FOOD")
    assert dict(reset.spent_today) == {}


def test_resetting_the_daily_spending_does_not_mutate_the_original_state() -> None:
    """The reset is pure."""
    state = consume(initial_state([FOOD]), [FOOD])
    reset_spent_today(state)
    assert state.spent_on("RES_FOOD") == 1


def test_the_daily_decay_does_not_count_as_daily_spending() -> None:
    """The town eating is not the player spending."""
    state = initial_state([FUEL])
    decayed = apply_daily_decay(state, [FUEL], days=1)
    assert decayed.spent_on("RES_FUEL") == 0


def test_two_states_with_the_same_spending_are_equal() -> None:
    """The equality covers the daily spending too."""
    first = consume(initial_state([FOOD]), [FOOD])
    second = consume(initial_state([FOOD]), [FOOD])
    assert first == second
    assert hash(first) == hash(second)


def test_two_states_with_different_spending_are_not_equal() -> None:
    """A day of spending is part of the content of the state."""
    first = consume(initial_state([FOOD]), [FOOD])
    second = initial_state([FOOD])
    assert first != second


def test_the_state_rejects_a_non_mapping_spending() -> None:
    """The daily spending must be a mapping."""
    with pytest.raises(TypeError, match="spent_today must be a mapping"):
        ResourceState(amounts={"RES_FOOD": 3}, spent_today=[("RES_FOOD", 1)])  # type: ignore[arg-type]


def test_the_state_rejects_a_non_integer_spending() -> None:
    """Every amount spent must be an integer."""
    with pytest.raises(TypeError, match="spent_today must be an int"):
        ResourceState(amounts={"RES_FOOD": 3}, spent_today={"RES_FOOD": 1.5})  # type: ignore[dict-item]


def test_the_state_rejects_a_negative_spending() -> None:
    """The town cannot have spent less than nothing."""
    with pytest.raises(ValueError, match="spent_today must be >= 0"):
        ResourceState(amounts={"RES_FOOD": 3}, spent_today={"RES_FOOD": -1})
