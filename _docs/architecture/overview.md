# Arquitetura v2

Arquitetura oficial do bot baseada no codigo atual.

Modelo:

`Sensor -> Attention -> Intel -> Awareness -> Planner -> Ego -> Task -> Ares/python-sc2`

Objetivos:
- separar fatos do tick (`Attention`) de memoria (`Awareness`)
- manter arbitragem unica no `Ego`
- garantir ownership de unidades por missao
- manter rastreabilidade por logs/eventos

---

## Principios

1. `Sensors` so leem estado do jogo.
2. `Attention` e snapshot imutavel por tick.
3. `Intel` transforma sinais em estado persistente (`Awareness`).
4. `Planners` propoem (`Proposal`), nao executam micro.
5. `Ego` arbitra admissao, cooldown, preempcao e binding.
6. `Tasks` sao a unica camada que emite comandos no jogo.
7. Decisoes importantes devem ser observaveis em logs.

---

## Topologia

Entradas principais:
- `run.py`
- `bot/main.py`
- `bot/mind/self.py`

Componentes centrais:
- `Sensors`: `bot/sensors/*`
- `Attention`: `bot/mind/attention.py`
- `Intel`: `bot/intel/*`
- `Awareness`: `bot/mind/awareness.py`
- `Planners`: `bot/planners/*`
- `Ego`: `bot/mind/ego.py`
- `Tasks`: `bot/tasks/*`
- `Body/Leases`: `bot/mind/body.py`

Pipeline:
1. sensors derivam snapshot
2. `derive_attention(...)`
3. intels atualizam `Awareness`
4. planners retornam `list[Proposal]`
5. `Ego` valida/admite
6. `Ego` executa tasks ativas
7. tasks emitem comandos no jogo

---

## Fluxo por tick

Sequencia em `RuntimeApp.on_step`:
1. `attention = derive_attention(...)`
2. `derive_enemy_build_intel(..., attention=attention, awareness=awareness, ...)`
3. `derive_my_army_composition(...)` e `derive_game_parity(...)`
4. `await ego.tick(..., attention=attention, awareness=awareness)`

Dentro de `Ego.tick`:
1. reap de leases/commitments expirados
2. coleta propostas de todos planners
3. valida `prop.validate()`
4. ordena por `score`
5. tenta admissao (`_admit`)
6. executa missoes (`_execute`) via `TaskResult`

Eventos principais:
- `attention_tick`
- `planner_proposed`
- `mission_started`
- `mission_step`
- `mission_ended`

---

## Contratos por camada

### Sensors

Permitido:
- ler estado do bot/engine

Proibido:
- escrever em `Awareness`
- emitir comando de unidade

### Attention

- snapshot somente leitura
- sem historico
- sem side-effect

Tipos principais:
- `EconomySnapshot`
- `CombatSnapshot`
- `UnitThreatsSnapshot`
- `IntelSnapshot`
- `MacroSnapshot`
- `EnemyBuildSnapshot`
- `MissionSnapshot`
- `Attention`

Nota: contrato antigo `economy.bases` foi removido; usar `economy.bases_sat`.

### Intel

- converte fatos em inferencia/state
- grava em `Awareness.mem` com TTL quando aplicavel
- nao comanda unidades

Split atual de enemy intel:
- `bot/intel/opening_intel.py`
- `bot/intel/weak_points_intel.py`
- orquestrador: `bot/intel/enemy_build_intel.py`

### Awareness

- blackboard entre ticks
- chaves namespaceadas via `K(...)`
- suporte a `ttl`, `age`, `staleness`, eventos

### Planners

Entrada:
- `Attention + Awareness`

Saida:
- `list[Proposal]`

Proibido:
- comando direto de unidade

Planners atuais:
- `DefensePlanner`
- `IntelPlanner`
- `HarassPlanner`
- `ReinforceMissionPlanner`
- `ProductionPlanner`
- `SpendingPlanner`
- `TechPlanner`
- `HousekeepingPlanner`
- `DepotControlPlanner`

### Ego

Responsabilidades:
- cooldown de propostas
- threat gate por dominio
- singleton/preempcao de dominio
- selecao/binding de unidades
- lifecycle de missao e persistencia em `Awareness`

### Tasks

Contrato:
- `on_step` retorna `TaskResult`
- status operacionais: `RUNNING`, `DONE`, `FAILED`, `NOOP`
- `bind_mission(...)` obrigatorio

Somente tasks emitem `move/attack/train/register_behavior/...`.

---

## Modelo de proposal/missao

Definicoes oficiais em:
- `bot/planners/utils/proposals.py`

Estruturas:
- `UnitRequirement(unit_type, count, pick_policy, required)`
- `TaskSpec(task_id, task_factory, unit_requirements, lease_ttl)`
- `Proposal(proposal_id, domain, score, tasks, reinforce_mission_id, lease_ttl, cooldown_s, risk_level, allow_preempt)`

Regras:
- `tasks` contem exatamente 1 `TaskSpec`
- `pick_policy` e obrigatorio por requisito
- `task_factory` recebe `mission_id`
- `reinforce_mission_id` permite bind de reforco na missao existente

### Admissao

`Ego._admit`:
1. ignora cooldown
2. valida singleton/domain gate
3. resolve requisitos por `pick_policy`
4. claim de unidades
5. bind task + commitment
6. persiste composicao original da missao

### Execucao e encerramento

`Ego._execute`:
- encerra por expiracao/degradacao
- executa `task.step(...)`
- em `FAILED`: aplica cooldown e encerra
- em `DONE`: encerra
- em `RUNNING/NOOP`: mantem ativa

---

## Estado persistente

Catalogo detalhado:
- [runtime/state_catalog.md](../runtime/state_catalog.md)

Namespaces principais:
- `ops:*` (missoes, cooldowns, proposals)
- `intel:*` (scout/scan)
- `enemy:*` (opening/rush/weak_points)
- `macro:*` (housekeeping, morph, mules)

---

## Observabilidade

Implementacao:
- `bot/devlog.py`

Formato:
- JSONL consolidado por run
- JSONL por modulo e por componente

Eventos-chave:
- churn de missao: `mission_started` e `mission_ended`
- falhas e cooldowns: `mission_ended` com `status=FAILED`
- pressao de combate: `attention_tick` (`primary_urgency`, `primary_enemy_count`, `threatened_bases`)
- decisao de planner: `planner_proposed`

Triagem rapida:
1. validar `attention_tick`
2. validar `planner_proposed`
3. validar `mission_started` e `mission_ended`
4. validar eventos de task (`*_tick`)

---

## Invariantes

1. `Attention` nao persiste estado entre ticks.
2. `Intel` nao emite comandos.
3. `Planners` nao executam micro.
4. `Ego` arbitra admissao e ownership.
5. Toda `Task` retorna `TaskResult` valido.
6. Toda missao admitida deixa rastro em `Awareness`.
7. Leases sao liberados ao fim da missao.
