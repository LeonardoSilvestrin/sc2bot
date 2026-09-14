from __future__ import annotations

import math

from sc2.ids.unit_typeid import UnitTypeId

from bot.awareness import AwarenessModel
from bot.body.engine import Engine
from bot.ego.planners import Command, core_army, defense
from bot.ego.strategy import StrategyModel

from .fakes import MAIN, NATURAL, attention, unit


def zergling(tag: int, x: float, y: float):
    return unit(tag, UnitTypeId.ZERGLING, x, y, power=0.9, attack_air=False)


def mutalisk(tag: int, x: float, y: float):
    return unit(tag, UnitTypeId.MUTALISK, x, y, power=1.2, flying=True)


ARMY = (
    unit(1, UnitTypeId.MARINE, 20, 20),
    unit(2, UnitTypeId.MARINE, 22, 20),
    unit(3, UnitTypeId.MARAUDER, 14, 11, power=1.6, attack_air=False),
    unit(4, UnitTypeId.MARINE, 40, 40),
)


def plan(frame, *, strategy_model=None, awareness_model=None):
    awareness = (awareness_model or AwarenessModel()).infer(frame)
    strategy = (strategy_model or StrategyModel()).decide(frame, awareness)
    return (
        awareness,
        strategy,
        defense.plan(frame, awareness, strategy) + core_army.plan(frame, awareness, strategy),
    )


def test_no_pressure_proposes_no_defense() -> None:
    _, _, proposals = plan(attention(own_units=ARMY))

    assert [item.owner for item in proposals] == [core_army.OWNER]


def test_each_base_under_pressure_gets_its_own_ranked_proposal() -> None:
    frame = attention(
        own_units=ARMY,
        bases=(MAIN, NATURAL),
        enemy_units=(zergling(90, 14, 10.5), zergling(91, 30.5, 16), zergling(92, 31, 16)),
    )
    awareness, strategy, proposals = plan(frame)

    defenses = [item for item in proposals if item.owner == defense.OWNER]
    assert {item.proposal_id for item in defenses} == {"defense:base:10:10", "defense:base:30:12"}
    fallback = next(item for item in proposals if item.owner == core_army.OWNER)
    for item in defenses:
        base = awareness.base(item.proposal_id.removeprefix("defense:"))
        mean_power = sum(u.power for u in ARMY) / len(ARMY)
        assert item.priority > fallback.priority
        assert item.command is Command.ATTACK
        assert item.target == base.center
        assert item.count == max(1, math.ceil(1.5 * base.pressure / mean_power))
        assert item.priority == base.threat * (0.5 + 0.5 * strategy.defense)


def test_an_air_attack_only_asks_for_units_that_shoot_up() -> None:
    _, _, proposals = plan(attention(own_units=ARMY, enemy_units=(mutalisk(90, 15, 11),)))

    (air,) = [item for item in proposals if item.owner == defense.OWNER]
    assert air.reason == "air_attack_on_base"
    assert air.unit_types == frozenset({UnitTypeId.MARINE})


def test_defense_outranks_the_core_army_and_hands_units_back_when_the_attack_ends() -> None:
    awareness_model, strategy_model, engine = AwarenessModel(), StrategyModel(), Engine()
    attack = attention(time=0.0, own_units=ARMY, enemy_units=(zergling(90, 14, 10.5),))
    _, _, proposals = plan(attack, awareness_model=awareness_model, strategy_model=strategy_model)

    during = engine.allocate(attack, proposals)
    owners = dict(during.owners)
    assert owners[3] == "defense:base:10:10"
    assert set(owners) == {1, 2, 3, 4}

    over = attention(time=1.0, own_units=ARMY, dead_tags=(90,))
    _, _, proposals = plan(over, awareness_model=awareness_model, strategy_model=strategy_model)
    after = engine.allocate(over, proposals)

    assert set(dict(after.owners).values()) == {core_army.OWNER}
    assert set(dict(after.owners)) == {1, 2, 3, 4}
