from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from ares.consts import UnitRole
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.adapters.ares.mission_commands import (
    AresMissionCommands,
    UnauthorizedUnitCommand,
)
from bot.engine.missions import UnitAllocator, UnitRequirement
from bot.world.observation.models import UnitSnapshot


def make_bot(tag: int):
    unit = SimpleNamespace(type_id=UnitTypeId.REAPER)
    bot = SimpleNamespace(
        worker_type=UnitTypeId.SCV,
        unit_tag_dict={tag: unit},
        mediator=Mock(),
        register_behavior=Mock(),
    )
    return bot, unit


def leased_allocator(tag: int, *, mission_id: str = "mission-0001") -> UnitAllocator:
    allocator = UnitAllocator()
    allocator.sync(
        (
            UnitSnapshot(
                tag=tag,
                unit_type=UnitTypeId.REAPER,
                position=Point2((10, 10)),
                health_percentage=1.0,
                is_flying=False,
                is_worker=False,
                can_attack_air=False,
                can_attack_ground=True,
            ),
        )
    )
    allocator.allocate(
        mission_id=mission_id,
        priority=90,
        requirement=UnitRequirement(
            unit_types=frozenset({UnitTypeId.REAPER}), desired=1, minimum=1
        ),
        objective=None,
        now=0.0,
        can_preempt=False,
        commitment_seconds=0.0,
    )
    return allocator


class AresMissionCommandsAttackMoveTests(unittest.TestCase):
    def test_raises_when_the_mission_does_not_own_the_unit(self):
        bot, _ = make_bot(1)
        commands = AresMissionCommands(bot, UnitAllocator())

        with self.assertRaises(UnauthorizedUnitCommand):
            commands.attack_move(
                mission_id="mission-0001",
                unit_tag=1,
                target=Point2((20, 20)),
                success_at_distance=2.0,
            )

    def test_assigns_the_attacking_role_and_registers_the_behavior(self):
        bot, _ = make_bot(1)
        allocator = leased_allocator(1)
        commands = AresMissionCommands(bot, allocator)

        commands.attack_move(
            mission_id="mission-0001",
            unit_tag=1,
            target=Point2((20, 20)),
            success_at_distance=2.0,
        )

        bot.mediator.assign_role.assert_called_once_with(
            tag=1, role=UnitRole.ATTACKING
        )
        bot.register_behavior.assert_called_once()


if __name__ == "__main__":
    unittest.main()
