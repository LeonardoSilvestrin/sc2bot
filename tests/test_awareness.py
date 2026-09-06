from __future__ import annotations

import unittest

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.attention.models import MapFacts, UnitSnapshot, WorldFacts
from bot.awareness import AwarenessService
from bot.knowledge import EnemyKnowledge


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

        knowledge = EnemyKnowledge().update(world)
        snapshot = AwarenessService().update(world, knowledge)

        self.assertGreater(snapshot.relative_strength.score, 0)
        self.assertEqual(snapshot.threat.known_anti_air_units, 1)
