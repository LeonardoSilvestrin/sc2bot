from __future__ import annotations

import unittest

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.behavior.harass import CloakedBansheeHarassExecutor, WorkerLineHarassExecutor
from bot.engine.missions import MissionContext, MissionOutcome
from bot.world.knowledge.enemy.models import EnemyAwareness
from bot.world.knowledge.models import (
    AwarenessSnapshot,
    RelativeStrength,
    ThreatAssessment,
)
from bot.world.observation.models import (
    AttentionSnapshot,
    MapFacts,
    UnitSnapshot,
    WorldFacts,
)
from tests.fakes import FakeCommands

TARGET = Point2((80, 80))
MAP = MapFacts(
    center=Point2((50, 50)),
    own_start=Point2((10, 10)),
    enemy_starts=(Point2((90, 90)),),
)


def reaper(tag: int, position: Point2, *, health: float = 1.0) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.REAPER,
        position=position,
        health_percentage=health,
        is_flying=False,
        is_worker=False,
        can_attack_air=False,
        can_attack_ground=True,
    )


def enemy_marine(tag: int, position: Point2) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.MARINE,
        position=position,
        health_percentage=1.0,
        is_flying=False,
        is_worker=False,
        can_attack_air=False,
        can_attack_ground=True,
        visible_now=True,
    )


<<<<<<< HEAD
def enemy_worker(
    tag: int,
    unit_type: UnitTypeId,
    position: Point2,
    *,
    health: float = 1.0,
) -> UnitSnapshot:
=======
def banshee(tag: int, position: Point2) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.BANSHEE,
        position=position,
        health_percentage=1.0,
        is_flying=True,
        is_worker=False,
        can_attack_air=False,
        can_attack_ground=True,
    )


def enemy_anti_air(tag: int, position: Point2) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.MARINE,
        position=position,
        health_percentage=1.0,
        is_flying=False,
        is_worker=False,
        can_attack_air=True,
        can_attack_ground=True,
        visible_now=True,
    )


def enemy_worker(tag: int, unit_type: UnitTypeId, position: Point2) -> UnitSnapshot:
>>>>>>> agents/claude
    return UnitSnapshot(
        tag=tag,
        unit_type=unit_type,
        position=position,
        health_percentage=health,
        is_flying=False,
        is_worker=True,
        can_attack_air=False,
        can_attack_ground=False,
        visible_now=True,
    )


def context(
    *,
    enemy_units: tuple[UnitSnapshot, ...] = (),
    assigned_units: tuple[UnitSnapshot, ...],
    commands: FakeCommands,
) -> MissionContext:
    world = WorldFacts(
        iteration=1,
        time=20.0,
        minerals=0,
        vespene=0,
        supply_used=0.0,
        supply_cap=0.0,
        own_units=(),
        enemy_units=enemy_units,
        map=MAP,
    )
    awareness = AwarenessSnapshot(
        enemy=EnemyAwareness(sightings=(), locations=()),
        relative_strength=RelativeStrength(0.0, 0.0, 0, 0),
        threat=ThreatAssessment(0, 0, 0),
        updated_at=20.0,
    )
    return MissionContext(
        attention=AttentionSnapshot(world),
        awareness=awareness,
        assigned_units=assigned_units,
        commands=commands,
    )


class WorkerLineHarassExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_attack_moves_the_harasser_toward_the_target_while_active(self):
        commands = FakeCommands()
        executor = WorkerLineHarassExecutor(
            mission_id="mission-0001",
            target_key="enemy_natural",
            target=TARGET,
            started_at=10.0,
        )
        harasser = reaper(1, Point2((70, 70)))

        result = await executor.step(
            context(assigned_units=(harasser,), commands=commands)
        )

        self.assertEqual(result.outcome, MissionOutcome.ACTIVE)
        self.assertTrue(result.reason.strip())
        self.assertEqual(
            commands.commands,
            [
                (
                    "attack_move",
                    "mission-0001",
                    1,
                    TARGET,
                    executor.arrival_radius,
                )
            ],
        )

    async def test_focuses_the_lowest_health_worker_of_any_race(self):
        commands = FakeCommands()
        executor = WorkerLineHarassExecutor(
            mission_id="mission-0001",
            target_key="enemy_natural",
            target=TARGET,
            started_at=10.0,
        )
        harasser = reaper(1, Point2((79, 80)))
        worker_line = (
            enemy_worker(91, UnitTypeId.PROBE, Point2((81, 80)), health=0.8),
            enemy_worker(92, UnitTypeId.DRONE, Point2((81, 80)), health=0.2),
            enemy_worker(93, UnitTypeId.SCV, Point2((81, 80)), health=0.6),
        )

        result = await executor.step(
            context(
                enemy_units=worker_line,
                assigned_units=(harasser,),
                commands=commands,
            )
        )

        self.assertEqual(result.outcome, MissionOutcome.ACTIVE)
        self.assertEqual(
            commands.commands,
            [("attack_unit", "mission-0001", 1, 92)],
        )

    async def test_stays_aggressive_when_the_target_has_a_defender(self):
        commands = FakeCommands()
        executor = WorkerLineHarassExecutor(
            mission_id="mission-0001",
            target_key="enemy_natural",
            target=TARGET,
            started_at=10.0,
        )
        harasser = reaper(1, Point2((79, 80)))
        defender = enemy_marine(2, Point2((81, 80)))

        result = await executor.step(
            context(
                enemy_units=(defender,),
                assigned_units=(harasser,),
                commands=commands,
            )
        )

        self.assertEqual(result.outcome, MissionOutcome.ACTIVE)
        self.assertEqual(result.reason, "harassing_enemy_worker_line")
        self.assertEqual(commands.commands[0][0], "attack_move")

    async def test_critical_reaper_retreats_to_own_main(self):
        commands = FakeCommands()
        executor = WorkerLineHarassExecutor(
            mission_id="mission-0001",
            target_key="enemy_natural",
            target=TARGET,
            started_at=10.0,
        )

        result = await executor.step(
            context(
                assigned_units=(reaper(1, Point2((70, 70)), health=0.25),),
                commands=commands,
            )
        )

        self.assertEqual(result.outcome, MissionOutcome.ACTIVE)
        self.assertEqual(result.reason, "retreating_critical_reaper")
        self.assertEqual(
            commands.commands,
            [
                (
                    "safe_path_to",
                    "mission-0001",
                    1,
                    MAP.own_start,
                    executor.retreat_arrival_radius,
                    6.0,
                )
            ],
        )

    async def test_retreat_finishes_after_the_reaper_reaches_safety(self):
        commands = FakeCommands()
        executor = WorkerLineHarassExecutor(
            mission_id="mission-0001",
            target_key="enemy_natural",
            target=TARGET,
            started_at=10.0,
        )
        executor._retreating = True

        result = await executor.step(
            context(
                assigned_units=(reaper(1, Point2((12, 12)), health=0.6),),
                commands=commands,
            )
        )

        self.assertEqual(result.outcome, MissionOutcome.COMPLETED)
        self.assertEqual(result.reason, "critical_reaper_returned_to_safety")
        self.assertEqual(commands.commands, [])

    async def test_fails_when_the_assigned_unit_is_missing(self):
        commands = FakeCommands()
        executor = WorkerLineHarassExecutor(
            mission_id="mission-0001",
            target_key="enemy_natural",
            target=TARGET,
            started_at=10.0,
        )

        result = await executor.step(context(assigned_units=(), commands=commands))

        self.assertEqual(result.outcome, MissionOutcome.FAILED)
        self.assertEqual(result.reason, "assigned_unit_missing")


class CloakedBansheeHarassExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_attack_moves_and_casts_cloak_while_active(self):
        commands = FakeCommands()
        executor = CloakedBansheeHarassExecutor(
            mission_id="mission-0001",
            target_key="enemy_natural",
            target=TARGET,
            started_at=10.0,
        )
        harasser = banshee(1, Point2((70, 70)))

        result = await executor.step(
            context(assigned_units=(harasser,), commands=commands)
        )

        self.assertEqual(result.outcome, MissionOutcome.ACTIVE)
        self.assertEqual(
            commands.commands,
            [
                (
                    "use_ability",
                    "mission-0001",
                    1,
                    AbilityId.BEHAVIOR_CLOAKON_BANSHEE,
                ),
                (
                    "attack_move",
                    "mission-0001",
                    1,
                    TARGET,
                    executor.arrival_radius,
                ),
            ],
        )

    async def test_ground_only_defenders_do_not_trigger_disengage(self):
        commands = FakeCommands()
        executor = CloakedBansheeHarassExecutor(
            mission_id="mission-0001",
            target_key="enemy_natural",
            target=TARGET,
            started_at=10.0,
        )
        harasser = banshee(1, Point2((79, 80)))
        # `enemy_marine` here cannot attack air, so it cannot threaten a
        # flying, cloaked Banshee at all.
        defender = enemy_marine(2, Point2((81, 80)))

        result = await executor.step(
            context(
                enemy_units=(defender,),
                assigned_units=(harasser,),
                commands=commands,
            )
        )

        self.assertEqual(result.outcome, MissionOutcome.ACTIVE)

    async def test_completes_when_an_anti_air_defender_is_in_range(self):
        commands = FakeCommands()
        executor = CloakedBansheeHarassExecutor(
            mission_id="mission-0001",
            target_key="enemy_natural",
            target=TARGET,
            started_at=10.0,
        )
        harasser = banshee(1, Point2((79, 80)))
        defender = enemy_anti_air(2, Point2((81, 80)))

        result = await executor.step(
            context(
                enemy_units=(defender,),
                assigned_units=(harasser,),
                commands=commands,
            )
        )

        self.assertEqual(result.outcome, MissionOutcome.COMPLETED)
        self.assertEqual(result.reason, "harass_target_defended")
        self.assertEqual(commands.commands, [])

    async def test_fails_when_the_assigned_unit_is_missing(self):
        commands = FakeCommands()
        executor = CloakedBansheeHarassExecutor(
            mission_id="mission-0001",
            target_key="enemy_natural",
            target=TARGET,
            started_at=10.0,
        )

        result = await executor.step(context(assigned_units=(), commands=commands))

        self.assertEqual(result.outcome, MissionOutcome.FAILED)
        self.assertEqual(result.reason, "assigned_unit_missing")


if __name__ == "__main__":
    unittest.main()
