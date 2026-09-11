from __future__ import annotations

import unittest

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.behavior.defense import DefendBaseExecutor, DefenseAnchors, DefenseConfig
from bot.engine.missions import MissionContext, MissionOutcome
from bot.world.attention import (
    AttentionSnapshot,
    MapFacts,
    UnitSnapshot,
    WorldFacts,
)
from bot.world.awareness import (
    AwarenessSnapshot,
    RelativeStrength,
    ThreatAssessment,
)
from bot.world.awareness.bases import (
    BaseAssessment,
    BaseAwareness,
    BaseSecurityLevel,
)
from bot.world.awareness.enemy import EnemyAwareness
from tests.fakes import FakeCommands, FakeLogger

MAP = MapFacts(
    center=Point2((50, 50)),
    own_start=Point2((10, 10)),
    enemy_starts=(Point2((90, 90)),),
)
BASE = Point2((10, 10))
# Attacked from the east: the default siege anchor sits 6 out from the base.
EAST_THREAT = Point2((30, 10))
SIEGE_ANCHOR = Point2((16, 10))


def reaper(tag: int, position: Point2) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.REAPER,
        position=position,
        health_percentage=1.0,
        is_flying=False,
        is_worker=False,
        can_attack_air=False,
        can_attack_ground=True,
    )


def tank(tag: int, position: Point2, *, sieged: bool = False) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.SIEGETANKSIEGED if sieged else UnitTypeId.SIEGETANK,
        position=position,
        health_percentage=1.0,
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


def enemy_worker(tag: int, unit_type: UnitTypeId, position: Point2) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=unit_type,
        position=position,
        health_percentage=1.0,
        is_flying=False,
        is_worker=True,
        can_attack_air=False,
        can_attack_ground=False,
        visible_now=True,
    )


def held_base(position: Point2 = BASE) -> BaseAwareness:
    return BaseAwareness(
        (
            BaseAssessment(
                base_id="own_base",
                position=position,
                is_main=True,
                threat_score=1.0,
                protection_score=0.0,
                security=BaseSecurityLevel.CRITICAL,
            ),
        )
    )


def context(
    *,
    enemy_units: tuple[UnitSnapshot, ...] = (),
    assigned_units: tuple[UnitSnapshot, ...],
    commands: FakeCommands,
    time: float = 20.0,
    bases: BaseAwareness | None = None,
) -> MissionContext:
    world = WorldFacts(
        iteration=int(time),
        time=time,
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
        updated_at=time,
        bases=bases if bases is not None else BaseAwareness(),
    )
    return MissionContext(
        attention=AttentionSnapshot(world),
        awareness=awareness,
        assigned_units=assigned_units,
        commands=commands,
    )


def executor(**kwargs) -> DefendBaseExecutor:
    return DefendBaseExecutor(
        mission_id="mission-0001",
        target_key="own_base",
        target=Point2((12, 10)),
        started_at=10.0,
        **kwargs,
    )


class DefendBaseExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_attack_moves_every_assigned_defender_toward_the_nearest_threat(
        self,
    ):
        commands = FakeCommands()
        executor = DefendBaseExecutor(
            mission_id="mission-0001",
            target_key="own_base",
            target=Point2((12, 10)),
            started_at=10.0,
        )
        threat = enemy_marine(9, Point2((13, 10)))
        defenders = (reaper(1, Point2((10, 10))), reaper(2, Point2((11, 10))))

        result = await executor.step(
            context(
                enemy_units=(threat,), assigned_units=defenders, commands=commands
            )
        )

        self.assertEqual(result.outcome, MissionOutcome.ACTIVE)
        self.assertTrue(result.reason.strip())
        self.assertEqual(len(commands.commands), 2)
        for command in commands.commands:
            self.assertEqual(command[0], "attack_move")
            self.assertEqual(command[3], threat.position)

    async def test_completes_when_no_threat_remains_near_the_engagement_area(self):
        commands = FakeCommands()
        executor = DefendBaseExecutor(
            mission_id="mission-0001",
            target_key="own_base",
            target=Point2((12, 10)),
            started_at=10.0,
        )
        defender = reaper(1, Point2((10, 10)))

        result = await executor.step(
            context(assigned_units=(defender,), commands=commands)
        )

        self.assertEqual(result.outcome, MissionOutcome.COMPLETED)
        self.assertEqual(result.reason, "threat_cleared_near_own_base")
        self.assertEqual(commands.commands, [])

    async def test_enemy_workers_of_any_race_are_not_treated_as_threats(self):
        commands = FakeCommands()
        executor = DefendBaseExecutor(
            mission_id="mission-0001",
            target_key="own_base",
            target=Point2((12, 10)),
            started_at=10.0,
        )
        nearby_workers = (
            enemy_worker(91, UnitTypeId.PROBE, Point2((13, 10))),
            enemy_worker(92, UnitTypeId.DRONE, Point2((13, 10))),
            enemy_worker(93, UnitTypeId.SCV, Point2((13, 10))),
        )
        defender = reaper(1, Point2((10, 10)))

        result = await executor.step(
            context(
                enemy_units=nearby_workers,
                assigned_units=(defender,),
                commands=commands,
            )
        )

        self.assertEqual(result.outcome, MissionOutcome.COMPLETED)
        self.assertEqual(result.reason, "threat_cleared_near_own_base")
        self.assertEqual(commands.commands, [])

    async def test_fails_when_the_assigned_team_is_missing_while_a_threat_remains(
        self,
    ):
        commands = FakeCommands()
        executor = DefendBaseExecutor(
            mission_id="mission-0001",
            target_key="own_base",
            target=Point2((12, 10)),
            started_at=10.0,
        )
        threat = enemy_marine(9, Point2((13, 10)))

        result = await executor.step(
            context(enemy_units=(threat,), assigned_units=(), commands=commands)
        )

        self.assertEqual(result.outcome, MissionOutcome.FAILED)
        self.assertEqual(result.reason, "assigned_unit_missing")


class DefenseRoleTests(unittest.IsolatedAsyncioTestCase):
    """unit type x DEFENSE -> tactical role -> what the unit is told to do."""

    async def test_tanks_hold_a_siege_anchor_while_bio_screens_the_threat(self):
        commands = FakeCommands()
        defenders = (tank(1, Point2((10, 13))), reaper(2, Point2((11, 10))))

        result = await executor().step(
            context(
                enemy_units=(enemy_marine(9, EAST_THREAT),),
                assigned_units=defenders,
                commands=commands,
                bases=held_base(),
            )
        )

        self.assertEqual(result.outcome, MissionOutcome.ACTIVE)
        self.assertEqual(
            commands.commands,
            [
                ("attack_move", "mission-0001", 1, SIEGE_ANCHOR, 2.5),
                ("attack_move", "mission-0001", 2, EAST_THREAT, 2.0),
            ],
        )

    def test_anchors_keep_the_tank_behind_the_screen_toward_the_threat(self):
        config = DefenseConfig()

        far = DefenseAnchors.toward(BASE, EAST_THREAT, config)
        self.assertEqual(far.siege, SIEGE_ANCHOR)
        self.assertEqual(far.screen, Point2((22, 10)))

        # An enemy already inside the screen line squeezes both anchors back.
        close = DefenseAnchors.toward(BASE, Point2((13, 10)), config)
        self.assertLess(close.siege.distance_to(BASE), close.screen.distance_to(BASE))
        self.assertAlmostEqual(close.screen.distance_to(BASE), 3.0)

    async def test_a_tank_on_its_anchor_sieges(self):
        commands = FakeCommands()

        await executor().step(
            context(
                enemy_units=(enemy_marine(9, EAST_THREAT),),
                assigned_units=(tank(1, Point2((16, 11))),),
                commands=commands,
                bases=held_base(),
            )
        )

        self.assertEqual(
            commands.commands,
            [("use_ability", "mission-0001", 1, AbilityId.SIEGEMODE_SIEGEMODE)],
        )

    async def test_a_sieged_tank_holds_its_anchor_instead_of_chasing(self):
        commands = FakeCommands()

        # A small shift in where the attack comes from is no reason to move.
        for threat in (EAST_THREAT, Point2((30, 16))):
            await executor().step(
                context(
                    enemy_units=(enemy_marine(9, threat),),
                    assigned_units=(tank(1, SIEGE_ANCHOR, sieged=True),),
                    commands=commands,
                    bases=held_base(),
                )
            )

        self.assertEqual(commands.commands, [])

    async def test_a_sieged_tank_repositions_when_the_attack_moves_elsewhere(self):
        commands = FakeCommands()

        await executor().step(
            context(
                enemy_units=(enemy_marine(9, Point2((10, 30))),),
                assigned_units=(tank(1, SIEGE_ANCHOR, sieged=True),),
                commands=commands,
                bases=held_base(),
            )
        )

        self.assertEqual(
            commands.commands,
            [("use_ability", "mission-0001", 1, AbilityId.UNSIEGE_UNSIEGE)],
        )

    async def test_tanks_unsiege_before_the_mission_completes(self):
        commands = FakeCommands()
        defense = executor()

        packing = await defense.step(
            context(
                assigned_units=(tank(1, SIEGE_ANCHOR, sieged=True),),
                commands=commands,
            )
        )
        released = await defense.step(
            context(
                assigned_units=(tank(1, SIEGE_ANCHOR),),
                commands=commands,
                time=23.0,
            )
        )

        self.assertEqual(packing.outcome, MissionOutcome.ACTIVE)
        self.assertEqual(
            commands.commands,
            [("use_ability", "mission-0001", 1, AbilityId.UNSIEGE_UNSIEGE)],
        )
        self.assertEqual(released.outcome, MissionOutcome.COMPLETED)
        self.assertEqual(released.reason, "threat_cleared_near_own_base")

    async def test_a_tank_still_setting_up_is_not_released_mid_siege(self):
        commands = FakeCommands()
        defense = executor()
        at_anchor = Point2((16, 11))

        # Ordered to siege while the threat is still there...
        await defense.step(
            context(
                enemy_units=(enemy_marine(9, EAST_THREAT),),
                assigned_units=(tank(1, at_anchor),),
                commands=commands,
                bases=held_base(),
            )
        )
        # ...then the threat clears before the Tank is reported sieged.
        outcomes = []
        for time, sieged in ((21.0, False), (23.0, True), (26.0, False)):
            result = await defense.step(
                context(
                    assigned_units=(tank(1, at_anchor, sieged=sieged),),
                    commands=commands,
                    time=time,
                )
            )
            outcomes.append(result.outcome)

        self.assertEqual(
            outcomes,
            [MissionOutcome.ACTIVE, MissionOutcome.ACTIVE, MissionOutcome.COMPLETED],
        )
        self.assertEqual(
            [command[3] for command in commands.commands],
            [AbilityId.SIEGEMODE_SIEGEMODE, AbilityId.UNSIEGE_UNSIEGE],
        )

    async def test_release_stops_waiting_for_a_tank_after_the_unsiege_timeout(self):
        commands = FakeCommands()
        defense = executor()
        stuck = (tank(1, SIEGE_ANCHOR, sieged=True),)

        first = await defense.step(context(assigned_units=stuck, commands=commands))
        last = await defense.step(
            context(assigned_units=stuck, commands=commands, time=26.0)
        )

        self.assertEqual(first.outcome, MissionOutcome.ACTIVE)
        self.assertEqual(last.outcome, MissionOutcome.COMPLETED)
        self.assertEqual(last.reason, "threat_cleared_unsiege_timed_out")

    async def test_roles_and_tank_transitions_are_logged_once_not_every_frame(self):
        logger = FakeLogger()
        commands = FakeCommands()
        defense = executor(logger=logger)
        screen = reaper(2, Point2((11, 10)))

        # Far from the anchor, still on the way, then arrived.
        for time, position in (
            (20.0, Point2((10, 13))),
            (21.0, Point2((12, 12))),
            (22.0, Point2((16, 11))),
        ):
            await defense.step(
                context(
                    enemy_units=(enemy_marine(9, EAST_THREAT),),
                    assigned_units=(tank(1, position), screen),
                    commands=commands,
                    time=time,
                    bases=held_base(),
                )
            )

        states = [
            (event["data"]["state"], event["data"]["reason"])
            for event in logger.events
        ]
        self.assertEqual(
            states,
            [
                ("SIEGE_ANCHOR", "role_resolved_from_unit_type"),
                ("SCREEN", "role_resolved_from_unit_type"),
                ("MOVING_TO_ANCHOR", "tank_away_from_siege_anchor"),
                ("SIEGING", "tank_reached_siege_anchor"),
            ],
        )
        self.assertEqual(
            {event["component"] for event in logger.events}, {"behavior.defense"}
        )
        moving = logger.events[2]["data"]
        self.assertEqual(moving["unit_tag"], 1)
        self.assertEqual(moving["siege_anchor"], [16.0, 10.0])


if __name__ == "__main__":
    unittest.main()
