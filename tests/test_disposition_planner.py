from __future__ import annotations

import unittest

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.behavior.army import CombatPosture, DispositionPlanner
from bot.engine.missions import MissionKind, MissionMode
from bot.world.attention import AttentionSnapshot, MapFacts, UnitSnapshot, WorldFacts
from bot.world.awareness import (
    AwarenessSnapshot,
    MacroPosture,
    RelativeStrength,
    ThreatAssessment,
)
from bot.world.awareness.bases import BaseSecurityAssessor
from bot.world.awareness.enemy import EnemyAwareness

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


def attention(
    now: float, own_structures: tuple[UnitSnapshot, ...]
) -> AttentionSnapshot:
    return AttentionSnapshot(
        WorldFacts(
            iteration=int(now),
            time=now,
            minerals=0,
            vespene=0,
            supply_used=0.0,
            supply_cap=0.0,
            own_units=(),
            enemy_units=(),
            map=MAP,
            own_structures=own_structures,
        )
    )


def awareness_for(
    current: AttentionSnapshot,
    *,
    macro_posture: MacroPosture = MacroPosture.BALANCED,
    score: float = 0.0,
    confidence: float = 0.0,
) -> AwarenessSnapshot:
    """Real base assessments, hand-picked posture-driving signals.

    Mirrors how ``derive_combat_posture`` reads Awareness: base security
    comes from the real ``BaseSecurityAssessor`` (so held-base ranking is
    exercised faithfully); the strength/macro signals are set directly so
    each test can pin down a specific ``CombatPosture`` deterministically.
    """

    return AwarenessSnapshot(
        enemy=EnemyAwareness(sightings=(), locations=()),
        relative_strength=RelativeStrength(
            score=score, confidence=confidence, own_combat_units=0,
            known_enemy_combat_units=0,
        ),
        threat=ThreatAssessment(0, 0, 0),
        updated_at=current.world.time,
        macro_posture=macro_posture,
        bases=BaseSecurityAssessor().update(current.world),
    )


class DispositionPlannerSlotTests(unittest.TestCase):
    def test_no_natural_or_third_slot_when_only_main_is_held(self):
        # BALANCED (the default posture with no strong signal) also wants a
        # small central/staging presence, so main + forward + reserve is the
        # full set with a single base -- natural/third simply have no base
        # to anchor to yet.
        current = attention(10.0, (townhall(1, MAP.own_start),))
        awareness = awareness_for(current)

        proposals = DispositionPlanner().propose(current, awareness)

        keys = {p.deduplication_key for p in proposals}
        self.assertEqual(
            keys, {"position:main", "position:forward", "position:reserve"}
        )

    def test_natural_and_third_are_ranked_by_distance_from_own_start(self):
        far = Point2((70, 70))
        near = Point2((25, 25))
        current = attention(
            10.0,
            (
                townhall(1, MAP.own_start),
                townhall(2, far),
                townhall(3, near),
            ),
        )
        awareness = awareness_for(current)

        proposals = DispositionPlanner().propose(current, awareness)
        by_key = {p.deduplication_key: p for p in proposals}

        self.assertEqual(
            set(by_key),
            {
                "position:main",
                "position:natural",
                "position:third",
                "position:forward",
                "position:reserve",
            },
        )
        self.assertEqual(by_key["position:natural"].target, near)
        self.assertEqual(by_key["position:third"].target, far)

    def test_every_proposal_is_standing_with_zero_minimum(self):
        current = attention(10.0, (townhall(1, MAP.own_start),))
        awareness = awareness_for(current)

        for proposal in DispositionPlanner().propose(current, awareness):
            self.assertEqual(proposal.mode, MissionMode.STANDING)
            self.assertEqual(proposal.requirement.minimum, 0)
            self.assertEqual(proposal.kind, MissionKind.POSITION)

    def test_reserve_is_lowest_priority_and_never_preempts(self):
        current = attention(10.0, (townhall(1, MAP.own_start),))
        awareness = awareness_for(current)
        proposals = {
            p.deduplication_key: p
            for p in DispositionPlanner().propose(current, awareness)
        }

        reserve = proposals["position:reserve"]
        main = proposals["position:main"]
        self.assertFalse(reserve.can_preempt)
        self.assertTrue(main.can_preempt)
        self.assertLess(reserve.priority, main.priority)

    def test_respects_its_proposal_cadence(self):
        planner = DispositionPlanner()
        first = attention(10.0, (townhall(1, MAP.own_start),))
        self.assertTrue(planner.propose(first, awareness_for(first)))

        second = attention(11.0, (townhall(1, MAP.own_start),))
        self.assertEqual(planner.propose(second, awareness_for(second)), ())


class DispositionPlannerPostureTests(unittest.TestCase):
    def test_turtle_prioritizes_the_most_exposed_expansion(self):
        structures = (
            townhall(1, MAP.own_start),
            townhall(2, Point2((25, 25))),
            townhall(3, Point2((70, 70))),
        )
        current = attention(10.0, structures)
        awareness = awareness_for(
            current, macro_posture=MacroPosture.DEFENSE
        )
        planner = DispositionPlanner()
        proposals = planner.propose(current, awareness)

        self.assertEqual(planner.last_posture, CombatPosture.TURTLE)
        desired = {
            p.deduplication_key.removeprefix("position:"): p.requirement.desired
            for p in proposals
        }
        self.assertGreater(desired["third"], desired["natural"])
        self.assertGreater(desired["natural"], desired["main"])

    def test_pressure_favors_a_forward_staging_slot_over_defensive_ones(self):
        current = attention(10.0, (townhall(1, MAP.own_start),))
        awareness = awareness_for(current, score=0.6, confidence=0.9)
        planner = DispositionPlanner()

        proposals = planner.propose(current, awareness)

        self.assertEqual(planner.last_posture, CombatPosture.PRESSURE)
        by_key = {p.deduplication_key: p for p in proposals}
        self.assertIn("position:forward", by_key)
        self.assertGreater(
            by_key["position:forward"].requirement.desired,
            by_key["position:main"].requirement.desired,
        )


if __name__ == "__main__":
    unittest.main()
