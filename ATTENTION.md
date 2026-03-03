# Attention Bus

Este documento define o **Attention Bus**: o contrato entre **Sensors** e o resto do sistema.

O Attention e o lugar onde o bot guarda um "pacote do tick":
- snapshots coletados pelos sensors
- derivados leves de consolidacao (normalizacao, reducao de ruido do tick)
- nada de inferencia estrategica persistente (isso e Intel -> Awareness)

Se o Attention for mal definido, voce cria acoplamento indireto, duplicacao de logica e "farofa" entre Intel/Controls/Planners.

---

# Papel do Attention na Arquitetura

Fluxo relevante:

```text
Ares/Game -> Sensors -> Attention -> (Intel, Controls, Planners)
                              |
                              v
                           Intel -> Awareness
```

- **Sensors escrevem** no Attention.
- **Intel/Controls/Planners leem** do Attention.
- Attention e **efemero por tick**: reconstruido/atualizado continuamente.
- Qualquer coisa persistente (memoria e inferencia) fica em **Awareness**.

---

# Regra de Ouro

O Attention contem:
1. **Fatos do tick** (snapshots)
2. **Consolidacao mecanica leve** para facilitar consumo

O Attention NAO contem inferencia estrategica, por exemplo:
- `rush_detected`
- `enemy_opening_type`
- `phase=midgame`
- `strategic_intent=...`

Esses sinais pertencem a Intel -> Awareness.

---

# Estrutura do Attention

Cada slot/chave do Attention deve conter:
- `value`: snapshot do tick
- `ts`: tempo do snapshot
- `source`: sensor que gerou
- `valid_for_ticks`: opcional (TTL curto)

## Modelo conceitual

```text
Attention
  - economy: EconomySnapshot
  - combat: CombatSnapshot
  - enemy: EnemySnapshot
  - tech: TechSnapshot
  - production: ProductionSnapshot
  - map: MapSnapshot
  - misc: MiscSnapshot (opcional)
```

> O nome exato dos campos pode seguir o codigo, mas o conceito e o contrato devem ficar fixos.

---

# Convencoes Contratuais Obrigatorias

## Tempo (`ts`)

- `ts` deve usar **iteration/frame do SC2** como unidade canonica.
- Nao usar segundos como fonte primaria.
- Se for necessario expor segundos, derivar de `iteration` em camada de consumo.

## Ausente vs zero

- `None` = desconhecido/nao observado no tick.
- `0` = observado e zero.

Exemplo: `enemy_workers_seen=None` (nao scoutado) e diferente de `enemy_workers_seen=0` (scoutado e nenhum visto).

## Snapshot vazio (shape minimo)

Quando sensor falhar/degradar, escrever snapshot vazio com shape estavel (nao omitir slot).

Shape minimo recomendado:
- contadores/listas/conjuntos: vazios
- bools: `False`
- numericos observaveis: `0`
- numericos de confianca/estimativa: `None`
- timestamps internos: `None`

## Precedencia de escrita por tick

- Regra padrao: **um slot, um sensor dono**.
- Se existir fallback/override para o mesmo slot, precedencia explicita:
  1. sensor primario
  2. sensor fallback
  3. ultimo writer apenas se mesma prioridade e `ts` maior
- Overrides devem ser documentados no proprio sensor.

---

# Tipos de Chave (Glossario)

- `BaseKey`: identificador estavel de base no contexto do bot (nao coordenada bruta).
- `UnitTag`: tag nativa do SC2 para unidade.

Se o projeto tiver aliases proprios, referenciar o tipo canonico no codigo junto da definicao.

---

# Snapshots Minimos Recomendados

## EconomySnapshot

Objetivo: retrato da economia agora.

Campos recomendados:
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

Consumidores tipicos:
- Controls (bank/budget)
- Macro Planner (infra/expansao)
- Intel (detectar sinais economicos)

---

## CombatSnapshot

Objetivo: situacao de combate imediata, sem interpretar estrategicamente.

Campos recomendados:
- `enemy_visible_by_type: Counter[UnitTypeId, int]`
- `enemy_army_supply_visible: float | None`
- `enemy_near_bases: bool`
- `enemy_near_base_keys: list[BaseKey]`
- `threat_positions: list[Point2]`
- `friendly_army_supply: float | None`
- `friendly_near_bases: bool`

Consumidores tipicos:
- Intel (ameaca persistente/opening)
- Defense planner (reacao)
- Controls (boost/dampen por ameaca)

---

## EnemySnapshot

Objetivo: consolidar informacao observavel do inimigo no tick.

Campos recomendados:
- `enemy_structures_by_type: Counter[UnitTypeId, int]`
- `enemy_units_by_type: Counter[UnitTypeId, int]`
- `enemy_bases_seen: int`
- `enemy_workers_seen: int | None`
- `last_seen_at: dict[UnitTag, int | None]`
- `scouting_confidence: float | None`

Consumidores tipicos:
- Intel (opening type/tech)
- Planners (transicoes)
- Controls (ajustes por baixa confianca)

---

## TechSnapshot

Objetivo: estado tecnologico observavel (proprio e inimigo), sem inferencia.

Campos recomendados:
- `self_upgrades: set[UpgradeId]`
- `self_tech_structures: Counter[UnitTypeId, int]`
- `self_addons: Counter[UnitTypeId, int]`
- `enemy_tech_structures_seen: Counter[UnitTypeId, int]`
- `enemy_upgrades_seen: set[UpgradeId]`

Consumidores tipicos:
- Macro planner (disponibilidade de producao)
- Intel (inferir tech path)
- Controls (targets/proporcao)

---

## ProductionSnapshot

Objetivo: o que esta em producao e o que esta ocioso agora.

Campos recomendados:
- `units_in_production: Counter[UnitTypeId, int]`
- `buildings_in_production: Counter[UnitTypeId, int]`
- `idle_production_buildings: Counter[UnitTypeId, int]`
- `refineries: int`
- `cc_count: int`
- `available_production_capacity: int | None`

Nota Terran-only:
- nao usar `larva_like` no contrato principal.

Consumidores tipicos:
- Macro planner (spend/production)
- Controls (capacidade limita acao)
- Intel (detectar stalled production)

---

## MapSnapshot

Objetivo: informacao de mapa util para planners, sem score estrategico persistente.

Campos recomendados:
- `owned_base_keys: list[BaseKey]`
- `enemy_base_keys_known: list[BaseKey]`
- `expansion_sites: list[Point2]`
- `rally_points: list[Point2] | None`
- `choke_info: dict | None`
- `influence_fields_available: bool | None`

Consumidores tipicos:
- Scout planner
- Defense planner
- Macro planner

---

# Consolidacoes Permitidas vs Proibidas

Permitido (mecanico):
- histogramas (`units_ready`)
- normalizacao (`supply_left`)
- listas e contagens do tick
- thresholds do tick (`enemy_near_bases`)

Proibido (inferencia estrategica):
- `rush_detected`
- `enemy_opening_type`
- `strategic_phase`
- `counter_strategy`

---

# API de Uso (Contrato de Acesso)

Operacoes minimas:
- `set(key, value, source, ts, valid_for_ticks=None)`
- `get(key) -> value | None`
- `has(key) -> bool`

Convencoes:
- chaves fixas (economy/combat/tech/production/map/enemy)
- valores como dataclasses (preferivel) ou dicts simples
- sensor em falha deve escrever snapshot vazio sempre que possivel

---

# Anti-patterns Comuns

1. Intel pulando Attention e lendo direto Game/Ares
- reduz testabilidade e duplica logica
- usar apenas como escape hatch documentado

2. Sensor escrevendo flag estrategica
- espalha inferencia e quebra fronteira arquitetural

3. Attention virando banco de dados
- Attention e pacote de tick; persistencia e Awareness

---

# Checklist para Novo Sensor

1. O sensor e read-only?
2. Escreve snapshot claramente definido?
3. Snapshot e factual e do tick?
4. Ha consumidor claro (Intel/Controls/Planner)?
5. Falha com snapshot vazio sem crash?
6. `ts` em iteration/frame?
7. Respeita convencao `None` vs `0`?

---

# Proximos Passos

- `INTEL.md`: inferencias produzidas e escrita na Awareness
- `AWARENESS.md`: campos/sinais persistentes e invariantes
- `CONTROLS.md`: loops PI e outputs para Macro Planner
