from __future__ import annotations

import unittest
from dataclasses import replace

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.attention.models import (
    AttentionSnapshot,
    MapFacts,
    MapObservation,
    UnitSnapshot,
    WorldFacts,
)
from bot.awareness import AwarenessService
from bot.ego import MissionController, MissionStatus
from bot.planners import IntelPlanner
from tests.fakes import FakeCommands, FakeLogger

TARGET = Point2((80, 80))


def worker(tag: int) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.SCV,
        position=Point2((10 + tag, 10)),
        health_percentage=1.0,
        is_flying=False,
        is_worker=True,
        can_attack_air=False,
        can_attack_ground=True,
    )


def reaper(tag: int) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.REAPER,
        position=Point2((10, 10)),
        health_percentage=1.0,
        is_flying=False,
        is_worker=False,
        can_attack_air=False,
        can_attack_ground=True,
    )


def attention(
    time: float, *, visible: bool, workers: int = 16, reapers: int = 1
) -> AttentionSnapshot:
    world = WorldFacts(
        iteration=int(time),
        time=time,
        minerals=500,
        vespene=0,
        supply_used=float(workers),
        supply_cap=30,
        own_units=(
            *(worker(tag) for tag in range(1, workers + 1)),
            *(reaper(9000 + tag) for tag in range(reapers)),
        ),
        enemy_units=(),
        map=MapFacts(
            center=Point2((50, 50)),
            own_start=Point2((10, 10)),
            enemy_starts=(Point2((90, 90)),),
            observations=(MapObservation("enemy_natural", TARGET, visible),),
        ),
    )
    return AttentionSnapshot(world)


class ScoutVerticalSliceTests(unittest.IsolatedAsyncioTestCase):
    async def test_second_proposal_for_live_objective_is_rejected(self):
        logger = FakeLogger()
        commands = FakeCommands()
        service = AwarenessService()
        planner = IntelPlanner()
        current = attention(10.0, visible=False)
        awareness = service.update(current)
        first = planner.propose(current, awareness)[0]
        duplicate = replace(first, proposal_id=f"{first.proposal_id}:duplicate")
        controller = MissionController(logger=logger)

        await controller.tick(
            attention=current,
            awareness=awareness,
            proposals=(first, duplicate),
            commands=commands,
        )

        self.assertEqual(len(controller.snapshots()), 1)
        rejection = next(
            event for event in logger.events if event["name"] == "proposal_rejected"
        )
        self.assertEqual(rejection["data"]["reason"], "matching_mission_already_live")

    async def test_unknown_location_flows_to_completed_mission_and_release(self):
        logger = FakeLogger()
        commands = FakeCommands()
        awareness_service = AwarenessService(location_stale_after=90.0)
        planner = IntelPlanner()
        controller = MissionController(logger=logger)

        first_attention = attention(10.0, visible=False)
        first_awareness = awareness_service.update(first_attention)
        proposals = planner.propose(first_attention, first_awareness)
        await controller.tick(
            attention=first_attention,
            awareness=first_awareness,
            proposals=proposals,
            commands=commands,
        )

        active = controller.snapshots()[0]
        self.assertNotEqual(active.proposal_id, active.mission_id)
        self.assertEqual(active.status, MissionStatus.ACTIVE)
        self.assertEqual(commands.commands[0][0], "path_to")

        refreshed_attention = attention(11.0, visible=True)
        refreshed_awareness = awareness_service.update(refreshed_attention)
        await controller.tick(
            attention=refreshed_attention,
            awareness=refreshed_awareness,
            proposals=planner.propose(refreshed_attention, refreshed_awareness),
            commands=commands,
        )

        completed = controller.snapshots()[0]
        self.assertEqual(completed.status, MissionStatus.COMPLETED)
        self.assertEqual(completed.reason, "target_observed_after_mission_started")
        self.assertEqual(completed.assigned_unit_tags, ())
        self.assertIsNone(controller.allocator.owner_of(active.assigned_unit_tags[0]))

        names = [event["name"] for event in logger.events]
        self.assertEqual(
            names[:5],
            [
                "proposal_created",
                "proposal_admitted",
                "mission_queued",
                "units_assigned",
                "mission_started",
            ],
        )
        self.assertIn("units_released", names)
        self.assertIn("mission_completed", names)
        for event in logger.events:
            if event["name"].startswith(("proposal_", "mission_")):
                self.assertTrue(event["data"]["reason"])

    async def test_admitted_mission_is_blocked_without_an_eligible_unit(self):
        logger = FakeLogger()
        commands = FakeCommands()
        awareness_service = AwarenessService()
        planner = IntelPlanner()

        # Create the proposal with a healthy economy, then expose no eligible units
        # to the controller. Planner and allocator remain distinct responsibilities.
        rich_attention = attention(10.0, visible=False)
        awareness = awareness_service.update(rich_attention)
        proposal = planner.propose(rich_attention, awareness)
        empty_attention = attention(10.0, visible=False, workers=0, reapers=0)
        controller = MissionController(logger=logger)
        await controller.tick(
            attention=empty_attention,
            awareness=awareness,
            proposals=proposal,
            commands=commands,
        )

        self.assertEqual(controller.snapshots()[0].status, MissionStatus.BLOCKED)
        self.assertEqual(commands.commands, [])
        self.assertIn("mission_blocked", [event["name"] for event in logger.events])

    async def test_executor_error_fails_and_releases_the_mission(self):
        class FailingCommands(FakeCommands):
            def path_to(self, **kwargs) -> None:
                raise RuntimeError("path unavailable")

        logger = FakeLogger()
        commands = FailingCommands()
        service = AwarenessService()
        planner = IntelPlanner()
        current = attention(10.0, visible=False)
        awareness = service.update(current)
        controller = MissionController(logger=logger)

        await controller.tick(
            attention=current,
            awareness=awareness,
            proposals=planner.propose(current, awareness),
            commands=commands,
        )

        mission = controller.snapshots()[0]
        self.assertEqual(mission.status, MissionStatus.FAILED)
        self.assertIn("executor_error:RuntimeError", mission.reason)
        self.assertEqual(mission.assigned_unit_tags, ())
        self.assertIn("mission_failed", [event["name"] for event in logger.events])
