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
| 7d | Macro: banco com supply livre | Investigado; mudança revertida, causa em aberto | `macro: detection and opening interrupt; hold stim` |
| 7e | Macro: detecção (scan, Missile Turret, reserva de energia) | Feito | `macro: detection and opening interrupt; hold stim` |
| 7f | Macro: interrupção do opening por emergência | Feito (sem evidência de partida) | `macro: detection and opening interrupt; hold stim` |
| 6e | Ofensiva: scan de reconhecimento da luta | Medido e revertido | `docs: record the 9-game baseline and the reverted fight scans` |
| 1b | Percepção: snapshots de memória do Ares não contam como vistos | Feito | `attention: see only this frame's enemies` |
| 3b | Identidade do incidente segue os membros | Feito | `awareness: keep an incident's id while its members stay` |
| 6d | Ofensiva: combat sim do Ares na decisão de lutar | Medido e revertido | `awareness: keep an incident's id while its members stay` (só documentação) |
| 7g | Macro: teto de produção cresce com as bases | Feito | `macro: let the production ceiling grow with the bases` |
| 7h | Macro: Reactors nas Barracks sem add-on | Feito (sem evidência de partida) | `macro: a reactor on every barracks with no add-on` |
| 7i | Macro: gás pelos geysers das bases | Feito (sem evidência de partida) | `macro: a refinery on every geyser the workers can mine` |
| 7 | Resto da macro (bases `ready + pending`, supply antecipado, reação a rush, reposição de produção, pico de banco) | Pendente | — |
| 8a | Micro: Stim e Medivac acompanhando o grupo | Feito | `offense: fight, retreat and search; macro upgrades; bio micro` |
| 8b | Micro: Stim no HOLD | Feito | `macro: detection and opening interrupt; hold stim` |
| 8 | `RegionState` e o resto do micro | Pendente | — |

As fatias 2, 6a–6c, 7c e 8a foram feitas numa mesma sessão, a pedido. O
harness tem commit próprio; as outras dividem arquivos e estão num só commit,
cada uma com sua seção e seus testes. As fatias 7d–7f e 8b também foram feitas
numa mesma sessão, a pedido ("implemente as fatias"), num só commit.

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
  (`NullLogger`); fingerprint de toda configuração decisória.
- O README do template foi substituído depois, fora de uma fatia (a
  pedido): identidade, capacidades, limitações, arquitetura, avaliação e
  entrega.

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
## 7d. Banco com supply livre — investigado, mudança revertida

Seleção: pedido explícito do usuário. Entre as partes pendentes da fatia 7,
esta é a que tem evidência de partida.

Evidência do problema: `bench/all3/001` (Terran VeryHard Macro), por
`attention.observed` a cada minuto: de 743 s a 1.182 s o banco fica entre 4 e
12 mil minerais com 19 a 117 de supply livre (806,8 s: 11.950 minerais,
164/200; 1.182,3 s: 4.015 minerais, 83/183) — o exército morre e não é
reposto. O mesmo aparece em `bench/7/002` (751–811 s: 8,4 mil minerais,
1,7 mil de gás, `freeflow`, 50 de supply livre, exército de 24 para 17
unidades).

Hipótese testada e rejeitada: o `ProductionController` do Ares, depois do
`SpawnController` no `MacroPlan` (que para no primeiro que age), quase nunca
rodaria. A mudança o registrou à parte, depois do plano. Em `bench/7`
(código com a mudança) o `ProductionController` passou a mandar Tech Labs em
Barracks que o `SpawnController` tinha acabado de mandar treinar no mesmo
frame (dezenas de `Adding BARRACKSTECHLAB` entre 587 s e 654 s e de
`FACTORYTECHLAB` aos 916–922 s no stdout de `bench/7/002`, contra nenhuma
rajada em `bench/all3/002`); a última ordem vale, e a Barracks para de treinar.
A hipótese também não se sustenta pelo código: com toda a produção ocupada o
`SpawnController` devolve `False` e o `ProductionController` já roda dentro do
plano (salvo quando supply, workers, gás, expansão ou upgrade agem antes).

**Feito**

- A mudança foi revertida; o `ProductionController` continua o último do
  `MacroPlan`, agora com o porquê no código.
- Teste: com o `SpawnController` agindo, o `ProductionController` não roda no
  mesmo frame (protege contra a reintrodução).
- Logs: `attention.observed.structures` (estruturas próprias por tipo, prontas
  ou não), que faltou para saber quantas Barracks havia quando o banco cresceu.

**Não feito**

- A causa do banco com supply livre continua desconhecida. Candidatos para a
  próxima partida com `structures` no log: produção destruída e não reposta,
  o teto de 12 Barracks do Ares, o supply dos 83 workers, Barracks com
  Reactor/Tech Lab ocupadas, o `break` do `SpawnController` em
  tipo prioritário que não pode pagar, ou comportamentos anteriores do
  `MacroPlan` agindo todo frame.
- Workers que caem de 83 para 28 com 7 mil minerais (`bench/all3/001`,
  1.119 s) não foram investigados.

## 7e. Detecção — feito

Seleção: pedido explícito do usuário; bug reproduzível por trace.

Evidência do problema: `bench/all4/000` (Zerg VeryHard Macro): um
`LURKERMPBURROWED` (tag 4391960578) aparece em `strongest_contacts` com
`visible: true` de 755 s em diante; de 771 s a pelo menos 799 s fica em
(64,65; 86,56), com `danger` 0,22–0,28. O mesmo tipo aparece em `bench/all/000`,
`bench/all5/000` e em dois traces de `logs/`. O bot não tinha scan, turret nem
Raven, e o python-sc2 não deixa atacar uma unidade camuflada sem detecção
(`can_be_attacked`). O trace não mostra quanto exército isso custou.

**Feito**

- Attention: `UnitView.energy`, `is_cloaked` (camuflada ou enterrada,
  detectada ou não) e `is_hidden` (e sem detecção), lidos de `is_cloaked`,
  `is_burrowed` e `is_revealed`.
- Awareness (descrição): `Contact.is_cloaked`/`is_hidden` do último
  avistamento; `AwarenessState.hidden_contacts` (escondidos à vista agora, sem
  estruturas) e `cloak_seen_at` (primeiro inimigo de exército visto camuflado
  ou enterrado; worker enterrado não conta).
- Ego (`planners/detection.py`, política): `DetectionConfig` validada e no
  fingerprint (`configs.detection`). Depois de `cloak_seen_at`: reserva de 50 de
  energia por Orbital, uma Missile Turret por base sem turret (pronta ou não)
  a ≤ 15, e uma Engineering Bay se não houver. Scan num escondido à vista com
  ≥ 2 Marines de exército a ≤ 10, se nenhum scan dos últimos 12,3 s o cobre
  (raio 13) e algum Orbital pronto tem 50 de energia; desempate: mais exército
  perto, mais poder escondido revelado, menor tag. Razões `no_cloak_seen`,
  `no_hidden_enemy`, `hidden_enemy_scanned`, `no_army_near_hidden`,
  `no_scan_energy`, `scan_hidden_enemy`.
- Body (`behaviors/detection.py`): scan pelo Orbital pronto de mais energia
  (menor tag no empate); Engineering Bay (`to_count=1`, ≥ 125 minerais) antes
  das turrets; uma turret por frame (≥ 100 minerais) pelo `BuildStructure` do
  Ares na expansão mais próxima da base, `missile_turret=True`, sem procurar em
  outras bases. Detecção roda antes da economia: MULE só com energia ≥ 50 +
  reserva, e o Orbital que escaneou não solta MULE no mesmo frame.
- Logs: `behavior.detection_planned` (todo scan; senão quando turrets,
  Engineering Bay, reserva, razão ou construção pedida ao Ares mudam — um
  pedido ainda não iniciado se repete a cada frame), com
  `inputs`, `scanned_by` e `building`; `awareness.updated` com
  `cloak_seen_at`, `hidden_contacts` e `strongest_contacts[].hidden`.
- Testes (`tests/test_detection.py`): sem camuflado, nada; escondido perto do
  exército → scan, reserva, turret só na base descoberta (turret exatamente a
  15 cobre), sem Engineering Bay pedida quando existe; turret inacabada cobre;
  scan não se repete por 12,5 s (config do teste) e volta exatamente ao fim;
  limites do alcance (10 conta, 10,1 não) e do poder (2 conta, 1 não); sem
  energia, Orbital inacabado ou sem Orbital → `no_scan_energy`; desempates;
  unidade detectada não é escaneada mas liga a reserva; Attention lê
  camuflagem, burrow, detecção e energia; contato lembrado fora de vista não é
  escondido à vista; Drone enterrado não liga `cloak_seen_at`; configuração
  inválida; o Body escolhe o Orbital de mais energia, respeita reserva e
  `busy`, põe a Engineering Bay antes, a turret na expansão certa e nada sem
  minerais; fluxo de frame com um Lurker enterrado a 8 de 4 Marines aos 771 s →
  scan, sem MULE do mesmo Orbital, e a trilha no log.

**Não feito**

- Raven; scan para informação ou para atacar em terreno alto; turret pela rota
  aérea ou na linha de minerais; política para camuflados perto de uma base sem
  exército (a turret é a resposta, e demora).
- A posição da turret é a do `BuildStructure` do Ares: sem posições de turret
  pré-calculadas para a base, ela cai numa posição 2×2 livre perto da base; se
  cair a mais de 15, a base continua pedindo turret.
- `cloak_seen_at` não expira; Observer, Overseer e alucinações não contam.
- O poder de um Lurker enterrado (2,1 Marines no trace) continua o de
  `sqrt(dps·vida)`.

## 7f. Interrupção do opening — feito (sem evidência de partida)

Seleção: pedido explícito do usuário; item 3 do "Próximo marco" de
`propostas.md`. Nenhum trace mostra o problema: em todas as partidas e traces
locais (`bench/*`, `logs/*`) não houve STABILIZE antes do fim do opening
(283–289 s). A IA Macro não faz rush; a fatia fica protegida só por cenário.

**Feito**

- Ego/economy: `OPENING_ABORT_DANGER = 0,6` (o `emergency_danger` da
  estratégia). Antes do fim do opening, com STABILIZE e
  `strategy.defense ≥ 0,6`, o plano fica ativo com `interrupt_opening`,
  razão `opening_interrupted`, `freeflow` (STABILIZE), sem upgrades, com
  Orbital e MULE. Input novo `danger`.
- Body/economy: com `interrupt_opening`, chama
  `build_order_runner.set_build_completed()` (só se ainda não terminou) antes
  de registrar qualquer behavior; o `MacroPlan` roda no mesmo frame. No frame
  seguinte `opening_done` é verdadeiro e o plano segue normal.
- Logs: `behavior.economy_planned.interrupt_opening` e `inputs.danger`.
- Testes: 0,6 interrompe e 0,59 não; BUILD_ADVANTAGE com 0,9 não; o Body para o
  runner uma vez em duas chamadas e não para com 0,1; fluxo de frame com seis
  Zerglings na main durante o opening → plano ativo, runner parado, evento com
  a razão, e no frame seguinte opening terminado sem nova interrupção. Com o
  `economy.py` anterior do Body o teste do runner falha.

**Não feito**

- Nenhuma partida contra rush: não se sabe se a interrupção ajuda.
- A interrupção é irreversível: um ataque que passa volta à macro dinâmica, não
  ao opening. Bunker, reparo, worker pull e reação a proxy não existem.

## 8b. Stim no HOLD — feito

Seleção: pedido explícito do usuário; menor corte de micro com consumidor. O
`RegionState` continua sem consumidor e não foi criado.

Evidência do problema (código): o CoreArmy luta com `AMove` quando um inimigo
chega a 10 de uma unidade no rally, e só o `attack` usava Stim.

**Feito**

- Body: `STIMS`, `STIM_RANGE`, `STIM_MIN_HEALTH` e `stim_for` passam para
  `combat.py` (o `attack` os reexporta); `core_army.execute` usa a mesma regra
  quando luta e devolve `MicroReport`, somado em `behavior.micro_executed`.
- Testes: Zergling exatamente a 10 → `UseAbility` e `AMove`; SCV a 2 → só
  `AMove`; Zergling a 10,5 → `PathUnitToTarget`; no fluxo de frame, os Marines
  que ficaram no rally também usam Stim (o teste passa a esperar a união).

**Não feito**: stutter, focus, target scoring, Medivac evacuando.

## Verificação da sessão 7d–7f/8b

- Local: 236 testes, `ruff check bot tests harness run.py bench.py` limpo.

- Partidas: mesma matriz das execuções anteriores (Persephone AIE, IA
  VeryHard Macro, uma por raça, seed 1, 1.200 s), cada uma de um `git worktree`
  sujo (`dirty: true`). Uma partida por combinação: nenhuma diferença é
  estatisticamente significativa.

| Execução | Código | Fingerprint | Zerg | Terran | Protoss |
| --- | --- | --- | --- | --- | --- |
| `bench/all3` | linha de base (antes da sessão) | `aaba38f6fedc1e7f` | vitória, 848 s | timeout | vitória, 1.121 s |
| `bench/7` | + 7d (revertida), 7e, 7f, 8b | `ab57813d0bfcc3fe` | vitória, 747 s | vitória, 710 s | derrota, 1.157 s |
| `bench/7b` | **código final** (sem 7d) | `ab57813d0bfcc3fe` | vitória, 707 s | timeout | vitória, 861 s |

- O fingerprint muda da linha de base por `configs.detection`. Nenhum crash nem
  `Traceback` no stdout das seis partidas.
- `bench/7/002`: a derrota levou à reversão da 7d (ver a seção). Com o mesmo
  seed, as partidas divergem da linha de base antes de 562 s.
- Detecção em jogo (Terran): em `bench/7/001` um inimigo camuflado aos 547 s
  levou a Missile Turrets em todas as bases até 597 s (o log pedia a turret a
  cada frame, 537 eventos; o gate foi corrigido). Em `bench/7b/001`, 2 scans
  (`scan_hidden_enemy`), 17 frames com escondido sem exército perto e 7
  turrets aos 880 s. Contra Zerg e Protoss nenhum camuflado apareceu nestas
  partidas; o Lurker da evidência não se repetiu.
- Banco (amostras de `attention.observed` depois de 600 s com ≥ 4 mil minerais,
  ≥ 19 de supply livre e < 190 usados): `all3` 14 / 74 / 25, `7b` 0 / 63 / 2
  (Zerg / Terran / Protoss); as partidas têm durações diferentes, então não é
  comparação de taxa. Em `bench/7b/001`, `structures` mostra 12 Barracks — o
  teto `max_production_structures` do Ares — desde 694 s, e 83 workers: aos
  787 s, 9,5 mil minerais com 184/200 de supply e só 39 unidades de exército.
  Teto de produção e supply de workers são as próximas hipóteses da 7d.
- Interrupção do opening: não aconteceu em nenhuma partida (esperado contra a
  IA Macro).

## 7g. Teto de produção cresce com as bases — feito

Seleção: pedido explícito do usuário ("aplique as propostas e fatias", depois
"continue com o próximo feature"). É a hipótese da 7d com evidência de
partida; supply block, a outra hipótese, não tem evidência (≤ 4 amostras de
`attention.observed` com supply cheio abaixo de 200 por partida, em `bench/7b`
e `bench/all3`).

Evidência do problema: as três partidas de `bench/7b` chegaram a 12 Barracks
aos 606–641 s, o `max_production_structures` padrão do `ProductionController`
do Ares, e nunca passaram disso. Em `bench/7b/001` (Terran), com 6 bases, 83
workers e 6 Orbitals, o banco foi de 4.155 minerais (608,9 s) a 9.930
(773,1 s) enquanto o exército caía para 31 unidades com 37 de supply livre, e
a composição estava abaixo da proporção de Marines (15/13/11/9 aos 805 s). Pela
conta de capacidade (estimativa, não medida): 12 Barracks (1 Reactor, 6 Tech
Labs), 2 Factories e 1 Starport gastam ~3,9 mil minerais/min, e a renda com 83
workers e 6 MULEs passa de ~5 mil/min; a regra de renda do próprio Ares
(`renda / (custo · 4,5)`) pediria ~22 Barracks. O `get_build_structures` e o
`SpawnController` foram lidos e não mostram outro bloqueio.

**Feito**

- Ego/economy: `PRODUCTION_PER_BASE = 4` e
  `EconomyPlan.max_production = 4 · bases` (3 bases = 12, o padrão do Ares;
  6 bases = 24). Input `production_per_base`.
- Body/economy: `ProductionController(max_production_structures=plan.max_production)`.
  Quantas estruturas construir dentro do teto continua sendo a regra de renda e
  de banco do Ares.
- Logs: `behavior.economy_planned.max_production` (entra na assinatura do
  gate) e `inputs.production_per_base`.
- Testes (`tests/test_economy.py`): teto 4/12/24 com 1/3/6 bases; o
  `ProductionController` real do Ares, sobre um fake com renda de seis bases,
  banco de 9.930/3.041, Barracks todas ocupadas e Marines abaixo da proporção,
  pede a 13ª Barracks com 6 bases, nada com 3 bases e 12 Barracks, uma com 3
  bases e 11, e nada com 6 bases e 24. Com o Body anterior o teste das 6 bases
  falha (não passa de 12). Fluxo de frame: `max_production` no log igual ao
  plano e a `production_per_base · bases`.
- Verificação local: 242 testes, ruff limpo.

**Partidas** (mesma matriz: Persephone AIE, IA VeryHard Macro, seed 1,
1.200 s; `bench/7g` rodou da árvore de trabalho, `dirty: true`, sobre
`f8da5b0`, que tem o mesmo código de `bench/7b`). Uma partida por raça: nenhuma
diferença é estatisticamente significativa.

| Execução | Zerg | Terran | Protoss |
| --- | --- | --- | --- |
| `bench/7b` (linha de base) | vitória, 707 s | timeout | vitória, 861 s |
| `bench/7g` | vitória, 702 s | vitória, 891 s | vitória, 868 s |

Depois de 600 s (amostras de `attention.observed`; Zerg / Terran / Protoss):

| Execução | Máximo de Barracks | Amostras com ≥ 4 mil minerais, ≥ 19 de supply livre e < 190 usados | Pico de minerais |
| --- | --- | --- | --- |
| `bench/7b` | 12 / 12 / 12 | 0 de 22 / 63 de 140 / 2 de 57 | 9.465 / 10.245 / 16.275 |
| `bench/7g` | 20 / 24 / 24 | 0 de 21 / 12 de 65 / 2 de 58 | 7.870 / 17.890 / 14.300 |

Nenhum `Traceback` no stdout. O `config_fingerprint` não mudou
(`ab57813d0bfcc3fe`): a economia não tem config no fingerprint.

**Não feito**

- O banco ainda chega a 14–18 mil minerais: com o supply cheio não há onde
  gastar, e o teto não resolve isso. Reactors nas Barracks sem add-on (5 de 12
  em `bench/7b/001`) não foram tratados.
- `PRODUCTION_PER_BASE` não foi calibrado nem entra no fingerprint; a vitória
  contra Terran é uma partida só e pode ter outras causas.
- Bases `ready + pending`, supply antecipado e reação a rush continuam
  pendentes.

## 6d. Combat sim do Ares na decisão de lutar — medido e revertido

Seleção: pedido explícito do usuário (continuar com a próxima fatia); item
pendente da 6b ("combat simulation do Ares e poder com alcance/splash").

Evidência do problema: `bench/7b/001` (Terran), 739,6–745,3 s — com parcela
local de 0,61–0,71 pelo poder, o grupo entrou em luta contra 4–5 Siege Tanks em
siege, Liberators em modo terrestre e 2 Missile Turrets, caiu de 70 para 34 de
poder em 3,5 s (`army_depleted` aos 746,9 s) e a ofensiva não comprometeu de
novo até o fim da partida. `sqrt(dps·vida)` não vê alcance nem splash.

**Experimento**

- Ego/offense: a luta local passava a ser julgada também pelo
  `mediator.can_win_fight` do Ares (unidades do grupo a ≤ `engage_radius` do
  núcleo contra os inimigos da luta à vista, unidades e estruturas), com
  `simulated_share = EngagementResult / 10`, e a parcela local era
  `min(parcela por poder, simulated_share)`. O simulador era uma consulta só de
  leitura sobre o bot, passada ao planner como `held_by`
  (`bot/body/combat_sim.py`). Logs: `power_share` e `simulated_share` em
  `inputs` e em `fight`.
- 257 testes e ruff verdes; os testes cobriam recuo com o simulador perdendo,
  recuo depois do dwell, simulador que não sobe a parcela, luta ganha, só
  inimigos à vista e a ligação no fluxo de frame.

**Partidas** (`bench/6d`, sobre `053aefd` sujo, mesma matriz):

| Execução | Zerg | Terran | Protoss |
| --- | --- | --- | --- |
| `bench/7g` (linha de base) | vitória, 702 s | vitória, 891 s | vitória, 868 s |
| `bench/6d` | vitória, 702 s | timeout | vitória, 868 s |

- Zerg e Protoss: mesma duração da linha de base; em nenhuma avaliação o
  simulador ficou abaixo da parcela por poder (45 e 32 avaliações
  registradas).
- Terran: 5 de 47 avaliações registradas abaixo do poder. A única decisão que o simulador
  mudou foi um recuo aos 659,4 s (poder 0,72, simulado 0,2); a partida diverge
  da linha de base a partir daí e termina em `timeout`. Nas duas lutas que
  custaram metade do exército (623,9 s: 81 → 35; 761,4 s: 71 → 34) o simulador
  respondeu 1,0 (vitória enfática): ele só vê inimigos à vista, e Siege Tanks
  em siege atiram de fora da visão.
- Uma partida por raça: nenhuma diferença é significativa, mas o simulador não
  mostrou o efeito pretendido. Sem ganho medido, o código e os testes saíram
  (como a regra de recuo por perda da 6b).

**Não feito / próximo passo possível**: contar contatos lembrados fora de visão
no simulador (o Ares só aceita `Unit` vivos), ou dar ao poder alcance e
splash; nenhum dos dois foi tentado.

## 3b. Identidade do incidente segue os membros — feito

Seleção: bug decisório reproduzível por trace (classe 1), achado nos logs de
`bench/7g`; pedido explícito do usuário de continuar.

Evidência do problema: em `bench/7g/001`, aos 520,4 s, o contato de menor tag
(…14017) saiu de um incidente de 7 membros e o mesmo ataque (os outros 6
continuaram) passou de `incident:4361814017` a `incident:4363124737`. A
proposta de defesa é `defense:<incident_id>:<parte>`, então foi renomeada, e o
Engine, que prefere as unidades que já eram da proposta, a tratou como nova:
todas as unidades aparecem como transferidas entre as duas propostas. Por
partida em `bench/7g`, transferências `defense → defense`: 115 / 165 / 123
(Zerg / Terran / Protoss), e unidades que voltam à proposta anterior em menos
de 2 s: 49 / 100 / 56. A regra anterior (id = menor tag, que vale só enquanto
esse contato está no grupo) produz a troca por construção.

**Feito**

- Awareness: o id segue os membros. Cada grupo herda o id do incidente do frame
  anterior com quem mais compartilha membros; pares resolvidos por mais membros
  em comum, depois menor tag do grupo, depois menor tag que o incidente
  anterior tinha; cada id vai a um grupo só. Sem herança:
  `incident:<menor tag>`, com sufixo `-1`, `-2`, … enquanto o id estiver em
  uso. Os casos do teste anterior (divisão e fusão de dois contatos) dão os
  mesmos ids de antes. A ordem dos incidentes continua pela menor tag.
- Nenhuma mudança em Ego, Engine ou logs: `awareness.updated.incidents[]` já
  traz id e contatos, o que basta para reconstruir a herança.
- Testes: a menor tag morre e o id fica; um recém-chegado de tag menor não
  renomeia; a menor tag sai sozinha → os dois que ficaram mantêm o id e ela
  recebe `incident:3-1`; refundido, volta a `incident:3`; fusão de um incidente
  de 1 com um de 3 fica com o id do de 3. Defesa ponta a ponta: o Zergling que
  nomeava o incidente morre, a proposta continua
  `defense:incident:90:ground` e as duas unidades concedidas saem das três que
  já defendiam, embora a quarta esteja mais perto. Com o `model.py` anterior os
  três testes falham.
- Verificação local: 245 testes, ruff limpo.

**Partidas** (`bench/3b`, sobre `053aefd` sujo, mesma matriz; linha de base
`bench/7g`, mesmo código sem a 3b):

| Execução | Zerg | Terran | Protoss |
| --- | --- | --- | --- |
| `bench/7g` | vitória, 702 s | vitória, 891 s | vitória, 868 s |
| `bench/3b` | vitória, 707 s | timeout | vitória, 868 s |

- Transferências `defense → defense` por partida: 115 / 165 / 123 → 0 / 120 / 0.
  As 120 da Terran são todas dentro de um mesmo incidente, entre as partes
  `ground` e `air` (109) ou entre incidentes que realmente se separam: o id não
  muda mais, mas o Engine reparte as unidades antiaéreas de novo quando a razão
  entre poder aéreo e terrestre muda.
- Terran: sem bases perdidas, mas `timeout`. Contra Terran os resultados
  oscilam entre execuções com o mesmo seed (7b timeout, 7g vitória, 6d timeout,
  3b timeout): basta uma decisão diferente para a partida divergir. Uma partida
  por raça não permite atribuir o timeout à 3b nem a vitória da 7g à 7g.
- Nenhum `Traceback`; fingerprint inalterado (`ab57813d0bfcc3fe`).

**Não feito**: troca de unidades entre as partes `air`/`ground` da mesma
demanda; histerese pelo poder; eventos explícitos de linhagem.

## 1b. Snapshots de memória do Ares não contam como vistos — feito

Seleção: bug de percepção reproduzível por trace (classe 1), achado ao ler o
`UnitMemoryManager` do Ares para a 6d; pedido explícito do usuário de
continuar. (O número segue a camada: Attention é a primeira.)

Evidência do problema:

- Código: a cada passo, o `UnitMemoryManager` do Ares acrescenta a
  `bot.enemy_units` o último snapshot (`Unit` de um frame anterior) de cada
  inimigo fora de visão, por até 30 s (`expire_ground`/`expire_air`), ou até a
  posição voltar à visão. O `is_visible` desse objeto lê o proto antigo e
  continua verdadeiro; o `_visible` do Attention só olhava isso.
- Trace: em `bench/3b`, contatos de unidade (sem estruturas e sem Siege Tank em
  siege) que ficaram "visíveis" parados na mesma posição por ≥ 3 s e depois
  sumiram: 24 / 36 / 22 por partida, com pico em 25–35 s (10 / 21 / 4). Os
  exemplos mais longos são SCVs, Drones e Probes minerando, vistos pelo scout
  aos 122–141 s e "parados" por 26,2–32,0 s. Workers minerando não ficam
  parados. Enquanto isso a Awareness os mantinha com confiança 1 e incerteza 0
  na última posição, e o decaimento (τ = 20 s) só começava depois.
- Body: a regra do Stim e o gatilho de luta do HOLD liam `bot.enemy_units`
  direto, então um inimigo lembrado a ≤ 10 também disparava Stim ou tirava a
  unidade do path.

**Feito**

- Attention: `_visible` exclui unidades com `is_memory` (objeto de outro game
  loop), em unidades e estruturas. Lembrar é papel da Awareness.
- Body/combat: `present(enemies)`; o Stim (`attack` e `core_army`) e o gatilho
  de luta do HOLD usam só inimigos presentes. A decisão de siege do Siege Tank
  continua com a memória do Ares, de propósito (tanks inimigos em terreno alto
  somem da visão).
- Nenhum evento novo: `attention.observed.visible_enemy_units` e
  `awareness.updated` (`visible`, `confidence`) já mostram a diferença.
- Testes: fluxo de frame — um Zergling visto aos 100 s e, aos 105 s, só como
  snapshot do Ares não está em `attention.enemy_units`, e o contato fica
  `visible = False` com confiança `exp(-5/20)`; o log registra 1 e depois 0
  inimigos visíveis. Body — um inimigo lembrado a 2 células não dispara Stim
  no ATTACK e, no HOLD, a unidade segue o path. Com o código anterior os três
  testes falham.
- Verificação local: 247 testes, ruff limpo.

**Partidas** (`bench/1b`, sobre `f1743c9` sujo, mesma matriz; linha de base
`bench/3b`):

| Execução | Zerg | Terran | Protoss |
| --- | --- | --- | --- |
| `bench/3b` | vitória, 707 s | timeout | vitória, 868 s |
| `bench/1b` | vitória, 900 s | vitória, 869 s | vitória, 869 s |

| Execução | Contatos "visíveis" congelados ≥ 3 s (25–35 s) | Usos de Stim |
| --- | --- | --- |
| `bench/3b` | 24 (7) / 36 (21) / 22 (4) | 408 / 368 / 417 |
| `bench/1b` | 6 (0) / 2 (0) / 0 (0) | 446 / 140 / 224 |

Os usos de Stim dependem da duração e das lutas de cada partida; não são uma
comparação de taxa. Nenhum `Traceback`. Uma partida por raça: a vitória contra
Terran não é atribuível à fatia (ver a nota da 3b sobre a variação contra
Terran), e a Zerg durou 193 s a mais.

**Não feito**: o overlay e o SVG não distinguem contato lembrado pelo Ares;
outras leituras do Ares que misturam memória (grids de influência, que são do
Ares) continuam como estão.

## Análise: trocas perdidas contra Terran (sem fatia)

Registro para a próxima fatia de combate; nada foi mudado por isto.

- Em `bench/3b/001` a ofensiva comprometeu 7 vezes e terminou 5 vezes em
  `army_depleted` 10–20 s depois de `favorable_fight`. Nas quatro lutas
  medidas (620–645 s, 738–752 s, 958–978 s, 1.070–1.098 s) o grupo entra com
  parcela local de 0,85–0,90 contra 7–10 de poder inimigo à vista; ao avançar,
  aparecem Siege Tanks em siege (o tipo mais frequente em `strongest_contacts`
  em três das quatro janelas), Liberators em modo terrestre, Cyclones e
  Hellbats, o inimigo local sobe para 21–54 e a parcela cai para 0,49–0,69,
  ainda acima de `retreat_share`, enquanto o núcleo perde 40–70 % do poder.
- O banco chega a 21 mil minerais com o supply cheio: perder o exército não
  falta dinheiro, mas cada onda chega com `assemble_timed_out` (parcela reunida
  0,62–0,79) e troca mal.
- Estabilidade de decisão nas partidas da 1b e da 3b: 2–5 trocas de objetivo
  por partida, nenhuma em menos de 10 s; nenhum rally A-B-A em 5 s.
- Candidatos, todos a medir contra uma linha de base com mais de uma partida
  por raça: splash/alcance no poder (Siege Tank em siege vale 2,7 Marines por
  `sqrt(dps·vida)`), scan de informação antes de engajar, e de novo o recuo por
  perda da 6b (medido com uma partida por raça). O combat sim do Ares (6d) não
  ajudou porque só vê o que está à vista.
- Linha de base maior: ver "Linha de base de 9 partidas" abaixo.

## Linha de base de 9 partidas (`bench/base3`)

Trabalho operacional, feito porque uma partida por raça não separava nenhuma
mudança contra Terran (7b, 7g, 6d e 3b deram timeout, vitória, timeout e
timeout com o mesmo seed).

- Código: `fe3cea0` limpo (`dirty: false`), de um `git worktree`. No worktree
  o submódulo não existe, então `ares_commit` sai nulo no `result.json`; o Ares
  importado é o do repositório principal (`8730865`). Fingerprint
  `ab57813d0bfcc3fe`.
- Matriz: Persephone AIE, IA VeryHard Macro, Zerg/Terran/Protoss, seeds 1–3,
  1.200 s (`bench.py run --games 3`).
- As partidas de seed 1 repetiram as de `bench/1b` (mesmo código) com os
  mesmos resultados e durações (900 / 869 / 869 s): reprodutível nesta máquina.

| Seed | Zerg | Terran | Protoss |
| --- | --- | --- | --- |
| 1 | vitória, 900 s | vitória, 869 s | vitória, 869 s |
| 2 | vitória, 775 s | vitória, 788 s | vitória, 701 s |
| 3 | vitória, 726 s | timeout | vitória, 708 s |

8 vitórias em 9 (Wilson 95 %: 0,57–0,98); por raça, 3/3 (0,44–1,00) ou 2/3
(0,21–0,94). Nenhum `Traceback`. Duas partidas rodaram ao mesmo tempo (esta e a
da 6e); os jogos são por passo, então a concorrência muda só o tempo de relógio.

## 6e. Scan de reconhecimento da luta — medido e revertido

Seleção: pedido explícito do usuário de continuar; primeiro candidato da
análise das trocas contra Terran (o grupo só vê os Siege Tanks depois de
entrar).

**Experimento**

- Ego/offense: `OffensePlan.contested_at`, o centro inimigo de uma luta
  disputada enquanto a ofensiva avança, busca ou está engajada.
- Ego/detection: `DetectionConfig.fight_scans` (padrão ligado). Depois do
  opening, cada Orbital guardava `scan_reserve` mesmo sem camuflado visto; sem
  escondido para escanear, o ponto disputado era escaneado se nenhum scan dos
  últimos `scan_duration` o cobria e havia energia (`scan_fight`,
  `fight_scanned`, input `contested_fight`). O Body já escaneava.
- 252 testes e ruff verdes, com um teste de ponta a ponta (ofensiva engajada →
  plano → scan do Orbital → log).

**Partidas** (`bench/6e3`, `a6f3787` + a mudança, `dirty: true`, mesma matriz de
9; fingerprint `1c6e017343309485`, porque a `DetectionConfig` mudou):

| Seed | Zerg | Terran | Protoss |
| --- | --- | --- | --- |
| 1 | timeout | vitória, 784 s | vitória, 862 s |
| 2 | vitória, 739 s | vitória, 833 s | vitória, 700 s |
| 3 | vitória, 797 s | vitória, 1.071 s | vitória, 694 s |

- 8 em 9, como a linha de base: nenhuma diferença.
- Scans de luta por partida: 1 / 5 / 4 / 10 / 3 / 6 / 19 / 18 / 7. Em nenhuma
  das 9 partidas um recuo por `unfavorable_fight` veio nos 3 s depois de um
  scan de luta: o efeito pretendido (ver os tanks e não entrar) não apareceu.
  Os scans acontecem quando a luta já está disputada, e o grupo já está dentro
  do alcance.
- Terran seed 3: `army_depleted` 3 vezes e timeout na linha de base; 2 vezes e
  vitória aos 1.071 s com a mudança. Zerg seed 1: a partida diverge da linha de
  base antes da primeira luta (a reserva muda o ritmo dos MULEs); o único scan
  de luta, aos 833,2 s, veio no mesmo frame do ENGAGE com parcela 0,89, e o
  grupo recuou por `fight_lost` 7,6 s depois, com metade do poder.
- Sem ganho medido e sem o mecanismo observado, o código e os testes saíram.

**Próximo passo possível**: escanear antes, na rota do avanço (antes de a luta
ficar disputada), ou dar ao poder alcance e splash; nenhum foi tentado.

## 7h. Reactors nas Barracks sem add-on — feito (sem evidência de partida)

Seleção: a regra do prompt corrigido (bug decisório reproduzível → fatia de
gameplay → operacional) sobre as partes pendentes da fatia 7. É o item que a
própria 7g deixou escrito no "Não feito" com evidência de partida, e a menor
fatia cujos pré-requisitos já existem (composição, `MacroPlan`, teto de
produção).

Evidência do problema: em `bench/7b/001` (Terran VeryHard Macro), 5 das 12
Barracks estavam sem add-on aos 773 s, enquanto o banco ia de 4.155 minerais
(608,9 s) a 9.930 (773,1 s) com 37 de supply livre e o exército caía para 31
unidades. Depois da 7g, com o teto em 24, o banco ainda chegou a 14–18 mil
minerais e 12 de 65 amostras de `bench/7g` (Terran, depois de 600 s) tinham
≥ 4 mil minerais, ≥ 19 de supply livre e supply usado < 190. Uma Barracks com
Reactor treina dois Marines de uma vez: é capacidade de gasto que já está
construída e paga 50/50.

**Feito**

- Ego/economy: `EconomyPlan.reactors` (verdadeiro depois da abertura e fora de
  `STABILIZE`, como os upgrades: enquanto estabiliza, todo recurso vai para o
  exército) e `EconomyPlan.techlab_reserve = TECHLAB_RESERVE = 1`, as Barracks
  que continuam sem add-on para o Ares poder pôr um Tech Lab quando a
  composição pedir Marauders. Input `techlab_reserve`.
- Body/economy: `AddReactors`, uma `MacroBehavior` do Ares dentro do
  `MacroPlan`, **última** do plano. Manda `build(BARRACKSREACTOR)` na Barracks
  pronta, ociosa e sem add-on de menor tag, uma por frame, enquanto sobrarem
  mais de `techlab_reserve` livres e o bot puder pagar
  (`can_afford(BARRACKSREACTOR)`, 50/50, sem custo de supply: é justamente com
  o supply cheio que ela precisa agir).
- Por que última: depois do `SpawnController` pelo mesmo motivo do
  `ProductionController` — um add-on mandado numa Barracks que acabou de
  receber ordem de treino substitui a ordem (`bench/7/002`) — e depois dele
  porque uma ordem que o jogo recusa (sem espaço ao lado da Barracks) agiria
  todo frame e deixaria o resto do plano sem vez.
- Logs: `behavior.economy_planned.reactors` e `.techlab_reserve` (ambos na
  assinatura do gate) e `inputs.techlab_reserve`; os Reactors construídos
  aparecem em `attention.observed.structures` como `BARRACKSREACTOR`.
- Testes (`tests/test_economy.py`): o plano liga os Reactors depois da abertura
  e os desliga na abertura e ao estabilizar; o caso da `bench/7b/001` (7 com
  add-on, 5 sem) manda um Reactor na de menor tag livre; Barracks treinando,
  não pronta ou já com add-on não recebem nada; a última sem add-on fica
  reservada e o `_add_techlab_to_existing` de verdade do Ares consegue pôr o
  Tech Lab nela; 50/49 e 49/50 não pagam um Reactor e 50/50 paga; e o frame em
  que o `SpawnController` age não chega ao `AddReactors`. `tests/test_frame_flow.py`:
  a decisão e a reserva aparecem no `behavior.economy_planned` do fluxo real.
- Verificação local: 253 testes e `ruff check bot tests harness run.py bench.py`
  limpos (`.venv`, sem poetry nesta máquina).

**Não feito**

- Nenhuma partida foi jogada com a mudança: não há evidência de que o banco
  caia, de que a vazão suba nem de efeito em vitória. `TECHLAB_RESERVE` não foi
  calibrado e a economia continua fora do `config_fingerprint`.
- Reactors de Factory e Starport (Medivacs saem de Starport com Reactor ao
  dobro) e `AddOnSwap` do Ares ficaram fora.
- Espaço ao lado da Barracks não é verificado antes da ordem; uma Barracks sem
  lugar para o add-on é tentada de novo a cada frame ocioso (por isso a
  behavior é a última do plano). Se aparecer num log, o próximo passo é lembrar
  a tag recusada ou usar o `AddOnSwap`.
- Continuam pendentes da fatia 7: bases por `ready + pending`, supply
  antecipado, reação a rush além da interrupção do opening e o pico de banco com
  o supply cheio.

## 7i. Gás pelos geysers das bases — feito (sem evidência de partida)

Seleção: bug decisório reproduzível por trace (classe 1), achado na linha de
base de 9 partidas (`bench/base3`), sobre as partes pendentes da fatia 7. É a
menor fatia cujos pré-requisitos já existem: o alvo de gás já existe no
`EconomyPlan` e o `GasBuildingController` do Ares já o consome.

Evidência do problema: o alvo era `min(2 · bases, 1 + workers // 12)`. Com 83
workers ele trava em 7 a partir de ~467 s, e as 9 partidas de `bench/base3`
terminam com `REFINERY: 7` enquanto seguram 6 bases — 12 geysers, 5 deles
parados até o fim. Entre 300 e 700 s, cada partida passou de 5 a 30 amostras de
`attention.observed` com menos de 100 de gás e mais de 800 minerais no banco
(de 89 a 150 amostras por partida; 4 % a 29 %), e **nenhuma** amostra no caso
espelhado (menos de 100 de minerais com mais de 800 de gás) em nenhuma das 9
partidas. O gás é o recurso que limita exatamente na janela em que o exército e
os upgrades são pagos; a composição é 45 % de unidades de gás (Marauder 25,
Siege Tank 125, Medivac 100) e cada Tech Lab custa mais 25.

**Feito**

- Ego/economy: `GAS_BUILDINGS_PER_BASE = 2` (os geysers de uma base nos mapas
  de ladder), `WORKERS_PER_GAS_BUILDING = 3` (o que um Refinery comporta, o
  `Mining.workers_per_gas` do Ares) e `GAS_WORKER_SHARE = 0.4` (o máximo da
  força de trabalho que pode estar no gás). O alvo passa a ser
  `min(2 · bases, int(workers · 0,4) // 3)`: com 6 bases e 83 workers, 11
  Refinerys (33 workers no gás, 50 nas linhas de minério) no lugar de 7.
- Nada mudou no Body: o `GasBuildingController(to_count=plan.gas)` já recebia o
  alvo, e quem constrói, escolhe o geyser e distribui os 3 workers continua
  sendo o Ares.
- Logs: `inputs.gas_worker_share` no `behavior.economy_planned`, ao lado de
  `workers` e `bases`, que já bastavam para recompor a conta.
- Testes (`tests/test_economy.py`): o caso da linha de base (6 bases, 83
  workers) pede 11; o alvo nunca passa dos geysers das bases (3 bases, 83
  workers = 6) nem do que a parcela de workers consegue minerar (6 bases, 12
  workers = 1; 41 workers = 5); e o `GasBuildingController` de verdade do Ares,
  sobre um fake de 6 bases com 7 Refinerys, recusa o oitavo geyser com o alvo
  antigo (7) e o inicia com o alvo do plano — o geyser livre mais perto do
  start. `tests/test_frame_flow.py`: com 3 bases e 48 workers o plano pede os
  6 geysers e não oscila quando um SCV está dentro de um Refinery.
- Verificação local: 258 testes e `ruff check bot tests harness run.py
  bench.py` limpos (`.venv`, sem poetry nesta máquina).

**Não feito**

- Nenhuma partida foi jogada com a mudança: não há evidência de que o gás pare
  de limitar, de que os upgrades saiam antes, nem de efeito em vitória. Trocar
  minério por gás pode atrasar Marines na janela de 300-500 s, quando o banco
  de minério ainda é baixo; é o risco principal e só uma partida mede.
- `GAS_WORKER_SHARE` não foi calibrado e a economia continua fora do
  `config_fingerprint`.
- A distribuição de workers entre minério e gás continua sendo a do Ares (3 por
  Refinery, sem rebalanceamento por preço); o plano só escolhe quantos Refinerys
  existem.
- Não entra aqui: geysers de bases que o bot não segura, `vespene_boost`, nem
  reduzir o gás quando o banco de gás é que sobra (o final de partida, com
  supply cheio, banca 4-5 mil de gás — é consequência do teto de supply, não do
  alvo).

**Medido de passagem em `bench/base3`, sem fatia** (para a próxima seleção)

- Supply block: 22 s por partida em média, quase todo no intervalo 20-35 s (a
  abertura, que é do build runner do Ares) mais 5-10 s perto de 420-455 s.
  "Supply antecipado" não tem evidência que sustente uma fatia.
- As 9 partidas param em exatamente 6 bases (~560-600 s) e nunca expandem
  de novo: `saturated` pede `workers >= 16 · bases` = 96 enquanto `MAX_WORKERS`
  é 80. A regra é inalcançável acima de 5 bases. Com o banco em 14-18 mil
  minerais não é o gargalo, mas é uma condição que nunca pode ser satisfeita.
- Reactors de Factory/Starport (pendência da 7h) não têm evidência: as 9
  partidas terminam com Tech Lab em todas as Factories e um Reactor no
  Starport, postos pelo `TechUp` do Ares.

## Itens de `propostas.md` fora de qualquer fatia concluída

- P0.2: distinguir scout, worker rush e ataque; histerese de admissão/liberação (a 3b tirou a troca de id, não a do poder)
  da defesa; antecipação e tráfego amigo do wall.
- P0.3: combat simulation com contatos fora de visão (6d medida e revertida), poder com alcance/splash, coesão e reforços da
  ofensiva; encerrar partidas contra Terran (timeout nas duas execuções).
- P0.4: banco que continua alto com supply cheio (7g; a 7h deu aos Reactors um
  destino para ele e a 7i deu ao gás, nenhuma das duas com partida que o meça),
  bases por `ready + pending` e expansão presa em 6 bases, reposição de produção
  destruída; reação a rush além da interrupção do opening
  (bunker, reparo, worker pull, proxy); Raven e scan de informação.
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
