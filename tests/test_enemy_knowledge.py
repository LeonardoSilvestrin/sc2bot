from __future__ import annotations

import unittest

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.attention.models import MapFacts, UnitSnapshot, WorldFacts
from bot.awareness.enemy import EnemyKnowledge


def world(time: float, enemies: tuple[UnitSnapshot, ...]) -> WorldFacts:
    return WorldFacts(
        iteration=int(time),
        time=time,
        minerals=0,
        vespene=0,
        supply_used=0,
        supply_cap=0,
        own_units=(),
        enemy_units=enemies,
        map=MapFacts(Point2((50, 50)), Point2((10, 10)), (Point2((90, 90)),)),
    )


def hydralisk(*, visible: bool, position: Point2) -> UnitSnapshot:
    return UnitSnapshot(
        tag=77,
        unit_type=UnitTypeId.HYDRALISK,
        position=position,
        health_percentage=1.0,
        is_flying=False,
        is_worker=False,
        can_attack_air=True,
        can_attack_ground=True,
        visible_now=visible,
    )


class EnemyKnowledgeTests(unittest.TestCase):
    def test_preserves_when_and_where_enemy_was_last_seen(self):
        knowledge = EnemyKnowledge()
        knowledge.update(
            world(10.0, (hydralisk(visible=True, position=Point2((30, 30))),))
        )

        view = knowledge.update(world(15.0, ()))
        sighting = next(item for item in view if item.tag == 77)

        self.assertIsNotNone(sighting)
        self.assertEqual(sighting.first_seen_at, 10.0)
        self.assertEqual(sighting.last_seen_at, 10.0)
        self.assertEqual(sighting.last_position, Point2((30, 30)))
        self.assertFalse(sighting.visible_now)
