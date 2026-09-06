from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.application import BotRuntime
from bot.ego import MissionStatus
from tests.fakes import FakeCommands, FakeLogger


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

    async def test_runtime_wires_unknown_to_scout_and_new_vision_to_completion(self):
        target = Point2((80, 80))
        commands = FakeCommands()
        bot = SimpleNamespace(
            time=10.0,
            minerals=400,
            vespene=0,
            supply_used=16,
            supply_cap=23,
            units=tuple(worker(tag) for tag in range(1, 17)),
            structures=(),
            enemy_units=(),
            enemy_structures=(),
            worker_type=UnitTypeId.SCV,
            start_location=Point2((10, 10)),
            enemy_start_locations=[Point2((90, 90))],
            game_info=SimpleNamespace(map_center=Point2((50, 50)), map_name="PilotMap"),
            mediator=SimpleNamespace(
                get_enemy_nat=target,
                get_unit_role_dict={"GATHERING": set(range(1, 17))},
            ),
            target_visible=False,
        )
        bot.is_visible = lambda position: bot.target_visible and position == target
        runtime = BotRuntime(logger=FakeLogger())

        with (
            patch(
                "bot.application.runtime.AresMissionCommands",
                return_value=commands,
            ),
            patch("bot.application.runtime.register_baseline_behaviors"),
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
