from __future__ import annotations

import unittest

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.world.awareness.enemy import (
    EnemyForceAwareness,
    EnemyForceCluster,
    EnemyForceHeuristics,
    EnemyForceTracker,
    EnemySighting,
)
from bot.world.awareness.enemy.forces.clustering import group_by_proximity


def unit(
    tag: int,
    x: float,
    y: float,
    *,
    unit_type: UnitTypeId = UnitTypeId.ROACH,
    supply_cost: float = 2.0,
    can_attack_air: bool = False,
    can_attack_ground: bool = True,
    is_worker: bool = False,
    is_structure: bool = False,
    visible_now: bool = True,
    last_seen_at: float = 100.0,
) -> EnemySighting:
    return EnemySighting(
        tag=tag,
        unit_type=unit_type,
        last_position=Point2((x, y)),
        first_seen_at=last_seen_at,
        last_seen_at=last_seen_at,
        visible_now=visible_now,
        can_attack_air=can_attack_air,
        can_attack_ground=can_attack_ground,
        is_structure=is_structure,
        is_worker=is_worker,
        supply_cost=supply_cost,
    )


def cluster_holding(forces: EnemyForceAwareness, tag: int) -> EnemyForceCluster:
    return next(cluster for cluster in forces if tag in cluster.unit_tags)


class ForceClusteringTests(unittest.TestCase):
    def test_nearby_units_group_together_and_distant_ones_apart(self):
        forces = EnemyForceTracker().update(
            (
                unit(1, 30, 30),
                unit(2, 33, 31),
                unit(3, 31, 34),
                unit(4, 70, 70),
                unit(5, 72, 70),
            ),
            now=100.0,
        )

        self.assertEqual([cluster.unit_count for cluster in forces], [3, 2])

    def test_a_strung_out_column_links_into_one_group(self):
        column = tuple(unit(tag, 10 + 6 * tag, 50) for tag in range(5))

        self.assertEqual(len(group_by_proximity(column, link_radius=7.0)), 1)

    def test_workers_and_structures_never_form_a_force(self):
        forces = EnemyForceTracker().update(
            (
                unit(
                    1,
                    30,
                    30,
                    unit_type=UnitTypeId.PROBE,
                    is_worker=True,
                    supply_cost=1.0,
                ),
                unit(
                    2,
                    31,
                    30,
                    unit_type=UnitTypeId.PHOTONCANNON,
                    is_structure=True,
                    can_attack_air=True,
                    supply_cost=0.0,
                ),
            ),
            now=100.0,
        )

        self.assertEqual(len(forces), 0)
        self.assertIsNone(forces.main)

    def test_strength_is_supply_split_by_what_each_unit_can_hit(self):
        forces = EnemyForceTracker().update(
            (
                unit(1, 30, 30),
                unit(2, 32, 30),
                unit(3, 31, 32, unit_type=UnitTypeId.HYDRALISK, can_attack_air=True),
                unit(
                    4,
                    30,
                    33,
                    unit_type=UnitTypeId.CORRUPTOR,
                    can_attack_air=True,
                    can_attack_ground=False,
                ),
            ),
            now=100.0,
        )

        (cluster,) = forces.clusters
        self.assertEqual(cluster.combat_strength, 8.0)
        self.assertEqual(cluster.anti_air_strength, 4.0)
        self.assertEqual(cluster.anti_ground_strength, 6.0)


class ForceFreshnessTests(unittest.TestCase):
    def test_confidence_falls_and_location_blurs_while_only_remembered(self):
        tracker = EnemyForceTracker()
        (seen,) = tracker.update((unit(1, 30, 30), unit(2, 32, 30)), now=100.0).clusters

        (remembered,) = tracker.update(
            (unit(1, 30, 30, visible_now=False), unit(2, 32, 30, visible_now=False)),
            now=105.0,
        ).clusters

        self.assertEqual((seen.confidence, seen.position_uncertainty), (1.0, 0.0))
        # What was seen is still what we believe exists; only confidence ages.
        self.assertEqual(remembered.combat_strength, seen.combat_strength)
        self.assertAlmostEqual(remembered.confidence, 1.0 - 5.0 / 30.0)
        self.assertAlmostEqual(remembered.position_uncertainty, 15.0)  # 3 tiles/s
        self.assertEqual(remembered.visible_unit_count, 0)
        self.assertEqual(remembered.last_observed_at, 100.0)

    def test_one_fresh_scout_does_not_make_an_old_army_read_as_fresh(self):
        army = tuple(
            unit(tag, 30 + tag % 4, 30 + tag // 4, visible_now=False, last_seen_at=85.0)
            for tag in range(10)
        )
        scout = unit(99, 31, 29, unit_type=UnitTypeId.ZERGLING, supply_cost=0.5)

        (cluster,) = EnemyForceTracker().update((*army, scout), now=100.0).clusters

        # 20 supply seen 15 s ago (freshness 0.5) outweighs 0.5 supply seen now.
        self.assertAlmostEqual(cluster.confidence, (20.0 * 0.5 + 0.5) / 20.5)


class ForceIdentityTests(unittest.TestCase):
    def test_a_cluster_keeps_its_id_while_its_units_move(self):
        tracker = EnemyForceTracker()
        before = tracker.update(
            (unit(1, 30, 30), unit(2, 32, 30), unit(3, 70, 70)), now=100.0
        )

        after = tracker.update(
            (unit(1, 45, 30), unit(2, 47, 30), unit(3, 70, 72)), now=104.0
        )

        for tag in (1, 3):
            self.assertEqual(
                cluster_holding(before, tag).cluster_id,
                cluster_holding(after, tag).cluster_id,
            )
        self.assertNotEqual(
            cluster_holding(after, 1).cluster_id, cluster_holding(after, 3).cluster_id
        )

    def test_a_new_group_gets_a_new_id(self):
        tracker = EnemyForceTracker()
        (first,) = tracker.update((unit(1, 30, 30),), now=100.0).clusters

        forces = tracker.update((unit(1, 30, 30), unit(5, 80, 20)), now=101.0)

        self.assertEqual(cluster_holding(forces, 1).cluster_id, first.cluster_id)
        self.assertNotEqual(cluster_holding(forces, 5).cluster_id, first.cluster_id)

    def test_a_group_reappearing_where_one_just_was_takes_over_its_id(self):
        tracker = EnemyForceTracker(
            EnemyForceHeuristics(match_radius=12.0, identity_memory=15.0)
        )
        (original,) = tracker.update(
            (unit(1, 30, 30), unit(2, 32, 30)), now=100.0
        ).clusters
        self.assertEqual(len(tracker.update((), now=101.0)), 0)

        (returned,) = tracker.update(
            (unit(7, 35, 30), unit(8, 37, 30)), now=110.0
        ).clusters
        tracker.update((), now=111.0)
        (unrelated,) = tracker.update((unit(9, 35, 30),), now=200.0).clusters

        self.assertEqual(returned.cluster_id, original.cluster_id)
        self.assertNotEqual(unrelated.cluster_id, original.cluster_id)


class MainForceTests(unittest.TestCase):
    def test_a_large_army_seen_a_while_ago_outranks_a_small_fresh_detachment(self):
        army = tuple(
            unit(tag, 30 + tag % 5, 30 + tag // 5, visible_now=False, last_seen_at=80.0)
            for tag in range(10)
        )
        detachment = (unit(50, 80, 80), unit(51, 82, 80))

        forces = EnemyForceTracker().update((*army, *detachment), now=100.0)

        self.assertEqual(forces.main.unit_count, 10)

    def test_fresher_evidence_wins_between_similar_forces(self):
        old = tuple(
            unit(tag, 30, 30 + tag, visible_now=False, last_seen_at=80.0)
            for tag in range(5)
        )
        fresh = tuple(unit(tag, 80, 30 + tag) for tag in range(10, 15))

        forces = EnemyForceTracker().update((*old, *fresh), now=100.0)

        self.assertIn(10, forces.main.unit_tags)


class NearQueryTests(unittest.TestCase):
    def test_near_reaches_further_for_a_cluster_that_may_have_moved(self):
        forces = EnemyForceTracker().update(
            (
                unit(1, 30, 30),
                unit(2, 70, 30, visible_now=False, last_seen_at=95.0),
            ),
            now=100.0,
        )
        midway = Point2((50, 30))  # 20 tiles from both

        # The remembered one may have moved 15 tiles toward it; the fresh one
        # is known to be where it was seen.
        self.assertEqual(
            [cluster.unit_tags for cluster in forces.near(midway, distance=6.0)],
            [(2,)],
        )
        self.assertEqual(
            [cluster.unit_tags for cluster in forces.near(midway, distance=25.0)],
            [(2,), (1,)],
        )


if __name__ == "__main__":
    unittest.main()
