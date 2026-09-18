# Modelos do branch `matematização`

O branch `matematização` é material de pesquisa: tem modelos matemáticos já
escritos e testados lá, dentro de uma arquitetura que não é a daqui (assessor →
model → planner → executor por behavior, `MissionPolicy`, `MissionBoard`,
`MacroPosture`). Este documento lista o que dele já veio para cá, o que ainda
pode vir e onde está cada coisa, para trazer **a fórmula, não a camada**.

Caminhos abaixo são do branch: `git show matematização:<caminho>`.

## Já trazido

| Modelo | Lá | Aqui |
| --- | --- | --- |
| Kernel gaussiano e saturação `S(x) = 1 − exp(−x)` | `bot/world/awareness/spatial/kernel.py` | [bot/awareness/field.py](../bot/awareness/field.py) |
| Memória de contato com confiança `exp(−idade/τ)`, esquecimento por morte confirmada e posição vista vazia | `bot/world/awareness/enemy/memory.py`, `knowledge.py` | [bot/awareness/model.py](../bot/awareness/model.py) |
| Identidade de grupo pelo pareamento de tags compartilhadas, desempate por id | `bot/world/awareness/enemy/forces/tracking.py` | `ThreatIncident` em [bot/awareness/model.py](../bot/awareness/model.py) |
| Objetivo por scores com margem, permanência mínima e desempate conservador | `bot/strategy/scoring.py`, `hysteresis.py` | [bot/ego/strategy.py](../bot/ego/strategy.py) (dois objetivos em vez de cinco) |
| Posse exclusiva, ordem total, preferência pelo dono anterior | `bot/engine/missions/allocator.py` | [bot/body/engine.py](../bot/body/engine.py) (sem preempção) |
| JSONL estrito, `ChangeGate`, identidade da execução | `bot/app/telemetry/`, `bot/app/run_identity.py` | [bot/logs/](../bot/logs/) |

O que foi deliberadamente simplificado ao trazer: a estimativa do inimigo
aqui é `max(conhecido, visto vivo, esperado)` com incerteza aditiva, não a
distribuição abaixo; o Engine não tem preempção; a Strategy tem
`STABILIZE`/`BUILD_ADVANTAGE`, não `RECOVER`, `TAKE_MAP_CONTROL` e `PRESSURE`.

## Candidatos

Ordenados pelo problema medido que cada um ataca. Nenhum deve entrar sem uma
partida que mostre o problema e outra que meça a mudança.

### Demanda de exército e capacidade de produção

**Ataca:** o banco de 4–21 mil minerais com supply livre, a causa em aberto
mais antiga do bot (ver "Medições" em [architecture.md](architecture.md)).

- `bot/macro/production/army_demand.py`: a meta de army supply é a âncora; a
  composição só diz *em que* pagar a dívida, nunca *se* ela existe.
  `ciclos = supply_desejado / Σ(peso · supply)`,
  `desejado_tipo = max(mínimo, ceil(peso · ciclos))`. Separa `missing` de
  `buildable_shortfall` (a dívida que a tech atual permite pagar).
- `bot/macro/construction/capacity.py`: produção nova só com unidade devida
  àquele produtor **e** utilização sustentada do que já existe
  (`utilization_20s ≥ minimum_utilization`). Cada decisão sai com razão
  (`existing_capacity_underutilized`, `sustained_income_exceeds_saturated_capacity`,
  `owed_units_need_an_add_on_not_a_building`, …).
- `bot/adapters/ares/world_observer.py` (`_producer_utilization`): utilização
  por tipo como média ponderada pelo tempo de jogo, não por frame:
  `u ← u + (ocupadas/prontas − u) · min(1, Δt / janela)`.
- `bot/macro/strategy/config.py` (`production_bonus`): produção extra pelo
  tamanho do banco. Lá é em degraus (`1 + (banco − limiar) // passo`); ao trazer,
  tornar contínuo.

Aqui o `ProductionController` do Ares decide pela renda, com o teto
`4 · bases`. O que falta é exatamente o diagnóstico: o bot não sabe se o banco
vem de produção ociosa, produção insuficiente ou dívida que a tech não paga.
A utilização por produtor sozinha já responderia isso no log.

### Estimativa do inimigo como distribuição

**Ataca:** a decisão de atacar lê `estimado + 0,5 · incerteza` — um número sem
probabilidade, e o crescimento esperado (`0,1 Marine/s` a partir de 120 s)
nunca foi calibrado.

- `bot/world/awareness/belief/estimate.py`: o inimigo é
  `max(leitura, prior + escala · informação · gap)`, com o gap relativo ao
  prior (o prior é "do nosso tamanho"), então a crença acompanha o crescimento
  dos dois lados. `informação` decai com τ e só é substituída por leitura pelo
  menos tão informativa: olhar várias vezes o mesmo canto não soma. O que está
  acima do conhecido é uma normal truncada em zero cuja média é a acreditada.
  `advantage(own, estimate) = P(nosso > deles)`, integrada por quantis do resto
  não visto.
- `bot/world/awareness/belief/relative.py`: `P(vantagem)` vira
  `AHEAD`/`EVEN`/`BEHIND` com limiares de entrada/saída (0,75/0,60 e
  0,25/0,40), persistência de 12 s, e `BEHIND ≤ 0,10` age na hora. Sem visão
  nenhuma, a leitura fica perto de 0,5.
- `bot/world/awareness/belief/losses.py`: trocas recentes (supply e workers
  perdidos por lado) com decaimento `τ = 120 s` corrigem o prior: um jogo par
  em que perdemos 20 de supply a mais já não é par.
- `bot/world/awareness/belief/economy.py`: workers inimigos pelo piso visto e
  pelas bases confirmadas (`bases · workers_por_base`, frescor pela última
  checagem).

Trazer `losses.py` primeiro: é pequeno e corrige o prior da estimativa atual
sem trocar o modelo.

### Cobertura de scouting

**Ataca:** o scouting acaba aos 240 s; depois disso a incerteza só cresce.

- `bot/world/awareness/enemy/bases/memory.py`: cada expansão candidata é
  `CONFIRMED`/`EMPTY`/`UNKNOWN` com a última checagem.
  `enemy_territory_coverage = Σ confiança das confirmadas / (confirmadas + 2)` —
  os dois lugares nunca vistos são "uma base ainda não achada" e "o exército
  fora de casa", então sem base confirmada a cobertura é zero, nunca "o inimigo
  tem pouco".
- `bot/behavior/scouting/model.py` (`IntelConfig`): scout recorrente
  (`repeat_scouts_after = 240 s`, informação velha depois de 90 s), Reaper antes
  de SCV, com oportunidade, risco e urgência separados.

### Território e frente

**Ataca:** a topologia (1.008 linhas em
[topology.py](../bot/attention/topology.py)) e o campo não decidem nada hoje.

- `bot/world/awareness/territory/influence.py`: por ponto, influência
  militar e de estruturas de cada lado somadas cruas e saturadas uma vez;
  `dominância = (F − E) / (F + E + ε)`; confiança da leitura
  `max(observação, conhecido / (evidência + presença_não_detectada))` — espaço
  vazio não observado lê 0, não "nosso".
- `bot/world/awareness/territory/frontline.py`: a frente é onde a dominância
  troca de sinal entre vizinhos do lattice, interpolada linearmente na aresta.
  Pontos sem dono não entram: a borda do nosso território contra mapa vazio é
  fronteira, não frente.
- `bot/strategy/spatial/policy.py`: objetivos de controle derivados do
  território — cada base segurada, as passagens para ela (importância herdada
  da base), e as regiões a uma passagem de distância (por controle ou por
  informação).

É o caminho para o `RegionState` da P1.2 em [propostas.md](propostas.md).

### Utilidade de missões

**Ataca:** quando houver mais de uma missão militar disputando unidades
(harass, map control, scout recorrente). Hoje só Defense e Offense disputam.

- `bot/strategy/mission_policy.py` (`evaluate_mission`):

  ```text
  desejabilidade = piso + (1 − piso) · intent[atividade]
  valor    = parcela · desejabilidade · (w_o · oportunidade
             + w_i · ganho_de_informação · intent.informação
             + w_c · alinhamento · importância · lacuna)
  urgência = w_u · urgência
  risco    = w_r · risco · (inevitável + (1 − inevitável) · (1 − tolerância_a_risco))
  piso_emergência = u_e · clamp((urgência − u_min) / (1 − u_min))
  utilidade = clamp(max(valor + urgência − risco, piso_emergência), 0, 1)
  ```

  O piso de emergência vale antes da viabilidade, então uma emergência real
  continua viável mesmo com utilidade crua negativa.
- `bot/engine/missions/allocator.py`: preempção com margem (10 pontos de
  prioridade) mais um custo de preempção de quem está no meio de uma ação.

### Harass e defesa posicional

- `bot/behavior/harass/reaper/model.py`, `harass/banshee/model.py`: alvo por
  `oportunidade_econômica − defesa − exército − incerteza`, com defesa tolerada
  (um Reaper que espera mineral line vazia nunca ataca) e tetos de risco para
  lançar.
- `bot/behavior/defense/model.py`: `DefenseAnchors`, `choose_approach` e
  `SiegePhase` — posição de defesa pela passagem de entrada em vez do centro
  do inimigo, e o ciclo de siege da defesa.
- `bot/behavior/map_control/model.py`: patrulha por amostras do campo, com os
  tipos de unidade que servem para isso.

## O que não trazer

A arquitetura do branch: `WorldFacts` → `AttentionSnapshot` → `StrategyInputs`
→ `StrategicIntent` → `StrategicContext` repetem a mesma decisão em
vocabulários diferentes, e o template assessor/model/planner/executor gera
quatro arquivos por behavior antes de haver estado que os justifique.
`MacroPosture` é uma segunda autoridade estratégica ao lado da Strategy. Aqui
cada modelo entra como função pura na camada que já é dona do dado.
