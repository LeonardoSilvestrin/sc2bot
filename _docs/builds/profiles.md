# Perfis de Build

Voce pode continuar usando `PROFILE` legado ou migrar para o formato compacto.

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

O engine expande isso para o schema legado esperado por `build_catalog`.

---

## Guia rapido

- `modes.<MODE>.comp`: pesos da composicao alvo
- `modes.<MODE>.priority`: desempate entre unidades buildaveis
- `army_supply_milestones`: expectativa de army supply por tempo
- `unit_count_milestones`: expectativa de unidades por tempo
- `production_structure_targets`: baseline duro de producao
- `production_scale`: crescimento por base
- `tech_timing_milestones`: upgrades e tech por tempo
- `scenario_overrides_by_phase.<PHASE>.<SCENARIO>`: override opcional apos transicao

---

## Contrato de runtime

- Intel resolve fase como `OPENING | EARLY | MID | LATE`
- Intel resolve scenario inimigo como `AGGRESSIVE | NORMAL | GREEDY`

Mapeamento para profiles:
- `OPENING -> OPENING`
- `EARLY/MID -> MIDGAME`
- `LATE -> LATEGAME`

O resolver pode aplicar override por fase mapeada e scenario.

---

## Afinacao pratica

- Se a terceira base sai tarde, reduza pressao inicial ou aumente `production_scale`
- Se o exercito sai tarde, aumente prioridade das core units e antecipe milestones
