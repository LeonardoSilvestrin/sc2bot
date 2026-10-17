# Regions

↑ [Awareness](README_AWARENESS.md) · [Field](field.md)

> As regiões da [topologia](../attention/topology.md), ranqueadas por presença de creep, controle e ameaça.
> As frentes de creep seguras vêm primeiro.

## O que calcula

`rank_regions(attention, influence)` devolve um `RegionControl` por região:

- `creep`: a fração das amostras do lattice da região com creep, contando também os tumores inimigos à
  vista nela. Tumor que não está à vista é achado pelo grid de creep;
- `threat`: a maior ameaça do [campo](field.md) na região;
- `control`: o controle médio na região;
- `score = creep + control − 2 · threat`;
- `target`: a amostra de creep mais perto da nossa main, não o centro da região. Assim quem limpa descasca a
  frente em vez de atravessá-la para chegar lá. Sem creep, o centro;
- `creep_points`: as amostras com creep, da mais perto para a mais longe da nossa main.

Ordem: maior `score` primeiro, empate pelo id.

## Quem lê

- MapControl (`missions/remove_creep.py`): escolhe a região a limpar. Ver [MapControl](../ego/planners/map-control.md)
  e o behavior [remove-creep](../body/behaviors/remove-creep.md).
- `TUMORS` também é importado pelo behavior e pela missão.

## Limitações conhecidas

- O peso 2 da ameaça no `score` não foi medido.

## Código

- [bot/awareness/regions.py](../../bot/awareness/regions.py): `rank_regions`, `RegionControl`, `TUMORS`.
