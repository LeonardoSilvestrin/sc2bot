from __future__ import annotations

import unittest

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.attention.models import (
    AttentionSnapshot,
    MapFacts,
    MapObservation,
    UnitSnapshot,
    WorldFacts,
)
from bot.awareness import AwarenessService, MacroPosture


def unit(tag: int, unit_type: UnitTypeId, *, enemy_air_attack: bool = False):
    return UnitSnapshot(
        tag=tag,
        unit_type=unit_type,
        position=Point2((10, 10)),
        health_percentage=1.0,
        is_flying=False,
        is_worker=False,
        can_attack_air=enemy_air_attack,
        can_attack_ground=True,
    )


class AwarenessServiceTests(unittest.TestCase):
    def test_derives_relative_strength_and_known_anti_air(self):
        world = WorldFacts(
            iteration=1,
            time=30.0,
            minerals=50,
            vespene=0,
            supply_used=15,
            supply_cap=23,
            own_units=(unit(1, UnitTypeId.MARINE), unit(2, UnitTypeId.MARINE)),
            enemy_units=(unit(3, UnitTypeId.HYDRALISK, enemy_air_attack=True),),
            map=MapFacts(
                center=Point2((50, 50)),
                own_start=Point2((10, 10)),
                enemy_starts=(Point2((90, 90)),),
            ),
        )

        snapshot = AwarenessService().update(AttentionSnapshot(world))

        self.assertGreater(snapshot.relative_strength.score, 0)
        self.assertEqual(snapshot.threat.known_anti_air_units, 1)
        self.assertEqual(snapshot.threat.near_own_base_enemy_combat_units, 1)
        self.assertEqual(snapshot.macro_posture, MacroPosture.DEFENSE)

    def test_defense_posture_releases_only_after_safe_window(self):
        service = AwarenessService(defense_release_after=10.0, posture_min_hold=0.0)

        def observed(time: float, enemies: tuple[UnitSnapshot, ...]):
            return service.update(
                AttentionSnapshot(
                    WorldFacts(
                        iteration=int(time),
                        time=time,
                        minerals=50,
                        vespene=0,
                        supply_used=15,
                        supply_cap=23,
                        own_units=(unit(1, UnitTypeId.MARINE),),
                        enemy_units=enemies,
                        map=MapFacts(
                            center=Point2((50, 50)),
                            own_start=Point2((10, 10)),
                            enemy_starts=(Point2((90, 90)),),
                        ),
                    )
                )
            )

        danger = observed(30.0, (unit(2, UnitTypeId.ZERGLING),))
        still_defending = observed(35.0, ())
        released = observed(41.0, ())

        self.assertEqual(danger.macro_posture, MacroPosture.DEFENSE)
        self.assertEqual(still_defending.macro_posture, MacroPosture.DEFENSE)
        self.assertEqual(released.macro_posture, MacroPosture.RECOVERY)

    def test_location_freshness_is_typed_and_persistent(self):
        target = Point2((80, 80))
        service = AwarenessService(location_stale_after=90.0)

        def snapshot(time: float, visible: bool):
            facts = WorldFacts(
                iteration=int(time),
                time=time,
                minerals=0,
                vespene=0,
                supply_used=0,
                supply_cap=0,
                own_units=(),
                enemy_units=(),
                map=MapFacts(
                    center=Point2((50, 50)),
                    own_start=Point2((10, 10)),
                    enemy_starts=(Point2((90, 90)),),
                    observations=(MapObservation("enemy_natural", target, visible),),
                ),
            )
            return service.update(AttentionSnapshot(facts))

        fresh = snapshot(10.0, True).enemy.location("enemy_natural")
        under_fog = snapshot(50.0, False).enemy.location("enemy_natural")
        stale = snapshot(100.0, False).enemy.location("enemy_natural")

        self.assertEqual(fresh.last_observed_at, 10.0)
        self.assertFalse(under_fog.is_stale)
        self.assertEqual(under_fog.age, 40.0)
        self.assertTrue(stale.is_stale)
        self.assertEqual(stale.confidence, 0.0)
