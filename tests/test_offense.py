from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pytest
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.attention import unit_power, unit_view
from bot.awareness import AwarenessModel
from bot.body.engine import Engine, GrantStatus
from bot.ego.planners import Command, Domain
from bot.ego.planners.military import army_fallback, defense
from bot.ego.planners.military.defense import DefensePlanner
from bot.ego.planners.military.offense import (
    ENEMY_START,
    FLYING_STRUCTURE,
    KNOWN_BASE,
    KNOWN_STRUCTURE,
    OWNER,
    SEARCH_TARGET,
    OffenseConfig,
    OffensePlanner,
    Stage,
)
from bot.ego.strategy import Objective, StrategyModel

from .fakes import MAIN, MAP, FakeUnit, attention, unit

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

    def __init__(self, config: OffenseConfig | None = None, *, engine: bool = False) -> None:
        self.awareness = AwarenessModel()
        self.strategy = StrategyModel()
        self.defense = DefensePlanner()
        self.offense = OffensePlanner(config)
        # With an Engine, the offense is told what it was granted last frame.
        self.engine = Engine() if engine else None
        self.feedback = None

    def step(
        self,
        time,
        *,
        army=(),
        enemies=(),
        structures=(),
        dead=(),
        supply=100.0,
        visibility=None,
    ):
        frame = replace(
            attention(
                time=time,
                own_units=army,
                enemy_units=enemies,
                enemy_structures=structures,
                dead_tags=dead,
                visibility=visibility,
            ),
            supply_used=supply,
        )
        awareness = self.awareness.infer(frame)
        strategy = self.strategy.decide(frame, awareness)
        if self.engine is None:
            return frame, awareness, strategy, self.offense.plan(frame, awareness, strategy)
        plan = self.offense.plan(frame, awareness, strategy, self.feedback)
        self.feedback = self.engine.allocate(
            frame,
            self.defense.plan(frame, awareness, strategy, self.feedback)
            + army_fallback.ArmyFallbackPlanner().plan(frame, awareness, strategy)
            + plan.proposals,
        )
        return frame, awareness, strategy, plan


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
    assert switch > 0
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
        DefensePlanner().plan(frame, awareness, strategy)
        + army_fallback.ArmyFallbackPlanner().plan(frame, awareness, strategy)
        + plan.proposals
    )

    result = Engine().allocate(frame, proposals)

    assert (strategy.objective, plan.stage) == (Objective.BUILD_ADVANTAGE, Stage.ADVANCE)
    guard, attack, hold = result.grants
    assert [grant.proposal.owner for grant in result.grants] == [
        defense.OWNER,
        OWNER,
        army_fallback.OWNER,
    ]
    assert (guard.status, guard.tags) == (GrantStatus.FULL, (100, 101))
    assert guard.power >= guard.proposal.minimum_power
    assert set(attack.tags) == {marine.tag for marine in army} - set(guard.tags)
    assert (attack.status, attack.reason) == (GrantStatus.FULL, "every_free_unit")
    assert (hold.tags, hold.status, hold.reason) == (
        (),
        GrantStatus.REJECTED,
        "eligible_units_taken",
    )


# Far from the rally and out of reach of the main: a fight away from home.
FRONT = Point2((40.0, 40.0))
ROACHES_AT = Point2((44.0, 44.0))


def roaches(count: int, *, first_tag: int = 500):
    return tuple(
        unit(
            first_tag + index,
            UnitTypeId.ROACH,
            ROACHES_AT.x,
            ROACHES_AT.y,
            power=ROACH_POWER,
            attack_air=False,
        )
        for index in range(count)
    )


def advancing_game(**config) -> tuple[Game, tuple]:
    """A maxed army of 30 Marines that has just advanced, granted to the offense,
    and the same army at the front."""

    game = Game(OffenseConfig(**config), engine=True)
    army = marines(30)
    game.step(700.0, army=army, supply=MAXED)
    *_, plan = game.step(700.5, army=army, supply=MAXED)
    assert plan.stage is Stage.ADVANCE
    return game, marines(30, FRONT.x, FRONT.y)


def test_a_squad_engages_a_weaker_force_and_advances_again_once_it_is_gone() -> None:
    game, army = advancing_game()
    enemies = roaches(10)

    *_, engaged = game.step(701.0, army=army, enemies=enemies, supply=MAXED)

    assert (engaged.stage, engaged.previous, engaged.reason) == (
        Stage.ENGAGE,
        Stage.ADVANCE,
        "favorable_fight",
    )
    fight = engaged.fight
    assert (fight.center, fight.own_power, fight.enemy_power) == (FRONT, 30.0, 15.0)
    assert fight.share == pytest.approx(30.0 / 45.0)
    (proposal,) = engaged.proposals
    assert (proposal.command, proposal.target, proposal.reason) == (
        Command.ATTACK,
        ROACHES_AT,
        "engage_near_enemies",
    )
    assert dict(proposal.inputs)["local_share"] == pytest.approx(30.0 / 45.0)

    dead = tuple(roach.tag for roach in enemies)
    plans = [
        game.step(701.0 + 0.5 * step, army=army, dead=dead, supply=MAXED)[-1]
        for step in range(1, 8)
    ]

    assert [(plan.stage, plan.blocked_by) for plan in plans[:5]] == [
        (Stage.ENGAGE, "clearing")
    ] * 5
    assert (plans[5].stage, plans[5].reason, plans[5].since) == (
        Stage.ADVANCE,
        "fight_won",
        701.0 + CONFIG.clear_after,
    )
    assert plans[5].fight.share is None
    assert plans[6].proposals[0].reason == "advance_on_enemy_start"


def test_an_unfavorable_contact_retreats_regroups_and_advances_again() -> None:
    game, army = advancing_game()

    *_, retreating = game.step(701.0, army=army, enemies=roaches(30), supply=MAXED)

    assert (retreating.stage, retreating.reason) == (Stage.RETREAT, "unfavorable_fight")
    assert retreating.fight.share == pytest.approx(30.0 / 75.0)
    (proposal,) = retreating.proposals
    assert (proposal.proposal_id, proposal.command, proposal.target, proposal.reason) == (
        OWNER,
        Command.RETREAT,
        RALLY,
        "retreat_to_rally",
    )
    assert (retreating.target, retreating.target_tag, retreating.target_kind) == (
        RALLY,
        None,
        None,
    )

    *_, still = game.step(701.5, army=army, supply=MAXED)
    *_, regrouped = game.step(702.0, army=marines(30), supply=MAXED)
    home = [
        game.step(702.0 + 0.5 * step, army=marines(30), supply=MAXED)[-1]
        for step in range(1, 21)
    ]

    assert (still.stage, still.blocked_by, still.proposals[0].command) == (
        Stage.RETREAT,
        "retreating",
        Command.RETREAT,
    )
    assert (regrouped.stage, regrouped.reason, regrouped.proposals) == (
        Stage.REGROUP,
        "army_regrouped",
        (),
    )
    assert all(
        (plan.stage, plan.blocked_by) == (Stage.REGROUP, "regroup_dwell") for plan in home[:19]
    )
    assert (home[19].stage, home[19].reason, home[19].since) == (
        Stage.ADVANCE,
        "regrouped",
        702.0 + CONFIG.regroup_dwell,
    )
    assert home[19].committed_power == 30.0


def test_an_engaged_squad_holds_inside_the_band_and_retreats_below_it_after_the_dwell() -> None:
    game, army = advancing_game()
    counts = [10, 30, 34, 40, 40, 40, 40, 40, 40]
    plans = [
        game.step(701.0 + 0.5 * step, army=army, enemies=roaches(count), supply=MAXED)[-1]
        for step, count in enumerate(counts)
    ]

    shares = [plan.fight.share for plan in plans]
    assert shares[1:4] == [
        pytest.approx(30.0 / 75.0),
        pytest.approx(30.0 / 81.0),
        pytest.approx(30.0 / 90.0),
    ]
    assert CONFIG.retreat_share < shares[2] < shares[1] < CONFIG.engage_share
    assert shares[3] < CONFIG.retreat_share
    assert [(plan.stage, plan.blocked_by) for plan in plans[:8]] == [
        (Stage.ENGAGE, None),
        (Stage.ENGAGE, "fight_holds"),
        (Stage.ENGAGE, "fight_holds"),
        *[(Stage.ENGAGE, "engage_dwell")] * 5,
    ]
    assert (plans[8].stage, plans[8].reason, plans[8].since) == (
        Stage.RETREAT,
        "fight_lost",
        701.0 + CONFIG.engage_dwell,
    )


def test_a_regrouped_army_without_an_advantage_stands_down() -> None:
    game, army = advancing_game(regroup_dwell=0.0)
    game.step(701.0, army=army, enemies=roaches(30), supply=MAXED)
    game.step(701.5, army=marines(30), supply=MAXED)
    *_, strategy, idle = game.step(702.0, army=marines(30), supply=100.0)
    *_, after = game.step(702.5, army=marines(30), supply=100.0)

    assert strategy.army_share < 0.5
    assert (idle.stage, idle.previous, idle.reason, idle.committed_power) == (
        Stage.IDLE,
        Stage.REGROUP,
        "advantage_lost",
        0.0,
    )
    assert after.blocked_by == "cooling_down"


def test_a_fight_the_squad_already_holds_is_no_reason_to_leave_the_target() -> None:
    # bench/all 000, 871-966 s: engaged with 0.95 of the power near, the army
    # chased 2 Marines of enemy across the map instead of attacking the base.
    game, army = advancing_game()
    base = structure(900, UnitTypeId.HATCHERY, 53.5, 53.5)
    # 30 against 2 roaches: 30 / 33 = 0.909.
    *_, advancing = game.step(
        701.0, army=army, enemies=roaches(2), structures=(base,), supply=MAXED
    )

    assert advancing.fight.share == pytest.approx(30.0 / 33.0)
    assert advancing.fight.share >= CONFIG.won_share
    assert (advancing.stage, advancing.target, advancing.proposals[0].reason) == (
        Stage.ADVANCE,
        base.position,
        "advance_on_known_base",
    )
    assert dict(advancing.inputs)["contested"] == 0.0

    # Engaged, a fight that becomes one-sided counts as won after clear_after.
    game, army = advancing_game()
    game.step(701.0, army=army, enemies=roaches(10), supply=MAXED)
    dead = tuple(range(502, 510))
    plans = [
        game.step(701.0 + 0.5 * step, army=army, enemies=roaches(2), dead=dead, supply=MAXED)[-1]
        for step in range(1, 8)
    ]
    assert [plan.blocked_by for plan in plans[:5]] == ["clearing"] * 5
    assert (plans[5].stage, plans[5].reason) == (Stage.ADVANCE, "fight_won")
    assert plans[0].target == MAP.enemy_start


def test_the_local_fight_is_judged_at_the_squads_core() -> None:
    # bench/all2 000, 777 s and 1131 s: with reinforcements strung out from home,
    # the power-weighted centre fell where no unit stood, and one enemy there
    # meant a share of 0 and a retreat.
    game, army = advancing_game()
    trickle = tuple(
        unit(700 + index, x=FRONT.x - 20.0 * (index + 1), y=FRONT.y) for index in (0, 1)
    )
    squad = army + trickle
    near_edge = unit(
        800, UnitTypeId.ROACH, FRONT.x + CONFIG.engage_radius, FRONT.y, power=ROACH_POWER
    )
    beyond = unit(801, UnitTypeId.ROACH, FRONT.x, FRONT.y + CONFIG.engage_radius + 0.5)
    drone = unit(802, UnitTypeId.DRONE, FRONT.x, FRONT.y, power=0.4, worker=True)
    # Where the old centre would have been: between the front and the trickle.
    between = unit(803, UnitTypeId.ROACH, FRONT.x - 20.0, FRONT.y, power=ROACH_POWER)
    # The trickle joins the squad once the Engine granted it.
    game.step(701.0, army=squad, supply=MAXED)

    *_, plan = game.step(
        701.5, army=squad, enemies=(near_edge, beyond, drone, between), supply=MAXED
    )

    fight = plan.fight
    assert fight.center == FRONT
    assert fight.own_power == 30.0
    assert fight.enemy_power == ROACH_POWER
    assert fight.enemy_center == near_edge.position
    assert plan.stage is Stage.ADVANCE


NATURAL_SPOT = MAP.expansions[1]
ENEMY_START_SPOT = MAP.enemy_start


def vision(*points: Point2) -> np.ndarray:
    grid = np.zeros((64, 64), dtype=np.uint8)
    for point in points:
        grid[int(point.y), int(point.x)] = 2
    return grid


def advanced(game: Game, army=None) -> None:
    army = marines(30) if army is None else army
    game.step(700.0, army=army, supply=MAXED)
    *_, plan = game.step(700.5, army=army, supply=MAXED)
    assert plan.stage is Stage.ADVANCE


def test_an_empty_enemy_start_turns_the_advance_into_a_search_of_the_stale_expansions() -> None:
    game = Game()
    advanced(game)

    *_, going = game.step(701.0, army=marines(30), supply=MAXED)
    *_, searching = game.step(
        701.5, army=marines(30), supply=MAXED, visibility=vision(ENEMY_START_SPOT)
    )

    assert (going.stage, going.target, going.target_kind) == (
        Stage.ADVANCE,
        ENEMY_START_SPOT,
        ENEMY_START,
    )
    assert dict(going.inputs)["start_cleared"] == 0.0
    assert (searching.stage, searching.previous, searching.reason) == (
        Stage.SEARCH,
        Stage.ADVANCE,
        "enemy_start_empty",
    )
    # Our main is not searched and the enemy start was just seen.
    (proposal,) = searching.proposals
    assert (proposal.command, proposal.target, proposal.reason) == (
        Command.ATTACK,
        NATURAL_SPOT,
        "search_expansion",
    )
    assert (searching.target_kind, searching.target_tag) == (SEARCH_TARGET, None)

    # Not yet in vision: the target holds.
    *_, holding = game.step(702.0, army=marines(30), supply=MAXED)
    # In vision: every place was seen within search_memory, so the one out of
    # vision the longest -- the enemy start -- comes next.
    *_, next_place = game.step(
        702.5, army=marines(30), supply=MAXED, visibility=vision(NATURAL_SPOT)
    )

    assert holding.target == NATURAL_SPOT
    assert (next_place.stage, next_place.target) == (Stage.SEARCH, ENEMY_START_SPOT)

    # Once it is seen, the natural -- seen before the start was, this time -- is next.
    *_, back = game.step(
        703.0, army=marines(30), supply=MAXED, visibility=vision(ENEMY_START_SPOT)
    )
    assert back.target == NATURAL_SPOT


def test_a_structure_found_while_searching_is_advanced_on() -> None:
    game = Game()
    advanced(game)
    game.step(701.0, army=marines(30), supply=MAXED, visibility=vision(ENEMY_START_SPOT))
    hidden_base = structure(905, UnitTypeId.HATCHERY, 30.5, 40.5)

    *_, found = game.step(701.5, army=marines(30), structures=(hidden_base,), supply=MAXED)

    assert (found.stage, found.reason) == (Stage.ADVANCE, "structure_found")
    assert (found.target, found.target_tag, found.target_kind) == (
        hidden_base.position,
        905,
        KNOWN_BASE,
    )


def test_an_enemy_start_seen_long_ago_is_advanced_on_rather_than_searched() -> None:
    game = Game()
    game.step(600.0, army=marines(30), supply=100.0, visibility=vision(ENEMY_START_SPOT))
    game.step(700.0, army=marines(30), supply=MAXED)
    game.step(700.5, army=marines(30), supply=MAXED)

    *_, plan = game.step(701.0, army=marines(30), supply=MAXED)

    assert (plan.stage, plan.target_kind) == (Stage.ADVANCE, ENEMY_START)
    assert dict(plan.inputs)["start_cleared"] == 0.0


def test_a_flying_structure_is_attacked_last_and_only_by_units_that_shoot_up() -> None:
    lifted = unit(
        906, UnitTypeId.COMMANDCENTERFLYING, 60, 60, power=0.0, structure=True, flying=True
    )
    depot = structure(907, UnitTypeId.SUPPLYDEPOT, 50, 50)
    tank = unit(300, UnitTypeId.SIEGETANK, RALLY.x, RALLY.y, power=2.8, attack_air=False)
    army = marines(30) + (tank,)
    game = Game(engine=True)
    advanced(game, army)

    *_, ground_first = game.step(701.0, army=army, structures=(lifted, depot), supply=MAXED)
    *_, air_last = game.step(701.5, army=army, structures=(lifted,), dead=(907,), supply=MAXED)
    result = game.engine.allocate(
        replace(attention(time=702.0, own_units=army), supply_used=MAXED),
        air_last.proposals,
    )

    assert (ground_first.target_tag, ground_first.target_kind) == (907, KNOWN_STRUCTURE)
    assert ground_first.proposals[0].must_attack is None
    assert (air_last.target_tag, air_last.target_kind, air_last.stage) == (
        906,
        FLYING_STRUCTURE,
        Stage.ADVANCE,
    )
    (proposal,) = air_last.proposals
    assert (proposal.must_attack, proposal.reason) == (
        Domain.AIR,
        "advance_on_flying_structure",
    )
    (grant,) = result.grants
    assert 300 not in grant.tags
    assert len(grant.tags) == 30


def test_the_core_is_the_lowest_tag_among_equals() -> None:
    game = Game(engine=True)
    left = marines(10, 30.0, 40.0, first_tag=100)
    right = marines(10, 50.0, 40.0, first_tag=200)
    advanced(game, marines(20))
    game.step(701.0, army=left + right, supply=MAXED)

    *_, plan = game.step(701.5, army=left + right, supply=MAXED)

    assert (plan.fight.center, plan.fight.own_power) == (Point2((30.0, 40.0)), 10.0)


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
        {"engage_radius": 0.0},
        {"retreat_share": 0.6},
        {"engage_share": 1.1},
        {"retreat_share": -0.1},
        {"engage_dwell": -1.0},
        {"clear_after": -1.0},
        {"retreat_timeout": -1.0},
        {"regroup_dwell": -1.0},
        {"won_share": 0.4},
        {"won_share": 1.1},
        {"search_memory": -1.0},
    ],
)
def test_an_invalid_offense_config_is_rejected(changes: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        OffenseConfig(**changes)


TANK_POWER = 2.3


def strung_out() -> tuple:
    """The granted squad in two clumps 14 cells apart: the core falls in the
    back one, which holds as much power as the front one and the lower tag."""

    return marines(20, FRONT.x, FRONT.y) + marines(
        10, FRONT.x, FRONT.y + 14.0, first_tag=120
    )


def sieged(count: int, *, y: float, first_tag: int = 900) -> tuple:
    return tuple(
        unit(
            first_tag + index,
            UnitTypeId.SIEGETANKSIEGED,
            FRONT.x,
            y,
            power=TANK_POWER,
            attack_air=False,
        )
        for index in range(count)
    )


def test_the_enemy_on_the_front_of_the_group_is_in_the_fight() -> None:
    # bench/base3/007, 515-521 s: the core of a bio ball 25 cells long read
    # 6.8 of enemy power against six sieged Siege Tanks and two Thors standing
    # 18-29 cells off, engaged at a share of 0.88 and then called the fight
    # won with 0 of enemy power, while the squad fell from 62 of power to 27.
    game, _ = advancing_game()
    squad = strung_out()
    # 26 cells from the core, 12 from the front of the group.
    tanks = sieged(6, y=FRONT.y + 26.0)
    game.step(701.0, army=squad, enemies=tanks, supply=MAXED)

    *_, plan = game.step(701.5, army=squad, enemies=tanks, supply=MAXED)

    fight = plan.fight
    assert fight.center == FRONT
    assert fight.own_power == 30.0
    assert fight.enemy_power == pytest.approx(6 * TANK_POWER)
    assert fight.share == pytest.approx(30.0 / (30.0 + 6 * TANK_POWER))


def test_a_fight_is_not_won_while_the_enemy_shoots_the_front_of_the_group() -> None:
    # Measured from the core alone those tanks are no enemy at all, so the
    # squad kept advancing into them.
    game, _ = advancing_game()
    squad = strung_out()
    tanks = sieged(20, y=FRONT.y + 26.0)

    *_, plan = game.step(701.0, army=squad, enemies=tanks, supply=MAXED)

    assert plan.fight.enemy_power == pytest.approx(20 * TANK_POWER)
    assert plan.fight.share < CONFIG.engage_share
    assert (plan.stage, plan.reason) == (Stage.RETREAT, "unfavorable_fight")


def test_the_splash_of_a_tank_line_turns_the_advance_away() -> None:
    # bench/base3/007, 520.7 s: the squad advanced into the tank line with 42
    # of its own power against 36 of enemy power in sight -- a favourable
    # fight by the old price of a sieged tank -- and was down to 15 fourteen
    # seconds later. The tanks are priced here by the model itself.
    game, _ = advancing_game()
    squad = marines(30, FRONT.x, FRONT.y)
    tanks = tuple(
        unit_view(
            FakeUnit(900 + index, UnitTypeId.SIEGETANKSIEGED, FRONT.x, FRONT.y + 14.0,
                     dps=40.0 / 2.14, hit_points=175.0),
            lambda _: 3.0,
        )
        for index in range(8)
    )

    without_splash = 8 * unit_power(40.0 / 2.14, 175.0)
    assert 30.0 / (30.0 + without_splash) > CONFIG.engage_share

    *_, plan = game.step(701.0, army=squad, enemies=tanks, supply=MAXED)

    assert plan.fight.enemy_power == pytest.approx(without_splash * math.sqrt(2.5))
    assert plan.fight.share < CONFIG.engage_share
    assert (plan.stage, plan.reason) == (Stage.RETREAT, "unfavorable_fight")


def test_an_enemy_beyond_the_reach_of_the_whole_group_is_not_in_the_fight() -> None:
    game, _ = advancing_game()
    squad = strung_out()
    # 16 cells past the front of the group, 30 past the core.
    tanks = sieged(20, y=FRONT.y + 14.0 + CONFIG.engage_radius + 0.5)

    *_, plan = game.step(701.0, army=squad, enemies=tanks, supply=MAXED)

    assert plan.fight.enemy_power == 0.0
    assert plan.stage is Stage.ADVANCE
