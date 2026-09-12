from __future__ import annotations

import re
import unittest
from dataclasses import replace
from pathlib import Path

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.world.attention import (
    AttentionSnapshot,
    MapFacts,
    MapPassage,
    MapRegion,
    UnitSnapshot,
    WorldFacts,
)
from bot.world.awareness import AwarenessService, TerritoryConfig, TerritoryControl
from bot.world.awareness.bases import BaseAssessment, BaseAwareness, BaseSecurityLevel
from bot.world.awareness.enemy import (
    EnemyAwareness,
    EnemyBaseAssessment,
    EnemyBaseAwareness,
    EnemyBaseStatus,
    EnemyForceAwareness,
    EnemyForceCluster,
)
from bot.world.awareness.spatial import SpatialField, SpatialFieldSample
from bot.world.awareness.territory import (
    TerritoryAssessor,
    TerritoryReading,
    TerritorySample,
    TerritorySnapshot,
)
from bot.world.awareness.territory.frontline import frontline, lattice_edges
from bot.world.awareness.territory.influence import classify, dominance
from bot.world.awareness.territory.topology import ground_access
from tests.fakes import FakeLogger

BOT = Path(__file__).resolve().parents[1] / "bot"
CONFIG = TerritoryConfig()
OWN_START = Point2((90, 50))
EPSILON = CONFIG.dominance_epsilon


def row(*xs: float, y: float = 50.0) -> tuple[Point2, ...]:
    return tuple(Point2((float(x), y)) for x in xs)


def army(
    position: Point2,
    supply: float,
    *,
    first_tag: int = 1,
    worker: bool = False,
    ground: bool = True,
) -> tuple[UnitSnapshot, ...]:
    """``supply`` worth of 2-supply units standing in a line centred on
    ``position``; ``ground=False`` makes them anti-air only."""

    count = max(1, round(supply / 2.0))
    if worker:
        unit_type = UnitTypeId.SCV
    else:
        unit_type = UnitTypeId.MARAUDER if ground else UnitTypeId.VIKINGFIGHTER
    return tuple(
        UnitSnapshot(
            tag=first_tag + index,
            unit_type=unit_type,
            position=Point2((position.x + 0.5 * (index - (count - 1) / 2), position.y)),
            health_percentage=1.0,
            is_flying=not ground,
            is_worker=worker,
            can_attack_air=not ground,
            can_attack_ground=ground,
            supply_cost=supply / count,
        )
        for index in range(count)
    )


def cluster(
    position: Point2,
    *,
    strength: float = 16.0,
    confidence: float = 1.0,
    uncertainty: float = 0.0,
) -> EnemyForceCluster:
    return EnemyForceCluster(
        cluster_id=1,
        center=position,
        radius=0.0,
        position_uncertainty=uncertainty,
        combat_strength=strength,
        anti_air_strength=0.0,
        anti_ground_strength=strength,
        unit_count=8,
        visible_unit_count=8 if confidence == 1.0 else 0,
        unit_tags=tuple(range(8)),
        last_observed_at=0.0,
        confidence=confidence,
    )


def enemy_base(position: Point2, confidence: float) -> EnemyBaseAssessment:
    return EnemyBaseAssessment(
        key="expansion:0",
        position=position,
        status=EnemyBaseStatus.CONFIRMED,
        economic_value=0.4,
        worker_count_estimate=0,
        workers_counted_at=None,
        air_defense=0.0,
        air_defense_confidence=confidence,
        ground_defense=0.0,
        ground_defense_confidence=confidence,
        last_confirmed_at=0.0,
        last_checked_at=0.0,
        confidence=confidence,
        is_stale=False,
    )


def enemy(
    *clusters: EnemyForceCluster, bases: tuple[EnemyBaseAssessment, ...] = ()
) -> EnemyAwareness:
    return EnemyAwareness(
        sightings=(),
        locations=(),
        bases=EnemyBaseAwareness(bases),
        forces=EnemyForceAwareness(clusters=clusters),
    )


def own_base(base_id: str, position: Point2, *, main: bool = False) -> BaseAssessment:
    return BaseAssessment(
        base_id=base_id,
        position=position,
        is_main=main,
        threat_score=0.0,
        protection_score=0.0,
        security=BaseSecurityLevel.SAFE,
    )


def world(
    points: tuple[Point2, ...],
    *,
    own_units: tuple[UnitSnapshot, ...] = (),
    now: float = 10.0,
    regions: tuple[MapRegion, ...] = (),
    passages: tuple[MapPassage, ...] = (),
    enemy_starts: tuple[Point2, ...] = (),
    own_start: Point2 = OWN_START,
    visibility: tuple[bool, ...] = (),
) -> WorldFacts:
    return WorldFacts(
        iteration=int(now),
        time=now,
        minerals=0,
        vespene=0,
        supply_used=0.0,
        supply_cap=0.0,
        own_units=own_units,
        enemy_units=(),
        map=MapFacts(
            center=Point2((50, 50)),
            own_start=own_start,
            enemy_starts=enemy_starts,
            pathable_points=points,
            pathable_visibility=visibility,
            regions=regions,
            passages=passages,
        ),
    )


def assess(
    facts: WorldFacts,
    *,
    enemy_awareness: EnemyAwareness | None = None,
    bases: BaseAwareness | None = None,
    assessor: TerritoryAssessor | None = None,
) -> TerritorySnapshot:
    return (assessor or TerritoryAssessor()).update(
        facts,
        spatial=SpatialField(
            samples=tuple(
                SpatialFieldSample(position=point)
                for point in facts.map.pathable_points
            ),
            sample_spacing=facts.map.pathable_sample_spacing,
        ),
        bases=bases or BaseAwareness(),
        enemy=enemy_awareness or enemy(),
    )


def sample(x: float, dominance_value: float, control: TerritoryControl):
    return TerritorySample(
        position=Point2((x, 50.0)),
        reading=TerritoryReading(
            friendly_influence=0.5, dominance=dominance_value, control=control
        ),
    )


F, C, E, U = (
    TerritoryControl.FRIENDLY,
    TerritoryControl.CONTESTED,
    TerritoryControl.ENEMY,
    TerritoryControl.UNCONTROLLED,
)

# enemy main -- p1 -- natural -- p2 -- main, along one row.
CHAIN_REGIONS = (
    MapRegion("enemy_main", Point2((15, 50)), row(10, 20), row(10)),
    MapRegion("natural", Point2((50, 50)), row(40, 50, 60), row(50)),
    MapRegion("main", Point2((85, 50)), row(80, 90), row(90)),
)
CHAIN_PASSAGES = (
    MapPassage("p1", Point2((30, 50)), ("enemy_main", "natural")),
    MapPassage("p2", Point2((70, 50)), ("natural", "main")),
)
CHAIN_POINTS = row(10, 20, 40, 50, 60, 80, 90)


def chain(own_units: tuple[UnitSnapshot, ...] = ()) -> WorldFacts:
    return world(
        CHAIN_POINTS,
        own_units=own_units,
        regions=CHAIN_REGIONS,
        passages=CHAIN_PASSAGES,
        enemy_starts=row(10),
    )


class DominanceTests(unittest.TestCase):
    def test_dominance_is_signed_normalized_and_stable_at_zero(self):
        self.assertGreater(dominance(0.9, 0.05, EPSILON), 0.85)
        self.assertLess(dominance(0.05, 0.9, EPSILON), -0.85)
        self.assertAlmostEqual(dominance(0.5, 0.5, EPSILON), 0.0)
        self.assertEqual(dominance(0.0, 0.0, EPSILON), 0.0)

        empty = classify(friendly=0.0, enemy=0.0, confidence=1.0, config=CONFIG)

        self.assertEqual((empty.dominance, empty.control), (0.0, U))


class ClassificationTests(unittest.TestCase):
    def control(self, friendly, enemy, *, confidence=1.0, previous=None):
        return classify(
            friendly=friendly,
            enemy=enemy,
            confidence=confidence,
            config=CONFIG,
            previous=previous,
        ).control

    def test_each_side_contested_and_uncontrolled(self):
        self.assertIs(self.control(0.9, 0.05), F)
        self.assertIs(self.control(0.05, 0.9), E)
        self.assertIs(self.control(0.6, 0.55), C)

    def test_negligible_influence_is_uncontrolled_however_lopsided(self):
        reading = classify(friendly=0.001, enemy=0.0, confidence=1.0, config=CONFIG)

        self.assertGreater(reading.dominance, 0.99)
        self.assertIs(reading.control, U)

    def test_low_confidence_keeps_a_mixed_reading_contested(self):
        self.assertIs(self.control(0.2, 0.6, confidence=1.0), E)
        self.assertIs(self.control(0.2, 0.6, confidence=0.2), C)

    def test_hysteresis_favours_the_class_a_place_already_has(self):
        # dominance ~0.395: just short of the 0.4 threshold.
        self.assertIs(self.control(0.6, 0.26), C)
        self.assertIs(self.control(0.6, 0.26, previous=F), F)
        self.assertIs(self.control(0.6, 0.26, previous=C), C)
        # presence 0.19: just under the 0.2 floor.
        self.assertIs(self.control(0.19, 0.0), U)
        self.assertIs(self.control(0.19, 0.0, previous=F), F)


class FriendlyMilitaryInfluenceTests(unittest.TestCase):
    def test_moving_an_army_projects_control_where_it_arrives(self):
        points = row(10, 20, 30, 40, 50, 60, 70, 80, 90)
        assessor = TerritoryAssessor()

        before = assess(
            world(points, own_units=army(Point2((20, 50)), 16), now=10.0),
            assessor=assessor,
        )
        after = assess(
            world(points, own_units=army(Point2((80, 50)), 16), now=11.0),
            assessor=assessor,
        )

        destination_before = before.at(Point2((80, 50)))
        destination_after = after.at(Point2((80, 50)))
        assert destination_before is not None and destination_after is not None
        self.assertGreater(
            destination_after.reading.friendly_influence,
            destination_before.reading.friendly_influence,
        )
        # No base anywhere: the control comes from the army alone.
        self.assertIs(destination_before.control, U)
        self.assertIs(destination_after.control, F)

    def test_workers_are_not_a_territorial_force(self):
        points = row(50)

        snapshot = assess(
            world(points, own_units=army(Point2((50, 50)), 12, worker=True))
        )

        self.assertEqual(snapshot.samples[0].reading.friendly_influence, 0.0)


class ConfidenceTests(unittest.TestCase):
    def test_unwatched_empty_space_is_uncontrolled_with_no_confidence(self):
        snapshot = assess(world(row(10, 50), visibility=(True, False)))

        watched, unwatched = snapshot.samples
        self.assertEqual((watched.control, watched.reading.confidence), (U, 1.0))
        self.assertEqual((unwatched.control, unwatched.reading.confidence), (U, 0.0))
        self.assertAlmostEqual(snapshot.confidence, 0.5)

    def test_a_look_fades_and_a_glimpse_between_updates_still_counts(self):
        points = row(50)
        assessor = TerritoryAssessor(TerritoryConfig(update_interval=1.0))

        assess(world(points, now=10.0, visibility=(True,)), assessor=assessor)
        faded = assess(world(points, now=25.0, visibility=(False,)), assessor=assessor)
        forgotten = assess(world(points, now=40.0), assessor=assessor)
        # In vision only on a frame the cadence skips.
        assess(world(points, now=40.5, visibility=(True,)), assessor=assessor)
        glimpsed = assess(world(points, now=41.0), assessor=assessor)

        self.assertAlmostEqual(faded.samples[0].reading.confidence, 0.5)
        self.assertEqual(forgotten.samples[0].reading.confidence, 0.0)
        self.assertAlmostEqual(glimpsed.samples[0].reading.confidence, 1.0 - 0.5 / 30.0)

    def test_a_remembered_enemy_base_vouches_for_less_than_its_own_confidence(self):
        position = Point2((50, 50))

        half = assess(
            world((position,)),
            enemy_awareness=enemy(bases=(enemy_base(position, 0.5),)),
        ).samples[0]
        sure = assess(
            world((position,)),
            enemy_awareness=enemy(bases=(enemy_base(position, 1.0),)),
        ).samples[0]

        self.assertIs(half.control, E)
        self.assertGreater(half.reading.confidence, 0.0)
        self.assertLess(half.reading.confidence, 0.5)
        self.assertGreater(sure.reading.confidence, half.reading.confidence)

    def test_stale_enemy_force_reads_wider_weaker_and_less_certain(self):
        center, flank = Point2((50, 50)), Point2((80, 50))
        facts = world((center, flank))

        fresh = assess(facts, enemy_awareness=enemy(cluster(center)))
        stale = assess(
            facts,
            enemy_awareness=enemy(cluster(center, confidence=0.4, uncertainty=20.0)),
        )
        forgotten = assess(
            facts, enemy_awareness=enemy(cluster(center, confidence=0.0))
        )
        watched = assess(
            world((center, flank), visibility=(True, False)),
            enemy_awareness=enemy(cluster(center)),
        )

        self.assertLess(
            stale.samples[0].reading.enemy_influence,
            fresh.samples[0].reading.enemy_influence,
        )
        self.assertGreater(
            stale.samples[1].reading.enemy_influence,
            fresh.samples[1].reading.enemy_influence,
        )
        self.assertLess(
            stale.samples[0].reading.confidence, fresh.samples[0].reading.confidence
        )
        # Unwatched, even a fresh army vouches only for itself, and its far
        # tail for almost nothing.
        self.assertLess(fresh.samples[0].reading.confidence, 1.0)
        self.assertLess(fresh.samples[1].reading.confidence, 0.3)
        self.assertEqual(watched.samples[0].reading.confidence, 1.0)
        self.assertEqual(forgotten.samples[0].reading.enemy_influence, 0.0)
        self.assertIs(forgotten.samples[0].control, U)


class FrontlineTests(unittest.TestCase):
    def test_frontline_sits_on_the_contested_sample_of_f_f_c_e_e(self):
        samples = (
            sample(10, 0.9, F),
            sample(20, 0.8, F),
            sample(30, 0.0, C),
            sample(40, -0.8, E),
            sample(50, -0.9, E),
        )
        edges = lattice_edges(tuple(item.position for item in samples), 10.0)

        self.assertEqual(edges, ((0, 1), (1, 2), (2, 3), (3, 4)))
        self.assertEqual(frontline(samples, edges), (Point2((30, 50)),))

    def test_frontline_slides_toward_the_side_that_is_losing_ground(self):
        samples = (sample(20, 0.8, F), sample(30, 0.2, C), sample(40, -0.8, E))
        edges = lattice_edges(tuple(item.position for item in samples), 10.0)

        (point,) = frontline(samples, edges)

        self.assertAlmostEqual(point.x, 32.0)

    def test_our_border_against_empty_map_is_not_a_front(self):
        samples = (sample(10, 0.9, F), sample(20, 0.6, F), sample(30, 0.0, U))

        self.assertEqual(
            frontline(samples, lattice_edges([s.position for s in samples], 10.0)),
            (),
        )

    def test_frontline_appears_between_opposing_armies(self):
        points = row(10, 20, 30, 40, 50, 60, 70, 80, 90)

        snapshot = assess(
            world(points, own_units=army(Point2((20, 50)), 16)),
            enemy_awareness=enemy(cluster(Point2((80, 50)))),
        )

        self.assertIs(snapshot.samples[1].control, F)
        self.assertIs(snapshot.samples[7].control, E)
        self.assertTrue(snapshot.frontline)
        self.assertTrue(all(20 < point.x < 80 for point in snapshot.frontline))


class GroundAccessTests(unittest.TestCase):
    def test_access_walks_the_widest_path_and_a_node_never_shields_itself(self):
        # enemy(0) -- p1(3) -- natural(1) -- p2(4) -- main(2)
        adjacency = ((3,), (3, 4), (4,), (0, 1), (1, 2))

        access = ground_access(
            adjacency, sources=(1, 0, 0, 0, 0), passes=(1, 0.2, 1, 0.5, 1)
        )

        for actual, expected in zip(access, (1.0, 0.5, 0.1, 1.0, 0.1), strict=True):
            self.assertAlmostEqual(actual, expected)

    def test_holding_the_natural_secures_the_main_behind_it(self):
        open_map = assess(chain()).region("main")
        held = assess(chain(army(Point2((50, 50)), 20)))
        natural, main = held.region("natural"), held.region("main")
        assert open_map is not None and natural is not None and main is not None

        # Security emerges from topology: nothing held, nothing secure.
        self.assertLess(open_map.ground_security, 0.05)
        enemy_main = held.region("enemy_main")
        assert enemy_main is not None
        self.assertEqual(enemy_main.ground_security, 0.0)
        self.assertIs(natural.control, F)
        self.assertGreater(main.ground_security, natural.ground_security)
        self.assertGreater(main.ground_security, 0.8)

    def test_one_army_is_one_barrier_per_passage_not_one_per_node(self):
        snapshot = assess(chain(army(Point2((50, 50)), 20)))

        first, second = snapshot.passages
        main = snapshot.region("main")
        assert main is not None
        self.assertAlmostEqual(
            main.ground_access,
            (1.0 - first.reading.hold) * (1.0 - second.reading.hold),
        )
        # The first model also counted the natural itself as a third wall.
        self.assertLess(main.layered_ground_access, main.ground_access)

    def test_bases_make_regions_ours_but_block_no_ground_passage(self):
        snapshot = assess(
            chain(),
            bases=BaseAwareness(
                (
                    own_base("base:natural", Point2((50, 50))),
                    own_base("base:main", Point2((90, 50)), main=True),
                )
            ),
        )

        natural, main = snapshot.region("natural"), snapshot.region("main")
        assert natural is not None and main is not None
        self.assertIs(natural.control, F)
        self.assertLess(main.ground_security, 0.05)

    def test_anti_air_units_are_presence_but_deny_no_ground_passage(self):
        snapshot = assess(chain(army(Point2((50, 50)), 20, ground=False)))

        natural = snapshot.at(Point2((50, 50)))
        main = snapshot.region("main")
        assert natural is not None and main is not None
        self.assertGreater(natural.reading.friendly_military, 0.5)
        self.assertEqual(natural.reading.friendly_ground_denial, 0.0)
        self.assertIs(natural.control, F)
        self.assertLess(main.ground_security, 0.05)

    def test_an_open_second_route_leaves_the_main_exposed(self):
        points = row(10, 20) + row(80, 90)
        facts = world(
            points,
            regions=(
                MapRegion("enemy_main", Point2((15, 50)), row(10, 20)),
                MapRegion("main", Point2((85, 50)), row(80, 90)),
            ),
            passages=(
                MapPassage("route_a", Point2((50, 20)), ("enemy_main", "main")),
                MapPassage("route_b", Point2((50, 80)), ("enemy_main", "main")),
            ),
            enemy_starts=row(10),
        )

        one_held = assess(replace(facts, own_units=army(Point2((50, 20)), 20)))
        both_held = assess(
            replace(
                facts,
                own_units=army(Point2((50, 20)), 20)
                + army(Point2((50, 80)), 20, first_tag=100),
            )
        )

        one_main = one_held.region("main")
        both_main = both_held.region("main")
        assert one_main is not None and both_main is not None
        self.assertLess(one_main.ground_security, 0.2)
        self.assertGreater(both_main.ground_security, 0.5)


class TerritoryStructureTests(unittest.TestCase):
    def test_topology_is_built_once_and_readings_follow_the_cadence(self):
        facts = chain()
        assessor = TerritoryAssessor(TerritoryConfig(update_interval=1.0))

        first = assess(facts, assessor=assessor)
        cached = assess(replace(facts, time=10.5), assessor=assessor)
        # An equal, rebuilt value is not a new topology version.
        rebuilt_equal = world(
            tuple(list(CHAIN_POINTS)),
            regions=tuple(list(CHAIN_REGIONS)),
            passages=CHAIN_PASSAGES,
            enemy_starts=row(10),
            now=11.0,
        )
        refreshed = assess(rebuilt_equal, assessor=assessor)

        self.assertIs(first, cached)
        self.assertIsNot(refreshed, first)
        self.assertEqual((assessor.topology_rebuilds, assessor.updates), (1, 2))

        assess(
            replace(
                facts,
                time=11.2,
                map=replace(facts.map, passages=CHAIN_PASSAGES[:1]),
            ),
            assessor=assessor,
        )

        # A new topology version rebuilds at once, off cadence.
        self.assertEqual((assessor.topology_rebuilds, assessor.updates), (2, 3))

    def test_performance_heartbeat_is_rate_limited(self):
        logger = FakeLogger()
        assessor = TerritoryAssessor(
            TerritoryConfig(update_interval=0.0), logger=logger
        )

        for now in (0.0, 1.0, 10.0):
            assess(world(CHAIN_POINTS, now=now), assessor=assessor)

        events = [event for event in logger.events if event["name"] == "territory.perf"]
        self.assertEqual(len(events), 2)
        self.assertEqual(events[-1]["data"]["topology_rebuilds"], 1)
        self.assertEqual(events[-1]["data"]["updates"], 3)

    def test_awareness_snapshot_places_our_bases_in_their_regions(self):
        facts = chain(army(Point2((50, 50)), 20))

        territory = AwarenessService().update(AttentionSnapshot(facts)).territory

        # Without a townhall, Attention stands the main in at our start.
        (base,) = territory.bases
        assert base.region is not None
        self.assertEqual(base.region.key, "main")
        self.assertGreater(base.region.ground_security, 0.8)
        self.assertIs(
            territory.region_at(Point2((52, 51))), territory.region("natural")
        )


class ShadowModeTests(unittest.TestCase):
    def test_no_behavior_macro_or_engine_reads_territory_yet(self):
        pattern = re.compile(r"\.territory\b|\w*Territory\w*")
        readers = [
            str(path.relative_to(BOT))
            for package in ("behavior", "macro", "engine")
            for path in (BOT / package).rglob("*.py")
            if pattern.search(path.read_text(encoding="utf-8"))
        ]

        self.assertEqual(readers, [])


if __name__ == "__main__":
    unittest.main()
