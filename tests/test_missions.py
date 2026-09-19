"""Missions: who opens, ends and carries an operation, and what the Engine
may and may not do to one."""

from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType

import pytest
from ares.behaviors.combat import CombatManeuver
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.awareness import AwarenessModel
from bot.body.engine import Engine, GrantStatus
from bot.ego.missions import (
    CancelMode,
    Lifecycle,
    MissionFeedback,
    MissionStatus,
)
from bot.ego.planners import Command, Proposal
from bot.ego.planners.military import defense
from bot.ego.planners.military.defense import DefensePlanner
from bot.ego.planners.military.intel import SCOUT_AT_WORKERS, START_BY, IntelPlanner, ScoutMission
from bot.ego.planners.military.offense import OWNER, MainAttackMission, Stage
from bot.ego.planners.military.offense.missions.main_attack import OffenseContext
from bot.ego.strategy import Objective, Posture, StrategyModel
from bot.logs import Logs
from bot.main import Layers, play_frame

from .fakes import MAIN, MAP, FakeLogger, FakeUnit, attention, unit
from .test_frame_flow import build_bot
from .test_intel import SCOUTING, frame, scv
from .test_offense import (
    CONFIG,
    MAXED,
    RALLY,
    Game,
    advancing_game,
    marines,
    roaches,
    zerglings,
)

# --- the lifecycle every mission shares ---


def test_a_cancel_request_is_not_a_cancel_and_only_escalates() -> None:
    lifecycle = Lifecycle("offense:main_attack:1")

    lifecycle.request_cancel(CancelMode.GRACEFUL, "reduce", 10.0)
    assert (lifecycle.status, lifecycle.cancel.mode) == (MissionStatus.ACTIVE, CancelMode.GRACEFUL)
    # A graceful request never softens an immediate one ...
    lifecycle.request_cancel(CancelMode.IMMEDIATE, "home_threatened", 11.0)
    lifecycle.request_cancel(CancelMode.GRACEFUL, "later", 12.0)
    assert (lifecycle.cancel.mode, lifecycle.cancel.reason, lifecycle.cancel.time) == (
        CancelMode.IMMEDIATE,
        "home_threatened",
        11.0,
    )

    lifecycle.end(MissionStatus.CANCELLED)
    # ... and a terminal mission takes no request at all.
    lifecycle.request_cancel(CancelMode.GRACEFUL, "after", 13.0)
    assert (lifecycle.status, lifecycle.cancel.reason) == (
        MissionStatus.CANCELLED,
        "home_threatened",
    )


def test_only_a_requested_cancel_ends_a_mission_as_cancelled() -> None:
    with pytest.raises(ValueError):
        Lifecycle("m").end(MissionStatus.CANCELLED)
    with pytest.raises(ValueError):
        Lifecycle("m").end(MissionStatus.ACTIVE)


def test_one_mission_may_make_several_proposals_and_reads_all_their_grants() -> None:
    # A drop would ask for a transport and for its cargo: two proposals, one
    # mission, and the feedback of both.
    def part(proposal_id: str, *, count: int, types, mission_id: str | None) -> Proposal:
        return Proposal(
            proposal_id=proposal_id,
            owner="drop",
            priority=0.5,
            command=Command.ATTACK,
            target=Point2((40.0, 40.0)),
            reason="test",
            count=count,
            unit_types=frozenset(types),
            mission_id=mission_id,
        )

    medivac = unit(1, UnitTypeId.MEDIVAC, 20, 20, power=0.0, flying=True, attack_air=False)
    frame_ = attention(own_units=(medivac, *marines(6, 20, 20)))
    result = Engine().allocate(
        frame_,
        (
            part("drop:transport", count=1, types={UnitTypeId.MEDIVAC}, mission_id="drop:1"),
            part("drop:cargo", count=4, types={UnitTypeId.MARINE}, mission_id="drop:1"),
            part("other", count=2, types={UnitTypeId.MARINE}, mission_id="drop:2"),
        ),
    )

    feedback = MissionFeedback.of(result, "drop:1")

    assert [grant.proposal.proposal_id for grant in feedback.grants] == [
        "drop:cargo",
        "drop:transport",
    ]
    assert feedback.tags == {1, 100, 101, 102, 103}
    assert feedback.power == pytest.approx(4.0)
    assert MissionFeedback.of(None, "drop:1") == MissionFeedback()


# --- the offense: the planner opens and ends, the mission carries ---


def test_the_planner_opens_a_mission_that_keeps_its_identity_through_every_phase() -> None:
    game, army = advancing_game()
    mission = game.offense.mission
    assert isinstance(mission, MainAttackMission)
    enemies = roaches(10)

    *_, engaged = game.step(701.0, army=army, enemies=enemies, supply=MAXED)
    dead = tuple(roach.tag for roach in enemies)
    cleared = [
        game.step(701.0 + 0.5 * step, army=army, dead=dead, supply=MAXED)[-1]
        for step in range(1, 7)
    ]
    *_, retreating = game.step(704.5, army=army, enemies=roaches(30, first_tag=700), supply=MAXED)

    stages = [engaged.stage, cleared[-1].stage, retreating.stage]
    assert stages == [Stage.ENGAGE, Stage.ADVANCE, Stage.RETREAT]
    for plan in (engaged, cleared[-1], retreating):
        (proposal,) = plan.proposals
        # One proposal id for the whole operation, so the Engine keeps its units.
        assert (proposal.proposal_id, proposal.mission_id) == (OWNER, "offense:main_attack:1")
        assert (plan.mission_id, plan.mission_status) == (mission.mission_id, MissionStatus.ACTIVE)
    (view,) = game.offense.views()
    assert (view.status, view.phase, view.reason, view.owner, view.kind) == (
        MissionStatus.ACTIVE,
        "RETREAT",
        "unfavorable_fight",
        OWNER,
        "main_attack",
    )
    assert view.proposals == (OWNER,)
    assert view.granted_units == 30


def test_strategy_withdrawing_the_offense_blocks_admission_and_cancels_at_once() -> None:
    game = Game(engine=True)
    army = marines(30)
    *_, strategy, idle = game.step(700.0, army=army, enemies=zerglings(8), supply=MAXED)

    assert strategy.objective is Objective.STABILIZE
    assert (strategy.offense.posture, strategy.offense.reason) == (
        Posture.WITHDRAW,
        "home_threatened",
    )
    assert (idle.stage, idle.blocked_by, game.offense.mission) == (
        Stage.IDLE,
        "home_threatened",
        None,
    )

    game = Game(engine=True)
    game.step(700.0, army=army, supply=MAXED)
    *_, advancing = game.step(700.5, army=army, supply=MAXED)
    mission = game.offense.mission
    frame_, awareness, strategy, called_off = game.step(
        701.0, army=army, enemies=zerglings(8), supply=MAXED
    )

    assert advancing.stage is Stage.ADVANCE
    assert strategy.offense.posture is Posture.WITHDRAW
    # The planner asked; the mission ended itself, and proposes nothing more.
    assert (mission.status, mission.lifecycle.cancel.mode, mission.reason) == (
        MissionStatus.CANCELLED,
        CancelMode.IMMEDIATE,
        "home_threatened",
    )
    assert (called_off.stage, called_off.previous, called_off.proposals) == (
        Stage.IDLE,
        Stage.ADVANCE,
        (),
    )
    assert (called_off.mission_id, called_off.mission_status) == (
        mission.mission_id,
        MissionStatus.CANCELLED,
    )
    assert game.offense.mission is None
    # The same allocation hands every unit to Defense and ArmyFallback.
    owners = {grant.proposal.owner for grant in game.feedback.grants if grant.tags}
    assert OWNER not in owners
    assert set(dict(game.feedback.owners)) == {marine.tag for marine in army}


def test_every_end_starts_the_cooldown_and_the_next_mission_is_a_new_one() -> None:
    army = marines(30)
    game = Game()
    game.step(700.0, army=army, supply=MAXED)
    first = game.offense.mission.mission_id
    game.step(700.5, army=army, supply=MAXED)
    *_, failed = game.step(701.0, army=army[:14], supply=MAXED)
    plans = [game.step(701.0 + 0.5 * step, army=army, supply=MAXED)[-1] for step in range(1, 62)]

    assert (failed.mission_status, failed.reason) == (MissionStatus.FAILED, "army_depleted")
    reopened = next(plan for plan in plans if plan.stage is not Stage.IDLE)
    assert (reopened.stage, reopened.since) == (Stage.ASSEMBLE, 701.0 + CONFIG.cooldown)
    assert reopened.mission_id == "offense:main_attack:2" != first


def test_a_graceful_cancel_withdraws_until_the_army_is_back_then_ends() -> None:
    game, army = advancing_game()
    mission = game.offense.mission
    # The planner's call (a test stands in for it): let the attack walk home.
    mission.request_cancel(CancelMode.GRACEFUL, "reduce_offense", 701.0)

    *_, withdrawing = game.step(701.0, army=army, supply=MAXED)
    *_, walking = game.step(701.5, army=army, supply=MAXED)

    assert (withdrawing.stage, withdrawing.reason, mission.status) == (
        Stage.WITHDRAW,
        "reduce_offense",
        MissionStatus.ACTIVE,
    )
    for plan in (withdrawing, walking):
        (proposal,) = plan.proposals
        assert (proposal.proposal_id, proposal.command, proposal.target, proposal.reason) == (
            OWNER,
            Command.RETREAT,
            RALLY,
            "withdraw_to_rally",
        )
    assert walking.blocked_by == "withdrawing"
    # The Engine kept the units with the withdrawal.
    (grant,) = [g for g in game.feedback.grants if g.proposal.owner == OWNER]
    assert len(grant.tags) == 30

    *_, released = game.step(702.0, army=marines(30), supply=MAXED)

    assert (released.stage, released.previous, released.reason, released.proposals) == (
        Stage.IDLE,
        Stage.WITHDRAW,
        "withdrawn",
        (),
    )
    assert (mission.status, game.offense.mission) == (MissionStatus.CANCELLED, None)
    assert not [g for g in game.feedback.grants if g.proposal.owner == OWNER]


def test_a_withdrawal_ends_by_its_deadline_even_away_from_the_rally() -> None:
    game, army = advancing_game()
    mission = game.offense.mission
    mission.request_cancel(CancelMode.GRACEFUL, "reduce_offense", 701.0)
    plans = [
        game.step(701.0 + 0.5 * step, army=army, supply=MAXED)[-1]
        for step in range(int(CONFIG.retreat_timeout / 0.5) + 1)
    ]

    assert all(plan.stage is Stage.WITHDRAW for plan in plans[:-1])
    assert (plans[-1].stage, plans[-1].reason, plans[-1].since) == (
        Stage.IDLE,
        "withdraw_timed_out",
        701.0 + CONFIG.retreat_timeout,
    )
    assert mission.status is MissionStatus.CANCELLED


def test_a_graceful_cancel_of_a_mission_holding_nothing_ends_it_at_once() -> None:
    game = Game()
    army = marines(20) + marines(10, 40, 40, first_tag=300)
    game.step(700.0, army=army, supply=MAXED)
    mission = game.offense.mission
    mission.request_cancel(CancelMode.GRACEFUL, "reduce_offense", 700.5)

    *_, plan = game.step(700.5, army=army, supply=MAXED)

    assert (plan.previous, plan.stage, plan.reason, plan.proposals) == (
        Stage.ASSEMBLE,
        Stage.IDLE,
        "reduce_offense",
        (),
    )
    assert mission.status is MissionStatus.CANCELLED


def test_the_engine_takes_units_from_a_withdrawal_without_touching_its_lifecycle() -> None:
    game, army = advancing_game()
    mission = game.offense.mission
    mission.request_cancel(CancelMode.GRACEFUL, "reduce_offense", 701.0)
    game.step(701.0, army=army, supply=MAXED)

    # A raid at home: Defense outranks the withdrawal and takes what it needs.
    *_, strategy, raided = game.step(701.5, army=army, enemies=zerglings(1), supply=MAXED)

    assert strategy.offense.posture is Posture.PURSUE
    guard, withdrawal = (
        next(g for g in game.feedback.grants if g.proposal.owner == owner)
        for owner in (defense.OWNER, OWNER)
    )
    assert guard.status is GrantStatus.FULL and guard.tags
    assert set(withdrawal.tags) == {m.tag for m in army} - set(guard.tags)
    assert (mission.status, mission.phase, raided.stage) == (
        MissionStatus.ACTIVE,
        Stage.WITHDRAW,
        Stage.WITHDRAW,
    )

    # The mission reads the partial grant next frame and keeps withdrawing.
    *_, next_frame = game.step(702.0, army=army, enemies=zerglings(1), supply=MAXED)
    (view,) = game.offense.views()
    assert view.granted_units == len(withdrawal.tags)
    assert dict(next_frame.inputs)["squad_units"] == len(withdrawal.tags)
    assert (view.status, view.phase, view.cancel.mode) == (
        MissionStatus.ACTIVE,
        "WITHDRAW",
        CancelMode.GRACEFUL,
    )


def test_a_withdrawal_granted_nothing_keeps_proposing_until_its_deadline() -> None:
    game, army = advancing_game()
    mission = game.offense.mission
    mission.request_cancel(CancelMode.GRACEFUL, "reduce_offense", 701.0)
    game.step(701.0, army=army, supply=MAXED)
    # Every unit taken elsewhere: an empty grant is no reason to fail.
    game.feedback = replace(
        game.feedback,
        grants=tuple(
            replace(
                grant,
                tags=(),
                power=0.0,
                status=GrantStatus.REJECTED,
                reason="eligible_units_taken",
            )
            for grant in game.feedback.grants
        ),
    )

    *_, plan = game.step(701.5, army=army, supply=MAXED)

    assert (plan.stage, plan.blocked_by, mission.status) == (
        Stage.WITHDRAW,
        "withdrawing",
        MissionStatus.ACTIVE,
    )
    assert dict(plan.inputs)["squad_units"] == 0.0
    assert plan.proposals[0].command is Command.RETREAT


def test_an_immediate_cancel_escalates_a_withdrawal() -> None:
    game, army = advancing_game()
    mission = game.offense.mission
    mission.request_cancel(CancelMode.GRACEFUL, "reduce_offense", 701.0)
    game.step(701.0, army=army, supply=MAXED)

    *_, plan = game.step(701.5, army=army, enemies=zerglings(8), supply=MAXED)

    assert (plan.stage, plan.previous, plan.proposals) == (Stage.IDLE, Stage.WITHDRAW, ())
    assert (mission.status, mission.lifecycle.cancel.reason) == (
        MissionStatus.CANCELLED,
        "home_threatened",
    )


def test_a_terminal_mission_proposes_nothing() -> None:
    game, army = advancing_game()
    mission = game.offense.mission
    frame_, awareness, strategy, _ = game.step(701.0, army=army[:14], supply=MAXED)
    assert mission.status is MissionStatus.FAILED
    ctx = _context(game, frame_, awareness, strategy)

    step = mission.step(ctx, MissionFeedback.of(game.feedback, mission.mission_id))

    assert (step.status, step.proposals, step.target) == (MissionStatus.FAILED, (), None)

    scout = ScoutMission("intel:scout:1", (MAP.enemy_start,), 50.0)
    scout.request_cancel(CancelMode.IMMEDIATE, "too_late", 50.0)
    assert scout.step(frame(50.0), frozenset(), MissionFeedback()) == ()
    assert scout.step(frame(51.0), frozenset(), MissionFeedback()) == ()
    assert scout.status is MissionStatus.CANCELLED


def test_the_same_frames_open_carry_and_end_the_same_missions() -> None:
    def run():
        game, army = advancing_game()
        steps = []
        for time, units, enemies in (
            (701.0, army, roaches(10)),
            (701.5, army, roaches(40)),
            (702.0, army, ()),
            (702.5, marines(30), ()),
            (703.0, marines(30), zerglings(8)),
        ):
            *_, plan = game.step(time, army=units, enemies=enemies, supply=MAXED)
            steps.append((plan, game.offense.views(), game.feedback))
        return steps

    assert run() == run()


# --- the whole frame: behaviors run only this frame's grants ---


def test_a_cancelled_attack_commands_nothing_in_the_frame_its_units_move_on() -> None:
    logger = FakeLogger()
    bot = build_bot(attackers=0)
    bot.time, bot.supply_used, bot.supply_cap = 700.0, 200.0, 200.0
    bot.units += [
        FakeUnit(400 + index, UnitTypeId.MARINE, 16 + index % 5, 17 + index // 5)
        for index in range(20)
    ]
    hatchery = FakeUnit(
        800, UnitTypeId.HATCHERY, 53.5, 53.5, dps=0.0, hit_points=1500.0, structure=True
    )
    bot.enemy_structures = [hatchery]
    layers = Layers(map_view=MAP, logs=Logs(logger))
    play_frame(bot, 0, layers)
    bot.time, bot.registered = 700.5, []
    attacking = play_frame(bot, 1, layers)
    assert attacking.offense.stage is Stage.ADVANCE

    bot.time, bot.registered = 701.0, []
    bot.enemy_units = [
        FakeUnit(900 + index, UnitTypeId.ZERGLING, 14 + index % 4, 12, hit_points=35.0)
        for index in range(12)
    ]
    cancelled = play_frame(bot, 2, layers)

    assert cancelled.strategy.offense.posture is Posture.WITHDRAW
    assert (cancelled.offense.stage, cancelled.offense.mission_status) == (
        Stage.IDLE,
        MissionStatus.CANCELLED,
    )
    assert OWNER not in {grant.proposal.owner for grant in cancelled.result.grants}
    commanded = {
        micro.unit.tag: micro.target
        for maneuver in bot.registered
        if isinstance(maneuver, CombatManeuver)
        for micro in maneuver.micros[-1:]
    }
    # Every army unit was commanded for Defense or ArmyFallback, none toward the hatchery.
    assert hatchery.position not in set(commanded.values())
    granted = {tag for grant in cancelled.result.grants for tag in grant.tags}
    assert set(commanded) <= granted
    # The raid opened a defense mission in the same frame the attack was cancelled.
    assert {view.owner for view in cancelled.missions} == {"defense", OWNER}
    (view,) = [view for view in cancelled.missions if view.owner == OWNER]
    assert (view.mission_id, view.status, view.reason) == (
        "offense:main_attack:1",
        MissionStatus.CANCELLED,
        "home_threatened",
    )
    updates = [
        [m for m in event["data"]["missions"] if m["owner"] == OWNER]
        for event in logger.named("behavior.missions_updated")
    ]
    assert [(m[0]["status"], m[0]["phase"]) for m in updates] == [
        ("ACTIVE", "ASSEMBLE"),
        ("ACTIVE", "ADVANCE"),
        ("CANCELLED", "ADVANCE"),
    ]
    assert updates[-1][0]["cancel"]["mode"] == "IMMEDIATE"
    planned = logger.named("behavior.offense_planned")[-1]["data"]
    assert (planned["mission_id"], planned["mission_status"]) == (
        "offense:main_attack:1",
        "CANCELLED",
    )
    granted_events = logger.named("engine.granted")
    assert any(
        item["mission_id"] == "offense:main_attack:1"
        for event in granted_events
        for item in event["data"]["grants"]
    )


def test_the_whole_frame_flow_replays_to_the_same_missions() -> None:
    def replay():
        bot = build_bot(attackers=0)
        bot.supply_used = 200.0
        bot.units += [FakeUnit(400 + i, UnitTypeId.MARINE, 18, 18) for i in range(20)]
        layers = Layers(map_view=MAP, logs=Logs())
        frames = []
        for iteration, time in enumerate((700.0, 700.5, 701.0, 710.0)):
            bot.time = time
            frame_ = play_frame(bot, iteration, layers)
            frames.append((frame_.offense, frame_.missions, frame_.result))
        return frames

    assert replay() == replay()


# --- intel: the planner opens the scout, the mission runs the route ---


def test_the_intel_planner_opens_one_scout_and_the_mission_carries_it() -> None:
    planner = IntelPlanner()

    assert planner.plan(frame(30.0, workers=SCOUT_AT_WORKERS - 1)) == ()
    assert planner.mission is None

    (asked,) = planner.plan(frame(50.0))
    mission = planner.mission
    assert (asked.proposal_id, asked.mission_id) == ("intel", "intel:scout:1")
    assert (mission.phase, mission.status) == (ScoutMission.REQUESTING, MissionStatus.ACTIVE)

    scout = scv(100, 50, 50, role=SCOUTING)
    (lapping,) = planner.plan(frame(51.0, own_units=(scout,)))
    assert (mission.phase, mission.set_out, lapping.mission_id) == (
        ScoutMission.LAPPING,
        51.0,
        "intel:scout:1",
    )

    assert planner.plan(frame(52.0, own_units=(scv(100),))) == ()
    (view,) = planner.views()
    assert (view.status, view.reason) == (MissionStatus.FAILED, "scout_lost")
    assert (planner.finished, planner.mission) == ("scout_lost", None)


def test_a_scout_not_yet_out_is_cancelled_when_the_mineral_line_shrinks_and_reopens() -> None:
    planner = IntelPlanner()
    planner.plan(frame(50.0))
    first = planner.mission

    assert planner.plan(frame(51.0, workers=SCOUT_AT_WORKERS - 1)) == ()
    assert (first.status, first.reason) == (MissionStatus.CANCELLED, "workers_below_threshold")
    assert planner.finished is None

    (proposal,) = planner.plan(frame(52.0))
    assert proposal.mission_id == "intel:scout:2"


def test_a_scout_not_yet_out_is_cancelled_once_the_early_game_is_over() -> None:
    planner = IntelPlanner()
    planner.plan(frame(START_BY - 1.0))
    mission = planner.mission

    assert planner.plan(frame(START_BY)) == ()
    assert (mission.status, mission.lifecycle.cancel.reason) == (
        MissionStatus.CANCELLED,
        "too_late",
    )
    assert planner.finished == "too_late"


def test_a_scout_that_set_out_is_never_cancelled_for_the_early_game_mark() -> None:
    planner = IntelPlanner()
    scout = scv(100, 50, 50, role=SCOUTING)
    planner.plan(frame(START_BY - 1.0))
    planner.plan(frame(START_BY - 0.5, own_units=(scout,)))

    (proposal,) = planner.plan(frame(START_BY + 1.0, own_units=(scout,)))

    assert planner.mission.lifecycle.cancel is None
    assert proposal.command is Command.SCOUT


def _context(game: Game, frame_, awareness, strategy):
    return OffenseContext(
        attention=frame_,
        awareness=awareness,
        strategy=strategy,
        places=(),
        seen_at=MappingProxyType({}),
        own_power=awareness.own_power,
        assembled=0.0,
        known=(),
        start_cleared=False,
        advantage=True,
        cooldown_left=0.0,
    )


# --- defense: one mission per incident ---


def test_each_incident_is_one_defense_mission_until_it_is_over() -> None:
    awareness_model, strategy_model, planner = AwarenessModel(), StrategyModel(), DefensePlanner()

    def step(time, enemies=(), dead=()):
        frame_ = attention(
            time=time, own_units=marines(8, 20, 20), enemy_units=enemies, dead_tags=dead
        )
        awareness = awareness_model.infer(frame_)
        strategy = strategy_model.decide(frame_, awareness)
        return planner.plan(frame_, awareness, strategy), planner.views()

    x, y = MAIN.position
    first = (_zergling(90, x, y), _zergling(91, x + 1, y))
    proposals, (opened,) = step(0.0, first)
    # The attacker that named the incident dies: same incident, same mission.
    kept, (holding,) = step(0.5, first[1:], dead=(90,))
    over, (done,) = step(1.0, dead=(91,))
    again, (reopened,) = step(1.5, (_zergling(90, x, y),))

    (proposal,) = proposals
    assert (proposal.proposal_id, proposal.demand_id, proposal.mission_id) == (
        "defense:incident:90:ground",
        "incident:90",
        "defense:defend_area:1",
    )
    assert (opened.status, opened.phase, opened.kind) == (
        MissionStatus.ACTIVE,
        "DEFENDING",
        "defend_area",
    )
    assert kept[0].proposal_id == proposal.proposal_id
    assert holding.mission_id == opened.mission_id
    assert (over, done.status, done.reason) == ((), MissionStatus.COMPLETED, "incident_over")
    # The incident id comes back for a new attack: a new mission, the same proposal id.
    assert (again[0].proposal_id, reopened.mission_id) == (
        "defense:incident:90:ground",
        "defense:defend_area:2",
    )


def _zergling(tag: int, x: float, y: float):
    return unit(tag, UnitTypeId.ZERGLING, x, y, power=0.9, attack_air=False)
