# Attention Bus

`Attention` e o snapshot read-only do tick atual.

Fonte:
- `bot/mind/attention.py`

Ele concentra:
- snapshots derivados pelos sensors
- consolidacoes leves do tick
- nenhum estado persistente

---

## Papel Na Arquitetura

Fluxo:

```text
Game/Ares -> Sensors -> Attention -> Intel -> Awareness
                              \-> Planners
```

Regra:
- `Sensors` escrevem fatos do tick
- `Intel` e `Planners` leem `Attention`
- persistencia fica em `Awareness`

---

## Estrutura Atual

`Attention` hoje contem:

- `economy: EconomySnapshot`
- `combat: CombatSnapshot`
- `intel: IntelSnapshot`
- `macro: MacroSnapshot`
- `enemy_build: EnemyBuildSnapshot`
- `unit_threats: UnitThreatsSnapshot`
- `missions: MissionSnapshot`
- `time: float`

### `EconomySnapshot`

Campos principais:
- `units_ready`
- `minerals`
- `gas`
- `supply_used`
- `supply_cap`
- `supply_left`
- `supply_blocked`
- `workers_total`
- `workers_idle`
- `idle_worker_tags`
- `idle_worker_pos`
- `bases_sat`
- `surplus_mineral_worker_tags`
- `deficit_mineral_worker_tags`

`BaseSat`:
- `base_id`
- `loc`
- `th_tag`
- `geysers_taken`
- `workers_actual`
- `workers_ideal`
- `mineral_actual`
- `mineral_ideal`
- `gas_saturation`
- `gas_ideal`
- `refinery_tags`

Contrato importante:
- o campo legado `economy.bases` nao existe mais
- o shape oficial e `economy.bases_sat`

### `CombatSnapshot`

- `primary_base_tag`
- `primary_enemy_count`
- `primary_urgency`
- `primary_threat_pos`
- `base_threats`

`BaseThreatSnapshot`:
- `th_tag`
- `th_pos`
- `enemy_count`
- `enemy_power`
- `urgency`
- `threat_pos`

### `UnitThreatsSnapshot`

- `units`
- `missions`

Uso:
- reinforce
- support
- micro de missao

### `IntelSnapshot`

- `orbital_ready_to_scan`
- `orbital_energy`

### `MacroSnapshot`

Campos atuais:
- `opening_done`
- `bases_total`
- `prod_structures_total`
- `prod_structures_idle`
- `prod_structures_active`
- `addon_total`
- `addon_reactor_total`
- `addon_techlab_total`
- `addon_reactor_ratio`
- `addon_techlab_ratio`
- `barracks_reactor`
- `barracks_techlab`
- `factory_reactor`
- `factory_techlab`
- `starport_reactor`
- `starport_techlab`

Observacao:
- `MacroSnapshot` hoje descreve estado operacional macro
- recursos e supply ficam em `EconomySnapshot`

### `EnemyBuildSnapshot`

- `enemy_units`
- `enemy_structures`
- `enemy_main_pos`
- `enemy_natural_pos`
- `enemy_units_main`
- `enemy_structures_main`
- `enemy_structures_progress`
- `enemy_natural_on_ground`
- `enemy_natural_townhall_progress`
- `enemy_natural_townhall_type`

### `MissionSnapshot`

- `ongoing`
- `ongoing_count`
- `ongoing_units_alive`
- `ongoing_units_missing`
- `needing_support_count`

Cada `MissionStatusSnapshot` contem:
- `mission_id`
- `proposal_id`
- `domain`
- `status`
- `started_at`
- `expires_at`
- `remaining_s`
- `assigned_count`
- `alive_count`
- `missing_count`
- `original_count`
- `original_alive_count`
- `original_missing_count`
- `original_alive_ratio`
- `mission_degraded`
- `original_type_counts`
- `alive_tags`
- `missing_tags`
- `can_reinforce`

---

## Consolidacoes Permitidas

Permitido em `Attention`:
- agregacoes do tick
- contagens e histogramas
- thresholds imediatos
- snapshots mecanicos para consumo por planner/intel

Proibido:
- `rush_detected`
- `enemy_opening_type`
- `strategic_phase`
- qualquer inferencia persistente

Esses sinais pertencem a `Intel -> Awareness`.

---

## Invariantes

1. `Attention` nao tem side-effect.
2. `Attention` e reconstruido todo tick.
3. `None` significa desconhecido; `0` significa observado e zero.
4. Sensor com falha deve preferir snapshot vazio com shape estavel.
5. Mudanca de shape em `Attention` exige atualizar `state_catalog.md`.
