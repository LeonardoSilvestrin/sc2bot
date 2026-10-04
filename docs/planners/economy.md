# Economy

> O que comprar: workers, bases, gás, estruturas de produção, upgrades, e qual exército?

## Resumo

- O planner junta três partes num único `EconomyPlan`, que os macro behaviors do Ares executam:

  | Parte | Pergunta | Arquivo |
  | --- | --- | --- |
  | **Investment** (policy) | Quanto investir: workers, bases, gás, teto de produção; quando assumir a abertura | `policies/investment.py` |
  | **Estilo** (knowledge) | Qual exército: BIO ou MECH, com abertura, doutrina, upgrades e add-ons | `knowledge/styles.py` |
  | **Composition** (policy) | O que treinar agora: o mix que melhor enfrenta o exército inimigo acreditado | `policies/composition.py` |

- A Economy **não pede unidades ao Engine**: o plano vai direto para o Body.
- Ela tem **dois regimes**:
  - **Abertura:** o build runner do Ares toca um script fixo, e o plano fica inativo (`active = false`);
  - **Macro:** depois da abertura, o plano manda.

## Entradas e saídas

| | |
| --- | --- |
| Lê | `attention` (workers, bases, minerais, upgrades, mapa, se a abertura acabou), `intent` (postura, `economy`, `emergency`), o estilo escolhido e, da `awareness`: o inimigo visto por tipo, o produzido por tipo, o observador, contatos e incidentes |
| Entrega | `EconomyPlan`: `active`, `workers`, `gas`, `bases`, `expand`, `freeflow`, `composition`, `upgrades`, `orbitals`, `mules`, `interrupt_opening`, `max_production`, `addons`, `addons_on`, `reactor_share` e o `composition_plan` (a explicação do mix) |

## 1. A abertura e quando o plano assume

A abertura é um build de [terran_builds.yml](../../terran_builds.yml), tocado pelo build runner do Ares
(`BioThreeOneOne` na bio, `MechHellionTank` no mech). Enquanto ela roda:

- o plano fica inativo (`reason = opening_runs`) e o Body não treina exército além do que o script lista;
- não há Orbital nem MULE pelo plano (o script faz o seu Orbital);
- o `SpawnController` registra `plan_inactive`.

O plano assume em três casos:

| Caso | Motivo | O que acontece |
| --- | --- | --- |
| O build runner terminou | `opening_done` | O plano passa a valer |
| A Strategy travou uma emergência (DEFEND com ameaça ≥ 0,6) antes do fim | `opening_interrupted` | O plano interrompe o script e gasta em exército primeiro |
| O banco chegou a 1.000 minerais com a abertura rodando | `opening_stalled` | O script travou (já aconteceu no 3º gás do mech); o plano interrompe |

## 2. Investment: quanto investir

| Item | Regra |
| --- | --- |
| **Bases** | `bases = max(1, townhalls no chão)` (inclui em construção) |
| **Saturação** | `saturated_at = min(80, 16 · bases)`: a força de trabalho que o próprio plano constrói, e não uma que ele nunca alcança |
| **Expandir** | Com `workers ≥ saturated_at`, `intent.economy ≥ 0,5`, postura DEVELOP ou PRESSURE e expansão livre no mapa |
| **Workers** | `min(80, 22 · bases desejadas)` (16 nos minerais e 6 no gás por base) |
| **Gás** | `min(2 · bases, int(workers · 0,4) // 3)`: os geysers das bases, até que 40 % dos workers estejam no gás, 3 por Refinery |
| **Teto de produção** | `4 · bases` estruturas de cada tipo (Barracks, Factory, Starport), ou `5 · bases` em PRESSURE e COMMIT. Dentro do teto, quantas construir é a regra de renda do Ares |

Por postura:

| Postura | Expande? | Upgrades e add-ons | Motivo no log |
| --- | --- | --- | --- |
| DEFEND | não | não; tudo vai para exército (`freeflow`) | `defend_spend_on_army` |
| RECOVER | não | sim | `recover_army_first` |
| COMMIT | não | sim; teto 5 por base | `commit_army_first` |
| DEVELOP | quando satura | sim | `mineral_lines_saturated`, `worker_cap_reached`, `no_expansion_left` ou `build_economy` |
| PRESSURE | quando satura | sim; teto 5 por base | os mesmos de DEVELOP |

## 3. O estilo de exército

O estilo é **dado, não código**. São dois:

| | BIO | MECH |
| --- | --- | --- |
| Abertura | `BioThreeOneOne` | `MechHellionTank` |
| Doutrina (proporção, prioridade) | Marine 0,55; Marauder 0,20; Siege Tank 0,15; Medivac 0,10 | Hellion 0,39; Cyclone 0,24; Siege Tank 0,37 |
| Pode acrescentar (`adds`) | Hellion, Cyclone, Thor, Viking | Thor, Viking |
| Add-ons em | Barracks | Factory |
| Upgrades, em ordem | Stim, Combat Shield, Infantry Weapons 1, Concussive, Infantry Armor 1, W2, A2, Vehicle Weapons 1, W3, A3, VW2, VW3 | Vehicle Weapons 1, Blue Flame, Vehicle Armor 1, W2, A2, W3, A3 |
| Contra | todas as raças | só Zerg |

**Escolha:** no `on_start`, sorteada entre os estilos feitos para a raça inimiga, com `--army` para fixar.
A seed é o hash do id do oponente: no ladder a escolha é fixa por adversário. Localmente, sem
`opponent_id`, é sempre a mesma. O bot anuncia o estilo no chat ("Going BIO today: …").

## 4. Composition: o que treinar agora

O mix é o **portfólio de recursos** que melhor enfrenta o exército inimigo acreditado, com a doutrina do estilo
como prior.

**A crença sobre o inimigo, por tipo.** Para cada tipo inimigo `e`:

- `S_e`: o poder visto vivo, que é o que está lá agora;
- `H_e`: o poder visto ser produzido, vivo ou morto, que é do que o inimigo é feito. Um Lurker morto ainda
  diz que existe Lurker Den.

O observador acredita em mais exército do que foi visto. A parte não vista é distribuída pela média do que
o inimigo produz (mais um prior da raça):

```text
w_e = (S_e + (U + P) · m_e) / (S + U + P)
m_e = (H_e + P · r_e) / (H + P)        U = max(S, μ + 0,5σ) − S        P = 10 Marines
```

**O valor de uma unidade nossa.** Por recurso gasto, o tipo `i` vale contra `e`:

```text
k_ie = a_i · sqrt(dps(i, e) · T_i) / custo_i
T_i  = hp_i / Σ_e (w_e / power_e) · dps(e, i)        (quanto i dura sob o fogo do exército acreditado)
a_i  = exp(−atraso da tech / 60 s)                   (desconto de quem ainda precisa de tech)
```

`dps(i, e)` vem do **modelo de combate** ([combat.py](../../bot/ego/planners/economy/knowledge/combat.py) e
`combat.yml`):

- a tabela tem vida, escudo, armadura, atributos e armas (dano, ataques, cooldown, bônus por atributo,
  splash) de cada tipo, no modo em que ele luta (Siege Tank em siege, Lurker enterrado);
- `dps(a, b)` é a melhor arma de `a` que alcança a camada de `b`: dano mais bônus, menos armadura (mínimo
  0,5; a armadura só pesa sobre a parte da vida que não é escudo). Um tiro nunca vale mais que a vida de
  `b`, e o resultado é multiplicado pelo splash;
- `power(e) = sqrt(dps · vida)` em Marines, como o `unit_power` da Attention;
- no `on_start`, `with_client` troca armadura, atributos e armas pelos dados do cliente em execução e
  reescala os cooldowns para que o Marine do cliente atire como o da tabela. Baneling, Widow Mine, Carrier,
  Battlecruiser e Oracle ficam com a tabela, e a vida sempre vem dela. O que mudou vai para
  `knowledge.combat_model`;
- o YAML também tem o prior de composição de cada raça (o `r_e` da crença, acima), usado antes de ver
  qualquer unidade.

**O mix.** Os recursos `x` maximizam:

```text
J(x) = H · Σ_e w_e log(Σ_i x_i k_ie)  +  D · Σ_i b_i log x_i
       └─ portfólio log-ótimo contra o inimigo ─┘   └─ doutrina b, com peso D = 20 Marines ─┘
```

- Sem nada visto, o mix é exatamente a doutrina (`style_baseline`).
- Quanto mais produção inimiga é vista (`H` cresce), mais o inimigo decide (`efficacy`).
- No ótimo, cada tipo inimigo recebe a fração `w_e` dos recursos, gasta nas unidades que o respondem.
- `J` é côncava. O ótimo sai de um ponto fixo em cerca de 1 ms.
- O Medivac, sem arma, fica com a fração da doutrina.

**Corte.** O mix vira proporções de **contagem** para o Ares. Um tipo com menos de 5 % (`min_share`) fica
de fora, porque o Ares não construiria produção para ele e compraria a tech por um token.

**SURVIVE.** Na emergência, os tipos com que o Body sabe lutar (Marine, Marauder, Hellion, Siege Tank,
Cyclone, Thor, Viking) que podem ser treinados agora e acertam os atacantes do incidente mais forte vão para
a frente. Eles são ordenados pela fração da resposta àquele incidente. O Liberator ficou de fora porque o
modelo o precifica pela arma em siege, que o Body nunca usa.

## 5. Como o Body executa o plano

O behavior de economia ([economy.py](../../bot/body/behaviors/economy.py)) roda o `MacroPlan` do Ares
nesta ordem. A ordem importa porque o `MacroPlan` para no primeiro behavior que age:

1. Se o plano pede, encerra o build runner (`interrupt_opening`).
2. **Add-on, um por frame, antes do `MacroPlan`.** Uma estrutura `addons_on` pronta, ociosa e sem add-on
   recebe Reactor enquanto `reactors + 1 ≤ reactor_share · n`, e Tech Lab depois disso.
   `reactor_share = s_r / (s_r + 2·s_t)`, onde `s_r` é a parcela do mix treinada nessa estrutura sem Tech
   Lab e `s_t` a que precisa de Tech Lab (um Reactor treina dois de cada vez). Dentro do `MacroPlan`, depois
   do `SpawnController`, os add-ons quase nunca rodavam.
3. **Orbital** (`UpgradeCCs`) antes de `BuildWorkers`.
4. **Pesquisa:** `ExactResearch` (conserta o plating de veículo e nave, cuja habilidade no `game_data`
   difere da tabela) e o `UpgradeController`, antes do `SpawnController`.
5. **`SpawnController`:** treina o tipo abaixo da sua proporção, contando o que está em produção. Se todos
   os tipos estão exatamente na proporção, ele não treinaria nada; nesse frame roda em `freeflow`
   (`composition_met`).
6. **`ProductionController`:** acrescenta estruturas de produção pela renda e pelo banco, até o teto do
   plano.
7. **MULEs:** todo Orbital com ≥ 50 de energia solta um MULE no campo mais cheio, sem gastar a reserva de
   scan do Intel nem usar o Orbital que acabou de escanear.

## Estado entre frames

- `CompositionPolicy`: o estilo e o modelo de combate (fixos na partida).
- O resto é recalculado por frame. A memória do inimigo por tipo é da Awareness.

## Parâmetros

| Parâmetro | Valor | Efeito |
| --- | --- | --- |
| `opening_stall_bank` | 1.000 | Banco que interrompe uma abertura travada |
| `max_workers` | 80 | Teto de workers |
| `workers_per_base` / `mineral_workers_per_base` | 22 / 16 | Workers por base / saturação dos minerais |
| `gas_worker_share` | 0,4 | Fração máxima dos workers no gás |
| `production_per_base` / `offensive_production_per_base` | 4 / 5 | Teto de estruturas de produção por base |
| `doctrine_power` | 20 Marines | Peso da doutrina no mix |
| `prior_power` | 10 Marines | Peso do prior da raça sobre o que o inimigo produz |
| `sigma_margin` | 0,5 | σ do observador no exército acreditado |
| `tech_horizon` | 60 s | Desconto da tech que falta |
| `min_share` | 0,05 | Fração mínima para um tipo entrar na composição |

## No log

- `planner.economy_planned`:
  - `reason`, `active`, `workers`, `gas`, `bases`, `expand`, `max_production`;
  - `composition[]` e `composition_reason` (`style_baseline`, `efficacy`, `survival_fallback`);
  - `enemy[]` (cada tipo inimigo com `seen`, `produced`, `share` e quem o responde), `doctrine`, `mix[]`,
    `survival`, `upgrades[]`, `interrupt_opening`.
- `behavior.spawn_executed`: `freeflow`, `reason` (`plan_inactive`, `plan_freeflow`, `composition_met`,
  `composition_short`) e a contagem por tipo.
- `knowledge.combat_model`: no `on_start`, o que os dados do cliente mudaram na tabela.
- `attention.observed`: minerais, gás, workers e exército a cada 5 s.

## Limitações conhecidas

- **Na abertura não sai exército além do script.** Contra o PhantomBot (`logs/game-20261004T032327451475Z`),
  o bot tinha 0 a 4 unidades de exército até 5:20, com 3 bases, e passou o resto do jogo em DEFEND perdendo
  workers. A abertura só termina por fim do script, emergência ou banco travado. O diagnóstico de all-in da
  Awareness (3:08) não interrompe nada.
- **O gás é uma fração fixa (0,4)**, independente do mix. Na mesma partida, com 64 a 87 % de Marines, ficaram
  1.100 de gás parados enquanto os minerais estavam entre 15 e 75.
- **A composição reproduz a doutrina:** em 2.690 frames medidos, nenhum tipo fora do estilo entrou e a
  distância à doutrina ficou entre 0,02 e 0,05 ([debate](../dev/agent_discussion/README.md)). Com Lurker, Roach e
  Hydra, o Marine subiu de 0,56 para 0,73. A composição não conhece upgrades, alcance, feitiços nem cura, e
  conta custo em recursos, não em supply nem em capacidade de produção.
- **Casters e Battlecruisers valem poder 0** no modelo que a Awareness usa, então não pesam no mix. Um Siege
  Tank nosso dominado por Neural Parasite foi contado como produção Zerg.
- **O sorteio do estilo nunca foi medido:** no ladder ele trava cada adversário num estilo sem dado.
- **Expansão sem fim:** a partir de 5 bases o bot está sempre "saturado" e termina jogos com 8 a 10 bases e 13
  a 16 mil minerais no banco.
- **Base em construção conta como base** (I4 no [gaps.md](../dev/gaps.md)): `saturated_at` e o teto de produção
  sobem no frame em que o SCV põe o CC.
- **O resto do `MacroPlan` do Ares passa na frente do exército:** como ele para no primeiro behavior que age,
  supply, workers, gás e expansão ainda vêm antes do `SpawnController`.
- Ainda faltam: a causa do banco com supply livre; reação específica a rush (bunker, worker pull, reparo);
  reposição de produção destruída; bases por `ready + pending` explícito, CC voando, cooldown do alvo e bases
  esgotadas (uma base sem minerais continua contando); supply antecipado além do `AutoSupply` do Ares; uma
  abertura e uma doutrina por matchup.

## Código

- [bot/ego/planners/economy/planner.py](../../bot/ego/planners/economy/planner.py): `plan`, que junta tudo.
- [bot/ego/planners/economy/policies/investment.py](../../bot/ego/planners/economy/policies/investment.py):
  `InvestmentConfig`, `plan`.
- [bot/ego/planners/economy/policies/composition.py](../../bot/ego/planners/economy/policies/composition.py):
  `CompositionPolicy`, `CompositionConfig`, `reactor_share`.
- [bot/ego/planners/economy/knowledge/styles.py](../../bot/ego/planners/economy/knowledge/styles.py):
  `ArmyStyle`, `BIO`, `MECH`, `choose`, `announcement`.
- [bot/ego/planners/economy/knowledge/combat.py](../../bot/ego/planners/economy/knowledge/combat.py) e
  `combat.yml`: o modelo de combate.
- Execução no Body: [economy.py](../../bot/body/behaviors/economy.py).
