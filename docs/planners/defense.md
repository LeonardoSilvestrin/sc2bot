# Defense

> Quem está atacando uma base nossa agora, e quanto exército mandar? E, se for um rush, onde segurá-lo?

## Resumo

- A Awareness agrupa os inimigos ao alcance das nossas bases em **incidentes**. A Defense abre uma missão
  (`DefendAreaMission`) por incidente.
- Cada missão pede ao Engine **poder**, e não um número de unidades: 1,5 vez o poder do incidente, ou 2,0
  vezes com a postura em DEFEND.
- O pedido é separado em parte aérea e parte terrestre, porque só quem atira para cima responde ao ar.
- A prioridade é positiva enquanto há atacante ao alcance, então a Defense sempre passa na frente da Offense
  (0) e do MapControl (−1).
- A missão termina quando a Awareness deixa de reportar o incidente.
- Por cima disso, um **rush** (um ataque que chega antes de o exército poder respondê-lo em campo aberto) abre
  uma `RushDefenseMission`: um Bunker na base que o rush vai atingir, cheio de Marines e reparado por SCVs.
  Uma por vez, aberta pela leitura de rush (`policies/rush.py`), que junta o que a abertura inimiga prometeu
  e a ameaça que uma base sofre agora, e só enquanto a Awareness diz que o early game não acabou.

## Entradas e saídas

| | |
| --- | --- |
| Lê | `awareness.incidents` (os incidentes do frame), `awareness.bases` (`recent_threat`, `pressure`), `awareness.opening` (`aggression`, `proxy`, `confidence`), `intent.posture` e `intent.defense`; da Attention, as bases, os nossos Bunkers (`cargo_used`/`cargo_max`) e o spot de Bunker que o Ares resolveu na natural (`map.bunker_sites`) |
| Entrega | Um `DefensePlan`: até duas `Proposal` por incidente (`defense:<incidente>:air` e `…:ground`), com `ATTACK` no centro do incidente; num rush, `GARRISON` (Marines para o Bunker) e `REPAIR` (SCVs) no Bunker; e o `FortificationPlan`, plano direto do Bunker a construir e dos Bunkers a esvaziar |
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

## Rush: Bunker e reparo

**A leitura** ([policies/rush.py](../../bot/ego/planners/defense/policies/rush.py)), contínua e sem memória
própria:

```text
esperado  = max(aggression, proxy) · confidence          (a abertura inimiga, lida pela Awareness)
presente  = maior recent_threat entre as nossas bases    (o ataque, com a memória de 20 s da Awareness)
early     = awareness.early_game                         (quanto do early game resta, em [0, 1])
rush      = early · (1 − (1 − esperado) · (1 − presente))
```

As duas evidências são independentes: qualquer uma basta. A promessa da abertura enfraquece sozinha, com a
`confidence` dela; a ameaça, com o `threat_memory`. A fase do jogo não é um relógio da Defense: é crença da
Awareness, e só desce (1 até 240 s, linear até 0 aos 420 s, ou 0 na hora em que temos 3 bases). Com o early
game acabado, um ataque é timing e quem responde é o exército: nenhuma defesa de rush abre, e a aberta termina.

**Abrir:** sem missão de rush aberta e com `rush ≥ open_at` (0,5), o planner abre `defense:rush_defense:N` na
base que o rush vai atingir: a natural, se há townhall nela (pronto ou não), com o Bunker no spot que o Ares
resolveu na frente dela (o mais perto da natural, até 15 células; sem spot, perto do próprio townhall); senão a
main, com o Bunker na 3x3 livre mais perto do topo da rampa. A razão é `rush_expected` ou `rush_present`, o
termo maior.

**A missão** ([missions/rush_defense.py](../../bot/ego/planners/defense/missions/rush_defense.py)) é a
operação do Bunker, não a da luta: cada incidente segue com a sua `DefendAreaMission`.

| Fase | O que pede |
| --- | --- |
| `FORTIFY` | Nenhum Bunker nosso pronto a até 12 células do ponto. Sem nenhum de pé, o `FortificationPlan` pede o Bunker. Um sendo construído é esperado (`bunker_building`), sem pedir de novo |
| `HOLD` | Bunker pronto. `GARRISON`: Marines para as vagas livres (`cargo_max − cargo_used`), prioridade 1,0, acima de qualquer incidente (que fica abaixo de 1): os Marines mais perto entram, em vez de sair para o aberto. `REPAIR`: `⌈0,5 · poder dos incidentes a até 15 do Bunker⌉` SCVs, no mínimo 1 se o Bunker está danificado, no máximo 5. Sem dano e sem ataque, nenhum: voltam a minerar |

| De | Para | Quando |
| --- | --- | --- |
| (aberta) | `FORTIFY` | `rush ≥ open_at` (`rush_expected`/`rush_present`) |
| `FORTIFY` | `HOLD` | O Bunker ficou pronto (`bunker_ready`) |
| `HOLD` | `FORTIFY` | O Bunker morreu (`bunker_lost`): pede outro |
| qualquer | `COMPLETED` | `rush < close_at` (0,15) e nenhum atacante pressiona a base (`rush_over`) |
| qualquer | `COMPLETED` | O early game acabou (`early_game_over`), mesmo com a base sob ataque: dali em diante o ataque é só dos incidentes |
| qualquer | `FAILED` | A base não é mais nossa (`base_lost`). No mesmo frame, se a leitura ainda passa de `open_at`, abre outra onde as bases estão agora |

Ao terminar, a missão manda esvaziar o Bunker (`unload`): Marine dentro de Bunker não aparece em lugar nenhum,
e o exército nunca mais o veria. O Bunker fica, e uma defesa de rush seguinte na mesma base luta dele.

**A execução** (Body): `fortify` pede o Bunker ao `BuildStructure` do Ares no conjunto de placements da base,
na 3x3 livre mais perto do ponto, sem procurar em outra base, e só com 100 de minério; o Ares espera o Barracks
e manda um construtor por vez. Roda antes da economia no frame. `garrison` dá a ordem de entrar no Bunker uma
vez só; sem Bunker com vaga, o Marine luta no ponto. `repair` tira o SCV da mineração (role `REPAIRING`), repara
o mais danificado entre estruturas e unidades mecânicas a até 6 do ponto (nunca outro worker) e, sem nada para
reparar, espera junto do Bunker. Quando nenhuma proposta o segura mais, o Engine o libera e ele volta a minerar.

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

As missões abertas, por id de incidente, e o contador que as numera; a defesa de rush aberta (com a tag do
Bunker que segura o ponto), o contador dela e a última leitura de rush.

## Parâmetros

| Parâmetro | Valor | Onde | Efeito |
| --- | --- | --- | --- |
| `COVER_MARGIN` | 1,5 | defend_area.py | Poder pedido por unidade de poder do incidente |
| `DEFEND_COVER_MARGIN` | 2,0 | defend_area.py | A mesma margem com a postura em DEFEND |
| `early_game_until` / `early_game_over` / `early_game_bases` | 240 s / 420 s / 3 | `AwarenessConfig` | O early game, inteiro até 240 s e acabado aos 420 s ou com 3 bases nossas; só desce |
| `open_at` / `close_at` | 0,5 / 0,15 | `RushConfig` | Leitura que abre a defesa de rush, e abaixo da qual ela termina |
| `BUNKER_REACH` | 12 | rush_defense.py | Um Bunker a essa distância do ponto é o do ponto |
| `ATTACK_REACH` | 15 | rush_defense.py | Um incidente com centro a essa distância do Bunker o está atacando |
| `REPAIRERS_PER_POWER` | 0,5 | rush_defense.py | SCVs reparando por Marine de poder atacando o Bunker |
| `MAX_REPAIRERS` | 5 | rush_defense.py | Teto de SCVs reparando |
| `GARRISON_PRIORITY` / `REPAIR_PRIORITY` | 1,0 | rush_defense.py | Acima de qualquer incidente |
| `REPAIR_REACH` | 6 | behaviors/repair.py | O que está a essa distância do ponto é reparado |
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
- `mission.updated` → abertura e fim de cada `defense:defend_area:N`, e as fases de cada
  `defense:rush_defense:N`.
- `planner.fortification_planned` → o Bunker pedido (`bunkers[]`: base, ponto), os Bunkers esvaziados, o que o
  Body entregou ao Ares (`building`), a razão (a da missão, ou `no_rush`) e a leitura (`inputs`: `rush`,
  `rush_expected`, `rush_present`, `early_game`).
- `awareness.updated` → `early_game`; o fim do early game é escrito no frame em que acontece.

## Limitações conhecidas

- **O feedback não é lido.** Uma defesa que recebeu metade do orçamento (`PARTIAL`) segue igual: não escala,
  não chama reforço e não avisa a Strategy (C6 no [gaps.md](../dev/gaps.md)).
- **A cobertura não entra.** A Awareness calcula quanto exército nosso já está na base (`cover`) e a razão
  pressão/cobertura (`balance`), e nada os lê. É o mesmo defeito que faz o DEFEND disparar com 3 Marines de
  pressão diante de 49 de cobertura ([strategy.md](strategy.md#limitações-conhecidas)).
- **Quem conta como atacante:** um worker de scout ou uma estrutura estática abre incidente e pode segurar um
  DEFEND (I2 e I3 no [gaps.md](../dev/gaps.md)). Não se distingue scout, worker rush e ataque.
- **Alcance pela distância reta**, não pelo pathing: um inimigo do outro lado de um penhasco conta.
- O ramo de cancelamento da missão é código morto: o planner nunca pede.
- Ainda faltam: histerese de admissão e liberação, eventos explícitos de linhagem de incidentes (divisão e
  fusão), custo de tirar uma unidade de onde ela está, preempção com compromisso, ciclo de siege próprio da
  defesa e turret pela rota aérea.
- **Rush, sem medição.** Os limiares (`open_at`, `close_at`, o early game de 240–420 s ou 3 bases) e o tamanho do reparo são
  palpites; falta bench contra as aberturas `Rush` das três raças. A leitura `presente` herda o defeito do DEFEND:
  3–4 Marines de pressão cedo já abrem a defesa, com ou sem cobertura na base.
- **Os Marines no Bunker somem do exército.** O Bunker não tem arma própria, e quem está dentro não é listado:
  `own_power` e o `cover` da base caem, e a Defense pede mais poder do que precisa.
- **A luta continua no centro do incidente.** As `DefendAreaMission` não sabem do Bunker: o exército que elas
  puxam pode perseguir o atacante para fora da cobertura dele.
- **Sem worker pull e sem cancelar Bunker em construção.** Também não repara o Bunker antes de ele ficar pronto
  (o jogo não deixa), nem alvos longe do ponto (o CC da natural atacado longe do Bunker). O Bunker não é
  vendido (salvage) depois do rush.
- O spot da main é a 3x3 livre mais perto do topo da rampa: tira uma vaga de produção da main.

## Código

- [bot/ego/planners/defense/planner.py](../../bot/ego/planners/defense/planner.py): `DefensePlanner`.
- [bot/ego/planners/defense/missions/defend_area.py](../../bot/ego/planners/defense/missions/defend_area.py):
  `DefendAreaMission`.
- [bot/ego/planners/defense/missions/rush_defense.py](../../bot/ego/planners/defense/missions/rush_defense.py):
  `RushDefenseMission`.
- [bot/ego/planners/defense/policies/rush.py](../../bot/ego/planners/defense/policies/rush.py): `RushConfig`,
  `read_rush`, `bunker_site`.
- [bot/body/behaviors/fortify.py](../../bot/body/behaviors/fortify.py),
  [garrison.py](../../bot/body/behaviors/garrison.py) e [repair.py](../../bot/body/behaviors/repair.py): o Bunker,
  a guarnição e o reparo.
- [bot/awareness/model.py](../../bot/awareness/model.py): `_pressure`, `_base_threat`, `_incidents`.
