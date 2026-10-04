# Fechamento do defensor

Fontes: `02_critico_replica.md` e a correção do moderador. Conferi tudo no HEAD `c7c336d` e nos JSONL,
com scripts read-only. Não lancei partidas.

## 0. Retiro uma concessão

Na réplica eu concedi que os dois `004` eram derrotas escondidas pelo harness. **Retiro essa concessão.**
O que os logs mostram é isto:

| Partida | Fim do log | Estruturas nossas | Bases | Supply |
| --- | --- | --- | --- | --- |
| `comp-eficacia/004` | `Result.Defeat` | 123 | 7 | 200 |
| `comp-base/004` | `Result.Defeat` | 109 | 6 | 161 |
| `t0/000`, `t0/001`, `comp-base/000`, `testando/000` (derrotas reais) | `Result.Defeat` | 1–2 | 0 | — |

Os dois `004` são clientes encerrados pelo logoff do Windows, e o harness acertou ao marcá-los como crash. A
minha melhoria nº 1 da réplica, "ler o `game.ended` do log", teria **inventado** duas derrotas. A tabela
acima deixa a regra certa (item 2 da lista final). O placar da planta atual fica em **9V 4D 2T** em 15
partidas decididas.

## 1. Placar do debate

**Provado; os dois lados concordam.**

1. O pipeline acíclico e a posse única no Engine são a melhor parte do projeto.
2. O observador mudou a crença e o comportamento: `army_position` máximo de 0,68 a 0,75 e COMMIT nas 4
   células Zerg Rush e Macro. A estimativa cai depois de lutas ganhas.
3. O DEFEND sai da pressão bruta e ignora a cobertura: 3,6 de pressão contra 49,1 de cobertura aos 1.152 s,
   e um ENGAGE cancelado com `army_position` +0,42 no `001`.
4. Casters e BC valem poder 0, e o Tank dominado por Neural Parasite virou "produção Zerg".
5. A composição ficou quase igual à doutrina: distância mediana de 0,02 a 0,05 e nenhum `add` passou de 1 %.
6. `KeyError: 0`: o Ares não filtra blips em `_should_add_unit` (`ares/main.py:860-885`), e o gatilho são as
   nossas torres.
7. O micro é primitivo, o bot não fecha jogos (14 a 16 mil minerais no banco), a doc normativa está
   desatualizada e a relocation só resolve 9 % dos casos.
8. **Processo:** as duas maiores mudanças entraram sem bench, e nada foi medido e revertido desde 17/09.

**Refutado.**

- "O harness esconde derrotas": o crítico retirou a acusação, e eu retirei a minha concessão.
- O placar "9V 6D em 17" e "16 de 17 contra Zerg".
- "O sorteio do estilo é ruído": a seed é o hash do oponente (`main.py:252-256`).
- O "custo por frame", que o crítico retirou.

**Em aberto, por falta de dado.**

- Se o observador **causou** as vitórias. O teste de Fisher de 4/4 contra 0/2 dá p ≈ 0,067.
- Se o filtro é consistente depois da projeção: o NEES não foi medido de novo.
- Se a composição ajuda ou atrapalha.
- Força contra Protoss e Terran: zero partidas decididas na planta atual.
- Força contra bots: uma derrota, para o PhantomBot aos 10:50.
- Qual campo do blip abre a guarda de `grid_manager.py:403`.

## 2. Divergências que restam, e o que as resolveria

**(1) "A queda do DEFEND não vem do observador."**

- **O que concedo:** o gate não mudou. `strategy.py` é idêntico entre `9457a4a` e `e647f7d`, e a diff de
  `awareness/model.py` não toca em `_base_threat` nem em `full_pressure`.
- **Dado novo:** as missões `defend_area` abertas nos primeiros 1.250 s caíram de 95–105 (`t0/000-001`) para
  43–64 (`comp-eficacia/000-003`). Há menos incursões; o alarme é o mesmo.
- **O que ainda sustento:** essa trajetória vem do COMMIT que o observador destravou.
- **O que resolveria:** um A/B `pre-observador` contra HEAD nas mesmas células, com 3 seeds, medindo
  incidentes por minuto, poder inimigo morto por minuto e o primeiro COMMIT.

**(2) O piso de bases.**

- **O que concedo:** o viés é real. Em `003`, aos 637 s, o filtro acredita em 5,2 bases e conhece 2. Em `000`,
  aos 935 s, acredita em 5,2 e conhece 0.
- **Onde discordo:** que `g` "só absorve erro". As mortes e a cobertura identificam `A`. Mas aceito que `g` e
  `B·W` estão confundidos.
- **O que resolveria:** um experimento **sem partidas**. O `EnemyArmyFilter.update` é puro, e os insumos
  estão em `awareness.updated`: `seen_enemy_power`, `lost`, `known_bases` e `coverage`. Basta reprocessar o
  filtro offline, com a versão de piso e a versão com bases como estado medido, e comparar com
  `tools/replay_truth.py` nos replays de `comp-eficacia/000-003`. Ganha quem tiver NEES perto de 1.

**(3) "Composição = doutrina com ruído."**

- **O que concedo:** é o comportamento observado.
- **Onde discordo:** do remédio. O crítico propõe voltar a counters fixos; eu proponho modo shadow (o mix é
  calculado e registrado, e quem decide é a doutrina) mais um termo físico de alcance ou de superfície de
  contato.
- **O que resolveria:** reprocessar offline as crenças `enemy[]` registradas, com e sem esse termo. Critério:
  contra Mutalisk e Corruptor surgem Viking e Thor acima de `min_share`, e contra Lurker o Marine não sobe.
  Depois, um A/B shadow contra ativo, medindo a troca por luta.

**(4) `radar_blips` como medição.**

- **Onde concordo:** na ordem. Nada de usar blips antes do filtro no Ares.
- **Onde discordo:** de cortar o radar de vez. Ele é a única informação de meio de jogo mais barata que um
  scan.
- **O que resolveria:** com o filtro já no lugar, um A/B entre torres desligadas e blips como medição de
  cobertura no observador. Medir o NEES, o `in_2sigma`, o banco de gás entre 400 e 650 s e o resultado. Sem
  ganho de consistência, as torres saem.

## 3. Lista final de melhorias

| # | Melhoria | Custo | Impacto esperado | Como medir / critério de aceite | Arquivos tocados |
| --- | --- | --- | --- | --- | --- |
| 1 | **Ladder sem crash.** Override `BotBandido._should_add_unit(unit)` → `not unit.is_blip and super()._should_add_unit(unit)`. `try/except` em volta de `play_frame` em `on_step`, que registra `frame_failed` e deixa o frame com o macro do Ares. Pausar as torres em `sensor_towers.plan` até o item 8 dar um consumidor | Horas | Fim de derrota certa contra Terran com unidade camuflada (2 de 2 crashes do `t0`) | Teste com `RawUnit` de blip `unit_type 0` camuflado: sem `KeyError`. Bench Terran CheatInsane em Magannatha, Macro e RandomBuild, 3 seeds: 0 crashes | `bot/main.py`, `bot/ego/planners/intel/policies/sensor_towers.py`, `tests/test_frame_flow.py`, `tests/test_sensor_towers.py` |
| 2 | **Harness distingue "interrompido".** Em `outcome()`: `Defeat` com `exit_code ≠ 0` e bases ou estruturas nossas > 0 na última `attention.observed` vira `interrupted`, fora das taxas. O `record.py` grava essa contagem | Horas | Placar sem derrota inventada nem escondida | Re-resumir `comp-*`: os dois `004` viram `interrupted`; `t0/000-001`, `comp-base/000` e `testando/000` continuam `defeat` | `harness/outcome.py`, `harness/record.py`, `harness/summary.py`, `tests/test_harness.py` |
| 3 | **DEFEND por ameaça líquida.** `_base_threat` passa a usar pressão contra cobertura de forma contínua, por exemplo `pressure·pressure/(pressure+cover)`, e o `balance` ganha leitor. A Offense só cancela IMEDIATAMENTE um ENGAGE se a Defense teve grant `PARTIAL` ou `REJECTED` (C6). Senão, cancelamento gracioso ou nenhum | 1 dia | Menos DEFEND falso e menos ataques mortos em casa | Offline sobre os logs: os gatilhos com cobertura ≥ 20 do `004` somem. Bench: o tempo em DEFEND e os `home_threatened` caem sem aumentar os townhalls perdidos | `bot/awareness/model.py`, `bot/ego/strategy/strategy.py`, `bot/ego/planners/offense/planner.py`, `bot/ego/planners/defense/missions/defend_area.py`, `tests/test_awareness.py`, `tests/test_offense.py` |
| 4 | **Um modelo de poder só.** O `unit_view` passa a usar `CombatModel.power` (via `with_client`). O `combat.yml` ganha valor de feitiço para HT, Infestor, Viper, Disruptor e Oracle, e de Interceptor para BC e Carrier. Tag que já foi nossa nunca entra em `_remember_production` | 1 dia | Ameaça e composição passam a ver Protoss air, casters e o Neural Parasite | Testes com BC e Infestor com poder > 0. Ao reprocessar `comp-eficacia/003`, não sobra SIEGETANK em `enemy[]` | `bot/attention/units.py`, `bot/attention/frame.py`, `bot/awareness/model.py`, `bot/ego/planners/economy/knowledge/combat.py`, `combat.yml`, `tests/fakes.py`, `tests/test_combat.py` |
| 5 | **Bench da planta atual**, depois de 1–4: 3 raças × {Rush, Macro, RandomBuild} × 3 seeds × {Torches, Magannatha}, mais 5 partidas contra o PhantomBot pelo `aiarena_local` e `replay_truth` num venv separado | Uma noite de máquina | Saber onde o bot perde, Protoss incluído | ≥ 45 partidas decididas, com Wilson por raça. A regra passa a ser: nada entra no HEAD sem esta matriz | matriz nova em `harness/` (só YAML; o `matrix.py` está com a outra sessão), `tools/replay_truth.py` |
| 6 | **Micro pelo Ares.** `ShootTargetInRange` e `StutterUnitBack` para ranged contra melee, `KeepUnitSafe` com pouca vida, `MedivacHeal`. RETREAT com `sense_danger=True` | 2–4 dias | O maior ganho contra bots reais | A/B no subconjunto do item 5 e contra o PhantomBot: a troca por luta (poder inimigo perdido sobre o nosso, no `fight` do `offense_planned`) sobe | `bot/body/behaviors/attack.py`, `hold.py`, `retreat.py`, `combat.py`, `tests/test_behaviors.py` |
| 7 | **Fechar o jogo.** I1: `committed` e `assembled` passam a vir do `MissionFeedback.power`. Unidades novas se reúnem no anchor antes de seguir o squad. No PRESSURE, o `power_spike` multiplica a vantagem em vez de substituí-la | 1–2 dias | Supply máximo vira dano | `assembled_share` mediano > 0,6. Banco aos 1.000 s < 5 mil (hoje 12 a 16 mil). Menos `army_depleted` | `bot/ego/planners/offense/planner.py`, `missions/main_attack.py`, `bot/ego/strategy/strategy.py`, `tests/test_offense.py`, `tests/test_strategy.py` |
| 8 | **Observador consistente.** Primeiro offline (ver 2.2): bases como estado com variância, medidas por townhalls conhecidos e expansões vistas vazias, no lugar do piso. Cobertura sobre as bases acreditadas. A medição usa o exército visível agora, não a memória de 180 s. Depois, os blips como cobertura, se o item 1 estiver feito | 1–2 dias | Um σ que sirva de margem `μ + kσ` | NEES entre 0,5 e 2 e `in_2sigma` ≥ 0,85 nos replays de `comp-eficacia/000-003` e do item 5. Bases acreditadas a ±1 da verdade | `bot/awareness/enemy_army.py`, `bot/awareness/model.py` (`infer`), `tools/replay_truth.py`, `tests/test_enemy_army.py` |
| 9 | **Composição em shadow, mais um termo físico.** `CompositionConfig.active=False`: a doutrina decide e o mix vai para o log. O termo de alcance entra em `_efficacy`, e só é ativado depois de um A/B | Horas, e 1 dia para o termo | Para de piorar contra Lurker; o termo pode passar a valer | Critério offline de 2.3, depois A/B de troca por luta | `bot/ego/planners/economy/policies/composition.py`, `knowledge/combat.py`, `tests/test_composition.py` |
| 10 | **Docs e sinais que dizem a verdade.** Tirar a `ScoutMission` de `architecture.md:270-279`, `:512`, `:553` e `:561`, corrigir o `:740` e pôr notas de estado no `gaps.md`. Ligar ou apagar `risk` e `economy_position`. Apagar o ramo de cancelamento morto da `DefendAreaMission`. Parar de anunciar o estilo no chat | Horas | Doc normativo confiável; nada entregue ao adversário | Zero ocorrências de `ScoutMission` nos docs; todo campo do `StrategicIntent` tem leitor fora dos logs | `docs/architecture.md`, `docs/gaps.md`, `bot/ego/strategy/model.py`, `assessment.py`, `bot/main.py` (`announced`), `bot/logs/chat.py` |

O README está sendo editado pela outra sessão; a correção dele ("catálogo de counters", "política por
domínio") fica com quem o mantém.
