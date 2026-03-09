# Catalogo de Estado

Este documento resume o contrato atual de estado do bot.

Fonte principal:
- `bot/mind/attention.py`
- `bot/mind/awareness.py`

Regra base:
- `Attention` = fatos do tick
- `Awareness` = inferencia persistente e estado operacional

---

## Attention

Campos principais do objeto `Attention`:

- `economy`
- `combat`
- `intel`
- `macro`
- `enemy_build`
- `unit_threats`
- `missions`
- `time`

### Economy

- `economy.units_ready`
- `economy.minerals`
- `economy.gas`
- `economy.supply_used`
- `economy.supply_cap`
- `economy.supply_left`
- `economy.supply_blocked`
- `economy.workers_total`
- `economy.workers_idle`
- `economy.idle_worker_tags`
- `economy.idle_worker_pos`
- `economy.bases_sat`
- `economy.surplus_mineral_worker_tags`
- `economy.deficit_mineral_worker_tags`

### Combat

- `combat.primary_base_tag`
- `combat.primary_enemy_count`
- `combat.primary_urgency`
- `combat.primary_threat_pos`
- `combat.base_threats`

### Intel

- `intel.orbital_ready_to_scan`
- `intel.orbital_energy`

### Macro

- `macro.opening_done`
- `macro.bases_total`
- `macro.prod_structures_total`
- `macro.prod_structures_idle`
- `macro.prod_structures_active`
- `macro.addon_total`
- `macro.addon_reactor_total`
- `macro.addon_techlab_total`
- `macro.addon_reactor_ratio`
- `macro.addon_techlab_ratio`

### Enemy build

- `enemy_build.enemy_units`
- `enemy_build.enemy_structures`
- `enemy_build.enemy_main_pos`
- `enemy_build.enemy_natural_pos`
- `enemy_build.enemy_units_main`
- `enemy_build.enemy_structures_main`
- `enemy_build.enemy_structures_progress`
- `enemy_build.enemy_natural_on_ground`

### Missions

- `missions.ongoing`
- `missions.ongoing_count`
- `missions.ongoing_units_alive`
- `missions.ongoing_units_missing`
- `missions.needing_support_count`

---

## Awareness.mem

Formato de chave:
- tupla `("a", "b", "c")`
- forma textual `a:b:c`

### Enemy

- `enemy:opening:kind`
- `enemy:opening:confidence`
- `enemy:opening:signals`
- `enemy:opening:last_update_t`
- `enemy:rush:state`
- `enemy:rush:tier`
- `enemy:rush:severity`
- `enemy:rush:last_confirmed_t`
- `enemy:rush:last_seen_pressure_t`
- `enemy:rush:ended_t`
- `enemy:rush:predicted`
- `enemy:aggression:state`
- `enemy:aggression:confidence`
- `enemy:build:snapshot`
- `enemy:build:units`
- `enemy:build:structures`
- `enemy:build:last_seen_t`
- `enemy:army:comp_summary`
- `enemy:weak_points:snapshot`
- `enemy:weak_points:points`
- `enemy:weak_points:primary`

### Geometria e territorio

- `intel:frontline:main:snapshot`
- `intel:frontline:nat:snapshot`
- `intel:frontline:main_shielded_by_nat`
- `intel:geometry:world:compression`
- `intel:geometry:operational:snapshot`
- `intel:geometry:operational:template`
- `intel:geometry:operational:bulk_anchor`
- `intel:geometry:operational:max_detach_supply`
- `intel:geometry:sector:<sector_id>`
- `intel:territory:defense:snapshot`
- `intel:territory:defense:active_line`

### Strategy

- `strategy:parity:state`
- `strategy:parity:army_score_norm`
- `strategy:parity:severity:army_behind`
- `strategy:parity:severity:econ_behind`
- `strategy:army:posture`
- `strategy:army:anchor`
- `strategy:army:secondary_anchor`
- `strategy:army:max_detach_supply`
- `strategy:army:min_bulk_supply`
- `strategy:army:defense_overflow`
- `strategy:army:snapshot`

### Macro desired

- `macro:opening:done`
- `macro:opening:done_reason`
- `macro:opening:done_owner`
- `macro:opening:selected`
- `macro:opening:transition_target`
- `macro:opening:requested`
- `macro:opening:requested_transition_target`
- `macro:opening:request_reason`
- `macro:opening:switch_t`
- `macro:opening:switch_reason`
- `macro:desired:mode`
- `macro:desired:phase`
- `macro:desired:scenario`
- `macro:desired:signals`
- `macro:desired:comp`
- `macro:desired:controller_comp`
- `macro:desired:priority_units`
- `macro:desired:reserve_unit`
- `macro:desired:reserve_minerals`
- `macro:desired:reserve_gas`
- `macro:desired:bank_target_minerals`
- `macro:desired:bank_target_gas`
- `macro:desired:pid_tuning`
- `macro:desired:army_supply_milestones`
- `macro:desired:unit_count_milestones`
- `macro:desired:timing_attacks`
- `macro:desired:production_structure_targets`
- `macro:desired:production_scale`
- `macro:desired:addon_targets`
- `macro:desired:tech_structure_targets`
- `macro:desired:tech_timing_milestones`
- `macro:desired:tech_targets`
- `macro:desired:construction_targets`

### Macro exec e control

- `macro:plan:active`
- `macro:plan:hash`
- `macro:plan:version`
- `macro:plan:owner`
- `macro:plan:changed_at`
- `macro:exec:*`
- `macro:gas:status`
- `macro:gas:target_workers_per_refinery`
- `control:phase`
- `control:pressure:level`
- `control:pressure:threat_pos`
- `control:priority:lag:*`
- `control:priority:bank_pi_output`
- `tech:exec:*`

### Ops

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
- `ops:cooldown:<proposal_id>:until`
- `ops:cooldown:<proposal_id>:reason`
- `ops:map_control:proposal:<pid>:last_t`
- `ops:defense:proposal:<pid>:last_t`
- `ops:harass:proposal:<pid>:last_t`
- `ops:wall:<zone>:proposal_last_t`

### Scout e scan

- `intel:scv:*`
- `intel:reaper:scout:*`
- `intel:scan:*`
- `intel:scan:by_label:*`
- `intel:worker_scout:*`
- `intel:my_comp:last_emit_t`
- `intel:opening:last_emit_t`

---

## Fluxos Relevantes

### Fluxo espacial

1. `frontline` publica estado da main e nat
2. `world compression` condensa pressao e commitment
3. `operational geometry` escolhe template e setores
4. `territorial control` transforma em linhas, zonas e slots
5. `army posture` publica adaptador legado
6. `MapControlPlanner` e `DefensePlanner` consomem isso

### Fluxo de harass

1. `weak_points_intel` publica `enemy:weak_points:*`
2. `HarassPlanner` escolhe alvo primario
3. task recebe alvo pronto e so executa

---

## Manutencao

Sempre atualize este arquivo quando mudar:
- shape de `Attention`
- chaves de `Awareness.mem`
- contrato da camada espacial
- fluxo planner -> task
