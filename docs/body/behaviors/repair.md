# Repair

↑ [Body](../README_BODY.md) · [Defense](../../ego/planners/defense.md)

> O que o Body faz com os SCVs de um `REPAIR`: consertar o que está danificado no ponto.

## Quem chama

**Defense**, na `RushDefenseMission`: SCVs reparando o Bunker durante um rush.

## O que faz

1. Tira o SCV da linha de minério e lhe dá o role `REPAIRING` do Ares, para que a mineração e as construções
   do Ares não o peguem de volta. Quando nenhuma proposta o segura mais, o Engine o libera e o
   [Macro](macro.md) o devolve a `GATHERING`.
2. Escolhe o alvo: nossas estruturas prontas e unidades mecânicas a até `REPAIR_REACH` do ponto, com vida
   abaixo de 100 %, a mais danificada primeiro (empate: a mais perto do ponto, depois a menor tag). Workers
   não entram: dois SCVs se reparando são um loop, não uma defesa.
3. Dá a ordem de reparo uma vez: quem já tem ordem nesse alvo não a recebe de novo.
4. Sem nada danificado, espera a `WAIT_AT` do ponto, que é onde está o ataque.

## Parâmetros

| Parâmetro | Valor | Onde | Efeito |
| --- | --- | --- | --- |
| `REPAIR_REACH` | 6 | repair.py | O que está a essa distância do ponto é reparado |
| `WAIT_AT` | 3 | repair.py | Onde o SCV espera quando não há o que reparar |

## No log

Não tem evento próprio: a proposta aparece em `planner.proposed` e o grant em `engine.granted`.

## Limitações conhecidas

- Todos os SCVs reparam o mesmo alvo, o mais danificado, mesmo que haja outros danificados no alcance.
- O caminho até o ponto não desvia de perigo (`sense_danger=False`).

## Código

- [bot/body/behaviors/repair.py](../../../bot/body/behaviors/repair.py): `execute`, `damaged_near`.
