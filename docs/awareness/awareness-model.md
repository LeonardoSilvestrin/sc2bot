# Awareness model

↑ [Awareness](README_AWARENESS.md)

> O `AwarenessModel`: lembra os contatos inimigos, lê a pressão sobre cada base, agrupa os atacantes em
> incidentes, lembra o exército visto e o produzido, e diz quanto ainda é early game.

## Contatos

Todo inimigo à vista vira um `Contact` com confiança 1 e incerteza 0. Fora de visão:

- confiança `exp(-idade / τ)`, com τ = `unit_memory` (20 s) para unidades e `structure_memory` (240 s) para
  estruturas;
- incerteza de posição `min(max_uncertainty, drift_speed · idade)` (2,8 células/s, até 16); estrutura não anda;
- é esquecido com a morte confirmada (`dead_tags`), com a confiança abaixo de `forget_below` (0,05) ou quando
  a última posição volta à visão vazia, depois de `vision_grace` (2 s);
- lembra se estava camuflado ou enterrado (`is_cloaked`) e se nada o detectava (`is_hidden`).
  `hidden_contacts` são os camuflados sem detecção, à vista agora; `cloak_seen_at` é quando um exército
  camuflado foi visto pela primeira vez.

## Ameaça por base

Para cada base nossa (`BaseThreat`):

- pressão `Σ poder · confiança · K(d, σ_base + incerteza)` dos atacantes ao alcance físico
  (`base_reach + incerteza`), com `base_sigma` 14 e `base_reach` 30;
- `threat = S(pressão / full_pressure)`, com `full_pressure` 4 Marines;
- ameaça lembrada `recent_threat = max(threat, recent_threat anterior · exp(-Δt / threat_memory))`, τ = 20 s.
  A parte que decaiu é esquecida abaixo de `forget_below`, e uma base que some leva a memória. Um ataque que
  rareia ou recua continua acreditado; um mais forte conta no mesmo frame;
- também `cover` (o nosso exército perto, pelo mesmo kernel), `air_share` e o `center` da pressão.

`danger` é o maior `recent_threat`, `danger_now` o maior `threat` e `most_threatened` a base de maior
`recent_threat`.

## Incidentes

Um `ThreatIncident` são os atacantes (poder > 0) ao alcance de alguma base, ligados em cadeia a até
`incident_link` (12) um do outro, quantas bases tocarem.

- **Identidade.** Cada grupo herda o id do incidente do frame anterior com quem mais compartilha membros.
  Os pares são resolvidos por mais membros em comum, depois menor tag do grupo, depois menor tag que o
  incidente anterior tinha, e cada id vai a um grupo só. Numa divisão, o id fica com a parte que leva mais do
  incidente; numa fusão, com o incidente que traz mais membros. Um grupo sem herança é
  `incident:<menor tag>`, com sufixo `-1`, `-2`… enquanto esse id estiver em uso.
- **Medidas.** Poder `Σ poder · confiança` (terrestre e aéreo), centro ponderado por esse poder, pressão em
  cada base afetada e `threat = S(maior pressão numa base / full_pressure)`.

A Defense abre uma missão por incidente: ver [Defense](../ego/planners/defense.md).

## Exército inimigo

Em Marines; workers e estruturas não são exército.

- `enemy_power` (conhecido): `Σ poder · confiança` dos contatos de exército, a parte que um contato ainda
  localiza.
- `seen_enemy_power` (visto vivo): `Σ poder · exp(-idade / army_memory)` das unidades vistas vivas e não vistas
  morrer, τ = 180 s. Sai com a morte confirmada ou abaixo de `forget_below`, não quando a última posição volta
  à visão vazia. Como `army_memory ≥ unit_memory`, conhecido ≤ visto vivo. `seen_enemy_types` é o mesmo, por
  tipo.
- `produced_enemy_types` (produzido): `Σ poder · exp(-idade / production_memory)` por tipo de toda unidade de
  exército já vista, **morta ou viva**, pelo maior poder com que foi vista, τ = 360 s. É o que o inimigo
  constrói, não o que ele tem: um Lurker morto ainda diz que existe Lurker Den.
- O exército inteiro é estado do [observador](enemy-army.md): `estimated_enemy_power =
  max(conhecido, visto vivo, A)`, `enemy_sigma = σ_A` e `enemy_coverage = conhecido / estimado` (1 enquanto o
  estimado é 0).

## Early game

`early_game` ∈ [0, 1] é crença da Awareness, não o relógio de quem a lê. Vale 1 até `early_game_until`
(240 s), cai linearmente até 0 em `early_game_over` (420 s), ou vai a 0 na hora em que temos
`early_game_bases` (3) bases. Nunca sobe: perder a third não devolve o early game. Só um ataque no early
game é rush; a defesa de rush da Defense e a fala "I'm getting rushed!" do chat leem esse valor.

## O resto do estado

- `influence`: o [campo de influência](field.md).
- `regions`: as [regiões ranqueadas](regions.md).
- `opening`: a [leitura da abertura](opening-belief.md).

## Parâmetros

Todos em `AwarenessConfig`, com os valores citados acima. `field_sigma` (7) e `structure_presence` (0,5) são do
[campo](field.md).

## No log

`awareness.updated`: muda quando mudam os contatos, o poder, a ameaça por base, os contatos escondidos, o
primeiro camuflado ou a estimativa do observador (de 5 em 5 Marines), e também por heartbeat. Traz os
incidentes (escrito também quando os membros de um incidente mudam) e o resumo do campo.

## Código

- [bot/awareness/model.py](../../bot/awareness/model.py): `AwarenessModel`, `AwarenessConfig`,
  `AwarenessState`, `Contact`, `BaseThreat`, `ThreatIncident`.
