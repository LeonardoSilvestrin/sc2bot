# Melhorias propostas: economia e composição

> Registro de design/revisão histórico. Composição por catálogo, SURVIVE e fronteiras de Planner,
> Mission e Behavior já estão implementadas; o estado atual e os nomes de eventos são definidos em
> [architecture.md](architecture.md).


> Revisão feita em 18 de setembro de 2026 sobre `7e5be42` (`botbandido`), com a reorganização
> dos planners militares (MapControl) ainda na árvore de trabalho. Foram lidos o pacote
> [economy](../bot/ego/planners/economy/), os planners militares e de controle, a Strategy, o
> `play_frame`, o behavior de economia do Body, os testes de economia e três peças do Ares:
> `SpawnController`, `ProductionController` e `get_build_structures`. Também foi lido o JSONL
> `logs/game-20260918T214112316288Z` (local, fora do git): bio contra a IA Terran em Ley Lines,
> commit `6eddd4b`, derrota aos 812 s. É o único jogo completo no disco, e a economia dele é a do
> HEAD, porque os commits seguintes só moveram arquivos. Nenhuma partida foi jogada para escrever
> isto.
>
> Complementa [novas_propostas.md](novas_propostas.md) (N2, N3, N5) e [propostas.md](propostas.md)
> (P0.4, P0.5). Os ids são `E1`…`E9`.

> **Estado em 19 de setembro de 2026 (`5f12156`).** Nenhum item implementado. O próximo refactor junta E1, E2,
> E3 e o E6 com a proposta STYLE / COUNTER ADAPTATION / SURVIVAL: catálogo ordenado de counters por raça no lugar
> de `COUNTERS`, baseline + adaptação no lugar de `prior × value`, e um modo de sobrevivência decidido pela
> Strategy. O E7 passa a ser um jeito de ordenar ou validar esse catálogo. O desenho, as decisões em aberto e as
> fatias estão em [staging/economia-e-builds.md](staging/economia-e-builds.md).

## Resumo

- **A economia é o único grupo de planners fora do padrão.** Ela é feita de funções soltas, e não
  de classes com estado e config. O estilo é escolhido em `main.py`, e as constantes ficam fora do
  fingerprint. A Strategy é lida por dentro, em vez de por uma política. Um `EconomyPlan` de 18
  campos responde a cinco perguntas e tem um `reason` só. O E1 põe a economia no padrão sem mudar
  o gameplay.
- **O que incomoda na composição:** a decisão tem três ingredientes, e só um deles é física, o
  `REACH`.
  - O prior do estilo multiplica o mix para sempre.
  - A matriz é digitada à mão e não casa com os tipos que a Awareness registra.
  - A conta é feita em cabeças, e custo, gás e supply não entram.
  - A prioridade fixa do estilo pode travar o `SpawnController` do Ares. Quando falta gás para o
    tanque, o Marine, que não usa gás, também deixa de ser treinado. O mecanismo está no código do
    Ares, e o E2 mede se é ele a causa do banco.
- **Caminho proposto:**
  - primeiro, medir essa trava (E2) e consertar as chaves da matriz (E3);
  - depois, prioridade calculada (E4), mix que lê o banco e o supply (E5), resposta por ameaça com
    o estilo como prior de verdade (E6) e matriz derivada dos dados (E7);
  - por fim, upgrades e add-ons pelo mix (E8) e a ordem do gasto decidida no Ego (E9).

## 1. Onde a economia foge do padrão

O padrão é o que os planners militares e de controle têm em comum depois da reorganização.

| Aspecto | Militares e controle | Economia hoje |
| --- | --- | --- |
| Forma | Uma classe por planner, guardada em `Layers`, com `plan()` | Funções de módulo: `economy.plan`, `investment.plan` e `composition.mix` ([planner.py:22](../bot/ego/planners/economy/planner.py#L22)) |
| Entrada | `attention`, `awareness` e `strategy` inteiros, mais o feedback | `plan(attention, strategy, army, awareness.seen_enemy_types)`: um pedaço da Awareness e o estilo passado por fora ([main.py:118](../bot/main.py#L118)) |
| Estado | Dentro do planner (passagem mantida, cooldown, rota) | O estilo mora em `Layers.army`. Ele é escolhido, trocado no runner e anunciado em `MyBot.on_start` ([main.py:196-201](../bot/main.py#L196-L201)) |
| Config | `OffenseConfig`, `MapControlConfig`, `DetectionConfig` e `StructureConfig`: frozen, validadas, em `Layers.configs()` e no fingerprint. Defense e Intel ainda usam constantes de módulo | Só constantes de módulo, fora do fingerprint: `MAX_WORKERS`, `GAS_WORKER_SHARE`, `PRODUCTION_PER_BASE`, `OPENING_STALL_BANK`, `PRIOR_POWER` e `COUNTERS`. O architecture.md avisa que dois benches com o mesmo fingerprint podem ter economias diferentes |
| Strategy | Onde a Strategy restringe um domínio, ela publica uma política: `strategy.offense` (`PURSUE`/`WITHDRAW`, com razão). O planner decide o que fazer com ela | Lê `strategy.objective is STABILIZE` e refaz a emergência com `OPENING_ABORT_DANGER = 0.6`, uma cópia de `StrategyConfig.emergency_danger` ([investment.py:105-106](../bot/ego/planners/economy/investment.py#L105-L106)) |
| Preferência contínua | Defense: `priority = threat·(0,5 + 0,5·defense)` | Usa `strategy.economy ≥ 0,5` como portão da expansão ([investment.py:99](../bot/ego/planners/economy/investment.py#L99)) e nunca lê `strategy.army` (A4 de novas_propostas) |
| Plano | Um por planner, com `reason` e `inputs` que explicam a decisão | Um `EconomyPlan` de 18 campos para cinco perguntas: investimento, abertura, modo de gasto, composição e add-ons/upgrades. O único `reason` é o do investimento. Da composição, só `enemy_seen_power` é registrado, então ela não diz por que mudou |
| Um módulo por pergunta | `planner.py` decide e `missions/` executa | `planner.py` só junta as partes. `Investment` repete 10 campos de `EconomyPlan`, copiados um a um (`stabilizing` vira `freeflow`) |
| Prioridade | Explícita na proposta; o Engine arbitra | Implícita na ordem de registro no Body: o `MacroPlan` ([economy.py:188-217](../bot/body/behaviors/economy.py#L188-L217)), com a detecção e os add-ons registrados antes dele. O Ares para no primeiro que age |
| Documentação | Catálogo de eventos em dia | O catálogo de `planner.economy_planned` lista `reactors`, `reactor_on` e `techlab_reserve`, que não existem mais (o código tem `addons`, `addons_on` e `reactor_share`). A descrição do Body ainda fala em `AddReactors` e "reserva de Tech Lab" |

No log, o investimento mostra mais dois problemas:

- `expand` inverteu 19 vezes depois do opening (de 290 a 812 s), 8 delas entre 685 e 717 s. A
  comparação `workers ≥ saturated_at` é dura, e o número de workers oscilava em torno do teto de 80.
  Abaixo do teto, a meta de workers oscila junto, porque é `min(80, 22·(bases + expand))`.
- Perto de 200/200 (194–198, de 586 a 636 s), o bot tinha 83 workers e 99–115 de supply de
  exército. No fim do jogo o recurso que falta é o supply, e `MAX_WORKERS` não leva isso em conta.

## 2. O que incomoda na decisão de composição

Hoje, para cada unidade `u` do estilo:

```text
value(u) = (Σ_e poder(e)·alcance(u,e)·COUNTERS[u][e] + PRIOR_POWER) / (Σ_e poder(e) + PRIOR_POWER)
share(u) = prior(u)·value(u) / Σ_v prior(v)·value(v)        → proporção de CABEÇAS para o Ares
```

Dos três ingredientes, só `alcance` é física. `prior` e `COUNTERS` são números de mão, e cada um
tem um defeito próprio.

### 2.1 A unidade de medida é a cabeça

O `SpawnController` e o `ProductionController` do Ares medem proporção como contagem do tipo
dividida pela contagem total
([spawn_controller.py:184-185](../ares-sc2/src/ares/behaviors/macro/spawn_controller.py#L184-L185)).
Nenhum dos dois olha custo, gás ou supply. Convertidos pelos custos do `UNIT_DATA` do Ares, os
priors dos estilos ficam assim:

| Estilo | Unidade | Cabeças | Dinheiro (minerais + gás) | Supply |
| --- | --- | --- | --- | --- |
| bio | Marine | 55 % | 24,2 % | 34,4 % |
| bio | Marauder | 20 % | 22,0 % | 25,0 % |
| bio | Siege Tank | 15 % | **36,3 %** | 28,1 % |
| bio | Medivac | 10 % | 17,6 % | 12,5 % |
| mech | Hellion | 35 % | 18,8 % | 28,6 % |
| mech | Cyclone | 22 % | 29,6 % | 26,9 % |
| mech | Siege Tank | 33 % | **48,9 %** | 40,4 % |
| mech | Marine | 10 % | **2,7 %** | 4,1 % |

O maior item do orçamento bio é o tanque. Os "10 % de Marines" do mech são 2,7 % do dinheiro. A
matriz fala em "troca por custo", mas o resultado vira proporção de cabeças. O P0.4 já pedia
"dívida de composição por supply", e a Defense já dimensiona forças por poder
(`minimum_power`), não por contagem.

### 2.2 O estilo não é prior: multiplica para sempre

Como `share ∝ prior·value`, `value(u)` converge para a média dos counters quando o exército
visto cresce. O `prior(u)` continua multiplicando, e o estilo nunca sai da conta. Mech contra
Mutalisk, pelo `composition.mix` de hoje, em parcela de cabeças:

| Mutalisk visto (Marines) | Hellion | Cyclone | Siege Tank | Marine |
| --- | --- | --- | --- | --- |
| 40 | 17,7 % | 44,4 % | 16,7 % | 21,2 % |
| 200 | 5,9 % | 59,7 % | 5,6 % | 28,8 % |
| 2.000 | 0,7 % | 66,4 % | 0,7 % | 32,2 % |
| 2.000, só com `value` | 0,3 % | 48,1 % | 0,3 % | 51,3 % |

Mesmo com evidência infinita, a razão de 2:1 entre Cyclone e Marine vem do 0,22 contra 0,10 do
estilo. A matriz dá 1,5 contra 1,6. Na prática, o prior é um bônus de preferência fixo por tipo.

### 2.3 A matriz é digitada e não casa com o que a Awareness vê

`COUNTERS` é indexada pelo tipo base (`SIEGETANK`, `LURKERMP`, `LIBERATOR`, `VIKINGFIGHTER`). Já
a Awareness guarda o tipo no modo em que a unidade foi vista
([model.py:363](../bot/awareness/model.py#L363)): `SIEGETANKSIEGED`, `LIBERATORAG`,
`VIKINGASSAULT`, `LURKERMPBURROWED`, `ROACHBURROWED`, `BANELINGBURROWED`, `WIDOWMINEBURROWED` e
`THORAP`. Nenhum desses é chave da matriz, e todos caem no padrão 1,0
([composition.py:204](../bot/ego/planners/economy/composition.py#L204)). O modelo de poder da
Attention usa justamente os modos: `SPLASH_TARGETS` tem `SIEGETANKSIEGED`, `LURKERMPBURROWED` e
`LIBERATORAG`. O bot tem, portanto, dois modelos de combate com convenções de chave diferentes.

- **No log contra Terran,** os tipos mais frequentes em `strongest_contacts` foram
  `SIEGETANKSIEGED` (2.755 registros), `MARAUDER`, `LIBERATORAG`, `LIBERATOR`, `VIKINGASSAULT` e
  `VIKINGFIGHTER`. `SIEGETANK` sem siege teve 149. O mix se moveu pouco: Marine entre 0,52 e 0,63,
  Tank entre 0,11 e 0,17. Há dois motivos:
  - `enemy_seen_power` ficou abaixo de `PRIOR_POWER` em 80 % do tempo depois do opening, com
    máximo de 52;
  - nas linhas da bio, as únicas chaves que casaram foram `MARINE` e `SIEGETANK` sem siege. O resto
    caiu no 1,0. Fora essas duas chaves, o que moveu o mix foi o alcance: Liberators e Vikings no
    ar, onde Marauder e Tank não atiram.
- **Contra Zerg,** 30 de Lurker enterrado e 10 de Roach dão hoje Hellion 31 % e Tank 36 % das
  cabeças. Com a chave certa, dariam Hellion 20 % e Tank 48 %. O Lurker, que quase só é visto
  enterrado, nunca recebe o 0,3 do Hellion nem o 1,6 do Tank.

Além disso, os números da matriz (2,0 para Hellion contra Zergling, 0,6 para Cyclone contra
Zealot…) são opinião. Nenhum foi medido, e um par que falta vale 1,0, o mesmo que um par medido
como troca igual.

### 2.4 Valor médio, não cobertura

`value(u)` é a média, pesada pelo poder, de quão bem `u` troca contra o exército inimigo inteiro.
Ela não diz se cada parte desse exército tem resposta, e uma ameaça que poucas unidades nossas
alcançam pesa pouco no total. Contra 50 de Mutalisk e 50 de Roach, o mech de hoje põe **45 % do
dinheiro em Siege Tanks**, que não atiram na metade aérea, e 48 % em unidades que atiram para
cima.

O suporte tem o defeito ao contrário. O Medivac não atira e fica com `value = 1` fixo
([composition.py:200-201](../bot/ego/planners/economy/composition.py#L200-L201)). Por isso a
parcela dele **cresce quando o resto do exército é ruim**: 8,5 % das cabeças contra 100 de Roach e
13,3 % contra 100 de Ultralisk. Um Medivac vale o que ele cura, e isso é proporcional à bio que ele
acompanha.

### 2.5 A prioridade do estilo trava o SpawnController

O `SpawnController` percorre a composição em ordem de prioridade e testa **se pode pagar antes de
testar se a cota já foi cumprida**
([spawn_controller.py:168-194](../ares-sc2/src/ares/behaviors/macro/spawn_controller.py#L168-L194)).
Se a unidade da vez tem uma estrutura ociosa e não cabe no banco, o laço para. Nada de prioridade
menor é treinado naquele frame, mesmo que a cota da unidade que travou já esteja cumprida.

- **Na bio,** a ordem é Siege Tank (0), Marauder e Medivac (1), Marine (2). Uma Factory com Tech
  Lab ociosa sem 125 de gás, ou um Starport ocioso sem 100, **impede o Marine**, que não usa gás.
  E a estrutura fica ociosa justamente porque o gás não chega.
- **No mech,** Tank (0) e Cyclone (1) vêm na frente de Hellion e Marine (2).
- **O `ProductionController` não compensa.** Ele não acrescenta Barracks enquanto houver uma
  Barracks ociosa (`_can_already_produce`). O caminho dele que acrescenta produção pelo banco exige
  400 de minerais **e** 400 de gás (`add_production_at_bank`), e fica fechado justamente quando falta
  gás.

O log é compatível com essa trava. Entre 317 e 375 s havia 3 Barracks, 1 Starport com Reactor e
1–2 Factories, uma delas com Tech Lab, e o supply esteve livre o tempo todo. Nesse intervalo:

- o gás ficou entre 0 e 170;
- os minerais subiram de 765 para 1.685;
- o exército passou de 11 para 17 de supply.

Depois do opening, 25 de 153 amostras tinham gás < 100, minerais ≥ 300 e pelo menos 3 de supply
livre. Isso pode ser a causa do banco que o P0.4 deixa em aberto. O mecanismo está no código, mas
o log não prova que foi ele, porque não registra estrutura ociosa. O E2 mede.

### 2.6 Nada lê o banco

O investimento pega todo geyser até 40 % dos workers, sem saber quanto gás a composição consome. O
mix bio gasta 0,42 de gás por mineral, e o mech gasta 0,52.

No fim do jogo do log, o gás subiu de 1.134 para 4.329 entre 614 e 799 s, cerca de 1.000 por
minuto. Continuou subindo quando as lutas liberavam supply (158/200 aos 659 s, 178/200 aos 799 s),
com os minerais entre 30 e 865. O bot chegou a 24 Barracks, mas não passou de 2 Factories e 1
Starport. O `ProductionController` não acrescenta produção para um tipo cuja `contagem·1,2` já
passa do alvo
([production_controller.py:207](../ares-sc2/src/ares/behaviors/macro/production_controller.py#L207)).
Com 11–13 tanques em 68–69 unidades, a cota de 15 % estava cumprida, e nenhuma Factory veio.

No começo do jogo faltava gás (seção 2.5) e no fim sobrava, mas o mix foi o mesmo nos dois casos.

### 2.7 Em STABILIZE a composição sai inteira

Com a base ameaçada, o plano liga `freeflow`, e o Ares ignora as proporções: treina o que tiver
estrutura ociosa, na ordem de prioridade do estilo. É justamente quando mais importa se a ameaça é
aérea ou terrestre, e os incidentes da Awareness já separam `air_power` de `ground_power`.

### 2.8 A crença esquece, a infraestrutura fica

O mix segue `seen_enemy_types`, que esquece com τ = 180 s. Add-ons, Factories e upgrades são
permanentes. Quando o inimigo some de vista, o mix volta para o estilo sem que o inimigo tenha
mudado, e um `reactor_share` calculado desse mix muda com ele. Hoje isso não aparece porque a
matriz quase não mexe o mix. Vai aparecer quando mexer (E6).

## 3. Propostas

### E1 — Economia no padrão dos planners (refactor puro)

**Por quê:** a seção 1, e porque um planner com estado, config e `inputs` próprios é onde E4–E8
entram sem mais cola em `main.py`.

```text
bot/ego/planners/economy/
  __init__.py            o grupo: o que comprar; sem missões
  investment/
    planner.py           InvestmentPlanner(config) → InvestmentPlan
  composition/
    planner.py           CompositionPlanner(style, config) → CompositionPlan
    styles.py            ArmyStyle, BIO, MECH, choose, announcement (dados)
    mix.py               mix, reactor_share (a matemática de hoje)
    counters.py          REACH, COUNTERS (dados)
```

- **Planners.** `InvestmentPlanner` e `CompositionPlanner` ficam em `Layers`, com
  `plan(attention, awareness, strategy)`. O `CompositionPlanner` guarda o estilo. O `on_start`
  continua sorteando (`styles.choose`) e constrói o planner com o estilo sorteado. Fora isso, ele só
  faz o que toca o bot: `switch_opening` e o chat.
- **Configs.** `InvestmentConfig` e `CompositionConfig` são frozen, validadas e entram em
  `Layers.configs()`. Isso cobre a parte da economia no "fingerprint da economia e do poder" do
  P0.5. As constantes físicas continuam de módulo, como `SCAN_ENERGY`: `GAS_BUILDINGS_PER_BASE`,
  `WORKERS_PER_GAS_BUILDING` e `TECHLAB_OF`.
- **Política da Strategy.** A Strategy publica `investment: DomainPolicy` ao lado de `offense`:
  - `PURSUE`: investir (upgrades e add-ons);
  - `WITHDRAW`: tudo no exército;
  - razão `home_secure`, `home_threatened` ou `emergency_threat`.

  A abertura é interrompida em `emergency_threat`. O `OPENING_ABORT_DANGER` sai, porque o limiar é o
  `emergency_danger` que a Strategy já tem.
- **Contratos.** Dois contratos em `contracts.py`, que o Body recebe como já recebe `StructurePlan`
  e `DetectionPlan`. A cópia campo a campo deixa de existir.
  - `InvestmentPlan`: `active`, `interrupt_opening`, `workers`, `gas`, `bases`, `expand`,
    `max_production`, `orbitals`, `mules`, `reason` e `inputs`.
  - `CompositionPlan`: `units`, `freeflow`, `upgrades`, `addons`, `addons_on`, `reactor_share`,
    `style`, `reason` e `inputs`. É o contrato que o N2.1 já desenhava.
- **Explicação.** A composição explica a mudança. `inputs` traz o `value` de cada tipo, o poder
  visto e o poder desconhecido. `reason` vale `style_prior` quando nada foi visto e
  `reweighted_by_seen_army` quando algo foi. O evento `planner.economy_planned` mantém nome e
  campos, por causa do viewer.
- **Documentação.** Corrigir no architecture.md o catálogo de `planner.economy_planned` e a
  descrição do Body.

**Critério:** a suíte passa. Salvo falha do cliente, os benches repetem as partidas de cada seed do
commit de base, porque as decisões são as mesmas. O fingerprint muda uma vez, quando `investment`
e `composition` entram nele.

### E2 — Medir a trava antes de mexer nela

**Por quê:** a seção 2.5 é uma hipótese forte, mas ainda é hipótese. Medir custa pouco e não muda o
gameplay.

- `SpawnMode` ganha dois campos:
  - `blocked_by`: o tipo em que o Ares pararia neste frame;
  - `short_of`: o recurso que faltou, `minerals`, `vespene` ou `supply`.

  Para isso, `spawn_mode` repete o laço do `SpawnController` com a mesma chamada
  `bot.get_build_structures` e o mesmo `can_afford`. É o que ele já faz com o teste de proporção
  ([economy.py:247](../bot/body/behaviors/economy.py#L247)).
- `behavior.spawn_executed` registra os dois campos. Um extrator do JSONL calcula a fração do tempo
  pós-opening com `blocked_by` e supply livre, e os minerais parados nesse tempo. O N1 já pedia
  métricas intermediárias no `summary.json`.

**Medir:** as matrizes `ci-bio` e `ci-mech` e uma célula Terran, no HEAD. Se a trava explicar o
banco de 300–700 s, o E4 é o próximo passo. Se não explicar, a causa do banco continua em aberto, e
o E4 perde a vez.

### E3 — Chave da matriz pelo tipo da unidade, alcance pelo modo

- A consulta passa pelo `UNIT_UNIT_ALIAS` do python-sc2: `COUNTERS[u].get(alias(e), 1.0)`. O alcance
  continua pelo tipo visto, porque um `VIKINGASSAULT` está no chão e um `LIBERATORAG` voa.
- Um teste garante que toda chave de `COUNTERS` é um tipo canônico e que um tanque em siege pesa
  como um tanque.

**Medir:** CheatInsane Zerg (Lurker e Roach enterrados) e uma célula Terran (tanque em siege,
Liberator AG). O efeito no placar deve ser pequeno. O mecanismo aparece nos `inputs` do E1.

### E4 — Prioridade calculada pelo planner

**Por quê:** a prioridade só existe para o Ares guardar dinheiro para quem vem primeiro. E guardar
só faz sentido no recurso que a unidade prioritária usa.

- O plano dá a ordem a cada frame. Primeiro vêm os tipos que não usam o recurso que falta, e depois
  os de maior déficit, isto é, alvo menos atual, medido em gasto (E5). É uma ordem, não um corte.
  O Body só traduz essa ordem para os inteiros de 0 a 10 do Ares, com a contagem do próprio Ares,
  que inclui o que está em produção.
- Com gás em falta, Marine e Hellion passam na frente e param na própria cota. Tanque, Medivac e
  Marauder vêm depois. Se o laço parar num deles, ele guarda gás para eles, e isso está certo.
- Em `freeflow` (STABILIZE), a ordem vem da ameaça em casa. Contra um incidente aéreo, primeiro vêm
  as unidades que atiram para cima.

**Medir:** `blocked_by` com supply livre (E2), o banco de minerais entre 300 e 700 s e o army
supply a 6, 8 e 10 min. **Depende de:** E2.

### E5 — O mix lê o banco e o supply (preço-sombra)

**Por quê:** as seções 2.1 e 2.6. O recurso que limita muda ao longo do jogo: gás no começo,
minerais depois, supply no fim. A composição precisa ser medida no recurso que falta agora.

```text
disponível_m = banco_m + renda_m·H                     minerais; H ≈ o tempo de treino
disponível_g = banco_g + renda_g·H                     gás
disponível_s = 200 − supply usado + s₀                 s₀ suaviza perto do teto
preço(u)     = minerais(u)/disponível_m + gás(u)/disponível_g + supply(u)/disponível_s
                                                       a fração do que vai haver que a unidade consome
cabeças(u)   ∝ gasto(u) / preço(u)                      só na fronteira com o Ares
```

- **O mix passa a ser calculado em gasto** (E6), e o preço converte gasto em cabeças.
  - Com gás parado, tanque, Medivac e Marauder ficam baratos. A cota deles sobe, e o
    `ProductionController` acrescenta Factories e Starports sozinho.
  - Com minerais parados, acontece o contrário.
  - Perto de 200, o que pesa é o supply.
- **O investimento lê o mesmo preço.**
  - O gás alvo segue o gás que o mix e os upgrades consomem, e não "todo geyser até 40 %". O Ares
    já oferece `Mining(workers_per_gas=…)` e `mediator.set_workers_per_gas`.
  - Perto do teto, a meta de workers também paga o supply, no lugar do `MAX_WORKERS` fixo.
- **Sem limiar.** O preço varia continuamente com o banco, a renda e o supply. `H` e `s₀` saem do
  log.

**Medir:** o banco de gás e o de minerais com supply livre (as janelas das seções 2.5 e 2.6), o army
supply e a troca de recursos. **Depende de:** E1. Rende mais depois do E6.

### E6 — Resposta por ameaça, com o estilo como prior de verdade

**Por quê:** as seções 2.2, 2.4 e 2.8. É a mudança de estrutura do modelo.

```text
Para cada tipo inimigo visto e (poder p_e) e cada candidato u que o alcança:
  resposta(u|e) = eff(u,e)² / Σ_v eff(v,e)²          quem troca melhor contra e responde mais por e
  gasto(u)     += p_e · resposta(u|e) / eff(u,e)     quanto de u iguala a troca contra essa parte
Para a parte do exército inimigo que ninguém viu, U = max(0, estimado − visto):
  gasto(u)     += U · prior_gasto(u)                 o estilo responde ao desconhecido
prior_gasto é o prior do estilo em dinheiro (a tabela da seção 2.1).
```

**E6.1, dentro dos candidatos do estilo:**

- **Cobertura, não média.** Cada ameaça recebe resposta na medida do seu poder, e uma unidade que
  não alcança a ameaça não responde por ela.
- **O estilo só responde ao desconhecido.** O peso dele sai da própria Awareness
  (`estimado − visto`), e não da constante `PRIOR_POWER = 20`. Sem nada visto, o mix é o estilo.
  Com tudo visto, o mix é a matriz.
- **O suporte deixa de ter valor fixo.** O Medivac vira uma fração do gasto em bio, tirada do
  estilo, porque ele vale o que cura.
- **A estabilidade continua vindo da crença** (τ = 180 s), e não de histerese no mix. O que é
  compromisso, como os add-ons, fica no E8.

**E6.2, candidatos além do estilo:**

- Um catálogo (dados) das unidades de exército Terran, com prior 0. Uma unidade dele só entra
  respondendo a uma ameaça vista.
- O preço inclui a infraestrutura que ainda não existe, amortizada no número de unidades que o mix
  pede. Por exemplo, o Armory para o Thor, ou o Starport com Tech Lab para o Liberator.
- O dict do Ares só recebe um tipo cuja meta arredonda para pelo menos uma unidade, porque unidade
  é inteira. É uma restrição física, não um corte de preferência. Sem ela, qualquer parcela minúscula
  dispararia o `TechUp` do Ares.
- É a transição "só pela produção", sem doutrina de transição.

**Depois:**

- Distribuir `U` pelo tech inimigo visto (Spire, Stargate, Starport) em vez de pelo estilo.
- Usar o déficit que o Engine já mede, isto é, `Grant` `PARTIAL`/`REJECTED` por `must_attack`. É o
  sinal mais direto de falta de cobertura, e entra como segunda fonte.

Com a mesma `COUNTERS` de hoje (β = 2, desconhecido = 20 Marines), só a estrutura muda. Parcela do
**dinheiro** no mech:

| Visto | Modelo | Hellion | Cyclone | Siege Tank | Marine |
| --- | --- | --- | --- | --- | --- |
| nada | hoje e proposta | 18,8 % | 29,6 % | 48,9 % | 2,7 % |
| 200 Mutalisk | hoje | 3,2 % | 80,7 % | 8,3 % | 7,8 % |
| | proposta | 2,5 % | 45,9 % | 6,6 % | 45,0 % |
| 50 Muta + 50 Roach | hoje | 7,0 % | 43,9 % | 45,3 % | 3,7 % |
| | proposta | 8,1 % | 36,5 % | 26,7 % | 28,7 % |
| 60 Zergling | hoje | 31,3 % | 19,7 % | 46,4 % | 2,6 % |
| | proposta | 35,7 % | 18,3 % | 30,3 % | 15,7 % |

**Medir:** CheatInsane Zerg × Air e Power (exército aéreo e misto), mais uma célula Terran,
olhando a troca de recursos e o army supply. Os timeouts continuam limitados pela ofensiva (N7.1),
então o placar sozinho não separa as mudanças. E6.1 e E6.2 são fatias separadas. **Depende de:**
E1 e E3. Fica melhor com o E5.

### E7 — A matriz sai dos dados

**Por quê:** a seção 2.3. O modelo é o mesmo de Lanchester que o bot já usa para o poder, só que
por par de tipos.

```text
P(x→y)   = sqrt(dps(x→y) · alvos(x) · hp(x))      o poder de hoje, com o dps contra y
eff(u,e) = (P(u→e) / custo(u)) / (P(e→u) / custo(e))
```

- **Dados.** O `dps(x→y)` leva o bônus por atributo e a armadura das armas do `game_data`, lidas
  uma vez no `on_start`, como o `read_map` faz com o mapa. `alvos` é o `SPLASH_TARGETS` da
  Attention, o mesmo que entra no poder.
- **`COUNTERS` vira correção.** O padrão é 1, e ela só cobre o que os dados não enxergam: alcance,
  kite e feitiços (Fungal, Storm, Bile, Lock On). A calibração é feita contra replays (N5), e não
  partida a partida.
- **Unidade que não atinge a outra.** Se `e` não atinge `u` (Colossus contra Viking), o `eff`
  daria infinito. Num exército ninguém é intocável, então `P(e→u)` usa o dano do exército inimigo
  que atinge `u`, e não só o de `e`.
- **N5.2.** Isto fecha o N5.2 pelo lado da composição. Depois, a luta local pode usar a mesma
  tabela.

### E8 — Upgrades e add-ons seguem o mix

- **Upgrades.** O valor de um upgrade é proporcional à parcela do gasto nas unidades que ele
  melhora: infantaria, veículo ou nave. A ordem sai desse valor, e os níveis vão em sequência
  porque o jogo exige.
  - O mech contra ar, com Marines a 45 % do dinheiro, passa a pedir armas de infantaria.
  - A bio sem tanques para de pedir armas de veículo.

  É o N2.5 sem posição fixa na lista.
- **Add-ons.** `reactor_share` passa a valer para todo tipo de produção, e não só para `addons_on`:
  o Starport da bio também treina Medivac. A fórmula ganha o tempo de treino de cada unidade, porque
  hoje ela supõe tempos iguais.
- **Compromisso.** Um add-on é permanente, então a divisão entre Reactor e Tech Lab lê uma
  estimativa mais lenta do mix do resto do jogo. A troca de add-on entre tipos de estrutura usa o
  `AddonSwap` do Ares.

### E9 — A ordem do gasto decidida no Ego

**Por quê:** hoje, a ordem entre supply, Orbital, workers, gás, expansão, pesquisa, exército e
produção sai do registro no Body e da regra do Ares de parar no primeiro que age. A detecção
(Engineering Bay, turrets) e os add-ons passam na frente só por estarem fora do `MacroPlan`. Essa é
uma decisão de "o que vem primeiro", e hoje ela mora no Body.

- Os planos trazem a ordem e a razão, e o Body registra nessa ordem. Com isso, `strategy.army`
  passa a decidir onde o exército e a economia se cruzam (N3.2), por ranking de scores e sem portão.
  O `strategy.economy ≥ 0,5` deixa de existir.
- A compra da detecção entra na mesma ordem.
- A expansão por previsão (N3.1) substitui a comparação dura que inverteu 19 vezes no log. Um
  pedido de expansão mantido já foi medido e revertido (`bench/7jk`), então histerese não resolve.

## 4. Ordem sugerida

| Ordem | Item | Por quê agora | Custo |
| --- | --- | --- | --- |
| 1 | E1 | Refactor puro; abre o resto | Médio: move código e testes, sem gameplay |
| 2 | E2 | Mede a hipótese mais forte sobre o banco | Baixo |
| 3 | E3 | Conserta um bug de chave: uma linha e um teste | Baixo |
| 4 | E4 | Se o E2 confirmar a trava | Baixo |
| 5 | E5 | O banco dos dois lados (seções 2.5 e 2.6) | Médio |
| 6 | E6.1, depois E6.2 | A mudança de modelo | Médio |
| 7 | E7 | Troca os números de mão por dados | Médio: tabela no `on_start` |
| 8 | E8 | Só vale depois que o mix se move (E6) | Médio |
| 9 | E9 | Depois que os planos têm ordem própria | Médio |

E2 e E3 não dependem do E1 e podem ir antes, se a pressa for medir.

Cada fatia é comparada com a execução medida mais recente, na mesma matriz: bio e mech × Zerg
CheatInsane × Macro/Timing/Rush/Air/Power, mais uma célula Terran para o E3 e o E6. Um experimento
sem ganho medido é revertido e fica registrado.

## 5. O que não fazer

- **Não trocar o `SpawnController` nem o `ProductionController` por um executor próprio.** O
  controle fica no dict (proporções, prioridades, quem entra) e no plano. As armadilhas do Ares
  entram no Body, como entrou a `ExactResearch`.
- **Não resolver a trava com `freeflow` permanente nem com histerese.** O `freeflow` apaga o mix
  inteiro.
- **Não pôr limiar de entrada no mix,** do tipo "só entra com parcela ≥ X". O único degrau é o da
  unidade inteira.
- **Não ajustar `COUNTERS` partida a partida.** Os números vêm dos dados (E7) e da calibração por
  replay (N5).
- **Não resolver a composição com LP.** O propostas.md já descarta solver global, e o E6 é uma conta
  fechada, sem otimizador.
- **Não criar missões na economia.** A abertura tem ciclo de vida, mas nenhuma outra operação
  econômica dura. `economy/` fica como `control/`, sem `missions/`.
- **Não criar um estilo ou um planner por matchup.** O estilo é a abertura mais a resposta ao
  desconhecido, e a raça entra como prior.
