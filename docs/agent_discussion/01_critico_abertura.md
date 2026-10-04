# Abertura do crítico: o bot é ruim, e tem recibo

Escrito sobre `observador` em `c7c336d` (working tree só com mudanças em `tools/aiarena_local/`). Fontes: o código,
os docs, `git log` e os JSONL de `bench/t0`, `bench/comp-base`, `bench/comp-eficacia` e `bench/testando observador`.
Nenhuma partida foi lançada. Os números de partida saíram de scripts read-only sobre esses logs.

## 1. Tese

Este bot é um laboratório de modelagem que, de vez em quando, joga StarCraft. Em três semanas desde o recomeço
(`8273544`, 13/09) ele ganhou um filtro de Kalman, um portfólio log-ótimo de Lanchester, uma leitura de abertura em
três camadas, uma barreira de radar por Dijkstra e 2.753 linhas de telemetria. Continua com 258 linhas de micro,
sem resposta a rush, sem nenhuma partida de ladder e sem **uma única** partida decidida contra Protoss. A evidência a
favor dele é 4–1 contra a IA Zerg num mapa só e numa seed, e o próprio harness registrou aquela derrota como "crash".
Os defeitos que perdem jogo estão nos logs há semanas: um DEFEND que dispara com 3 Marines de pressão diante de 49 de
cobertura e cancela o ataque que estava ganhando, um crash no `on_step` que provavelmente vem das próprias Sensor
Towers, e a cegueira a casters. Nenhum deles foi consertado, enquanto a camada matemática seguinte entrava sem
bench. O autor violou quase todo princípio que ele mesmo escreveu.

## 2. Acusações (da mais grave para a menos grave)

### A1. Não existe evidência de que o bot seja bom, e o harness esconde derrotas

- **O que se jogou desde as posturas** (`c38f168`, 19/09), que é a planta atual: `t0` 2V 2D; `testando observador` 0V 1D; `comp-base` 2V 2D 1T;
  `comp-eficacia` 4V 1D; `local` 1V (CheatMoney). Somando, são 9V 6D em 17 partidas decididas, com Wilson 95 % de
  0,31 a 0,74. Dessas, 16 foram contra Zerg e uma contra Terran (`t0/003`). **Contra Protoss, nenhuma:** `t0/006`
  e `t0/007` ficaram `not_played` (o Ares morreu no `on_start`), e as células 012/013 de `comp-base` e de
  `comp-eficacia` caíram em cerca de 11 s de relógio. Do ladder, nada: "o bot ainda não joga ladder"
  (`staging/estimacao-e-controle.md:40-41`).
- **Os 24/25 contra VeryHard** (`base3`, `6f` e `7jk`, de 17/09) são de outra planta: antes das posturas, do
  observador e da composição, só Macro e só Persephone. O próprio autor aposentou essa régua: "sem um oponente
  que ainda vença o bot, nenhuma proposta abaixo pode ser medida" (`novas_propostas.md:63`).
- **10 de 14 células de `comp-eficacia` são `crash`**, e entre elas estão todas as de Terran e de Protoss. A
  manchete "composição por eficácia: 4 vitórias" vale só para Zerg Rush e Macro em Torches, com seed 1. Os
  intervalos de Wilson, 4/5 → [0,38; 0,96] e 2/5 → [0,12; 0,77], se sobrepõem quase por inteiro. O próprio
  `architecture.md:814` admite: "o placar não separa nenhuma mudança".
- **O harness conta derrota como crash.** Em `harness/outcome.py:61-62`, um `exit_code ≠ 0` vira `CRASH` antes
  de o resultado ser lido. Em `comp-eficacia/004` (Zerg RandomBuild, bio) o JSONL termina com
  `game.ended {"result":"Result.Defeat"}` aos 1.248,9 s; quem falhou foi o `save_replay`, depois do fim. O
  `summary.json` diz `"defeat": 0`. `comp-base/004` repete o mesmo: Defeat aos 1.312,3 s, registrado como crash.
  Na única célula que separa as duas versões, as duas perderam, e o resumo não mostra.
- **Impacto:** nenhuma decisão de design dos últimos 15 dias foi validada. O `architecture.md:860` diz que o
  observador "entrou no HEAD sem bench próprio", e o `:864` que "o HEAD não tem matriz própria". Isso contradiz
  a prática declarada pelo autor, que é reverter experimento não medido.

### A2. O DEFEND é um alarme de incêndio que dispara com fumaça de cigarro, e mata o ataque que estava ganhando

- `bot/awareness/model.py:488` calcula `threat = 1 − exp(−pressure / 4)` (`full_pressure = 4.0`, `:65`). A
  `cover` (o nosso exército na base) é calculada logo acima, em `:475-487`, e **não entra**. `BaseThreat.balance`
  (`:150`), a razão pressão/cobertura, tem zero leitores no bot. O DEFEND usa `threat_level` puro
  (`strategy.py:215`) e abre a partir de 0,55, o que equivale a uns 3,2 Marines de pressão. Com 0,6
  (`strategy.py:92`) ele pula o dwell.
- Os efeitos se somam. A ofensiva é cancelada **IMEDIATAMENTE** (`offense/planner.py:196-199`). O exército livre
  inteiro vira `HOLD` na base ameaçada (`map_control/planner.py:145-146`). E a economia corta upgrades, add-ons e
  expansão (`investment.py:155`, `architecture.md:245`).
- **Nos logs:** em `comp-eficacia/004`, a derrota, o bot entrou em DEFEND 11 vezes e ficou 32 % do jogo nessa
  postura. Os gatilhos tinham pressão de 3,2 a 4,3 contra cobertura de 20 a 49. Aos 966 s foi 4,1 contra 49,4.
  Aos 1.152 s foi 3,6 contra 49,1, e isso cancelou um ataque em ENGAGE. Cinco ataques terminaram em
  `home_threatened`, quatro deles ainda no ASSEMBLE. Em `comp-eficacia/001`, aos 773 s, uma pressão de 3,2
  cancelou um ENGAGE com `army_position = +0,40`, ou seja, com o bot na frente.
- **Quem já sabia:** o autor, desde o `bench/t0` ("DEFEND dispara com 3–4 Marines de pressão mesmo com 10–53 de
  cobertura", `estimacao-e-controle.md:124-128`), e o `gaps.md`, que tem o I3 com severidade **alta** desde
  18/09. Corrigir isso pede algumas dezenas de linhas. Em vez disso entraram 1.658 linhas de Lanchester.

### A3. Um crash no `on_step` que provavelmente vem das próprias Sensor Towers, e nenhuma guarda

- `t0/004` e `t0/005` (Magannatha contra Terran CheatInsane) morreram aos 1.106 s e aos 834 s com
  `KeyError: 0` em `GridManager._handle_generic_unit → Unit._type_data`, chamado de `bot/main.py:270`. Foram
  **2 das 2** partidas contra Terran que chegaram ao meio do jogo nesse mapa.
- A cadeia causal está no próprio repositório:
  1. `attention/frame.py:191-192` diz, com as palavras do autor, que o Ares "files each [radar blip] as a
     NOTAUNIT enemy with tag 0".
  2. `unit_type` 0 é exatamente a chave que falta em `game_data.units`.
  3. `grid_manager.py:403` descarta inimigo "não pronto", **a menos que** esteja camuflado ou enterrado. Widow
     Mine e Banshee são Terran. Contra a IA Zerg do bench isso não aparece, e contra Zerg nunca houve crash.
  4. As torres começam com 4 bases, por volta dos 500–650 s, antes dos dois crashes.

  Ainda é hipótese, mas dá para testar: basta ler o replay ou forçar um blip de uma unidade enterrada.
- O radar não serve para nada. `radar_blips` (`frame.py:142`) só é lido pela telemetria (`telemetry.py:519,539`),
  e o próprio `architecture.md:289` diz que "a rede de Sensor Towers ainda não alimenta Awareness". O preço são 6
  a 8 torres por jogo. A quarta ficou pronta entre 499 e 645 s, e nesse momento o banco de gás estava entre 33 e
  337 em 4 dos 5 jogos. É justamente a janela em que o gás é o recurso que limita
  (`investment.py:34-41`).
- `bot/main.py:269-273` não tem `try`. Os dois únicos `except Exception` do bot protegem o **chat**
  (`main.py:285-289`, com o comentário "a log may never drop a match") e o SVG. O pedido "Crash como derrota",
  da N8 de 19/09, nunca foi atendido.

### A4. Cego a casters, a BC e a Oracle: o poder vem do dps automático do python-sc2

- `attention/units.py:126-130` calcula o poder com `max(ground_dps, air_dps)` do python-sc2. Lá, BC e Oracle
  dão `ground_dps = 0` (o TODO de `sc2/unit.py` admite que o proto não tem armas). O dano do Carrier é dos
  Interceptors (o `combat.yml:9-10` diz isso). Infestor, Viper, High Templar e Disruptor dão zero.
- `awareness/model.py:407` e `:433` filtram `unit.power > 0.0`, então essas unidades **nunca** entram em "visto"
  nem em "produzido". As entradas de BC, Oracle, Carrier, HT, Disruptor, Infestor e Viper do `combat.yml` são
  dados mortos. Pior: existem dois modelos de poder, `SPLASH_TARGETS` com o dps do python-sc2 e o `combat.yml`
  com `with_client`. Eles divergem justamente nessas unidades, enquanto o `architecture.md:316` diz que é o
  mesmo "como `unit_power`".
- **Nos logs:** em `comp-eficacia/003`, o Siege Tank de tag `4364959746` é **nosso** aos 378 s (HOLD do
  `core_army`). Aos 490 s ele aparece como **inimigo**, um SIEGETANK com 2,39 de poder, e o mix responde com
  **67 % de Siege Tanks** a um Zerg "que produz Tanks" (parcela de 0,36). Num ZvT, só o Neural Parasite faz isso.
  "INFESTOR" aparece **0 vezes** nos 5 logs, e houve "Siege Tank inimigo" em 3 dos 5 jogos (203, 33 e 319
  entradas de `economy_planned`).
- **Impacto:** Storm, Disruptor, Carrier, BC e Infestor não geram ameaça nem DEFEND, e a composição não responde
  a nenhum deles. É exatamente o que um Protoss de ladder usa contra bio. Os 486 testes não pegam isso porque
  `tests/fakes.py:63` dá `power = 1.0` a qualquer unidade.

### A5. A "composição por eficácia" devolve a doutrina com ruído, e quando se mexe vai para o lado errado

- O commit `e647f7d` tem 1.658 inserções. Nos 5 jogos, em 2.690 frames com `composition_reason = efficacy`, o
  otimizador **não acrescentou um único tipo** fora da doutrina do estilo: Hellion, Cyclone, Thor e Viking, os
  `adds` da bio, nunca saíram. O desvio mediano em relação à doutrina ficou entre 0,02 e 0,05, com 0,115 no
  jogo perdido.
- Quando se mexeu, foi para o lado errado. Em `004`, com Lurker em 0,44–0,45 da crença, o Marine subiu de 0,59
  para 0,72. Aos 899 s o exército tinha 70 Marines, 4 Marauders, 5 Tanks e **1 Medivac**, e o jogo foi perdido.
  O viés pró-Marine já estava escrito (`estimacao-e-controle.md:113-116`, "o modelo não vê alcance"), e o Lurker
  tem mais alcance que o Marine.
- No fim, o portfólio contínuo passa por um corte, `min_share = 0.05` (`composition.py:129`), e pelo teste de
  contagem do `SpawnController`.

### A6. Não fecha o jogo: supply máximo aos 10–13 min e 13 a 16 mil minerais no banco

- Supply ≥ 190 chegou entre 589 e 774 s, e as vitórias só vieram entre 1.000 e 1.244 s. Minerais no fim das 4
  vitórias: 13.623, 14.562, 16.626 e 16.301. O `003` já tinha 12.003 aos 958 s. Dos 36 PRESSURE, 33 abriram por
  `power_spike` (supply ou upgrade), não por vantagem.
- **Causas no código:**
  - A2.
  - Reforços pingando sozinhos até o grupo (`architecture.md:744`). O autor escreve que a força cresce com N² e
    que o reforço aos poucos custa quadraticamente (`estimacao-e-controle.md:144-146`), e deixa assim.
  - O I1, com severidade alta desde 18/09: compromisso e reunião medidos sobre o exército inteiro
    (`offense/planner.py:175`, `:264`).
  - Expansão sem fim. `investment.py:140` faz `saturated_at = min(80, 16·bases)`, então a partir de 5 bases o
    bot está sempre "saturado" e expande até o mapa acabar: 9 a 10 bases no fim. Cada base nova é mais
    superfície para o alarme da A2.

### A7. Micro inexistente, com dez vezes mais linhas de log do que de micro

- Todo o combate cabe em `attack.py`, `combat.py`, `hold.py` e `retreat.py`: 258 linhas. Isso é A-move, Stim a
  10 células, Medivac indo para o centróide e `SiegeTankDecision` do Ares. Não há foco de fogo, stutter, esquiva
  de Storm/Bile/Disruptor, pickup de Medivac nem habilidade de Cyclone, Thor, Viking, Banshee ou Liberator. O
  SURVIVE comprou 5 a 6 Liberators em `004`, e eles nunca entram em siege.
- Do outro lado: `bot/logs/` tem 2.753 linhas, das quais `telemetry.py` sozinho tem 1.328 (o segundo maior
  arquivo do bot). `topology.py` tem 1.396. A relocation de Tanks soma 763.
- Três revisões pediram a mesma coisa: `propostas.md`, a N6 de `novas_propostas.md` ("maior ganho de troca por
  linha de código, tudo do Ares", item 4 da ordem) e `bots-opensource.md:16-18` em 03/10. Ficou por fazer.

### A8. Sinais sem consumidor, contra a regra do próprio autor

`novas_propostas.md:272` diz: "Não manter sinal sem consumidor... é melhor apagá-los do que carregá-los."
O que está no HEAD:

- `intent.risk` (`strategy.py:191`) só aparece num `inputs` de log (`map_control/planner.py:154`).
- `intent.economy` é lido uma vez como `>= 0.5` (`investment.py:148`), e o `architecture.md:239-240` admite que
  isso é sempre verdadeiro sem ameaça.
- `economy_position` (`assessment.py:102`) não tem leitor, e o `architecture.md:777-778` admite.
- `balance` (`model.py:150`) não tem leitor.
- `radar_blips` não tem leitor (ver A3).
- `OpeningBelief.aggression`, `greed` e `tech` só vão para chat, overlay, SVG e telemetria (`chat.py:58-60,
  123-125`). O commit `4026669` (+2.894 linhas) produz a frase "an all-in is coming." e nenhum Bunker nem worker
  pull (README, "Limitações conhecidas"). O bot avisa o oponente de que foi lido e não faz nada com isso.
- `DefendAreaMission.step` recebe `feedback` e não o lê (`defend_area.py:78`). Ninguém chama o `request_cancel`
  dela, então o ramo de cancelamento é código morto. O próprio `architecture.md:610-611` diz que ela só
  acrescenta "identidade e lifecycle nos logs". A malha que deveria ser fechada fica aberta.

### A9. O observador reintroduz, um nível acima, o prior irrefutável que ele veio matar

- O motivo da virada foi "um prior que nenhuma evidência derrubava" (`estimacao-e-controle.md:9-10`). Mas em
  `enemy_army.py:202-203` as bases inimigas são `max(conhecidas, min(sites/2, 1 + t/150) − mortas)`: um piso por
  tempo que só cai se um townhall morrer à vista. Os workers só são medidos por baixo (`known_workers`), nunca
  por cima.
- A entrada `u` do filtro, que é a renda, é portanto um prior por tempo. Só a pseudo-medição de cobertura puxa a
  estimativa de volta, e só enquanto o bot está olhando as bases dele. Para piorar, essa "medição" (`seen`) é uma
  memória exponencial de 180 s, fortemente autocorrelacionada, reaplicada a cada frame com
  `R = 225/(c·dt)` como se fosse ruído branco. É a receita clássica de filtro otimista.
- A única medida de consistência que existe deu NEES de 34,9 (`estimacao-e-controle.md:67-71`). Depois disso o
  `power_drift` foi multiplicado por 6 com base em **uma** partida, e ninguém mediu de novo, embora os replays de
  `comp-eficacia/000-003` estejam no disco para o `tools/replay_truth.py`.

### A10. Cut-offs e histerese em camadas, contra os próprios princípios

Os princípios declarados são utilidade contínua sem cortes, crença robusta antes de histerese e "lei contínua
onde o atuador é contínuo; relé com tempo morto dá ciclo limite" (`estimacao-e-controle.md:30-31`). No código:

- **A Strategy é um relé de 5 estados com três camadas de histerese** (`switch_margin`, `minimum_dwell` e
  `stance_dwell`, em `strategy.py:86-94`). Mesmo assim oscila: `004` teve 37 trocas de postura em 1.249 s, uma a
  cada 34 s.
- **A economia é liga/desliga por postura** (`investment.py:147-155`): upgrades, add-ons e expansão.
- **Os limiares fixos estão por toda parte:**
  - `PROXY_SEARCH_AT = 0.55` e `PROXY_CONFIDENCE_AT = 0.3` (`intel/planner.py:55-56`);
  - `READ_ENOUGH = 0.75` (`early_scout.py:110`);
  - onze limiares e timers na ofensiva (`main_attack.py:130-160`: 20, 0,8, 0,5, 0,35, 0,9, 0,5, 30 s...).
- **O estilo é sorteado por partida** (`main.py:256`, `styles.py:120-129`), contra "Não variar a abertura por
  sorteio... é ruído" (`novas_propostas.md:266`).
- **A recomendação de não empilhar matemática foi ignorada.** Em 14/09 o `propostas.md:49-50` dizia: "O maior
  ganho agora não virá de outra camada matemática." Em 03/10 entraram duas.

### A11. Docs que contradizem o HEAD que dizem descrever

- O `architecture.md`, normativo, descreve em `:270-279`, `:512`, `:553` e `:561` uma `ScoutMission` com
  `intel:scout:N`, fase `LAPPING` e arquivo `missions/scout.py`. Nada disso existe; só existe `early_scout.py`.
  O mesmo documento descreve a `EarlyScoutMission` em `:118` e em `:596`.
- `:740` afirma que "topologia e campo... nenhuma decisão os consome", mas o `:432` (staging) consome os dois.
- `:833` ainda fala em `STABILIZE ↔ BUILD_ADVANTAGE`, postura que não existe mais.
- O README vende um "catálogo validado de counters", que foi removido em `e647f7d`, e uma "Strategy com política
  por domínio", que o `architecture.md:65-66` proíbe.
- Os docs somam 3.870 linhas, das quais cerca de 2.400 são proposta ou backlog, repetindo as mesmas
  recomendações.

### A12. Remendos em cima do Ares em vez da causa

A relocation de Tanks emparedados tem 763 linhas. Nos 5 jogos houve 127 `tank_stuck` e só 11 (9 %) saíram
com `reason: blocker_selected`; 64 foram `no_blocker`. A causa, o placement do Ares sem corredores, continua lá.
Em duas semanas houve oito commits de reorganização (`91bd950`, `c9f7008`, `7e5be42`, `6cff78d`, `45653bb`,
`0d00a68`, `ced89ae` e `c7c336d`). Sobrou legado nominal: `core_army` e as "compatibility views" do `Frame`.

## 3. Antecipação: as defesas prováveis, e por que não colam

1. **"É dívida consciente: está tudo no `gaps.md` e em 'Ainda não implementado'."** Documentar não é consertar.
   O I1 e o I3, os dois de severidade alta, estão abertos desde 18/09. A N8 (crash) é de 19/09. O DEFEND em
   cascata se sabe desde o `t0`. Nesse intervalo entraram cerca de 3 mil linhas de matemática nova. E três
   achados acima **não** estão documentados: a derrota contada como crash, o Neural Parasite e a provável causa
   do `KeyError: 0`. O volume de documentação é o sintoma, não o atenuante.
2. **"A arquitetura é limpa, determinística, testável, com 486 testes."** São canos limpos com a água errada.
   Os fakes dão `power = 1.0` a tudo (`fakes.py:63-85`), então nenhum teste vê BC, Oracle ou Infestor. O
   determinismo cai com a primeira falha do cliente (`architecture.md:884`). E uma arquitetura reorganizada sete
   vezes em três semanas não está "pronta"; está em movimento.
3. **"O observador foi medido e o erro caiu de +9,7 para +1,7."** Isso foi n = 1, numa partida perdida, com
   NEES de 34,9: o filtro falhou no teste de consistência. Depois foi alterado (projeção e `power_drift` ×6) e
   não foi medido de novo. Mesmo com `army_position` chegando a 0,75, os ataques terminam em `army_depleted` ou
   `home_threatened`. Estimar melhor não adianta enquanto o gargalo é a A2 com a A7.
4. **"Ele ganha do CheatInsane, que trapaceia na renda" ou "fez 24/25 contra VeryHard".** Os 24/25 são de
   outra planta, numa régua que o próprio autor aposentou (A1). Contra o CheatInsane, é só Zerg, só Torches, só
   seed 1, e o placar é 4–1, não 4–0. Ganha aos 17–21 min, com 14 mil no banco. Contra Protoss não há nenhuma partida decidida, e
   contra bots de ladder também não, apesar das 977 linhas de infraestrutura de ladder local (`b69e8df`).
5. **"Os crashes são do ambiente ou do Ares."** As 10 quedas em 11 s são do cliente, concedo, e por isso
   **não medem nada a favor do bot**. Os do `t0` acontecem no `on_step`, com causa provável nas torres do próprio
   bot, e não há guarda nenhuma. No ladder, crash é derrota, seja de quem for a stack.

## 4. O que eu faria no lugar (por prioridade)

| # | Ação | Custo | Impacto esperado |
| --- | --- | --- | --- |
| 1 | **Medir de verdade.** `outcome.py` lê `game.ended` do JSONL quando o processo cai depois do fim. Rodar de novo Terran e Protoss. Matriz de 3 seeds × 3 raças × 2 mapas, mais 2 bots de ladder pelo `aiarena_local` | Horas, mais uma noite de bench | Pela primeira vez, saber **onde** o bot perde. Hoje não se sabe nada sobre Protoss |
| 2 | **Sobreviver no ladder.** `try/except` em `play_frame` e em `super().on_step`, com fallback para só macro do Ares. Filtrar blips (`unit_type == 0`) antes do `GridManager` ou parar de construir torres. Teste de regressão com um blip enterrado | Horas | Elimina derrota certa (2 das 6 partidas jogadas do `t0`) |
| 3 | **Cortar as Sensor Towers** até alguma decisão ler `radar_blips` | Minutos | Uns 400 de gás de volta na janela 400–650 s e um vetor de crash a menos |
| 4 | **DEFEND por déficit.** Ameaça líquida pela cobertura (o `balance` já existe), e DEFEND só quando a Defense recebe `PARTIAL`/`REJECTED` (C6). Nunca cancelar IMEDIATAMENTE um ENGAGE que está ganhando se a casa cobre o incidente | 1 dia | Os 5 cancelamentos de `004` e o de `001`. Fecha jogos e derruba o banco |
| 5 | **Micro pelo Ares** (N6.1 e N6.2): `ShootTargetInRange` com prioridade de alvo, `StutterUnitBack` contra melee, `KeepUnitSafe` e o grid de esquiva (Storm, Bile, Disruptor), cura de Medivac e siege antes do contato | 2–4 dias | É o maior ganho de troca por linha, segundo as três revisões do próprio autor |
| 6 | **Um modelo de poder só**, o `combat.yml` com `with_client`, também na Attention. Valor de feitiço para HT, Infestor, Viper e Disruptor. Tag que já foi nossa nunca conta como produção inimiga | 1 dia | Ameaça e composição passam a enxergar Protoss air/caster, BC e Neural Parasite |
| 7 | **Reforço agrupado (N7.1) e I1:** compromisso e reunião medidos pelo `MissionFeedback.power` do squad | 1–2 dias | Ataques que não morrem um a um; supply máximo vira dano |
| 8 | **Resposta a rush** ligada à `aggression`: Bunker, reparo e worker pull. Se não houver ligação, apagar `aggression`, `greed` e `tech` | 1–2 dias, ou minutos para apagar | Converte o chat em defesa, ou remove peso morto |
| 9 | **Apagar o que não decide:** `risk`, `economy_position`, o ramo de cancelamento da `DefendAreaMission`, o anúncio do estilo no chat (entrega informação ao oponente) e boa parte da telemetria, que roda no ladder | Horas | Menos superfície de bug, menos custo por frame, código que diz a verdade |
| 10 | **Congelar a composição por eficácia** na doutrina com 2–3 counters medidos, até um termo físico (alcance ou supply) mostrar efeito em bench | Horas | Deixa de piorar o mix contra Lurker e reduz complexidade |
| 11 | **Docs:** `architecture.md` só com o que é verdade (ScoutMission, `:740`, `:833`), README corrigido e um único backlog | Horas | Quem lê para de ser enganado pelo documento "normativo" |

Só depois disso faz sentido falar de DEFEND em cascata com PI, de lei de gasto contínua ou de bandit entre
partidas. Controle sobre uma planta que trava, não enxerga metade do jogo e não sabe atirar continua sendo só
ornamento.
