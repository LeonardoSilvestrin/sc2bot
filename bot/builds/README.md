# Build Profiles (Compact)

You can keep using legacy `PROFILE` (flat keys), or switch to compact format:

```python
PROFILE = {
    "modes": {
        "STANDARD": {
            "comp": {"MARINE": 0.52, "MARAUDER": 0.20, "SIEGETANK": 0.13, "MEDIVAC": 0.15},
            "priority": ["SIEGETANK", "MARINE", "MARAUDER", "MEDIVAC"],
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
    "transition_overrides": {
        "BANSHEE": {
            "priority_standard": ["BANSHEE", "HELLION", "SIEGETANK", "MARINE", "MARAUDER", "MEDIVAC"]
        }
    },
    "scenario_overrides_by_phase": {
        "OPENING": {
            "AGGRESSIVE": {
                "comp_rush_response": {"MARINE": 0.60, "SIEGETANK": 0.22, "HELLION": 0.12, "MEDIVAC": 0.06}
            },
            "NORMAL": {},
            "GREEDY": {
                "comp_punish": {"MARINE": 0.46, "MARAUDER": 0.22, "SIEGETANK": 0.18, "MEDIVAC": 0.14}
            }
        },
        "MIDGAME": {"AGGRESSIVE": {}, "NORMAL": {}, "GREEDY": {}},
        "LATEGAME": {"AGGRESSIVE": {}, "NORMAL": {}, "GREEDY": {}}
    },
}
```

The engine auto-expands this into the legacy schema expected by `build_catalog`.

## Quick Edit Guide

- `modes.<MODE>.comp`: target composition weights (`MARINE`, `SIEGETANK`, etc).
- `modes.<MODE>.priority`: tie-break order when multiple units are buildable.
- `bank targets`: inferred automatically from comp + Ares `COST_DICT` (do not set in build).
  Contract: adding `bank_minerals` / `bank_gas` (or legacy `bank_setpoint_*`) is invalid and raises `invalid_contract`.
- `modes.<MODE>.army_supply_milestones`: expected army supply over game time (`t` in seconds).
- `modes.<MODE>.unit_count_milestones`: expected unit counts over time (`t` in seconds).
- `modes.<MODE>.production_structure_targets`: hard baseline of Barracks/Factory/Starport.
- `modes.<MODE>.production_scale`: per-base soft growth for production structures.
- `modes.<MODE>.tech_timing_milestones`: desired upgrades/tech by time (`t` in seconds).
- `scenario_overrides_by_phase.<PHASE>.<SCENARIO>`: optional deep-override applied after transition, with `PHASE in {OPENING, MIDGAME, LATEGAME}` and `SCENARIO in {AGGRESSIVE, NORMAL, GREEDY}`.

## Runtime Contract

- Intel resolves build phase as `OPENING | EARLY | MID | LATE`.
- Intel resolves enemy scenario as `AGGRESSIVE | NORMAL | GREEDY`.
- Build profile phase mapping:
  - `OPENING -> OPENING`
  - `EARLY/MID -> MIDGAME`
  - `LATE -> LATEGAME`
- Build resolver can apply optional scenario override by mapped phase + scenario.

Practical tuning:
- If third base is late, reduce early combat pressure (`unit_count_milestones`) and/or increase `production_scale` for Barracks slightly.
- If army is late, increase `priority` pressure on core units and bring forward `unit_count_milestones`.
