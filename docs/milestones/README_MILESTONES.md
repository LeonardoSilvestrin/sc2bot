# Marcos

↑ [README](../../README.md) · [Arquitetura](../architecture.md)

Tudo aqui é sobre **fazer** o bot, não sobre como ele funciona. O funcionamento do HEAD está em
[architecture.md](../architecture.md) e nas pastas de cada camada ([Ego](../ego/README_EGO.md),
[Body](../body/README_BODY.md)…).

O trabalho está dividido em **marcos**: etapas de melhoria, cada uma com um objetivo, um critério de saída
medido e o que ela pede dos marcos anteriores. Um marco junta o que está em andamento e o que falta fazer
naquele assunto; os itens dentro dele vão do mais urgente ao menos. Conferido no código em 17/10/2026.

## Onde o bot está

O veredito do debate de 04/10 continua valendo: **a parte que decide é boa; quem perde jogo é o resto.** O pipeline
é acíclico, o Engine é o único dono das unidades, a telemetria é auditável e o frame leva de 6,5 a 9,8 ms. O que
perde jogo: um crash contra Terran, um DEFEND que dispara diante de cobertura de sobra, casters valendo poder zero,
micro de a-move e um exército que não fecha o jogo (13 a 16 mil minerais no banco com supply máximo). As maiores
mudanças desde então (posturas, observador, composição, resposta a rush) entraram sem bench. Por isso os marcos
começam por não perder por crash e por medir.

## Os marcos

| Marco | Objetivo | Critério de saída | Depende de |
| --- | --- | --- | --- |
| [M1 — Estabilidade](m1-estabilidade.md) | Nenhuma partida perdida por crash | Terran CheatInsane, 3 seeds, 0 crash; um planner que falha não derruba o frame | — |
| [M2 — Medição](m2-medicao.md) | Um bench da planta atual e um veredito para tudo que entrou sem bench | ≥ 18 partidas decididas por raça, Wilson por raça; cada item sem bench fica ou é revertido | M1 |
| [M3 — Ameaça e defesa](m3-ameaca-e-defesa.md) | DEFEND só quando a defesa local não dá conta | Nenhum DEFEND com cobertura/pressão ≥ 3 | M2 |
| [M4 — Poder e estimativa](m4-poder-e-estimativa.md) | Um modelo de poder só, com casters, alcance e upgrades; observador consistente | Casters com poder > 0; NEES entre 0,5 e 2, ≥ 85 % em 2σ | M2 |
| [M5 — Fechar o jogo](m5-fechar-o-jogo.md) | O exército chega junto, luta bem e termina a partida | `assembled_share` mediano > 0,6; banco < 5 mil no supply máximo; troca ≥ 1 em ENGAGE | M3, M4 |
| [M6 — Intel](m6-intel.md) | Informação de meio de jogo, não só a do scout inicial | A fixar quando o marco começar | M2 |
| [M7 — Economia](m7-economia.md) | O gasto segue o mix e o recurso que falta, decidido no Ego | A fixar com o E2: o que explica o banco | M2, M6 |
| [M8 — Sinais, topologia e limpeza](m8-sinais-e-limpeza.md) | Todo sinal com leitor, nada degradando em silêncio | Todo campo do `StrategicIntent` com leitor fora dos logs | — |

**Agora:** M1 e o M2. O bench do M2 destrava a avaliação de quase todo o resto.

**Depois dos marcos (não decidido):** estilo de exército adaptativo entre partidas, como bandit por oponente
(Thompson sampling), com os resultados guardados entre partidas no ladder. Vem da
[virada para estimação e controle](registros/estimacao-e-controle.md).

## Pesquisa e registros

| Documento | Papel | Muda quando |
| --- | --- | --- |
| [pesquisa/bots-opensource.md](pesquisa/bots-opensource.md) | Pesquisa de 03/10: implementações verificadas em bots open source e o que aproveitar (OS1–OS10) | Só com uma nota de estado |
| [pesquisa/ladder-local.md](pesquisa/ladder-local.md) | Pesquisa de 04/10 dos cinco bots locais, com foco no Phantom e late game (LL1–LL12); hashes e símbolos em [ladder-local-evidencias.json](pesquisa/ladder-local-evidencias.json) | Com nova evidência ou uma nota de estado |
| [pesquisa/migration-map.md](pesquisa/migration-map.md) | Modelos matemáticos do branch `matematização`: o que já veio e o que ainda pode vir | Quando um deles vem |
| [registros/economia-e-builds.md](registros/economia-e-builds.md) | Design de 19/09 da economia (estilo, composição, SURVIVE, ordem de builds) e as decisões tomadas | Não muda; o que falta está no [M7](m7-economia.md) |
| [registros/estimacao-e-controle.md](registros/estimacao-e-controle.md) | A virada de 03/10 para estimação e controle: regras, observador, composição por eficácia | Com uma medição nova do observador |
| [milestones.canvas](milestones.canvas) | Para abrir no Obsidian: pesquisa → marcos → HEAD num quadro, com os documentos embutidos | Quando um marco entra ou sai |

As pesquisas são datadas, e as linhas citadas nelas são as da época. Os ids delas (OS, LL) são citados nos marcos
que os absorvem.

## Ids antigos

Os marcos juntam cinco revisões antigas, que saíram da árvore em 17/10. Os ids entre colchetes nos marcos são delas,
para quem quiser o raciocínio completo no git:

| Ids | Revisão | Onde está |
| --- | --- | --- |
| P0–P2 | Propostas de 14/09 (o que aprender de outros bots, roadmap) | `git show 1122cba:docs/dev/propostas.md` |
| A1–A15, N1–N8 | Revisão de 18/09 (achados e propostas) | `git show 1122cba:docs/dev/novas_propostas.md` |
| E1–E9 | Revisão de 18/09 da economia e da composição | `git show 1122cba:docs/dev/melhorias_propostas_eco.md` |
| C, F, L, I | Achados de revisão do código de 18/09 | `git show 8c3f9d3:docs/dev/gaps.md` |
| D1–D10 | Plano final do debate de 04/10 entre dois agentes | `git show 1122cba:docs/dev/agent_discussion/README.md` |

O backlog e o staging que vieram antes destes marcos estão em `git show ba88e8e:docs/dev/backlog.md` e
`git show ba88e8e:docs/dev/staging/README.md`.

## Ciclo de um item

Um item nasce num marco (de uma pesquisa, de um log ou de uma revisão). Quando se decide fazê-lo, ele ganha
estado no marco ("em andamento", com o próximo passo e como medir) e, se não couber ali, um registro próprio em
`registros/`. Quando entra no HEAD:

- o mecanismo vai para o [architecture.md](../architecture.md) ou para o documento da camada
  ([Ego](../ego/README_EGO.md), [Body](../body/README_BODY.md)…);
- a medição vai para "Medições" do architecture.md;
- o item sai do marco e vai para [Concluído](#concluído), e os ids de pesquisa que ele fechou (OS1, LL3…)
  ganham uma nota no documento de origem.

Um experimento medido sem ganho é revertido e fica registrado no marco, em "Medido e revertido". Um marco fecha
quando o critério de saída é medido num bench; ele sai da tabela e o que ele entregou vai para Concluído.

**O imaginado não se liga ao implementado.** Daqui se citam os documentos de `docs/` com link, mas o código só
como texto (`composition.py:199`), sem link. No sentido contrário, `docs/` só entra aqui por este índice; um id
citado num documento do HEAD fica como texto ("I2 no marco 3"). Assim, no grafo do Obsidian, o que estamos
imaginando fica numa nuvem à parte, ligada ao resto por poucas pontes.

## O que não fazer

Juntado das cinco revisões; continua valendo.

- **Não reescrever as camadas** nem trocar o Ares: os seams atuais são o maior ativo, e o Ares é o mecanismo
  (micro, pathing, macro); a política é nossa. Não forkar o Ares vendorizado.
- **Não reimplementar o que o Ares já tem**, nem trocar o `SpawnController`/`ProductionController` por um executor
  próprio: as armadilhas dele entram no Body, como entrou o `ExactResearch`.
- **Não manter sinal sem consumidor.** Se `risk`, o campo ou um agregado não ganharem leitor, é melhor apagá-los.
- **Nada de cortes nem bônus de preferência** em scores: restrições físicas, utilidade contínua e, só por último,
  histerese. Nada de `freeflow` permanente, limiar de entrada no mix ou solver global (LP/ILP).
- **Não calibrar jogando partidas** o que o replay já responde, e não ajustar números de combate partida a partida.
- **Não variar abertura por sorteio** nem criar um planner ou estilo por matchup: a raça é entrada, não dono.
- **Não usar uma vitória isolada nem Elo como diagnóstico.** Nada entra no HEAD sem bench, e um experimento sem
  ganho medido é revertido e registrado.
- **Não começar por RL**, rede neural ou crença probabilística completa, e não copiar código externo sem conferir a
  licença.

## Concluído

Para não reabrir: o P0 inteiro (harness, defesa por incidente, wall nos dois sentidos, ciclo ofensivo, macro mínima,
CI com pytest e ruff); a economia como pacote com contratos próprios [E1, N2.1]; a composição por eficácia sobre o
modelo de combate, com chaves canônicas [E3, E6, E7]; aberturas por raça e estilo [N2.3]; resposta a rush com Bunker
e reparo [P0.4]; o observador do exército inimigo [P1.1]; a ofensiva pelas posturas, com `power_spike` [A7, N7.2,
I15, F7]; o limiar duplicado da abertura [I6]; a seed do estilo pelo oponente [I8]; o scout pela tag concedida
[I12]; o cancelamento gracioso da ofensiva em uso [L3, a parte da Offense]; a `ScoutMission` fora dos docs [D10].

Várias dessas entregas (posturas, observador, composição, resposta a rush) estão no código mas ainda sem bench:
o veredito delas é parte do [M2](m2-medicao.md).
