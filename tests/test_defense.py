from __future__ import annotations

import pytest
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.attention import BaseView
from bot.awareness import AwarenessModel
from bot.body.engine import Engine, GrantStatus
from bot.ego.planners import Command, Domain, core_army, defense
from bot.ego.strategy import StrategyModel

from .fakes import MAIN, NATURAL, attention, unit


def zergling(tag: int, x: float, y: float):
    return unit(tag, UnitTypeId.ZERGLING, x, y, power=0.9, attack_air=False)


def mutalisk(tag: int, x: float, y: float):
    return unit(tag, UnitTypeId.MUTALISK, x, y, power=1.2, flying=True)


def marauder(tag: int, x: float, y: float):
    return unit(tag, UnitTypeId.MARAUDER, x, y, power=1.6, attack_air=False)


ARMY = (
    unit(1, UnitTypeId.MARINE, 20, 20),
    unit(2, UnitTypeId.MARINE, 22, 20),
    marauder(3, 14, 11),
    unit(4, UnitTypeId.MARINE, 40, 40),
)
THIRD = BaseView(base_id="base:20:36", position=Point2((20.5, 36.5)), is_main=False)


def plan(frame, *, strategy_model=None, awareness_model=None):
    awareness = (awareness_model or AwarenessModel()).infer(frame)
    strategy = (strategy_model or StrategyModel()).decide(frame, awareness)
    return (
        awareness,
        strategy,
        defense.plan(frame, awareness, strategy) + core_army.plan(frame, awareness, strategy),
    )


def defenses(proposals):
    return [item for item in proposals if item.owner == defense.OWNER]


def test_no_pressure_proposes_no_defense() -> None:
    _, _, proposals = plan(attention(own_units=ARMY))

    assert [item.owner for item in proposals] == [core_army.OWNER]


def test_one_scv_in_reach_of_three_bases_is_one_incident_answered_once() -> None:
    # Trace of 788af1d at 500 s: one SCV in reach of three bases drew three
    # proposals, and a Marine, a Marauder and a Siege Tank each left the army.
    frame = attention(
        own_units=(
            unit(1, UnitTypeId.MARINE, 28, 14),
            marauder(2, 12, 12),
            unit(3, UnitTypeId.SIEGETANK, 20, 34, power=2.8, attack_air=False),
        ),
        bases=(MAIN, THIRD, NATURAL),
        enemy_units=(unit(90, UnitTypeId.SCV, 22, 20, power=0.58, attack_air=False, worker=True),),
    )
    awareness, strategy, proposals = plan(frame)

    assert all(base.pressure > 0.0 for base in awareness.bases)
    (incident,) = awareness.incidents
    assert incident.affected_bases == (MAIN.base_id, THIRD.base_id, NATURAL.base_id)
    (answer,) = defenses(proposals)
    assert answer.demand_id == incident.incident_id == "incident:90"
    assert answer.command is Command.ATTACK
    assert answer.target == incident.center
    assert answer.must_attack is Domain.GROUND
    assert answer.minimum_power == pytest.approx(defense.COVER_MARGIN * 0.58)
    assert answer.priority == incident.threat * (0.5 + 0.5 * strategy.defense)

    result = Engine().allocate(frame, proposals)

    # The Marine on the spot covers it; nothing is pulled from the other bases.
    grant = next(item for item in result.grants if item.proposal is answer)
    assert (grant.tags, grant.status, grant.reason) == ((1,), GrantStatus.FULL, "minimum_power_met")
    assert dict(result.owners) == {1: answer.proposal_id, 2: core_army.OWNER, 3: core_army.OWNER}


def test_an_air_attack_is_answered_only_by_units_that_shoot_up() -> None:
    frame = attention(
        own_units=(marauder(3, 15, 11), unit(4, x=25, y=20), unit(5, x=26, y=20)),
        enemy_units=(mutalisk(90, 15, 10.5),),
    )
    _, _, proposals = plan(frame)

    (air,) = defenses(proposals)
    assert air.reason == "air_attackers_in_reach"
    assert air.must_attack is Domain.AIR
    result = Engine().allocate(frame, proposals)

    # The Marauder beside the Mutalisk is no cover against it.
    assert result.grants[0].proposal is air
    assert result.grants[0].tags == (4, 5)
    assert result.owner_of(3) == core_army.OWNER


def test_a_mixed_attack_splits_one_budget_between_air_and_ground() -> None:
    frame = attention(own_units=ARMY, enemy_units=(zergling(90, 14, 10.5), mutalisk(91, 16, 11)))
    awareness, _, proposals = plan(frame)

    (incident,) = awareness.incidents
    air, ground = defenses(proposals)
    assert (air.must_attack, ground.must_attack) == (Domain.AIR, Domain.GROUND)
    assert air.demand_id == ground.demand_id == incident.incident_id
    assert air.minimum_power == pytest.approx(defense.COVER_MARGIN * 1.2)
    assert ground.minimum_power == pytest.approx(defense.COVER_MARGIN * 0.9)
    assert air.minimum_power + ground.minimum_power == pytest.approx(
        defense.COVER_MARGIN * incident.power
    )

    result = Engine().allocate(frame, proposals)

    air_grant, ground_grant, _ = result.grants
    assert (air_grant.proposal, ground_grant.proposal) == (air, ground)
    assert (air_grant.tags, ground_grant.tags) == ((1, 2), (3,))
    assert air_grant.status is ground_grant.status is GrantStatus.FULL
    granted = [tag for grant in result.grants for tag in grant.tags]
    assert len(granted) == len(set(granted))


def test_an_attack_beyond_the_army_is_partial_and_one_nobody_can_shoot_is_rejected() -> None:
    swarm = tuple(zergling(90 + index, 14, 10.5 + 0.5 * index) for index in range(6))
    frame = attention(own_units=ARMY, enemy_units=swarm)
    _, _, proposals = plan(frame)

    ground = Engine().allocate(frame, proposals).grants[0]
    assert ground.proposal.owner == defense.OWNER
    assert (ground.status, ground.reason) == (GrantStatus.PARTIAL, "insufficient_power")
    assert ground.tags == (1, 2, 3, 4)
    assert ground.power == pytest.approx(4.6)
    assert ground.power < ground.proposal.minimum_power

    grounded = attention(own_units=(marauder(3, 14, 11),), enemy_units=(mutalisk(91, 15, 11),))
    _, _, proposals = plan(grounded)
    result = Engine().allocate(grounded, proposals)

    air = result.grants[0]
    assert air.proposal.owner == defense.OWNER
    assert (air.tags, air.status, air.reason) == ((), GrantStatus.REJECTED, "no_eligible_units")
    assert result.owner_of(3) == core_army.OWNER


def test_defense_outranks_the_core_army_and_hands_units_back_when_the_attack_ends() -> None:
    awareness_model, strategy_model, engine = AwarenessModel(), StrategyModel(), Engine()
    attack = attention(time=0.0, own_units=ARMY, enemy_units=(zergling(90, 14, 10.5),))
    _, _, proposals = plan(attack, awareness_model=awareness_model, strategy_model=strategy_model)

    during = engine.allocate(attack, proposals)
    owners = dict(during.owners)
    assert owners[3] == "defense:incident:90:ground"
    assert set(owners) == {1, 2, 3, 4}

    over = attention(time=1.0, own_units=ARMY, dead_tags=(90,))
    _, _, proposals = plan(over, awareness_model=awareness_model, strategy_model=strategy_model)
    after = engine.allocate(over, proposals)

    assert set(dict(after.owners).values()) == {core_army.OWNER}
    assert set(dict(after.owners)) == {1, 2, 3, 4}
    assert after.released == ()
