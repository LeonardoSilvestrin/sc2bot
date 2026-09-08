from __future__ import annotations

import unittest

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.world.knowledge.enemy import EnemyAwareness, EnemyKnowledge
from bot.world.observation import MapFacts, UnitSnapshot, WorldFacts


def world(
    time: float,
    enemies: tuple[UnitSnapshot, ...],
    *,
    structures: tuple[UnitSnapshot, ...] = (),
) -> WorldFacts:
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
        enemy_structures=structures,
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


def enemy_structure(tag: int, unit_type: UnitTypeId) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=unit_type,
        position=Point2((80 + tag, 80)),
        health_percentage=1.0,
        is_flying=False,
        is_worker=False,
        can_attack_air=False,
        can_attack_ground=False,
        is_structure=True,
    )


class EnemyKnowledgeTests(unittest.TestCase):
    def test_reports_known_enemy_base_and_structure_counts(self):
        sightings = EnemyKnowledge().update(
            world(
                10.0,
                (),
                structures=(
                    enemy_structure(1, UnitTypeId.HATCHERY),
                    enemy_structure(2, UnitTypeId.LAIR),
                    enemy_structure(3, UnitTypeId.SPAWNINGPOOL),
                ),
            )
        )
        awareness = EnemyAwareness(sightings=sightings, locations=())

        self.assertEqual(awareness.known_base_count, 2)
        self.assertEqual(awareness.known_structure_count, 3)

    def test_tracks_first_and_last_seen_while_visible(self):
        knowledge = EnemyKnowledge()
        knowledge.update(
            world(10.0, (hydralisk(visible=True, position=Point2((30, 30))),))
        )

        view = knowledge.update(
            world(12.0, (hydralisk(visible=True, position=Point2((31, 30))),))
        )
        sighting = next(item for item in view if item.tag == 77)

        self.assertEqual(sighting.first_seen_at, 10.0)
        self.assertEqual(sighting.last_seen_at, 12.0)
        self.assertEqual(sighting.last_position, Point2((31, 30)))
        self.assertTrue(sighting.visible_now)

    def test_keeps_last_known_position_while_ares_still_remembers_it(self):
        """Ares keeps reporting an out-of-vision unit (visible_now=False) for
        a while after it leaves vision -- see UnitMemoryManager's ~30s ghost
        expiry. While Ares still reports the tag, the sighting survives with
        its last known position and does not forget when it was first seen.
        """

        knowledge = EnemyKnowledge()
        knowledge.update(
            world(10.0, (hydralisk(visible=True, position=Point2((30, 30))),))
        )

        view = knowledge.update(
            world(15.0, (hydralisk(visible=False, position=Point2((30, 30))),))
        )
        sighting = next(item for item in view if item.tag == 77)

        self.assertEqual(sighting.first_seen_at, 10.0)
        self.assertEqual(sighting.last_position, Point2((30, 30)))
        self.assertFalse(sighting.visible_now)

    def test_does_not_advance_last_seen_while_only_remembered(self):
        knowledge = EnemyKnowledge()
        knowledge.update(
            world(10.0, (hydralisk(visible=True, position=Point2((30, 30))),))
        )
        knowledge.update(
            world(15.0, (hydralisk(visible=False, position=Point2((30, 30))),))
        )

        view = knowledge.update(
            world(20.0, (hydralisk(visible=False, position=Point2((30, 30))),))
        )
        sighting = next(item for item in view if item.tag == 77)

        self.assertEqual(sighting.last_seen_at, 10.0)

    def test_drops_sighting_once_ares_stops_reporting_it_at_all(self):
        """Once a tag no longer appears at all -- Ares confirmed it destroyed,
        or its own out-of-vision memory expired -- the sighting is dropped
        instead of being remembered forever.
        """

        knowledge = EnemyKnowledge()
        knowledge.update(
            world(10.0, (hydralisk(visible=True, position=Point2((30, 30))),))
        )

        view = knowledge.update(world(45.0, ()))

        self.assertEqual(tuple(item.tag for item in view), ())

    def test_captures_a_memory_only_unit_never_seen_visible_by_this_runtime(self):
        """Ares can expose a memory unit before this runtime ever saw it
        visible (e.g. on startup, or after a game load)."""

        knowledge = EnemyKnowledge()

        view = knowledge.update(
            world(5.0, (hydralisk(visible=False, position=Point2((30, 30))),))
        )
        sighting = next(item for item in view if item.tag == 77)

        self.assertEqual(sighting.first_seen_at, 5.0)
        self.assertEqual(sighting.last_seen_at, 5.0)
        self.assertFalse(sighting.visible_now)


if __name__ == "__main__":
    unittest.main()
