"""In-game debug drawing for the spatial and territory snapshots.

This is deliberately an application-layer observer. It consumes the latest
Awareness snapshot, queues python-sc2 debug primitives and derives no world
state of its own.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from sc2.position import Point2, Point3

from bot.world.awareness import AwarenessSnapshot, BaseTerritory, TerritoryControl

from .config import SpatialDebugConfig

Color = tuple[int, int, int]

GRID_COLOR: Final[Color] = (80, 180, 255)
FRONTLINE_COLOR: Final[Color] = (255, 0, 255)
TEXT_COLOR: Final[Color] = (255, 255, 255)
CONTROL_COLORS: Final[dict[TerritoryControl, Color]] = {
    TerritoryControl.FRIENDLY: (0, 255, 0),
    TerritoryControl.CONTESTED: (255, 255, 0),
    TerritoryControl.ENEMY: (255, 0, 0),
    TerritoryControl.UNCONTROLLED: (128, 128, 128),
}

_GRID_RADIUS = 0.20
_TERRITORY_RADIUS = 0.32
_FRONTLINE_RADIUS = 0.65


def color_for_control(control: TerritoryControl) -> Color:
    """Presentation-only mapping from territory category to RGB."""

    return CONTROL_COLORS[control]


def format_security_label(base: BaseTerritory, *, is_main: bool) -> str:
    """Format the existing base-region security without recalculating it."""

    name = "MAIN" if is_main else "BASE"
    if base.region is None:
        return f"{name}\nUNKNOWN | Sec n/a"
    return (
        f"{name}\n{base.region.control.name} | "
        f"Sec {base.region.ground_security:.2f}"
    )


class SpatialDebugView:
    """Queue a compact visualization of the latest Awareness snapshot."""

    def __init__(self, config: SpatialDebugConfig | None = None) -> None:
        self.config = config or SpatialDebugConfig()

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def render(self, bot, awareness: AwarenessSnapshot) -> None:
        if not self.enabled:
            return

        client = bot.client
        terrain_point = _terrain_point_factory(bot)
        territory = awareness.territory

        # A territory marker already shows both that the sample exists and
        # its classification, so never stack a second grid sphere under it.
        if self.config.show_territory and territory.samples:
            for territory_sample in territory.samples:
                client.debug_sphere_out(
                    terrain_point(territory_sample.position, 0.20),
                    _TERRITORY_RADIUS,
                    color_for_control(territory_sample.control),
                )
        elif self.config.show_grid:
            for spatial_sample in awareness.spatial.samples:
                client.debug_sphere_out(
                    terrain_point(spatial_sample.position, 0.15),
                    _GRID_RADIUS,
                    GRID_COLOR,
                )

        if self.config.show_frontline:
            for point in territory.frontline:
                client.debug_sphere_out(
                    terrain_point(point, 0.35),
                    _FRONTLINE_RADIUS,
                    FRONTLINE_COLOR,
                )

        if self.config.show_security:
            own_bases = {base.base_id: base for base in awareness.bases}
            for base in territory.bases:
                assessment = own_bases.get(base.base_id)
                client.debug_text_world(
                    format_security_label(
                        base,
                        is_main=assessment is not None and assessment.is_main,
                    ),
                    terrain_point(base.position, 1.25),
                    TEXT_COLOR,
                    10,
                )

        client.debug_text_screen(
            _panel_text(awareness),
            (0.01, 0.16),
            TEXT_COLOR,
            10,
        )


def _terrain_point_factory(bot) -> Callable[[Point2, float], Point3]:
    def point(position: Point2, offset: float) -> Point3:
        return Point3(
            (
                float(position.x),
                float(position.y),
                float(bot.get_terrain_z_height(position)) + offset,
            )
        )

    return point


def _panel_text(awareness: AwarenessSnapshot) -> str:
    territory = awareness.territory
    counts = {
        control: territory.count(control) for control in TerritoryControl
    }
    return "\n".join(
        (
            "TERRITORY DEBUG",
            f"samples: {len(territory.samples)}",
            f"friendly: {counts[TerritoryControl.FRIENDLY]}",
            f"contested: {counts[TerritoryControl.CONTESTED]}",
            f"enemy: {counts[TerritoryControl.ENEMY]}",
            f"uncontrolled: {counts[TerritoryControl.UNCONTROLLED]}",
            f"frontline: {len(territory.frontline)}",
        )
    )
