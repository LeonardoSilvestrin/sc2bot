from __future__ import annotations

import unittest
from dataclasses import replace

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.behavior.standing import StandingPlanner
from bot.engine.missions import MissionKind, MissionMode
from bot.world.attention import AttentionSnapshot, MapFacts, UnitSnapshot, WorldFacts
from bot.world.awareness import AwarenessSnapshot, RelativeStrength, ThreatAssessment
from bot.world.awareness.bases import BaseSecurityAssessor
from bot.world.awareness.enemy import EnemyAwareness
from tests.fakes import FakeLogger

MAP = MapFacts(
    center=Point2((50, 50)),
    own_start=Point2((10, 10)),
    enemy_starts=(Point2((90, 90)),),
)


def unit(tag: int, unit_type: UnitTypeId = UnitTypeId.MARINE) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=unit_type,
        position=MAP.own_start,
        health_percentage=1.0,
        is_flying=unit_type is UnitTypeId.BANSHEE,
        is_worker=False,
        can_attack_air=True,
        can_attack_ground=True,
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


def current(
    now: float,
    *,
    count: int = 10,
    bases: tuple[UnitSnapshot, ...] = (),
) -> tuple[AttentionSnapshot, AwarenessSnapshot]:
    attention = AttentionSnapshot(
        WorldFacts(
            iteration=int(now),
            time=now,
            minerals=0,
            vespene=0,
            supply_used=float(count),
            supply_cap=200,
            own_units=tuple(unit(tag) for tag in range(1, count + 1)),
            enemy_units=(),
            map=MAP,
            own_structures=bases,
        )
    )
    awareness = AwarenessSnapshot(
        enemy=EnemyAwareness(sightings=(), locations=()),
        relative_strength=RelativeStrength(0.0, 0.0, count, 0),
        threat=ThreatAssessment(0, 0, 0),
        updated_at=now,
        bases=BaseSecurityAssessor().update(attention.world),
    )
    return attention, awareness


class CoreArmyStandingTests(unittest.TestCase):
    def test_declares_one_persistent_main_army_at_eighty_percent(self):
        attention, awareness = current(10.0, count=10)

        proposals = StandingPlanner().propose(attention, awareness)

        self.assertEqual(len(proposals), 1)
        proposal = proposals[0]
        self.assertEqual(proposal.kind, MissionKind.HOLD_RALLY)
        self.assertEqual(proposal.mode, MissionMode.STANDING)
        self.assertEqual(proposal.squad_id, "main_army")
        self.assertEqual(proposal.deduplication_key, "hold_rally:main_army")
        self.assertEqual(proposal.requirement.desired, 8)
        self.assertEqual(proposal.requirement.minimum, 0)

    def test_rally_is_seventy_two_percent_from_previous_to_newest_base(self):
        main = townhall(100, MAP.own_start)
        natural = townhall(101, Point2((20, 20)))
        newest = townhall(102, Point2((40, 40)))
        attention, awareness = current(10.0, bases=(newest, main, natural))

        proposal = StandingPlanner().propose(attention, awareness)[0]

        self.assertEqual(proposal.target, Point2((34.4, 34.4)))

    def test_banshees_are_left_for_the_specialized_persistent_squad(self):
        attention, awareness = current(10.0, count=5)
        attention = AttentionSnapshot(
            replace(
                attention.world,
                own_units=(*attention.world.own_units, unit(99, UnitTypeId.BANSHEE)),
            )
        )

        proposal = StandingPlanner().propose(attention, awareness)[0]

        self.assertNotIn(UnitTypeId.BANSHEE, proposal.requirement.unit_types)
        self.assertEqual(proposal.requirement.desired, 4)

    def test_assessment_reports_what_the_plan_was_decided_from(self):
        attention, awareness = current(10.0, count=10)
        planner = StandingPlanner()

        planner.propose(attention, awareness)

        assessment = planner.last_assessment
        plan = planner.last_plan
        self.assertEqual(assessment.eligible_units, 10)
        self.assertEqual(assessment.posture, planner.last_posture)
        self.assertEqual(plan.core_count, 8)
        self.assertEqual(plan.core_fraction, 0.8)
        self.assertAlmostEqual(plan.roaming_fraction, 0.2)
        self.assertTrue(plan.anchor_reason.strip())

    def test_a_moved_anchor_is_logged_with_its_reason(self):
        logger = FakeLogger()
        planner = StandingPlanner(logger=logger)
        main = townhall(100, MAP.own_start)
        first, awareness = current(10.0, bases=(main,))
        planner.propose(first, awareness)

        newest = townhall(101, Point2((40, 40)))
        second, awareness = current(20.0, bases=(main, newest))
        planner.propose(second, awareness)

        anchors = [
            event["data"]
            for event in logger.events
            if event["name"] == "behavior.proposed"
        ]
        self.assertEqual(len(anchors), 2)
        self.assertEqual(anchors[0]["anchor_reason"], "single_base_held")
        self.assertEqual(
            anchors[1]["anchor_reason"], "between_previous_and_newest_base"
        )
        self.assertEqual(anchors[1]["previous_anchor"], anchors[0]["anchor"])

    def test_an_unchanged_anchor_is_not_re_logged_every_cadence_tick(self):
        logger = FakeLogger()
        planner = StandingPlanner(logger=logger)
        for now in (10.0, 20.0, 30.0):
            attention, awareness = current(now, count=10)
            planner.propose(attention, awareness)

        proposed = [e for e in logger.events if e["name"] == "behavior.proposed"]
        self.assertEqual(len(proposed), 1)

    def test_keeps_the_same_dedup_key_across_cadence_ticks(self):
        planner = StandingPlanner()
        first, awareness = current(10.0)
        first_proposal = planner.propose(first, awareness)[0]
        second, awareness = current(16.0)
        second_proposal = planner.propose(second, awareness)[0]

        self.assertEqual(
            first_proposal.deduplication_key,
            second_proposal.deduplication_key,
        )
        self.assertEqual(planner.propose(second, awareness), ())


if __name__ == "__main__":
    unittest.main()
