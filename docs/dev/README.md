# Desenvolvimento

Tudo aqui é sobre **fazer** o bot, não sobre como ele funciona. O funcionamento do HEAD está em
[architecture.md](../architecture.md) e em [planners/](../planners/README.md).

| Documento | Papel | Muda quando |
| --- | --- | --- |
| [staging/](staging/README.md) | O que está em andamento: objetivo, o que já foi decidido, o que está em aberto, as fatias e como medir | Um item começa, muda de estado ou entra no HEAD |
| [agent_discussion/](agent_discussion/README.md) | Debate de 04/10 entre dois agentes (defensor e crítico) sobre o HEAD `c7c336d`: fatos aceitos, divergências e um plano unificado | Não muda: é o registro do debate |
| [bots-opensource.md](bots-opensource.md) | Pesquisa de 03/10: implementações verificadas em bots open source e o que aproveitar (OS1–OS10) | Só com uma nota de estado |
| [propostas.md](propostas.md) | O que aprender de outros bots (Ares, PiG, Sajuuk, Sharky, MicroMachine, Sharpy) e o roadmap P0–P2 | Só com uma nota de estado |
| [novas_propostas.md](novas_propostas.md) | Revisão de 18/09: benchmark, builds, Strategy, informação, micro, ofensiva (N1–N8) | Só com uma nota de estado |
| [melhorias_propostas_eco.md](melhorias_propostas_eco.md) | Revisão de 18/09 da economia e da composição (E1–E9) | Só com uma nota de estado |
| [gaps.md](gaps.md) | Achados de revisão do código (C, F, L, I), com severidade | Quando um achado é resolvido ou aparece outro |
| [migration-map.md](migration-map.md) | Modelos matemáticos do branch `matematização`: o que já veio e o que ainda pode vir | Quando um deles vem |

Os documentos de pesquisa, revisão e backlog são datados. Os links para o código neles apontam para o
código da época, e alguns arquivos foram renomeados ou movidos depois.

**Ciclo de um item.** Um item entra em [staging/](staging/README.md) quando se decide fazê-lo. Quando entra no
HEAD:

- o mecanismo vai para o [architecture.md](../architecture.md) ou para o documento do planner em
  [planners/](../planners/README.md);
- a medição vai para "Medições" do architecture.md;
- o item sai do staging;
- os ids que ele fechou (E3, I6, OS1…) ganham uma nota no documento de origem.
