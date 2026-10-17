# M3 — Ameaça e defesa

↑ [Marcos](README_MILESTONES.md)

**Objetivo:** o que conta como ameaça é o que de fato ameaça, e o DEFEND da Strategy só abre quando a defesa local
não dá conta.

**Critério de saída:** nenhum DEFEND com cobertura/pressão ≥ 3, e o tempo em DEFEND nas derrotas medido contra os
42–45 % do `bench/t0`.

**Depende de:** [M2](m2-medicao.md) (o bench de comparação). O [M5](m5-fechar-o-jogo.md) depende deste: a Offense só
larga um ENGAGE pela Defense quando a Defense recebeu `PARTIAL`/`REJECTED`.

## O que é ameaça

**DEFEND pela ameaça líquida** [D3, C2, P0.2] — `threat_level` é o `danger` bruto: o DEFEND disparou com 3 Marines
de pressão diante de 49 de cobertura, e cancelou um ENGAGE com +0,42 de vantagem. `BaseThreat.cover` e `balance`
são calculados e só vão para o log. Direção: pressão contra cobertura, contínua; a Offense só larga um ENGAGE se a
Defense recebeu `PARTIAL`/`REJECTED`. Aceite: nenhum DEFEND com cobertura/pressão ≥ 3.

**DEFEND em cascata** [estimação e controle] — a direção decidida em 03/10 para o item acima, pela regra "a malha
externa vê o erro da interna, não a perturbação". Hoje o DEFEND dispara com 3–4 Marines de pressão mesmo com 10–53
de cobertura na base (`bench/t0`: 42–45 % do tempo em DEFEND nas derrotas, 7 de 12 ataques cancelados no ASSEMBLE).
A malha externa passa a ler o déficit da Defense — poder pedido menos concedido, o `GrantStatus` que nenhuma missão
lê (C6, abaixo) — ou a ameaça líquida da cobertura (`balance`, C2). DEFEND passa a significar "a malha interna
saturou". O porquê está no [registro](registros/estimacao-e-controle.md#a-virada).

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

## Defense

**A concessão parcial não muda nada** [C6, P1.4] — a `DefendAreaMission` recebe o `MissionFeedback` e não lê o
`GrantStatus`: uma defesa com metade do orçamento segue igual, sem escalar nem avisar a Strategy. É a medição de
que o DEFEND em cascata precisa.

**Em DEFEND, o MapControl espera no CC** [I17] — o anchor vai para a base ameaçada, enquanto a Defense ataca no
centro do incidente: quem a Defense não pegou espera no townhall em vez de entrar na luta.

**Partes aérea e terrestre competem** [I14, C8] (baixa) — as duas partes de um incidente são alocadas uma depois
da outra; a aérea leva os Marines mais perto, e a terrestre puxa Tanks de longe. O `demand_id` que as une só
existe no log.

**Cancelamento que nunca acontece** [L3, D10] (baixa) — nenhum planner pede o cancelamento de uma
`DefendAreaMission`; o ramo `CANCELLED` dela só roda nos testes.

## Pesquisa

- **OS9 — ameaça regional pela distância de rota** ([bots-opensource](pesquisa/bots-opensource.md#os9--ameaça-regional-usando-distância-de-rota-p2-médioalto)):
  alcance por caminho em vez de raio, para o I2.
- **OS4, OS5, LL11 — rush, reparo e bunker operacionais**: a primeira parte entrou com a resposta a rush, que
  está sendo medida no [M2](m2-medicao.md); o reparo com orçamento e destino persistente continua em aberto
  ([OS5](pesquisa/bots-opensource.md#os5--reparo-com-orçamento-e-destino-persistente-p1-médio),
  [LL11](pesquisa/ladder-local.md#ll11--reparo-e-bunker-precisam-estar-operacionais)).
- **Harass e defesa posicional** no [migration-map](pesquisa/migration-map.md#harass-e-defesa-posicional).
