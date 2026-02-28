from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WeakPointsIntelConfig:
    ttl_s: float = 20.0
