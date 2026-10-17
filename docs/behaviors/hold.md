# Hold

↑ [MapControl](../planners/map-control.md)

> O que o Body faz com as unidades de um `HOLD`: segurar o ponto e lutar com o que vier.

## Quem chama

**MapControl**, com o anchor como ponto: é o exército que ninguém mais está usando, esperando no lugar que o
planner escolheu.

## O que faz

Para cada unidade concedida, numa `CombatManeuver` do Ares:

1. **Siege Tank**: `SiegeTankDecision`, ficando sentado perto do ponto (`stay_sieged=True`).
2. **Changeling**: sem outro inimigo a até `ENGAGE_RADIUS`, atira no Changeling mais perto que vê, onde quer
   que esteja.
3. **Luta**: com um inimigo de verdade (visível agora, sem Changeling) a até `ENGAGE_RADIUS`, faz
   attack-move até o ponto, e o bio stima como no [Attack](attack.md).
4. **Caminho**: sem ninguém por perto, anda até o ponto pelo grid do Ares (terrestre ou aéreo) e para a
   `HOLD_RADIUS` dele, **sem desviar de perigo** (`sense_danger=False`).

As regras de siege, stim e Changeling são as do [combat](combat.md).

## Parâmetros

| Parâmetro | Valor | Onde | Efeito |
| --- | --- | --- | --- |
| `HOLD_RADIUS` | 4 | hold.py | A essa distância do ponto, a unidade para de andar |
| `ENGAGE_RADIUS` | 10 | combat.py | Inimigo a essa distância faz a unidade lutar |

## No log

Os stims entram em `behavior.micro_executed` (`stimmed`), junto com os do Attack.

## Limitações conhecidas

- No caminho até o ponto a unidade não desvia de perigo: passa pelo meio de quem estiver na rota e só reage
  quando alguém chega a `ENGAGE_RADIUS` dela.
- A luta é um attack-move até o próprio ponto, não até o inimigo: quem está além do ponto não é perseguido.

## Código

- [bot/body/behaviors/hold.py](../../bot/body/behaviors/hold.py): `execute`, `HOLD_RADIUS`.
