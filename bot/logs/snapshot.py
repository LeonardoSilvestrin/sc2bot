"""Deterministic offline SVG snapshots of the influence field and the frame's
decisions, for the log viewer. Presentation only."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from html import escape
from pathlib import Path
from time import perf_counter
from typing import Protocol

from sc2.position import Point2

from bot.attention import AttentionState, is_army
from bot.awareness import AwarenessState
from bot.awareness.field import PRESENCE_FLOOR
from bot.body.engine import EngineResult
from bot.ego.planners.map_control import MapControlPlan
from bot.ego.strategy import StrategicIntent

from .jsonl import BotLogger, NullLogger
from .overlay import OTHER_OWNER_COLOR, OWNER_COLORS, influence_color

CANVAS_WIDTH = 1280
CANVAS_HEIGHT = 1000
_MAP_LEFT = 40.0
_MAP_TOP = 40.0
_MAP_WIDTH = 900.0
_MAP_HEIGHT = 920.0
_PANEL_X = 975


@dataclass(frozen=True, slots=True)
class SnapshotConfig:
    enabled: bool = False
    interval_seconds: float = 30.0
    # Also capture the frame the posture changes.
    on_posture_change: bool = True
    write_latest: bool = True

    def __post_init__(self) -> None:
        if self.interval_seconds <= 0.0:
            raise ValueError("interval_seconds must be positive")


@dataclass(frozen=True, slots=True)
class Projection:
    """Aspect-preserving world-to-SVG projection with the SC2 Y axis inverted."""

    min_x: float
    max_y: float
    left: float
    top: float
    scale: float
    width: float
    height: float

    @classmethod
    def fit(cls, bounds: tuple[float, float, float, float]) -> Projection:
        min_x, min_y, max_x, max_y = bounds
        span_x = max(1.0, max_x - min_x)
        span_y = max(1.0, max_y - min_y)
        scale = min(_MAP_WIDTH / span_x, _MAP_HEIGHT / span_y)
        width, height = span_x * scale, span_y * scale
        return cls(
            min_x=min_x,
            max_y=max_y,
            left=_MAP_LEFT + (_MAP_WIDTH - width) / 2.0,
            top=_MAP_TOP + (_MAP_HEIGHT - height) / 2.0,
            scale=scale,
            width=width,
            height=height,
        )

    def point(self, position: Point2) -> tuple[float, float]:
        return (
            self.left + (float(position.x) - self.min_x) * self.scale,
            self.top + (self.max_y - float(position.y)) * self.scale,
        )


def render_svg(
    attention: AttentionState,
    awareness: AwarenessState,
    intent: StrategicIntent,
    map_control: MapControlPlan,
    result: EngineResult,
) -> str:
    projection = Projection.fit(attention.map.bounds)
    influence = awareness.influence
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{CANVAS_WIDTH}" '
        f'height="{CANVAS_HEIGHT}" viewBox="0 0 {CANVAS_WIDTH} {CANVAS_HEIGHT}">',
        "<style>text{font-family:monospace;fill:#e8edf2}"
        ".label{font-size:11px}.tiny{font-size:9px}.panel{font-size:14px}"
        ".head{font-size:14px;font-weight:bold;fill:#8ad4ff}</style>",
        f'<rect width="{CANVAS_WIDTH}" height="{CANVAS_HEIGHT}" fill="#11161d"/>',
        _rect(
            projection.left,
            projection.top,
            projection.width,
            projection.height,
            fill="#171e27",
            stroke="#53606f",
        ),
        '<g id="threat">',
    ]
    # Orange underneath: possible presence, uncertainty included. The colored
    # samples above it are credible presence only.
    for index, position in enumerate(influence.positions):
        threat = float(influence.threat[index])
        if threat <= 0.01:
            continue
        x, y = projection.point(position)
        parts.append(
            _circle(
                x,
                y,
                1.5 + 4.5 * threat,
                fill="#f2994a",
                opacity=0.1 + 0.35 * threat,
                extra='data-field="threat"',
            )
        )
    parts.append('</g><g id="influence">')
    for index, position in enumerate(influence.positions):
        support = float(influence.support[index])
        enemy = float(influence.enemy[index])
        strength = max(support, enemy)
        x, y = projection.point(position)
        parts.append(
            _circle(
                x,
                y,
                1.2 + 3.8 * strength,
                fill=_hex(influence_color(support, enemy, 0.0)),
                opacity=0.16 if strength < PRESENCE_FLOOR else 0.35 + 0.55 * strength,
            )
        )
    parts.append('</g><g id="topology">')
    topology = attention.map.topology
    topology_regions = {region.region_id: region for region in topology.regions}
    for passage in topology.passages:
        px, py = projection.point(passage.position)
        for region_id in passage.regions:
            region = topology_regions[region_id]
            rx, ry = projection.point(region.center)
            parts.append(
                _line(rx, ry, px, py, "#596779", 1.0, dashed=passage.kind == "border")
            )
        parts.append(
            _circle(
                px,
                py,
                3.5,
                fill="#ffd166",
                stroke="#11161d",
                extra=f'data-passage="{escape(passage.passage_id)}"',
            )
        )
    for candidate in topology.choke_candidates:
        if candidate.accepted or candidate.position is None:
            continue
        cx, cy = projection.point(candidate.position)
        parts.append(
            _circle(
                cx,
                cy,
                4.0,
                fill="none",
                stroke="#eb5757",
                width=1.5,
                extra=f'data-choke-rejected="{escape(candidate.reason)}"',
            )
        )
        parts.append(_text(cx + 6, cy + 9, candidate.reason, "tiny"))
    for region in topology.regions:
        x, y = projection.point(region.center)
        parts.append(
            _circle(
                x,
                y,
                4.5,
                fill="#8ad4ff",
                stroke="#11161d",
                extra=f'data-region="{escape(region.region_id)}"',
            )
        )
        parts.append(_text(x + 6, y - 5, region.region_id, "tiny"))
    parts.append('</g><g id="expansions">')
    for expansion in attention.map.expansions:
        x, y = projection.point(expansion)
        parts.append(_circle(x, y, 3.0, fill="none", stroke="#718096"))
    parts.append('</g><g id="bases">')
    for base in awareness.bases:
        x, y = projection.point(base.position)
        parts.append(_rect(x - 7, y - 7, 14, 14, fill="#35d07f", stroke="#ffffff"))
        parts.append(
            _text(
                x + 10,
                y - 2,
                f"{'MAIN' if base.is_main else 'BASE'} thr {base.threat:.2f}",
                "label",
            )
        )
        parts.append(
            _text(x + 10, y + 11, f"p {base.pressure:.1f} c {base.cover:.1f}", "tiny")
        )
        if base.center is not None:
            cx, cy = projection.point(base.center)
            parts.append(_line(x, y, cx, cy, "#eb5757", 1.5, dashed=True))
    parts.append('</g><g id="contacts">')
    for contact in awareness.contacts:
        x, y = projection.point(contact.position)
        opacity = 0.25 + 0.75 * contact.confidence
        if contact.is_structure:
            parts.append(
                _rect(
                    x - 3, y - 3, 6, 6, fill="#eb5757", stroke="none", opacity=opacity
                )
            )
            continue
        if contact.uncertainty > 0.0:
            parts.append(
                _circle(
                    x,
                    y,
                    max(4.0, contact.uncertainty * projection.scale),
                    fill="none",
                    stroke="#f2994a",
                    opacity=0.6,
                    extra='stroke-dasharray="5 4" data-field="uncertainty"',
                )
            )
        radius = max(2.5, min(14.0, 2.5 + 3.0 * math.sqrt(max(0.0, contact.power))))
        parts.append(
            _circle(
                x,
                y,
                radius,
                fill="#ff6b6b" if contact.visible else "none",
                stroke="#ff6b6b",
                width=1.5,
                opacity=opacity,
                extra=f'data-contact="{"visible" if contact.visible else "remembered"}"',
            )
        )
    parts.append('</g><g id="army">')
    owner_of = {
        grant.proposal.proposal_id: grant.proposal.owner for grant in result.grants
    }
    owners = dict(result.owners)
    for unit in attention.own_units:
        if not is_army(unit):
            continue
        x, y = projection.point(unit.position)
        owner = owner_of.get(owners.get(unit.tag, ""), "")
        parts.append(
            _circle(
                x,
                y,
                2.8,
                fill=_hex(OWNER_COLORS.get(owner, OTHER_OWNER_COLOR)),
                stroke="#11161d",
                extra=f'data-owner="{escape(owner)}"',
            )
        )
    parts.append('</g><g id="targets">')
    for grant in result.grants:
        if not grant.tags:
            continue
        proposal = grant.proposal
        x, y = projection.point(proposal.target)
        color = _hex(OWNER_COLORS.get(proposal.owner, OTHER_OWNER_COLOR))
        parts.append(_line(x - 6, y - 6, x + 6, y + 6, color, 2.5))
        parts.append(_line(x - 6, y + 6, x + 6, y - 6, color, 2.5))
        parts.append(
            _text(
                x + 9,
                y + 4,
                f"{proposal.proposal_id} {len(grant.tags)}u {proposal.command.value}",
                "label",
            )
        )
    # Base labels sit right of their square and grant labels right of their
    # cross, so the anchor label goes left: the anchor is often on a base.
    held = next(
        (
            passage
            for passage in attention.map.topology.passages
            if passage.passage_id == map_control.held_passage
        ),
        None,
    )
    if held is not None:
        px, py = projection.point(held.position)
        parts.append(
            _circle(
                px,
                py,
                8.0,
                fill="none",
                stroke="#ffffff",
                width=1.5,
                extra=f'data-held-passage="{escape(held.passage_id)}"',
            )
        )
    x, y = projection.point(map_control.anchor)
    parts.append(_diamond(x, y, 7.0, fill="#ffffff"))
    parts.append(_text(x - 52, y - 10, "ANCHOR", "label"))
    parts.append("</g>")
    parts.extend(_panel(attention, awareness, intent, result))
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


class SvgWriter(Protocol):
    def write(self, path: Path, svg: str) -> None:
        ...


class FileSvgWriter:
    def write(self, path: Path, svg: str) -> None:
        path.write_text(svg, encoding="utf-8")


class SnapshotExporter:
    """Applies the game-time cadence and safely persists rendered SVG files."""

    def __init__(
        self,
        *,
        config: SnapshotConfig | None = None,
        directory: Path | None = None,
        logger: BotLogger | None = None,
        writer: SvgWriter | None = None,
    ) -> None:
        self.config = config or SnapshotConfig()
        self.directory = directory
        self._logger = logger or NullLogger()
        self._writer = writer or FileSvgWriter()
        self._next_at = self.config.interval_seconds
        self._posture = None

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def capture(
        self,
        attention: AttentionState,
        awareness: AwarenessState,
        intent: StrategicIntent,
        map_control: MapControlPlan,
        result: EngineResult,
    ) -> bool:
        if not self.enabled:
            return False
        now = attention.time
        changed = (
            self.config.on_posture_change
            and self._posture is not None
            and intent.posture is not self._posture
        )
        self._posture = intent.posture
        due = now >= self._next_at
        if not (due or changed):
            return False
        while self._next_at <= now:
            self._next_at += self.config.interval_seconds
        started = perf_counter()
        try:
            if self.directory is None:
                raise OSError("snapshot directory is not configured")
            svg = render_svg(attention, awareness, intent, map_control, result)
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.directory / snapshot_filename(now)
            self._writer.write(path, svg)
            if self.config.write_latest:
                self._writer.write(self.directory / "latest.svg", svg)
            self._logger.event(
                "logs.snapshot_written",
                component="logs",
                game_time=now,
                data={
                    "path": str(path),
                    "trigger": "posture_changed" if changed else "interval",
                    "posture": intent.posture.value,
                    "elements": sum(
                        svg.count(tag)
                        for tag in ("<circle", "<line", "<rect", "<polygon", "<text")
                    ),
                    "bytes": len(svg.encode("utf-8")),
                    "render_write_ms": round((perf_counter() - started) * 1000.0, 3),
                },
            )
            return True
        except Exception as error:  # diagnostics must never stop a match
            self._logger.event(
                "logs.snapshot_failed",
                component="logs",
                game_time=now,
                data={"error": f"{type(error).__name__}: {error}"},
            )
            return False


def snapshot_filename(game_time: float) -> str:
    milliseconds = max(0, round(game_time * 1000))
    seconds, remainder = divmod(milliseconds, 1000)
    suffix = "" if remainder == 0 else f"-{remainder:03d}"
    return f"field-{seconds:04d}{suffix}.svg"


def _panel(
    attention: AttentionState,
    awareness: AwarenessState,
    intent: StrategicIntent,
    result: EngineResult,
) -> list[str]:
    assessment = intent.assessment
    scores = dict(intent.scores)
    summary = awareness.influence.summary()
    visible = sum(contact.visible for contact in awareness.contacts)
    rows: list[tuple[str, str]] = [
        ("head", "FIELD SNAPSHOT"),
        ("panel", f"Game time      {_clock(attention.time)}"),
        ("panel", ""),
        ("head", "STRATEGY"),
        ("panel", f"Posture   {intent.posture.value}"),
        ("panel", f"Reason    {intent.reason}"),
        ("panel", f"Since     {_clock(intent.since)}"),
        (
            "panel",
            f"Threat {assessment.threat_level:.2f}  Army {assessment.army_position:+.2f}",
        ),
        (
            "panel",
            f"Spike {assessment.power_spike:.2f}  Conf {assessment.confidence:.2f}",
        ),
        (
            "panel",
            f"Def {intent.defense:.2f} Army {intent.army:.2f} Risk {intent.risk:.2f}",
        ),
        (
            "panel",
            "Scores "
            + "  ".join(f"{name[:5]} {value:.2f}" for name, value in scores.items()),
        ),
        ("panel", ""),
        ("head", "AWARENESS"),
        ("panel", f"Contacts  {len(awareness.contacts)} ({visible} visible)"),
        (
            "panel",
            f"Power     own {awareness.own_power:.1f} enemy {awareness.enemy_power:.1f}"
            f" est {awareness.estimated_enemy_power:.1f}",
        ),
        ("panel", f"Samples   {summary['samples']}"),
        (
            "panel",
            f"Own/Cont/Enemy {summary['friendly']}/{summary['contested']}/{summary['enemy']}",
        ),
        (
            "panel",
            f"Threatened {summary['threatened']}  max {summary['max_threat']:.2f}",
        ),
    ]
    for base in awareness.bases:
        rows.append(
            (
                "panel",
                f"{'Main' if base.is_main else 'Base'} {base.threat:.2f} "
                f"p{base.pressure:.1f} c{base.cover:.1f}",
            )
        )
    topology = attention.map.topology
    candidates = topology.choke_candidates
    accepted = sum(candidate.accepted for candidate in candidates)
    rows += [
        ("panel", ""),
        ("head", "TOPOLOGY"),
        ("panel", f"Chokes {accepted}/{len(candidates)} accepted"),
        (
            "panel",
            f"Rejected {len(candidates) - accepted}  Splits {len(topology.region_splits)}",
        ),
    ]
    rows += [("panel", ""), ("head", "ENGINE")]
    for grant in result.grants:
        rows.append(
            ("panel", f"{grant.proposal.proposal_id[:22]:<22} {len(grant.tags):>3}u")
        )
    rows.append(("panel", f"unassigned {len(result.unassigned)}"))
    result_parts = ['<g id="panel">']
    for index, (css, line) in enumerate(rows):
        result_parts.append(_text(_PANEL_X, 55 + index * 21, line, css))
    result_parts.append("</g>")
    return result_parts


def _clock(seconds: float) -> str:
    minutes, rest = divmod(int(seconds), 60)
    return f"{minutes:02d}:{rest:02d}"


def _hex(color: Iterable[int]) -> str:
    return "#" + "".join(f"{int(channel):02x}" for channel in color)


def _number(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _circle(
    x, y, radius, *, fill, stroke="none", width=1.0, opacity=1.0, extra=""
) -> str:
    suffix = f" {extra}" if extra else ""
    return (
        f'<circle cx="{_number(x)}" cy="{_number(y)}" r="{_number(radius)}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="{_number(width)}" '
        f'opacity="{_number(opacity)}"{suffix}/>'
    )


def _rect(x, y, width, height, *, fill, stroke, opacity=1.0) -> str:
    return (
        f'<rect x="{_number(x)}" y="{_number(y)}" width="{_number(width)}" '
        f'height="{_number(height)}" fill="{fill}" stroke="{stroke}" opacity="{_number(opacity)}"/>'
    )


def _line(x1, y1, x2, y2, color, width, *, dashed=False) -> str:
    dash = ' stroke-dasharray="4 3"' if dashed else ""
    return (
        f'<line x1="{_number(x1)}" y1="{_number(y1)}" x2="{_number(x2)}" '
        f'y2="{_number(y2)}" stroke="{color}" stroke-width="{_number(width)}"{dash}/>'
    )


def _text(x, y, value: str, css_class: str) -> str:
    return f'<text x="{_number(x)}" y="{_number(y)}" class="{css_class}">{escape(value)}</text>'


def _diamond(x, y, radius, *, fill, stroke="#11161d") -> str:
    points = " ".join(
        f"{_number(px)},{_number(py)}"
        for px, py in (
            (x, y - radius),
            (x + radius, y),
            (x, y + radius),
            (x - radius, y),
        )
    )
    return f'<polygon points="{points}" fill="{fill}" stroke="{stroke}"/>'
