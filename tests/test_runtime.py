from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ares.consts import BUILD_CHOICES, CYCLE
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.app import BotRuntime
from bot.engine.missions import MissionKind, MissionStatus
from bot.macro import macro_config_for_opening
from tests.fakes import FakeCommands, FakeEconomyCommands, FakeLogger


class FakeBuildOrderRunner:
    def __init__(self, *, config: dict, chosen_opening: str) -> None:
        self.config = config
        self.chosen_opening = chosen_opening
        self.build_completed = False
        self.build_step = 0
        self.build_order = ()
        self.switch_calls: list[str] = []

    def switch_opening(self, opening_name: str) -> None:
        self.switch_calls.append(opening_name)
        self.chosen_opening = opening_name


class FakeChat:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def __call__(self, message: str) -> None:
        self.messages.append(message)


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


def enemy_worker(tag: int, position: Point2):
    return SimpleNamespace(
        tag=tag,
        type_id=UnitTypeId.SCV,
        position=position,
        health_percentage=1.0,
        is_flying=False,
        can_attack_air=False,
        can_attack_ground=False,
        is_ready=True,
        is_carrying_resource=False,
        is_constructing_scv=False,
        is_structure=False,
        is_memory=False,
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

        # No scout/harass/defense/map-control target exists on this bare
        # map, but the standing disposition planner still gives every
        # eligible unit (there are none here) a home -- only POSITION
        # missions (main/reserve) come up, never a FINITE one.
        self.assertTrue(
            all(m.kind is MissionKind.HOLD_RALLY for m in runtime.missions.snapshots())
        )
        self.assertTrue(
            any(event["name"] == "game.started" for event in runtime.logger.events)
        )

    async def test_runtime_logs_structured_observation_and_knowledge(self):
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

        knowledge_events = [
            event
            for event in runtime.logger.events
            if event["name"] == "knowledge.updated"
        ]
        observation_events = [
            event
            for event in runtime.logger.events
            if event["name"] == "observation.updated"
        ]

        self.assertEqual(len(knowledge_events), 2)
        self.assertEqual(len(observation_events), 2)
        self.assertNotIn(
            "attention.world_state",
            [event["name"] for event in runtime.logger.events],
        )
        self.assertEqual(
            knowledge_events[0]["data"],
            {
                "posture": "RECOVERY",
                "relative_strength": {
                    "score": 0.0,
                    "confidence": 1.0,
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
                # The standing disposition planner now always claims
                # position:main and position:reserve for this single-base
                # setup (RECOVERY macro posture maps to CombatPosture.TURTLE,
                # see derive_combat_posture), even though nothing else
                # (scout/harass/defense) is active.
                "active_missions": 1,
            },
        )
        self.assertEqual(
            observation_events[0]["data"],
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
        self.assertEqual(observation_events[1]["game_time"], 130.0)
        self.assertEqual(observation_events[1]["data"]["minerals"], 400)
        self.assertEqual(observation_events[0]["component"], "world.attention")
        self.assertEqual(knowledge_events[0]["component"], "world.awareness")

    async def test_runtime_announces_an_awareness_belief_change_in_chat(self):
        # Directly observed enemy workers outnumbering our own is hard proof
        # (see RelativeBeliefConfig.observed_certainty_floor) -- ECONOMY
        # should flip UNKNOWN -> BEHIND on the very first tick and be
        # announced in chat, with a matching structured log event.
        commands = FakeCommands()
        chat = FakeChat()
        bot = SimpleNamespace(
            time=10.0,
            minerals=50,
            vespene=0,
            supply_used=5,
            supply_cap=15,
            units=tuple(worker(tag) for tag in range(1, 6)),
            structures=(),
            enemy_units=tuple(
                enemy_worker(tag, Point2((80, 80))) for tag in range(50, 60)
            ),
            enemy_structures=(),
            worker_type=UnitTypeId.SCV,
            start_location=Point2((10, 10)),
            enemy_start_locations=[Point2((90, 90))],
            game_info=SimpleNamespace(map_center=Point2((50, 50)), map_name="PilotMap"),
            chat_send=chat,
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

        self.assertEqual(len(chat.messages), 1)
        self.assertIn("ECONOMY", chat.messages[0])
        self.assertIn("UNKNOWN -> BEHIND", chat.messages[0])

        belief_events = [
            event
            for event in runtime.logger.events
            if event["name"] == "awareness.belief_changed"
        ]
        self.assertEqual(len(belief_events), 1)
        self.assertEqual(belief_events[0]["data"]["message"], chat.messages[0])
        logged = {event["name"] for event in runtime.logger.events}
        self.assertIn("awareness.world_belief", logged)
        self.assertIn("knowledge.enemy_model", logged)

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

    async def test_macro_spends_the_surplus_during_an_opening(self):
        # Before this refactor an unfinished opening meant the economy
        # controller never ran at all, so a bank could pile up untouched. Now
        # macro keeps workers and units coming, and the price of the opening's
        # next two steps (Factory + Starport = 300/200) is withheld instead.
        logger = FakeLogger()
        economy_commands = FakeEconomyCommands()
        bot = self._opening_bot(minerals=500)
        runtime = BotRuntime(logger=logger)

        with (
            patch(
                "bot.app.runtime.AresEconomyCommands",
                return_value=economy_commands,
            ),
            patch("bot.app.runtime.register_baseline_behaviors"),
        ):
            await runtime.on_step(bot, iteration=1)

        dispatched = [command[0] for command in economy_commands.commands]
        self.assertIn("produce_unit", dispatched)
        self.assertIn("produce_worker", dispatched)
        status = next(
            event for event in logger.events if event["name"] == "macro.status"
        )
        # Both steps' 300 minerals are withheld; their 200 gas cannot be,
        # since protection can only hold resources that exist.
        self.assertEqual(status["data"]["resources"]["protected"], [300, 0])
        self.assertFalse(status["data"]["opening"]["completed"])

    async def test_structural_macro_resumes_when_the_opening_ends(self):
        # Same bank and the same world as
        # test_macro_spends_the_surplus_during_an_opening: with no steps left
        # to own the build, production capacity becomes macro's decision and
        # nothing is protected any more.
        logger = FakeLogger()
        economy_commands = FakeEconomyCommands()
        bot = self._opening_bot(minerals=500)
        bot.build_order_runner.build_completed = True
        runtime = BotRuntime(logger=logger)

        with (
            patch(
                "bot.app.runtime.AresEconomyCommands",
                return_value=economy_commands,
            ),
            patch("bot.app.runtime.register_baseline_behaviors"),
        ):
            await runtime.on_step(bot, iteration=1)

        dispatched = [command[0] for command in economy_commands.commands]
        self.assertIn("build_production", dispatched)
        status = next(
            event for event in logger.events if event["name"] == "macro.status"
        )
        self.assertEqual(status["data"]["resources"]["protected"], [0, 0])

    async def test_a_producer_idle_with_money_and_demand_is_reported(self):
        # Idle production is allowed to have a reason (saving for a protected
        # timing, nothing it builds being wanted). Idle with Marines owed and
        # minerals free is not one, and must not pass quietly.
        logger = FakeLogger()
        economy_commands = FakeEconomyCommands()
        bot = self._opening_bot(minerals=900)
        bot.build_order_runner.build_completed = True
        bot.structures = (
            *bot.structures,
            *(
                SimpleNamespace(
                    tag=tag,
                    type_id=UnitTypeId.BARRACKS,
                    position=Point2((20, 20)),
                    health_percentage=1.0,
                    is_flying=False,
                    can_attack_air=False,
                    can_attack_ground=False,
                    is_ready=True,
                    is_idle=True,
                    is_structure=True,
                )
                for tag in (101, 102, 103)
            ),
        )
        runtime = BotRuntime(logger=logger)

        with (
            patch(
                "bot.app.runtime.AresEconomyCommands",
                return_value=economy_commands,
            ),
            patch("bot.app.runtime.register_baseline_behaviors"),
        ):
            await runtime.on_step(bot, iteration=1)
            names = [event["name"] for event in logger.events]
            self.assertNotIn("macro.idle_producer_unexplained", names)

            bot.time = 220.0
            await runtime.on_step(bot, iteration=2)

        reported = [
            event
            for event in logger.events
            if event["name"] == "macro.idle_producer_unexplained"
        ]
        self.assertEqual(len(reported), 1)
        self.assertEqual(reported[0]["data"]["producer"], UnitTypeId.BARRACKS.name)
        self.assertIn(UnitTypeId.MARINE.name, reported[0]["data"]["owed_units"])

    @staticmethod
    def _opening_bot(*, minerals: int):
        costs = {
            UnitTypeId.FACTORY: SimpleNamespace(minerals=150, vespene=100),
            UnitTypeId.STARPORT: SimpleNamespace(minerals=150, vespene=100),
        }
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
        return SimpleNamespace(
            time=200.0,
            minerals=minerals,
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
            calculate_cost=lambda item: costs.get(
                item, SimpleNamespace(minerals=0, vespene=0)
            ),
            build_order_runner=SimpleNamespace(
                build_completed=False,
                build_step=0,
                build_order=(
                    SimpleNamespace(command=UnitTypeId.FACTORY),
                    SimpleNamespace(command=UnitTypeId.STARPORT),
                ),
                chosen_opening="BioThreeOneOne",
            ),
        )

    async def test_runtime_wires_stale_main_vision_to_scanner_sweep(self):
        bot = self._opening_bot(minerals=500)
        orbital = bot.structures[0]
        orbital.type_id = UnitTypeId.ORBITALCOMMAND
        orbital.energy = 100.0
        vision_commands = SimpleNamespace(
            has_vision=Mock(return_value=False),
            scan=Mock(return_value=True),
        )

        runtime = BotRuntime(logger=FakeLogger())
        with (
            patch(
                "bot.app.runtime.AresVisionCommands",
                return_value=vision_commands,
            ),
            patch(
                "bot.app.runtime.AresEconomyCommands",
                return_value=FakeEconomyCommands(),
            ),
            patch("bot.app.runtime.register_baseline_behaviors"),
        ):
            await runtime.on_step(bot, iteration=1)

        vision_commands.scan.assert_called_once_with(
            orbital_tag=999, target=Point2((90, 90))
        )

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

    async def test_runtime_does_not_redispatch_an_accepted_economic_action(
        self,
    ):
        # FakeEconomyCommands accepts every command immediately. The
        # controller may retry a WAITING action, but must never issue an
        # accepted IN_FLIGHT purchase a second time while Attention catches
        # up with the command.
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
        self.assertEqual(second_tick_commands, first_tick_commands)

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

    async def test_on_start_rerolls_opening_from_build_choices_and_announces_it(self):
        # `terran_builds.yml` sets `UseData: false`, which makes Ares' own
        # cycle logic always resolve to `Cycle[0]` (`BioThreeOneOne`) --
        # `BansheeCloak` would never be picked without this reroll.
        runner = FakeBuildOrderRunner(
            config={
                BUILD_CHOICES: {
                    "Zerg": {CYCLE: ["BioThreeOneOne", "BansheeCloak"]},
                },
            },
            chosen_opening="BioThreeOneOne",
        )
        chat = FakeChat()
        bot = SimpleNamespace(
            time=0.0,
            game_info=SimpleNamespace(map_name="PilotMap"),
            build_order_runner=runner,
            enemy_race=SimpleNamespace(name="Zerg"),
            opponent_id=None,
            chat_send=chat,
        )
        runtime = BotRuntime(
            logger=FakeLogger(), rng=SimpleNamespace(choice=lambda seq: seq[1])
        )

        await runtime.on_start(bot)

        self.assertEqual(runner.switch_calls, ["BansheeCloak"])
        self.assertEqual(
            chat.messages,
            ["Plan: Reaper expand into cloaked Banshee harass."],
        )

    async def test_on_start_announces_without_switching_when_no_build_choices(self):
        runner = FakeBuildOrderRunner(config={}, chosen_opening="BioThreeOneOne")
        chat = FakeChat()
        bot = SimpleNamespace(
            time=0.0,
            game_info=SimpleNamespace(map_name="PilotMap"),
            build_order_runner=runner,
            enemy_race=SimpleNamespace(name="Zerg"),
            opponent_id=None,
            chat_send=chat,
        )
        runtime = BotRuntime(logger=FakeLogger())

        await runtime.on_start(bot)

        self.assertEqual(runner.switch_calls, [])
        self.assertEqual(chat.messages, ["Plan: Reaper expand into Bio 3-1-1."])

    async def test_on_start_falls_back_to_a_generic_message_for_unmapped_openings(
        self,
    ):
        runner = FakeBuildOrderRunner(config={}, chosen_opening="SomeFutureBuild")
        chat = FakeChat()
        bot = SimpleNamespace(
            time=0.0,
            game_info=SimpleNamespace(map_name="PilotMap"),
            build_order_runner=runner,
            chat_send=chat,
        )
        runtime = BotRuntime(logger=FakeLogger())

        await runtime.on_start(bot)

        self.assertEqual(chat.messages, ["Plan: SomeFutureBuild."])

    async def test_macro_profile_switches_to_match_the_chosen_opening(self):
        # `MacroPlannerConfig` defaults to the Bio profile; once Ares resolves
        # `chosen_opening` to `BansheeCloak` the runtime must pick up that
        # opening's own convergence goals instead of silently keeping Bio's.
        economy_commands = FakeEconomyCommands()
        bot = SimpleNamespace(
            time=5.0,
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
            build_order_runner=SimpleNamespace(
                build_completed=False,
                build_step=0,
                build_order=(),
                chosen_opening="BansheeCloak",
            ),
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

        expected = macro_config_for_opening("BansheeCloak")
        self.assertEqual(runtime.macro_planner.config.goals.name, expected.goals.name)
        self.assertEqual(
            runtime.macro_planner.config.goals.opening_name, "BansheeCloak"
        )


if __name__ == "__main__":
    unittest.main()
