# Andamento das propostas

Registro do que já foi implementado a partir de `propostas.md` e
`propostas_corrigidas.txt`, e do que continua pendente. Cada fatia concluída
atualiza este arquivo no mesmo commit.

"Feito" significa: teste que reproduz o problema, suíte e lint verdes localmente,
diff restrito à fatia. **Nenhuma linha aqui é evidência de ganho de gameplay**:
ainda não existe baseline de partidas (fatia 2).

## Fatias

A numeração segue a §4 da corrigenda; ela agrupa marcos, não define a ordem de
seleção (ver regra no prompt corrigido).

| # | Fatia | Status | Commit |
| --- | --- | --- | --- |
| 1 | Gate de entrega (pytest/ruff antes do artefato) | Feito | `5ab151a` |
| 2 | Harness/baseline de partidas | Pendente | — |
| 3 | Contrato defensivo mínimo + `ThreatIncident` | Feito | `defense: one incident, one demand, one budget` |
| 4 | Wall bidirecional | Feito | `wall: raise depots when ground enemies come near` |
| 5 | Desconhecido conservador mínimo | Pendente | — |
| 6a | Ofensiva: assemble/advance | Pendente | — |
| 6b | Ofensiva: engage/retreat/regroup | Pendente | — |
| 6c | Ofensiva: search/finish | Pendente | — |
| 7a | Macro: plano econômico estável (contagem de workers) | Feito | `economy: count workers inside gas buildings` |
| 7 | Macro resiliente (opening, supply/pending, reposição, upgrades, spending) | Pendente | — |
| 8 | RegionState e micro | Pendente | — |

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
  lembrados pedem `poder·confiança`, que decai — o desconhecido conservador é a
  fatia 5.

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
- A semântica de `army`/`risk` sem visão continua na fatia 5.

## Itens de `propostas.md` fora de qualquer fatia concluída

- P0.2: distinguir scout, worker rush e ataque; histerese de admissão/liberação
  da defesa; antecipação e tráfego amigo do wall.
- P0.3–P0.4: toda a ofensiva e a macro resiliente.
- P1.1–P1.5 e P2: scouting recorrente, RegionState, micro, contrato completo de
  Proposal/Engine (desired_power, suitability, custos, preemption), builds por
  matchup, calibração.

## Mudanças nos documentos de orientação

- Regra de seleção sem escolha do usuário: bug decisório reproduzível → fatia
  de gameplay → trabalho operacional (este só antes quando bloquear verificação).
- `ThreatIncident`: regra determinística do id em divisão/fusão é obrigatória;
  eventos de linhagem, pathing e cenários de split/merge são evolutivos.
- Desconhecido: nem zero confiante, nem pior caso ilimitado; decisão ofensiva
  com estimativa mais margem proporcional à incerteza.
