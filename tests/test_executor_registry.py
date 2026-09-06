from __future__ import annotations

import unittest

from bot.awareness import AwarenessService
from bot.ego import Mission, MissionController, MissionKind, MissionStatus
from bot.executors import MissionContext, MissionExecutor, MissionOutcome, MissionResult
from bot.planners import IntelPlanner
from tests.fakes import FakeCommands, FakeLogger
from tests.test_scout_slice import attention


class StubExecutor(MissionExecutor):
    async def step(self, context: MissionContext) -> MissionResult:
        return MissionResult(MissionOutcome.COMPLETED, "stub_executor_completed")


class ExecutorRegistryTests(unittest.IsolatedAsyncioTestCase):
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
