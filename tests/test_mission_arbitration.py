from __future__ import annotations

import unittest
from dataclasses import replace

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.app.mission_registry import DEFAULT_EXECUTOR_FACTORIES
from bot.behavior.defense import DefensePlanner
from bot.behavior.harass import HarassPlanner
from bot.behavior.scouting import IntelPlanner
from bot.engine.missions import MissionController, MissionKind, MissionStatus
from bot.world.knowledge import AwarenessService
from bot.world.observation.models import UnitSnapshot
from tests.fakes import FakeCommands, FakeLogger
from tests.test_scout_slice import attention


def enemy_marine(tag: int, position: Point2) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.MARINE,
        position=position,
        health_percentage=1.0,
        is_flying=False,
        is_worker=False,
        can_attack_air=False,
        can_attack_ground=True,
        visible_now=True,
    )


class HarassDeduplicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_second_harass_proposal_for_the_same_target_is_rejected_while_live(
        self,
    ):
        logger = FakeLogger()
        commands = FakeCommands()
        service = AwarenessService()
        controller = MissionController(logger=logger, executor_factories=DEFAULT_EXECUTOR_FACTORIES)

        service.update(attention(10.0, visible=True))
        current = attention(20.0, visible=False)
        awareness = service.update(current)
        first = HarassPlanner().propose(current, awareness)[0]
        duplicate = replace(first, proposal_id=f"{first.proposal_id}:duplicate")

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


class DefensePreemptionTests(unittest.IsolatedAsyncioTestCase):
    async def test_defense_preempts_a_lower_priority_scout_after_commitment_window(
        self,
    ):
        service = AwarenessService()
        controller = MissionController(logger=FakeLogger(), executor_factories=DEFAULT_EXECUTOR_FACTORIES)
        commands = FakeCommands()

        current = attention(10.0, visible=False)
        awareness = service.update(current)
        scout_proposal = IntelPlanner().propose(current, awareness)[0]
        await controller.tick(
            attention=current,
            awareness=awareness,
            proposals=(scout_proposal,),
            commands=commands,
        )
        scout = controller.snapshots()[0]
        self.assertEqual(scout.status, MissionStatus.ACTIVE)
        reaper_tag = scout.assigned_unit_tags[0]

        threatened = attention(16.0, visible=False)
        threatened = replace(
            threatened,
            world=replace(
                threatened.world,
                enemy_units=(enemy_marine(7000, Point2((12, 10))),),
            ),
        )
        threat_awareness = service.update(threatened)
        defense_proposal = DefensePlanner().propose(threatened, threat_awareness)[0]

        await controller.tick(
            attention=threatened,
            awareness=threat_awareness,
            proposals=(defense_proposal,),
            commands=commands,
        )

        donor, recipient = controller.snapshots()
        self.assertEqual(donor.kind, MissionKind.SCOUT)
        self.assertEqual(donor.status, MissionStatus.FAILED)
        self.assertEqual(donor.reason, "all_assigned_units_preempted")
        self.assertEqual(recipient.kind, MissionKind.DEFENSE)
        self.assertEqual(recipient.status, MissionStatus.ACTIVE)
        self.assertEqual(
            controller.allocator.owner_of(reaper_tag), recipient.mission_id
        )


if __name__ == "__main__":
    unittest.main()
