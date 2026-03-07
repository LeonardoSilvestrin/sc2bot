# Attention Bus

Este documento define o contrato entre `Sensors` e o resto do sistema.

O `Attention` guarda o pacote do tick:
- snapshots coletados pelos sensors
- derivados leves de consolidacao
- nada de inferencia estrategica persistente

Se o Attention for mal definido, Intel, Controls e Planners passam a disputar logica e ownership.

---

## Papel na arquitetura

Fluxo relevante:

```text
Ares/Game -> Sensors -> Attention -> (Intel, Controls, Planners)
                              |
                              v
                           Intel -> Awareness
```

- `Sensors` escrevem no Attention
- `Intel/Controls/Planners` leem do Attention
- Attention e efemero por tick
- Persistencia fica em Awareness

---

## Regra de ouro

O Attention contem:
1. fatos do tick
2. consolidacao mecanica leve para facilitar consumo

O Attention nao contem inferencia estrategica, por exemplo:
- `rush_detected`
- `enemy_opening_type`
- `phase=midgame`
- `strategic_intent=...`

Esses sinais pertencem a `Intel -> Awareness`.

---

## Estrutura

Cada slot do Attention deve conter:
- `value`
- `ts`
- `source`
- `valid_for_ticks` opcional

Modelo conceitual:

```text
Attention
  - economy: EconomySnapshot
  - combat: CombatSnapshot
  - enemy: EnemySnapshot
  - tech: TechSnapshot
  - production: ProductionSnapshot
  - map: MapSnapshot
  - misc: MiscSnapshot
```

---

## Convencoes obrigatorias

### Tempo

- `ts` usa `iteration/frame` do SC2 como unidade canonica
- segundos so existem como derivacao

### Ausente vs zero

- `None` = desconhecido ou nao observado
- `0` = observado e zero

### Snapshot vazio

Quando sensor falhar, escrever snapshot vazio com shape estavel.

Shape minimo recomendado:
- listas, contadores e conjuntos: vazios
- bools: `False`
- numericos observaveis: `0`
- confianca ou estimativa: `None`
- timestamps internos: `None`

### Precedencia de escrita

- regra padrao: um slot, um sensor dono
- se houver fallback:
  1. sensor primario
  2. sensor fallback
  3. ultimo writer apenas se mesma prioridade e `ts` maior

---

## Tipos de chave

- `BaseKey`: identificador estavel de base
- `UnitTag`: tag nativa do SC2

---

## Snapshots minimos recomendados

### EconomySnapshot

- `minerals: int`
- `gas: int`
- `supply_used: int`
- `supply_cap: int`
- `supply_left: int`
- `worker_count: int`
- `base_count: int`
- `units_ready: Counter[UnitTypeId, int]`
- `income_minerals: float | None`
- `income_gas: float | None`

### CombatSnapshot

- `enemy_visible_by_type: Counter[UnitTypeId, int]`
- `enemy_army_supply_visible: float | None`
- `enemy_near_bases: bool`
- `enemy_near_base_keys: list[BaseKey]`
- `threat_positions: list[Point2]`
- `friendly_army_supply: float | None`
- `friendly_near_bases: bool`

### EnemySnapshot

- `enemy_structures_by_type: Counter[UnitTypeId, int]`
- `enemy_units_by_type: Counter[UnitTypeId, int]`
- `enemy_bases_seen: int`
- `enemy_workers_seen: int | None`
- `last_seen_at: dict[UnitTag, int | None]`
- `scouting_confidence: float | None`

### TechSnapshot

- `self_upgrades: set[UpgradeId]`
- `self_tech_structures: Counter[UnitTypeId, int]`
- `self_addons: Counter[UnitTypeId, int]`
- `enemy_tech_structures_seen: Counter[UnitTypeId, int]`
- `enemy_upgrades_seen: set[UpgradeId]`

### ProductionSnapshot

- `units_in_production: Counter[UnitTypeId, int]`
- `buildings_in_production: Counter[UnitTypeId, int]`
- `idle_production_buildings: Counter[UnitTypeId, int]`
- `refineries: int`
- `cc_count: int`
- `available_production_capacity: int | None`

### MapSnapshot

- `owned_base_keys: list[BaseKey]`
- `enemy_base_keys_known: list[BaseKey]`
- `expansion_sites: list[Point2]`
- `rally_points: list[Point2] | None`
- `choke_info: dict | None`
- `influence_fields_available: bool | None`

---

## Consolidacoes permitidas e proibidas

Permitido:
- histogramas
- normalizacao
- listas e contagens do tick
- thresholds do tick como `enemy_near_bases`

Proibido:
- `rush_detected`
- `enemy_opening_type`
- `strategic_phase`
- `counter_strategy`

---

## API de uso

Operacoes minimas:
- `set(key, value, source, ts, valid_for_ticks=None)`
- `get(key) -> value | None`
- `has(key) -> bool`

Convencoes:
- chaves fixas
- valores como dataclasses, preferencialmente
- sensor em falha escreve snapshot vazio sempre que possivel

---

## Anti-patterns

1. Intel lendo direto Game/Ares sem passar por Attention
2. Sensor escrevendo flag estrategica
3. Attention virando banco de dados

---

## Checklist para novo sensor

1. O sensor e read-only?
2. Escreve snapshot claramente definido?
3. Snapshot e factual e do tick?
4. Ha consumidor claro?
5. Falha com snapshot vazio sem crash?
6. `ts` usa iteration/frame?
7. Respeita `None` vs `0`?
