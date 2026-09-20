# Refactor: economia (composição) e ordem de builds

> Registro de design/revisão histórico. Composição por catálogo, SURVIVE e fronteiras de Planner,
> Mission e Behavior já estão implementadas; o estado atual e os nomes de eventos são definidos em
> [architecture.md](../architecture.md).


> Design consolidado em 19 de setembro de 2026 sobre `5f12156` (`botbandido`). O núcleo foi implementado
> no working tree em 19 de setembro de 2026, ainda sem partidas de validação. Junta a proposta
> STYLE / COUNTER ADAPTATION / SURVIVAL (conversa de 19/09 com outro agente)
> ao que já estava escrito: E1–E9 de [melhorias_propostas_eco.md](../melhorias_propostas_eco.md), N2 de
> [novas_propostas.md](../novas_propostas.md), P0.4 e P1.5 de [propostas.md](../propostas.md) e os achados
> F5, F6, F8, I6, I7, I8, I9, L5 e L6 de [gaps.md](../gaps.md). Onde a proposta nova e os documentos antigos
> discordam, o texto diz, e a decisão está em [Decisões adotadas](#decisões-adotadas-na-implementação).

## Objetivo

Separar três perguntas que hoje estão misturadas numa fórmula só:

| Conceito | Pergunta | Quem responde |
| --- | --- | --- |
| **STYLE** | Que exército é a nossa doutrina, quando não sabemos nada? | O estilo (dado): o baseline |
| **COUNTER ADAPTATION** | Dado o estilo e o exército inimigo acreditado, que exército queremos ter? | O `CompositionPlanner`, pelo catálogo de counters e pela tech atual |
| **SURVIVAL** | Com a base caindo agora, o que conseguimos pôr em campo a tempo? | A Strategy decide que é emergência; o planner responde |

A composição normal é `baseline + adaptação = target`. O SURVIVE quebra as restrições do estilo por um tempo, sem
mudar o estilo. A execução continua do Body e do Ares (`SpawnController`, `ProductionController`).

## Como era antes deste refactor

O pacote [economy/](../../bot/ego/planners/economy/) tem quatro módulos de funções soltas: `investment` (quanto
investir), `styles` (BIO e MECH como dado), `composition` (o mix) e `planner.plan`, que junta tudo num
`EconomyPlan` de 18 campos. O estilo é sorteado em `BotBandido.on_start` e mora em `Layers.army`.

```text
value(u) = (Σ_e poder(e)·alcance(u,e)·COUNTERS[u][e] + PRIOR_POWER) / (Σ_e poder(e) + PRIOR_POWER)
share(u) ∝ prior(u)·value(u)              proporção de CABEÇAS para o Ares; prioridade = a do estilo
```

`poder(e)` é `awareness.seen_enemy_types` (poder visto vivo por tipo, τ = 180 s), `COUNTERS` é uma matriz de mão,
`REACH` diz o que cada unidade nossa atinge. Em STABILIZE o plano liga `freeflow` e o Ares ignora as proporções.

O que está errado, já escrito e medido (seção 2 do melhorias_propostas_eco.md):

- **O estilo multiplica para sempre** (2.2): com evidência infinita, Cyclone:Marine contra Mutalisk continua 2:1
  porque 0,22:0,10 é o prior do MECH.
- **A matriz não casa com o que a Awareness vê** (2.3): a Awareness guarda o modo (`SIEGETANKSIEGED`,
  `LURKERMPBURROWED`, `LIBERATORAG`…), `COUNTERS` usa o tipo base, e toda consulta nesses modos cai em 1,0.
- **Unidade de medida é a cabeça** (2.1): os "10 % de Marines" do MECH são 2,7 % do dinheiro.
- **A prioridade fixa do estilo pode travar o `SpawnController`** (2.5, hipótese; o E2 mede).
- **Em STABILIZE a composição sai inteira** (2.7): o `freeflow` treina o que o estilo tem, na ordem do estilo.
- `COUNTERS` tem linhas de Thor, Widow Mine e Viking que nenhum estilo constrói ([L5](../gaps.md#l5)); o limiar da
  interrupção da abertura é uma cópia do da Strategy ([I6](../gaps.md#i6)); as constantes da economia ficam fora do
  fingerprint ([I7](../gaps.md#i7)); o sorteio do estilo não tem seed ([I8](../gaps.md#i8)).

Por que o MECH tem Marine hoje: em `bench/ci-mech/002` um ling rush interrompeu a abertura aos 181 s com um Marine
e nenhum Hellion, e, sem Marine no mix, a Barracks ficou ociosa enquanto as duas bases caíam (`bench/ci-mech-542`,
Rush: derrota aos 520 s). Com os Marines (`bb8f00c`), `bench/ci-mech-5f1` teve 5 timeouts e 0 derrotas. **Tirar o
Marine do MECH sem o SURVIVE no lugar traz essa derrota de volta** — por isso as duas coisas entram na mesma fatia
([Fatias](#fatias)).

## Desenho

### Estilo = baseline

- **BIO:** o baseline de hoje (Marine 0,55, Marauder 0,20, Siege Tank 0,15, Medivac 0,10).
- **MECH:** Hellion, Cyclone e Siege Tank, sem Marine. Mantendo a relação entre os três (0,35 : 0,22 : 0,33):
  **Hellion 0,39, Cyclone 0,24, Siege Tank 0,37**. A Barracks pode ficar ociosa.
- O estilo continua levando a abertura, os upgrades em ordem, `addons_on` e as raças contra quem é sorteado. O
  anúncio no chat lista o baseline.

### Catálogo de counters

Conhecimento estático, separado da conta: para cada unidade inimiga, uma lista **ordenada** de respostas Terran.
O primeiro item é a resposta preferida; os seguintes, alternativas cada vez menos desejadas.

```yaml
# terran.yaml, protoss.yaml, zerg.yaml: um arquivo por raça inimiga
MUTALISK: [THOR, MARINE, CYCLONE, VIKINGFIGHTER]
LURKERMP: [SIEGETANK, LIBERATOR, MARAUDER]
BROODLING: []         # conhecida, sem resposta própria: some sozinha
```

`CounterCatalog.counters_for(tipo)` devolve a lista na ordem declarada. O planner não conhece o YAML. O catálogo:

- **carrega os três arquivos e valida no `on_start`** (erro, não aviso): todo nome é um `UnitTypeId`; toda chave é
  canônica (não é chave do `UNIT_UNIT_ALIAS`); toda resposta é uma unidade Terran treinável
  (`UNIT_TRAINED_FROM` dá Barracks, Factory ou Starport); nada repetido numa lista nem entre arquivos;
- **distingue três respostas**: lista com itens; lista vazia (conhecida, sem counter); ausente (fora do
  catálogo). Ausente vai para o log como `uncatalogued` e fica com o baseline;
- **entra no fingerprint**: um hash do conteúdo dos três arquivos em `CompositionConfig`, senão dois benches com o
  mesmo fingerprint jogam catálogos diferentes (o [I7](../gaps.md#i7) de hoje, com `COUNTERS`).

`COUNTERS` e o `prior × value` saem. `REACH` fica (é física: o que cada unidade nossa atinge), porque o SURVIVE
precisa saber quem atinge a ameaça; o [F6](../gaps.md#f6) (tipo fora de `REACH` entra calado) vira erro na
validação.

**Canonicalização.** Antes de consultar, o tipo visto passa pelo `UNIT_UNIT_ALIAS` do python-sc2 (é o E3). Conferido
no ambiente do projeto: `SIEGETANKSIEGED → SIEGETANK`, `LIBERATORAG → LIBERATOR`, `VIKINGASSAULT → VIKINGFIGHTER`,
`LURKERMPBURROWED → LURKERMP`, `ROACHBURROWED`, `BANELINGBURROWED`, `WIDOWMINEBURROWED`, `THORAP`, os outros
`*BURROWED` Zerg, `WARPPRISMPHASING` e `OBSERVERSIEGEMODE`. `HELLIONTANK` (Hellbat) **não** é alias: é tipo
próprio e tem entrada própria. O modo continua valendo para a física: o alcance usa o tipo visto
(`VIKINGASSAULT` está no chão, `LIBERATORAG` voa), pelo `flying` do `UNIT_DATA` do Ares. O poder por tipo também
fica o do modo (a Awareness guarda o poder de quando viu: um tanque visto em siege pesa 4,3, fora dele 2,7).

Cuidado com a validação por camada: o Colossus é terrestre (`flying: False`) e é alvo de antiaéreo. Se o loader
checar que a resposta atinge a camada do inimigo, o Colossus precisa desse caso, senão o Viking é rejeitado.

**Tensão com o E7 e com "não ajustar `COUNTERS` partida a partida".** A lista é opinião, como a matriz de hoje.
A diferença é o formato: a ordem é fácil de revisar e não finge precisão. Regra proposta: mudar a ordem só com
evidência de bench ou replay, e o fingerprint registra. O E7 (eficiência por par derivada do `game_data`) deixa de
ser o próximo passo e vira um jeito futuro de **ordenar ou validar** o catálogo.

### Produzível agora

Um counter só entra no target se a tech atual o treina. A definição é a do Ares, `tech_ready_for_unit`
([custom_bot_ai.py:246](../../ares-sc2/src/ares/custom_bot_ai.py#L246)): toda estrutura de
`UNIT_TECH_REQUIREMENT` pronta (com os equivalentes de `EQUIVALENTS_FOR_TECH_PROGRESS`). É o mesmo teste que o
`SpawnController` faz ([spawn_controller.py:130](../../ares-sc2/src/ares/behaviors/macro/spawn_controller.py#L130)).
Os requisitos vêm do Ares, nunca do YAML. Exemplos: Thor pede Armory e Tech Lab de Factory; Viking, Liberator e
Medivac pedem Starport; Hellion e Widow Mine pedem Factory.

O Ego não toca o bot. Proposta: a **Attention** expõe `tech_ready: frozenset[UnitTypeId]`, calculado em `observe`
chamando o próprio `bot.tech_ready_for_unit` para os tipos Terran do catálogo e dos estilos — é um fato do frame,
como `upgrades`. A alternativa é uma função pura sobre `attention.own_structures` com os mesmos dicts do Ares.

**Por que isto é uma guarda, não um detalhe.** O `ProductionController` do Ares roda `TechUp` para todo tipo do
dict ([production_controller.py:145](../../ares-sc2/src/ares/behaviors/macro/production_controller.py#L145)): um
Thor no dict sem Armory faz o Ares construir o Armory. Pôr no target só o que já é produzível impede tech implícita.
Decidir **investir** em tech por causa de um counter é outra decisão (o E6.2: preço da infraestrutura amortizado) e
fica fora desta versão.

"Produzível" é "a tech existe", não "há capacidade agora": o Ares não olha se o Tech Lab está numa Factory ociosa.
O SURVIVE, que precisa de capacidade, conta as estruturas de produção prontas em `own_structures`.

### Adaptação ao inimigo

Para cada tipo inimigo acreditado `e` com poder `p_e` (`seen_enemy_types`):

```text
c        = alias(e)                                      tipo canônico
resp(e)  = primeiro u de catálogo[c] com u ∈ tech_ready   nenhum → 'no_producible_counter', fica com o baseline
R         = ameaças com resposta produzível
U         = poder das ameaças sem resposta (vazia, ausente ou sem tech)
target(u) = ((W + U) · baseline(u) + Σ_{e ∈ R} p_e · [u = resp(e)])
            / (W + U + Σ_{e ∈ R} p_e)
```

- **A mistura é aditiva, não multiplicativa.** Corrige o 2.2: o baseline pesa
  `(W + U) / (W + U + Σ_{e ∈ R} p_e)`; quando todas as ameaças têm resposta, muita evidência faz o target tender
  às respostas.
- **Uma ameaça sem resposta volta ao baseline.** Seu poder entra em `U`; portanto o target continua normalizado
  e, se nenhuma ameaça tiver resposta produzível, sai exatamente o baseline.
- **Intensidade sem limiar.** Poucos lings mexem pouco; um exército inteiro mexe muito. `W` v1 = `PRIOR_POWER`
  (20 Marines, o de hoje); o E6.1 propõe `W = max(0, estimado − visto)` da Awareness (o estilo responde ao
  desconhecido). A estabilidade vem da crença (τ = 180 s), não de histerese.
- **Uma resposta por ameaça, a primeira produzível.** A troca de resposta só acontece quando a tech muda (o Armory
  fica pronto: Mutalisk passa de Marine a Thor), que é um degrau físico, não um corte de preferência.
- **O estilo não restringe o counter.** MECH contra Mutalisk sem Armory põe Marine no target, como adaptação
  (`counter_adaptation`), não como doutrina. Contra Mutalisk com Armory, põe Thor — hoje o MECH respondia com
  Cyclone 0,22 → 0,42 (`bench/ci-mech-5f1`, Air). É a mudança de comportamento a medir na célula Air.
- **Prioridade de um tipo que o estilo não tem:** a menor do estilo (o maior número), até o E4. Assim um counter
  caro (Thor, Viking) nunca trava o laço do `SpawnController` para as unidades do estilo (2.5).
- **Consequência conhecida, fora desta versão:** Marines ou Vikings entrando no MECH não ganham upgrade de
  infantaria nem add-on (`addons_on` é só a Factory). É o E8.

### SURVIVE

**Na Strategy.** A Strategy já tem o que o SURVIVE precisa: STABILIZE com histerese e a entrada por emergência
(`danger ≥ emergency_danger`, 0,6, razão `emergency_threat`). A proposta é o que o E1 já pedia: a Strategy publica
uma política para a economia, ao lado de `offense`, com três níveis:

| Nível | Quando | A composição |
| --- | --- | --- |
| investir | BUILD_ADVANTAGE | baseline + adaptação; upgrades e add-ons |
| exército primeiro | STABILIZE | baseline + adaptação, `freeflow`; sem upgrade nem add-on (o STABILIZE de hoje) |
| **SURVIVE** | STABILIZE em que `danger` chegou a `emergency_danger` | o de cima + o fallback de sobrevivência |

- **Entrada (v1):** em STABILIZE, `danger ≥ emergency_danger` em qualquer frame — a condição com que a
  `investment` interrompe a abertura hoje, mas lida da config da Strategy e não de uma cópia. A mesma política passa
  a interromper a abertura: o `OPENING_ABORT_DANGER` sai (fecha o [I6](../gaps.md#i6)).
- **Saída:** o SURVIVE dura até a Strategy sair do STABILIZE, com a histerese que ela já tem (`switch_margin`,
  `minimum_dwell`). Nenhum limiar novo; sair por `danger < 0,6` oscilaria (Ley Lines, 715–875 s, `danger` entre
  0,45 e 0,6).
- **Entrada (v2), se a v1 disparar demais:** emergência **e** déficit — o poder do incidente numa camada (os
  incidentes separam `ground_power` e `air_power`) maior que o nosso poder que atinge essa camada, ou uma concessão
  `PARTIAL`/`REJECTED` da Defense ([C6](../gaps.md#c6)). É isto que separa "a doutrina não responde" de "a base
  está sob ataque".

**No planner.** Durante o SURVIVE a pergunta muda de "o que quero ter" para "o que consigo pôr em campo a tempo":

- candidatos: todo tipo em `tech_ready`, com estrutura de produção pronta, que atinge alguma camada da ameaça do
  incidente (`REACH` contra o `ground_power`/`air_power`);
- entre eles, a ordem do catálogo para os tipos do incidente; a prioridade do dict segue essa ordem;
- `freeflow` ligado: nenhuma estrutura de produção que pode treinar algo que atinge a ameaça fica ociosa. É
  exatamente o caso do `ci-mech/002`: Barracks pronta, Factory sem entregar, Marine atira em ling;
- `reason = survival_fallback`, com o incidente e cada tipo que entrou fora do estilo.

Fica fora e continua em "Ainda não implementado": Bunker, reparo e worker pull. O SURVIVE é o lugar natural deles
depois.

**Volta ao baseline.** O planner não guarda memória da emergência: o target é recalculado a cada frame de
(estilo, crença, tech, política). Quando a política sai do SURVIVE, o fallback some e o Marine sai do dict. Os
Marines já feitos continuam no exército (o Engine os concede como qualquer unidade); o `SpawnController` só conta os
tipos do dict ([spawn_controller.py:99](../../ares-sc2/src/ares/behaviors/macro/spawn_controller.py#L99)); o
`ProductionController` não acrescenta Barracks para um tipo que não está no dict. Se Mutalisk continua acreditado,
o Marine fica — como `counter_adaptation`, não como sobrevivência.

### CompositionPlan e logs

O `CompositionPlan` (o contrato do E1 e do N2.1) carrega a explicação:

```text
CompositionPlan
  style                   'mech'
  baseline                ((HELLION, 0.39), (CYCLONE, 0.24), (SIEGETANK, 0.37))
  enemy                   ((tipo visto, tipo canônico, poder), ...)
  adaptations             ((ameaça, resposta, poder, pulados), ...)   pulados: ((THOR, 'tech_missing'), ...)
  survival                None | (incident_id, ((tipo, 'fora_do_estilo'), ...))
  units                   ((tipo, proporção, prioridade), ...)       o target, para o Ares
  freeflow, upgrades, addons, addons_on, reactor_share
  reason                  style_baseline | counter_adaptation | survival_fallback
  inputs
```

`planner.economy_planned` mantém nome e campos (o viewer lê) e ganha os novos. Uma adaptação vai compacta, por
exemplo `MUTALISK→MARINE (THOR: tech_missing)`, `LURKERMPBURROWED→SIEGETANK`. As perguntas que o log tem que
responder:

| Pergunta | Campo |
| --- | --- |
| Qual era o estilo e o baseline? | `style`, `baseline` |
| Que inimigo provocou adaptação, e qual counter? | `adaptations` |
| O counter estava produzível? Qual foi pulado e por quê? | `adaptations[].pulados`, `tech_ready` no `inputs` |
| Estávamos em SURVIVE? | `survival`, a política em `strategy.decided` |
| Qual foi o target final? | `units` |
| O Ares treinou o target, ou travou? | `behavior.spawn_executed` (+ `blocked_by`/`short_of` do E2) |

## Ordem de builds

Hoje:

- **Aberturas.** Duas, em [terran_builds.yml](../../terran_builds.yml): `BioThreeOneOne` e `MechHellionTank`. O
  estilo escolhe e o `on_start` troca a abertura do Ares por `switch_opening`. `BuildSelection: Cycle` e
  `BuildChoices` não decidem nada ([L6](../gaps.md#l6)).
- **Sorteio do estilo.** Sem seed ([I8](../gaps.md#i8)); contra Random só sai BIO, e o estilo não é revisto quando a
  raça aparece ([F5](../gaps.md#f5)); MECH só contra Zerg.
- **Saídas da abertura.** Emergência (a cópia do limiar, [I6](../gaps.md#i6)) e banco parado
  (`OPENING_STALL_BANK`, 1.000). Nenhum MULE durante a abertura ([I9](../gaps.md#i9)).
- **Ordem do gasto depois da abertura.** É a ordem do `MacroPlan` no Body, e o Ares para no primeiro que age:
  `AutoSupply`, `UpgradeCCs`, `BuildWorkers`, gás, expansão, pesquisa, `SpawnController`, `ProductionController`;
  add-ons e detecção passam na frente por estarem fora dele. É uma decisão do Ego morando no Body (E9).

O que já foi proposto: uma abertura por raça (N2.3), um ramo seguro por `switch_opening` num sinal de rush antes do
fim da abertura (N2.4, depende de scouting, N4.1), um portfolio por matchup (P1.5), a ordem do gasto decidida no
Ego com `strategy.army` (E9, N3.2). No branch `matematização` há a build `BattleMech` do usuário (Barracks Reactor
trocado para a Factory, Hellions, Starport com Tech Lab para Banshee e Cloak, Factories e Starport extras pela 3ª
base) — outra linhagem, referência se o MECH daqui evoluir.

Como se liga ao refactor de composição:

- a abertura continua sendo parte do estilo;
- o SURVIVE assume da abertura (uma saída de emergência só, a da Strategy);
- depois dele, o refactor de ordem de builds propriamente dito é o E9 (a ordem do gasto sai do Body) e, com
  scouting, o N2.3/N2.4. O que "ordem de builds" cobre está em [Em aberto](#em-aberto).

## Fatias

A proposta original ordena 1) catálogo, 2) canonicalização, 3) catálogo na composition, 4) tirar o Marine do MECH,
5) baseline + adaptação, 6) SURVIVE na Strategy, 7) fallback, 8) logs, 9) testes, 10) bench. Reordenado para que
cada fatia seja medível sozinha e nenhuma reintroduza a derrota do `ci-mech/002`:

| # | Fatia | Muda gameplay? | Medir |
| --- | --- | --- | --- |
| 1 | `CompositionPlanner` e `InvestmentPlanner` como classes com config (fingerprint), `CompositionPlan` e `InvestmentPlan` em `contracts.py`, estilo dentro do planner, seed no sorteio (E1, [I8](../gaps.md#i8)) | Não | A suíte; o bench repete as partidas por seed |
| 2 | `CounterCatalog`, os três YAMLs, canonicalização, `tech_ready` na Attention. A adaptação é calculada e vai para o log **em shadow**, ao lado do mix de hoje | Não | Ler no JSONL de `ci-bio`/`ci-mech` o que a adaptação teria pedido |
| 3 | Baseline + adaptação controlando; `COUNTERS` e o `prior × value` saem. BIO e MECH ainda com Marine | Sim | `ci-bio` e `ci-mech` × Zerg CheatInsane (Air é a célula que mais muda) + uma célula Terran (`SIEGETANKSIEGED`, `LIBERATORAG`) |
| 4 | Política de economia na Strategy (três níveis), SURVIVE, fallback, **MECH sem Marine**, a abertura interrompida pela política ([I6](../gaps.md#i6)) | Sim | `ci-mech` Rush (o caso do `ci-mech/002`) e a transição MECH → SURVIVE → MECH no log |
| 5 | Logs: adaptação compacta, `survival`, `blocked_by`/`short_of` (E2); viewer | Não | As perguntas da tabela de logs respondidas num JSONL |

Depois, na ordem do melhorias_propostas_eco.md: E4 (prioridade calculada, se o E2 confirmar a trava), E5 (mix em
gasto e preço-sombra), E8 (upgrades e add-ons pelo mix), E9 (ordem do gasto no Ego), N2.3/N2.4 (aberturas).

Cada fatia é comparada com a execução medida mais recente da mesma matriz (hoje `bench/ci-bio-5f1` e
`bench/ci-mech-5f1`); sem ganho medido, é revertida e registrada. O placar contra CheatInsane não separa quase nada
(os timeouts são limitados pela ofensiva, N7.1): o que sustenta cada fatia é o mecanismo no JSONL.

## Testes

- **Catálogo:** carrega os três arquivos; rejeita nome inexistente, chave não canônica, resposta não Terran e
  repetição; mantém a ordem; `[]` e ausente são respostas diferentes; `SIEGETANKSIEGED` consulta `SIEGETANK` e
  `LURKERMPBURROWED` consulta `LURKERMP`; mudar um YAML muda o fingerprint.
- **Estilos:** o baseline MECH não tem Marine; a soma das proporções de cada estilo é 1.
- **Composição normal:** sem inimigo, o target é o baseline (e o dict do Ares sai igual ao de hoje para BIO); com
  ameaça, o catálogo é consultado e o target se move; com a primeira resposta sem tech (Thor sem Armory), entra a
  próxima produzível (Marine); sem nenhuma produzível, `no_producible_counter` e baseline; poucos inimigos mexem
  pouco, muitos mexem muito, sem degrau.
- **SURVIVE:** MECH normal não tem Marine; MECH em SURVIVE com Barracks pronta e ameaça terrestre põe Marine;
  com a Strategy de volta a BUILD_ADVANTAGE, o Marine some do target; uma unidade que não atinge a camada da ameaça
  não entra; SURVIVE antes do fim da abertura a interrompe.
- **Strategy:** a política sai de SURVIVE só quando o objetivo sai de STABILIZE.

## Decisões adotadas na implementação

Decisões usadas no código:

1. **Onde mora o catálogo.** `bot/ego/planners/economy/counters/`, com loader em `counter_catalog.py`.
2. **A unidade da mistura.** Supply, convertido em cabeças na fronteira com o Ares; sem adaptação o dict sai
   exatamente igual ao baseline.
3. **O peso do baseline `W`.** Constante em 20 na v1.
4. **Escolha do counter.** Primeira resposta produzível que também atinge o modo observado.
5. **SURVIVE.** Política da economia com `INVEST`, `ARMY_FIRST` e `SURVIVE`; fica latched até sair de
   `STABILIZE`.
6. **Entrada do SURVIVE.** v1, pelo limiar de emergência da Strategy.
7. **Ordem de builds.** Aberturas adaptativas, investimento proativo em tech e E9 continuam como fatias próprias,
   depois dos benches deste refactor.

## Estado da implementação

- Implementado: catálogo YAML por raça, validação forte e fingerprint; aliases e camada física; mistura em supply;
  primeira resposta produzível; `CompositionPlan`; política latched de SURVIVE; fallback por capacidade pronta;
  MECH sem Marine; interrupção da abertura pela política; seed reproduzível no bench; telemetria detalhada.
- Pendente: partidas/benches, `blocked_by`/`short_of` do E2, investimento proativo na infraestrutura de um
  counter bloqueado, upgrades/add-ons para respostas fora do estilo e a ordem de gasto E9.
