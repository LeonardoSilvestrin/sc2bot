from __future__ import annotations

import unittest
from types import SimpleNamespace

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.attention import AttentionBuilder


def unit(tag: int, unit_type: UnitTypeId, *, structure=False, memory=False):
    return SimpleNamespace(
        tag=tag,
        type_id=unit_type,
        position=Point2((tag, tag)),
        health_percentage=1.0,
        is_flying=False,
        can_attack_air=False,
        can_attack_ground=True,
        is_ready=True,
        is_carrying_resource=False,
        is_constructing_scv=False,
        is_structure=structure,
        is_memory=memory,
    )


class AttentionBuilderTests(unittest.TestCase):
    def test_publishes_current_facts_without_ares_memory_units(self):
        natural = Point2((80, 80))
        bot = SimpleNamespace(
            time=12.0,
            minerals=50,
            vespene=0,
            supply_used=12,
            supply_cap=15,
            worker_type=UnitTypeId.SCV,
            units=(unit(1, UnitTypeId.SCV),),
            structures=(unit(2, UnitTypeId.COMMANDCENTER, structure=True),),
            enemy_units=(
                unit(3, UnitTypeId.MARINE),
                unit(4, UnitTypeId.MARINE, memory=True),
            ),
            enemy_structures=(unit(5, UnitTypeId.BARRACKS, structure=True),),
            enemy_start_locations=(Point2((90, 90)),),
            start_location=Point2((10, 10)),
            game_info=SimpleNamespace(map_center=Point2((50, 50))),
            mediator=SimpleNamespace(
                get_enemy_nat=natural,
                get_unit_role_dict={"GATHERING": {1}},
            ),
            is_visible=lambda position: position == natural,
        )

        world = AttentionBuilder().world_facts(bot, iteration=1)

        self.assertEqual(tuple(item.tag for item in world.enemy_units), (3,))
        self.assertEqual(tuple(item.tag for item in world.enemy_structures), (5,))
        self.assertEqual(tuple(item.tag for item in world.own_structures), (2,))
        self.assertTrue(world.map.observation("enemy_natural").visible_now)
        self.assertTrue(world.own_units[0].available_for_mission)
