from __future__ import annotations

import math
from dataclasses import dataclass, field
from time import perf_counter

from sc2.position import Point2

from bot.ports.logging import BotLogger
from bot.world.attention import MapChoke, MapRoute, WorldFacts
from bot.world.awareness.bases import BaseAwareness
from bot.world.awareness.enemy import EnemyForceAwareness

from .field import SpatialField, SpatialFieldSample
from .kernel import (
    cadence_due,
    distance_squared,
    force_influence,
    kernel_squared,
    same_version,
    saturate,
)
from .performance import SpatialPerformance

COMPONENT = "world.awareness.spatial"


@dataclass(frozen=True, slots=True)
class SpatialModelConfig:
    """Cadences and geometry of the shared spatial representation."""

    # Kept under its original name for configuration compatibility. It now
    # controls only the genuinely dynamic threat/confidence component.
    update_interval: float = 2.0
    friendly_sigma: float = 18.0
    frontier_base_weight: float = 1.15
    threat_sigma: float = 7.0
    full_threat_strength: float = 8.0
    choke_sigma: float = 5.0
    reference_choke_width: float = 5.0
    # Narrowness credited to a choke whose geometry has no measured width
    # (vision blockers, areas without sides). Unknown is neutral: a missing
    # measurement must not read as the narrowest possible passage.
    unmeasured_choke_narrowness: float = 0.5
    route_sigma: float = 4.5
    route_point_spacing: float = 8.0
    threat_position_step: float = 2.0
    threat_uncertainty_step: float = 2.0
    threat_strength_step: float = 0.5
    threat_confidence_step: float = 0.1
    perf_heartbeat_interval: float = 10.0

    def __post_init__(self) -> None:
        for name in (
            "friendly_sigma",
            "threat_sigma",
            "full_threat_strength",
            "choke_sigma",
            "reference_choke_width",
            "route_sigma",
            "route_point_spacing",
            "threat_position_step",
            "threat_uncertainty_step",
            "threat_strength_step",
            "threat_confidence_step",
            "perf_heartbeat_interval",
        ):
            if getattr(self, name) <= 0.0:
                raise ValueError(f"{name} must be positive")
        if self.update_interval < 0.0:
            raise ValueError("update_interval must not be negative")
        if self.frontier_base_weight <= 0.0:
            raise ValueError("frontier_base_weight must be positive")
        if not 0.0 <= self.unmeasured_choke_narrowness <= 1.0:
            raise ValueError("unmeasured_choke_narrowness must be between 0 and 1")


@dataclass(slots=True)
class SpatialFieldModel:
    """Build independently cached static, semi-static and dynamic fields.

    Every source still uses ``K(d, sigma) = exp(-0.5 * (d / sigma) ** 2)``
    and ``S(x) = 1 - exp(-x)`` (see ``kernel.py``). Routes use
    distance-spaced representative points instead of an exact projection
    against every polyline segment.

    Each component first checks whether its cache is still valid and only
    then recomputes; ``last_performance`` reports both costs separately.
    Topology and routes are versioned by identity -- the adapter keeps the
    same tuple until it changes -- with equality as the fallback when
    identity differs, so an identical rebuilt value is not a new version.
    """

    config: SpatialModelConfig = field(default_factory=SpatialModelConfig)
    logger: BotLogger | None = None
    last_performance: SpatialPerformance | None = field(
        default=None, init=False, repr=False
    )
    _field: SpatialField | None = field(default=None, init=False, repr=False)
    _points_source: tuple[Point2, ...] | None = field(
        default=None, init=False, repr=False
    )
    _chokes_source: tuple[MapChoke, ...] | None = field(
        default=None, init=False, repr=False
    )
    # ``center`` is a topology input only while the pathable lattice is not
    # available and the field uses its one-point fallback.
    _fallback_center: Point2 | None = field(default=None, init=False, repr=False)
    _points: tuple[Point2, ...] = field(default=(), init=False, repr=False)
    _choke_values: tuple[float, ...] = field(default=(), init=False, repr=False)
    _friendly_values: tuple[float, ...] = field(default=(), init=False, repr=False)
    _route_values: tuple[float, ...] = field(default=(), init=False, repr=False)
    _threat_values: tuple[float, ...] = field(default=(), init=False, repr=False)
    _confidences: tuple[float, ...] = field(default=(), init=False, repr=False)
    _sample_spacing: float = field(default=10.0, init=False, repr=False)
    _friendly_key: tuple | None = field(default=None, init=False, repr=False)
    _route_source: tuple[MapRoute, ...] | None = field(
        default=None, init=False, repr=False
    )
    _route_points: tuple[tuple[Point2, ...], ...] = field(
        default=(), init=False, repr=False
    )
    _threat_key: tuple | None = field(default=None, init=False, repr=False)
    _threat_updated_at: float | None = field(default=None, init=False, repr=False)
    _last_perf_logged_at: float | None = field(default=None, init=False, repr=False)
    _static_rebuilds: int = field(default=0, init=False, repr=False)
    _friendly_rebuilds: int = field(default=0, init=False, repr=False)
    _route_rebuilds: int = field(default=0, init=False, repr=False)
    _threat_rebuilds: int = field(default=0, init=False, repr=False)

    def update(
        self,
        world: WorldFacts,
        *,
        bases: BaseAwareness,
        enemy_forces: EnemyForceAwareness,
    ) -> SpatialField:
        total_started = perf_counter()
        map_facts = world.map

        started = perf_counter()
        static_valid = (
            same_version(map_facts.pathable_points, self._points_source)
            and same_version(map_facts.chokes, self._chokes_source)
            and map_facts.pathable_sample_spacing == self._sample_spacing
            and (
                bool(map_facts.pathable_points)
                or map_facts.center == self._fallback_center
            )
        )
        if static_valid:
            # Adopt an equal rebuilt value so the next check is identity again.
            self._points_source = map_facts.pathable_points
            self._chokes_source = map_facts.chokes
            self._fallback_center = map_facts.center
        static_cache_ms = _elapsed_ms(started)
        static_recompute_ms = 0.0
        if not static_valid:
            started = perf_counter()
            self._points_source = map_facts.pathable_points
            self._chokes_source = map_facts.chokes
            self._fallback_center = map_facts.center
            self._sample_spacing = map_facts.pathable_sample_spacing
            # Until the adapter has a pathing grid, one placeholder keeps the
            # field usable; the first real topology version replaces it.
            self._points = map_facts.pathable_points or (map_facts.center,)
            self._choke_values = tuple(
                self._choke_value(point, map_facts.chokes) for point in self._points
            )
            # Every other component is indexed by these samples.
            self._friendly_key = None
            self._route_source = None
            self._threat_key = None
            self._static_rebuilds += 1
            static_recompute_ms = _elapsed_ms(started)

        started = perf_counter()
        # Bases come in the order the game lists our townhalls, which is not
        # stable between frames; the component only depends on the set.
        friendly_key = tuple(
            sorted(
                (
                    base.base_id,
                    float(base.position.x),
                    float(base.position.y),
                    base.is_main,
                )
                for base in bases
            )
        )
        friendly_valid = friendly_key == self._friendly_key
        friendly_cache_ms = _elapsed_ms(started)
        friendly_recompute_ms = 0.0
        if not friendly_valid:
            started = perf_counter()
            self._friendly_key = friendly_key
            self._friendly_values = tuple(
                self._friendly_value(point, bases) for point in self._points
            )
            self._friendly_rebuilds += 1
            friendly_recompute_ms = _elapsed_ms(started)

        started = perf_counter()
        routes = map_facts.traffic_routes
        routes_valid = same_version(routes, self._route_source)
        if routes_valid:
            self._route_source = routes
        route_cache_ms = _elapsed_ms(started)
        route_recompute_ms = 0.0
        if not routes_valid:
            started = perf_counter()
            self._route_source = routes
            self._route_points = tuple(
                sample_route_positions(route, self.config.route_point_spacing)
                for route in routes
                if route.waypoints
            )
            self._route_values = tuple(
                self._route_value(point, self._route_points) for point in self._points
            )
            self._route_rebuilds += 1
            route_recompute_ms = _elapsed_ms(started)

        started = perf_counter()
        threat_key = self._enemy_force_key(enemy_forces)
        threat_valid = threat_key == self._threat_key and not cadence_due(
            world.time, self._threat_updated_at, self.config.update_interval
        )
        threat_cache_ms = _elapsed_ms(started)
        threat_recompute_ms = 0.0
        if not threat_valid:
            started = perf_counter()
            self._threat_key = threat_key
            self._threat_updated_at = world.time
            threat_values: list[float] = []
            confidences: list[float] = []
            for point in self._points:
                threat, confidence = self._threat_and_confidence(point, enemy_forces)
                threat_values.append(threat)
                confidences.append(confidence)
            self._threat_values = tuple(threat_values)
            self._confidences = tuple(confidences)
            self._threat_rebuilds += 1
            threat_recompute_ms = _elapsed_ms(started)

        compose_ms = 0.0
        if self._field is None or not (
            static_valid and friendly_valid and routes_valid and threat_valid
        ):
            started = perf_counter()
            self._field = SpatialField(
                samples=tuple(
                    SpatialFieldSample(
                        position=point,
                        friendly_value=self._friendly_values[index],
                        enemy_threat=self._threat_values[index],
                        choke_value=self._choke_values[index],
                        route_value=self._route_values[index],
                        confidence=self._confidences[index],
                    )
                    for index, point in enumerate(self._points)
                ),
                updated_at=world.time,
                sample_spacing=self._sample_spacing,
            )
            compose_ms = _elapsed_ms(started)

        assert self._field is not None
        performance = SpatialPerformance(
            samples=len(self._points),
            clusters=len(enemy_forces),
            routes=len(routes),
            route_points=sum(len(points) for points in self._route_points),
            static_cache_ms=static_cache_ms,
            static_recompute_ms=static_recompute_ms,
            friendly_cache_ms=friendly_cache_ms,
            friendly_recompute_ms=friendly_recompute_ms,
            route_cache_ms=route_cache_ms,
            route_recompute_ms=route_recompute_ms,
            threat_cache_ms=threat_cache_ms,
            threat_recompute_ms=threat_recompute_ms,
            compose_ms=compose_ms,
            total_ms=_elapsed_ms(total_started),
            static_rebuilt=not static_valid,
            friendly_rebuilt=not friendly_valid,
            routes_rebuilt=not routes_valid,
            threat_rebuilt=not threat_valid,
            static_rebuilds=self._static_rebuilds,
            friendly_rebuilds=self._friendly_rebuilds,
            route_rebuilds=self._route_rebuilds,
            threat_rebuilds=self._threat_rebuilds,
        )
        self.last_performance = performance
        self._maybe_log_performance(world.time, performance)
        return self._field

    def _friendly_value(self, point: Point2, bases: BaseAwareness) -> float:
        raw = sum(
            (1.0 if base.is_main else self.config.frontier_base_weight)
            * kernel_squared(
                distance_squared(point, base.position), self.config.friendly_sigma
            )
            for base in bases
        )
        return saturate(raw)

    def _threat_and_confidence(
        self, point: Point2, enemy_forces: EnemyForceAwareness
    ) -> tuple[float, float]:
        influence = force_influence(
            point,
            enemy_forces,
            sigma=self.config.threat_sigma,
            full_strength=self.config.full_threat_strength,
        )
        return saturate(influence.raw), influence.confidence

    def _choke_value(self, point: Point2, chokes: tuple[MapChoke, ...]) -> float:
        raw = sum(
            self._choke_narrowness(choke)
            * kernel_squared(
                distance_squared(point, choke.position), self.config.choke_sigma
            )
            for choke in chokes
        )
        return saturate(raw)

    def _choke_narrowness(self, choke: MapChoke) -> float:
        if choke.width is None:
            return self.config.unmeasured_choke_narrowness
        return min(1.0, self.config.reference_choke_width / max(1.0, choke.width))

    def _route_value(
        self, point: Point2, routes: tuple[tuple[Point2, ...], ...]
    ) -> float:
        raw = sum(
            kernel_squared(
                min(distance_squared(point, route_point) for route_point in route),
                self.config.route_sigma,
            )
            for route in routes
            if route
        )
        return saturate(raw)

    def _enemy_force_key(self, enemy_forces: EnemyForceAwareness) -> tuple:
        config = self.config
        return tuple(
            (
                cluster.cluster_id,
                round(float(cluster.center.x) / config.threat_position_step),
                round(float(cluster.center.y) / config.threat_position_step),
                round(cluster.radius / config.threat_uncertainty_step),
                round(cluster.position_uncertainty / config.threat_uncertainty_step),
                round(cluster.combat_strength / config.threat_strength_step),
                round(cluster.confidence / config.threat_confidence_step),
            )
            for cluster in enemy_forces
        )

    def _maybe_log_performance(
        self, now: float, performance: SpatialPerformance
    ) -> None:
        if self.logger is None:
            return
        if (
            self._last_perf_logged_at is not None
            and 0.0
            <= now - self._last_perf_logged_at
            < self.config.perf_heartbeat_interval
        ):
            return
        self._last_perf_logged_at = now
        self.logger.event(
            "spatial.perf",
            component=COMPONENT,
            game_time=now,
            data=performance.log_fields(),
        )


def sample_route_positions(route: MapRoute, spacing: float) -> tuple[Point2, ...]:
    """Reduce a polyline to points separated by cumulative path distance."""

    if spacing <= 0.0:
        raise ValueError("spacing must be positive")
    positions = tuple(waypoint.position for waypoint in route.waypoints)
    if len(positions) <= 1:
        return positions

    cumulative = [0.0]
    for start, end in zip(positions, positions[1:], strict=False):
        cumulative.append(cumulative[-1] + start.distance_to(end))
    total = cumulative[-1]
    if total <= 0.0:
        return (positions[0],)

    targets = [index * spacing for index in range(math.floor(total / spacing) + 1)]
    if not math.isclose(targets[-1], total):
        targets.append(total)

    sampled: list[Point2] = []
    segment = 0
    for target in targets:
        while segment + 1 < len(cumulative) and cumulative[segment + 1] < target:
            segment += 1
        start = positions[segment]
        end = positions[min(segment + 1, len(positions) - 1)]
        next_segment = min(segment + 1, len(cumulative) - 1)
        segment_length = cumulative[next_segment] - cumulative[segment]
        fraction = (
            0.0
            if segment_length <= 0.0
            else (target - cumulative[segment]) / segment_length
        )
        sampled.append(
            Point2(
                (
                    start.x + (end.x - start.x) * fraction,
                    start.y + (end.y - start.y) * fraction,
                )
            )
        )
    return tuple(sampled)


def _elapsed_ms(started: float) -> float:
    return (perf_counter() - started) * 1000.0
