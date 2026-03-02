from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from bot.intel.config.opening_timing_rules import DEFAULT_OPENING_TIMING_RULES, OpeningTimingRule


@dataclass(frozen=True)
class OpeningIntelConfig:
    ttl_s: float = 12.0
    rush_ttl_min_s: float = 10.0
    rush_ttl_max_s: float = 42.0
    rush_ttl_confirmed_bonus_s: float = 10.0
    rush_ttl_suspected_bonus_s: float = 6.0
    rush_ttl_no_natural_bonus_s: float = 8.0
    rush_ttl_hard_rule_bonus_s: float = 8.0
    rush_ttl_main_army_no_nat_bonus_s: float = 8.0
    rush_ttl_worker_deficit_bonus_s: float = 4.0
    early_s: float = 210.0
    greedy_s: float = 165.0
    rush_units_near_bases: int = 6
    rush_score_suspected: float = 48.0
    rush_score_confirmed: float = 76.0
    rush_end_clear_s: float = 22.0
    rush_hold_max_s: float = 36.0
    log_interval_s: float = 8.0
    rush_suspect_decay_s: float = 16.0
    rush_confirmed_min_hold_s: float = 90.0
    rush_structural_hold_s: float = 70.0
    rush_no_natural_hold_s: float = 55.0
    rush_worker_deficit_hold_s: float = 45.0
    expected_worker_period_s: float = 12.0
    worker_under_count_tolerance: int = 6
    worker_deficit_check_until_s: float = 150.0
    worker_deficit_score_cap: float = 10.0
    one_base_alert_at_s: float = 90.0
    one_base_alert_score: float = 8.0
    no_natural_alert_until_s: float = 150.0
    no_natural_alert_score: float = 4.0
    rush_main_army_refresh_units_min: int = 5
    rush_main_army_refresh_no_nat_until_s: float = 300.0
    threatened_urgency_min: int = 40
    threatened_near_bases_min: int = 2
    timing_rules: Tuple[OpeningTimingRule, ...] = DEFAULT_OPENING_TIMING_RULES
