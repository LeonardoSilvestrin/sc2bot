from __future__ import annotations

import unittest
from dataclasses import replace

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.engine.missions import UnitAllocator, UnitRequirement
from bot.world.attention import UnitSnapshot


def marine(tag: int = 1) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.MARINE,
        position=Point2((10, 10)),
        health_percentage=1.0,
        is_flying=False,
        is_worker=False,
        can_attack_air=True,
        can_attack_ground=True,
    )


class UnitAllocatorTests(unittest.TestCase):
    def test_existing_lease_survives_external_role_becoming_unavailable(self):
        allocator = UnitAllocator()
        requirement = UnitRequirement(
            unit_types=frozenset({UnitTypeId.MARINE}), desired=1, minimum=1
        )
        allocator.sync((marine(),))
        allocator.allocate(
            mission_id="scout",
            priority=55,
            requirement=requirement,
            objective=None,
            now=0.0,
            can_preempt=False,
            commitment_seconds=5.0,
        )
        unavailable = replace(marine(), available_for_mission=False)
        allocator.sync((unavailable,))

        result = allocator.allocate(
            mission_id="scout",
            priority=55,
            requirement=requirement,
            objective=None,
            now=1.0,
            can_preempt=False,
            commitment_seconds=5.0,
        )

        self.assertTrue(result.requirements_satisfied)
        self.assertEqual(result.assigned_tags, (1,))

    def test_preemption_respects_priority_and_commitment_window(self):
        allocator = UnitAllocator(preemption_margin=10)
        allocator.sync((marine(),))
        requirement = UnitRequirement(
            unit_types=frozenset({UnitTypeId.MARINE}), desired=1, minimum=1
        )

        low = allocator.allocate(
            mission_id="attack",
            priority=60,
            requirement=requirement,
            objective=None,
            now=0.0,
            can_preempt=True,
            commitment_seconds=5.0,
        )
        protected = allocator.allocate(
            mission_id="emergency-defense",
            priority=100,
            requirement=requirement,
            objective=None,
            now=2.0,
            can_preempt=True,
            commitment_seconds=5.0,
        )
        transferred = allocator.allocate(
            mission_id="emergency-defense",
            priority=100,
            requirement=requirement,
            objective=None,
            now=6.0,
            can_preempt=True,
            commitment_seconds=5.0,
        )

        self.assertTrue(low.requirements_satisfied)
        self.assertFalse(protected.requirements_satisfied)
        self.assertEqual(allocator.owner_of(1), "emergency-defense")
        self.assertEqual(transferred.transfers[0].from_mission_id, "attack")


def banshee(tag: int = 2) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.BANSHEE,
        position=Point2((10, 10)),
        health_percentage=1.0,
        is_flying=True,
        is_worker=False,
        can_attack_air=False,
        can_attack_ground=True,
    )


class PreemptionCostTests(unittest.TestCase):
    """The owner's own cost of being interrupted, on top of the margin."""

    def hold(self, allocator: UnitAllocator, *, cost: float) -> None:
        allocator.allocate(
            mission_id="air-harass",
            priority=62,
            requirement=UnitRequirement(
                unit_types=frozenset({UnitTypeId.BANSHEE}), desired=1, minimum=1
            ),
            objective=None,
            now=0.0,
            can_preempt=True,
            commitment_seconds=1.0,
            preemption_cost=cost,
        )

    def take(self, allocator: UnitAllocator, *, priority: int):
        return allocator.allocate(
            mission_id="defense",
            priority=priority,
            requirement=UnitRequirement(
                unit_types=frozenset({UnitTypeId.BANSHEE}), desired=1, minimum=1
            ),
            objective=None,
            now=5.0,
            can_preempt=True,
            commitment_seconds=1.0,
        )

    def test_a_costly_owner_needs_more_than_the_bare_margin(self):
        allocator = UnitAllocator(preemption_margin=10)
        allocator.sync((banshee(),))
        self.hold(allocator, cost=5.0)

        # 62 + margin 10 = 72 clears the margin but not the extra cost.
        self.assertFalse(self.take(allocator, priority=75).requirements_satisfied)
        self.assertEqual(allocator.owner_of(2), "air-harass")

    def test_defense_priority_still_clears_a_costly_owner(self):
        allocator = UnitAllocator(preemption_margin=10)
        allocator.sync((banshee(),))
        self.hold(allocator, cost=5.0)

        self.assertTrue(self.take(allocator, priority=85).requirements_satisfied)
        self.assertEqual(allocator.owner_of(2), "defense")

    def test_a_zero_cost_owner_behaves_exactly_as_before(self):
        allocator = UnitAllocator(preemption_margin=10)
        allocator.sync((banshee(),))
        self.hold(allocator, cost=0.0)

        self.assertTrue(self.take(allocator, priority=72).requirements_satisfied)


class UnitUtilityTests(unittest.TestCase):
    """Which unit a mission gets, when priority does not settle it."""

    def test_the_most_useful_matching_unit_is_taken_first(self):
        allocator = UnitAllocator()
        allocator.sync((marine(1), banshee(2)))

        result = allocator.allocate(
            mission_id="defense",
            priority=85,
            requirement=UnitRequirement(
                unit_types=frozenset({UnitTypeId.MARINE, UnitTypeId.BANSHEE}),
                desired=1,
                minimum=1,
                type_desirability=(
                    (UnitTypeId.BANSHEE, 1.0),
                    (UnitTypeId.MARINE, 0.2),
                ),
            ),
            objective=None,
            now=0.0,
            can_preempt=False,
            commitment_seconds=1.0,
        )

        self.assertEqual(result.assigned_tags, (2,))

    def test_a_zero_utility_unit_is_never_leased(self):
        """Mutalisks overhead: do not even ask for the Banshee."""

        allocator = UnitAllocator()
        allocator.sync((banshee(2),))

        result = allocator.allocate(
            mission_id="defense",
            priority=95,
            requirement=UnitRequirement(
                unit_types=frozenset({UnitTypeId.BANSHEE}),
                desired=1,
                minimum=1,
                type_desirability=((UnitTypeId.BANSHEE, 0.0),),
            ),
            objective=None,
            now=0.0,
            can_preempt=True,
            commitment_seconds=1.0,
        )

        self.assertFalse(result.requirements_satisfied)
        self.assertIsNone(allocator.owner_of(2))
