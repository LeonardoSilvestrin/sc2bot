# Combat

↑ [Body](../README_BODY.md) · [Attack](attack.md) · [Hold](hold.md)

> O que os behaviors de luta compartilham: o siege do Tank, o attack-move, o stim e o tiro no Changeling.

Não é um behavior: nenhum `Command` cai aqui. São as regras que o [Attack](attack.md) e o [Hold](hold.md)
aplicam a cada unidade. O [Garrison](garrison.md) usa o attack-move quando não há Bunker, e o
[Retreat](retreat.md) usa o conjunto de Siege Tanks para desfazer o siege.

## O que decide

- **Quem é inimigo agora** (`present`): o que o frame mostra, sem os snapshots que o Ares lembra fora de visão.
  Uma luta (um stim, ou uma unidade em `HOLD` saindo do caminho) só começa com um inimigo visível.
- **Quem é inimigo de verdade** (`fighting`): tudo menos os Changelings. Nenhuma unidade adquire um
  Changeling sozinha, então ele só leva tiro por ordem direta.
- **Siege** (`maneuver`): um Siege Tank começa a manobra com o `SiegeTankDecision` do Ares, olhando os
  inimigos a até `TANK_SIGHT`, inclusive os lembrados. `stay_sieged` diz se ele fica sentado perto do ponto
  (sim no Hold, não no Attack).
- **Attack-move** (`attack_move`): `AMove` do Ares até o ponto, com chegada a `ATTACK_ARRIVAL`.
- **Stim** (`stim_for`): Marine ou Marauder com a habilidade disponível, sem o buff, com pelo menos
  `STIM_MIN_HEALTH` de vida e um inimigo a até `STIM_RANGE`.
- **Changeling** (`changeling_for`): uma unidade que atira no chão, sem outro inimigo a até
  `ENGAGE_RADIUS`, mira o Changeling mais perto dentro da sua visão.

## Parâmetros

| Parâmetro | Valor | Efeito |
| --- | --- | --- |
| `TANK_SIGHT` | 14 | Até onde o Siege Tank olha para decidir o siege |
| `ATTACK_ARRIVAL` | 2 | A essa distância do ponto, a unidade para e adquire alvo sozinha |
| `STIM_RANGE` | 10 | Distância do inimigo que dispara o stim |
| `STIM_MIN_HEALTH` | 0,5 | Stimar custa vida; abaixo disso não stima |
| `ENGAGE_RADIUS` | 10 | Com outro inimigo a essa distância, a unidade luta com ele e ignora o Changeling |

## Código

- [bot/body/behaviors/combat.py](../../../bot/body/behaviors/combat.py): `present`, `fighting`, `maneuver`,
  `attack_move`, `stim_for`, `changeling_for`.
