from __future__ import annotations

import unittest

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.world.attention import MapFacts, MapObservation, UnitSnapshot, WorldFacts
from bot.world.awareness.enemy import (
    EnemyBaseMemory,
    EnemyBaseStatus,
    scouting_coverage,
)

NATURAL = Point2((80, 80))
THIRD = Point2((60, 90))
OWN_START = Point2((10, 10))


def world(
    time: float,
    *,
    expansions: tuple[MapObservation, ...],
    enemy_structures: tuple[UnitSnapshot, ...] = (),
) -> WorldFacts:
    return WorldFacts(
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
            own_start=OWN_START,
            enemy_starts=(Point2((90, 90)),),
            expansions=expansions,
        ),
        enemy_structures=enemy_structures,
    )


def enemy_townhall(tag: int, position: Point2) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.HATCHERY,
        position=position,
        health_percentage=1.0,
        is_flying=False,
        is_worker=False,
        can_attack_air=False,
        can_attack_ground=False,
        is_structure=True,
        visible_now=True,
    )


class EnemyBaseMemoryTests(unittest.TestCase):
    def test_unseen_slot_is_unknown_with_zero_confidence(self):
        memory = EnemyBaseMemory()

        observations = memory.update(
            world(10.0, expansions=(MapObservation("expansion:0", NATURAL, False),))
        )

        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].status, EnemyBaseStatus.UNKNOWN)
        self.assertEqual(observations[0].confidence, 0.0)

    def test_confirms_a_base_when_an_enemy_townhall_is_seen_on_the_slot(self):
        memory = EnemyBaseMemory()

        observations = memory.update(
            world(
                10.0,
                expansions=(MapObservation("expansion:0", NATURAL, True),),
                enemy_structures=(enemy_townhall(1, NATURAL),),
            )
        )

        self.assertEqual(observations[0].status, EnemyBaseStatus.CONFIRMED)
        self.assertEqual(observations[0].last_confirmed_at, 10.0)
        self.assertEqual(observations[0].confidence, 1.0)

    def test_disproves_a_base_when_the_slot_is_seen_empty(self):
        memory = EnemyBaseMemory()

        observations = memory.update(
            world(10.0, expansions=(MapObservation("expansion:0", NATURAL, True),))
        )

        self.assertEqual(observations[0].status, EnemyBaseStatus.EMPTY)

    def test_confirmed_base_stays_in_memory_once_vision_is_lost(self):
        """A base confirmed once should not silently revert to UNKNOWN just
        because Ares stopped reporting the townhall's tag (out of vision) --
        it stays CONFIRMED, only its confidence should age."""

        memory = EnemyBaseMemory(stale_after=60.0)
        memory.update(
            world(
                10.0,
                expansions=(MapObservation("expansion:0", NATURAL, True),),
                enemy_structures=(enemy_townhall(1, NATURAL),),
            )
        )

        later = memory.update(
            world(40.0, expansions=(MapObservation("expansion:0", NATURAL, False),))
        )

        self.assertEqual(later[0].status, EnemyBaseStatus.CONFIRMED)
        self.assertFalse(later[0].is_stale)
        self.assertLess(later[0].confidence, 1.0)
        self.assertGreater(later[0].confidence, 0.0)

        much_later = memory.update(
            world(500.0, expansions=(MapObservation("expansion:0", NATURAL, False),))
        )
        self.assertEqual(much_later[0].status, EnemyBaseStatus.CONFIRMED)
        self.assertTrue(much_later[0].is_stale)
        self.assertEqual(much_later[0].confidence, 0.0)

    def test_excludes_slots_occupied_by_our_own_bases(self):
        memory = EnemyBaseMemory()

        observations = memory.update(
            world(
                10.0,
                expansions=(
                    MapObservation("expansion:own", OWN_START, True),
                    MapObservation("expansion:natural", NATURAL, True),
                ),
            )
        )

        self.assertEqual(tuple(o.key for o in observations), ("expansion:natural",))


class ScoutingCoverageTests(unittest.TestCase):
    def test_defaults_to_full_coverage_when_no_expansion_data_available(self):
        self.assertEqual(scouting_coverage(()), 1.0)

    def test_counts_only_recently_checked_slots(self):
        memory = EnemyBaseMemory(stale_after=30.0)
        memory.update(
            world(
                0.0,
                expansions=(
                    MapObservation("expansion:0", NATURAL, True),
                    MapObservation("expansion:1", THIRD, False),
                ),
            )
        )

        observations = memory.update(
            world(
                0.0,
                expansions=(
                    MapObservation("expansion:0", NATURAL, False),
                    MapObservation("expansion:1", THIRD, False),
                ),
            )
        )

        # Only slot 0 has actually been looked at.
        self.assertAlmostEqual(scouting_coverage(observations), 0.5)


if __name__ == "__main__":
    unittest.main()
