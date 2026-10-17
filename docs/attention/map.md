# Map

↑ [Attention](README_ATTENTION.md)

> O mapa físico, lido uma vez no `on_start` e congelado: "o mapa é assim".

## O que lê

`read_map(bot, lattice_spacing=4)` devolve um `MapView` com:

| Campo | O que é |
| --- | --- |
| `bounds` | A área jogável |
| `own_start`, `enemy_start`, `main_ramp` | Os starts e o topo da rampa da nossa main |
| `expansions` | Todas as expansões, em ordem de (x, y) |
| `lattice`, `lattice_spacing` | Os centros de célula andáveis a cada 4 células, em ordem de linha. Toda leitura espacial da Awareness é feita nesses pontos |
| `topology` | A [MapTopology](topology.md) |
| `production_sites` | Os sites 3x3 com espaço para add-on que o placement do Ares resolveu na nossa main, sem o wall da rampa |
| `base_production_sites` | Os mesmos sites 3x3, por expansão |
| `tower_sites` | Os spots 2x2 do Ares por expansão, sem o wall; é onde a barreira de Sensor Towers do Intel pode ir |
| `bunker_sites` | O spot 3x3 que o Ares resolveu para um Bunker na frente da nossa natural |
| `own_expansion_order`, `enemy_expansion_order` | As expansões que o Ares ordenou pela distância por terra a partir de cada start |

E responde:

- `own_natural`, `enemy_natural` e `enemy_third`: a n-ésima expansão a partir de um start, pela ordem do Ares.
  Sem ela, usa a distância em linha reta.
- `region_at(ponto)`: a região da topologia onde fica o ponto.
- `route_to` e `reachable_now`: rota e alcance pelas passagens abertas **agora**.

## O que não é estático

Os mineral walls e as rocks fazem parte do mapa, mas caem durante a partida. `read_blockers` lista os
neutros que podem ser removidos e que, enquanto estão de pé, fecham uma passagem. Ficam de fora os
decorativos (placas, zonas de aceleração e de limpeza), que o MapAnalyzer também ignora. A identidade do mapa
não muda: `enemy_natural` nomeia o mesmo chão a partida inteira. Quem acompanha a abertura das passagens é o
[Passages](passages.md).

## Quem lê

| Campo | Quem lê |
| --- | --- |
| `production_sites`, `base_production_sites` | StructureControl (relocation e `keep_clear` do corredor da rampa) e o log `planner.production_kept_clear` |
| `tower_sites` | Intel (`policies/sensor_towers.py`) |
| `bunker_sites` | Defense (`policies/rush.py`) |
| `route_to` | MapControl (`missions/remove_creep.py`) |
| `reachable_now` | Intel (`policies/proxy.py`) |

## Parâmetros

| Parâmetro | Valor | Efeito |
| --- | --- | --- |
| `lattice_spacing` | 4 | Distância entre os pontos do lattice, em células |
| `EXPANSION_GAP` | 15 | Uma expansão a essa distância de um start é o próprio start (o mesmo corte do python-sc2) |
| `BASE_SNAP_DISTANCE` | 6 | Até onde um townhall é associado a uma expansão |

## No log

`game.started` traz o `lattice` e os `bounds`; a topologia sai em `map.topology_built`.

## Código

- [bot/attention/map.py](../../bot/attention/map.py): `MapView`, `read_map`, `read_blockers`,
  `pathable_lattice`.
