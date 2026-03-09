# Perfis de Build

O bot aceita dois formatos:
- formato canonico atual: profile compacto por `modes`
- formato em selecao de cenario: um profile de fase com `scenarios`

O arquivo de expansao e:
- `bot/builds/profile_compact.py`

A resolucao final fica em:
- `bot/intel/macro/desired_intel.py`

---

## Formato Compacto

Exemplo:

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
    "transition_overrides": {...},
    "scenario_overrides_by_phase": {
        "OPENING": {"AGGRESSIVE": {...}, "NORMAL": {...}, "GREEDY": {...}},
        "MIDGAME": {"AGGRESSIVE": {...}, "NORMAL": {...}, "GREEDY": {...}},
        "LATEGAME": {"AGGRESSIVE": {...}, "NORMAL": {...}, "GREEDY": {...}},
    },
    "seed": {...},
}
```

O expansor converte isso para o contrato legado esperado pelos consumidores antigos:
- `comp_<mode>`
- `priority_<mode>`
- `*_by_mode`

---

## Formato Com `scenarios`

O formato novo tambem aceita um profile de fase assim:

```python
PROFILE = {
    "scenarios": {
        "AGGRESSIVE": {...},
        "NORMAL": {...},
        "GREEDY": {...},
    },
    "transition_overrides": {...},
    "scenario_overrides_by_phase": {...},
}
```

Regra importante:
- `expand_compact_profile(...)` falha se receber `scenarios` sem que um cenario ja tenha sido selecionado
- a selecao do cenario precisa acontecer antes em `resolve_build_profile(...)`

---

## Resolucao Em Runtime

Pipeline atual em `derive_macro_mode_intel(...)`:

1. resolve opening e transition target ativos
2. determina fase do jogo: `OPENING | EARLY | MID | LATE`
3. mapeia fase para profile:
   - `OPENING -> OPENING`
   - `EARLY/MID -> MIDGAME`
   - `LATE -> LATEGAME`
4. hoje o `scenario` operacional e fixado como `NORMAL`
5. carrega o profile da opening e da fase
6. aplica `transition_overrides`
7. aplica `scenario_overrides_by_phase` quando houver
8. aplica adaptacao dinamica via `seed`

---

## Adaptacao Dinamica Via `seed`

O profile pode carregar um bloco `seed` consumido por `_apply_seed_adaptive_profile(...)`.

Ele ajusta em runtime:
- `army_supply_milestones`
- `unit_count_milestones`
- `production_scale`
- `production_structure_targets`

Sinais usados:
- flood mineral (`minerals` vs `macro:control:bank_target_minerals`)
- pressao de combate
- rush/aggression state

Objetivo:
- evitar profile estatico demais
- acelerar producao sob flood
- segurar estrutura quando a pressao esta alta

---

## Campos Publicados Em Awareness

`derive_my_army_composition_intel(...)` publica, entre outros:
- `macro:desired:mode`
- `macro:desired:phase`
- `macro:desired:scenario`
- `macro:desired:signals`
- `macro:desired:comp`
- `macro:desired:priority_units`
- `macro:desired:bank_target_minerals`
- `macro:desired:bank_target_gas`
- `macro:desired:army_supply_milestones`
- `macro:desired:unit_count_milestones`
- `macro:desired:timing_attacks`
- `macro:desired:production_structure_targets`
- `macro:desired:production_scale`
- `macro:desired:addon_targets`
- `macro:desired:tech_structure_targets`
- `macro:desired:tech_targets`

---

## Regras E Restricoes

1. `bank_setpoint_minerals` e `bank_setpoint_gas` estao obsoletos e geram erro.
2. `bank_minerals` e `bank_gas` tambem sao rejeitados.
3. Todo profile expandido precisa conter as chaves obrigatorias listadas em `_REQUIRED_KEYS`.
4. `transition_overrides` e `scenario_overrides_by_phase` sao merges, nao substituicao bruta.

---

## Afinacao Pratica

- Se o bot boia mineral cedo, ajuste `seed.adapt_gain_production` ou targets de producao.
- Se a opening mecha esta quebrando contra rush, ajuste `RushDefenseOpen` e floors de barracks/factory.
- Se timings de ataque estao entrando cedo demais, revise `timing_attacks` e `army_supply_milestones`.
- Se o profile precisa comportamento por fase, prefira staged profile por opening em vez de logica especial no planner.
