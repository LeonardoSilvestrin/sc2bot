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
exército, o modelo de combate); as `*Config` de ajuste (limiares, pesos) ficam com o Planner ou a Policy
que as lê. `policies/` e `knowledge/` são classificação, não subsistema: não há classe base, registry nem
lifecycle de Policy, e cada uma tem a interface de que o seu Planner precisa (uma função, uma classe com
estado). A intenção da Strategy (`StrategicIntent`) é outra coisa: contexto global publicado igual para
todos os planners, não a Policy de um Planner. A Strategy não publica política por domínio; o que uma
postura significa para a economia, a ofensiva ou o MapControl é decisão do planner de cada um
([tabela](planners/README.md#a-postura-em-cada-planner)).

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
| AWARENESS | [bot/awareness/](../bot/awareness/) | `AwarenessState` | Pinta o mapa ao longo da partida. Memória de contatos com confiança `exp(-idade/τ)` e incerteza `min(cap, v·idade)`; esquece por morte confirmada, posição vista vazia (após carência) ou confiança < piso. Pressão por base com a ameaça lembrada (`recent_threat`, τ = `threat_memory`), incidentes de ameaça (`ThreatIncident`), o exército inimigo conhecido e visto vivo e o **observador** dele (`enemy_army.py`, `EnemyArmyBelief`: filtro de Kalman do exército e da produção por worker, com a economia acreditada — bases e workers — como entrada, as mortes vistas como entrada conhecida e o visto vivo como medição censurada; média, σ, cobertura), contatos escondidos (camuflados sem detecção, à vista) e quando um exército camuflado foi visto pela primeira vez, e campo de influência. `opening/`: lê os fatos da Attention como `OpeningBelief` — `aggression`, `greed`, `tech` e `proxy` contínuos e independentes, com a `confidence` que cobertura, checagens e atualidade lhe dão; as expectativas por raça ficam em `opening/knowledge.py`. Descreve; não escolhe margem nem prioridade. |
| EGO / strategy | [bot/ego/strategy/](../bot/ego/strategy/) | `GameAssessment`, `StrategicIntent`, `StrategicPosture` | `assessment.py` transforma a Awareness numa avaliação contínua (ameaça, posição militar, revés, power spike, confiança); `strategy.py` escolhe a postura (`RECOVER`, `DEFEND`, `DEVELOP`, `PRESSURE`, `COMMIT`) com histerese e publica o `StrategicIntent`. Não conhece missão nenhuma nem escolhe lugar no mapa. Detalhes: [planners/strategy.md](planners/strategy.md). |
| EGO / planners / common | [bot/ego/planners/common/](../bot/ego/planners/common/) | `Proposal`, os planos, `MissionStatus`, `CancelMode`, `Lifecycle`, `MissionFeedback`, `MissionView` | O que todo planner compartilha: `contracts` (o que entrega ao Body) e `mission` (o que é uma missão: status terminal, pedido de cancelamento e modos, o feedback que ela lê e o resumo que reporta). Nenhuma missão concreta mora aqui; tudo é reexportado por `bot.ego.planners`. |
| EGO / planners | [bot/ego/planners/](../bot/ego/planners/) | `Proposal`, `Command`, `IntelPlan`, `EconomyPlan`, `StructurePlan` | Decidem o que deve ser feito (tarefa, alvo, prioridade, requisitos) sem nomear unidades, um pacote por domínio: `defense/`, `offense/` e `map_control/` pedem exército ao Engine; `intel/` obtém informação por um SCV, scans e estruturas; `economy/` diz o que comprar; `structure_control/` opera estruturas existentes. Um documento por planner em [planners/](planners/README.md). |
| BODY / engine | [bot/body/engine.py](../bot/body/engine.py) | `EngineResult` | Só alocação. Ordena por `(-priority, owner, proposal_id)` e concede cada unidade de exército a no máximo uma proposta. Restrições duras vêm antes de qualquer ordem: `unit_types`, `must_attack` (`GROUND`/`AIR`) e, num pedido de poder, `power > 0`. Entre as elegíveis livres, as que já eram da proposta primeiro, depois as mais próximas. Pede-se `minimum_power` (unidades até atingir o poder), `count` ou todas as livres; cada `Grant` traz `power`, `status` (`FULL`/`PARTIAL`/`REJECTED`) e `reason`. Um pedido de todas as livres que não recebe nenhuma fica `REJECTED` (`eligible_units_taken`/`no_eligible_units`). Workers só são elegíveis para propostas que pedem um tipo de worker, só saindo da mineração (role `GATHERING`) ou já sendo da proposta. `released` lista quem perdeu o dono. O `EngineResult` é o feedback que as missões leem no frame seguinte, sem nomear unidades; o Engine é o único registro de posse e nunca lê nem muda o lifecycle de uma missão. Não comanda nada. |
| BODY / behaviors | [bot/body/behaviors/](../bot/body/behaviors/) | — | Executam os grants, despachados por `Command`. `attack` (`ATTACK`, de Defense ou da ofensiva): `AMove`, Siege Tank decide o siege sem ficar preso ao ponto; Marine/Marauder usam Stim com inimigo a ≤ 10 e ≥ 50 % de vida; Medivac vai ao centro do próprio grupo. `retreat` (`RETREAT`): path ao ponto sem lutar, Siege Tank sai do siege. `hold` (`HOLD`): `PathUnitToTarget` até o ponto, `AMove` com inimigo a ≤ 10 (bio usa Stim pela mesma regra do `attack`), Siege Tank fica sieged perto do ponto. `scout` (`SCOUT`): tira o worker da mineral, role `SCOUTING`, path sem evitar perigo. `economy`: para o build runner do Ares quando o plano interrompe o opening; workers liberados voltam a `GATHERING`, `Mining`, um add-on por frame antes do `MacroPlan` (Reactor ou Tech Lab na estrutura `addons_on`, pelo `reactor_share`), `MacroPlan` (Orbital antes de `BuildWorkers`, pesquisa — `ExactResearch` e `UpgradeController` — antes do `SpawnController`, depois `ProductionController`, nesta ordem, com o teto de produção do plano) e MULEs, sem gastar a reserva de scan nem usar o Orbital que escaneou; devolve o `SpawnMode` (com a composição inteira exatamente na proporção, o `SpawnController` roda em `freeflow` naquele frame). `detection`: scan com o Orbital pronto de mais energia; uma Missile Turret por vez após o pré-requisito consolidado pelo Intel, pelo `BuildStructure` do Ares na expansão mais próxima da base. `execute` devolve `BodyReport` (`spawn`, `micro`, `detection`, `sensor_towers`, `infrastructure`). `structure_control`: abaixa e levanta os depots do plano; levanta as estruturas da relocation (cancela o que treinam antes, um item por frame: ocupada, não levanta; já levantando, não repete a ordem), e o `economy` não treina nem põe add-on nelas enquanto isso; as pousa pelo `move_structure` do Ares; no `on_start`, `keep_clear` marca como ocupados no placement do Ares os sites do corredor da rampa, e o macro do Ares não constrói neles. `combat` guarda o que `attack` e `hold` compartilham: decisão de siege, `AMove` e a regra do Stim. O Siege Tank decide o siege também contra os inimigos que o Ares lembra fora de visão; o Stim e a saída do path no HOLD só contam inimigos à vista neste frame. |
| LOGS | [bot/logs/](../bot/logs/) | — | Log JSONL, snapshots SVG do campo, overlay in-game e o chat, onde o bot diz em voz alta o que está pensando (`chat.py`: postura nova, emergência, camuflado visto e a leitura da opening; uma linha por vez, `gap` de 12 s, um assunto não se repete antes de `topic_cooldown`, teto de `max_lines` por partida, escolha determinística, e `gg` no fim). Falar é async e o frame não é: `observe` só enfileira, e `BotBandido._speak` manda — engolindo qualquer erro. Nenhum deles muda decisão nem derruba partida. |
| HARNESS | [harness/](../harness/), [bench.py](../bench.py) | `Game`, `GameSpec`, `result.json` | Fora do bot, um módulo por assunto: `config.py` é a **lista** que se escreve à mão — o `harness/matrix.yml`, uma linha por partida (`race`, `strategy`, `map`, mais `army`, `difficulty`, `games`, `time_limit`), o que a linha não diz vem de `defaults`, `games: 10` pede dez daquela partida (cada uma com a sua seed), `map: random` sorteia um mapa por execução (o mesmo para todas as linhas que pedem random, enquanto a linha que nomeia um mapa fica nele) — é YAML porque YAML aceita comentário, e é ali no topo do arquivo que mora a colinha com todos os nomes que cabem; os nomes são conferidos contra as tabelas do jogo e do bot antes de qualquer partida subir, então um erro de digitação custa uma mensagem (com a linha do arquivo, quando é o YAML que não fecha) e não uma tarde; `matrix.py` é a **tabela** fixa de partidas, uma linha por jogo (`Game(mapa, raça, abertura da IA)`), `BASE` com as 9 em que uma fatia é medida (cada raça contra `Rush`, `Macro` e `RandomBuild`, porque uma mudança que só aparece contra uma abertura não é mudança) e `WIDE` com essas 9 nos três mapas de `WIDE_MAPS` (27, e não nos sete da rotação, porque 63 partidas não respondem melhor se o mapa estava carregando o resultado); `MAPS` é a rotação — o pool da temporada, sete mapas — e é dela que um `random` sorteia, uma vez por execução (todas as partidas que pedem `random` no mesmo mapa, outro mapa na próxima), então duas execuções que precisam ser comparadas fixam o mapa na linha ou com `--maps` — o `compare` avisa quando foram mapas diferentes. Qual matriz uma execução joga sem nenhum argumento mora nesse arquivo (`DEFAULT_MATRIX` = `file`, a lista do `harness/matrix.yml`, para o `bench.py`; `DEFAULT_LAUNCHER` para o `run.py`), que é onde se troca isso em vez de nos argumentos de uma configuração de launch; com `--matrix file` valem `--matrix-file`, `--seed` e `--time-limit`, e as colunas de uma tabela (`--maps`, `--races`, `--difficulties`, `--ai-builds`, `--armies`, `--games`) são recusadas com uma mensagem porque o arquivo já diz o que jogar; `games_of` devolve a tabela, ou o produto do eixo que for dado à mão (`--maps`, `--races`, `--ai-builds` substituem aquela coluna), e `matrix` transforma jogos em `GameSpec` (× dificuldade × estilo do bot `--armies` × `--games` repetições, cada repetição com a sua seed; sem `--armies` o bot sorteia e o `game_id` não leva sufixo). `outcome.py`: o que aconteceu com uma partida. `record.py`: o `result.json` que liga o desfecho a commit, SHA do Ares, árvore suja, fingerprint da configuração, mapa, oponente, seed, replay e JSONL. `summary.py`: `summarize` e o intervalo de Wilson. O launcher lê as mesmas listas: `run.py --matrix builds` joga as três aberturas no mesmo mapa e raça (3 partidas), `--matrix wide` percorre as 27 e `--matrix file` joga a lista do `harness/matrix.yml`, cada partida com o mapa, a raça, o army, a dificuldade e a seed da sua linha, com a janela aberta e sem registrar nada — para medir é o `bench.py`; cada partida de uma sequência é cortada em `--time-limit` (30 min por padrão) e roda com um bot novo. Nomes de raça, dificuldade e build são conferidos antes de qualquer partida subir, e um mapa que não está instalado também, cada partida num processo com timeout de relógio; `result.json` liga resultado (`victory`, `defeat`, `tie`, `timeout`, `crash`, `no_result`, `not_played`) a commit, SHA do Ares, árvore suja, fingerprint da configuração, mapa, oponente, seed, replay e JSONL. Uma partida que reportou resultado com o relógio do bot em 0 é `not_played` (o python-sc2 resigna no primeiro passo quando o `on_start` levanta): conta em `games`, não em `played`, fica fora da taxa de vitória e da duração média, e `run` a joga de novo em vez de pular. `summarize` recalcula o desfecho do que cada registro guardou, então execuções antigas são resumidas pela regra atual; `compare` agrega com intervalo de Wilson. O fingerprint cobre `Layers.configs()`, incluindo estilo, composição (digest do modelo de combate, já com os dados do cliente) e investment; constantes fora das configs ainda exigem comparação pelo commit. |

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
  - `produced_enemy_types` (produzido, por tipo): `Σ poder·exp(-idade / production_memory)` de toda unidade de
    exército já vista, **morta ou viva**, cada uma pelo maior poder com que foi vista, τ = 360 s
    (`production_memory ≥ army_memory`). É o que o inimigo constrói, não o que ele tem: um Lurker morto ainda
    diz que existe Lurker Den. Lido pela composição.
  - O exército inteiro é estado de um observador ([enemy_army.py](../bot/awareness/enemy_army.py)), não um
    prior por tempo: previsto pela economia que o paga, baixado pelo que se vê morrer e corrigido pelo que se
    vê vivo. Por frame, com `Δt` desde o anterior:
    - bases `B = max(townhalls lembrados, min(expansões / 2, 1 + t / base_interval) − townhalls vistos morrer)`,
      `base_interval` 150 s;
    - workers `W ← min(vaga, W + worker_rate · Δt) − workers vistos morrer`, nunca menos que os workers
      lembrados, com `vaga = min(80, 22 · B)`, `W₀ = 12`, `worker_rate` 0,1/s;
    - produção `u = min(W, 22 · B) · f(t)`, `f` a fatia da renda em exército: 0,15 até 240 s, rampa linear até
      0,65 aos 600 s;
    - exército `A ← A + Δt · g · u − D`, com `D` o poder inimigo visto morrer no frame (preço do último
      avistamento) e `g` o poder que a renda de um worker compra por segundo (prior 0,008, σ 0,003, limites
      0,002–0,03), **no estado**: o filtro é de `x = (A, g)`, `F = [[1, Δt·u], [0, 1]]`, `H = [1, 0]`,
      `Q = diag(0,3, 1,5·10⁻⁸)·Δt`. É isso que o torna adaptativo: uma inovação positiva sobe `A` e `g`
      pela covariância cruzada, então um inimigo que produz mais que o prior (a renda trapaceada do
      CheatInsane) é aprendido, e um que produz menos também;
    - teto `cap = 0,9 · (200 − W)` (o supply que os workers deixam); no teto não há produção, e a variância
      de `A` fica limitada a `cap_sigma²` (15²): ninguém planeja contra mais exército do que cabe no supply;
    - **limite inferior**: o visto vivo `y` é restrição, `A ≥ y`, e não medição de `A`. Com a previsão
      abaixo dele, a estimativa é **projetada** na restrição (o método de projeção do Kalman com restrições):
      `A = y` e `g += P_Ag / P_AA · (y − A)`, com a covariância intacta. Ver 40 Marines vivos diz que o
      inimigo tem pelo menos 40, não que não há mais nada: como medição de igualdade com `R = 2²` (a
      primeira versão) o σ caía de 71 para 2 depois de uma luta, com 10–30 a mais fora de vista;
    - medição, **cobertura**: `c` = fração das bases inimigas conhecidas (ou do start, sem nenhuma) em visão
      agora. Com `c > 0` e `y < A`, `y` mede `A` por cima com `R = 15² / (c · Δt)`: quanto mais tempo e mais
      das bases dele se olha sem achar o exército, mais se acredita que ele não existe;
    - sem nada visto, a previsão dá 11 aos 300 s, 37 aos 480 s, 74 aos 600 s e o teto (108) aos ~700 s; nos
      replays do `bench/t0` o exército pago pelo inimigo foi 12–16, 39–60 e 85–109, e pelo próprio bot 4–8,
      27–38 e 54–86.
  - `estimated_enemy_power = max(conhecido, visto vivo, A)`, `enemy_sigma = σ_A`, `enemy_coverage =
    conhecido / estimado` (1 enquanto o estimado é 0).
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
- Avaliação (`GameAssessment`), postura (`StrategicIntent`), preferências e como cada planner lê a postura:
  [planners/strategy.md](planners/strategy.md) e [planners/README.md](planners/README.md#a-postura-em-cada-planner).
- Incidente: atacantes (poder > 0) ao alcance de alguma base, ligados em cadeia a
  ≤ `incident_link` (12) um do outro, quantas bases tocarem. O id segue os membros: cada grupo herda o
  id do incidente do frame anterior com quem mais compartilha membros (pares resolvidos por mais membros
  em comum, depois menor tag do grupo, depois menor tag que o incidente anterior tinha; cada id vai a um
  grupo só), quaisquer que sejam os contatos que entram ou saem. Numa divisão, fica com a parte que leva
  mais do incidente; numa fusão, com o incidente que traz mais membros. Um grupo sem herança é
  `incident:<menor tag>`, com sufixo `-1`, `-2`, … enquanto esse id estiver em uso. Poder `Σ poder·confiança` (terrestre e aéreo), centro ponderado
  por esse poder, pressão em cada base afetada e `threat = S(maior pressão numa base / full_pressure)`.
  Os incidentes somam a pressão de cada base.
- O que cada planner faz com tudo isso (fórmulas, fases, parâmetros e limitações) está num documento por
  planner, em [planners/](planners/README.md): [Defense](planners/defense.md), [Offense](planners/offense.md),
  [MapControl](planners/map-control.md), [Intel](planners/intel.md) (scout, detecção e Sensor Towers),
  [Economy](planners/economy.md) (investment, estilo, modelo de combate, composição, SURVIVE e a execução pelo
  `MacroPlan` do Ares) e [StructureControl](planners/structure-control.md) (depots e relocation).

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
  planners/
    __init__.py                     reexporta common/: o que os planners e o resto do bot importam
    common/                         o que todo planner compartilha
      contracts.py                  contratos com o Body: Proposal, Command, Domain, os planos
      mission.py                    o que é uma missão: MissionStatus, CancelMode, CancelRequest,
                                    Lifecycle, MissionFeedback, MissionView
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
      missions/early_scout.py       EarlyScoutMission: o SCV que lê a abertura inimiga
      policies/detection.py         Detection: scans, reserva, Missile Turrets
      policies/proxy.py             onde procurar um proxy, na nossa metade do mapa
      policies/sensor_towers.py     cálculo contínuo da barreira de radar
    economy/                        o que comprar; sem missões
      planner.py                    plan -> EconomyPlan
      policies/investment.py        quanto investir: workers, bases, gás, teto de produção, opening
      policies/composition.py       CompositionPolicy: o que construir agora
      knowledge/styles.py           ArmyStyle, BIO, MECH, o sorteio e o anúncio
      knowledge/combat.py           CombatModel: dps de um tipo contra outro, poder, prior por raça
      knowledge/combat.yml          hp, armadura, atributos, armas; prior de composição por raça
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

`bot/ego/planners/common/` contém apenas contratos e o lifecycle compartilhado. Missões concretas ficam
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
(`mission_id`: `offense:main_attack:N`, `defense:defend_area:N`, `intel:early_scout:N`, um número por operação para
separar as sucessivas nos logs) e a
proposta (`proposal_id`). A proposta da ofensiva guarda o id `offense` em todas as fases e em todas as
missões, a do scout guarda `intel` e as da defesa seguem o incidente (`defense:<incidente>:air`/`ground`),
porque o Engine prefere manter as unidades de quem já as tinha pelo `proposal_id`. `demand_id` continua outra
coisa: agrupa as partes aérea e terrestre de uma `DefendAreaMission`, que é quem as emite.

**Lifecycle.** Status pequeno e comum (`ACTIVE`, `COMPLETED`, `FAILED`, `CANCELLED`); as fases são de cada
operação (ASSEMBLE … WITHDRAW; DEFENDING; REQUESTING … SURVEIL). Um pedido de cancelamento não é um cancelamento:
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
| `knowledge.combat_model` | planners | `on_start` | `digest` (do modelo de combate em uso), `changed[]` (cada tipo cujo dado do cliente substituiu a tabela: antes -> depois) |
| `planner.production_kept_clear` | planners | `on_start` | `production_sites` (da main), `sites` (os do corredor da rampa), `cleared` (quantos o placement do Ares tinha) |
| `game.ended` | logs | `on_end` | `result` |
| `attention.observed` | attention | bases, fim do opening, inimigos à vista ou contatos de radar mudam; amostra a cada 5 s | `minerals`, `vespene`, `supply_used`, `supply_cap`, `workers`, `army_units`, `army_supply`, `army_power`, `visible_enemy_units`, `visible_enemy_structures`, `radar_blips`, `bases`, `opening`, `opening_done`, `upgrades[]`, `structures` {tipo: contagem, prontas ou não} |
| `awareness.updated` | awareness | mudança de contatos/poder/ameaça por base, contatos escondidos, primeiro camuflado, estimativa do observador (de 5 em 5 Marines) ou da medição que a corrigiu, heartbeat | `contacts`, `visible_contacts`, `enemy_power`, `seen_enemy_power`, `estimated_enemy_power`, `enemy_sigma`, `enemy_coverage`, `enemy_army` {`power`, `sigma`, `growth`, `growth_sigma`, `production`, `workers`, `bases`, `known_bases`, `expected_bases`, `coverage`, `cap`, `lost`, `correction` (`none`/`lower_bound`/`coverage`)}, `own_power`, `danger`, `danger_now`, `cloak_seen_at`, `hidden_contacts[]`, `bases[]` {`base_id`, `position`, `is_main`, `threat`, `recent_threat`, `pressure`, `cover`, `balance`, `air_share`, `center`}, `incidents[]` {`incident_id`, `contacts`, `center`, `power`, `ground_power`, `air_power`, `confidence`, `threat`, `pressure_by_base`} (escrito também quando os membros de um incidente mudam), `strongest_contacts[]` (com `hidden`), `field` {`samples`, `friendly`, `contested`, `enemy`, `threatened`, `max_threat`} |
| `opening_scout.expansion_checked` | attention | o estado da natural ou do third inimigo muda | `expansion` (`natural`/`third`), `status` (`UNKNOWN`/`ABSENT_CONFIRMED`/`PRESENT`), `previous`, `position`, `last_checked_at`, `first_seen_at`, `absent_at`, `appeared_between` (vista vazia, vista de pé) |
| `opening_scout.structure_seen` | attention | mais uma estrutura inimiga de um tipo é vista no early game | `structure`, `count_seen`, `first_seen_at`, `last_seen_at`, `gases_seen`, `workers_seen`, `proxy_structures_seen`, `main_coverage` |
| `awareness.opening_updated` | awareness | um fato novo, a leitura muda de faixa (1 casa) ou heartbeat | `summary` (uma linha: `t=1:52 race=Protoss natural=ABSENT_CONFIRMED@1:34 third=UNKNOWN coverage=0.81 \| aggression=0.74 …`), `race`, `natural` e `third` {`status`, `last_checked_at`, `first_seen_at`, `absent_at`, `appeared_between`}, `observed` {estrutura: contagem, `gases`, `workers`, `combat_units`, `proxy_structures`}, `main_coverage`, `last_updated`, `belief` {`aggression`, `greed`, `tech`, `proxy`, `confidence`}, `evidence` {cada termo da leitura} |
| `opening_scout.phase_changed` | missions | o early scout abre, muda de fase ou termina | `mission_id`, `phase` (`REQUESTING`, `CHECK_NATURAL`, `ENTER_MAIN`, `CIRCLE_MAIN`, `RECHECK_NATURAL`, `CHECK_THIRD`, `SURVEIL`, `PROXY_SEARCH`, `COMPLETE`), `previous`, `since`, `reason` (em `SURVEIL`: `third_found`, `third_empty`, `third_window_over`, `no_third_known`), `status`, `target`, `proxy_search`, `inputs` {`set_out`, `proxy_ordered`, `proxy_index`, `proxy_points`, `watching`, `watchpoints`}; em `COMPLETE` o motivo diz o que a encerrou (`opening_read`, `opening_over`, `proxy_found`, `proxy_search_done`, `proxy_search_timed_out`, `nowhere_left_to_look`, ou o motivo do cancelamento) |
| `opening_scout.proxy_search_started` | missions | o planner manda o scout procurar proxy (uma vez) | `mission_id`, `reason`, `target`, `inputs` |
| `strategy.posture_changed` | strategy | toda troca de postura (e a primeira), nunca por heartbeat | `posture`, `previous` (null na primeira), `reason`, `because` {os valores salientes da troca}, `summary` (uma linha: `DEVELOP -> DEFEND (home_threatened): threat=HIGH threat_level=0.71 army_position=-0.18 power_spike=0.00`), `threat` (CLEAR/LOW/ELEVATED/HIGH), `emergency`, `assessment` {como abaixo}, `gates` {postura: {`score`, `open`, `since`}} |
| `strategy.decided` | strategy | troca de postura ou de emergência, heartbeat | `posture`, `previous`, `since`, `reason`, `emergency`, `defense`, `army`, `economy`, `risk`, `assessment` {`threat_level`, `threat`, `army_position`, `economy_position`, `enemy_vulnerability`, `power_spike`, `confidence`, `setback`, `upgrade_spike`, `supply_spike`}, `inputs` {`danger`, `danger_now`, `army_share`, `own_power`, `enemy_power`, `seen_enemy_power`, `estimated_enemy_power`, `enemy_sigma`, `enemy_growth`, `enemy_production`, `enemy_workers`, `planned_enemy_power`, `own_lost`, `enemy_lost`, `own_bases`, `known_enemy_bases`, `expected_enemy_bases`, `enemy_bases`, `fresh_upgrades`, `supply_used`}, `scores` {postura: score do gate}, `gates` |
| `planner.proposed` | planners | o conjunto ranqueado de propostas muda | `proposals[]` {`proposal_id`, `owner`, `priority`, `command`, `target`, `count`, `minimum_power`, `must_attack`, `demand_id`, `mission_id`, `unit_types`, `reason`, `inputs`} |
| `planner.map_control_planned` | planners | origem, razão, anchor (grade de 3), fallback, ponto mantido do `staging` (e quando foi escolhido) mudam; heartbeat de 30 s | `anchor`, `source` (`threatened_base`, `staging`, `legacy`), `reason` (`hold_<staging|rally>_<postura>`), `posture`, `advance`, `fallback` (`no_candidates`, `no_enemy_route` ou null), `passage` e `region` (do ponto do `staging` que pôs o anchor, ou null), `staging` {`anchor`, `switch` (`kept`, `initial`, `held_invalid`, `bases_changed`, `posture_changed`, `awareness`), `since`, `previous`, `advance`, `scale` (D), `bases`, `candidate_count`, `selected`, `top[]` (o melhor de cada região, até 5, melhor primeiro); cada ponto {`anchor`, `region`, `passage`, `reaction`, `worst` e `worst_base` (a base respondida por último e a resposta, em células), `mean` (distância média às bases), `front` (à frente da base média no caminho do inimigo, em células; negativo atrás), `choke`, `threat`, `support`, `control`, `exposure`, `score`}} ou null |
| `planner.offense_planned` | planners | estágio, `since`, bloqueio, alvo (tag ou grade de 3) mudam | `stage`, `previous`, `since`, `reason`, `blocked_by`, `committed_power`, `target`, `target_tag`, `target_kind` (`known_base`, `known_structure`, `flying_structure`, `enemy_start`, `search`), `inputs` {`own_power`, `army_share`, `power_spike`, `offensive`, `supply_used`, `assembled_share`, `committed_power`, `stage_for`, `cooldown_left`, `known_structures`, `squad_units`, `squad_power`, `core_power`, `local_enemy_power`, `local_share` (−1 sem inimigo), `contested`, `clear_for`, `start_cleared`}, `fight` {`center`, `own_power`, `enemy_power`, `share`, `enemy_center`} ou null, `mission_id` e `mission_status` (a missão avançada ou aberta no frame, também no frame em que termina; null em IDLE) |
| `mission.updated` | missions | uma missão abre, muda de fase, recebe pedido de cancelamento ou termina | `missions[]` {`mission_id`, `owner`, `kind` (`main_attack`, `defend_area`, `early_scout`), `status` (`ACTIVE`, `COMPLETED`, `FAILED`, `CANCELLED`), `phase`, `since`, `reason`, `cancel` {`mode`, `reason`, `time`} ou null, `proposals[]`, `granted_units`, `granted_power` (o que a alocação anterior lhe deu)} |
| `planner.economy_planned` | planners | o plano muda (a composição com 2 casas) | `active`, `workers`, `gas`, `bases`, `expand`, `freeflow`, `reason`, `composition[]`, `inputs` {`workers`, `bases`, `saturated_at`, `expansion_sites`, `strategy_economy`, `danger`, `production_per_base`, `gas_worker_share`, `upgrades_done`, `enemy_seen_power`}, `upgrades[]`, `orbitals`, `mules`, `interrupt_opening`, `max_production`, `addons`, `addons_on`, `reactor_share`, `army`, `style`, `baseline[]`, `enemy[]` {`type`, `seen`, `produced`, `share`, `answers[]` {`type`, `share`}}, `seen_power`, `believed_power`, `produced_power`, `doctrine`, `mix[]` {`type`, `resources`, `availability`}, `unmodeled[]`, `survival`, `composition_reason` (`style_baseline`, `efficacy`, `survival_fallback`), `tech_ready[]` |
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
python tools\replay_truth.py bench\<rótulo>
```

`tools/replay_truth.py` precisa do `sc2reader` (`pip install sc2reader`), que não é dependência do bot.

## Ainda não implementado

Cada item entra quando um problema de gameplay medido pedir. Os modelos já escritos no branch
`matematização` que servem a vários deles estão em [migration-map.md](migration-map.md). O que já está em
andamento, ou decidido como o próximo, está em [staging/](staging/README.md).

- **Informação:** a Strategy ainda não consome a `OpeningBelief` (Attention, Awareness e Intel já a
  produzem e a registram); nenhum limiar ou peso da leitura da opening foi medido em partida real;
  scouting depois do early game (o SCV sai uma vez, antes de 240 s, e a ronda dele acaba com a janela
  da opening), forças inimigas agregadas além dos incidentes, Raven e scan de informação. O observador do
  exército inimigo ainda não tem: composição por tipo no estado (a composição lê o poder escalar e espalha o não
  visto pelo visto e pelo prior da raça), renda medida pelos
  workers vistos em vez de só limitada por eles, cobertura além das bases conhecidas (o exército no meio do
  mapa não conta como "olhei e não vi"), atraso de produção, e nenhum parâmetro dele foi medido com o
  `tools/replay_truth.py` em partidas jogadas com ele.
- **Espaço:** `RegionState` e território (a topologia e o campo só são consumidos pelo staging do MapControl e
  pelas rotas do scout), map control de verdade (visão, presença, negar expansões), path de grupo consciente
  de risco, alcance de estruturas voando sobre terreno impassável.
- **Combate:** alcance no modelo de poder (o splash já conta, o alcance não) e splash contado contra a
  aglomeração real em vez da suposta; coesão e reforços da ofensiva (hoje toda unidade livre vai sozinha
  até o grupo); stutter, focus fire, target scoring; Medivac evacuando; harass.
- **Por planner** (Defense, wall dos depots, Economy, MapControl, Strategy e os demais): a seção
  "Limitações conhecidas" de cada documento em [planners/](planners/README.md).
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

**Observador do exército inimigo.** O `bench/t0` (`9457a4a`, Zerg e Terran CheatInsane, 4 partidas com
replay) foi a primeira medição das posturas e a última do prior por tempo. A verdade dos replays
(`tools/replay_truth.py`) contra o que o bot acreditou:

| Partida | Resultado | Erro médio da estimativa | Erro absoluto médio | Tempo realmente à frente | Tempo em que o bot se achou à frente |
| --- | --- | --- | --- | --- | --- |
| 000 Zerg Rush | derrota | +9,7 | 18,0 | 13 % | 0 % |
| 001 Zerg Macro | derrota | +5,5 | 14,9 | 10 % | 5 % |
| 002 Zerg RandomBuild | vitória | +40,8 | 47,8 | 64 % | 8 % |
| 003 Terran Rush | vitória | +22,3 | 28,5 | 49 % | 41 % |

(O "achou à frente" desta tabela planeja contra a estimativa sem margem; com a margem de 0,5 da incerteza
que o bot usava, o `army_position` máximo de cada partida ficou entre 0,00 e 0,13.) Nas vitórias o inimigo
perdeu o exército (poder real 0–16) e o prior seguiu subindo até 78–100: na 002, aos 15 min, o inimigo tinha
7,6 de poder, 51 workers e 2 bases, e o bot acreditava em 78. Nas derrotas o erro pequeno é coincidência: a
rampa calhou de bater com o Zerg CheatInsane. O visto vivo acompanhou a verdade quando o inimigo desmoronou
(17 → 11 → 6,6 contra 28 → 16 → 7,6), e o `max()` o descartava. Parâmetros medidos nos mesmos replays e usados
no observador: renda por worker de 55–68/min do bot e 75–112/min do CheatInsane (por isso a produção é
adaptativa); fatia da renda em exército de 0,2–0,4 até ~6 min e 0,4–0,8 depois, igual nos dois lados;
1,0–1,3 Marine de poder por 100 de recurso em exército. O poder "verdadeiro" vem de uma tabela estática
calibrada por partida pelo `own_power` do próprio bot (escala 0,79–0,84). O observador entrou no HEAD sem
bench próprio (commit "virada de chave", tag de rollback `pre-observador`).

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
