# Sensor Towers

↑ [Intel](../planners/intel.md)

> O que o Body faz com o `SensorTowerPlan` do Intel: construir a torre exatamente onde o radar foi avaliado.

## Quem chama

**Intel**, pelo `SensorTowerPlan` dentro do `IntelPlan`, um plano direto: não passa pelo Engine.

## O que faz

1. Com sítios no plano, Engineering Bay pronto (`plan.engineering_bay` falso) e
   `SENSOR_TOWER_MINERAL_COST`/`SENSOR_TOWER_VESPENE_COST` no banco, o **primeiro** sítio vai para o Ares.
2. `BuildSensorTower` é o `BuildStructure` do Ares com uma trava: antes de mandar um worker, consulta o
   placement sem reservar e só segue se o spot que o Ares devolve for **exatamente** o ponto avaliado. A
   flag `sensor_tower` do Ares prefere spots prontos ao `closest_to`, e um alvo ocupado pode cair em outro
   spot; os dois casos são recusados, porque a cobertura de radar só vale no ponto calculado.

## Parâmetros

| Parâmetro | Valor | Onde | Efeito |
| --- | --- | --- | --- |
| `SENSOR_TOWER_MINERAL_COST` | 125 | sensor_towers.py | Minerais exigidos antes de pedir |
| `SENSOR_TOWER_VESPENE_COST` | 100 | sensor_towers.py | Gás exigido antes de pedir |

## No log

`behavior.intel_executed` (`building`), junto com a Detection e o Intel infra. O plano sai em
`planner.sensor_towers_planned`.

## Limitações conhecidas

- Uma torre por frame, sempre a do primeiro sítio. Se o spot dele estiver ocupado, os outros esperam.

## Código

- [bot/body/behaviors/sensor_towers.py](../../bot/body/behaviors/sensor_towers.py): `execute`,
  `BuildSensorTower`, `SensorTowerReport`.
