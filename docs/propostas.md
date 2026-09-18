# Propostas para evoluir o bot

> Análise realizada em 14 de setembro de 2026 sobre o commit `483722e`
> (`botbandido`) e o submódulo Ares `v3.13.1`, commit `8730865` de 5 de
> setembro de 2026.
>
> Este é somente um documento de pesquisa e planejamento. Nenhuma proposta foi
> implementada, nenhum teste foi executado e nenhuma partida foi iniciada. Foram
> lidos os dois traces já existentes em `logs/`, ambos sem evento `game.ended`;
> portanto eles servem para diagnosticar decisões, não para afirmar vitória,
> derrota ou força competitiva.

> **Estado em 18 de setembro de 2026 (`3fd7723`).** O P0 inteiro foi
> implementado: harness e baseline, defesa por incidente, wall nos dois
> sentidos, desconhecido estimado, ciclo ofensivo completo, macro mínima com
> interrupção do opening e CI. P1 e P2 continuam abertos. A análise abaixo é a
> de 14/09 e descreve o bot de `483722e`; cada lacuna e cada item do roadmap
> tem uma nota **Hoje** com o que mudou. Como o bot funciona agora está em
> [architecture.md](architecture.md), com as medições e os experimentos
> revertidos; os modelos do branch `matematização` que servem ao P1 estão em
> [migration-map.md](migration-map.md).

## Conclusão

Sim: o bot está na mesma família arquitetural dos projetos open source maduros
de SC2. Ele já possui equivalentes de percepção, memória, influência espacial,
estratégia, planners, arbitragem de unidades e behaviors. A semelhança é ainda
mais direta porque o projeto usa Ares como infraestrutura.

O ponto importante, porém, é separar **maturidade da fundação** de **maturidade
do jogador**:

| Área | Estado atual | Avaliação |
| --- | --- | --- |
| Arquitetura, determinismo e testabilidade | Forte | Melhor parte do projeto; deve ser preservada |
| Explicabilidade e observabilidade | Forte | Diferencial mais defensável em relação à amostra pesquisada |
| Memória, campo e topologia | Infraestrutura forte | Há boa informação calculada, mas ainda poucos consumidores decisórios |
| Estratégia e inteligência contínua | Inicial | Dois objetivos, um scout early e pouca leitura do adversário |
| Macro adaptativa e resiliência | Inicial | Uma abertura para todos os matchups e composição fixa depois dela |
| Combate e capacidade de encerrar partidas | Muito inicial | Defesa, `HOLD`, `AMove` e decisão de siege; não há missão ofensiva |
| Avaliação empírica | Insuficiente | Há traces excelentes, mas não há baseline reproduzível de partidas |

Em uma frase: **já existe uma plataforma de decisão melhor estruturada que o
bot que joga sobre ela**. O maior ganho agora não virá de outra camada
matemática. Virá de fechar o ciclo
`perceber → escolher → executar → medir`: defesa correta, ataque/retirada,
scouting recorrente, macro que reage e uma matriz reproduzível de partidas.

## Como esta avaliação foi feita

Foram inspecionados o fluxo de frame, os contratos públicos, planners,
behaviors, testes, telemetria, workflows, configuração, abertura Terran e os
traces locais. A comparação externa usou documentação e repositórios primários:

- [Ares](https://github.com/AresSC2/ares-sc2), sua
  [documentação](https://aressc2.github.io/ares-sc2/),
  [grids e pathing](https://aressc2.github.io/ares-sc2/tutorials/influence_and_pathing.html),
  [squads](https://aressc2.github.io/ares-sc2/tutorials/unit_squads_group_behaviors.html),
  [mediator e combat simulation](https://aressc2.github.io/ares-sc2/api_reference/manager_mediator.html)
  e [Build Runner](https://aressc2.github.io/ares-sc2/tutorials/build_runner.html);
- [PiG Bot](https://github.com/Vers-AI/SC2_PiGBot),
  [Sajuuk](https://github.com/Guillaume-Docquier/Sajuuk-SC2),
  [Sharky](https://github.com/sharknice/Sharky),
  [MicroMachine](https://github.com/RaphaelRoyerRivard/MicroMachine) e
  [Sharpy](https://github.com/DrInfy/sharpy-sc2);
- [BurnySc2/python-sc2](https://github.com/BurnySc2/python-sc2) e a
  documentação da AI Arena sobre
  [desenvolvimento](https://aiarena.net/wiki/bot-development/),
  [execução local](https://github.com/aiarena/local-play-bootstrap),
  [Data API](https://aiarena.net/wiki/data-api/) e
  [regras](https://aiarena.net/wiki/rules/).

Não foi feita uma auditoria completa linha a linha de todos os projetos
externos, nem um benchmark entre eles. Features declaradas em README são
tratadas como padrões para estudo, não como prova de qualidade ou superioridade.
Frameworks e bots completos também são comparados separadamente sempre que isso
importa.

## Revisão crítica da análise prévia

### O que ela acertou

- A correspondência conceitual
  `Attention → Awareness → Ego → Body` é real e aparece, com outros nomes, em
  frameworks e bots maduros.
- Influence maps, memória sob fog, valor/força regional, target scoring, papéis,
  squads e prioridades são técnicas amplamente usadas. A matemática espacial
  não é exótica.
- Ares já oferece boa parte dos mecanismos operacionais necessários ao Body:
  roles, squads, grids, pathing, behaviors combináveis e combat simulation.
- Sajuuk é uma boa analogia para avaliação regional e despacho dinâmico de
  unidades. Sharky é uma boa analogia para tarefas priorizadas que disputam
  unidades. PiG é o comparador mais direto por também estar sobre Ares.
- Há valor genuíno em tornar ownership e arbitragem explícitos, determinísticos
  e observáveis.

### O que precisa de nuance ou atualização

1. **A análise descreve como futuro várias coisas que já existem.** O projeto já
   implementou memória com confiança e incerteza, campo gaussiano, topologia,
   histerese estratégica, proposals, ownership exclusivo, scout, JSONL, SVG e
   viewer.

2. **A originalidade não está nos componentes isolados.** Sharky, por exemplo,
   também ordena tarefas e deixa cada uma reclamar unidades. O diferencial
   concreto daqui é a combinação de fluxo puro, ordem total determinística,
   posse central e trilha causal.

3. **“Mais limpa” deve significar “mais explícita e verificável”, não
   automaticamente menos complexa.** Só `topology.py` tem quase mil linhas, e o
   subsistema de logs/viewer já é um produto relevante. Essa complexidade pode
   valer a pena, mas precisa gerar decisões e métricas de jogo.

4. **O exemplo de soma de DPS na documentação do Ares não descreve todo o grid
   padrão.** A implementação atual também separa perigos ground/air, detecção e
   efeitos. O exemplo comprova a técnica, não uma fórmula única do framework.

5. **Uso difundido não é prova de ganho competitivo.** Influence maps e scoring
   são bons precedentes, mas sua contribuição precisa ser medida por replay,
   cenário e ablação.

6. **Manager e `if` não são opostos.** Manager define responsabilidade e ciclo
   de vida; constraints, estados, thresholds e scores ainda formam a política.
   Uma utility mal calibrada apenas esconde os `ifs` em pesos.

7. **A utility comum ainda não existe de fato neste bot.** `Proposal.priority`
   é um float calculado localmente. Defense e Intel usam números em `[0,1]`, mas
   disputam pools diferentes; CoreArmy é só fallback. Economia e estruturas
   passam fora dessa arbitragem. Não há ainda vários planners militares reais
   comparando valor, risco e custo na mesma escala.

8. **A conclusão “Sajuuk é o mais parecido” é uma boa hipótese, não um fato
   demonstrado por auditoria do runtime.** A documentação pública confirma as
   features, mas não a equivalência completa dos fluxos.

Portanto, a tese revisada fica assim: **a arquitetura não é inédita pelos seus
ingredientes; ela é promissora por tornar causalidade, arbitragem e diagnóstico
excepcionalmente explícitos.**

## O que aprender de cada projeto

| Referência | Tipo | Padrão útil | Aplicação aqui |
| --- | --- | --- | --- |
| [Ares](https://github.com/AresSC2/ares-sc2) | Framework usado pelo projeto | Roles, squads, behaviors pequenos, grids especializados, combat sim, macro/tech controllers e deduplicação de ações | Manter a política própria e reutilizar estes mecanismos no Body; não reimplementar micro e pathing genéricos |
| [PiG Bot](https://github.com/Vers-AI/SC2_PiGBot) | Bot completo sobre Ares | Builds por matchup, switches por scouting, reações a cheese, decisão de lutar só quando favorecido, target scoring, formação e relatório de jogo | É o melhor comparador funcional: estudar especialmente o caminho entre intel, reação, combate e dados, sem copiar sua organização por managers |
| [Sajuuk](https://github.com/Guillaume-Docquier/Sajuuk-SC2) | Bot completo | Valor e força por região, objetivos de guerra, despacho dinâmico, prioridades e condições de bloqueio em pedidos de construção | Transformar a topologia já pronta em `RegionState` consumido por defesa, ataque, scouting e expansão |
| [Sharky](https://github.com/sharknice/Sharky) | Framework C# | MicroTasks priorizadas reclamando unidades, transições/counter-transitions de builds, identificação de estratégia e histórico de resultados | Comparar seu claiming com o Engine e adotar portfolio pequeno de builds e resultados reproduzíveis |
| [MicroMachine](https://github.com/RaphaelRoyerRivard/MicroMachine) | Bot Terran C++ | Squads com ordens, memória inimiga, controllers especializados e coordenação Terran | Referência histórica para bio/tank/medivac, coesão de grupo, siege, kite e target selection |
| [Sharpy](https://github.com/DrInfy/sharpy-sc2) | Framework Python | Planos declarativos sequenciais/paralelos com requisito, conclusão, skip e lifecycle; bots pequenos de teste | Inspirar etapas reativas da abertura e cenários mínimos, sem adicionar Sharpy como segunda dependência |
| [AI Arena](https://aiarena.net/wiki/bot-development/) | Runtime e ladder | Ambiente reproduzível, resultados/replays, estados explícitos de crash/timeout e `OpponentId`/dados persistentes | Fazer o benchmark local usar o mesmo contrato da ladder e ligar cada resultado a commit e configuração |

Não há razão para trocar Ares por outro framework. Os outros projetos servem
como biblioteca de padrões. Ares, PiG, Sajuuk, MicroMachine e Sharpy declaram
licenças permissivas nos repositórios consultados; no caso de Sharky, não foi
identificada uma licença raiz clara durante esta pesquisa, então convém estudar
ideias e não copiar código sem esclarecer a licença. As
[regras da AI Arena](https://aiarena.net/wiki/rules/) também distinguem usar um
bot como referência de simplesmente cloná-lo.

## O que já está muito bom aqui

### 1. A cadeia causal é curta e legível

[`play_frame`](../bot/main.py#L60) mostra a ordem completa sem esconder a
política em callbacks dispersos:

```text
Attention → Awareness → Strategy/Planners → Engine → Behaviors → Logs
```

A regra documentada — Planner decide **o quê**, Engine decide **quem**, Behavior
decide **como** — é uma fronteira boa. Só a percepção, execução e observadores
tocam o objeto mutável do bot; o miolo trabalha com estados congelados.

### 2. Determinismo e posse são tratados como invariantes

O [`Engine`](../bot/body/engine.py#L45) possui ordem total, uma única posse por
tag, preferência por manter o dono anterior e liberação explícita. Isso é mais
fácil de testar e explicar que vários controllers emitindo ordens concorrentes.
O teste de replay da mesma sequência de frames reforça a intenção de
reprodutibilidade.

### 3. Awareness distingue observação de crença

[`AwarenessModel`](../bot/awareness/model.py#L124) não apenas guarda a última
posição: aplica decaimento de confiança, incerteza crescente, morte confirmada,
carência de visão e memória distinta para estruturas. A separação entre ameaça
possível alargada pela incerteza e presença inimiga crível é uma boa ideia e
mais interessante que uma simples lista de “últimos vistos”.

### 4. O mapa está preparado para decisões de nível mais alto

A topologia é determinística, associa expansões a regiões, valida adjacências e
trata chokes internos. Em um trace existente, ela resolveu 14 expansões sem
pendências e produziu 18 regiões/27 passagens. O problema não é qualidade da
infraestrutura; é que ela ainda quase não decide gameplay.

### 5. A observabilidade é excepcional

O logger usa JSON estrito, schema versionado, `run`, sequência causal, iteração,
fingerprint de configuração e commit. Há ChangeGates, tempos por camada,
snapshots SVG, overlay e um viewer que liga estado, proposta, concessão e
comando. Isso permite tuning baseado em evidência e deve ser tratado como parte
do produto, não como debug descartável.

### 6. Há disciplina de testes

Foram encontradas 70 funções de teste próprias cobrindo topologia, memória,
campo, estratégia, Engine, defesa, scouting, fluxo, logs, SVG e viewer. A suíte
não foi executada nesta análise, então a afirmação é sobre cobertura declarada,
não sobre estado verde. Ainda assim, a forma dos testes protege invariantes
úteis em vez de apenas detalhes de implementação.

**Hoje:** 279 testes verdes em cerca de 2,5 s, sem instanciar `AresBot`.

### 7. A fronteira com Ares está saudável

O núcleo puro não virou uma coleção de chamadas ao mediator, enquanto o Body
reutiliza behaviors e grids do Ares. O submódulo está fixado em uma revisão
recente. A direção correta é aprofundar essa divisão: **política explicável
própria; mecanismo operacional do Ares**.

## Lacunas concretas encontradas

### Não existe uma missão para vencer a partida

[`Objective`](../bot/ego/strategy.py#L22) contém somente `STABILIZE` e
`BUILD_ADVANTAGE`; [`CoreArmy`](../bot/ego/planners/core_army.py#L18) sempre
produz `HOLD`. Defense só ataca uma ameaça próxima às próprias bases. Logo, não
há ataque proativo, retirada, regroup, pressão, destruição de bases inimigas ou
caça às últimas estruturas.

O trace antigo confirma o efeito, sem provar resultado: aos 523 s, 52 unidades
(incluindo cinco Medivacs e sete Tanks) continuavam sob comando `HOLD`.

**Hoje:** resolvido. `Offense` tem IDLE → ASSEMBLE → ADVANCE ⇄ SEARCH,
ENGAGE/RETREAT → REGROUP, alvo por estrutura lembrada e busca de estruturas
voando. Os objetivos da Strategy continuam dois.

### Defense confunde presença, perigo e déficit de resposta

[`defense.plan`](../bot/ego/planners/defense.py#L26) cria uma proposta para toda
base com qualquer pressão positiva. O tamanho depende de `pressure / mean_power`
e ignora `cover`; o mesmo contato pode influenciar várias bases e criar várias
missões para o mesmo alvo.

Há uma reprodução clara no trace do commit `788af1d`; a fórmula continua
semanticamente igual no HEAD. Um único SCV inimigo, poder `0,58`, contribuiu
pressão para três bases. Mesmo com cobertura `6,60`, `3,12` e `12,49`, surgiram
três propostas e foram retirados do CoreArmy um Marine, um Marauder e um Tank
para atacar o mesmo SCV. É um excelente caso de regressão já pronto.

**Hoje:** resolvido. Um incidente por grupo de atacantes, id que segue os
membros, um orçamento `1,5 · poder` repartido entre ar e terra, e o caso do SCV
virou teste. Continua sem distinguir scout, worker rush e ataque.

### Ausência de visão parece vantagem

`enemy_power` é apenas a soma dos contatos conhecidos, já reduzidos por
confiança. Quando não há visão recente, ele converge a zero. Strategy então
interpreta a fração do nosso exército como próxima de um e produz `risk` alto,
embora a inferência correta seja “não sabemos”. Em um trace, aos 500 s,
`own_power=50`, `enemy_power=0`, `army=0,10` e `risk=1,0` coexistiam sem visão do
exército adversário.

Além disso, o nome `risk` não combina bem com a fórmula atual: o valor aumenta
quando estamos aparentemente fortes e seguros. Antes de virar uma entrada real
de decisões, deve ser renomeado para algo como `initiative`/`commit_confidence`
ou ter sua semântica corrigida.

**Hoje:** resolvido no mínimo. `estimated = max(conhecido, visto vivo,
esperado)`, com incerteza e cobertura explícitas, e a ofensiva planeja contra
`estimado + 0,5 · incerteza`. `risk` não foi renomeado; o crescimento esperado
não foi calibrado.

### Campo e topologia ainda fecham pouco o loop

O campo é calculado a cada frame, mas seus consumidores no bot são quase todos
logs, overlay e snapshots. A topologia participa da rota do scout e da
visualização, mas ainda não produz frontline, valor regional, escolha de alvo,
rota estratégica ou expansão segura. Na execução, CoreArmy usa o grid do Ares
com `sense_danger=False`, e Defense usa `AMove`.

Isso cria dois mapas: um cognitivo, próprio e explicável; outro operacional, do
Ares. A duplicação pode ser boa se as responsabilidades forem explícitas, mas
hoje a ponte entre ambos está incompleta.

**Hoje:** igual. Nenhuma decisão consome o campo nem a topologia além do scout.

### A política macro é pequena para o meio de jogo

- O mesmo `BioThreeOneOne` é usado contra Protoss, Terran, Zerg e Random.
- Depois da abertura, a composição é fixa em Marine/Marauder/Tank/Medivac.
- Não há continuação explícita de upgrades, detecção, reação a air/cloak,
  reposição de infraestrutura, Orbital/scan/MULE ou capacidade de produção por
  dívida.
- A abertura não tem um caminho claro de abort/branch para rush: o macro
  dinâmico só entra quando `opening_done`.
- O alvo de expansão pode oscilar quando a contagem observada de townhalls
  oscila; os traces mostram alternância rápida entre quatro e cinco bases.

No trace antigo, o último frame observado tinha 1.270 minerais, 1.173 gás e 15
de supply livre. Isso não prova um problema geral, mas é um sinal mensurável de
capacidade/spending insuficiente, especialmente no gás.

**Hoje:** parcialmente. Upgrades, Orbital, MULE, detecção, interrupção do
opening, teto de produção por base, Reactors, gás por geyser e expansão sem
teto de seis bases entraram. Continuam uma abertura e uma composição para
todos, nenhuma reação a rush além da interrupção, e o banco: 4–21 mil minerais
com supply livre nas partidas medidas, com a causa em aberto.

### O combate ainda é uma vertical slice

O controle atual é `AMove`, path individual e decisão de siege para Tank. Não há
decisão squad-level de engajar/retirar, formação, focus fire, overkill control,
stutter para bio, Stim, comportamento próprio de Medivac, proteção contra
splash ou target scoring. O Ares já fornece várias primitivas para isso; não é
necessário começar do zero.

**Hoje:** Stim no ataque e no rally, Medivac acompanhando o grupo, decisão de
lutar/recuar por grupo. Sem stutter, focus fire, target scoring nem formação.

### O modelo de capacidade militar é excessivamente agregado

`unit_power = sqrt(max(ground_dps, air_dps) × hp)` é uma medida simples e útil
para um primeiro corte, mas ignora range, armor, upgrades, splash, velocidade,
spells e compatibilidade ground/air. `Contact` nem preserva `can_attack_ground`
e `can_attack_air`. Em ataques mistos, a defesa aceita qualquer unidade de
exército; uma unidade de suporte ou incapaz contra o alvo pode ocupar uma vaga.

A incerteza também alarga o sigma sem conservar massa. Isso faz sentido como
**possibilidade de risco**, mas não necessariamente como **ameaça esperada**.
Os dois conceitos precisam de nomes e consumidores distintos.

**Hoje:** o poder é `sqrt(dps · alvos · vida)`, com splash, e cada unidade
carrega `can_attack` ground/air; a defesa exige a capacidade (`must_attack`). O alcance
continua fora — é o que perde as lutas contra Siege Tanks.

### Há duas representações potenciais de ownership

O Engine guarda o owner real, mas o exército ainda não espelha esse owner nos
`UnitRole`/squads do Ares; roles são usados principalmente para worker scout e
mineração. Se squads do Ares entrarem depois, Engine e Ares não podem se tornar
duas autoridades independentes.

**Hoje:** igual; nenhum squad do Ares entrou.

### Operação e avaliação ainda são pouco reproduzíveis

[`run.py`](../run.py#L137) sorteia mapa e raça e inicia uma partida. Não há CLI
para uma matriz fixa, agregador de resultados, baseline/challenger ou salvamento
sistemático de replay. Os workflows atuais empacotam o bot, mas não executam os
testes próprios nem o Ruff antes do artefato/upload. O README e o nome do bot
ainda são os placeholders do template.

**Hoje:** resolvido, exceto o nome do bot. `bench.py` joga uma matriz fixa e
grava `result.json` com resultado, commit, fingerprint, replay e log; o CI roda
pytest e ruff antes de empacotar; o README descreve o bot.

### O wall só abre

StructureControl considera apenas `SUPPLYDEPOT` levantado e só emite `lower`.
Depois de virar `SUPPLYDEPOTLOWERED`, não há plano que o levante quando um
inimigo terrestre se aproxima. A própria arquitetura atual lista essa limitação
como fora da fatia.

**Hoje:** resolvido. O depot sobe com inimigo terrestre a ≤ 8 e desce 3 s
depois, empurrando nossas unidades para a borda.

## Fronteiras recomendadas

Para aproveitar o que já existe sem criar verdades concorrentes:

| Decisão/dado | Fonte de verdade recomendada |
| --- | --- |
| Unidades e fatos visíveis do frame | Attention |
| Memória, confiança e estimativas inimigas | Awareness próprio |
| Campo estratégico grosso e resumos regionais | Awareness próprio |
| Custos táticos tile-level, efeitos e avoidance | Grids do Ares |
| Objetivos e utilidade de missões | Ego/planners |
| Owner exclusivo e grant efetivo | Engine |
| `UnitRole`/squad do Ares | Espelho do grant do Engine, nunca outra autoridade |
| Micro, pathing e emissão/deduplicação de comandos | Body sobre behaviors do Ares |
| Orçamento de macro e composição desejada | Strategy + planner de economia |

Também convém usar uma política híbrida, não uma soma universal:

1. constraints duras de elegibilidade e segurança;
2. classes lexicográficas quando necessário, por exemplo emergência antes de
   oportunidade;
3. score contínuo apenas entre opções comparáveis;
4. custo de assignment para escolher as unidades.

Uma forma explicável para missões comparáveis pode ser:

```text
utility = strategic_value + urgency + information_gain
          - tactical_risk - travel_cost - opportunity_cost
```

Cada termo precisa de intervalo, unidade, peso, saturação e log. Hard constraints
como “precisa atacar air” ou “precisa de detector” não devem virar uma penalidade
que outro peso consiga comprar.

Quem é dono de cada parte da decisão (revisão de 15/09, que prevalece sobre o
texto acima onde divergir):

- **Awareness** fornece fatos lembrados ou inferidos: poder e capacidades
  observadas ou estimadas, confiança, incerteza, continuidade, pathability e
  ativos afetados. Descreve; não escolhe margem nem prioridade.
- **Ego** define a política: poder requerido, margem, valor estratégico,
  requisitos, preferências de suitability, prioridade, alvo e demanda/lifecycle.
- **Engine** é o dono exclusivo das tags e aplica elegibilidade e custo de
  assignment ao contrato do Ego.
- **Behavior** executa e pode reagir localmente para esquiva e sobrevivência,
  mas não redefine missão, orçamento ou prioridade global.

“Dois consumidores” é uma boa heurística de generalização, não condição
necessária: um único consumidor mais uma invariante testável pode justificar um
módulo. O problema é criar outra autoridade, não usar certo sufixo ou pasta.

## Roadmap priorizado

| Ordem | Proposta | Impacto esperado | Por que agora | Hoje |
| --- | --- | --- | --- | --- |
| P0.1 | Harness reproduzível e baseline | Torna todo o resto mensurável | Hoje não há evidência de win rate/regressão | Feito; a matriz de 9 partidas é pequena |
| P0.2 | Corrigir incidentes defensivos e o wall | Remove decisões comprovadamente erradas | Há caso real de um SCV gerando três respostas | Feito |
| P0.3 | Missão ofensiva com engage/retreat/regroup | Dá ao bot uma condição de vitória | O exército hoje só segura posição | Feito; alcance no poder pendente |
| P0.4 | Macro resiliente mínima | Evita morrer durante opening e reduz bancos/produção parada | Abertura e composição são estáticas | Parcial: banco e rush abertos |
| P0.5 | CI e artefato verificável | Protege a base já bem testada | Workflows empacotam sem rodar testes/lint | Feito; nunca rodou no GitHub |
| P1.1 | Scouting recorrente e estimativa do desconhecido | Evita confundir falta de visão com vantagem | `enemy_power` decai para zero | Estimativa feita; scouting recorrente não |
| P1.2 | `RegionState` e campo acionável | Faz a topologia pagar seu custo | Hoje quase só scout/debug a consomem | Não começado |
| P1.3 | Squads e micro Terran incremental | Melhora trade e sobrevivência | Ares já oferece os blocos operacionais | Stim e Medivac; o resto não |
| P1.4 | Contrato de Proposal/Engine por capacidade e poder | Permite missões concorrentes sem alocações ruins | `count` e proximidade são insuficientes | `minimum_power`, `must_attack` e FULL/PARTIAL/REJECTED feitos; `desired_power`, suitability e preempção não |
| P1.5 | Builds e reações por matchup | Torna macro/intel adaptativos | Uma única abertura cobre todos os adversários | Não começado |
| P2 | Calibração, portfolio por oponente e crença mais rica | Otimiza uma política já funcional | Exige dados que ainda não existem | Não começado |

### P0.1 — Criar um loop de avaliação reproduzível

**Corte mínimo proposto**

- Tornar mapa, raça inimiga, dificuldade/oponente, revisão e número de partidas
  parâmetros explícitos; não depender de `random.choice` sem seed registrada.
- Gerar um `result.json` por partida ligando resultado, replay, JSONL, commit,
  Ares SHA, configuração e motivo de término (`victory`, `defeat`, `tie`, crash,
  timeout ou sem resultado).
- Começar com smoke contra a IA e uma matriz pequena de bots fixos/mapas AIE;
  depois usar o
  [local-play-bootstrap](https://github.com/aiarena/local-play-bootstrap) para
  reproduzir a ladder.
- Comparar baseline e challenger nas mesmas condições. Não promover mudança por
  uma única partida.

**Métricas iniciais**

- win rate com intervalo de incerteza, crash/timeout e duração;
- supply block acumulado, recursos parados, workers e army supply em marcos;
- utilização de produtores, upgrades/tech timing e expansões;
- valor perdido/trocado, tempo do exército ocioso, primeiro ataque e retreats;
- cobertura/idade de scouting e reações corretas a tech/rush;
- tempo total do frame em média, p50, p95 e máximo, além de ações/APM.

O logger atual já resolve boa parte da identidade causal. Falta agregar resultado
e replay em torno dele.

**Hoje:** feito com a IA do jogo, não com o local-play-bootstrap. Uma partida que
o bot não jogou (`on_start` falhou) é `not_played`, fora da taxa de vitória.
Falta: bots fixos como oponente, células fora de VeryHard Macro, repetir a célula
na mesma execução, distinguir falha do cliente de exceção nossa, e as métricas
intermediárias acima como relatório (hoje são extraídas do JSONL à mão).

### P0.2 — Modelar defesa como incidente, não como “base × contato”

**Corte mínimo proposto**

- Agrupar contatos próximos em um `ThreatIncident` e associar a ele todas as
  bases afetadas. Um incidente produz uma resposta, ainda que seu kernel toque
  três bases.
- Separar poder requerido, cobertura adequada já presente e reforço faltante:

  ```text
  required_power = margin × incident_power
  reinforcement_deficit = max(0, required_power - suitable_committed_cover)
  ```

- Manter pelo menos um responder local quando for preciso expulsar um nuisance,
  mas não tirar três classes de unidade para perseguir um único scout.
- Distinguir scout, worker rush e ataque usando quantidade, duração, dano,
  direção/rota e proximidade de ativos vulneráveis.
- Separar requisitos ground/air por capacidade; ataques mistos pedem uma
  composição compatível, não “qualquer unidade”.
- Adicionar histerese curta para admitir/liberar a missão sem churn.
- Transformar o frame do SCV triplicado em teste de regressão.

**Wall**

- Controlar `RAISED`/`LOWERED` nos dois sentidos, antecipando o fechamento por
  ameaça visível ou lembrada na rota/choke.
- Considerar unidades amigas atravessando, debounce e fallback seguro para não
  esmagar o próprio tráfego nem abrir/fechar a cada frame.

**Critério de sucesso**

O log deve explicar `incident_id`, contatos, bases afetadas, poder necessário,
cobertura compatível, déficit, unidades concedidas e razão de release. O caso de
um SCV gera no máximo uma resposta pequena; um ataque real ainda mobiliza força
suficiente.

**Hoje:** feito, lido como **uma demanda coordenada com orçamento único**, não
como uma única proposta: o orçamento de um incidente é repartido entre as partes
aérea e terrestre, que somam o total e compartilham `demand_id`; a cobertura já
no local conta porque o Engine concede primeiro as unidades compatíveis mais
próximas. Falta: distinguir scout, worker rush e ataque; histerese de
admissão/liberação; antecipação e tráfego amigo no wall.

### P0.3 — Fechar o ciclo ofensivo

Não é necessário começar por um sistema genérico de missões. Um planner
`Attack` persistente já basta para criar competição real com Defense e
CoreArmy.

**Corte mínimo proposto**

1. `ASSEMBLE`: reunir uma massa mínima perto do rally.
2. `ADVANCE`: escolher base/expansão inimiga conhecida ou provável e usar path
   de grupo consciente de risco.
3. `ENGAGE`: consultar força local e o combat sim do Ares; lutar com margem.
4. `RETREAT/REGROUP`: preservar unidades quando o combate deixa de ser
   favorável, com cooldown para não oscilar.
5. `SEARCH`: quando alvos conhecidos acabam, visitar expansões/estruturas
   lembradas e procurar prédios flutuantes.

O gatilho não deve usar `enemy_power == 0` como certeza. Precisa de força mínima,
estimativa conservadora do desconhecido, confiança/recência da informação e
uma margem de compromisso. Combat simulation deve decidir confrontos locais,
não substituir Strategy inteira.

**Critério de sucesso**

- O bot consegue encerrar uma partida em que possui vantagem clara.
- Attack preempta CoreArmy, mas Defense preempta somente a parcela necessária.
- Engage/retreat não alternam rapidamente.
- Todo início, cancelamento, target switch e retreat possui razão no JSONL.

**Hoje:** feito sem o combat sim do Ares, que foi medido e revertido: ele só
aceita unidades à vista, e os Siege Tanks em siege atiram de fora da visão. A
luta local é medida contra o grupo inteiro, não em volta do núcleo. Falta:
alcance no poder, path de grupo consciente de risco, coesão e reforços (toda
unidade livre vai sozinha até o grupo).

### P0.4 — Completar a macro mínima e permitir emergência durante a abertura

**Antes de diversificar builds**, a baseline precisa sobreviver e gastar bem:

- uma saída de emergência do opening para proxy, worker rush, ling flood e
  ameaça aérea/cloak; Defense pode pedir bunker, units, repair/worker pull ou
  detecção antes de `opening_done`;
- workers, bases e gás calculados com `ready + pending`, cooldown e alvo estável;
- reposição de produtores/add-ons/tech destruídos;
- supply com previsão, não apenas reação;
- dívida de composição por supply e capacidade de produção baseada em demanda
  buildable e utilização sustentada;
- continuação de upgrades e uso básico de Orbital (`MULE` versus `scan` conforme
  energia e necessidade de informação/detecção);
- limite/fallback para recursos parados.

Reutilizar `ProductionController`, `TechUp`, `UpgradeController`, placements e
outros mecanismos do Ares é preferível a criar um macro executor paralelo. A
política de alvo, prioridade e reação permanece no projeto.

**Critério de sucesso**

Reduzir supply blocks, idle production e banco por minuto sem piorar
sobrevivência; reagir aos cenários de rush definidos; manter os targets de base
e produção estáveis na presença de pending/morph.

**Hoje:** feitos a interrupção do opening por emergência, upgrades, Orbital,
MULE, scan, Missile Turret, teto de produção por base, Reactors, gás por geyser e
expansão sem teto fixo. Falta: a causa do banco, reposição de produção
destruída, reação a rush (bunker, reparo, worker pull, proxy), supply com
previsão, alvo de bases estável (um pedido mantido foi medido e revertido) e
dívida/capacidade por utilização, que já está escrita no `matematização`.

### P0.5 — Colocar os testes existentes na fronteira de entrega

- Workflow de PR/push com `pytest` e `ruff` antes de construir/uploadar.
- Smoke de import e de criação do zip na revisão exata do submódulo.
- Testes novos para cover/deduplicação, ataque misto, depot levantando, reação
  durante opening, base `ready + pending` e falha isolada de observer.
- Fazer falhas de logger/overlay degradarem para `NullLogger`, como a
  documentação promete; hoje nem todo observer está isolado.
- Registrar todos os valores de configuração decisória, não só hashes de
  Awareness/Strategy. Defense, Intel, Economy, micro e build também precisam
  entrar no fingerprint reproduzível.
- Substituir o README do template por identidade, objetivo, capacidades reais,
  limitações, arquitetura, protocolo de benchmark e instruções de reprodução.

**Hoje:** feitos o gate de pytest/ruff nos dois workflows e o README. Falta:
gatilho de PR, smoke de import e do zip, isolamento de observers
(`NullLogger`), fingerprint da economia e do poder, e rodar os workflows no
GitHub (a suíte nunca rodou em Linux).

### P1.1 — Tornar informação uma necessidade recorrente

O scout early existente é um bom primeiro behavior e deve continuar. Depois
dele, um scheduler de Intel escolhe observações por valor esperado:

- idade de visão por expansão, região e tech location;
- probabilidade de base ocupada e última composição observada;
- perguntas explícitas: terceira base? air tech? cloak? massa de exército? rota
  de ataque?;
- candidatos Terran: Reaper, Marine barato, scan e eventualmente unidade aérea;
- score de informação menos risco, custo de scan e distância;
- reposição/cancelamento com lifecycle, em vez de “um SCV e acabou”.

Awareness deve expor ao menos `known_enemy_power`, `estimated_enemy_power`, faixa
de incerteza e `coverage/confidence`. Um modelo simples com piso por tempo,
bases/produção vistas e o máximo já observado é melhor que assumir zero. Não há
necessidade de Bayes completo nesta fase.

**Hoje:** a parte da Awareness está feita (`enemy_power`, `seen_enemy_power`,
`expected_enemy_power`, `estimated_enemy_power`, `enemy_uncertainty`,
`enemy_coverage`). O scheduler de Intel não existe: um SCV, uma vez, antes de
240 s.

### P1.2 — Produzir `RegionState` e obrigar o campo a ter consumidores

Agregar o lattice e os contatos por região:

```text
RegionState:
  own_power, known_enemy_power, possible_threat
  control, information_age, base_value
  neighbours, ingress/egress risk
```

Primeiros consumidores:

- Intel escolhe a pergunta/região mais valiosa e velha;
- Attack escolhe alvo e corredor de avanço;
- Defense escolhe choke/intercept em vez do centro médio do inimigo;
- Economy penaliza expansão sem rota/cobertura segura.

O campo próprio deve ficar grosso e estratégico. Perigo de spells, detecção e
path tático continuam nos grids do Ares. Antes de adicionar kernels, canais ou
resolução, exigir pelo menos dois consumidores e uma métrica que possa melhorar.
Se o custo aparecer antes do valor, calcular em cadência/lazy e por dirty state.

### P1.3 — Evoluir combate por uma fatia Terran de cada vez

Ordem compatível com a composição atual:

1. squad coeso com pathing e decisão comum de engage/retreat;
2. target scoring com ameaça, alcance, killability, overkill e alvo atual;
3. Marine/Marauder: stutter, focus e Stim com critérios de vida/valor;
4. Tank: posição atrás do bio, arco/choke, siege/unsiege e rota de retirada;
5. Medivac: heal, follow seguro, distância da ameaça e evacuação;
6. avoidance de efeitos e splash.

Usar behaviors de grupo/individuais do Ares e espelhar cada grant do Engine em
role/squad. Cada micro nova deve vir acompanhada de cenário isolado e comparação
de trade/sobrevivência; não implementar o catálogo inteiro de unidades.

### P1.4 — Enriquecer Proposal/Engine somente quando as novas missões disputarem

O próximo contrato útil não é um solver geral. É informação suficiente para um
greedy competente:

- `minimum_power` e `desired_power`, em vez de apenas `count`;
- capacidades obrigatórias e desejáveis: ground/air, detector, healer, siege,
  mobilidade;
- score de suitability por matchup;
- custo de caminho/tempo, coesão de squad e opportunity cost;
- commitment/preemption margin para evitar roubo a cada pequeno delta;
- deadline/lifecycle apenas para missões persistentes;
- resultado `full`, `partial` ou `rejected`, sempre com razão.

Hard constraints vêm antes de utility. Entre candidatos elegíveis, o assignment
pode priorizar dono anterior, adequação, custo de caminho, coesão e tag como
desempate. O Engine permanece a única fonte de ownership; Ares recebe o espelho.

### P1.5 — Criar um portfolio pequeno por matchup

Depois da baseline estável:

- uma abertura principal por matchup;
- no máximo uma alternativa ou branch inicialmente;
- transições baseadas em evidência observável, com recência/confiança e
  cooldown: proxy, expansão, air tech, greed e ausência de tech esperado;
- fallback explícito quando o scouting falha;
- resultado e motivo do switch no relatório de fim de jogo.

PiG mostra o valor de switches predefinidos; Sharky mostra transições e
counter-transitions. Regras claras e testáveis devem vir antes de classificador
ou aprendizado.

### P2 — Calibrar e aprender depois que o loop funcionar

- Ajustar pesos/kernels/thresholds por replay e ablação, não por sensação.
- Separar ameaça esperada de pior caso possível e calibrar ambos.
- Propagar incerteza por mobilidade, pathability e regiões alcançáveis, em vez de
  apenas círculo isotrópico, se os erros de fog justificarem.
- Usar histórico por mapa/matchup e, opcionalmente, `OpponentId` para selecionar
  entre poucas estratégias. A AI Arena permite dados persistentes e expõe o ID;
  `UseData: false` é uma escolha conservadora, não uma exigência da ladder.
- Só considerar otimização automática/ML quando houver dataset versionado,
  baseline, holdout de mapas/oponentes e proteção contra overfitting.

## O que não fazer agora

- Não reescrever a arquitetura de camadas; os seams atuais são o maior ativo.
- Não substituir Ares por Sharpy/Sharky nem manter dois frameworks de runtime.
- Não criar um `Manager` ou DTO para cada conceito antes de haver dois usos.
- Não transformar macro, scouting e combate em uma única utility sem unidades e
  constraints comparáveis.
- Não introduzir ILP/global solver; um greedy com requisitos corretos resolve o
  estágio atual.
- Não refinar o lattice, kernels ou topologia enquanto eles não dirigirem pelo
  menos duas decisões mensuráveis.
- Não começar por RL, rede neural ou belief probabilístico completo.
- Não copiar código externo sem conferir licença e regras; aprender padrões é
  suficiente para esta evolução.
- Não usar Elo ou uma vitória isolada como diagnóstico. Guardar replay, causa da
  decisão e métricas intermediárias.

## Marcos

### Marco do P0 — atingido

1. ~~uma matriz fixa de partidas produz resultado, replay e logs ligados à revisão~~;
2. ~~o caso do SCV não gera três respostas defensivas e o depot volta a levantar~~;
3. ~~uma emergência pode interromper/adaptar a abertura~~ (sem partida que o
   exercite);
4. ~~o exército forma, ataca um objetivo, recua quando desfavorecido e retoma sem
   oscilar~~;
5. ~~o bot procura e destrói os últimos alvos quando está em vantagem~~;
6. ~~falta de visão aparece como incerteza, não como `enemy_power=0` confiável~~;
7. ~~testes/lint protegem o artefato de ladder~~;
8. a comparação com o baseline mostra se houve ganho e em qual métrica —
   **parcial**: `bench.py compare` existe, mas nove partidas contra a IA não
   separam nenhuma mudança pelo placar, e o HEAD não tem matriz própria.

### Próximo marco

O bot fecha o ciclo contra a IA VeryHard Macro; o que o separa de um oponente
mais forte está no P1. A ordem sugerida parte do que já foi medido:

1. **Medição que separe mudanças.** Matriz do HEAD; mais seeds por célula;
   células de Rush (a única partida fora de Macro foi um timeout); um ou dois
   bots fixos pelo local-play-bootstrap; métricas intermediárias (banco por
   minuto, utilização de produtores, army supply em marcos) no `summary.json`
   em vez de extraídas à mão.
2. **Macro que gasta.** A causa do banco, com utilização por produtor no log
   (o modelo está no `matematização`), reposição de produção e reação a rush.
3. **Poder com alcance.** As lutas perdidas contra Terran são contra Siege Tanks
   em siege fora da visão; splash já entrou, alcance não.
4. **Portfolio por matchup (P1.5)** e **scouting recorrente (P1.1)**, juntos:
   uma troca de build só vale com a informação que a dispara.
5. **`RegionState` (P1.2)** quando um desses consumidores precisar dele.

Esse marco está atingido quando uma mudança de macro ou de combate aparece como
diferença medida numa matriz que inclui rush e mais de uma dificuldade, e não
só como mecanismo no JSONL.
