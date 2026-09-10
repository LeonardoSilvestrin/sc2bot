from __future__ import annotations

import unittest

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.app.mission_registry import DEFAULT_EXECUTOR_FACTORIES
from bot.behavior.defense import DefendBaseExecutor
from bot.behavior.harass import BansheeHarassExecutor, ReaperHarassExecutor
from bot.behavior.map_control import MapControlExecutor
from bot.behavior.scouting import IntelPlanner, ScoutExecutor
from bot.engine.missions import (
    Mission,
    MissionContext,
    MissionController,
    MissionExecutor,
    MissionKind,
    MissionOutcome,
    MissionProposal,
    MissionResult,
    MissionStatus,
    UnitRequirement,
)
from bot.world.awareness import AwarenessService
from tests.fakes import FakeCommands, FakeLogger
from tests.test_scout_slice import attention


class StubExecutor(MissionExecutor):
    async def step(self, context: MissionContext) -> MissionResult:
        return MissionResult(MissionOutcome.COMPLETED, "stub_executor_completed")


class ExecutorRegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_factory_exception_fails_and_releases_without_starting(self):
        def broken_factory(mission: Mission, now: float) -> MissionExecutor:
            raise ValueError("invalid executor configuration")

        logger = FakeLogger()
        commands = FakeCommands()
        controller = MissionController(
            logger=logger,
            executor_factories={MissionKind.SCOUT: broken_factory},
        )
        current = attention(10.0, visible=False)
        awareness = AwarenessService().update(current)
        await controller.tick(
            attention=current,
            awareness=awareness,
            proposals=IntelPlanner().propose(current, awareness),
            commands=commands,
        )
        mission = controller.snapshots()[0]
        self.assertEqual(mission.status, MissionStatus.FAILED)
        self.assertIsNone(mission.started_at)
        self.assertEqual(
            mission.reason, "executor_error:ValueError:invalid executor configuration"
        )
        self.assertEqual(controller.allocator.assigned_tags(mission.mission_id), ())
        self.assertEqual(commands.commands, [("release", mission.mission_id, 9000)])
        self.assertNotIn("mission_started", [event["name"] for event in logger.events])

    async def test_custom_factory_is_used_for_registered_mission_kind(self):
        def build_stub(mission: Mission, now: float) -> MissionExecutor:
            return StubExecutor()

        controller = MissionController(
            logger=FakeLogger(),
            executor_factories={MissionKind.SCOUT: build_stub},
        )
        current = attention(10.0, visible=False)
        awareness = AwarenessService().update(current)
        proposals = IntelPlanner().propose(current, awareness)

        await controller.tick(
            attention=current,
            awareness=awareness,
            proposals=proposals,
            commands=FakeCommands(),
        )

        mission = controller.snapshots()[0]
        self.assertEqual(mission.status, MissionStatus.COMPLETED)
        self.assertEqual(mission.reason, "stub_executor_completed")

    async def test_proposal_for_unregistered_mission_kind_is_rejected(self):
        controller = MissionController(logger=FakeLogger(), executor_factories={})
        current = attention(10.0, visible=False)
        awareness = AwarenessService().update(current)
        proposals = IntelPlanner().propose(current, awareness)

        logger = controller.logger
        await controller.tick(
            attention=current,
            awareness=awareness,
            proposals=proposals,
            commands=FakeCommands(),
        )

        self.assertEqual(controller.snapshots(), ())
        rejection = next(
            event for event in logger.events if event["name"] == "proposal_rejected"
        )
        self.assertEqual(rejection["data"]["reason"], "unsupported_mission_kind")


def _proposal(kind: MissionKind) -> MissionProposal:
    return MissionProposal(
        proposal_id="test-proposal",
        deduplication_key="test-dedup",
        planner="test_planner",
        kind=kind,
        priority=50,
        target_key="test_target",
        target=Point2((10, 10)),
        reason="test_reason",
        requirement=UnitRequirement(
            unit_types=frozenset({UnitTypeId.REAPER}), desired=1, minimum=1
        ),
        created_at=0.0,
    )


class DefaultExecutorFactoryCoverageTests(unittest.TestCase):
    def test_every_mission_kind_has_a_registered_default_factory(self):
        self.assertEqual(set(DEFAULT_EXECUTOR_FACTORIES), set(MissionKind))

    def test_scout_kind_builds_a_scout_executor(self):
        mission = Mission(
            mission_id="m1", proposal=_proposal(MissionKind.SCOUT), admitted_at=0.0
        )
        executor = DEFAULT_EXECUTOR_FACTORIES[MissionKind.SCOUT](mission, 0.0)
        self.assertIsInstance(executor, ScoutExecutor)

    def test_harass_kind_builds_a_reaper_harass_executor(self):
        mission = Mission(
            mission_id="m1", proposal=_proposal(MissionKind.HARASS), admitted_at=0.0
        )
        executor = DEFAULT_EXECUTOR_FACTORIES[MissionKind.HARASS](mission, 0.0)
        self.assertIsInstance(executor, ReaperHarassExecutor)

    def test_air_harass_kind_builds_a_banshee_harass_executor(self):
        mission = Mission(
            mission_id="m1",
            proposal=_proposal(MissionKind.AIR_HARASS),
            admitted_at=0.0,
        )
        executor = DEFAULT_EXECUTOR_FACTORIES[MissionKind.AIR_HARASS](mission, 0.0)
        self.assertIsInstance(executor, BansheeHarassExecutor)

    def test_defense_kind_builds_a_defend_base_executor(self):
        mission = Mission(
            mission_id="m1", proposal=_proposal(MissionKind.DEFENSE), admitted_at=0.0
        )
        executor = DEFAULT_EXECUTOR_FACTORIES[MissionKind.DEFENSE](mission, 0.0)
        self.assertIsInstance(executor, DefendBaseExecutor)

    def test_map_control_kind_builds_a_map_control_executor(self):
        mission = Mission(
            mission_id="m1",
            proposal=_proposal(MissionKind.MAP_CONTROL),
            admitted_at=0.0,
        )
        executor = DEFAULT_EXECUTOR_FACTORIES[MissionKind.MAP_CONTROL](mission, 0.0)
        self.assertIsInstance(executor, MapControlExecutor)
