from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OpeningIntelConfig:
    ttl_s: float = 12.0
    early_s: float = 210.0
    greedy_s: float = 165.0
    rush_units_near_bases: int = 6
    rush_score_suspected: float = 48.0
    rush_score_confirmed: float = 76.0
    rush_end_clear_s: float = 22.0
    rush_hold_max_s: float = 36.0
    rush_suspect_decay_s: float = 16.0
    expected_worker_period_s: float = 12.0
    worker_under_count_tolerance: int = 6
