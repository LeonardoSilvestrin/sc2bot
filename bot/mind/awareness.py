from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class IntelState:
    # SCV scout
    scv_dispatched: bool = False
    scv_arrived_main: bool = False
    last_scv_dispatch_at: float = 0.0

    # scan
    scanned_enemy_main: bool = False
    last_scan_at: float = 0.0


@dataclass
class Awareness:
    intel: IntelState = field(default_factory=IntelState)