from __future__ import annotations

import unittest
from types import SimpleNamespace

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.world.observation import AttentionBuilder


def unit(
    tag: int,
    unit_type: UnitTypeId,
    *,
    structure=False,
    memory=False,
    ready=True,
    idle=None,
    orders=(),
    ideal_harvesters=None,
    assigned_harvesters=None,
):
    return SimpleNamespace(
        tag=tag,
        type_id=unit_type,
        position=Point2((tag, tag)),
        health_percentage=1.0,
        is_flying=False,
        can_attack_air=False,
        can_attack_ground=True,
        is_ready=ready,
        is_idle=idle,
        orders=orders,
        ideal_harvesters=ideal_harvesters,
        assigned_harvesters=assigned_harvesters,
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

    def test_publishes_opening_income_pending_counts_and_producer_capacity(self):
        barracks = (
            unit(30, UnitTypeId.BARRACKS, structure=True, idle=True),
            unit(
                31,
                UnitTypeId.BARRACKS,
                structure=True,
                idle=False,
                orders=(
                    SimpleNamespace(
                        ability=SimpleNamespace(
                            id=UnitTypeId.MARINE,
                        )
                    ),
                ),
            ),
        )
        townhall = unit(
            20,
            UnitTypeId.COMMANDCENTER,
            structure=True,
            idle=False,
            ideal_harvesters=16,
            assigned_harvesters=14,
        )
        refinery = unit(
            21,
            UnitTypeId.REFINERY,
            structure=True,
            ideal_harvesters=3,
            assigned_harvesters=3,
        )
        factory = unit(
            32,
            UnitTypeId.FACTORY,
            structure=True,
            ready=False,
        )
        pending_structures = {
            UnitTypeId.COMMANDCENTER: 1,
            UnitTypeId.FACTORY: 1,
            UnitTypeId.SUPPLYDEPOT: 1,
        }
        pending_units = {UnitTypeId.SCV: 1, UnitTypeId.MARINE: 2}
        structures = (townhall, refinery, *barracks, factory)
        workers = tuple(unit(tag, UnitTypeId.SCV) for tag in range(1, 13))
        marines = tuple(unit(tag, UnitTypeId.MARINE) for tag in range(40, 43))
        bot = SimpleNamespace(
            time=90.0,
            minerals=450,
            vespene=125,
            supply_used=27,
            supply_cap=39,
            worker_type=UnitTypeId.SCV,
            base_townhall_type=UnitTypeId.COMMANDCENTER,
            supply_type=UnitTypeId.SUPPLYDEPOT,
            gas_type=UnitTypeId.REFINERY,
            units=(*workers, *marines),
            structures=structures,
            townhalls=(townhall,),
            gas_buildings=(refinery,),
            enemy_units=(),
            enemy_structures=(),
            enemy_start_locations=(Point2((90, 90)),),
            start_location=Point2((10, 10)),
            game_info=SimpleNamespace(map_center=Point2((50, 50))),
            state=SimpleNamespace(
                score=SimpleNamespace(
                    collection_rate_minerals=740,
                    collection_rate_vespene=230,
                )
            ),
            build_order_runner=SimpleNamespace(
                chosen_opening="BioThreeOneOne",
                build_completed=True,
                build_order=(),
            ),
            mediator=SimpleNamespace(
                get_unit_role_dict={},
                get_building_counter=pending_structures,
            ),
            unit_pending=lambda unit_type: pending_units.get(unit_type, 0),
            structure_pending=lambda unit_type: pending_structures.get(unit_type, 0),
        )

        economy = AttentionBuilder().world_facts(bot, iteration=10).economy

        self.assertEqual(economy.opening_name, "BioThreeOneOne")
        self.assertTrue(economy.opening_completed)
        self.assertEqual(economy.mineral_collection_rate, 740.0)
        self.assertEqual(economy.vespene_collection_rate, 230.0)
        self.assertEqual((economy.workers.existing, economy.workers.pending), (12, 1))
        self.assertEqual(
            (economy.ideal_harvesters, economy.assigned_harvesters), (19, 17)
        )
        self.assertEqual(
            (economy.townhalls.ready, economy.townhalls.pending), (1, 1)
        )
        self.assertEqual(economy.supply_pending, 1)
        self.assertEqual(economy.unit_count(UnitTypeId.MARINE).total, 5)
        self.assertEqual(economy.structure_count(UnitTypeId.FACTORY).total, 1)
        self.assertEqual(economy.structure_count(UnitTypeId.SUPPLYDEPOT).pending, 1)
        self.assertEqual(
            (
                economy.producer(UnitTypeId.BARRACKS).ready,
                economy.producer(UnitTypeId.BARRACKS).idle,
                economy.producer(UnitTypeId.BARRACKS).busy,
            ),
            (2, 1, 1),
        )
        self.assertEqual(economy.producer(UnitTypeId.FACTORY).pending, 1)

    def test_missing_ares_economy_state_uses_safe_defaults(self):
        bot = SimpleNamespace(
            time=1.0,
            minerals=50,
            vespene=0,
            supply_used=12,
            supply_cap=15,
            worker_type=UnitTypeId.SCV,
            units=(),
            enemy_start_locations=(),
            start_location=Point2((10, 10)),
            game_info=SimpleNamespace(map_center=Point2((50, 50))),
        )

        economy = AttentionBuilder().world_facts(bot, iteration=1).economy

        self.assertEqual(economy.opening_name, "")
        self.assertFalse(economy.opening_completed)
        self.assertEqual(economy.mineral_collection_rate, 0.0)
        self.assertEqual(economy.vespene_collection_rate, 0.0)
        self.assertEqual(economy.workers.total, 0)
        self.assertEqual(economy.townhalls.total, 0)
        self.assertEqual(economy.supply_pending, 0)
        self.assertEqual(economy.unit_count(UnitTypeId.MARINE).total, 0)
        self.assertEqual(economy.structure_count(UnitTypeId.BARRACKS).total, 0)
        self.assertEqual(economy.producer(UnitTypeId.BARRACKS).total, 0)
