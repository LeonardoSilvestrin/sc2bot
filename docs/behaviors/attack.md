# Attack

↑ [Defense](../planners/defense.md) · [Offense](../planners/offense.md)

> O que o Body faz com as unidades de um `ATTACK`: lutar no ponto.

## Quem chama

- **Defense**: a `DefendAreaMission` de cada incidente (`defense:<incidente>:air` e `…:ground`), com o centro
  do incidente como ponto, e a política de Changelings (`defense:changeling:<tag>`), com o ponto onde ele está.
- **Offense**: a `MainAttackMission` ao avançar e lutar, com o alvo do ataque ou o centro dos inimigos.

O Engine entrega as unidades concedidas e o Body despacha pelo `Command` (`BY_COMMAND`), sem saber quem pediu.

## O que faz

Cada unidade concedida monta uma `CombatManeuver` do Ares, nesta ordem:

1. **Siege Tank**: `SiegeTankDecision` contra os inimigos a até `TANK_SIGHT`, sem ficar preso ao ponto
   (`stay_sieged=False`). Conta também os inimigos que o Ares lembra fora de visão.
2. **Stim**: Marine ou Marauder com um inimigo de verdade (visível agora, sem Changeling e sem worker) a até
   `STIM_RANGE`, com pelo menos `STIM_MIN_HEALTH` de vida, sem o buff e com a habilidade disponível.
3. **Changeling**: sem nenhum outro inimigo a até `ENGAGE_RADIUS`, atira no Changeling mais perto dentro da
   visão. Um attack-move passa por ele sem atirar.
4. **Attack-move** até o ponto, parando a `ATTACK_ARRIVAL` dele. O **Medivac** vai, em vez disso, ao centro
   das outras unidades concedidas (cura no caminho e não voa à frente do grupo). Sozinho, vai ao ponto.

As regras de 1 a 3 vêm do [combat](combat.md), que o [Hold](hold.md) também usa.

## Parâmetros

| Parâmetro | Valor | Onde | Efeito |
| --- | --- | --- | --- |
| `STIM_RANGE` | 10 | combat.py | Distância do inimigo que dispara o stim |
| `STIM_MIN_HEALTH` | 0,5 | combat.py | Fração mínima de vida para stimar |
| `ENGAGE_RADIUS` | 10 | combat.py | Com outro inimigo a essa distância, o Changeling é ignorado |
| `TANK_SIGHT` | 14 | combat.py | Até onde o Siege Tank olha para decidir o siege |
| `ATTACK_ARRIVAL` | 2 | combat.py | A essa distância do ponto, a unidade para e adquire alvo sozinha |
| `ESCORTS` | Medivac | attack.py | Quem segue o grupo em vez do ponto |

## No log

`behavior.micro_executed`, com `stimmed` (tags que stimaram neste frame) e `escorts` (Medivacs seguindo o
grupo). Sai quando alguém stima ou quando o conjunto de escoltas muda.

## Limitações conhecidas

- Todas as unidades recebem o mesmo ponto. Não há foco de alvo, kiting nem formação: quem escolhe o alvo é o
  attack-move do jogo.
- O Medivac segue o centro das unidades concedidas a esta proposta, não o das que estão de fato lutando.

## Código

- [bot/body/behaviors/attack.py](../../bot/body/behaviors/attack.py): `execute`, `MicroReport`, `group_center`.
