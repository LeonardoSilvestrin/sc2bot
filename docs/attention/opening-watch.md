# Opening watch

↑ [Attention](README_ATTENTION.md) · [Frame](frame.md)

> O registro do que o early game mostrou da abertura inimiga, e quando. São fatos; o que eles significam é
> lido na [Opening belief](../awareness/opening-belief.md) da Awareness.

## O que registra

`OpeningWatch.observe` dobra cada frame num único `OpeningObservations`:

- **Natural e third** (`ExpansionObservation`): `UNKNOWN` (ninguém olhou), `ABSENT_CONFIRMED` (olhamos e não
  havia nada) ou `PRESENT` (há um townhall), com `last_checked_at`, `first_seen_at`, `absent_at` e
  `appeared_between` (vista vazia, depois vista de pé). Uma ausência só é registrada para um ponto que estava
  em visão no frame.
- **Estruturas** por tipo (`StructureObservation`): contagem, primeiro e último avistamento. Cada tag conta
  uma vez.
- `gases_seen`, `workers_seen`, `early_combat_units_seen`.
- `proxy_structures_seen`: estruturas inimigas vistas na nossa metade do mapa.
- `main_scout_coverage`: a fração das amostras do lattice da main inimiga que já esteve em visão.
- `enemy_race` e `last_updated`.

Até `OPENING_WINDOW` (300 s). Depois a abertura acabou, e o registro congela como estava.

## Quem lê

- Awareness: `read_opening` transforma o registro na [Opening belief](../awareness/opening-belief.md).
- Intel (`missions/early_scout.py`): as fases do scout leem o que ele pôs à vista. A missão não registra
  nada: o que ela vê, a Attention grava.

## No log

- `opening_scout.expansion_checked`: o estado da natural ou da third muda.
- `opening_scout.structure_seen`: mais uma estrutura de um tipo é vista no early game.

## Código

- [bot/attention/opening.py](../../bot/attention/opening.py): `OpeningWatch`, `OpeningObservations`,
  `ExpansionObservation`, `StructureObservation`, `OPENING_WINDOW`.
