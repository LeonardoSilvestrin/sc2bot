# Mapa de migração: `matematização` → bot enxuto

Este documento compara a base limpa no commit
`ffe400e5430c422b3420b9975fd30ee118b4f60e` com a branch `matematização`.
A branch antiga é material de pesquisa: dela vêm invariantes, fórmulas e lições de
gameplay, não a arquitetura de destino.

## Mapa priorizado

| Componente antigo | O que realmente faz | Parte valiosa | Complexidade / problema | Decisão | Destino novo |
| --- | --- | --- | --- | --- | --- |
| `AresWorldObserver` + `WorldFacts` + `AttentionService` + `AttentionSnapshot` | Converte o estado mutável do Ares em uma visão imutável do frame | Snapshot de unidade, contagens econômicas, custo protegido do opening e utilização de produtores suavizada por tempo | O observer tem cerca de 1.400 linhas e `AttentionService` apenas embrulha `WorldFacts` em outro objeto | **REIMPLEMENTAR** | Um `AttentionState` público, produzido diretamente por `observe(bot, iteration)`; helpers privados por assunto somente quando o arquivo exigir |
| `EnemyKnowledge`, `EnemyRoster` e `EnemyBaseMemory` | Mantêm o que foi visto, quando foi visto e quais bases foram confirmadas ou esvaziadas | Memória por tag, remoção por morte confirmada, idade/confiança de observações e estados `CONFIRMED/EMPTY/UNKNOWN` | Três memórias parcialmente sobrepostas e vários snapshots intermediários | **MANTER IDEIA** | Estado privado de `Awareness`; uma única coleção pública de contatos e bases lembradas |
| `belief/estimate.py`, `belief/relative.py`, economia e exército | Estimam quantidades inimigas incompletamente observadas e estabilizam comparações | Decaimento por tempo de jogo, piso do que foi observado, distribuição truncada, probabilidade de vantagem e histerese | Modelo forte cercado por muitos tipos de transporte e dois pipelines paralelos | **MANTER MATEMÁTICA** | Funções puras internas de `Awareness`; migrar depois da fatia mínima, com testes das invariantes matemáticas |
| `EnemyForceTracker` e clustering | Agrupam contatos inimigos e preservam a identidade dos grupos entre frames | Pareamento determinístico por tags compartilhadas, proximidade e desempate por id | Clustering, tracking, heurísticas e modelos estão fragmentados antes de haver necessidade na base nova | **MANTER IDEIA** | Um módulo interno de forças em `Awareness`, apenas quando defesa/map control precisarem de forças agregadas |
| `SpatialFieldModel`, kernel e território | Espalham influência, estimam ameaça/controle e extraem regiões, passagens e frontline | Kernel gaussiano, saturação `1-exp(-x)`, distinção entre ameaça possível e controle confirmado, cache/cadência | É o maior subsistema cognitivo e introduz lattice, projeções e muitos snapshots | **MANTER MATEMÁTICA** | Adiar; começar com distância a bases. Depois adicionar um `SpatialAwareness` interno com um resultado público compacto |
| `StrategicDirector`, scoring e histerese | Pontuam objetivos a partir de sinais normalizados e evita oscilações | Contribuições explicáveis, limites `[-1,1]`/`[0,1]`, margens, tempo mínimo e desempate conservador | `StrategyInputs → StrategySnapshot → StrategicIntent → StrategicContext` repete a mesma decisão em vocabulários diferentes | **REIMPLEMENTAR** | Um `StrategyState` público com objetivo, preferências e razão; o decisor guarda somente o estado necessário à histerese |
| `StrategicIntent`, `ControlObjectives`, `MissionSignals`, `MissionEvaluation` e `MissionRanker` | Traduz estratégia em preferências e aplica uma utilidade comum às missões | Normalização de utilidade, piso de emergência, penalidade de risco e contribuição detalhada para diagnóstico | Política central cria uma burocracia entre Strategy e Behaviors e duplica representação estratégica | **MANTER MATEMÁTICA / DESCARTAR CAMADAS** | Cada behavior calcula sua prioridade com seus sinais locais modulados diretamente por `StrategyState`; a proposta já chega pronta ao Engine |
| `UnitAllocator` | Garante posse exclusiva, escolhe unidades e permite preempção controlada | Lease exclusivo, filtros explícitos, `minimum/desired`, ordenação total, compromisso e margem de preempção | Requisitos, squads, custos dinâmicos e lifecycle completo são maiores que a necessidade inicial | **REIMPLEMENTAR MENOR** | `Engine` com mapa `unit_tag → owner`, seleção determinística e prioridade; adicionar commitment/preempção apenas quando dois behaviors reais competirem |
| `MissionController`, `MissionBoard`, executors e registry | Admite, atualiza, bloqueia, executa e encerra missões | Ordem determinística, deduplicação, limpeza de posse ao terminar e motivo de cada decisão | Controller de mais de 600 linhas, registry, factories e vários estados antes de existir um conjunto pequeno de missões | **REIMPLEMENTAR MENOR** | Um `Engine.step(proposals)` que ordena, aloca e chama um executor/função da proposta; lifecycle finito somente quando scouting/harass exigirem |
| `StandingPlanner`, `StandingExecutor` e squads | Dá dono e posição de repouso a toda unidade de combate sem tarefa melhor | Invariante “toda unidade controlável tem exatamente um dono” e fallback de menor prioridade | Standing vira missão persistente, squad e lifecycle próprio | **REIMPLEMENTAR** | `CoreArmy` simples, sempre presente e último na arbitragem; segura/reagrupa no ponto escolhido por Strategy |
| Defense assessor/planner/model/executor | Detecta ameaça por base, dimensiona resposta e posiciona unidades por função | Urgência local, razão ameaça/proteção, preferência anti-ar/ground, geometria de screen/siege e liberação segura de Tanks | Um comportamento ocupa quatro módulos e replica assessment/model/plan/executor mesmo onde há pouco estado | **REIMPLEMENTAR MENOR** | `behaviors/defense.py`; separar executor apenas quando o ciclo de siege justificar |
| Macro planner, `ArmyDemand` e capacidade | Converte metas de composição em dívida de exército e detecta gargalo de produção | Target por supply, contagem de pending, tech readiness, demanda por produtor e utilização sustentada | `MacroPosture` é uma segunda autoridade estratégica; proposals/controller/contexts alongam a causa de uma compra | **MANTER MATEMÁTICA / REIMPLEMENTAR** | `macro.py` recebe `StrategyState`; funções de worker, supply, army e capacity retornam ações simples. O build runner do Ares sustenta o opening inicial |
| Scouting, Map Control, Reaper e Banshee | Criam capacidades especializadas com cadência, oportunidade, risco e alvo | Ganho de informação por idade, retenção de alvo, avaliação espacial e micro específico já testado | Template obrigatório assessor/model/planner/executor gera dezenas de tipos e arquivos | **MANTER IDEIA** | Um arquivo por behavior no início; extrair planner/executor somente se houver estado tático real |
| JSONL, `ChangeGate` e telemetry reporters | Registra uma cadeia causal reproduzível por frame | Envelope `run/seq/iteration/time`, JSON estrito, log por mudança + heartbeat e ids que unem decisão à ação | Muitos reporters e snapshots repetem o estado inteiro; o viewer é um segundo produto | **MANTER IDEIA** | Um logger JSONL pequeno e eventos nos pontos de decisão. Registrar valores de entrada, resultado e razão; viewer fica para depois |
| Testes da branch antiga | Protegem fórmulas, decisões, arquitetura e integrações | Determinismo, posse exclusiva, ausência de conflito, transições, replay e bugs reais | Grande parte fixa DTOs, imports e camadas que não existirão | **SELECIONAR E REESCREVER** | Testes pequenos de estado e invariantes; reutilizar cenários/replays, não a estrutura dos testes |

## Primeira fatia vertical executável

Objetivo: produzir um bot Terran que observa o frame, reconhece ataque à base,
escolhe entre defender e manter o exército reunido, arbitra cada unidade uma única
vez e registra por que cada comando ocorreu. O opening e a economia continuam sob
o build runner e os behaviors básicos do Ares nesta fatia.

Arquivos iniciais previstos:

```text
bot/
  main.py
  attention.py
  awareness.py
  strategy.py
  engine.py
  telemetry.py
  behaviors/
    __init__.py
    core_army.py
    defense.py
tests/
  test_awareness.py
  test_strategy.py
  test_engine.py
  test_defense.py
  test_frame_flow.py
```

Fluxo de um frame:

```text
attention = observe(bot, iteration)
awareness = awareness_model.infer(attention)
strategy = strategy_model.decide(awareness)
proposals = defense.plan(attention, awareness, strategy)
proposals += core_army.plan(attention, awareness, strategy)
engine.execute(bot, attention, proposals)
telemetry.record(attention, awareness, strategy, proposals, engine.result)
```

Contratos mínimos:

- `AttentionState`: tempo, recursos/supply, unidades próprias, inimigos visíveis,
  estruturas e posições das bases. Não interpreta ameaça.
- `AwarenessState`: contatos inimigos lembrados e ameaças por base. Na primeira
  versão, ameaça é uma função explícita de capacidade de ataque e distância.
- `StrategyState`: `objective` (`STABILIZE` ou `BUILD_ADVANTAGE`), `defense`,
  `army`, `economy`, `risk` e `reason`. Ameaça imediata escolhe `STABILIZE`;
  ausência dela escolhe `BUILD_ADVANTAGE`.
- `MissionProposal`: id, owner, priority, requested unit types/count, target,
  reason e comando local. Nada de signals/context/evaluation intermediários.
- `Engine`: ordena por `(-priority, owner, proposal_id)`, entrega cada tag a no
  máximo uma proposta e executa somente comandos autorizados pelo mapa de posse.
- `CoreArmy`: pede toda unidade de combate ainda livre com prioridade de fallback.
- `Defense`: cria uma proposta por base ameaçada, com prioridade derivada de
  urgência local e da preferência defensiva de Strategy.

Critérios de conclusão da fatia:

1. O `on_step` mostra, em ordem, Attention → Awareness → Strategy → Behaviors → Engine.
2. A mesma entrada sempre produz a mesma estratégia, ordem de propostas e alocação.
3. Nenhuma unidade recebe comandos de dois owners no mesmo frame.
4. Toda unidade de combate elegível pertence a Defense ou CoreArmy.
5. Defense supera CoreArmy quando existe ameaça, e a posse volta ao CoreArmy quando ela some.
6. Cada ação pode ser explicada por um registro curto com observação, inferência,
   estratégia, proposta, vencedor, tags e comando.
7. Testes unitários não precisam instanciar `AresBot`; somente o teste do fluxo usa um fake do bot.
8. O bot continua importável e o runner existente continua iniciando `MyBot`.

## Matemática candidata, fora da primeira fatia

### Estimativa relativa de exército

- **Entradas:** supply próprio, supply inimigo conhecido, idade dos contatos e cobertura.
- **Modelo:** piso conhecido com decaimento `exp(-idade/τ)`, informação que também
  decai por tempo e probabilidade de vantagem sobre o restante não observado.
- **Saída:** supply inimigo estimado, confiança e `P(próprio > inimigo)`.
- **Por quê:** modular agressão/defesa sem confundir falta de visão com vantagem.

### Campo espacial

- **Entradas:** posição, raio, força e confiança de cada força lembrada.
- **Modelo:** `K(d, σ) = exp(-0.5 d²/σ²)` e saturação `S(x) = 1 - exp(-x)`;
  incerteza alarga ameaça possível, mas não cria controle territorial confirmado.
- **Saída:** ameaça, apoio, controle e confiança em `[0, 1]` por ponto relevante.
- **Por quê:** escolher rotas, posições defensivas e objetivos de map control.

### Demanda e capacidade de produção

- **Entradas:** target de supply militar, pesos/custos da composição, unidades
  ready/pending, tech, produtores e utilização suavizada.
- **Modelo:** `ciclos = target_supply / Σ(peso × supply)` e
  `desejado_tipo = max(mínimo, ceil(peso × ciclos))`; nova capacidade só é
  proposta com dívida buildable e produtores sustentadamente ocupados.
- **Saída:** dívida por unidade e quantidade desejada de produtores.
- **Por quê:** impedir tanto produção que para cedo quanto construção de fábricas ociosas.

## Explicitamente fora da primeira fatia

Belief probabilístico completo, territory/lattice, ControlObjectives, MissionPolicy,
squads, scans, economy controller próprio, scouting, map control, harassment,
mission lifecycle genérico, viewer e snapshots SVG. Cada item só entra depois de
um problema de gameplay mensurável e preservando o fluxo público curto.
