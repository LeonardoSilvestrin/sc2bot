# Ego

↑ [Arquitetura](../architecture.md) · [README](../../README.md)

> Decide. Lê a [Attention](../attention/README_ATTENTION.md) e a [Awareness](../awareness/README_AWARENESS.md)
> e entrega ao [Body](../body/README_BODY.md) propostas de unidades e planos diretos. Não causa efeito
> nenhum no jogo.

O Ego tem três partes lado a lado. Nenhum planner importa outro, e o que uma parte passa para a outra vai
pelo frame. Entre elas só se importam contratos: o `StrategicIntent` da Strategy e o `UnitRequest` da
Economy, que o MapControl usa para pedir unidades.

| Documento | Código | Pergunta |
| --- | --- | --- |
| [Strategy](strategy.md) | [bot/ego/strategy/](../../bot/ego/strategy/__init__.py) | Como está a partida, e o que o bot quer agora? Publica o `StrategicIntent` que todos leem |
| [Planners](planners/README_PLANNERS.md) | [bot/ego/planners/](../../bot/ego/planners/__init__.py) | O que fazer com o que já existe (unidades, estruturas, energia)? Um pacote por domínio |
| [Economy](economy.md) | [bot/ego/economy/](../../bot/ego/economy/__init__.py) | O que passa a existir: workers, bases, gás, produção, exército, upgrades |

A Economy não é um planner: decide sobre outro recurso (minerais, gás, supply, tempo de produção), entrega
outro contrato (setpoints, não propostas) e nenhum planner a importa. Por dentro tem a mesma forma de um
planner (`planner.py`, `policies/`, `knowledge/`), sem missões.

## O frame, em ordem

```text
intent       = strategy.decide(attention, awareness)
defense      = defense.plan(attention, awareness, intent, feedback)
map_control  = map_control.plan(attention, awareness, intent, feedback)
offense      = offense.plan(attention, awareness, intent, map_control.anchor, feedback)
intel        = intel.plan(attention, awareness, intent, feedback)
economy_plan = economy.plan(attention, intent, army, ..., awareness, map_control.unit_requests)
structures   = structure_control.plan(attention)
```

- Todo planner que pede unidades (Defense, MapControl, Offense, Intel) lê o `feedback`: o `EngineResult` do
  frame anterior.
- O MapControl passa o `anchor` para a Offense e os `unit_requests` para a Economy. São os únicos fios
  entre partes do Ego no mesmo frame.
- A Economy também recebe o estilo de exército (`army`), a política de composição e a configuração de
  investimento.
- O StructureControl só lê a Attention: nem a postura, nem a Awareness.

## Onde fica cada coisa

```text
bot/ego/
  strategy/                         coordenação global: como está a partida e o que o bot quer
    model.py                        GameAssessment, StrategicIntent, StrategicPosture, PostureGate
    assessment.py                   AssessmentModel: Awareness -> GameAssessment
    strategy.py                     StrategyModel: GameAssessment -> StrategicIntent (gates, persistência)
  economy/                          o que comprar; não é planner; sem missões
    contracts.py                    contratos com o Body: EconomyPlan, CompositionPlan
    planner.py                      plan -> EconomyPlan
    policies/investment.py          quanto investir: workers, bases, gás, teto de produção, opening
    policies/composition.py         CompositionPolicy: o que construir agora
    knowledge/styles.py             ArmyStyle, BIO, MECH, o sorteio e o anúncio
    knowledge/combat.py             CombatModel: dps de um tipo contra outro, poder, prior por raça
    knowledge/combat.yml            hp, armadura, atributos, armas; prior de composição por raça
  planners/                         o uso do que já existe
    __init__.py                     reexporta common/
    common/                         contratos e missões, ver planners/common.md
    defense/  offense/  map_control/  intel/  structure_control/
```

Quem compra é a Economy, com duas exceções por enquanto: a Engineering Bay, as Missile Turrets e as Sensor
Towers são compradas pelo Intel, e o Bunker de uma defesa de rush pela Defense.

Cada domínio segue, quando se aplica, a forma `planner.py` + `missions/` + `policies/` + `knowledge/`. Os
papéis (Planner, Mission, Policy, Knowledge, desired state) estão em
[Papéis arquiteturais](../architecture.md#papéis-arquiteturais).
