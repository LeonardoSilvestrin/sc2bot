from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict


def _bio_phase(*, phase: str) -> Dict[str, Any]:
    p = str(phase).upper()
    if p == "OPENING":
        return {
            "seed": {"focus_structure": "BARRACKS", "adapt_gain_supply": 0.22, "adapt_gain_units": 0.26, "adapt_gain_production": 0.18},
            "comp": {"MARINE": 0.58, "MARAUDER": 0.20, "SIEGETANK": 0.16, "MEDIVAC": 0.06},
            "priority": ["SIEGETANK", "MARINE", "MARAUDER", "MEDIVAC"],
            "pid": {"lag_pi_kp": 0.92, "lag_pi_ki": 0.22, "production_lag_weight_boost": 0.72, "tech_lag_inflight_dampen_gain": 0.80, "block_production_max_lag_prod": 0.78, "timing_attack_production_weight_boost": 0.80},
            "army_supply_milestones": [{"t": 90.0, "supply": 10.0}, {"t": 150.0, "supply": 20.0}, {"t": 210.0, "supply": 32.0}],
            "unit_count_milestones": [{"t": 90.0, "units": {"MARINE": 8, "MARAUDER": 1}}, {"t": 150.0, "units": {"MARINE": 16, "MARAUDER": 2, "SIEGETANK": 1}}, {"t": 210.0, "units": {"MARINE": 23, "MARAUDER": 4, "SIEGETANK": 2}}],
            "timing_attacks": [],
            "production_structure_targets": {"BARRACKS": 3, "FACTORY": 1, "STARPORT": 1},
            "production_scale": {"BARRACKS": 1.35, "FACTORY": 0.42, "STARPORT": 0.42},
            "tech_structure_targets": {"ENGINEERINGBAY": 1, "ARMORY": 0},
            "tech_timing_milestones": [{"t": 220.0, "structures": {}, "upgrades": ["STIMPACK"]}],
        }
    if p == "LATEGAME":
        return {
            "seed": {"focus_structure": "BARRACKS", "adapt_gain_supply": 0.26, "adapt_gain_units": 0.30, "adapt_gain_production": 0.22},
            "comp": {"MARINE": 0.50, "MARAUDER": 0.14, "SIEGETANK": 0.10, "MEDIVAC": 0.26},
            "priority": ["MEDIVAC", "SIEGETANK", "MARINE", "MARAUDER"],
            "pid": {"lag_pi_kp": 0.90, "lag_pi_ki": 0.21, "production_lag_weight_boost": 0.68, "tech_lag_inflight_dampen_gain": 0.76, "block_production_max_lag_prod": 0.70, "timing_attack_production_weight_boost": 1.02},
            "army_supply_milestones": [{"t": 420.0, "supply": 74.0}, {"t": 540.0, "supply": 98.0}, {"t": 660.0, "supply": 118.0}, {"t": 780.0, "supply": 134.0}],
            "unit_count_milestones": [{"t": 420.0, "units": {"MARINE": 30, "MARAUDER": 6, "SIEGETANK": 4, "MEDIVAC": 4}}, {"t": 600.0, "units": {"MARINE": 42, "MARAUDER": 9, "SIEGETANK": 6, "MEDIVAC": 6}}],
            "timing_attacks": [{"name": "bio_10m", "hit_t": 600.0, "prep_s": 80.0, "hold_s": 35.0, "army_supply_target": 110.0}],
            "production_structure_targets": {"BARRACKS": 6, "FACTORY": 2, "STARPORT": 3},
            "production_scale": {"BARRACKS": 1.90, "FACTORY": 0.62, "STARPORT": 0.72},
            "tech_structure_targets": {"ENGINEERINGBAY": 2, "ARMORY": 2},
            "tech_timing_milestones": [{"t": 520.0, "structures": {"ENGINEERINGBAY": 2, "ARMORY": 1}, "upgrades": ["TERRANINFANTRYWEAPONSLEVEL2"]}, {"t": 700.0, "structures": {"ENGINEERINGBAY": 2, "ARMORY": 2}, "upgrades": ["TERRANINFANTRYWEAPONSLEVEL3"]}],
        }
    return {
        "seed": {"focus_structure": "BARRACKS", "adapt_gain_supply": 0.24, "adapt_gain_units": 0.28, "adapt_gain_production": 0.20},
        "comp": {"MARINE": 0.54, "MARAUDER": 0.18, "SIEGETANK": 0.12, "MEDIVAC": 0.16},
        "priority": ["SIEGETANK", "MARINE", "MARAUDER", "MEDIVAC"],
        "pid": {"lag_pi_kp": 0.88, "lag_pi_ki": 0.20, "production_lag_weight_boost": 0.64, "tech_lag_inflight_dampen_gain": 0.74, "block_production_max_lag_prod": 0.68, "timing_attack_production_weight_boost": 0.96},
        "army_supply_milestones": [{"t": 210.0, "supply": 30.0}, {"t": 300.0, "supply": 46.0}, {"t": 420.0, "supply": 70.0}, {"t": 540.0, "supply": 94.0}],
        "unit_count_milestones": [{"t": 210.0, "units": {"MARINE": 21, "MARAUDER": 4, "SIEGETANK": 2, "MEDIVAC": 1}}, {"t": 300.0, "units": {"MARINE": 28, "MARAUDER": 5, "SIEGETANK": 3, "MEDIVAC": 3}}],
        "timing_attacks": [{"name": "bio_5m30", "hit_t": 330.0, "prep_s": 72.0, "hold_s": 32.0, "army_supply_target": 64.0}],
        "production_structure_targets": {"BARRACKS": 5, "FACTORY": 2, "STARPORT": 2},
        "production_scale": {"BARRACKS": 1.70, "FACTORY": 0.58, "STARPORT": 0.58},
        "tech_structure_targets": {"ENGINEERINGBAY": 2, "ARMORY": 1},
        "tech_timing_milestones": [{"t": 210.0, "structures": {}, "upgrades": ["STIMPACK"]}, {"t": 460.0, "structures": {"ENGINEERINGBAY": 2, "ARMORY": 1}, "upgrades": ["TERRANINFANTRYWEAPONSLEVEL1"]}],
    }


STAGED_PROFILES_BY_PHASE: Dict[str, Dict[str, Any]] = {
    "OPENING": _bio_phase(phase="OPENING"),
    "MIDGAME": _bio_phase(phase="MIDGAME"),
    "LATEGAME": _bio_phase(phase="LATEGAME"),
}


PROFILE: Dict[str, Any] = deepcopy(STAGED_PROFILES_BY_PHASE["MIDGAME"])
