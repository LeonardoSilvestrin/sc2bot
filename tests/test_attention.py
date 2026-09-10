from __future__ import annotations

import unittest
from types import SimpleNamespace

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.adapters.ares import AresWorldObserver


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


class AresWorldObserverTests(unittest.TestCase):
    def test_builds_enemy_main_route_from_perimeter_away_from_ramp(self):
        main = Point2((90, 90))
        natural = Point2((90, 70))
        region = SimpleNamespace(
            center=main,
            perimeter=((80, 90), (90, 100), (100, 90), (82, 82)),
            region_ramps=(SimpleNamespace(top_center=Point2((90, 80))),),
        )
        mediator = SimpleNamespace(
            get_enemy_nat=natural,
            get_enemy_ramp=SimpleNamespace(top_center=Point2((90, 80))),
            get_map_data_object=SimpleNamespace(in_region_p=lambda _: region),
        )
        bot = SimpleNamespace(
            enemy_start_locations=(main,),
            mediator=mediator,
            is_visible=lambda _: False,
        )

        routes = AresWorldObserver._map_routes(bot)

        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0].key, "enemy_main")
        self.assertEqual(routes[0].waypoints[0].position, natural)
        self.assertEqual(
            routes[0].waypoints[-1].position,
            routes[0].waypoints[1].position,
        )

    def test_flags_ares_memory_units_as_not_currently_visible(self):
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

        world = AresWorldObserver().world_facts(bot, iteration=1)

        # Memory units are kept -- not silently dropped -- but flagged as not
        # currently visible so callers can tell "there now" from "last known
        # here" (see bot.world.awareness.enemy.EnemyKnowledge).
        self.assertEqual(
            {item.tag: item.visible_now for item in world.enemy_units},
            {3: True, 4: False},
        )
        self.assertEqual(tuple(item.tag for item in world.enemy_structures), (5,))
        self.assertEqual(tuple(item.tag for item in world.own_structures), (2,))
        self.assertTrue(world.map.observation("enemy_natural").visible_now)
        self.assertTrue(world.own_units[0].available_for_mission)

    def test_recognizes_enemy_workers_of_any_race(self):
        bot = SimpleNamespace(
            time=10.0,
            minerals=0,
            vespene=0,
            supply_used=0,
            supply_cap=0,
            worker_type=UnitTypeId.SCV,
            units=(),
            enemy_units=(
                unit(1, UnitTypeId.SCV),
                unit(2, UnitTypeId.PROBE),
                unit(3, UnitTypeId.DRONE),
            ),
            enemy_start_locations=(Point2((90, 90)),),
            start_location=Point2((10, 10)),
            game_info=SimpleNamespace(map_center=Point2((50, 50))),
        )

        world = AresWorldObserver().world_facts(bot, iteration=1)

        self.assertTrue(all(item.is_worker for item in world.enemy_units))

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

        economy = AresWorldObserver().world_facts(bot, iteration=10).economy

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

    def test_producer_utilization_averages_across_frames(self):
        # One Barracks, busy at first and then idle for a long stretch. A
        # single frame cannot tell those apart from the gap between two
        # Marines, so the observer carries the average across frames.
        observer = AresWorldObserver()
        barracks = unit(30, UnitTypeId.BARRACKS, structure=True, idle=False)
        bot = SimpleNamespace(
            time=100.0,
            minerals=0,
            vespene=0,
            supply_used=10,
            supply_cap=20,
            worker_type=UnitTypeId.SCV,
            units=(),
            structures=(barracks,),
            enemy_units=(),
            enemy_structures=(),
            enemy_start_locations=(),
            start_location=Point2((10, 10)),
            game_info=SimpleNamespace(map_center=Point2((50, 50))),
        )

        busy = observer.world_facts(bot, iteration=1).economy
        self.assertEqual(busy.producer(UnitTypeId.BARRACKS).utilization_20s, 1.0)

        barracks.is_idle = True
        bot.time = 105.0
        after_five_seconds = observer.world_facts(bot, iteration=2).economy
        bot.time = 125.0
        after_a_long_pause = observer.world_facts(bot, iteration=3).economy

        # Five seconds of quiet is a gap between units, not spare capacity.
        self.assertGreater(
            after_five_seconds.producer(UnitTypeId.BARRACKS).utilization_20s, 0.7
        )
        self.assertLess(
            after_a_long_pause.producer(UnitTypeId.BARRACKS).utilization_20s, 0.1
        )

    def test_upcoming_build_steps_are_priced_as_protected_commitments(self):
        bot = SimpleNamespace(
            time=60.0,
            minerals=500,
            vespene=0,
            supply_used=10,
            supply_cap=20,
            worker_type=UnitTypeId.SCV,
            units=(),
            structures=(),
            enemy_units=(),
            enemy_structures=(),
            enemy_start_locations=(),
            start_location=Point2((10, 10)),
            game_info=SimpleNamespace(map_center=Point2((50, 50))),
            calculate_cost=lambda item: SimpleNamespace(minerals=150, vespene=100),
            build_order_runner=SimpleNamespace(
                chosen_opening="BansheeCloak",
                build_completed=False,
                build_step=1,
                build_order=(
                    SimpleNamespace(command=UnitTypeId.BARRACKS),
                    SimpleNamespace(command=UnitTypeId.FACTORY),
                    SimpleNamespace(command=UnitTypeId.STARPORT),
                    SimpleNamespace(command=UnitTypeId.BANSHEE),
                ),
            ),
        )

        economy = AresWorldObserver().world_facts(bot, iteration=1).economy

        # Two steps ahead of the current one, and the step already taken is
        # not paid for twice.
        self.assertEqual(economy.protected_minerals, 300)
        self.assertEqual(economy.protected_vespene, 200)

    def test_a_finished_opening_protects_nothing(self):
        bot = SimpleNamespace(
            time=400.0,
            minerals=500,
            vespene=0,
            supply_used=10,
            supply_cap=20,
            worker_type=UnitTypeId.SCV,
            units=(),
            structures=(),
            enemy_units=(),
            enemy_structures=(),
            enemy_start_locations=(),
            start_location=Point2((10, 10)),
            game_info=SimpleNamespace(map_center=Point2((50, 50))),
            calculate_cost=lambda item: SimpleNamespace(minerals=150, vespene=100),
            build_order_runner=SimpleNamespace(
                chosen_opening="BansheeCloak",
                build_completed=True,
                build_step=0,
                build_order=(SimpleNamespace(command=UnitTypeId.FACTORY),),
            ),
        )

        economy = AresWorldObserver().world_facts(bot, iteration=1).economy

        self.assertEqual(economy.protected_minerals, 0)
        self.assertEqual(economy.protected_vespene, 0)

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

        economy = AresWorldObserver().world_facts(bot, iteration=1).economy

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
