from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from ares.consts import UnitRole
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.adapters.ares.mission_commands import (
    AresMissionCommands,
    UnauthorizedUnitCommand,
)
from bot.engine.missions import UnitAllocator, UnitRequirement
from bot.world.observation import UnitSnapshot


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


class AresMissionCommandsUseAbilityTests(unittest.TestCase):
    def test_raises_when_the_mission_does_not_own_the_unit(self):
        bot, _ = make_bot(1)
        commands = AresMissionCommands(bot, UnitAllocator())

        with self.assertRaises(UnauthorizedUnitCommand):
            commands.use_ability(
                mission_id="mission-0001",
                unit_tag=1,
                ability=AbilityId.BEHAVIOR_CLOAKON_BANSHEE,
            )

    def test_registers_the_ability_behavior_without_reassigning_role(self):
        bot, unit = make_bot(1)
        allocator = leased_allocator(1)
        commands = AresMissionCommands(bot, allocator)

        commands.use_ability(
            mission_id="mission-0001",
            unit_tag=1,
            ability=AbilityId.BEHAVIOR_CLOAKON_BANSHEE,
        )

        bot.mediator.assign_role.assert_not_called()
        bot.register_behavior.assert_called_once()


class AresMissionCommandsSafePathTests(unittest.TestCase):
    def test_assigns_map_control_role_and_registers_safe_movement(self):
        bot, _ = make_bot(1)
        bot.mediator.get_ground_grid = object()
        allocator = leased_allocator(1)
        commands = AresMissionCommands(bot, allocator)

        commands.safe_path_to(
            mission_id="mission-0001",
            unit_tag=1,
            target=Point2((20, 20)),
            success_at_distance=2.0,
        )

        bot.mediator.assign_role.assert_called_once_with(
            tag=1, role=UnitRole.MAP_CONTROL
        )
        bot.register_behavior.assert_called_once()


class AresMissionCommandsScoutPathTests(unittest.TestCase):
    def test_reaper_scout_combines_keep_safe_with_the_climber_grid(self):
        bot, _ = make_bot(1)
        climber_grid = object()
        bot.mediator.get_climber_grid = climber_grid
        bot.mediator.get_ground_grid = object()
        commands = AresMissionCommands(bot, leased_allocator(1))

        commands.path_to(
            mission_id="mission-0001",
            unit_tag=1,
            target=Point2((20, 20)),
            success_at_distance=2.0,
        )

        behavior = bot.register_behavior.call_args.args[0]
        self.assertEqual(
            [type(micro).__name__ for micro in behavior.micros],
            ["KeepUnitSafe", "PathUnitToTarget"],
        )
        self.assertTrue(all(micro.grid is climber_grid for micro in behavior.micros))


class AresMissionCommandsFocusedHarassTests(unittest.TestCase):
    def test_reaper_focus_uses_harass_role_grenade_and_forward_stutter(self):
        bot, _ = make_bot(1)
        target = SimpleNamespace(tag=2)
        bot.unit_tag_dict[2] = target
        bot.enemy_units = (target,)
        bot.start_location = Point2((10, 10))
        bot.mediator.get_climber_grid = object()
        commands = AresMissionCommands(bot, leased_allocator(1))

        commands.attack_unit(
            mission_id="mission-0001",
            unit_tag=1,
            target_unit_tag=2,
        )

        bot.mediator.assign_role.assert_called_once_with(
            tag=1, role=UnitRole.HARASSING
        )
        behavior = bot.register_behavior.call_args.args[0]
        self.assertEqual(
            [type(micro).__name__ for micro in behavior.micros],
            ["ReaperGrenade", "StutterUnitForward"],
        )


if __name__ == "__main__":
    unittest.main()
