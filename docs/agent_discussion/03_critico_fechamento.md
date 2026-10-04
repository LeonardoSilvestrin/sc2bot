# Fechamento do crítico

Escrito sobre o HEAD `c7c336d`, depois da réplica do defensor. Usei só scripts read-only e não lancei partidas.

## 1. Placar final

**Provado.** Os dois lados concordam, e há evidência no código e nos logs.

- **O DEFEND ignora a cobertura.** Ele abre com cerca de 3,2 Marines de pressão (`model.py:488`). Cancelou um
  ENGAGE com 49 de cobertura aos 1.152 s de `comp-eficacia/004` e outro com o bot à frente em `comp-eficacia/001`.
- **O bot é cego a casters, a BC e a Oracle** (`units.py:126-130` e `model.py:407,433`). Um Siege Tank nosso,
  dominado por Neural Parasite, virou "produção Zerg", e o bot respondeu com 67 % de Tanks.
- **A composição por eficácia reproduz a doutrina.** Em 2.690 frames nenhum tipo novo entrou, e a distância à
  doutrina ficou entre 0,02 e 0,05. O próprio defensor retirou o elogio que tinha feito a ela.
- **O bot não fecha o jogo.** Chega a supply ≥ 190 entre 589 e 774 s, termina com 13,6 a 16,6 mil minerais e 8
  a 10 bases. O micro tem 258 linhas e não usa os behaviors do Ares. A relocation de Tanks resolve 9 % dos casos.
- **Há sinais calculados que nenhuma decisão lê** (`risk`, `economy_position`, `balance`, `radar_blips`,
  `aggression`/`greed`/`tech`). O `architecture.md`, documento normativo, descreve uma `ScoutMission` que não
  existe.
- **O `KeyError: 0` sai de um blip de radar** que o Ares não filtra. O `ares main.py:194-292` não tem nenhum
  `is_blip`, ao contrário do `bot_ai_internal.py:766-767`. O defensor fechou a correlação: o `cloak_seen_at`
  aparece só nos 2 jogos que caíram, entre 16 jogos com JSONL. As torres que geram esses blips não têm leitor.
- **Do lado do defensor, também provado:** o observador mudou a crença e a decisão (`army_position` até 0,75 e
  COMMIT nos 4 jogos Rush/Macro). O pipeline é acíclico, com posse única, e a telemetria tornou cada um destes
  achados verificável em minutos. O frame tem mediana de 6,5 a 9,8 ms.

**Refutado.**

- **A minha "derrota escondida pelo harness".** Os dois `004` são logoff do Windows (`0xC000026B`), e o rótulo
  `crash` estava certo.
- **A "progressão monotônica" como prova causal do observador.** A regra do DEFEND é idêntica entre `9457a4a` e
  `e647f7d`, a tabela escolheu as células e o Fisher de 4/4 contra 0/2 dá p ≈ 0,067.
- **O meu argumento de custo por frame.**

**Em aberto por falta de dado.**

- O σ do observador é honesto? O `replay_truth` nunca rodou sobre `comp-eficacia/000-003`.
- O blip só derruba o bot quando vem de uma unidade camuflada ou enterrada? Falta teste ou leitura de replay.
- Qualquer placar contra Terran, contra Protoss ou contra bots de ladder: hoje há 1 jogo, 0 jogos e 1 derrota
  aos 10:50.

## 2. Divergências que restam, e o dado que resolve cada uma

1. **O observador reintroduz um piso.** O defensor diz que o piso só mudou de lugar, para as bases, "onde pesa
   menos". Eu digo que é ali que ele pesa:
   - em `003`, entre 580 e 760 s, o filtro acredita em 4,5 a 5,4 bases contra 1 a 3 conhecidas;
   - a cobertura mede sobre as bases conhecidas, mas a renda é prevista sobre as acreditadas;
   - `g` e `B·W` não se separam, então a queda de `g` (de 0,0080 para 0,0060) pode estar apenas absorvendo esse
     erro.

   **O que resolve:** rodar offline o `EnemyArmyFilter.update` com as entradas dos JSONL de `000-003`, comparando
   duas variantes de bases (o piso de hoje e `B` medido pelos townhalls conhecidos) contra a verdade do
   `tools/replay_truth.py`. **Critério:** NEES entre 0,5 e 2, pelo menos 90 % dentro de 2σ e erro de bases ≤ 1
   depois do primeiro scout. A variante que passar fica, e sem lançar nenhuma partida.
2. **O estilo sorteado com o hash do oponente.** Concedo que, por oponente, não é ruído: a escolha é fixa. Mas é
   uma moeda fixa e nunca medida. Ela só vale contra Zerg (o `against` do MECH é só Zerg, `styles.py:105`) e trava
   cada adversário do ladder num estilo escolhido sem dado.

   **O que resolve:** um bench pareado com `--armies bio mech` contra Zerg Rush, Macro e RandomBuild, em 3 seeds,
   mais o PhantomBot. Sem diferença, apaga-se o sorteio (BIO fixo). Com diferença, escolhe-se pelo dado.
3. **Composição em shadow ou congelada.** Aceito o modo shadow do defensor, com duas condições:
   - o SURVIVE fica dentro do shadow, porque ele usa o mesmo `k` (foram os 6 Liberators);
   - há prazo, e sem medição o código sai.

   **O que resolve:** um A/B pareado (mesma seed) entre eficácia e doutrina, com as três raças, olhando a razão
   de troca por luta no replay. **Critério:** ganho ≥ 0,1 na razão de troca ou no placar pareado. Abaixo disso,
   apaga-se.
4. **A correção do harness.** O item 1 do defensor ("ler o `game.ended` do JSONL quando `exit_code ≠ 0`") teria
   registrado os dois logoffs como derrota, que foi exatamente o meu erro. O certo é um desfecho `interrupted`
   (códigos de logoff, ou falha no `save_replay`) que não entra em nenhuma taxa e é rejogado.

   **O que resolve:** rodar `bench.py summarize` de novo sobre os `comp-*`. Com a regra certa, os `004` saem das
   taxas e os placares Rush/Macro não mudam.
5. **Micro ou I1 primeiro.** Este dado é novo e pesa a meu favor: os **6 de 6** ataques que acabaram em
   `army_depleted` entraram em ENGAGE com parcela local de 0,85 a 0,90. Terminaram ainda com 0,41 a 0,61 pelo
   modelo do próprio bot; o pior caso é `002`, ataque 3, que nunca caiu abaixo de 0,61 e mesmo assim perdeu dois
   terços do squad.
   - O bot "vence" toda luta no papel e perde metade do squad.
   - O I1 explica as reuniões e os cancelamentos, não essas mortes.
   - Quem as explica é o modelo de luta (sem alcance, sem feitiço) mais a execução.

   **O que resolve:** a razão de troca, recursos mortos sobre perdidos, em cada janela de ENGAGE pelo
   `replay_truth`, antes e depois da fatia de micro, com as mesmas seeds.
6. **"PRESSURE não abre atrás" com `army_position ≥ 0`.** A proposta do defensor é um corte novo, contra o
   princípio. A alternativa contínua é trocar o `min(1, 2·share)` de `gate_scores` (`strategy.py:218`) por um
   fator que vá a zero suavemente abaixo do empate.

   **O que resolve:** contar, no bench, os ataques abertos com `army_position < 0` e como cada um terminou.

## 3. Lista final

| # | Melhoria | Custo | Impacto esperado | Como medir / critério de aceite | Arquivos tocados |
| --- | --- | --- | --- | --- | --- |
| 1 | **Sobreviver no ladder:** descartar blips antes dos managers do Ares, guardar `play_frame` e `super().on_step` com `try/except` (fallback: só macro do Ares) e suspender as Sensor Towers | Horas | Remove derrota certa contra Terran com Ghost/Mine (2/2 crashes do `t0`) | Teste com unidade crua fake (`unit_type` 0, `is_blip`, camuflada) sem exceção; Magannatha × Terran CheatInsane × 3 seeds com 0 crash | `ares-sc2/src/ares/main.py` (`AresBot._prepare_units`: `if unit.is_blip: continue`), `bot/main.py` (`BotBandido.on_step`), `bot/ego/planners/intel/planner.py` (`IntelPlanner._plan_sensor_towers`), `tests/test_frame_flow.py` |
| 2 | **Harness com desfecho `interrupted`** (logoff `0xC000026B`/`0x40010004`, ou falha no `save_replay`): fora das taxas e rejogado | Horas | Nenhum bench mente nem para mais nem para menos | `summarize` dos `comp-*` com 004–013 fora das taxas e Rush/Macro iguais; caso novo em `tests/test_harness.py` | `harness/outcome.py` (`outcome`, `UNMEASURED`), `bench.py` (`_play`, versão do HEAD) |
| 3 | **DEFEND por ameaça líquida:** ameaça pelo `balance`/`cover`; cancelamento IMEDIATO só quando a Defense recebe `PARTIAL`/`REJECTED`; a missão passa a ler o feedback | 1 dia | Acaba com o ENGAGE cancelado com 49 de cobertura; menos DEFEND e banco menor | Zero DEFEND com cobertura/pressão ≥ 3; zero `home_threatened` em ENGAGE com a Defense `FULL`; % de tempo em DEFEND no `summary` | `bot/awareness/model.py` (`_base_threat`), `bot/ego/strategy/strategy.py` (`gate_scores`), `bot/ego/planners/offense/planner.py` (`_govern`), `bot/ego/planners/defense/missions/defend_area.py` (`step`) |
| 4 | **Um modelo de poder só**, com valor de feitiço e sem contar como produção uma tag que já foi nossa | 1 dia | Protoss air e casters, BC e Neural Parasite passam a ser vistos | Testes com BC, Oracle, Infestor e HT com poder > 0; nenhum SIEGETANK "inimigo" contra Zerg; Storm/Disruptor em `enemy[]` nas células Protoss | `bot/attention/units.py` (`unit_view`, `unit_power`, apagar `SPLASH_TARGETS`), `economy/knowledge/combat.py` (`CombatModel.power`), `combat.yml`, `bot/awareness/model.py` (`_remember_army`, `_remember_production`) |
| 5 | **Medir de verdade:** 3 seeds × 3 raças × {Rush, Macro, RandomBuild} × 2 mapas, PhantomBot × 5 e `replay_truth` em tudo | Uma noite de máquina | Primeiro placar contra Protoss e contra bot de ladder; NEES do observador | ≥ 18 partidas decididas por raça, Wilson por raça, NEES e `in_2sigma` publicados em "Medições" | `harness/matrix.yml`, `tools/replay_truth.py` (sem mudança), `docs/architecture.md` |
| 6 | **Micro pelo Ares:** `ShootTargetInRange` com prioridade de alvo e `StutterUnitBack` na bio, `KeepUnitSafe`/`sense_danger=True` no recuo e Medivac com cura | 2–4 dias | Luta com parcela ≥ 0,6 deixa de custar metade do squad | Razão de troca ≥ 1 nas janelas de ENGAGE com parcela ≥ 0,6 (hoje 6 de 6 morrem); passar dos 10:50 contra o PhantomBot | `bot/body/behaviors/combat.py` (`attack_move`), `attack.py` (`execute`), `hold.py` (`execute`), `retreat.py` (`execute`) |
| 7 | **I1 + reforço agrupado + expansão até onde há workers** | 1–2 dias | Do supply máximo ao fim em menos tempo e banco menor | Mediana de `assembled_share` > 0,6; banco < 5 mil no supply máximo; bases ≤ `ceil(workers/16)` + 1 | `bot/ego/planners/offense/planner.py` (`plan`, `_idle`), `offense/missions/main_attack.py` (`MainAttackMission.step` com `MissionFeedback.power`), `economy/policies/investment.py` (`plan`, `saturated_at`) |
| 8 | **Cortes:** Sensor Towers, `risk`, `army`, `economy_position`, `aggression`/`greed`/`tech` (ou ligar a `aggression` a Bunker/reparo), anúncio do estilo no chat e composição em shadow (SURVIVE incluído) com prazo | Horas | Menos superfície de bug e nenhuma informação dada ao oponente | Testes verdes; bench pareado igual ou melhor; LOC do Ego e dos logs cai | `intel/policies/sensor_towers.py`, `body/behaviors/sensor_towers.py`, `strategy.py`, `assessment.py`, `logs/chat.py`, `bot/main.py` (`styles.announcement`), `economy/policies/composition.py` (`CompositionPolicy.plan`) |
| 9 | **Bases do observador como estado medido**, e não como piso; cobertura sobre as bases acreditadas | 1 dia | σ honesto, e `g` deixa de absorver o erro de bases | Offline, sobre `000-003`: NEES entre 0,5 e 2, ≥ 90 % em 2σ e erro de bases ≤ 1 | `bot/awareness/enemy_army.py` (`EnemyArmyFilter.update`), `tests/test_enemy_army.py` |
| 10 | **Docs verdadeiros** | Horas | O documento normativo deixa de enganar | `grep ScoutMission\|LAPPING` sem resultado; README sem "catálogo" nem "política por domínio" | `docs/architecture.md` (`:270-279`, `:512`, `:553`, `:561`, `:740`), `README.md` (`:14`, `:67` do HEAD; hoje modificado por outra sessão) |

A ordem segue o critério que o debate mostrou: primeiro parar de perder por crash e parar de medir errado
(1–2), depois os defeitos de decisão medidos (3–4), depois a amostra (5), e só então execução e fechamento
(6–7). O item 9 só entra com o resultado do 5.
