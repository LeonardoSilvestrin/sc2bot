# Detection

↑ [Intel](../planners/intel.md)

> O que o Body faz com o `DetectionPlan` do Intel: o scan e as Missile Turrets.

## Quem chama

**Intel**, pelo `DetectionPlan` dentro do `IntelPlan`, um plano direto: não passa pelo Engine. Roda antes da
economia, e o Orbital que escaneou fica fora dos MULEs do frame.

## O que faz

1. **Scan**: se o plano pede um, sai do Orbital pronto com mais energia (empate: a menor tag), desde que tenha
   `SCAN_ENERGY`.
2. **Turret**: se o plano pede, o Engineering Bay já existe e há `TURRET_COST` em minerais, a **primeira** base
   da lista ganha uma Missile Turret pelo `BuildStructure` do Ares, no local de expansão mais perto dela, sem
   procurar em outras bases. O Ares manda um construtor por vez.
3. O Engineering Bay é pedido pelo [Intel infra](intel-infra.md); enquanto ele falta (`plan.engineering_bay`),
   nenhuma Turret é pedida.

## Parâmetros

| Parâmetro | Valor | Onde | Efeito |
| --- | --- | --- | --- |
| `SCAN_ENERGY` | 50 | intel/policies/detection.py | Energia mínima do Orbital para escanear |
| `TURRET_COST` | 100 | detection.py | Sem isso em minerais, nenhuma Turret neste frame |

## No log

`behavior.intel_executed`, com `scanned_by` (o Orbital que escaneou) e `building` (o que foi entregue ao Ares,
junto com o Intel infra e as Sensor Towers). O pedido em si sai em `planner.detection_planned`.

## Limitações conhecidas

- Uma Turret por frame, sempre a da primeira base da lista.

## Código

- [bot/body/behaviors/detection.py](../../bot/body/behaviors/detection.py): `execute`, `DetectionReport`.
