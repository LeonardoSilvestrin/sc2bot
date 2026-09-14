from __future__ import annotations

from dataclasses import replace

import pytest
from ares.behaviors.combat import CombatManeuver
from ares.behaviors.combat.individual import AMove, PathUnitToTarget, SiegeTankDecision
from ares.behaviors.macro import ExpansionController, MacroPlan, Mining
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.behaviors import economy
from bot.engine import Command, EconomyPlan, Engine, Proposal, command_army, rank, run_economy

from .fakes import FakeBot, FakeUnit, attention, unit

TARGET = Point2((30.0, 30.0))


def proposal(
    proposal_id: str,
    priority: float,
    *,
    owner: str | None = None,
    count=None,
    unit_types=None,
    command=Command.ATTACK,
    target=TARGET,
) -> Proposal:
    return Proposal(
        proposal_id=proposal_id,
        owner=owner or proposal_id.split(":")[0],
        priority=priority,
        command=command,
        target=target,
        reason="test",
        count=count,
        unit_types=unit_types,
    )


def test_proposals_rank_by_priority_then_owner_then_id() -> None:
    proposals = (
        proposal("core_army", 0.0),
        proposal("defense:b", 0.5),
        proposal("defense:a", 0.5),
        proposal("alpha:z", 0.5),
        proposal("defense:c", 0.9),
    )

    assert [item.proposal_id for item in rank(proposals)] == [
        "defense:c",
        "alpha:z",
        "defense:a",
        "defense:b",
        "core_army",
    ]


def test_each_unit_is_granted_once_nearest_first_and_the_fallback_takes_the_rest() -> None:
    army = (unit(1, x=29, y=30), unit(2, x=20, y=30), unit(3, x=25, y=30), unit(4, x=10, y=10))
    frame = attention(
        own_units=(
            *army,
            unit(9, UnitTypeId.SCV, 30, 30, worker=True),
            unit(8, UnitTypeId.MULE, 30, 30, worker=True),
            unit(7, UnitTypeId.BARRACKS, 30, 30, power=0.0, structure=True),
        )
    )

    result = Engine().allocate(
        frame, (proposal("core_army", 0.0), proposal("defense:main", 0.4, count=2))
    )

    defense, core = result.grants
    assert defense.proposal.proposal_id == "defense:main"
    assert defense.tags == (1, 3)
    assert core.tags == (2, 4)
    assert result.unassigned == ()
    assert dict(result.owners) == {
        1: "defense:main",
        2: "core_army",
        3: "defense:main",
        4: "core_army",
    }


def test_unit_types_restrict_who_a_proposal_can_take() -> None:
    frame = attention(own_units=(unit(1, x=30, y=30), unit(2, UnitTypeId.MARAUDER, 30, 30)))

    result = Engine().allocate(
        frame,
        (
            proposal("defense:air", 1.0, unit_types=frozenset({UnitTypeId.MARINE})),
            proposal("core_army", 0.0),
        ),
    )

    assert result.grants[0].tags == (1,)
    assert result.grants[1].tags == (2,)


def test_a_grant_keeps_its_units_while_they_move() -> None:
    engine = Engine()
    engine.allocate(
        attention(own_units=(unit(1, x=29, y=30), unit(2, x=10, y=10))),
        (proposal("defense:main", 1.0, count=1),),
    )

    moved = attention(own_units=(unit(1, x=15, y=15), unit(2, x=28, y=30)))
    result = engine.allocate(moved, (proposal("defense:main", 1.0, count=1),))

    assert result.grants[0].tags == (1,)


def test_a_duplicate_proposal_id_is_a_programming_error() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        Engine().allocate(attention(), (proposal("defense:a", 1.0), proposal("defense:a", 0.5)))


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

    command_army(bot, result)

    maneuvers = [behavior for behavior in bot.registered if isinstance(behavior, CombatManeuver)]
    by_tag = {maneuver.micros[-1].unit.tag: maneuver.micros for maneuver in maneuvers}
    assert sorted(by_tag) == [1, 2]
    assert [type(micro) for micro in by_tag[1]] == [AMove]
    assert [type(micro) for micro in by_tag[2]] == [SiegeTankDecision, PathUnitToTarget]


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
    run_economy(bot, plan)
    assert [type(behavior) for behavior in bot.registered] == [Mining]

    bot = FakeBot()
    run_economy(bot, replace(plan, active=True, workers=44, gas=2, bases=2, expand=True))
    mining, macro = bot.registered
    assert isinstance(mining, Mining) and isinstance(macro, MacroPlan)
    assert any(isinstance(item, ExpansionController) for item in macro.macros)
