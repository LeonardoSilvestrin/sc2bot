from __future__ import annotations

from typing import Any, Dict


# Example only. Not registered in PROFILES_BY_OPENING by default.
PROFILE: Dict[str, Any] = {
    "modes": {
        "DEFENSIVE": {
            "comp": {"MARINE": 0.60, "MARAUDER": 0.16, "SIEGETANK": 0.18, "MEDIVAC": 0.06},
            "priority": ["SIEGETANK", "MARINE", "MARAUDER", "MEDIVAC"],
            "bank_minerals": 480,
            "bank_gas": 190,
            "pid": {"lag_pi_kp": 0.90, "lag_pi_ki": 0.24},
            "army_supply_milestones": [],
            "unit_count_milestones": [],
            "timing_attacks": [],
            "production_structure_targets": {"BARRACKS": 3, "FACTORY": 1, "STARPORT": 1},
            "production_scale": {"BARRACKS": 1.4, "FACTORY": 0.5, "STARPORT": 0.5},
            "tech_structure_targets": {"ENGINEERINGBAY": 1, "ARMORY": 0},
            "tech_timing_milestones": [],
        },
        "STANDARD": {
            "comp": {"MARINE": 0.52, "MARAUDER": 0.20, "SIEGETANK": 0.13, "MEDIVAC": 0.15},
            "priority": ["SIEGETANK", "MARINE", "MARAUDER", "MEDIVAC"],
            "bank_minerals": 650,
            "bank_gas": 180,
            "pid": {"lag_pi_kp": 0.85, "lag_pi_ki": 0.20},
            "army_supply_milestones": [],
            "unit_count_milestones": [],
            "timing_attacks": [],
            "production_structure_targets": {"BARRACKS": 5, "FACTORY": 2, "STARPORT": 2},
            "production_scale": {"BARRACKS": 1.6, "FACTORY": 0.55, "STARPORT": 0.55},
            "tech_structure_targets": {"ENGINEERINGBAY": 2, "ARMORY": 2},
            "tech_timing_milestones": [],
        },
        "PUNISH": {
            "comp": {"MARINE": 0.55, "MARAUDER": 0.12, "SIEGETANK": 0.13, "MEDIVAC": 0.20},
            "priority": ["SIEGETANK", "MARINE", "MEDIVAC", "MARAUDER"],
            "bank_minerals": 900,
            "bank_gas": 300,
            "pid": {"lag_pi_kp": 0.92, "lag_pi_ki": 0.22},
            "army_supply_milestones": [],
            "unit_count_milestones": [],
            "timing_attacks": [],
            "production_structure_targets": {"BARRACKS": 6, "FACTORY": 2, "STARPORT": 2},
            "production_scale": {"BARRACKS": 1.8, "FACTORY": 0.6, "STARPORT": 0.6},
            "tech_structure_targets": {"ENGINEERINGBAY": 2, "ARMORY": 2},
            "tech_timing_milestones": [],
        },
        "RUSH_RESPONSE": {
            "comp": {"MARINE": 0.55, "MARAUDER": 0.18, "SIEGETANK": 0.22, "MEDIVAC": 0.05},
            "priority": ["SIEGETANK", "MARINE", "MARAUDER", "MEDIVAC"],
            "bank_minerals": 380,
            "bank_gas": 160,
            "pid": {"lag_pi_kp": 0.95, "lag_pi_ki": 0.22},
            "army_supply_milestones": [],
            "unit_count_milestones": [],
            "timing_attacks": [],
            "production_structure_targets": {"BARRACKS": 3, "FACTORY": 1, "STARPORT": 1},
            "production_scale": {"BARRACKS": 1.4, "FACTORY": 0.5, "STARPORT": 0.5},
            "tech_structure_targets": {"ENGINEERINGBAY": 1, "ARMORY": 0},
            "tech_timing_milestones": [],
        },
    },
    "reserve_costs": {
        "SIEGETANK": (150, 125),
        "MARINE": (50, 0),
        "MARAUDER": (100, 25),
        "MEDIVAC": (100, 100),
    },
}

