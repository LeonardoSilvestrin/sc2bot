# M4 — Poder e estimativa

↑ [Marcos](README_MILESTONES.md)

**Objetivo:** um modelo de poder só, que veja casters, alcance e upgrades, e um observador do inimigo
consistente com a verdade dos replays.

**Critério de saída:** HT, Infestor, Viper, Disruptor, Oracle e BC com poder > 0; observador com NEES entre 0,5 e
2, ≥ 85 % em 2σ e bases a ±1 contra o `replay_truth`.

**Depende de:** [M2](m2-medicao.md) (benches e replays para comparar). O [M5](m5-fechar-o-jogo.md) depende deste:
ENGAGE e RETREAT comparam poder.

## Itens

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

**Observador mais rico** [estimação e controle] — workers vistos como medição de renda (não só limite), cobertura
pelo mapa e não só pelas bases, composição por tipo no estado (hoje a `CompositionPolicy` lê o visto por tipo e só
o poder escalar do observador). Os parâmetros a calibrar estão no
[registro](registros/estimacao-e-controle.md#parâmetros-a-calibrar-com-o-replay_truth).

**O Marine vence no modelo de combate** [composição por eficácia] — pela lei quadrada por custo o Marine é das
unidades mais eficientes do jogo: bio contra 200 de Zergling vai a 93 % de Marine. O modelo não vê alcance (melee
que não encosta, kite), upgrades, feitiços nem cura. Se o bench do [M2](m2-medicao.md) mostrar que isso pesa, o
próximo termo é físico (alcance/superfície de contato ou custo em supply perto do teto), não um bônus.

## Pesquisa

- **LL5 — combate por alcance, tempo e alvos válidos** e **LL6 — detector e caster com comportamento próprio**
  ([ladder-local](pesquisa/ladder-local.md#ll5--combate-por-alcance-tempo-e-alvos-válidos)).
- **OS7 — Raven como detecção móvel** e **OS10 — simulação local como sinal**
  ([bots-opensource](pesquisa/bots-opensource.md#os10--simulação-local-como-sinal-adicional-p2-alto)), depois de
  cenários e replays suficientes.
- **Estimativa do inimigo como distribuição** no
  [migration-map](pesquisa/migration-map.md#estimativa-do-inimigo-como-distribuição).
