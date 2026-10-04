# Estimação e controle

Registro de uma virada de direção, decidida em 2026-10-03 no branch `observador` (tag de rollback
`pre-observador`, em `9457a4a`). O que já está no HEAD está descrito em
[architecture.md](../../architecture.md#matemática); aqui fica o porquê, o que vem depois e como medir.

## A virada

Até `9457a4a`, o bot decidia com crenças feitas de pisos, limiares e histerese. O exemplo mais caro era o
exército inimigo: `max(conhecido, visto vivo, prior por tempo)`, um prior que nenhuma evidência derrubava.
A direção nova é tratar o bot como uma malha de controle e cada crença como um **estimador**, com modelo,
medições e incerteza:

```text
          inimigo (perturbação que reage)
                │
  jogo ──► Attention ──► Awareness ──► Strategy + planners ──► Engine / Ares ──► jogo
           sensor com     observador     controlador            atuador: satura
           névoa                                                e tem tempo morto
```

Regras que saem disso, na ordem em que valem:

1. **Crença é estado estimado, com σ.** Um valor sem incerteza não serve de margem robusta. Isso formaliza a
   regra já escrita de "crença robusta antes de histerese": o filtro com covariância é a crença; histerese
   fica para a última camada.
2. **Margem robusta = k·σ.** Planejar contra μ + kσ, sendo k o apetite de risco, em vez de margens fixas.
3. **Cascata: a malha externa vê o erro da interna, não a perturbação.** A Strategy não deve reagir à
   pressão bruta que a Defense já trata localmente, e sim ao déficit dela.
4. **Lei contínua onde o atuador é contínuo.** Relé com tempo morto dá ciclo limite; a divisão do gasto entre
   exército e economia é contínua.
5. **Adaptativo é parâmetro no estado.** O que varia por oponente (renda por worker, fatia em exército) é
   estimado online, não fixado.

## Passo 1 — observador do exército inimigo (no HEAD)

`bot/awareness/enemy_army.py`: filtro de Kalman de `(A, g)` — exército e poder comprado por worker-segundo —
com as bases e os workers acreditados como entrada, as mortes vistas como entrada conhecida e o visto vivo
como medição censurada (limite inferior, e medição por cima enquanto as bases do inimigo estão em visão). A
Assessment planeja contra `μ + 0,5σ`. Entrou sem shadow mode e sem bench: o bot ainda não joga ladder, e o
rollback é a tag.

O motivo medido (`bench/t0`, verdade dos replays): nas duas vitórias o inimigo ficou com 0–16 de poder por
5–10 min enquanto o bot acreditava em 78–100; o bot esteve realmente à frente 49–64 % do tempo e se achou à
frente 0–1 % (com a margem que usava). Tabela completa em
[architecture.md](../../architecture.md#medições), "Observador do exército inimigo".

### Como medir

```text
.venv\Scripts\python.exe bench.py run --out bench\<rótulo>
python tools\replay_truth.py bench\<rótulo>
```

O que olhar, contra o `bench/t0`:

- **Erro do estimador** (`bias`, `mae`): deve cair, sobretudo nas partidas em que o inimigo perde o exército.
- **Consistência** (`nees`, `in_2sigma`): a média de `(verdade − μ)² / σ²` perto de 1 e ~95 % dentro de 2σ.
  Acima disso o filtro é otimista demais e o σ não serve de margem; bem abaixo, pessimista demais.
- **Decisão**: o "tempo à frente" do bot deve se aproximar do real; `strategy.posture_changed` deve passar a
  ter PRESSURE por `army_advantage` e COMMIT, que nunca abriram.
- **Efeito colateral esperado**: sem nada visto, a previsão é mais alta que o prior antigo no meio do jogo
  (74 contra 48 aos 600 s), então antes da primeira luta o bot pode se achar mais atrás do que se achava.

### Primeira partida (`bench/testando observador`, Zerg CheatInsane Rush, derrota)

Contra a mesma célula do `bench/t0`: erro médio +9,7 → **+1,7**, erro absoluto 18,0 → **12,8**. Até 800 s
o erro normalizado ficou em |z| < 1. Mas `nees` 34,9 e só 67 % dentro de 2σ: depois de uma luta aos ~820 s o
σ caiu de 71 para 2 e ficou, com 10–30 a mais do inimigo fora de vista. Causa: o limite inferior era
medição de igualdade (`R = 2²`). Corrigido para projeção na restrição `A ≥ y` com a covariância intacta, e
o `power_drift` subiu de 0,05 para 0,3 (o CheatInsane produz mais cedo do que o σ admitia: z = +3 a +4
entre 200 e 280 s). Essa partida também revelou um bug do observador: a cobertura vinha como bool do numpy
e contaminava a crença até o `expand`, e todo `planner.economy_planned` era rejeitado pelo log (838 na
partida).

### Parâmetros a calibrar com o replay_truth

`growth` (prior 0,008), a rampa `f(t)` (0,15 → 0,65 entre 240 e 600 s), `worker_rate` (0,1/s),
`coverage_sigma` (15), `power_drift` (0,3), `cap_sigma` (15) e `sigma_margin` (0,5). Os quatro primeiros
saíram dos replays do `bench/t0`, que são só CheatInsane, com renda trapaceada; um bench contra oponentes sem
cheat deve mover o `growth` aprendido para baixo — se não mover, a adaptação não está funcionando.

## Composição por eficácia (working tree, sem bench)

O que estava errado no catálogo de counters (conversa de 2026-10-03): a resposta a cada tipo inimigo era a
**primeira da lista do YAML que já tinha tech pronta** — discreta (troca de uma vez quando um Tech Lab fica pronto),
cega à tech que falta (contra Colossus sem Starport ia de Siege Tank, e nada pedia a Starport), um único counter por
tipo independente de quão melhor ele é, poder inimigo em Marines somado direto como supply nosso, e a entrada era o
visto vivo, não o observador. Algumas linhas eram ruins (`IMMORTAL: [MARINE, MARAUDER…]`).

O que entrou no lugar (o mecanismo completo está em [architecture.md](../../architecture.md)):

- **Modelo de combate** (`economy/knowledge/combat.yml`): dps de qualquer tipo contra qualquer tipo, com bônus,
  armadura, splash e overkill; os dados de tipo do cliente substituem a tabela no `on_start`, então o 4.10 do AI
  Arena e o 5.0.14 local são precificados cada um pelo seu patch.
- **Crença de composição**: Dirichlet (produzido + prior da raça) e o não visto do observador (μ + 0,5σ − visto
  vivo) espalhado por ela. O produzido (`produced_enemy_types`, toda unidade já vista, morta ou viva, τ = 360 s)
  é a evidência de composição e o peso contra a doutrina; o vivo diz o que está presente; o observador, *quanto*
  exército não foi visto. A composição por tipo no estado do observador (item 3 abaixo) continua por fazer.
- **Decisão**: portfólio log-ótimo de Lanchester (`k_ie = a_i √(dps·T_i)/custo_i`) com a doutrina do estilo como prior
  de peso D = 20 Marines vistos. Contínua: um Roach a mais move o mix um pouco, não troca o counter. Tech que falta
  desconta por `exp(−atraso/60 s)`; tipo com ≥ 5 % entra na composição e o `TechUp` do Ares compra a tech.
- **Estilo**: ganhou `adds` (o que o mix pode acrescentar). O mech não usa Marine nem fora do SURVIVE: contra Muta
  vai de Thor e Cyclone.

Primeiros jogos (`bench/comp-eficacia` contra `bench/comp-base` no `fd732fe`, Torches, CheatInsane, seed 1;
interrompidos): Zerg Rush e Macro, bio e mech, 4 vitórias contra 2 vitórias, 1 derrota e 1 timeout. Uma seed por
célula não separa a composição das outras divergências. Dois achados nos logs, corrigidos depois do `e647f7d`:
(1) o SURVIVE treinava qualquer unidade e pôs 6 Liberators (precificados pela arma sieged, que o Body nunca usa)
num exército bio — agora só `survival_types`; (2) a evidência era o visto *vivo*, então cada luta ganha devolvia
o mix à doutrina (jogo 000: visto 65 → 9 entre 780 e 900 s, doutrina 0,24 → 0,70) — agora é o produzido.

Ressalva medida antes do bench (cenários sintéticos): pela lei quadrada por custo o Marine é das unidades mais
eficientes do jogo — bio contra 200 de Zergling vai a 93 % de Marine. O modelo não vê alcance (melee que não
encosta, kite), upgrades, feitiços nem cura. Se o bench mostrar que isso pesa, o próximo termo é físico
(alcance/superfície de contato ou custo em supply perto do teto), não um bônus.

Como medir: bench 3 seeds × 3 raças × bio/mech contra a última execução medida; `planner.economy_planned`
(`enemy[].answers`, `doctrine`, `mix`, `composition_reason`) e `knowledge.combat_model.changed` (onde a tabela
divergiu do cliente).

## Próximos passos (decididos como direção, não implementados)

1. **DEFEND em cascata.** Hoje o DEFEND dispara com 3–4 Marines de pressão mesmo com 10–53 de cobertura na
   base (`bench/t0`: 42–45 % do tempo em DEFEND nas derrotas, 7 de 12 ataques cancelados no ASSEMBLE). A malha
   externa passa a ler o déficit da Defense — poder pedido menos concedido, o `GrantStatus` que nenhuma missão
   lê (C6 do [gaps.md](../gaps.md#c6)) — ou a ameaça líquida da cobertura (`balance`, C2). DEFEND passa a
   significar "a malha interna saturou".
2. **Lei de gasto contínua.** `alvo = μ̂(t+τ) + kσ̂(t+τ)`, `erro = alvo − (exército + exército na fila)` (o
   termo da fila é um preditor de Smith: sem ele um controlador de alvo dá overshoot pelo tempo de produção),
   `u_army = PI(erro)` saturado com anti-windup (supply 200, teto de produção). Substitui o liga/desliga de
   upgrades, add-ons e expansão por postura. O atuador é o Ares, que não aceita um `u` contínuo: a tradução
   passa por reserva de minerais ou ordem de prioridade.
3. **Observador mais rico.** Workers vistos como medição de renda (não só limite), cobertura pelo mapa e não só
   pelas bases, composição por tipo no estado (hoje a `CompositionPolicy` lê o visto por tipo e só o poder escalar
   do observador).
4. **Adaptativo entre partidas.** Estilo de exército como bandit por oponente (Thompson sampling), com os
   resultados guardados entre partidas no ladder.

## O que fica de fora da analogia

O inimigo se adapta (é mais teoria dos jogos que perturbação; o controle robusto é a ponte), luta é fortemente
não linear e discreta, e decisões combinatórias — onde lutar, que alvo — não são malha de controle. Controle
serve aos fluxos: economia, produção e estimação. A métrica de poder `sqrt(dps·hp)` somada já é a força de
combate da lei quadrática de Lanchester, então comparar somas está certo; a consequência é que a força cresce
com N², e reforço chegando aos poucos custa quadraticamente.
