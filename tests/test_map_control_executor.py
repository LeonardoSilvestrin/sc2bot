from __future__ import annotations

import unittest

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.behavior.map_control import MapControlExecutor
from bot.engine.missions import MissionContext, MissionOutcome
from bot.world.attention import (
    AttentionSnapshot,
    MapFacts,
    UnitSnapshot,
    WorldFacts,
)
from bot.world.awareness import (
    AwarenessSnapshot,
    MacroPosture,
    RelativeStrength,
    ThreatAssessment,
)
from bot.world.awareness.bases import (
    BaseAssessment,
    BaseAwareness,
    BaseSecurityLevel,
)
from bot.world.awareness.enemy import EnemyAwareness
from tests.fakes import FakeCommands

MAP = MapFacts(
    center=Point2((50, 50)),
    own_start=Point2((10, 10)),
    enemy_starts=(Point2((90, 90)),),
)


def marine(tag: int, position: Point2, *, health: float = 1.0) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.MARINE,
        position=position,
        health_percentage=health,
        is_flying=False,
        is_worker=False,
        can_attack_air=True,
        can_attack_ground=True,
    )


def base_awareness(
    security: BaseSecurityLevel = BaseSecurityLevel.SAFE,
) -> BaseAwareness:
    return BaseAwareness(
        (
            BaseAssessment(
                base_id="base:1",
                position=MAP.own_start,
                is_main=True,
                threat_score=0.0 if security is BaseSecurityLevel.SAFE else 1.0,
                protection_score=0.0,
                security=security,
            ),
        )
    )


def context(
    *,
    assigned_units: tuple[UnitSnapshot, ...],
    enemy_units: tuple[UnitSnapshot, ...] = (),
    posture: MacroPosture = MacroPosture.BALANCED,
    bases: BaseAwareness | None = None,
    commands: FakeCommands,
) -> MissionContext:
    world = WorldFacts(
        iteration=1,
        time=200.0,
        minerals=0,
        vespene=0,
        supply_used=0.0,
        supply_cap=0.0,
        own_units=assigned_units,
        enemy_units=enemy_units,
        map=MAP,
    )
    awareness = AwarenessSnapshot(
        enemy=EnemyAwareness(sightings=(), locations=()),
        relative_strength=RelativeStrength(0.0, 0.0, 0, 0),
        threat=ThreatAssessment(0, 0, 0),
        updated_at=world.time,
        macro_posture=posture,
        bases=bases or base_awareness(),
    )
    return MissionContext(
        attention=AttentionSnapshot(world),
        awareness=awareness,
        assigned_units=assigned_units,
        commands=commands,
    )


class MapControlExecutorTests(unittest.IsolatedAsyncioTestCase):
    def executor(self) -> MapControlExecutor:
        return MapControlExecutor(
            mission_id="mission-0001",
            target_key="map_control:patrol",
            target=MAP.center,
            started_at=180.0,
        )

    async def test_patrols_with_safe_paths_and_never_attack_moves(self):
        commands = FakeCommands()
        squad = (
            marine(1, MAP.own_start),
            marine(2, MAP.own_start),
            marine(3, MAP.own_start),
        )

        result = await self.executor().step(
            context(assigned_units=squad, commands=commands)
        )

        self.assertEqual(result.outcome, MissionOutcome.ACTIVE)
        self.assertEqual(len(commands.commands), 3)
        self.assertEqual(
            {command[0] for command in commands.commands},
            {"safe_path_to"},
        )

    async def test_retreats_the_whole_squad_when_an_enemy_gets_close(self):
        commands = FakeCommands()
        squad = (
            marine(1, Point2((40, 40))),
            marine(2, Point2((41, 40))),
        )
        enemy = marine(100, Point2((42, 40)))

        result = await self.executor().step(
            context(
                assigned_units=squad,
                enemy_units=(enemy,),
                commands=commands,
            )
        )

        self.assertEqual(result.outcome, MissionOutcome.ACTIVE)
        self.assertEqual(result.reason, "enemy_too_close_retreating")
        self.assertTrue(
            all(command[0] == "safe_path_to" for command in commands.commands)
        )
        self.assertTrue(
            all(command[3] == MAP.own_start for command in commands.commands)
        )

    async def test_finishes_safely_after_a_damaged_squad_reaches_home(self):
        commands = FakeCommands()
        damaged = (marine(1, MAP.own_start, health=0.5),)

        result = await self.executor().step(
            context(assigned_units=damaged, commands=commands)
        )

        self.assertEqual(result.outcome, MissionOutcome.ACTIVE)
        self.assertEqual(result.reason, "squad_health_low_holding_home")
        self.assertEqual(commands.commands, [])

    async def test_strategic_defense_posture_sends_the_squad_home(self):
        commands = FakeCommands()
        squad = (marine(1, Point2((40, 40))),)

        result = await self.executor().step(
            context(
                assigned_units=squad,
                posture=MacroPosture.DEFENSE,
                commands=commands,
            )
        )

        self.assertEqual(result.reason, "strategic_danger_retreating")
        self.assertEqual(commands.commands[0][3], MAP.own_start)

    async def test_fails_if_the_assigned_squad_disappears(self):
        commands = FakeCommands()

        result = await self.executor().step(
            context(assigned_units=(), commands=commands)
        )

        self.assertEqual(result.outcome, MissionOutcome.ACTIVE)
        self.assertEqual(result.reason, "waiting_for_squad_members")


if __name__ == "__main__":
    unittest.main()
