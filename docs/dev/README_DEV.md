# Desenvolvimento

↑ [README](../../README.md) · [Arquitetura](../architecture.md)

Tudo aqui é sobre **fazer** o bot, não sobre como ele funciona. O funcionamento do HEAD está em
[architecture.md](../architecture.md) e em [planners/](../ego/planners/README_PLANNERS.md).

| Documento                                                | Papel                                                                                                                                  | Muda quando                                                                                                                 |
| -------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| [staging/](staging/README.md)                            | O que está em andamento: objetivo, o que já foi decidido, o que está em aberto, as fatias e como medir                                 | Um item começa, muda de estado ou entra no HEAD                                                                             |
| [backlog.md](backlog.md) | Tudo o que ainda não foi feito, conferido no código, do mais urgente ao menos, com os ids das revisões antigas (P, N, E, C/F/L/I, D) | Quando um item é decidido (vai para o staging), resolvido ou aparece outro |
| [bots-opensource.md](bots-opensource.md)                 | Pesquisa de 03/10: implementações verificadas em bots open source e o que aproveitar (OS1–OS10)                                        | Só com uma nota de estado                                                                                                   |
| [ladder-local.md](ladder-local.md)                       | Pesquisa de 04/10 dos cinco bots locais, com foco no Phantom e late game: evidências, comparação com o backlog e adaptações (LL1–LL12) | Com nova evidência ou uma nota de estado; hashes e símbolos em [ladder-local-evidencias.json](ladder-local-evidencias.json) |
| [migration-map.md](migration-map.md)                     | Modelos matemáticos do branch `matematização`: o que já veio e o que ainda pode vir                                                    | Quando um deles vem                                                                                                         |
| [melhorias.canvas](melhorias.canvas)                     | Para abrir no Obsidian: o ciclo pesquisa → backlog → staging → HEAD num quadro, com as seções dos documentos embutidas                  | Quando uma seção do backlog ou do staging muda de título                                                                    |

As duas pesquisas são datadas, e as linhas citadas nelas são as da época. O backlog é conferido contra o código;
a data da última conferência está no topo dele.

**O imaginado não se liga ao implementado.** Daqui se citam os documentos de `docs/` com link, mas o código só
como texto (`composition.py:199`), sem link. No sentido contrário, `docs/` e `tools/` só entram aqui por este
índice e pelo [staging/](staging/README.md); um id de backlog citado num documento do HEAD fica como texto
("I2 no backlog"). Assim, no grafo do Obsidian, o que estamos imaginando fica numa nuvem à parte, ligada ao
resto por poucas pontes.

**Ciclo de um item.** Um item entra em [staging/](staging/README.md) quando se decide fazê-lo. Quando entra no
HEAD:

- o mecanismo vai para o [architecture.md](../architecture.md) ou para o documento do planner em
  [planners/](../ego/planners/README_PLANNERS.md);
- a medição vai para "Medições" do architecture.md;
- o item sai do staging;
- o item vai para "Já resolvido" no [backlog](backlog.md), e os ids de pesquisa que ele fechou (OS1, LL3…)
  ganham uma nota no documento de origem.
