# Common

↑ [Planners](README_PLANNERS.md) · [Ego](../README_EGO.md)

> O que todo planner compartilha: os contratos que ele entrega ao Body e o que é uma missão. Nenhuma missão
> concreta mora aqui.

Tudo é reexportado por `bot.ego.planners`. O que a Economy entrega ao Body fica em
`bot/ego/economy/contracts.py` ([Economy](../economy.md)).

## Contratos

| Contrato | O que é | Quem produz | Quem consome |
| --- | --- | --- | --- |
| `Proposal` | Um pedido de unidades: `command`, `target`, `priority`, e `count`, `minimum_power` ou todas as livres; restrições `unit_types` e `must_attack` (`Domain`: `GROUND`/`AIR`); `mission_id`, `demand_id`, `fallback` | Defense, Offense, MapControl, Intel | [Engine](../../body/engine.md) |
| `Command` | A instrução da unidade: `ATTACK`, `HOLD`, `SCOUT`, `RETREAT`, `GARRISON`, `REPAIR`, `REMOVE_CREEP` | dentro da `Proposal` | o behavior com o mesmo nome ([Body](../../body/README_BODY.md)) |
| `DefensePlan` | As propostas da Defense e a `FortificationPlan` (`BunkerSite`s a construir, Bunkers a esvaziar) | Defense | Engine e o behavior [fortify](../../body/behaviors/fortify.md) |
| `IntelPlan` | As propostas do scout, a `DetectionPlan`, a `SensorTowerPlan`, o pedido consolidado de Engineering Bay e o `EarlyScoutReport` | Intel | Engine e os behaviors [detection](../../body/behaviors/detection.md), [sensor-towers](../../body/behaviors/sensor-towers.md) e [intel-infra](../../body/behaviors/intel-infra.md) |
| `StructurePlan` | Depots a abaixar e levantar; estruturas a levantar e pousar e os passos da relocation (`RelocationEvent`) | StructureControl | o behavior [structures](../../body/behaviors/structures.md) |

**Plan** é intenção estruturada, com ou sem propostas. **Proposal** pede atores ao Engine; **Grant** é a
alocação dela. **Command** identifica a instrução consumida pelo Behavior, com alvo na proposta. Mission não
é sinônimo de nenhum desses contratos, e uma proposta contínua pode ter `mission_id=None`.

## Missões

Uma missão é uma operação episódica que um planner governa, em `<planner>/missions/`. As regras de quando
abrir uma estão em [Admissão de Mission](../../architecture.md#papéis-arquiteturais).

**Mission e Proposal.** A missão persiste; a proposta é a demanda de um frame. Uma missão emite zero, uma ou
várias propostas (um drop pediria transporte e carga), cada uma com `mission_id`. São três identidades
distintas:

- o planner (`owner`: `offense`, `defense`, `intel`, `map_control`);
- a missão (`mission_id`: `offense:main_attack:N`, `defense:defend_area:N`, `intel:early_scout:N`…), um número
  por operação para separar as sucessivas nos logs;
- a proposta (`proposal_id`). A da ofensiva guarda o id `offense` em todas as fases e missões, a do scout
  guarda `intel` e as da defesa seguem o incidente (`defense:<incidente>:air`/`ground`), porque o Engine
  prefere manter as unidades de quem já as tinha pelo `proposal_id`.

`demand_id` é outra coisa: agrupa as partes aérea e terrestre de uma `DefendAreaMission`.

**Lifecycle.** O status é pequeno e comum (`ACTIVE`, `COMPLETED`, `FAILED`, `CANCELLED`); as fases são de cada
operação. Um pedido de cancelamento não é um cancelamento: `request_cancel(modo, razão)` guarda o pedido, e é a
missão, no seu passo, que chega a `CANCELLED`. Um pedido imediato escala um gracioso, nunca o contrário; uma
missão terminal não aceita pedido e não emite proposta.

- **Imediato:** a missão termina no mesmo passo, sem propostas; as unidades que tinha ficam livres na alocação
  desse frame.
- **Gracioso:** a missão continua emitindo a retirada (`WITHDRAW`, `RETREAT` ao rally) até a sua condição de
  liberação (exército reunido) ou o prazo (`retreat_timeout`), e só então fica `CANCELLED`. A retirada não
  garante posse: uma proposta de prioridade maior (Defense) ainda toma unidades, e a missão segue com as que
  receber, inclusive nenhuma. Uma missão sem unidades na mão (ASSEMBLE, REGROUP, um scout que não saiu)
  encerra na hora.

**Feedback.** O `EngineResult` de um frame fica em `Layers.feedback` e é lido no frame seguinte:
`MissionFeedback.of(result, mission_id)` junta as `Grant` das propostas da missão (tags, poder, `status`,
`reason`). As tags são feedback, não posse. O fluxo é determinístico e sem ciclos: observação atual + feedback
anterior → Strategy → planners/missões → propostas → Engine → behaviors → feedback do próximo frame.

**Liberação de unidades.** Quando uma missão para de emitir uma proposta (terminal, ou numa fase sem
proposta), o Engine deixa de conceder aquelas unidades na mesma alocação: vão para quem as pede, e um worker
liberado volta à mineração (`released`). A missão não libera nada: ela só deixa de pedir.

**Resumo para quem está acima.** `planner.views()` devolve um `MissionView` imutável por missão governada no
frame (também a que acabou de terminar), com o que a alocação anterior lhe deu. Vai para o log
(`mission.updated`) e para `Frame.missions`. A Strategy poderia recebê-lo, mas hoje nenhuma decisão dela
depende disso.

## Quem usa missões

| Planner | Missões | Detalhes |
| --- | --- | --- |
| Offense | `MainAttackMission` | [Offense](offense.md) |
| Defense | `DefendAreaMission` (uma por incidente), `RushDefenseMission` (no máximo uma) | [Defense](defense.md) |
| Intel | `EarlyScoutMission` | [Intel](intel.md) |
| MapControl | `RemoveCreepMission` (contra Zerg) | [MapControl](map-control.md) |
| StructureControl | nenhuma: a relocation tem episódios, mas opera estruturas que o Engine não arbitra, então é Policy | [StructureControl](structure-control.md) |

**Uma missão nova** entra como um módulo em `missions/` do planner que a governa, e um comando novo como um
behavior com o nome dele. A próxima prevista é `harass/` (N7.3 no marco 5): `harass/planner.py` com
`missions/drop.py` e `missions/banshee_raid.py`, e os behaviors `move`, `load` e `unload`. Nenhum deles existe
ainda. Não é preciso criar classe base, registry ou Mission por feature.

**Orçamentos.** Não há orçamento de poder por domínio: a precedência entre domínios é a prioridade das
propostas (Defense > 0, ofensiva 0, MapControl −1) e a postura da Strategy. Se um orçamento vier, ele
precisa separar a meta desejada, o limite de admissão de novas operações, as unidades ainda comprometidas
numa retirada e a precedência para preempção.

**Cancelamento em produção.** A postura DEFEND leva a Offense a pedir cancelamento imediato, e a Defense
recebe unidades já nesse frame. A postura RECOVER leva ao cancelamento gracioso: o exército volta ao rally
antes de a missão terminar.

## No log

`planner.proposed` (o conjunto de propostas) e `mission.updated` (uma missão abre, muda de fase, recebe
pedido de cancelamento ou termina).

## Código

- [bot/ego/planners/common/contracts.py](../../../bot/ego/planners/common/contracts.py): `Proposal`,
  `Command`, `Domain`, `DefensePlan`, `FortificationPlan`, `IntelPlan`, `DetectionPlan`, `SensorTowerPlan`,
  `StructurePlan`.
- [bot/ego/planners/common/mission.py](../../../bot/ego/planners/common/mission.py): `MissionStatus`,
  `CancelMode`, `CancelRequest`, `Lifecycle`, `MissionFeedback`, `MissionView`.
