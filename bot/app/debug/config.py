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
