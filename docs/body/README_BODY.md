# Body

↑ [Arquitetura](../architecture.md) · [README](../../README.md)

> Aloca e executa. O [Engine](engine.md) decide qual unidade atende qual proposta do
> [Ego](../ego/README_EGO.md), e os behaviors transformam grants e planos diretos em ordens do jogo, quase
> sempre pelo Ares.

Na cadeia decisória, só os behaviors causam efeito deliberado no jogo. Um behavior pode mudar o path, o
siege, o stim, o ator equivalente ou a posição fina, mas não o objetivo, o alvo estratégico, o compromisso ou
o cancelamento. O teste: dá para trocar a implementação dele sem mudar o que o bot quer fazer?

## No frame

```text
result = engine.allocate(attention, proposals)
body   = behaviors.execute(bot, attention, result, economy_plan, structures, intel, defense.fortification)
```

Dentro de `behaviors.execute`, nesta ordem:

1. `release_workers`: os workers que o Engine soltou (`result.released`) voltam a minerar.
2. Os grants, cada um com o behavior do seu `Command`. As partes de um `REMOVE_CREEP` com o mesmo
   `mission_id` (Raven e escolta) são executadas como um squad só.
3. [fortify](behaviors/fortify.md): o Bunker é pedido antes de a economia gastar os minerais do frame.
4. [detection](behaviors/detection.md): o scan. O Orbital que escaneou (`busy`) e a reserva de energia
   (`energy_reserve`) passam para a economia.
5. [intel-infra](behaviors/intel-infra.md) e [sensor-towers](behaviors/sensor-towers.md).
6. [macro](behaviors/macro.md): o `EconomyPlan`, sem usar o Orbital que escaneou, sem gastar a reserva de
   scan e sem treinar nas estruturas que o `StructurePlan` está levantando (`lifting`).
7. [structures](behaviors/structures.md): depots e relocation.

`execute` devolve o `BodyReport` (`spawn`, `micro`, `detection`, `sensor_towers`, `infrastructure`,
`fortified`), que só vai para o log.

## Documentos

| Documento | Código | Entrada | Quem pede |
| --- | --- | --- | --- |
| [Engine](engine.md) | [engine.py](../../bot/body/engine.py) | `Proposal`s | Defense, Offense, MapControl, Intel |
| [attack](behaviors/attack.md) | [attack.py](../../bot/body/behaviors/attack.py) | `ATTACK` | Defense, Offense |
| [retreat](behaviors/retreat.md) | [retreat.py](../../bot/body/behaviors/retreat.py) | `RETREAT` | Offense |
| [hold](behaviors/hold.md) | [hold.py](../../bot/body/behaviors/hold.py) | `HOLD` | MapControl |
| [remove-creep](behaviors/remove-creep.md) | [remove_creep.py](../../bot/body/behaviors/remove_creep.py) | `REMOVE_CREEP` | MapControl |
| [garrison](behaviors/garrison.md) | [garrison.py](../../bot/body/behaviors/garrison.py) | `GARRISON` | Defense |
| [repair](behaviors/repair.md) | [repair.py](../../bot/body/behaviors/repair.py) | `REPAIR` | Defense |
| [scout](behaviors/scout.md) | [scout.py](../../bot/body/behaviors/scout.py) | `SCOUT` | Intel |
| [combat](behaviors/combat.md) | [combat.py](../../bot/body/behaviors/combat.py) | — (regras compartilhadas) | usado por attack, hold, garrison e retreat |
| [fortify](behaviors/fortify.md) | [fortify.py](../../bot/body/behaviors/fortify.py) | `FortificationPlan` | Defense |
| [detection](behaviors/detection.md) | [detection.py](../../bot/body/behaviors/detection.py) | `DetectionPlan` | Intel |
| [sensor-towers](behaviors/sensor-towers.md) | [sensor_towers.py](../../bot/body/behaviors/sensor_towers.py) | `SensorTowerPlan` | Intel |
| [intel-infra](behaviors/intel-infra.md) | [intel.py](../../bot/body/behaviors/intel.py) | `IntelPlan.engineering_bay` | Intel |
| [macro](behaviors/macro.md) | [economy.py](../../bot/body/behaviors/economy.py) | `EconomyPlan` | Economy |
| [structures](behaviors/structures.md) | [structure_control.py](../../bot/body/behaviors/structure_control.py) | `StructurePlan` | StructureControl |

Os nomes `macro`, `structures` e `intel-infra` diferem do arquivo de código para não repetir no grafo os
rótulos dos docs da Economy, do StructureControl e do Intel.

Um comando novo entra como um behavior com o nome dele, registrado em `BY_COMMAND`.

## Código

- [bot/body/behaviors/\_\_init\_\_.py](../../bot/body/behaviors/__init__.py): `execute`, `command_units`,
  `BY_COMMAND`, `BodyReport`.
