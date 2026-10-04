# Strategy

> Como está a partida, e o que o bot quer agora?

A Strategy não é um planner: não pede unidades, não escolhe lugar e não manda nada para o jogo. Ela
produz o **contexto comum** que todos os planners leem, o `StrategicIntent`. O que cada postura significa
para a economia, o ataque ou o anchor é decisão de cada planner ([tabela](README.md#a-postura-em-cada-planner)).

## Resumo

- **Passo 1, avaliação** (`GameAssessment`): transforma o que a Awareness acredita em números contínuos.
  São eles: ameaça em casa, quem tem mais exército, quem perdeu exército há pouco, power spike e quanto da
  estimativa do inimigo foi de fato visto.
- **Passo 2, postura**: faz quatro perguntas em ordem (DEFEND, RECOVER, COMMIT, PRESSURE). A primeira
  respondida "sim" vence. Se nenhuma for, a postura é DEVELOP.
- **Passo 3, preferências**: quatro números contínuos (`defense`, `army`, `economy`, `risk`) que alguns
  planners leem.
- Tem histerese em dois níveis: em cada pergunta e na postura.

## Entradas e saídas

| | |
| --- | --- |
| Lê | `AttentionState` (mortes do frame, upgrades, supply, bases) e `AwarenessState` (ameaça por base, poder nosso, estimativa do exército inimigo e σ do observador) |
| Entrega | `StrategicIntent`: `posture`, `previous`, `since`, `reason`, `because`, `assessment`, `emergency`, `defense`, `army`, `economy`, `risk`, `gates` |
| Quem lê | Todos os planners (`posture`); Defense (`defense`); Economy (`economy`, `emergency`); Offense (`reason`, `army_share`, `power_spike`) |

## Passo 1: a avaliação

Todos os valores são contínuos. Os do inimigo são sempre estimativa.

| Sinal | Fórmula | Em palavras |
| --- | --- | --- |
| `threat_level` | `danger` da Awareness | A ameaça lembrada na base mais ameaçada, em [0, 1]. Vem só da **pressão** dos atacantes, sem descontar o nosso exército que está lá (ver Limitações) |
| `army_position` | `(nosso − planejado) / (nosso + planejado + 20)` | Quem tem mais exército, em [−1, 1]. O inimigo planejado é `μ + 0,5σ` do observador: a névoa não é vantagem. Os 20 Marines de dúvida impedem que uma escaramuça vire veredito |
| `army_share` | `(1 + army_position) / 2` | A mesma coisa em [0, 1] |
| `economy_position` | `(nossas bases − bases inimigas) / soma` | Bases contra bases acreditadas. **Nenhuma postura lê** |
| `enemy_vulnerability` | `perdido / (perdido + estimado)` | Quanto do exército inimigo morreu à nossa vista há pouco (memória de 30 s) |
| `setback` | `perdido / (perdido + nosso)`, vezes `min(1, 2·perdido / (perdido + perdido inimigo))` | Quanto do nosso exército morreu há pouco. Conta inteiro numa troca igual ou pior, e menos quanto melhor foi a troca |
| `power_spike` | `1 − (1 − upgrades)(1 − supply)` | Um upgrade recém-concluído (decai em 60 s) ou o supply perto do teto (rampa de 170 a 190): momentos em que vale atacar |
| `confidence` | `max(conhecido, visto vivo) / estimado` | Quanto da estimativa do inimigo vem de avistamento, e não do modelo |

## Passo 2: a postura

As perguntas são feitas nesta ordem, e a primeira com o gate aberto vence:

| # | Postura | Pergunta | Score `s` |
| --- | --- | --- | --- |
| 1 | DEFEND | A casa está ameaçada? | `threat_level` |
| 2 | RECOVER | O exército levou um revés, ou estamos muito atrás? | `1 − (1 − setback)(1 − confidence · max(0, −army_position))` |
| 3 | COMMIT | Vantagem decisiva? | `safety · sqrt(max(0, army_position) · enemy_vulnerability)` |
| 4 | PRESSURE | Há uma janela? | `safety · max(army_share, min(1, 2·army_share) · power_spike)` |
| — | DEVELOP | Nenhuma das anteriores | — |

`safety = 1 − threat_level`. RECOVER só conta o déficit na medida em que ele foi visto (`confidence`). O
power spike vale inteiro com exército igual ou maior e some quando o `army_share` vai a zero.

**Histerese em cada pergunta (gate).** Cada pergunta é um gate que abre com `s ≥ 0,55` e fecha com
`s ≤ 0,45` (`switch_margin` 0,1 em torno de 0,5). O gate do DEFEND também espera 8 s (`minimum_dwell`)
antes de virar, mas abre na hora com `threat_level ≥ 0,6` (`emergency_danger`). No primeiro frame, um
empate abre os gates conservadores (DEFEND, RECOVER).

**Histerese na postura.** A postura nunca volta para a que ela acabou de substituir antes de 15 s
(`stance_dwell`). Ir para uma terceira postura não espera (PRESSURE pode escalar para COMMIT). DEFEND é
isento nos dois sentidos: entra na hora e sai pelo próprio gate.

**Emergência.** Fica travada enquanto o bot está em DEFEND depois de ter visto `threat_level ≥ 0,6`, e
solta ao sair de DEFEND. A Economy usa a emergência para interromper a abertura e ligar o SURVIVE.

**Motivo da troca** (`reason`):

| Postura | Motivos |
| --- | --- |
| DEFEND | `home_threatened`, `emergency_threat` (abriu sem esperar o dwell) |
| RECOVER | `army_setback` (perdas) ou `outmatched` (déficit visto) |
| COMMIT | `decisive_advantage` |
| PRESSURE | `army_advantage` ou `power_spike` |
| DEVELOP | pelo que deixou: `threat_cleared`, `recovered`, `window_closed`, `no_opportunity` |

## Passo 3: as preferências

| Campo | Fórmula | Quem lê |
| --- | --- | --- |
| `defense` | `danger` | Defense (prioridade das propostas); a Economy só o registra nos `inputs` |
| `army` | `clamp(0,3 + 0,5·danger + 0,4·(0,5 − army_share))` | ninguém diretamente (é o complemento de `economy`) |
| `economy` | `1 − army` | Economy: só expande com `economy ≥ 0,5` |
| `risk` | `army_share · (1 − danger)` | **ninguém**: só aparece nos `inputs` do MapControl, no log |

## Estado entre frames

- `AssessmentModel`: o poder por tag do frame anterior (para dar preço a uma morte), as perdas lembradas
  dos dois lados e quando cada upgrade terminou.
- `StrategyModel`: o estado de cada gate (aberto, desde quando), a postura atual, a anterior, desde quando
  e a emergência.

## Parâmetros

| Parâmetro | Valor | Efeito |
| --- | --- | --- |
| `switch_margin` | 0,1 | Largura da histerese de cada gate (abre em 0,55, fecha em 0,45) |
| `minimum_dwell` | 8 s | Tempo mínimo antes de o gate do DEFEND virar |
| `emergency_danger` | 0,6 | Ameaça que abre o DEFEND sem esperar e trava a emergência |
| `stance_dwell` | 15 s | Tempo antes de voltar à postura anterior |
| `sigma_margin` | 0,5 | Quantos σ do observador entram no inimigo planejado |
| `prior_power` | 20 Marines | Dúvida somada aos dois lados em `army_position` |
| `loss_memory` | 30 s | Constante de tempo das perdas lembradas |
| `upgrade_window` | 60 s | Constante de tempo do spike de um upgrade |
| `supply_spike_from` / `maxed_supply` | 170 / 190 | Rampa do spike de supply |

## No log

- `strategy.posture_changed`: toda troca, com `summary` numa linha (por exemplo,
  `DEVELOP -> DEFEND (home_threatened): threat=HIGH threat_level=0.71 army_position=-0.18`), `because`
  e o score de cada gate.
- `strategy.decided`: heartbeat com a avaliação inteira, as preferências e os `inputs` (poder nosso,
  estimado, σ, bases).
- O viewer ([logs/viewer.html](../../logs/viewer.html)) mostra a trilha das posturas na Decision Timeline.

## Limitações conhecidas

- **O DEFEND ignora a cobertura.** `threat_level` vem da pressão bruta: cerca de 3 Marines de pressão abrem o
  DEFEND, mesmo com 49 de cobertura na base. A Awareness calcula `cover` e `balance`, e nada os lê. Isso
  cancelou ataques que estavam ganhando (`comp-eficacia/001` e `004`, ver
  [debate](../dev/agent_discussion/README.md)).
- **Postura instável:** 37 trocas em 1.249 s no `comp-eficacia/004`. Cada troca mexe na economia, no anchor
  e no ataque ao mesmo tempo.
- **Sinais sem leitor:** `risk`, `economy_position` e a leitura da abertura da Awareness
  (`aggression`, `greed`, `tech`) não mudam nenhuma decisão.
- Nenhum limiar, peso ou `stance_dwell` foi medido em partida. As posturas foram ajustadas contra o prior
  antigo do inimigo, que nunca deixava `army_position` positivo, e nenhum gate foi revisto depois do
  observador.
- `enemy_vulnerability` só vê mortes à nossa vista. Exército inimigo fora de posição, bases desprotegidas,
  defesa estática e troca de tech não entram.
- `power_spike` conhece upgrades e supply. Não conhece tech nova, composição contra o inimigo nem ciclos
  de produção.
- `confidence` mede avistamento, não frescor: um exército visto há 3 minutos ainda conta como evidência.

## Código

- [bot/ego/strategy/model.py](../../bot/ego/strategy/model.py): contratos (`GameAssessment`,
  `StrategicIntent`, `StrategicPosture`, `PostureGate`).
- [bot/ego/strategy/assessment.py](../../bot/ego/strategy/assessment.py): `AssessmentModel`.
- [bot/ego/strategy/strategy.py](../../bot/ego/strategy/strategy.py): `StrategyModel`, gates e postura.
