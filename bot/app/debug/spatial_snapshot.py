"""Deterministic, offline SVG rendering of the bot's spatial snapshots."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from html import escape
from pathlib import Path
from time import perf_counter
from typing import Protocol

from sc2.position import Point2

from bot.ports.logging import BotLogger
from bot.world.attention import AttentionSnapshot
from bot.world.awareness import (
    AwarenessSnapshot,
    BaseTerritory,
    TerritoryConfig,
    TerritoryControl,
)

from .config import SpatialSnapshotConfig

_CANVAS_WIDTH = 1280
_CANVAS_HEIGHT = 1000
_MAP_LEFT = 40.0
_MAP_TOP = 40.0
_MAP_WIDTH = 900.0
_MAP_HEIGHT = 920.0
_PANEL_X = 980
_CONTROL_REACH = TerritoryConfig().military_max_reach

_CONTROL_COLORS = {
    TerritoryControl.FRIENDLY: "#35d07f",
    TerritoryControl.CONTESTED: "#f2c94c",
    TerritoryControl.ENEMY: "#eb5757",
    TerritoryControl.UNCONTROLLED: "#66707d",
}


@dataclass(frozen=True, slots=True)
class WorldBounds:
    min_x: float
    min_y: float
    max_x: float
    max_y: float

    @classmethod
    def from_points(cls, points: Iterable[Point2]) -> WorldBounds:
        coordinates = tuple((float(point.x), float(point.y)) for point in points)
        if not coordinates:
            return cls(0.0, 0.0, 1.0, 1.0)
        xs, ys = zip(*coordinates, strict=True)
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        if min_x == max_x:
            min_x, max_x = min_x - 0.5, max_x + 0.5
        if min_y == max_y:
            min_y, max_y = min_y - 0.5, max_y + 0.5
        return cls(min_x, min_y, max_x, max_y)

    @property
    def width(self) -> float:
        return self.max_x - self.min_x

    @property
    def height(self) -> float:
        return self.max_y - self.min_y


@dataclass(frozen=True, slots=True)
class WorldToSvg:
    """Aspect-preserving world projection with the SC2 Y axis inverted."""

    bounds: WorldBounds
    left: float
    top: float
    scale: float
    width: float
    height: float

    @classmethod
    def fit(
        cls,
        bounds: WorldBounds,
        *,
        left: float = 0.0,
        top: float = 0.0,
        max_width: float = 1000.0,
        max_height: float = 1000.0,
    ) -> WorldToSvg:
        scale = min(max_width / bounds.width, max_height / bounds.height)
        width = bounds.width * scale
        height = bounds.height * scale
        return cls(
            bounds=bounds,
            left=left + (max_width - width) / 2.0,
            top=top + (max_height - height) / 2.0,
            scale=scale,
            width=width,
            height=height,
        )

    def point(self, position: Point2) -> tuple[float, float]:
        x = self.left + (float(position.x) - self.bounds.min_x) * self.scale
        y = self.top + (self.bounds.max_y - float(position.y)) * self.scale
        return x, y


class SvgWriter(Protocol):
    def write(self, path: Path, svg: str) -> None:
        ...


class FileSvgWriter:
    def write(self, path: Path, svg: str) -> None:
        path.write_text(svg, encoding="utf-8")


class SpatialSnapshotRenderer:
    """Transform existing Attention/Awareness data into an SVG string."""

    def render(self, attention: AttentionSnapshot, awareness: AwarenessSnapshot) -> str:
        territory = awareness.territory
        bounds = WorldBounds.from_points(
            attention.world.map.pathable_points
            or tuple(sample.position for sample in territory.samples)
            or (attention.world.map.center,)
        )
        projection = WorldToSvg.fit(
            bounds,
            left=_MAP_LEFT,
            top=_MAP_TOP,
            max_width=_MAP_WIDTH,
            max_height=_MAP_HEIGHT,
        )
        parts = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            (
                f'<svg xmlns="http://www.w3.org/2000/svg" '
                f'width="{_CANVAS_WIDTH}" height="{_CANVAS_HEIGHT}" '
                f'viewBox="0 0 {_CANVAS_WIDTH} {_CANVAS_HEIGHT}">'
            ),
            "<style>text{font-family:monospace;fill:#e8edf2}"
            ".label{font-size:11px}.tiny{font-size:9px}"
            ".panel{font-size:14px}</style>",
            '<rect width="1280" height="1000" fill="#11161d"/>',
            _rect(
                projection.left,
                projection.top,
                projection.width,
                projection.height,
                fill="#171e27",
                stroke="#53606f",
            ),
            '<g id="expansions">',
        ]
        for item in sorted(
            attention.world.map.expansions,
            key=lambda item: (float(item.position.x), float(item.position.y), item.key),
        ):
            x, y = projection.point(item.position)
            parts.append(_circle(x, y, 3.0, fill="none", stroke="#718096"))
        parts.append('</g><g id="enemy-threat">')

        # Orange is possible threat/presence, including position uncertainty.
        # It sits underneath the categorical territory samples; red therefore
        # remains actual enemy control only.
        for threat_sample in sorted(
            awareness.spatial.samples,
            key=lambda item: (float(item.position.x), float(item.position.y)),
        ):
            if threat_sample.enemy_threat <= 0.01:
                continue
            x, y = projection.point(threat_sample.position)
            parts.append(
                _circle(
                    x,
                    y,
                    2.0 + 4.0 * threat_sample.enemy_threat,
                    fill="#f2994a",
                    opacity=0.12 + 0.35 * threat_sample.enemy_threat,
                    extra='data-field="enemy-threat"',
                )
            )
        parts.append('</g><g id="samples">')

        for territory_sample in sorted(
            territory.samples,
            key=lambda item: (float(item.position.x), float(item.position.y)),
        ):
            x, y = projection.point(territory_sample.position)
            reading = territory_sample.reading
            radius = 1.8 + 4.8 * reading.presence
            opacity = (
                0.18
                if territory_sample.control is TerritoryControl.UNCONTROLLED
                else 0.42 + 0.48 * abs(reading.dominance)
            )
            parts.append(
                _circle(
                    x,
                    y,
                    radius,
                    fill=_CONTROL_COLORS[territory_sample.control],
                    opacity=opacity,
                    extra=(
                        f'data-control="{territory_sample.control.name.lower()}"'
                    ),
                )
            )
        parts.append('</g><g id="passages">')

        regions = {region.key: region for region in territory.regions}
        for passage in sorted(territory.passages, key=lambda item: item.key):
            first = regions.get(passage.regions[0])
            second = regions.get(passage.regions[1])
            if first is not None and second is not None:
                x1, y1 = projection.point(first.center)
                x2, y2 = projection.point(second.center)
                parts.append(_line(x1, y1, x2, y2, "#526170", 1.5))
            x, y = projection.point(passage.position)
            parts.append(_circle(x, y, 4.0, fill="#10151c", stroke="#8ad4ff"))
            parts.append(_text(x + 6, y - 5, f"H {passage.reading.hold:.2f}", "tiny"))
        parts.append('</g><g id="regions">')

        for region in sorted(territory.regions, key=lambda item: item.key):
            x, y = projection.point(region.center)
            color = _CONTROL_COLORS[region.control]
            parts.append(_circle(x, y, 7.0, fill="#11161d", stroke=color))
            parts.append(_text(x + 9, y + 4, region.key, "label"))
        parts.append('</g><g id="frontline">')

        for point in sorted(
            territory.frontline, key=lambda item: (float(item.x), float(item.y))
        ):
            x, y = projection.point(point)
            parts.append(_circle(x, y, 5.0, fill="#ffffff", stroke="#11161d"))
        parts.append('</g><g id="bases">')

        own_bases = {base.base_id: base for base in awareness.bases}
        for base in sorted(territory.bases, key=lambda item: item.base_id):
            x, y = projection.point(base.position)
            assessment = own_bases.get(base.base_id)
            name = "MAIN" if assessment is not None and assessment.is_main else "BASE"
            region_key, control, security, access = _base_region(base)
            parts.append(_rect(x - 7, y - 7, 14, 14, fill="#35d07f", stroke="#fff"))
            parts.append(_text(x + 10, y - 2, f"{name} [{region_key}]", "label"))
            parts.append(
                _text(
                    x + 10,
                    y + 11,
                    f"{control} | Sec {security} Acc {access}",
                    "tiny",
                )
            )
        for enemy_base in sorted(
            awareness.enemy.bases.confirmed, key=lambda item: item.key
        ):
            x, y = projection.point(enemy_base.position)
            parts.append(_diamond(x, y, 8.0, fill="#eb5757"))
            parts.append(_text(x + 10, y + 4, f"EN BASE {enemy_base.key}", "label"))
        parts.append('</g><g id="friendly-forces">')

        for force in sorted(
            territory.friendly_forces,
            key=lambda item: (float(item.center.x), float(item.center.y)),
        ):
            x, y = projection.point(force.center)
            radius = max(8.0, min(28.0, 7.0 + force.combat_strength * 0.7))
            parts.append(
                _circle(x, y, radius, fill="none", stroke="#50e3a4", width=2.5)
            )
            parts.append(
                _text(
                    x + radius + 3,
                    y + 4,
                    f"OWN {force.combat_strength:g}",
                    "label",
                )
            )
        parts.append('</g><g id="enemy-forces">')

        for enemy_force in sorted(
            awareness.enemy.forces, key=lambda item: item.cluster_id
        ):
            x, y = projection.point(enemy_force.center)
            possible_presence = max(
                0.0, enemy_force.radius + enemy_force.position_uncertainty
            )
            control_reach = territory.military_control_reach or _CONTROL_REACH
            control_radius = max(0.0, enemy_force.radius + control_reach)
            parts.append(
                _circle(
                    x,
                    y,
                    max(6.0, control_radius * projection.scale),
                    fill="none",
                    stroke="#eb5757",
                    opacity=0.55 * enemy_force.confidence,
                    extra='data-field="enemy-control-radius"',
                )
            )
            if possible_presence > 0.0:
                parts.append(
                    _circle(
                        x,
                        y,
                        max(6.0, possible_presence * projection.scale),
                        fill="none",
                        stroke="#f2994a",
                        opacity=0.65,
                        extra=(
                            'stroke-dasharray="5 4" '
                            'data-field="enemy-possible-presence-radius"'
                        ),
                    )
                )
            radius = max(8.0, min(28.0, 7.0 + enemy_force.combat_strength * 0.7))
            parts.append(
                _circle(x, y, radius, fill="none", stroke="#ff6b6b", width=2.5)
            )
            parts.append(
                _text(
                    x + radius + 3,
                    y,
                    f"EN {enemy_force.combat_strength:g}",
                    "label",
                )
            )
            parts.append(
                _text(
                    x + radius + 3,
                    y + 12,
                    (
                        f"C {enemy_force.confidence:.2f} "
                        f"U {enemy_force.position_uncertainty:.1f}"
                    ),
                    "tiny",
                )
            )
            parts.append(
                _text(
                    x + radius + 3,
                    y + 24,
                    f"R ctl {control_radius:.1f} poss {possible_presence:.1f}",
                    "tiny",
                )
            )
        parts.append("</g>")
        parts.extend(_panel(attention, awareness))
        parts.append("</svg>")
        return "\n".join(parts) + "\n"


class SpatialSnapshotExporter:
    """Apply the game-time cadence and safely persist rendered SVG files."""

    def __init__(
        self,
        *,
        config: SpatialSnapshotConfig | None = None,
        output_directory: Path | None = None,
        logger: BotLogger,
        renderer: SpatialSnapshotRenderer | None = None,
        writer: SvgWriter | None = None,
    ) -> None:
        self.config = config or SpatialSnapshotConfig()
        self.output_directory = output_directory
        self._logger = logger
        self._renderer = renderer or SpatialSnapshotRenderer()
        self._writer = writer or FileSvgWriter()
        self._next_at = self.config.interval_seconds
        self._last_seen: float | None = None
        self.last_write_ms = 0.0
        self.last_element_count = 0

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def capture(
        self, attention: AttentionSnapshot, awareness: AwarenessSnapshot
    ) -> bool:
        if not self.enabled:
            return False
        now = float(attention.world.time)
        if self._last_seen is not None and now < self._last_seen:
            self._next_at = self.config.interval_seconds
        self._last_seen = now
        if now < self._next_at:
            return False
        while self._next_at <= now:
            self._next_at += self.config.interval_seconds

        started = perf_counter()
        try:
            if self.output_directory is None:
                raise OSError("spatial snapshot output directory is not configured")
            svg = self._renderer.render(attention, awareness)
            self.output_directory.mkdir(parents=True, exist_ok=True)
            name = _snapshot_filename(now)
            self._writer.write(self.output_directory / name, svg)
            if self.config.write_latest:
                self._writer.write(self.output_directory / "latest.svg", svg)
            self.last_write_ms = (perf_counter() - started) * 1000.0
            self.last_element_count = sum(
                svg.count(tag)
                for tag in ("<circle", "<line", "<rect", "<polygon", "<text")
            )
            self._logger.event(
                "debug.spatial_snapshot_written",
                component="app.debug.spatial_snapshot",
                game_time=now,
                data={
                    "path": str(self.output_directory / name),
                    "elements": self.last_element_count,
                    "bytes": len(svg.encode("utf-8")),
                    "render_write_ms": round(self.last_write_ms, 3),
                },
            )
            return True
        except Exception as error:  # diagnostics must never stop a match
            self._logger.event(
                "debug.spatial_snapshot_failed",
                component="app.debug.spatial_snapshot",
                game_time=now,
                data={"error": f"{type(error).__name__}: {error}"},
            )
            return False


def _base_region(base: BaseTerritory) -> tuple[str, str, str, str]:
    if base.region is None:
        return "?", "?", "n/a", "n/a"
    return (
        base.region.key,
        base.region.control.name[0],
        f"{base.region.ground_security:.2f}",
        f"{base.region.ground_access:.2f}",
    )


def _snapshot_filename(game_time: float) -> str:
    milliseconds = max(0, round(game_time * 1000))
    seconds, remainder = divmod(milliseconds, 1000)
    suffix = "" if remainder == 0 else f"-{remainder:03d}"
    return f"territory-{seconds:04d}{suffix}.svg"


def _panel(attention: AttentionSnapshot, awareness: AwarenessSnapshot) -> list[str]:
    territory = awareness.territory
    counts = {control: territory.count(control) for control in TerritoryControl}
    minutes, seconds = divmod(int(attention.world.time), 60)
    lines = [
        "TERRITORY SNAPSHOT",
        f"Game time: {minutes:02d}:{seconds:02d}",
        "",
        "Samples",
        f"Friendly       {counts[TerritoryControl.FRIENDLY]}",
        f"Contested      {counts[TerritoryControl.CONTESTED]}",
        f"Enemy          {counts[TerritoryControl.ENEMY]}",
        f"Uncontrolled   {counts[TerritoryControl.UNCONTROLLED]}",
        "",
        f"Frontline      {len(territory.frontline)}",
        f"Regions        {len(territory.regions)}",
        f"Passages       {len(territory.passages)}",
        f"Own forces     {len(territory.friendly_forces)}",
        f"Enemy forces   {len(awareness.enemy.forces)}",
        "Threat samples "
        f"{sum(s.enemy_threat > 0.05 for s in awareness.spatial.samples)}",
        f"Max ctl radius {territory.largest_control_radius:.1f}",
        f"Max uncertainty {territory.largest_position_uncertainty:.1f}",
        "",
        "Bases",
    ]
    own_bases = {base.base_id: base for base in awareness.bases}
    for base in sorted(territory.bases, key=lambda item: item.base_id):
        assessment = own_bases.get(base.base_id)
        name = "Main" if assessment is not None and assessment.is_main else "Base"
        region_key, control, security, access = _base_region(base)
        lines.append(
            f"{name:<5} [{region_key}] {control} Sec {security} Acc {access}"
        )
    result = ['<g id="panel">']
    for index, line in enumerate(lines):
        result.append(_text(_PANEL_X, 55 + index * 22, line, "panel"))
    result.append("</g>")
    return result


def _number(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _circle(
    x: float,
    y: float,
    radius: float,
    *,
    fill: str,
    stroke: str = "none",
    width: float = 1.0,
    opacity: float = 1.0,
    extra: str = "",
) -> str:
    suffix = f" {extra}" if extra else ""
    return (
        f'<circle cx="{_number(x)}" cy="{_number(y)}" r="{_number(radius)}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="{_number(width)}" '
        f'opacity="{_number(opacity)}"{suffix}/>'
    )


def _rect(
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    fill: str,
    stroke: str,
) -> str:
    return (
        f'<rect x="{_number(x)}" y="{_number(y)}" '
        f'width="{_number(width)}" height="{_number(height)}" '
        f'fill="{fill}" stroke="{stroke}"/>'
    )


def _line(x1: float, y1: float, x2: float, y2: float, color: str, width: float) -> str:
    return (
        f'<line x1="{_number(x1)}" y1="{_number(y1)}" '
        f'x2="{_number(x2)}" y2="{_number(y2)}" '
        f'stroke="{color}" stroke-width="{_number(width)}"/>'
    )


def _text(x: float, y: float, value: str, css_class: str) -> str:
    return (
        f'<text x="{_number(x)}" y="{_number(y)}" '
        f'class="{css_class}">{escape(value)}</text>'
    )


def _diamond(x: float, y: float, radius: float, *, fill: str) -> str:
    points = " ".join(
        f"{_number(px)},{_number(py)}"
        for px, py in (
            (x, y - radius),
            (x + radius, y),
            (x, y + radius),
            (x - radius, y),
        )
    )
    return f'<polygon points="{points}" fill="{fill}" stroke="#fff"/>'
