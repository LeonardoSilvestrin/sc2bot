from __future__ import annotations

import unittest

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.behavior.army import PositioningExecutor
from bot.engine.missions import MissionContext, MissionOutcome
from bot.world.attention import AttentionSnapshot, MapFacts, UnitSnapshot, WorldFacts
from bot.world.awareness import (
    AwarenessSnapshot,
    RelativeStrength,
    ThreatAssessment,
)
from bot.world.awareness.bases import BaseAwareness
from bot.world.awareness.enemy import EnemyAwareness
from tests.fakes import FakeCommands

MAP = MapFacts(
    center=Point2((50, 50)),
    own_start=Point2((10, 10)),
    enemy_starts=(Point2((90, 90)),),
)
ANCHOR = Point2((40, 40))


def marine(tag: int, position: Point2) -> UnitSnapshot:
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


def context(
    *, assigned_units: tuple[UnitSnapshot, ...], commands: FakeCommands
) -> MissionContext:
    world = WorldFacts(
        iteration=1,
        time=100.0,
        minerals=0,
        vespene=0,
        supply_used=0.0,
        supply_cap=0.0,
        own_units=assigned_units,
        enemy_units=(),
        map=MAP,
    )
    awareness = AwarenessSnapshot(
        enemy=EnemyAwareness(sightings=(), locations=()),
        relative_strength=RelativeStrength(0.0, 0.0, 0, 0),
        threat=ThreatAssessment(0, 0, 0),
        updated_at=world.time,
        bases=BaseAwareness(),
    )
    return MissionContext(
        attention=AttentionSnapshot(world),
        awareness=awareness,
        assigned_units=assigned_units,
        commands=commands,
    )


def executor(arrival_radius: float = 4.0) -> PositioningExecutor:
    return PositioningExecutor(
        mission_id="mission-0001",
        target_key="position:third",
        target=ANCHOR,
        started_at=90.0,
        arrival_radius=arrival_radius,
    )


class PositioningExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_moves_a_unit_that_is_outside_the_tolerance(self):
        commands = FakeCommands()
        unit = marine(1, Point2((10, 10)))

        result = await executor().step(
            context(assigned_units=(unit,), commands=commands)
        )

        self.assertEqual(result.outcome, MissionOutcome.ACTIVE)
        self.assertEqual(result.reason, "moving_to_position")
        self.assertEqual(len(commands.commands), 1)
        self.assertEqual(commands.commands[0][0], "safe_path_to")

    async def test_does_not_command_a_unit_already_within_tolerance(self):
        commands = FakeCommands()
        unit = marine(1, Point2((41, 41)))

        result = await executor().step(
            context(assigned_units=(unit,), commands=commands)
        )

        self.assertEqual(result.outcome, MissionOutcome.ACTIVE)
        self.assertEqual(result.reason, "holding_position")
        self.assertEqual(commands.commands, [])

    async def test_only_commands_the_units_that_have_drifted_out_of_tolerance(self):
        commands = FakeCommands()
        near = marine(1, Point2((41, 41)))
        far = marine(2, Point2((10, 10)))

        result = await executor().step(
            context(assigned_units=(near, far), commands=commands)
        )

        self.assertEqual(result.reason, "moving_to_position")
        self.assertEqual(len(commands.commands), 1)
        self.assertEqual(commands.commands[0][2], 2)

    async def test_never_fails_with_zero_assigned_units(self):
        commands = FakeCommands()

        result = await executor().step(context(assigned_units=(), commands=commands))

        self.assertEqual(result.outcome, MissionOutcome.ACTIVE)
        self.assertEqual(result.reason, "no_units_assigned")
        self.assertEqual(commands.commands, [])

    async def test_repeated_steps_within_tolerance_never_spam_commands(self):
        commands = FakeCommands()
        unit = marine(1, ANCHOR)
        step_executor = executor()

        for _ in range(5):
            await step_executor.step(context(assigned_units=(unit,), commands=commands))

        self.assertEqual(commands.commands, [])


if __name__ == "__main__":
    unittest.main()
