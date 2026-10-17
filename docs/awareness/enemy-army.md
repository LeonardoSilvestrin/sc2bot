# Enemy army

↑ [Awareness](README_AWARENESS.md) · [Awareness model](awareness-model.md)

> Um observador de estado do exército inimigo e da economia que o paga: previsto pela economia, baixado
> pelo que se vê morrer e corrigido pelo que se vê vivo. Um filtro de Kalman com média e σ.

O exército inimigo é um estado que o bot nunca vê inteiro. Antes era um prior por tempo, que crescia com o
relógio e que nada refutava. Agora é previsto e corrigido.

## O modelo

Por frame, com `Δt` desde o anterior:

- bases `B = max(townhalls lembrados, min(expansões / 2, 1 + t / base_interval) − townhalls vistos morrer)`,
  `base_interval` 150 s;
- workers `W ← min(vaga, W + worker_rate · Δt) − workers vistos morrer`, nunca menos que os workers
  lembrados, com `vaga = min(80, 22 · B)`, `W₀ = 12`, `worker_rate` 0,1/s;
- produção `u = min(W, 22 · B) · f(t)`, com `f` a fatia da renda em exército: 0,15 até 240 s, rampa linear até
  0,65 aos 600 s;
- exército `A ← A + Δt · g · u − D`, com `D` o poder inimigo visto morrer no frame (preço do último
  avistamento) e `g` o poder que a renda de um worker compra por segundo (prior 0,008, σ 0,003, limites
  0,002–0,03).

`g` está **no estado**: o filtro é de `x = (A, g)`, `F = [[1, Δt·u], [0, 1]]`, `H = [1, 0]`,
`Q = diag(0,3, 1,5·10⁻⁸)·Δt`. É isso que o torna adaptativo: uma inovação positiva sobe `A` e `g` pela
covariância cruzada, então um inimigo que produz mais que o prior (a renda trapaceada do CheatInsane) é
aprendido, e um que produz menos também.

**Teto.** `cap = 0,9 · (200 − W)`, o supply que os workers deixam. No teto não há produção, e a variância de
`A` fica limitada a `cap_sigma²` (15²): ninguém planeja contra mais exército do que cabe no supply.

## As medições

Ambas são do poder visto vivo e não visto morrer (`y`), que é um limite inferior do exército, nunca ele todo.

- **Limite inferior.** `A ≥ y` é restrição, não medição de `A`. Com a previsão abaixo dele, a estimativa é
  **projetada** na restrição (o método de projeção do Kalman com restrições): `A = y` e
  `g += P_Ag / P_AA · (y − A)`, com a covariância intacta. Ver 40 Marines vivos diz que o inimigo tem pelo
  menos 40, não que não há mais nada. Como medição de igualdade com `R = 2²` (a primeira versão), o σ caía de
  71 para 2 depois de uma luta, com 10–30 a mais fora de vista.
- **Cobertura.** `c` é a fração das bases inimigas conhecidas (ou do start, sem nenhuma) em visão agora. Com
  `c > 0` e `y < A`, `y` mede `A` por cima com `R = 15² / (c · Δt)`: quanto mais tempo e quanto mais das bases
  dele se olha sem achar o exército, mais se acredita que ele não existe.

O exército visto morrer é entrada conhecida, não medição: sai da estimativa na hora e não custa certeza.

Sem nada visto, a previsão dá 11 aos 300 s, 37 aos 480 s, 74 aos 600 s e o teto (108) aos ~700 s. Nos
replays do `bench/t0`, o exército pago pelo inimigo foi 12–16, 39–60 e 85–109, e pelo próprio bot 4–8, 27–38
e 54–86. A medição que motivou o observador está em
[Medições](../architecture.md#medições).

## Quem lê

[Strategy](../ego/strategy.md) (a avaliação militar e o power spike) e [Economy](../ego/economy.md) (a
composição), pelo `AwarenessState`: `estimated_enemy_power`, `enemy_sigma` e `enemy_army`.

## Parâmetros

`EnemyArmyConfig`, dentro do `AwarenessConfig`, com os valores citados acima.

## No log

`awareness.updated` → `enemy_army` {`power`, `sigma`, `growth`, `growth_sigma`, `production`, `workers`,
`bases`, `known_bases`, `expected_bases`, `coverage`, `cap`, `lost`, `correction` (`none`, `lower_bound`
ou `coverage`)}.

## Limitações conhecidas

- Não há composição por tipo no estado: a composição lê o poder escalar e espalha o não visto pelo visto e
  pelo prior da raça.
- A renda é limitada pelos workers vistos, mas não medida por eles.
- A cobertura só conta as bases conhecidas: o exército no meio do mapa não conta como "olhei e não vi".
- Não há atraso de produção.
- Nenhum parâmetro foi medido com o `tools/replay_truth.py` em partidas jogadas com o observador.

## Código

- [bot/awareness/enemy_army.py](../../bot/awareness/enemy_army.py): `EnemyArmyFilter`, `EnemyArmyBelief`,
  `EnemyArmyConfig`.
