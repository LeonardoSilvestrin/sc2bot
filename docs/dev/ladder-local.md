# Bots locais da ladder: mecanismos para aproveitar

Pesquisa de **04/10/2026** sobre os cinco pacotes em
[`tools/aiarena_local/runtime/bots`](../../tools/aiarena_local/runtime/bots), comparados com o código
do working tree e com `docs/dev`. É pesquisa e proposta; não altera o comportamento do bot e não
representa trabalho adotado em staging. Nenhuma partida foi lançada nesta análise.

**Resultado:** o Sharpy local oferece implementações verificáveis para completar OS1, OS4/OS5,
OS6 e N7.4. O Phantom oferece pistas particularmente relevantes para late game: objetivos de tech,
reservas para morph, prioridade de gás quando maxed, expansão considerando recursos restantes e
combate que representa alcance e tempo de chegada. A maior parte já tem equivalente no nosso
backlog; o ganho está em tornar os mecanismos executáveis e medir seu efeito.

## Escopo e qualidade da evidência

| Pacote | O que está disponível | Papel nesta comparação |
| --- | --- | --- |
| PhantomBot | Versão **3.48.1**, commit declarado `8dfd757c3c5a7d246243872d6fc9922ebe661745`; módulos ELF/Cython para Linux, metadados, changelog e parâmetros | Principal referência de macro/late; implementação interna parcialmente inacessível |
| RustyMarines | Fonte Python; `version.txt` registra `2024-08-08` / `6933621` | All-in de Marines/proxy, até 20 SCVs; referência de execução Terran, não de economia de late |
| SharpKnives | Fonte Python; mesma identificação de pacote | Proxy de Zealots com transição para macro, Stalkers/Void Rays |
| SharpCannon | Fonte Python; mesma identificação de pacote | Cannon rush/contain/expand com continuação de macro e Stalkers |
| RoachRush | Fonte Python | Rush de uma base; micro e busca para encerrar, sem transição econômica sofisticada |

O [`build.json` do Phantom](../../tools/aiarena_local/runtime/bots/PhantomBot/build.json) identifica
o fonte como `https://github.com/phantomsc2/phantom-sc2`. O download do commit retornou **HTTP 404**.
Isso não permite concluir se o repositório é privado, foi removido ou mudou de endereço.
Não foi possível verificar as fórmulas desse fonte.

Para o Phantom, distinguimos:

- **Fonte disponível:** `run.py`, `build.json`, `METADATA`, `data/params.json` e o Leitwerk empacotado.
- **Declaração do autor:** itens do changelog em
  [`METADATA`](../../tools/aiarena_local/runtime/bots/PhantomBot/phantom-3.48.1.dist-info/METADATA).
  Descrevem evolução, sem provar ativação ou desempenho na versão atual.
- **Símbolo no binário:** nomes de rotinas preservados pelo Cython, extraídos como texto, sem
  importar ou executar os módulos. Provam a presença do nome; não a fórmula, ordem de chamada ou eficácia.

Os nomes selecionados e SHA-256 dos arquivos estão em
[`ladder-local-evidencias.json`](ladder-local-evidencias.json). Não atribuímos algoritmos ao Phantom
só por existir uma função com nome sugestivo. As adaptações abaixo são propostas nossas.

Nos três pacotes Sharpy, os arquivos de foco, agrupamento, ataque por zona, cleanup e
`SequentialList` consultados têm hashes iguais. São uma referência compartilhada, não três
implementações independentes. `KnowledgeBot` instala `GroupCombatManager`, que carrega as regras e
micros padrão. Ainda assim, um micro empacotado só importa para a partida se o bot produzir aquele
tipo: RustyMarines não produz Medivacs, Ravens ou Battlecruisers.

## Phantom: o que interessa para o late

### LL1 — Mix, objetivo absoluto e reserva para transição

**Evidência:** o changelog 3.32 declara objetivos de tech e composição de reserva para morph
dinâmicos. O módulo `agent/macro/strategy` preserva `composition_target`, `composition_deficit`,
`banking_resources`, `tech_target`, `counter_composition` e `rush_defense_composition`.
Isso sugere responsabilidades separadas; não revela como combina ou dimensiona cada uma.

**Comparação:** nossa
[`CompositionPolicy`](../../bot/ego/economy/policies/composition.py) já diferencia crença,
eficácia, custo, atraso de tech e SURVIVE. O produto normal continua sendo uma proporção, corrigida
pelo SpawnController. Não há nessa política uma reserva explícita de recursos para uma transição
nem um objetivo absoluto de reposição. E5, E9 e a demanda militar de
[`migration-map.md`](migration-map.md#demanda-de-exército-e-capacidade-de-produção) já apontam nessa direção.

**Aproveitar:** Economy pode traduzir o mix em quantidade desejada, déficit descontando produção
pendente e recursos reservados para uma transição útil. Para Terran, a reserva é de infraestrutura,
add-on, pesquisa e unidade de resposta; não se copia o mecanismo Zerg de larva/morph. Aplicar
depois de corrigir e validar a eficácia do mix, cujo problema já está documentado no debate.

**Medir:** tempo entre confirmar uma ameaça e produzir sua resposta, déficit por tipo, produção
ociosa por falta de recurso e reservas que ficaram paradas. Reserva precisa poder ser liberada
quando a ameaça muda; caso contrário ela vira outra fonte de banco improdutivo.

### LL2 — Gás e investimento sob supply máximo

**Evidência:** changelog 3.22 declara ajuste de prioridade de gás quando maxed; 3.36 declara limite
da taxa de mudança do alvo de gás. `Strategy.income` e `banking_resources` aparecem no binário.
Não foi recuperada a lei de controle.

**Comparação:** nosso
[`investment.py`](../../bot/ego/economy/policies/investment.py) dimensiona Refineries por
bases e parcela máxima de workers em gás. Usa banco mineral para detectar opening parado, mas
o alvo de gás não lê banco de gás, demanda do mix ou fila de gasto. É uma referência adicional
para E5/E9 e a lei de gasto proposta em
[`estimacao-e-controle.md`](staging/estimacao-e-controle.md#próximos-passos-decididos-como-direção-não-implementados).

**Aproveitar:** calcular demanda mineral/gás de reposição, pesquisas e transição num horizonte;
ajustar alocação de workers e investimento por essa demanda, com resposta gradual para evitar
trocas incessantes entre gás e minerais. O planner publica a decisão; Body/Ares executa.

**Limite importante:** em 200 de supply não cabe comprar outro exército. Mais produção ajuda a
repor perdas, mas não resolve sozinha uma ofensiva que não troca nem progride. O banco de 13–16 mil
citado no debate precisa ser separado em falta de supply, gás, capacidade, decisão de compra e
ausência de perdas/progresso. Não usar apenas “banco < 5 mil” como critério de qualidade.

**Medir:** tempo maxed, banco por recurso, tempo para repor uma luta, pesquisas úteis concluídas e
tempo em que havia supply, recurso e produtor disponível sem compra.

### LL3 — Expandir por recursos úteis, além de contar bases

**Evidência:** changelog 3.35 declara exclusão de destinos com poucos recursos restantes;
3.43 declara um solver de expansão no lugar de tabela fixa. O binário contém `select_expansion`
e `is_expansion_possible`; a função de custo não foi recuperada.

**Comparação:** nosso investimento decide expandir por saturação/teto de workers, postura e
quantidade de locais do mapa. `BaseView` contém identidade e posição, sem recursos restantes ou
saturação efetiva. Ares já cuida de mineração e execução da expansão; o dado que falta é para a
decisão no Ego. O problema aparece em propostas macro e no debate sobre excesso de bases.

**Aproveitar:** perceber recursos e workers por linha, diferenciar base mineradora de base esgotada
e atribuir valor à próxima base pelo retorno e custo de defesa/rota. Um limite rígido pelo número
de SCVs pode impedir a reposição de linhas esgotadas: comparar essa alternativa do debate com
uma política baseada em recursos, antes de adotá-la.

**Medir:** renda por base, workers em long-distance mining, expansões sem utilização, custo de
defender bases novas e capacidade de substituir linhas esgotadas.

### LL4 — Upgrades e tech como decisões distintas

**Evidência:** changelog 3.31 declara separação de prioridades de tech e upgrades; 3.32 registra
que pedir Adrenal Glands não deve iniciar automaticamente a transição para Hive. Os símbolos
incluem `allowed_upgrades`, `_allows_upgrade`, `upgrade_weights`, `_upgrade_priorities` e
`_composition_priorities`.

**Comparação:** nós já temos upgrades, add-ons e compra de pré-requisitos pelo Ares, incluindo
correções de execução em [`economy.py`](../../bot/body/behaviors/economy.py). Entretanto,
[`styles.py`](../../bot/ego/economy/knowledge/styles.py) mantém a lista de upgrades do
estilo, enquanto o mix pode mudar. E8/E9 já pedem essa ligação.

**Aproveitar:** Economy escolhe pesquisas pelo exército atual e reposição planejada, e autoriza
explicitamente a infraestrutura que elas exigem. A existência de um pedido de upgrade não deve,
por si só, justificar uma cadeia cara de tech. Preservar o tratamento de ability exata já existente.

**Medir:** gasto em upgrades sem unidades beneficiadas, atraso das pesquisas que beneficiam o mix
dominante e produção que deixou de ocorrer para financiar tech.

### LL5 — Combate por alcance, tempo e alvos válidos

**Evidência:** no binário de `CombatObservation` existem `dps_matrix`, `range_matrix`,
`cooldown_matrix`, `move_time_matrix`, `turn_time_matrix`, `can_reach`, `is_attackable`,
`is_detected` e `simulate`. O assignment preserva `target_engage_time`, `_death_time_with_extra`
e `_discounted_survival`. São indícios de um modelo mais detalhado que uma soma de poder;
não demonstram sua fórmula ou que ele evita overkill.

**Comparação:** nosso modelo já inclui matchup, armadura e splash em parte do cálculo, e a missão
avalia o núcleo local do squad. Isso não equivale a representar quando cada unidade consegue
começar a causar dano. N5, OS10 e o termo de alcance discutido pelos agentes são os equivalentes.

**Aproveitar:** primeiro corrigir o poder de casters/armas especiais apontado no debate; depois
medir em shadow um sinal de força que consegue atirar/chegar no horizonte da luta. Aproveitar o
CombatSimManager do Ares como referência disponível e manter planners recebendo dados imutáveis.
Não substituir nosso observador nem tomar memória sob fog por observação atual.

**Medir:** previsão versus troca real em lutas com melee, Tank, Lurker, ar e suporte; falsos
positivos de vitória e custo de CPU. Evitar copiar um simulador inteiro a partir de nomes no binário.

### LL6 — Detector e caster precisam de comportamento próprio

**Evidência:** há rotinas `Overseer.detection_assignment`/`tracking_assignment`,
`Viper.abduct_targets`/`gather_target`, `Lurker.has_targets` e `DodgeThreat.eta`/`dodge`.
O changelog declara micro de Lurker (3.32), melhorias de detecção (3.23) e arma virtual de Phoenix
contra solo (3.42). Não é possível reconstruir seleção, segurança ou uso de energia dessas rotinas.

**Comparação:** nosso Body possui stim, decisão de siege e escolta simples de Medivac. Não oferece
a execução correspondente para toda unidade que o modelo econômico poderia valorizar. O comentário
de SURVIVE já registra Liberators comprados sem siege. OS2/OS7 e o item de modelo de poder do debate
já reconhecem partes desse problema.

**Aproveitar:** condicionar novas unidades ao comportamento executável. Primeiro suporte e
detecção móvel segura; depois Raven/Matrix ou outra ability com seleção de alvo, energia, alcance
e rota. Avaliar ameaça de feitiços e controle mesmo quando o DPS automático é zero; não transformar
suporte sem arma em poder ofensivo inventado.

**Medir:** detecção útil durante a luta, spells efetivos, suporte perdido e unidades produzidas
que nunca executaram sua função. A transposição Viper → Raven é conceitual, não equivalência de ability.

### LL7 — Informação sobre expansão e defesa deve continuar chegando

**Evidência:** changelog 3.23 declara cobertura de scouts; 3.34 declara scouting de expansões e
adiamento da terceira contra uma base. `BaseRecord.observe`, `probability_of_being_taken`,
`observed_enemy_base_count`, `expected_enemy_base_count`, `_scout_eta_and_candidates` e
`suggest_scout_target` aparecem no binário. Não recuperamos o score nem o prior de bases.

**Comparação:** Intel governa uma missão de abertura; a busca de estruturas da Offense não é
scouting recorrente de tech/composição. OS3, N4 e a cobertura do migration-map já descrevem a lacuna.

**Aproveitar:** manter última confirmação de expansão/tech/exército e mandar scouts pelo impacto
na próxima decisão, idade, ETA e risco. Scouting deve poder alterar alvo, tech e investimento;
gerar observações que só entram no log não fecha o ciclo. Não copiar o prior probabilístico do
Phantom sem fonte, especialmente enquanto discutimos o piso de bases do nosso observador.

**Medir:** idade das confirmações, custo de scouts e quantas decisões mudaram após uma visita.

## Fonte local verificável: Sharpy e RoachRush

### LL8 — Foco com reserva de dano e avanço durante o cooldown

O [`focus_fire`](../../tools/aiarena_local/runtime/bots/RustyMarines/sharpy/combat/default_micro_methods.py)
filtra a categoria atingível, combina valor/vida/distância, favorece o último alvo e reduz o score
quando o dano já reservado supera a vida. O dano escolhido é somado em `focus_fired`.
[`GenericMicro`](../../tools/aiarena_local/runtime/bots/RustyMarines/sharpy/combat/generic_micro.py)
distingue tiro, movimento e modalidades de recuo; no modo Push pode avançar durante cooldown.
`MicroRules` liga Marines/Marauders a `MicroBio`, que herda essa lógica.

**É OS1/N6 com um exemplo local concreto**, inclusive para a reserva de dano que a pesquisa
anterior propôs como extensão. Nosso [`combat.py`](../../bot/body/behaviors/combat.py) ainda monta
siege/stim e a-move. O RoachRush também faz tiro com arma pronta e movimento durante cooldown,
mas usa heurísticas simples; não é necessário importar seu controlador.

Adaptar o mecanismo através dos behaviors Ares, preservando o objetivo do planner. A reserva do
Sharpy é limpa ao inicializar o micro de grupo, não uma reserva global de todo o exército. O teste
usa `enemy.health`, sem shield, e o bônus de último alvo é alto: copiar literalmente preservaria
essas limitações. Nossa reserva pode ser compartilhada por frame, considerar HP+shield, dano real
e apenas tiros executáveis. Medir troca, overkill e progresso; kite sem avanço também pode perder.

### LL9 — Agrupar durante a marcha, além do ASSEMBLE inicial

[`GroupCombatManager`](../../tools/aiarena_local/runtime/bots/RustyMarines/sharpy/combat/group_combat_manager.py)
forma grupos espaciais e
[`handle_groups`](../../tools/aiarena_local/runtime/bots/RustyMarines/sharpy/combat/default_micro_methods.py)
compara o grupo com o poder total recebido pelo manager. Grupos pequenos em risco podem se mover
para outro grupo; um grupo dominante espalhado pode reagrupar antes do contato.
As regras padrão habilitam regroup e usam parcela 0,75; os números não são recomendação para nós.

**É OS6/N7.1/I1 com execução verificável.** Nós já temos ASSEMBLE/REGROUP e combate por núcleo
local, mas a ofensiva continua pedindo todas as unidades livres. O comprometimento/depleção ainda
usa poder global; reforços podem seguir um destino distante individualmente.

A primeira adaptação é corrigir o compromisso pela concessão real e reunir reforços com destino
e condição de liberação explícitos. O contrato atual aceita tipos/count/poder, mas não seleção por
tags ou região; decidir essa extensão antes de criar outra autoridade de ownership. Depois pode
entrar coesão durante a marcha. Body não deve reclamar unidades fora do que o Engine concedeu.
Medir mortes em trânsito, parcela de poder chegando junta e tempo até a luta.

### LL10 — Atacar a base menos cara de alcançar e vencer

[`PlanZoneAttack._get_target`](../../tools/aiarena_local/runtime/bots/RustyMarines/sharpy/plans/tactics/zone_attack.py)
escolhe entre zonas inimigas por distância do grupo/gather point mais `5 × poder estático`.
Também prioriza proxies perto da nossa main. É um score verificável e simples.

**É N7.4/OS9.** Nosso alvo já permanece estável e prioriza townhalls, mas o ranking é categoria,
distância ao rally e tag; não leva a defesa do destino em conta.
Adaptar valor econômico, defesa, custo de rota e incerteza, conservando estabilidade do alvo.
Não copiar o coeficiente 5 nem o gatilho bruto de atacar a 190 supply.
Medir bases/produção inimiga destruídas por perda própria, tempo de travessia e trocas de alvo.

### LL11 — Reparo e bunker precisam estar operacionais

RustyMarines ativa
[`Repair`](../../tools/aiarena_local/runtime/bots/RustyMarines/sharpy/plans/tactics/terran/repair.py),
[`ManTheBunkers`](../../tools/aiarena_local/runtime/bots/RustyMarines/sharpy/plans/tactics/terran/man_the_bunkers.py)
e `ContinueBuilding` em seu plano. Reparo escolhe por tipo/vida e limita SCVs segundo ameaça;
guarnição encaminha Marine para bunker pronto com vaga.

**É OS4/OS5**, com uma referência Terran que já está em disco. O nosso `Command` não tem reparo
ou guarnição, e construir bunker não basta para obter sua proteção. Adaptar necessidade e
orçamento no Ego, concessão no Engine e ação/liberação no Body. O reparo local usa um contador
por zona, sem reserva robusta por alvo; não é um sistema pronto para copiar inteiro.
Medir bunker operacional, estruturas/unidades salvas, custo de reparo e renda dos SCVs retirados.

### LL12 — Transição e cleanup: aproveitar a intenção, conservar o que já temos

SharpKnives encerra permanentemente o plano de proxy quando `Once(Supply(50))` dispara e passa ao
backup. SharpCannon interrompe a fase de rush com três Probes perdidos ou após quatro minutos,
e continua em macro/Stalkers. São exemplos verificáveis de saída do plano inicial, relacionados
a OS8/N2; não são adaptação geral ao adversário. Nós já temos interrupção emergencial e por
opening parado. O passo adicional seria uma transição econômica viável pelo que existe e pelo
que foi observado, em vez de apenas copiar supply/tempo fixos.

Há uma armadilha no SharpKnives: defesa, gather, ataque e cleanup estão dentro do objeto `proxy`,
que o `Step` inteiro deixa de executar após o latch de supply 50. O objeto `backup` contém macro,
mas não repõe esses atos táticos. Pela leitura do fluxo, essa transição desliga também a condução
tática do plano; não foi medida numa partida. Ao adaptar uma transição, manter os serviços de
combate/defesa fora da etapa descartável. Isso também limita seu valor como referência de late.

Os três incluem
[`PlanFinishEnemy`](../../tools/aiarena_local/runtime/bots/RustyMarines/sharpy/plans/tactics/attack_expansions.py):
unidades ociosas atacam estruturas conhecidas ou uma expansão aleatória. No RustyMarines e no
SharpCannon ele fica depois do ataque numa `SequentialList`, portanto espera esse ato liberar a
sequência. O RoachRush percorre expansões em ciclo quando não encontra estruturas.

**Cleanup já existe aqui:** `MainAttackMission` conserva alvo, procura expansões por idade de
visão e trata estruturas voadoras com atacantes apropriados. Não precisamos adicionar uma
segunda missão para replicar a busca aleatória. Há ainda um defeito no exemplo Sharpy: no loop
de estruturas ele calcula distância de `target`, não de `building`, então não garante a escolha
da estrutura mais próxima. O gargalo de fechamento apontado no debate é executar/progredir,
não ausência dessa busca.

## Ordem sugerida e relação com os documentos existentes

Esta pesquisa reforça o plano do debate; não promove automaticamente um item para staging.

| Ordem | Fatia | Relação com `docs/dev` | Evidência / dependência |
| --- | --- | --- | --- |
| Prévia | Corrigir estabilidade, DEFEND indevido e poder das unidades especiais | Plano unificado, itens 1–4 | Defeitos já registrados; referências de late não os substituem |
| 1 | Micro de bio: foco, cooldown, efeitos; suporte seguro | LL8/LL6 → OS1/OS2, N6 | Fonte Sharpy + behaviors Ares; medir micro em composição fixa |
| 2 | Compromisso pela concessão e reforços em grupo | LL9 → I1, OS6, N7.1 | Fonte Sharpy; extensão de elegibilidade quando necessária |
| 3 | Alvo considerando defesa/rota; scouting recorrente | LL10/LL7 → N7.4, OS3/OS9, N4 | Fonte para alvo; pistas Phantom para Intel; precisa de visão atual |
| 4 | Diagnóstico de gasto maxed, gás por demanda e recursos por base | LL2/LL3 → E5/E9, staging de controle | Changelog Phantom; perceber dados ausentes antes de alterar política |
| 5 | Reposição/transição explícita e upgrades seguindo mix | LL1/LL4 → E8/E9, migration-map | Validar composição e execução dos tipos primeiro |
| Em paralelo à defesa | Reparo mínimo e guarnição | LL11 → OS4/OS5 | Fonte Terran; contratos e orçamento |
| Posterior | Tempo/alcance na previsão de luta; caster novo | LL5/LL6 → N5, OS7/OS10 | Shadow e cenários antes de decidir partidas |

**O que acrescenta ao backlog:** evidência local para reserva de dano e coesão em movimento;
uma comparação explícita entre expansão por contagem e reposição de linhas esgotadas; prioridades
separadas de tech/pesquisa; e decomposição do banco em causas, incluindo supply máximo sem progresso.
**O que já estava previsto:** praticamente todo o restante. Não há evidência para trocar nossa
arquitetura, importar Sharpy ou reescrever a conexão SC2 porque o Phantom deixou o Ares em 3.38.
Proteção básica de workers e speed mining também não seriam novidades: nosso Body já registra
`Mining()`, cujo `keep_safe` é verdadeiro por padrão no Ares local. Uma adaptação adicional precisaria
demonstrar ganho sobre essa execução existente.

Para medir, manter composição/upgrades fixos nos cenários de micro, depois partidas pareadas com
mesmo mapa, oponente, estilo e configuração. Separar partida decidida, interrupção e crash.
Contra o Phantom fixar **pacote e arquivo de dados**, não apenas nome/versão: o `params.json`
contém estado de otimização de três parâmetros (`range_bonus`, `time_distribution_lambda`,
`influence_range_bonus`). Seus 5.452 samples são metadado do otimizador, não uma taxa de vitória
nem evidência de ganho. Não copiar esses valores para nosso modelo, que tem outra escala.

Não incorporar trechos sem conferir a licença do arquivo/projeto de origem: RoachRush inclui MIT;
os pacotes dos três bots Sharpy não trazem uma licença raiz para seu código de bot, e o Phantom
não oferece fonte/licença verificável nesses artefatos. A licença de uma dependência não licencia
automaticamente o bot que a usa. Esta revisão propõe mecanismos, sem incorporar código deles.
