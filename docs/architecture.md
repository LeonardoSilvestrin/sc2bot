# Arquitetura: camadas

Implementação da primeira fatia do [mapa de migração](migration-map.md). No `on_start`,
Attention lê o mapa físico uma vez (`read_map`). Depois, um frame atravessa as camadas
sempre na mesma ordem, em `play_frame` ([bot/main.py](../bot/main.py)):

```text
attention = observe(bot, iteration, map_view)                  ATTENTION
awareness = awareness_model.infer(attention)                    AWARENESS
strategy  = strategy_model.decide(attention, awareness)         EGO / strategy
proposals = defense.plan(...) + core_army.plan(...)             EGO / planners
            + intel.plan(attention)
economy   = economy.plan(attention, strategy)
structures = structure_control.plan(attention)
result    = engine.allocate(attention, proposals)               BODY / engine
behaviors.execute(bot, attention, result, economy, structures)  BODY / behaviors
logs.record(bot, attention, awareness, strategy, ...)           LOGS
```

Regra: **o Planner decide O QUÊ, o Engine decide QUEM recebe O QUÊ, o Behavior decide COMO.**

Só `read_map`/`observe`, `behaviors.execute` e os observadores de `logs` tocam o bot.
Todo o resto lê estados imutáveis e é testável sem `AresBot`.

## Camadas

| Camada | Arquivo | Estado público | O que faz |
| --- | --- | --- | --- |
| ATTENTION | [bot/attention/](../bot/attention/) | `MapView`, `AttentionState` | Percepção. `map.py`/`topology.py`: no `on_start`, `read_map` congela lattice, expansões e `MapTopology` (regiões, passagens/chokes, adjacência, regiões dos starts) — "o mapa físico é assim". `frame.py`: `observe` lê o frame (recursos, workers pela contagem do jogo, unidades próprias e inimigas visíveis ordenadas por tag, bases, mortes, visibilidade) e classifica unidades (`is_army`). Não interpreta valor, ameaça ou controle. |
| AWARENESS | [bot/awareness/](../bot/awareness/) | `AwarenessState` | Pinta o mapa ao longo da partida. Memória de contatos com confiança `exp(-idade/τ)` e incerteza `min(cap, v·idade)`; esquece por morte confirmada, posição vista vazia (após carência) ou confiança < piso. Pressão por base, incidentes de ameaça (`ThreatIncident`) e campo de influência. Descreve; não escolhe margem nem prioridade. |
| EGO / strategy | [bot/ego/strategy.py](../bot/ego/strategy.py) | `StrategyState` | `STABILIZE` vs `BUILD_ADVANTAGE` com margem, permanência mínima e emergência; preferências contínuas `defense`, `army`, `economy`, `risk`; ponto de rally. |
| EGO / planners | [bot/ego/planners/](../bot/ego/planners/) | `Proposal`, `Command`, `EconomyPlan`, `StructurePlan` | Decidem o que deve ser feito (tarefa, alvo, prioridade, requisitos) sem nomear unidades. `defense`: uma demanda `ATTACK` por incidente, com um orçamento de poder repartido entre a parte aérea e a terrestre. `core_army`: `HOLD` no rally, fallback com todas as unidades livres. `intel`: `SCOUT` de um SCV pela main inimiga no early game. `economy`: plano para os macro behaviors do Ares depois do opening. `structure_control`: quais depots levantar e quais abaixar. |
| BODY / engine | [bot/body/engine.py](../bot/body/engine.py) | `EngineResult` | Só alocação. Ordena por `(-priority, owner, proposal_id)` e concede cada unidade de exército a no máximo uma proposta. Restrições duras vêm antes de qualquer ordem: `unit_types`, `must_attack` (`GROUND`/`AIR`) e, num pedido de poder, `power > 0`. Entre as elegíveis livres, as que já eram da proposta primeiro, depois as mais próximas. Pede-se `minimum_power` (unidades até atingir o poder), `count` ou todas as livres; cada `Grant` traz `power`, `status` (`FULL`/`PARTIAL`/`REJECTED`) e `reason`. Workers só são elegíveis para propostas que pedem um tipo de worker, só saindo da mineração (role `GATHERING`) ou já sendo da proposta. `released` lista quem perdeu o dono. Não comanda nada. |
| BODY / behaviors | [bot/body/behaviors/](../bot/body/behaviors/) | — | Executam os grants, despachados por `Command`. `defense` (`ATTACK`): `AMove`, Siege Tank decide o siege sem ficar preso ao ponto. `core_army` (`HOLD`): `PathUnitToTarget` até o ponto, `AMove` com inimigo a ≤ 10, Siege Tank fica sieged perto do ponto. `scout` (`SCOUT`): tira o worker da mineral, role `SCOUTING`, path sem evitar perigo. `economy`: workers liberados voltam a `GATHERING`, `Mining` e `MacroPlan`. `structure_control`: abaixa e levanta os depots do plano. `combat` guarda o que `defense` e `core_army` compartilham. |
| LOGS | [bot/logs/](../bot/logs/) | — | Log JSONL, snapshots SVG do campo e overlay in-game. Nenhum deles muda decisão nem derruba partida. |

## Matemática

- Kernel `K(d, σ) = exp(-½·d²/σ²)` e saturação `S(x) = 1 - exp(-x)` ([field.py](../bot/awareness/field.py)).
- Poder de uma unidade: `sqrt(dps · (hp + shield))`, em Marines.
- Pressão na base: `Σ poder·confiança·K(d, σ_base + incerteza)` dos atacantes ao alcance
  físico (`base_reach + incerteza`); `threat = S(pressão / full_pressure)`.
- Campo por ponto do lattice:
  - `threat`: presença possível, σ alargado pela incerteza;
  - `enemy`: presença crível, sem alargamento;
  - `support`: nosso exército e estruturas;
  - `control = support - enemy`.
- Strategy: scores `STABILIZE = danger`, `BUILD_ADVANTAGE = 1 - danger`; troca só com
  vantagem ≥ `switch_margin` e `minimum_dwell` cumprido (STABILIZE pula a permanência
  com `danger ≥ emergency_danger`). Empate inicial é conservador.
- Incidente: atacantes (poder > 0) ao alcance de alguma base, ligados em cadeia a
  ≤ `incident_link` (12) um do outro, quantas bases tocarem. `incident_id = incident:<menor tag>`:
  vale enquanto esse contato estiver no grupo; numa divisão, a parte sem ele leva a própria menor
  tag; numa fusão, vence a menor. Poder `Σ poder·confiança` (terrestre e aéreo), centro ponderado
  por esse poder, pressão em cada base afetada e `threat = S(maior pressão numa base / full_pressure)`.
  Os incidentes somam a pressão de cada base.
- Defense: por incidente, `orçamento = 1.5 · poder`, repartido em `defense:<incidente>:air`
  (`minimum_power = 1.5 · poder aéreo`, `must_attack = AIR`) e `…:ground` (idem, terrestre); as
  partes somam o orçamento e compartilham `demand_id`. `priority = threat · (0.5 + 0.5·strategy.defense)`
  (> 0 exatamente enquanto há atacante ao alcance, logo acima do CoreArmy, que é 0); no empate a
  parte aérea vem antes (id). A cobertura já no local é usada porque o Engine concede as unidades
  compatíveis mais próximas primeiro; uma incompatível não conta.
- Intel: com `workers ≥ 16` e antes de 240 s, pede um SCV. Rota: start inimigo, depois o
  sample mais distante da região da main em cada um de 8 setores angulares, anti-horário a
  partir da direção do nosso start. Um waypoint conta como visto na primeira vez em visão;
  `priority = waypoints não vistos / total`. Termina com a rota vista, o scout morto (não
  repõe) ou 90 s depois de sair; o SCV volta para a mineração.
- Economy (depois do opening): `workers` é `supply_workers`, a contagem do jogo — inclui SCVs
  dentro de refinarias, que somem de `bot.units` enquanto estão lá, e exclui os em produção.
  `bases = max(1, townhalls no chão)`; satura com `workers ≥ 16·bases` e expande saturado com
  `strategy.economy ≥ 0,5`; `gas = min(2·bases, 1 + workers // 12)`.
- StructureControl: um depot pronto sobe no frame em que um inimigo terrestre visível está a
  ≤ `raise_reach` (8) dele e desce quando nenhum esteve a essa distância por `lower_after` (3 s),
  com a última ameaça guardada por tag. Voadores não contam. Subir empurra nossas unidades de cima
  para a borda mais próxima (contadas em `friendly_on_raising`); um inimigo em cima impede a
  subida, e o comando se repete enquanto o plano pedir.

## Visualização

- **Bolinhas in-game** (`--spatial-view`): uma esfera por ponto do lattice, cor contínua
  verde (nosso) → amarelo (disputado) → vermelho (inimigo crível), laranja onde a ameaça é
  só possível; contatos com anel de incerteza, dono de cada unidade, rally e painel da estratégia.
- **SVG** (`--spatial-snapshot`): `logs/game-*/spatial/field-SSSS.svg` a cada intervalo e em
  toda troca de objetivo, com o grafo estático de regiões/passagens, ameaça, influência,
  bases, contatos, exército por dono, alvos das concessões e painel das camadas.
- **Viewer** ([logs/viewer.html](../logs/viewer.html)): carregue a pasta do jogo. Summary,
  Decision Timeline (trilhas agrupadas por camada, inspetor de todas as camadas no instante
  selecionado, SVG mais próximo, dicas de contradição e causas das mudanças), Events,
  Attention, Awareness e Engine.

## Catálogo de eventos

Envelope: `schema` (4), `run`, `seq`, `iteration`, `event`, `component` (a camada),
`game_time`, `data`. Resumos de estado passam por `ChangeGate` (mudança + heartbeat de
10 s); decisões são escritas quando mudam.

Os nomes de evento e de componente são anteriores à separação Ego/Body e continuam os
mesmos por compatibilidade com o viewer: `behavior.*`/`behaviors` são os planners, e
`engine.commanded` registra o grant que os behaviors executaram. Em `logs.frame_perf`,
as fatias de tempo são `attention`, `awareness`, `strategy`, `planners`, `engine`,
`behaviors` e `logs`.

| Evento | Camada | Quando | Dados |
| --- | --- | --- | --- |
| `game.started` | logs | `on_start` | `map`, `race`, `enemy_race`, `opening`, `build` {`commit`, `branch`}, `config_fingerprint`, `configs`, `lattice`, `bounds` |
| `map.topology_built` | attention | `on_start` | `regions`, `passages`, `chokes`, `expansions`, `unresolved_expansions`, `own_start_region`, `enemy_start_region` |
| `game.ended` | logs | `on_end` | `result` |
| `attention.observed` | attention | bases, fim do opening ou inimigos à vista mudam; amostra a cada 5 s | `minerals`, `vespene`, `supply_used`, `supply_cap`, `workers`, `army_units`, `army_supply`, `army_power`, `visible_enemy_units`, `visible_enemy_structures`, `bases`, `opening`, `opening_done` |
| `awareness.updated` | awareness | mudança de contatos/poder/ameaça por base, heartbeat | `contacts`, `visible_contacts`, `enemy_power`, `own_power`, `danger`, `bases[]` {`base_id`, `position`, `is_main`, `threat`, `pressure`, `cover`, `balance`, `air_share`, `center`}, `incidents[]` {`incident_id`, `contacts`, `center`, `power`, `ground_power`, `air_power`, `confidence`, `threat`, `pressure_by_base`} (escrito também quando os membros de um incidente mudam), `strongest_contacts[]`, `field` {`samples`, `friendly`, `contested`, `enemy`, `threatened`, `max_threat`} |
| `strategy.decided` | strategy | troca de objetivo, heartbeat | `objective`, `previous`, `since`, `reason`, `defense`, `army`, `economy`, `risk`, `rally`, `inputs`, `scores` |
| `behavior.proposed` | behaviors | o conjunto ranqueado de propostas muda | `proposals[]` {`proposal_id`, `owner`, `priority`, `command`, `target`, `count`, `minimum_power`, `must_attack`, `demand_id`, `unit_types`, `reason`, `inputs`} |
| `behavior.economy_planned` | behaviors | o plano muda | `active`, `workers`, `gas`, `bases`, `expand`, `freeflow`, `reason`, `composition[]`, `inputs` {`workers`, `bases`, `saturated_at`, `strategy_economy`} |
| `behavior.structures_planned` | behaviors | depots a abaixar/levantar ou razão mudam | `lower`, `raise`, `reason` (`no_depots`, `enemy_near`, `enemy_recently_near`, `no_enemy_near`), `inputs` {`depots`, `lowered`, `enemy_near`, `recently_near`, `ground_enemies`, `friendly_on_raising`, `nearest_ground_enemy` (só com depot e inimigo terrestre)} |
| `engine.granted` | engine | alguma concessão muda | `grants[]` {`proposal_id`, `owner`, `priority`, `requested`, `minimum_power`, `granted`, `granted_power`, `status`, `reason`, `tags`, `types`}, `transfers[]` {`tag`, `type`, `from`, `to`}, `unassigned` |
| `engine.commanded` | engine | comando, alvo (grade de 3) ou unidades de uma concessão mudam | `proposal_id`, `owner`, `command`, `target`, `tags`, `types`, `priority`, `reason`, `demand_id`, `inputs`, `strategy` {`objective`, `reason`, `defense`, `risk`}, `awareness` {`danger`, `contacts`, `enemy_power`}, `attention` {`army_units`, `visible_enemy_units`}; `tags: []` e `reason: no_units_granted` quando a concessão acaba |
| `logs.frame_perf` | logs | heartbeat | `frames`, `last_ms`, `max_ms` por camada |
| `logs.snapshot_written` / `logs.snapshot_failed` | logs | SVG escrito / falhou | `path`, `trigger`, `objective`, `elements`, `bytes`, `render_write_ms` / `error` |
| `logging.record_rejected` | logs | um registro não era JSON estrito | `rejected_event`, `rejected_component`, `error` |

## Comandos

```text
.venv\Scripts\python.exe run.py
.venv\Scripts\python.exe run.py --bot-log events
.venv\Scripts\python.exe run.py --bot-log events --spatial-view
.venv\Scripts\python.exe run.py --bot-log events --spatial-snapshot
.venv\Scripts\python.exe run.py --bot-log events --spatial-view --spatial-snapshot --spatial-view-spacing 6
.venv\Scripts\python.exe logs\open_viewer.py
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m ruff check bot tests run.py
```

## Fora desta fatia

Belief probabilístico de exército, forças agregadas, avaliação dinâmica de território,
scouting depois do early game, map control, harass, preempção com compromisso e ciclo de siege próprio da
defesa. No wall: antecipar o fechamento por contato lembrado ou pela rota, alcance pela velocidade do inimigo, distinguir
os depots do wall e política para unidades nossas empurradas ou presas do lado de fora. Na defesa: distinguir scout, worker rush e ataque; histerese de admissão/liberação; alcance por pathing em vez de
distância; eventos explícitos de linhagem de incidentes; `desired_power`, suitability e custos de assignment. Na economia:
bases por `ready + pending` explícito, CC voando, cooldown do alvo e interrupção do opening. Cada um entra quando um problema de gameplay medido pedir.
