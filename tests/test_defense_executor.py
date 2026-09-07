from __future__ import annotations

import unittest

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.behavior.defense import DefendBaseExecutor
from bot.engine.missions import MissionContext, MissionOutcome
from bot.world.knowledge.enemy.models import EnemyAwareness
from bot.world.knowledge.models import (
    AwarenessSnapshot,
    RelativeStrength,
    ThreatAssessment,
)
from bot.world.observation.models import (
    AttentionSnapshot,
    MapFacts,
    UnitSnapshot,
    WorldFacts,
)
from tests.fakes import FakeCommands

MAP = MapFacts(
    center=Point2((50, 50)),
    own_start=Point2((10, 10)),
    enemy_starts=(Point2((90, 90)),),
)


def reaper(tag: int, position: Point2) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.REAPER,
        position=position,
        health_percentage=1.0,
        is_flying=False,
        is_worker=False,
        can_attack_air=False,
        can_attack_ground=True,
    )


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


def context(
    *,
    enemy_units: tuple[UnitSnapshot, ...] = (),
    assigned_units: tuple[UnitSnapshot, ...],
    commands: FakeCommands,
) -> MissionContext:
    world = WorldFacts(
        iteration=1,
        time=20.0,
        minerals=0,
        vespene=0,
        supply_used=0.0,
        supply_cap=0.0,
        own_units=(),
        enemy_units=enemy_units,
        map=MAP,
    )
    awareness = AwarenessSnapshot(
        enemy=EnemyAwareness(sightings=(), locations=()),
        relative_strength=RelativeStrength(0.0, 0.0, 0, 0),
        threat=ThreatAssessment(0, 0, 0),
        updated_at=20.0,
    )
    return MissionContext(
        attention=AttentionSnapshot(world),
        awareness=awareness,
        assigned_units=assigned_units,
        commands=commands,
    )


class DefendBaseExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_attack_moves_every_assigned_defender_toward_the_nearest_threat(
        self,
    ):
        commands = FakeCommands()
        executor = DefendBaseExecutor(
            mission_id="mission-0001",
            target_key="own_base",
            target=Point2((12, 10)),
            started_at=10.0,
        )
        threat = enemy_marine(9, Point2((13, 10)))
        defenders = (reaper(1, Point2((10, 10))), reaper(2, Point2((11, 10))))

        result = await executor.step(
            context(
                enemy_units=(threat,), assigned_units=defenders, commands=commands
            )
        )

        self.assertEqual(result.outcome, MissionOutcome.ACTIVE)
        self.assertTrue(result.reason.strip())
        self.assertEqual(len(commands.commands), 2)
        for command in commands.commands:
            self.assertEqual(command[0], "attack_move")
            self.assertEqual(command[3], threat.position)

    async def test_completes_when_no_threat_remains_near_the_engagement_area(self):
        commands = FakeCommands()
        executor = DefendBaseExecutor(
            mission_id="mission-0001",
            target_key="own_base",
            target=Point2((12, 10)),
            started_at=10.0,
        )
        defender = reaper(1, Point2((10, 10)))

        result = await executor.step(
            context(assigned_units=(defender,), commands=commands)
        )

        self.assertEqual(result.outcome, MissionOutcome.COMPLETED)
        self.assertEqual(result.reason, "threat_cleared_near_own_base")
        self.assertEqual(commands.commands, [])

    async def test_fails_when_the_assigned_team_is_missing_while_a_threat_remains(
        self,
    ):
        commands = FakeCommands()
        executor = DefendBaseExecutor(
            mission_id="mission-0001",
            target_key="own_base",
            target=Point2((12, 10)),
            started_at=10.0,
        )
        threat = enemy_marine(9, Point2((13, 10)))

        result = await executor.step(
            context(enemy_units=(threat,), assigned_units=(), commands=commands)
        )

        self.assertEqual(result.outcome, MissionOutcome.FAILED)
        self.assertEqual(result.reason, "assigned_unit_missing")


if __name__ == "__main__":
    unittest.main()
