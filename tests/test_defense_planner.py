from __future__ import annotations

import unittest
from dataclasses import replace

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.behavior.defense import DefenseAssessor, DefensePlanner
from bot.engine.missions import MissionKind, UnitRequirement
from bot.engine.missions.allocator import UnitAllocator
from bot.world.attention import (
    AttentionSnapshot,
    MapFacts,
    UnitSnapshot,
    WorldFacts,
)
from bot.world.awareness import AwarenessService
from tests.fakes import FakeLogger

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


def own_unit(
    tag: int, unit_type: UnitTypeId, position: Point2, *, flying: bool = False
) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=unit_type,
        position=position,
        health_percentage=1.0,
        is_flying=flying,
        is_worker=False,
        can_attack_air=False,
        can_attack_ground=True,
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
            frozenset(
                {
                    UnitTypeId.MARINE,
                    UnitTypeId.MARAUDER,
                    UnitTypeId.REAPER,
                    UnitTypeId.SIEGETANK,
                    UnitTypeId.SIEGETANKSIEGED,
                    UnitTypeId.BANSHEE,
                }
            ),
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

    def test_proposes_independently_for_each_threatened_base(self):
        current = attention(
            10.0,
            enemy_units=(
                enemy_marine(1, Point2((41, 40))),
                enemy_marine(2, Point2((71, 70))),
            ),
            own_structures=(
                townhall(10, Point2((40, 40))),
                townhall(11, Point2((70, 70))),
            ),
        )
        awareness = AwarenessService().update(current)

        proposals = DefensePlanner().propose(current, awareness)

        self.assertEqual(len(proposals), 2)
        dedup_keys = {proposal.deduplication_key for proposal in proposals}
        self.assertEqual(dedup_keys, {"defense:base:10", "defense:base:11"})

    def test_does_not_propose_for_a_base_with_no_threat_nearby(self):
        current = attention(
            10.0,
            enemy_units=(enemy_marine(1, Point2((41, 40))),),
            own_structures=(
                townhall(10, Point2((40, 40))),
                townhall(11, Point2((70, 70))),
            ),
        )
        awareness = AwarenessService().update(current)

        proposals = DefensePlanner().propose(current, awareness)

        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0].deduplication_key, "defense:base:10")

    def test_an_already_defended_base_gets_lower_priority_than_an_undefended_one(self):
        current = attention(
            10.0,
            enemy_units=(
                enemy_marine(1, Point2((41, 40))),
                enemy_marine(2, Point2((71, 70))),
            ),
            own_structures=(
                townhall(10, Point2((40, 40))),
                townhall(11, Point2((70, 70))),
            ),
        )
        current = replace(
            current,
            world=replace(
                current.world,
                own_units=(
                    UnitSnapshot(
                        tag=99,
                        unit_type=UnitTypeId.MARINE,
                        position=Point2((40, 40)),
                        health_percentage=1.0,
                        is_flying=False,
                        is_worker=False,
                        can_attack_air=False,
                        can_attack_ground=True,
                    ),
                ),
            ),
        )
        awareness = AwarenessService().update(current)

        proposals = DefensePlanner().propose(current, awareness)
        by_key = {proposal.deduplication_key: proposal for proposal in proposals}

        self.assertLess(
            by_key["defense:base:10"].priority, by_key["defense:base:11"].priority
        )

    def test_respects_its_proposal_cadence(self):
        planner = DefensePlanner()
        first = attention(10.0, enemy_units=(enemy_marine(1, Point2((12, 10))),))
        self.assertEqual(
            len(planner.propose(first, AwarenessService().update(first))), 1
        )

        second = attention(11.0, enemy_units=(enemy_marine(1, Point2((12, 10))),))
        self.assertEqual(planner.propose(second, AwarenessService().update(second)), ())


def enemy_mutalisk(tag: int, position: Point2) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.MUTALISK,
        position=position,
        health_percentage=1.0,
        is_flying=True,
        is_worker=False,
        can_attack_air=True,
        can_attack_ground=True,
        visible_now=True,
    )


class DefenseAssessmentTests(unittest.TestCase):
    def test_reports_nothing_threatened_when_the_map_is_quiet(self):
        current = attention(10.0)
        awareness = AwarenessService().update(current)

        assessment = DefenseAssessor().assess(current, awareness)

        self.assertFalse(assessment.under_attack)
        self.assertEqual(assessment.threatened, ())
        self.assertEqual(assessment.log_fields()["threatened_bases"], [])

    def test_separates_air_from_ground_attackers(self):
        """The composition, not just the size, of what is hitting the base.

        The planner derives `type_desirability` from this split; see
        `DefenderPreferenceTests`.
        """

        current = attention(
            10.0,
            enemy_units=(
                enemy_marine(1, Point2((12, 10))),
                enemy_mutalisk(2, Point2((12, 11))),
                enemy_mutalisk(3, Point2((13, 11))),
            ),
        )
        awareness = AwarenessService().update(current)

        assessment = DefenseAssessor().assess(current, awareness)

        self.assertTrue(assessment.under_attack)
        base = assessment.threatened[0]
        self.assertEqual(base.ground_threats, 1)
        self.assertEqual(base.air_threats, 2)
        self.assertEqual(assessment.log_fields()["air_threats"], 2)

    def test_the_plan_sizes_the_request_to_the_gap(self):
        current = attention(
            10.0,
            enemy_units=tuple(
                enemy_marine(tag, Point2((12, 10 + tag * 0.1)))
                for tag in range(1, 4)
            ),
        )
        awareness = AwarenessService().update(current)
        planner = DefensePlanner(logger=FakeLogger())

        proposals = planner.propose(current, awareness)

        self.assertEqual(len(proposals), 1)
        plan = planner.last_plans[0]
        self.assertEqual(plan.desired_units, proposals[0].requirement.desired)
        self.assertTrue(plan.base.is_critical)
        self.assertEqual(plan.priority, 95)

    def test_logs_the_assessment_and_every_plan(self):
        logger = FakeLogger()
        current = attention(10.0, enemy_units=(enemy_marine(1, Point2((12, 10))),))
        awareness = AwarenessService().update(current)

        DefensePlanner(logger=logger).propose(current, awareness)

        names = [event["name"] for event in logger.events]
        self.assertIn("behavior.assessed", names)
        self.assertIn("behavior.proposed", names)
        self.assertEqual(
            {event["component"] for event in logger.events}, {"behavior.defense"}
        )


class DefenderPreferenceTests(unittest.TestCase):
    """Which of the available units are actually worth pulling for this attack."""

    TANK = own_unit(20, UnitTypeId.SIEGETANK, Point2((40, 40)))
    SIEGED_TANK = own_unit(21, UnitTypeId.SIEGETANKSIEGED, Point2((40, 40)))
    MARINE = own_unit(22, UnitTypeId.MARINE, Point2((12, 12)))
    MARAUDER = own_unit(23, UnitTypeId.MARAUDER, Point2((12, 12)))
    BANSHEE = own_unit(24, UnitTypeId.BANSHEE, Point2((40, 40)), flying=True)

    def requirement_against(self, *enemies: UnitSnapshot) -> UnitRequirement:
        current = attention(10.0, enemy_units=enemies)
        proposals = DefensePlanner().propose(
            current, AwarenessService().update(current)
        )
        self.assertEqual(len(proposals), 1)
        return proposals[0].requirement

    def test_a_ground_attack_makes_tanks_the_most_wanted_defender(self):
        requirement = self.requirement_against(enemy_marine(1, Point2((12, 10))))

        self.assertEqual(requirement.utility_for(self.TANK), 1.0)
        self.assertEqual(requirement.utility_for(self.SIEGED_TANK), 1.0)
        for bio in (self.MARINE, self.MARAUDER):
            self.assertGreater(requirement.utility_for(bio), 0.0)
            self.assertLess(requirement.utility_for(bio), 1.0)

    def test_an_air_only_attack_never_requests_tanks_or_banshees(self):
        requirement = self.requirement_against(enemy_mutalisk(1, Point2((12, 10))))

        for useless in (self.TANK, self.SIEGED_TANK, self.BANSHEE):
            self.assertEqual(requirement.utility_for(useless), 0.0)
        self.assertEqual(requirement.utility_for(self.MARINE), 1.0)

    def test_a_mixed_attack_still_wants_tanks_for_its_ground_part(self):
        requirement = self.requirement_against(
            enemy_marine(1, Point2((12, 10))), enemy_mutalisk(2, Point2((12, 11)))
        )

        self.assertEqual(requirement.utility_for(self.TANK), 1.0)

    def test_the_allocator_pulls_a_distant_tank_only_against_the_ground(self):
        """The planner's answer, not the allocator, decides who is pulled."""

        cases = (
            (enemy_marine(1, Point2((12, 10))), (self.TANK.tag,)),
            (enemy_mutalisk(1, Point2((12, 10))), (self.MARINE.tag,)),
        )
        for enemy, expected in cases:
            with self.subTest(enemy=enemy.unit_type.name):
                allocator = UnitAllocator()
                allocator.sync((self.TANK, self.MARINE))
                result = allocator.allocate(
                    mission_id="defense",
                    priority=95,
                    requirement=replace(
                        self.requirement_against(enemy), desired=1, minimum=1
                    ),
                    objective=Point2((12, 10)),
                    now=10.0,
                    can_preempt=True,
                    commitment_seconds=3.0,
                )
                self.assertEqual(result.assigned_tags, expected)

    def test_the_plan_logs_which_defenders_it_wants(self):
        logger = FakeLogger()
        current = attention(
            10.0, enemy_units=(enemy_mutalisk(1, Point2((12, 10))),)
        )

        DefensePlanner(logger=logger).propose(
            current, AwarenessService().update(current)
        )

        proposed = next(
            event for event in logger.events if event["name"] == "behavior.proposed"
        )
        self.assertEqual(proposed["data"]["air_threats"], 1)
        self.assertEqual(proposed["data"]["type_desirability"]["SIEGETANK"], 0.0)


if __name__ == "__main__":
    unittest.main()
