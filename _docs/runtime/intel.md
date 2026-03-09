# Intel Bus

`Intel` transforma fatos do tick em inferencia persistente.

Pipeline oficial:

```text
Attention -> derive_* intel -> Awareness.mem
```

Regras:
- le `Attention`
- pode ler `Awareness`
- escreve em `Awareness`
- nao comanda unidades

---

## Ordem De Execucao Atual

Fonte:
- `bot/mind/self.py`

Ordem:

1. `derive_opening_contract_intel(...)`
2. `derive_enemy_opening_intel(...)`
3. `derive_enemy_build_intel(...)`
4. `derive_my_army_composition_intel(...)`
5. `derive_game_parity_intel(...)`
6. `derive_pathing_flow_intel(...)`
7. `derive_pathing_route_intel(...)`
8. `derive_enemy_presence_intel(...)`
9. `derive_map_control_intel(...)`
10. `derive_frontline_intel(...)`
11. `derive_world_compression(...)`
12. `derive_operational_geometry(...)`
13. `derive_territorial_control_intel(...)`
14. `derive_army_posture_intel(...)`
15. `derive_mission_unit_threat_intel(...)`
16. `derive_mission_value_intel(...)`
17. `AdvantageGameStatusIntel.derive(...)`

---

## Modulos Principais

### Opening Contract Intel

Arquivo:
- `bot/intel/enemy/opening_contract.py`

Escreve:
- `macro:opening:done`
- `macro:opening:done_reason`
- `macro:opening:done_owner`

### Enemy Opening Intel

Arquivo:
- `bot/intel/enemy/opening_intel.py`

Responsabilidade:
- classificar opening e rush inimigos
- acompanhar severidade, tier, confidence e sinais estruturais

Escreve:
- `enemy:opening:*`
- `enemy:rush:*`
- `enemy:aggression:*`
- `intel:opening:last_emit_t`

### Enemy Build Intel

Arquivo:
- `bot/intel/enemy/enemy_build_intel.py`

Escreve:
- `enemy:build:*`
- `enemy:army:*`

### Macro Desired Intel

Arquivo:
- `bot/intel/macro/desired_intel.py`

Responsabilidade:
- resolver opening, fase e profile
- publicar composicao desejada, prioridades, banco alvo, marcos, tech targets e sinais macro

Escreve:
- `macro:desired:*`
- `enemy:rush:predicted`
- `intel:my_comp:last_emit_t`

### Game Parity Intel

Arquivo:
- `bot/intel/strategy/i1_game_parity_intel.py`

Escreve:
- `strategy:parity:*`
- partes de `enemy:parity:*` se aplicavel

### Pathing e Presenca

Arquivos:
- `bot/intel/locations/i1_pathing_flow_intel.py`
- `bot/intel/locations/i2_pathing_route_intel.py`
- `bot/intel/locations/i4_enemy_presence_intel.py`
- `bot/intel/locations/i5_frontline_intel.py`

Escrevem:
- `enemy:pathing:*`
- snapshots de presenca local
- `intel:frontline:*`

### World Compression

Arquivo:
- `bot/intel/geometry/i1_world_compression_intel.py`

Escreve:
- `intel:geometry:world:compression`

### Operational Geometry

Arquivo:
- `bot/intel/geometry/i2_operational_geometry_intel.py`

Escreve:
- `intel:geometry:operational:snapshot`
- `intel:geometry:operational:template`
- `intel:geometry:operational:bulk_anchor`
- `intel:geometry:operational:max_detach_supply`
- `intel:geometry:sector:<sector_id>`

### Territorial Control

Arquivo:
- `bot/intel/locations/i6_territorial_control_intel.py`

Escreve:
- `intel:territory:defense:snapshot`
- `intel:territory:defense:active_line`

### Army Posture

Arquivo:
- `bot/intel/strategy/i3_army_posture_intel.py`

Responsabilidade:
- camada de compatibilidade
- traduz `FrontTemplate` para `ArmyPosture`

Escreve:
- `strategy:army:posture`
- `strategy:army:anchor`
- `strategy:army:secondary_anchor`
- `strategy:army:max_detach_supply`
- `strategy:army:min_bulk_supply`
- `strategy:army:snapshot`

---

## Contratos Novos Da Camada Espacial

### World Compression

Shape esperado:
- `pressure_main`
- `pressure_nat`
- `pressure_outer`
- `expansion_commit`
- `push_commit`
- `mobility_need`
- `map_presence_need`
- `army_strength_rel`
- `drop_risk`
- `air_risk`
- metadados como `rush_active`, `nat_taken`, `army_supply`

### Operational Geometry

Shape principal do snapshot:
- `template`
- `template_switched`
- `template_switched_at`
- `bulk_sector`
- `bulk_anchor_pos`
- `max_detach_supply`
- `sector_states`
- `reserved_zones`
- `reallocation_cost`

### Territorial Control

Shape principal:
- `active_line`
- `desired_line`
- `rush_state`
- `lines`
- `zones`

Cada zona contem:
- `center`
- `front_anchor`
- `fallback_anchor`
- `control_score`
- `threat_score`
- `missing_roles`
- `active_slots`
- `is_stable`

---

## Invariantes

1. Intel nao emite comando de unidade.
2. Prefixos escritos precisam de owner claro.
3. TTL deve ser coerente com a volatilidade do sinal.
4. Geometria decide forma espacial; planners nao devem duplicar essa decisao.
5. `ArmyPosture` hoje e adaptador de compatibilidade, nao fonte primaria.
