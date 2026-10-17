# Engine

↑ [Body](README_BODY.md) · [Common](../ego/planners/common.md)

> Só alocação: decide qual unidade atende qual `Proposal`. Cada unidade vai para no máximo uma. Não comanda
> nada.

## Como aloca

`Engine.allocate(attention, proposals)`:

1. **Ordena** as propostas por `(-priority, owner, proposal_id)`. Dois `proposal_id` iguais no mesmo frame são
   erro.
2. **Elegíveis**: as restrições duras vêm antes de qualquer ordem, e nenhuma preferência compra uma unidade
   que não as cumpre.
   - Sem `unit_types`, só unidades de exército (`is_army`). Com `unit_types`, só esses tipos.
   - Um pedido de poder (`minimum_power`) só aceita unidades com poder > 0.
   - `must_attack` `GROUND` ou `AIR`: a unidade tem que atirar nesse domínio.
   - Workers só são elegíveis para propostas que pedem um tipo de worker, e só saindo da mineração (role
     `GATHERING`) ou já sendo de alguma proposta.
3. **Candidatas**: as elegíveis ainda livres, primeiro as que a proposta já tinha (para o grant não trocar de
   unidades enquanto elas andam), depois as mais perto do alvo, e por fim a menor tag.
4. **Escolhe** até `count`, ou até atingir `minimum_power`, ou todas as candidatas.
5. **Julga** cada `Grant`:

   | Pedido | `FULL` | `PARTIAL` | `REJECTED` |
   | --- | --- | --- | --- |
   | `minimum_power` | `minimum_power_met` | `insufficient_power` | nenhuma unidade |
   | `count` | `count_met` | `insufficient_units` | nenhuma unidade |
   | todas as livres | `every_free_unit` | — | nenhuma unidade |

   O `REJECTED` diz por quê: `eligible_units_taken` (havia elegíveis, mas propostas acima levaram) ou
   `no_eligible_units`.

## O que devolve

`EngineResult`:

- `grants`: um `Grant` por proposta (`tags`, `power`, `status`, `reason`);
- `owners`: o dono (`proposal_id`) de cada unidade concedida;
- `unassigned`: as unidades de exército que ninguém pegou;
- `released`: quem tinha dono no frame anterior e perdeu. Um worker liberado volta a minerar no behavior
  [macro](behaviors/macro.md) (`release_workers`).

O `EngineResult` vai para os behaviors no mesmo frame e é o **feedback** que os planners e as missões leem no
frame seguinte (`MissionFeedback`).

## O que não faz

- Não arbitra minerais, energia de Orbital nem produção: isso são planos diretos, que não passam por aqui.
- Não decide objetivo, alvo nem lifecycle. É o único registro de posse, e nunca lê nem muda o lifecycle de
  uma missão.
- Não comanda: o que fazer é dos planners, como fazer é dos behaviors.

## No log

- `engine.granted`: alguma concessão muda (`grants[]`, `transfers[]`, `unassigned`).
- `engine.commanded`: comando, alvo, unidades ou missão de uma concessão mudam.

## Código

- [bot/body/engine.py](../../bot/body/engine.py): `Engine`, `EngineResult`, `Grant`, `GrantStatus`, `rank`.
