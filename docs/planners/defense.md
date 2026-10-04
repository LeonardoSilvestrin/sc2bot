# Defense

> Quem está atacando uma base nossa agora, e quanto exército mandar?

## Resumo

- A Awareness agrupa os inimigos ao alcance das nossas bases em **incidentes**. A Defense abre uma missão
  (`DefendAreaMission`) por incidente.
- Cada missão pede ao Engine **poder**, e não um número de unidades: 1,5 vez o poder do incidente, ou 2,0
  vezes com a postura em DEFEND.
- O pedido é separado em parte aérea e parte terrestre, porque só quem atira para cima responde ao ar.
- A prioridade é positiva enquanto há atacante ao alcance, então a Defense sempre passa na frente da Offense
  (0) e do MapControl (−1).
- A missão termina quando a Awareness deixa de reportar o incidente.

## Entradas e saídas

| | |
| --- | --- |
| Lê | `awareness.incidents` (os incidentes do frame), `intent.posture` e `intent.defense` |
| Entrega | Até duas `Proposal` por incidente (`defense:<incidente>:air` e `…:ground`), com `ATTACK` no centro do incidente |
| Recebe de volta | O `EngineResult` do frame anterior (passado à missão, mas **não lido**: ver Limitações) |

## De onde vêm os incidentes

Os incidentes são montados pela Awareness ([model.py](../../bot/awareness/model.py)). A Defense não os
calcula, mas tudo o que ela faz depende deles:

1. **Pressão de um contato numa base:** `poder · confiança · K(d, 14 + incerteza)`, onde `K` é um kernel
   gaussiano da distância à base. Só conta dentro de `30 + incerteza` células (`base_reach`). Workers e
   unidades sem arma (poder 0) não contam.
2. **Incidente:** os contatos com pressão em alguma base, ligados em cadeia a até 12 células um do outro
   (`incident_link`). Um grupo pode tocar várias bases.
3. **Identidade:** o id do incidente segue os membros. Cada grupo herda o id do incidente do frame anterior
   com quem mais compartilha contatos. Numa divisão, o id fica com a parte maior; numa fusão, com o
   incidente que traz mais membros. Um grupo sem herança vira `incident:<menor tag>`.
4. **Números do incidente:** poder total, poder aéreo e terrestre (`Σ poder·confiança`), centro ponderado
   pelo poder e `threat = 1 − exp(−maior pressão numa base / 4)`.

A mesma pressão alimenta o `danger` da Awareness, que é o `threat_level` da Strategy. Por isso a Defense e
a postura DEFEND reagem à mesma coisa.

## Como decide

Por frame, para cada incidente reportado:

1. Se não há missão para ele, abre `defense:defend_area:N`. Um id de incidente que volta depois de sumir é
   uma missão nova.
2. **Orçamento:** `margem · poder do incidente`, com margem 1,5, ou 2,0 se a postura é DEFEND.
3. **Partes:** uma proposta para o poder aéreo (`must_attack = AIR`, `minimum_power = margem · poder
   aéreo`) e uma para o terrestre (`must_attack = GROUND`). As duas somam o orçamento e compartilham o
   `demand_id` (o id do incidente). Uma parte com poder zero não é pedida.
4. **Prioridade:** `threat · (0,5 + 0,5 · intent.defense)`. No empate, a parte aérea vem antes (pelo id),
   porque menos unidades atiram para cima.
5. **O Engine escolhe as unidades:** dá primeiro as que a proposta já tinha, depois as mais próximas. Assim, o
   exército que já está na base responde antes de puxar unidades de longe.

Para cada missão cujo incidente não foi reportado neste frame: a missão termina `COMPLETED`
(`incident_over`), e as unidades voltam a ficar livres na alocação do mesmo frame.

## A missão

`DefendAreaMission` tem uma fase só, `DEFENDING`. Ela existe para dar identidade e lifecycle ao incidente
nos logs (`mission.updated`), não para sequenciar nada.

| De | Para | Quando |
| --- | --- | --- |
| (aberta) | `DEFENDING` | A Awareness reporta um incidente novo (`attackers_in_reach`) |
| `DEFENDING` | `COMPLETED` | O incidente não é mais reportado (`incident_over`) |
| `DEFENDING` | `CANCELLED` | Um pedido de cancelamento. **Nunca acontece**: o planner nunca pede |

## Interação com os outros planners

- **Offense:** com a postura em DEFEND, o ataque em curso é cancelado na hora, e as unidades dele ficam
  livres para a Defense no mesmo frame ([offense.md](offense.md)).
- **MapControl:** em DEFEND, o anchor vai para a base mais ameaçada, e o exército que a Defense não pegou
  espera lá ([map-control.md](map-control.md)).
- **Economy:** em DEFEND tudo vai para exército, e na emergência a composição de sobrevivência (SURVIVE)
  treina primeiro o que acerta os atacantes do incidente mais forte ([economy.md](economy.md)).

## Estado entre frames

As missões abertas, por id de incidente, e o contador que as numera.

## Parâmetros

| Parâmetro | Valor | Onde | Efeito |
| --- | --- | --- | --- |
| `COVER_MARGIN` | 1,5 | defend_area.py | Poder pedido por unidade de poder do incidente |
| `DEFEND_COVER_MARGIN` | 2,0 | defend_area.py | A mesma margem com a postura em DEFEND |
| `base_reach` | 30 | Awareness | Até onde um contato pressiona uma base |
| `base_sigma` | 14 | Awareness | Espalhamento da pressão em torno da base |
| `full_pressure` | 4 Marines | Awareness | Pressão que leva a ameaça a `1 − 1/e` |
| `incident_link` | 12 | Awareness | Distância que liga dois atacantes no mesmo incidente |
| `threat_memory` | 20 s | Awareness | Quanto tempo uma base lembra a ameaça (só para o `danger`) |

## No log

- `awareness.updated` → `incidents[]` (id, contatos, centro, poder aéreo e terrestre, ameaça, pressão por
  base) e `bases[]` (`pressure`, `cover`, `balance`, `threat`, `recent_threat`).
- `planner.proposed` → as propostas `defense:<incidente>:air`/`ground` com `inputs` (`threat`, `budget`,
  `cover_margin`, `part_power`…).
- `engine.granted` → o que cada parte recebeu (`granted_power`, `status` `FULL`/`PARTIAL`/`REJECTED`).
- `mission.updated` → abertura e fim de cada `defense:defend_area:N`.

## Limitações conhecidas

- **O feedback não é lido.** Uma defesa que recebeu metade do orçamento (`PARTIAL`) segue igual: não escala,
  não chama reforço e não avisa a Strategy (C6 no [gaps.md](../gaps.md)).
- **A cobertura não entra.** A Awareness calcula quanto exército nosso já está na base (`cover`) e a razão
  pressão/cobertura (`balance`), e nada os lê. É o mesmo defeito que faz o DEFEND disparar com 3 Marines de
  pressão diante de 49 de cobertura ([strategy.md](strategy.md#limitações-conhecidas)).
- **Quem conta como atacante:** um worker de scout ou uma estrutura estática abre incidente e pode segurar um
  DEFEND (I2 e I3 no [gaps.md](../gaps.md)). Não se distingue scout, worker rush e ataque.
- **Alcance pela distância reta**, não pelo pathing: um inimigo do outro lado de um penhasco conta.
- O ramo de cancelamento da missão é código morto: o planner nunca pede.
- Ainda faltam: histerese de admissão e liberação, eventos explícitos de linhagem de incidentes (divisão e
  fusão), custo de tirar uma unidade de onde ela está, preempção com compromisso, ciclo de siege próprio da
  defesa e turret pela rota aérea.

## Código

- [bot/ego/planners/defense/planner.py](../../bot/ego/planners/defense/planner.py): `DefensePlanner`.
- [bot/ego/planners/defense/missions/defend_area.py](../../bot/ego/planners/defense/missions/defend_area.py):
  `DefendAreaMission`.
- [bot/awareness/model.py](../../bot/awareness/model.py): `_pressure`, `_base_threat`, `_incidents`.
