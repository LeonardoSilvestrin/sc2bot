# StructureControl

> O que nossas estruturas fazem sozinhas: depots e tirar uma estrutura do caminho de um Siege Tank.

## Resumo

- **Depots:** um depot pronto sobe quando um inimigo terrestre chega perto e desce depois que nenhum esteve
  perto por 3 s.
- **Relocation:** quando um Siege Tank fica preso por uma Barracks, Factory ou Starport nossa, essa
  estrutura levanta voo, espera o Tank sair e pousa fora do caminho.
- **Corredor da rampa:** no `on_start`, os sites de produção no caminho entre o nosso start e a rampa da main
  são marcados como ocupados no placement do Ares, que não constrói neles.
- Não pede unidades ao Engine: o plano (`StructurePlan`) vai direto ao Body. A relocation tem episódios
  (levanta, espera, pousa), mas opera estruturas que o Engine não arbitra, então é policy e não missão.
- A relocation e os depots não leem um ao outro.

## Entradas e saídas

| | |
| --- | --- |
| Lê | `attention`: nossas estruturas e unidades, inimigos visíveis, o mapa e os sites de produção |
| Entrega | `StructurePlan`: `lower` e `raise_` (depots por tag), `lift` (estruturas a levantar), `land` (estrutura e site de pouso) e os eventos da relocation |

## Depots

1. Um depot pronto **sobe** no frame em que um inimigo terrestre visível está a até 8 células
   (`raise_reach`). Voadores não contam, porque o depot não os para.
2. Ele **desce** quando nenhum inimigo terrestre esteve a essa distância por 3 s (`lower_after`). Um
   inimigo andando na borda do alcance não consegue fazer o depot subir e descer mais rápido que isso.
3. Subir empurra as nossas unidades de cima para a borda (o plano conta quantas, em
   `friendly_on_raising`). Um inimigo em cima impede a subida, e o Body repete a ordem.

Motivos no log: `no_depots`, `enemy_near`, `enemy_recently_near`, `no_enemy_near`.

## Relocation

**Quando um Tank está preso.** O Siege Tank (fora de siege) tem ordem para um ponto a mais de 3 células e
ficou a até 1,5 do mesmo lugar por 4 s. Não contam:

- Tank parado ou esperando no ponto;
- Tank em siege;
- Tank com inimigo visível a até 12 células.

Um frame sem ordem por até 1 s não zera a contagem: o jogo derruba a ordem sem caminho e o behavior a repete.

**Quem bloqueia.** Uma Barracks, Factory ou Starport pronta e pousada:

- **à frente:** com o centro à frente do Tank e o footprint a até 1,5 das próximas 4 células rumo ao
  ponto;
- **cercando:** sem nenhuma à frente, o Tank nasceu num bolso de produção, penhasco e doodads. O bloqueador
  é então uma estrutura cujo footprint ou add-on fica a até 1,25 do centro do Tank.

Entre os candidatos, a sem add-on vem primeiro (levantar deixa o add-on para trás), depois a mais perto. O
Command Center nunca se move.

**O episódio, uma relocation por vez:**

```text
tank_stuck ─▶ blocker_selected ─▶ lifting ─▶ tank_moving / tank_gone ─▶ relocating ─▶ landing ─▶ relocation_complete
                                     │                                     │
                                     └─ relocation_aborted (lift_failed)   └─ no_landing_site: tenta de novo;
                                                                              depois de 30 s pousa na origem
```

1. **Levanta**, repetindo a ordem a cada frame até voar. O jogo recusa o lift atrás do que a estrutura ainda
   treina, e o Ares enche de novo a estrutura ociosa. Enquanto isso, a Economy não treina nem põe add-on
   nela.
2. **Espera** o Tank andar 1,5 células, sumir (morto ou em siege) ou passarem 8 s.
3. **Pousa** no site de produção livre mais perto da origem, na main ou em outra base nossa, cujo footprint
   (com o do add-on) fique a ≥ 2,5 do caminho do Tank e do corredor da rampa.
4. Sem site, fica no ar e procura de novo a cada 5 s. Depois de 30 s volta para a origem, se ela estiver
   livre: no ar a estrutura não treina e segura todas as outras relocations.
5. Um site não alcançado em 25 s é trocado pelo próximo.
6. Depois de cada relocation, 20 s sem outra; a mesma estrutura só levanta de novo 90 s depois.

## Estado entre frames

- **Depots:** quando um inimigo terrestre esteve perto pela última vez, por depot.
- **Relocation:** o rastreio de cada Tank (onde parou, desde quando), a relocation em curso (estrutura, Tank,
  fase, site) e os cooldowns.

## Parâmetros

| Parâmetro | Valor | Efeito |
| --- | --- | --- |
| `raise_reach` | 8 | Distância de um inimigo terrestre que sobe o depot |
| `lower_after` | 3 s | Tempo sem inimigo para descer |
| `arrive_distance` / `progress_distance` / `stuck_after` | 3 / 1,5 / 4 s | Quando um Tank está preso |
| `combat_reach` | 12 | Tank com inimigo perto não conta como preso |
| `order_grace` | 1 s | Frame sem ordem que não zera a contagem |
| `look_ahead` / `blocker_reach` | 4 / 1,5 | Bloqueador à frente |
| `hem_reach` | 1,25 | Bloqueador que cerca |
| `lift_timeout` / `wait_timeout` | 6 s / 8 s | Desiste do lift / para de esperar o Tank |
| `lane` | 2,5 | Folga do caminho do Tank e do corredor da rampa |
| `land_retry` / `return_after` / `land_timeout` | 5 s / 30 s / 25 s | Pouso |
| `global_cooldown` / `structure_cooldown` | 20 s / 90 s | Espera entre relocations |

## No log

- `planner.structures_planned`: depots a subir e descer, com motivo e `inputs` (`enemy_near`,
  `nearest_ground_enemy`, `friendly_on_raising`).
- `planner.structure_relocation`: cada passo da relocation (`transition`, `reason`, `tank`, `structure`,
  `site` e `at`, onde o Tank estava).
- `planner.production_kept_clear`: no `on_start`, os sites do corredor da rampa.

## Limitações conhecidas

- **A relocation resolve pouco:** nos benches houve 127 `tank_stuck`, só 11 com `blocker_selected` (9 %) e 64
  `no_blocker` ([debate](../agent_discussion/README.md)). A causa é o placement do Ares, que empacota a
  produção Terran sem corredores e faz Tanks nascerem cercados. A relocation é um remendo; o caminho seria
  atacar o placement ou retirá-la.
- O wall ainda não antecipa o fechamento por contato lembrado ou pela rota, não usa a velocidade do inimigo,
  não distingue os depots do wall e não tem política para unidades nossas presas do lado de fora.

## Código

- [bot/ego/planners/structure_control/planner.py](../../bot/ego/planners/structure_control/planner.py):
  `StructureControlPlanner`, `StructureConfig`, os depots.
- [bot/ego/planners/structure_control/policies/relocation.py](../../bot/ego/planners/structure_control/policies/relocation.py):
  `Relocator`, `RelocationConfig`.
- Execução no Body: [structure_control.py](../../bot/body/behaviors/structure_control.py).
