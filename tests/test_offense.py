from __future__ import annotations

from dataclasses import replace

import pytest
from sc2.ids.unit_typeid import UnitTypeId

from bot.awareness import AwarenessModel
from bot.body.engine import Engine, GrantStatus
from bot.ego.planners import Command, core_army, defense
from bot.ego.planners.offense import (
    ENEMY_START,
    KNOWN_BASE,
    KNOWN_STRUCTURE,
    OWNER,
    Offense,
    OffenseConfig,
    Stage,
)
from bot.ego.strategy import Objective, StrategyModel

from .fakes import MAIN, MAP, attention, unit

CONFIG = OffenseConfig()
# With only the main and no threat, Strategy rallies at the main ramp.
RALLY = MAP.main_ramp
MAXED = CONFIG.maxed_supply


def marines(count: int, x: float = RALLY.x, y: float = RALLY.y, *, first_tag: int = 100):
    return tuple(unit(first_tag + index, x=x, y=y) for index in range(count))


def structure(tag: int, type_id: UnitTypeId, x: float, y: float):
    return unit(tag, type_id, x, y, power=0.0, structure=True)


def zerglings(count: int, *, first_tag: int = 600):
    x, y = MAIN.position
    return tuple(
        unit(first_tag + index, UnitTypeId.ZERGLING, x, y, power=0.9, attack_air=False)
        for index in range(count)
    )


class Game:
    """Awareness, Strategy and the offense, stepped over hand-built frames."""

    def __init__(self, config: OffenseConfig | None = None) -> None:
        self.awareness = AwarenessModel()
        self.strategy = StrategyModel()
        self.offense = Offense(config)

    def step(self, time, *, army=(), enemies=(), structures=(), dead=(), supply=100.0):
        frame = replace(
            attention(
                time=time,
                own_units=army,
                enemy_units=enemies,
                enemy_structures=structures,
                dead_tags=dead,
            ),
            supply_used=supply,
        )
        awareness = self.awareness.infer(frame)
        strategy = self.strategy.decide(frame, awareness)
        return frame, awareness, strategy, self.offense.plan(frame, awareness, strategy)


def test_a_maxed_army_commits_although_the_fog_would_never_show_an_advantage() -> None:
    # Trace 3769f04, 675-896 s: supply 190-200, no threat at home and 75-82
    # Marines of army, while 4,210 minerals grew to 11,970 and every unit held
    # the rally. By then the enemy planned against in the fog was already more
    # than a maxed army.
    hatchery = structure(900, UnitTypeId.HATCHERY, 53.5, 53.5)
    army = marines(30)

    held = Game()
    for step in range(20):
        *_, strategy, plan = held.step(
            700.0 + 0.5 * step, army=army, structures=(hatchery,), supply=MAXED - 1.0
        )
        assert (plan.stage, plan.blocked_by, plan.proposals) == (Stage.IDLE, "no_advantage", ())
    assert strategy.army_share < 0.5

    game = Game()
    *_, committed = game.step(700.0, army=army, structures=(hatchery,), supply=MAXED)
    *_, advancing = game.step(700.5, army=army, structures=(hatchery,), supply=MAXED)

    assert (committed.stage, committed.previous, committed.reason) == (
        Stage.ASSEMBLE,
        Stage.IDLE,
        "supply_maxed",
    )
    assert (committed.proposals, committed.blocked_by) == ((), None)
    assert committed.committed_power == pytest.approx(30.0)
    assert (advancing.stage, advancing.reason, advancing.since) == (
        Stage.ADVANCE,
        "army_assembled",
        700.5,
    )
    (proposal,) = advancing.proposals
    assert (proposal.owner, proposal.command, proposal.priority) == (OWNER, Command.ATTACK, 0.0)
    assert (proposal.count, proposal.unit_types, proposal.minimum_power) == (None, None, None)
    assert (proposal.target, proposal.reason) == (hatchery.position, "advance_on_known_base")
    assert (advancing.target_tag, advancing.target_kind) == (900, KNOWN_BASE)
    assert dict(proposal.inputs)["assembled_share"] == 1.0


ROACH_POWER = 1.5


@pytest.mark.parametrize(
    "time, army, roaches, stage, why, share",
    [
        # 15 Marines of army in sight and 18 expected by 300 s: 18 + 0.5 * 3
        # planned against, and 20 of our own is enough.
        (300.0, 20, 10, Stage.ASSEMBLE, "army_advantage", 20.0 / 39.5),
        (300.0, 19, 10, Stage.IDLE, "army_below_minimum", 19.0 / 38.5),
        # Nothing in sight at 600 s: 48 expected, all of it uncertain, 72 planned.
        (600.0, 30, 0, Stage.IDLE, "no_advantage", 30.0 / 102.0),
    ],
)
def test_the_army_commits_on_an_advantage_over_the_enemy_planned_against(
    time: float, army: int, roaches: int, stage: Stage, why: str, share: float
) -> None:
    enemies = tuple(
        unit(500 + index, UnitTypeId.ROACH, 50, 50, power=ROACH_POWER, attack_air=False)
        for index in range(roaches)
    )

    *_, strategy, plan = Game().step(time, army=marines(army), enemies=enemies, supply=60.0)

    assert plan.stage is stage
    assert (plan.reason if stage is Stage.ASSEMBLE else plan.blocked_by) == why
    assert strategy.army_share == pytest.approx(share)
    assert dict(plan.inputs)["army_share"] == strategy.army_share


def test_a_scattered_army_waits_to_assemble_but_not_past_the_timeout() -> None:
    # 24 of 30 Marines of power within reach of the rally, one exactly at its edge.
    edge = (unit(200, x=RALLY.x + CONFIG.assemble_radius, y=RALLY.y),)
    army = marines(23) + edge + marines(6, 40, 40, first_tag=300)
    game = Game()
    game.step(700.0, army=army, supply=MAXED)
    *_, assembled = game.step(700.5, army=army, supply=MAXED)

    assert (assembled.stage, assembled.reason) == (Stage.ADVANCE, "army_assembled")
    assert dict(assembled.inputs)["assembled_share"] == pytest.approx(CONFIG.assemble_share)

    army = marines(20) + marines(10, 40, 40, first_tag=300)
    game = Game()
    plans = [game.step(700.0 + 0.5 * step, army=army, supply=MAXED)[-1] for step in range(92)]
    advanced = next(index for index, plan in enumerate(plans) if plan.stage is Stage.ADVANCE)

    assert (plans[advanced].since, plans[advanced].reason) == (
        700.0 + CONFIG.assemble_timeout,
        "assemble_timed_out",
    )
    assert all(
        (plan.stage, plan.blocked_by) == (Stage.ASSEMBLE, "army_not_assembled")
        for plan in plans[1:advanced]
    )


def test_an_army_that_lost_half_its_power_calls_the_attack_off() -> None:
    army = marines(30)
    game = Game()
    game.step(700.0, army=army, supply=MAXED)
    game.step(700.5, army=army, supply=MAXED)

    *_, half = game.step(701.0, army=army[:15], supply=MAXED)
    *_, less = game.step(701.5, army=army[:14], supply=MAXED)
    *_, after = game.step(702.0, army=army[:14], supply=MAXED)

    assert (half.stage, half.committed_power) == (Stage.ADVANCE, 30.0)
    assert (less.stage, less.previous, less.reason) == (Stage.IDLE, Stage.ADVANCE, "army_depleted")
    assert (less.committed_power, less.proposals, less.target, less.target_tag) == (
        0.0,
        (),
        None,
        None,
    )
    assert after.blocked_by == "cooling_down"
    assert dict(after.inputs)["cooldown_left"] == pytest.approx(CONFIG.cooldown - 0.5)


def test_a_threat_at_home_calls_the_attack_off_and_the_next_waits_out_the_cooldown() -> None:
    army = marines(30)
    attackers = zerglings(8)
    game = Game()
    game.step(700.0, army=army, supply=MAXED)
    *_, advancing = game.step(700.5, army=army, supply=MAXED)
    *_, strategy, called_off = game.step(701.0, army=army, enemies=attackers, supply=MAXED)
    dead = tuple(attacker.tag for attacker in attackers)
    plans = [
        game.step(700.0 + 0.5 * step, army=army, dead=dead, supply=MAXED)[-1]
        for step in range(3, 70)
    ]

    assert advancing.stage is Stage.ADVANCE
    assert strategy.objective is Objective.STABILIZE
    assert (called_off.stage, called_off.reason, called_off.proposals) == (
        Stage.IDLE,
        "home_threatened",
        (),
    )
    committed = next(index for index, plan in enumerate(plans) if plan.stage is not Stage.IDLE)
    assert (plans[committed].stage, plans[committed].reason, plans[committed].since) == (
        Stage.ASSEMBLE,
        "supply_maxed",
        701.0 + CONFIG.cooldown,
    )
    # Home stays threatened while Strategy still stabilizes; then the cooldown runs out.
    waiting = [plan.blocked_by for plan in plans[:committed]]
    switch = waiting.index("cooling_down")
    assert 0 < switch
    assert waiting == ["home_threatened"] * switch + ["cooling_down"] * (len(waiting) - switch)


def test_the_target_holds_until_destroyed_and_a_known_base_outranks_other_structures() -> None:
    pool = structure(901, UnitTypeId.SPAWNINGPOOL, 30, 30)
    tumor = structure(902, UnitTypeId.CREEPTUMORBURROWED, 20, 20)
    far_base = structure(903, UnitTypeId.HATCHERY, 53.5, 53.5)
    near_base = structure(904, UnitTypeId.HATCHERY, 18, 50)
    army = marines(30)
    game = Game()

    def target(time: float, *structures, dead=()):
        *_, plan = game.step(time, army=army, structures=structures, dead=dead, supply=MAXED)
        return plan.target_tag, plan.target_kind, plan.target

    game.step(700.0, army=army, structures=(pool, tumor), supply=MAXED)

    assert target(700.5, pool, tumor) == (901, KNOWN_STRUCTURE, pool.position)
    assert target(701.0, pool, tumor, far_base) == (903, KNOWN_BASE, far_base.position)
    # A nearer base of the same kind does not pull the army around.
    assert target(701.5, pool, tumor, far_base, near_base)[0] == 903
    assert target(702.0, pool, tumor, near_base, dead=(903,))[0] == 904
    assert target(702.5, tumor, dead=(901, 903, 904)) == (None, ENEMY_START, MAP.enemy_start)


def test_defense_takes_what_an_incident_needs_and_the_offense_the_rest() -> None:
    army = marines(30)
    game = Game()
    game.step(700.0, army=army, supply=MAXED)
    game.step(700.5, army=army, supply=MAXED)
    frame, awareness, strategy, plan = game.step(
        701.0, army=army, enemies=zerglings(1), supply=MAXED
    )
    proposals = (
        defense.plan(frame, awareness, strategy)
        + core_army.plan(frame, awareness, strategy)
        + plan.proposals
    )

    result = Engine().allocate(frame, proposals)

    assert (strategy.objective, plan.stage) == (Objective.BUILD_ADVANTAGE, Stage.ADVANCE)
    guard, attack, hold = result.grants
    assert [grant.proposal.owner for grant in result.grants] == [
        defense.OWNER,
        OWNER,
        core_army.OWNER,
    ]
    assert (guard.status, guard.tags) == (GrantStatus.FULL, (100, 101))
    assert guard.power >= guard.proposal.minimum_power
    assert set(attack.tags) == {marine.tag for marine in army} - set(guard.tags)
    assert (attack.status, attack.reason) == (GrantStatus.FULL, "every_free_unit")
    assert (hold.tags, hold.status, hold.reason) == ((), GrantStatus.REJECTED, "eligible_units_taken")


def test_the_same_frames_plan_the_same_offense() -> None:
    def run():
        pool = structure(901, UnitTypeId.SPAWNINGPOOL, 30, 30)
        base = structure(903, UnitTypeId.HATCHERY, 53.5, 53.5)
        army = marines(30)
        game = Game()
        return [
            game.step(time, army=army[:count], structures=structures, dead=dead, supply=MAXED)[-1]
            for time, count, structures, dead in (
                (700.0, 30, (pool,), ()),
                (700.5, 30, (pool, base), ()),
                (701.0, 30, (pool,), (903,)),
                (701.5, 14, (pool,), ()),
                (732.0, 30, (pool,), ()),
            )
        ]

    assert run() == run()


@pytest.mark.parametrize(
    "changes",
    [
        {"minimum_power": 0.0},
        {"assemble_radius": -1.0},
        {"maxed_supply": 0.0},
        {"maxed_supply": 201.0},
        {"assemble_share": 0.0},
        {"assemble_share": 1.1},
        {"depleted_share": -0.1},
        {"depleted_share": 1.0},
        {"assemble_timeout": -1.0},
        {"cooldown": -1.0},
    ],
)
def test_an_invalid_offense_config_is_rejected(changes: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        OffenseConfig(**changes)
