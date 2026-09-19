# Em andamento (staging)

O que está sendo feito agora, ou foi decidido e é o próximo. Cada documento dos outros tem um papel fixo:

| Documento | Papel | Muda quando |
| --- | --- | --- |
| [architecture.md](../architecture.md) | O que o código do HEAD faz, os eventos, os comandos e as medições | Uma fatia entra no HEAD |
| **staging/** (este) | O que está em andamento: objetivo, o que já foi decidido, o que está em aberto, as fatias e como medir | Um item começa, muda de estado ou entra no HEAD |
| [propostas.md](../propostas.md), [novas_propostas.md](../novas_propostas.md), [melhorias_propostas_eco.md](../melhorias_propostas_eco.md) | Pesquisa e backlog, com data e commit (P0–P2, N1–N8, E1–E9) | Só com uma nota de estado; o texto é o da revisão |
| [gaps.md](../gaps.md) | Achados de revisão do código (C, F, L, I), com severidade | Quando um achado é resolvido ou aparece outro |
| [migration-map.md](../migration-map.md) | Modelos do branch `matematização` que ainda podem vir | Quando um deles vem |

**Ciclo de um item.** Um item entra aqui quando se decide fazê-lo, com um arquivo próprio se não couber numa
linha. Quando entra no HEAD, o mecanismo vai para o architecture.md, a medição vai para "Medições", o item sai
daqui, e os ids que ele fechou (E3, I6…) ganham uma nota no documento de origem. Um experimento medido e
revertido também sai daqui e fica registrado em "Medido e revertido".

## Agora

Estado em 19 de setembro de 2026, sobre `5f12156` (`botbandido`).

| Item | Estado | Próximo passo | Onde |
| --- | --- | --- | --- |
| **Economia: composição e ordem de builds** | Próximo refactor. Design consolidado, nada implementado | Fechar as decisões em aberto e começar pela fatia 1 | [economia-e-builds.md](economia-e-builds.md) |
| MapControl: anchor `staging` | No HEAD (`5f12156`), controlando; a política `passage` roda em shadow no mesmo evento | Medir o `staging` numa matriz (duas partidas até agora, uma por mapa, não separam nada). Depois: tirar o shadow (`anchor.py`, menos o `reached`) e decidir o `legacy` ([F1](../gaps.md#f1)) | [architecture.md](../architecture.md) (MapControl e Medições) |
| `bench.py --spatial-view --spatial-snapshot` | Na árvore, sem commit | Commitar e pôr em "Comandos" no architecture.md; os SVGs de cada partida vão para `log/spatial/` | `bench.py` |
| `run.py`: dificuldade padrão `CheatInsane` | Na árvore, sem commit | Se ficar, o README ("contra a IA VeryHard Macro") muda junto | `run.py`, [README](../../README.md) |
| `.vscode/launch.json` | Na árvore, sem commit | Configurações locais de debug; nada a documentar | — |

## Depois

Não decidido. É o que os documentos de backlog já apontam como o próximo limite, para não se perder:

- **Fechar o jogo.** Contra Zerg CheatInsane todo jogo sobrevivido é timeout: o grupo não se junta
  (`assembled_share` 0–0,22) e `home_threatened` o chama de volta. É o [I1](../gaps.md#i1) (compromisso medido no
  exército inteiro, severidade alta) e o N7.1 (reforços agrupados).
- **Quem conta como atacante** ([I2](../gaps.md#i2), [I3](../gaps.md#i3)): um worker de scout ou uma estrutura
  estática abre incidente e pode segurar um STABILIZE. O SURVIVE do refactor de economia lê a mesma ameaça, então
  este item fica mais caro depois dele.
- **Limpeza que não muda decisão**, de uma vez: C13, L1–L7, I6, I7, I8 (a ordem sugerida do gaps.md). O I6, o I7
  e o I8 entram no refactor de economia.
