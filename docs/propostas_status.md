# Andamento das propostas

Registro do que já foi implementado a partir de `propostas.md` e
`propostas_corrigidas.txt`, e do que continua pendente. Cada fatia concluída
atualiza este arquivo no mesmo commit.

"Feito" significa: teste que reproduz o problema, suíte e lint verdes localmente,
diff restrito à fatia. **Nenhuma linha aqui é evidência de ganho de gameplay**:
a matriz da fatia 2 tem uma partida por raça, o que não sustenta taxa de
vitória.

## Fatias

A numeração segue a §4 da corrigenda; ela agrupa marcos, não define a ordem de
seleção (ver regra no prompt corrigido).

| # | Fatia | Status | Commit |
| --- | --- | --- | --- |
| 1 | Gate de entrega (pytest/ruff antes do artefato) | Feito | `5ab151a` |
| 2 | Harness/baseline de partidas | Feito (matriz mínima) | `harness: play a fixed matrix of games and record each outcome` |
| 3 | Contrato defensivo mínimo + `ThreatIncident` | Feito | `defense: one incident, one demand, one budget` |
| 3a | Ameaça lembrada por base (objetivo não abandona ataque em pausa) | Feito | `awareness: remember each base's threat` |
| 4 | Wall bidirecional | Feito | `wall: raise depots when ground enemies come near` |
| 5 | Desconhecido conservador mínimo | Feito | `awareness: believe the unseen enemy army` |
| 6a | Ofensiva: assemble/advance | Feito | `d609fc7` + `offense: fight, retreat and search; macro upgrades; bio micro` |
| 6b | Ofensiva: engage/retreat/regroup | Feito | `offense: fight, retreat and search; macro upgrades; bio micro` |
| 6c | Ofensiva: search/finish | Feito | `offense: fight, retreat and search; macro upgrades; bio micro` |
| 7a | Macro: plano econômico estável (contagem de workers) | Feito | `economy: count workers inside gas buildings` |
| 7b | Macro: produção não congela na composição exata | Feito | `61e3988` |
| 7c | Macro: upgrades, Orbital e MULE depois do opening | Feito | `offense: fight, retreat and search; macro upgrades; bio micro` |
| 7 | Macro resiliente (opening, supply/pending, reposição, detecção, spending) | Pendente | — |
| 8a | Micro: Stim e Medivac acompanhando o grupo | Feito | `offense: fight, retreat and search; macro upgrades; bio micro` |
| 8 | `RegionState` e o resto do micro | Pendente | — |

As fatias 2, 6a–6c, 7c e 8a foram feitas numa mesma sessão, a pedido. O
harness tem commit próprio; as outras dividem arquivos e estão num só commit,
cada uma com sua seção e seus testes.

## 1. Gate de entrega — feito (`5ab151a`)

**Feito**

- `ladder_zip.yml` e `build_windows_exe.yaml` rodam `pytest` e
  `ruff check bot tests run.py` no mesmo job, antes de zip, exe, artifact e
  upload para AI Arena.
- `poetry.lock` regenerado: o grupo dev (`pytest`, `ruff`) estava no
  `pyproject.toml` desde `8273544` sem lock, e `poetry check --lock` falhava —
  `poetry install` quebraria os dois workflows. Nenhuma versão travada mudou.
- `tests/test_workflows.py`: todo job que entrega roda pytest e ruff antes, sem
  `continue-on-error`, e nenhuma entrega roda após falha.

**Não feito**

- Os workflows não foram executados no GitHub; a suíte nunca rodou em Linux.
- Sem gatilho de PR; smoke de import e do zip; isolamento de observers
  (`NullLogger`); fingerprint de toda configuração decisória; README.

## Partidas desta sessão

Persephone AIE, IA VeryHard Macro, uma partida por raça, seed 1, limite de
1.200 s de jogo (`bench.py run --maps PersephoneAIE_v4 --races Zerg Terran
Protoss --time-limit 1200`). Cada execução rodou de um `git worktree` do
`d609fc7` com os arquivos alterados copiados (`dirty: true`). Uma partida
por combinação: nenhuma diferença abaixo é estatisticamente significativa
(Wilson 95 % de 1/3 é 0,06–0,79; de 2/3, 0,21–0,94).

| Execução | Código | Fingerprint | Zerg | Terran | Protoss |
| --- | --- | --- | --- | --- | --- |
| `bench/6a` | 6a + correção do Engine | `a8ffba2698d1a952` | vitória, 840 s | timeout | timeout |
| `bench/all` | + 6b (1ª versão), 6c, 7c, 8a | — | timeout (perseguição, corrigida) | interrompida | — |
| `bench/all2` | + `won_share` | — | timeout (centro vazio, corrigido) | interrompida | — |
| `bench/all3` | + núcleo do grupo (**código final**) | `aaba38f6fedc1e7f` | vitória, 848 s | timeout | vitória, 1.121 s |
| `bench/all4` | + recuo por perda | — | timeout | interrompida | — |
| `bench/all5` | + recuo por troca (revertido) | `85cf7625ef89c843` | timeout | timeout | vitória, 1.121 s |

Observado no JSONL (script fora do repositório):

- `6a`: nenhuma pesquisa depois do opening; gás depois de 600 s até 4,6–4,9
  mil; nenhum Stim usado.
- `all3`: 10–11 dos 12 upgrades concluídos; 284–338 frames com Stim;
  8–12 Medivacs escoltando; contra Protoss, quatro SEARCH → ADVANCE
  (`structure_found`) antes da vitória. Minerais depois de 600 s continuam
  subindo (12–29 mil): a capacidade de produção não acompanha.
- Mesmo seed, mesmas decisões → mesma partida (`all4/000` e `all5/000`
  idênticas até o fim); o seed torna a comparação reproduzível nesta máquina.

## 2. Harness/baseline de partidas — feito (matriz mínima)

Seleção: pedido explícito do usuário (implementar as fatias pendentes). A
ofensiva (6a–6c) só pode ter aceite "depois de cenário/partida registrado",
então o harness vem antes dela.

**Feito**

- `harness/` (puro, testável sem SC2): `matrix` (todas as combinações de
  mapas × raças × dificuldades × builds, `games` vezes, em ordem fixa; a
  repetição k usa `seed + k`), `outcome`, `build_record`, `identity`,
  `load_records`, `summarize` e `wilson`.
- Resultado explícito: `victory`, `defeat`, `tie`, `timeout`, `crash`,
  `no_result`. O python-sc2 encerra no limite de tempo como `Tie`, e o último
  passo do bot fica alguns game loops antes do limite (119,91 s num limite de
  120 s, na partida de fumaça); um `Tie` a até `LIMIT_TOLERANCE` (1 s) do limite
  é `timeout`. Processo com código ≠ 0 ou estouro do timeout de relógio é
  `crash`.
- `result.json` por partida: spec, resultado, tempo de jogo e de relógio,
  commit e branch do bot, SHA do Ares, `dirty` (a árvore difere do commit),
  `config_fingerprint` e `configs` lidos do `game.started` da própria
  partida, caminhos do replay e do JSONL, erro.
- `bench.py run|summarize|compare`: cada partida num subprocesso
  (`bench.py play`) com timeout de relógio; `summary.json` reescrito a cada
  partida; `compare` recusa execuções que não jogaram a mesma matriz. Os
  resultados ficam em `bench/` (ignorado pelo git).
- CI: `ruff check` passa a cobrir `harness` e `bench.py`.
- Testes: matriz fixa e determinística, ids únicos e ida e volta em JSON;
  matriz vazia ou inválida rejeitada; cada combinação de resultado, código e
  timeout vira o desfecho certo, inclusive o `Tie` 0,09 s antes do limite;
  registro com identidade, fingerprint, replay e log, e sem eles quando não
  existem; resumo com contagens, taxa de vitória, intervalo de Wilson e
  duração média; valores do intervalo de Wilson.
- Verificação: partida de fumaça real (Persephone, Zerg Easy, 120 s) gerou
  `result.json`, replay e JSONL; foi ela que mostrou o `Tie` antes do limite.

**Não feito**

- Nenhuma matriz com repetições: as execuções abaixo têm uma partida por
  combinação e não sustentam taxa de vitória (o intervalo de Wilson de 1 em 1
  é 0,21–1,00).
- Oponentes bots/`local-play-bootstrap`, mapas além dos três AIE instalados,
  métricas agregadas no resumo (supply block, banco, primeiro ataque,
  tempo de frame); hoje saem de script fora do repositório sobre o JSONL.
- Reprodutibilidade verificada só num par (`all4/000` = `all5/000`, mesmo
  seed e mesmas decisões) e só nesta máquina.
- `dirty` diz que a árvore mudou, não o quê; partidas de código não commitado
  foram rodadas de um `git worktree` com a cópia dos arquivos alterados.

## 3. Contrato defensivo mínimo + `ThreatIncident` — feito

Evidência do problema: trace `788af1d`, t=500 s — um SCV (poder 0,58) gerou três
propostas `defense:base:*` com o mesmo alvo, e o Engine concedeu Marine,
Marauder e Siege Tank. No trace de `483722e`, 1.671 de 2.117 conjuntos de
propostas tinham duas ou mais defesas simultâneas. O planner anterior, rodado
sobre o cenário do teste novo, reproduz o mesmo trio.

**Feito**

- Awareness: `ThreatIncident` — atacantes ao alcance de alguma base, ligados em
  cadeia a ≤ `incident_link` (12). Id `incident:<menor tag>`; numa divisão, a
  parte sem essa tag leva a própria menor, numa fusão vence a menor. Poder
  terrestre/aéreo (`Σ poder·confiança`), confiança, centro, pressão por base
  afetada e `threat`. Os incidentes somam a pressão de cada base.
- Ego/defense: uma demanda por incidente; orçamento `1,5 × poder` repartido em
  partes `air`/`ground` (`minimum_power`, `must_attack`, `demand_id`) cuja soma é
  o orçamento.
- Engine: restrições duras (`must_attack`, poder > 0 em pedido de poder), grant
  por poder com as compatíveis mais próximas primeiro, `power`, `status`
  `FULL`/`PARTIAL`/`REJECTED` e `reason` (`minimum_power_met`,
  `insufficient_power`, `no_eligible_units`, `eligible_units_taken`,
  `count_met`, `insufficient_units`, `every_free_unit`).
- Logs: `awareness.updated.incidents[]` (escrito também quando membros mudam),
  `behavior.proposed` com `minimum_power`/`must_attack`/`demand_id`,
  `engine.granted` com `granted_power`/`status`/`reason`,
  `engine.commanded.demand_id`; o viewer mostra poder e status.
- Testes: SCV em três bases → 1 incidente, 1 demanda, só o Marine próximo;
  ataque aéreo ignora cobertura incompatível; ataque misto reparte um orçamento;
  `partial`/`rejected` com razão; id em divisão, fusão e memória; Engine por
  poder e razões; trilha incidente → demanda → grant no fluxo de frame.
- Verificação local: 93 testes, ruff limpo. Microbenchmark isolado do
  agrupamento: 200 contatos ≈ 3 ms p50 (não é medida de partida).

**Não feito**

- Nenhuma partida: sem evidência de gameplay nem de desempenho em jogo.
- Histerese de admissão/liberação: o grant pode oscilar quando o poder do
  incidente cruza o poder de uma unidade.
- Distinguir scout, worker rush e ataque; alcance por pathing; eventos
  explícitos de linhagem; `desired_power`, suitability, custos de assignment e
  preemption; overlay/SVG ainda não desenham incidentes; `COVER_MARGIN` fora do
  fingerprint de configuração (`incident_link` entra, via Awareness).
- O poder do incidente não é atenuado pela distância à base (era, na fórmula
  anterior): um atacante no limite do alcance pede o poder inteiro. Contatos
  lembrados pedem `poder·confiança`, que decai; a fatia 5 não mudou a defesa.

## 3a. Ameaça lembrada por base — feito

Seleção: bug decisório reproduzível por trace (classe 1). A regra de objetivo
(`strategy.py`) e a ameaça por base não mudaram desde `483722e`.

Evidência do problema: no trace `483722e`, 21 trocas de objetivo em 772 s, 6
janelas com menos de 10 s. Duas saídas de STABILIZE voltaram por
`emergency_threat` depois de 4,3 s (1.017,1 s) e 2,1 s (1.318,7 s). Em 1.318,7 s,
depois de 44 s em STABILIZE, `danger` caiu de 0,63 para 0,33 num passo quando
atacantes morreram. O rally foi da base (37,5; 34,5) para a frente
(126,75; 34,18), ~90 células, e voltou 2,1 s depois, com 26 contatos novos
chegando. Em 1.017,1 s, `danger` ficou ≤ 0,45 por 3,5 s e subiu de novo. A
decisão lia só a ameaça do frame.

Direção: corrigir a estimativa, não pôr espera na decisão. Um "calmo por N s"
foi descartado pela preferência do projeto por crença persistente com
histerese só como última camada.

Replay (script fora do repositório): a regra de objetivo reaplicada à série de
ameaças por base do log, em passos de 0,089 s, reproduz as 21 trocas nos mesmos
instantes. Com memória τ: 5 s e 10 s mantêm as duas voltas por emergência; 20 s
dá 13 trocas, 2 janelas < 10 s, nenhuma volta por emergência e 6 s em
STABILIZE sem ameaça alguma; 30 s traz uma volta por emergência de novo.
Escolhido τ = 20 s, o mesmo tempo da memória de unidades.

Partida nova com o código de `3769f04` (Persephone AIE, contra Zerg VeryHard
Macro, 900 s; o bot saiu aos 900 s, sem resultado): 8 trocas e nenhuma volta
por emergência, ou seja, o caso não aconteceu nessa partida. O replay com
τ = 20 s mostra o custo: janelas < 10 s de 2 para 1, e STABILIZE sem ameaça
alguma de 4 s para 18 s. Depois que um ataque termina, o exército volta à frente
mais tarde: de 0,6 até 0,45 leva 5,8 s; de 0,9, 13,9 s.

**Feito**

- Awareness: `AwarenessConfig.threat_memory` (20 s, validado; muda o hash de
  `configs.awareness`). `BaseThreat.recent_threat =
  max(threat, anterior · exp(-Δt / threat_memory))`; a parte decaída é esquecida
  abaixo de `forget_below`, e uma base que some leva a memória. `danger` passa a
  ser o maior `recent_threat`, `danger_now` o maior `threat`, e `most_threatened`
  escolhe pela `recent_threat`, então o rally de STABILIZE fica na base lembrada.
- Strategy: nenhuma regra mudou; lê o `danger` lembrado e registra `danger_now`.
- Outros leitores de `danger` passam a ver a memória: prioridade da defesa
  (`0,5 + 0,5·defense`, só enquanto há incidente), `army`, overlay, SVG e viewer.
- Logs: `awareness.updated.danger_now`, `bases[].recent_threat`;
  `strategy.decided.inputs.danger_now`.
- Testes: base sem atacantes lembra `pico · exp(-Δt/τ)` aos 5 s e aos 10 s, com
  `danger_now = 0` e a mesma base em `most_threatened`; um ataque mais forte conta
  no mesmo frame; a memória é esquecida abaixo de `forget_below`. Strategy com
  Awareness real: 44 s de ataque, 3 de 4 atacantes morrem, 2 s depois chegam 5,
  aos 60 s todos morrem → STABILIZE e rally na base até o primeiro frame (0,5 s)
  depois de `60 + τ·ln(pico / 0,45)`. Com o `bot/` anterior esse teste falha:
  o objetivo sai aos 44,5 s. Fluxo de frame: `danger`, `danger_now`,
  `recent_threat` e `inputs.danger_now` no log.
- Verificação local: 103 testes, ruff limpo.

**Não feito**

- Nenhuma medida de gameplay; τ escolhido só por replay de dois logs.
- STABILIZE de exatamente 8 s quando a ameaça de entrada é baixa: entrando a 0,57,
  a memória cai a 0,45 em 4,7 s, antes do dwell (replay mantém 1.213,4 s).
- Rally alternando entre bases de ameaça quase igual (1.089–1.093 s, 0,80 contra
  0,79): argmax com desempate por id, uma rajada no trace.
- Reforços ainda não vistos (a segunda onda): a fatia 5 estima o exército não
  visto, mas o objetivo lê só `danger`.
- Uma base destruída perde a memória; a prioridade da defesa elevada pela
  memória não foi medida.

## 4. Wall bidirecional — feito

Evidência do problema: o planner só considerava `SUPPLYDEPOT` levantado e o
behavior só conhecia `MORPH_SUPPLYDEPOT_LOWER`. Sobre um depot abaixado com um
Zergling a 2 células, o planner de `eb43a59` devolve `lower=()` e
`no_raised_depots`, sem ordem nenhuma. Nos dois traces locais todo depot é
abaixado e sai do plano no frame seguinte, inclusive aos 138 s com 20 inimigos
terrestres visíveis; o log não trazia posição de depot, então o trace não mostra
a distância.

**Feito**

- Ego: `StructureControl` passa a ter estado. Depot pronto, levantado ou
  abaixado, sobe no frame em que um inimigo terrestre visível está a
  ≤ `raise_reach` (8 células) e só desce quando nenhum esteve a essa distância
  por `lower_after` (3 s). A última ameaça fica por tag e é podada quando o depot
  some. Voadores não contam. `StructureConfig` é validada e entra no fingerprint
  (`configs.structure_control`).
- Body: `MORPH_SUPPLYDEPOT_RAISE` para `StructurePlan.raise_`.
- Logs: `behavior.structures_planned` com `raise`; razões `no_depots`,
  `enemy_near`, `enemy_recently_near`, `no_enemy_near`; inputs `depots`,
  `lowered`, `enemy_near`, `recently_near`, `ground_enemies`,
  `friendly_on_raising`, `nearest_ground_enemy`.
- Testes: depot abaixado sobe com inimigo exatamente a `raise_reach`, só o
  ameaçado; voador em cima e terrestre a `raise_reach + 0,5` não o levantam;
  ainda de pé a `lower_after − 0,1` s, desce em exatamente `lower_after`; um
  Zergling cruzando a borda do alcance a cada 0,5 s por 10 s gera exatamente uma
  subida (0 s) e uma descida (12,25 s = último frame dentro + 3 s); unidades
  terrestres nossas sobre um depot que sobe são contadas; depot inacabado é
  ignorado; configuração inválida é rejeitada; o behavior só ordena os depots do
  plano; fluxo de frame attention → plano → `RAISE` → log.
- Verificação local: 100 testes, ruff limpo.

**Não feito**

- Nenhuma partida: sem evidência de gameplay. `raise_reach` e `lower_after` não
  foram calibrados; o tempo de morph do depot não foi verificado.
- Antecipar o fechamento por contato lembrado ou pela rota/choke; alcance
  proporcional à velocidade do inimigo.
- Distinguir os depots do wall: qualquer depot sobe com inimigo terrestre perto.
- Tráfego amigo: no SC2, subir empurra nossas unidades de cima para a borda mais
  próxima (talvez para fora do wall), e um inimigo em cima impede a subida. A
  fatia só registra `friendly_on_raising`; não há política para unidades nossas
  presas do lado de fora nem para o comando repetido enquanto um inimigo está em
  cima.
- Viewer, overlay e SVG não mostram depots.

## 5. Desconhecido conservador mínimo — feito

Seleção: nenhum bug decisório novo reproduzível. O trace de `6455342`
(Incorporeal AIE, contra Zerg) termina aos 404 s em `Result.Defeat` sem inimigo
visível, com 4 bases e `danger` 0 no último evento; não conta como resultado.
Entre as fatias de gameplay pendentes, esta é a menor com pré-requisitos prontos,
e a corrigenda a põe antes de qualquer gatilho ofensivo.

Evidência do problema:

- Trace `3769f04` (Persephone AIE, contra Zerg VeryHard Macro): de 240 s a 560 s,
  `strategy.decided` registra `enemy_power = 0`, `army_share = 1,00` e
  `risk = 1,00` sem nenhum exército inimigo avistado. Aos 565,6 s entra em
  STABILIZE e aos 575,6 s tem `enemy_power` 45,3 contra `own_power` 45,5.
- Trace `6455342`: de 95 s a 180 s, `enemy_power` 9,3–10,4 vinha de ~20 Drones
  minerando na main inimiga, vistos pelo SCV scout (`strongest_contacts` só
  com DRONE). Com `own_power` entre 0 e 1, dava `army_share` 0–0,09 e
  `economy` 0,44–0,48, abaixo do gate de expansão. Awareness somava workers ao
  poder inimigo, e `own_power` não os soma.
- Nenhum trace mostra decisão mudada por isso: o opening ainda rodava, e com
  `danger = 0` o gate `economy ≥ 0,5` passa com qualquer `army_share`.

**Feito**

- Awareness, só descrição, em Marines:
  - `enemy_power` (conhecido) passa a somar só contatos de exército; workers e
    estruturas saem.
  - `seen_enemy_power` (visto vivo): unidades de exército vistas vivas e não
    vistas morrer, por tag, com `exp(-idade / army_memory)` (180 s). Saem com a
    morte confirmada ou abaixo de `forget_below`, não quando a última posição
    volta à visão vazia.
  - `expected_enemy_power` (esperado sem avistamento):
    `min(army_cap, army_growth · max(0, t − army_onset))`, com 0,1 Marine/s a
    partir de 120 s e teto 100.
  - `estimated_enemy_power = max(conhecido, visto vivo, esperado)`,
    `enemy_uncertainty = estimado − conhecido` e
    `enemy_coverage = conhecido / estimado` (1 enquanto o estimado é 0).
  - `AwarenessConfig` valida `army_memory ≥ unit_memory` (garante conhecido ≤
    visto vivo) e `army_growth`, `army_onset`, `army_cap` ≥ 0; o hash de
    `configs.awareness` muda.
- Strategy (política): `commit_margin` 0,5, validado; o hash de
  `configs.strategy` muda. O inimigo planejado é
  `estimado + commit_margin · incerteza`, e `army_share = own / (own + planejado)`
  alimenta `army`, `economy` e `risk` com as mesmas fórmulas. Objetivo, `danger`
  e rally não mudaram.
- Logs: `awareness.updated` com `seen_enemy_power`, `expected_enemy_power`,
  `estimated_enemy_power`, `enemy_uncertainty` e `enemy_coverage`;
  `strategy.decided.inputs` com `estimated_enemy_power`, `enemy_uncertainty` e
  `planned_enemy_power`. Overlay e SVG mostram o estimado ao lado do conhecido.
- Testes:
  - 16 Drones, uma Hatchery e uma Spine não são exército: só o Zergling conta.
  - Um exército fora de vista: o contato decai com τ = 20 s, e o visto vivo
    com 180 s continua depois que a posição volta à visão vazia. As mortes
    confirmadas descontam no frame; o visto vivo é esquecido abaixo de
    `forget_below`; conhecido ≤ visto vivo em todo passo.
  - Sem avistamento, o esperado vale 0, 20, 48 e 100 aos 60, 320, 600 e 2.000 s,
    e é todo incerteza.
  - Um avistamento acima do esperado deixa incerteza 0 e cobertura 1.
  - Configuração inválida é rejeitada.
  - Strategy aos 500 s com 47 de exército: na névoa, `army_share` fica em
    47 / (47 + 1,5 · 38) = 0,45, acima de 0 e abaixo de 0,5; com 39 de exército
    inimigo à vista, fica em 47/86 > 0,5.
  - Fluxo de frame aos 600 s: saturado em 3 bases, 8,9 de exército, um Zergling
    na main e nenhum exército à vista → `economy < 0,5`, sem expansão, e a
    trilha estimado → planejado → `strategy_economy` no log.
  - O teste do gás lê a `economy` do próprio frame.
- Com o `bot/` de `6455342` (extraído com `git archive`, testes novos por cima),
  o fluxo de frame falha na decisão: `economy` 0,767 e expansão. Os testes de
  Awareness falham por falta dos campos. Mesmos cenários, antes → depois:
  Drones + Zergling, `enemy_power` 9,7 → 0,9; névoa aos 500 s, `army_share` e
  `risk` 1,0 → 0,452; 600 s sob ameaça, `economy` 0,767 com expansão → 0,448 com
  `build_economy`.
- Verificação local: 116 testes, ruff limpo.
- Replay aproximado (script fora do repositório): a regra de preferências foi
  reaplicada às amostras de `strategy.decided` depois do opening. O visto vivo
  não se reconstrói pelo log, então estimado = max(`enemy_power` do log,
  esperado). O gate de expansão muda em 5 de 64 amostras em `3769f04` (565,6;
  599,8; 645,7; 836,2; 873,2 s, `danger` 0,44–0,66), em 0 de 12 em `6455342` e
  em 25 de 116 em `483722e` (`danger` 0,23–0,72). Nenhuma mudança com `danger = 0`.

**Não feito**

- Nenhuma partida. `army_growth`, `army_onset`, `army_cap`, `army_memory` e
  `commit_margin` não foram calibrados; 0,1 Marine/s só tem a ordem de grandeza
  dos 45 Marines vistos aos 575 s em `3769f04`. Não se sabe se deixar de expandir
  sob ameaça ajuda ou atrapalha.
- O esperado é piso: informação ampla que mostre um exército menor que o esperado
  não baixa a estimativa. Faltam estimativa por produção ou economia vista e
  scouting recorrente. Hoje só um avistamento maior que o esperado zera a
  incerteza.
- `enemy_coverage` mede a parte do estimado que um contato localiza, não área
  vista nem idade da informação.
- O visto vivo pode contar a mais unidades de vida limitada (Interceptor, Locust),
  alucinações e mortes fora da visão; a memória de 180 s limita o erro.
- Nenhum gatilho ofensivo usa a estimativa (fatia 6a). `risk` mantém o nome.
- Incidentes e defesa ainda contam workers com poder > 0: o Drone scout de
  `6455342` gerou incidente aos 95,8 s e puxou o Reaper aos 134,5 s (distinguir
  scout é P0.2).
- O viewer não mostra os campos novos; lê `enemy_power`, agora só exército.

## 6a. Ofensiva: assemble/advance — feito

Evidência do problema: trace `3769f04`, 675–896 s: supply 190–200, sem ameaça,
75–82 Marines de exército em `HOLD` enquanto 4.210 minerais viravam 11.970.
O código estava em `d609fc7` ("fatia 6a em andamento") com dois testes
falhando.

**Feito**

- Ego: `Offense` (IDLE → ASSEMBLE → ADVANCE) com `OffenseConfig` validada e no
  fingerprint; prioridade 0, entre Defense (> 0) e CoreArmy (agora −1).
- Engine (correção desta sessão): um pedido de todas as livres que não
  recebe nenhuma unidade passa a ser `REJECTED` (`eligible_units_taken` ou
  `no_eligible_units`) em vez de `FULL`/`every_free_unit`. Era o que os dois
  testes falhando pediam: o CoreArmy sem unidades aparecia como atendido.
- Body: `behaviors/attack.py` executa o `ATTACK` de Defense e da ofensiva.
- Logs: `behavior.offense_planned`.
- Testes: `tests/test_offense.py` e o fluxo de frame do exército maxado.

**Não feito**: path de grupo consciente de risco; coesão (toda unidade livre,
inclusive a recém-treinada em casa, recebe o `ATTACK` e vai sozinha).

## 6b. Ofensiva: engage/retreat/regroup — feito

Evidência do problema: linha de base `bench/6a/001` (Terran VeryHard):
ADVANCE aos 839 s e `army_depleted` aos 866 s — o exército perdeu metade do
poder em 27 s sem nenhuma decisão de recuar; nada no planner comparava forças.

**Feito**

- Engine: `held_by(proposal_id)`, as unidades que a última alocação deu a uma
  proposta. O planner lê a própria concessão sem nomear unidades.
- Ego/offense: grupo = concessão anterior; `LocalFight` em volta do núcleo
  do grupo (a unidade com mais poder do grupo a ≤ `engage_radius` 16; menor
  tag no empate): esse poder contra `poder·confiança` dos inimigos sem workers
  a ≤ 16 + incerteza, e `share`. Estágios ENGAGE, RETREAT e REGROUP com
  histerese: entra em luta com `share ≥ 0,5` (abaixo, recua); engajado, só
  recua com `share < 0,35` depois de `engage_dwell` (4 s); luta ganha depois de
  `clear_after` (3 s) sem inimigo; recuo termina com o exército reunido ou em
  30 s; REGROUP espera `regroup_dwell` (10 s) e avança de novo (recomprometendo
  com o poder atual) ou volta a IDLE (`advantage_lost`, com cooldown).
- Correção vinda da primeira partida do desafiante (`bench/all/000`,
  871–966 s): engajado com parcela local 0,95, o exército perseguiu 1,9–2,8
  Marines de inimigo pelo mapa em vez de atacar a base, até o `timeout`. Uma
  luta com `share ≥ won_share` (0,9) não é disputa: conta como sem inimigo,
  e o alvo continua a estrutura.
- Segunda correção (`bench/all2/000`, 777 s e 1.131 s): com reforços em fila
  entre a base e a frente, o centro ponderado do grupo caía onde não havia
  unidade; um inimigo ali dava `share = 0` e um recuo. A primeira versão
  usava esse centro; a luta passou a ser medida no núcleo.
- Body: `Command.RETREAT` e `behaviors/retreat.py` (path ao rally sem lutar,
  `force_unsiege` no Siege Tank).
- Logs: `behavior.offense_planned` com `fight` e inputs `squad_units`,
  `squad_power` (o grupo inteiro), `core_power`, `local_enemy_power`,
  `local_share`, `contested`, `clear_for`.
- Testes: luta favorável → ENGAGE no centro inimigo → `clearing` por 3 s →
  ADVANCE; contato desfavorável → RETREAT (mesmo `proposal_id`) → REGROUP →
  10 s → ADVANCE; parcela 0,40 e 0,37 mantém a luta, 0,33 espera o dwell e recua
  em exatamente 4 s; REGROUP sem vantagem → IDLE e cooldown; luta local conta só
  quem está no raio do núcleo (borda inclusa, worker fora, reforços em fila
  e o inimigo entre eles fora); núcleo empatado vai à menor tag; luta ganha
  (0,909) não tira o alvo; o behavior de recuo não
  luta, tira o siege e usa o grid aéreo para voadores; configuração inválida.

Experimento medido e revertido: em `bench/all3/001` (Terran, 624–641 s),
engajado contra Siege Tanks em siege com parcela estimada entre 0,53 e 0,90, o
grupo caiu de 81 para 33 de poder sem recuar (o poder `sqrt(dps·vida)` não vê
alcance nem splash). Foram testadas duas regras de recuo pela perda
observada: perder 35 % do poder com que engajou (`bench/all4`) e perder 35 %
matando menos do que perdeu, com um `killed_enemy_power` novo na Awareness
(`bench/all5`). Com o mesmo seed, `all4` e `all5` jogaram contra Zerg a mesma
partida, que diverge da do `all3` no primeiro recuo (594 s) e terminou em
`timeout` em vez de vitória; contra Terran continuou `timeout`; contra
Protoss nenhuma luta acionou a regra (vitória idêntica). Sem ganho medido, a
regra e o `killed_enemy_power` saíram; o código final tem o fingerprint de
configuração do `all3` (`aaba38f6fedc1e7f`).

**Não feito**: combat simulation do Ares e poder com alcance/splash (o caso
Terran acima continua); reforços e coesão; recuo por caminho seguro; um recuo
pode ser seguido de novo avanço contra a mesma linha; `won_share`, raios e
tempos não calibrados; ENGAGE ↔ ADVANCE volta em menos de 10 s várias vezes
numa partida (7 em `bench/all3/000`), respeitando `clear_after`.

## 6c. Ofensiva: search/finish — feito

Evidência do problema: `bench/6a/000`, 814–836 s: sem estrutura lembrada, o
alvo alternava entre `enemy_start` e `known_base`; nada procurava bases fora
do start inimigo.

**Feito**

- Ego/offense: SEARCH. ADVANCE → SEARCH (`enemy_start_empty`) sem estrutura
  lembrada e com o start inimigo em visão nos últimos `search_memory` (60 s).
  Percorre expansões e start inimigo (menos as nossas, ≤ 6): primeiro as fora
  de visão há mais de 60 s, a mais próxima do grupo; depois a fora de visão há
  mais tempo; alvo mantido até entrar em visão. SEARCH → ADVANCE
  (`structure_found`). Lutas durante a busca seguem a 6b.
- Finish: estrutura voando é alvo depois das de chão (`flying_structure`) e o
  pedido leva `must_attack = AIR`.
- Testes: start vazio → busca a natural (a main é nossa), mantém até ver,
  depois a mais antiga; estrutura achada → ADVANCE nela; start visto há mais de
  60 s → ADVANCE no start; voadora por último e só unidades antiaéreas
  concedidas (o Siege Tank fica fora).

**Não feito**: voadora sobre terreno impassável; busca com Reaper/scan;
“encerra a partida” ainda sem medida além das partidas abaixo.

## 7a. Plano econômico estável — feito

Seleção: bug decisório reproduzível por trace (classe 1), à frente da fatia 5.
`enemy_power = 0` sem visão leva `army` a 0,1, mas `army` só entra no gatilho
de expansão (`economy ≥ 0,5`), que com `danger = 0` passa com qualquer
`army_share`; nenhum trace mostra decisão mudada por isso.

Evidência do problema: nos dois traces o plano alterna a cada 1–2 passos depois
do opening — trace `788af1d`, 362,9–367,3 s, 15 eventos entre
`bases=4, expand, gas=5` e `bases=3, build_economy, gas=4`. Contando como oscilação um plano que volta ao de
dois eventos antes em ≤ 1 s, com o plano ativo: 13 em `788af1d` (363–423 s) e 92
em `483722e` (358–1.212 s, espalhadas entre os minutos 5 e 20). Pela aritmética do plano, com 3 townhalls nos dois
lados, `expand` e `gas=5` exigem 48 ≤ workers < 60 e o outro lado
36 ≤ workers < 48: a contagem de workers cruza 48 e volta, com os townhalls
fixos. O diagnóstico de `propostas.md` (contagem de townhalls oscilando) não
confere com o trace. No opening, `gas` alterna do mesmo jeito com `bases` fixo.
Causa: Attention contava workers em `bot.units`, e um SCV dentro da refinaria
não aparece ali enquanto está lá. O teste novo, rodado antes da correção,
reproduz o par exato `(3, False, 4)`/`(4, True, 5)`.

**Feito**

- Attention: `workers = bot.supply_workers`, a contagem do jogo, a mesma que
  `BuildWorkers` e o build runner do Ares usam. Inclui workers dentro de
  refinarias; exclui os em produção. Intel (`workers ≥ 16`) lê o mesmo campo.
- Ego/economy: `EconomyPlan.inputs` com `workers`, `bases`, `saturated_at` e
  `strategy_economy`. Nenhuma regra do plano mudou.
- Logs: `behavior.economy_planned.inputs`; a assinatura do gate não inclui os
  inputs, então o evento continua sendo escrito só quando o plano muda.
- Testes: 48 SCVs em 3 bases, um deles dentro da refinaria a cada dois passos
  por 8 passos → `workers = 48` em todos, plano `(4, expand, gas 5)` em todos e
  exatamente um `behavior.economy_planned`, com os inputs.
- Verificação local: 101 testes, ruff limpo.
- Verificação da premissa numa partida local curta (script fora do repositório;
  Persephone AIE, contra IA Terran VeryEasy, 0–480 s, 5.377 passos; o bot saiu
  aos 480 s, então o resultado não conta): a contagem listada mudou 723 vezes
  (337 quedas); `supply_workers` mudou 64 vezes (1 queda). A diferença entre as
  duas ficou entre 0 e os SCVs atribuídos a gás em todos os passos. Recalculando
  `(saturado, gas)` do plano por passo, houve 76 trocas com a contagem listada e
  11 com `supply_workers`. Não é baseline nem medida de gameplay.

**Não feito**

- Nenhuma medida de gameplay: não se sabe quanto a oscilação atrasava expansão
  ou gás, nem se a correção muda o resultado.
- Bases: `townhalls` inclui CC em construção e exclui CC voando (trace
  `483722e`, 93 s: `bases` 2 → 1 no opening); `ready + pending` explícito,
  cooldown do alvo e interrupção do opening continuam na fatia 7.
- Sem histerese nos limiares: uma mudança real da contagem exatamente no limiar
  (morte e reposição de um worker) ainda troca o plano, uma vez por mudança.
- `army`/`risk` sem visão: fatia 5 (o nome `risk` não mudou).

## 7b. Produção não congela na composição exata — feito

Seleção: bug decisório reproduzível por trace (classe 1), à frente da ofensiva
6a. O trace de teste de `8b7f5ba` (Torches AIE, contra Protoss, 290 s, fechado
sem inimigo à vista) não mostrou bug novo; a busca por evidência de macro nos
traces longos achou este.

Evidência do problema: `army_supply` parado, banco crescendo e supply livre. Nas
concessões do Engine, o exército estava exatamente nas proporções da composição
(0,55/0,20/0,15/0,10):

- `483722e`: 417,9–589,0 s (171 s), 11 Marines, 4 Marauders, 3 Siege Tanks e
  2 Medivacs; minerais 460 → 5.520, gás 587 → 3.011, supply 141/179 no fim.
- `3769f04`: 481,5–573,5 s (92 s), 22/8/6/4; minerais 580 → 3.600, gás
  856 → 2.064, supply 166/200 no fim.

Causa: o `SpawnController` do Ares pula todo tipo com
`contagem / total ≥ proporção`, contando alias e unidades em produção. Com todos
os tipos no alvo, não treina nada, e só volta com `freeflow` (STABILIZE aos 575 s
em `483722e` e aos 566 s em `3769f04`) ou quando alguma unidade morre. O próprio
controlador leva as contagens às proporções, e o empate cai em todo múltiplo de
20 unidades dessa composição. O trecho não mudou no `dev` do Ares.

**Feito**

- Body (`behaviors/economy.py`), na fronteira com o Ares: `SpawnMode`
  (`freeflow`, `reason`, `counts`). Com o plano ativo, conta cada tipo da
  composição com `mediator.get_own_unit_count` (a contagem que o
  `SpawnController` usa) e aplica o mesmo teste. Com todos os tipos atingidos,
  `SpawnController(freeflow_mode=True)` naquele frame (`composition_met`); senão
  segue o plano (`plan_freeflow`, `composition_short`), e `plan_inactive` no
  opening. O Ego (plano, composição e `freeflow` do plano) e o Ares não mudaram.
- `behaviors.execute` devolve o `SpawnMode`, que vai em `Frame.spawn`,
  `Logs.record` e `Telemetry.record`.
- Logs: `behavior.spawn_executed` {`freeflow`, `reason`, `counts`} quando
  `freeflow` ou `reason` mudam.
- Testes:
  - O `SpawnController` real do Ares, sobre um fake de produção (2 Barracks,
    Factory, Starport, 5.000/3.000 e 30 de supply livre), com 11/4/3/2 não
    treina nada.
  - No mesmo estado, o behavior do bot devolve `composition_met`, e o
    `SpawnController` que ele registra treina (inclusive Siege Tank).
  - 12/4/3/2 e exército vazio dão `composition_short` sem `freeflow`; o
    `freeflow` do plano dá `plan_freeflow`; o plano inativo dá `plan_inactive`.
  - Fluxo de frame com 11/4/3/2: `frame.spawn`, o `SpawnController` do
    `MacroPlan` em `freeflow` e o evento com as contagens.
- Com o `bot/` de `8b7f5ba` (extraído com `git archive`, testes novos por cima),
  o teste de reprodução falha na decisão: o `SpawnController` devolve `False` e
  não treina nada.
- Verificação local: 121 testes (inclusive o viewer no navegador, com o evento
  novo no log), ruff limpo.

**Não feito**

- Nenhuma partida: não se mediu banco, supply nem exército depois da correção.
- O frame em `freeflow` gasta, por prioridade, em toda estrutura ociosa, sem
  olhar proporção; o lote pode desviar a composição até o controlador corrigir.
- O `MacroPlan` do Ares para no primeiro behavior que age (`any`): no frame em
  que supply, workers, gás ou expansão agem, `SpawnController` e
  `ProductionController` não rodam.
- Banco depois de 200/200 (os dois traces passam de 10 mil minerais): o exército
  não ataca (6a) e não há upgrades nem tech depois do opening (fatia 7).

## 7c. Upgrades, Orbital e MULE depois do opening — feito

Evidência do problema: nos traces `483722e` e `3769f04` e na linha de base
`bench/6a` o gás passa de 4,5 mil (5,4–5,6 mil nos traces antigos) e
`economy.execute` não registrava nenhuma pesquisa depois do opening. O
`MacroPlan` do Ares para no primeiro behavior que age, e o `SpawnController`
age sempre que há produção ociosa, então nada depois dele rodaria.

**Feito**

- Attention: `upgrades` (concluídos, de `state.upgrades`).
- Ego/economy: `EconomyPlan.upgrades` (`UPGRADES`, 12 itens, fora de
  STABILIZE), `orbitals` e `mules` depois do opening; input `upgrades_done`.
- Body: `UpgradeCCs(ORBITALCOMMAND)` antes de `BuildWorkers`,
  `UpgradeController` antes do `SpawnController`; `call_mules`: Orbital pronto
  com ≥ 50 de energia solta MULE no campo mais cheio a ≤ 10 de um townhall
  pronto.
- Logs: `attention.observed.upgrades`, `behavior.economy_planned.upgrades`,
  `orbitals`, `mules`.
- Testes: plano com/sem upgrades (opening, STABILIZE); ordem do `MacroPlan`;
  o `UpgradeController` real do Ares pesquisa o primeiro não concluído e age
  (o `SpawnController` não roda naquele frame); MULE no campo certo, não abaixo
  de 50, não em Orbital inacabado, não no opening; upgrades no log pelo fluxo de
  frame.
- Partida: em `bench/all/000` os 12 upgrades estavam concluídos aos 1.197 s
  (na linha de base, nenhum além dos do opening — o campo não existia lá, mas
  nada os pesquisava).

**Não feito**: o banco continua enorme (35 mil minerais e 11 mil de gás em
`bench/all/000`): capacidade de produção (`max_production_structures` 12 do
Ares) e reposição são outra fatia. Scan/detecção, interrupção do opening,
supply/pending.

## 8a. Micro: Stim e Medivac acompanhando o grupo — feito

Seleção: dentro da fatia 8, o menor corte com um consumidor e teste.
`RegionState` não foi criado: nenhuma decisão desta sessão o exigiu (a busca
usa as expansões diretamente), e a regra dos documentos é não generalizar sem
consumidor.

Evidência do problema (código): o opening pesquisa Stim e nenhum behavior o
usava; Medivac recebia `AMove` para o alvo e, mais rápido, chegava antes do bio.

**Feito**

- Body/attack: Marine/Marauder com inimigo não-worker a ≤ 10, ≥ 50 % de vida,
  sem o buff e com a habilidade disponível usam Stim (`UseAbility`) antes do
  `AMove`; Medivac faz `AMove` para o centro das outras unidades concedidas.
- `behaviors.execute` devolve `BodyReport` (`spawn`, `micro`); `MicroReport`
  (`stimmed`, `escorts`) vai a `Frame.micro` e ao log
  `behavior.micro_executed` (todo frame com Stim; escoltas quando mudam).
- Testes: limites do alcance e da vida, buff, habilidade ausente, worker;
  Stim do Marauder; Medivac no centro do grupo e sozinho no alvo; relatório
  somado entre concessões; fluxo de frame com defensores usando Stim.
- Partida: `bench/all/000` registrou 852 frames com Stim (1.265 usos) e 11
  Medivacs escoltando.

**Não feito**: `RegionState`; stutter, focus, target scoring; Stim no HOLD;
Medivac evacuando.
## Itens de `propostas.md` fora de qualquer fatia concluída

- P0.2: distinguir scout, worker rush e ataque; histerese de admissão/liberação
  da defesa; antecipação e tráfego amigo do wall.
- P0.3: combat simulation, poder com alcance/splash, coesão e reforços da
  ofensiva; encerrar partidas contra Terran (timeout nas duas execuções).
- P0.4: interrupção do opening, supply/pending, reposição, capacidade de
  produção (banco de 12–29 mil minerais em `all3`), detecção e scan.
- P1.1–P1.5 e P2: scouting recorrente e estimativa do inimigo por produção ou
  economia vista, `RegionState`, micro além de Stim e escolta de Medivac, contrato completo de
  Proposal/Engine (desired_power, suitability, custos, preemption), builds por
  matchup, calibração.

## Mudanças nos documentos de orientação

- Regra de seleção sem escolha do usuário: bug decisório reproduzível → fatia
  de gameplay → trabalho operacional (este só antes quando bloquear verificação).
- `ThreatIncident`: regra determinística do id em divisão/fusão é obrigatória;
  eventos de linhagem, pathing e cenários de split/merge são evolutivos.
- Desconhecido: nem zero confiante, nem pior caso ilimitado; decisão ofensiva
  com estimativa mais margem proporcional à incerteza.
