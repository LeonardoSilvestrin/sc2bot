from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LanePriority:
    spending: float = 1.0
    production: float = 1.0
    tech: float = 1.0
    housekeeping: float = 1.0
    depot: float = 1.0


@dataclass(frozen=True)
class ResourceReserve:
    minerals: int = 0
    gas: int = 0
    name: str = ""


@dataclass(frozen=True)
class MacroPlanContract:
    """
    Snapshot contract for macro intent consumed by macro executors.
    This is a typed view over awareness keys, not a command executor.
    """

    mode: str = "STANDARD"
    comp: dict[str, float] = field(default_factory=dict)
    priority_units: tuple[str, ...] = ()
    reserve_unit: str = ""
    reserves: dict[str, ResourceReserve] = field(default_factory=dict)
    lane_priority: LanePriority = field(default_factory=LanePriority)
    extras: dict[str, Any] = field(default_factory=dict)
