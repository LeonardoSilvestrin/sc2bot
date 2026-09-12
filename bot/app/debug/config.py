from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SpatialDebugConfig:
    """Small, local-only switchboard for the spatial debug pilot."""

    enabled: bool = False
    show_grid: bool = False
    show_territory: bool = True
    show_frontline: bool = True
    show_security: bool = True


@dataclass(frozen=True, slots=True)
class SpatialSnapshotConfig:
    """Cadence and output choices for the offline SVG observer."""

    enabled: bool = False
    interval_seconds: float = 30.0
    write_latest: bool = True

    def __post_init__(self) -> None:
        if self.interval_seconds <= 0.0:
            raise ValueError("interval_seconds must be positive")
