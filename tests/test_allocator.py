from __future__ import annotations

import unittest
from dataclasses import replace

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.engine.missions import UnitAllocator, UnitRequirement
from bot.world.observation.models import UnitSnapshot


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
