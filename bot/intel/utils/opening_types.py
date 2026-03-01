from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from bot.intel.config.opening_timing_rules import DEFAULT_OPENING_TIMING_RULES, OpeningTimingRule


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
    worker_deficit_check_until_s: float = 150.0
    worker_deficit_score_cap: float = 10.0
    one_base_alert_at_s: float = 90.0
    one_base_alert_score: float = 8.0
    no_natural_alert_until_s: float = 150.0
    no_natural_alert_score: float = 4.0
    threatened_urgency_min: int = 40
    threatened_near_bases_min: int = 2
    timing_rules: Tuple[OpeningTimingRule, ...] = DEFAULT_OPENING_TIMING_RULES
