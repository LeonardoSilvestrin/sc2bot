from __future__ import annotations

import unittest

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.world.awareness.enemy import (
    EnemyBaseAssessment,
    EnemyBaseAssessor,
    EnemyBaseObservation,
    EnemyBaseStatus,
    EnemySighting,
)

BASE = Point2((80, 80))
MINERAL_LINE = Point2((84, 80))


def slot(
    status: EnemyBaseStatus = EnemyBaseStatus.CONFIRMED, *, confidence: float = 1.0
) -> EnemyBaseObservation:
    return EnemyBaseObservation(
        key="expansion:3",
        position=BASE,
        status=status,
        last_confirmed_at=100.0 if status is EnemyBaseStatus.CONFIRMED else None,
        last_checked_at=None if status is EnemyBaseStatus.UNKNOWN else 100.0,
        confidence=confidence,
        stale_after=120.0,
        is_stale=confidence <= 0.0,
    )


def sighting(
    tag: int,
    unit_type: UnitTypeId,
    *,
    position: Point2 = BASE,
    is_worker: bool = False,
    is_structure: bool = False,
    can_attack_air: bool = False,
    can_attack_ground: bool = False,
    visible_now: bool = True,
    last_seen_at: float = 100.0,
    supply_cost: float = 0.0,
) -> EnemySighting:
    return EnemySighting(
        tag=tag,
        unit_type=unit_type,
        last_position=position,
        first_seen_at=last_seen_at,
        last_seen_at=last_seen_at,
        visible_now=visible_now,
        can_attack_air=can_attack_air,
        can_attack_ground=can_attack_ground,
        is_structure=is_structure,
        is_worker=is_worker,
        supply_cost=supply_cost,
    )


def workers(
    count: int, *, visible: int | None = None, first_tag: int = 1
) -> tuple[EnemySighting, ...]:
    """``count`` drones on the mineral line, the first ``visible`` in vision."""

    visible = count if visible is None else visible
    return tuple(
        sighting(
            first_tag + index,
            UnitTypeId.DRONE,
            position=MINERAL_LINE,
            is_worker=True,
            visible_now=index < visible,
            supply_cost=1.0,
        )
        for index in range(count)
    )


def spore(tag: int, *, last_seen_at: float = 100.0) -> EnemySighting:
    return sighting(
        tag,
        UnitTypeId.SPORECRAWLER,
        is_structure=True,
        can_attack_air=True,
        last_seen_at=last_seen_at,
    )


def roach(tag: int, *, position: Point2 = BASE) -> EnemySighting:
    return sighting(
        tag,
        UnitTypeId.ROACH,
        position=position,
        can_attack_ground=True,
        supply_cost=2.0,
    )


def hydralisk(tag: int) -> EnemySighting:
    return sighting(
        tag,
        UnitTypeId.HYDRALISK,
        can_attack_air=True,
        can_attack_ground=True,
        supply_cost=2.0,
    )


def assess(
    sightings: tuple[EnemySighting, ...],
    observation: EnemyBaseObservation | None = None,
    *,
    now: float = 100.0,
    assessor: EnemyBaseAssessor | None = None,
) -> EnemyBaseAssessment:
    awareness = (assessor or EnemyBaseAssessor()).update(
        observations=(observation or slot(),), sightings=sightings, now=now
    )
    return awareness.assessments[0]


class EnemyBaseEconomicValueTests(unittest.TestCase):
    def test_only_a_confirmed_base_has_economic_value(self):
        for status in (EnemyBaseStatus.EMPTY, EnemyBaseStatus.UNKNOWN):
            with self.subTest(status=status.name):
                self.assertEqual(assess(workers(16), slot(status)).economic_value, 0.0)

        self.assertAlmostEqual(assess(workers(16)).economic_value, 1.0)

    def test_counted_workers_add_to_the_value_of_presence_alone(self):
        half_saturated = assess(workers(8))

        self.assertAlmostEqual(assess(()).economic_value, 0.4)
        self.assertAlmostEqual(half_saturated.economic_value, 0.7)
        self.assertEqual(half_saturated.worker_count_estimate, 8)

    def test_a_sweep_counts_remembered_workers_not_only_visible_ones(self):
        self.assertEqual(assess(workers(10, visible=3)).worker_count_estimate, 10)

    def test_the_worker_count_outlives_the_worker_sightings(self):
        """Ares forgets an out-of-vision worker after ~30 s; the count of that
        mineral line stays the best estimate until the base is looked at again."""

        assessor = EnemyBaseAssessor()
        assess(workers(12), now=100.0, assessor=assessor)

        later = assess((), slot(confidence=0.5), now=160.0, assessor=assessor)

        self.assertEqual(later.worker_count_estimate, 12)
        self.assertEqual(later.workers_counted_at, 100.0)

    def test_a_slot_seen_empty_forgets_its_worker_count(self):
        assessor = EnemyBaseAssessor()
        assess(workers(12), assessor=assessor)

        emptied = assess(
            (), slot(EnemyBaseStatus.EMPTY), now=150.0, assessor=assessor
        )

        self.assertEqual(emptied.worker_count_estimate, 0)
        self.assertIsNone(emptied.workers_counted_at)

    def test_staleness_lowers_confidence_not_economic_value(self):
        assessor = EnemyBaseAssessor()
        assess(workers(18), assessor=assessor)

        stale = assess((), slot(confidence=0.0), now=400.0, assessor=assessor)

        self.assertEqual(stale.worker_count_estimate, 18)
        self.assertAlmostEqual(stale.economic_value, 1.0)
        self.assertEqual(stale.confidence, 0.0)
        self.assertTrue(stale.is_stale)


class EnemyBaseDefenseTests(unittest.TestCase):
    def test_air_and_ground_defense_are_read_separately(self):
        base = assess(
            (spore(1), roach(2), roach(3), roach(4), *workers(16, first_tag=10))
        )

        self.assertAlmostEqual(base.air_defense, 0.25)  # one spore: 2 of 8
        self.assertAlmostEqual(base.ground_defense, 0.75)  # three roaches: 6 of 8

    def test_a_unit_that_hits_both_counts_toward_both(self):
        base = assess((hydralisk(1),))

        self.assertAlmostEqual(base.air_defense, 0.25)
        self.assertAlmostEqual(base.ground_defense, 0.25)

    def test_defenders_away_from_the_base_do_not_count(self):
        far_roach = roach(1, position=Point2((80, 100)))

        self.assertEqual(assess((far_roach,)).ground_defense, 0.0)

    def test_defender_age_lowers_defense_confidence_not_defense(self):
        recent = assess((spore(1), roach(2)), now=115.0)
        old = assess((spore(1), roach(2)), now=400.0)

        for base in (recent, old):
            self.assertAlmostEqual(base.air_defense, 0.25)  # the spore: 2 of 8
            self.assertAlmostEqual(base.ground_defense, 0.25)  # the roach: 2 of 8
        # 15 s unseen: half stale for a unit (30 s), barely for a structure.
        self.assertAlmostEqual(recent.ground_defense_confidence, 0.5)
        self.assertAlmostEqual(recent.air_defense_confidence, 1.0 - 15.0 / 180.0)
        self.assertEqual(old.air_defense_confidence, 0.0)
        self.assertEqual(old.ground_defense_confidence, 0.0)

    def test_each_defense_confidence_weighs_only_its_own_defenders(self):
        # A spore seen just now and a hydralisk seen 15 s ago share the air
        # reading; only the hydralisk stands behind the ground one.
        base = assess((spore(1, last_seen_at=115.0), hydralisk(2)), now=115.0)

        self.assertAlmostEqual(
            base.air_defense_confidence, (2.0 * 1.0 + 2.0 * 0.5) / 4.0
        )
        self.assertAlmostEqual(base.ground_defense_confidence, 0.5)

    def test_no_defender_seen_is_as_current_as_the_last_look_at_the_slot(self):
        base = assess((), slot(confidence=0.4))

        self.assertEqual((base.air_defense, base.ground_defense), (0.0, 0.0))
        self.assertEqual(
            (base.air_defense_confidence, base.ground_defense_confidence),
            (0.4, 0.4),
        )


if __name__ == "__main__":
    unittest.main()
