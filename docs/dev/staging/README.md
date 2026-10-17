# Em andamento (staging)

↑ [Desenvolvimento](../README_DEV.md)

O que está sendo feito agora, ou foi decidido e é o próximo. O papel de cada um dos outros documentos, e o
ciclo de um item (daqui para o HEAD), estão no [índice do desenvolvimento](../README_DEV.md).

Um item entra aqui quando se decide fazê-lo, com um arquivo próprio se não couber numa linha. Um
experimento medido e revertido também sai daqui e fica registrado em "Medido e revertido".

## Agora

Estado atual: composição por eficácia (substituiu o catálogo), política SURVIVE e proteção contra
opening parado estão implementadas. [economia-e-builds.md](economia-e-builds.md) é o registro histórico do design.
Os papéis arquiteturais consolidados, sensor coverage contínuo e o pedido compartilhado de
Engineering Bay estão descritos em [architecture.md](../../architecture.md#papéis-arquiteturais).

| Item | Estado | Próximo passo |
| --- | --- | --- |
| Economia e builds | Composição, SURVIVE e opening stall no código | Avaliar desempenho em partidas e os limites restantes de macro |
| Strategy: avaliação e intenção comum | `GameAssessment`, `StrategicIntent` e as posturas RECOVER/DEFEND/DEVELOP/PRESSURE/COMMIT no código, lidas por Economy, Offense, MapControl, Intel e Defense ([planners/strategy.md](../../planners/strategy.md)); sem partidas | Bench 3 seeds × 3 raças contra a última execução medida. Mudou o gatilho do ataque (antes `army_share ≥ 0,5` ou supply 190; agora PRESSURE/COMMIT), a expansão (não em RECOVER/COMMIT), o teto de produção (5/base em PRESSURE/COMMIT), o staging (0,8 em PRESSURE/COMMIT, 0 em RECOVER), a reserva de scan e a margem da defesa (2,0 em DEFEND). Olhar `strategy.posture_changed` para trocas por minuto e o tempo em cada postura. Primeira medição: `bench/t0` (`9457a4a`), DEFEND 42–45 % do tempo nas derrotas, PRESSURE só por `power_spike`, COMMIT nunca |
| **Composição por eficácia** ([estimacao-e-controle.md](estimacao-e-controle.md#composição-por-eficácia)) | No working tree: catálogo de counters substituído pelo modelo de combate (`knowledge/combat.yml`, dados do cliente no `on_start`) e pelo portfólio log-ótimo com a doutrina do estilo como prior; lê o observador. Sem bench | Bench 3 seeds × 3 raças × bio/mech contra a última execução medida; olhar `planner.economy_planned` (`enemy[].answers`, `doctrine`, `mix`) e `knowledge.combat_model.changed` |
| **Resposta a rush** ([planners/defense.md](../../planners/defense.md#rush-bunker-e-reparo)) | No working tree: `RushDefenseMission` (Bunker na natural ou no topo da rampa, guarnição de Marines, reparo por SCVs), leitura de rush contínua (`policies/rush.py`), comandos `GARRISON`/`REPAIR` e o behavior `fortify`. Sem bench | Bench 3 seeds × 3 raças contra a abertura `Rush`, contra a última execução medida; olhar `planner.fortification_planned`, as fases de `defense:rush_defense:N`, workers e bases nos primeiros 6 min, e quantas defesas abrem contra `Macro` (falso positivo) |
| **Estimação e controle** ([estimacao-e-controle.md](estimacao-e-controle.md)) | Virada de direção. Passo 1 no HEAD: observador do exército inimigo (`bot/awareness/enemy_army.py`), sem bench; rollback na tag `pre-observador` | Bench contra o `bench/t0` e `tools/replay_truth.py` (erro, `nees`, tempo à frente); depois DEFEND em cascata e a lei de gasto contínua |

## Depois

Não decidido. O que vem depois está no [backlog](../backlog.md), do mais urgente ao menos: não perder por
crash, medir, o que conta como ameaça (I2, I3) e fechar o jogo (I1, N7.1).
