# Fortify

↑ [Defense](../planners/defense.md)

> O que o Body faz com o `FortificationPlan` da Defense: construir o Bunker e esvaziar os que mandam.

## Quem chama

**Defense**, pelo `FortificationPlan`, um plano direto: não passa pelo Engine e não tem `Command`. Roda antes
da economia, para que o Bunker seja pedido antes de o frame gastar os minerais.

## O que faz

1. **Bunkers**: cada sítio do plano vai para o `BuildStructure` do Ares no conjunto de placement da base do
   sítio, no spot 3x3 livre mais perto do ponto que o plano dá, e em nenhum outro lugar
   (`find_alternative=False`): um Bunker em outra base não segura nada. O Ares manda um construtor por vez e
   espera o Barracks; aqui só se espera ter `BUNKER_COST` em minerais.
2. **Unload**: um Bunker cuja guarnição deve sair (`plan.unload`) e que tem alguém dentro recebe
   `UNLOADALL_BUNKER`.

## Parâmetros

| Parâmetro | Valor | Onde | Efeito |
| --- | --- | --- | --- |
| `BUNKER_COST` | 100 | fortify.py | Sem isso em minerais, nenhum Bunker é pedido neste frame |

## No log

`planner.fortification_planned`, com `building` (o que foi entregue ao Ares neste frame) e `unloaded` (os
Bunkers esvaziados). Sai quando o pedido muda ou quando há um unload.

## Limitações conhecidas

- O teste de minerais não desconta um Bunker já pedido no mesmo frame: com dois sítios e 100 minerais, os dois
  vão para o Ares.

## Código

- [bot/body/behaviors/fortify.py](../../bot/body/behaviors/fortify.py): `execute`, `FortifyReport`.
