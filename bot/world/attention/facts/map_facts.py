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
class MapChoke:
    """One ground choke reported by Ares/python-sc2-map-analysis.

    ``width`` is the measured passage width, or ``None`` when the source
    geometry does not measure one; consumers must not read that as narrow.
    """

    key: str
    position: Point2
    width: float | None


@dataclass(frozen=True, slots=True)
class MapFacts:
    center: Point2
    own_start: Point2
    enemy_starts: tuple[Point2, ...]
    observations: tuple[MapObservation, ...] = ()
    routes: tuple[MapRoute, ...] = ()
    # All expansion slots on the map (ours, the enemy's, and neutral), each
    # tagged with whether it is in vision this frame -- lets Awareness track
    # which slots it has actually looked at, not just the two named
    # ``observations`` above (enemy_main/enemy_natural).
    expansions: tuple[MapObservation, ...] = ()
    # Coarse, immutable ground topology for reusable spatial reasoning.
    # The adapter computes these once Ares provides them and then reuses the
    # same tuples each frame, so a new tuple means a new topology version.
    pathable_points: tuple[Point2, ...] = ()
    pathable_sample_spacing: float = 10.0
    chokes: tuple[MapChoke, ...] = ()
    # Ground paths from likely enemy origins to currently held bases.
    traffic_routes: tuple[MapRoute, ...] = ()

    def observation(self, key: str) -> MapObservation | None:
        return next((item for item in self.observations if item.key == key), None)

    def route(self, key: str) -> MapRoute | None:
        return next((item for item in self.routes if item.key == key), None)
