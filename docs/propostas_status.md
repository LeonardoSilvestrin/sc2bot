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
| 4 | Wall bidirecional | Pendente | — |
| 5 | Desconhecido conservador mínimo | Pendente | — |
| 6a | Ofensiva: assemble/advance | Pendente | — |
| 6b | Ofensiva: engage/retreat/regroup | Pendente | — |
| 6c | Ofensiva: search/finish | Pendente | — |
| 7 | Macro resiliente (opening, supply, reposição, upgrades, spending) | Pendente | — |
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

## Itens de `propostas.md` fora de qualquer fatia concluída

- P0.2: distinguir scout, worker rush e ataque; histerese de admissão/liberação
  da defesa; wall.
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
