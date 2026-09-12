from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bot.app.frame import FrameProcessor
from tests.fakes import FakeLogger


class FrameProcessorOrderTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_frame_runs_its_steps_in_the_documented_order(self):
        # The order is behavior, not presentation: vision needs collected
        # before it resolves, leases synced before macro reads the frame,
        # diagnostics after both domains acted. See "Frame lifecycle" in
        # _botdev/architecture/contracts.md.
        calls: list[str] = []

        def record(name, result=None):
            def call(*args, **kwargs):
                calls.append(name)
                return result

            return call

        class Planner:
            def __init__(self, name: str) -> None:
                self.name = name

            def propose(self, attention, awareness):
                calls.append(f"propose:{self.name}")
                return (f"proposal:{self.name}",)

        async def missions_tick(**kwargs):
            calls.append("missions.tick")
            proposals.append(kwargs["proposals"])

        proposals: list[tuple] = []
        logger = FakeLogger()
        processor = FrameProcessor(
            logger=logger,
            world_observer=SimpleNamespace(
                world_facts=record("observe", SimpleNamespace(time=42.0))
            ),
            awareness=SimpleNamespace(
                update=record(
                    "awareness.update",
                    SimpleNamespace(belief_changes=("belief moved",), updated_at=42.0),
                )
            ),
            vision=SimpleNamespace(
                begin_frame=record("vision.begin_frame"),
                resolve=record("vision.resolve"),
            ),
            services=SimpleNamespace(),
            scouting_vision=SimpleNamespace(tick=record("scouting_vision.tick")),
            mission_planners=(Planner("intel"), Planner("standing")),
            missions=SimpleNamespace(allocator=object(), tick=missions_tick),
            macro_planner=SimpleNamespace(
                propose=record("macro_planner.propose", ()), last_status=None
            ),
            economy=SimpleNamespace(step=record("economy.step")),
            macro_diagnostics=SimpleNamespace(
                report=record("macro_diagnostics.report")
            ),
            telemetry=SimpleNamespace(report=record("telemetry.report")),
            spatial_debug=SimpleNamespace(
                enabled=True, render=record("spatial_debug.render")
            ),
        )

        with (
            patch("bot.app.frame.AresVisionCommands"),
            patch("bot.app.frame.AresMissionCommands"),
            patch("bot.app.frame.AresEconomyCommands"),
            patch(
                "bot.app.frame.register_baseline_behaviors",
                side_effect=record("register_baseline_behaviors"),
            ),
        ):
            await processor.process(SimpleNamespace(), iteration=7)

        self.assertEqual(
            calls,
            [
                "observe",
                "awareness.update",
                "vision.begin_frame",
                "scouting_vision.tick",
                "propose:intel",
                "propose:standing",
                "vision.resolve",
                "register_baseline_behaviors",
                "missions.tick",
                "macro_planner.propose",
                "economy.step",
                "macro_diagnostics.report",
                "spatial_debug.render",
                "telemetry.report",
            ],
        )
        self.assertEqual(proposals, [("proposal:intel", "proposal:standing")])
        self.assertEqual(
            [event["name"] for event in logger.events], ["awareness.belief_changed"]
        )


if __name__ == "__main__":
    unittest.main()
