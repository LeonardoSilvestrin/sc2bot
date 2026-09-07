from __future__ import annotations

import unittest

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.behavior.defense import DefensePlanner
from bot.engine.missions import MissionKind
from bot.world.knowledge import AwarenessService
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


def townhall(tag: int, position: Point2) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.COMMANDCENTER,
        position=position,
        health_percentage=1.0,
        is_flying=False,
        is_worker=False,
        can_attack_air=False,
        can_attack_ground=False,
        is_structure=True,
    )


def enemy_marine(tag: int, position: Point2, *, visible: bool = True) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.MARINE,
        position=position,
        health_percentage=1.0,
        is_flying=False,
        is_worker=False,
        can_attack_air=False,
        can_attack_ground=True,
        visible_now=visible,
    )


def enemy_worker(tag: int, position: Point2) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.SCV,
        position=position,
        health_percentage=1.0,
        is_flying=False,
        is_worker=True,
        can_attack_air=False,
        can_attack_ground=True,
        visible_now=True,
    )


def attention(
    time: float,
    *,
    enemy_units: tuple[UnitSnapshot, ...] = (),
    own_structures: tuple[UnitSnapshot, ...] = (),
) -> AttentionSnapshot:
    world = WorldFacts(
        iteration=int(time),
        time=time,
        minerals=500,
        vespene=0,
        supply_used=16.0,
        supply_cap=30.0,
        own_units=(),
        enemy_units=enemy_units,
        map=MAP,
        own_structures=own_structures,
    )
    return AttentionSnapshot(world)


class DefensePlannerTests(unittest.TestCase):
    def test_no_proposal_without_any_visible_enemy(self):
        current = attention(10.0)
        awareness = AwarenessService().update(current)

        self.assertEqual(DefensePlanner().propose(current, awareness), ())

    def test_no_proposal_for_an_enemy_worker_alone(self):
        current = attention(10.0, enemy_units=(enemy_worker(1, Point2((12, 10))),))
        awareness = AwarenessService().update(current)

        self.assertEqual(DefensePlanner().propose(current, awareness), ())

    def test_no_proposal_for_a_threat_outside_the_detection_radius(self):
        current = attention(
            10.0, enemy_units=(enemy_marine(1, Point2((60, 60))),)
        )
        awareness = AwarenessService().update(current)

        self.assertEqual(DefensePlanner().propose(current, awareness), ())

    def test_no_proposal_for_a_threat_that_is_not_currently_visible(self):
        current = attention(
            10.0,
            enemy_units=(enemy_marine(1, Point2((12, 10)), visible=False),),
        )
        awareness = AwarenessService().update(current)

        self.assertEqual(DefensePlanner().propose(current, awareness), ())

    def test_proposes_defense_for_a_combat_threat_near_own_start(self):
        current = attention(10.0, enemy_units=(enemy_marine(1, Point2((12, 10))),))
        awareness = AwarenessService().update(current)

        proposals = DefensePlanner().propose(current, awareness)

        self.assertEqual(len(proposals), 1)
        proposal = proposals[0]
        self.assertEqual(proposal.kind, MissionKind.DEFENSE)
        self.assertEqual(proposal.target, Point2((12, 10)))
        self.assertEqual(proposal.deduplication_key, "defense:own_base")
        self.assertTrue(proposal.reason.strip())
        self.assertTrue(0 <= proposal.priority <= 100)
        self.assertGreater(proposal.priority, 90)
        self.assertTrue(proposal.can_preempt)
        self.assertGreater(proposal.timeout_seconds, 0.0)
        self.assertGreaterEqual(proposal.cooldown_seconds, 0.0)
        self.assertEqual(
            proposal.requirement.unit_types,
            frozenset({UnitTypeId.MARINE, UnitTypeId.REAPER}),
        )
        self.assertEqual(proposal.requirement.minimum, 1)
        self.assertGreaterEqual(
            proposal.requirement.desired, proposal.requirement.minimum
        )

    def test_proposes_defense_for_a_threat_near_an_owned_structure(self):
        current = attention(
            10.0,
            enemy_units=(enemy_marine(1, Point2((41, 40))),),
            own_structures=(townhall(2, Point2((40, 40))),),
        )
        awareness = AwarenessService().update(current)

        proposals = DefensePlanner().propose(current, awareness)

        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0].target, Point2((41, 40)))

    def test_targets_the_closest_threat_when_several_are_observed(self):
        current = attention(
            10.0,
            enemy_units=(
                enemy_marine(1, Point2((20, 10))),
                enemy_marine(2, Point2((11, 10))),
            ),
        )
        awareness = AwarenessService().update(current)

        proposals = DefensePlanner().propose(current, awareness)

        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0].target, Point2((11, 10)))

    def test_respects_its_proposal_cadence(self):
        planner = DefensePlanner()
        first = attention(10.0, enemy_units=(enemy_marine(1, Point2((12, 10))),))
        self.assertEqual(
            len(planner.propose(first, AwarenessService().update(first))), 1
        )

        second = attention(11.0, enemy_units=(enemy_marine(1, Point2((12, 10))),))
        self.assertEqual(planner.propose(second, AwarenessService().update(second)), ())


if __name__ == "__main__":
    unittest.main()
