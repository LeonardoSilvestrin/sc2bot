from __future__ import annotations

from typing import Any, Dict


PROFILE: Dict[str, Any] = {
    "comp_defensive": {"MARINE": 0.65, "MARAUDER": 0.15, "SIEGETANK": 0.15, "MEDIVAC": 0.05},
    "comp_standard": {"MARINE": 0.52, "MARAUDER": 0.20, "SIEGETANK": 0.13, "MEDIVAC": 0.15},
    "comp_punish": {"MARINE": 0.55, "MARAUDER": 0.12, "SIEGETANK": 0.13, "MEDIVAC": 0.20},
    "comp_rush_response": {"MARINE": 0.55, "MARAUDER": 0.18, "SIEGETANK": 0.22, "MEDIVAC": 0.05},
    "priority_defensive": ["SIEGETANK", "MARINE", "MARAUDER", "MEDIVAC"],
    "priority_standard": ["SIEGETANK", "MARINE", "MARAUDER", "MEDIVAC"],
    "priority_punish": ["SIEGETANK", "MARINE", "MEDIVAC", "MARAUDER"],
    "priority_rush_response": ["SIEGETANK", "MARINE", "MARAUDER", "MEDIVAC"],
    "reserve_costs": {
        "SIEGETANK": (150, 125),
        "MARINE": (50, 0),
        "MARAUDER": (100, 25),
        "MEDIVAC": (100, 100),
        "REAPER": (50, 50),
        "HELLION": (100, 0),
        "BANSHEE": (150, 100),
    },
    "bank_setpoint_minerals": {"RUSH_RESPONSE": 380, "DEFENSIVE": 480, "STANDARD": 650, "PUNISH": 900},
    "bank_setpoint_gas": {"RUSH_RESPONSE": 160, "DEFENSIVE": 190, "STANDARD": 180, "PUNISH": 300},
    "pid_tuning_by_mode": {
        "RUSH_RESPONSE": {
            "lag_pi_kp": 0.95,
            "lag_pi_ki": 0.22,
            "production_lag_weight_boost": 0.72,
            "tech_lag_inflight_dampen_gain": 0.78,
            "block_production_max_lag_prod": 0.78,
            "timing_attack_production_weight_boost": 0.65,
        },
        "DEFENSIVE": {
            "lag_pi_kp": 0.90,
            "lag_pi_ki": 0.24,
            "production_lag_weight_boost": 0.66,
            "tech_lag_inflight_dampen_gain": 0.75,
            "block_production_max_lag_prod": 0.72,
            "timing_attack_production_weight_boost": 0.75,
        },
        "STANDARD": {
            "lag_pi_kp": 0.85,
            "lag_pi_ki": 0.20,
            "production_lag_weight_boost": 0.60,
            "tech_lag_inflight_dampen_gain": 0.72,
            "block_production_max_lag_prod": 0.65,
            "timing_attack_production_weight_boost": 0.95,
        },
        "PUNISH": {
            "lag_pi_kp": 0.92,
            "lag_pi_ki": 0.22,
            "production_lag_weight_boost": 0.70,
            "tech_lag_inflight_dampen_gain": 0.74,
            "block_production_max_lag_prod": 0.70,
            "timing_attack_production_weight_boost": 1.05,
        },
    },
    "army_supply_milestones_by_mode": {
        "RUSH_RESPONSE": [
            {"t": 90.0, "supply": 10.0},
            {"t": 150.0, "supply": 20.0},
            {"t": 210.0, "supply": 34.0},
            {"t": 300.0, "supply": 52.0},
            {"t": 420.0, "supply": 78.0},
            {"t": 540.0, "supply": 100.0},
            {"t": 660.0, "supply": 118.0},
            {"t": 780.0, "supply": 132.0},
        ],
        "DEFENSIVE": [
            {"t": 90.0, "supply": 9.0},
            {"t": 150.0, "supply": 18.0},
            {"t": 210.0, "supply": 30.0},
            {"t": 300.0, "supply": 46.0},
            {"t": 420.0, "supply": 72.0},
            {"t": 540.0, "supply": 92.0},
            {"t": 660.0, "supply": 110.0},
            {"t": 780.0, "supply": 126.0},
        ],
        "STANDARD": [
            {"t": 90.0, "supply": 8.0},
            {"t": 150.0, "supply": 16.0},
            {"t": 210.0, "supply": 28.0},
            {"t": 270.0, "supply": 42.0},
            {"t": 360.0, "supply": 60.0},
            {"t": 480.0, "supply": 84.0},
            {"t": 600.0, "supply": 106.0},
            {"t": 720.0, "supply": 126.0},
            {"t": 840.0, "supply": 142.0},
        ],
        "PUNISH": [
            {"t": 90.0, "supply": 10.0},
            {"t": 150.0, "supply": 20.0},
            {"t": 210.0, "supply": 34.0},
            {"t": 270.0, "supply": 50.0},
            {"t": 360.0, "supply": 70.0},
            {"t": 480.0, "supply": 94.0},
            {"t": 600.0, "supply": 116.0},
            {"t": 720.0, "supply": 136.0},
            {"t": 840.0, "supply": 150.0},
        ],
    },
    "unit_count_milestones_by_mode": {
        "RUSH_RESPONSE": [
            {"t": 90.0, "units": {"MARINE": 8, "MARAUDER": 1, "SIEGETANK": 1}},
            {"t": 150.0, "units": {"MARINE": 16, "MARAUDER": 3, "SIEGETANK": 2}},
            {"t": 210.0, "units": {"MARINE": 24, "MARAUDER": 6, "SIEGETANK": 3, "MEDIVAC": 1}},
        ],
        "DEFENSIVE": [
            {"t": 90.0, "units": {"MARINE": 7, "MARAUDER": 1, "SIEGETANK": 1}},
            {"t": 150.0, "units": {"MARINE": 14, "MARAUDER": 3, "SIEGETANK": 2}},
            {"t": 210.0, "units": {"MARINE": 22, "MARAUDER": 5, "SIEGETANK": 3, "MEDIVAC": 1}},
        ],
        "STANDARD": [
            {"t": 90.0, "units": {"MARINE": 6, "HELLION": 1}},
            {"t": 150.0, "units": {"MARINE": 12, "HELLION": 2, "SIEGETANK": 1}},
            {"t": 210.0, "units": {"MARINE": 20, "MARAUDER": 3, "SIEGETANK": 2, "MEDIVAC": 2}},
            {"t": 300.0, "units": {"MARINE": 32, "MARAUDER": 7, "SIEGETANK": 4, "MEDIVAC": 4}},
        ],
        "PUNISH": [
            {"t": 90.0, "units": {"MARINE": 8, "HELLION": 2}},
            {"t": 150.0, "units": {"MARINE": 14, "HELLION": 4, "SIEGETANK": 1}},
            {"t": 210.0, "units": {"MARINE": 22, "MARAUDER": 3, "SIEGETANK": 2, "MEDIVAC": 2}},
            {"t": 300.0, "units": {"MARINE": 34, "MARAUDER": 6, "SIEGETANK": 4, "MEDIVAC": 5}},
        ],
    },
    "timing_attacks_by_mode": {
        "RUSH_RESPONSE": [],
        "DEFENSIVE": [],
        "STANDARD": [
            {
                "name": "mmt_5m30",
                "hit_t": 330.0,
                "prep_s": 75.0,
                "hold_s": 35.0,
                "army_supply_target": 62.0,
            }
        ],
        "PUNISH": [
            {
                "name": "mmt_5m10",
                "hit_t": 310.0,
                "prep_s": 70.0,
                "hold_s": 30.0,
                "army_supply_target": 66.0,
            }
        ],
    },
    "production_structure_targets_by_mode": {
        "RUSH_RESPONSE": {"BARRACKS": 3, "FACTORY": 1, "STARPORT": 1},
        "DEFENSIVE": {"BARRACKS": 3, "FACTORY": 1, "STARPORT": 1},
        "STANDARD": {"BARRACKS": 5, "FACTORY": 2, "STARPORT": 2},
        "PUNISH": {"BARRACKS": 6, "FACTORY": 2, "STARPORT": 2},
    },
    "production_scale_by_mode": {
        "RUSH_RESPONSE": {"BARRACKS": 1.4, "FACTORY": 0.5, "STARPORT": 0.5},
        "DEFENSIVE": {"BARRACKS": 1.4, "FACTORY": 0.5, "STARPORT": 0.5},
        "STANDARD": {"BARRACKS": 1.6, "FACTORY": 0.55, "STARPORT": 0.55},
        "PUNISH": {"BARRACKS": 1.8, "FACTORY": 0.6, "STARPORT": 0.6},
    },
    "tech_structure_targets_by_mode": {
        "RUSH_RESPONSE": {"ENGINEERINGBAY": 1, "ARMORY": 0},
        "DEFENSIVE": {"ENGINEERINGBAY": 1, "ARMORY": 0},
        "STANDARD": {"ENGINEERINGBAY": 2, "ARMORY": 2},
        "PUNISH": {"ENGINEERINGBAY": 2, "ARMORY": 2},
    },
    "tech_timing_milestones_by_mode": {
        "RUSH_RESPONSE": [
            {"t": 260.0, "structures": {"ENGINEERINGBAY": 1}, "upgrades": []},
            {"t": 420.0, "structures": {"ENGINEERINGBAY": 1, "ARMORY": 0}, "upgrades": ["TERRANINFANTRYWEAPONSLEVEL1"]},
        ],
        "DEFENSIVE": [
            {"t": 280.0, "structures": {"ENGINEERINGBAY": 1}, "upgrades": []},
            {"t": 440.0, "structures": {"ENGINEERINGBAY": 1, "ARMORY": 0}, "upgrades": ["TERRANINFANTRYWEAPONSLEVEL1"]},
        ],
        "STANDARD": [
            {"t": 230.0, "structures": {}, "upgrades": ["STIMPACK"]},
            {"t": 320.0, "structures": {"ENGINEERINGBAY": 1}, "upgrades": []},
            {"t": 470.0, "structures": {"ENGINEERINGBAY": 2, "ARMORY": 1}, "upgrades": ["TERRANINFANTRYWEAPONSLEVEL1", "TERRANINFANTRYARMORSLEVEL1"]},
            {"t": 640.0, "structures": {"ENGINEERINGBAY": 2, "ARMORY": 2}, "upgrades": ["TERRANINFANTRYWEAPONSLEVEL2"]},
        ],
        "PUNISH": [
            {"t": 220.0, "structures": {}, "upgrades": ["STIMPACK"]},
            {"t": 300.0, "structures": {"ENGINEERINGBAY": 1}, "upgrades": []},
            {"t": 430.0, "structures": {"ENGINEERINGBAY": 2, "ARMORY": 1}, "upgrades": ["TERRANINFANTRYWEAPONSLEVEL1"]},
            {"t": 600.0, "structures": {"ENGINEERINGBAY": 2, "ARMORY": 2}, "upgrades": ["TERRANINFANTRYWEAPONSLEVEL2", "TERRANINFANTRYARMORSLEVEL1"]},
        ],
    },
    "transition_overrides": {
        "BANSHEE": {
            "priority_standard": ["BANSHEE", "HELLION", "SIEGETANK", "MARINE", "MARAUDER", "MEDIVAC"],
            "priority_punish": ["BANSHEE", "HELLION", "SIEGETANK", "MARINE", "MEDIVAC", "MARAUDER"],
        }
    },
}
