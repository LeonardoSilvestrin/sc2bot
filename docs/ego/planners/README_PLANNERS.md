# Planners

↑ [Ego](../README_EGO.md) · [Arquitetura](../../architecture.md)

Um documento por planner, um pacote por domínio em `bot/ego/planners/`: o que ele decide, como decide e o que
ainda falta. Todos descrevem o código do HEAD. A [Strategy](../strategy.md) e a [Economy](../economy.md) não
são planners e ficam no [Ego](../README_EGO.md). O que está em andamento fica em
[staging/](../../dev/staging/README.md), e os papéis e eventos em [architecture.md](../../architecture.md).

| Documento | Pergunta que responde | Pede unidades ao Engine? |
| --- | --- | --- |
| [Defense](defense.md) | Quem está atacando uma base nossa, e quanto exército mandar? E onde segurar um rush? | Sim, prioridade > 0; o Bunker por plano direto |
| [Offense](offense.md) | Atacar agora? E, durante o ataque, avançar, lutar ou recuar? | Sim, prioridade 0 |
| [MapControl](map-control.md) | Onde espera o exército que ninguém está usando? E, contra Zerg, onde limpar creep? | Sim, prioridade −1 |
| [Intel](intel.md) | O que precisamos ver, e com o quê (scout, scan, torre)? | Só um SCV |
| [StructureControl](structure-control.md) | O que nossas estruturas fazem sozinhas (depots, tirar estrutura do caminho)? | Não (plano direto) |
| [Common](common.md) | O que todos compartilham: os contratos com o Body e o que é uma missão | — |

Cada documento de planner tem as mesmas seções: **Resumo**, **Entradas e saídas**, **Como decide**, **Estado entre
frames**, **Parâmetros**, **No log**, **Limitações conhecidas** e **Código**.

## O frame, em ordem

A ordem em que os planners rodam e o que passam um para o outro estão no [Ego](../README_EGO.md#o-frame-em-ordem).
Nenhum planner chama outro. Os contratos (Proposal, Grant, planos diretos) e o lifecycle das missões estão em
[Common](common.md); a alocação, no [Engine](../../body/engine.md).

## Quem pede o quê

| Quem | Pede | Prioridade | Comando |
| --- | --- | --- | --- |
| Defense | poder suficiente para cada incidente, separado em ar e terra | `ameaça · (0,5 + 0,5·defense)`, entre 0 e 1 | `ATTACK` |
| Defense (rush) | Marines para as vagas do Bunker; SCVs para repará-lo | 1,0 | `GARRISON`, `REPAIR` |
| Offense | todas as unidades livres | 0 | `ATTACK` ou `RETREAT` |
| MapControl | todas as unidades livres (o que sobrou) | −1 | `HOLD` |
| MapControl (creep, contra Zerg) | 1 Raven; 2 Hellions ou 4 Marines + 1 Medivac de escolta | Raven 0,05; escolta −0,5 | `REMOVE_CREEP` |
| Intel | 1 SCV (só workers; não disputa exército) | 0,5 a 1,0, pela fase do scout | `SCOUT` |

Na prática: a Defense pega o que o incidente precisa, a Offense pega o resto quando há ataque, e o
MapControl fica com o que ninguém pediu.

## A postura em cada planner

A Strategy escolhe uma postura e todos leem a mesma. O que ela significa em cada domínio é decisão do
planner (a tabela vem do código de cada um):

| Postura | Economy | Offense | MapControl | Intel | Defense |
| --- | --- | --- | --- | --- | --- |
| DEFEND | tudo em exército: sem upgrades, add-ons nem expansão; em emergência interrompe a abertura e liga o SURVIVE | não abre; cancela o ataque **na hora** | anchor na base mais ameaçada | nenhum scout sai; Orbitais guardam scan | margem 2,0 |
| RECOVER | sem expansão; upgrades e add-ons seguem | não abre; cancela **com retirada** | `advance` 0 (só cobre as bases) | foco em economia | margem 1,5 |
| DEVELOP | expande quando satura | não abre; ataque em curso segue até o próximo reagrupamento | `advance` 0,7 | foco em economia | margem 1,5 |
| PRESSURE | expande quando satura; teto de produção 5 por base | abre ataque | `advance` 0,8 | Orbitais guardam scan | margem 1,5 |
| COMMIT | sem expansão; teto 5 por base | abre ataque sem esperar o cooldown | `advance` 0,8 | Orbitais guardam scan | margem 1,5 |

## Termos que aparecem em todos

- **Poder** (em Marines): `sqrt(dps · alvos · vida)` de uma unidade, dividido pelo de um Marine. Um Marine
  vale 1; um Siege Tank em siege com vida cheia vale cerca de 4,3. Somar poderes é a lei quadrática de
  Lanchester: dobrar o número de unidades dobra o poder somado.
- **Postura**: o que o bot quer agora (DEFEND, RECOVER, DEVELOP, PRESSURE, COMMIT). Ver
  [strategy.md](../strategy.md).
- **Incidente**: um grupo de inimigos ao alcance de alguma base nossa, montado pela Awareness. Ver
  [defense.md](defense.md).
- **Anchor**: o ponto onde o exército livre espera e onde a ofensiva se reúne. Ver
  [map-control.md](map-control.md).
- **Missão**: uma operação com começo e fim (um ataque, a defesa de um incidente, o scout inicial). Tem
  fases próprias e termina `COMPLETED`, `FAILED` ou `CANCELLED`. Planner sem operação episódica não tem
  missão (StructureControl; a Economy também não). Ver [Common](common.md#quem-usa-missões).
- **Desired state**: uma condição que o planner mantém continuamente (o anchor, a barreira de radar, os
  depots). Se deixa de valer, é pedida de novo, sem abrir missão.
