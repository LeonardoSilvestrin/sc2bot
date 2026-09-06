from __future__ import annotations

import unittest
from dataclasses import dataclass

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.actions import (
    Action,
    ActionOutcome,
    ActionResult,
    ActionScheduler,
    UnitRequirement,
)
from bot.attention.models import AttentionSnapshot, MapFacts, UnitSnapshot, WorldFacts
from bot.awareness.models import AwarenessSnapshot, RelativeStrength, ThreatAssessment
from bot.knowledge.models import EnemyKnowledgeView
from bot.units import UnitRegistry
from tests.fakes import FakeCommands, FakeLogger


@dataclass
class CompleteAction(Action):
    async def step(self, context):
        return ActionResult(ActionOutcome.COMPLETED, "objective_reached")

    def requirements(self, attention):
        return (
            UnitRequirement(
                unit_types=frozenset({UnitTypeId.MARINE}), desired=1, minimum=1
            ),
        )


def attention_with_marines(count: int) -> AttentionSnapshot:
    units = tuple(
        UnitSnapshot(
            tag=index,
            unit_type=UnitTypeId.MARINE,
            position=Point2((10, 10)),
            health_percentage=1.0,
            is_flying=False,
            is_worker=False,
            can_attack_air=True,
            can_attack_ground=True,
        )
        for index in range(1, count + 1)
    )
    world = WorldFacts(
        iteration=1,
        time=12.0,
        minerals=50,
        vespene=0,
        supply_used=12,
        supply_cap=15,
        own_units=units,
        enemy_units=(),
        map=MapFacts(Point2((50, 50)), Point2((10, 10)), (Point2((90, 90)),)),
    )
    awareness = AwarenessSnapshot(
        RelativeStrength(0, 0, 0, 0), ThreatAssessment(0, 0, 0), 12.0
    )
    return AttentionSnapshot(world, EnemyKnowledgeView((), 12.0), awareness, ())


class ActionSchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def test_completed_action_releases_its_units(self):
        logger = FakeLogger()
        registry = UnitRegistry()
        scheduler = ActionScheduler(registry=registry, logger=logger)
        scheduler.submit(CompleteAction(action_id="defend-main", priority=100))

        await scheduler.tick(attention_with_marines(1), commands=FakeCommands())

        self.assertEqual(scheduler.mission_summaries(), ())
        self.assertIsNone(registry.owner_of(1))
        self.assertTrue(
            any(event["name"] == "action.finished" for event in logger.events)
        )

    async def test_action_waits_when_minimum_units_are_unavailable(self):
        logger = FakeLogger()
        registry = UnitRegistry()
        scheduler = ActionScheduler(registry=registry, logger=logger)
        scheduler.submit(CompleteAction(action_id="defend-main", priority=100))

        await scheduler.tick(attention_with_marines(0), commands=FakeCommands())

        mission = scheduler.mission_summaries()[0]
        self.assertEqual(mission.status, "BLOCKED")
        self.assertIsNone(mission.started_at)
