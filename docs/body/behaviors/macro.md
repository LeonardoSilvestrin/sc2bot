# Macro

↑ [Body](../README_BODY.md) · [Economy](../../ego/economy.md)

> O que o Body faz com o `EconomyPlan`: os workers mineram, e o plano vira os macro behaviors do Ares.

## Quem chama

**Economy**, pelo `EconomyPlan`, um plano direto: não passa pelo Engine. Roda depois da Detection (o Orbital
que escaneou não solta MULE) e com as estruturas que o [Structures](structures.md) está levantando fora de
qualquer treino.

## O que faz

A cada frame, nesta ordem:

1. **Workers liberados** (`release_workers`): um worker que nenhuma proposta segura mais volta ao role
   `GATHERING`, e o `Mining` do Ares o pega de novo.
2. **Fim da abertura**: um plano que interrompe a abertura (`interrupt_opening`) para o build runner do Ares
   antes de tudo, e o plano assume no mesmo frame.
3. **Mining** do Ares roda sempre.
4. **Plano inativo** (abertura rodando): só os pedidos de unidade por missão (`RequestedUnits`), e só quando a
   abertura não é uma variante que já treina o Raven e já há Factory.
5. **Add-on**, fora do `MacroPlan`, um por frame: uma estrutura de produção pronta, parada e sem add-on ganha
   um Reactor enquanto os Reactors ficam dentro de `reactor_share`, e um Tech Lab no resto. Essa estrutura
   fica fora do `SpawnController` no frame, porque a última ordem vence.
6. **`MacroPlan`** do Ares, que para no primeiro behavior que age: `AutoSupply`, `UpgradeCCs` (Orbitals),
   `BuildWorkers`, `GasBuildingController`, `ExpansionController`, `RequestedUnits`, `ExactResearch` +
   `UpgradeController`, `SpawnController` (a composição) e `ProductionController`. O que não pode esperar o
   exército parar de crescer vem antes do `SpawnController`, que age sempre que a produção está parada.
7. **MULEs**: cada Orbital pronto com energia além da reserva do scan, e que não escaneou neste frame, solta um
   MULE no campo mais cheio de uma base pronta.

Três peças são nossas, por cima do Ares:

- **`ExactResearch`**: pesquisa o plating de veículos e naves pela habilidade que a estrutura oferece. O
  `UpgradeController` do Ares pedia outra, o jogo descartava a ordem, e como o `MacroPlan` para no primeiro que
  age, nada depois dele era comprado pelo resto da partida (`bench/smoke-mech`).
- **`RequestedUnits`**: compra totais fixos pedidos por missões,
  fora da proporção da composição; constrói Starport e Tech Lab se faltam.
- **`spawn_mode`**: quando todos os tipos da composição batem a proporção ao mesmo tempo, o `SpawnController`
  do Ares não treina nada; nesse frame ele passa a gastar livre (`composition_met`).

## Parâmetros

| Parâmetro | Valor | Onde | Efeito |
| --- | --- | --- | --- |
| `MULE_ENERGY` | 50 | economy.py | Energia de um MULE, somada à reserva do scan |
| `MINING_DISTANCE` | 10 | economy.py | Campo a essa distância de uma base é dela (alvo do MULE) |

O resto (workers, gás, bases, composição, upgrades, `reactor_share`) vem do `EconomyPlan`.

## No log

`behavior.spawn_executed`, com `freeflow`, `reason` (`plan_inactive`, `plan_freeflow`, `composition_met` ou
`composition_short`) e `counts` (como o `SpawnController` conta, com produção). Sai quando o modo muda. O
plano em si sai em `planner.economy_planned`.

## Limitações conhecidas

- Um add-on por frame.
- O `MacroPlan` para no primeiro behavior que age: um behavior que age todo frame sem efeito trava o resto (foi
  o caso do plating, corrigido pelo `ExactResearch`).

## Código

- [bot/body/behaviors/economy.py](../../../bot/body/behaviors/economy.py): `execute`, `release_workers`,
  `add_add_on`, `ExactResearch`, `RequestedUnits`, `spawn_mode`, `call_mules`.
