# Build Profiles (Compact)

You can keep using legacy `PROFILE` (flat keys), or switch to compact format:

```python
PROFILE = {
    "modes": {
        "STANDARD": {
            "comp": {"MARINE": 0.52, "MARAUDER": 0.20, "SIEGETANK": 0.13, "MEDIVAC": 0.15},
            "priority": ["SIEGETANK", "MARINE", "MARAUDER", "MEDIVAC"],
            "bank_minerals": 650,
            "bank_gas": 180,
            "pid": {"lag_pi_kp": 0.85, "lag_pi_ki": 0.20},
            "army_supply_milestones": [{"t": 210.0, "supply": 28.0}],
            "unit_count_milestones": [{"t": 210.0, "units": {"MARINE": 20}}],
            "timing_attacks": [{"name": "mmt_5m30", "hit_t": 330.0, "prep_s": 75.0, "hold_s": 35.0, "army_supply_target": 62.0}],
            "production_structure_targets": {"BARRACKS": 5, "FACTORY": 2, "STARPORT": 2},
            "production_scale": {"BARRACKS": 1.6, "FACTORY": 0.55, "STARPORT": 0.55},
            "tech_structure_targets": {"ENGINEERINGBAY": 2, "ARMORY": 2},
            "tech_timing_milestones": [{"t": 230.0, "structures": {}, "upgrades": ["STIMPACK"]}],
        },
        "DEFENSIVE": {...},
        "PUNISH": {...},
        "RUSH_RESPONSE": {...},
    },
    "reserve_costs": {"SIEGETANK": (150, 125), "MARINE": (50, 0)},
    "transition_overrides": {
        "BANSHEE": {
            "priority_standard": ["BANSHEE", "HELLION", "SIEGETANK", "MARINE", "MARAUDER", "MEDIVAC"]
        }
    },
}
```

The engine auto-expands this into the legacy schema expected by `build_catalog`.
