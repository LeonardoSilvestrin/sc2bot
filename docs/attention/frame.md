# Frame

↑ [Attention](README_ATTENTION.md)

> `observe` lê o Ares/python-sc2 uma vez por frame e devolve um `AttentionState` imutável. Toda camada
> seguinte lê esse estado em vez do `bot`.

## O que o `AttentionState` traz

| Grupo | Campos |
| --- | --- |
| Recursos | `minerals`, `vespene`, `supply_used`, `supply_cap`, `workers` (a contagem do jogo, como o `BuildWorkers` do Ares: um worker dentro de um gás some de `bot.units`, e contar a lista oscilaria) |
| Abertura própria | `opening` (a escolhida pelo build runner do Ares) e `opening_done` |
| Unidades | `own_units`, `own_structures`, `enemy_units`, `enemy_structures`, como [UnitView](units.md), ordenadas por tag |
| Bases | `bases` (`BaseView`: id, posição, se é a main), cada townhall associado a uma expansão do [Map](map.md) |
| Mortes | `dead_tags` do frame |
| Grids | `visibility` e `creep` (`has_creep`, `is_visible`) |
| Tech | `upgrades` concluídos e `tech_ready` (as unidades Terran cujo pré-requisito de tech já está pronto) |
| Inimigo | `enemy_race` (um Random continua Random até a primeira unidade aparecer), `enemy_opening` (o [Opening watch](opening-watch.md)) e `radar_blips` (contatos das nossas Sensor Towers fora de visão: só a posição) |
| Construção | `available_tower_sites`: os spots de torre do Map que ainda estão livres |
| Mapa | `map`, o `MapView` do frame |

**Só o que está à vista.** O Ares mistura em `enemy_units` os snapshots de até 30 s de inimigos fora de
visão. `observe` os tira: lembrar é papel da Awareness.

## Quem lê

Todo mundo. Dos campos menos óbvios:

| Campo | Quem lê |
| --- | --- |
| `creep` | MapControl (`missions/remove_creep.py`) e [regions](../awareness/regions.md) |
| `cargo_used` / `cargo_max` | Defense (`missions/rush_defense.py`) e o behavior [garrison](../body/behaviors/garrison.md) |
| `moving_to` | StructureControl (relocation) |
| `tech_ready` | Economy e o behavior [macro](../body/behaviors/macro.md) |
| `available_tower_sites` | Intel (`policies/sensor_towers.py`) |
| `radar_blips` | Só o log (`attention.observed`) |

## No log

`attention.observed`, quando bases, o fim do opening, os inimigos à vista ou os contatos de radar mudam,
com amostra a cada 5 s.

## Limitações conhecidas

- Os contatos de radar (`radar_blips`) não entram na Awareness: a barreira de Sensor Towers do Intel é
  construída, mas o que ela vê só aparece no log.

## Código

- [bot/attention/frame.py](../../bot/attention/frame.py): `observe`, `AttentionState`, `BaseView`.
