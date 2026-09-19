# Gaps

> Registro de design/revisão histórico. Composição por catálogo, SURVIVE e fronteiras de Planner,
> Mission e Behavior já estão implementadas; o estado atual e os nomes de eventos são definidos em
> [architecture.md](architecture.md).


Levantamento de 2026-09-18 no branch `botbandido`, em `7e5be42` mais a working tree daquele dia (a troca
ArmyFallback → MapControl, com `map_control/anchor.py`, ainda sem commit). Tudo foi lido no código; nada
aqui foi medido em partida. As linhas citadas são as desse dia e andam com o código.

Quatro tipos de achado:

- **C — calculado e não decide:** sai de uma camada e nenhuma decisão o lê. Só log, overlay, SVG, testes,
  ou ninguém.
- **F — fallback:** um caminho que troca o resultado pedido por outro quando algo falta ou falha, em geral
  sem avisar.
- **L — legado:** nome, dado, caminho ou doc que sobrevive de uma versão anterior.
- **I — inconsistência lógica:** duas partes do bot que medem ou decidem a mesma coisa de formas
  diferentes, ou uma regra que não faz o que o nome promete.

Severidade: **alta** muda uma decisão em partida hoje; **média** muda uma decisão num caso plausível, ou
custa desempenho todo frame; **baixa** é higiene. Um achado que outro doc já registra aponta para ele em
vez de repetir: A4/A5/N3 de [novas_propostas.md](novas_propostas.md) e "Ainda não implementado" de
[architecture.md](architecture.md#ainda-não-implementado).

Fica de fora a telemetria por contrato: `inputs`, `reason`, `blocked_by`, os campos do `OffensePlan` além
das propostas, `SpawnMode`, `MicroReport` e `DetectionReport` existem para o log, e isso é o papel de LOGS.

## Prioridades

| ID | Achado | Sev. |
| --- | --- | --- |
| [I1](#i1) | Compromisso e reunião da ofensiva medidos contra o exército inteiro, não contra o squad | alta |
| [I3](#i3) | Worker de scout e defesa estática contam como atacantes (incidente, `danger`, STABILIZE) | alta |
| [I2](#i2) | Um contato fora de vista fica *mais* ao alcance das bases com a idade | média |
| [C6](#c6) | Nenhuma missão lê `GrantStatus`; a Defense não reage a uma concessão parcial | média |
| [I9](#i9) | Nenhum MULE durante toda a abertura | média |
| [I10](#i10) | Um cloak visto uma vez liga turrets, Engineering Bay e reserva de scan até o fim | média |
| [C1](#c1) | `InfluenceField` recalculado todo frame só para log | média |
| [C5](#c5) | Preferências da Strategy (`army`, `risk`) sem consumidor | média |
| [I8](#i8) | Estilo de exército sorteado sem seed | média |
| [F2](#f2) | A topologia degrada em silêncio, e o MapControl cai no `legacy` | média |
| [I7](#i7) | O fingerprint deixa de fora constantes da Defense, do Intel e dos behaviors | média |

## C — Calculado e não decide

<a id="c1"></a>**C1 · `InfluenceField` inteiro** (média) —
[model.py:298](../bot/awareness/model.py#L298), [field.py](../bot/awareness/field.py).
`threat`, `support` e `enemy` (e `control`) são recalculados todo frame: três matrizes de pontos do lattice ×
fontes (contatos com poder, nosso exército, nossas estruturas). Leem: [overlay.py](../bot/logs/overlay.py),
[snapshot.py](../bot/logs/snapshot.py) e o `field` de `awareness.updated`. Desde o staging do MapControl
([staging.py](../bot/ego/planners/military/map_control/staging.py)) há um planner que lê `threat`,
`support` e `control` nos seus candidatos (a `exposure`), então o campo decide; mas só nesses pontos, e o
campo inteiro continua calculado todo frame. É o A5 de novas_propostas.

<a id="c2"></a>**C2 · Leituras por base sem leitor** (baixa) —
[model.py:115](../bot/awareness/model.py#L115). `BaseThreat.cover`, `balance`, `air_share` e `center` só
vão para log e SVG; `cover` custa um laço sobre o nosso exército por base, todo frame. `balance` (quanto do
que está na base é do inimigo) é justamente a leitura que falta à Defense para separar "atacada e coberta"
de "atacada e descoberta" ([C6](#c6)).

<a id="c3"></a>**C3 · Agregados da Awareness sem leitor** (baixa) —
`enemy_coverage` ([model.py:223](../bot/awareness/model.py#L223)) só vai ao log; `danger_now` só aos
`inputs` da Strategy; `ThreatIncident.confidence`, `pressure`, `affected_bases` e o número de `contacts`
só aos `inputs` das propostas da Defense.

<a id="c4"></a>**C4 · Campos da Attention sem leitor** (baixa) —
`UnitView.health` ([frame.py:189](../bot/attention/frame.py#L189)) é calculado para toda unidade, nossa e
inimiga, todo frame, e ninguém lê, nem o log: o Stim lê `health_percentage` direto do Ares.
`UnitView.supply`, `supply_cap`, `vespene` e `opening` só vão para `attention.observed`.
`MapTopology.own_start_region`, `choke_candidates` e `region_splits` só vão para log e SVG (os dois últimos
são "debug only" por contrato).

<a id="c5"></a>**C5 · Preferências da Strategy** (média) —
[strategy.py:119-129](../bot/ego/strategy.py#L119-L129). `army` não tem leitor. `economy = 1 − army` é o
mesmo número, lido só em `economy ≥ 0,5` ([investment.py:99](../bot/ego/planners/economy/investment.py#L99)),
que só fecha com `0,5·danger + 0,4·(0,5 − army_share) > 0,2`. `risk` só entra nos `inputs` do MapControl
([planner.py:130](../bot/ego/planners/military/map_control/planner.py#L130)) e em `engine.commanded`.
`defense` é `danger` com outro nome. `scores` é log. É o A4/N3 de novas_propostas, sem mudança desde então.

<a id="c6"></a>**C6 · Feedback que só vira log** (média) —
`DefendAreaMission.step` recebe o `MissionFeedback` e não o usa
([defend_area.py:69](../bot/ego/planners/military/defense/missions/defend_area.py#L69)); a `ScoutMission`
também não ([I12](#i12)). `GrantStatus` (`FULL`/`PARTIAL`/`REJECTED`) e a `reason` do Engine
([engine.py:33](../bot/body/engine.py#L33)) não são lidos por missão nenhuma; a ofensiva lê só as `tags`.
Uma defesa que recebeu metade do orçamento segue igual: não escala, não chama reforço, não muda de alvo.
Quem a socorre é só o STABILIZE, que precisa de `danger ≥ 0,55` para entrar.

<a id="c7"></a>**C7 · `MissionView` e `Frame`** (baixa) —
[main.py:117](../bot/main.py#L117), [main.py:147](../bot/main.py#L147). As views são montadas todo frame
para `mission.updated` e para o `Frame`, que o `on_step` descarta (só os testes o usam). O
architecture.md diz que a Strategy "pode recebê-lo quando precisar"; hoje ninguém recebe.

<a id="c8"></a>**C8 · `Proposal.demand_id`** (baixa) —
[contracts.py:59](../bot/ego/planners/contracts.py#L59),
[defend_area.py:106](../bot/ego/planners/military/defense/missions/defend_area.py#L106). O Engine não o
lê: as partes de um incidente "compartilham um orçamento" só no log. Ver [I14](#i14).

<a id="c9"></a>**C9 · Prioridade do scout** (baixa) —
[scout.py:106](../bot/ego/planners/intel/missions/scout.py#L106). Workers são um pool à parte no
Engine; o próprio docstring da missão diz que a prioridade "só ordena o log".

<a id="c10"></a>**C10 · `MapControlPlan` além do anchor** (baixa) — `candidates`, `source`, `fallback`, os
termos de cada `PassageCandidate` e os `inputs` só vão para log e SVG. É telemetria; está anotado porque
`risk` e `danger` entram como `inputs` sem entrar no score.

<a id="c11"></a>**C11 · Plano de economia durante a abertura** (baixa) —
[planner.py](../bot/ego/planners/economy/planner.py) monta composição, upgrades, workers e gás todo frame.
Com `active` falso o Body retorna antes de ler qualquer um deles
([economy.py:177](../bot/body/behaviors/economy.py#L177)); só `interrupt_opening` conta.

<a id="c12"></a>**C12 · Telemetria no ladder** (baixa) —
[logs/\_\_init\_\_.py:97](../bot/logs/__init__.py#L97). No ladder, `Logs()` usa `NullLogger`, mas
`Telemetry.record` roda inteiro: a assinatura de cada `ChangeGate` todo frame, a lista de exército de
`_record_attention` antes do gate ([telemetry.py:224](../bot/logs/telemetry.py#L224)) e cada payload,
montado a cada mudança para um logger que o joga fora.

<a id="c13"></a>**C13 · Helpers sem chamador em produção** (baixa) —
`MapTopology.neighbours()` ([topology.py:105](../bot/attention/topology.py#L105)),
`InfluenceField.nearest()` ([field.py:75](../bot/awareness/field.py#L75)) e `EngineResult.owner_of()`
([engine.py:61](../bot/body/engine.py#L61)) só são chamados por testes; `AwarenessState.base()`
([model.py:256](../bot/awareness/model.py#L256)) por ninguém. `Source.reach`
([field.py:31](../bot/awareness/field.py#L31)) nunca é passado e é sempre `inf`, mas `accumulate` monta a
máscara `np.where` a cada chamada. `EngineResult.unassigned` só vai para log e SVG.

## F — Fallbacks

<a id="f1"></a>**F1 · Anchor `legacy` do MapControl** (média) —
[planner.py:285](../bot/ego/planners/military/map_control/planner.py#L285). O antigo `Strategy._rally`
continua como terceira fonte do anchor quando a política que controla não põe anchor: no `staging`, sem base
localizada ou ponto do lattice nas regiões (`no_candidates`) ou sem caminho até o start inimigo
(`no_enemy_route`); no `passage`, sem passagem que separe (`no_separating_passage`) ou sem ponto do lattice
(`anchor_unresolved`). Se a topologia degrada ([F2](#f2)), o bot joga com a heurística antiga e só o campo
`fallback` de `planner.map_control_planned` conta. As medições até o `bench/ci-*` usaram o rally antigo ou a
passagem; depois que o `staging` for medido num bench, o `legacy` sai ou vira um caso raro com alerta.

<a id="f2"></a>**F2 · Topologia que degrada em silêncio** (média) —
[map.py:102](../bot/attention/map.py#L102), [topology.py:971-984](../bot/attention/topology.py#L971-L984).
Se o mediator do Ares falha, `map_data` é `None`; `_safe_attr`, `_call_region` e `_iter` engolem
`AttributeError`, `KeyError`, `RuntimeError`, `TypeError`, `ValueError` e `IndexError`. Sem as regiões do
MapAnalyzer, cada componente caminhável vira uma região `transit:N`
([topology.py:190](../bot/attention/topology.py#L190)), uma expansão sem região vira uma região sintética
`expansion:N` sem amostras ([topology.py:265](../bot/attention/topology.py#L265)), e `locate` desce quatro
níveis: região direta, expansão a ≤ max(3, espaçamento), BFS no grid, centro mais próximo
([topology.py:286](../bot/attention/topology.py#L286)). A jusante, o MapControl fica sem candidatas e cai no
`legacy`, e a rota do scout vira só o start
([intel/planner.py:117](../bot/ego/planners/intel/planner.py#L117)). Nada falha; só as contagens de
`map.topology_built` mostram. Direção: uma razão de degradação no evento e um teste que falhe quando o
MapAnalyzer não responde num mapa do pool.

<a id="f3"></a>**F3 · Rampa da main** (baixa) — [map.py:50](../bot/attention/map.py#L50). Sem
`main_base_ramp`, `main_ramp = own_start`: o anchor `legacy` com uma base só fica em cima do CC.

<a id="f4"></a>**F4 · Defaults da percepção** (média para `_roles`, baixa para o resto) —
[frame.py](../bot/attention/frame.py). Numa exceção do mediator, `_roles` devolve `{}`
([frame.py:219](../bot/attention/frame.py#L219)): nenhum worker aparece com role `GATHERING`, o Engine nunca
os concede ([engine.py:80](../bot/body/engine.py#L80)) e o scout nunca sai, sem erro. `_supply_lookup`
devolve supply 0 ([frame.py:253](../bot/attention/frame.py#L253)). `opening_done` é verdadeiro sem
`build_order_runner` ([frame.py:164](../bot/attention/frame.py#L164)). Com `visibility = None`, `is_visible`
é sempre falso ([frame.py:124](../bot/attention/frame.py#L124)): a Awareness nunca esquece por visão, o
Intel nunca vê um waypoint e a ofensiva nunca começa a busca. Em partida o grid sempre existe; esse default
serve aos testes.

<a id="f5"></a>**F5 · Estilo de exército** (média) — [styles.py:127](../bot/ego/planners/economy/styles.py#L127),
[main.py:196](../bot/main.py#L196). O estilo é escolhido uma vez, no `on_start`, pela raça que o python-sc2
informa nesse momento. Contra um oponente Random a raça é `Random`, `candidates` só tem BIO (MECH é
`against={Zerg}`), e o estilo não é revisto quando a raça aparece. Sem candidato algum, BIO. Ver também
[I8](#i8).

<a id="f6"></a>**F6 · Composição** (baixa) — [composition.py:199](../bot/ego/planners/economy/composition.py#L199).
Uma unidade fora de `REACH` é tratada como "só atira no chão", e `mix` volta ao prior quando os pesos somam
0 ([composition.py:170](../bot/ego/planners/economy/composition.py#L170)). Hoje todo tipo dos estilos está
em `REACH`; um tipo novo sem entrada entraria calado, com o alcance errado.

<a id="f7"></a>**F7 · `army_share = 0,5` sem poder algum** (baixa) —
[strategy.py:114](../bot/ego/strategy.py#L114). O valor neutro cai exatamente em `EVEN_SHARE`
([offense/planner.py:67](../bot/ego/planners/military/offense/planner.py#L67)): sem informação nenhuma,
`advantage` é verdadeiro. Hoje quem segura a ofensiva é o `minimum_power` (20).

<a id="f8"></a>**F8 · Defaults duplicados nos contratos** (baixa) —
`EconomyPlan.max_production = 12`, `addons_on = BARRACKS`, `reactor_share = 1.0` e `army = "bio"`
([contracts.py:91-101](../bot/ego/planners/contracts.py#L91-L101)), e `Layers.army = BIO`
([main.py:56](../bot/main.py#L56)), repetem valores que o estilo e a `investment` já decidem. Só valem num
caminho que construa o plano sem eles, que hoje são os testes.

<a id="f9"></a>**F9 · `run.py`** (baixa) — sem `MyBotRace` no `config.yml`, `race = Race.Random`
([run.py:139](../run.py#L139)), mas o bot só joga de Terran (SCV, `terran_builds.yml`, add-ons). Sem mapas
em `MAPS_PATH`, entra uma lista fixa de mapas de ladder ([run.py:181](../run.py#L181)).
`MyBotName: MyBotName` ([config.yml:6](../config.yml#L6)) ainda é o placeholder do template.

<a id="f10"></a>**F10 · Local da turret** (baixa) —
[detection.py](../bot/body/behaviors/detection.py) (Body). `min(expansion_locations_list, …, default=base)`
recalcula a expansão mais próxima de uma posição que já é uma expansão: a `BaseView` é ajustada a ela em
[frame.py:259](../bot/attention/frame.py#L259).

## L — Legado

<a id="l1"></a>**L1 · `core_army`** (baixa) — o id e o owner da proposta do MapControl
([planner.py:41](../bot/ego/planners/military/map_control/planner.py#L41)) são o nome de duas versões atrás
(CoreArmy → ArmyFallback → MapControl). Quem os mantém: o viewer
([viewer.html:613](../logs/viewer.html#L613), [timeline_model.js:10](../logs/viewer/timeline_model.js#L10),
com o rótulo "Core army", e [decision_view.js:189](../logs/viewer/decision_view.js#L189)), as cores do
overlay ([overlay.py:22](../bot/logs/overlay.py#L22)) e os benches antigos. Os testes usam `core_army` como
id arbitrário (`test_engine`, `test_behaviors`, `test_intel`, `test_logs`, `test_log_viewer`), e dois nomes
de teste ainda falam em core army ([test_defense.py:161](../tests/test_defense.py#L161),
[test_frame_flow.py:415](../tests/test_frame_flow.py#L415)). Renomear pede `SCHEMA_VERSION` novo e compat
no viewer.

<a id="l2"></a>**L2 · Nomes de evento de antes de Ego/Body** (baixa) — os planners escrevem `behavior.*`
com component `behaviors`, e `engine.commanded` registra o que os behaviors executaram. O
[catálogo de eventos](architecture.md#catálogo-de-eventos) documenta isso como compat. No mesmo espírito, o
harness dá o default a um campo que um `result.json` antigo não tinha
([harness/\_\_init\_\_.py:83](../harness/__init__.py#L83)); isso é intencional, não é gap.

<a id="l3"></a>**L3 · Cancelamento gracioso sem gatilho** (baixa) — `CancelMode.GRACEFUL`
([lifecycle.py:33](../bot/ego/missions/lifecycle.py#L33)), a fase `WITHDRAW` e as razões `withdrawn` e
`withdraw_timed_out` ([main_attack.py:422-430](../bot/ego/planners/military/offense/missions/main_attack.py#L422-L430))
só rodam nos testes: o único pedido feito em produção é `IMMEDIATE`
([offense/planner.py:192](../bot/ego/planners/military/offense/planner.py#L192)). O
`DefendAreaMission.request_cancel` e o ramo `CANCELLED`
([defend_area.py:83](../bot/ego/planners/military/defense/missions/defend_area.py#L83)) são inalcançáveis:
o planner nunca pede. O architecture.md já diz que "nenhum gatilho de produção o usa"; o custo é manter e
testar um caminho que nenhuma partida exercita.

<a id="l4"></a>**L4 · Pacote `core`** (baixa) — o docstring de
[missions/\_\_init\_\_.py:1](../bot/ego/missions/__init__.py#L1) ainda começa com "CORE:", e o
architecture.md aponta `bot/ego/core/` em três lugares (a tabela de camadas, a tabela de papéis e "Onde fica
cada coisa"). O pacote é `bot/ego/missions/`. **19/09:** o architecture.md foi corrigido; falta o docstring.

<a id="l5"></a>**L5 · Counters de unidades que nenhum estilo constrói** (baixa) — `REACH` tem Thor, Widow
Mine e Viking ([composition.py:65-67](../bot/ego/planners/economy/composition.py#L65-L67)), e `COUNTERS`
tem uma linha inteira do Thor ([composition.py:116](../bot/ego/planners/economy/composition.py#L116)).
Nenhum estilo os constrói, então nunca entram em `mix`: ou entram num estilo, ou saem.

<a id="l6"></a>**L6 · Arquivos de build** (baixa) — `[template]_builds.yml` é o exemplo do template do Ares
("FEEL FREE TO DELETE!!"). Em `terran_builds.yml`, `BuildSelection: Cycle` e `BuildChoices`
([terran_builds.yml:7](../terran_builds.yml#L7)) não decidem nada, porque o `on_start` troca a abertura pela
do estilo; o comentário do próprio arquivo admite. Antes de tirar as chaves, confirmar se o parser do Ares as
exige.

<a id="l7"></a>**L7 · Docs e comentários que descrevem código que não existe** (baixa). **19/09:** os itens do
architecture.md foram corrigidos, e o novas_propostas.md ganhou uma nota com os caminhos novos; faltam os
comentários do código.

- [architecture.md](architecture.md): `bot/ego/core/` ([L4](#l4)). O `ArmyStyle` teria `reactor_on` e
  `techlab_reserve` (seção Matemática, "Estilo de exército"), e `planner.economy_planned` teria `reactors`,
  `reactor_on`, `techlab_reserve` e o input `techlab_reserve`; o plano tem `addons`, `addons_on` e
  `reactor_share`. `mission.updated.kind` lista `main_attack` e `scout` e esquece `defend_area`. A
  lista de `SPLASH_TARGETS` não tem o Hellion (2,0, [frame.py:54](../bot/attention/frame.py#L54)).
- [novas_propostas.md](novas_propostas.md): A2 a A11 apontam para `bot/ego/planners/economy.py`,
  `offense.py` e `intel.py`, que viraram pacotes. A4 e N4.1 ainda falam em CoreArmy, e
  [propostas.md](propostas.md) também.
- Comentários: o de `vision_grace` fala em "hidden contact"
  ([model.py:42](../bot/awareness/model.py#L42)), mas a carência vale para todo contato
  ([model.py:337](../bot/awareness/model.py#L337)). `DetectionPlan.turrets` diz "by base id"
  ([contracts.py:118](../bot/ego/planners/contracts.py#L118)) e é uma tupla de posições.

## I — Inconsistências lógicas

<a id="i1"></a>**I1 · A ofensiva mede o compromisso no exército inteiro** (alta) —
[offense/planner.py:167](../bot/ego/planners/military/offense/planner.py#L167),
[offense/planner.py:258](../bot/ego/planners/military/offense/planner.py#L258),
[main_attack.py:431](../bot/ego/planners/military/offense/missions/main_attack.py#L431),
[main_attack.py:481](../bot/ego/planners/military/offense/missions/main_attack.py#L481).
`committed = awareness.own_power` é o exército inteiro na hora da abertura, inclusive o que a Defense segura
e o que acabou de sair da fábrica. `army_depleted` compara de novo o exército inteiro com metade disso. Um
squad destruído do outro lado do mapa, enquanto a produção repõe em casa, não dispara `army_depleted`; uma
defesa cara em casa conta como perda do ataque. O mesmo vale para `assembled` (poder perto do rally / exército
inteiro): quando a Defense segura mais de 20 % do poder longe do rally, ASSEMBLE, RETREAT e WITHDRAW só
saem pelo timeout. As [medições](architecture.md#medições) contra Zerg CheatInsane registram
`assembled_share` entre 0 e 0,22; quanto disso vem daqui não foi medido. A missão já tem a medida certa à
mão: `MissionFeedback.power` e o `squad` que ela mesma calcula.

<a id="i2"></a>**I2 · Presença possível tratada como atacante ao alcance** (média) —
[model.py:383](../bot/awareness/model.py#L383). O alcance de um contato até uma base é
`base_reach + incerteza`, e a incerteza cresce 2,8 células/s até 16: quanto mais velho o contato, mais "ao
alcance" (o limite vai de 30 a 46 em 5,7 s). Se a última posição dele continua na nossa visão, ele é
esquecido em `vision_grace` (2 s) e o efeito para em 35,6. Se a posição também sai da visão (o squad recuou,
o observador morreu, a visão era de um scan), ele fica até 60 s. Um contato visto assim a 40 células de uma
base entra no alcance 3,6 s depois, entra num incidente, a Defense pede 1,5 × o poder dele (vezes a
confiança) e manda `ATTACK` no centro velho, e `danger` sobe; um STABILIZE pode vir de um contato que foi
embora. É o caso de uma luta perto da terceira base seguida de RETREAT. O campo separa `threat` (possível,
alargado pela incerteza) de `enemy` (crível), mas incidentes e `danger` usam só a leitura possível. Hoje quem
corrige é a visão: o defensor que chega ao ponto o vê vazio, e o contato é esquecido.

<a id="i3"></a>**I3 · Quem conta como atacante** (alta) — a pressão e os incidentes contam todo contato com
`power > 0` ([model.py:395](../bot/awareness/model.py#L395), [model.py:455](../bot/awareness/model.py#L455)),
e isso inclui workers e estruturas armadas.

- Um SCV, Probe ou Drone de scout na nossa mineral abre uma `DefendAreaMission` com prioridade acima da
  ofensiva.
- Uma estrutura estática (Photon Cannon, Spine Crawler, Spore Crawler, Missile Turret, Planetary Fortress) a
  até 30 células de uma base nossa conta enquanto está à vista, e até ~12 min depois de sair dela
  (`structure_memory` de 240 s, esquecida abaixo de 0,05, logo 719 s). Nesse tempo ela mantém um incidente e
  missões de defesa contra algo que não anda. Se a pressão bastar (uma Planetary Fortress a 15 células já
  passa de 0,55), mantém também o STABILIZE, que põe a ofensiva em WITHDRAW enquanto a estrutura existir.

As outras camadas definem "lutador" de outro jeito: a luta local da ofensiva exclui workers
([main_attack.py:614](../bot/ego/planners/military/offense/missions/main_attack.py#L614)), o Stim também
([attack.py:60](../bot/body/behaviors/attack.py#L60)), e o HOLD sai do path com qualquer inimigo à vista,
worker incluído ([hold.py:36](../bot/body/behaviors/hold.py#L36)). "Distinguir scout, worker rush e ataque"
está em "Ainda não implementado"; a estrutura estática não está.

<a id="i4"></a>**I4 · Uma base em construção conta como base** (média) — o `bot.townhalls` do python-sc2
inclui townhalls em construção, e `_bases` não filtra `is_ready`
([frame.py:259](../bot/attention/frame.py#L259)). No frame em que o SCV põe o CC, `saturated_at` sobe 16 (e
o pedido de expansão some), o alvo de gás conta os geysers de uma base que ainda não minera,
`max_production` sobe 4, o MapControl recalcula as candidatas como se a base estivesse de pé, a Detection
pede uma turret para ela e a Awareness passa a medir a ameaça sobre ela. "Bases por ready + pending
explícito" está em "Ainda não implementado"; o efeito no MapControl e na Detection não está.

<a id="i5"></a>**I5 · Três definições de exército** (baixa) — o Engine distribui o que passa em `is_army`
([engine.py:74](../bot/body/engine.py#L74)): Medivac (poder 0) entra, AutoTurret e MULE ficam fora.
`own_power`, o `near` da ofensiva e o exército da Detection usam `not is_worker and power > 0`
([model.py:284](../bot/awareness/model.py#L284)): Medivac fica fora, AutoTurret entra. O lado inimigo usa
`is_army and power > 0`. O poder que a Strategy compara e o conjunto que o Engine concede não são o mesmo
conjunto.

<a id="i6"></a>**I6 · Limiar duplicado** (baixa) — `OPENING_ABORT_DANGER = 0.6`
([investment.py:51](../bot/ego/planners/economy/investment.py#L51)) se descreve como "the strategy's
emergency level", mas é uma cópia de `StrategyConfig.emergency_danger` ([strategy.py:64](../bot/ego/strategy.py#L64)).
Mudar a config não muda a interrupção da abertura, e o fingerprint só vê o valor da config.

<a id="i7"></a>**I7 · Fingerprint incompleto** (média) — o architecture.md diz que ficam fora do
fingerprint as constantes da economia (`PRODUCTION_PER_BASE`, `GAS_WORKER_SHARE`, `MAX_WORKERS`, `COUNTERS`,
`PRIOR_POWER`) e `SPLASH_TARGETS`. Também ficam fora, sem registro: `COVER_MARGIN` (Defense), `EVEN_SHARE`
(admissão da ofensiva), `SCOUT_AT_WORKERS`, `START_BY`, `LAP_TIMEOUT` e `LAP_SECTORS` (Intel),
`OPENING_ABORT_DANGER` e `OPENING_STALL_BANK`, `HOLD_RADIUS`, `ENGAGE_RADIUS`, `STIM_RANGE`,
`STIM_MIN_HEALTH`, `TANK_SIGHT` e `ATTACK_ARRIVAL` (behaviors), `ON_DEPOT`, `_BASE_SNAP_DISTANCE` e `REACH`.
Dois benches com o mesmo fingerprint podem decidir diferente na Defense, no Intel e no micro, não só na
economia.

<a id="i8"></a>**I8 · Sorteio sem seed** (média) — [main.py:196](../bot/main.py#L196):
`styles.choose(..., Random(), ...)` usa um `Random` sem semente, e o bench só semeia o jogo
(`random_seed=spec.seed`, [bench.py:193](../bench.py#L193)). Contra Zerg sem `--armies`, o mesmo spec com o
mesmo seed joga bio ou mech ao acaso, e o determinismo por seed que o harness pressupõe não vale nessas
células. O `game_id` sem sufixo nem diz qual estilo saiu; só o `game.started` diz.

<a id="i9"></a>**I9 · Nenhum MULE na abertura** (média) —
[planner.py:50-51](../bot/ego/planners/economy/planner.py#L50-L51): `orbitals = mules = spend.active`, e
`active` só fica verdadeiro depois do último passo da abertura. As duas aberturas fazem o Orbital cedo
(`0 orbital`, [terran_builds.yml:48](../terran_builds.yml#L48) e [:79](../terran_builds.yml#L79)), e o build
runner do Ares não solta MULE (não há `CALLDOWNMULE` em lugar nenhum do Ares). A energia do primeiro Orbital
acumula sem uso até 36–37 de supply, ou até uma interrupção. O docstring diz "after the opening" de
propósito, mas nenhuma medição sustenta segurar o MULE nesse intervalo.

<a id="i10"></a>**I10 · Um cloak visto uma vez vale para sempre** (média) —
[model.py:280-282](../bot/awareness/model.py#L280-L282). `cloak_seen_at` é gravado com qualquer unidade de
exército inimiga camuflada **ou enterrada**, detectada ou não, e nunca volta a `None`. Daí em diante toda base
pede Missile Turret, pede-se uma Engineering Bay, e cada Orbital guarda 50 de energia
([detection.py:105](../bot/ego/planners/intel/detection.py#L105)), um MULE a menos por Orbital. Isso dura
até o fim do jogo, disparado por uma única unidade vista enterrada (uma Widow Mine de um Terran basta). É um
latch, não uma crença que decai ou que separa um exército camuflado de uma unidade que se enterrou uma vez.

<a id="i11"></a>**I11 · Scan contado antes de acontecer** (baixa) —
[detection.py:86](../bot/ego/planners/intel/detection.py#L86). O planner registra o scan em `_scans` ao
planejá-lo; se o Body não escanear, a área conta como coberta por 12,3 s. Hoje os dois filtros de Orbital
são iguais e o caso não acontece. `DetectionReport.scanned_by` existe, e o planner não o lê.

<a id="i12"></a>**I12 · Scout reconhecido pelo role** (baixa) — `_scouting`
([scout.py:145](../bot/ego/planners/intel/missions/scout.py#L145)) aceita qualquer SCV com role
`SCOUTING`, não a tag que o Engine concedeu à missão (o `MissionFeedback` é ignorado, [C6](#c6)). Hoje nada
mais dá esse role; um segundo uso de `SCOUTING` faria a missão acreditar no scout errado. `observe` roda duas
vezes por frame, uma no planner e outra em `step`.

<a id="i13"></a>**I13 · O ataque nunca termina bem** (baixa) — a `MainAttackMission` não tem caminho para
`COMPLETED`: todo fim é `FAILED` ou `CANCELLED` e inicia o cooldown, e o SEARCH gira pelas expansões sem fim
quando nada é achado. É o "Não existe uma missão para vencer a partida" de [propostas.md](propostas.md);
anotado aqui porque o lifecycle promete um status que a missão nunca usa.

<a id="i14"></a>**I14 · As partes aérea e terrestre competem** (baixa) — as duas partes de um incidente são
alocadas uma depois da outra, sem que uma saiba da outra ([C8](#c8)). A parte aérea vem primeiro (pelo id) e
leva os anti-aéreos mais próximos, Marines e Cyclones, que não contam para a parte terrestre. A terrestre
então puxa Tanks e Marauders de mais longe, embora o Marine que já está no local também atire no chão.

<a id="i15"></a>**I15 · Admissão e expansão por corte** (baixa) — o objetivo lê só `danger`. `army_share`
decide a ofensiva por um corte (`≥ 0,5`), escrito duas vezes
([offense/planner.py:171](../bot/ego/planners/military/offense/planner.py#L171) e
[:234](../bot/ego/planners/military/offense/planner.py#L234)), e `economy ≥ 0,5` decide a expansão. É o
A4/A7/N3 de novas_propostas.

<a id="i16"></a>**I16 · Lugar para expandir** (baixa) — `room = bases < len(map.expansions)`
([investment.py:97](../bot/ego/planners/economy/investment.py#L97)) conta também as expansões que o inimigo
ocupa. Com todas as restantes tomadas, `expand` continua verdadeiro, a razão diz `mineral_lines_saturated`, e
o `ExpansionController` não tem onde pôr o CC.

<a id="i17"></a>**I17 · Em STABILIZE, o MapControl espera no CC** (baixa) —
[planner.py:123](../bot/ego/planners/military/map_control/planner.py#L123). Com uma base ameaçada, o anchor é
a posição do townhall mais ameaçado, enquanto a Defense manda `ATTACK` no centro do incidente. As unidades que
a Defense não pegou esperam no CC (lutam só com inimigo a ≤ 10) em vez de juntar-se à luta. A alternância
entre bases de ameaça parecida já está em "Ainda não implementado".

<a id="i18"></a>**I18 · A escala "em Marines" (a verificar)** (baixa) —
[frame.py:39](../bot/attention/frame.py#L39). `MARINE_POWER = sqrt(9,8 · 45)` usa o dps do Marine com o
cooldown de velocidade *faster* (6 / 0,61), e o teste fixa `unit_power(9.8, 45) == 1`. O `ground_dps` do
python-sc2 é `damage · attacks / weapon.speed`, com o `speed` que a API do jogo entrega, e a API costuma dar
esse valor em segundos de velocidade *normal* (0,8608 para o Marine). Se for isso, um Marine de verdade vale
`sqrt(6,97 / 9,8) ≈ 0,84` "Marines". As razões (`army_share`, a luta local, a composição) não mudam, porque
toda unidade escala igual. Mudam os limiares absolutos escritos em Marines: `minimum_power` (20) pede ~24
Marines reais, e `expected_enemy_power` (0,1/s, teto 100) e `PRIOR_POWER` (20) pesam ~19 % mais contra um
exército real. Para verificar: o `army_power` de `attention.observed` num jogo com só Marines. Além disso, o
docstring do python-sc2 avisa que `ground_dps`/`air_dps` não incluem upgrades: +3 de ataque, nosso ou do
inimigo, não entra no poder. O A13 de novas_propostas cobre bônus, armadura e alcance, mas não upgrades.

## Ordem sugerida

Cada item entra com a sua medição, como o resto do bot; os que mudam decisão precisam de bench antes de
ficar.

1. **I1:** a missão passa a medir compromisso e reunião pelo que recebeu (`MissionFeedback`). É local,
   testável sem partida, e ataca o `assembled_share` de 0–0,22 medido.
2. **I2 + I3:** incidentes e `danger` com presença crível e uma definição única de atacante (workers e
   estruturas à parte). Mexe em Defense e Strategy ao mesmo tempo, então precisa de bench.
3. **C6:** a Defense lê `GrantStatus`, e um déficit vira sinal (para a Strategy ou para a própria missão).
4. **I9, I10:** MULE na abertura e o latch de cloak, cada um com a sua medição de economia.
5. **C1 + F1 + F2:** o campo já entra no score do anchor (`staging`); falta calculá-lo só onde é lido, ou
   sem observador; a degradação da topologia vira razão explícita.
6. **Limpeza de uma vez:** C13, L1–L7, I6, I7 e I8. Não mudam decisão, exceto I8, que muda o que um bench
   mede.
