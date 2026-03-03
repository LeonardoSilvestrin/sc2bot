from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict


PROFILE: Dict[str, Any] = {
    "modes": {
        "RUSH_RESPONSE": {
            "comp": {"MARINE": 0.54, "MARAUDER": 0.16, "SIEGETANK": 0.18, "MEDIVAC": 0.04, "HELLION": 0.08},
            "priority": ["SIEGETANK", "MARINE", "MARAUDER", "HELLION", "MEDIVAC"],
            "pid": {
                "lag_pi_kp": 0.96,
                "lag_pi_ki": 0.22,
                "production_lag_weight_boost": 0.74,
                "tech_lag_inflight_dampen_gain": 0.80,
                "block_production_max_lag_prod": 0.80,
                "timing_attack_production_weight_boost": 0.62,
            },
            "army_supply_milestones": [
                {"t": 90.0, "supply": 10.0},
                {"t": 150.0, "supply": 20.0},
                {"t": 210.0, "supply": 32.0},
                {"t": 300.0, "supply": 50.0},
                {"t": 420.0, "supply": 76.0},
                {"t": 540.0, "supply": 96.0},
                {"t": 660.0, "supply": 114.0},
                {"t": 780.0, "supply": 128.0},
            ],
            "unit_count_milestones": [
                {"t": 90.0, "units": {"MARINE": 8, "HELLION": 1}},
                {"t": 150.0, "units": {"MARINE": 16, "HELLION": 2, "SIEGETANK": 1}},
                {"t": 210.0, "units": {"MARINE": 22, "HELLION": 3, "SIEGETANK": 2, "MEDIVAC": 1}},
            ],
            "timing_attacks": [],
            "production_structure_targets": {"BARRACKS": 3, "FACTORY": 1, "STARPORT": 1},
            "production_scale": {"BARRACKS": 1.3, "FACTORY": 0.5, "STARPORT": 0.5},
            "tech_structure_targets": {"ENGINEERINGBAY": 1, "ARMORY": 0},
            "tech_timing_milestones": [
                {"t": 280.0, "structures": {"ENGINEERINGBAY": 1}, "upgrades": []},
                {"t": 450.0, "structures": {"ENGINEERINGBAY": 1, "ARMORY": 0}, "upgrades": ["TERRANINFANTRYWEAPONSLEVEL1"]},
            ],
        },
        "DEFENSIVE": {
            "comp": {"MARINE": 0.58, "MARAUDER": 0.14, "SIEGETANK": 0.14, "MEDIVAC": 0.04, "HELLION": 0.10},
            "priority": ["SIEGETANK", "MARINE", "MARAUDER", "HELLION", "MEDIVAC"],
            "pid": {
                "lag_pi_kp": 0.92,
                "lag_pi_ki": 0.23,
                "production_lag_weight_boost": 0.68,
                "tech_lag_inflight_dampen_gain": 0.78,
                "block_production_max_lag_prod": 0.74,
                "timing_attack_production_weight_boost": 0.70,
            },
            "army_supply_milestones": [
                {"t": 90.0, "supply": 9.0},
                {"t": 150.0, "supply": 18.0},
                {"t": 210.0, "supply": 30.0},
                {"t": 300.0, "supply": 46.0},
                {"t": 420.0, "supply": 70.0},
                {"t": 540.0, "supply": 88.0},
                {"t": 660.0, "supply": 106.0},
                {"t": 780.0, "supply": 122.0},
            ],
            "unit_count_milestones": [
                {"t": 90.0, "units": {"MARINE": 7, "HELLION": 1}},
                {"t": 150.0, "units": {"MARINE": 14, "HELLION": 2, "SIEGETANK": 1}},
                {"t": 210.0, "units": {"MARINE": 20, "HELLION": 3, "SIEGETANK": 2, "MEDIVAC": 1}},
            ],
            "timing_attacks": [],
            "production_structure_targets": {"BARRACKS": 3, "FACTORY": 1, "STARPORT": 1},
            "production_scale": {"BARRACKS": 1.3, "FACTORY": 0.5, "STARPORT": 0.5},
            "tech_structure_targets": {"ENGINEERINGBAY": 1, "ARMORY": 0},
            "tech_timing_milestones": [
                {"t": 300.0, "structures": {"ENGINEERINGBAY": 1}, "upgrades": []},
                {"t": 470.0, "structures": {"ENGINEERINGBAY": 1, "ARMORY": 0}, "upgrades": ["TERRANINFANTRYWEAPONSLEVEL1"]},
            ],
        },
        "STANDARD": {
            "comp": {"SIEGETANK": 0.30, "HELLION": 0.30, "BANSHEE": 0.20, "MARINE": 0.12, "MEDIVAC": 0.08},
            "priority": ["SIEGETANK", "HELLION", "BANSHEE", "MARINE", "MEDIVAC"],
            "pid": {
                "lag_pi_kp": 0.86,
                "lag_pi_ki": 0.20,
                "production_lag_weight_boost": 0.62,
                "tech_lag_inflight_dampen_gain": 0.76,
                "block_production_max_lag_prod": 0.66,
                "timing_attack_production_weight_boost": 1.00,
            },
            "army_supply_milestones": [
                {"t": 90.0, "supply": 8.0},
                {"t": 150.0, "supply": 16.0},
                {"t": 210.0, "supply": 27.0},
                {"t": 270.0, "supply": 41.0},
                {"t": 360.0, "supply": 60.0},
                {"t": 480.0, "supply": 90.0},
                {"t": 600.0, "supply": 112.0},
                {"t": 720.0, "supply": 130.0},
                {"t": 840.0, "supply": 146.0},
            ],
            "unit_count_milestones": [
                {"t": 90.0, "units": {"MARINE": 6, "HELLION": 2}},
                {"t": 150.0, "units": {"MARINE": 10, "HELLION": 4, "SIEGETANK": 1}},
                {"t": 210.0, "units": {"MARINE": 14, "HELLION": 5, "BANSHEE": 1, "SIEGETANK": 2}},
                {"t": 300.0, "units": {"MARINE": 20, "HELLION": 6, "BANSHEE": 2, "SIEGETANK": 2, "MEDIVAC": 2}},
            ],
            "timing_attacks": [
                {"name": "banshee_hellion_5m20", "hit_t": 320.0, "prep_s": 70.0, "hold_s": 30.0, "army_supply_target": 64.0}
            ],
            "production_structure_targets": {"BARRACKS": 1, "FACTORY": 1, "STARPORT": 1},
            "production_scale": {"BARRACKS": 0.0, "FACTORY": 0.67, "STARPORT": 0.34},
            "tech_structure_targets": {"ENGINEERINGBAY": 1, "ARMORY": 2},
            "tech_timing_milestones": [
                {"t": 180.0, "structures": {"ENGINEERINGBAY": 1, "ARMORY": 2}, "upgrades": []},
                {"t": 230.0, "structures": {}, "upgrades": ["BANSHEECLOAK"]},
                {"t": 340.0, "structures": {"ENGINEERINGBAY": 1}, "upgrades": []},
                {"t": 500.0, "structures": {"ENGINEERINGBAY": 1, "ARMORY": 2}, "upgrades": ["TERRANVEHICLEWEAPONSLEVEL1"]},
                {"t": 680.0, "structures": {"ENGINEERINGBAY": 1, "ARMORY": 2}, "upgrades": ["TERRANVEHICLEWEAPONSLEVEL2", "TERRANSHIPWEAPONSLEVEL1"]},
            ],
        },
        "PUNISH": {
            "comp": {"SIEGETANK": 0.28, "HELLION": 0.28, "BANSHEE": 0.24, "MARINE": 0.10, "MEDIVAC": 0.10},
            "priority": ["BANSHEE", "SIEGETANK", "HELLION", "MARINE", "MEDIVAC"],
            "pid": {
                "lag_pi_kp": 0.92,
                "lag_pi_ki": 0.22,
                "production_lag_weight_boost": 0.72,
                "tech_lag_inflight_dampen_gain": 0.78,
                "block_production_max_lag_prod": 0.70,
                "timing_attack_production_weight_boost": 1.10,
            },
            "army_supply_milestones": [
                {"t": 90.0, "supply": 10.0},
                {"t": 150.0, "supply": 20.0},
                {"t": 210.0, "supply": 30.0},
                {"t": 270.0, "supply": 47.0},
                {"t": 360.0, "supply": 66.0},
                {"t": 480.0, "supply": 98.0},
                {"t": 600.0, "supply": 120.0},
                {"t": 720.0, "supply": 138.0},
                {"t": 840.0, "supply": 152.0},
            ],
            "unit_count_milestones": [
                {"t": 90.0, "units": {"MARINE": 7, "HELLION": 2}},
                {"t": 150.0, "units": {"MARINE": 12, "HELLION": 4, "SIEGETANK": 1}},
                {"t": 210.0, "units": {"MARINE": 15, "HELLION": 5, "BANSHEE": 1, "SIEGETANK": 2}},
                {"t": 300.0, "units": {"MARINE": 22, "HELLION": 6, "BANSHEE": 2, "SIEGETANK": 2, "MEDIVAC": 2}},
            ],
            "timing_attacks": [
                {"name": "banshee_hellion_5m00", "hit_t": 300.0, "prep_s": 65.0, "hold_s": 30.0, "army_supply_target": 68.0}
            ],
            "production_structure_targets": {"BARRACKS": 1, "FACTORY": 1, "STARPORT": 1},
            "production_scale": {"BARRACKS": 0.0, "FACTORY": 0.67, "STARPORT": 0.34},
            "tech_structure_targets": {"ENGINEERINGBAY": 1, "ARMORY": 2},
            "tech_timing_milestones": [
                {"t": 180.0, "structures": {"ENGINEERINGBAY": 1, "ARMORY": 2}, "upgrades": []},
                {"t": 220.0, "structures": {}, "upgrades": ["BANSHEECLOAK"]},
                {"t": 320.0, "structures": {"ENGINEERINGBAY": 1}, "upgrades": []},
                {"t": 460.0, "structures": {"ENGINEERINGBAY": 1, "ARMORY": 2}, "upgrades": ["TERRANVEHICLEWEAPONSLEVEL1"]},
                {"t": 620.0, "structures": {"ENGINEERINGBAY": 1, "ARMORY": 2}, "upgrades": ["TERRANVEHICLEWEAPONSLEVEL2", "TERRANSHIPWEAPONSLEVEL1"]},
            ],
        },
    },
}


def _apply_phase(
    *,
    profile: Dict[str, Any],
    comp: Dict[str, float],
    priority: list[str],
    production_targets: Dict[str, int],
    production_scale: Dict[str, float],
    tech_targets: Dict[str, int],
    tech_milestones: list[Dict[str, Any]],
) -> Dict[str, Any]:
    out: Dict[str, Any] = deepcopy(profile)
    for mode in ("STANDARD", "PUNISH", "DEFENSIVE", "RUSH_RESPONSE"):
        cfg = out["modes"][mode]
        cfg["comp"] = dict(comp)
        cfg["priority"] = list(priority)
        cfg["production_structure_targets"] = dict(production_targets)
        cfg["production_scale"] = dict(production_scale)
        cfg["tech_structure_targets"] = dict(tech_targets)
        cfg["tech_timing_milestones"] = list(tech_milestones)
    return out


STAGED_PROFILES_BY_PHASE: Dict[str, Dict[str, Any]] = {
    "OPENING": _apply_phase(
        profile=PROFILE,
        comp={
            "CYCLONE": 0.34,
            "HELLION": 0.28,
            "BANSHEE": 0.22,
            "SIEGETANK": 0.12,
            "LIBERATOR": 0.04,
        },
        priority=["CYCLONE", "HELLION", "BANSHEE", "SIEGETANK", "LIBERATOR"],
        production_targets={"BARRACKS": 1, "FACTORY": 1, "STARPORT": 1},
        production_scale={"BARRACKS": 0.0, "FACTORY": 0.70, "STARPORT": 0.30},
        tech_targets={"ENGINEERINGBAY": 1, "ARMORY": 2},
        tech_milestones=[
            {"t": 180.0, "structures": {"ENGINEERINGBAY": 1, "ARMORY": 2}, "upgrades": []},
            {"t": 230.0, "structures": {}, "upgrades": ["BANSHEECLOAK"]},
            {"t": 260.0, "structures": {}, "upgrades": ["SMARTSERVOS"]},
            {"t": 300.0, "structures": {}, "upgrades": ["DRILLCLAWS"]},
            {"t": 360.0, "structures": {"ENGINEERINGBAY": 1, "ARMORY": 2}, "upgrades": ["TERRANVEHICLEWEAPONSLEVEL1"]},
        ],
    ),
    "MIDGAME": _apply_phase(
        profile=PROFILE,
        comp={
            "SIEGETANK": 0.34,
            "HELLION": 0.24,
            "BANSHEE": 0.14,
            "LIBERATOR": 0.16,
            "CYCLONE": 0.12,
            "WIDOWMINE": 0.08,
        },
        priority=["SIEGETANK", "LIBERATOR", "HELLION", "BANSHEE", "CYCLONE", "WIDOWMINE"],
        production_targets={"BARRACKS": 1, "FACTORY": 2, "STARPORT": 1},
        production_scale={"BARRACKS": 0.0, "FACTORY": 0.80, "STARPORT": 0.45},
        tech_targets={"ENGINEERINGBAY": 1, "ARMORY": 2},
        tech_milestones=[
            {"t": 180.0, "structures": {"ENGINEERINGBAY": 1, "ARMORY": 2}, "upgrades": []},
            {"t": 230.0, "structures": {}, "upgrades": ["BANSHEECLOAK"]},
            {"t": 260.0, "structures": {}, "upgrades": ["SMARTSERVOS"]},
            {"t": 300.0, "structures": {}, "upgrades": ["DRILLCLAWS"]},
            {"t": 420.0, "structures": {"ENGINEERINGBAY": 1, "ARMORY": 2}, "upgrades": ["TERRANVEHICLEWEAPONSLEVEL1"]},
            {"t": 560.0, "structures": {"ENGINEERINGBAY": 1, "ARMORY": 2}, "upgrades": ["TERRANVEHICLEWEAPONSLEVEL2", "TERRANSHIPWEAPONSLEVEL1"]},
        ],
    ),
    "LATEGAME": _apply_phase(
        profile=PROFILE,
        comp={
            "SIEGETANK": 0.36,
            "LIBERATOR": 0.24,
            "THOR": 0.14,
            "HELLION": 0.14,
            "WIDOWMINE": 0.04,
            "BANSHEE": 0.08,
            "CYCLONE": 0.00,
        },
        priority=["SIEGETANK", "LIBERATOR", "THOR", "HELLION", "BANSHEE", "WIDOWMINE", "CYCLONE"],
        production_targets={"BARRACKS": 1, "FACTORY": 3, "STARPORT": 2},
        production_scale={"BARRACKS": 0.0, "FACTORY": 0.95, "STARPORT": 0.60},
        tech_targets={"ENGINEERINGBAY": 1, "ARMORY": 2},
        tech_milestones=[
            {"t": 180.0, "structures": {"ENGINEERINGBAY": 1, "ARMORY": 2}, "upgrades": []},
            {"t": 260.0, "structures": {}, "upgrades": ["SMARTSERVOS"]},
            {"t": 300.0, "structures": {}, "upgrades": ["DRILLCLAWS"]},
            {"t": 520.0, "structures": {"ENGINEERINGBAY": 1, "ARMORY": 2}, "upgrades": ["TERRANVEHICLEWEAPONSLEVEL2", "TERRANSHIPWEAPONSLEVEL1"]},
            {"t": 700.0, "structures": {"ENGINEERINGBAY": 1, "ARMORY": 2}, "upgrades": ["TERRANVEHICLEWEAPONSLEVEL3", "TERRANSHIPWEAPONSLEVEL2"]},
        ],
    ),
}
