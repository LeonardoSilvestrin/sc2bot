# ARQUITETURA v2 (Runtime Real)

## 1. Objetivo

Este documento define a arquitetura oficial do bot com base no codigo atual.

Modelo oficial:

`Sensor -> Attention -> Intel -> Awareness -> Planner -> Ego -> Task -> Ares/python-sc2`

Objetivos praticos:

- Separar fatos do tick (`Attention`) de memoria e inferencia (`Awareness`).
- Manter um orquestrador unico de missoes (`Ego`) com contratos estaveis.
- Garantir ownership explicito de unidades (`UnitLeases`).
- Manter o sistema auditavel por eventos e logs (`DevLogger`).

Este documento foca exclusivamente no modelo operacional vigente no codigo atual.

---

## 2. Principios Arquiteturais

1. `Sensors` leem estado do jogo e nao emitem comandos.
2. `Attention` e um snapshot imutavel por tick.
3. `Intel` transforma sinais em crenças e grava em `Awareness`.
4. `Planners` propõem candidatos de missao (`Proposal`) e nao executam micro.
5. `Ego` e o unico arbitro de admissao, cooldown, preempcao e leases.
6. `Tasks` sao a unica camada que comanda unidades/estruturas.
7. Ownership de unidade e explicito por `mission_id` e `UnitRole`.
8. Toda decisao operacional relevante deve ser observavel em log/evento.

---

## 3. Topologia do Sistema (real)

### 3.1 Entradas principais

- [`run.py`](run.py): inicializacao do bot e partida local/ladder.
- [`bot/main.py`](bot/main.py): integra `MyBot(AresBot)` com `RuntimeApp`.
- [`bot/mind/self.py`](bot/mind/self.py): composicao da runtime e loop por tick.

### 3.2 Componentes centrais

- `Sensors`: em `bot/sensors/*`
- `Attention`: [`bot/mind/attention.py`](bot/mind/attention.py)
- `Intel`: `bot/intel/*` (atual: enemy opening inference)
- `Awareness`: [`bot/mind/awareness.py`](bot/mind/awareness.py)
- `Planners`: `bot/planners/*`
- `Ego`: [`bot/mind/ego.py`](bot/mind/ego.py)
- `Tasks`: `bot/tasks/*`
- `Body/Leases`: [`bot/mind/body.py`](bot/mind/body.py)

### 3.3 Pipeline canonico

1. Sensors derivam snapshot do tick.
2. Snapshot e consolidado em `Attention`.
3. Intel le `Attention` e atualiza `Awareness` (stateful).
4. Planners leem `Attention + Awareness` e retornam `Proposal`.
5. Ego valida/ordena/admite propostas.
6. Ego executa tasks ativas e fecha missoes quando necessario.
7. Tasks enviam comandos via Ares/python-sc2.

---

## 4. Fluxo por Tick (sequencia oficial)

Sequencia implementada em [`RuntimeApp.on_step`](bot/mind/self.py):

1. `attention = derive_attention(...)`
2. `derive_enemy_build_intel(..., attention=attention, awareness=awareness, ...)`
3. `await ego.tick(..., tick=TaskTick, attention=attention, awareness=awareness)`

Dentro de `Ego.tick`:

1. `body.reap(...)` + reap de commitments expirados.
2. coleta de propostas de todos os planners.
3. `prop.validate()` para cada proposta.
4. ordenacao por `score` decrescente.
5. admissao (`_admit`) com regras de cooldown, singleton domain e threat gate.
6. execucao (`_execute`) das missoes ativas e transicao por `TaskResult`.

Eventos emitidos durante o fluxo:

- `attention_tick`
- `planner_proposed` (quando planner loga)
- `mission_started`
- `mission_step`
- `mission_ended`

---

## 5. Contratos por Camada

## 5.1 Sensors

Responsabilidade:

- Derivar fatos do estado atual do jogo.

Permitido:

- Ler estado do bot/engine.

Proibido:

- Escrever em `Awareness`.
- Emitir comandos de unidade.

Exemplos:

- `derive_economy_snapshot`
- `derive_combat_snapshot`
- `derive_enemy_build_sensor`
- `derive_macro_snapshot`
- `derive_orbital_snapshot`

## 5.2 Attention

Responsabilidade:

- Representar snapshot imutavel por tick.

Contrato:

- Sem side-effects.
- Sem memoria historica.
- Campos estaveis usados por planners/tasks.

Tipos principais:

- `EconomySnapshot`
- `CombatSnapshot`
- `IntelSnapshot`
- `MacroSnapshot`
- `EnemyBuildSnapshot`
- `Attention`

## 5.3 Intel

Responsabilidade:

- Converter fatos de `Attention` em crenças stateful em `Awareness`.

Permitido:

- Escrever chaves em `Awareness.mem` com TTL quando fizer sentido.

Proibido:

- Comandar unidades.

Exemplo atual:

- [`derive_enemy_build_intel`](bot/intel/enemy_build_intel.py): classifica abertura inimiga (`GREEDY/NORMAL/AGGRESSIVE`) e grava sinais em `Awareness`.

## 5.4 Awareness

Responsabilidade:

- Blackboard de estado entre ticks.

Contrato:

- Chaves namespaceadas via `K(...)`.
- Suporte a `ttl`, `age`, `staleness`.
- API de eventos (`emit`, `tail_events`).

Regra:

- `Awareness` nao executa comandos; apenas estado e eventos.

## 5.5 Planners

Responsabilidade:

- Gerar `Proposal` com score e `TaskSpec`.

Entrada:

- `Attention` + `Awareness`.

Saida:

- `list[Proposal]`.

Proibido:

- Comandar unidades diretamente.

Planners atuais:

- `DefensePlanner`
- `IntelPlanner`
- `MacroPlanner`

## 5.6 Ego

Responsabilidade:

- Arbitragem central de operacoes.

Funcoes:

- aplicar cooldown de proposta
- bloquear dominios nao defensivos sob alta ameaca
- garantir singleton por dominio configurado
- selecionar/claim de unidades por requisito
- bind de missao em task
- lifecycle de missao + persistencia em `Awareness`

`Ego` e o unico dono do ciclo de admissao/execucao/encerramento de missao.

## 5.7 Tasks

Responsabilidade:

- Execucao concreta no jogo.

Contrato:

- `on_step` retorna obrigatoriamente `TaskResult`.
- Estados efetivos: `RUNNING`, `DONE`, `FAILED`, `NOOP`.
- `bind_mission(...)` e obrigatorio antes de executar.

Somente tasks podem enviar comandos para jogo (`attack`, `move`, `train`, `register_behavior`, etc.).

---

## 6. Modelo de Missao Atual

Definicoes em [`bot/planners/proposals.py`](bot/planners/proposals.py):

- `UnitRequirement(unit_type, count)`
- `TaskSpec(task_id, task_factory, unit_requirements, lease_ttl)`
- `Proposal(proposal_id, domain, score, tasks[1], lease_ttl, cooldown_s, risk_level, allow_preempt)`

Observacoes:

- `Proposal.tasks` contem exatamente 1 `TaskSpec` no modelo atual.
- `task_factory` recebe `mission_id`.

## 6.1 Admissao de missao

Durante `_admit`, `Ego`:

1. ignora proposta em cooldown
2. ignora proposta ja em execucao
3. aplica threat gate (`domain != DEFENSE` sob urgencia alta)
4. aplica preempcao para dominios singleton
5. seleciona e claima unidades (se houver requisitos)
6. instancia task, faz bind de missao e registra commitment

## 6.2 Execucao e encerramento

Durante `_execute`, `Ego`:

- encerra expiradas (`reason=expired`)
- executa `task.step(...)`
- em `FAILED`: aplica cooldown e encerra
- em `DONE`: encerra
- em `RUNNING/NOOP`: mantem ativa e registra `mission_step`

## 6.3 Leases e ownership

`UnitLeases` garante exclusividade por `mission_id` com TTL:

- `claim(...)`
- `touch(...)`
- `release_mission(...)`
- mapeamento de `domain -> UnitRole`

Invariante:

- unidade claimada nao pode ser usada por outra missao sem release/expiracao.

---

## 7. Estado e Memoria (`Awareness.mem`)

Catalogo detalhado: [`_docs/attention_awareness.md`](_docs/attention_awareness.md).

Resumo de namespaces:

- `ops:*`: estado de missoes e cooldowns
- `intel:*`: bookkeeping de scout/scan
- `enemy:*`: inferencia de abertura inimiga
- `macro:*`: housekeeping e controles auxiliares

Politica de TTL/staleness:

- fatos inferidos com meia-vida curta usam `ttl` (ex.: enemy opening confidence)
- bookkeeping estrutural usa `ttl=None`
- consumidores devem considerar staleness (`age`, `is_stale`, `max_age`) quando relevante

---

## 8. Observabilidade e Debug

Implementacao principal em [`bot/devlog.py`](bot/devlog.py).

Formato:

- JSONL consolidado por run
- JSONL por modulo (`attention`, `planner`, `ego`, `runtime`, etc.)
- JSONL por componente
- trilhas de tick por modulo para eventos `*_tick`

Eventos-chave para diagnostico:

- Churn de missao: `mission_started`/`mission_ended`
- Cooldown e falhas: `mission_ended` com `status=FAILED` + reason
- Pressao de combate: `attention_tick` (`threatened`, `defense_urgency`)
- Decisao de planner: `planner_proposed` e eventos especificos de planner

Fluxo minimo de triagem:

1. validar `attention_tick` para contexto do jogo
2. validar `planner_proposed` para candidatas
3. validar `mission_started`/`mission_ended` para churn/preempcao
4. validar eventos de task (`*_tick`, success/fail)

---

## 9. Invariantes Operacionais

1. `Attention` nao persiste estado entre ticks.
2. `Intel` nao emite comandos de unidade.
3. `Planners` nao executam micro.
4. `Ego` decide admissao e ownership.
5. `Task` retorna `TaskResult` valido em todo `on_step`.
6. `Awareness` registra inicio/fim de toda missao admitida.
7. Leases de unidades devem ser liberados no fim de missao.

---

## 10. Limites Atuais (MVP) e Roadmap

Limites atuais:

- Enemy build intel ainda heuristico (regras fixas, sem aprendizado online).
- Ausencia de dominios completos de `Harass` e `MapControl` no runtime atual.
- Parte da macro ainda sensivel a churn de missao em cenarios especificos.
- Cobertura de testes focada no framework; modulo `bot` ainda precisa ampliar testes.

Roadmap sugerido:

1. Estabilizar lifecycle de missoes longas (reduzir churn em defesa/macro/scan).
2. Consolidar dominio de manutencao separado de macro principal.
3. Adicionar planners/tasks de `Harass` e `MapControl` com contratos iguais.
4. Introduzir KPIs de runtime (uptime por missao, preempcao por dominio, taxa de falha).
5. Expandir testes de `bot` para contracts de Ego/Planner/Task.

---

## 11. Mapa de Arquivos de Referencia

- [`bot/mind/self.py`](bot/mind/self.py)
- [`bot/mind/attention.py`](bot/mind/attention.py)
- [`bot/mind/awareness.py`](bot/mind/awareness.py)
- [`bot/intel/enemy_build_intel.py`](bot/intel/enemy_build_intel.py)
- [`bot/mind/ego.py`](bot/mind/ego.py)
- [`bot/mind/body.py`](bot/mind/body.py)
- [`bot/planners/proposals.py`](bot/planners/proposals.py)
- [`_docs/attention_awareness.md`](_docs/attention_awareness.md)

---

## 12. Status do Documento

Este arquivo substitui o modelo legado como referencia oficial.
Atualizacoes futuras devem acompanhar mudancas em contratos de `Attention/Awareness/Intel/Planner/Ego/Task`.
