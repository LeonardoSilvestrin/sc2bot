# Field

↑ [Awareness](README_AWARENESS.md) · [Awareness model](awareness-model.md)

> A matemática que toda leitura espacial da Awareness compartilha, e o campo de influência em cada ponto do
> lattice.

## Kernel e saturação

- `K(d, σ) = exp(-½ · d² / σ²)` espalha uma fonte pelo mapa de forma suave.
- `S(x) = 1 − exp(−x)` satura o que várias fontes somam, então toda leitura fica contínua e dentro de [0, 1).
- `accumulate` soma `força · K(d, σ)` em cada ponto, antes da saturação. Uma fonte pode ter alcance
  (`reach`); fora dele não conta.

A incerteza de posição alarga a ameaça **possível** de uma fonte, mas nunca cria presença confirmada.

## O campo de influência

`InfluenceField` tem uma leitura por ponto do [lattice](../attention/map.md), com σ = `field_sigma` (7) e
força em unidades de `full_pressure`:

| Leitura | Fontes | Alargada pela incerteza? |
| --- | --- | --- |
| `threat` | contatos de exército, `poder · confiança` | Sim (`σ + incerteza`): presença possível |
| `enemy` | os mesmos contatos, mais as estruturas inimigas (`structure_presence · confiança`) | Não: presença crível |
| `support` | nosso exército (`poder`) e nossas estruturas (`structure_presence`) | — |
| `control` | `support − enemy` | — |

`summary` conta os pontos amigos, disputados e inimigos (`|control|` dentro de `CONTROL_BAND`, 0,15, é
disputado), os ameaçados e a ameaça máxima, entre os pontos com presença acima de `PRESENCE_FLOOR` (0,05).

## Quem lê

- MapControl: o staging pontua candidatos por ameaça, suporte e controle; a missão de remover creep evita
  ameaça.
- [Regions](regions.md): ameaça e controle por região.
- Logs: o resumo em `awareness.updated`, as bolinhas in-game (`--spatial-view`) e os SVG
  (`--spatial-snapshot`).

## Código

- [bot/awareness/field.py](../../bot/awareness/field.py): `kernel`, `saturate`, `accumulate`, `Source`,
  `InfluenceField`, `build_field`.
- [bot/awareness/model.py](../../bot/awareness/model.py): `AwarenessModel._field` monta as fontes.
