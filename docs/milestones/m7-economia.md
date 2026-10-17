# M7 — Economia

↑ [Marcos](README_MILESTONES.md)

**Objetivo:** o gasto segue o mix e o recurso que falta, numa ordem decidida no Ego, em vez da ordem de registro
no Body e do liga/desliga por postura.

**Critério de saída:** a fixar com o E2, que mede o que explica o banco. A medida comum com o
[M5](m5-fechar-o-jogo.md) é o banco no supply máximo (13 a 16 mil hoje).

**Depende de:** [M2](m2-medicao.md) (o veredito da composição por eficácia) e [M6](m6-intel.md) (a troca de
abertura).

O design e as decisões da economia estão no [registro de 19/09](registros/economia-e-builds.md); a composição por
eficácia, no [registro da virada](registros/estimacao-e-controle.md#composição-por-eficácia-working-tree-sem-bench).
O que falta deles está abaixo.

## Itens

**Medir a trava do `SpawnController`** [E2] — `SpawnMode` ganha `blocked_by` (o tipo em que o Ares para) e
`short_of` (o recurso que faltou). Mede se a trava por prioridade (o Tank sem gás impede o Marine) explica o banco.
Depois: prioridade calculada pelo planner [E4], se a trava se confirmar.

**O mix lê o banco e o supply** [E5] — preço-sombra: a composição em gasto, convertida em cabeças pelo recurso que
falta agora (gás no começo, minerais depois, supply no fim). O gás alvo segue o consumo do mix.

**Lei de gasto contínua** [estimação e controle] — `alvo = μ̂(t+τ) + kσ̂(t+τ)`,
`erro = alvo − (exército + exército na fila)` (o termo da fila é um preditor de Smith: sem ele um controlador de
alvo dá overshoot pelo tempo de produção), `u_army = PI(erro)` saturado com anti-windup (supply 200, teto de
produção). Substitui o liga/desliga de upgrades, add-ons e expansão por postura. O atuador é o Ares, que não aceita
um `u` contínuo: a tradução passa por reserva de minerais ou ordem de prioridade.

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
da abertura. Depende da informação ([M6](m6-intel.md)).

**Nenhum MULE na abertura** [I9] — `mules = spend.active`, e o plano só fica ativo no fim da abertura: a energia
do primeiro Orbital acumula sem uso.

**Lugar para expandir** [I16] (baixa) — `room = bases < sites` conta as expansões que o inimigo ocupa: com todas
tomadas, o pedido de expansão continua.

## Pesquisa

- **LL1 — mix, objetivo absoluto e reserva para transição**, **LL2 — gás e investimento sob supply máximo**,
  **LL3 — expandir por recursos úteis** e **LL4 — upgrades e tech como decisões distintas**
  ([ladder-local](pesquisa/ladder-local.md#phantom-o-que-interessa-para-o-late)). Diagnosticar o gasto maxed antes
  de mudar a política.
- **OS8 — aberturas por matchup e transições justificadas**
  ([bots-opensource](pesquisa/bots-opensource.md#os8--aberturas-por-matchup-e-transições-justificadas-p1-médio)).
- **Demanda de exército e capacidade de produção** no
  [migration-map](pesquisa/migration-map.md#demanda-de-exército-e-capacidade-de-produção).
