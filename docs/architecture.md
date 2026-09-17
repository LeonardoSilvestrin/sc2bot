# Arquitetura: camadas

Implementação da primeira fatia do [mapa de migração](migration-map.md). No `on_start`,
Attention lê o mapa físico uma vez (`read_map`). Depois, um frame atravessa as camadas
sempre na mesma ordem, em `play_frame` ([bot/main.py](../bot/main.py)):

```text
attention = observe(bot, iteration, map_view)                  ATTENTION
awareness = awareness_model.infer(attention)                    AWARENESS
strategy  = strategy_model.decide(attention, awareness)         EGO / strategy
proposals = defense.plan(...) + core_army.plan(...)             EGO / planners
offense   = offense.plan(..., engine.held_by("offense"))
proposals += offense.proposals + intel.plan(attention)
economy   = economy.plan(attention, strategy)
structures = structure_control.plan(attention)
detection = detection.plan(attention, awareness)
result    = engine.allocate(attention, proposals)               BODY / engine
body      = behaviors.execute(bot, attention, result,           BODY / behaviors
                              economy, structures, detection)
logs.record(bot, attention, awareness, strategy, offense, ...,  LOGS
            body.spawn, body.micro, detection, body.detection)
```

Regra: **o Planner decide O QUÊ, o Engine decide QUEM recebe O QUÊ, o Behavior decide COMO.**

Só `read_map`/`observe`, `behaviors.execute` e os observadores de `logs` tocam o bot.
Todo o resto lê estados imutáveis e é testável sem `AresBot`.

## Camadas

| Camada | Arquivo | Estado público | O que faz |
| --- | --- | --- | --- |
| ATTENTION | [bot/attention/](../bot/attention/) | `MapView`, `AttentionState` | Percepção. `map.py`/`topology.py`: no `on_start`, `read_map` congela lattice, expansões e `MapTopology` (regiões, passagens/chokes, adjacência, regiões dos starts) — "o mapa físico é assim". `frame.py`: `observe` lê o frame (recursos, workers pela contagem do jogo, unidades próprias e inimigas visíveis ordenadas por tag, bases, mortes, visibilidade, upgrades concluídos; por unidade, energia e se está camuflada/enterrada e se nada a detecta) e classifica unidades (`is_army`). Não interpreta valor, ameaça ou controle. |
| AWARENESS | [bot/awareness/](../bot/awareness/) | `AwarenessState` | Pinta o mapa ao longo da partida. Memória de contatos com confiança `exp(-idade/τ)` e incerteza `min(cap, v·idade)`; esquece por morte confirmada, posição vista vazia (após carência) ou confiança < piso. Pressão por base com a ameaça lembrada (`recent_threat`, τ = `threat_memory`), incidentes de ameaça (`ThreatIncident`), estimativa do exército inimigo (conhecido, visto vivo, esperado sem avistamento, incerteza e cobertura), contatos escondidos (camuflados sem detecção, à vista) e quando um exército camuflado foi visto pela primeira vez, e campo de influência. Descreve; não escolhe margem nem prioridade. |
| EGO / strategy | [bot/ego/strategy.py](../bot/ego/strategy.py) | `StrategyState` | `STABILIZE` vs `BUILD_ADVANTAGE` com margem, permanência mínima e emergência; preferências contínuas `defense`, `army`, `economy`, `risk`, com o inimigo planejado como estimativa mais `commit_margin` da incerteza; ponto de rally. |
| EGO / planners | [bot/ego/planners/](../bot/ego/planners/) | `Proposal`, `Command`, `EconomyPlan`, `StructurePlan`, `DetectionPlan` | Decidem o que deve ser feito (tarefa, alvo, prioridade, requisitos) sem nomear unidades. `defense`: uma demanda `ATTACK` por incidente, com um orçamento de poder repartido entre a parte aérea e a terrestre. `offense`: ciclo de vida IDLE → ASSEMBLE → ADVANCE ⇄ SEARCH, ENGAGE/RETREAT → REGROUP; `ATTACK` no alvo ou `RETREAT` ao rally, com todas as unidades livres, lendo a própria concessão anterior. `core_army`: `HOLD` no rally, fallback com todas as unidades livres. `intel`: `SCOUT` de um SCV pela main inimiga no early game. `economy`: plano para os macro behaviors do Ares depois do opening (inclusive upgrades, Orbital e MULE), ou já durante o opening, interrompendo-o, numa emergência. `detection`: onde escanear, quais bases precisam de Missile Turret, Engineering Bay e a energia que cada Orbital guarda. `structure_control`: quais depots levantar e quais abaixar. |
| BODY / engine | [bot/body/engine.py](../bot/body/engine.py) | `EngineResult` | Só alocação. Ordena por `(-priority, owner, proposal_id)` e concede cada unidade de exército a no máximo uma proposta. Restrições duras vêm antes de qualquer ordem: `unit_types`, `must_attack` (`GROUND`/`AIR`) e, num pedido de poder, `power > 0`. Entre as elegíveis livres, as que já eram da proposta primeiro, depois as mais próximas. Pede-se `minimum_power` (unidades até atingir o poder), `count` ou todas as livres; cada `Grant` traz `power`, `status` (`FULL`/`PARTIAL`/`REJECTED`) e `reason`. Um pedido de todas as livres que não recebe nenhuma fica `REJECTED` (`eligible_units_taken`/`no_eligible_units`). Workers só são elegíveis para propostas que pedem um tipo de worker, só saindo da mineração (role `GATHERING`) ou já sendo da proposta. `released` lista quem perdeu o dono; `held_by(proposal_id)` devolve ao planner o que a última alocação lhe deu, sem que ele nomeie unidades. Não comanda nada. |
| BODY / behaviors | [bot/body/behaviors/](../bot/body/behaviors/) | — | Executam os grants, despachados por `Command`. `attack` (`ATTACK`, de Defense ou da ofensiva): `AMove`, Siege Tank decide o siege sem ficar preso ao ponto; Marine/Marauder usam Stim com inimigo a ≤ 10 e ≥ 50 % de vida; Medivac vai ao centro do próprio grupo. `retreat` (`RETREAT`): path ao ponto sem lutar, Siege Tank sai do siege. `core_army` (`HOLD`): `PathUnitToTarget` até o ponto, `AMove` com inimigo a ≤ 10 (bio usa Stim pela mesma regra do `attack`), Siege Tank fica sieged perto do ponto. `scout` (`SCOUT`): tira o worker da mineral, role `SCOUTING`, path sem evitar perigo. `economy`: para o build runner do Ares quando o plano interrompe o opening; workers liberados voltam a `GATHERING`, `Mining`, `MacroPlan` (Orbital antes de `BuildWorkers`, upgrades antes do `SpawnController`, `ProductionController` por último, com o teto de produção do plano) e MULEs, sem gastar a reserva de scan nem usar o Orbital que escaneou; devolve o `SpawnMode` (com a composição inteira exatamente na proporção, o `SpawnController` roda em `freeflow` naquele frame). `detection`: scan com o Orbital pronto de mais energia; Engineering Bay e depois uma Missile Turret por vez, pelo `BuildStructure` do Ares na expansão mais próxima da base. `execute` devolve `BodyReport` (`spawn`, `micro`, `detection`). `structure_control`: abaixa e levanta os depots do plano. `combat` guarda o que `attack` e `core_army` compartilham: decisão de siege, `AMove` e a regra do Stim. |
| LOGS | [bot/logs/](../bot/logs/) | — | Log JSONL, snapshots SVG do campo e overlay in-game. Nenhum deles muda decisão nem derruba partida. |
| HARNESS | [harness/](../harness/), [bench.py](../bench.py) | `GameSpec`, `result.json` | Fora do bot. Matriz fixa de partidas contra a IA, cada uma num processo com timeout de relógio; `result.json` liga resultado (`victory`, `defeat`, `tie`, `timeout`, `crash`, `no_result`) a commit, SHA do Ares, árvore suja, fingerprint da configuração, mapa, oponente, seed, replay e JSONL. `summarize`/`compare` agregam com intervalo de Wilson. |

## Matemática

- Kernel `K(d, σ) = exp(-½·d²/σ²)` e saturação `S(x) = 1 - exp(-x)` ([field.py](../bot/awareness/field.py)).
- Poder de uma unidade: `sqrt(dps · (hp + shield))`, em Marines.
- Pressão na base: `Σ poder·confiança·K(d, σ_base + incerteza)` dos atacantes ao alcance
  físico (`base_reach + incerteza`); `threat = S(pressão / full_pressure)`.
- Ameaça lembrada por base: `recent_threat = max(threat, recent_threat anterior · exp(-Δt / threat_memory))`,
  τ = 20 s; a parte que decaiu é esquecida abaixo de `forget_below`, e uma base que some leva a memória.
  `danger` é o maior `recent_threat`, `danger_now` o maior `threat`, e `most_threatened` a base de maior
  `recent_threat`. Um ataque que rareia ou recua continua acreditado; um mais forte conta no mesmo frame.
- Exército inimigo, em Marines. Workers e estruturas não são exército.
  - `enemy_power` (conhecido): `Σ poder·confiança` dos contatos de exército, a parte que um contato ainda localiza.
  - `seen_enemy_power` (visto vivo): `Σ poder·exp(-idade / army_memory)` das unidades de exército vistas vivas e não
    vistas morrer, τ = 180 s; sai com a morte confirmada ou abaixo de `forget_below`, não quando a última posição
    volta à visão vazia. Como `army_memory ≥ unit_memory`, conhecido ≤ visto vivo.
  - `expected_enemy_power` (esperado sem avistamento): `min(army_cap, army_growth · max(0, t − army_onset))`,
    0,1 Marine/s a partir de 120 s, teto 100.
  - `estimated_enemy_power = max(conhecido, visto vivo, esperado)`, `enemy_uncertainty = estimado − conhecido`,
    `enemy_coverage = conhecido / estimado` (1 enquanto o estimado é 0).
- Campo por ponto do lattice:
  - `threat`: presença possível, σ alargado pela incerteza;
  - `enemy`: presença crível, sem alargamento;
  - `support`: nosso exército e estruturas;
  - `control = support - enemy`.
- Strategy: scores `STABILIZE = danger`, `BUILD_ADVANTAGE = 1 - danger`; troca só com
  vantagem ≥ `switch_margin` e `minimum_dwell` cumprido (STABILIZE pula a permanência
  com `danger ≥ emergency_danger`). Empate inicial é conservador.
- Preferências: inimigo planejado `= estimated_enemy_power + commit_margin · enemy_uncertainty` (margem 0,5);
  `army_share = own / (own + planejado)` (0,5 sem poder algum); `army = clamp(0,3 + 0,5·danger + 0,4·(0,5 − army_share))`,
  `economy = 1 − army`, `risk = army_share · (1 − danger)`. Com `danger = 0`, `economy ≥ 0,5` com qualquer `army_share`.
- Incidente: atacantes (poder > 0) ao alcance de alguma base, ligados em cadeia a
  ≤ `incident_link` (12) um do outro, quantas bases tocarem. O id segue os membros: cada grupo herda o
  id do incidente do frame anterior com quem mais compartilha membros (pares resolvidos por mais membros
  em comum, depois menor tag do grupo, depois menor tag que o incidente anterior tinha; cada id vai a um
  grupo só), quaisquer que sejam os contatos que entram ou saem. Numa divisão, fica com a parte que leva
  mais do incidente; numa fusão, com o incidente que traz mais membros. Um grupo sem herança é
  `incident:<menor tag>`, com sufixo `-1`, `-2`, … enquanto esse id estiver em uso. Poder `Σ poder·confiança` (terrestre e aéreo), centro ponderado
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
- Produção (teto): o `ProductionController` do Ares acrescenta estruturas de produção pela renda e pelo banco, até um
  teto por tipo (Barracks, Factory, Starport); `max_production = PRODUCTION_PER_BASE (4) · bases`. Com 3 bases é o
  padrão do Ares (12); com 6, 24. Dentro do teto, quem decide quantas construir continua sendo a regra de renda do Ares.
- Spawn (Body): o `SpawnController` do Ares pula um tipo com `contagem / total ≥ proporção` (contagem do
  Ares, com alias e unidades em produção). Com todos os tipos da composição atingidos ao mesmo tempo — contagens
  num múltiplo exato das proporções, como 11/4/3/2 para 0,55/0,20/0,15/0,10 — ele não treinaria nada; nesse
  frame roda em `freeflow` (`composition_met`). Senão segue o plano: `plan_freeflow`, `composition_short`, e
  `plan_inactive` no opening.
- Opening: com STABILIZE e `defense ≥ OPENING_ABORT_DANGER` (0,6, o nível de emergência da estratégia) antes do fim do
  opening, o plano econômico fica ativo (`opening_interrupted`, `interrupt_opening`) e o Body chama
  `build_order_runner.set_build_completed()`; o `MacroPlan` roda no mesmo frame, em `freeflow`.
- Produção (ordem): o `ProductionController` fica depois do `SpawnController` no `MacroPlan` e só roda num frame em que
  ele não agiu; registrado à parte, mandava Tech Labs em Barracks que o `SpawnController` acabara de mandar treinar
  (a última ordem vale).
- Detection: depois que um inimigo de exército foi visto camuflado ou enterrado (`cloak_seen_at`), cada Orbital guarda
  `scan_reserve` (50) de energia (MULE só com ≥ 100), cada base sem Missile Turret (pronta ou não) a ≤ `turret_cover` (15)
  pede uma, e sem Engineering Bay pede-se uma. Um contato escondido à vista com ≥ `scan_min_power` (2) do nosso exército
  a ≤ `scan_reach` (10) é escaneado se nenhum scan dos últimos `scan_duration` (12,3 s) o cobre (`scan_radius` 13) e
  algum Orbital pronto tem 50 de energia; entre vários, mais exército perto, depois mais poder escondido revelado,
  depois menor tag. Razões: `no_cloak_seen`, `no_hidden_enemy`, `hidden_enemy_scanned`, `no_army_near_hidden`,
  `no_scan_energy`, `scan_hidden_enemy`.
- Offense (uma transição por frame; `_TOLERANCE` conta o valor exato no limiar):
  - IDLE → ASSEMBLE sem STABILIZE, sem call-off há `cooldown` (30 s), com `own_power ≥ minimum_power` (20) e
    `army_share ≥ 0,5` (`army_advantage`) ou `supply_used ≥ maxed_supply` (190, `supply_maxed`).
  - Qualquer estágio comprometido → IDLE com STABILIZE (`home_threatened`) ou `own_power < depleted_share (0,5) ·
    comprometido` (`army_depleted`); ambos contam como call-off.
  - ASSEMBLE → ADVANCE com `assemble_share` (0,8) do poder a ≤ `assemble_radius` (12) do rally, ou `assemble_timeout` (45 s).
  - Grupo = unidades que o Engine deu à ofensiva no frame anterior. Núcleo = a unidade do grupo com mais poder do
    grupo a ≤ `engage_radius` (16) dela (menor tag no empate). Luta local: esse poder contra `Σ poder·confiança` dos
    contatos inimigos com poder, sem workers, a ≤ 16 + incerteza do núcleo; `share = próprio / (próprio + inimigo)`,
    nenhum com inimigo zero ou com `share ≥ won_share` (0,9, não é disputa).
  - ADVANCE/SEARCH → ENGAGE com `share ≥ engage_share` (0,5), → RETREAT abaixo. ENGAGE → RETREAT só com
    `share < retreat_share` (0,35) e `engage_dwell` (4 s) cumprido; → ADVANCE depois de `clear_after` (3 s) sem inimigo.
  - RETREAT (`RETREAT` ao rally) → REGROUP com o exército reunido ou `retreat_timeout` (30 s). REGROUP (sem proposta)
    espera `regroup_dwell` (10 s) e a reunião (até mais 45 s); então ADVANCE com vantagem ou supply máximo,
    recomprometendo com o poder atual, senão IDLE (`advantage_lost`, call-off).
  - Alvo: estrutura lembrada — townhall no chão, depois outra no chão, depois voando; mais próxima do rally, menor tag;
    mantida enquanto lembrada e sem tipo melhor. Voando: `must_attack = AIR`. Sem nenhuma: o start inimigo, ou,
    com ele visto nos últimos `search_memory` (60 s), ADVANCE → SEARCH (`enemy_start_empty`).
  - SEARCH: expansões e start inimigo, menos as nossas (≤ 6); primeiro as fora de visão há mais de 60 s, a mais
    próxima do grupo (ou do rally); depois a fora de visão há mais tempo; empate por posição; alvo mantido até entrar
    na visão. SEARCH → ADVANCE ao lembrar uma estrutura (`structure_found`).
  - Prioridade 0: Defense (> 0) passa na frente, CoreArmy (−1) fica com o resto.
- Economy (Orbital, MULE e upgrades): depois do opening, `orbitals` e `mules`; `upgrades = UPGRADES` (Stim, Combat
  Shield, Infantry Weapons 1, Concussive, Infantry Armor 1, W2, A2, Vehicle Weapons 1, W3, A3, VW2, VW3) fora de
  STABILIZE, senão nenhum. O `MacroPlan` do Ares para no primeiro behavior que age e o `SpawnController` age sempre
  que há produção ociosa, então `UpgradeCCs` vem antes de `BuildWorkers` e `UpgradeController` antes do
  `SpawnController`. Todo Orbital pronto com ≥ 50 de energia solta um MULE no campo mineral mais cheio a ≤ 10 de
  um townhall pronto (empate: menor tag).
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
| `attention.observed` | attention | bases, fim do opening ou inimigos à vista mudam; amostra a cada 5 s | `minerals`, `vespene`, `supply_used`, `supply_cap`, `workers`, `army_units`, `army_supply`, `army_power`, `visible_enemy_units`, `visible_enemy_structures`, `bases`, `opening`, `opening_done`, `upgrades[]`, `structures` {tipo: contagem, prontas ou não} |
| `awareness.updated` | awareness | mudança de contatos/poder/ameaça por base, contatos escondidos, primeiro camuflado, heartbeat | `contacts`, `visible_contacts`, `enemy_power`, `seen_enemy_power`, `expected_enemy_power`, `estimated_enemy_power`, `enemy_uncertainty`, `enemy_coverage`, `own_power`, `danger`, `danger_now`, `cloak_seen_at`, `hidden_contacts[]`, `bases[]` {`base_id`, `position`, `is_main`, `threat`, `recent_threat`, `pressure`, `cover`, `balance`, `air_share`, `center`}, `incidents[]` {`incident_id`, `contacts`, `center`, `power`, `ground_power`, `air_power`, `confidence`, `threat`, `pressure_by_base`} (escrito também quando os membros de um incidente mudam), `strongest_contacts[]` (com `hidden`), `field` {`samples`, `friendly`, `contested`, `enemy`, `threatened`, `max_threat`} |
| `strategy.decided` | strategy | troca de objetivo, heartbeat | `objective`, `previous`, `since`, `reason`, `defense`, `army`, `economy`, `risk`, `rally`, `inputs` {`danger`, `danger_now`, `army_share`, `own_power`, `enemy_power`, `estimated_enemy_power`, `enemy_uncertainty`, `planned_enemy_power`}, `scores` |
| `behavior.proposed` | behaviors | o conjunto ranqueado de propostas muda | `proposals[]` {`proposal_id`, `owner`, `priority`, `command`, `target`, `count`, `minimum_power`, `must_attack`, `demand_id`, `unit_types`, `reason`, `inputs`} |
| `behavior.offense_planned` | behaviors | estágio, `since`, bloqueio, alvo (tag ou grade de 3) mudam | `stage`, `previous`, `since`, `reason`, `blocked_by`, `committed_power`, `target`, `target_tag`, `target_kind` (`known_base`, `known_structure`, `flying_structure`, `enemy_start`, `search`), `inputs` {`own_power`, `army_share`, `supply_used`, `assembled_share`, `committed_power`, `stage_for`, `cooldown_left`, `known_structures`, `squad_units`, `squad_power`, `core_power`, `local_enemy_power`, `local_share` (−1 sem inimigo), `contested`, `clear_for`, `start_cleared`}, `fight` {`center`, `own_power`, `enemy_power`, `share`, `enemy_center`} ou null |
| `behavior.economy_planned` | behaviors | o plano muda | `active`, `workers`, `gas`, `bases`, `expand`, `freeflow`, `reason`, `composition[]`, `inputs` {`workers`, `bases`, `saturated_at`, `strategy_economy`, `upgrades_done`, `danger`, `production_per_base`}, `upgrades[]`, `orbitals`, `mules`, `interrupt_opening`, `max_production` |
| `behavior.spawn_executed` | behaviors | `freeflow` ou razão do spawn mudam | `freeflow`, `reason` (`plan_inactive`, `plan_freeflow`, `composition_met`, `composition_short`), `counts` {tipo: contagem do Ares} |
| `behavior.micro_executed` | behaviors | alguma unidade usou Stim (em `ATTACK` ou `HOLD`), ou os Medivacs que escoltam mudam | `stimmed[]`, `escorts[]` |
| `behavior.detection_planned` | behaviors | todo scan; turrets, Engineering Bay, reserva, razão ou construção pedida ao Ares mudam | `scan`, `turrets[]`, `engineering_bay`, `energy_reserve`, `reason`, `inputs` {`hidden_enemies`, `cloak_seen_at` (−1 antes), `army_near_hidden`, `orbitals_with_scan`, `active_scans`}, `scanned_by`, `building[]` |
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
.venv\Scripts\python.exe -m ruff check bot tests harness run.py bench.py
.venv\Scripts\python.exe bench.py run --out bench\<rótulo> --maps PersephoneAIE_v4 --races Zerg Terran Protoss --time-limit 1200
.venv\Scripts\python.exe bench.py summarize bench\<rótulo>
.venv\Scripts\python.exe bench.py compare bench\<base> bench\<desafiante>
```

## Fora desta fatia

Belief probabilístico de exército, forças agregadas, avaliação dinâmica de território, `RegionState` (nenhuma decisão o consome ainda),
scouting depois do early game, map control, harass, combat simulation do Ares na decisão de lutar (medida e revertida), path de grupo
consciente de risco, coesão/reforços da ofensiva (hoje toda unidade livre vai sozinha até o grupo), alcance de
estruturas voando sobre terreno impassável, stutter/focus/target scoring, Medivac evacuando, Raven e scan ofensivo/de informação, turret por rota aérea,
preempção com compromisso e ciclo de siege próprio da
defesa. No wall: antecipar o fechamento por contato lembrado ou pela rota, alcance pela velocidade do inimigo, distinguir
os depots do wall e política para unidades nossas empurradas ou presas do lado de fora. Na defesa: distinguir scout, worker rush e ataque; histerese de admissão/liberação; alcance por pathing em vez de
distância; eventos explícitos de linhagem de incidentes; `desired_power`, suitability e custos de assignment. Na economia:
bases por `ready + pending` explícito, CC voando, cooldown do alvo, supply antecipado além do que o `AutoSupply`
do Ares já faz (pending e produção), a causa do banco com supply livre, reação específica a
rush (bunker, worker pull, reparo) e o resto do `MacroPlan` do Ares que para no primeiro behavior que age (supply,
workers, gás e expansão ainda passam na frente do `SpawnController`). Na estratégia: rally alternando
entre bases de ameaça quase igual e reforços que ainda não foram vistos (o objetivo lê só `danger`, não a estimativa). No desconhecido: estimativa por produção ou economia vista, informação ampla que mostre
um exército menor que o esperado, scouting recorrente, calibração de `army_growth`/`army_cap` e renomear `risk`. Cada um entra quando um problema de gameplay medido pedir.
