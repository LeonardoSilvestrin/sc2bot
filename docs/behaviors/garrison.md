# Garrison

↑ [Defense](../planners/defense.md)

> O que o Body faz com as unidades de um `GARRISON`: entrar no Bunker do ponto.

## Quem chama

**Defense**, na `RushDefenseMission`: Marines para o Bunker da natural durante um rush.

## O que faz

1. Procura o Bunker: o nosso mais perto do ponto, a até `BUNKER_REACH`, pronto e com vaga
   (`cargo_left > 0`). No empate, a menor tag.
2. Com Bunker, cada unidade recebe a ordem de entrar (`SMART` no Bunker) **uma vez**: quem já tem uma ordem
   com esse alvo é deixado em paz.
3. Sem Bunker (morreu, ainda não ficou pronto ou as unidades mais perto já o encheram), a unidade faz
   attack-move até o ponto e luta lá, com o attack-move do [combat](combat.md).

## Parâmetros

| Parâmetro | Valor | Onde | Efeito |
| --- | --- | --- | --- |
| `BUNKER_REACH` | 4 | garrison.py | Até onde do ponto o Bunker é procurado |

## No log

Não tem evento próprio: a proposta aparece em `planner.proposed` e o grant em `engine.granted`. Quem está
dentro do Bunker não aparece em lugar nenhum além de `cargo_used`.

## Limitações conhecidas

- Sem Bunker, a unidade luta no ponto sem stim e sem as outras reações do [Attack](attack.md).

## Código

- [bot/body/behaviors/garrison.py](../../bot/body/behaviors/garrison.py): `execute`, `find_bunker`,
  `ordered_onto`.
