# Retreat

↑ [Offense](../planners/offense.md)

> O que o Body faz com as unidades de um `RETREAT`: voltar ao ponto sem lutar.

## Quem chama

**Offense**, nas fases `RETREAT` e `WITHDRAW` da `MainAttackMission`: o ponto é o rally, para onde o exército
volta.

## O que faz

Para cada unidade concedida:

1. **Siege Tank** sentado desfaz o siege primeiro (`SiegeTankDecision` com `force_unsiege=True`).
2. Anda até o ponto pelo grid do Ares (terrestre ou aéreo) e para a `HOLD_RADIUS` dele. Não ataca no caminho e
   não desvia de perigo (`sense_danger=False`).

## Parâmetros

| Parâmetro | Valor | Onde | Efeito |
| --- | --- | --- | --- |
| `HOLD_RADIUS` | 4 | hold.py | A essa distância do ponto, a unidade para |

## No log

Não tem evento próprio. A decisão de recuar aparece nos eventos da Offense, e quem recebeu as unidades em
`engine.granted`.

## Limitações conhecidas

- Não desvia de perigo: um recuo cuja rota passa pelo inimigo atravessa o inimigo sem atirar.
- Não há cobertura (Tanks ou bio segurando enquanto o resto sai): todos andam ao mesmo tempo.

## Código

- [bot/body/behaviors/retreat.py](../../bot/body/behaviors/retreat.py): `execute`. Usa `TANKS` do
  [combat](combat.md).
