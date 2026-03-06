from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict


def _mecha_phase(*, phase: str) -> Dict[str, Any]:
    p = str(phase).upper()
    if p == "OPENING":
        return {
            "seed": {"focus_structure": "FACTORY", "adapt_gain_supply": 0.20, "adapt_gain_units": 0.24, "adapt_gain_production": 0.20},
            "comp": {"HELLION": 0.34, "CYCLONE": 0.24, "SIEGETANK": 0.20, "BANSHEE": 0.22},
            "priority": ["CYCLONE", "HELLION", "SIEGETANK", "BANSHEE"],
            "pid": {"lag_pi_kp": 0.92, "lag_pi_ki": 0.22, "production_lag_weight_boost": 0.74, "tech_lag_inflight_dampen_gain": 0.80, "block_production_max_lag_prod": 0.78, "timing_attack_production_weight_boost": 0.84},
            "army_supply_milestones": [{"t": 90.0, "supply": 9.0}, {"t": 150.0, "supply": 18.0}, {"t": 210.0, "supply": 30.0}],
            "unit_count_milestones": [{"t": 90.0, "units": {"HELLION": 2}}, {"t": 150.0, "units": {"HELLION": 4, "CYCLONE": 2}}, {"t": 210.0, "units": {"HELLION": 6, "CYCLONE": 4, "SIEGETANK": 1}}],
            "timing_attacks": [],
            "production_structure_targets": {"BARRACKS": 1, "FACTORY": 2, "STARPORT": 1},
            "production_scale": {"BARRACKS": 0.0, "FACTORY": 0.90, "STARPORT": 0.55},
            "tech_structure_targets": {"ENGINEERINGBAY": 1, "ARMORY": 1},
            "tech_timing_milestones": [{"t": 260.0, "structures": {}, "upgrades": ["BANSHEECLOAK"]}],
        }
    if p == "LATEGAME":
        return {
            "seed": {"focus_structure": "FACTORY", "adapt_gain_supply": 0.25, "adapt_gain_units": 0.30, "adapt_gain_production": 0.24},
            "comp": {"HELLION": 0.22, "CYCLONE": 0.28, "SIEGETANK": 0.26, "BANSHEE": 0.24},
            "priority": ["CYCLONE", "SIEGETANK", "HELLION", "BANSHEE"],
            "pid": {"lag_pi_kp": 0.92, "lag_pi_ki": 0.22, "production_lag_weight_boost": 0.72, "tech_lag_inflight_dampen_gain": 0.78, "block_production_max_lag_prod": 0.72, "timing_attack_production_weight_boost": 1.04},
            "army_supply_milestones": [{"t": 420.0, "supply": 74.0}, {"t": 540.0, "supply": 98.0}, {"t": 660.0, "supply": 118.0}, {"t": 780.0, "supply": 136.0}],
            "unit_count_milestones": [{"t": 420.0, "units": {"HELLION": 10, "CYCLONE": 8, "SIEGETANK": 5, "BANSHEE": 3}}, {"t": 620.0, "units": {"HELLION": 12, "CYCLONE": 11, "SIEGETANK": 7, "BANSHEE": 4}}],
            "timing_attacks": [{"name": "mecha_10m", "hit_t": 600.0, "prep_s": 80.0, "hold_s": 35.0, "army_supply_target": 112.0}],
            "production_structure_targets": {"BARRACKS": 1, "FACTORY": 4, "STARPORT": 2},
            "production_scale": {"BARRACKS": 0.0, "FACTORY": 1.05, "STARPORT": 0.72},
            "tech_structure_targets": {"ENGINEERINGBAY": 1, "ARMORY": 2},
            "tech_timing_milestones": [{"t": 520.0, "structures": {"ENGINEERINGBAY": 1, "ARMORY": 2}, "upgrades": ["TERRANVEHICLEWEAPONSLEVEL2"]}, {"t": 700.0, "structures": {"ENGINEERINGBAY": 1, "ARMORY": 2}, "upgrades": ["TERRANVEHICLEWEAPONSLEVEL3", "TERRANSHIPWEAPONSLEVEL1"]}],
        }
    return {
        "seed": {"focus_structure": "FACTORY", "adapt_gain_supply": 0.23, "adapt_gain_units": 0.28, "adapt_gain_production": 0.22},
        "comp": {"HELLION": 0.30, "CYCLONE": 0.30, "SIEGETANK": 0.22, "BANSHEE": 0.18},
        "priority": ["CYCLONE", "HELLION", "SIEGETANK", "BANSHEE"],
        "pid": {"lag_pi_kp": 0.90, "lag_pi_ki": 0.21, "production_lag_weight_boost": 0.68, "tech_lag_inflight_dampen_gain": 0.78, "block_production_max_lag_prod": 0.72, "timing_attack_production_weight_boost": 0.96},
        "army_supply_milestones": [{"t": 210.0, "supply": 30.0}, {"t": 300.0, "supply": 46.0}, {"t": 420.0, "supply": 70.0}, {"t": 540.0, "supply": 94.0}],
        "unit_count_milestones": [{"t": 210.0, "units": {"HELLION": 6, "CYCLONE": 4, "SIEGETANK": 2, "BANSHEE": 1}}, {"t": 300.0, "units": {"HELLION": 8, "CYCLONE": 6, "SIEGETANK": 3, "BANSHEE": 2}}],
        "timing_attacks": [{"name": "mecha_5m20", "hit_t": 320.0, "prep_s": 70.0, "hold_s": 30.0, "army_supply_target": 66.0}],
        "production_structure_targets": {"BARRACKS": 1, "FACTORY": 3, "STARPORT": 2},
        "production_scale": {"BARRACKS": 0.0, "FACTORY": 0.98, "STARPORT": 0.62},
        "tech_structure_targets": {"ENGINEERINGBAY": 1, "ARMORY": 2},
        "tech_timing_milestones": [{"t": 260.0, "structures": {}, "upgrades": ["BANSHEECLOAK"]}, {"t": 320.0, "structures": {}, "upgrades": ["SMARTSERVOS"]}, {"t": 470.0, "structures": {"ENGINEERINGBAY": 1, "ARMORY": 2}, "upgrades": ["TERRANVEHICLEWEAPONSLEVEL1"]}],
    }


STAGED_PROFILES_BY_PHASE: Dict[str, Dict[str, Any]] = {
    "OPENING": _mecha_phase(phase="OPENING"),
    "MIDGAME": _mecha_phase(phase="MIDGAME"),
    "LATEGAME": _mecha_phase(phase="LATEGAME"),
}


PROFILE: Dict[str, Any] = deepcopy(STAGED_PROFILES_BY_PHASE["MIDGAME"])
