# Awareness

↑ [Arquitetura](../architecture.md) · [README](../../README.md)

> O que o bot acredita sobre o mundo além deste frame. Pinta o mapa ao longo da partida em cima do que a
> [Attention](../attention/README_ATTENTION.md) viu. Descreve; não escolhe margem nem prioridade.

`AwarenessModel.infer(attention)` roda uma vez por frame, logo depois de `observe`, e devolve um
`AwarenessState` imutável. É a única camada que lembra o inimigo: a Attention só mostra o que está à vista.

Toda leitura é contínua. Nada tem limiar: a confiança decai com `exp(-idade/τ)`, a ameaça satura com
`S(x) = 1 − exp(−x)` e a opening é lida em rampas.

## Documentos

| Documento | Código | O que é |
| --- | --- | --- |
| [Awareness model](awareness-model.md) | [model.py](../../bot/awareness/model.py) | Memória de contatos, ameaça por base, incidentes, exército visto e produzido, early game |
| [Enemy army](enemy-army.md) | [enemy_army.py](../../bot/awareness/enemy_army.py) | O observador (Kalman) do exército inimigo e da economia que o paga |
| [Field](field.md) | [field.py](../../bot/awareness/field.py) | O kernel, a saturação e o campo de influência no lattice |
| [Regions](regions.md) | [regions.py](../../bot/awareness/regions.py) | Regiões ranqueadas por creep, controle e ameaça |
| [Opening belief](opening-belief.md) | [opening/](../../bot/awareness/opening/__init__.py) | A leitura da abertura inimiga: `aggression`, `greed`, `tech`, `proxy` e `confidence` |

## Quem lê

| Leitor | O que lê |
| --- | --- |
| [Strategy](../ego/strategy.md) | `danger`, `danger_now`, `own_power`, o poder inimigo conhecido, visto vivo e estimado (o observador) |
| [Defense](../ego/planners/defense.md) | `incidents`, `early_game`, `opening` (a leitura de rush) |
| [MapControl](../ego/planners/map-control.md) | `influence` (o staging) e `regions` (a remoção de creep) |
| [Intel](../ego/planners/intel.md) | `opening` (proxy, fim da ronda), `hidden_contacts` e `cloak_seen_at` (detecção) |
| [Economy](../ego/economy.md) | o observador, `seen_enemy_types`, `produced_enemy_types`, `contacts`, `incidents` |
| Logs | tudo: `awareness.updated`, `awareness.opening_updated`, os SVG do campo e o chat |

O StructureControl não lê a Awareness.

## Código

- [bot/awareness/\_\_init\_\_.py](../../bot/awareness/__init__.py): reexporta `AwarenessModel`,
  `AwarenessState` e os tipos públicos.
