from __future__ import annotations

import pytest
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId

from bot.body.behaviors import structure_control as structure_behavior
from bot.ego.planners import StructurePlan
from bot.ego.planners.control.structure_control import StructureConfig, StructureControl

from .fakes import FakeBot, FakeUnit, attention, unit

REACH = StructureConfig().raise_reach
LOWER_AFTER = StructureConfig().lower_after


def depot(tag: int, x: float = 20.0, y: float = 20.0, *, lowered=False, ready=True):
    type_id = UnitTypeId.SUPPLYDEPOTLOWERED if lowered else UnitTypeId.SUPPLYDEPOT
    return unit(tag, type_id, x, y, power=0.0, structure=True, ready=ready)


def zergling(tag: int, x: float, y: float):
    return unit(tag, UnitTypeId.ZERGLING, x, y, attack_air=False)


def test_a_raised_depot_goes_down_with_no_enemy_near() -> None:
    plan = StructureControl().plan(attention(own_structures=(depot(1),)))

    assert (plan.lower, plan.raise_, plan.reason) == ((1,), (), "no_enemy_near")


def test_a_lowered_depot_rises_when_a_ground_enemy_comes_within_reach() -> None:
    # Only raised depots used to be planned, so a lowered one never rose again.
    frame = attention(
        own_structures=(depot(1, 20, 20, lowered=True), depot(2, 40, 40, lowered=True)),
        enemy_units=(zergling(90, 20 + REACH, 20),),
    )

    plan = StructureControl().plan(frame)

    assert (plan.lower, plan.raise_, plan.reason) == ((), (1,), "enemy_near")
    inputs = dict(plan.inputs)
    assert (inputs["depots"], inputs["lowered"], inputs["enemy_near"]) == (2.0, 2.0, 1.0)
    assert inputs["nearest_ground_enemy"] == pytest.approx(REACH)


def test_a_raised_depot_near_a_ground_enemy_stays_up() -> None:
    frame = attention(own_structures=(depot(1),), enemy_units=(zergling(90, 24, 20),))

    plan = StructureControl().plan(frame)

    assert (plan.lower, plan.raise_, plan.reason) == ((), (), "enemy_near")


def test_flying_and_distant_enemies_do_not_raise_a_depot() -> None:
    frame = attention(
        own_structures=(depot(1, 20, 20, lowered=True),),
        enemy_units=(
            unit(90, UnitTypeId.OVERLORD, 20, 20, power=0.0, flying=True),
            zergling(91, 20 + REACH + 0.5, 20),
        ),
    )

    plan = StructureControl().plan(frame)

    assert (plan.lower, plan.raise_, plan.reason) == ((), (), "no_enemy_near")


def test_a_depot_goes_down_lower_after_seconds_after_the_enemy_left() -> None:
    control = StructureControl()
    near = attention(
        time=10.0, own_structures=(depot(1, lowered=True),), enemy_units=(zergling(90, 22, 20),)
    )
    assert control.plan(near).raise_ == (1,)

    held = control.plan(attention(time=10.0 + LOWER_AFTER - 0.1, own_structures=(depot(1),)))
    cleared = control.plan(attention(time=10.0 + LOWER_AFTER, own_structures=(depot(1),)))

    assert (held.lower, held.reason) == ((), "enemy_recently_near")
    assert dict(held.inputs)["recently_near"] == 1.0
    assert (cleared.lower, cleared.reason) == ((1,), "no_enemy_near")


def test_an_enemy_pacing_across_the_edge_of_reach_does_not_toggle_the_depot() -> None:
    control = StructureControl()
    lowered = True
    orders: list[tuple[float, str]] = []
    # Frames every 0.25 s for 20 s. Until 10 s the Zergling is inside reach for
    # 0.5 s and outside for 0.5 s, last inside at 9.25 s; then it is gone.
    for index in range(81):
        now = index * 0.25
        pacing = now < 10.0
        inside = int(now / 0.5) % 2 == 0
        x = 20 + REACH + (-1.0 if inside else 1.0)
        frame = attention(
            time=now,
            own_structures=(depot(1, lowered=lowered),),
            enemy_units=(zergling(90, x, 20),) if pacing else (),
        )
        plan = control.plan(frame)
        if plan.raise_:
            orders.append((now, "raise"))
            lowered = False
        if plan.lower:
            orders.append((now, "lower"))
            lowered = True

    assert orders == [(0.0, "raise"), (9.25 + LOWER_AFTER, "lower")]


def test_raising_counts_our_ground_units_it_pushes_off_the_depot() -> None:
    frame = attention(
        own_units=(
            unit(5, x=20.5, y=20),
            unit(6, x=23, y=20),
            unit(7, UnitTypeId.MEDIVAC, 20, 20, flying=True),
        ),
        own_structures=(depot(1, lowered=True),),
        enemy_units=(zergling(90, 25, 20),),
    )

    plan = StructureControl().plan(frame)

    assert plan.raise_ == (1,)
    assert dict(plan.inputs)["friendly_on_raising"] == 1.0


def test_unfinished_depots_are_left_alone() -> None:
    frame = attention(
        own_structures=(depot(1, ready=False),), enemy_units=(zergling(90, 21, 20),)
    )

    plan = StructureControl().plan(frame)

    assert (plan.lower, plan.raise_, plan.reason) == ((), (), "no_depots")


@pytest.mark.parametrize("values", [{"raise_reach": 0.0}, {"lower_after": -1.0}])
def test_the_config_rejects_impossible_values(values) -> None:
    with pytest.raises(ValueError):
        StructureConfig(**values)


def test_the_behavior_orders_only_the_planned_depots() -> None:
    bot = FakeBot()
    bot.structures = [
        FakeUnit(1, UnitTypeId.SUPPLYDEPOT, 20, 20, dps=0.0, structure=True),
        FakeUnit(2, UnitTypeId.SUPPLYDEPOTLOWERED, 30, 30, dps=0.0, structure=True),
        FakeUnit(3, UnitTypeId.SUPPLYDEPOT, 40, 40, dps=0.0, structure=True),
    ]

    structure_behavior.execute(bot, StructurePlan(lower=(1,), raise_=(2,), reason="test"))

    assert [structure.commands for structure in bot.structures] == [
        [AbilityId.MORPH_SUPPLYDEPOT_LOWER],
        [AbilityId.MORPH_SUPPLYDEPOT_RAISE],
        [],
    ]
