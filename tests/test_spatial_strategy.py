"""Strategy's spatial policy: desired control, derived from current control."""

from __future__ import annotations

import unittest
from dataclasses import replace

from sc2.position import Point2

from bot.app.strategy_runtime import StrategyRuntime
from bot.strategy import (
    ControlObjective,
    ControlTargetKind,
    IntentConfig,
    SpatialPolicyConfig,
    SpatialStrategySnapshot,
    StrategicActivity,
    StrategicContext,
    StrategicIntent,
    StrategicObjective,
    derive_control_objectives,
)
from bot.world.awareness import (
    AwarenessSnapshot,
    BaseAssessment,
    BaseAwareness,
    BaseSecurityLevel,
    BaseTerritory,
    EnemyAwareness,
    EnemyBaseAssessment,
    EnemyBaseAwareness,
    EnemyBaseStatus,
    PassageTerritory,
    RegionTerritory,
    RelativeStrength,
    TerritoryReading,
    TerritorySnapshot,
    ThreatAssessment,
)
from tests.fakes import FakeLogger

PROFILES = IntentConfig()
BUILD = PROFILES.profile(StrategicObjective.BUILD_ADVANTAGE)

MAIN = Point2((10, 10))
NATURAL = Point2((40, 40))
ENEMY_NATURAL = Point2((85, 85))


def reading(
    *, hold: float = 0.0, confidence: float = 0.8, dominance: float = 0.0
) -> TerritoryReading:
    return TerritoryReading(
        dominance=dominance,
        confidence=confidence,
        friendly_ground_denial=hold,
    )


def region(key: str, center: Point2, *expansions: Point2, **kwargs) -> RegionTerritory:
    access = kwargs.pop("ground_access", 1.0)
    return RegionTerritory(
        key=key,
        center=center,
        expansions=expansions,
        reading=reading(**kwargs),
        ground_access=access,
    )


def passage(key: str, position: Point2, first: str, second: str, **kwargs):
    return PassageTerritory(
        key=key, position=position, regions=(first, second), reading=reading(**kwargs)
    )


def own_base(base_id: str, position: Point2, *, main: bool, threat: float = 0.0):
    return BaseAssessment(
        base_id=base_id,
        position=position,
        is_main=main,
        threat_score=threat,
        protection_score=0.0,
        security=BaseSecurityLevel.SAFE if threat == 0 else BaseSecurityLevel.CRITICAL,
    )


def world(
    *,
    natural_choke_hold: float = 0.1,
    natural_threat: float = 0.0,
    outside_confidence: float = 0.2,
    with_natural: bool = True,
) -> AwarenessSnapshot:
    """A main behind its ramp, a natural facing the open map, the enemy
    natural beyond it.

        main --ramp-- natural --nat_choke-- outside --enemy_link-- enemy_nat
                                               |
                                          north_link
                                               |
                                             north
    """

    regions = {
        "main": region("main", Point2((15, 15)), MAIN, ground_access=0.3),
        "natural": region("natural", Point2((35, 35)), NATURAL, ground_access=0.8),
        "outside": region(
            "outside", Point2((55, 55)), confidence=outside_confidence
        ),
        "north": region("north", Point2((40, 85)), confidence=0.0),
        "enemy_nat": region("enemy_nat", Point2((80, 80)), ENEMY_NATURAL),
    }
    passages = (
        passage("ramp", Point2((25, 25)), "main", "natural", hold=0.3),
        passage(
            "nat_choke", Point2((47, 47)), "natural", "outside", hold=natural_choke_hold
        ),
        passage("north_link", Point2((50, 70)), "outside", "north"),
        passage("enemy_link", Point2((70, 70)), "outside", "enemy_nat"),
    )
    bases = [own_base("main", MAIN, main=True)]
    territory_bases = [BaseTerritory("main", MAIN, regions["main"])]
    if with_natural:
        bases.append(own_base("nat", NATURAL, main=False, threat=natural_threat))
        territory_bases.append(BaseTerritory("nat", NATURAL, regions["natural"]))
    enemy_base = EnemyBaseAssessment(
        key="enemy-natural",
        position=ENEMY_NATURAL,
        status=EnemyBaseStatus.CONFIRMED,
        economic_value=1.0,
        worker_count_estimate=12,
        workers_counted_at=100.0,
        air_defense=0.0,
        air_defense_confidence=1.0,
        ground_defense=0.0,
        ground_defense_confidence=1.0,
        last_confirmed_at=100.0,
        last_checked_at=100.0,
        confidence=1.0,
        is_stale=False,
    )
    return AwarenessSnapshot(
        enemy=EnemyAwareness(
            sightings=(), locations=(), bases=EnemyBaseAwareness((enemy_base,))
        ),
        relative_strength=RelativeStrength(0.0, 0.0, 0, 0),
        threat=ThreatAssessment(0, 0, 0),
        updated_at=100.0,
        bases=BaseAwareness(tuple(bases)),
        territory=TerritorySnapshot(
            regions=tuple(regions.values()),
            passages=passages,
            bases=tuple(territory_bases),
            updated_at=100.0,
        ),
    )


def objectives(
    intent: StrategicIntent = BUILD, **world_options
) -> SpatialStrategySnapshot:
    return derive_control_objectives(intent, world(**world_options))


def get(snapshot: SpatialStrategySnapshot, objective_id: str) -> ControlObjective:
    objective = snapshot.get(objective_id)
    assert objective is not None, objective_id
    return objective


class BaseObjectiveTests(unittest.TestCase):
    def test_every_held_base_is_an_objective_to_protect(self):
        snapshot = objectives()

        for base_id in ("main", "nat"):
            objective = get(snapshot, f"base:{base_id}")
            with self.subTest(base=base_id):
                self.assertIs(objective.kind, ControlTargetKind.BASE)
                self.assertIs(objective.activity, StrategicActivity.DEFENSE)
                self.assertGreater(objective.desired_control, 0.0)

    def test_the_exposed_expansion_matters_more_than_the_sheltered_main(self):
        snapshot = objectives()

        natural = get(snapshot, "base:nat")
        main = get(snapshot, "base:main")

        self.assertGreater(natural.importance, main.importance)
        self.assertEqual(natural.reason, "exposed_expansion")
        self.assertEqual(main.reason, "sheltered_main")

    def test_a_lone_main_faces_the_outside_itself(self):
        snapshot = objectives(with_natural=False)

        self.assertEqual(get(snapshot, "base:main").reason, "exposed_main")

    def test_stabilizing_wants_bases_held_harder_than_pressing(self):
        stabilize = get(
            objectives(PROFILES.profile(StrategicObjective.STABILIZE)),
            "base:nat",
        )
        pressure = get(
            objectives(PROFILES.profile(StrategicObjective.PRESSURE)),
            "base:nat",
        )

        self.assertGreater(stabilize.desired_control, pressure.desired_control)
        self.assertGreater(stabilize.importance, pressure.importance)

    def test_enemy_presence_raises_importance_even_without_a_defense_preference(self):
        careless = replace(BUILD, defense=0.0)

        quiet = objectives(careless).get("base:nat")
        attacked = get(objectives(careless, natural_threat=4.0), "base:nat")

        # Nothing asks for a quiet base Strategy does not want defended; an
        # attacked one matters anyway.
        self.assertIsNone(quiet)
        self.assertGreaterEqual(
            attacked.importance, SpatialPolicyConfig().threat_weight
        )
        self.assertEqual(attacked.reason, "threatened_expansion")

    def test_bases_without_a_region_graph_still_get_objectives(self):
        awareness = replace(world(), territory=TerritorySnapshot())

        snapshot = derive_control_objectives(BUILD, awareness)

        self.assertEqual(
            {item.kind for item in snapshot.objectives}, {ControlTargetKind.BASE}
        )
        self.assertEqual(
            get(snapshot, "base:nat").reason, "expansion_without_topology"
        )


class PassageObjectiveTests(unittest.TestCase):
    def test_a_high_importance_base_behind_a_passage_asks_to_hold_it(self):
        snapshot = objectives()

        natural = get(snapshot, "base:nat")
        choke = get(snapshot, "passage:nat_choke")

        self.assertIs(choke.kind, ControlTargetKind.PASSAGE)
        self.assertEqual(choke.protects, natural.objective_id)
        self.assertEqual(snapshot.protecting(natural.objective_id)[0], choke)
        self.assertEqual(choke.reason, "entrance_to_nat")
        self.assertGreaterEqual(choke.desired_control, natural.desired_control)
        self.assertGreater(choke.importance, 0.5 * natural.importance)

    def test_the_entrance_matters_more_than_the_link_between_held_bases(self):
        snapshot = objectives()

        self.assertGreater(
            get(snapshot, "passage:nat_choke").importance,
            get(snapshot, "passage:ramp").importance,
        )
        self.assertTrue(get(snapshot, "passage:ramp").reason.startswith("internal"))

    def test_current_and_desired_control_are_separate_values(self):
        loose = get(objectives(natural_choke_hold=0.1), "passage:nat_choke")
        held = get(objectives(natural_choke_hold=0.9), "passage:nat_choke")

        # Awareness' reading moves; Strategy's desire does not follow it.
        self.assertAlmostEqual(loose.current_control, 0.1, places=3)
        self.assertAlmostEqual(held.current_control, 0.9, places=3)
        self.assertEqual(loose.desired_control, held.desired_control)
        self.assertEqual(loose.importance, held.importance)
        self.assertGreater(loose.control_gap, held.control_gap)

    def test_we_do_not_control_this_choke_but_strategy_considers_it_critical(self):
        stabilize = PROFILES.profile(StrategicObjective.STABILIZE)

        choke = get(objectives(stabilize, natural_choke_hold=0.0), "passage:nat_choke")

        self.assertLess(choke.current_control, 0.05)
        self.assertGreater(choke.desired_control, 0.9)
        self.assertGreater(choke.importance, 0.7)
        self.assertGreater(choke.need.value, 0.6)


class ApproachObjectiveTests(unittest.TestCase):
    def test_an_uncertain_approach_is_wanted_under_take_map_control(self):
        control = PROFILES.profile(StrategicObjective.TAKE_MAP_CONTROL)

        outside = get(objectives(control), "region:outside")

        self.assertIs(outside.kind, ControlTargetKind.REGION)
        self.assertIn(
            outside.activity,
            {StrategicActivity.MAP_CONTROL, StrategicActivity.INFORMATION},
        )
        self.assertGreater(outside.desired_visibility, 0.7)
        self.assertGreater(outside.desired_control, 0.5)
        self.assertGreater(outside.visibility_gap, 0.0)

    def test_information_intent_raises_approach_importance(self):
        curious = replace(BUILD, information=0.9, map_control=0.0)
        incurious = replace(BUILD, information=0.1, map_control=0.0)

        self.assertGreater(
            get(objectives(curious), "region:outside").importance,
            get(objectives(incurious), "region:outside").importance,
        )
        self.assertIs(
            get(objectives(curious), "region:outside").activity,
            StrategicActivity.INFORMATION,
        )

    def test_approaches_stop_at_one_passage_and_skip_enemy_regions(self):
        snapshot = objectives(PROFILES.profile(StrategicObjective.TAKE_MAP_CONTROL))

        keys = {item.target_key for item in snapshot.of_kind(ControlTargetKind.REGION)}

        self.assertEqual(keys, {"outside"})


class SnapshotTests(unittest.TestCase):
    def test_objectives_are_ordered_and_stable(self):
        first = objectives()
        second = objectives()

        self.assertEqual(first, second)
        importances = [item.importance for item in first.objectives]
        self.assertEqual(importances, sorted(importances, reverse=True))

    def test_the_context_exposes_each_objectives_need(self):
        snapshot = objectives(natural_choke_hold=0.2)
        context = StrategicContext(intent=BUILD, spatial=snapshot)
        choke = get(snapshot, "passage:nat_choke")

        need = context.need_for("passage:nat_choke")

        self.assertEqual(need, choke.need)
        self.assertIsNone(context.need_for("passage:unknown"))
        self.assertIsNone(context.need_for(None))

    def test_each_revision_record_is_complete_so_a_removal_is_visible(self):
        logger = FakeLogger()
        runtime = StrategyRuntime(logger=logger)

        runtime.update(world())
        runtime.record_context()
        # The natural is lost: its objective must not appear to remain.
        runtime.update(replace(world(with_natural=False), updated_at=105.0))
        runtime.record_context()

        first, second = (
            event["data"]
            for event in logger.events
            if event["name"] == "strategy.context"
        )
        self.assertIn("base:nat", [item["id"] for item in first["control_objectives"]])
        self.assertNotIn(
            "base:nat", [item["id"] for item in second["control_objectives"]]
        )
        self.assertEqual(
            second["control_objectives"],
            [item.log_fields() for item in runtime.context.spatial.objectives],
        )
        self.assertEqual(second["revision"], first["revision"] + 1)

    def test_the_runtime_publishes_objectives_with_the_intent(self):
        runtime = StrategyRuntime(logger=FakeLogger())

        runtime.update(world())

        context = runtime.context
        self.assertIsNotNone(context.spatial.get("passage:nat_choke"))
        self.assertEqual(
            context.spatial, derive_control_objectives(context.intent, world())
        )


if __name__ == "__main__":
    unittest.main()
