# Intel infra

↑ [Intel](../planners/intel.md)

> O que o Body faz com o pedido consolidado de infraestrutura do Intel: o Engineering Bay.

## Quem chama

**Intel**, pelo `IntelPlan.engineering_bay`. A [Detection](detection.md) (Turrets) e as
[Sensor Towers](sensor-towers.md) dependem dele; só este executor o constrói, para que as duas não o peçam em
dobro.

## O que faz

Com o pedido ativo e `ENGINEERING_BAY_COST` em minerais, entrega ao `BuildStructure` do Ares um Engineering
Bay na main (`to_count=1`: com um pronto ou em construção, o Ares não faz outro).

## Parâmetros

| Parâmetro | Valor | Onde | Efeito |
| --- | --- | --- | --- |
| `ENGINEERING_BAY_COST` | 125 | intel.py | Sem isso em minerais, nada é pedido neste frame |

## No log

`behavior.intel_executed` (`building`), junto com a Detection e as Sensor Towers.

## Código

- [bot/body/behaviors/intel.py](../../bot/body/behaviors/intel.py): `execute`.
