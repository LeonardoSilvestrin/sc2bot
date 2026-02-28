# ARQUITETURA v2 (Runtime Atual)

## 1. Objetivo

Arquitetura oficial do bot baseada no codigo atual.

Modelo:

`Sensor -> Attention -> Intel -> Awareness -> Planner -> Ego -> Task -> Ares/python-sc2`

Objetivos:
- separar fatos do tick (`Attention`) de memoria (`Awareness`)
- manter arbitragem unica no `Ego`
- garantir ownership de unidades por missao
- manter rastreabilidade por logs/eventos

---

## 2. Principios

1. `Sensors` so leem estado do jogo.
2. `Attention` e snapshot imutavel por tick.
3. `Intel` transforma sinais em estado persistente (`Awareness`).
4. `Planners` propoem (`Proposal`), nao executam micro.
5. `Ego` arbitra admissao, cooldown, preempcao e binding.
6. `Tasks` sao a unica camada que emite comandos no jogo.
7. Decisoes importantes devem ser observaveis em logs.

---

## 3. Topologia

Entradas principais:
- [`run.py`](run.py)
- [`bot/main.py`](bot/main.py)
- [`bot/mind/self.py`](bot/mind/self.py)

Componentes centrais:
- `Sensors`: `bot/sensors/*`
- `Attention`: [`bot/mind/attention.py`](bot/mind/attention.py)
- `Intel`: `bot/intel/*`
- `Awareness`: [`bot/mind/awareness.py`](bot/mind/awareness.py)
- `Planners`: `bot/planners/*`
- `Ego`: [`bot/mind/ego.py`](bot/mind/ego.py)
- `Tasks`: `bot/tasks/*`
- `Body/Leases`: [`bot/mind/body.py`](bot/mind/body.py)

Pipeline:
1. sensors derivam snapshot
2. `derive_attention(...)`
3. intels atualizam `Awareness`
4. planners retornam `list[Proposal]`
5. `Ego` valida/admite
6. `Ego` executa tasks ativas
7. tasks emitem comandos no jogo

---

## 4. Fluxo por Tick

Sequencia em [`RuntimeApp.on_step`](bot/mind/self.py):
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

## 5. Contratos por Camada

### 5.1 Sensors
Permitido:
- ler estado do bot/engine

Proibido:
- escrever em `Awareness`
- emitir comando de unidade

### 5.2 Attention
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

### 5.3 Intel
- converte fatos em inferencia/state
- grava em `Awareness.mem` (com TTL quando aplicavel)
- nao comanda unidades

Split atual de enemy intel:
- [`bot/intel/opening_intel.py`](bot/intel/opening_intel.py)
- [`bot/intel/weak_points_intel.py`](bot/intel/weak_points_intel.py)
- orquestrador: [`bot/intel/enemy_build_intel.py`](bot/intel/enemy_build_intel.py)

### 5.4 Awareness
- blackboard entre ticks
- chaves namespaceadas via `K(...)`
- suporte a `ttl`, `age`, `staleness`, eventos

### 5.5 Planners
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

### 5.6 Ego
Responsabilidades:
- cooldown de propostas
- threat gate por dominio
- singleton/preempcao de dominio
- selecao/binding de unidades
- lifecycle de missao e persistencia em `Awareness`

### 5.7 Tasks
Contrato:
- `on_step` retorna `TaskResult`
- status operacionais: `RUNNING`, `DONE`, `FAILED`, `NOOP`
- `bind_mission(...)` obrigatorio

Somente tasks emitem `move/attack/train/register_behavior/...`.

---

## 6. Modelo de Proposal/Missao

Definicoes oficiais em:
- [`bot/planners/utils/proposals.py`](bot/planners/utils/proposals.py)

Estruturas:
- `UnitRequirement(unit_type, count, pick_policy, required)`
- `TaskSpec(task_id, task_factory, unit_requirements, lease_ttl)`
- `Proposal(proposal_id, domain, score, tasks, reinforce_mission_id, lease_ttl, cooldown_s, risk_level, allow_preempt)`

Regras:
- `tasks` contem exatamente 1 `TaskSpec`
- `pick_policy` e obrigatorio por requisito
- `task_factory` recebe `mission_id`
- `reinforce_mission_id` permite bind de reforco na missao existente

### 6.1 Admissao (Ego)
`Ego._admit`:
1. ignora cooldown
2. valida singleton/domain gate
3. resolve requisitos por `pick_policy`
4. claim de unidades
5. bind task + commitment
6. persiste composicao original da missao

### 6.2 Execucao/encerramento
`Ego._execute`:
- encerra por expiracao/degradacao
- executa `task.step(...)`
- em `FAILED`: aplica cooldown e encerra
- em `DONE`: encerra
- em `RUNNING/NOOP`: mantem ativa

---

## 7. Estado Persistente (Awareness)

Catalogo detalhado:
- [`_docs/attention_awareness.md`](_docs/attention_awareness.md)

Namespaces principais:
- `ops:*` (missoes, cooldowns, proposals)
- `intel:*` (scout/scan)
- `enemy:*` (opening/rush/weak_points)
- `macro:*` (housekeeping, morph, mules)

---

## 8. Observabilidade

Implementacao:
- [`bot/devlog.py`](bot/devlog.py)

Formato:
- JSONL consolidado por run
- JSONL por modulo e por componente

Eventos-chave:
- churn de missao: `mission_started`/`mission_ended`
- falhas/cooldowns: `mission_ended` com `status=FAILED`
- pressao de combate: `attention_tick` (`primary_urgency`, `primary_enemy_count`, `threatened_bases`)
- decisao de planner: `planner_proposed`

Triagem rapida:
1. validar `attention_tick`
2. validar `planner_proposed`
3. validar `mission_started`/`mission_ended`
4. validar eventos de task (`*_tick`)

---

## 9. Invariantes

1. `Attention` nao persiste estado entre ticks.
2. `Intel` nao emite comandos.
3. `Planners` nao executam micro.
4. `Ego` arbitra admissao/ownership.
5. toda `Task` retorna `TaskResult` valido.
6. toda missao admitida deixa rastro em `Awareness`.
7. leases sao liberados ao fim da missao.

---

## 10. Referencias

- [`bot/mind/self.py`](bot/mind/self.py)
- [`bot/mind/attention.py`](bot/mind/attention.py)
- [`bot/mind/awareness.py`](bot/mind/awareness.py)
- [`bot/intel/enemy_build_intel.py`](bot/intel/enemy_build_intel.py)
- [`bot/mind/ego.py`](bot/mind/ego.py)
- [`bot/mind/body.py`](bot/mind/body.py)
- [`bot/planners/utils/proposals.py`](bot/planners/utils/proposals.py)
- [`_docs/attention_awareness.md`](_docs/attention_awareness.md)
