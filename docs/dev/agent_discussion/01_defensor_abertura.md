# Abertura do defensor

Debate técnico sobre o BotBandido (Terran, python-sc2 + Ares-sc2), branch `observador`, HEAD `c7c336d`.
Data: 2026-10-04. Todo o trabalho foi só de leitura: código em `bot/`, docs, `result.json` e `game.jsonl` dos
benches. Rodei `pytest` (**602 passaram em 4,4 s**), `ruff check` (**limpo**) e scripts read-only sobre os
JSONL (tempo em cada postura, `army_position` máximo, `logs.frame_perf`). Não lancei nenhuma partida.

## 1. Tese

O BotBandido não é forte em micro e ainda não provou força contra bots de verdade. O que ele é: um
**sistema de decisão bem construído**, com uma cadeia causal acíclica e auditável. A crença sobre o inimigo é
um estimador de verdade (Kalman adaptativo com restrições), e não um chute com piso. A composição sai de um
modelo de combate contínuo, não de uma tabela de counters. A melhor evidência de que essa base funciona é
empírica: trocar o prior por tempo pelo observador transformou um bot que **nunca** se achava à frente
(`army_position` máximo de 0,00 a 0,13, COMMIT nunca) em um que fecha jogos contra o Zerg CheatInsane em
1.019–1.244 s. As fraquezas que sobram (micro, fechar o jogo, falso DEFEND, amostra pequena) estão quase
todas registradas com severidade e próximo passo. Isso é dívida consciente, não descuido. A exceção, que eu
admito, é um crash do Ares que não está documentado.

## 2. Pontos fortes

### 2.1 Arquitetura: pipeline acíclico, posse única, fronteiras verificáveis

- O frame inteiro está em `play_frame` (`bot/main.py:133-213`), com uma ordem fixa: Attention → Awareness →
  Strategy → planners → Engine → behaviors → logs. O feedback do Engine só é lido no frame seguinte
  (`main.py:165-166`). Não há ciclo, nada é replanejado duas vezes, e o próprio docstring promete isso
  (`main.py:10-12`).
- O Engine é o único dono da posse de unidades (`bot/body/engine.py:69-116`). A ordenação é determinística,
  `(-priority, owner, proposal_id)` (`engine.py:65-66`), as restrições duras vêm antes de qualquer score
  (`engine.py:119-134`) e cada grant volta com `FULL/PARTIAL/REJECTED` e o motivo. A precedência entre
  domínios é só a prioridade (Defense > 0, Offense 0, MapControl −1): sem orçamento implícito e sem planner
  chamando outro. O anchor do MapControl chega à Offense pelo frame (`main.py:150`).
- Os papéis são normativos e cada um tem um teste de fronteira (`docs/architecture.md:32-41`). Há um
  checklist para admitir uma Mission (`architecture.md:86-96`) e um teste para Behavior: "sua implementação
  pode ser trocada sem mudar o que o bot quer fazer?" (`architecture.md:105`). Esse teste é o argumento
  central da minha defesa do micro (seção 3): a fraqueza fica confinada ao Body por contrato.
- Não é over-engineering no sentido de OO. Não há classe base, registry nem framework próprio
  (`architecture.md:539`); Policy e Knowledge são só classificação de pastas.

### 2.2 Estimação: observador de Kalman adaptativo, e o dado que o motivou

`bot/awareness/enemy_army.py` (288 linhas) é teoria de controle aplicada de verdade, não decoração:

- O estado é `x = (A, g)`, com o parâmetro de produção `g` dentro do estado (`enemy_army.py:20-25`, predição
  em `:214-228`). Uma inovação positiva sobe `A` **e** `g` pela covariância cruzada: o filtro aprende a renda
  trapaceada do CheatInsane. Nos logs, `g` foi de 0,0083 a 0,0125 em `bench/comp-eficacia/000` e de 0,0080 a
  0,0060 em `003`, ou seja, adapta nos dois sentidos.
- O que se vê morrer é **entrada conhecida**, não medição (`:216`). Sai da estimativa na hora, sem custar
  certeza.
- O visto vivo é tratado como **restrição** `A ≥ y`, com projeção (`:232-237`). Não é uma medição de
  igualdade. Essa correção veio de uma falha medida: na primeira partida o NEES foi 34,9 e o σ caiu de 71
  para 2 com 10–30 de exército fora de vista (`docs/staging/estimacao-e-controle.md:65-75`). É o ciclo
  clássico de validação de filtro: consistência medida, causa achada, modelo corrigido.
- Olhar as bases inimigas sem achar exército é medição por cima, com `R = σ²/(c·Δt)` (`:238-241`). O teto de
  supply limita a variância (`:222-228`).

O motivo e o efeito estão medidos. Com o prior por tempo (`bench/t0`), nas vitórias o inimigo tinha 0–16 de
poder e o bot acreditava em 78–100 (`architecture.md:851-855`). Com o observador, a estimativa cai depois de
uma luta ganha: em `comp-eficacia/003` foi de 42,5 (σ 36,8) aos 600 s para 10,9 (σ 4,5) aos 720 s, com
`correction=coverage`. Medido nos meus scripts sobre os JSONL:

| Execução (Torches, Zerg CheatInsane, Rush+Macro, seed 1) | Commit | Resultado | `army_position` máx. | COMMIT | DEFEND (% do tempo) |
| --- | --- | --- | --- | --- | --- |
| `bench/t0` (prior por tempo) | `9457a4a` | 2 derrotas (1.842 s, 2.141 s) | 0,00 / 0,04 | nunca | 42 % / 45 % |
| `bench/comp-base` (observador, catálogo antigo) | `fd732fe` | 2V 1D 1T | 0,00–0,75 | 2 de 4 jogos | 0–22 % |
| `bench/comp-eficacia` (observador + composição) | `e647f7d` | **4V** (1.019–1.244 s) | 0,68–0,75 | **4 de 4** | 4–10 % |

O mesmo mapa, as mesmas células e a mesma seed mostram uma progressão monotônica. Uma ressalva honesta: o
`t0` sorteava o estilo e tinha limite de 2.200 s, contra 1.500 s nos outros. Mesmo assim, nenhuma das duas
derrotas do `t0` teria virado vitória antes de 1.500 s.

### 2.3 Composição: portfólio log-ótimo de Lanchester, contínuo como o autor exige

`bot/ego/planners/economy/policies/composition.py`:

- A crença sobre a composição inimiga é uma posterior de Dirichlet: o que o inimigo produziu, mais o prior da
  raça. O exército não visto vem do observador, `μ + 0,5σ − visto` (`:315-337`). Ela lê o **produzido** e
  não só o vivo, e por isso uma luta ganha não devolve o mix à doutrina. Isso foi medido: a doutrina tinha
  voltado de 0,24 para 0,70 em `comp-eficacia/000` (`estimacao-e-controle.md:106-111`), e há teste em
  `tests/test_composition.py:276`.
- A decisão maximiza `H·Σ w_e log(Σ x_i k_ie) + D·Σ b_i log x_i`, uma função côncava resolvida pelo ponto
  fixo EM (`:339-374`, cerca de 1 ms). Nenhum tipo inimigo fica sem resposta (log 0), e nenhuma unidade é
  escolhida por ranking: um Roach a mais move o mix um pouco (`tests/test_composition.py:81`). É exatamente
  o princípio "utilidade contínua, sem bônus de preferência".
- A tech que falta é descontada por `exp(−atraso/60 s)` (`:440-460`), o que resolve o "contra Colossus sem
  Starport vai de Tank" do catálogo antigo. Os dados de dano vêm do **cliente** em execução no `on_start`
  (`main.py:259`): o patch 4.10 do AI Arena e o 5.0.14 local são precificados cada um pelo seu.

### 2.4 Usa o Ares para a mecânica e corrige só o que mediu

A macro inteira roda no `MacroPlan` do Ares (`bot/body/behaviors/economy.py:199-221`): `AutoSupply`,
`BuildWorkers`, `GasBuildingController`, `ExpansionController`, `UpgradeController`, `SpawnController` e
`ProductionController`. A abertura vem do `build_order_runner.switch_opening` (`main.py:258`) e o movimento de
`PathUnitToTarget`, `AMove` e `SiegeTankDecision`. O bot só intervém onde um bench mostrou defeito no Ares, e
cada intervenção cita o número:

- `ExactResearch`: o `UpgradeController` "pesquisou" o plating 950 vezes e travou o `MacroPlan`
  (`economy.py:16-26`, `bench/smoke-mech`).
- Add-ons fora do `MacroPlan`: 9 de 13 Factories estavam sem add-on aos 502 s (`economy.py:28-38`).
- `freeflow` no múltiplo exato das proporções, em que o `SpawnController` não treinava nada
  (`economy.py:6-12`).

### 2.5 Disciplina de engenharia

- Há 602 testes para cerca de 15 mil linhas de bot, e os nomes funcionam como especificação, por exemplo
  `test_the_army_seen_to_die_leaves_the_estimate_at_once_and_costs_no_certainty`
  (`tests/test_enemy_army.py:49`) e `test_the_same_awareness_decides_the_same_intent`
  (`tests/test_strategy.py:255`).
- O harness amarra cada partida a commit, SHA do Ares, árvore suja e fingerprint da configuração
  (`harness/record.py:34-35,103`), com intervalo de Wilson (`harness/summary.py:23`).
- Os números mágicos têm proveniência no docstring. `OPENING_STALL_BANK` vem de 17 aberturas que nunca
  passaram de 680 minerais; a meta de gás vem das amostras do `bench/base3` (`investment.py:23-50`).
- A seção **"Medido e revertido"** tem cinco hipóteses que saíram do código depois do bench
  (`architecture.md:866-878`), entre elas o combat sim do Ares, que dava "vitória enfática" em lutas
  perdidas. Isso é raro em projetos amadores.
- O próprio autor escreve que "o placar não separa nenhuma mudança" (`architecture.md:814-815`) e mede o
  mecanismo no JSONL. Há tags de rollback (`pre-observador`, `virada-observador`) e um ciclo de vida
  explícito para o trabalho em andamento (`docs/staging/README.md:13-16`).

### 2.6 Observabilidade que paga o próprio custo

O catálogo de eventos tem schema versionado (`architecture.md:649-695`), cada decisão registra `reason` e
`inputs`, e há viewer, SVG do campo e overlay. Não é vaidade: foi assim que apareceram o NEES 34,9, o `bool`
do numpy que fazia o log rejeitar 838 eventos `planner.economy_planned` (`estimacao-e-controle.md:72-74`), os
6 Liberators no SURVIVE e o mix voltando à doutrina.

### 2.7 Custo computacional

Medi o `logs.frame_perf` de `comp-eficacia/000-003`, com a telemetria ligada: o frame do bot tem mediana de
6,5 a 9,6 ms e p95 de 12,9 a 15,0 ms. Contra o PhantomBot no ambiente AI Arena foram 7,12 ms por step, contra
19,08 ms do adversário (`tools/aiarena_local/PHANTOMBOT.md`).

### 2.8 Mapa

- A topologia tem passagens dinâmicas: mineral walls e rocks são seguidos pelas tags dos blockers. A
  validação em Torches mostrou a rota caindo de 4 passagens para 1 sem reconstruir a geometria
  (`docs/passages.md:44-61`).
- O staging do anchor é um score contínuo, `−reaction + choke − exposure`, com distâncias por terra
  (`map_control/policies/staging.py:22-56,401-420`), comparado com a política anterior em partida real
  (`architecture.md:817-837`).
- A barreira de Sensor Towers é o menor número de torres que sela as bases pelo ar, via Dijkstra sobre
  nó × paridade (`intel/policies/sensor_towers.py:1-10`).

## 3. Fraquezas que admito

| # | Fraqueza | Onde | Status |
| --- | --- | --- | --- |
| W1 | **Micro primitivo**: ATTACK é `AMove` + Stim + Medivac indo ao centro do grupo; o RETREAT usa `sense_danger=False` | `body/behaviors/attack.py:58-76`, `retreat.py:37` | Documentado (`architecture.md:743-745`, OS1/OS2 em `bots-opensource.md:62-103`). Aceitável **arquiteturalmente**, porque é local ao Body. **Não** aceitável competitivamente: perdeu para o PhantomBot (Elo 1963) aos 10:50 (`PHANTOMBOT.md`, n = 1) |
| W2 | **Não fecha o jogo**: a ofensiva mede compromisso e reunião contra o exército inteiro | `offense/planner.py:157,264`; `gaps.md:260` (I1, alta) | Documentado como o próximo limite (`staging/README.md:36-39`). Melhorou com o COMMIT, que agora abre, mas o I1 continua aberto |
| W3 | **DEFEND dispara demais**: a pressão conta qualquer contato com `power > 0`, workers e estruturas armadas incluídos; o `cover` é calculado e a ameaça o ignora | `awareness/model.py:463-481`; `gaps.md:274-296` (I2, I3) | DEFEND em cascata decidido (`estimacao-e-controle.md:124-128`). No `t0`, 42–45 % do tempo em DEFEND nas derrotas |
| W4 | **Evidência estatística fraca**: uma seed por célula; o 4/4 tem Wilson de 0,51 a 1,00. Observador e composição entraram **sem bench**, contra a prática do próprio autor | `estimacao-e-controle.md:40-41`; `staging/README.md:29-30` | Decisão consciente, com tags de rollback, mas é dívida a pagar **agora** |
| W5 | **Crash do Ares não documentado**: `GridManager._handle_generic_unit` → `KeyError: 0` derrubou `bench/t0/004` e `005` (Magannatha × Terran, aos 1.106 s e 834 s). `on_step` não tem guarda | `ares-sc2/.../grid_manager.py:808`; `main.py:269-273` | **Não está** em "Falhas de ambiente conhecidas" (`architecture.md:880-885`). Isto eu chamo de erro, não de dívida: no ladder é derrota certa |
| W6 | **Calculado sem consumidor**: `radar_blips` não chega à Awareness; a `OpeningBelief` não chega à Strategy; o campo é calculado inteiro todo frame; a telemetria roda no ladder | `attention/frame.py:90,142`; `architecture.md:731`; `gaps.md` C1, C12 | Documentado e barato; é instrumentação antes de decisão |
| W7 | **Cortes residuais contra o próprio princípio**: `min_share` 0,05, `economy ≥ 0,5` para expandir, gates com histerese | `composition.py:128-129`; `investment.py:148`; `strategy.py:110-128` | Ficam na fronteira com atuadores discretos do Ares (`composition.py:55-59`). A lei de gasto contínua que substitui o liga/desliga por postura está escrita (`estimacao-e-controle.md:129-133`) |
| W8 | **Lacunas do modelo de combate**: não modela alcance, upgrades, feitiços nem cura; o Marine leva 93 % contra Zergling. Os parâmetros do observador foram calibrados só contra CheatInsane | `estimacao-e-controle.md:76-81,113-116` | Documentado, com a direção certa: um termo físico, não um bônus |

Sobre o `gaps.md`: ele é de 2026-09-18 e não marca como resolvidos o I8 (hoje o estilo tem seed pelo hash do
oponente, `main.py:252-256`), o L3 (o cancelamento gracioso é usado em RECOVER, `offense/planner.py:202`)
nem vários achados A do `novas_propostas.md` (A1, A2, A12–A15). É uma falha de higiene, mas para o lado bom:
o documento subestima o bot atual.

## 4. Antecipação dos ataques do crítico

**A1. "Kalman e Lanchester num bot que dá a-move e perdeu para o PhantomBot."** A teoria não está ali por
estética: corrigiu um defeito de **decisão** medido. Com o prior, o bot nunca abria COMMIT e só pressionava
por `power_spike`. Com o observador, abre COMMIT em 4 de 4 jogos e vence antes de 1.250 s (tabela 2.2). As
duas peças custam cerca de 900 linhas e 1 ms por frame. A derrota para o PhantomBot é n = 1, na primeira
partida da história contra um bot de ladder, e o gargalo dela é o Body (W1), que o contrato deixa trocar
sem tocar no Ego. Concordo que o micro é a próxima fronteira; discordo que isso invalide a base.

**A2. "10 de 14 partidas dos benches de composição deram crash."** Não procede. Nas duas execuções, 9 das 10
são o run sendo derrubado: códigos de saída do Windows `0x40010004` (processo terminado) e `0xC000026B`
(DLL init falhou com a sessão encerrando), ou `ConnectionAlreadyClosed` com 10–13 s de relógio. Nenhum
frame foi jogado, e o doc registra "interrompidos" (`estimacao-e-controle.md:106-107`). A décima é a
conexão do cliente caindo aos ~1.250–1.310 s, na **mesma célula** (Zerg RandomBuild bio) nas duas
execuções. Isso merece investigação e eu não vou chamar de ambiente sem prova. O crash do Ares no
Magannatha (W5) é real, e eu o admito.

**A3. "Nada disso é estatisticamente significativo."** Para o placar, correto, e o autor diz isso primeiro
(`architecture.md:814-815`). Mas a afirmação central não é "ganha X %". É "a crença deixou de ser um piso
irrefutável", e essa se mede com milhares de amostras por partida: viés de +9,7 para +1,7, erro absoluto de
18,0 para 12,8 (`estimacao-e-controle.md:67-68`), `army_position` máximo de 0,04 para 0,75 e DEFEND de
42–45 % para 4–10 % do tempo. Mesmo assim, a minha melhoria nº 1 abaixo é exatamente pagar essa dívida.

**A4. "Ele viola os próprios princípios: cortes e histerese por todo lado."** A ordem que o autor prescreve
é "crença robusta antes de histerese" (`estimacao-e-controle.md:24-26`), e foi seguida: o falso
"estou atrás" foi corrigido no estimador, não afinando gates. Nenhum gate foi mexido depois da troca
(`architecture.md:772-774`). Os cortes que sobram estão onde o atuador é discreto: o `SpawnController` do
Ares ignora tipos abaixo de 5 %, e a postura é uma intenção de 5 níveis. Cada um tem o motivo escrito ao
lado, e a substituição contínua já tem forma: um PI com preditor de Smith e anti-windup
(`estimacao-e-controle.md:129-133`).

**A5. "Arquitetura e docs inchados: 3.870 linhas de docs, 2.700 de logs, 700 de relocation."** A
telemetria é o instrumento que achou todos os bugs citados em 2.6. A topologia (1.396 linhas) alimenta o
staging, as passagens, as rotas do scout e a barreira de radar. A relocation de Tanks (698 linhas) é, sim,
um remendo para o placement do Ares, que empacota a produção sem corredores. O corredor da rampa
(`keep_clear`, `main.py:263-265`) é a correção estrutural parcial. Concedo dois pontos: o `architecture.md`
(885 linhas) é denso demais para servir de onboarding, e o `gaps.md` precisa de notas de estado.

## 5. Melhorias que eu proporia, em ordem

| # | Melhoria | Custo | Impacto esperado |
| --- | --- | --- | --- |
| 1 | **Bench de verdade antes de qualquer feature**: 3 seeds × 3 raças × {Rush, Macro, RandomBuild} × estilo (bio; mech só contra Zerg), em 2 mapas, mais `tools/replay_truth.py` (instalar `sc2reader` num venv à parte) para `bias`, `nees` e `in_2sigma` | Zero código; cerca de 60 partidas, ~15 h de máquina | Converte "4/4 na seed 1" em intervalo, calibra `growth`/`power_drift`/`sigma_margin` com NEES, e decide se o observador e a composição ficam. É pré-requisito de tudo abaixo |
| 2 | **Robustez para o ladder**: (a) guarda no Ares contra unidade de tipo desconhecido (patch mínimo no `GridManager` ou filtro antes dele); (b) no ladder, um `try/except` em volta de `play_frame` que registra o erro e deixa o frame só com o macro do Ares; (c) documentar o `KeyError: 0` em "Falhas de ambiente"; (d) investigar a queda do cliente na célula Zerg RandomBuild bio | Horas | Elimina derrotas certas: 2 das 6 partidas jogadas do `t0` acabaram nesse crash |
| 3 | **Micro com os behaviors que o Ares já tem** (OS1/OS2): `ShootTargetInRange` + `StutterUnitBack`/`KeepUnitSafe` para ranged, RETREAT com `sense_danger=True`, Medivac com cura e posição segura | 2–4 dias, só em `body/behaviors/` (`attack.py`, `hold.py`, `retreat.py`, `combat.py`) | O maior ganho contra bots reais, e o contrato garante que o Ego não muda |
| 4 | **I1 + reforços agrupados** (N7.1/OS6): a missão mede compromisso e reunião pelo `MissionFeedback` (poder concedido), e a unidade nova se junta no anchor antes de seguir o squad | 1–2 dias, testável sem partida | Ataca o `assembled_share` de 0–0,22 e os timeouts com o bot em 200/200 contra CheatInsane |
| 5 | **DEFEND em cascata + definição única de atacante** (I2, I3, C6): a Strategy lê o déficit da Defense (pedido − concedido, o `GrantStatus` que já existe), e workers e estruturas estáticas saem da pressão ou entram pelo dano possível à base | 2–3 dias + bench | Menos DEFEND falso (42–45 % do tempo nas derrotas do `t0`) e menos ataques cancelados em ASSEMBLE (7 de 12) |
| 6 | **Informação no meio do jogo**: `radar_blips` como medição de cobertura do observador (as torres já são construídas), scan de reconhecimento na rota do avanço e não na luta (o que o `bench/6e3` ensinou) | 2–3 dias | Dá ao filtro medições depois dos 240 s e deixa o σ honesto, que é o que o `μ + kσ` precisa |
| 7 | **Lei de gasto contínua** (PI com preditor de Smith, saturação no supply 200 e no teto de produção) | Alto; o atuador do Ares não aceita `u` contínuo | Remove os cortes de W7, mas só depois de 1–5: sem bench, não se sintoniza malha nenhuma |

Em resumo: a base de decisão é o que este bot tem de melhor, e a evidência, ainda que pequena, aponta
na direção certa. O que falta é execução (micro), robustez (crash), fechamento (I1) e amostra. São quatro
itens, todos com endereço no código e custo estimável.
