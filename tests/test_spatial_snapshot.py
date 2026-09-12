from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sc2.position import Point2

from bot.app.debug import (
    SpatialSnapshotConfig,
    SpatialSnapshotExporter,
    SpatialSnapshotRenderer,
)
from bot.app.debug.spatial_snapshot import WorldBounds, WorldToSvg
from bot.world.attention import (
    AttentionSnapshot,
    MapFacts,
    MapPassage,
    MapRegion,
    WorldFacts,
)
from bot.world.awareness import (
    AwarenessSnapshot,
    BaseAwareness,
    BaseTerritory,
    EnemyAwareness,
    EnemyBaseAssessment,
    EnemyBaseAwareness,
    EnemyBaseStatus,
    EnemyForceAwareness,
    EnemyForceCluster,
    FriendlyForce,
    PassageTerritory,
    RegionTerritory,
    RelativeStrength,
    TerritoryControl,
    TerritoryReading,
    TerritorySample,
    TerritorySnapshot,
    ThreatAssessment,
)
from bot.world.awareness.bases import BaseAssessment, BaseSecurityLevel
from tests.fakes import FakeLogger


class RecordingWriter:
    def __init__(self) -> None:
        self.writes: list[tuple[Path, str]] = []

    def write(self, path: Path, svg: str) -> None:
        self.writes.append((path, svg))


class FailingWriter:
    def write(self, path: Path, svg: str) -> None:
        raise OSError("disk full")


def reading(
    control: TerritoryControl,
    *,
    friendly: float,
    enemy: float,
    dominance: float,
    ground_denial: float = 0.0,
) -> TerritoryReading:
    return TerritoryReading(
        friendly_influence=friendly,
        enemy_influence=enemy,
        dominance=dominance,
        control=control,
        confidence=0.8,
        friendly_military=friendly,
        friendly_ground_denial=ground_denial,
    )


def snapshots(game_time: float = 30.0) -> tuple[AttentionSnapshot, AwarenessSnapshot]:
    friendly = TerritorySample(
        Point2((10, 10)),
        reading(
            TerritoryControl.FRIENDLY,
            friendly=0.9,
            enemy=0.1,
            dominance=0.8,
        ),
        region="R1",
    )
    enemy = TerritorySample(
        Point2((90, 90)),
        reading(
            TerritoryControl.ENEMY,
            friendly=0.1,
            enemy=0.9,
            dominance=-0.8,
        ),
        region="R2",
    )
    region_one = RegionTerritory(
        key="R1",
        center=Point2((20, 20)),
        expansions=(Point2((10, 10)),),
        reading=friendly.reading,
        ground_access=0.25,
    )
    region_two = RegionTerritory(
        key="R2",
        center=Point2((80, 80)),
        expansions=(Point2((90, 90)),),
        reading=enemy.reading,
    )
    passage = PassageTerritory(
        key="P1",
        position=Point2((50, 50)),
        regions=("R1", "R2"),
        reading=reading(
            TerritoryControl.FRIENDLY,
            friendly=0.8,
            enemy=0.1,
            dominance=0.9,
            ground_denial=0.8,
        ),
    )
    map_facts = MapFacts(
        center=Point2((50, 50)),
        own_start=Point2((10, 10)),
        enemy_starts=(Point2((90, 90)),),
        pathable_points=(Point2((0, 0)), Point2((100, 100))),
        regions=(
            MapRegion("R1", Point2((20, 20))),
            MapRegion("R2", Point2((80, 80))),
        ),
        passages=(MapPassage("P1", Point2((50, 50)), ("R1", "R2")),),
    )
    attention = AttentionSnapshot(
        WorldFacts(
            iteration=1,
            time=game_time,
            minerals=50,
            vespene=0,
            supply_used=12,
            supply_cap=15,
            own_units=(),
            enemy_units=(),
            map=map_facts,
        )
    )
    own_base = BaseAssessment(
        base_id="base:1",
        position=Point2((10, 10)),
        is_main=True,
        threat_score=0.0,
        protection_score=4.0,
        security=BaseSecurityLevel.SAFE,
    )
    enemy_force = EnemyForceCluster(
        cluster_id=7,
        center=Point2((75, 75)),
        radius=3.0,
        position_uncertainty=4.0,
        combat_strength=16.0,
        anti_air_strength=8.0,
        anti_ground_strength=16.0,
        unit_count=8,
        visible_unit_count=4,
        unit_tags=(1, 2),
        last_observed_at=game_time,
        confidence=0.72,
    )
    enemy_base = EnemyBaseAssessment(
        key="enemy-main",
        position=Point2((90, 90)),
        status=EnemyBaseStatus.CONFIRMED,
        economic_value=1.0,
        worker_count_estimate=12,
        workers_counted_at=game_time,
        air_defense=0.0,
        air_defense_confidence=1.0,
        ground_defense=0.0,
        ground_defense_confidence=1.0,
        last_confirmed_at=game_time,
        last_checked_at=game_time,
        confidence=1.0,
        is_stale=False,
    )
    awareness = AwarenessSnapshot(
        enemy=EnemyAwareness(
            sightings=(),
            locations=(),
            bases=EnemyBaseAwareness((enemy_base,)),
            forces=EnemyForceAwareness((enemy_force,), enemy_force),
        ),
        relative_strength=RelativeStrength(0.0, 1.0, 4, 8),
        threat=ThreatAssessment(0, 0, 0),
        updated_at=game_time,
        bases=BaseAwareness((own_base,)),
        territory=TerritorySnapshot(
            samples=(enemy, friendly),
            regions=(region_two, region_one),
            passages=(passage,),
            bases=(BaseTerritory("base:1", Point2((10, 10)), region_one),),
            friendly_forces=(FriendlyForce(Point2((25, 25)), 2.0, 24.0, 24.0, 12),),
            frontline=(Point2((48, 50)), Point2((52, 50))),
            updated_at=game_time,
        ),
    )
    return attention, awareness


class SpatialSnapshotRendererTests(unittest.TestCase):
    def test_world_coordinates_are_scaled_and_y_is_inverted(self):
        projection = WorldToSvg.fit(
            WorldBounds(0, 0, 100, 100), max_width=100, max_height=100
        )

        self.assertEqual(projection.point(Point2((0, 0))), (0.0, 100.0))
        self.assertEqual(projection.point(Point2((100, 100))), (100.0, 0.0))

    def test_output_contains_friendly_and_enemy_samples(self):
        svg = SpatialSnapshotRenderer().render(*snapshots())

        self.assertIn('data-control="friendly"', svg)
        self.assertIn('data-control="enemy"', svg)

    def test_frontline_is_rendered(self):
        svg = SpatialSnapshotRenderer().render(*snapshots())

        self.assertIn('<g id="frontline">', svg)
        frontline = svg.split('<g id="frontline">', 1)[1].split("</g>", 1)[0]
        self.assertEqual(frontline.count("<circle"), 2)

    def test_regions_passages_bases_and_forces_are_labeled(self):
        svg = SpatialSnapshotRenderer().render(*snapshots())

        self.assertIn(">R1</text>", svg)
        self.assertIn(">H 0.80</text>", svg)
        self.assertIn(">MAIN [R1]</text>", svg)
        self.assertIn(">F | Sec 0.75 Acc 0.25</text>", svg)
        self.assertIn(">OWN 24</text>", svg)
        self.assertIn(">EN 16</text>", svg)
        self.assertIn(">EN BASE enemy-main</text>", svg)

    def test_same_input_produces_identical_svg(self):
        inputs = snapshots()
        renderer = SpatialSnapshotRenderer()

        self.assertEqual(renderer.render(*inputs), renderer.render(*inputs))


class SpatialSnapshotExporterTests(unittest.TestCase):
    def test_disabled_exporter_does_not_write_or_create_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "spatial"
            writer = RecordingWriter()
            exporter = SpatialSnapshotExporter(
                config=SpatialSnapshotConfig(enabled=False),
                output_directory=output,
                logger=FakeLogger(),
                writer=writer,
            )

            self.assertFalse(exporter.capture(*snapshots()))
            self.assertEqual(writer.writes, [])
            self.assertFalse(output.exists())

    def test_game_time_interval_is_respected(self):
        writer = RecordingWriter()
        exporter = SpatialSnapshotExporter(
            config=SpatialSnapshotConfig(enabled=True, interval_seconds=30),
            output_directory=Path("spatial"),
            logger=FakeLogger(),
            writer=writer,
        )

        self.assertFalse(exporter.capture(*snapshots(29.9)))
        self.assertTrue(exporter.capture(*snapshots(30.0)))
        self.assertFalse(exporter.capture(*snapshots(59.9)))
        self.assertTrue(exporter.capture(*snapshots(60.0)))
        self.assertEqual(
            [path.name for path, _ in writer.writes],
            ["territory-0030.svg", "latest.svg", "territory-0060.svg", "latest.svg"],
        )

    def test_latest_svg_is_updated(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "spatial"
            exporter = SpatialSnapshotExporter(
                config=SpatialSnapshotConfig(enabled=True, interval_seconds=30),
                output_directory=output,
                logger=FakeLogger(),
            )

            exporter.capture(*snapshots(30.0))
            first = (output / "latest.svg").read_text(encoding="utf-8")
            exporter.capture(*snapshots(60.0))
            latest = (output / "latest.svg").read_text(encoding="utf-8")

            self.assertIn("Game time: 00:30", first)
            self.assertIn("Game time: 01:00", latest)
            self.assertEqual(
                latest,
                (output / "territory-0060.svg").read_text(encoding="utf-8"),
            )

    def test_filesystem_error_is_logged_and_does_not_escape(self):
        logger = FakeLogger()
        exporter = SpatialSnapshotExporter(
            config=SpatialSnapshotConfig(enabled=True),
            output_directory=Path("spatial"),
            logger=logger,
            writer=FailingWriter(),
        )

        self.assertFalse(exporter.capture(*snapshots()))
        self.assertEqual(logger.events[-1]["name"], "debug.spatial_snapshot_failed")
        self.assertIn("disk full", logger.events[-1]["data"]["error"])

    def test_config_rejects_non_positive_interval(self):
        with self.assertRaises(ValueError):
            SpatialSnapshotConfig(interval_seconds=0)


if __name__ == "__main__":
    unittest.main()
