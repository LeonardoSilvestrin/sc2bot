# Novas propostas

> Revisão feita em 18 de setembro de 2026 sobre o commit `f910e1a` (`botbandido`).
> Foram lidos o fluxo de frame, Attention, Awareness, Strategy, todos os planners,
> o Engine, todos os behaviors, o harness, a abertura e as medições registradas em
> [architecture.md](architecture.md). Nenhuma partida foi jogada para escrever isto.
>
> Este documento complementa [propostas.md](propostas.md) e não o substitui. Quando
> uma lacuna já está lá, ela aparece aqui só se a revisão trouxe um fato novo ou um
> jeito concreto de atacá-la. Os ids são `N1`…`N8` para não colidir com `P0`…`P2`.

> **Estado em 19 de setembro de 2026 (`5f12156`).** Os caminhos citados são os de `f910e1a`: `economy.py`,
> `offense.py` e `intel.py` viraram pacotes em `bot/ego/planners/` (`economy/`, `offense/`,
> `intel/`), e o CoreArmy virou o MapControl. Desde então: N1 em parte (matriz Zerg CheatInsane ×
> Macro/Timing/Rush/Air/Power, sem métricas no `summary.json`); N2.1 em parte (a economia virou pacote com
> `composition` e dois estilos, sem planner nem contrato próprios). O N2.1/N2.2 é o próximo refactor, em
> [staging/economia-e-builds.md](staging/economia-e-builds.md).

## Diagnóstico

O P0 está feito e o bot vence a IA VeryHard Macro: 9/9 em `bench/6f`. Isso é bom e
é também o problema principal. **O benchmark saturou.** Com 9/9, nenhuma mudança
pode aparecer como ganho no placar. As próximas melhorias (build, composição,
micro) só são mensuráveis contra um oponente que ainda ganha do bot.

A revisão do código mostra três padrões:

1. **O bot joga igual contra qualquer adversário.** São uma abertura, uma composição
   e uma ordem de upgrades para as três raças. Nada do que o scout ou a Awareness
   veem muda o que é construído.
2. **Várias leituras são calculadas e ninguém as consome.** Alguns sinais da
   Strategy e o campo de influência inteiro não mudam nenhuma decisão.
3. **O combate é um a-move com Stim.** A decisão de lutar ou recuar é boa. A
   execução é o limite: não há foco, stutter, posicionamento de tanque nem recuo
   que evite perigo.

## Achados da revisão

Fatos lidos no código, sem interpretação:

| # | Onde | Achado |
| --- | --- | --- |
| A1 | [terran_builds.yml](../terran_builds.yml#L7) | `BuildSelection: Cycle` com um único build (`BioThreeOneOne`) para Protoss, Terran, Zerg e Random. |
| A2 | [economy.py:56](../bot/ego/planners/economy.py#L56) | `COMPOSITION` é constante: 55 % Marine, 20 % Marauder, 15 % Siege Tank, 10 % Medivac. Não há unidade antiaérea além do Marine, nem Viking, Liberator, Widow Mine, Ghost ou Thor. |
| A3 | [economy.py:65](../bot/ego/planners/economy.py#L65) | `UPGRADES` é uma lista única e sequencial. Com uma Engineering Bay, weapons e armor saem em série. |
| A4 | [strategy.py:95-105](../bot/ego/strategy.py#L95-L105) | `strategy.army` e `strategy.risk` não são lidos por nenhum planner (`risk` só vai para os `inputs` do CoreArmy). `strategy.economy` só é lido em `economy >= 0.5`, que é sempre verdadeiro com `danger = 0`. Na prática, as preferências contínuas da Strategy não decidem nada. |
| A5 | [model.py:295](../bot/awareness/model.py#L295) | O `InfluenceField` é recalculado todo frame, e só logs, overlay e SVG o leem. A topologia só é consumida pela rota do scout ([intel.py:103](../bot/ego/planners/intel.py#L103)). |
| A6 | [economy.py:114](../bot/ego/planners/economy.py#L114) | A terceira base em diante só é pedida **depois** que as linhas de mineral saturam. Um CC leva cerca de 71 s, e nesse intervalo os workers excedentes rendem pouco. |
| A7 | [offense.py:304](../bot/ego/planners/offense.py#L304) | Só há dois gatilhos de ataque: vantagem estimada (`army_share ≥ 0,5`) ou supply 190. Não existe o conceito de janela de timing, como upgrade concluído ou tech do inimigo ainda ausente. |
| A8 | [offense.py](../bot/ego/planners/offense.py) + [engine.py](../bot/body/engine.py) | A proposta ofensiva pede "todas as livres". Uma unidade recém-produzida no meio do ataque é concedida ao squad e atravessa o mapa sozinha (já anotado em propostas; o mecanismo está aqui). |
| A9 | [retreat.py:37](../bot/body/behaviors/retreat.py#L37) | O recuo usa `PathUnitToTarget(..., sense_danger=False)` e não atira no caminho. Um recuo sob fogo tende a atravessar a ameaça em vez de contorná-la. |
| A10 | [attack.py:58](../bot/body/behaviors/attack.py#L58) | Todo `ATTACK` é `AMove` + Stim + Medivac seguindo o centro do grupo. O Ares já traz `ShootTargetInRange`, `StutterUnitBack`, `KeepUnitSafe`, `MedivacHeal`, `PickUpCargo`, `StutterGroupBack` e `KeepGroupSafe`, e nenhum deles é usado. |
| A11 | [intel.py:31](../bot/ego/planners/intel.py#L31) | O scout é um SCV, uma vez, antes de 240 s. Depois disso o bot só vê o que o exército encontra. |
| A12 | [model.py:64-66](../bot/awareness/model.py#L64-L66) | `expected_enemy_power` é uma reta de 0,1 Marine/s a partir de 120 s, com teto 100. Nenhum número foi calibrado contra um exército real. |
| A13 | [frame.py:39](../bot/attention/frame.py#L39) | O poder, `sqrt(dps · alvos · hp)`, ignora o bônus de dano por atributo (armored, light, bio), armadura e alcance. Um Marauder "vale" o mesmo contra Zergling e contra Stalker. |
| A14 | [bench.py](../bench.py) | O harness só joga contra a IA embutida, e toda medição até hoje foi VeryHard Macro num único mapa. O `bench.py` já aceita `--difficulties` e `--ai-builds`; eles só nunca foram usados. |
| A15 | Ares | `BuildOrderRunner.switch_opening(nome)` existe (`build_order_runner.py:189`). O bot só usa `set_build_completed()`. |

## Propostas

### N1 — Subir a régua do benchmark (antes de tudo)

**Por quê:** sem um oponente que ainda vença o bot, nenhuma proposta abaixo pode
ser medida (A14). Isso custa pouco, porque o harness já suporta tudo.

- Nova matriz de referência: `CheatInsane` (e/ou `CheatMoney`) × `Macro`, `Rush`,
  `Timing`, `Air`, `Power` × três raças. Isso usa só `--difficulties` e
  `--ai-builds`, sem código novo.
- Dois ou três mapas do pool atual, e não só Persephone. As builds por matchup
  (N2) e o `RegionState` dependem de geometria.
- Um ou dois bots do ladder rodando pelo `local-play-bootstrap` (já citado em
  propostas.md). Um bot Zerg de ling/bane e um Protoss de gateway cobrem os
  piores casos da composição atual.
- **Métrica pareada por seed:** o `compare` hoje mostra dois summaries lado a lado.
  Ele deveria mostrar a diferença por célula (mesmo mapa, raça e seed). Com
  pareamento, 9 jogos separam bem mais do que 9 contra 9 independentes.
- **Métricas intermediárias no `summary.json`**, extraídas do JSONL que já existe:
  army supply em 6, 8 e 10 min; banco médio de minerais e gás; a troca de recursos
  (valor morto contra valor perdido, que o replay tem); o primeiro ataque
  (`ASSEMBLE`); e o número de `RETREAT`. Uma mudança de micro aparece na troca
  muito antes de aparecer no placar.

**Critério:** existe uma matriz onde o bot perde de 30 % a 70 % dos jogos. É a
faixa em que uma mudança pode aparecer.

### N2 — Build e composição que reagem ao adversário

É o pedido original: "variações". A proposta é variar pelo que o bot sabe, não
por sorteio (A1, A2, A3, A15).

**N2.1 — Um planner `composition`, extraído do `economy`.** Primeiro como
refactor puro: mesmos valores e mesmos testes, e o bench tem que dar igual. O
`economy` fica com "quanto investir" (workers, bases, gás, emergência), e o
`composition` com "o que construir" (mix de unidades, upgrades, add-ons).
Contrato:

```text
CompositionPlan:
  units:     ((UnitTypeId, proporção, prioridade), ...)
  upgrades:  (UpgradeId, ...)            # em ordem
  addons:    reactor/techlab por tipo de produção
  reason, inputs
```

**N2.2 — Mix contínuo pelo que foi visto.** Cada candidato (Marine, Marauder,
Tank, Medivac, Viking, Widow Mine, Liberator, Ghost, Thor) recebe um valor
contínuo: o dano efetivo contra o exército inimigo **acreditado**, e não contra
o que está visível agora. A fonte é o `_army` da Awareness, com tipos e decaimento.
O valor é multiplicado pela sobrevivência contra esse exército e dividido pelo
custo. A proporção de cada unidade segue esse valor. Não há `if` por matchup, e
a raça só entra como prior antes do primeiro avistamento. A estabilidade vem da
memória longa do exército (τ = 180 s), não de histerese na composição. O dano
efetivo por par de tipos sai de `Unit.calculate_dps_vs_target` do python-sc2,
tabelado uma vez por par (ver N5.2).

**N2.3 — Uma abertura por raça.** No YAML, três builds em `BuildChoices` e uma
por raça, sem `Cycle`:

| Contra | Mudança sobre o `BioThreeOneOne` |
| --- | --- |
| Zerg | Reaper expand, Bunker na natural, 3º CC cedo; Widow Mines no lugar de parte dos Marines |
| Protoss | Bunker na natural, Factory antes, primeiro Tank cedo contra gateway |
| Terran | Factory e Starport mais cedo; Vikings/Liberator contra tank e Liberator |
| Random | O atual, até ver a raça |

**N2.4 — Ramo seguro com `switch_opening`.** Quando o scout ou a Awareness veem
um sinal de rush antes de `opening_done` (pool cedo, gateway/barracks proxy,
nenhuma natural inimiga por volta de 2:30), o bot troca a abertura por
`switch_opening("<Raça>Safe")` em vez de só interromper. É uma variante por
raça, e o motivo vai para o JSONL. Depende de N4.1: sem scouting não há
gatilho.

**N2.5 — Upgrades em paralelo.** Duas Engineering Bays a partir da 3ª base.
Armory (e vehicle weapons) só quando o `composition` pedir tanks ou mech de
verdade, e não na posição fixa 8 da lista.

**Medir:** a troca de recursos e o army supply por raça na matriz de N1. A
composição reativa tem que ganhar do mix fixo pelo menos na célula `Air`, que
hoje é a pior aposta (A2).

### N3 — Strategy que decide alguma coisa

Hoje a Strategy devolve três números contínuos que ninguém consome (A4). Há duas
saídas honestas: consumir os números ou apagá-los.

- **N3.1 — Expansão por previsão.** Troca `saturated` por "vai saturar antes de
  o CC ficar pronto": workers mais a taxa de produção vezes o tempo de
  construção do CC, comparados com a capacidade. O `strategy.economy` modula
  quanto antes isso acontece, em vez de ser um portão que nunca fecha (A6).
- **N3.2 — Gasto dividido por `strategy.army`.** Hoje o gasto de exército é
  "`SpawnController` quando sobra". A preferência `army` passa a ser o alvo da
  fração do gasto no exército. Com `army` alto, workers e expansão esperam; com
  `army` baixo, eles passam na frente. É a primeira vez que a Strategy muda o
  macro de forma contínua.
- **N3.3 — `risk` ou sai ou vira entrada da ofensiva.** Uma proposta concreta é
  o `engage_share` da ofensiva escorregar com `risk`: mais agressivo quando a
  estimativa do inimigo é confiável e há folga em casa. Se nenhum consumidor
  aparecer, apaga-se o campo, que hoje só polui os logs.

### N4 — Informação recorrente

A11 é o maior ponto cego depois dos 4 minutos. Tudo em N2 e N3 depende de saber
o que o inimigo tem.

- **N4.1 — Reaper e scan como sensores.** O Reaper da abertura já existe e hoje
  fica parado no rally com o CoreArmy, como qualquer unidade livre. Ele pode receber uma proposta `SCOUT` da Intel
  com rota natural → terceira → proxies prováveis. O scan de informação sai
  quando uma pergunta ficou velha: "tech desconhecido há mais de 90 s" ou
  "terceira base não vista".
- **N4.2 — Perguntas explícitas com idade.** A Intel mantém um conjunto pequeno
  de perguntas (bases, tech de ar, cloak, tamanho do exército), cada uma com a
  idade da última resposta. O valor de observar é idade × quanto a resposta
  muda uma decisão (N2.2 e N2.4). Isso é o P1.1 de propostas.md com o primeiro
  consumidor definido.
- **N4.3 — Marine de vigia.** Um Marine parado nos caminhos de ataque, como
  proposta `HOLD` de `count=1`, dá o aviso do ataque antes de ele chegar à base.
  É barato e usa só o Engine que já existe.

### N5 — Modelo de poder calibrado contra a verdade

O bench já grava replays, e o replay tem o exército inimigo **real** a cada
instante. É a oportunidade mais barata de calibrar a Awareness (A12, A13).

- **N5.1 — Calibrar a estimativa do exército.** Um script lê os replays de
  `bench/*` e compara, a cada 10 s, o `estimated_enemy_power` do JSONL com o
  poder real do inimigo no replay. Daí saem `army_growth`, `army_onset` e
  `army_cap` por raça e build da IA, e o erro fica medido. Hoje são chutes.
- **N5.2 — Poder por par de tipos.** Troca o `dps` genérico por
  `calculate_dps_vs_target` contra a composição do outro lado. O poder de um
  lado passa a depender de contra quem ele luta. A tabela é pequena
  (tipo × tipo) e calculada uma vez. Serve à luta local, à Defense e ao
  `composition` (N2.2). O alcance continua fora, como já anotado.
- **N5.3 — Validar o `LocalFight`.** Com os mesmos replays, cada decisão de
  ENGAGE/RETREAT do JSONL vira um rótulo: a troca de recursos nos 20 s
  seguintes. Isso mede se `engage_share = 0,5` e `retreat_share = 0,35` estão
  bem colocados, sem jogar mais partidas.

### N6 — Micro com os behaviors do Ares

Segue o princípio de usar o Ares para o mecânico e manter a política aqui (A10).
Cada item é uma fatia, com uma célula do bench que a mede.

1. **Bio:** `ShootTargetInRange` com prioridade de alvo (Baneling, Widow Mine,
   Siege Tank, depois o de menor vida) antes do `AMove`, e `StutterUnitBack`
   contra melee (lings e zealots). Mede-se na célula Zerg e na `Rush`.
2. **Recuo:** `KeepUnitSafe` / `PathUnitToTarget(sense_danger=True)` no grid de
   perigo, e Marines atirando enquanto recuam (A9).
3. **Medivac:** `MedivacHeal` explícito, e pegar e soltar a bio com vida baixa
   (`PickUpCargo`/`DropCargo`).
4. **Tank:** posição atrás da bio (o centro do grupo recuado na direção do
   rally) e siege antes do contato, não durante.
5. **Evasão de efeitos:** Storm, Bile, Disruptor e Widow Mine pelo grid de
   avoidance do Ares, que já existe.

### N7 — Ofensiva em mais de um corpo

- **N7.1 — Reforços agrupados (A8).** A proposta ofensiva deixa de pedir "todas
  as livres" e pede as livres **a até X do squad**. As demais ficam com o
  CoreArmy num ponto de encontro avançado e se juntam em lote quando o caminho é
  seguro pelo campo. É o primeiro consumidor real do `InfluenceField` (A5).
- **N7.2 — Ataque por timing (A7).** Um terceiro gatilho de commit: upgrade de
  poder concluído (Stim + Combat Shield + +1; mais tarde +2), com
  `army_share ≥ 0,4` em vez de 0,5. A janela fecha sozinha depois de alguns
  minutos. É o que torna o bot perigoso contra quem joga greedy.
- **N7.3 — Segundo squad de harass.** Drop de 8 Marines + Medivac, ou Hellions,
  na mineração mais distante do exército inimigo acreditado, com prioridade
  abaixo da ofensiva principal e `count` fixo. O Engine já sabe dividir
  unidades entre propostas, e esta seria a primeira missão concorrente real
  (motiva o P1.4).
- **N7.4 — Alvo pelo campo.** Entre as estruturas lembradas, o alvo passa a ser
  a de maior valor por risco da rota (base sem cobertura e longe do exército
  inimigo), e não a mais próxima do rally.

### N8 — Prontidão para o ladder

Nada disso aparece contra a IA, e todo o resto quebra no ladder se faltar:

- **Tempo de frame:** ler `logs.frame_perf.max_ms` dos jogos longos da matriz e
  compará-lo com o limite de tempo por passo do AI Arena, que precisa ser
  conferido na wiki. Os candidatos a custo são o campo por frame (A5, sem
  consumidor) e o `_incidents` O(n²). Se passar do limite, calcular o campo em
  cadência ou sob demanda.
- **Crash como derrota:** qualquer exceção num planner derruba o frame inteiro.
  Envolver cada planner num `try` que registra o erro e devolve um plano neutro
  segue o que já foi pedido para os observers (P0.5).
- **`UseData`:** quando N2.3 existir, ligar o histórico por `OpponentId` para
  escolher entre as duas aberturas da raça (P2). É barato depois que o
  portfolio existe.

## Ordem sugerida

| Ordem | Item | Por quê agora | Custo |
| --- | --- | --- | --- |
| 1 | N1 (matriz CheatInsane + builds da IA + métricas) | Sem isso nada abaixo é mensurável | Baixo: parâmetros e um extrator do JSONL |
| 2 | N2.1 (extrair `composition`) | Refactor puro, abre N2.2 | Baixo |
| 3 | N5.1 e N5.3 (calibração por replay) | Usa dados que já existem; conserta a base de N2.2 e N7 | Médio: leitor de replay |
| 4 | N6.1 e N6.2 (bio e recuo) | Maior ganho de troca por linha de código, tudo do Ares | Médio |
| 5 | N2.2 + N2.5 (mix reativo e upgrades) | O "variações" de verdade | Médio |
| 6 | N4.1 e N4.2 (Reaper e scan com perguntas) | Gatilho para N2.4 | Médio |
| 7 | N2.3 + N2.4 (aberturas por raça e ramo seguro) | Só vale com N4 e N1 medindo | Baixo no YAML, médio no gatilho |
| 8 | N7.1 e N7.2 (reforços e timing) | Primeiro uso do campo; ataque contra greedy | Médio |
| 9 | N3, N7.3, N7.4, N8 | Conforme N1 mostrar onde o bot perde | Variado |

## O que não fazer

- **Não variar a abertura por sorteio** (`Cycle` com várias builds). Sem
  histórico, é ruído; com 9 jogos, cada variante fica com 3 e nada é medido.
- **Não criar um planner por matchup.** A raça é uma entrada do `composition`
  e da Intel, não um dono. Três cópias de economia, defesa e ataque divergem.
- **Não calibrar mais thresholds jogando partidas** quando o replay já tem a
  resposta (N5). Uma partida custa minutos de relógio; ler um replay que já existe, segundos.
- **Não manter sinal sem consumidor.** Se `risk`, o campo ou a topologia não
  ganharem um consumidor nas fatias acima, é melhor apagá-los do que carregá-los.
- **Não reimplementar micro que o Ares já tem.** Os behaviors de A10 cobrem quase
  todo o N6; o trabalho daqui é a política (quem, quando, contra o quê).
