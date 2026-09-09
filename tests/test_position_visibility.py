from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.adapters.ares import AresMissionCommands, AresWorldObserver
from bot.engine.missions import UnitAllocator, UnitRequirement
from bot.world.attention import UnitSnapshot


class RoleTrackingMediator:
    """Minimal stand-in for Ares' UnitRoleManager: a real dict-of-sets kept
    in sync by `assign_role`, so `AresWorldObserver.world_facts` (which reads
    `get_unit_role_dict`) actually observes what `AresMissionCommands`
    (which calls `assign_role`) did -- the exact boundary Invariant 3 is
    about.
    """

    def __init__(self) -> None:
        self.role_dict: dict[str, set[int]] = {}
        self.get_ground_grid = object()

    def assign_role(self, *, tag: int, role) -> None:
        for tags in self.role_dict.values():
            tags.discard(tag)
        self.role_dict.setdefault(role.name, set()).add(tag)

    @property
    def get_unit_role_dict(self):
        return self.role_dict


def make_bot_and_unit(tag: int):
    unit_obj = SimpleNamespace(
        tag=tag,
        type_id=UnitTypeId.MARINE,
        position=Point2((10, 10)),
        health_percentage=1.0,
        is_flying=False,
        can_attack_air=True,
        can_attack_ground=True,
        is_ready=True,
        is_carrying_resource=False,
        is_constructing_scv=False,
        is_structure=False,
        is_memory=False,
    )
    mediator = RoleTrackingMediator()
    bot = SimpleNamespace(
        worker_type=UnitTypeId.SCV,
        unit_tag_dict={tag: unit_obj},
        mediator=mediator,
        register_behavior=Mock(),
        time=10.0,
        minerals=0,
        vespene=0,
        supply_used=0,
        supply_cap=0,
        units=(unit_obj,),
        structures=(),
        enemy_units=(),
        enemy_structures=(),
        enemy_start_locations=(Point2((90, 90)),),
        start_location=Point2((10, 10)),
        game_info=SimpleNamespace(map_center=Point2((50, 50))),
    )
    return bot, mediator


def leased_allocator(tag: int, *, mission_id: str) -> UnitAllocator:
    allocator = UnitAllocator()
    allocator.sync(
        (
            UnitSnapshot(
                tag=tag,
                unit_type=UnitTypeId.MARINE,
                position=Point2((10, 10)),
                health_percentage=1.0,
                is_flying=False,
                is_worker=False,
                can_attack_air=True,
                can_attack_ground=True,
            ),
        )
    )
    allocator.allocate(
        mission_id=mission_id,
        priority=25,
        requirement=UnitRequirement(
            unit_types=frozenset({UnitTypeId.MARINE}), desired=1, minimum=0
        ),
        objective=None,
        now=0.0,
        can_preempt=False,
        commitment_seconds=0.0,
    )
    return allocator


class PositionParkedUnitVisibilityTests(unittest.TestCase):
    """Invariant 3: POSITION must not make units invisible to higher-priority
    planners the way an incidental Ares role would."""

    def test_position_parked_unit_stays_available_for_mission(self):
        bot, _ = make_bot_and_unit(1)
        allocator = leased_allocator(1, mission_id="position:forward")
        commands = AresMissionCommands(bot, allocator)

        commands.safe_path_to(
            mission_id="position:forward",
            unit_tag=1,
            target=Point2((40, 40)),
            success_at_distance=4.0,
            keep_available=True,
        )

        world = AresWorldObserver().world_facts(bot, iteration=1)
        self.assertTrue(world.own_units[0].available_for_mission)

    def test_map_control_parked_unit_stays_unavailable_for_mission(self):
        """Regression guard: a genuinely active MAP_CONTROL/DEFENSE/harass
        responsibility must still look busy -- only POSITION's own park
        should flip to available."""

        bot, _ = make_bot_and_unit(1)
        allocator = leased_allocator(1, mission_id="map_control:patrol")
        commands = AresMissionCommands(bot, allocator)

        commands.safe_path_to(
            mission_id="map_control:patrol",
            unit_tag=1,
            target=Point2((40, 40)),
            success_at_distance=4.0,
        )

        world = AresWorldObserver().world_facts(bot, iteration=1)
        self.assertFalse(world.own_units[0].available_for_mission)


if __name__ == "__main__":
    unittest.main()
