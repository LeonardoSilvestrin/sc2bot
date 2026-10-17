# Backlog

↑ [Desenvolvimento](README_DEV.md)

O que ainda não foi feito, conferido no código em 17/10/2026. Um item por problema, do mais urgente ao menos.
O que já foi decidido e está em andamento fica em [staging/](staging/README.md); quando um item daqui é
decidido, ele vai para lá.

Este documento junta cinco revisões antigas, que saíram da árvore em 17/10. Os ids entre colchetes são delas, para
quem quiser o raciocínio completo no git:

| Ids | Revisão | Onde está |
| --- | --- | --- |
| P0–P2 | Propostas de 14/09 (o que aprender de outros bots, roadmap) | `git show 1122cba:docs/dev/propostas.md` |
| A1–A15, N1–N8 | Revisão de 18/09 (achados e propostas) | `git show 1122cba:docs/dev/novas_propostas.md` |
| E1–E9 | Revisão de 18/09 da economia e da composição | `git show 1122cba:docs/dev/melhorias_propostas_eco.md` |
| C, F, L, I | Achados de revisão do código de 18/09 | `git show 8c3f9d3:docs/dev/gaps.md` |
| D1–D10 | Plano final do debate de 04/10 entre dois agentes | `git show 1122cba:docs/dev/agent_discussion/README.md` |

## Onde o bot está

O veredito do debate de 04/10 continua valendo: **a parte que decide é boa; quem perde jogo é o resto.** O pipeline
é acíclico, o Engine é o único dono das unidades, a telemetria é auditável e o frame leva de 6,5 a 9,8 ms. O que
perde jogo: um crash contra Terran, um DEFEND que dispara diante de cobertura de sobra, casters valendo poder zero,
micro de a-move e um exército que não fecha o jogo (13 a 16 mil minerais no banco com supply máximo). As duas
maiores mudanças desde então (observador e composição) entraram sem bench, e quase todo item do staging espera o
mesmo bench. Por isso a ordem abaixo começa por não perder por crash e por medir.

## 1. Não perder por crash

**Blips de radar derrubam o bot** [D1] — o Ares não filtra os blips das nossas Sensor Towers, e um `KeyError: 0`
encerra a partida contra Terran. Direção: sobrescrever `_should_add_unit` no bot (o Ares só o chama para unidades
inimigas), sem forkar o Ares; até lá, pausar as torres. Aceite: Terran CheatInsane, 3 seeds, 0 crash.

**Uma exceção derruba o frame inteiro** [D1, N8, P0.5] — não há `try` em volta de `play_frame` nem de cada
planner. Direção: o planner que falha devolve um plano neutro e registra o erro; sem frame, só o macro do Ares.

## 2. Medir

**Bench da planta atual** [D5, N1, P0.1] — nenhuma partida decidida contra Protoss e uma só contra bot de ladder.
O harness e o `aiarena_local` já jogam tudo: 3 raças × {Rush, Macro, RandomBuild} × 3 seeds × 2 mapas, mais
PhantomBot × 5, com `tools/replay_truth.py` em todos. Aceite: ≥ 18 partidas decididas por raça, Wilson por raça.
Este bench destrava a avaliação de quase todo o staging.

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

## 3. O que é ameaça

**DEFEND pela ameaça líquida** [D3, C2, P0.2] — `threat_level` é o `danger` bruto: o DEFEND disparou com 3 Marines
de pressão diante de 49 de cobertura, e cancelou um ENGAGE com +0,42 de vantagem. `BaseThreat.cover` e `balance`
são calculados e só vão para o log. Direção: pressão contra cobertura, contínua; a Offense só larga um ENGAGE se a
Defense recebeu `PARTIAL`/`REJECTED`. Aceite: nenhum DEFEND com cobertura/pressão ≥ 3.

**Quem conta como atacante** [I3, P0.2] (alta) — incidentes e pressão contam todo contato com poder > 0: um worker
de scout abre uma `DefendAreaMission`, e uma estrutura estática (Cannon, Spine, Planetary) mantém incidente por
até ~12 min depois de sair de vista. Direção: uma definição única de atacante, com workers e estruturas à parte, e
distinguir scout, worker rush e ataque.

**Contato velho fica mais ao alcance** [I2] — o alcance de um contato até a base é `base_reach + incerteza`, e a
incerteza cresce com a idade: um squad que recuou entra no alcance segundos depois e abre um incidente contra o
nada. O campo já separa o possível (`threat`) do crível (`enemy`); incidentes e `danger` usam só o possível.

**Base em construção conta como base** [I4] — `_bases` não filtra `is_ready`: no frame em que o CC é posto,
sobem a saturação, o gás, o teto de produção, as candidatas do MapControl e o pedido de turret.

**Cloak visto uma vez vale para sempre** [I10] — `cloak_seen_at` nunca volta a `None`: daí em diante toda base
pede turret e cada Orbital guarda energia de scan (um MULE a menos), até o fim do jogo. Direção: uma crença que
decai.

**Três definições de exército** [I5] (baixa) — o Engine concede `is_army` (Medivac entra), a Awareness soma
`not is_worker and power > 0` (Medivac sai, AutoTurret entra). O poder comparado e o conjunto concedido não são
o mesmo.

## 4. Poder e estimativa

**Um modelo de poder só, com casters** [D4, A13] — a Attention tira o poder do dps, então HT, Infestor, Viper,
Disruptor, Oracle e o BC (sem Interceptors) valem 0; a economia tem o seu próprio modelo de combate
(`combat.yml`). Um Tank nosso dominado por Neural Parasite já virou "produção Zerg". Direção: a Attention usa o
`CombatModel`, com valor de feitiço e Interceptors, e uma tag que já foi nossa não entra na produção inimiga.

**Alcance, bônus e upgrades fora do poder** [A13, I18, P0.3] — as lutas perdidas contra Terran são contra Siege
Tanks em siege, de fora da visão; +3 de ataque não entra no poder. A escala "em Marines" (`MARINE_POWER`) usa o
dps da velocidade *faster*; se a API der o *normal*, um Marine vale 0,84 e os limiares absolutos pesam ~19 % a
mais. Verificar no `army_power` de um jogo só de Marines.

**Observador: bases como estado medido** [D8] — as bases acreditadas nunca ficam abaixo do prior, e a queda de
`g` absorve o erro. Direção, offline primeiro: rodar `EnemyArmyFilter.update` sobre os `awareness.updated` de
`comp-eficacia/000-003` com as bases como estado e comparar com `replay_truth`. Aceite: NEES entre 0,5 e 2,
≥ 85 % em 2σ, bases a ±1.

## 5. Fechar o jogo

**Compromisso e reunião medidos no exército inteiro** [I1, N7.1, A8, D7] (alta) — `assembled` é poder perto do
rally / exército inteiro, e `committed` é o exército inteiro na abertura: o que a Defense segura e o que acabou de
sair da fábrica contam. Medido contra Zerg CheatInsane: `assembled_share` de 0 a 0,22, todo jogo sobrevivido
termina em timeout. Direção: a missão mede pelo que recebeu (`MissionFeedback.power`), e o reforço se junta no
anchor antes de seguir o squad, em vez de atravessar o mapa sozinho. Aceite: `assembled_share` mediano > 0,6;
banco < 5 mil no supply máximo.

**Micro pelo Ares** [D6, N6, A9, A10, P1.3] — ATTACK é attack-move, RETREAT e HOLD andam sem desviar de perigo
(ver [Attack](../behaviors/attack.md)). O Ares já tem `ShootTargetInRange`, `StutterUnitBack`, `KeepUnitSafe`,
`MedivacHeal` e `PickUpCargo`. Os 6 ataques perdidos no debate entraram com parcela local de 0,85 a 0,90: o problema
foi a luta, não a reunião. Fatias: bio (alvo e stutter), recuo com `sense_danger`, Medivac, posição do Tank,
evasão de efeitos. Aceite: razão de troca ≥ 1 em ENGAGE; passar dos 10:50 contra o PhantomBot.

**PRESSURE com exército atrás** [D, divergência] — `min(1, 2·share)·power_spike` deixa abrir PRESSURE com
`army_position < 0`. Contar no bench quantos ataques abrem assim e como terminam; se precisar, um fator que vá a
zero suavemente, não um corte.

**O ataque nunca termina bem** [I13] (baixa) — a `MainAttackMission` não tem caminho para `COMPLETED`, e o SEARCH
gira pelas expansões sem fim.

**Ideias sem dono:** segundo squad de harass, drop ou Hellions na mineração longe do exército inimigo [N7.3];
alvo de maior valor por risco da rota, em vez da estrutura mais perto do rally [N7.4].

## 6. Defense

**A concessão parcial não muda nada** [C6, P1.4] — a `DefendAreaMission` recebe o `MissionFeedback` e não lê o
`GrantStatus`: uma defesa com metade do orçamento segue igual, sem escalar nem avisar a Strategy.

**Em DEFEND, o MapControl espera no CC** [I17] — o anchor vai para a base ameaçada, enquanto a Defense ataca no
centro do incidente: quem a Defense não pegou espera no townhall em vez de entrar na luta.

**Partes aérea e terrestre competem** [I14, C8] (baixa) — as duas partes de um incidente são alocadas uma depois
da outra; a aérea leva os Marines mais perto, e a terrestre puxa Tanks de longe. O `demand_id` que as une só
existe no log.

**Cancelamento que nunca acontece** [L3, D10] (baixa) — nenhum planner pede o cancelamento de uma
`DefendAreaMission`; o ramo `CANCELLED` dela só roda nos testes.

## 7. Intel

**Informação de meio de jogo** [P1.1, N4, A11] — depois do scout inicial, o bot só vê o que o exército encontra,
fora a busca de proxy, os scans contra cloak e as Sensor Towers. Direção: o Reaper da abertura como sensor, scan
quando uma pergunta envelhece (tech desconhecido há 90 s, terceira não vista), e um Marine de vigia nos caminhos de
ataque, como `HOLD` de `count=1`. Primeiro consumidor: a troca de abertura (§8).

**Scan contado antes de acontecer** [I11] (baixa) — o planner registra o scan ao planejá-lo e não lê o
`DetectionReport.scanned_by`; se o Body não escanear, a área conta como coberta.

## 8. Economia

O design e as decisões da economia estão em [staging/economia-e-builds.md](staging/economia-e-builds.md). O que
falta dele:

**Medir a trava do `SpawnController`** [E2] — `SpawnMode` ganha `blocked_by` (o tipo em que o Ares para) e
`short_of` (o recurso que faltou). Mede se a trava por prioridade (o Tank sem gás impede o Marine) explica o banco.
Depois: prioridade calculada pelo planner [E4], se a trava se confirmar.

**O mix lê o banco e o supply** [E5] — preço-sombra: a composição em gasto, convertida em cabeças pelo recurso que
falta agora (gás no começo, minerais depois, supply no fim). O gás alvo segue o consumo do mix.

**Upgrades e add-ons seguem o mix** [E8, N2.5] — o valor de um upgrade é a parcela do gasto nas unidades que ele
melhora; `reactor_share` para todo tipo de produção; Engineering Bays em paralelo.

**A ordem do gasto decidida no Ego** [E9, N3.2] — hoje sai da ordem de registro no Body e da regra do Ares de
parar no primeiro que age. Com ela, a expansão por previsão [N3.1, A6]: "vai saturar antes de o CC ficar pronto"
no lugar de `workers ≥ saturated_at`, que inverteu 19 vezes num jogo. Também sai o portão `intent.economy ≥ 0,5`.

**Composição em shadow** [D9] — a composição por eficácia reproduz a doutrina (distância de 0,02 a 0,05, nenhum
tipo novo em 2.690 frames). Direção: decide a doutrina, o mix vai para o log, até um A/B mostrar ganho ≥ 0,1 na
razão de troca; sem ganho, sai.

**Troca de abertura por scouting** [N2.4, P1.5] — as aberturas já variam por raça e estilo, mas são escolhidas só
no `on_start`. Direção: `switch_opening` para uma variante segura quando o scout vê um sinal de rush antes do fim
da abertura. Depende da informação (§7).

**Nenhum MULE na abertura** [I9] — `mules = spend.active`, e o plano só fica ativo no fim da abertura: a energia
do primeiro Orbital acumula sem uso.

**Lugar para expandir** [I16] (baixa) — `room = bases < sites` conta as expansões que o inimigo ocupa: com todas
tomadas, o pedido de expansão continua.

## 9. Strategy e sinais sem leitor

**Ligar ou apagar** [D10, C5, N3.3, A4] — `risk` e `economy_position` só vão para o log; `greed` e `tech` da
`OpeningBelief` não têm leitor (`aggression` e `proxy` já têm: rush e Intel). Todo campo do `StrategicIntent`
deveria ter um leitor fora dos logs.

**Campo calculado inteiro todo frame** [C1, A5] — o MapControl lê o campo só nos seus candidatos, mas o
`InfluenceField` inteiro é recalculado todo frame.

## 10. MapControl e topologia

**Anchor `legacy`** [F1] — o rally antigo continua como terceira fonte do anchor quando o staging não acha
candidatas. Depois que o staging for medido num bench, sai ou vira um caso raro com alerta.

**Topologia que degrada em silêncio** [F2] — sem o MapAnalyzer, as regiões viram componentes caminháveis, o
MapControl cai no `legacy` e a rota do scout vira só o start, sem erro. Direção: uma razão de degradação em
`map.topology_built` e um teste que falhe quando o MapAnalyzer não responde num mapa do pool.

## 11. Limpeza

Não mudam decisão; de uma vez, quando der. Só o `core_army` foi reconferido em 17/10.

- **Nomes legados:** o MapControl ainda propõe com id e owner `core_army` [L1], que o viewer e o overlay conhecem;
  renomear pede `SCHEMA_VERSION` novo. Eventos `behavior.*` escritos por planners [L2].
- **Dados e arquivos mortos:** counters de unidades que nenhum estilo constrói [L5]; o `[template]_builds.yml` do
  Ares e chaves sem efeito no `terran_builds.yml` [L6]; comentários que descrevem código que não existe [L4, L7].
- **Calculado só para o log:** leituras por base, agregados da Awareness e campos da Attention sem leitor [C2–C4],
  `MissionView`/`Frame` [C7], prioridade do scout [C9], plano de economia montado durante a abertura [C11],
  telemetria inteira rodando no ladder para um `NullLogger` [C12], helpers só chamados por testes [C13].
- **Fallbacks silenciosos:** rampa da main [F3], defaults da percepção numa exceção do mediator [F4], tipo fora do
  modelo de alcance [F6], defaults duplicados nos contratos [F8], `run.py` sem `MyBotRace` [F9], local da turret
  recalculado [F10].

## O que não fazer

Juntado das cinco revisões; continua valendo.

- **Não reescrever as camadas** nem trocar o Ares: os seams atuais são o maior ativo, e o Ares é o mecanismo
  (micro, pathing, macro); a política é nossa. Não forkar o Ares vendorizado.
- **Não reimplementar o que o Ares já tem**, nem trocar o `SpawnController`/`ProductionController` por um executor
  próprio: as armadilhas dele entram no Body, como entrou o `ExactResearch`.
- **Não manter sinal sem consumidor.** Se `risk`, o campo ou um agregado não ganharem leitor, é melhor apagá-los.
- **Nada de cortes nem bônus de preferência** em scores: restrições físicas, utilidade contínua e, só por último,
  histerese. Nada de `freeflow` permanente, limiar de entrada no mix ou solver global (LP/ILP).
- **Não calibrar jogando partidas** o que o replay já responde, e não ajustar números de combate partida a partida.
- **Não variar abertura por sorteio** nem criar um planner ou estilo por matchup: a raça é entrada, não dono.
- **Não usar uma vitória isolada nem Elo como diagnóstico.** Nada entra no HEAD sem bench, e um experimento sem
  ganho medido é revertido e registrado.
- **Não começar por RL**, rede neural ou crença probabilística completa, e não copiar código externo sem conferir a
  licença.

## Já resolvido

Para não reabrir: o P0 inteiro (harness, defesa por incidente, wall nos dois sentidos, ciclo ofensivo, macro mínima,
CI com pytest e ruff); a economia como pacote com contratos próprios [E1, N2.1]; a composição por eficácia sobre o
modelo de combate, com chaves canônicas [E3, E6, E7]; aberturas por raça e estilo [N2.3]; resposta a rush com Bunker
e reparo [P0.4]; o observador do exército inimigo [P1.1]; a ofensiva pelas posturas, com `power_spike` [A7, N7.2,
I15, F7]; o limiar duplicado da abertura [I6]; a seed do estilo pelo oponente [I8]; o scout pela tag concedida
[I12]; o cancelamento gracioso da ofensiva em uso [L3, a parte da Offense]; a `ScoutMission` fora dos docs [D10].
