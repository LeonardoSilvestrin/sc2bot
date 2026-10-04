# Intel

> O que precisamos ver, e com o quê: scout, scan ou torre?

## Resumo

O Intel junta quatro mecanismos num único `IntelPlan`:

| Mecanismo | Tipo | O que faz |
| --- | --- | --- |
| **Scout inicial** | Missão (`EarlyScoutMission`) | Um SCV lê a abertura inimiga e, se a Awareness suspeitar, procura proxy |
| **Detecção** | Policy (`Detection`) | Scan contra unidade camuflada, reserva de energia nos Orbitais, Missile Turrets |
| **Barreira de radar** | Desired state (`sensor_towers`) | Sensor Towers que fecham todas as nossas bases pelo ar, a partir de 4 bases |
| **Engineering Bay** | Pedido consolidado | Um só pedido, se a detecção ou as torres precisarem |

O foco do Intel (`focus`) segue a postura:

| Postura | `focus` | Efeito |
| --- | --- | --- |
| DEFEND | `threat` | Nenhum scout sai; todo Orbital guarda energia para um scan |
| PRESSURE, COMMIT | `offense` | Todo Orbital guarda energia para um scan |
| DEVELOP, RECOVER | `economy` | Orbitais guardam scan só depois de ter visto unidade camuflada |

## Entradas e saídas

| | |
| --- | --- |
| Lê | `attention` (workers, visão, mapa, a gravação da abertura inimiga, estruturas e Orbitais), `awareness` (`opening`: a leitura da abertura; contatos escondidos; `cloak_seen_at`), `intent.posture` e o feedback do Engine |
| Entrega | `IntelPlan`: `proposals` (o pedido do SCV), `detection`, `sensor_towers`, `engineering_bay`, `focus`, `scout` (o relatório do scout para o log) |

## O scout inicial

### Quando sai

O planner abre `intel:early_scout:N` quando há **16 workers ou mais**, **antes de 240 s** e fora de DEFEND.
Se o SCV ainda não saiu:

- aos 240 s, o planner cancela (`too_late`);
- se os workers caem abaixo de 16, cancela (`workers_below_threshold`), e esse é o único motivo que deixa
  abrir outro scout depois.

Um scout que saiu nunca é reposto. Ao terminar, o SCV volta para a mineração.

### As fases

```text
REQUESTING ─▶ CHECK_NATURAL ─▶ ENTER_MAIN ─▶ CIRCLE_MAIN ─▶ RECHECK_NATURAL ─▶ CHECK_THIRD ─▶ SURVEIL ─▶ COMPLETE
                                    (PROXY_SEARCH a qualquer momento, quando o planner manda)
```

| Fase | O que faz | Sai quando |
| --- | --- | --- |
| `REQUESTING` | Pede um SCV | O SCV sai (`scout_set_out`) |
| `CHECK_NATURAL` | Olha a natural inimiga no caminho | Natural checada, ou 30 s depois de chegar |
| `ENTER_MAIN` | Entra na main | Main à vista, ou 30 s |
| `CIRCLE_MAIN` | Circula a main pelos 8 setores da borda, vendo produção, gás, tech e unidades | Volta completa, ou 60 s. Se a natural estava vazia e já deu tempo de recheck, vai para `RECHECK_NATURAL`; senão para `CHECK_THIRD` |
| `RECHECK_NATURAL` | Volta à natural vista vazia, 25 s depois, para fechar a janela em que ela subiu | Natural vista de pé, ou vista vazia de novo, ou 30 s |
| `CHECK_THIRD` | Confirma a third | Third vista de pé ou vazia, ou passou da janela da third da raça |
| `SURVEIL` | Ronda: vai sempre ao lugar visto há mais tempo (natural, third, saídas da main, a main) | A leitura da abertura passa de confiança 0,75 (`opening_read`) |
| `PROXY_SEARCH` | Percorre até 6 lugares da nossa metade do mapa onde caberia um proxy | Proxy encontrado, rota completa ou 60 s |

A missão também termina:

- `FAILED`, se o SCV morre (`scout_lost`);
- `COMPLETED`, quando a janela da abertura fecha aos 300 s (`opening_over`);
- `COMPLETED`, se não sobrar lugar alcançável (`nowhere_left_to_look`).

**Por que a ronda acaba com a confiança:** um scout só vale enquanto a leitura está fraca. Três bases de pé
e nenhuma estrutura de exército é uma leitura, não uma lacuna, e o SCV vale mais minerando.

**A missão não registra nada.** O que o scout põe à vista, a Attention grava
([opening.py](../../bot/attention/opening.py)) e a Awareness interpreta (`OpeningBelief`). As fases leem
essa gravação.

**Prioridade do pedido:** de 0,5 (`SURVEIL`) a 1,0 (`CHECK_NATURAL`, `PROXY_SEARCH`). Na `CIRCLE_MAIN` ela
cai com a fração da volta já vista. Como o pedido é de um worker, ele não disputa exército.

### Busca de proxy

O planner manda o scout procurar proxy **uma vez**, quando a Awareness lê `proxy ≥ 0,55` com confiança
≥ 0,3. A suspeita é da Awareness, e onde procurar é da policy [proxy.py](../../bot/ego/planners/intel/policies/proxy.py):
os bolsos ao lado da nossa main e da natural, e as expansões da nossa metade, da main para fora, até 6
lugares.

## Detecção

1. **Scan:** um contato escondido (camuflado ou enterrado, sem detecção) à vista é escaneado quando há
   pelo menos 2 de poder nosso a até 10 células dele e algum Orbital tem 50 de energia. Contatos já
   cobertos por um scan dos últimos 12,3 s (raio 13) são pulados. Entre vários, escolhe o com mais exército
   perto, depois o que revela mais poder escondido.
2. **Reserva:** depois de ver unidade camuflada, ou com o `focus` pedindo, cada Orbital guarda 50 de energia
   (o MULE só sai com ≥ 100).
3. **Turrets:** só depois de ver unidade camuflada. Cada base sem Missile Turret a até 15 células pede uma.
   Sem Engineering Bay, pede uma.

Motivos no log: `no_cloak_seen`, `no_hidden_enemy`, `hidden_enemy_scanned`, `no_army_near_hidden`,
`no_scan_energy`, `scan_hidden_enemy`.

## Barreira de radar (Sensor Towers)

- Liga quando o bot chega a **4 bases** e continua ligada mesmo se as bases caírem.
- **Objetivo:** nenhuma base nossa alcançável pelo ar, a partir do start inimigo, sem passar por radar. O ar
  ignora o terreno, então isso é julgado na área jogável inteira.
- Cada base fica dentro do raio de uma torre, ou atrás de uma cadeia de raios sobrepostos que vai de uma
  borda do mapa à outra.
- O raio é **22**, o `radar_range` que o jogo reporta.
- O planner pede o **menor número de torres novas** que fecha a barreira. Ele usa Dijkstra sobre os spots
  2x2 que o Ares resolveu nas nossas bases, main incluída, e conta as torres de pé e as inacabadas.
- Entre cadeias do mesmo tamanho, puxa para o lado do inimigo e evita sobreposição. Uma base que nenhuma
  cadeia fecha ganha uma torre própria.

## Estado entre frames

- **Planner:** a rota do scout (start inimigo e o ponto mais distante de cada um dos 8 setores da main), a
  rota de proxy, as saídas da main inimiga, os waypoints já vistos, a missão aberta, por que o scout acabou,
  quando a busca de proxy foi mandada e se a barreira já foi liberada.
- **Detecção:** os scans recentes (posição e instante).
- **Missão:** fase, alvo, chegada e o índice da rota de proxy.

## Parâmetros

| Parâmetro | Valor | Efeito |
| --- | --- | --- |
| `SCOUT_AT_WORKERS` | 16 | Workers para o scout sair |
| `START_BY` | 240 s | Depois disso nenhum scout sai |
| `PROXY_SEARCH_AT` / `PROXY_CONFIDENCE_AT` | 0,55 / 0,3 | Leitura de proxy que manda procurar |
| `READ_ENOUGH` | 0,75 | Confiança da leitura que encerra a ronda |
| `ScoutWindow` | recheck 25 s; check 30 s; circle 60 s; search 60 s; travel 75 s; passo da ronda 20 s; abertura até 300 s | O relógio do scout. A janela da third vem da raça inimiga |
| `scan_reach` / `scan_min_power` | 10 / 2 | Exército perto que justifica um scan |
| `scan_radius` / `scan_duration` | 13 / 12,3 s | Área e duração de um scan |
| `scan_reserve` | 50 | Energia guardada por Orbital |
| `turret_cover` | 15 | Distância que uma turret cobre uma base |
| `MIN_BASES` | 4 | Bases que liberam a barreira de radar |
| `RADAR_RADIUS` | 22 | Raio da Sensor Tower |

## No log

- `opening_scout.phase_changed` e `opening_scout.proxy_search_started`: as fases do scout, com motivo e
  alvo.
- `awareness.opening_updated`: a leitura da abertura (`aggression`, `greed`, `tech`, `proxy`,
  `confidence`) e o que foi visto.
- `planner.detection_planned` e `behavior.intel_executed`: scans, turrets e Engineering Bay.
- `planner.sensor_towers_planned`: as torres que faltam.

## Limitações conhecidas

- **Os blips das nossas Sensor Towers derrubam o bot contra Terran.** O Ares não filtra blips de radar, e um
  blip de unidade camuflada ou enterrada vira um inimigo de tipo 0 que levanta `KeyError: 0` no
  `GridManager`. Os 2 crashes do `bench/t0` foram assim. Nenhuma decisão lê os blips, então as torres hoje
  só custam gás e risco (item 1 do [debate](../agent_discussion/README.md)).
- **Nada depois da abertura:** o SCV sai uma vez, antes de 240 s, e a ronda acaba com a janela da abertura.
  Não há scan de informação, Raven nem scout no meio do jogo. O observador do exército inimigo fica sem
  medição nova das bases inimigas.
- A Strategy não consome a leitura da abertura. Na partida contra o PhantomBot, a Awareness disse "an all-in
  is coming" aos 3:08 e nada mudou.
- Nenhum limiar ou peso da leitura da abertura foi medido em partida.

## Código

- [bot/ego/planners/intel/planner.py](../../bot/ego/planners/intel/planner.py): `IntelPlanner`, rota do
  scout, foco por postura.
- [bot/ego/planners/intel/missions/early_scout.py](../../bot/ego/planners/intel/missions/early_scout.py):
  `EarlyScoutMission`.
- [bot/ego/planners/intel/policies/detection.py](../../bot/ego/planners/intel/policies/detection.py),
  [proxy.py](../../bot/ego/planners/intel/policies/proxy.py),
  [sensor_towers.py](../../bot/ego/planners/intel/policies/sensor_towers.py).
- Execução no Body: [scout.py](../../bot/body/behaviors/scout.py),
  [detection.py](../../bot/body/behaviors/detection.py),
  [sensor_towers.py](../../bot/body/behaviors/sensor_towers.py), [intel.py](../../bot/body/behaviors/intel.py).
