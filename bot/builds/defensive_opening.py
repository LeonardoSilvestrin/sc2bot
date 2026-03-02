from __future__ import annotations

from typing import Any, Dict


PROFILE: Dict[str, Any] = {
    "comp_defensive": {"MARINE": 0.68, "MARAUDER": 0.16, "SIEGETANK": 0.12, "MEDIVAC": 0.04},
    "comp_standard": {"MARINE": 0.58, "MARAUDER": 0.19, "SIEGETANK": 0.13, "MEDIVAC": 0.10},
    "comp_punish": {"MARINE": 0.57, "MARAUDER": 0.15, "SIEGETANK": 0.13, "MEDIVAC": 0.15},
    "comp_rush_response": {"MARINE": 0.58, "MARAUDER": 0.20, "SIEGETANK": 0.18, "MEDIVAC": 0.04},
    "priority_defensive": ["MARINE", "SIEGETANK", "MARAUDER", "MEDIVAC"],
    "priority_standard": ["MARINE", "SIEGETANK", "MARAUDER", "MEDIVAC"],
    "priority_punish": ["SIEGETANK", "MARINE", "MEDIVAC", "MARAUDER"],
    "priority_rush_response": ["MARINE", "SIEGETANK", "MARAUDER", "MEDIVAC"],
    "reserve_costs": {
        "SIEGETANK": (150, 125),
        "MARINE": (50, 0),
        "MARAUDER": (100, 25),
        "MEDIVAC": (100, 100),
        "REAPER": (50, 50),
        "HELLION": (100, 0),
        "BANSHEE": (150, 100),
    },
    "bank_setpoint_minerals": {"RUSH_RESPONSE": 330, "DEFENSIVE": 420, "STANDARD": 560, "PUNISH": 780},
    "bank_setpoint_gas": {"RUSH_RESPONSE": 140, "DEFENSIVE": 170, "STANDARD": 210, "PUNISH": 280},
    "pid_tuning_by_mode": {
        "RUSH_RESPONSE": {
            "lag_pi_kp": 0.98,
            "lag_pi_ki": 0.24,
            "production_lag_weight_boost": 0.78,
            "tech_lag_inflight_dampen_gain": 0.82,
            "block_production_max_lag_prod": 0.82,
            "timing_attack_production_weight_boost": 0.58,
        },
        "DEFENSIVE": {
            "lag_pi_kp": 0.94,
            "lag_pi_ki": 0.25,
            "production_lag_weight_boost": 0.72,
            "tech_lag_inflight_dampen_gain": 0.78,
            "block_production_max_lag_prod": 0.78,
            "timing_attack_production_weight_boost": 0.68,
        },
        "STANDARD": {
            "lag_pi_kp": 0.88,
            "lag_pi_ki": 0.22,
            "production_lag_weight_boost": 0.64,
            "tech_lag_inflight_dampen_gain": 0.74,
            "block_production_max_lag_prod": 0.70,
            "timing_attack_production_weight_boost": 0.88,
        },
        "PUNISH": {
            "lag_pi_kp": 0.92,
            "lag_pi_ki": 0.22,
            "production_lag_weight_boost": 0.69,
            "tech_lag_inflight_dampen_gain": 0.75,
            "block_production_max_lag_prod": 0.72,
            "timing_attack_production_weight_boost": 0.98,
        },
    },
    "army_supply_milestones_by_mode": {
        "RUSH_RESPONSE": [
            {"t": 90.0, "supply": 12.0},
            {"t": 150.0, "supply": 24.0},
            {"t": 210.0, "supply": 36.0},
            {"t": 300.0, "supply": 54.0},
            {"t": 420.0, "supply": 78.0},
            {"t": 540.0, "supply": 98.0},
            {"t": 660.0, "supply": 116.0},
            {"t": 780.0, "supply": 130.0},
        ],
        "DEFENSIVE": [
            {"t": 90.0, "supply": 11.0},
            {"t": 150.0, "supply": 20.0},
            {"t": 210.0, "supply": 32.0},
            {"t": 300.0, "supply": 48.0},
            {"t": 420.0, "supply": 72.0},
            {"t": 540.0, "supply": 90.0},
            {"t": 660.0, "supply": 108.0},
            {"t": 780.0, "supply": 124.0},
        ],
        "STANDARD": [
            {"t": 90.0, "supply": 9.0},
            {"t": 150.0, "supply": 17.0},
            {"t": 210.0, "supply": 28.0},
            {"t": 270.0, "supply": 40.0},
            {"t": 360.0, "supply": 56.0},
            {"t": 480.0, "supply": 80.0},
            {"t": 600.0, "supply": 100.0},
            {"t": 720.0, "supply": 120.0},
            {"t": 840.0, "supply": 138.0},
        ],
        "PUNISH": [
            {"t": 90.0, "supply": 10.0},
            {"t": 150.0, "supply": 20.0},
            {"t": 210.0, "supply": 32.0},
            {"t": 270.0, "supply": 46.0},
            {"t": 360.0, "supply": 66.0},
            {"t": 480.0, "supply": 90.0},
            {"t": 600.0, "supply": 112.0},
            {"t": 720.0, "supply": 132.0},
            {"t": 840.0, "supply": 146.0},
        ],
    },
    "unit_count_milestones_by_mode": {
        "RUSH_RESPONSE": [
            {"t": 90.0, "units": {"MARINE": 10, "MARAUDER": 1}},
            {"t": 150.0, "units": {"MARINE": 18, "MARAUDER": 3, "SIEGETANK": 2}},
            {"t": 210.0, "units": {"MARINE": 26, "MARAUDER": 5, "SIEGETANK": 3, "MEDIVAC": 1}},
        ],
        "DEFENSIVE": [
            {"t": 90.0, "units": {"MARINE": 9, "MARAUDER": 1}},
            {"t": 150.0, "units": {"MARINE": 16, "MARAUDER": 3, "SIEGETANK": 2}},
            {"t": 210.0, "units": {"MARINE": 24, "MARAUDER": 5, "SIEGETANK": 3, "MEDIVAC": 1}},
        ],
        "STANDARD": [
            {"t": 90.0, "units": {"MARINE": 7, "HELLION": 1}},
            {"t": 150.0, "units": {"MARINE": 13, "HELLION": 2, "SIEGETANK": 1}},
            {"t": 210.0, "units": {"MARINE": 20, "MARAUDER": 3, "SIEGETANK": 2, "MEDIVAC": 2}},
        ],
        "PUNISH": [
            {"t": 90.0, "units": {"MARINE": 8, "HELLION": 2}},
            {"t": 150.0, "units": {"MARINE": 14, "HELLION": 3, "SIEGETANK": 1}},
            {"t": 210.0, "units": {"MARINE": 22, "MARAUDER": 4, "SIEGETANK": 2, "MEDIVAC": 2}},
        ],
    },
    "timing_attacks_by_mode": {
        "RUSH_RESPONSE": [],
        "DEFENSIVE": [],
        "STANDARD": [
            {
                "name": "safe_6m00",
                "hit_t": 360.0,
                "prep_s": 80.0,
                "hold_s": 35.0,
                "army_supply_target": 58.0,
            }
        ],
        "PUNISH": [
            {
                "name": "safe_5m40",
                "hit_t": 340.0,
                "prep_s": 75.0,
                "hold_s": 30.0,
                "army_supply_target": 62.0,
            }
        ],
    },
    "tech_structure_targets_by_mode": {
        "RUSH_RESPONSE": {"ENGINEERINGBAY": 1, "ARMORY": 0},
        "DEFENSIVE": {"ENGINEERINGBAY": 1, "ARMORY": 0},
        "STANDARD": {"ENGINEERINGBAY": 2, "ARMORY": 2},
        "PUNISH": {"ENGINEERINGBAY": 2, "ARMORY": 2},
    },
}
