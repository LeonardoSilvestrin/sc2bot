from __future__ import annotations

import unittest
from dataclasses import replace

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.behavior.map_control import MapControlPlanner, MapControlPlannerConfig
from bot.engine.missions import MissionKind
from bot.world.knowledge.bases.models import BaseAwareness
from bot.world.knowledge.enemy.models import EnemyAwareness
from bot.world.knowledge.models import (
    AwarenessSnapshot,
    MacroPosture,
    RelativeStrength,
    ThreatAssessment,
)
from bot.world.observation.models import (
    AttentionSnapshot,
    MapFacts,
    UnitSnapshot,
    WorldFacts,
)

MAP = MapFacts(
    center=Point2((50, 50)),
    own_start=Point2((10, 10)),
    enemy_starts=(Point2((90, 90)),),
)


def marine(
    tag: int,
    *,
    available: bool = True,
    health: float = 1.0,
) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.MARINE,
        position=Point2((10, 10)),
        health_percentage=health,
        is_flying=False,
        is_worker=False,
        can_attack_air=True,
        can_attack_ground=True,
        available_for_mission=available,
    )


def enemy_marine(tag: int) -> UnitSnapshot:
    return replace(marine(tag), position=Point2((50, 50)))


def attention(now: float, *, marines: int = 6, enemies: int = 0) -> AttentionSnapshot:
    return AttentionSnapshot(
        WorldFacts(
            iteration=int(now),
            time=now,
            minerals=0,
            vespene=0,
            supply_used=float(marines),
            supply_cap=200.0,
            own_units=tuple(marine(tag) for tag in range(1, marines + 1)),
            enemy_units=tuple(enemy_marine(100 + tag) for tag in range(enemies)),
            map=MAP,
        )
    )


def awareness(
    now: float,
    *,
    posture: MacroPosture = MacroPosture.BALANCED,
) -> AwarenessSnapshot:
    return AwarenessSnapshot(
        enemy=EnemyAwareness(sightings=(), locations=()),
        relative_strength=RelativeStrength(0.0, 0.0, 0, 0),
        threat=ThreatAssessment(0, 0, 0),
        updated_at=now,
        macro_posture=posture,
        bases=BaseAwareness(),
    )


class MapControlPlannerConfigTests(unittest.TestCase):
    def test_rejects_a_minimum_larger_than_the_desired_squad(self):
        with self.assertRaises(ValueError):
            MapControlPlannerConfig(desired_units=1, minimum_units=2)


class MapControlPlannerTests(unittest.TestCase):
    def test_waits_for_start_time_and_reserve(self):
        planner = MapControlPlanner()

        self.assertEqual(planner.propose(attention(179.0), awareness(179.0)), ())
        self.assertEqual(
            planner.propose(attention(180.0, marines=5), awareness(180.0)), ()
        )

    def test_does_not_start_during_danger_or_with_a_visible_enemy(self):
        planner = MapControlPlanner()

        self.assertEqual(
            planner.propose(
                attention(180.0),
                awareness(180.0, posture=MacroPosture.DEFENSE),
            ),
            (),
        )
        self.assertEqual(
            planner.propose(attention(180.0, enemies=1), awareness(180.0)), ()
        )

    def test_proposes_a_low_priority_three_marine_patrol(self):
        planner = MapControlPlanner()

        proposals = planner.propose(attention(180.0), awareness(180.0))

        self.assertEqual(len(proposals), 1)
        proposal = proposals[0]
        self.assertEqual(proposal.kind, MissionKind.MAP_CONTROL)
        self.assertEqual(proposal.target, MAP.center)
        self.assertEqual(proposal.deduplication_key, "map_control:patrol")
        self.assertEqual(proposal.requirement.desired, 3)
        self.assertEqual(proposal.requirement.minimum, 2)
        self.assertEqual(
            proposal.requirement.unit_types,
            frozenset({UnitTypeId.MARINE}),
        )
        self.assertEqual(proposal.priority, 40)
        self.assertFalse(proposal.can_preempt)

    def test_respects_proposal_cadence(self):
        planner = MapControlPlanner()

        self.assertEqual(len(planner.propose(attention(180.0), awareness(180.0))), 1)
        self.assertEqual(planner.propose(attention(181.0), awareness(181.0)), ())


if __name__ == "__main__":
    unittest.main()
