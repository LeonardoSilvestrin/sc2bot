# Arquitetura: camadas

↑ [README](../README.md) · [Desenvolvimento](dev/README_DEV.md)

O bot é quatro camadas, cada uma num pacote de `bot/` e numa pasta de `docs/` com um índice:

| Camada | Pergunta | Código | Docs |
| --- | --- | --- | --- |
| Attention | O que o jogo mostra? | [bot/attention/](../bot/attention/__init__.py) | [Attention](attention/README_ATTENTION.md) |
| Awareness | O que acredito sobre o que não vejo? | [bot/awareness/](../bot/awareness/__init__.py) | [Awareness](awareness/README_AWARENESS.md) |
| Ego | O que fazer? Strategy, planners e Economy | [bot/ego/](../bot/ego/__init__.py) | [Ego](ego/README_EGO.md) |
| Body | Quem faz, e como? Engine e behaviors | [bot/body/](../bot/body/__init__.py) | [Body](body/README_BODY.md) |

Este documento guarda o que atravessa as camadas: os papéis, os logs, o harness, os comandos e as medições.

No `on_start`, a Attention lê o mapa físico uma vez (`read_map`). Depois, um frame atravessa as camadas
sempre na mesma ordem, em `play_frame` ([bot/main.py](../bot/main.py)):

```text
map_view, opened = passages.refresh(bot, map_view)                     ATTENTION
attention    = observe(bot, iteration, map_view, opening)              ATTENTION
awareness    = awareness.infer(attention)                              AWARENESS
intent       = strategy.decide(attention, awareness)                   EGO / strategy
defense      = defense.plan(attention, awareness, intent, feedback)    EGO / planners
map_control  = map_control.plan(attention, awareness, intent, feedback)
offense      = offense.plan(attention, awareness, intent, map_control.anchor, feedback)
intel        = intel.plan(attention, awareness, intent, feedback)
missions     = defense.views() + offense.views() + intel.views() + map_control.views()
economy_plan = economy.plan(attention, intent, army, ..., awareness, map_control.unit_requests)   EGO / economy
structures   = structure_control.plan(attention)                       EGO / planners
result       = engine.allocate(attention, proposals)                   BODY / engine
feedback     = result                                                  (lido no próximo frame)
body         = behaviors.execute(bot, attention, result, economy_plan, structures, intel,
                                 defense.fortification)                BODY / behaviors
logs.record(...)                                                       LOGS
```

## Papéis arquiteturais

Esta seção é a definição normativa dos papéis. Docstrings e exemplos aplicam estas regras.

| Papel | Responsabilidade | Fronteira verificável |
| --- | --- | --- |
| Strategy | Responde "como está a partida?" (`GameAssessment`) e "o que o bot quer agora?" (`StrategicIntent`: postura, motivo, preferências contínuas e emergência), o contexto comum de todos os planners. | Não governa operações individuais, não escolhe lugar, alvo, composição, construção nem micro; cada planner traduz a postura para o seu domínio. |
| Planner | Dono e coordenador de um domínio: decide a intenção dele a partir do estado conhecido, da postura e do feedback relevante, e junta o que suas Missions e Policies decidem. | Um único por domínio, em `planner.py`. Decide o uso do que já existe (unidades, estruturas, energia); o que comprar é da Economy, com exceção, por enquanto, da infraestrutura do Intel e do Bunker da Defense. Produz planos/propostas; não causa efeitos no jogo. Pode ser função, objeto stateless ou stateful. |
| Economy | Decide o que passa a existir: workers, bases, gás, produção, composição do exército e upgrades, num `EconomyPlan` de setpoints. | Não é um Planner: fica ao lado de `strategy/` e `planners/`, lê a postura, não pede unidades ao Engine e nenhum planner a importa. Por dentro tem a mesma forma (`planner.py`, `policies/`, `knowledge/`), sem missões. |
| Desired state | Condição contínua que um Planner tenta manter. | Se deixar de estar satisfeita, volta a ser pedida, sem criar uma operação numerada. |
| Mission | Conduz uma operação persistente com identidade, lifecycle próprio e término, normalmente com unidades cuja posse o Engine arbitra. | É opcional e interna ao Planner que a abre, em `missions/`; não é uma etapa obrigatória da arquitetura. |
| Policy | Implementa uma regra de decisão interna que o Planner usa. | Pode ter estado; não tem `mission_id`, lifecycle nem `MissionView` e não pede unidades ao Engine. Fica em `policies/`. |
| Knowledge | Contém fatos estáticos do domínio: dados, tabelas e catálogos. | Não decide nada por frame nem guarda estado da partida. Fica em `knowledge/`. |
| Engine | Arbitra quais unidades atendem quais intenções; transforma proposals em grants. | Não arbitra minerais, energia orbital ou toda a produção. Não decide objetivos nem lifecycle. |
| Behavior | Materializa a intenção em ações do jogo, com decisões locais de execução. | Pode mudar path, siege, stim, ator equivalente ou posição fina; não muda objetivo, alvo estratégico, compromisso ou cancelamento. |

**Planner owns the domain. Mission owns an operation. Policy implements a decision rule. Knowledge
contains static domain facts.**

Cada domínio em `planners/`, e a `economy/`, segue, quando se aplica, a mesma forma; nem todo domínio tem
todas as pastas:

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
([tabela](ego/planners/README_PLANNERS.md#a-postura-em-cada-planner)).

Um Planner pode expressar tanto desired states contínuos quanto operações episódicas.
Economy, MapControl, controle de depots, detection e sensor coverage são contínuos.
Ataque principal, scout e defesa de um incidente são episódios. Estado persistente por si só não
justifica Mission: hysteresis do anchor e cobertura já desbloqueada pertencem aos planners e às suas policies.

```text
Attention → Awareness → GameAssessment → Strategy → StrategicIntent → Planners (um por domínio) e Economy
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

## Fora das camadas

O que cada camada faz está no índice dela (tabela acima). Fora delas:

| Parte | Arquivo | Estado público | O que faz |
| --- | --- | --- | --- |
| LOGS | [bot/logs/](../bot/logs/__init__.py) | — | Log JSONL, snapshots SVG do campo, overlay in-game e o chat, onde o bot diz em voz alta o que está pensando (`chat.py`: postura nova — DEFEND é "rushed" só enquanto há early game, depois é "attacked" —, emergência, camuflado visto e a leitura da opening; uma linha por vez, `gap` de 12 s, um assunto não se repete antes de `topic_cooldown`, teto de `max_lines` por partida, escolha determinística, e `gg` no fim). Falar é async e o frame não é: `observe` só enfileira, e `BotBandido._speak` manda — engolindo qualquer erro. Nenhum deles muda decisão nem derruba partida. |
| HARNESS | [harness/](../harness/__init__.py), [bench.py](../bench.py) | `Game`, `GameSpec`, `result.json` | Fora do bot, um módulo por assunto: `config.py` é a **lista** que se escreve à mão — o `harness/matrix.yml`, uma linha por partida (`race`, `strategy`, `map`, mais `army`, `difficulty`, `games`, `time_limit`), o que a linha não diz vem de `defaults`, `games: 10` pede dez daquela partida (cada uma com a sua seed), `map: random` sorteia um mapa por execução (o mesmo para todas as linhas que pedem random, enquanto a linha que nomeia um mapa fica nele) — é YAML porque YAML aceita comentário, e é ali no topo do arquivo que mora a colinha com todos os nomes que cabem; os nomes são conferidos contra as tabelas do jogo e do bot antes de qualquer partida subir, então um erro de digitação custa uma mensagem (com a linha do arquivo, quando é o YAML que não fecha) e não uma tarde; `matrix.py` é a **tabela** fixa de partidas, uma linha por jogo (`Game(mapa, raça, abertura da IA)`), `BASE` com as 9 em que uma fatia é medida (cada raça contra `Rush`, `Macro` e `RandomBuild`, porque uma mudança que só aparece contra uma abertura não é mudança) e `WIDE` com essas 9 nos três mapas de `WIDE_MAPS` (27, e não nos sete da rotação, porque 63 partidas não respondem melhor se o mapa estava carregando o resultado); `MAPS` é a rotação — o pool da temporada, sete mapas — e é dela que um `random` sorteia, uma vez por execução (todas as partidas que pedem `random` no mesmo mapa, outro mapa na próxima), então duas execuções que precisam ser comparadas fixam o mapa na linha ou com `--maps` — o `compare` avisa quando foram mapas diferentes. Qual matriz uma execução joga sem nenhum argumento mora nesse arquivo (`DEFAULT_MATRIX` = `file`, a lista do `harness/matrix.yml`, para o `bench.py`; `DEFAULT_LAUNCHER` para o `run.py`), que é onde se troca isso em vez de nos argumentos de uma configuração de launch; com `--matrix file` valem `--matrix-file`, `--seed` e `--time-limit`, e as colunas de uma tabela (`--maps`, `--races`, `--difficulties`, `--ai-builds`, `--armies`, `--games`) são recusadas com uma mensagem porque o arquivo já diz o que jogar; `games_of` devolve a tabela, ou o produto do eixo que for dado à mão (`--maps`, `--races`, `--ai-builds` substituem aquela coluna), e `matrix` transforma jogos em `GameSpec` (× dificuldade × estilo do bot `--armies` × `--games` repetições, cada repetição com a sua seed; sem `--armies` o bot sorteia e o `game_id` não leva sufixo). `outcome.py`: o que aconteceu com uma partida. `record.py`: o `result.json` que liga o desfecho a commit, SHA do Ares, árvore suja, fingerprint da configuração, mapa, oponente, seed, replay e JSONL. `summary.py`: `summarize` e o intervalo de Wilson. O launcher lê as mesmas listas: `run.py --matrix builds` joga as três aberturas no mesmo mapa e raça (3 partidas), `--matrix wide` percorre as 27 e `--matrix file` joga a lista do `harness/matrix.yml`, cada partida com o mapa, a raça, o army, a dificuldade e a seed da sua linha, com a janela aberta e sem registrar nada — para medir é o `bench.py`; cada partida de uma sequência é cortada em `--time-limit` (30 min por padrão) e roda com um bot novo. Nomes de raça, dificuldade e build são conferidos antes de qualquer partida subir, e um mapa que não está instalado também, cada partida num processo com timeout de relógio; `result.json` liga resultado (`victory`, `defeat`, `tie`, `timeout`, `crash`, `no_result`, `not_played`) a commit, SHA do Ares, árvore suja, fingerprint da configuração, mapa, oponente, seed, replay e JSONL. Uma partida que reportou resultado com o relógio do bot em 0 é `not_played` (o python-sc2 resigna no primeiro passo quando o `on_start` levanta): conta em `games`, não em `played`, fica fora da taxa de vitória e da duração média, e `run` a joga de novo em vez de pular. `summarize` recalcula o desfecho do que cada registro guardou, então execuções antigas são resumidas pela regra atual; `compare` agrega com intervalo de Wilson. O fingerprint cobre `Layers.configs()`, incluindo estilo, composição (digest do modelo de combate, já com os dados do cliente) e investment; constantes fora das configs ainda exigem comparação pelo commit. |

## Matemática e missões

A matemática mora com quem a calcula: o poder de uma unidade em [Units](attention/units.md); o kernel e o
campo em [Field](awareness/field.md); contatos, ameaça por base, incidentes e early game em
[Awareness model](awareness/awareness-model.md); o observador do exército inimigo em
[Enemy army](awareness/enemy-army.md); a leitura da opening em [Opening belief](awareness/opening-belief.md);
a avaliação e a postura em [Strategy](ego/strategy.md). Contratos, lifecycle, feedback e quem usa missões
estão em [Common](ego/planners/common.md); a alocação, no [Engine](body/engine.md).

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
`matematização` que servem a vários deles estão em `migration-map.md`. O que já está em
andamento, ou decidido como o próximo, está em [staging/](dev/staging/README.md).

- **Informação:** a Strategy ainda não consome a `OpeningBelief` (Attention, Awareness e Intel já a
  produzem e a registram); nenhum limiar ou peso da leitura da opening foi medido em partida real;
  scouting depois do early game (o SCV sai uma vez, antes de 240 s, e a ronda dele acaba com a janela
  da opening), forças inimigas agregadas além dos incidentes, Raven e scan de informação. O observador do
  exército inimigo ainda não tem: composição por tipo no estado (a composição lê o poder escalar e espalha o não
  visto pelo visto e pelo prior da raça), renda medida pelos
  workers vistos em vez de só limitada por eles, cobertura além das bases conhecidas (o exército no meio do
  mapa não conta como "olhei e não vi"), atraso de produção, e nenhum parâmetro dele foi medido com o
  `tools/replay_truth.py` em partidas jogadas com ele.
- **Espaço:** `RegionState` e território (a topologia e o campo só são consumidos pelo staging do MapControl,
  pela remoção de creep e pelas rotas do scout), map control de verdade (visão, presença, negar expansões), path de grupo consciente
  de risco, alcance de estruturas voando sobre terreno impassável.
- **Combate:** alcance no modelo de poder (o splash já conta, o alcance não) e splash contado contra a
  aglomeração real em vez da suposta; coesão e reforços da ofensiva (hoje toda unidade livre vai sozinha
  até o grupo); stutter, focus fire, target scoring; Medivac evacuando; harass.
- **Por planner** (Defense, wall dos depots, Economy, MapControl, Strategy e os demais): a seção
  "Limitações conhecidas" de cada documento em [planners/](ego/planners/README_PLANNERS.md).
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
