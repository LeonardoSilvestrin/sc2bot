from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SpatialPerformance:
    """Timing and cache decisions for the most recent spatial update.

    Every component reports two costs: ``*_cache_ms`` is what it cost to
    decide whether its cached values are still valid, paid on every update;
    ``*_recompute_ms`` is what rebuilding them cost, paid only when that
    check failed (and exactly ``0.0`` otherwise). Composing the exposed field
    counts as recomputation.
    """

    samples: int
    clusters: int
    routes: int
    route_points: int
    static_cache_ms: float
    static_recompute_ms: float
    friendly_cache_ms: float
    friendly_recompute_ms: float
    route_cache_ms: float
    route_recompute_ms: float
    threat_cache_ms: float
    threat_recompute_ms: float
    compose_ms: float
    total_ms: float
    static_rebuilt: bool
    friendly_rebuilt: bool
    routes_rebuilt: bool
    threat_rebuilt: bool
    static_rebuilds: int
    friendly_rebuilds: int
    route_rebuilds: int
    threat_rebuilds: int

    @property
    def cache_check_ms(self) -> float:
        return (
            self.static_cache_ms
            + self.friendly_cache_ms
            + self.route_cache_ms
            + self.threat_cache_ms
        )

    @property
    def recompute_ms(self) -> float:
        return (
            self.static_recompute_ms
            + self.friendly_recompute_ms
            + self.route_recompute_ms
            + self.threat_recompute_ms
            + self.compose_ms
        )

    def log_fields(self) -> dict[str, Any]:
        return {
            "samples": self.samples,
            "clusters": self.clusters,
            "routes": self.routes,
            "route_points": self.route_points,
            "cache_check_ms": _ms(self.cache_check_ms),
            "recompute_ms": _ms(self.recompute_ms),
            "total_ms": _ms(self.total_ms),
            "static_cache_ms": _ms(self.static_cache_ms),
            "static_recompute_ms": _ms(self.static_recompute_ms),
            "friendly_cache_ms": _ms(self.friendly_cache_ms),
            "friendly_recompute_ms": _ms(self.friendly_recompute_ms),
            "route_cache_ms": _ms(self.route_cache_ms),
            "route_recompute_ms": _ms(self.route_recompute_ms),
            "threat_cache_ms": _ms(self.threat_cache_ms),
            "threat_recompute_ms": _ms(self.threat_recompute_ms),
            "compose_ms": _ms(self.compose_ms),
            "static_rebuilt": self.static_rebuilt,
            "friendly_rebuilt": self.friendly_rebuilt,
            "routes_rebuilt": self.routes_rebuilt,
            "threat_rebuilt": self.threat_rebuilt,
            "static_rebuilds": self.static_rebuilds,
            "friendly_rebuilds": self.friendly_rebuilds,
            "route_rebuilds": self.route_rebuilds,
            "threat_rebuilds": self.threat_rebuilds,
        }


def _ms(value: float) -> float:
    # Cache checks are usually microseconds; keep enough digits to see them.
    return round(value, 4)
