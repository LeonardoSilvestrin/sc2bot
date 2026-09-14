from __future__ import annotations

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId

from bot.behaviors import structure_control
from bot.engine import StructurePlan, run_structures

from .fakes import FakeBot, FakeUnit, attention, unit


def depot(tag: int, x: float = 20.0, y: float = 20.0, *, lowered=False, ready=True):
    type_id = UnitTypeId.SUPPLYDEPOTLOWERED if lowered else UnitTypeId.SUPPLYDEPOT
    return unit(tag, type_id, x, y, power=0.0, structure=True, ready=ready)


def zergling(tag: int, x: float, y: float):
    return unit(tag, UnitTypeId.ZERGLING, x, y, attack_air=False)


def test_a_raised_depot_goes_down_with_no_enemy_near() -> None:
    plan = structure_control.plan(attention(own_structures=(depot(1),)))

    assert plan.lower == (1,)
    assert plan.reason == "no_enemy_near"


def test_a_ground_enemy_near_keeps_only_that_depot_up() -> None:
    frame = attention(
        own_structures=(depot(1, 20, 20), depot(2, 40, 40)),
        enemy_units=(zergling(90, 24, 20),),
    )

    plan = structure_control.plan(frame)

    assert plan.lower == (2,)
    assert plan.reason == "enemy_near"


def test_flying_and_distant_enemies_do_not_keep_a_depot_up() -> None:
    frame = attention(
        own_structures=(depot(1, 20, 20),),
        enemy_units=(
            unit(90, UnitTypeId.OVERLORD, 21, 20, power=0.0, flying=True),
            zergling(91, 20 + structure_control.ENEMY_NEAR + 0.5, 20),
        ),
    )

    assert structure_control.plan(frame).lower == (1,)


def test_lowered_and_unfinished_depots_are_left_alone() -> None:
    frame = attention(own_structures=(depot(1, lowered=True), depot(2, ready=False)))

    plan = structure_control.plan(frame)

    assert plan.lower == ()
    assert plan.reason == "no_raised_depots"


def test_the_engine_lowers_only_the_planned_depots() -> None:
    bot = FakeBot()
    bot.structures = [
        FakeUnit(1, UnitTypeId.SUPPLYDEPOT, 20, 20, dps=0.0, structure=True),
        FakeUnit(2, UnitTypeId.SUPPLYDEPOT, 40, 40, dps=0.0, structure=True),
    ]

    run_structures(bot, StructurePlan(lower=(1,), reason="test"))

    assert bot.structures[0].commands == [AbilityId.MORPH_SUPPLYDEPOT_LOWER]
    assert bot.structures[1].commands == []
