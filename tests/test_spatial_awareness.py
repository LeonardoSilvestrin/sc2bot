from __future__ import annotations

import unittest
from dataclasses import replace

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.world.attention import (
    AttentionSnapshot,
    MapChoke,
    MapFacts,
    MapRoute,
    RouteWaypoint,
    UnitSnapshot,
    WorldFacts,
)
from bot.world.awareness.bases import BaseAssessment, BaseAwareness, BaseSecurityLevel
from bot.world.awareness.enemy import EnemyForceAwareness, EnemyForceCluster
from bot.world.awareness.service import AwarenessService
from bot.world.awareness.spatial import (
    SpatialFieldModel,
    SpatialModelConfig,
    sample_route_positions,
)
from bot.world.awareness.spatial.kernel import saturate
from tests.fakes import FakeLogger


def base(position: Point2, *, main: bool = True) -> BaseAssessment:
    return BaseAssessment(
        base_id="base:1",
        position=position,
        is_main=main,
        threat_score=0.0,
        protection_score=0.0,
        security=BaseSecurityLevel.SAFE,
    )


def force(
    position: Point2,
    *,
    strength: float = 8.0,
    confidence: float = 1.0,
    uncertainty: float = 0.0,
) -> EnemyForceCluster:
    return EnemyForceCluster(
        cluster_id=1,
        center=position,
        radius=0.0,
        position_uncertainty=uncertainty,
        combat_strength=strength,
        anti_air_strength=strength,
        anti_ground_strength=strength,
        unit_count=4,
        visible_unit_count=4 if confidence == 1.0 else 0,
        unit_tags=(1, 2, 3, 4),
        last_observed_at=0.0,
        confidence=confidence,
    )


def world(
    points: tuple[Point2, ...],
    *,
    chokes: tuple[MapChoke, ...] = (),
    routes: tuple[MapRoute, ...] = (),
    now: float = 10.0,
) -> WorldFacts:
    return WorldFacts(
        iteration=int(now),
        time=now,
        minerals=0,
        vespene=0,
        supply_used=0.0,
        supply_cap=0.0,
        own_units=(),
        enemy_units=(),
        map=MapFacts(
            center=Point2((50, 50)),
            own_start=Point2((10, 10)),
            enemy_starts=(Point2((90, 90)),),
            pathable_points=points,
            chokes=chokes,
            traffic_routes=routes,
        ),
    )


class SpatialFieldModelTests(unittest.TestCase):
    def model(self) -> SpatialFieldModel:
        return SpatialFieldModel(SpatialModelConfig(update_interval=0.0))

    def test_friendly_value_decays_continuously_away_from_a_base(self):
        points = (Point2((10, 10)), Point2((22, 10)), Point2((46, 10)))

        field = self.model().update(
            world(points),
            bases=BaseAwareness((base(points[0]),)),
            enemy_forces=EnemyForceAwareness(),
        )

        values = tuple(sample.friendly_value for sample in field.samples)
        self.assertGreater(values[0], values[1])
        self.assertGreater(values[1], values[2])
        self.assertGreater(values[2], 0.0)

    def test_fresh_enemy_force_is_localized_and_uncertainty_spreads_threat(self):
        center, flank = Point2((50, 50)), Point2((70, 50))
        current = world((center, flank))

        fresh = self.model().update(
            current,
            bases=BaseAwareness(),
            enemy_forces=EnemyForceAwareness((force(center),)),
        )
        uncertain = self.model().update(
            current,
            bases=BaseAwareness(),
            enemy_forces=EnemyForceAwareness(
                (force(center, confidence=0.4, uncertainty=20.0),)
            ),
        )

        self.assertGreater(fresh.samples[0].enemy_threat, fresh.samples[1].enemy_threat)
        self.assertGreater(
            uncertain.samples[1].enemy_threat, fresh.samples[1].enemy_threat
        )
        self.assertLess(
            uncertain.samples[0].enemy_threat, fresh.samples[0].enemy_threat
        )
        self.assertAlmostEqual(uncertain.samples[0].confidence, 0.4)

    def test_choke_and_repeated_routes_raise_nearby_values(self):
        near, far = Point2((50, 50)), Point2((80, 80))
        route = MapRoute(
            "traffic:0:0",
            (RouteWaypoint(Point2((10, 50))), RouteWaypoint(Point2((90, 50)))),
        )
        second_route = MapRoute(
            "traffic:0:1",
            (RouteWaypoint(Point2((50, 10))), RouteWaypoint(Point2((50, 90)))),
        )

        field = self.model().update(
            world(
                (near, far),
                chokes=(MapChoke("choke:0", near, 3.0),),
                routes=(route, second_route),
            ),
            bases=BaseAwareness(),
            enemy_forces=EnemyForceAwareness(),
        )
        one_route = self.model().update(
            world((near, far), routes=(route,), now=11.0),
            bases=BaseAwareness(),
            enemy_forces=EnemyForceAwareness(),
        )

        self.assertGreater(field.samples[0].choke_value, field.samples[1].choke_value)
        self.assertGreater(field.samples[0].route_value, field.samples[1].route_value)
        self.assertGreater(
            field.samples[0].route_value, one_route.samples[0].route_value
        )

    def test_field_supports_nearest_and_radius_queries(self):
        points = (Point2((10, 10)), Point2((20, 10)), Point2((40, 10)))
        field = self.model().update(
            world(points),
            bases=BaseAwareness(),
            enemy_forces=EnemyForceAwareness(),
        )

        nearest = field.at(Point2((18, 10)))
        assert nearest is not None
        self.assertEqual(nearest.position, points[1])
        self.assertEqual(
            tuple(sample.position for sample in field.near(points[0], 11.0)),
            points[:2],
        )

    def test_awareness_exposes_force_clusters_as_spatial_threat(self):
        enemy_position = Point2((50, 50))
        far = Point2((80, 80))
        enemy = UnitSnapshot(
            tag=99,
            unit_type=UnitTypeId.MARINE,
            position=enemy_position,
            health_percentage=1.0,
            is_flying=False,
            is_worker=False,
            can_attack_air=True,
            can_attack_ground=True,
            supply_cost=1.0,
        )
        current = replace(
            world((enemy_position, far)),
            enemy_units=(enemy,),
        )

        snapshot = AwarenessService(
            spatial_model_config=SpatialModelConfig(update_interval=0.0)
        ).update(AttentionSnapshot(current))

        self.assertEqual(len(snapshot.enemy.forces), 1)
        near_sample = snapshot.spatial.at(enemy_position)
        far_sample = snapshot.spatial.at(far)
        assert near_sample is not None and far_sample is not None
        self.assertGreater(near_sample.enemy_threat, far_sample.enemy_threat)

    def test_unchanged_inputs_reuse_every_component_and_the_field(self):
        points = (Point2((10, 10)), Point2((20, 20)))
        route = MapRoute(
            "traffic:0:0",
            (RouteWaypoint(Point2((0, 0))), RouteWaypoint(Point2((30, 30)))),
        )
        routes = (route,)
        bases = BaseAwareness((base(points[0]),))
        forces = EnemyForceAwareness((force(points[1]),))
        model = SpatialFieldModel(SpatialModelConfig(update_interval=2.0))

        first = model.update(
            world(points, routes=routes, now=0.0),
            bases=bases,
            enemy_forces=forces,
        )
        second = model.update(
            world(points, routes=routes, now=1.0),
            bases=bases,
            enemy_forces=forces,
        )

        self.assertIs(first, second)
        perf = model.last_performance
        assert perf is not None
        self.assertEqual(
            (
                perf.static_rebuilds,
                perf.friendly_rebuilds,
                perf.route_rebuilds,
                perf.threat_rebuilds,
            ),
            (1, 1, 1, 1),
        )
        self.assertFalse(perf.static_rebuilt)
        self.assertFalse(perf.friendly_rebuilt)
        self.assertFalse(perf.routes_rebuilt)
        self.assertFalse(perf.threat_rebuilt)

    def test_friendly_and_route_caches_invalidate_independently(self):
        points = (Point2((10, 10)), Point2((30, 30)))
        first_route = MapRoute(
            "traffic:0:0",
            (RouteWaypoint(Point2((0, 0))), RouteWaypoint(Point2((40, 40)))),
        )
        first_routes = (first_route,)
        model = SpatialFieldModel(SpatialModelConfig(update_interval=10.0))
        forces = EnemyForceAwareness()

        model.update(
            world(points, routes=first_routes, now=0.0),
            bases=BaseAwareness((base(points[0]),)),
            enemy_forces=forces,
        )
        model.update(
            world(points, routes=first_routes, now=1.0),
            bases=BaseAwareness((base(points[1]),)),
            enemy_forces=forces,
        )
        after_base = model.last_performance
        assert after_base is not None
        self.assertTrue(after_base.friendly_rebuilt)
        self.assertFalse(after_base.routes_rebuilt)
        self.assertFalse(after_base.threat_rebuilt)

        second_routes = (
            MapRoute(
                "traffic:0:1",
                (RouteWaypoint(Point2((0, 40))), RouteWaypoint(Point2((40, 0)))),
            ),
        )
        model.update(
            world(points, routes=second_routes, now=1.5),
            bases=BaseAwareness((base(points[1]),)),
            enemy_forces=forces,
        )
        after_route = model.last_performance
        assert after_route is not None
        self.assertFalse(after_route.friendly_rebuilt)
        self.assertTrue(after_route.routes_rebuilt)
        self.assertFalse(after_route.threat_rebuilt)
        self.assertEqual(after_route.static_rebuilds, 1)
        self.assertEqual(after_route.friendly_rebuilds, 2)
        self.assertEqual(after_route.route_rebuilds, 2)
        self.assertEqual(after_route.threat_rebuilds, 1)

    def test_threat_uses_cadence_but_reacts_to_meaningful_force_change(self):
        points = (Point2((10, 10)), Point2((30, 30)))
        bases = BaseAwareness()
        initial_force = EnemyForceAwareness((force(points[0]),))
        model = SpatialFieldModel(SpatialModelConfig(update_interval=2.0))

        model.update(world(points, now=0.0), bases=bases, enemy_forces=initial_force)
        model.update(world(points, now=1.0), bases=bases, enemy_forces=initial_force)
        before_cadence = model.last_performance
        assert before_cadence is not None
        self.assertFalse(before_cadence.threat_rebuilt)

        model.update(world(points, now=2.0), bases=bases, enemy_forces=initial_force)
        on_cadence = model.last_performance
        assert on_cadence is not None
        self.assertTrue(on_cadence.threat_rebuilt)

        moved_force = EnemyForceAwareness((force(Point2((14, 10))),))
        model.update(world(points, now=2.1), bases=bases, enemy_forces=moved_force)
        after_move = model.last_performance
        assert after_move is not None
        self.assertTrue(after_move.threat_rebuilt)
        self.assertEqual(after_move.threat_rebuilds, 3)

    def test_long_route_is_distance_sampled_without_losing_local_influence(self):
        route = MapRoute(
            "traffic:long",
            tuple(RouteWaypoint(Point2((x, 50))) for x in range(181)),
        )

        sampled = sample_route_positions(route, spacing=6.0)
        field = self.model().update(
            world(
                (Point2((93, 50)), Point2((93, 80))),
                routes=(route,),
            ),
            bases=BaseAwareness(),
            enemy_forces=EnemyForceAwareness(),
        )

        self.assertEqual(len(sampled), 31)
        self.assertEqual(sampled[0], Point2((0, 50)))
        self.assertEqual(sampled[-1], Point2((180, 50)))
        self.assertGreater(field.samples[0].route_value, field.samples[1].route_value)

    def test_performance_heartbeat_is_rate_limited_and_reports_cache_state(self):
        logger = FakeLogger()
        model = SpatialFieldModel(
            SpatialModelConfig(update_interval=2.0, perf_heartbeat_interval=10.0),
            logger=logger,
        )
        points = (Point2((10, 10)),)

        for now in (0.0, 1.0, 10.0):
            model.update(
                world(points, now=now),
                bases=BaseAwareness(),
                enemy_forces=EnemyForceAwareness(),
            )

        events = [event for event in logger.events if event["name"] == "spatial.perf"]
        self.assertEqual(len(events), 2)
        self.assertEqual(events[-1]["data"]["samples"], 1)
        self.assertEqual(events[-1]["data"]["static_rebuilds"], 1)
        self.assertFalse(events[-1]["data"]["static_rebuilt"])
        self.assertTrue(events[-1]["data"]["threat_rebuilt"])

    def test_performance_separates_cache_checks_from_recomputation(self):
        points = (Point2((10, 10)), Point2((30, 30)))
        bases = BaseAwareness((base(points[0]),))
        forces = EnemyForceAwareness((force(points[1]),))
        model = SpatialFieldModel(SpatialModelConfig(update_interval=10.0))

        model.update(world(points, now=0.0), bases=bases, enemy_forces=forces)
        rebuilt = model.last_performance
        model.update(world(points, now=1.0), bases=bases, enemy_forces=forces)
        cached = model.last_performance
        assert rebuilt is not None and cached is not None

        self.assertGreater(rebuilt.recompute_ms, 0.0)
        self.assertAlmostEqual(
            rebuilt.recompute_ms,
            rebuilt.static_recompute_ms
            + rebuilt.friendly_recompute_ms
            + rebuilt.route_recompute_ms
            + rebuilt.threat_recompute_ms
            + rebuilt.compose_ms,
        )
        self.assertEqual(
            (
                cached.static_recompute_ms,
                cached.friendly_recompute_ms,
                cached.route_recompute_ms,
                cached.threat_recompute_ms,
                cached.compose_ms,
                cached.recompute_ms,
            ),
            (0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        )
        self.assertAlmostEqual(
            cached.cache_check_ms,
            cached.static_cache_ms
            + cached.friendly_cache_ms
            + cached.route_cache_ms
            + cached.threat_cache_ms,
        )
        self.assertGreaterEqual(cached.cache_check_ms, 0.0)
        self.assertLessEqual(cached.cache_check_ms, cached.total_ms)
        self.assertLessEqual(
            {
                "cache_check_ms",
                "recompute_ms",
                "static_cache_ms",
                "static_recompute_ms",
                "friendly_cache_ms",
                "friendly_recompute_ms",
                "route_cache_ms",
                "route_recompute_ms",
                "threat_cache_ms",
                "threat_recompute_ms",
            },
            set(cached.log_fields()),
        )

    def test_unmeasured_choke_is_neutral_rather_than_maximally_narrow(self):
        point = Point2((50, 50))

        narrow = self.model().update(
            world((point,), chokes=(MapChoke("choke:0", point, 3.0),)),
            bases=BaseAwareness(),
            enemy_forces=EnemyForceAwareness(),
        )
        unmeasured = self.model().update(
            world((point,), chokes=(MapChoke("choke:0", point, None),)),
            bases=BaseAwareness(),
            enemy_forces=EnemyForceAwareness(),
        )

        self.assertLess(
            unmeasured.samples[0].choke_value, narrow.samples[0].choke_value
        )
        self.assertAlmostEqual(
            unmeasured.samples[0].choke_value, saturate(0.5)
        )

    def test_static_topology_retries_until_pathable_samples_arrive(self):
        points = (Point2((10, 10)), Point2((30, 30)))
        bases = BaseAwareness((base(points[0]),))
        forces = EnemyForceAwareness()
        model = SpatialFieldModel(SpatialModelConfig(update_interval=10.0))

        pending = model.update(world((), now=0.0), bases=bases, enemy_forces=forces)
        still_pending = model.update(
            world((), now=1.0), bases=bases, enemy_forces=forces
        )
        ready = model.update(world(points, now=2.0), bases=bases, enemy_forces=forces)

        self.assertEqual(
            tuple(sample.position for sample in pending.samples),
            (Point2((50, 50)),),
        )
        self.assertIs(pending, still_pending)
        self.assertEqual(tuple(sample.position for sample in ready.samples), points)
        perf = model.last_performance
        assert perf is not None
        # Every component is indexed by the samples, so all of them follow.
        self.assertTrue(
            perf.static_rebuilt
            and perf.friendly_rebuilt
            and perf.routes_rebuilt
            and perf.threat_rebuilt
        )
        self.assertEqual(perf.static_rebuilds, 2)

    def test_equal_rebuilt_inputs_are_not_treated_as_new_versions(self):
        points = (Point2((10, 10)), Point2((30, 30)))
        chokes = (MapChoke("choke:0", points[1], 4.0),)
        route = MapRoute(
            "traffic:0:0",
            (RouteWaypoint(Point2((0, 0))), RouteWaypoint(Point2((40, 40)))),
        )
        bases = BaseAwareness((base(points[0]),))
        forces = EnemyForceAwareness()
        model = SpatialFieldModel(SpatialModelConfig(update_interval=10.0))

        first = model.update(
            world(points, chokes=chokes, routes=(route,), now=0.0),
            bases=bases,
            enemy_forces=forces,
        )
        second = model.update(
            world(
                tuple(list(points)),
                chokes=tuple(list(chokes)),
                routes=tuple([route]),
                now=1.0,
            ),
            bases=bases,
            enemy_forces=forces,
        )

        self.assertIs(first, second)
        perf = model.last_performance
        assert perf is not None
        self.assertEqual((perf.static_rebuilds, perf.route_rebuilds), (1, 1))


if __name__ == "__main__":
    unittest.main()
