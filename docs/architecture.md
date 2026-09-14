# Arquitetura: seis camadas

Implementação da primeira fatia do [mapa de migração](migration-map.md). Um frame
atravessa as camadas sempre na mesma ordem, em `play_frame` ([bot/main.py](../bot/main.py)):

```text
attention = observe(bot, iteration, map_view)                  ATTENTION
awareness = awareness_model.infer(attention)                    AWARENESS
strategy  = strategy_model.decide(attention, awareness)         STRATEGY
proposals = defense.plan(...) + core_army.plan(...)             BEHAVIORS
economy   = economy.plan(attention, strategy)
result    = engine.execute(bot, attention, proposals, economy)  ENGINE
logs.record(bot, attention, awareness, strategy, ...)           LOGS
```

Só `observe`, `engine.execute` e os observadores de `logs` tocam o bot. Todo o
resto lê estados imutáveis e é testável sem `AresBot`.

## Camadas

| Camada | Arquivo | Estado público | O que faz |
| --- | --- | --- | --- |
| ATTENTION | [bot/attention.py](../bot/attention.py) | `AttentionState`, `MapView` | Lê o frame: recursos, unidades próprias e inimigas visíveis (ordenadas por tag), bases, mortes, visibilidade. `read_map` lê o mapa uma vez e congela lattice, expansões e `MapTopology` (regiões, passagens, adjacência e regiões dos starts). Não interpreta valor, ameaça ou controle territorial. |
| AWARENESS | [bot/awareness/](../bot/awareness/) | `AwarenessState` | Memória de contatos com confiança `exp(-idade/τ)` e incerteza `min(cap, v·idade)`; esquece por morte confirmada, posição vista vazia (após carência) ou confiança < piso. Pressão por base e campo de influência. |
| STRATEGY | [bot/strategy.py](../bot/strategy.py) | `StrategyState` | `STABILIZE` vs `BUILD_ADVANTAGE` com margem, permanência mínima e emergência; preferências contínuas `defense`, `army`, `economy`, `risk`; ponto de rally. |
| BEHAVIORS | [bot/behaviors/](../bot/behaviors/) | `Proposal`, `EconomyPlan` | `defense`: uma proposta por base sob pressão. `core_army`: fallback com todas as unidades livres. `economy`: plano para os macro behaviors do Ares depois do opening. |
| ENGINE | [bot/engine.py](../bot/engine.py) | `EngineResult` | Ordena por `(-priority, owner, proposal_id)`, concede cada unidade de exército a no máximo uma proposta (as que já eram dela primeiro, depois as mais próximas) e só comanda as concedidas, via `CombatManeuver`/`AMove`/`PathUnitToTarget`/`SiegeTankDecision`. Registra `Mining` e o `MacroPlan`. |
| LOGS | [bot/logs/](../bot/logs/) | — | Log JSONL, snapshots SVG do campo e overlay in-game. Nenhum deles muda decisão nem derruba partida. |

## Matemática

- Kernel `K(d, σ) = exp(-½·d²/σ²)` e saturação `S(x) = 1 - exp(-x)` ([field.py](../bot/awareness/field.py)).
- Poder de uma unidade: `sqrt(dps · (hp + shield))`, em Marines.
- Pressão na base: `Σ poder·confiança·K(d, σ_base + incerteza)` dos atacantes ao alcance
  físico (`base_reach + incerteza`); `threat = S(pressão / full_pressure)`.
- Campo por ponto do lattice:
  - `threat`: presença possível, σ alargado pela incerteza;
  - `enemy`: presença crível, sem alargamento;
  - `support`: nosso exército e estruturas;
  - `control = support - enemy`.
- Strategy: scores `STABILIZE = danger`, `BUILD_ADVANTAGE = 1 - danger`; troca só com
  vantagem ≥ `switch_margin` e `minimum_dwell` cumprido (STABILIZE pula a permanência
  com `danger ≥ emergency_danger`). Empate inicial é conservador.
- Defense: `priority = threat · (0.5 + 0.5·strategy.defense)` (> 0 exatamente enquanto há
  atacante ao alcance, logo acima do CoreArmy, que é 0) e
  `count = ceil(1.5 · pressão / poder médio do exército)`. Ataque só aéreo pede só quem atira no ar.

## Visualização

- **Bolinhas in-game** (`--spatial-view`): uma esfera por ponto do lattice, cor contínua
  verde (nosso) → amarelo (disputado) → vermelho (inimigo crível), laranja onde a ameaça é
  só possível; contatos com anel de incerteza, dono de cada unidade, rally e painel da estratégia.
- **SVG** (`--spatial-snapshot`): `logs/game-*/spatial/field-SSSS.svg` a cada intervalo e em
  toda troca de objetivo, com o grafo estático de regiões/passagens, ameaça, influência,
  bases, contatos, exército por dono, alvos das concessões e painel das camadas.
- **Viewer** ([logs/viewer.html](../logs/viewer.html)): carregue a pasta do jogo. Summary,
  Decision Timeline (trilhas agrupadas por camada, inspetor de todas as camadas no instante
  selecionado, SVG mais próximo, dicas de contradição e causas das mudanças), Events,
  Attention, Awareness e Engine.

## Catálogo de eventos

Envelope: `schema` (3), `run`, `seq`, `iteration`, `event`, `component` (a camada),
`game_time`, `data`. Resumos de estado passam por `ChangeGate` (mudança + heartbeat de
10 s); decisões são escritas quando mudam.

| Evento | Camada | Quando | Dados |
| --- | --- | --- | --- |
| `game.started` | logs | `on_start` | `map`, `race`, `enemy_race`, `opening`, `build` {`commit`, `branch`}, `config_fingerprint`, `configs`, `lattice`, `bounds` |
| `map.topology_built` | attention | `on_start` | `regions`, `passages`, `chokes`, `expansions`, `unresolved_expansions`, `own_start_region`, `enemy_start_region` |
| `game.ended` | logs | `on_end` | `result` |
| `attention.observed` | attention | bases, fim do opening ou inimigos à vista mudam; amostra a cada 5 s | `minerals`, `vespene`, `supply_used`, `supply_cap`, `workers`, `army_units`, `army_supply`, `army_power`, `visible_enemy_units`, `visible_enemy_structures`, `bases`, `opening`, `opening_done` |
| `awareness.updated` | awareness | mudança de contatos/poder/ameaça por base, heartbeat | `contacts`, `visible_contacts`, `enemy_power`, `own_power`, `danger`, `bases[]` {`base_id`, `position`, `is_main`, `threat`, `pressure`, `cover`, `balance`, `air_share`, `center`}, `strongest_contacts[]`, `field` {`samples`, `friendly`, `contested`, `enemy`, `threatened`, `max_threat`} |
| `strategy.decided` | strategy | troca de objetivo, heartbeat | `objective`, `previous`, `since`, `reason`, `defense`, `army`, `economy`, `risk`, `rally`, `inputs`, `scores` |
| `behavior.proposed` | behaviors | o conjunto ranqueado de propostas muda | `proposals[]` {`proposal_id`, `owner`, `priority`, `command`, `target`, `count`, `unit_types`, `reason`, `inputs`} |
| `behavior.economy_planned` | behaviors | o plano muda | `active`, `workers`, `gas`, `bases`, `expand`, `freeflow`, `reason`, `composition[]` |
| `engine.granted` | engine | alguma concessão muda | `grants[]` {`proposal_id`, `owner`, `priority`, `requested`, `granted`, `tags`, `types`}, `transfers[]` {`tag`, `type`, `from`, `to`}, `unassigned` |
| `engine.commanded` | engine | comando, alvo (grade de 3) ou unidades de uma concessão mudam | `proposal_id`, `owner`, `command`, `target`, `tags`, `types`, `priority`, `reason`, `inputs`, `strategy` {`objective`, `reason`, `defense`, `risk`}, `awareness` {`danger`, `contacts`, `enemy_power`}, `attention` {`army_units`, `visible_enemy_units`}; `tags: []` e `reason: no_units_granted` quando a concessão acaba |
| `logs.frame_perf` | logs | heartbeat | `frames`, `last_ms`, `max_ms` por camada |
| `logs.snapshot_written` / `logs.snapshot_failed` | logs | SVG escrito / falhou | `path`, `trigger`, `objective`, `elements`, `bytes`, `render_write_ms` / `error` |
| `logging.record_rejected` | logs | um registro não era JSON estrito | `rejected_event`, `rejected_component`, `error` |

## Comandos

```text
.venv\Scripts\python.exe run.py
.venv\Scripts\python.exe run.py --bot-log events
.venv\Scripts\python.exe run.py --bot-log events --spatial-view
.venv\Scripts\python.exe run.py --bot-log events --spatial-snapshot
.venv\Scripts\python.exe run.py --bot-log events --spatial-view --spatial-snapshot --spatial-view-spacing 6
.venv\Scripts\python.exe logs\open_viewer.py
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m ruff check bot tests run.py
```

## Fora desta fatia

Belief probabilístico de exército, forças agregadas, avaliação dinâmica de território,
scouting, map control, harass, preempção com compromisso e ciclo de siege próprio da
defesa. Cada um entra quando um problema de gameplay medido pedir.
