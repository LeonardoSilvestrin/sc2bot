# Offense

> Atacar agora? E, durante o ataque, avançar, lutar ou recuar?

## Resumo

- O **planner** decide *se* há ataque: ele abre a missão quando a postura é PRESSURE ou COMMIT, e pede para
  encerrá-la em DEFEND ou RECOVER.
- A **missão** (`MainAttackMission`) decide *como* o ataque anda. Ela tem sete fases: reunir, avançar,
  buscar, lutar, recuar, reagrupar e retirar.
- Existe no máximo um ataque por vez. Sem missão aberta, a ofensiva está em `IDLE`.
- A missão pede **todas as unidades livres**, com prioridade 0: abaixo da Defense e acima do MapControl.
- A decisão de lutar ou recuar é **local**: o poder do grupo contra o poder inimigo perto dele.

## Entradas e saídas

| | |
| --- | --- |
| Lê | `intent` (postura, motivo, `army_share`, `power_spike`), `awareness` (poder nosso, contatos, estruturas lembradas), `attention` (unidades, visão), o **rally** (o anchor do MapControl neste frame) e o feedback do Engine |
| Entrega | `OffensePlan`: etapa, motivo, bloqueio, alvo, poder comprometido, a luta local e no máximo uma `Proposal` (`ATTACK` ou `RETREAT`, id `offense`) |

## O planner: quando atacar

Sem missão aberta, o planner abre `offense:main_attack:N` quando **tudo** isto vale:

| Condição | Se falhar, `blocked_by` |
| --- | --- |
| Postura em PRESSURE ou COMMIT | `home_threatened` (DEFEND), `recovering` (RECOVER), `no_opportunity` (DEVELOP) |
| Nenhum ataque encerrado nos últimos 30 s (`cooldown`); **em COMMIT não espera** | `cooling_down` |
| Nosso poder ≥ 20 Marines (`minimum_power`) | `army_below_minimum` |

A missão abre com o motivo da postura (`army_advantage`, `power_spike` ou `decisive_advantage`) e guarda o
poder daquele instante como **poder comprometido**.

Com uma missão aberta, o planner só pede o encerramento:

| Postura | O que o planner faz | Efeito |
| --- | --- | --- |
| DEFEND | Pede cancelamento **imediato** (`home_threatened`) | A missão termina no mesmo frame e as unidades ficam livres para a Defense e o MapControl |
| RECOVER | Pede cancelamento **gracioso** (`recovering`) | A missão entra em `WITHDRAW`: recua ao rally e só então termina |
| DEVELOP | Nada | O ataque segue; no próximo `REGROUP` ele termina com `window_closed` |
| PRESSURE, COMMIT | Nada | O ataque segue |

Todo encerramento, por qualquer motivo, reinicia o cooldown.

## A missão: as fases

```text
ASSEMBLE ──▶ ADVANCE ◀────────▶ SEARCH
               │   ▲               │
  parcela ≥ 0,5│   │ fight_won     │ parcela ≥ 0,5
               ▼   │               │
             ENGAGE ◀──────────────┘
               │
               │ parcela < 0,35 (fight_lost)     ADVANCE ou SEARCH com parcela < 0,5
               ▼                                 (unfavorable_fight)
            RETREAT ◀──────────────────────────────────┘
               │
               ▼
            REGROUP ──postura ainda ofensiva──▶ ADVANCE
               └──────senão──▶ FAILED (window_closed)

WITHDRAW: só depois de um cancelamento gracioso; recua ao rally e termina CANCELLED.
```

| Fase | Proposta | Sai quando |
| --- | --- | --- |
| `ASSEMBLE` | nenhuma (o MapControl junta o exército no rally) | 80 % do poder a até 12 do rally (`army_assembled`), ou 45 s depois de abrir (`assemble_timed_out`) → `ADVANCE` |
| `ADVANCE` | `ATTACK` no alvo | luta com parcela ≥ 0,5 → `ENGAGE`; luta com parcela < 0,5 → `RETREAT`; start inimigo visto vazio e nenhuma estrutura conhecida → `SEARCH` |
| `SEARCH` | `ATTACK` numa expansão | estrutura encontrada → `ADVANCE`; luta como em `ADVANCE` |
| `ENGAGE` | `ATTACK` no centro dos inimigos perto | parcela < 0,35 depois de 4 s de luta → `RETREAT`; 3 s sem inimigo perto → `ADVANCE` (`fight_won`) |
| `RETREAT` | `RETREAT` ao rally (sem lutar) | exército reunido no rally, ou 30 s → `REGROUP` |
| `REGROUP` | nenhuma | espera ≥ 10 s e a reunião (até mais 45 s); então, com postura PRESSURE ou COMMIT, volta a `ADVANCE` e **recompromete** com o poder atual; senão termina `FAILED` (`window_closed`) |
| `WITHDRAW` | `RETREAT` ao rally | exército reunido (`withdrawn`) ou 30 s (`withdraw_timed_out`) → `CANCELLED` |

Em qualquer fase, se o poder cair abaixo de 50 % do comprometido, a missão termina `FAILED`
(`army_depleted`). Há no máximo uma transição por frame.

## A luta local

- **Grupo:** as unidades que o Engine deu à ofensiva no frame anterior.
- **Núcleo:** a unidade do grupo com mais poder do grupo a até 16 células dela (`engage_radius`). O
  **grupo do núcleo** são essas unidades.
- **Inimigo perto:** a soma `poder · confiança` dos contatos inimigos com arma (sem workers) a até
  `16 + incerteza` de **alguma** unidade do grupo do núcleo. Assim, um inimigo que atira na frente do grupo
  conta mesmo com o núcleo atrás.
- **Parcela:** `nosso / (nosso + inimigo)`. Com parcela ≥ 0,9 (`won_share`), não é disputa: conta como se não
  houvesse inimigo, e o attack-move resolve no caminho.
- **Histerese:** entra na luta com 0,5 e só recua abaixo de 0,35, depois de 4 s lutando (`engage_dwell`).

## Alvo e busca

- **Alvo:** uma estrutura inimiga lembrada. Primeiro um townhall no chão, depois outra estrutura no chão,
  depois uma voando (que só unidades antiaéreas atacam). Entre as do mesmo tipo, a mais perto do rally. O
  alvo é mantido enquanto for lembrado e não aparecer um tipo melhor, para o exército não ficar trocando.
- **Sem estrutura conhecida:** vai ao start inimigo. Se o start foi visto vazio nos últimos 60 s
  (`search_memory`), a missão entra em `SEARCH`.
- **Busca:** percorre as expansões (start inimigo incluído, nossas bases fora). Primeiro as que estão fora
  de visão há mais de 60 s, a mais perto do grupo antes; depois a que está fora de visão há mais tempo. O
  alvo da busca é mantido até entrar em visão.

## Estado entre frames

- **Planner:** a missão aberta, quando e como a última terminou (para o cooldown e o motivo do `IDLE`) e
  quando cada expansão foi vista pela última vez (para a busca de qualquer ataque).
- **Missão:** fase, desde quando, poder comprometido, alvo mantido, alvo da busca e o último instante com
  inimigo perto.

## Parâmetros (`OffenseConfig`)

| Parâmetro | Valor | Efeito |
| --- | --- | --- |
| `minimum_power` | 20 | Poder mínimo para abrir um ataque |
| `cooldown` | 30 s | Espera depois de qualquer encerramento (COMMIT ignora) |
| `assemble_share` / `assemble_radius` | 0,8 / 12 | Exército reunido: 80 % do poder a até 12 do rally |
| `assemble_timeout` | 45 s | Avança mesmo sem reunir |
| `depleted_share` | 0,5 | Abaixo desta fração do comprometido, o ataque falha |
| `engage_radius` | 16 | Raio da luta local |
| `engage_share` / `retreat_share` | 0,5 / 0,35 | Entra na luta / recua dela |
| `engage_dwell` | 4 s | Tempo mínimo lutando antes de recuar |
| `won_share` | 0,9 | Acima disto, não é disputa |
| `clear_after` | 3 s | Sem inimigo por este tempo, a luta foi ganha |
| `retreat_timeout` | 30 s | Duração máxima de um recuo ou retirada |
| `regroup_dwell` | 10 s | Tempo mínimo reagrupando |
| `search_memory` | 60 s | Um lugar visto há menos que isso não precisa ser buscado |

## No log

- `planner.offense_planned`: `stage`, `reason`, `blocked_by`, `target` e `target_kind`, `committed_power`,
  `fight` (centro, nosso poder, poder inimigo, parcela) e os `inputs` (`assembled_share`, `local_share`,
  `squad_power`, `cooldown_left`…).
- `mission.updated`: abertura, troca de fase, pedido de cancelamento e fim de `offense:main_attack:N`.
- `engine.granted` com `proposal_id = offense`: quanto do exército o ataque realmente tem.

## Limitações conhecidas

- **Reunião medida contra o exército inteiro** (I1 no [gaps.md](../gaps.md), severidade alta): o
  `assembled_share` divide o poder perto do rally pelo poder total, inclusive unidades da Defense ou em
  produção longe. Nos benches ele fica entre 0 e 0,22, e o `ASSEMBLE` quase sempre acaba por timeout.
- **Reforço pinga:** a proposta pede todas as unidades livres, então cada unidade nova vai sozinha até o
  grupo. Pela lei quadrática de Lanchester, reforço que chega aos poucos custa caro (N7.1 em
  [novas_propostas.md](../novas_propostas.md), OS6 em [bots-opensource.md](../bots-opensource.md)).
- **DEFEND cancela na hora**, mesmo com a casa coberta: um DEFEND falso (ver [strategy.md](strategy.md))
  mata um ataque que estava ganhando.
- **O modelo de luta não vê alcance nem feitiço:** nos 6 ataques que terminaram em `army_depleted`, o grupo
  entrou na luta com parcela local de 0,85 a 0,90 e perdeu metade do exército ([debate](../agent_discussion/README.md)).
  Casters e Battlecruisers valem poder 0.
- **O micro é attack-move** (no Body): sem stutter, foco ou esquiva.
- O bot não fecha o jogo: chega ao supply máximo entre 589 e 774 s e termina com 13 a 16 mil minerais no
  banco.

## Código

- [bot/ego/planners/offense/planner.py](../../bot/ego/planners/offense/planner.py): `OffensePlanner`.
- [bot/ego/planners/offense/missions/main_attack.py](../../bot/ego/planners/offense/missions/main_attack.py):
  `MainAttackMission`, `OffenseConfig`, a luta local, o alvo e a busca.
- Execução no Body: [attack.py](../../bot/body/behaviors/attack.py), [retreat.py](../../bot/body/behaviors/retreat.py),
  [combat.py](../../bot/body/behaviors/combat.py).
