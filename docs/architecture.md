# Arquitetura: camadas

No `on_start`, Attention lê o mapa físico uma vez (`read_map`). Depois, um frame atravessa
as camadas sempre na mesma ordem, em `play_frame` ([bot/main.py](../bot/main.py)):

```text
attention = observe(bot, iteration, map_view, opening)         ATTENTION
awareness = awareness_model.infer(attention)                    AWARENESS
intent    = strategy_model.decide(attention, awareness)         EGO / strategy (avaliação → intenção)
proposals = defense.plan(attention, awareness, intent, feedback)  EGO / planners → missões
held      = map_control.plan(attention, awareness, intent)      EGO / planner (sem missão)
proposals += held.proposals
offense   = offense.plan(..., intent, held.anchor, feedback)    EGO / planner → missão
proposals += offense.proposals
intel     = intel.plan(attention, awareness, intent, feedback)  EGO / IntelPlan
proposals += intel.proposals
missions  = defense.views() + offense.views() + intel.views()
economy   = economy.plan(attention, intent, army, awareness=awareness, ...)
structures = structure_control.plan(attention)
result    = engine.allocate(attention, proposals)               BODY / engine
feedback  = result                                              (lido no próximo frame)
body      = behaviors.execute(bot, attention, result,           BODY / behaviors
                              economy, structures, intel)
logs.record(bot, attention, awareness, intent, held, offense, ...,  LOGS
            body.spawn, body.micro, intel, body.detection, missions)
```

## Papéis arquiteturais

Esta seção é a definição normativa dos papéis. Docstrings e exemplos aplicam estas regras.

| Papel | Responsabilidade | Fronteira verificável |
| --- | --- | --- |
| Strategy | Responde "como está a partida?" (`GameAssessment`) e "o que o bot quer agora?" (`StrategicIntent`: postura, motivo, preferências contínuas e emergência), o contexto comum de todos os planners. | Não governa operações individuais, não escolhe lugar, alvo, composição, construção nem micro; cada planner traduz a postura para o seu domínio. |
| Planner | Dono e coordenador de um domínio: decide a intenção dele a partir do estado conhecido, da postura e do feedback relevante, e junta o que suas Missions e Policies decidem. | Um único por domínio, em `planner.py`. Produz planos/propostas; não causa efeitos no jogo. Pode ser função, objeto stateless ou stateful. |
| Desired state | Condição contínua que um Planner tenta manter. | Se deixar de estar satisfeita, volta a ser pedida, sem criar uma operação numerada. |
| Mission | Conduz uma operação persistente com identidade, lifecycle próprio e término, normalmente com unidades cuja posse o Engine arbitra. | É opcional e interna ao Planner que a abre, em `missions/`; não é uma etapa obrigatória da arquitetura. |
| Policy | Implementa uma regra de decisão interna que o Planner usa. | Pode ter estado; não tem `mission_id`, lifecycle nem `MissionView` e não pede unidades ao Engine. Fica em `policies/`. |
| Knowledge | Contém fatos estáticos do domínio: dados, tabelas e catálogos. | Não decide nada por frame nem guarda estado da partida. Fica em `knowledge/`. |
| Engine | Arbitra quais unidades atendem quais intenções; transforma proposals em grants. | Não arbitra minerais, energia orbital ou toda a produção. Não decide objetivos nem lifecycle. |
| Behavior | Materializa a intenção em ações do jogo, com decisões locais de execução. | Pode mudar path, siege, stim, ator equivalente ou posição fina; não muda objetivo, alvo estratégico, compromisso ou cancelamento. |

**Planner owns the domain. Mission owns an operation. Policy implements a decision rule. Knowledge
contains static domain facts.**

Cada domínio em `planners/` segue, quando se aplica, a mesma forma; nem todo domínio tem todas as pastas:

```text
<domínio>/
  planner.py      o Planner
  missions/       as operações que ele abre e governa
  policies/       as regras de decisão que ele usa
  knowledge/      os fatos estáticos que ele e as policies leem
```

O que separa Mission de Policy não é ter estado nem fases, e sim participar do sistema de missões:
`mission_id`, lifecycle terminal, `MissionView` no log e, normalmente, unidades pedidas ao Engine. Uma
máquina de estados interna não vira Mission por ser máquina de estados: a relocation da StructureControl
tem episódios (levanta, espera, pousa), mas opera estruturas que o Engine não arbitra e não aparece como
missão, então é Policy. Knowledge é o conteúdo do domínio que independe da regra que o lê (os estilos de
exército, o catálogo de counters); as `*Config` de ajuste (limiares, pesos) ficam com o Planner ou a Policy
que as lê. `policies/` e `knowledge/` são classificação, não subsistema: não há classe base, registry nem
lifecycle de Policy, e cada uma tem a interface de que o seu Planner precisa (uma função, uma classe com
estado). A intenção da Strategy (`StrategicIntent`) é outra coisa: contexto global publicado igual para
todos os planners, não a Policy de um Planner. A Strategy não publica política por domínio; o que uma
postura significa para a economia, a ofensiva ou o MapControl é decisão do planner de cada um.

Um Planner pode expressar tanto desired states contínuos quanto operações episódicas.
Economy, MapControl, controle de depots, detection e sensor coverage são contínuos.
Ataque principal, scout e defesa de um incidente são episódios. Estado persistente por si só não
justifica Mission: hysteresis do anchor e cobertura já desbloqueada pertencem aos planners e às suas policies.

```text
Attention → Awareness → GameAssessment → Strategy → StrategicIntent → Planners (um por domínio)
                                    ├─ desired state contínuo
                                    ├─ Missions opcionais (episódios)
                                    └─ Policies (regras internas), sobre Knowledge (fatos estáticos)
                                    ↓
                              Plans / Proposals
                              ├─ propostas de unidades → Engine → Grants → Behaviors
                              └─ planos diretos de economia/estrutura/abilities → Behaviors
                                                                                ↓
                                                                               Jogo
```

**Admissão de Mission.** Antes de criar uma, verificar:

1. Existem ocorrências individuais?
2. Cada ocorrência começa e termina?
3. Faz sentido distinguir #1 de #2?
4. Há memória/progresso válido apenas naquela ocorrência?
5. COMPLETED, FAILED ou CANCELLED representam resultados reais?

Se a maioria não se aplica, usar desired state no Planner. Uma torre destruída restaura uma
necessidade de cobertura; não abre uma nova missão. Não existe fase genérica de manutenção
permanente de Mission. As fases concretas pertencem à operação, e o lifecycle permanece terminal.

**Contratos.** Plan é intenção estruturada, com ou sem propostas. Proposal pede atores ao Engine;
Grant é sua alocação. Command identifica a instrução de unidade consumida pelo Behavior, com alvo
na proposta. Intent é o conceito de intenção, não outro tipo obrigatório. Mission não é sinônimo
de nenhum desses contratos. Uma proposta contínua pode ter `mission_id=None`.

**Execução.** Na cadeia decisória, apenas Behaviors causam efeitos deliberados no jogo.
Attention/Awareness leem e inferem; o bootstrap em `on_start` configura a partida e os logs observam.
Teste do Behavior: sua implementação pode ser trocada sem mudar o que o bot quer fazer?
O ajuste `composition_met` traduz a composição para a mecânica do SpawnController; a composição
continua vindo do Ego. Tags do Orbital que efetivamente escaneou impedem ordens conflitantes de
MULE no mesmo frame; a reserva de energia é intenção do Intel, não política criada pelo Body.

## Camadas

| Camada | Arquivo | Estado público | O que faz |
| --- | --- | --- | --- |
| ATTENTION | [bot/attention/](../bot/attention/) | `MapView`, `AttentionState` | Percepção. `map.py`/`topology.py`: no `on_start`, `read_map` congela lattice, expansões, `MapTopology` (regiões, passagens/chokes, adjacência, regiões dos starts) e os sites 3x3 com espaço de add-on que o placement do Ares resolveu na nossa main, sem o wall da rampa (`production_sites`), e os spots 2x2 dele por expansão, também sem o wall (`tower_sites`), e os sites 3x3 por expansão (`base_production_sites`) — "o mapa físico é assim". `frame.py`: `observe` lê o frame (recursos, workers pela contagem do jogo, unidades próprias e inimigas visíveis neste frame ordenadas por tag — sem os snapshots de até 30 s que o Ares mistura em `enemy_units` para inimigos fora de visão, porque lembrar é papel da Awareness —, bases, mortes, visibilidade, upgrades concluídos; por unidade, energia, se está camuflada/enterrada e se nada a detecta, o ponto aonde a primeira ordem a leva — move, attack-move, patrol ou smart no chão (`moving_to`) — e se tem add-on (`has_add_on`); e os contatos inimigos que as nossas Sensor Towers pegam fora de visão, só a posição, ordenada (`radar_blips`)); `units.py` classifica e precifica unidades (`UnitView`, `unit_power`, `is_army`). `opening.py`: o registro de scouting que atravessa frames — `OpeningWatch` dobra cada frame em `OpeningObservations` (natural e third como `UNKNOWN`/`ABSENT_CONFIRMED`/`PRESENT` com os instantes em que foram checadas, estruturas inimigas por tipo com contagem e timestamps, gases, workers, unidades de combate, estruturas vistas na nossa metade e a cobertura acumulada da main inimiga), até `OPENING_WINDOW` = 300 s; depois congela. `passages.py`: o outro registro que atravessa frames — a identidade do mapa (regiões, ids de passagem, qual expansão é a natural/third do inimigo) é fixa, mas mineral walls e rocks caem durante a partida, e só isso muda: `MapPassage.state` (`OPEN`/`CLOSED`/`UNKNOWN`). O `pathing_grid` do jogo já vem com blocker em cima do chão andável, então toda passagem que o mapa pode ter existe desde o primeiro frame; as que um blocker sela nascem `CLOSED`. Cada passagem guarda as tags dos objetos neutros que a fecham (`blocker_tags`, `blocker_type`) e `PassageWatch` pergunta a cada frame quais delas o jogo ainda lista — compara as tags sobreviventes antes de atualizar estados, sem reconstruir geometria. Sobra alguma → `CLOSED`; sumiram todas → `OPEN`; não deu para ler → `UNKNOWN`, que não é caminho. Quando algo muda de estado o `MapView` é substituído (e só então), e quem depende de conectividade lê `topology.open_passages()`, `neighbours(..., open_only=True)`, `connected_regions`, `route`, `map.route_to`/`reachable_now`. Não interpreta valor, ameaça ou controle. |
| AWARENESS | [bot/awareness/](../bot/awareness/) | `AwarenessState` | Pinta o mapa ao longo da partida. Memória de contatos com confiança `exp(-idade/τ)` e incerteza `min(cap, v·idade)`; esquece por morte confirmada, posição vista vazia (após carência) ou confiança < piso. Pressão por base com a ameaça lembrada (`recent_threat`, τ = `threat_memory`), incidentes de ameaça (`ThreatIncident`), estimativa do exército inimigo (conhecido, visto vivo, esperado sem avistamento, incerteza e cobertura), contatos escondidos (camuflados sem detecção, à vista) e quando um exército camuflado foi visto pela primeira vez, e campo de influência. `opening/`: lê os fatos da Attention como `OpeningBelief` — `aggression`, `greed`, `tech` e `proxy` contínuos e independentes, com a `confidence` que cobertura, checagens e atualidade lhe dão; as expectativas por raça ficam em `opening/knowledge.py`. Descreve; não escolhe margem nem prioridade. |
| EGO / strategy | [bot/ego/strategy/](../bot/ego/strategy/) | `GameAssessment`, `StrategicIntent`, `StrategicPosture` | `model.py`: os contratos. `assessment.py`: `AssessmentModel` transforma Awareness (e as mortes e upgrades do frame) em `GameAssessment` contínuo — ameaça, posição militar e econômica, vulnerabilidade inimiga, power spike, revés e confiança —, com o inimigo sempre como estimativa. `strategy.py`: `StrategyModel` escolhe a postura (`RECOVER`, `DEFEND`, `DEVELOP`, `PRESSURE`, `COMMIT`) por perguntas com histerese e persistência, e publica o `StrategicIntent` com motivo, valores que o explicam, emergência travada e as preferências `defense`, `army`, `economy`, `risk`. Não conhece missão nenhuma nem escolhe lugar no mapa. |
| EGO / missions | [bot/ego/missions/](../bot/ego/missions/) | `MissionStatus`, `CancelMode`, `Lifecycle`, `MissionFeedback`, `MissionView` | O que todas as missões compartilham: `lifecycle` (status terminal, pedido de cancelamento e modos) e `contracts` (o feedback que a missão lê e o resumo que ela reporta). Nenhuma missão concreta mora aqui. |
| EGO / planners | [bot/ego/planners/](../bot/ego/planners/) | `Proposal`, `Command`, `IntelPlan`, `EconomyPlan`, `StructurePlan` | Decidem o que deve ser feito (tarefa, alvo, prioridade, requisitos) sem nomear unidades, um pacote por planner: `offense/`, `defense/` e `map_control/` pedem exército ao Engine, `intel/` obtém informação por unidades, scans e estruturas, `economy/` diz o que comprar e `structure_control/` opera estruturas existentes. `defense/`: o `DefensePlanner` abre uma `DefendAreaMission` por incidente, que pede `ATTACK` com um orçamento de poder repartido entre a parte aérea e a terrestre. `offense/`: `OffensePlanner` (`planner.py`) abre e encerra a `MainAttackMission` (`missions/main_attack.py`) (ASSEMBLE → ADVANCE ⇄ SEARCH, ENGAGE/RETREAT → REGROUP, e WITHDRAW só num cancelamento gracioso); `ATTACK` no alvo ou `RETREAT` ao rally (o anchor do MapControl, que o frame lhe passa), com todas as unidades livres, lendo a concessão anterior da missão. `map_control/`: `MapControlPlanner` (`planner.py`) escolhe o anchor — a base ameaçada em DEFEND, senão o ponto de reação que melhor responde a todas as nossas bases, na frente delas, num choke que as guarda e longe da influência inimiga (`policies/staging.py`), senão a heurística antiga do rally — e pede `HOLD` nele com todas as unidades livres, sem missão (a proposta mantém o id `core_army`, nome anterior, por compatibilidade com logs, viewer e benches). `intel/`: `IntelPlanner` (`planner.py`) abre a `EarlyScoutMission` (`missions/early_scout.py`), o SCV que lê a opening inimiga (CHECK_NATURAL → ENTER_MAIN → CIRCLE_MAIN → RECHECK_NATURAL → CHECK_THIRD → SURVEIL → COMPLETE, e PROXY_SEARCH quando o planner manda; SURVEIL é a ronda que tapa o que ficou em aberto, sempre indo ao lugar visto há mais tempo — natural, third, saídas da main e a própria main —, e acaba quando a `confidence` da `OpeningBelief` passa de `READ_ENOUGH` (0,75) ou a janela da opening fecha: um scout só se paga enquanto a leitura ainda está fina), e manda procurar proxy quando a leitura da Awareness acredita em um (`policies/proxy.py` diz onde procurar, na nossa metade do mapa). `economy/` (`planner.py` junta uma policy por pergunta e o estilo): `policies/investment` diz quanto investir (workers, bases, gás, teto de produção, quando o plano assume do opening ou o interrompe numa emergência); `knowledge/styles` diz qual exército (o estilo sorteado na partida: abertura, composição, upgrades e onde vão os Reactors); `policies/composition` (`CompositionPolicy`) diz o que construir agora (baseline do estilo combinado com respostas viáveis do catálogo `knowledge/counter_catalog` contra o exército inimigo acreditado); `planner.plan` junta tudo num `EconomyPlan` para os macro behaviors do Ares (inclusive upgrades, Orbital e MULE). `intel/policies/detection`: onde escanear, quais bases precisam de Missile Turret, Engineering Bay e a energia que cada Orbital guarda. `structure_control/`: `StructureControlPlanner` (`planner.py`) diz quais depots levantar e quais abaixar e junta `policies/relocation.py`, que tira do caminho de um Siege Tank preso a Barracks, Factory ou Starport que o bloqueia (levanta, espera o Tank andar, pousa fora do caminho) e diz quais sites da main ficam vazios no corredor da rampa. |
| BODY / engine | [bot/body/engine.py](../bot/body/engine.py) | `EngineResult` | Só alocação. Ordena por `(-priority, owner, proposal_id)` e concede cada unidade de exército a no máximo uma proposta. Restrições duras vêm antes de qualquer ordem: `unit_types`, `must_attack` (`GROUND`/`AIR`) e, num pedido de poder, `power > 0`. Entre as elegíveis livres, as que já eram da proposta primeiro, depois as mais próximas. Pede-se `minimum_power` (unidades até atingir o poder), `count` ou todas as livres; cada `Grant` traz `power`, `status` (`FULL`/`PARTIAL`/`REJECTED`) e `reason`. Um pedido de todas as livres que não recebe nenhuma fica `REJECTED` (`eligible_units_taken`/`no_eligible_units`). Workers só são elegíveis para propostas que pedem um tipo de worker, só saindo da mineração (role `GATHERING`) ou já sendo da proposta. `released` lista quem perdeu o dono. O `EngineResult` é o feedback que as missões leem no frame seguinte, sem nomear unidades; o Engine é o único registro de posse e nunca lê nem muda o lifecycle de uma missão. Não comanda nada. |
| BODY / behaviors | [bot/body/behaviors/](../bot/body/behaviors/) | — | Executam os grants, despachados por `Command`. `attack` (`ATTACK`, de Defense ou da ofensiva): `AMove`, Siege Tank decide o siege sem ficar preso ao ponto; Marine/Marauder usam Stim com inimigo a ≤ 10 e ≥ 50 % de vida; Medivac vai ao centro do próprio grupo. `retreat` (`RETREAT`): path ao ponto sem lutar, Siege Tank sai do siege. `hold` (`HOLD`): `PathUnitToTarget` até o ponto, `AMove` com inimigo a ≤ 10 (bio usa Stim pela mesma regra do `attack`), Siege Tank fica sieged perto do ponto. `scout` (`SCOUT`): tira o worker da mineral, role `SCOUTING`, path sem evitar perigo. `economy`: para o build runner do Ares quando o plano interrompe o opening; workers liberados voltam a `GATHERING`, `Mining`, um add-on por frame antes do `MacroPlan` (Reactor ou Tech Lab na estrutura `addons_on`, pelo `reactor_share`), `MacroPlan` (Orbital antes de `BuildWorkers`, pesquisa — `ExactResearch` e `UpgradeController` — antes do `SpawnController`, depois `ProductionController`, nesta ordem, com o teto de produção do plano) e MULEs, sem gastar a reserva de scan nem usar o Orbital que escaneou; devolve o `SpawnMode` (com a composição inteira exatamente na proporção, o `SpawnController` roda em `freeflow` naquele frame). `detection`: scan com o Orbital pronto de mais energia; uma Missile Turret por vez após o pré-requisito consolidado pelo Intel, pelo `BuildStructure` do Ares na expansão mais próxima da base. `execute` devolve `BodyReport` (`spawn`, `micro`, `detection`, `sensor_towers`, `infrastructure`). `structure_control`: abaixa e levanta os depots do plano; levanta as estruturas da relocation (cancela o que treinam antes, um item por frame: ocupada, não levanta; já levantando, não repete a ordem), e o `economy` não treina nem põe add-on nelas enquanto isso; as pousa pelo `move_structure` do Ares; no `on_start`, `keep_clear` marca como ocupados no placement do Ares os sites do corredor da rampa, e o macro do Ares não constrói neles. `combat` guarda o que `attack` e `hold` compartilham: decisão de siege, `AMove` e a regra do Stim. O Siege Tank decide o siege também contra os inimigos que o Ares lembra fora de visão; o Stim e a saída do path no HOLD só contam inimigos à vista neste frame. |
| LOGS | [bot/logs/](../bot/logs/) | — | Log JSONL, snapshots SVG do campo, overlay in-game e o chat, onde o bot diz em voz alta o que está pensando (`chat.py`: postura nova, emergência, camuflado visto e a leitura da opening; uma linha por vez, `gap` de 12 s, um assunto não se repete antes de `topic_cooldown`, teto de `max_lines` por partida, escolha determinística, e `gg` no fim). Falar é async e o frame não é: `observe` só enfileira, e `BotBandido._speak` manda — engolindo qualquer erro. Nenhum deles muda decisão nem derruba partida. |
| HARNESS | [harness/](../harness/), [bench.py](../bench.py) | `Game`, `GameSpec`, `result.json` | Fora do bot, um módulo por assunto: `config.py` é a **lista** que se escreve à mão — o `harness/matrix.yml`, uma linha por partida (`race`, `strategy`, `map`, mais `army`, `difficulty`, `games`, `time_limit`), o que a linha não diz vem de `defaults`, `games: 10` pede dez daquela partida (cada uma com a sua seed), `map: random` sorteia um mapa por execução (o mesmo para todas as linhas que pedem random, enquanto a linha que nomeia um mapa fica nele) — é YAML porque YAML aceita comentário, e é ali no topo do arquivo que mora a colinha com todos os nomes que cabem; os nomes são conferidos contra as tabelas do jogo e do bot antes de qualquer partida subir, então um erro de digitação custa uma mensagem (com a linha do arquivo, quando é o YAML que não fecha) e não uma tarde; `matrix.py` é a **tabela** fixa de partidas, uma linha por jogo (`Game(mapa, raça, abertura da IA)`), `BASE` com as 9 em que uma fatia é medida (cada raça contra `Rush`, `Macro` e `RandomBuild`, porque uma mudança que só aparece contra uma abertura não é mudança) e `WIDE` com essas 9 nos três mapas de `WIDE_MAPS` (27, e não nos sete da rotação, porque 63 partidas não respondem melhor se o mapa estava carregando o resultado); `MAPS` é a rotação — o pool da temporada, sete mapas — e é dela que um `random` sorteia, uma vez por execução (todas as partidas que pedem `random` no mesmo mapa, outro mapa na próxima), então duas execuções que precisam ser comparadas fixam o mapa na linha ou com `--maps` — o `compare` avisa quando foram mapas diferentes. Qual matriz uma execução joga sem nenhum argumento mora nesse arquivo (`DEFAULT_MATRIX` = `file`, a lista do `harness/matrix.yml`, para o `bench.py`; `DEFAULT_LAUNCHER` para o `run.py`), que é onde se troca isso em vez de nos argumentos de uma configuração de launch; com `--matrix file` valem `--matrix-file`, `--seed` e `--time-limit`, e as colunas de uma tabela (`--maps`, `--races`, `--difficulties`, `--ai-builds`, `--armies`, `--games`) são recusadas com uma mensagem porque o arquivo já diz o que jogar; `games_of` devolve a tabela, ou o produto do eixo que for dado à mão (`--maps`, `--races`, `--ai-builds` substituem aquela coluna), e `matrix` transforma jogos em `GameSpec` (× dificuldade × estilo do bot `--armies` × `--games` repetições, cada repetição com a sua seed; sem `--armies` o bot sorteia e o `game_id` não leva sufixo). `outcome.py`: o que aconteceu com uma partida. `record.py`: o `result.json` que liga o desfecho a commit, SHA do Ares, árvore suja, fingerprint da configuração, mapa, oponente, seed, replay e JSONL. `summary.py`: `summarize` e o intervalo de Wilson. O launcher lê as mesmas listas: `run.py --matrix builds` joga as três aberturas no mesmo mapa e raça (3 partidas), `--matrix wide` percorre as 27 e `--matrix file` joga a lista do `harness/matrix.yml`, cada partida com o mapa, a raça, o army, a dificuldade e a seed da sua linha, com a janela aberta e sem registrar nada — para medir é o `bench.py`; cada partida de uma sequência é cortada em `--time-limit` (30 min por padrão) e roda com um bot novo. Nomes de raça, dificuldade e build são conferidos antes de qualquer partida subir, e um mapa que não está instalado também, cada partida num processo com timeout de relógio; `result.json` liga resultado (`victory`, `defeat`, `tie`, `timeout`, `crash`, `no_result`, `not_played`) a commit, SHA do Ares, árvore suja, fingerprint da configuração, mapa, oponente, seed, replay e JSONL. Uma partida que reportou resultado com o relógio do bot em 0 é `not_played` (o python-sc2 resigna no primeiro passo quando o `on_start` levanta): conta em `games`, não em `played`, fica fora da taxa de vitória e da duração média, e `run` a joga de novo em vez de pular. `summarize` recalcula o desfecho do que cada registro guardou, então execuções antigas são resumidas pela regra atual; `compare` agrega com intervalo de Wilson. O fingerprint cobre `Layers.configs()`, incluindo estilo, composição (digests do catálogo e da física) e investment; constantes fora das configs ainda exigem comparação pelo commit. |

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
- Leitura da opening (`bot/awareness/opening/`), em [0, 1] e independentes entre si — não somam 1.
  Toda evidência é contínua: nada tem limiar, e o que vale é **quando foi observado**, não o instante atual.
  - Rampas por raça (`knowledge.py`): `atraso = clamp((referência − early) / (late − early))` e
    `antecipação = clamp((late − visto) / (late − early))`; a referência de uma expansão é o instante em que
    foi vista de pé (`PRESENT`) ou o da última checagem vazia (`ABSENT_CONFIRMED`). `UNKNOWN` lê 0: ninguém
    olhou não é "não tem".
  - `aggression = S(1,0·atraso_natural + 0,9·produção_extra + 0,9·rush + 0,6·unidades_precoces)`.
  - `greed = S(1,1·antecipação_natural + 1,3·antecipação_third)`.
  - `tech = S(0,9·tipos_de_tech + 0,8·gás_extra + 0,6·atraso_third·gás_extra)`.
  - `proxy = S(1,6·faltando_na_main·cobertura + 2,0·estruturas_na_nossa_metade + 0,5·rush)`, onde
    `faltando_na_main` é a fração do que a raça deveria ter na main, pesada pela cobertura e por quanto o
    registro passou do horário esperado.
  - `confidence = clamp((0,45·cobertura + 0,35·checagens + 0,20·evidência) · recência · raça)`, com
    `recência = exp(-max(0, t − last_updated − 30 s) / 120 s)` e `raça = 0,6` enquanto a raça é desconhecida.
    Um registro velho continua dizendo o mesmo; o que cai é quanto ele vale.
- Campo por ponto do lattice:
  - `threat`: presença possível, σ alargado pela incerteza;
  - `enemy`: presença crível, sem alargamento;
  - `support`: nosso exército e estruturas;
  - `control = support - enemy`.
- Avaliação (`GameAssessment`, [assessment.py](../bot/ego/strategy/assessment.py)), tudo contínuo:
  - `threat_level = danger` (a ameaça lembrada na base mais ameaçada), com um nome para leitura
    (`CLEAR` < 0,05 ≤ `LOW` < 0,3 ≤ `ELEVATED` < 0,6 ≤ `HIGH`); decisões leem o valor.
  - `army_position = (own − planejado) / (own + planejado + prior_power)` em [−1, 1], com inimigo planejado
    `= estimated_enemy_power + commit_margin · enemy_uncertainty` (margem 0,5: a névoa não é vantagem) e
    `prior_power` (20 Marines) de dúvida nos dois lados: uma escaramuça de poucas unidades não é veredito.
    `army_share = (1 + army_position) / 2`.
  - `economy_position = (nossas bases − bases inimigas) / soma`, com as bases inimigas `= max(townhalls
    lembrados, 1 + t / enemy_base_interval (150 s))`, o prior limitado à metade das expansões do mapa.
  - `enemy_vulnerability = perdido / (perdido + estimado)`: poder do exército inimigo morto à nossa vista
    (tags de `dead_tags` com o poder do frame anterior), somado com memória `exp(−Δt / loss_memory)` (30 s).
  - `setback`: o mesmo para o nosso exército, `perdido / (perdido + own)`, vezes `min(1, 2 · perdido /
    (perdido + perdido inimigo))` — inteiro numa troca igual ou pior, menos quanto melhor foi a troca.
  - `power_spike = 1 − (1 − upgrades)(1 − supply)`: `upgrades = 1 − exp(−Σ exp(−idade / upgrade_window))`
    sobre os upgrades concluídos (60 s; os já prontos no primeiro frame não contam) e `supply` uma rampa de
    `supply_spike_from` (170) a `maxed_supply` (190), onde o exército não cresce mais.
  - `confidence = max(conhecido, visto vivo) / estimado` (1 sem estimativa): quanto da estimativa do
    exército inimigo vem de avistamento e não do prior que cresce com o tempo.
- Postura (`StrategicIntent`, [strategy.py](../bot/ego/strategy/strategy.py)): quatro perguntas em ordem; a
  primeira respondida sim vence, e DEVELOP é o que sobra. `safety = 1 − threat_level`.
  - DEFEND: `threat_level`.
  - RECOVER: `1 − (1 − setback)(1 − confidence · max(0, −army_position))` — perdas vistas, ou um déficit na
    medida em que avistamentos o sustentam.
  - COMMIT: `safety · sqrt(max(0, army_position) · enemy_vulnerability)` — vantagem clara e inimigo que acabou
    de perder o exército.
  - PRESSURE: `safety · max(army_share, min(1, 2 · army_share) · power_spike)` — mais forte, ou num spike, que
    vale inteiro de um exército igual para cima e some quando o `army_share` cai a zero.
  - Cada pergunta é um gate com a histerese do antigo objetivo binário: o score `s` contra `1 − s`, e o gate
    só vira com a vantagem ≥ `switch_margin` (0,1: abre com `s ≥ 0,55`, fecha com `s ≤ 0,45`). O gate do
    DEFEND espera também `minimum_dwell` (8 s) e abre na hora com `threat_level ≥ emergency_danger` (0,6).
    No primeiro frame o empate abre os gates conservadores (DEFEND, RECOVER).
  - Persistência: a postura nunca volta à que ela substituiu antes de ficar `stance_dwell` (15 s) — nada
    de ping-pong entre PRESSURE e DEVELOP; seguir para uma terceira não espera (PRESSURE escala para
    COMMIT com a janela aberta), e DEFEND é isento nos dois sentidos (entra na hora; sai pelo próprio gate).
  - Razões: `home_threatened`/`emergency_threat` (DEFEND), `army_setback`/`outmatched` (RECOVER),
    `decisive_advantage` (COMMIT), `army_advantage`/`power_spike` (PRESSURE), e DEVELOP pelo que deixou:
    `threat_cleared`, `recovered`, `window_closed`, `no_opportunity`. `because` guarda os valores salientes
    da troca (os das duas posturas envolvidas) e `summary()` os escreve numa linha.
  - Emergência: travada ao entrar/estar em DEFEND com `threat_level ≥ emergency_danger`, solta ao sair de DEFEND.
- Preferências: `army = clamp(0,3 + 0,5·danger + 0,4·(0,5 − army_share))`, `economy = 1 − army`,
  `risk = army_share · (1 − danger)`, `defense = danger`. Com `danger = 0`, `economy ≥ 0,5` com qualquer
  `army_share`.
- Como cada planner lê a postura (a tradução é do planner; a Strategy não decide nada disso):

  | Postura | Economy | Offense | MapControl (`advance`) | Intel (`focus`) | Defense |
  | --- | --- | --- | --- | --- | --- |
  | DEFEND | tudo no exército: `freeflow`, sem upgrades, add-ons nem expansão; emergência interrompe o opening e ativa a composição de sobrevivência | não abre; cancela **imediato** (`home_threatened`) | base ameaçada, senão 0 | `threat`: nenhum scout sai, Orbitals guardam um scan | orçamento `2,0 ·` poder do incidente |
  | RECOVER | sem expansão (`recover_army_first`); upgrades e add-ons seguem | não abre; cancela **gracioso** (`recovering`) | 0 | `economy` | `1,5 ·` |
  | DEVELOP | expande saturado | não abre (`no_opportunity`); o ataque em curso segue até o próximo REGROUP | 0,7 | `economy` | `1,5 ·` |
  | PRESSURE | expande saturado; teto de produção 5 por base | abre com o motivo da intenção | `pressure_advance` 0,8 | `offense`: Orbitals guardam um scan | `1,5 ·` |
  | COMMIT | sem expansão (`commit_army_first`); teto 5 por base | abre, e sem esperar o cooldown | 0,8 | `offense` | `1,5 ·` |
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
  depois é uma missão nova), `orçamento = margem · poder` (margem 1,5, ou 2,0 com a postura em DEFEND),
  repartido em `defense:<incidente>:air` (`minimum_power = margem · poder aéreo`, `must_attack = AIR`) e
  `…:ground` (idem, terrestre); as partes somam o orçamento e compartilham `demand_id`; `cover_margin` vai nos
  `inputs`. `priority = threat · (0.5 + 0.5·intent.defense)`
  (> 0 exatamente enquanto há atacante ao alcance, logo acima do MapControl, que é −1); no empate a
  parte aérea vem antes (id). A cobertura já no local é usada porque o Engine concede as unidades
  compatíveis mais próximas primeiro; uma incompatível não conta.
- Intel é um domínio transversal em `planners/intel/`. Um único `IntelPlan` reúne propostas de
  unidades, scans/detecção e infraestrutura de visão; o Body executa cada mecanismo. Com
  `workers ≥ 16`, antes de 240 s e fora de DEFEND, o `IntelPlanner` abre uma `ScoutMission`
  (`intel:scout:N`), que pede um SCV (`REQUESTING`) e passa a `LAPPING` quando ele sai. Rota: start
  inimigo, depois o sample mais distante da região da main em cada um de 8 setores angulares,
  anti-horário a partir da direção do nosso start. Um waypoint conta como visto na primeira vez em
  visão, com ou sem scout na rua (a rota e essa memória são do planner, desde o primeiro frame);
  `priority = waypoints não vistos / total`. A missão termina `COMPLETED` com a rota vista e
  `FAILED` com o scout morto (`scout_lost`) ou 90 s depois de sair (`lap_timed_out`); o SCV volta
  para a mineração. Antes de o scout sair, o planner pede o cancelamento imediato em 240 s
  (`too_late`) ou se os workers caem abaixo de 16 (`workers_below_threshold`, a única razão que
  deixa abrir outra missão depois). Um scout que saiu nunca é reposto. Ao alcançar quatro bases,
  ativa o desired state de sensor coverage: nenhuma base nossa alcançável pelo ar a partir do
  start inimigo sem passar por radar (raio 22, o `radar_range` que o jogo reporta), julgado na
  área jogável inteira, porque o ar ignora o terreno. Cada base fica dentro do raio de uma torre
  ou atrás de uma cadeia de raios sobrepostos de borda a borda do mapa. O planner pede o menor
  número de torres novas que fecha isso (Dijkstra sobre nó × paridade de cruzamento por base),
  nos spots 2x2 que o Ares resolveu nas nossas bases, main incluída, contando as torres de pé;
  entre cadeias do mesmo tamanho, puxa para o lado do inimigo e evita sobreposição. Uma base que
  nenhuma cadeia fecha ganha torre própria. Reconstruídas quando faltarem. Detection pertence ao mesmo planner: decide scans
  contra unidades escondidas, reserva de energia, Missile Turrets e Engineering Bay. A rede de
  Sensor Towers ainda não alimenta Awareness. O desbloqueio persiste se o número de bases cair.
  `intel/policies/sensor_towers.py` calcula as torres que faltam, as mais perto do nosso start primeiro;
  torres inacabadas já contam. Não há
  mission id, fase nem MissionView. `IntelPlan.engineering_bay` consolida com OR as necessidades
  de Detection e Sensor Towers antes da execução. `behaviors/intel.py` executa esse único pedido;
  os executores de turrets e torres apenas aguardam o pré-requisito ausente. Uma Engineering Bay
  inacabada já evita outro pedido; Ares verifica prontidão e viabilidade da construção.
- Economy (depois do opening): `workers` é `supply_workers`, a contagem do jogo — inclui SCVs
  dentro de refinarias, que somem de `bot.units` enquanto estão lá, e exclui os em produção.
  `bases = max(1, townhalls no chão)`; satura com `workers ≥ saturated_at = min(MAX_WORKERS (80), 16·bases)` —
  a força de trabalho que o próprio plano pede, não uma que ele nunca constrói — e expande saturado com
  `intent.economy ≥ 0,5`, a postura em DEVELOP ou PRESSURE e lugar no mapa (`bases < len(map.expansions)`,
  constraint discreta antes do score). Razões: `mineral_lines_saturated`, `worker_cap_reached` (saturado pelo
  teto de workers, não pelas linhas), `no_expansion_left`, `defend_spend_on_army`, `recover_army_first` e
  `commit_army_first`. `gas = min(2·bases, int(workers·GAS_WORKER_SHARE (0,4)) // 3)`: os geysers das bases,
  limitado pela parcela da força de trabalho que pode estar no gás, a 3 workers por Refinery.
- Estilo de exército: no `on_start` o bot sorteia um estilo entre os feitos para a raça inimiga (`styles.candidates`;
  bio contra todas, mech só contra Zerg), ou usa o que `--army` fixou, troca a abertura do Ares por
  `build_order_runner.switch_opening(estilo.opening)` e anuncia no chat ("Hoje vai de MECH: Hellion, Cyclone e
  Siege Tank."). O estilo é dado, não código: abertura, composição (o prior), upgrades em ordem, `addons_on` (a
  estrutura de produção que recebe add-ons) e `against` (as raças contra quem é sorteado). Entra no fingerprint (`configs.army`).
- Composição: `CompositionPolicy` combina o baseline do estilo com respostas ordenadas de
  `economy/knowledge/counters/{terran,protoss,zerg}.yml`. Canonicaliza aliases, filtra alcance físico e tecnologia
  pronta, escolhe a primeira resposta viável e registra alternativas rejeitadas. Poder sem resposta
  permanece no baseline; `prior_power=20` estabiliza a mistura. A mistura é calculada em supply e
  convertida em proporções de contagem. `CompositionPlan` expõe baseline, adaptações, tech e resultado.
- Sobrevivência: `StrategicIntent.emergency`, travada dentro de DEFEND. Ela permite complementar a
  composição usando capacidade pronta contra o incidente prioritário; não é Mission nem postura separada.
- Add-ons: `addons` liga depois do opening e fora de DEFEND (como os upgrades). Antes do `MacroPlan`, fora dele, uma
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
  teto por tipo (Barracks, Factory, Starport); `max_production = PRODUCTION_PER_BASE (4) · bases`, ou
  `OFFENSIVE_PRODUCTION_PER_BASE (5) · bases` em PRESSURE e COMMIT. Com 3 bases é o padrão do Ares (12); com 6, 24. Dentro do teto, quem decide quantas construir continua sendo a regra de renda do Ares.
- Spawn (Body): o `SpawnController` do Ares pula um tipo com `contagem / total ≥ proporção` (contagem do
  Ares, com alias e unidades em produção). Com todos os tipos da composição atingidos ao mesmo tempo — contagens
  num múltiplo exato das proporções, como 11/4/3/2 para 0,55/0,20/0,15/0,10 — ele não treinaria nada; nesse
  frame roda em `freeflow` (`composition_met`). Senão segue o plano: `plan_freeflow`, `composition_short`, e
  `plan_inactive` no opening.
- Opening: Investment interrompe o opening quando a Strategy trava a emergência (`intent.emergency`) ou o
  banco atinge `opening_stall_bank`. O plano fica ativo e o Behavior encerra o build runner antes do macro.

- Produção (ordem): o `ProductionController` fica depois do `SpawnController` no `MacroPlan` e só roda num frame em que
  ele não agiu; registrado à parte, mandava Tech Labs em Barracks que o `SpawnController` acabara de mandar treinar
  (a última ordem vale).
- Detection: depois que um inimigo de exército foi visto camuflado ou enterrado (`cloak_seen_at`), ou enquanto
  o Intel pede (`hold_scan`, com a postura em DEFEND, PRESSURE ou COMMIT), cada Orbital guarda
  `scan_reserve` (50) de energia (MULE só com ≥ 100); só o `cloak_seen_at` pede turrets: cada base sem Missile Turret (pronta ou não) a ≤ `turret_cover` (15)
  pede uma, e sem Engineering Bay pede-se uma. Um contato escondido à vista com ≥ `scan_min_power` (2) do nosso exército
  a ≤ `scan_reach` (10) é escaneado se nenhum scan dos últimos `scan_duration` (12,3 s) o cobre (`scan_radius` 13) e
  algum Orbital pronto tem 50 de energia; entre vários, mais exército perto, depois mais poder escondido revelado,
  depois menor tag. Razões: `no_cloak_seen`, `no_hidden_enemy`, `hidden_enemy_scanned`, `no_army_near_hidden`,
  `no_scan_energy`, `scan_hidden_enemy`.
- Offense (uma transição por frame; `_TOLERANCE` conta o valor exato no limiar). IDLE é do planner e
  derivado: nenhuma missão aberta. As outras etapas são as fases da `MainAttackMission`.
  - IDLE → ASSEMBLE (o planner abre `offense:main_attack:N`) com a postura em PRESSURE ou COMMIT (senão
    `blocked_by` = `home_threatened`, `recovering` ou `no_opportunity`), sem missão encerrada há `cooldown`
    (30 s) — COMMIT dispensa o cooldown: a janela é agora — e com `own_power ≥ minimum_power` (20). A missão
    abre com o motivo da intenção (`army_advantage`, `power_spike`, `decisive_advantage`).
  - Com a postura em DEFEND o planner pede o cancelamento **imediato** e a missão termina `CANCELLED`
    (`home_threatened`) no mesmo frame; em RECOVER, o **gracioso** (`recovering`): a missão recua ao rally
    (WITHDRAW) e só então termina. Em DEVELOP nada é pedido. A própria missão termina `FAILED` com `own_power <
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
    espera `regroup_dwell` (10 s) e a reunião (até mais 45 s); então ADVANCE com a postura ainda em PRESSURE
    ou COMMIT, recomprometendo com o poder atual, senão a missão termina `FAILED` (`window_closed`, call-off).
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
  - `threatened_base`: em DEFEND com base ameaçada, a mais ameaçada (a heurística antiga).
  - `staging` ([staging.py](../bot/ego/planners/map_control/policies/staging.py)), avaliado todo frame e no log mesmo
    com uma base ameaçada segurando o anchor: candidatos são os pontos do lattice das regiões com base nossa e
    das vizinhas, menos a região do start inimigo e as vizinhas dela (a menos que uma base nossa esteja lá). O
    hold point de cada passagem que guarda alguma base — `setback` (4) da passagem para o centro da região do
    nosso lado, no ponto do lattice mais próximo — é um deles, marcado com a passagem. Distâncias por terra
    sobre a própria `MapTopology`: reta dentro da região, senão pelas passagens **abertas**, passagem a
    passagem (todos os pares, uma vez por mapa; nenhum grafo novo — a tabela é refeita quando uma passagem
    abre, porque aí o `MapView` é outro). D = distância entre os starts, E = start inimigo.
    `score = −reaction + choke − exposure`:
    - `reaction = sqrt(média_b (r_b / D)²)` sobre as nossas bases, com `r_b = d(p, b) − advance ·
      max(0, d(E, b) − d(E, p))`: a distância à base, encurtada pelo quanto o ponto está à frente dela no
      caminho do inimigo (o inimigo que vem para b encontra o exército antes). Atrás de uma base, a resposta
      é só a distância. O RMS fica entre a média (que abandona uma base externa) e o pior caso (que arrasta
      o exército até ela). `advance` é a leitura que o planner faz da postura: 0 em DEFEND e RECOVER (só
      cobertura), `advance` 0,7 em DEVELOP e `pressure_advance` 0,8 em PRESSURE e COMMIT.
    - `choke = choke_weight (0,15) · guarded · exp(−largura / 6)` no hold point de uma passagem; `guarded` é a
      fração das nossas bases que o start inimigo deixa de alcançar com ela fechada (BFS na `adjacency`).
      `border` não ganha.
    - `exposure = threat_weight (0,3) · threat · (1 − support) + control_weight (0,2) · max(0, −control)`, o
      `InfluenceField` da Awareness no ponto: ameaça que não contestamos e estar do lado inimigo do campo.
      `support` sozinho não pontua (no anchor ele é o próprio exército do anchor, e premiá-lo prenderia o
      exército onde já está); o campo é saturado e só ordena lugares, não mede luta.
    Histerese: uma base tomada ou perdida, ou a troca de `advance`, escolhe de novo; fora isso o ponto mantido
    só troca quando outro o supera por `staging_margin` (0,04 de D). Toda troca diz o motivo (`initial`,
    `held_invalid`, `bases_changed`, `posture_changed`, `awareness`). As distâncias são calculadas uma vez
    por conjunto de bases (2–4 ms num mapa real); o campo é lido todo frame (numpy, sobre ~300–700 pontos).
  - `legacy`: a frente da base mais avançada, `rally_forward` (6) para o start inimigo, ou a rampa da main só com
    a main — quando o `staging` não põe anchor: `no_candidates` (nenhuma base localizada ou nenhum ponto do
    lattice nas regiões) ou `no_enemy_route` (sem região do start inimigo, ou sem caminho até ele).
  - Nos 5 mapas do pool (topologias reais, bases na ordem de distância ao nosso start): 1 base → rampa da main;
    2 bases → choke da natural (Torches, que não tem, fica na rampa); da 3ª base em diante o anchor sai do choke
    da natural e avança aos poucos, um hub por vez, para a frente do centro das bases; com 7 bases fica entre
    0,43 (Pylon) e 0,63 (Ley Lines) de D do start inimigo. A política anterior (uma passagem só, removida
    depois da comparação em "Medições") ficava no choke da natural até a 7ª base, e aí saltava para uma
    passagem perto do inimigo.
- Economy (Orbital, MULE e upgrades): depois do opening, `orbitals` e `mules`; `upgrades = UPGRADES` (Stim, Combat
  Shield, Infantry Weapons 1, Concussive, Infantry Armor 1, W2, A2, Vehicle Weapons 1, W3, A3, VW2, VW3) fora de
  DEFEND, senão nenhum. O `MacroPlan` do Ares para no primeiro behavior que age e o `SpawnController` age sempre
  que há produção ociosa, então `UpgradeCCs` vem antes de `BuildWorkers` e `UpgradeController` antes do
  `SpawnController`. Todo Orbital pronto com ≥ 50 de energia solta um MULE no campo mineral mais cheio a ≤ 10 de
  um townhall pronto (empate: menor tag).
- StructureControl: um depot pronto sobe no frame em que um inimigo terrestre visível está a
  ≤ `raise_reach` (8) dele e desce quando nenhum esteve a essa distância por `lower_after` (3 s),
  com a última ameaça guardada por tag. Voadores não contam. Subir empurra nossas unidades de cima
  para a borda mais próxima (contadas em `friendly_on_raising`); um inimigo em cima impede a
  subida, e o comando se repete enquanto o plano pedir.
- StructureControl (relocation): um `SIEGETANK` (não sieged) com ordem para um ponto a mais de
  `arrive_distance` (3) que fica a ≤ `progress_distance` (1,5) do mesmo lugar por `stuck_after` (4 s) está
  preso; parado, esperando no ponto ou com inimigo visível a ≤ `combat_reach` (12) não conta, e um frame sem
  ordem por até `order_grace` (1 s) não zera a contagem (o jogo derruba a ordem sem caminho e o behavior a
  repete). O bloqueador é uma Barracks, Factory ou Starport pronta, pousada, com o centro à frente do Tank e o
  footprint a ≤ `blocker_reach` (1,5) das próximas `look_ahead` (4) células rumo ao ponto. Sem nenhuma à
  frente o Tank está cercado (nasceu num bolso de produção, penhasco e doodads; o rumo ao ponto não é a
  saída), e o bloqueador é uma cujo footprint ou add-on fica a ≤ `hem_reach` (1,25) do centro do Tank. Sem
  add-on primeiro, depois a mais perto. Command Center nunca. Uma relocation por vez: levanta, repetindo a
  ordem a cada frame até voar (o jogo recusa o lift enfileirado atrás do que ainda treina, e o Ares enche de
  novo a estrutura ociosa); já no ar, espera o Tank andar `progress_distance` (ou sumir — morto ou sieged —,
  ou `wait_timeout`, 8 s); então pousa no site de produção livre mais perto da origem, na main ou noutra base
  nossa, cujo footprint, com o do add-on, fica a ≥ `lane` (2,5) do caminho do Tank e do corredor da rampa.
  Sem site, fica no ar e procura de novo a cada `land_retry` (5 s), e depois de `return_after` (30 s) volta a
  pousar na origem, se nada estiver nela (no ar não treina e segura todas as outras relocations); site não
  alcançado em `land_timeout` (25 s) é trocado pelo seguinte; lift que não acontece em `lift_timeout` (6 s)
  aborta. Depois de cada relocation, `global_cooldown` (20 s) sem outra, e
  cada estrutura só levanta de novo `structure_cooldown` (90 s) depois do seu lift. O corredor da rampa é a
  faixa de `lane` de cada lado do segmento do nosso start ao topo da rampa da main: nada pousa nele e o
  Ares não constrói produção nele. Os depots não leem a relocation, nem ela os depots.

## Missões

As missões aplicam os [papéis arquiteturais](#papéis-arquiteturais) acima.

**Onde fica cada coisa.** O Ego separa a coordenação global, a infraestrutura comum das missões e os
planners, um pacote por domínio:

```text
bot/ego/
  strategy/                         coordenação global: como está a partida e o que o bot quer
    model.py                        GameAssessment, StrategicIntent, StrategicPosture, PostureGate
    assessment.py                   AssessmentModel: Awareness -> GameAssessment
    strategy.py                     StrategyModel: GameAssessment -> StrategicIntent (gates, persistência)
  missions/                         o que todas as missões compartilham
    lifecycle.py                    MissionStatus, CancelMode, CancelRequest, Lifecycle
    contracts.py                    MissionFeedback, MissionView
  planners/
    __init__.py                     contratos com o Body: Proposal, Command, Domain, os planos
    offense/                        pede unidades ao Engine
      planner.py                    OffensePlanner
      missions/main_attack.py       MainAttackMission
    defense/                        pede unidades ao Engine
      planner.py                    DefensePlanner
      missions/defend_area.py       DefendAreaMission (uma por incidente)
    map_control/                    pede unidades ao Engine
      planner.py                    MapControlPlanner: o que ninguém pediu, no anchor; sem missão
      policies/staging.py           StagingPolicy: onde o exército livre reage (candidatos, distâncias
                                    por terra, score, histerese do ponto mantido)
    intel/                          obter informação por unidades, scans e estruturas
      planner.py                    IntelPlanner -> IntelPlan
      missions/scout.py             ScoutMission
      policies/detection.py         Detection: scans, reserva, Missile Turrets
      policies/sensor_towers.py     cálculo contínuo da barreira de radar
    economy/                        o que comprar; sem missões
      planner.py                    plan -> EconomyPlan
      policies/investment.py        quanto investir: workers, bases, gás, teto de produção, opening
      policies/composition.py       CompositionPolicy: o que construir agora
      knowledge/styles.py           ArmyStyle, BIO, MECH, o sorteio e o anúncio
      knowledge/counter_catalog.py  CounterCatalog, REACH: quem responde a quem e o que cada um atinge
      knowledge/counters/           terran.yml, protoss.yml, zerg.yml
    structure_control/              estado desejado de estruturas existentes; sem missões
      planner.py                    StructureControlPlanner: depots, e junta a relocation
      policies/relocation.py        Relocator: Siege Tank preso, levantar o bloqueador e pousá-lo fora
                                    do caminho

bot/body/behaviors/
  attack.py    ATTACK        hold.py      HOLD
  retreat.py   RETREAT       scout.py     SCOUT
  combat.py    o que attack e hold compartilham
  economy.py, detection.py, sensor_towers.py, structure_control.py  planos diretos
  intel.py     pedido consolidado de Engineering Bay
```

`bot/ego/missions/` contém apenas contratos e lifecycle compartilhados. Missões concretas ficam
em `missions/` dentro do domínio que as possui, regras de decisão em `policies/` e fatos estáticos em
`knowledge/`. Todos os domínios são irmãos em `planners/`, sem agrupamento intermediário, e nenhum
importa outro: o que um planner passa a outro (o anchor do MapControl para a Offense) vai pelo frame.
Não é necessário criar classe base, registry ou Mission por feature.

Um tipo de missão novo entra como um módulo em `missions/` do planner que o governa, e um comando novo
como um behavior com o nome dele. O próximo previsto é `harass/` (N7.3 em
[novas_propostas.md](novas_propostas.md)): `harass/planner.py` com `missions/drop.py` e
`missions/banshee_raid.py`, e os behaviors `move.py`, `load.py` e `unload.py` para os comandos que o drop
pedir. Nenhum deles existe ainda: entram com o gameplay, gatilho e teste próprios.

No Body, o Engine continua a única autoridade de posse (concede, concede em parte, rejeita, transfere) e
nunca lê nem muda o lifecycle de uma missão; os Behaviors de Command executam só as unidades concedidas no frame. Planos diretos não passam pelo Engine.

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
(`mission.updated`) e para `Frame.missions`; a Strategy pode recebê-lo quando precisar, mas hoje
nenhuma decisão dela depende disso, então não recebe.

**Quem usa missões.**

- **Offense:** o `OffensePlanner` guarda admissão, cooldown, a memória de lugares vistos (que a busca de qualquer ataque lê) e o pedido
  de cancelamento; a `MainAttackMission` com montagem, avanço, combate, busca, retirada e reagrupamento.
  IDLE é derivado da ausência de missão, não uma segunda máquina de estados.
- **Intel:** abrir, reabrir ou encerrar antes da saída é do planner, e é dele também a decisão de mandar
  procurar proxy (a suspeita vem da `OpeningBelief` da Awareness, `PROXY_SEARCH_AT`/`PROXY_CONFIDENCE_AT`);
  as fases, a rota concreta e o scout são da missão. A `EarlyScoutMission` adapta a sequência ao que
  encontra: uma natural já de pé não é rechecada, uma main inalcançável não é circulada para sempre, e a
  janela do third vem da raça (`scout_window`). Uma third vazia é resposta com prazo de validade, então em
  vez de estacionar nela a missão entra em `SURVEIL`: a ronda escolhe sempre o lugar visto há mais tempo
  (natural, third, saídas da main, a main), o que vira rotação, recheca as duas expansões sozinha e não
  deixa o SCV parado; um lugar inalcançável cede a vez depois de `surveil_step`. A ronda existe para tapar
  buraco de informação, então termina quando a `confidence` da `OpeningBelief` passa de `READ_ENOUGH`
  (`opening_read`) — três bases de pé e nenhuma estrutura de exército é leitura, não lacuna, e aí o SCV
  vale mais minerando — ou com o fim da janela da opening (`opening_over`). O limiar só vale em `SURVEIL`:
  as fases roteirizadas são o que produz a leitura, e não são puladas por causa dela. A missão não registra
  nada: o que ela põe à vista, a Attention grava, e é isso que as fases leem; a leitura vem da Awareness
  pelo planner.
- **Defense:** uma `DefendAreaMission` por incidente, com o `incident_id` da Awareness ligando a missão ao
  incidente enquanto os atacantes entram e saem. A missão é redimensionada a cada frame pelo incidente, tem
  uma fase só (`DEFENDING`) e termina quando o incidente some; o que ela acrescenta é identidade e
  lifecycle nos logs. O planner nunca pede para encerrar uma. A missão produz as propostas por domínio aéreo/terrestre.
- **MapControl**: sem missão; a `StagingPolicy` guarda o ponto mantido e o
  cache das candidatas. Não é uma reserva estratégica: recebe o que os planners acima deixaram, e escolhe onde
  ficam. Quando a Defense toma parte das unidades num incidente, o resto continua no anchor e as que ela solta
  voltam a ser dele; quando a ofensiva toma o exército, as unidades novas se juntam no anchor.
- **Economy, Detection, StructureControl:** planos de recurso, não pedem unidades ao Engine; mantêm seus
  contratos. O que têm de estado (a janela de scans da Detection, a relocation em curso) fica nas suas
  policies, não em missões.

**Orçamentos.** Não há orçamento de poder por domínio nesta versão: a precedência entre domínios é a
prioridade das propostas (Defense > 0, ofensiva 0, MapControl −1) e a postura da Strategy. Se um orçamento
vier, ele precisa separar a meta desejada, o limite de admissão de novas operações, as unidades ainda
comprometidas numa retirada e a precedência para preempção: uma meta reduzida a zero pode coexistir com
uma operação em WITHDRAW.

**Cancelamento em produção.** A postura DEFEND leva a Offense a pedir cancelamento imediato: Defense
recebe unidades já nesse frame. A postura RECOVER leva ao cancelamento gracioso: o exército volta ao rally
antes de a missão terminar.

## Visualização

- **Bolinhas in-game** (`--spatial-view`): uma esfera por ponto do lattice, cor contínua
  verde (nosso) → amarelo (disputado) → vermelho (inimigo crível), laranja onde a ameaça é
  só possível; contatos com anel de incerteza, dono de cada unidade, anchor do MapControl e painel da
  estratégia (com uma linha da leitura da opening enquanto ela vale alguma coisa).
- **SVG** (`--spatial-snapshot`): `logs/game-*/spatial/field-SSSS.svg` a cada intervalo e em
  toda troca de postura, com o grafo estático de regiões/passagens, ameaça, influência,
  bases, contatos, exército por dono, alvos das concessões e painel das camadas (com a leitura da
  opening enquanto ela vale alguma coisa).
- **Chat in-game** (ligado por padrão, `--no-chat` cala): o bot comenta o que pensa — "Tô sendo
  rushado!", "Isso cheira a proxy.", "Tô indo com tudo." —, anuncia o estilo sorteado no começo e
  fecha com `gg`. Tudo o que ele fala também vira `chat.said` no log.
- **Viewer** ([logs/viewer.html](../logs/viewer.html)): carregue a pasta do jogo. Summary,
  Decision Timeline (trilhas agrupadas por camada — incluindo `aggression`/`greed` e `proxy` da
  opening —, inspetor de todas as camadas no instante selecionado, com a seção "Opening read"
  (scores, natural, third, cobertura e o que foi visto), SVG mais próximo, dicas de contradição e
  causas das mudanças), Events, Attention, Awareness e Engine.

## Catálogo de eventos

Envelope: `schema` (5), `run`, `seq`, `iteration`, `event`, `component` (a camada),
`game_time`, `data`. Resumos de estado passam por `ChangeGate` (mudança + heartbeat de
10 s); decisões são escritas quando mudam.

A taxonomia acompanha o dono da decisão: `strategy.*`, `planner.*`, `mission.*`, `engine.*`
e `behavior.*`. Planos não carregam resultados de execução: `behavior.intel_executed` relata
scan e construções entregues ao Ares. `engine.commanded` registra a instrução associada ao grant,
não uma confirmação de sucesso no jogo. Tempos: attention, awareness, strategy, planners, engine,
behaviors e logs. O viewer normaliza nomes de eventos anteriores ao schema 5 ao carregar logs antigos.

| Evento | Camada | Quando | Dados |
| --- | --- | --- | --- |
| `game.started` | logs | `on_start` | `map`, `race`, `enemy_race`, `opening`, `build` {`commit`, `branch`}, `config_fingerprint`, `configs`, `lattice`, `bounds` |
| `map.topology_built` | attention | `on_start` | `regions`, `passages`, `chokes`, `blocked_passages[]` {`passage_id`, `state`, `blocker_type`, `blockers`, `regions`}, `expansions`, `unresolved_expansions`, `own_start_region`, `enemy_start_region` |
| `map.passage_changed` | attention | uma passagem abre ou fecha (mineral wall minerada, rocks derrubados) | `passage_id`, `transition` (`CLOSED -> OPEN`), `from`, `to`, `blocker_type` (`mineral_wall`/`destructible`/`mixed`), `blockers_left`, `regions`, `position` |
| `planner.production_kept_clear` | planners | `on_start` | `production_sites` (da main), `sites` (os do corredor da rampa), `cleared` (quantos o placement do Ares tinha) |
| `game.ended` | logs | `on_end` | `result` |
| `attention.observed` | attention | bases, fim do opening, inimigos à vista ou contatos de radar mudam; amostra a cada 5 s | `minerals`, `vespene`, `supply_used`, `supply_cap`, `workers`, `army_units`, `army_supply`, `army_power`, `visible_enemy_units`, `visible_enemy_structures`, `radar_blips`, `bases`, `opening`, `opening_done`, `upgrades[]`, `structures` {tipo: contagem, prontas ou não} |
| `awareness.updated` | awareness | mudança de contatos/poder/ameaça por base, contatos escondidos, primeiro camuflado, heartbeat | `contacts`, `visible_contacts`, `enemy_power`, `seen_enemy_power`, `expected_enemy_power`, `estimated_enemy_power`, `enemy_uncertainty`, `enemy_coverage`, `own_power`, `danger`, `danger_now`, `cloak_seen_at`, `hidden_contacts[]`, `bases[]` {`base_id`, `position`, `is_main`, `threat`, `recent_threat`, `pressure`, `cover`, `balance`, `air_share`, `center`}, `incidents[]` {`incident_id`, `contacts`, `center`, `power`, `ground_power`, `air_power`, `confidence`, `threat`, `pressure_by_base`} (escrito também quando os membros de um incidente mudam), `strongest_contacts[]` (com `hidden`), `field` {`samples`, `friendly`, `contested`, `enemy`, `threatened`, `max_threat`} |
| `opening_scout.expansion_checked` | attention | o estado da natural ou do third inimigo muda | `expansion` (`natural`/`third`), `status` (`UNKNOWN`/`ABSENT_CONFIRMED`/`PRESENT`), `previous`, `position`, `last_checked_at`, `first_seen_at`, `absent_at`, `appeared_between` (vista vazia, vista de pé) |
| `opening_scout.structure_seen` | attention | mais uma estrutura inimiga de um tipo é vista no early game | `structure`, `count_seen`, `first_seen_at`, `last_seen_at`, `gases_seen`, `workers_seen`, `proxy_structures_seen`, `main_coverage` |
| `awareness.opening_updated` | awareness | um fato novo, a leitura muda de faixa (1 casa) ou heartbeat | `summary` (uma linha: `t=1:52 race=Protoss natural=ABSENT_CONFIRMED@1:34 third=UNKNOWN coverage=0.81 \| aggression=0.74 …`), `race`, `natural` e `third` {`status`, `last_checked_at`, `first_seen_at`, `absent_at`, `appeared_between`}, `observed` {estrutura: contagem, `gases`, `workers`, `combat_units`, `proxy_structures`}, `main_coverage`, `last_updated`, `belief` {`aggression`, `greed`, `tech`, `proxy`, `confidence`}, `evidence` {cada termo da leitura} |
| `opening_scout.phase_changed` | missions | o early scout abre, muda de fase ou termina | `mission_id`, `phase` (`REQUESTING`, `CHECK_NATURAL`, `ENTER_MAIN`, `CIRCLE_MAIN`, `RECHECK_NATURAL`, `CHECK_THIRD`, `SURVEIL`, `PROXY_SEARCH`, `COMPLETE`), `previous`, `since`, `reason` (em `SURVEIL`: `third_found`, `third_empty`, `third_window_over`, `no_third_known`), `status`, `target`, `proxy_search`, `inputs` {`set_out`, `proxy_ordered`, `proxy_index`, `proxy_points`, `watching`, `watchpoints`}; em `COMPLETE` o motivo diz o que a encerrou (`opening_read`, `opening_over`, `proxy_found`, `proxy_search_done`, `proxy_search_timed_out`, `nowhere_left_to_look`, ou o motivo do cancelamento) |
| `opening_scout.proxy_search_started` | missions | o planner manda o scout procurar proxy (uma vez) | `mission_id`, `reason`, `target`, `inputs` |
| `strategy.posture_changed` | strategy | toda troca de postura (e a primeira), nunca por heartbeat | `posture`, `previous` (null na primeira), `reason`, `because` {os valores salientes da troca}, `summary` (uma linha: `DEVELOP -> DEFEND (home_threatened): threat=HIGH threat_level=0.71 army_position=-0.18 power_spike=0.00`), `threat` (CLEAR/LOW/ELEVATED/HIGH), `emergency`, `assessment` {como abaixo}, `gates` {postura: {`score`, `open`, `since`}} |
| `strategy.decided` | strategy | troca de postura ou de emergência, heartbeat | `posture`, `previous`, `since`, `reason`, `emergency`, `defense`, `army`, `economy`, `risk`, `assessment` {`threat_level`, `threat`, `army_position`, `economy_position`, `enemy_vulnerability`, `power_spike`, `confidence`, `setback`, `upgrade_spike`, `supply_spike`}, `inputs` {`danger`, `danger_now`, `army_share`, `own_power`, `enemy_power`, `seen_enemy_power`, `expected_enemy_power`, `estimated_enemy_power`, `enemy_uncertainty`, `planned_enemy_power`, `own_lost`, `enemy_lost`, `own_bases`, `known_enemy_bases`, `expected_enemy_bases`, `fresh_upgrades`, `supply_used`}, `scores` {postura: score do gate}, `gates` |
| `planner.proposed` | planners | o conjunto ranqueado de propostas muda | `proposals[]` {`proposal_id`, `owner`, `priority`, `command`, `target`, `count`, `minimum_power`, `must_attack`, `demand_id`, `mission_id`, `unit_types`, `reason`, `inputs`} |
| `planner.map_control_planned` | planners | origem, razão, anchor (grade de 3), fallback, ponto mantido do `staging` (e quando foi escolhido) mudam; heartbeat de 30 s | `anchor`, `source` (`threatened_base`, `staging`, `legacy`), `reason` (`hold_<staging|rally>_<postura>`), `posture`, `advance`, `fallback` (`no_candidates`, `no_enemy_route` ou null), `passage` e `region` (do ponto do `staging` que pôs o anchor, ou null), `staging` {`anchor`, `switch` (`kept`, `initial`, `held_invalid`, `bases_changed`, `posture_changed`, `awareness`), `since`, `previous`, `advance`, `scale` (D), `bases`, `candidate_count`, `selected`, `top[]` (o melhor de cada região, até 5, melhor primeiro); cada ponto {`anchor`, `region`, `passage`, `reaction`, `worst` e `worst_base` (a base respondida por último e a resposta, em células), `mean` (distância média às bases), `front` (à frente da base média no caminho do inimigo, em células; negativo atrás), `choke`, `threat`, `support`, `control`, `exposure`, `score`}} ou null |
| `planner.offense_planned` | planners | estágio, `since`, bloqueio, alvo (tag ou grade de 3) mudam | `stage`, `previous`, `since`, `reason`, `blocked_by`, `committed_power`, `target`, `target_tag`, `target_kind` (`known_base`, `known_structure`, `flying_structure`, `enemy_start`, `search`), `inputs` {`own_power`, `army_share`, `power_spike`, `offensive`, `supply_used`, `assembled_share`, `committed_power`, `stage_for`, `cooldown_left`, `known_structures`, `squad_units`, `squad_power`, `core_power`, `local_enemy_power`, `local_share` (−1 sem inimigo), `contested`, `clear_for`, `start_cleared`}, `fight` {`center`, `own_power`, `enemy_power`, `share`, `enemy_center`} ou null, `mission_id` e `mission_status` (a missão avançada ou aberta no frame, também no frame em que termina; null em IDLE) |
| `mission.updated` | missions | uma missão abre, muda de fase, recebe pedido de cancelamento ou termina | `missions[]` {`mission_id`, `owner`, `kind` (`main_attack`, `defend_area`, `early_scout`), `status` (`ACTIVE`, `COMPLETED`, `FAILED`, `CANCELLED`), `phase`, `since`, `reason`, `cancel` {`mode`, `reason`, `time`} ou null, `proposals[]`, `granted_units`, `granted_power` (o que a alocação anterior lhe deu)} |
| `planner.economy_planned` | planners | o plano muda (a composição com 2 casas) | `active`, `workers`, `gas`, `bases`, `expand`, `freeflow`, `reason`, `composition[]`, `inputs` {`workers`, `bases`, `saturated_at`, `expansion_sites`, `strategy_economy`, `danger`, `production_per_base`, `gas_worker_share`, `upgrades_done`, `enemy_seen_power`}, `upgrades[]`, `orbitals`, `mules`, `interrupt_opening`, `max_production`, `addons`, `addons_on`, `reactor_share`, `army` |
| `behavior.intel_executed` | behaviors | construção muda ou scan executado | `scanned_by`, `building[]` (inclui Engineering Bay compartilhada) |
| `behavior.spawn_executed` | behaviors | `freeflow` ou razão do spawn mudam | `freeflow`, `reason` (`plan_inactive`, `plan_freeflow`, `composition_met`, `composition_short`), `counts` {tipo: contagem do Ares} |
| `behavior.micro_executed` | behaviors | alguma unidade usou Stim (em `ATTACK` ou `HOLD`), ou os Medivacs que escoltam mudam | `stimmed[]`, `escorts[]` |
| `planner.detection_planned` | planners | todo scan; turrets, Engineering Bay, reserva, razão, foco mudam | `scan`, `turrets[]`, `engineering_bay`, `energy_reserve`, `reason`, `focus` (`threat`, `offense`, `economy`), `inputs` {`hidden_enemies`, `cloak_seen_at` (−1 antes), `army_near_hidden`, `orbitals_with_scan`, `active_scans`, `scan_held`} |
| `planner.sensor_towers_planned` | planners | torres que faltam, requisito ou razão mudam | `sites[]` {`site_id`, `base`, `target`}, `engineering_bay`, `reason`, `inputs` |
| `planner.structures_planned` | planners | depots a abaixar/levantar ou razão mudam | `lower`, `raise`, `reason` (`no_depots`, `enemy_near`, `enemy_recently_near`, `no_enemy_near`), `inputs` {`depots`, `lowered`, `enemy_near`, `recently_near`, `ground_enemies`, `friendly_on_raising`, `nearest_ground_enemy` (só com depot e inimigo terrestre)} |
| `planner.structure_relocation` | planners | cada passo de uma relocation | `transition` (`tank_stuck`, `blocker_selected`, `lifting`, `tank_moving`, `tank_gone`, `tank_still_stuck`, `relocating`, `no_landing_site` — uma vez por relocation —, `landing`, `relocation_complete`, `relocation_aborted`), `reason` (em `tank_stuck`: `blocker_selected`, `no_blocker`, `cooldown`, `relocation_active`; em `blocker_selected`: `no_add_on`, `with_add_on`; em `relocating`: `site_found`, `retry`, `back_to_origin`; em `relocation_aborted`: `structure_lost`, `lift_failed`), `tank`, `structure`, `site` (origem do bloqueador, site de pouso ou onde pousou), `at` (onde o Tank estava, em `tank_stuck` e `blocker_selected`), `inputs` {`stuck_for`, `moved`, `destination_distance`, `nearest_production`, `gap`, `candidates`, `has_add_on`, `ahead`, `waited`, `free_sites`, `flight`, `sites`, `took`, conforme o passo} |
| `engine.granted` | engine | alguma concessão muda | `grants[]` {`proposal_id`, `owner`, `mission_id`, `priority`, `requested`, `minimum_power`, `granted`, `granted_power`, `status`, `reason`, `tags`, `types`}, `transfers[]` {`tag`, `type`, `from`, `to`}, `unassigned` |
| `engine.commanded` | engine | comando, alvo (grade de 3), unidades ou missão de uma concessão mudam | `proposal_id`, `owner`, `command`, `target`, `tags`, `types`, `priority`, `reason`, `demand_id`, `mission_id`, `inputs`, `strategy` {`posture`, `reason`, `defense`, `risk`}, `awareness` {`danger`, `contacts`, `enemy_power`}, `attention` {`army_units`, `visible_enemy_units`}; `tags: []` e `reason: no_units_granted` quando a concessão acaba |
| `logs.frame_perf` | logs | heartbeat | `frames`, `last_ms`, `max_ms` por camada |
| `logs.snapshot_written` / `logs.snapshot_failed` | logs | SVG escrito / falhou | `path`, `trigger` (`interval`, `posture_changed`), `posture`, `elements`, `bytes`, `render_write_ms` / `error` |
| `chat.said` | logs | toda linha que o bot manda para o chat da partida | `topic` (`army`, `rushed`, `emergency`, `pressure`, `commit`, `recover`, `develop`, `cloaked`, `proxy`, `aggression`, `greed`, `tech`, `gg`), `line` |
| `logging.record_rejected` | logs | um registro não era JSON estrito | `rejected_event`, `rejected_component`, `error` |

## Comandos

```text
.venv\Scripts\python.exe run.py
.venv\Scripts\python.exe run.py --bot-log events
.venv\Scripts\python.exe run.py --no-chat
.venv\Scripts\python.exe run.py --matrix builds --enemy-race Zerg
.venv\Scripts\python.exe run.py --matrix wide --time-limit 1200
.venv\Scripts\python.exe run.py --matrix file
.venv\Scripts\python.exe run.py --army mech --enemy-race Zerg --difficulty CheatInsane --ai-build Macro
.venv\Scripts\python.exe run.py --bot-log events --spatial-view
.venv\Scripts\python.exe run.py --bot-log events --spatial-snapshot
.venv\Scripts\python.exe run.py --bot-log events --spatial-view --spatial-snapshot --spatial-view-spacing 6
.venv\Scripts\python.exe logs\open_viewer.py
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m ruff check bot tests harness run.py bench.py
.venv\Scripts\python.exe bench.py run --out bench\<rótulo>
.venv\Scripts\python.exe bench.py run --out bench\<rótulo> --matrix-file matrizes\protoss-rush.yml
.venv\Scripts\python.exe bench.py run --out bench\<rótulo> --matrix base --time-limit 1200
.venv\Scripts\python.exe bench.py run --out bench\<rótulo> --matrix wide --time-limit 1200
.venv\Scripts\python.exe bench.py run --out bench\<rótulo> --matrix base --maps PersephoneAIE_v4 --races Zerg --difficulties CheatInsane --ai-builds Macro Timing --armies bio mech --time-limit 1200
.venv\Scripts\python.exe bench.py summarize bench\<rótulo>
.venv\Scripts\python.exe bench.py compare bench\<base> bench\<desafiante>
```

## Ainda não implementado

Cada item entra quando um problema de gameplay medido pedir. Os modelos já escritos no branch
`matematização` que servem a vários deles estão em [migration-map.md](migration-map.md). O que já está em
andamento, ou decidido como o próximo, está em [staging/](staging/README.md).

- **Informação:** a Strategy ainda não consome a `OpeningBelief` (Attention, Awareness e Intel já a
  produzem e a registram); nenhum limiar ou peso da leitura da opening foi medido em partida real;
  scouting depois do early game (o SCV sai uma vez, antes de 240 s, e a ronda dele acaba com a janela
  da opening), belief
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
  por matchup. Composição por catálogo, fallback de sobrevivência e interrupção por opening parado já estão implementados.
  O documento [economia-e-builds.md](staging/economia-e-builds.md) registra o design histórico.
- **MapControl:** anchor em DEFEND alternando entre bases de ameaça quase igual, e entre a base ameaçada e
  o staging quando a Strategy entra e sai de DEFEND; um só ponto para o exército todo, sem dividir; bases
  com o mesmo peso (main e natural não valem mais que as outras); distância reta dentro de uma região
  (subestima regiões côncavas); a exclusão das regiões vizinhas ao start inimigo é uma regra fixa; uma ameaça
  pequena perto de uma base, fora de DEFEND, afasta o anchor dela (a Defense cuida do incidente). O
  `staging` é sensível a `advance`: com 0,6 o Persephone volta para a rampa da main com 2 bases (o choke da
  natural ganha por 0,005–0,017), com 0,8 o anchor de 7 bases passa do meio do mapa (Incorporeal 0,35 D,
  Torches 0,39 D); com 0,7 o Pylon de 7 bases já fica a 0,43 D do start inimigo. O `pressure_advance` (0,8)
  de PRESSURE e COMMIT usa esse mesmo ponto sem medição própria.
- **Estratégia:** nenhum limiar, peso ou `stance_dwell` da avaliação e das posturas foi medido em partida
  (bench pendente). Onde os dados ainda não sustentam uma avaliação confiável:
  - o prior `expected_enemy_power` (0,1 Marine/s até 100) só cresce: matar o exército inimigo não baixa a
    estimativa abaixo dele, então `army_position` quase não sobe depois de uma luta vencida no meio do jogo
    e COMMIT raramente abre antes de o avistamento superar o prior;
  - `enemy_vulnerability` só vê mortes à nossa vista; exército inimigo fora de posição, bases desprotegidas,
    defesa estática e troca de tech não entram;
  - `economy_position` compara só bases, e o lado inimigo é quase sempre prior (nenhum scouting depois de
    240 s); por isso nenhuma postura o lê;
  - `power_spike` conhece upgrades e supply; tech nova, composição contra o inimigo e ciclos de produção não;
  - `confidence` mede avistamento, não frescor: um exército visto há 3 minutos ainda conta como evidência;
  - o Intel lê a postura, mas só tem scan de detecção e o scout inicial; falta obter informação no meio do
    jogo (scan ou unidade de reconhecimento) para confirmar a ameaça ou preparar a ofensiva.
  Renomear `risk`.
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
políticas no mesmo `planner.map_control_planned`, a antiga em `shadow`). O anchor novo coincide com o antigo
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
A política `passage` (`anchor.py`) e o `shadow` do log foram removidos depois desta comparação, sem uma
matriz própria do `staging`.

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
