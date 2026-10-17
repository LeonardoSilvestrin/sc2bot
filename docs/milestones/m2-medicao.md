# M2 — Medição

↑ [Marcos](README_MILESTONES.md)

**Objetivo:** um bench da planta atual, com as métricas que mostram uma mudança antes do placar, e um veredito
para tudo que entrou no HEAD sem bench.

**Critério de saída:** ≥ 18 partidas decididas por raça, com intervalo de Wilson por raça; cada item de
[Em andamento](#em-andamento-no-código-sem-bench) fica (a medição vai para "Medições" do
[architecture.md](../architecture.md#medições)) ou é revertido e registrado aqui.

**Depende de:** [M1](m1-estabilidade.md) (partidas que terminam).

## Em andamento: no código, sem bench

Estado atual: composição por eficácia (substituiu o catálogo), política SURVIVE e proteção contra opening parado
estão implementadas. Os papéis arquiteturais consolidados, sensor coverage contínuo e o pedido compartilhado de
Engineering Bay estão descritos em [architecture.md](../architecture.md#papéis-arquiteturais).

| Item | Estado | Próximo passo |
| --- | --- | --- |
| **Economia e builds** ([registro](registros/economia-e-builds.md)) | Composição, SURVIVE e opening stall no código | Avaliar desempenho em partidas; o que falta de macro está no [M7](m7-economia.md) |
| **Strategy: avaliação e intenção comum** ([strategy.md](../ego/strategy.md)) | `GameAssessment`, `StrategicIntent` e as posturas RECOVER/DEFEND/DEVELOP/PRESSURE/COMMIT no código, lidas por Economy, Offense, MapControl, Intel e Defense; sem partidas | Bench 3 seeds × 3 raças contra a última execução medida. Mudou o gatilho do ataque (antes `army_share ≥ 0,5` ou supply 190; agora PRESSURE/COMMIT), a expansão (não em RECOVER/COMMIT), o teto de produção (5/base em PRESSURE/COMMIT), o staging (0,8 em PRESSURE/COMMIT, 0 em RECOVER), a reserva de scan e a margem da defesa (2,0 em DEFEND). Olhar `strategy.posture_changed` para trocas por minuto e o tempo em cada postura. Primeira medição: `bench/t0` (`9457a4a`), DEFEND 42–45 % do tempo nas derrotas, PRESSURE só por `power_spike`, COMMIT nunca |
| **Composição por eficácia** ([registro](registros/estimacao-e-controle.md#composição-por-eficácia-working-tree-sem-bench)) | Catálogo de counters substituído pelo modelo de combate (`knowledge/combat.yml`, dados do cliente no `on_start`) e pelo portfólio log-ótimo com a doutrina do estilo como prior; lê o observador | Bench 3 seeds × 3 raças × bio/mech contra a última execução medida; olhar `planner.economy_planned` (`enemy[].answers`, `doctrine`, `mix`) e `knowledge.combat_model.changed` |
| **Resposta a rush** ([defense.md](../ego/planners/defense.md#rush-bunker-e-reparo)) | `RushDefenseMission` (Bunker na natural ou no topo da rampa, guarnição de Marines, reparo por SCVs), leitura de rush contínua (`policies/rush.py`), comandos `GARRISON`/`REPAIR` e o behavior `fortify` | Bench 3 seeds × 3 raças contra a abertura `Rush`, contra a última execução medida; olhar `planner.fortification_planned`, as fases de `defense:rush_defense:N`, workers e bases nos primeiros 6 min, e quantas defesas abrem contra `Macro` (falso positivo) |
| **Observador do exército inimigo** ([registro](registros/estimacao-e-controle.md)) | `bot/awareness/enemy_army.py` no HEAD; rollback na tag `pre-observador` | Bench contra o `bench/t0` e `tools/replay_truth.py` (erro, `nees`, tempo à frente), como em [Como medir](registros/estimacao-e-controle.md#como-medir); calibrar os parâmetros com o replay_truth |

## Itens

**Bench da planta atual** [D5, N1, P0.1] — nenhuma partida decidida contra Protoss e uma só contra bot de ladder.
O harness e o `aiarena_local` já jogam tudo: 3 raças × {Rush, Macro, RandomBuild} × 3 seeds × 2 mapas, mais
PhantomBot × 5, com `tools/replay_truth.py` em todos. Aceite: ≥ 18 partidas decididas por raça, Wilson por raça.
Este bench destrava a avaliação de quase todo o resto.

**Desfecho `interrupted`** [D2, P0.1] — uma partida cortada pelo logoff do Windows conta como `crash` ou `defeat`.
Direção: detectar pelos códigos de logoff e pela falha do `save_replay`, e por Defeat com estruturas nossas vivas;
fora das taxas e rejogada. Não ler o `game.ended` puro, que inventaria derrotas.

**Métricas intermediárias no `summary.json`** [N1, P0.1] — army supply em 6, 8 e 10 min, banco médio, troca de
recursos, primeiro ataque e número de RETREAT. Hoje se extrai do JSONL à mão. Uma mudança de micro aparece na
troca muito antes de aparecer no placar.

**Fingerprint incompleto** [I7, P0.5] — já cobre awareness, strategy, map_control, offense, rush, detection e a
economia; ficam de fora constantes da Defense, do Intel e dos behaviors (`ENGAGE_RADIUS`, `STIM_RANGE`,
`HOLD_RADIUS`…). Dois benches com o mesmo fingerprint podem decidir diferente.

**Validar a luta local por replay** [N5.3] — cada ENGAGE/RETREAT do JSONL vira um rótulo pela troca de recursos
nos 20 s seguintes. Mede `engage_share` e `retreat_share` sem jogar partida.

## Pesquisa

As duas pesquisas pedem o mesmo método: cenários de micro com composição e upgrades fixos, depois partidas
pareadas com mesmo mapa, oponente, estilo e configuração, e crash, timeout e interrupção separados de derrota
([bots-opensource](pesquisa/bots-opensource.md#ordem-recomendada-e-validação),
[ladder-local](pesquisa/ladder-local.md#ordem-sugerida-e-relação-com-os-documentos-existentes)). Contra o Phantom,
fixar pacote e arquivo de dados, não só nome e versão.
