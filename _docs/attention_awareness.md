# Attention & Awareness State Catalog

Este documento descreve o contrato atual de estado do bot:
- `bot/mind/attention.py` (snapshot do tick)
- `bot/mind/awareness.py` (memoria entre ticks)

Regra base:
- `Attention` = fatos do tick atual (imutavel)
- `Awareness` = estado persistente, inferencia, cooldown e trilha operacional

---

## 1) Attention

Fonte: `bot/mind/attention.py`.

### 1.1 Estrutura principal
- `economy: EconomySnapshot`
- `combat: CombatSnapshot`
- `unit_threats: UnitThreatsSnapshot`
- `intel: IntelSnapshot`
- `macro: MacroSnapshot`
- `enemy_build: EnemyBuildSnapshot`
- `missions: MissionSnapshot`
- `time: float`

### 1.2 EconomySnapshot
- `units_ready: dict` (`{UnitTypeId -> count}`)
- `minerals: int`
- `gas: int`
- `supply_used: int`
- `supply_cap: int`
- `supply_left: int`
- `supply_blocked: bool`
- `workers_total: int`
- `workers_idle: int`
- `idle_worker_tags: tuple[int, ...]`
- `idle_worker_pos: tuple[(float,float), ...]`
- `bases_sat: tuple[BaseSat, ...]`
- `surplus_mineral_worker_tags: tuple[int, ...]`
- `deficit_mineral_worker_tags: tuple[int, ...]`

`BaseSat`:
- `base_id`, `loc`, `th_tag`
- `geysers_taken`
- `workers_actual`, `workers_ideal`
- `mineral_actual`, `mineral_ideal`
- `gas_saturation`, `gas_ideal`
- `refinery_tags`

Nota: o campo legado `economy.bases` foi removido. O contrato oficial agora e apenas `bases_sat`.

### 1.3 CombatSnapshot
- `primary_base_tag: Optional[int]`
- `primary_enemy_count: int`
- `primary_urgency: int` (0..100)
- `primary_threat_pos: Optional[Point2]`
- `base_threats: tuple[BaseThreatSnapshot, ...]`

### 1.4 UnitThreatsSnapshot
- `units: tuple[UnitThreatSnapshot, ...]`
- `missions: tuple[MissionUnitThreatSnapshot, ...]`

Uso principal:
- micro de missao (ex.: can-win, unidades em perigo)
- gatilho de reinforce/support

### 1.5 IntelSnapshot
- `orbital_ready_to_scan: bool`
- `orbital_energy: float`

### 1.6 MacroSnapshot
- `opening_done: bool`
- `bases_total: int`
- `prod_structures_total: int`
- `prod_structures_idle: int`
- `prod_structures_active: int`
- `minerals`, `vespene`, `workers_total`, `workers_idle`
- `bases_under_saturated`, `bases_over_saturated`
- `supply_used`, `supply_cap`, `supply_left`, `supply_blocked`

### 1.7 EnemyBuildSnapshot
- `enemy_units`, `enemy_structures`
- `enemy_main_pos`, `enemy_natural_pos`
- `enemy_units_main`, `enemy_structures_main`
- `enemy_structures_progress`
- `enemy_natural_on_ground`
- `enemy_natural_townhall_progress`
- `enemy_natural_townhall_type`

### 1.8 MissionSnapshot
- `ongoing: tuple[MissionStatusSnapshot, ...]`
- `ongoing_count`
- `ongoing_units_alive`
- `ongoing_units_missing`
- `needing_support_count`

`MissionStatusSnapshot` inclui:
- `mission_id`, `proposal_id`, `domain`, `status`
- `started_at`, `expires_at`, `remaining_s`
- `assigned_count`, `alive_count`, `missing_count`
- `original_count`, `original_alive_count`, `original_missing_count`, `original_alive_ratio`
- `mission_degraded`
- `original_type_counts`
- `alive_tags`, `missing_tags`
- `can_reinforce`

---

## 2) Awareness.mem

Fonte: `bot/mind/awareness.py`.

Formato de chave: tupla `("a","b","c")`, documentada como `a:b:c`.

### 2.1 Ops / Missions (Ego)
- `ops:mission:<mission_id>:status`
- `ops:mission:<mission_id>:domain`
- `ops:mission:<mission_id>:proposal_id`
- `ops:mission:<mission_id>:started_at`
- `ops:mission:<mission_id>:expires_at`
- `ops:mission:<mission_id>:assigned_tags`
- `ops:mission:<mission_id>:original_assigned_tags`
- `ops:mission:<mission_id>:original_type_counts`
- `ops:mission:<mission_id>:reason`
- `ops:mission:<mission_id>:ended_at`

### 2.2 Ops / Proposals e cooldown
- `ops:cooldown:<proposal_id>:until`
- `ops:cooldown:<proposal_id>:reason`
- `ops:proposal_running:<proposal_id>` (helper de runtime)

### 2.3 Intel / Scout e scan
- `intel:scv:*`
- `intel:reaper:scout:*`
- `intel:scan:*`

### 2.4 Enemy openMing
- `enemy:opening:first_seen_t`
- `enemy:rush:*` (state, score, confidence, evidence)
- `enemy:opening:kind`
- `enemy:opening:confidence`
- `enemy:opening:signals`
- `enemy:opening:last_update_t`

### 2.5 Enemy weak points
- `enemy:weak_points:snapshot`
- `enemy:weak_points:points`
- `enemy:weak_points:primary`
- `enemy:weak_points:bases_visible`
- `enemy:weak_points:last_update_t`

### 2.6 Macro / housekeeping
- `macro:opening:selected`
- `macro:opening:transition_target`
- `macro:opening:build_selected`
- `macro:opening:build_transition_target`
- `macro:opening:requested`
- `macro:opening:requested_transition_target`
- `macro:opening:request_reason`
- `macro:opening:switch_t`
- `macro:opening:switch_reason`
- `macro:scv:housekeeping:last_done_at`
- `macro:gas:status`
- `macro:gas:target_workers_per_refinery`
- `macro:exec:*`
- `tech:exec:*`
- `control:phase`
- `control:pressure:*`
- `macro:morph:*`
- `macro:mules:*`

---

## 3) Fluxo alvo de harass

Fluxo oficial atual:
1. `weak_points_intel` atualiza `enemy:weak_points:*` na `Awareness`.
2. `harass_planner` le `enemy:weak_points:primary` e define `objective`.
3. planner cria proposal com `task_factory(..., preferred_target=objective)`.
4. tasks de harass executam somente o alvo recebido (`preferred_target`), sem recalcular `weak_points` internamente.

Isso centraliza decisao no planner e deixa task focada em execucao.

---

## 4) Manutencao

Ao mudar:
- campos de `Attention`
- chaves de `Awareness.mem`
- fluxo planner -> task

atualize este arquivo na mesma PR.
