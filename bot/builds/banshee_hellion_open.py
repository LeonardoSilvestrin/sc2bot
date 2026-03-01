from __future__ import annotations

from typing import Any, Dict


PROFILE: Dict[str, Any] = {
    "comp_defensive": {"MARINE": 0.58, "MARAUDER": 0.14, "SIEGETANK": 0.14, "MEDIVAC": 0.04, "HELLION": 0.10},
    "comp_standard": {"MARINE": 0.42, "MARAUDER": 0.12, "SIEGETANK": 0.12, "MEDIVAC": 0.12, "HELLION": 0.12, "BANSHEE": 0.10},
    "comp_punish": {"MARINE": 0.40, "MARAUDER": 0.10, "SIEGETANK": 0.10, "MEDIVAC": 0.14, "HELLION": 0.14, "BANSHEE": 0.12},
    "comp_rush_response": {"MARINE": 0.54, "MARAUDER": 0.16, "SIEGETANK": 0.18, "MEDIVAC": 0.04, "HELLION": 0.08},
    "priority_defensive": ["SIEGETANK", "MARINE", "MARAUDER", "HELLION", "MEDIVAC"],
    "priority_standard": ["HELLION", "BANSHEE", "SIEGETANK", "MARINE", "MARAUDER", "MEDIVAC"],
    "priority_punish": ["BANSHEE", "HELLION", "SIEGETANK", "MARINE", "MEDIVAC", "MARAUDER"],
    "priority_rush_response": ["SIEGETANK", "MARINE", "MARAUDER", "HELLION", "MEDIVAC"],
    "reserve_costs": {
        "BANSHEE": (150, 100),
        "HELLION": (100, 0),
        "SIEGETANK": (150, 125),
        "MARINE": (50, 0),
        "MARAUDER": (100, 25),
        "MEDIVAC": (100, 100),
        "REAPER": (50, 50),
    },
    "bank_setpoint_minerals": {"RUSH_RESPONSE": 360, "DEFENSIVE": 450, "STANDARD": 620, "PUNISH": 900},
    "bank_setpoint_gas": {"RUSH_RESPONSE": 170, "DEFENSIVE": 220, "STANDARD": 320, "PUNISH": 420},
    "pid_tuning_by_mode": {
        "RUSH_RESPONSE": {
            "lag_pi_kp": 0.96,
            "lag_pi_ki": 0.22,
            "production_lag_weight_boost": 0.74,
            "tech_lag_inflight_dampen_gain": 0.80,
            "block_production_max_lag_prod": 0.80,
            "timing_attack_production_weight_boost": 0.62,
        },
        "DEFENSIVE": {
            "lag_pi_kp": 0.92,
            "lag_pi_ki": 0.23,
            "production_lag_weight_boost": 0.68,
            "tech_lag_inflight_dampen_gain": 0.78,
            "block_production_max_lag_prod": 0.74,
            "timing_attack_production_weight_boost": 0.70,
        },
        "STANDARD": {
            "lag_pi_kp": 0.86,
            "lag_pi_ki": 0.20,
            "production_lag_weight_boost": 0.62,
            "tech_lag_inflight_dampen_gain": 0.76,
            "block_production_max_lag_prod": 0.66,
            "timing_attack_production_weight_boost": 1.00,
        },
        "PUNISH": {
            "lag_pi_kp": 0.92,
            "lag_pi_ki": 0.22,
            "production_lag_weight_boost": 0.72,
            "tech_lag_inflight_dampen_gain": 0.78,
            "block_production_max_lag_prod": 0.70,
            "timing_attack_production_weight_boost": 1.10,
        },
    },
    "army_supply_milestones_by_mode": {
        "RUSH_RESPONSE": [
            {"t": 90.0, "supply": 10.0},
            {"t": 150.0, "supply": 20.0},
            {"t": 210.0, "supply": 32.0},
            {"t": 300.0, "supply": 50.0},
            {"t": 420.0, "supply": 76.0},
            {"t": 540.0, "supply": 96.0},
            {"t": 660.0, "supply": 114.0},
            {"t": 780.0, "supply": 128.0},
        ],
        "DEFENSIVE": [
            {"t": 90.0, "supply": 9.0},
            {"t": 150.0, "supply": 18.0},
            {"t": 210.0, "supply": 30.0},
            {"t": 300.0, "supply": 46.0},
            {"t": 420.0, "supply": 70.0},
            {"t": 540.0, "supply": 88.0},
            {"t": 660.0, "supply": 106.0},
            {"t": 780.0, "supply": 122.0},
        ],
        "STANDARD": [
            {"t": 90.0, "supply": 8.0},
            {"t": 150.0, "supply": 16.0},
            {"t": 210.0, "supply": 30.0},
            {"t": 270.0, "supply": 46.0},
            {"t": 360.0, "supply": 68.0},
            {"t": 480.0, "supply": 90.0},
            {"t": 600.0, "supply": 112.0},
            {"t": 720.0, "supply": 130.0},
            {"t": 840.0, "supply": 146.0},
        ],
        "PUNISH": [
            {"t": 90.0, "supply": 10.0},
            {"t": 150.0, "supply": 20.0},
            {"t": 210.0, "supply": 34.0},
            {"t": 270.0, "supply": 52.0},
            {"t": 360.0, "supply": 74.0},
            {"t": 480.0, "supply": 98.0},
            {"t": 600.0, "supply": 120.0},
            {"t": 720.0, "supply": 138.0},
            {"t": 840.0, "supply": 152.0},
        ],
    },
    "unit_count_milestones_by_mode": {
        "RUSH_RESPONSE": [
            {"t": 90.0, "units": {"MARINE": 8, "HELLION": 1}},
            {"t": 150.0, "units": {"MARINE": 16, "HELLION": 2, "SIEGETANK": 1}},
            {"t": 210.0, "units": {"MARINE": 22, "HELLION": 3, "SIEGETANK": 2, "MEDIVAC": 1}},
        ],
        "DEFENSIVE": [
            {"t": 90.0, "units": {"MARINE": 7, "HELLION": 1}},
            {"t": 150.0, "units": {"MARINE": 14, "HELLION": 2, "SIEGETANK": 1}},
            {"t": 210.0, "units": {"MARINE": 20, "HELLION": 3, "SIEGETANK": 2, "MEDIVAC": 1}},
        ],
        "STANDARD": [
            {"t": 90.0, "units": {"MARINE": 6, "HELLION": 2}},
            {"t": 150.0, "units": {"MARINE": 10, "HELLION": 4, "SIEGETANK": 1}},
            {"t": 210.0, "units": {"MARINE": 16, "HELLION": 6, "BANSHEE": 1, "SIEGETANK": 2}},
            {"t": 300.0, "units": {"MARINE": 24, "HELLION": 8, "BANSHEE": 2, "SIEGETANK": 3, "MEDIVAC": 2}},
        ],
        "PUNISH": [
            {"t": 90.0, "units": {"MARINE": 7, "HELLION": 2}},
            {"t": 150.0, "units": {"MARINE": 12, "HELLION": 4, "SIEGETANK": 1}},
            {"t": 210.0, "units": {"MARINE": 18, "HELLION": 6, "BANSHEE": 1, "SIEGETANK": 2}},
            {"t": 300.0, "units": {"MARINE": 26, "HELLION": 8, "BANSHEE": 3, "SIEGETANK": 3, "MEDIVAC": 3}},
        ],
    },
    "timing_attacks_by_mode": {
        "RUSH_RESPONSE": [],
        "DEFENSIVE": [],
        "STANDARD": [
            {
                "name": "banshee_hellion_5m20",
                "hit_t": 320.0,
                "prep_s": 70.0,
                "hold_s": 30.0,
                "army_supply_target": 64.0,
            }
        ],
        "PUNISH": [
            {
                "name": "banshee_hellion_5m00",
                "hit_t": 300.0,
                "prep_s": 65.0,
                "hold_s": 30.0,
                "army_supply_target": 68.0,
            }
        ],
    },
}
