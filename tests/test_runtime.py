from __future__ import annotations

import unittest
from types import SimpleNamespace

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.application import BotRuntime
from tests.fakes import FakeLogger


class RuntimePilotTests(unittest.IsolatedAsyncioTestCase):
    async def test_neutral_runtime_builds_snapshots_without_creating_actions(self):
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
            game_info=SimpleNamespace(
                map_center=Point2((50, 50)), map_name="PilotMap"
            ),
            unit_tag_dict={},
        )
        runtime = BotRuntime(logger=FakeLogger())

        await runtime.on_start(fake_bot)
        await runtime.on_step(fake_bot, iteration=1)

        self.assertEqual(runtime.actions.mission_summaries(), ())
        self.assertEqual(runtime.enemy_knowledge.view(updated_at=10.0).sightings, ())
