# M5 — Fechar o jogo

↑ [Marcos](README_MILESTONES.md)

**Objetivo:** o exército chega junto, luta bem e termina a partida, em vez de acumular banco no supply máximo.

**Critério de saída:** `assembled_share` mediano > 0,6; banco < 5 mil no supply máximo; razão de troca ≥ 1 em
ENGAGE; passar dos 10:50 contra o PhantomBot.

**Depende de:** [M3](m3-ameaca-e-defesa.md) (a Defense não toma o exército que está atacando sem precisar) e
[M4](m4-poder-e-estimativa.md) (o poder comparado no ENGAGE). As métricas de troca vêm do [M2](m2-medicao.md).

## Itens

**Compromisso e reunião medidos no exército inteiro** [I1, N7.1, A8, D7] (alta) — `assembled` é poder perto do
rally / exército inteiro, e `committed` é o exército inteiro na abertura: o que a Defense segura e o que acabou de
sair da fábrica contam. Medido contra Zerg CheatInsane: `assembled_share` de 0 a 0,22, todo jogo sobrevivido
termina em timeout. Direção: a missão mede pelo que recebeu (`MissionFeedback.power`), e o reforço se junta no
anchor antes de seguir o squad, em vez de atravessar o mapa sozinho. Aceite: `assembled_share` mediano > 0,6;
banco < 5 mil no supply máximo.

**Micro pelo Ares** [D6, N6, A9, A10, P1.3] — ATTACK é attack-move, RETREAT e HOLD andam sem desviar de perigo
(ver [Attack](../body/behaviors/attack.md)). O Ares já tem `ShootTargetInRange`, `StutterUnitBack`, `KeepUnitSafe`,
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

## Pesquisa

A ordem das duas pesquisas para este marco: micro de bio primeiro, depois reforços em grupo, depois o alvo.

- **OS1 — micro ranged: kite, foco e esquiva** e **OS2 — sobrevivência no recuo e Medivac seguro**
  ([bots-opensource](pesquisa/bots-opensource.md#os1--micro-ranged-kite-foco-e-esquiva-p0-médio)), com
  **LL8 — foco com reserva de dano e avanço durante o cooldown**
  ([ladder-local](pesquisa/ladder-local.md#ll8--foco-com-reserva-de-dano-e-avanço-durante-o-cooldown)).
- **OS6 — reforços chegando em grupo** e **LL9 — agrupar durante a marcha**
  ([ladder-local](pesquisa/ladder-local.md#ll9--agrupar-durante-a-marcha-além-do-assemble-inicial)), para o I1.
- **LL10 — atacar a base menos cara de alcançar e vencer**
  ([ladder-local](pesquisa/ladder-local.md#ll10--atacar-a-base-menos-cara-de-alcançar-e-vencer)), para o N7.4, e
  **LL12 — transição e cleanup**.
- Harass de Hellion do Ketroc
  ([bots-opensource](pesquisa/bots-opensource.md#reuso-de-código-e-itens-para-depois)), para o N7.3, depois de
  orçamento, rota segura e retirada.
