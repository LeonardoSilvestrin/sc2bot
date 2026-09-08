from __future__ import annotations

from dataclasses import dataclass

from sc2.position import Point2


@dataclass(frozen=True, slots=True)
class MapObservation:
    """A selected map point and whether the game currently exposes it."""

    key: str
    position: Point2
    visible_now: bool


@dataclass(frozen=True, slots=True)
class RouteWaypoint:
    """One point in a map route and whether it is currently in vision."""

    position: Point2
    visible_now: bool = False


@dataclass(frozen=True, slots=True)
class MapRoute:
    """A stable, map-derived route for a specialized movement profile."""

    key: str
    waypoints: tuple[RouteWaypoint, ...]


@dataclass(frozen=True, slots=True)
class MapFacts:
    center: Point2
    own_start: Point2
    enemy_starts: tuple[Point2, ...]
    observations: tuple[MapObservation, ...] = ()
    routes: tuple[MapRoute, ...] = ()

    def observation(self, key: str) -> MapObservation | None:
        return next((item for item in self.observations if item.key == key), None)

    def route(self, key: str) -> MapRoute | None:
        return next((item for item in self.routes if item.key == key), None)
