# Arquitetura: camadas

No `on_start`, Attention lê o mapa físico uma vez (`read_map`). Depois, um frame atravessa
as camadas sempre na mesma ordem, em `play_frame` ([bot/main.py](../bot/main.py)):

```text
attention = observe(bot, iteration, map_view)                  ATTENTION
awareness = awareness_model.infer(attention)                    AWARENESS
strategy  = strategy_model.decide(attention, awareness)         EGO / strategy (política)
proposals = defense.plan(..., feedback)                         EGO / planners → missões
held      = map_control.plan(attention, awareness, strategy)    EGO / planner (sem missão)
proposals += held.proposals
offense   = offense.plan(..., held.anchor, feedback)            EGO / planner → missão
proposals += offense.proposals + intel.plan(attention, feedback)
missions  = defense.views() + offense.views() + intel.views()
economy   = economy.plan(attention, strategy, army, awareness.seen_enemy_types)
structures = structure_control.plan(attention)
detection = detection.plan(attention, awareness)
result    = engine.allocate(attention, proposals)               BODY / engine
feedback  = result                                              (lido no próximo frame)
body      = behaviors.execute(bot, attention, result,           BODY / behaviors
                              economy, structures, detection)
logs.record(bot, attention, awareness, strategy, held, offense, ...,  LOGS
            body.spawn, body.micro, detection, body.detection, missions)
```

Regra: **a Strategy decide o que é permitido e o que tem precedência, o Planner decide quais
operações do seu domínio existem, a Mission decide como a operação avança, o Engine decide QUEM
recebe cada proposta, o Behavior decide COMO.** Detalhes em [Missões](#missões).

Só `read_map`/`observe`, `behaviors.execute` e os observadores de `logs` tocam o bot.
Todo o resto lê estados imutáveis e é testável sem `AresBot`.

## Camadas

| Camada | Arquivo | Estado público | O que faz |
| --- | --- | --- | --- |
| ATTENTION | [bot/attention/](../bot/attention/) | `MapView`, `AttentionState` | Percepção. `map.py`/`topology.py`: no `on_start`, `read_map` congela lattice, expansões e `MapTopology` (regiões, passagens/chokes, adjacência, regiões dos starts) — "o mapa físico é assim". `frame.py`: `observe` lê o frame (recursos, workers pela contagem do jogo, unidades próprias e inimigas visíveis neste frame ordenadas por tag — sem os snapshots de até 30 s que o Ares mistura em `enemy_units` para inimigos fora de visão, porque lembrar é papel da Awareness —, bases, mortes, visibilidade, upgrades concluídos; por unidade, energia e se está camuflada/enterrada e se nada a detecta) e classifica unidades (`is_army`). Não interpreta valor, ameaça ou controle. |
| AWARENESS | [bot/awareness/](../bot/awareness/) | `AwarenessState` | Pinta o mapa ao longo da partida. Memória de contatos com confiança `exp(-idade/τ)` e incerteza `min(cap, v·idade)`; esquece por morte confirmada, posição vista vazia (após carência) ou confiança < piso. Pressão por base com a ameaça lembrada (`recent_threat`, τ = `threat_memory`), incidentes de ameaça (`ThreatIncident`), estimativa do exército inimigo (conhecido, visto vivo, esperado sem avistamento, incerteza e cobertura), contatos escondidos (camuflados sem detecção, à vista) e quando um exército camuflado foi visto pela primeira vez, e campo de influência. Descreve; não escolhe margem nem prioridade. |
| EGO / strategy | [bot/ego/strategy.py](../bot/ego/strategy.py) | `StrategyState`, `DomainPolicy` | `STABILIZE` vs `BUILD_ADVANTAGE` com margem, permanência mínima e emergência; preferências contínuas `defense`, `army`, `economy`, `risk`, com o inimigo planejado como estimativa mais `commit_margin` da incerteza; a política da ofensiva (`offense`: `PURSUE` ou `WITHDRAW`, com a razão). Não conhece missão nenhuma nem escolhe lugar no mapa. |
| EGO / missions | [bot/ego/missions/](../bot/ego/missions/) | `MissionStatus`, `CancelMode`, `Lifecycle`, `MissionFeedback`, `MissionView` | O que todas as missões compartilham: `lifecycle` (status terminal, pedido de cancelamento e modos) e `contracts` (o feedback que a missão lê e o resumo que ela reporta). Nenhuma missão concreta mora aqui. |
| EGO / planners | [bot/ego/planners/](../bot/ego/planners/) | `Proposal`, `Command`, `EconomyPlan`, `StructurePlan`, `DetectionPlan` | Decidem o que deve ser feito (tarefa, alvo, prioridade, requisitos) sem nomear unidades, em três grupos: `military/` pede unidades ao Engine, `economy/` diz o que comprar, `control/` diz qual estrutura ou habilidade age. `military/defense/`: o `DefensePlanner` abre uma `DefendAreaMission` por incidente, que pede `ATTACK` com um orçamento de poder repartido entre a parte aérea e a terrestre. `military/offense/`: `OffensePlanner` (`planner.py`) abre e encerra a `MainAttackMission` (`missions/main_attack.py`) (ASSEMBLE → ADVANCE ⇄ SEARCH, ENGAGE/RETREAT → REGROUP, e WITHDRAW só num cancelamento gracioso); `ATTACK` no alvo ou `RETREAT` ao rally (o anchor do MapControl, que o frame lhe passa), com todas as unidades livres, lendo a concessão anterior da missão. `military/map_control/`: `MapControlPlanner` (`planner.py`) escolhe o anchor — a base ameaçada em STABILIZE, senão o ponto de reação que melhor responde a todas as nossas bases, na frente delas, num choke que as guarda e longe da influência inimiga (`staging.py`, com a passagem única de antes, `anchor.py`, em shadow), senão a heurística antiga do rally — e pede `HOLD` nele com todas as unidades livres, sem missão (a proposta mantém o id `core_army`, nome anterior, por compatibilidade com logs, viewer e benches). `military/intel/`: `IntelPlanner` (`planner.py`) abre uma `ScoutMission` (`missions/scout.py`), `SCOUT` de um SCV pela main inimiga no early game. `economy/` (`planner.py` junta um módulo por pergunta): `investment` diz quanto investir (workers, bases, gás, teto de produção, quando o plano assume do opening ou o interrompe numa emergência); `styles` diz qual exército (o estilo sorteado na partida: abertura, composição, upgrades e onde vão os Reactors); `composition` diz o que construir agora (a composição do estilo repesada pela matriz de counters contra o exército inimigo acreditado); `planner.plan` junta tudo num `EconomyPlan` para os macro behaviors do Ares (inclusive upgrades, Orbital e MULE). `control/detection`: onde escanear, quais bases precisam de Missile Turret, Engineering Bay e a energia que cada Orbital guarda. `control/structure_control`: quais depots levantar e quais abaixar. |
| BODY / engine | [bot/body/engine.py](../bot/body/engine.py) | `EngineResult` | Só alocação. Ordena por `(-priority, owner, proposal_id)` e concede cada unidade de exército a no máximo uma proposta. Restrições duras vêm antes de qualquer ordem: `unit_types`, `must_attack` (`GROUND`/`AIR`) e, num pedido de poder, `power > 0`. Entre as elegíveis livres, as que já eram da proposta primeiro, depois as mais próximas. Pede-se `minimum_power` (unidades até atingir o poder), `count` ou todas as livres; cada `Grant` traz `power`, `status` (`FULL`/`PARTIAL`/`REJECTED`) e `reason`. Um pedido de todas as livres que não recebe nenhuma fica `REJECTED` (`eligible_units_taken`/`no_eligible_units`). Workers só são elegíveis para propostas que pedem um tipo de worker, só saindo da mineração (role `GATHERING`) ou já sendo da proposta. `released` lista quem perdeu o dono. O `EngineResult` é o feedback que as missões leem no frame seguinte, sem nomear unidades; o Engine é o único registro de posse e nunca lê nem muda o lifecycle de uma missão. Não comanda nada. |
| BODY / behaviors | [bot/body/behaviors/](../bot/body/behaviors/) | — | Executam os grants, despachados por `Command`. `attack` (`ATTACK`, de Defense ou da ofensiva): `AMove`, Siege Tank decide o siege sem ficar preso ao ponto; Marine/Marauder usam Stim com inimigo a ≤ 10 e ≥ 50 % de vida; Medivac vai ao centro do próprio grupo. `retreat` (`RETREAT`): path ao ponto sem lutar, Siege Tank sai do siege. `hold` (`HOLD`): `PathUnitToTarget` até o ponto, `AMove` com inimigo a ≤ 10 (bio usa Stim pela mesma regra do `attack`), Siege Tank fica sieged perto do ponto. `scout` (`SCOUT`): tira o worker da mineral, role `SCOUTING`, path sem evitar perigo. `economy`: para o build runner do Ares quando o plano interrompe o opening; workers liberados voltam a `GATHERING`, `Mining`, um add-on por frame antes do `MacroPlan` (Reactor ou Tech Lab na estrutura `addons_on`, pelo `reactor_share`), `MacroPlan` (Orbital antes de `BuildWorkers`, pesquisa — `ExactResearch` e `UpgradeController` — antes do `SpawnController`, depois `ProductionController`, nesta ordem, com o teto de produção do plano) e MULEs, sem gastar a reserva de scan nem usar o Orbital que escaneou; devolve o `SpawnMode` (com a composição inteira exatamente na proporção, o `SpawnController` roda em `freeflow` naquele frame). `detection`: scan com o Orbital pronto de mais energia; Engineering Bay e depois uma Missile Turret por vez, pelo `BuildStructure` do Ares na expansão mais próxima da base. `execute` devolve `BodyReport` (`spawn`, `micro`, `detection`). `structure_control`: abaixa e levanta os depots do plano. `combat` guarda o que `attack` e `hold` compartilham: decisão de siege, `AMove` e a regra do Stim. O Siege Tank decide o siege também contra os inimigos que o Ares lembra fora de visão; o Stim e a saída do path no HOLD só contam inimigos à vista neste frame. |
| LOGS | [bot/logs/](../bot/logs/) | — | Log JSONL, snapshots SVG do campo e overlay in-game. Nenhum deles muda decisão nem derruba partida. |
| HARNESS | [harness/](../harness/), [bench.py](../bench.py) | `GameSpec`, `result.json` | Fora do bot. Matriz fixa de partidas contra a IA (mapa × raça × dificuldade × build da IA × estilo do bot, `--armies`; sem `--armies` o bot sorteia e o `game_id` não leva sufixo), cada uma num processo com timeout de relógio; `result.json` liga resultado (`victory`, `defeat`, `tie`, `timeout`, `crash`, `no_result`, `not_played`) a commit, SHA do Ares, árvore suja, fingerprint da configuração, mapa, oponente, seed, replay e JSONL. Uma partida que reportou resultado com o relógio do bot em 0 é `not_played` (o python-sc2 resigna no primeiro passo quando o `on_start` levanta): conta em `games`, não em `played`, fica fora da taxa de vitória e da duração média, e `run` a joga de novo em vez de pular. `summarize` recalcula o desfecho do que cada registro guardou, então execuções antigas são resumidas pela regra atual; `compare` agrega com intervalo de Wilson. O fingerprint cobre só as configs de `Layers.configs()` (awareness, strategy, map_control, offense, structure_control, detection, army — o estilo inteiro, com composição e upgrades); as constantes de módulo da economia (`PRODUCTION_PER_BASE`, `GAS_WORKER_SHARE`, `MAX_WORKERS`, `COUNTERS`, `PRIOR_POWER`) e do poder (`SPLASH_TARGETS`) ficam de fora, então dois benches com o mesmo fingerprint podem ter economias diferentes: compare pelo commit. |

## Matemática

- Kernel `K(d, σ) = exp(-½·d²/σ²)` e saturação `S(x) = 1 - exp(-x)` ([field.py](../bot/awareness/field.py)).
- Poder de uma unidade: `sqrt(dps · alvos · (hp + shield))`, em Marines. `alvos` é quantos alvos um tiro cobre,
  em equivalentes de dano cheio, contra um grupo aglomerado como a nossa bola de bio (`SPLASH_TARGETS`, ≥ 1;
  Siege Tank em siege 2,5, Baneling 3,0, Widow Mine enterrada / Hellbat / Colossus / Lurker enterrado 2,5,
  Liberator em modo terrestre / Hellion / Archon 2,0, Mutalisk 1,5). Splash multiplica o dano que a unidade **causa**,
  dentro da raiz: um tanque em siege com a vida cheia vale 4,3 Marines em vez de 2,7. Só armas automáticas
  entram — o `ground_dps`/`air_dps` não enxerga feitiço.
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
- Defense: uma `DefendAreaMission` por incidente (`defense:defend_area:N`; aberta quando a Awareness
  reporta o incidente, `COMPLETED` com `incident_over` quando deixa de reportar; um `incident_id` que volta
  depois é uma missão nova), `orçamento = 1.5 · poder`, repartido em `defense:<incidente>:air`
  (`minimum_power = 1.5 · poder aéreo`, `must_attack = AIR`) e `…:ground` (idem, terrestre); as
  partes somam o orçamento e compartilham `demand_id`. `priority = threat · (0.5 + 0.5·strategy.defense)`
  (> 0 exatamente enquanto há atacante ao alcance, logo acima do MapControl, que é −1); no empate a
  parte aérea vem antes (id). A cobertura já no local é usada porque o Engine concede as unidades
  compatíveis mais próximas primeiro; uma incompatível não conta.
- Intel: com `workers ≥ 16` e antes de 240 s, o `IntelPlanner` abre uma `ScoutMission`
  (`intel:scout:N`), que pede um SCV (`REQUESTING`) e passa a `LAPPING` quando ele sai. Rota: start
  inimigo, depois o sample mais distante da região da main em cada um de 8 setores angulares,
  anti-horário a partir da direção do nosso start. Um waypoint conta como visto na primeira vez em
  visão, com ou sem scout na rua (a rota e essa memória são do planner, desde o primeiro frame);
  `priority = waypoints não vistos / total`. A missão termina `COMPLETED` com a rota vista e
  `FAILED` com o scout morto (`scout_lost`) ou 90 s depois de sair (`lap_timed_out`); o SCV volta
  para a mineração. Antes de o scout sair, o planner pede o cancelamento imediato em 240 s
  (`too_late`) ou se os workers caem abaixo de 16 (`workers_below_threshold`, a única razão que
  deixa abrir outra missão depois). Um scout que saiu nunca é reposto.
- Economy (depois do opening): `workers` é `supply_workers`, a contagem do jogo — inclui SCVs
  dentro de refinarias, que somem de `bot.units` enquanto estão lá, e exclui os em produção.
  `bases = max(1, townhalls no chão)`; satura com `workers ≥ saturated_at = min(MAX_WORKERS (80), 16·bases)` —
  a força de trabalho que o próprio plano pede, não uma que ele nunca constrói — e expande saturado com
  `strategy.economy ≥ 0,5` e lugar no mapa (`bases < len(map.expansions)`, constraint discreta antes do score).
  Razões: `mineral_lines_saturated`, `worker_cap_reached` (saturado pelo teto de workers, não pelas linhas) e
  `no_expansion_left`. `gas = min(2·bases, int(workers·GAS_WORKER_SHARE (0,4)) // 3)`: os geysers das bases,
  limitado pela parcela da força de trabalho que pode estar no gás, a 3 workers por Refinery.
- Estilo de exército: no `on_start` o bot sorteia um estilo entre os feitos para a raça inimiga (`styles.candidates`;
  bio contra todas, mech só contra Zerg), ou usa o que `--army` fixou, troca a abertura do Ares por
  `build_order_runner.switch_opening(estilo.opening)` e anuncia no chat ("Hoje vai de MECH: Hellion, Cyclone e
  Siege Tank."). O estilo é dado, não código: abertura, composição (o prior), upgrades em ordem, `addons_on` (a
  estrutura de produção que recebe add-ons) e `against` (as raças contra quem é sorteado). Entra no fingerprint (`configs.army`).
- Composição: `value(u) = (Σ_e poder(e)·alcance(u,e)·COUNTERS[u][e] + PRIOR_POWER) / (Σ_e poder(e) + PRIOR_POWER)`,
  `share(u) ∝ prior(u)·value(u)`. `poder(e)` é `seen_enemy_types` da Awareness (o poder visto vivo por tipo, τ = 180 s);
  `alcance` é física (0 se `u` não atira onde `e` está: `REACH` nosso, `flying` do `UNIT_DATA` do Ares); `COUNTERS`
  é a troca por custo, 1 = par; `PRIOR_POWER` = 20 Marines. Sem limiar: a mistura desliza com a crença. Unidade que
  não atira (Medivac) fica no prior.
- Add-ons: `addons` liga depois do opening e fora de STABILIZE (como os upgrades). Antes do `MacroPlan`, fora dele, uma
  por frame: a estrutura `addons_on` do estilo (Barracks na bio, Factory no mech) pronta, ociosa e sem add-on de menor tag
  recebe Reactor enquanto `reactors + 1 ≤ reactor_share · n`, e Tech Lab senão; `reactor_share = s_r / (s_r + 2·s_t)`, com `s_t` a
  parcela da mistura que exige Tech Lab (requisitos do Ares). O `SpawnController` ignora essa estrutura no frame
  (`ignored_build_from_tags`), senão a ordem de treino substituiria a do add-on. Dentro do `MacroPlan`, depois do
  `SpawnController`, os add-ons quase nunca rodavam: `ci-mech/000` (`d784503`) tinha 9 de 13 Factories sem add-on aos 502 s.
- Pesquisa: `ExactResearch` roda antes do `UpgradeController` do Ares e só age num upgrade cuja habilidade no
  `game_data` difere da tabela `RESEARCH_INFO` do python-sc2 (o plating de veículo e nave): manda a habilidade da tabela.
  Sem isso o `UpgradeController` "pesquisava" o plating todo frame, o jogo recusava, e o `MacroPlan` parava nele — o
  mech de `bench/smoke-mech` ficou com 12 unidades e 3.000 minerais no banco aos 490 s.
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
  `build_order_runner.set_build_completed()`; o `MacroPlan` roda no mesmo frame, em `freeflow`. Também com `minerals ≥ OPENING_STALL_BANK` (1.000) antes do fim do opening (`opening_stalled`): nenhuma abertura que andou passou de 680 (17 jogos), e o runner do Ares parou num passo de gás da abertura mech em `ci-mech/003` e `004` (banco de 9.415 e 2.125).
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
- Offense (uma transição por frame; `_TOLERANCE` conta o valor exato no limiar). IDLE é do planner e
  derivado: nenhuma missão aberta. As outras etapas são as fases da `MainAttackMission`.
  - IDLE → ASSEMBLE (o planner abre `offense:main_attack:N`) com a política da ofensiva em `PURSUE`
    (senão `blocked_by = home_threatened`), sem missão encerrada há `cooldown` (30 s), com
    `own_power ≥ minimum_power` (20) e `army_share ≥ 0,5` (`army_advantage`) ou `supply_used ≥ maxed_supply`
    (190, `supply_maxed`).
  - Com a política em `WITHDRAW` (STABILIZE), o planner pede o cancelamento **imediato** e a missão termina
    `CANCELLED` (`home_threatened`) no mesmo frame. A própria missão termina `FAILED` com `own_power <
    depleted_share (0,5) · comprometido` (`army_depleted`). Todo encerramento conta como call-off e inicia o cooldown.
  - ASSEMBLE → ADVANCE com `assemble_share` (0,8) do poder a ≤ `assemble_radius` (12) do rally, ou `assemble_timeout` (45 s).
  - Grupo = unidades que o Engine deu à ofensiva no frame anterior. Núcleo = a unidade do grupo com mais poder do
    grupo a ≤ `engage_radius` (16) dela (menor tag no empate). Luta local: esse poder contra `Σ poder·confiança` dos
    contatos inimigos com poder, sem workers, a ≤ 16 + incerteza de **alguma unidade do grupo do núcleo** — as
    mesmas que formam o `own_power`, de modo que os dois lados descrevem o mesmo corpo de unidades (um inimigo
    que alcança a frente do grupo entra na conta mesmo com o núcleo atrás); `share = próprio / (próprio + inimigo)`,
    nenhum com inimigo zero ou com `share ≥ won_share` (0,9, não é disputa).
  - ADVANCE/SEARCH → ENGAGE com `share ≥ engage_share` (0,5), → RETREAT abaixo. ENGAGE → RETREAT só com
    `share < retreat_share` (0,35) e `engage_dwell` (4 s) cumprido; → ADVANCE depois de `clear_after` (3 s) sem inimigo.
  - RETREAT (`RETREAT` ao rally) → REGROUP com o exército reunido ou `retreat_timeout` (30 s). REGROUP (sem proposta)
    espera `regroup_dwell` (10 s) e a reunião (até mais 45 s); então ADVANCE com vantagem ou supply máximo,
    recomprometendo com o poder atual, senão a missão termina `FAILED` (`advantage_lost`, call-off).
  - WITHDRAW (só depois de um pedido de cancelamento gracioso com unidades na mão): `RETREAT` ao rally
    (`withdraw_to_rally`) até o exército reunido (`withdrawn`) ou `retreat_timeout` (`withdraw_timed_out`);
    então `CANCELLED`. Em ASSEMBLE ou REGROUP a missão não segura unidades, e o pedido gracioso encerra na hora.
  - Alvo: estrutura lembrada — townhall no chão, depois outra no chão, depois voando; mais próxima do rally, menor tag;
    mantida enquanto lembrada e sem tipo melhor. Voando: `must_attack = AIR`. Sem nenhuma: o start inimigo, ou,
    com ele visto nos últimos `search_memory` (60 s), ADVANCE → SEARCH (`enemy_start_empty`).
  - SEARCH: expansões e start inimigo, menos as nossas (≤ 6); primeiro as fora de visão há mais de 60 s, a mais
    próxima do grupo (ou do rally); depois a fora de visão há mais tempo; empate por posição; alvo mantido até entrar
    na visão. SEARCH → ADVANCE ao lembrar uma estrutura (`structure_found`).
  - Prioridade 0: Defense (> 0) passa na frente, MapControl (−1) fica com o resto.
  - O rally é o anchor do MapControl no frame: o `main.py` passa `held.anchor` ao `OffensePlanner.plan`; nenhum
    planner importa ou chama o outro.
- MapControl: dono residual (−1) de toda unidade de exército livre, `HOLD` no anchor — a posição de reação e
  staging do exército não comprometido, que o frame também passa à ofensiva como rally. Primeiro que vale:
  - `threatened_base`: em STABILIZE com base ameaçada, a mais ameaçada (a heurística antiga).
  - a política de `policy` (padrão `staging`); as duas são avaliadas todo frame e a que não controla vai ao log
    ao lado do anchor (shadow, temporário, para comparar):
    - `staging` ([staging.py](../bot/ego/planners/military/map_control/staging.py)): candidatos são os pontos do
      lattice das regiões com base nossa e das vizinhas, menos a região do start inimigo e as vizinhas dela (a
      menos que uma base nossa esteja lá). O hold point de cada passagem que guarda alguma base é um deles,
      marcado com a passagem. Distâncias por terra sobre a própria `MapTopology`: reta dentro da região, senão
      pelas passagens, passagem a passagem (todos os pares, uma vez por mapa; nenhum grafo novo). D = distância
      entre os starts, E = start inimigo. `score = −reaction + choke − exposure`:
      - `reaction = sqrt(média_b (r_b / D)²)` sobre as nossas bases, com `r_b = d(p, b) − advance ·
        max(0, d(E, b) − d(E, p))`: a distância à base, encurtada pelo quanto o ponto está à frente dela no
        caminho do inimigo (o inimigo que vem para b encontra o exército antes). Atrás de uma base, a resposta
        é só a distância. O RMS fica entre a média (que abandona uma base externa) e o pior caso (que arrasta
        o exército até ela). `advance` é a postura: 0,7 em BUILD_ADVANTAGE, 0 em STABILIZE (só cobertura).
      - `choke = choke_weight (0,15) · guarded · exp(−largura / 6)` no hold point de uma passagem; `guarded` é a
        fração das nossas bases que o start inimigo deixa de alcançar com ela fechada. `border` não ganha.
      - `exposure = threat_weight (0,3) · threat · (1 − support) + control_weight (0,2) · max(0, −control)`, o
        `InfluenceField` da Awareness no ponto: ameaça que não contestamos e estar do lado inimigo do campo.
        `support` sozinho não pontua (no anchor ele é o próprio exército do anchor, e premiá-lo prenderia o
        exército onde já está); o campo é saturado e só ordena lugares, não mede luta.
      Histerese: uma base tomada ou perdida, ou a troca de objetivo, escolhe de novo; fora isso o ponto mantido
      só troca quando outro o supera por `staging_margin` (0,04 de D). Toda troca diz o motivo (`initial`,
      `held_invalid`, `bases_changed`, `posture_changed`, `awareness`). As distâncias são calculadas uma vez
      por conjunto de bases (2–4 ms num mapa real); o campo é lido todo frame (numpy, sobre ~300–700 pontos).
    - `passage` ([anchor.py](../bot/ego/planners/military/map_control/anchor.py)), a política anterior: as
      passagens que **separam** — fechando-a, alguma base nossa que o start inimigo alcança hoje deixa de ser
      alcançável (BFS na `adjacency`). `score = protected + quality − overextension`: `protected = base_value
      (1) · bases separadas`; `quality = 0,25 · exp(−largura/6)`; `overextension = Σ base_value · (1 −
      exp(−d/L))`, `L = reach_share (0,5) · distância entre starts`. Troca com `switch_margin` (0,25). Anchor:
      `setback` (4) da passagem para o centro da região do nosso lado, no ponto do lattice mais próximo.
  - `legacy`: a frente da base mais avançada, `rally_forward` (6) para o start inimigo, ou a rampa da main só com
    a main — quando a política não põe anchor: `no_candidates` (nenhuma base localizada ou nenhum ponto do
    lattice nas regiões) ou `no_enemy_route` (sem região do start inimigo, ou sem caminho até ele) no `staging`;
    `no_separating_passage` ou `anchor_unresolved` no `passage`.
  - Nos 5 mapas do pool (topologias reais, bases na ordem de distância ao nosso start): 1 base → rampa da main;
    2 bases → choke da natural (Torches, que não tem, fica na rampa); da 3ª base em diante o anchor sai do choke
    da natural e avança aos poucos, um hub por vez, para a frente do centro das bases; com 7 bases fica entre
    0,43 (Pylon) e 0,63 (Ley Lines) de D do start inimigo. A política `passage` ficava no choke da natural até a
    7ª base, e aí saltava para uma passagem perto do inimigo.
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

## Missões

Dentro do Ego, três papéis, cada um com uma pergunta:

| Papel | Onde | Decide | Não decide |
| --- | --- | --- | --- |
| Strategy | [strategy.py](../bot/ego/strategy.py) | A política global: o que cada domínio pode fazer e o que tem precedência. Hoje, `StrategyState.offense`: `PURSUE` fora de STABILIZE, `WITHDRAW` (`home_threatened`) em STABILIZE. | Qual missão existe, qual termina e como. Não conhece `mission_id` nem chama `cancel`. |
| Planner | `military/{offense,defense,intel}/planner.py` | Quais missões abrir, manter ou pedir para encerrar, interpretando a política e o próprio domínio; o modo do pedido (imediato ou gracioso). Guarda só a memória que sobrevive a uma operação: cooldown, lugares vistos, rota do scout, contadores de id. | Tags de unidades, comandos ao jogo, a fase de uma operação. |
| Mission | `military/offense/missions/main_attack.py`, `military/defense/missions/defend_area.py`, `military/intel/missions/scout.py`; o que todas compartilham em `bot/ego/missions/` | Identidade, fase e memória de uma operação; progride lendo observação e feedback; emite propostas; conclui (`COMPLETED`), falha (`FAILED`) ou, depois de um pedido, cancela (`CANCELLED`). | Posse de unidades, registro de behaviors, política global. |

**Onde fica cada coisa.** O Ego separa a coordenação global, a infraestrutura comum das missões e os
planners, e os planners se agrupam pelo que pedem:

```text
bot/ego/
  strategy.py                       coordenação global: objetivo, preferências, política por domínio
  missions/                         o que todas as missões compartilham
    lifecycle.py                    MissionStatus, CancelMode, CancelRequest, Lifecycle
    contracts.py                    MissionFeedback, MissionView
  planners/
    __init__.py                     contratos com o Body: Proposal, Command, Domain, os planos
    military/                       pedem unidades ao Engine
      offense/
        planner.py                  OffensePlanner
        missions/main_attack.py     MainAttackMission
      defense/
        planner.py                  DefensePlanner
        missions/defend_area.py     DefendAreaMission (uma por incidente)
      intel/
        planner.py                  IntelPlanner
        missions/scout.py           ScoutMission
      map_control/
        planner.py                  MapControlPlanner: o que ninguém pediu, no anchor; sem missão
        staging.py                  onde o exército livre reage: candidatos, distâncias por terra, score
        anchor.py                   a política anterior (uma passagem), mantida em shadow para comparar
    economy/                        o que comprar
      planner.py, investment.py, styles.py, composition.py
    control/                        qual estrutura ou habilidade age; sem missões
      detection.py, structure_control.py

bot/body/behaviors/
  attack.py    ATTACK        hold.py      HOLD
  retreat.py   RETREAT       scout.py     SCOUT
  combat.py    o que attack e hold compartilham
  economy.py, detection.py, structure_control.py  planos de recurso
```

`bot/ego/missions/` é a infraestrutura comum; `planners/<grupo>/<domínio>/missions/` são as missões concretas
daquele domínio. Cada pasta de planner tem `planner.py`, e o `__init__.py` só reexporta os nomes públicos
(`from bot.ego.planners.military.offense import OffensePlanner`). Um planner de `control/` ou de
`economy/` que crescer vira pasta do mesmo jeito. No Body, cada behavior tem o nome do `Command` que
executa.

Um tipo de missão novo entra como um módulo em `missions/` do planner que o governa, e um comando novo
como um behavior com o nome dele. O próximo previsto é `military/harass/` (N7.3 em
[novas_propostas.md](novas_propostas.md)): `harass/planner.py` com `missions/drop.py` e
`missions/banshee_raid.py`, e os behaviors `move.py`, `load.py` e `unload.py` para os comandos que o drop
pedir. Nenhum deles existe ainda: entram com o gameplay, gatilho e teste próprios.

No Body, o Engine continua a única autoridade de posse (concede, concede em parte, rejeita, transfere) e
nunca lê nem muda o lifecycle de uma missão; o Behavior executa só as unidades concedidas no frame.

**Mission e Proposal.** A missão persiste; a proposta é a demanda de um frame. Uma missão emite zero, uma
ou várias propostas (o contrato aceita várias: um drop pediria transporte e carga), cada uma com
`mission_id`. Três identidades distintas: o planner (`owner`: `offense`, `defense`, `intel`), a missão
(`mission_id`: `offense:main_attack:N`, `defense:defend_area:N`, `intel:scout:N`, um número por operação para
separar as sucessivas nos logs) e a
proposta (`proposal_id`). A proposta da ofensiva guarda o id `offense` em todas as fases e em todas as
missões, a do scout guarda `intel` e as da defesa seguem o incidente (`defense:<incidente>:air`/`ground`),
porque o Engine prefere manter as unidades de quem já as tinha pelo `proposal_id`. `demand_id` continua outra
coisa: agrupa as partes aérea e terrestre de uma `DefendAreaMission`, que é quem as emite.

**Lifecycle.** Status pequeno e comum (`ACTIVE`, `COMPLETED`, `FAILED`, `CANCELLED`); as fases são de cada
operação (ASSEMBLE … WITHDRAW; DEFENDING; REQUESTING, LAPPING). Um pedido de cancelamento não é um cancelamento:
`request_cancel(modo, razão)` guarda o pedido, e é a missão, no seu passo, que chega a `CANCELLED`. Um pedido
imediato escala um gracioso, nunca o contrário; uma missão terminal não aceita pedido e não emite proposta.

- **Imediato:** a missão termina no mesmo passo, sem propostas; as unidades que tinha estão livres na
  alocação desse frame.
- **Gracioso:** a missão continua emitindo a retirada (`WITHDRAW`, `RETREAT` ao rally) até a sua condição de
  liberação (exército reunido) ou o prazo (`retreat_timeout`), e só então fica `CANCELLED`. A retirada não
  garante posse: uma proposta de prioridade maior (Defense) ainda toma unidades, e a missão segue com as que
  receber, inclusive nenhuma, até a liberação ou o prazo. Uma missão sem unidades na mão (ASSEMBLE, REGROUP,
  um scout que não saiu) encerra na hora.

**Feedback.** O `EngineResult` de um frame fica em `Layers.feedback` e é lido no frame seguinte:
`MissionFeedback.of(result, mission_id)` junta as `Grant` das propostas da missão (tags, poder, `status`,
`reason`). As tags são feedback, não posse. O fluxo é determinístico e sem ciclos:
observação atual + feedback anterior → Strategy → planners/missões → propostas → Engine → behaviors → feedback
do próximo frame. Nada é replanejado nem realocado duas vezes no mesmo frame.

**Liberação de unidades.** Quando uma missão para de emitir uma proposta (terminal, ou numa fase sem
proposta), o Engine deixa de conceder aquelas unidades na mesma alocação: vão para quem as pede (Defense,
MapControl), e um worker liberado volta à mineração (`released`). Não existe liberação pela missão: ela só
deixa de pedir.

**Resumo para quem está acima.** `planner.views()` devolve um `MissionView` imutável por missão governada no
frame (também a que acabou de terminar), com o que a alocação anterior lhe deu. Vai para o log
(`behavior.missions_updated`) e para `Frame.missions`; a Strategy pode recebê-lo quando precisar, mas hoje
nenhuma decisão dela depende disso, então não recebe.

**Quem usa missões.**

- **Offense:** misturava a decisão de compromisso com a máquina de estados da operação. O `OffensePlanner`
  ficou com admissão, cooldown, a memória de lugares vistos (que a busca de qualquer ataque lê) e o pedido
  de cancelamento; a `MainAttackMission` com montagem, avanço, combate, busca, retirada e reagrupamento.
  IDLE é derivado da ausência de missão, não uma segunda máquina de estados.
- **Intel:** abrir, reabrir ou encerrar antes da saída é do planner; a rota concreta e o scout, da missão.
- **Defense:** uma `DefendAreaMission` por incidente, com o `incident_id` da Awareness ligando a missão ao
  incidente enquanto os atacantes entram e saem. A missão é redimensionada a cada frame pelo incidente, tem
  uma fase só (`DEFENDING`) e termina quando o incidente some; o que ela acrescenta é identidade e
  lifecycle nos logs. O planner nunca pede para encerrar uma. As propostas (ids, `demand_id`, orçamento,
  prioridade) são as de antes.
- **MapControl** (era ArmyFallback, antes CoreArmy): sem missão; guarda o ponto mantido de cada política e o
  cache das candidatas. Não é uma reserva estratégica: recebe o que os planners acima deixaram, e escolhe onde
  ficam. Quando a Defense toma parte das unidades num incidente, o resto continua no anchor e as que ela solta
  voltam a ser dele; quando a ofensiva toma o exército, as unidades novas se juntam no anchor.
- **Economy, Detection, StructureControl:** planos de recurso, não pedem unidades ao Engine; mantêm seus
  contratos.

**Orçamentos.** Não há orçamento de poder por domínio nesta versão: a precedência entre domínios é a
prioridade das propostas (Defense > 0, ofensiva 0, MapControl −1) e a política da Strategy. Se um orçamento
vier, ele precisa separar a meta desejada, o limite de admissão de novas operações, as unidades ainda
comprometidas numa retirada e a precedência para preempção: uma meta reduzida a zero pode coexistir com
uma operação em WITHDRAW.

**Diferença de gameplay.** Nenhuma nos gatilhos existentes. A Strategy em `WITHDRAW` leva o planner a pedir
o cancelamento **imediato**, como o call-off de antes (Defense precisa das unidades já, e o MapControl as segura
na base ameaçada, que é o anchor em STABILIZE). O cancelamento gracioso (fase WITHDRAW) existe no contrato e
na `MainAttackMission`, testado, mas nenhum gatilho de produção o usa. Verificado fora da suíte, rodando o
Offense, o Intel e o Defense anteriores ao lado dos novos em sequências aleatórias de frames (48 mil, 800 mil
e 60 mil frames): mesmas etapas, razões, alvos, entradas e propostas, a menos do `mission_id`.

## Visualização

- **Bolinhas in-game** (`--spatial-view`): uma esfera por ponto do lattice, cor contínua
  verde (nosso) → amarelo (disputado) → vermelho (inimigo crível), laranja onde a ameaça é
  só possível; contatos com anel de incerteza, dono de cada unidade, anchor do MapControl (e o da política em
  shadow, em cinza) e painel da estratégia.
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
| `strategy.decided` | strategy | troca de objetivo, heartbeat | `objective`, `previous`, `since`, `reason`, `defense`, `army`, `economy`, `risk`, `inputs` {`danger`, `danger_now`, `army_share`, `own_power`, `enemy_power`, `estimated_enemy_power`, `enemy_uncertainty`, `planned_enemy_power`}, `scores`, `policy` {`offense` {`posture`, `reason`}} |
| `behavior.proposed` | behaviors | o conjunto ranqueado de propostas muda | `proposals[]` {`proposal_id`, `owner`, `priority`, `command`, `target`, `count`, `minimum_power`, `must_attack`, `demand_id`, `mission_id`, `unit_types`, `reason`, `inputs`} |
| `behavior.map_control_planned` | behaviors | origem, razão, anchor (grade de 3), fallback, ponto mantido do `staging` (e quando foi escolhido), anchor ou candidatas do `passage` mudam; heartbeat de 30 s | `anchor`, `source` (`threatened_base`, `staging`, `passage`, `legacy`), `reason`, `policy`, `fallback` (`no_candidates`, `no_enemy_route`, `no_separating_passage`, `anchor_unresolved` ou null), `passage` e `region` (da escolha que pôs o anchor, ou null), `staging` {`anchor`, `switch` (`kept`, `initial`, `held_invalid`, `bases_changed`, `posture_changed`, `awareness`), `since`, `previous`, `objective`, `advance`, `scale` (D), `bases`, `candidate_count`, `selected`, `top[]` (o melhor de cada região, até 5, melhor primeiro); cada ponto {`anchor`, `region`, `passage`, `reaction`, `worst` e `worst_base` (a base respondida por último e a resposta, em células), `mean` (distância média às bases), `front` (à frente da base média no caminho do inimigo, em células; negativo atrás), `choke`, `threat`, `support`, `control`, `exposure`, `score`}} ou null, `shadow` (a política que não controla: `policy`, `anchor`, `passage`, `region`, `distance` ao anchor; do `passage` também `fallback`, `candidates[]` (até 8: `passage`, `kind`, `position`, `region`, `protected_bases`, `protected`, `quality`, `overextension`, `score`) e `candidate_count`) |
| `behavior.offense_planned` | behaviors | estágio, `since`, bloqueio, alvo (tag ou grade de 3) mudam | `stage`, `previous`, `since`, `reason`, `blocked_by`, `committed_power`, `target`, `target_tag`, `target_kind` (`known_base`, `known_structure`, `flying_structure`, `enemy_start`, `search`), `inputs` {`own_power`, `army_share`, `supply_used`, `assembled_share`, `committed_power`, `stage_for`, `cooldown_left`, `known_structures`, `squad_units`, `squad_power`, `core_power`, `local_enemy_power`, `local_share` (−1 sem inimigo), `contested`, `clear_for`, `start_cleared`}, `fight` {`center`, `own_power`, `enemy_power`, `share`, `enemy_center`} ou null, `mission_id` e `mission_status` (a missão avançada ou aberta no frame, também no frame em que termina; null em IDLE) |
| `behavior.missions_updated` | behaviors | uma missão abre, muda de fase, recebe pedido de cancelamento ou termina | `missions[]` {`mission_id`, `owner`, `kind` (`main_attack`, `defend_area`, `scout`), `status` (`ACTIVE`, `COMPLETED`, `FAILED`, `CANCELLED`), `phase`, `since`, `reason`, `cancel` {`mode`, `reason`, `time`} ou null, `proposals[]`, `granted_units`, `granted_power` (o que a alocação anterior lhe deu)} |
| `behavior.economy_planned` | behaviors | o plano muda (a composição com 2 casas) | `active`, `workers`, `gas`, `bases`, `expand`, `freeflow`, `reason`, `composition[]`, `inputs` {`workers`, `bases`, `saturated_at`, `expansion_sites`, `strategy_economy`, `danger`, `production_per_base`, `gas_worker_share`, `upgrades_done`, `enemy_seen_power`}, `upgrades[]`, `orbitals`, `mules`, `interrupt_opening`, `max_production`, `addons`, `addons_on`, `reactor_share`, `army` |
| `behavior.spawn_executed` | behaviors | `freeflow` ou razão do spawn mudam | `freeflow`, `reason` (`plan_inactive`, `plan_freeflow`, `composition_met`, `composition_short`), `counts` {tipo: contagem do Ares} |
| `behavior.micro_executed` | behaviors | alguma unidade usou Stim (em `ATTACK` ou `HOLD`), ou os Medivacs que escoltam mudam | `stimmed[]`, `escorts[]` |
| `behavior.detection_planned` | behaviors | todo scan; turrets, Engineering Bay, reserva, razão ou construção pedida ao Ares mudam | `scan`, `turrets[]`, `engineering_bay`, `energy_reserve`, `reason`, `inputs` {`hidden_enemies`, `cloak_seen_at` (−1 antes), `army_near_hidden`, `orbitals_with_scan`, `active_scans`}, `scanned_by`, `building[]` |
| `behavior.structures_planned` | behaviors | depots a abaixar/levantar ou razão mudam | `lower`, `raise`, `reason` (`no_depots`, `enemy_near`, `enemy_recently_near`, `no_enemy_near`), `inputs` {`depots`, `lowered`, `enemy_near`, `recently_near`, `ground_enemies`, `friendly_on_raising`, `nearest_ground_enemy` (só com depot e inimigo terrestre)} |
| `engine.granted` | engine | alguma concessão muda | `grants[]` {`proposal_id`, `owner`, `mission_id`, `priority`, `requested`, `minimum_power`, `granted`, `granted_power`, `status`, `reason`, `tags`, `types`}, `transfers[]` {`tag`, `type`, `from`, `to`}, `unassigned` |
| `engine.commanded` | engine | comando, alvo (grade de 3), unidades ou missão de uma concessão mudam | `proposal_id`, `owner`, `command`, `target`, `tags`, `types`, `priority`, `reason`, `demand_id`, `mission_id`, `inputs`, `strategy` {`objective`, `reason`, `defense`, `risk`}, `awareness` {`danger`, `contacts`, `enemy_power`}, `attention` {`army_units`, `visible_enemy_units`}; `tags: []` e `reason: no_units_granted` quando a concessão acaba |
| `logs.frame_perf` | logs | heartbeat | `frames`, `last_ms`, `max_ms` por camada |
| `logs.snapshot_written` / `logs.snapshot_failed` | logs | SVG escrito / falhou | `path`, `trigger`, `objective`, `elements`, `bytes`, `render_write_ms` / `error` |
| `logging.record_rejected` | logs | um registro não era JSON estrito | `rejected_event`, `rejected_component`, `error` |

## Comandos

```text
.venv\Scripts\python.exe run.py
.venv\Scripts\python.exe run.py --bot-log events
.venv\Scripts\python.exe run.py --army mech --enemy-race Zerg --difficulty CheatInsane --ai-build Macro
.venv\Scripts\python.exe run.py --bot-log events --spatial-view
.venv\Scripts\python.exe run.py --bot-log events --spatial-snapshot
.venv\Scripts\python.exe run.py --bot-log events --spatial-view --spatial-snapshot --spatial-view-spacing 6
.venv\Scripts\python.exe logs\open_viewer.py
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m ruff check bot tests harness run.py bench.py
.venv\Scripts\python.exe bench.py run --out bench\<rótulo> --maps PersephoneAIE_v4 --races Zerg Terran Protoss --time-limit 1200
.venv\Scripts\python.exe bench.py run --out bench\<rótulo> --maps PersephoneAIE_v4 --races Zerg --difficulties CheatInsane --ai-builds Macro Timing --armies bio mech --time-limit 1200
.venv\Scripts\python.exe bench.py summarize bench\<rótulo>
.venv\Scripts\python.exe bench.py compare bench\<base> bench\<desafiante>
```

## Ainda não implementado

Cada item entra quando um problema de gameplay medido pedir. Os modelos já escritos no branch
`matematização` que servem a vários deles estão em [migration-map.md](migration-map.md). O que já está em
andamento, ou decidido como o próximo, está em [staging/](staging/README.md).

- **Informação:** scouting depois do early game (o SCV sai uma vez, antes de 240 s), belief
  probabilístico do exército inimigo, forças inimigas agregadas além dos incidentes, estimativa do
  inimigo por produção ou economia vista, informação ampla que mostre um exército menor que o esperado,
  calibração de `army_growth`/`army_cap`, Raven e scan de informação.
- **Espaço:** `RegionState` e território (a topologia e o campo são calculados e nenhuma decisão os
  consome), map control, path de grupo consciente de risco, alcance de estruturas voando sobre terreno
  impassável.
- **Combate:** alcance no modelo de poder (o splash já conta, o alcance não) e splash contado contra a
  aglomeração real em vez da suposta; coesão e reforços da ofensiva (hoje toda unidade livre vai sozinha
  até o grupo); stutter, focus fire, target scoring; Medivac evacuando; harass.
- **Defesa:** distinguir scout, worker rush e ataque; histerese de admissão/liberação; alcance por
  pathing em vez de distância; eventos explícitos de linhagem de incidentes; `desired_power`,
  suitability e custos de assignment; preempção com compromisso; ciclo de siege próprio da defesa;
  turret por rota aérea.
- **Wall:** antecipar o fechamento por contato lembrado ou pela rota, alcance pela velocidade do
  inimigo, distinguir os depots do wall e política para unidades nossas empurradas ou presas do lado
  de fora.
- **Economia:** a causa do banco com supply livre; reação específica a rush (bunker, worker pull,
  reparo); reposição de produção destruída; bases por `ready + pending` explícito, CC voando, cooldown
  do alvo e bases esgotadas (uma base sem minerais continua contando); supply antecipado além do
  `AutoSupply` do Ares; o resto do `MacroPlan` do Ares que para no primeiro behavior que age (supply,
  workers, gás e expansão ainda passam na frente do `SpawnController`); uma abertura e uma composição
  por matchup. A composição (estilo, counters, sobrevivência) e a ordem de builds são o próximo refactor:
  [staging/economia-e-builds.md](staging/economia-e-builds.md).
- **MapControl:** anchor em STABILIZE alternando entre bases de ameaça quase igual, e entre a base ameaçada e
  o staging quando a Strategy oscila entre os objetivos; um só ponto para o exército todo, sem dividir; bases
  com o mesmo peso (main e natural não valem mais que as outras); distância reta dentro de uma região
  (subestima regiões côncavas); a exclusão das regiões vizinhas ao start inimigo é uma regra fixa; uma ameaça
  pequena perto de uma base, em BUILD_ADVANTAGE, afasta o anchor dela (a Defense cuida do incidente). O
  `staging` é sensível a `advance`: com 0,6 o Persephone volta para a rampa da main com 2 bases (o choke da
  natural ganha por 0,005–0,017), com 0,8 o anchor de 7 bases passa do meio do mapa (Incorporeal 0,35 D,
  Torches 0,39 D); com 0,7 o Pylon de 7 bases já fica a 0,43 D do start inimigo. O shadow da política
  `passage` (e `anchor.py`, menos o `reached`) sai depois de medido o `staging` num bench.
- **Estratégia:** objetivo que leia a estimativa do
  inimigo, não só `danger`; renomear `risk`.
- **Harness:** repetir a célula na mesma execução; distinguir a falha do cliente de uma exceção nossa
  no `on_start`; células fora de VeryHard Macro.

## Medições

Toda medição até aqui: Persephone AIE, IA VeryHard Macro, Zerg/Terran/Protoss, 1.200 s, de um
`git worktree` limpo, salvo onde a linha diz outra coisa. `bench/` fica fora do git; os números abaixo são o registro.

| Execução | Commit | Resultado | O que mediu |
| --- | --- | --- | --- |
| `bench/base3` | `fe3cea0` | 8/9 (1 timeout, Terran seed 3) | Linha de base de 9 partidas, seeds 1–3 |
| `bench/6f` | `455209e` | 9/9 | Luta medida contra o grupo inteiro + gás pelos geysers. Defeito da luta de 16 → 1; o timeout virou vitória em 708 s |
| `bench/7jk` | `bcd324a` | 7/7 jogadas (2 não jogadas) | Expansão além da sexta base + pedido de base mantido. Bases 6 → 7–9; banco, army supply e duração não mudaram |
| `bench/6g` | `3fd7723` | 2 `crash`, 1 sem resultado | Tentativa de medir o HEAD; o cliente do SC2 caiu (`WSMessageTypeError`). Não refeita |
| `bench/rush-probe` | `3fd7723` | 1 timeout (Zerg Rush) | Única partida fora de Macro |
| `bench/smoke-mech` | `810185f` | derrota 882 s (Zerg CheatInsane Macro, mech) | O `UpgradeController` "pesquisou" o plating 950 vezes e o `MacroPlan` parou nele: 12 unidades e 3.000 minerais aos 490 s → `ExactResearch` |
| `bench/smoke-mech2` | `1bd236e` | derrota 1.020 s | Plating ok, mas o `ExactResearch` pulou a fila e o Weapons nunca saiu; 5 de 7 Factories com Reactor, Tanks esperando 2 Tech Labs → pesquisa em ordem, `reactor_share` |
| `bench/ci-mech-d784` | `d784503` | derrota 1.013 s (Macro) | 9 de 13 Factories sem add-on aos 502 s: os add-ons, depois do `SpawnController`, quase nunca rodavam → add-ons antes do `MacroPlan` |
| `bench/ci-mech-542` | `542151e` | Macro/Timing timeout; Rush derrota 520 s; Air derrota 600 s | Com add-ons: 200/200 aos 655 s (15 Hellion, 11 Cyclone, 20 Tank). Rush: Barracks ociosa sem Marine no mix → Marines. Air: abertura travada no 3º gás (banco 9.415) → `OPENING_STALL_BANK` |
| `bench/ci-bio` | `1bd236e` | 4 timeout, 1 derrota (Rush 953 s) | Linha de base bio contra Zerg CheatInsane × Macro/Timing/Rush/Air/Power |
| `bench/ci-bio-5f1` | `5f163e5` | 4 timeout, 1 derrota (Rush 737 s) | Bio no HEAD (regra de add-on nova, proteção da abertura); mesmo placar da linha de base |
| `bench/ci-mech-5f1` | `5f163e5` | **5 timeout, 0 derrota** | Mech no HEAD. Air: a proteção disparou aos 235 s e a matriz levou Cyclone 0,22 → 0,42 e Marine 0,10 → 0,17 contra Mutalisk |
| `bench/staging-pers` | árvore suja sobre `1b24bc2` (o código do commit do staging) | vitória 663 s (Zerg VeryHard Macro) | Anchor `staging` controlando, `passage` em shadow, com `--spatial-snapshot` |
| `bench/staging-ley` | idem | timeout (Ley Lines, Terran VeryHard Macro, bio) | Idem, no mapa onde o anchor ficava no choke da natural com 5–7 bases |

Contra Zerg CheatInsane nenhum jogo terminou em vitória: todo jogo sobrevivido é timeout, com o bot em 200/200
e banco de 1.500–19.000. A ofensiva entra em ASSEMBLE/ADVANCE, mas o grupo não se junta (`assembled_share` 0–0,22) e
`home_threatened` o chama de volta: o limite agora é fechar o jogo (N7.1), não a composição. Um seed por célula;
Rush perde com bio nos dois commits e trajetórias divergem cedo, então 953 → 737 s não é atribuível.

Wilson 95 % de 9/9 é 0,70–1,00 e de 8/9 é 0,57–0,98: o placar não separa nenhuma mudança. O que
sustenta cada uma é a medida do mecanismo no JSONL.

**Anchor `staging` × `passage` em partida real** (`bench/staging-ley`, `bench/staging-pers`; as duas
políticas no mesmo `behavior.map_control_planned`, a antiga em `shadow`). O anchor novo coincide com o antigo
com 1 e 2 bases (rampa da main, depois o choke da natural) e se afasta dele a cada base a partir da terceira:

| Bases | Ley Lines: `staging` | `passage` | distância | Persephone: `staging` | `passage` | distância |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | (154,122) `choke:19` | igual | 0 | (50,38) `choke:5` | igual | 0 |
| 2 | (150,102) `choke:15` | igual | 0 | (70,34) `choke:4` | igual | 0 |
| 3 | (134,102) região 3.1 | `choke:15` | 16 | (70,54) região 1.2 | `choke:4` | 20 |
| 4 | (130,98) | `choke:15` | 20 | (70,54) | `choke:4` | 20 |
| 5 | (130,98) | `choke:15` | 20 | (86,62) região 1.5 | `choke:4` | 32 |
| 6 | (118,94) | `choke:15` | 33 | (66,82) região 6.1 | `choke:4` | 48 |
| 7 | (106,94) região 4.2 | `choke:7`, junto ao inimigo | 56 | — | — | — |

Nenhum erro; a ofensiva montou (ASSEMBLE → ADVANCE) no anchor e a Defense tomou unidades como antes. Em
Ley Lines, entre 715 e 875 s, o anchor efetivo alternou entre a base ameaçada (104,107) e o ponto de staging
(110,98), a 11 células, a cada troca STABILIZE ↔ BUILD_ADVANTAGE da Strategy (`danger` entre 0,45 e 0,6: a
emergência pula o `minimum_dwell`). A alternância é da Strategy; com a política `passage` o anchor ia até o
choke da natural (150,102), a 46 células da base ameaçada. Uma partida por mapa: nada aqui separa resultado.

**Nunca medido sozinho:** Reactors nas Barracks sem add-on (`BARRACKSREACTOR`), a expansão além da
sexta base sem o pedido mantido (o código que roda hoje), o splash no poder e a interrupção do opening.
O HEAD não tem matriz própria.

**Medido e revertido** (o código saiu; a hipótese continua descartável ou por refazer):

- **Combat sim do Ares na decisão de lutar** (`bench/6d`): `min(parcela por poder, can_win_fight / 10)`.
  Nas duas lutas que custaram metade do exército contra Terran, o simulador respondeu vitória enfática:
  ele só aceita `Unit` vivos, e Siege Tanks em siege atiram de fora da visão.
- **Scan de reconhecimento da luta** (`bench/6e3`, 8/9 como a linha de base): o scan vinha com a luta já
  disputada e o grupo dentro do alcance; nenhum recuo veio nos 3 s depois de um scan. Refazer escaneando
  na rota do avanço.
- **Pedido de base mantido até virar base** (`bench/7jk`): o pedido ficou seguro 0,2–4,1 s em 4 de 7
  partidas e não evitou a queda de 43 s que o motivou, porque ela incluía um `STABILIZE`.
- **Recuo por perda / por troca** na ofensiva (`bench/all4`, `bench/all5`): timeouts sem ganho.
- **`ProductionController` fora do `MacroPlan`** (`bench/7`): mandava Tech Labs em Barracks que o
  `SpawnController` acabara de mandar treinar, e a última ordem vale. Há teste contra a reintrodução.

**Falhas de ambiente conhecidas:** o Ares às vezes morre no `on_start`
(`PlacementManager._solve_natural_bunker` → `TerrainManager.own_expansions[0]` com a lista vazia) e o bot
resigna com `game_time` 0 — o harness registra `not_played` e rejoga. O cliente do SC2 também fecha a
conexão no meio da partida (`WSMessageTypeError`, `TimeoutError: Websocket`); aí o jogo reporta derrota e
**duas execuções do mesmo spec e do mesmo código divergem**, então o determinismo por seed só vale sem
falha do cliente.
