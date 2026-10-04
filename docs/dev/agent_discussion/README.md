# Debate: o BotBandido é bom ou é uma bosta?

Dois agentes leram o bot inteiro (`bot/`, cerca de 15 mil linhas), os docs (`docs/` e `docs/staging/`), os testes,
o `git log` e os JSONL de `bench/`. Cada um tinha um papel:

- o **defensor** argumentava que o bot é bom;
- o **crítico** argumentava que é ruim.

Os dois tinham que provar cada afirmação com `arquivo:linha` ou com número de bench. Nenhum alterou código e nenhum
lançou partida. O debate foi sobre o HEAD `c7c336d` da branch `observador`, em 2026-10-04, em três rodadas.

| Rodada | Defensor | Crítico |
| --- | --- | --- |
| 1. Abertura | [01_defensor_abertura.md](01_defensor_abertura.md) | [01_critico_abertura.md](01_critico_abertura.md) |
| 2. Réplica (cada um lê o outro e verifica) | [02_defensor_replica.md](02_defensor_replica.md) | [02_critico_replica.md](02_critico_replica.md) |
| 3. Fechamento (placar e lista final) | [03_defensor_fechamento.md](03_defensor_fechamento.md) | [03_critico_fechamento.md](03_critico_fechamento.md) |

Este arquivo é a síntese do moderador.

## Veredito

Os dois terminaram concordando no diagnóstico e, quase item por item, na ordem das correções.

- **O que é bom:** a parte que decide é bem construída. O pipeline é acíclico, o Engine é o único dono das
  unidades, a telemetria é auditável e o frame leva de 6,5 a 9,8 ms. O observador mudou a crença e o
  comportamento: COMMIT nas 4 células Zerg Rush/Macro, contra nunca no `t0`.
- **O que é ruim:** quem perde jogo é o resto.
  - O DEFEND dispara com cerca de 3 Marines de pressão diante de 49 de cobertura.
  - Casters e BC valem poder zero.
  - O micro é a-move.
  - Um crash do Ares, disparado pelas nossas Sensor Towers, derruba o bot contra Terran.
  - O bot acumula de 13 a 16 mil minerais sem fechar o jogo.
  - Não houve nenhuma partida decidida contra Protoss, e contra bot de ladder houve uma só, uma derrota.

Na frase do crítico: *"um laboratório de modelagem que, de vez em quando, joga StarCraft"*. A resposta do
defensor, aceita no fechamento: o laboratório é bom e é ele que tornou cada defeito verificável em minutos. Só que
a camada matemática seguinte entrou antes de esses defeitos serem corrigidos.

**Placar da planta atual, depois das correções dos dois lados:** 9V 4D 2T em 15 partidas decididas. Quase todas
foram contra a IA Zerg CheatInsane em Torches, com seed 1.

## Fatos que os dois aceitam

| Fato | Evidência principal |
| --- | --- |
| O pipeline é acíclico, com posse única de unidades no Engine | `bot/main.py:133-213`, `bot/body/engine.py:65-134` |
| O observador mudou a decisão: `army_position` máximo de 0,68 a 0,75 e COMMIT em 4 de 4 jogos | JSONL de `comp-eficacia/000-003`, contra 0,00 a 0,13 no `t0` |
| A causalidade entre observador e vitórias **não** está provada (Fisher 4/4 contra 0/2, p ≈ 0,067) | Fechamento do crítico, item 1 |
| O DEFEND usa a pressão bruta e ignora a cobertura; o `balance` não tem leitor | `bot/awareness/model.py:488`; ENGAGE cancelado com 49 de cobertura (`comp-eficacia/004`) e com +0,42 de vantagem (`001`) |
| `KeyError: 0`: o Ares não filtra blips de radar, e o gatilho são as nossas Sensor Towers, que nada lê | `ares-sc2/src/ares/main.py:194-292` sem `is_blip`, ao contrário de `sc2/bot_ai_internal.py:766`; `cloak_seen_at` só nos 2 jogos que caíram |
| Casters, BC e Oracle valem poder 0; um Tank nosso dominado por Neural Parasite virou "produção Zerg" | `bot/attention/units.py:126-130`, `bot/awareness/model.py:407,433` |
| A composição por eficácia reproduz a doutrina: distância de 0,02 a 0,05 e nenhum tipo novo em 2.690 frames | Réplicas dos dois |
| O bot não fecha o jogo: supply ≥ 190 aos 589–774 s e banco de 13 a 16 mil | JSONL dos benches |
| Há sinais calculados que nenhuma decisão lê (`risk`, `economy_position`, `aggression`/`greed`/`tech`), e o `architecture.md` descreve uma `ScoutMission` que não existe | `bot/ego/strategy/`, `docs/architecture.md:270-279` |
| **Processo:** as duas maiores mudanças (observador e composição) entraram sem bench, e nada foi "medido e revertido" desde 17/09 | `git log`; seção "Medido e revertido" do `architecture.md` |

## O que foi refutado

- **"O harness esconde derrotas"**, acusação do crítico, que o defensor concedeu na réplica. Os dois se cruzaram:
  o crítico retirou a acusação no mesmo momento em que o defensor a concedia. O moderador verificou: os dois `004`
  receberam `Status.ended → Defeat` com 5 s de diferença de relógio (23:21:42 e 23:21:47), em execuções
  independentes. Logo depois, todo lançamento morreu com `0xC000026B` (STATUS_DLL_INIT_FAILED_LOGOFF). Foi o
  logoff do Windows fechando os clientes. Os dois jogos terminaram com 109 a 123 estruturas e 6 a 7 bases nossas, e
  o bot nunca chama `leave()`. O rótulo `crash` estava certo.
- **"Os crashes de bench são falha do bot":** 9 por execução foram a sessão sendo encerrada.
- **"O sorteio do estilo é ruído":** a seed é o hash do oponente (`bot/main.py:252-256`). A escolha é fixa por
  oponente, mas nunca foi medida.
- **"O observador causou a progressão t0 → comp-base → comp-eficacia":** a regra do DEFEND é idêntica entre
  `9457a4a` e `e647f7d`, e a tabela escolheu as células (na RandomBuild o `t0` venceu).
- **O argumento de custo por frame**, que o crítico retirou.

## Divergências em aberto, e o experimento que resolve cada uma

Quase todas se resolvem **sem lançar partida**, reprocessando os JSONL.

| Divergência | Defensor | Crítico | O que resolve |
| --- | --- | --- | --- |
| O piso de bases do observador | O viés é real (5,2 bases acreditadas contra 2 conhecidas), mas as mortes e a cobertura ainda identificam a renda | O piso por tempo voltou, e a queda de `g` só absorve o erro de bases | **Offline:** rodar `EnemyArmyFilter.update` (função pura) sobre os `awareness.updated` de `comp-eficacia/000-003`, com piso contra bases como estado medido, e comparar com `tools/replay_truth.py`. Critério: NEES entre 0,5 e 2, ≥ 90 % dentro de 2σ e erro de bases ≤ 1 |
| Por que o DEFEND caiu de 35–45 % para 4–10 % | O COMMIT destravado reduziu as incursões (missões `defend_area` caíram de 95–105 para 43–64) | É trajetória de jogo; o gate é o mesmo | A/B `pre-observador` contra HEAD, mesmas células, 3 seeds: incidentes por minuto e tempo até o primeiro COMMIT |
| Micro ou I1 primeiro | Micro e I1 têm peso parecido | **6 de 6** ataques mortos entraram com parcela local de 0,85 a 0,90 e nunca caíram abaixo de 0,41 no modelo do próprio bot: o problema é a luta, não a reunião | Razão de troca por janela de ENGAGE (via `replay_truth`), antes e depois da fatia de micro |
| Composição: o que fazer com ela | Shadow mais um termo físico de alcance | Shadow com prazo, SURVIVE incluído; sem ganho, apagar | Offline: contra Mutalisk e Corruptor surgem Viking e Thor, e contra Lurker o Marine não sobe. Depois, A/B com ganho ≥ 0,1 na razão de troca |
| Sensor Towers | Pausar; depois um A/B de blips como medição de cobertura | Cortar | Só depois do item 1: A/B de torres desligadas contra blips no observador, medindo NEES e o banco de gás entre 400 e 650 s |
| PRESSURE atrás | Corte `army_position ≥ 0` | Isso é um corte novo, contra o princípio de utilidade contínua; trocar o `min(1, 2·share)` de `strategy.py:218` por um fator que vá a zero suavemente | Contar no bench os ataques abertos com `army_position < 0` e o desfecho de cada um |

## Plano unificado

As duas listas finais coincidem nos itens 1 a 7, na mesma ordem. A ordem segue a lógica que saiu do debate:
1. parar de perder por crash e parar de medir errado (1–2);
2. corrigir os defeitos de decisão já medidos (3–4);
3. ganhar amostra (5);
4. só então execução e fechamento (6–7).

| # | Melhoria | Custo | Critério de aceite | Onde os dois diferem |
| --- | --- | --- | --- | --- |
| 1 | **Ladder sem crash:** filtrar blips antes dos managers do Ares, `try/except` em volta de `play_frame` (fallback: só macro do Ares) e pausar as Sensor Towers | Horas | Teste com `RawUnit` de blip, `unit_type` 0 e camuflado, sem `KeyError`; Terran CheatInsane em Magannatha, 3 seeds, 0 crash | O crítico remenda o `_prepare_units` do Ares; o defensor sobrescreve `BotBandido._should_add_unit`. **Moderador:** o `_should_add_unit` (`ares/main.py:860`) só é chamado para unidades inimigas (`:269`), então dá para resolver sem mexer no Ares vendorizado, que é o que o princípio "usar o Ares, não forkar" pede |
| 2 | **Desfecho `interrupted` no harness**, fora das taxas e rejogado | Horas | Re-resumir os `comp-*`: os `004` viram `interrupted` e as derrotas reais (`t0/000-001`, `comp-base/000`) continuam `defeat` | Critério de detecção: o crítico usa os códigos de logoff e a falha do `save_replay`; o defensor usa Defeat com estruturas nossas vivas. São complementares, dá para usar os dois. **Não** ler o `game.ended` puro, que inventaria derrotas |
| 3 | **DEFEND por ameaça líquida:** pressão contra cobertura de forma contínua; a Offense só cancela um ENGAGE imediatamente se a Defense recebeu `PARTIAL`/`REJECTED` | 1 dia | Nenhum DEFEND com cobertura/pressão ≥ 3; nenhum `home_threatened` em ENGAGE com a Defense `FULL` | — |
| 4 | **Um modelo de poder só** (`unit_view` usa `CombatModel.power`), com valor de feitiço para HT, Infestor, Viper, Disruptor e Oracle, Interceptors para BC e Carrier, e tag que já foi nossa fora de `_remember_production` | 1 dia | BC e Infestor com poder > 0; ao reprocessar `comp-eficacia/003`, nenhum SIEGETANK em `enemy[]` | — |
| 5 | **Bench da planta atual:** 3 raças × {Rush, Macro, RandomBuild} × 3 seeds × 2 mapas, PhantomBot × 5 e `replay_truth` em tudo | Uma noite de máquina | Defensor: ≥ 45 partidas decididas. Crítico: ≥ 18 por raça. Wilson por raça publicado | O defensor quer que vire regra: nada entra no HEAD sem essa matriz |
| 6 | **Micro pelo Ares:** `ShootTargetInRange`, `StutterUnitBack`, `KeepUnitSafe`, `MedivacHeal` e RETREAT com `sense_danger=True` | 2–4 dias | Razão de troca ≥ 1 em ENGAGE com parcela ≥ 0,6; passar dos 10:50 contra o PhantomBot | O crítico quer este item antes do 7 (veja a tabela de divergências) |
| 7 | **Fechar o jogo:** I1 via `MissionFeedback.power` e reforço reunido no anchor antes de seguir o squad | 1–2 dias | `assembled_share` mediano > 0,6; banco < 5 mil no supply máximo | O crítico soma: limitar as bases a `ceil(workers/16)+1`. O defensor soma: no PRESSURE, o `power_spike` multiplica a vantagem |
| 8 | **Observador com as bases como estado medido**, não como piso | 1–2 dias | Offline: NEES entre 0,5 e 2, `in_2sigma` ≥ 0,85, bases a ±1 da verdade | O crítico só implementa depois do resultado do 5 |
| 9 | **Composição em shadow** (`CompositionConfig.active=False`) | Horas | A/B com ganho ≥ 0,1 na razão de troca, senão sai | O crítico põe o SURVIVE dentro do shadow e exige prazo; o defensor acrescenta um termo de alcance |
| 10 | **Cortes e docs verdadeiros:** ligar ou apagar `risk`, `economy_position` e `aggression`/`greed`/`tech`; tirar a `ScoutMission` do `architecture.md`; parar de anunciar o estilo no chat | Horas | Todo campo do `StrategicIntent` tem leitor fora dos logs; `grep ScoutMission docs/` vazio | — |

As tabelas completas, com arquivos e funções para cada item, estão nos dois fechamentos.

## Notas do moderador

- O que o moderador verificou pessoalmente:
  - a resolução dos dois `004`, pelo `result.json`, pelo `stdout.txt` e pelos códigos de saída;
  - o ponto de inserção do filtro de blips no Ares (`ares/main.py:269,860`);
  - que o bot nunca chama `leave()`.

  Os demais números foram levantados pelos agentes com scripts read-only sobre os JSONL e conferidos pelo lado
  oposto na réplica. Não foram reproduzidos de forma independente.
- Durante o debate, outra sessão estava editando o working tree: `README.md`, `bench.py`, `run.py`,
  `harness/matrix.py`, `tools/aiarena_local/*` e `tests/test_ladder_launcher.py`. Nenhum agente tocou nesses
  arquivos. As citações valem para o HEAD.
- As listas de melhoria são propostas, não decisões. Pela regra de staging do projeto, o que for adotado deve
  migrar para `docs/staging/`.
