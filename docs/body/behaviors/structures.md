# Structures

↑ [Body](../README_BODY.md) · [StructureControl](../../ego/planners/structure-control.md)

> O que o Body faz com o `StructurePlan`: abaixar e levantar depots, decolar e pousar estruturas de produção.

## Quem chama

**StructureControl**, pelo `StructurePlan`, um plano direto: não passa pelo Engine. As estruturas que estão
decolando ficam fora de qualquer treino no [Macro](macro.md).

## O que faz

Para cada estrutura nomeada no plano:

- **`lower`/`raise_`**: o depot abaixa ou levanta.
- **`lift`**: cancela o que a estrutura está treinando e decola na fila. O jogo recusa a decolagem enquanto
  houver algo para treinar (um Reactor treina dois), então o plano nomeia a estrutura todo frame até ela voar,
  um cancelamento por frame; quem já está decolando é deixado em paz.
- **`land`**: vai para o `move_structure` do Ares, que voa até o sítio e pousa lá.

E uma vez, no início da partida (`keep_clear`, chamado de `main.py`): os sítios que o planner quer vazios saem
do placement 3x3 da main no Ares, para que o macro do Ares não construa neles.

## No log

Não tem evento próprio: o plano sai em `planner.structures_planned`, as relocações em
`planner.structure_relocation` e os sítios liberados em `planner.production_kept_clear`.

## Código

- [bot/body/behaviors/structure_control.py](../../../bot/body/behaviors/structure_control.py): `execute`,
  `keep_clear`.
