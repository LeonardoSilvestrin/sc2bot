from __future__ import annotations

import unittest
from copy import deepcopy
from types import SimpleNamespace

from sc2.position import Point2

from bot.app.debug import SpatialDebugConfig, SpatialDebugView
from bot.app.debug.spatial_view import color_for_control, format_security_label
from bot.world.awareness import (
    AwarenessSnapshot,
    BaseTerritory,
    EnemyAwareness,
    RegionTerritory,
    RelativeStrength,
    SpatialField,
    SpatialFieldSample,
    TerritoryControl,
    TerritoryReading,
    TerritorySample,
    TerritorySnapshot,
    ThreatAssessment,
)
from bot.world.awareness.bases import BaseAssessment, BaseAwareness, BaseSecurityLevel


class FakeDebugClient:
    def __init__(self) -> None:
        self.spheres: list[tuple] = []
        self.world_text: list[tuple] = []
        self.screen_text: list[tuple] = []

    def debug_sphere_out(self, *args) -> None:
        self.spheres.append(args)

    def debug_text_world(self, *args) -> None:
        self.world_text.append(args)

    def debug_text_screen(self, *args) -> None:
        self.screen_text.append(args)


def awareness_with_territory() -> AwarenessSnapshot:
    sample = TerritorySample(
        Point2((20, 20)),
        TerritoryReading(
            dominance=0.8,
            control=TerritoryControl.FRIENDLY,
            confidence=1.0,
        ),
        region="main",
    )
    region = RegionTerritory(
        key="main",
        center=Point2((20, 20)),
        expansions=(Point2((20, 20)),),
        reading=sample.reading,
        ground_access=0.09,
    )
    return AwarenessSnapshot(
        enemy=EnemyAwareness(sightings=(), locations=()),
        relative_strength=RelativeStrength(0.0, 0.0, 0, 0),
        threat=ThreatAssessment(0, 0, 0),
        updated_at=10.0,
        bases=BaseAwareness(
            (
                BaseAssessment(
                    base_id="base:1",
                    position=Point2((20, 20)),
                    is_main=True,
                    threat_score=0.0,
                    protection_score=0.0,
                    security=BaseSecurityLevel.SAFE,
                ),
            )
        ),
        spatial=SpatialField(samples=(SpatialFieldSample(Point2((20, 20))),)),
        territory=TerritorySnapshot(
            samples=(sample,),
            regions=(region,),
            bases=(BaseTerritory("base:1", Point2((20, 20)), region),),
            frontline=(Point2((25, 20)),),
            updated_at=10.0,
        ),
    )


class SpatialDebugViewTests(unittest.TestCase):
    def test_disabled_view_does_not_touch_the_bot(self):
        view = SpatialDebugView()

        view.render(SimpleNamespace(), awareness_with_territory())

    def test_control_colors_are_conventional(self):
        self.assertEqual(color_for_control(TerritoryControl.FRIENDLY), (0, 255, 0))
        self.assertEqual(color_for_control(TerritoryControl.CONTESTED), (255, 255, 0))
        self.assertEqual(color_for_control(TerritoryControl.ENEMY), (255, 0, 0))
        self.assertEqual(
            color_for_control(TerritoryControl.UNCONTROLLED), (128, 128, 128)
        )

    def test_security_label_uses_existing_region_reading(self):
        snapshot = awareness_with_territory()

        label = format_security_label(snapshot.territory.bases[0], is_main=True)

        self.assertEqual(label, "MAIN\nFRIENDLY | Sec 0.91")

    def test_territory_replaces_grid_and_snapshot_is_not_modified(self):
        snapshot = awareness_with_territory()
        before = deepcopy(snapshot)
        client = FakeDebugClient()
        bot = SimpleNamespace(
            client=client,
            get_terrain_z_height=lambda position: 8.0,
        )
        view = SpatialDebugView(
            SpatialDebugConfig(enabled=True, show_grid=True)
        )

        view.render(bot, snapshot)

        self.assertEqual(len(client.spheres), 2)  # territory + frontline
        self.assertEqual(client.spheres[0][2], (0, 255, 0))
        self.assertEqual(len(client.world_text), 1)
        self.assertEqual(len(client.screen_text), 1)
        self.assertEqual(snapshot, before)

    def test_empty_territory_falls_back_to_grid_and_panel(self):
        snapshot = awareness_with_territory()
        snapshot = AwarenessSnapshot(
            enemy=snapshot.enemy,
            relative_strength=snapshot.relative_strength,
            threat=snapshot.threat,
            updated_at=snapshot.updated_at,
            spatial=snapshot.spatial,
        )
        client = FakeDebugClient()
        bot = SimpleNamespace(
            client=client,
            get_terrain_z_height=lambda position: 8.0,
        )
        view = SpatialDebugView(
            SpatialDebugConfig(enabled=True, show_grid=True)
        )

        view.render(bot, snapshot)

        self.assertEqual(len(client.spheres), 1)
        self.assertEqual(client.spheres[0][2], (80, 180, 255))
        self.assertIn("samples: 0", client.screen_text[0][0])


if __name__ == "__main__":
    unittest.main()
