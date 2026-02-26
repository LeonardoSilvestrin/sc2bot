# Attention & Awareness State Catalog

Este arquivo documenta:
- `bot/mind/attention.py` (`Attention`: snapshot por tick, sem memoria)
- `bot/mind/awareness.py` (`Awareness.mem`: memoria persistente com `t`/`ttl`)

Regra de arquitetura:
- `Attention` = fatos do tick atual (imutavel)
- `Awareness` = estado entre ticks (inferencias, cooldowns, bookkeeping de missoes)

---

## 1) Attention (tick snapshot)

Fonte: `bot/mind/attention.py`.

### 1.1 Attention
- `economy: EconomySnapshot`
- `combat: CombatSnapshot`
- `intel: IntelSnapshot`
- `macro: MacroSnapshot`
- `enemy_build: EnemyBuildSnapshot`
- `time: float`

### 1.2 EconomySnapshot
- `units_ready: dict` (`{UnitTypeId -> count}`)
- `supply_left: int`
- `minerals: int`
- `gas: int`

### 1.3 CombatSnapshot
- `threatened: bool`
- `defense_urgency: int` (0..100)
- `threat_pos: Optional[Point2]`
- `enemy_count_near_bases: int`

### 1.4 IntelSnapshot
- `orbital_ready_to_scan: bool`
- `orbital_energy: float`

### 1.5 MacroSnapshot
- `opening_done: bool`
  - derivado de `bot.build_order_runner.build_completed` (macro sensor)

### 1.6 EnemyBuildSnapshot (fatos do tick)
Base:
- `enemy_units: dict` (`{UnitTypeId -> count}` visiveis em qualquer lugar)
- `enemy_structures: dict` (`{UnitTypeId -> count}` visiveis em qualquer lugar)

Extended:
- `enemy_main_pos: Optional[Point2]` (strict: `enemy_start_locations[0]`)
- `enemy_natural_pos: Optional[Point2]` (2a expansao mais proxima da main inimiga)
- `enemy_units_main: dict` (visiveis no raio da main)
- `enemy_structures_main: dict` (visiveis no raio da main)
- `enemy_structures_progress: dict` com stats por estrutura:
  - `count`, `ready`, `incomplete`, `min`, `max`, `avg`
- `enemy_natural_on_ground: bool`
- `enemy_natural_townhall_progress: Optional[float]`
- `enemy_natural_townhall_type: Optional[object]`

---

## 2) Awareness.mem (estado persistente)

Fonte: `bot/mind/awareness.py`.

Formato de chave: tupla `("a","b","c")`, documentada como `a:b:c`.

### 2.1 Ops / Missions (gravado pelo Ego)
- `ops:mission:<mission_id>:status` = `"RUNNING" | "DONE" | "FAILED"`
- `ops:mission:<mission_id>:domain` = `str`
- `ops:mission:<mission_id>:proposal_id` = `str`
- `ops:mission:<mission_id>:started_at` = `float`
- `ops:mission:<mission_id>:expires_at` = `float | None`
- `ops:mission:<mission_id>:assigned_tags` = `list[int]`
- `ops:mission:<mission_id>:reason` = `str`
- `ops:mission:<mission_id>:ended_at` = `float`

### 2.2 Ops / Cooldowns
- `ops:cooldown:<proposal_id>:until` = `float`
- `ops:cooldown:<proposal_id>:reason` = `str`

### 2.3 Intel / SCV + Scan
- `intel:scv:dispatched` = `bool`
- `intel:scv:last_dispatch_at` = `float`
- `intel:scv:arrived_main` = `bool` (pode ter TTL)
- `intel:scan:enemy_main` = `bool`
- `intel:scan:last_scan_at` = `float`

### 2.4 Intel / Reaper scout
- `intel:reaper:scout:dispatched` = `bool`
- `intel:reaper:scout:last_dispatch_at` = `float`
- `intel:reaper:scout:last_done_at` = `float`

### 2.5 Macro / SCV housekeeping
- `macro:scv:housekeeping:last_done_at` = `float`

### 2.6 Enemy opening inference (EnemyBuildIntel)
- `enemy:opening:first_seen_t` = `float`
- `enemy:opening:kind` = `"GREEDY" | "NORMAL" | "AGGRESSIVE"` (TTL curto)
- `enemy:opening:confidence` = `float` (TTL curto)
- `enemy:opening:signals` = `dict` (TTL curto)
- `enemy:opening:last_update_t` = `float`

---

## 3) Manutencao

Ao mudar campos de `Attention` ou chaves de `Awareness.mem`, atualize este arquivo na mesma PR.
