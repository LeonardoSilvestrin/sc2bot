# Remove creep

↑ [MapControl](../planners/map-control.md)

> O que o Body faz com o squad de um `REMOVE_CREEP`: limpar tumores com Raven e escolta, fugindo de luta.

## Quem chama

**MapControl**, na missão `remove_creep` (só contra Zerg). Diferente dos outros comandos, o Body junta todas
as partes concedidas ao mesmo `mission_id` (Raven e escolta vêm em propostas separadas) e executa o squad
inteiro de uma vez.

## O que faz

Os parâmetros vêm de `proposal.inputs`: a missão põe os de `MapControlConfig.remove_creep` e diz se está na
fase `CLEAR` (`clear`). O `fallback` é o anchor.

1. **Perigo**: inimigo visível (unidade ou estrutura, sem os lembrados e sem tumores) que ataca chão ou ar a
   até `danger_distance` de qualquer membro faz **todos** fugirem, mesmo com tumor ao alcance. A fuga vai para
   o `fallback`; se o inimigo está entre o squad e o fallback, primeiro foge na direção oposta a
   ele, presa à área jogável.
2. **Pronto para sair**: há Raven e pelo menos `minimum_escort` escoltas (Marine ou Hellion); com Marines, é
   preciso também um Medivac. Sem isso, o squad espera no fallback.
3. **Coesão**: pronto, mas com alguém a mais de `cohesion` do Raven, o squad se reagrupa na escolta (um Raven
   rápido nunca vai na frente sozinho).
4. **Limpeza**: pronto e sem perigo, o squad vai ao tumor visível e detectado mais perto do Raven, entre os que
   estão a até 12 do ponto. Uma escolta com um tumor no alcance de arma, a até 10 de um Raven (que o
   detecta), ataca o tumor. O Medivac cura o Marine mais ferido a até 4.
5. **Movimento**: quem não atacou nem curou anda pelo grid do Ares **com** desvio de perigo
   (`sense_danger=True`, `danger_distance`).

## Parâmetros

| Parâmetro | Padrão | Efeito |
| --- | --- | --- |
| `danger_distance` | 15 | Inimigo a essa distância de qualquer membro faz o squad fugir |
| `cohesion` | 8 | Distância máxima ao Raven antes de reagrupar |
| `minimum_escort` | 2 | Escoltas mínimas para sair |
| `clear` | 1 na fase `CLEAR` | Com 0 (`ASSEMBLE`, `RETREAT`, `WAIT`), o squad anda mas não vai atrás de tumores |

## No log

Não tem evento próprio: as fases da missão saem em `mission.updated`, o pedido do Raven em
`planner.economy_planned.unit_requests` e as unidades em `engine.granted`.

## Limitações conhecidas

- Só ataca tumores já visíveis e detectados: não pede scan para revelá-los.
- Os raios de busca de tumor (12), de detecção pelo Raven (10) e de cura (4) estão fixos no código, fora do
  `MapControlConfig`.

## Código

- [bot/body/behaviors/remove_creep.py](../../bot/body/behaviors/remove_creep.py): `execute`.
