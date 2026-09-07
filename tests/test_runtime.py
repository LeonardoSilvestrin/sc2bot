from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.app import BotRuntime
from bot.engine.missions import MissionKind, MissionStatus
from tests.fakes import FakeCommands, FakeEconomyCommands, FakeLogger


def worker(tag: int):
    return SimpleNamespace(
        tag=tag,
        type_id=UnitTypeId.SCV,
        position=Point2((10 + tag, 10)),
        health_percentage=1.0,
        is_flying=False,
        can_attack_air=False,
        can_attack_ground=True,
        is_ready=True,
        is_carrying_resource=False,
        is_constructing_scv=False,
        is_structure=False,
    )


def reaper(tag: int):
    return SimpleNamespace(
        tag=tag,
        type_id=UnitTypeId.REAPER,
        position=Point2((10, 10)),
        health_percentage=1.0,
        is_flying=False,
        can_attack_air=False,
        can_attack_ground=True,
        is_ready=True,
        is_carrying_resource=False,
        is_constructing_scv=False,
        is_structure=False,
    )


def enemy_marine(tag: int, position: Point2):
    return SimpleNamespace(
        tag=tag,
        type_id=UnitTypeId.MARINE,
        position=position,
        health_percentage=1.0,
        is_flying=False,
        can_attack_air=False,
        can_attack_ground=True,
        is_ready=True,
        is_carrying_resource=False,
        is_constructing_scv=False,
        is_structure=False,
        is_memory=False,
    )


class RuntimePilotTests(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_stays_idle_when_map_has_no_configured_scout_target(self):
        fake_bot = SimpleNamespace(
            time=10.0,
            minerals=50,
            vespene=0,
            supply_used=12,
            supply_cap=15,
            units=(),
            all_enemy_units=(),
            worker_type=UnitTypeId.SCV,
            start_location=Point2((10, 10)),
            enemy_start_locations=[Point2((90, 90))],
            game_info=SimpleNamespace(map_center=Point2((50, 50)), map_name="PilotMap"),
            unit_tag_dict={},
        )
        runtime = BotRuntime(logger=FakeLogger())

        await runtime.on_start(fake_bot)
        await runtime.on_step(fake_bot, iteration=1)

        self.assertEqual(runtime.missions.snapshots(), ())
        self.assertTrue(
            any(event["name"] == "game.started" for event in runtime.logger.events)
        )

    async def test_runtime_logs_structured_awareness_and_world_state(self):
        commands = FakeCommands()
        townhall = SimpleNamespace(
            tag=999,
            type_id=UnitTypeId.COMMANDCENTER,
            position=Point2((10, 10)),
            health_percentage=1.0,
            is_flying=False,
            can_attack_air=False,
            can_attack_ground=False,
            is_ready=True,
            is_structure=True,
            ideal_harvesters=20,
            assigned_harvesters=18,
        )
        bot = SimpleNamespace(
            time=120.0,
            minerals=375,
            vespene=125,
            supply_used=24,
            supply_cap=31,
            units=(worker(1), reaper(2)),
            structures=(townhall,),
            enemy_units=(enemy_marine(50, Point2((80, 80))),),
            enemy_structures=(),
            worker_type=UnitTypeId.SCV,
            start_location=Point2((10, 10)),
            enemy_start_locations=[Point2((90, 90))],
            game_info=SimpleNamespace(
                map_center=Point2((50, 50)), map_name="PilotMap"
            ),
            build_order_runner=SimpleNamespace(
                build_completed=False,
                build_step=0,
                build_order=(),
                chosen_opening="ReaperExpand",
            ),
            state=SimpleNamespace(
                score=SimpleNamespace(
                    collection_rate_minerals=720.0,
                    collection_rate_vespene=180.0,
                )
            ),
            pending_units={UnitTypeId.SCV: 2},
            supply_pending=1,
        )
        runtime = BotRuntime(logger=FakeLogger())

        with (
            patch(
                "bot.app.runtime.AresMissionCommands",
                return_value=commands,
            ),
            patch("bot.app.runtime.register_baseline_behaviors"),
        ):
            await runtime.on_step(bot, iteration=1)

            bot.time = 121.0
            bot.minerals = 400
            await runtime.on_step(bot, iteration=2)

            bot.time = 130.0
            await runtime.on_step(bot, iteration=3)

        awareness_events = [
            event
            for event in runtime.logger.events
            if event["name"] == "awareness.updated"
        ]
        world_events = [
            event
            for event in runtime.logger.events
            if event["name"] == "attention.world_state"
        ]

        self.assertEqual(len(awareness_events), 2)
        self.assertEqual(len(world_events), 2)
        self.assertNotIn(
            "attention.snapshot", [event["name"] for event in runtime.logger.events]
        )
        self.assertEqual(
            awareness_events[0]["data"],
            {
                "posture": "RECOVERY",
                "relative_strength": {
                    "score": 0.0,
                    "confidence": 0.083,
                    "own_combat_units": 1,
                    "known_enemy_combat_units": 1,
                },
                "threat": {
                    "visible_enemy_units": 1,
                    "known_anti_air_units": 0,
                    "visible_anti_air_units": 0,
                    "visible_enemy_combat_units": 1,
                    "near_own_base_enemy_units": 0,
                    "near_own_base_enemy_combat_units": 0,
                },
                "enemy_sightings": 1,
                "active_missions": 0,
            },
        )
        self.assertEqual(
            world_events[0]["data"],
            {
                "minerals": 375,
                "vespene": 125,
                "supply_used": 24.0,
                "supply_cap": 31.0,
                "economy": {
                    "opening_name": "ReaperExpand",
                    "opening_completed": False,
                    "mineral_collection_rate": 720.0,
                    "vespene_collection_rate": 180.0,
                    "workers": {"existing": 1, "ready": 1, "pending": 2},
                    "townhalls": {"existing": 1, "ready": 1, "pending": 0},
                    "ideal_harvesters": 20,
                    "assigned_harvesters": 18,
                    "supply_pending": 1,
                },
                "own_unit_count": 2,
                "own_structure_count": 1,
                "visible_enemy_unit_count": 1,
            },
        )
        self.assertEqual(world_events[1]["game_time"], 130.0)
        self.assertEqual(world_events[1]["data"]["minerals"], 400)

    async def test_runtime_wires_unknown_to_scout_and_new_vision_to_completion(self):
        target = Point2((80, 80))
        commands = FakeCommands()
        bot = SimpleNamespace(
            time=10.0,
            minerals=400,
            vespene=0,
            supply_used=16,
            supply_cap=23,
            units=(*(worker(tag) for tag in range(1, 17)), reaper(17)),
            structures=(),
            enemy_units=(),
            enemy_structures=(),
            worker_type=UnitTypeId.SCV,
            start_location=Point2((10, 10)),
            enemy_start_locations=[Point2((90, 90))],
            game_info=SimpleNamespace(map_center=Point2((50, 50)), map_name="PilotMap"),
            mediator=SimpleNamespace(
                get_enemy_nat=target,
                get_unit_role_dict={"GATHERING": set(range(1, 17)), "IDLE": {17}},
            ),
            target_visible=False,
        )
        bot.is_visible = lambda position: bot.target_visible and position == target
        runtime = BotRuntime(logger=FakeLogger())

        with (
            patch(
                "bot.app.runtime.AresMissionCommands",
                return_value=commands,
            ),
            patch("bot.app.runtime.register_baseline_behaviors"),
        ):
            await runtime.on_step(bot, iteration=1)
            self.assertEqual(
                runtime.missions.snapshots()[0].status, MissionStatus.ACTIVE
            )

            bot.time = 11.0
            bot.target_visible = True
            await runtime.on_step(bot, iteration=2)

        self.assertEqual(
            runtime.missions.snapshots()[0].status,
            MissionStatus.COMPLETED,
        )
        self.assertIn("path_to", [command[0] for command in commands.commands])
        self.assertIn("release", [command[0] for command in commands.commands])

    async def test_runtime_stays_economically_idle_before_build_completes(self):
        economy_commands = FakeEconomyCommands()
        bot = SimpleNamespace(
            time=200.0,
            minerals=500,
            vespene=0,
            supply_used=10,
            supply_cap=30,
            units=(),
            enemy_units=(),
            worker_type=UnitTypeId.SCV,
            start_location=Point2((10, 10)),
            enemy_start_locations=[Point2((90, 90))],
            game_info=SimpleNamespace(map_center=Point2((50, 50)), map_name="PilotMap"),
        )
        runtime = BotRuntime(logger=FakeLogger())

        with (
            patch(
                "bot.app.runtime.AresEconomyCommands",
                return_value=economy_commands,
            ),
            patch("bot.app.runtime.register_baseline_behaviors"),
        ):
            await runtime.on_step(bot, iteration=1)

        self.assertEqual(economy_commands.commands, [])

    async def test_runtime_drives_economy_once_build_completes(self):
        economy_commands = FakeEconomyCommands()
        base_townhall = SimpleNamespace(
            tag=999,
            type_id=UnitTypeId.COMMANDCENTER,
            position=Point2((10, 10)),
            health_percentage=1.0,
            is_flying=False,
            can_attack_air=False,
            can_attack_ground=False,
            is_ready=True,
            is_structure=True,
        )
        bot = SimpleNamespace(
            time=200.0,
            minerals=500,
            vespene=0,
            supply_used=10,
            supply_cap=30,
            units=tuple(worker(tag) for tag in range(1, 11)),
            structures=(base_townhall,),
            enemy_units=(),
            enemy_structures=(),
            worker_type=UnitTypeId.SCV,
            start_location=Point2((10, 10)),
            enemy_start_locations=[Point2((90, 90))],
            game_info=SimpleNamespace(map_center=Point2((50, 50)), map_name="PilotMap"),
            build_order_runner=SimpleNamespace(build_completed=True),
        )
        runtime = BotRuntime(logger=FakeLogger())

        with (
            patch(
                "bot.app.runtime.AresEconomyCommands",
                return_value=economy_commands,
            ),
            patch("bot.app.runtime.register_baseline_behaviors"),
        ):
            await runtime.on_step(bot, iteration=1)

        self.assertTrue(economy_commands.commands)

    async def test_runtime_redispatches_a_still_pending_economic_action_every_tick(
        self,
    ):
        # Regression test: Ares macro behaviors (SpawnController,
        # BuildStructure, ...) only make one unit of progress per call and
        # must be re-invoked every frame to keep working toward a proposal's
        # target_count. Before the fix, the runtime only ever dispatched
        # `result.admitted_actions` -- the single tick an action was first
        # admitted -- then left it dispatched-and-forgotten until a 60s
        # confirmation timeout, stalling all further production in that
        # category. It must now dispatch every live (pending/in-flight)
        # commitment on every tick.
        economy_commands = FakeEconomyCommands()
        base_townhall = SimpleNamespace(
            tag=999,
            type_id=UnitTypeId.COMMANDCENTER,
            position=Point2((10, 10)),
            health_percentage=1.0,
            is_flying=False,
            can_attack_air=False,
            can_attack_ground=False,
            is_ready=True,
            is_structure=True,
        )
        bot = SimpleNamespace(
            time=200.0,
            minerals=500,
            vespene=0,
            supply_used=10,
            supply_cap=30,
            units=tuple(worker(tag) for tag in range(1, 11)),
            structures=(base_townhall,),
            enemy_units=(),
            enemy_structures=(),
            worker_type=UnitTypeId.SCV,
            start_location=Point2((10, 10)),
            enemy_start_locations=[Point2((90, 90))],
            game_info=SimpleNamespace(map_center=Point2((50, 50)), map_name="PilotMap"),
            build_order_runner=SimpleNamespace(build_completed=True),
        )
        runtime = BotRuntime(logger=FakeLogger())

        with (
            patch(
                "bot.app.runtime.AresEconomyCommands",
                return_value=economy_commands,
            ),
            patch("bot.app.runtime.register_baseline_behaviors"),
        ):
            await runtime.on_step(bot, iteration=1)
            first_tick_commands = len(economy_commands.commands)

            bot.time = 201.0
            await runtime.on_step(bot, iteration=2)
            second_tick_commands = len(economy_commands.commands)

        self.assertGreater(first_tick_commands, 0)
        # The worker count and bank did not change between ticks, so the
        # macro planner proposes the exact same worker deficit again; it
        # must still be dispatched again while its action stays pending or
        # in flight, not silently dropped because the key is already live.
        self.assertGreater(second_tick_commands, first_tick_commands)

    async def test_runtime_tolerates_ares_driving_the_bank_negative(self):
        # Ares behaviors (eg. SpawnController) decrement bot.minerals/vespene
        # in place to simulate virtual spend across chained behaviors in one
        # frame, which can leave them momentarily negative.
        economy_commands = FakeEconomyCommands()
        base_townhall = SimpleNamespace(
            tag=999,
            type_id=UnitTypeId.COMMANDCENTER,
            position=Point2((10, 10)),
            health_percentage=1.0,
            is_flying=False,
            can_attack_air=False,
            can_attack_ground=False,
            is_ready=True,
            is_structure=True,
        )
        bot = SimpleNamespace(
            time=200.0,
            minerals=-25,
            vespene=-10,
            supply_used=10,
            supply_cap=30,
            units=tuple(worker(tag) for tag in range(1, 11)),
            structures=(base_townhall,),
            enemy_units=(),
            enemy_structures=(),
            worker_type=UnitTypeId.SCV,
            start_location=Point2((10, 10)),
            enemy_start_locations=[Point2((90, 90))],
            game_info=SimpleNamespace(map_center=Point2((50, 50)), map_name="PilotMap"),
            build_order_runner=SimpleNamespace(build_completed=True),
        )
        runtime = BotRuntime(logger=FakeLogger())

        with (
            patch(
                "bot.app.runtime.AresEconomyCommands",
                return_value=economy_commands,
            ),
            patch("bot.app.runtime.register_baseline_behaviors"),
        ):
            await runtime.on_step(bot, iteration=1)

        self.assertEqual(economy_commands.commands, [])

    async def test_runtime_defends_the_base_and_outprioritizes_the_scout_for_it(self):
        commands = FakeCommands()
        bot = SimpleNamespace(
            time=10.0,
            minerals=400,
            vespene=0,
            supply_used=16,
            supply_cap=23,
            units=(*(worker(tag) for tag in range(1, 17)), reaper(17)),
            structures=(),
            enemy_units=(enemy_marine(50, Point2((12, 10))),),
            enemy_structures=(),
            worker_type=UnitTypeId.SCV,
            start_location=Point2((10, 10)),
            enemy_start_locations=[Point2((90, 90))],
            game_info=SimpleNamespace(map_center=Point2((50, 50)), map_name="PilotMap"),
            mediator=SimpleNamespace(
                get_enemy_nat=Point2((80, 80)),
                get_unit_role_dict={"GATHERING": set(range(1, 17)), "IDLE": {17}},
            ),
        )
        bot.is_visible = lambda position: False
        runtime = BotRuntime(logger=FakeLogger())

        with (
            patch(
                "bot.app.runtime.AresMissionCommands",
                return_value=commands,
            ),
            patch("bot.app.runtime.register_baseline_behaviors"),
        ):
            await runtime.on_step(bot, iteration=1)

        missions = runtime.missions.snapshots()
        defense = next(m for m in missions if m.kind is MissionKind.DEFENSE)
        scout = next(m for m in missions if m.kind is MissionKind.SCOUT)

        self.assertEqual(defense.status, MissionStatus.ACTIVE)
        self.assertEqual(scout.status, MissionStatus.BLOCKED)
        self.assertIn("attack_move", [command[0] for command in commands.commands])


if __name__ == "__main__":
    unittest.main()
