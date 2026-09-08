from __future__ import annotations

import unittest

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.behavior.scouting import ScoutExecutor
from bot.engine.missions import MissionContext, MissionOutcome
from bot.world.attention import (
    AttentionSnapshot,
    MapFacts,
    MapObservation,
    MapRoute,
    RouteWaypoint,
    UnitSnapshot,
    WorldFacts,
)
from bot.world.awareness import AwarenessService
from tests.fakes import FakeCommands


def reaper(position: Point2) -> UnitSnapshot:
    return UnitSnapshot(
        tag=7,
        unit_type=UnitTypeId.REAPER,
        position=position,
        health_percentage=1.0,
        is_flying=False,
        is_worker=False,
        can_attack_air=False,
        can_attack_ground=True,
    )


def attention(
    *, time: float, reaper_position: Point2, route: MapRoute
) -> AttentionSnapshot:
    main = Point2((80, 80))
    return AttentionSnapshot(
        WorldFacts(
            iteration=int(time),
            time=time,
            minerals=0,
            vespene=0,
            supply_used=0,
            supply_cap=0,
            own_units=(reaper(reaper_position),),
            enemy_units=(),
            map=MapFacts(
                center=Point2((50, 50)),
                own_start=Point2((10, 10)),
                enemy_starts=(main,),
                observations=(MapObservation("enemy_main", main, True),),
                routes=(route,),
            ),
        )
    )


class ReaperScoutExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_main_vision_does_not_finish_before_the_full_lap(self):
        first = Point2((75, 80))
        second = Point2((80, 85))
        route = MapRoute(
            "enemy_main",
            (RouteWaypoint(first), RouteWaypoint(second)),
        )
        commands = FakeCommands()
        service = AwarenessService()
        executor = ScoutExecutor(
            mission_id="mission-0001",
            target_key="enemy_main",
            target=Point2((80, 80)),
            started_at=10.0,
        )
        current = attention(
            time=20.0,
            reaper_position=Point2((60, 60)),
            route=route,
        )

        result = await executor.step(
            MissionContext(
                attention=current,
                awareness=service.update(current),
                assigned_units=current.world.own_units,
                commands=commands,
            )
        )

        self.assertEqual(result.outcome, MissionOutcome.ACTIVE)
        self.assertEqual(commands.commands[0][0], "path_to")
        self.assertEqual(commands.commands[0][3], first)

    async def test_completes_only_after_reaching_every_route_waypoint(self):
        first = Point2((75, 80))
        second = Point2((80, 85))
        route = MapRoute(
            "enemy_main",
            (RouteWaypoint(first), RouteWaypoint(second)),
        )
        commands = FakeCommands()
        service = AwarenessService()
        executor = ScoutExecutor(
            mission_id="mission-0001",
            target_key="enemy_main",
            target=Point2((80, 80)),
            started_at=10.0,
        )

        at_first = attention(time=20.0, reaper_position=first, route=route)
        first_result = await executor.step(
            MissionContext(
                attention=at_first,
                awareness=service.update(at_first),
                assigned_units=at_first.world.own_units,
                commands=commands,
            )
        )
        self.assertEqual(first_result.outcome, MissionOutcome.ACTIVE)
        self.assertEqual(commands.commands[-1][3], second)

        at_second = attention(time=21.0, reaper_position=second, route=route)
        final_result = await executor.step(
            MissionContext(
                attention=at_second,
                awareness=service.update(at_second),
                assigned_units=at_second.world.own_units,
                commands=commands,
            )
        )

        self.assertEqual(final_result.outcome, MissionOutcome.COMPLETED)
        self.assertEqual(final_result.reason, "enemy_main_route_completed")


if __name__ == "__main__":
    unittest.main()
