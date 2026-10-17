# Topology

↑ [Attention](README_ATTENTION.md) · [Map](map.md)

> As regiões e passagens do mapa, construídas uma vez a partir do MapAnalyzer do Ares e alinhadas ao
> lattice. A identidade é estática; só o estado de cada passagem muda.

## O que constrói

`build_topology` copia do MapAnalyzer só as regiões e as passagens, como valores pequenos e
determinísticos:

- **`MapRegion`**: id, centro, os índices do lattice que caem nela e as expansões que contém. Uma região
  do MapAnalyzer cortada por chokes que ficam inteiros dentro dela vira sub-regiões (`RegionSplit`). Um
  pedaço com menos chão que o choke que o toca é um recorte do terreno e não vira região.
- **`MapPassage`**: uma ligação por terra entre duas ou mais regiões. Pode ser `choke`, um choke geométrico
  do MapAnalyzer, ou `border`, uma fronteira limpa do lattice onde o MapAnalyzer não viu choke (nesse caso
  a largura fica desconhecida). Chokes que o MapAnalyzer dá como faixas paralelas de uma célula, ligando as
  mesmas regiões, viram uma passagem só.
- **Adjacência**, a região de cada expansão e as regiões dos dois starts.

O `pathing_grid` do jogo já conta mineral wall e rocks como chão andável, então **toda passagem que o mapa
pode ter existe desde o primeiro frame**, com o mesmo id e entre as mesmas regiões. Um blocker só decide o
`state`:

- um grupo de blockers que se tocam (um mineral wall são 15 patches) fica numa passagem quando, carimbado
  no grid, separa os dois lados dela dentro de uma janela de `BLOCKER_WINDOW` (16) células;
- a passagem selada nasce `CLOSED`, com `blocker_type` (`mineral_wall`, `destructible` ou `mixed`) e
  `blocker_tags`.

`ChokeCandidate` guarda o que a topologia fez de cada choke do MapAnalyzer: aceito (`between_regions`,
`splits_region`) ou o motivo da recusa. Serve só para debug.

## Consultas

- `open_passages()`, `closed_passages()`, `blocked_passages()`.
- `neighbours(região, open_only=True)` e `open_adjacency()`.
- `connected_regions`, `route` e `reachable`: conectividade pelas passagens abertas.
- `with_passage_states(...)`: a mesma topologia com outros estados. É o que o [Passages](passages.md) usa.

Um estado `UNKNOWN` nunca conta como caminho.

## Quem lê

- MapControl (`policies/staging.py`): distâncias, candidatos e proteção das bases, só por passagens abertas.
- Intel: as saídas da main inimiga e as rotas de busca de proxy.
- Awareness ([regions](../awareness/regions.md)): regiões e as amostras do lattice em cada uma.

## No log

`map.topology_built` (`on_start`): `regions`, `passages`, `chokes`, `blocked_passages[]`, `expansions`,
`unresolved_expansions`, `own_start_region`, `enemy_start_region`.

## Código

- [bot/attention/topology.py](../../bot/attention/topology.py): `MapTopology`, `MapRegion`, `MapPassage`,
  `MapBlocker`, `build_topology`.
