from __future__ import annotations

from dataclasses import replace

from ares.behaviors.combat import CombatManeuver
from ares.behaviors.combat.individual import AMove, PathUnitToTarget, SiegeTankDecision
from ares.behaviors.macro import ExpansionController, MacroPlan, Mining
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.body import behaviors
from bot.body.behaviors import economy as economy_behavior
from bot.body.engine import Engine
from bot.ego.planners import Command, EconomyPlan, economy

from .fakes import FakeBot, FakeUnit, attention, proposal, unit


def maneuvers(bot) -> dict[int, list]:
    return {
        behavior.micros[-1].unit.tag: behavior.micros
        for behavior in bot.registered
        if isinstance(behavior, CombatManeuver)
    }


def test_commands_go_only_to_granted_units() -> None:
    bot = FakeBot()
    bot.units = [
        FakeUnit(1, UnitTypeId.MARINE, 30, 30),
        FakeUnit(2, UnitTypeId.SIEGETANK, 10, 10, dps=20, hit_points=175),
        FakeUnit(3, UnitTypeId.MARINE, 12, 12),
    ]
    frame = attention(
        own_units=(unit(1, x=30, y=30), unit(2, UnitTypeId.SIEGETANK, 10, 10), unit(3, x=12, y=12))
    )
    result = Engine().allocate(
        frame,
        (
            proposal("defense:main", 1.0, count=1),
            proposal("core_army", 0.0, command=Command.HOLD, target=Point2((20, 20))),
        ),
    )
    bot.units = bot.units[:2]  # unit 3 died before execution

    behaviors.command_units(bot, result)

    by_tag = maneuvers(bot)
    assert sorted(by_tag) == [1, 2]
    assert [type(micro) for micro in by_tag[1]] == [AMove]
    assert [type(micro) for micro in by_tag[2]] == [SiegeTankDecision, PathUnitToTarget]


def test_a_tank_stays_sieged_only_while_holding_and_a_holder_fights_what_comes() -> None:
    bot = FakeBot()
    tank = FakeUnit(2, UnitTypeId.SIEGETANK, 10, 10, dps=20, hit_points=175)
    marine = FakeUnit(1, UnitTypeId.MARINE, 30, 30)
    bot.enemy_units = [FakeUnit(90, UnitTypeId.ZERGLING, 32, 30, hit_points=35.0)]
    target = Point2((20, 20))

    behaviors.BY_COMMAND[Command.HOLD](
        bot, [tank, marine], proposal("core_army", 0.0, command=Command.HOLD, target=target)
    )
    held = maneuvers(bot)
    bot.registered = []
    behaviors.BY_COMMAND[Command.ATTACK](bot, [tank], proposal("defense:main", 1.0))
    attacking = maneuvers(bot)

    assert held[2][0].stay_sieged_near_target
    assert isinstance(held[2][1], PathUnitToTarget)
    assert [type(micro) for micro in held[1]] == [AMove]
    assert not attacking[2][0].stay_sieged_near_target
    assert isinstance(attacking[2][1], AMove)


def test_the_economy_runs_mining_always_and_macro_only_after_the_opening() -> None:
    plan = EconomyPlan(
        active=False,
        workers=22,
        gas=1,
        bases=1,
        expand=False,
        freeflow=False,
        composition=economy.COMPOSITION,
        reason="opening_runs",
    )
    bot = FakeBot()
    economy_behavior.execute(bot, plan)
    assert [type(behavior) for behavior in bot.registered] == [Mining]

    bot = FakeBot()
    economy_behavior.execute(
        bot, replace(plan, active=True, workers=44, gas=2, bases=2, expand=True)
    )
    mining, macro = bot.registered
    assert isinstance(mining, Mining) and isinstance(macro, MacroPlan)
    assert any(isinstance(item, ExpansionController) for item in macro.macros)
