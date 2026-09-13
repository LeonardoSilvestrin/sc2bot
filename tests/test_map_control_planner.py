from __future__ import annotations

import unittest
from dataclasses import replace

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.behavior.map_control import (
    MapControlAssessor,
    MapControlConfig,
    MapControlPlanner,
    score_spatial_sample,
)
from bot.engine.missions import CombatRole, MissionKind
from bot.world.attention import (
    AttentionSnapshot,
    MapFacts,
    UnitSnapshot,
    WorldFacts,
)
from bot.world.awareness import (
    AwarenessSnapshot,
    MacroPosture,
    RelativeStrength,
    SpatialField,
    SpatialFieldSample,
    ThreatAssessment,
)
from bot.world.awareness.bases import (
    BaseAssessment,
    BaseAwareness,
    BaseSecurityLevel,
)
from bot.world.awareness.enemy import EnemyAwareness
from tests.fakes import FakeLogger

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
        supply_cost=1.0,
    )


def enemy_marine(tag: int) -> UnitSnapshot:
    return replace(marine(tag), position=Point2((50, 50)))


def attention(
    now: float,
    *,
    marines: int = 6,
    enemies: int = 0,
    extra: tuple[UnitSnapshot, ...] = (),
) -> AttentionSnapshot:
    return AttentionSnapshot(
        WorldFacts(
            iteration=int(now),
            time=now,
            minerals=0,
            vespene=0,
            supply_used=float(marines),
            supply_cap=200.0,
            own_units=(
                *(marine(tag) for tag in range(1, marines + 1)),
                *extra,
            ),
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


class MapControlConfigTests(unittest.TestCase):
    def test_rejects_an_invalid_force_ratio_or_minimum_supply(self):
        with self.assertRaises(ValueError):
            MapControlConfig(force_ratio=1.0)
        with self.assertRaises(ValueError):
            MapControlConfig(minimum_force_supply=0.0)

    def test_score_combines_components_with_behavior_owned_weights(self):
        sample = SpatialFieldSample(
            position=Point2((40, 40)),
            friendly_value=0.7,
            choke_value=0.8,
            route_value=0.6,
            enemy_threat=0.2,
        )
        config = MapControlConfig(
            friendly_weight=1.0,
            frontier_weight=0.0,
            advancement_weight=0.0,
            choke_weight=2.0,
            route_weight=3.0,
            threat_weight=4.0,
            enemy_control_weight=0.0,
            unknown_weight=0.0,
            travel_weight=0.0,
        )

        self.assertAlmostEqual(score_spatial_sample(sample, config), 2.8857142857)

    def test_friendly_influence_is_a_frontier_support_band(self):
        config = MapControlConfig(
            frontier_weight=0.0,
            advancement_weight=0.0,
            choke_weight=0.0,
            route_weight=0.0,
            threat_weight=0.0,
            enemy_control_weight=0.0,
            unknown_weight=0.0,
            travel_weight=0.0,
        )

        frontier = SpatialFieldSample(Point2((40, 40)), friendly_value=0.45)
        deep_home = SpatialFieldSample(Point2((10, 10)), friendly_value=1.0)

        self.assertGreater(
            score_spatial_sample(frontier, config),
            score_spatial_sample(deep_home, config),
        )


class MapControlPlannerTests(unittest.TestCase):
    @staticmethod
    def spatial_awareness(
        now: float, *samples: SpatialFieldSample
    ) -> AwarenessSnapshot:
        return replace(
            awareness(now),
            spatial=SpatialField(samples=tuple(samples), updated_at=now),
        )

    def test_waits_for_minimum_force_supply(self):
        planner = MapControlPlanner()

        self.assertEqual(
            planner.propose(attention(0.0, marines=5), awareness(0.0)), ()
        )

    def test_persistent_responsibility_is_declared_during_danger(self):
        planner = MapControlPlanner()

        self.assertEqual(
            len(
                planner.propose(
                    attention(180.0),
                    awareness(180.0, posture=MacroPosture.DEFENSE),
                )
            ),
            1,
        )

    def test_proposes_a_persistent_twenty_percent_patrol(self):
        planner = MapControlPlanner()

        proposals = planner.propose(attention(180.0), awareness(180.0))

        self.assertEqual(len(proposals), 1)
        proposal = proposals[0]
        self.assertEqual(proposal.kind, MissionKind.MAP_CONTROL)
        self.assertEqual(proposal.target, MAP.center)
        self.assertEqual(proposal.deduplication_key, "map_control:patrol")
        # A fifth of six supply; the count only caps, it does not size.
        self.assertEqual(proposal.requirement.supply_budget, 1.2)
        self.assertEqual(proposal.requirement.desired, 6)
        self.assertEqual(proposal.requirement.minimum, 0)
        # A role, not a unit list.
        self.assertIs(
            proposal.requirement.capability, CombatRole.MOBILE_CONTROL.requirement
        )
        self.assertEqual(proposal.requirement.unit_types, frozenset())
        self.assertEqual(proposal.priority, 40)
        # Standing POSITION/RESERVE missions hold most idle units now, so
        # map control must be able to preempt them to get its squad at all.
        self.assertTrue(proposal.can_preempt)
        self.assertEqual(proposal.mode.name, "STANDING")
        self.assertEqual(proposal.squad_id, "map_control")

    def test_a_fixed_unit_count_override_sizes_by_count(self):
        planner = MapControlPlanner(config=MapControlConfig(desired_units=3))

        proposal = planner.propose(attention(180.0), awareness(180.0))[0]

        self.assertEqual(proposal.requirement.desired, 3)
        self.assertIsNone(proposal.requirement.supply_budget)

    def test_respects_proposal_cadence(self):
        planner = MapControlPlanner()

        self.assertEqual(len(planner.propose(attention(180.0), awareness(180.0))), 1)
        self.assertEqual(planner.propose(attention(181.0), awareness(181.0)), ())

    def test_hysteresis_ignores_small_gain_then_accepts_material_retarget(self):
        first, second = Point2((30, 30)), Point2((50, 50))
        config = MapControlConfig(
            proposal_cadence=1.0,
            friendly_weight=1.0,
            frontier_weight=0.0,
            advancement_weight=0.0,
            choke_weight=0.0,
            route_weight=0.0,
            threat_weight=0.0,
            enemy_control_weight=0.0,
            unknown_weight=0.0,
            travel_weight=0.0,
            retarget_score_improvement=0.1,
            retarget_min_sample_steps=1.5,
        )
        planner = MapControlPlanner(config=config)

        initial = planner.propose(
            attention(0.0),
            self.spatial_awareness(
                0.0,
                SpatialFieldSample(first, friendly_value=0.47),
                SpatialFieldSample(second, friendly_value=0.30),
            ),
        )[0]
        small_gain = planner.propose(
            attention(1.0),
            self.spatial_awareness(
                1.0,
                SpatialFieldSample(first, friendly_value=0.47),
                SpatialFieldSample(second, friendly_value=0.45),
            ),
        )[0]
        material_gain = planner.propose(
            attention(2.0),
            self.spatial_awareness(
                2.0,
                SpatialFieldSample(first, friendly_value=0.70),
                SpatialFieldSample(second, friendly_value=0.45),
            ),
        )[0]

        self.assertEqual(initial.target, first)
        self.assertEqual(small_gain.target, first)
        self.assertEqual(material_gain.target, second)

    def test_retarget_distance_is_measured_in_grid_steps(self):
        current, neighbour = Point2((30, 30)), Point2((40, 30))
        config = MapControlConfig(
            proposal_cadence=1.0,
            friendly_weight=1.0,
            frontier_weight=0.0,
            advancement_weight=0.0,
            choke_weight=0.0,
            route_weight=0.0,
            threat_weight=0.0,
            enemy_control_weight=0.0,
            unknown_weight=0.0,
            travel_weight=0.0,
            retarget_score_improvement=0.1,
            retarget_min_sample_steps=1.5,
        )

        def spatial_state(now, spacing, current_value, neighbour_value):
            return replace(
                awareness(now),
                spatial=SpatialField(
                    samples=(
                        SpatialFieldSample(current, friendly_value=current_value),
                        SpatialFieldSample(neighbour, friendly_value=neighbour_value),
                    ),
                    updated_at=now,
                    sample_spacing=spacing,
                ),
            )

        coarse = MapControlPlanner(config=config)
        coarse.propose(attention(0.0), spatial_state(0.0, 10.0, 0.45, 0.2))
        # One step on a 10-cell grid: the patrol region already covers it.
        coarse_retarget = coarse.propose(
            attention(1.0), spatial_state(1.0, 10.0, 0.2, 0.45)
        )[0]
        fine = MapControlPlanner(config=config)
        fine.propose(attention(0.0), spatial_state(0.0, 5.0, 0.45, 0.2))
        # The same ten units are two steps on a 5-cell grid: a real move.
        fine_retarget = fine.propose(
            attention(1.0), spatial_state(1.0, 5.0, 0.2, 0.45)
        )[0]

        self.assertEqual(coarse_retarget.target, current)
        self.assertEqual(fine_retarget.target, neighbour)

    def test_logs_ranked_components_when_spatial_target_is_selected(self):
        logger = FakeLogger()
        planner = MapControlPlanner(logger=logger)
        point = Point2((35, 35))

        planner.propose(
            attention(10.0),
            self.spatial_awareness(
                10.0,
                SpatialFieldSample(
                    point,
                    friendly_value=0.7,
                    choke_value=0.8,
                    route_value=0.9,
                    enemy_threat=0.1,
                ),
            ),
        )

        event = next(
            item
            for item in logger.events
            if item["name"] == "map_control.spatial_candidates"
        )
        selected = event["data"]["selected"]
        self.assertEqual(selected["position"], [35.0, 35.0])
        self.assertEqual(
            set(selected),
            {
                "position",
                "score",
                "frontier",
                "advancement",
                "friendly_support",
                "friendly_proximity",
                "support_band",
                "enemy_control",
                "enemy_threat",
                "knowledge",
                "unknown_risk",
                "choke",
                "route",
                "travel_cost",
                "selected",
                "reason",
            },
        )

    def test_does_not_select_the_townhall_center_as_military_position(self):
        base_position = Point2((20, 20))
        valid_position = Point2((32, 20))
        state = self.spatial_awareness(
            10.0,
            SpatialFieldSample(base_position, friendly_value=1.0),
            SpatialFieldSample(valid_position, friendly_value=0.7),
        )
        state = replace(
            state,
            bases=BaseAwareness(
                (
                    BaseAssessment(
                        "base:1",
                        base_position,
                        True,
                        0.0,
                        0.0,
                        BaseSecurityLevel.SAFE,
                    ),
                )
            ),
        )

        proposal = MapControlPlanner().propose(attention(10.0), state)[0]

        self.assertEqual(proposal.target, valid_position)

    def test_selects_useful_supported_frontier_not_deep_base_or_danger(self):
        home = Point2((10, 10))
        deep = Point2((20, 10))
        frontier = Point2((40, 10))
        choke = Point2((50, 10))
        dangerous = Point2((70, 10))
        unknown_distant = Point2((90, 10))
        state = self.spatial_awareness(
            10.0,
            SpatialFieldSample(deep, friendly_value=0.95, knowledge_confidence=1.0),
            SpatialFieldSample(frontier, friendly_value=0.55, knowledge_confidence=1.0),
            SpatialFieldSample(
                choke,
                friendly_value=0.42,
                choke_value=1.0,
                route_value=1.0,
                knowledge_confidence=0.8,
            ),
            SpatialFieldSample(
                dangerous,
                friendly_value=0.35,
                choke_value=1.0,
                route_value=1.0,
                enemy_control=0.8,
                enemy_threat=0.9,
                knowledge_confidence=1.0,
            ),
            SpatialFieldSample(
                unknown_distant,
                friendly_value=0.30,
                route_value=0.4,
                knowledge_confidence=0.0,
            ),
        )
        state = replace(
            state,
            bases=BaseAwareness(
                (
                    BaseAssessment(
                        "base:1", home, True, 0.0, 0.0, BaseSecurityLevel.SAFE
                    ),
                )
            ),
        )

        proposal = MapControlPlanner().propose(attention(10.0), state)[0]

        self.assertEqual(proposal.target, choke)
        self.assertNotEqual(proposal.target, deep)
        self.assertNotEqual(proposal.target, dangerous)
        self.assertNotEqual(proposal.target, unknown_distant)

    def test_advancing_friendly_frontier_advances_anchor(self):
        first, second = Point2((40, 10)), Point2((60, 10))
        planner = MapControlPlanner(
            config=MapControlConfig(proposal_cadence=1.0)
        )

        initial = planner.propose(
            attention(0.0),
            self.spatial_awareness(
                0.0,
                SpatialFieldSample(
                    first, friendly_value=0.45, knowledge_confidence=1.0
                ),
                SpatialFieldSample(
                    second, friendly_value=0.05, knowledge_confidence=0.5
                ),
            ),
        )[0]
        advanced = planner.propose(
            attention(1.0),
            self.spatial_awareness(
                1.0,
                SpatialFieldSample(
                    first, friendly_value=0.95, knowledge_confidence=1.0
                ),
                SpatialFieldSample(
                    second, friendly_value=0.45, knowledge_confidence=0.8
                ),
            ),
        )[0]

        self.assertEqual(initial.target, first)
        self.assertEqual(advanced.target, second)

    def test_enemy_threat_invalidates_current_anchor_despite_hysteresis(self):
        current, alternative = Point2((40, 10)), Point2((60, 10))
        logger = FakeLogger()
        planner = MapControlPlanner(
            config=MapControlConfig(proposal_cadence=1.0), logger=logger
        )
        planner.propose(
            attention(0.0),
            self.spatial_awareness(
                0.0,
                SpatialFieldSample(
                    current, friendly_value=0.45, knowledge_confidence=1.0
                ),
                SpatialFieldSample(
                    alternative, friendly_value=0.35, knowledge_confidence=1.0
                ),
            ),
        )

        proposal = planner.propose(
            attention(1.0),
            self.spatial_awareness(
                1.0,
                SpatialFieldSample(
                    current,
                    friendly_value=0.45,
                    enemy_threat=0.9,
                    knowledge_confidence=1.0,
                ),
                SpatialFieldSample(
                    alternative, friendly_value=0.45, knowledge_confidence=1.0
                ),
            ),
        )[0]

        self.assertEqual(proposal.target, alternative)
        change = [
            event
            for event in logger.events
            if event["name"] == "map_control.anchor_changed"
        ][-1]
        self.assertEqual(
            change["data"]["reason"],
            "current_anchor_invalidated_by_enemy_threat",
        )


class MapControlAssessmentTests(unittest.TestCase):
    def test_counts_every_combat_unit_healthy_enough_to_roam(self):
        extra = (
            marine(20, health=0.5),
            replace(marine(21), unit_type=UnitTypeId.MEDIVAC, supply_cost=2.0),
            replace(marine(22), unit_type=UnitTypeId.SIEGETANK, supply_cost=3.0),
        )
        current, state = attention(30.0, marines=8, extra=extra), awareness(30.0)

        assessment = MapControlAssessor().assess(current, state)

        self.assertEqual(assessment.combat_units, 9)
        self.assertEqual(assessment.combat_supply, 11.0)
        self.assertTrue(assessment.started)
        self.assertTrue(assessment.force_available)

    def test_the_plan_claims_the_configured_share_of_supply(self):
        tanks = tuple(
            replace(marine(tag), unit_type=UnitTypeId.SIEGETANK, supply_cost=3.0)
            for tag in (20, 21)
        )
        current, state = attention(30.0, marines=4, extra=tanks), awareness(30.0)
        planner = MapControlPlanner()

        proposals = planner.propose(current, state)

        self.assertEqual(len(proposals), 1)
        # Four Marines and two Tanks are ten supply, not six heads.
        self.assertEqual(planner.last_plan.supply_budget, 2.0)
        self.assertEqual(
            proposals[0].requirement.supply_budget, planner.last_plan.supply_budget
        )

    def test_a_too_small_army_produces_no_plan(self):
        current, state = attention(30.0, marines=3), awareness(30.0)
        planner = MapControlPlanner()

        self.assertEqual(planner.propose(current, state), ())
        self.assertIsNone(planner.last_plan)
        self.assertEqual(planner.last_assessment.combat_supply, 3.0)


if __name__ == "__main__":
    unittest.main()
