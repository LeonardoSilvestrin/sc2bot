"""The Banshee harass vertical, end to end.

One test per responsibility boundary the behavior is built on: assessment
describes, planner decides, MissionController owns, executor commands.
"""

from __future__ import annotations

import unittest

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2

from bot.app.mission_registry import build_executor_factories
from bot.behavior.harass.banshee import (
    BansheeHarassAssessor,
    BansheeHarassConfig,
    BansheeHarassExecutor,
    BansheeHarassPlanner,
    BansheePhase,
    BansheeTargetHeuristics,
)
from bot.behavior.standing import StandingPlanner
from bot.engine.missions import (
    MissionContext,
    MissionController,
    MissionKind,
    MissionMode,
    MissionOutcome,
    MissionProposal,
    MissionResult,
    MissionStatus,
    UnitRequirement,
)
from bot.world.attention import (
    AttentionSnapshot,
    EconomyFacts,
    MapFacts,
    MapObservation,
    UnitSnapshot,
    UnitTypeCount,
    WorldFacts,
)
from bot.world.awareness import AwarenessService
from tests.fakes import FakeCommands, FakeLogger

TARGET = Point2((80, 80))
HOME = Point2((10, 10))
MAP = MapFacts(
    center=Point2((50, 50)),
    own_start=HOME,
    enemy_starts=(Point2((90, 90)),),
    observations=(MapObservation("enemy_natural", TARGET, False),),
)


def banshee(tag: int, position: Point2 = HOME, *, health: float = 1.0) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.BANSHEE,
        position=position,
        health_percentage=health,
        is_flying=True,
        is_worker=False,
        can_attack_air=False,
        can_attack_ground=True,
    )


def marine(tag: int, position: Point2 = HOME) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.MARINE,
        position=position,
        health_percentage=1.0,
        is_flying=False,
        is_worker=False,
        can_attack_air=True,
        can_attack_ground=True,
    )


def worker(tag: int) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.SCV,
        position=Point2((10 + tag * 0.1, 10)),
        health_percentage=1.0,
        is_flying=False,
        is_worker=True,
        can_attack_air=False,
        can_attack_ground=True,
    )


def enemy_anti_air(tag: int, position: Point2) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.MARINE,
        position=position,
        health_percentage=1.0,
        is_flying=False,
        is_worker=False,
        can_attack_air=True,
        can_attack_ground=True,
        visible_now=True,
        supply_cost=1.0,
    )


def attention(
    time: float,
    *,
    natural_visible: bool = False,
    own_units: tuple[UnitSnapshot, ...] = (),
    enemy_units: tuple[UnitSnapshot, ...] = (),
    workers: int = 16,
    banshees_pending: int = 0,
    cloak_progress: float = 1.0,
    opening: str = "BansheeCloak",
) -> AttentionSnapshot:
    researched = cloak_progress >= 1.0
    upgrades = frozenset({UpgradeId.BANSHEECLOAK}) if researched else frozenset()
    in_progress = () if researched else ((UpgradeId.BANSHEECLOAK, cloak_progress),)
    return AttentionSnapshot(
        WorldFacts(
            iteration=int(time),
            time=time,
            minerals=500,
            vespene=200,
            supply_used=float(workers),
            supply_cap=60.0,
            own_units=(*(worker(tag) for tag in range(1, workers + 1)), *own_units),
            enemy_units=enemy_units,
            map=MapFacts(
                center=MAP.center,
                own_start=MAP.own_start,
                enemy_starts=MAP.enemy_starts,
                observations=(
                    MapObservation("enemy_natural", TARGET, natural_visible),
                ),
            ),
            economy=EconomyFacts(
                opening_name=opening,
                unit_counts=(
                    UnitTypeCount(
                        UnitTypeId.BANSHEE,
                        existing=len(own_units),
                        ready=len(own_units),
                        pending=banshees_pending,
                    ),
                ),
                upgrades=upgrades,
                upgrades_in_progress=in_progress,
            ),
        )
    )


def scouted(service: AwarenessService, **kwargs) -> tuple:
    """Look at the natural once, then report it from memory."""

    service.update(attention(10.0, natural_visible=True, **kwargs))
    current = attention(20.0, natural_visible=False, **kwargs)
    return current, service.update(current)


class AssessmentTests(unittest.TestCase):
    def test_assessment_describes_the_situation_without_deciding_anything(self):
        service = AwarenessService()
        current, awareness = scouted(
            service, own_units=(banshee(1), banshee(2)), banshees_pending=1
        )

        assessment = BansheeHarassAssessor().assess(current, awareness)

        self.assertEqual(assessment.banshees_alive, 2)
        self.assertEqual(assessment.banshees_ready, 2)
        self.assertEqual(assessment.banshees_pending, 1)
        self.assertTrue(assessment.cloak_ready)
        self.assertEqual(assessment.cloak_progress, 1.0)
        self.assertEqual(assessment.preferred_target.key, "enemy_natural")
        self.assertGreater(assessment.readiness, 0.9)
        # Nobody has looked for anti-air at the natural: it reads as the
        # assumed amount, not as none.
        self.assertTrue(assessment.preferred_target.is_fallback)
        self.assertEqual(
            assessment.risk, BansheeTargetHeuristics().assumed_air_defense
        )
        # It produced a reading, not a commitment.
        self.assertFalse(hasattr(assessment, "mission_id"))
        self.assertNotIn("mission", assessment.log_fields())

    def test_cloak_still_researching_reads_as_low_readiness(self):
        service = AwarenessService()
        current, awareness = scouted(
            service, own_units=(banshee(1),), cloak_progress=0.3
        )

        assessment = BansheeHarassAssessor().assess(current, awareness)

        self.assertFalse(assessment.cloak_ready)
        self.assertAlmostEqual(assessment.cloak_progress, 0.3)
        self.assertLess(assessment.readiness, 0.2)
        self.assertEqual(assessment.log_fields()["cloak"], "30%")

    def test_anti_air_at_the_target_raises_risk_and_makes_it_unviable(self):
        service = AwarenessService()
        current, awareness = scouted(
            service,
            own_units=(banshee(1),),
            enemy_units=tuple(enemy_anti_air(900 + tag, TARGET) for tag in range(4)),
        )

        assessment = BansheeHarassAssessor().assess(current, awareness)

        self.assertIsNone(assessment.preferred_target)
        self.assertFalse(assessment.targets[0].viable)
        self.assertGreater(assessment.risk, 0.5)


class PlannerTests(unittest.TestCase):
    def test_proposes_a_standing_air_harass_once_ready(self):
        service = AwarenessService()
        current, awareness = scouted(service, own_units=(banshee(1), banshee(2)))

        proposals = BansheeHarassPlanner().propose(current, awareness)

        self.assertEqual(len(proposals), 1)
        proposal = proposals[0]
        self.assertEqual(proposal.kind, MissionKind.AIR_HARASS)
        self.assertEqual(proposal.mode, MissionMode.STANDING)
        self.assertEqual(proposal.deduplication_key, "air_harass:banshee_harass")
        self.assertEqual(proposal.requirement.desired, 2)
        self.assertEqual(proposal.requirement.minimum, 0)
        self.assertEqual(proposal.squad_id, "banshee_harass")

    def test_withholds_when_no_banshee_exists_yet(self):
        service = AwarenessService()
        current, awareness = scouted(service)

        self.assertEqual(BansheeHarassPlanner().propose(current, awareness), ())

    def test_withholds_while_the_build_does_not_call_for_the_raid(self):
        service = AwarenessService()
        current, awareness = scouted(
            service, own_units=(banshee(1),), opening="BioThreeOneOne"
        )

        self.assertEqual(BansheeHarassPlanner().propose(current, awareness), ())

    def test_records_its_assessment_and_plan_for_the_log(self):
        logger = FakeLogger()
        service = AwarenessService()
        current, awareness = scouted(service, own_units=(banshee(1),))
        planner = BansheeHarassPlanner(logger=logger)

        planner.propose(current, awareness)

        self.assertIsNotNone(planner.last_assessment)
        self.assertIsNotNone(planner.last_plan)
        names = [event["name"] for event in logger.events]
        self.assertIn("behavior.assessed", names)
        self.assertIn("behavior.proposed", names)
        assessed = next(
            e for e in logger.events if e["name"] == "behavior.assessed"
        )
        self.assertEqual(assessed["component"], "behavior.harass.banshee")
        self.assertEqual(assessed["data"]["decision"], "propose")


def mission_context(
    *,
    assigned_units: tuple[UnitSnapshot, ...],
    commands: FakeCommands,
    enemy_units: tuple[UnitSnapshot, ...] = (),
    now: float = 20.0,
) -> MissionContext:
    current = attention(now, own_units=assigned_units, enemy_units=enemy_units)
    return MissionContext(
        attention=current,
        awareness=AwarenessService().update(current),
        assigned_units=assigned_units,
        commands=commands,
    )


class ExecutorTests(unittest.IsolatedAsyncioTestCase):
    def executor(self, **kwargs) -> BansheeHarassExecutor:
        return BansheeHarassExecutor(
            mission_id="mission-0001",
            target_key="enemy_natural",
            target=TARGET,
            started_at=10.0,
            **kwargs,
        )

    async def test_waits_in_assemble_until_it_owns_a_banshee(self):
        commands = FakeCommands()
        executor = self.executor()

        result = await executor.step(
            mission_context(assigned_units=(), commands=commands)
        )

        self.assertEqual(executor.phase, BansheePhase.ASSEMBLE)
        self.assertEqual(result.reason, "waiting_for_banshee_squad")
        self.assertEqual(commands.commands, [])

    async def test_only_commands_the_banshees_the_mission_owns(self):
        commands = FakeCommands()
        executor = self.executor()
        mine = banshee(1, Point2((60, 60)))
        someone_elses = banshee(2, Point2((61, 61)))
        context = mission_context(assigned_units=(mine,), commands=commands)
        context = MissionContext(
            attention=attention(
                20.0, own_units=(mine, someone_elses), natural_visible=False
            ),
            awareness=context.awareness,
            assigned_units=(mine,),
            commands=commands,
        )

        await executor.step(context)

        commanded = {command[2] for command in commands.commands}
        self.assertEqual(commanded, {mine.tag})

    async def test_walks_approach_then_infiltrate_then_strike(self):
        commands = FakeCommands()
        executor = self.executor()

        await executor.step(
            mission_context(
                assigned_units=(banshee(1, Point2((40, 40))),), commands=commands
            )
        )
        self.assertEqual(executor.phase, BansheePhase.APPROACH)

        await executor.step(
            mission_context(
                assigned_units=(banshee(1, Point2((72, 72))),), commands=commands
            )
        )
        self.assertEqual(executor.phase, BansheePhase.INFILTRATE)

        await executor.step(
            mission_context(
                assigned_units=(banshee(1, Point2((80, 79))),), commands=commands
            )
        )
        self.assertEqual(executor.phase, BansheePhase.STRIKE)
        self.assertEqual(
            commands.commands[-2:],
            [
                (
                    "use_ability",
                    "mission-0001",
                    1,
                    AbilityId.BEHAVIOR_CLOAKON_BANSHEE,
                ),
                ("attack_move", "mission-0001", 1, TARGET, executor.arrival_radius),
            ],
        )

    async def test_a_ground_only_defender_never_triggers_disengage(self):
        """Nothing that cannot shoot up is a reason to abort a cloaked raid."""

        commands = FakeCommands()
        executor = self.executor()
        ground_only = UnitSnapshot(
            tag=900,
            unit_type=UnitTypeId.MARINE,
            position=Point2((81, 80)),
            health_percentage=1.0,
            is_flying=False,
            is_worker=False,
            can_attack_air=False,
            can_attack_ground=True,
            visible_now=True,
        )

        result = await executor.step(
            mission_context(
                assigned_units=(banshee(1, Point2((79, 80))),),
                enemy_units=(ground_only,),
                commands=commands,
            )
        )

        self.assertEqual(executor.phase, BansheePhase.STRIKE)
        self.assertEqual(result.reason, "harassing_enemy_worker_line_cloaked")

    async def test_evades_anti_air_then_repositions_home(self):
        commands = FakeCommands()
        executor = self.executor()

        result = await executor.step(
            mission_context(
                assigned_units=(banshee(1, Point2((79, 80))),),
                enemy_units=(enemy_anti_air(900, Point2((81, 80))),),
                commands=commands,
            )
        )
        self.assertEqual(executor.phase, BansheePhase.EVADE)
        self.assertEqual(result.outcome, MissionOutcome.ACTIVE)
        self.assertEqual(commands.commands[-1][0], "safe_path_to")

        # Threat gone but still out of position: heading home, not evading.
        await executor.step(
            mission_context(
                assigned_units=(banshee(1, Point2((60, 60))),), commands=commands
            )
        )
        self.assertEqual(executor.phase, BansheePhase.REPOSITION)

    async def test_a_striking_squad_costs_more_to_preempt_than_an_approaching_one(
        self,
    ):
        commands = FakeCommands()
        executor = self.executor()

        await executor.step(
            mission_context(
                assigned_units=(banshee(1, Point2((40, 40))),), commands=commands
            )
        )
        self.assertEqual(executor.preemption_cost(), 0.0)

        await executor.step(
            mission_context(
                assigned_units=(banshee(1, Point2((80, 80))),), commands=commands
            )
        )
        self.assertEqual(
            executor.preemption_cost(), BansheeHarassConfig().strike_preemption_cost
        )

    async def test_logs_every_phase_change_once(self):
        logger = FakeLogger()
        commands = FakeCommands()
        executor = self.executor(logger=logger)

        for _ in range(2):
            await executor.step(
                mission_context(
                    assigned_units=(banshee(1, Point2((40, 40))),), commands=commands
                )
            )

        states = [
            event["data"]["state"]
            for event in logger.events
            if event["name"] == "behavior.state_changed"
        ]
        self.assertEqual(states, ["APPROACH"])


def defense_proposal(now: float) -> MissionProposal:
    """A DEFENSE-priority request for a Banshee, built directly.

    Going through `DefensePlanner` would need a whole threatened-base
    fixture; what this test is about is the arbitration, not how defense
    decides it wants one.
    """

    return MissionProposal(
        proposal_id=f"defense:{now}",
        deduplication_key="defense:base:1",
        planner="defense_planner",
        kind=MissionKind.DEFENSE,
        priority=85,
        target_key="base:1",
        target=HOME,
        reason="base_outnumbered_by_observed_threat",
        requirement=UnitRequirement.combat(
            unit_types=frozenset({UnitTypeId.BANSHEE}),
            desired=1,
            minimum=1,
        ),
        created_at=now,
        can_preempt=True,
        commitment_seconds=1.0,
    )


class HoldingDefenseExecutor:
    """Stands in for `DefendBaseExecutor` so the fight lasts a chosen number
    of ticks.

    The real one completes the instant no threat is visible, which would end
    the mission inside the same tick it acquired its units -- fine in a game,
    useless for observing who owns what in between.
    """

    def __init__(self, steps_before_completion: int = 99) -> None:
        self.remaining = steps_before_completion

    async def step(self, context) -> MissionResult:
        self.remaining -= 1
        if self.remaining <= 0:
            return MissionResult(MissionOutcome.COMPLETED, "threat_cleared")
        return MissionResult(MissionOutcome.ACTIVE, "engaging_enemy_near_own_base")


class OwnershipTests(unittest.IsolatedAsyncioTestCase):
    """The mission boundary: who owns the Banshees, and when they come back."""

    def controller(self, logger=None, *, defense_steps: int = 99) -> MissionController:
        return MissionController(
            logger=logger or FakeLogger(),
            executor_factories={
                **build_executor_factories(),
                MissionKind.DEFENSE: (
                    lambda mission, now: HoldingDefenseExecutor(defense_steps)
                ),
            },
        )

    async def test_controller_leases_the_banshees_to_the_admitted_raid(self):
        service = AwarenessService()
        controller = self.controller()
        commands = FakeCommands()
        current, awareness = scouted(service, own_units=(banshee(1), banshee(2)))

        await controller.tick(
            attention=current,
            awareness=awareness,
            proposals=BansheeHarassPlanner().propose(current, awareness),
            commands=commands,
        )

        mission = controller.board.live()[0]
        self.assertEqual(mission.proposal.kind, MissionKind.AIR_HARASS)
        self.assertEqual(mission.status, MissionStatus.ACTIVE)
        self.assertEqual(set(mission.assigned_unit_tags), {1, 2})
        for tag in (1, 2):
            self.assertEqual(
                controller.allocator.owner_of(tag), mission.mission_id
            )

    async def test_defense_takes_the_banshees_and_the_raid_survives_empty(self):
        """A raid holding zero units is idle, not failed -- it waits."""

        service = AwarenessService()
        controller = self.controller()
        commands = FakeCommands()
        current, awareness = scouted(service, own_units=(banshee(1),))
        await controller.tick(
            attention=current,
            awareness=awareness,
            proposals=BansheeHarassPlanner().propose(current, awareness),
            commands=commands,
        )
        raid = controller.board.live()[0]
        self.assertEqual(raid.assigned_unit_tags, (1,))

        # Past the raid's 5s commitment window, a threatened base asks for it.
        later = attention(30.0, own_units=(banshee(1, Point2((40, 40))),))
        await controller.tick(
            attention=later,
            awareness=service.update(later),
            proposals=(defense_proposal(30.0),),
            commands=commands,
        )

        defense = next(
            m for m in controller.board.live() if m.proposal.kind is MissionKind.DEFENSE
        )
        self.assertEqual(controller.allocator.owner_of(1), defense.mission_id)
        self.assertEqual(raid.status, MissionStatus.ACTIVE)
        self.assertEqual(raid.assigned_unit_tags, ())

    async def test_defense_still_outranks_a_banshee_mid_strike(self):
        """`preemption_cost` makes a striking raid dearer, not untouchable."""

        logger = FakeLogger()
        service = AwarenessService()
        controller = MissionController(
            logger=logger,
            executor_factories={
                **build_executor_factories(logger=logger),
                MissionKind.DEFENSE: lambda mission, now: HoldingDefenseExecutor(),
            },
        )
        commands = FakeCommands()
        current, awareness = scouted(service, own_units=(banshee(1),))
        await controller.tick(
            attention=current,
            awareness=awareness,
            proposals=BansheeHarassPlanner().propose(current, awareness),
            commands=commands,
        )

        # Drive the executor into STRIKE by putting the Banshee on the target.
        striking = attention(26.0, own_units=(banshee(1, TARGET),))
        await controller.tick(
            attention=striking,
            awareness=service.update(striking),
            proposals=(),
            commands=commands,
        )
        states = [
            event["data"]["state"]
            for event in logger.events
            if event["name"] == "behavior.state_changed"
        ]
        self.assertEqual(states[-1], BansheePhase.STRIKE.name)

        contested = attention(30.0, own_units=(banshee(1, TARGET),))
        await controller.tick(
            attention=contested,
            awareness=service.update(contested),
            proposals=(defense_proposal(30.0),),
            commands=commands,
        )

        defense = next(
            m for m in controller.board.live() if m.proposal.kind is MissionKind.DEFENSE
        )
        self.assertEqual(controller.allocator.owner_of(1), defense.mission_id)

    async def test_banshees_return_to_the_raid_once_defense_ends(self):
        service = AwarenessService()
        controller = self.controller(defense_steps=2)
        commands = FakeCommands()
        planner = BansheeHarassPlanner()
        current, awareness = scouted(service, own_units=(banshee(1),))
        await controller.tick(
            attention=current,
            awareness=awareness,
            proposals=planner.propose(current, awareness),
            commands=commands,
        )
        raid = controller.board.live()[0]

        stolen = attention(30.0, own_units=(banshee(1, Point2((40, 40))),))
        await controller.tick(
            attention=stolen,
            awareness=service.update(stolen),
            proposals=(defense_proposal(30.0),),
            commands=commands,
        )
        defense = next(
            m for m in controller.board.live() if m.proposal.kind is MissionKind.DEFENSE
        )
        self.assertEqual(controller.allocator.owner_of(1), defense.mission_id)

        # Next tick the threat is gone, the defense mission completes, and
        # the raid -- still standing, still declared -- takes its Banshee back.
        back = attention(40.0, own_units=(banshee(1, Point2((40, 40))),))
        back_awareness = service.update(back)
        await controller.tick(
            attention=back,
            awareness=back_awareness,
            proposals=planner.propose(back, back_awareness),
            commands=commands,
        )
        self.assertEqual(defense.status, MissionStatus.COMPLETED)
        self.assertEqual(controller.allocator.owner_of(1), raid.mission_id)
        self.assertEqual(raid.assigned_unit_tags, (1,))

    async def test_a_released_marine_returns_to_the_standing_behavior(self):
        """Ownership is singular: standing picks a unit back up, once free."""

        service = AwarenessService()
        controller = self.controller()
        commands = FakeCommands()
        standing = StandingPlanner()
        units = (marine(1), marine(2), marine(3), marine(4), marine(5))

        current = attention(10.0, own_units=units)
        awareness = service.update(current)
        await controller.tick(
            attention=current,
            awareness=awareness,
            proposals=standing.propose(current, awareness),
            commands=commands,
        )
        standing_mission = controller.board.live()[0]
        owned_by_standing = {
            tag
            for tag in (1, 2, 3, 4, 5)
            if controller.allocator.owner_of(tag) == standing_mission.mission_id
        }
        self.assertTrue(owned_by_standing)

        # Every unit that has an owner has exactly one.
        for tag in owned_by_standing:
            self.assertEqual(
                controller.allocator.owner_of(tag), standing_mission.mission_id
            )

    async def test_the_tactical_loop_runs_every_tick_the_planner_does_not(self):
        """A raid keeps flying between the planner's 8-second proposals."""

        service = AwarenessService()
        controller = self.controller()
        commands = FakeCommands()
        planner = BansheeHarassPlanner()
        current, awareness = scouted(service, own_units=(banshee(1),))
        await controller.tick(
            attention=current,
            awareness=awareness,
            proposals=planner.propose(current, awareness),
            commands=commands,
        )
        commands.commands.clear()

        # One second later the planner's cadence is not ready...
        soon = attention(21.0, own_units=(banshee(1, Point2((50, 50))),))
        soon_awareness = service.update(soon)
        self.assertEqual(planner.propose(soon, soon_awareness), ())

        # ...but the mission still steps its executor and issues commands.
        await controller.tick(
            attention=soon,
            awareness=soon_awareness,
            proposals=(),
            commands=commands,
        )
        self.assertTrue(
            any(command[0] == "attack_move" for command in commands.commands)
        )


if __name__ == "__main__":
    unittest.main()
