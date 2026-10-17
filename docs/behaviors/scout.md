# Scout

↑ [Intel](../planners/intel.md)

> O que o Body faz com as unidades de um `SCOUT`: ir até o ponto e olhar.

## Quem chama

**Intel**, na `EarlyScoutMission`: o worker que vai ver a base inimiga, ponto a ponto da rota do planner.

## O que faz

1. Um worker sai da linha de minério. Qualquer unidade recebe o role `SCOUTING` do Ares, para que a mineração
   e as construções do Ares não a peguem de volta. Quando é liberado, o worker volta a `GATHERING` pelo
   [Macro](macro.md).
2. Anda até o ponto pelo grid do Ares (terrestre ou aéreo) e chega a `SCOUT_ARRIVAL` dele, **sem desviar de
   perigo**: para o grid do Ares os workers inimigos são perigo, e um scout que se afasta deles nunca vê a linha
   de minério.

## Parâmetros

| Parâmetro | Valor | Onde | Efeito |
| --- | --- | --- | --- |
| `SCOUT_ARRIVAL` | 3 | scout.py | A essa distância do ponto, o scout chegou |

## No log

Não tem evento próprio: a rota e as fases saem nos eventos do Intel e em `mission.updated`.

## Limitações conhecidas

- Sem desvio de perigo, o scout não foge de unidades de combate: só a missão o tira de lá.

## Código

- [bot/body/behaviors/scout.py](../../bot/body/behaviors/scout.py): `execute`.
