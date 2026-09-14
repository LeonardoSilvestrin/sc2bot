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
| 3 | Contrato defensivo mínimo + `ThreatIncident` | Em andamento | — |
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

## 3. Contrato defensivo mínimo + `ThreatIncident` — em andamento

Evidência do problema: trace `788af1d`, t=500 s — um SCV (poder 0,58) gerou três
propostas `defense:base:*` com o mesmo alvo, e o Engine concedeu Marine,
Marauder e Siege Tank. No trace de `483722e`, 1.671 de 2.117 conjuntos de
propostas tinham duas ou mais defesas simultâneas.

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
