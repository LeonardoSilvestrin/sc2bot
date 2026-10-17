# Attention

↑ [Arquitetura](../architecture.md) · [README](../../README.md)

> Percepção: o que o jogo mostra, antes de qualquer interpretação. Não diz quem controla um lugar nem quão
> perigoso ele é; isso é da [Awareness](../awareness/README_AWARENESS.md).

A Attention lê o jogo de duas formas:

- **O mapa, uma vez.** No `on_start`, `read_map` devolve um `MapView` congelado, com a `MapTopology` (regiões,
  passagens, adjacência) e os sites de construção que o placement do Ares resolveu.
- **O frame, a cada passo.** `observe` devolve um `AttentionState` imutável, e daí em diante nenhuma camada
  lê o `bot`: todas leem esse estado.

Dois registros atravessam frames e continuam sendo percepção, porque um fato observado continua fato:

- `OpeningWatch` guarda o que o early game mostrou da abertura inimiga, e quando mostrou.
- `PassageWatch` acompanha a única coisa do mapa que muda: se uma passagem fechada por mineral wall ou rocks
  já abriu.

## No frame

`play_frame` ([main.py](../../bot/main.py)) começa por aqui:

```text
map_view, opened = passages.refresh(bot, map_view)     só troca o MapView quando uma passagem muda
attention        = observe(bot, iteration, map_view, opening)
```

## Documentos

| Documento | Código | O que é |
| --- | --- | --- |
| [Map](map.md) | [map.py](../../bot/attention/map.py) | `read_map` e `MapView`: área, starts, rampa, expansões, lattice, sites de construção |
| [Topology](topology.md) | [topology.py](../../bot/attention/topology.py) | `MapTopology`: regiões, passagens, adjacência e rotas, construída uma vez |
| [Passages](passages.md) | [passages.py](../../bot/attention/passages.py) | `PassageWatch`: passagens fechadas por blockers que abrem durante a partida |
| [Frame](frame.md) | [frame.py](../../bot/attention/frame.py) | `observe` e `AttentionState`: o que este frame mostra |
| [Units](units.md) | [units.py](../../bot/attention/units.py) | `UnitView`, `unit_power` e `is_army`: o que uma unidade é e quanto vale em Marines |
| [Opening watch](opening-watch.md) | [opening.py](../../bot/attention/opening.py) | `OpeningWatch` e `OpeningObservations`: os fatos da abertura inimiga até 300 s |

O pacote reexporta tudo isso em [\_\_init\_\_.py](../../bot/attention/__init__.py).

## Quem lê

Todos. A Awareness, a Strategy, todos os planners, a Economy, o Engine, os behaviors e os logs recebem o
mesmo `AttentionState`.
