# Bots open source: o que aproveitar no nosso

> Pesquisa de 03/10/2026 sobre o código local em `e647f7d` e o Ares fixado em
> `87308658b0dfe1e59486c2b157ef552e9af0c7fd`. Foram consultados repositórios,
> árvores de arquivos, licenças identificadas pelo GitHub e trechos de código.
> As referências externas abaixo usam commits fixos.
>
> Esta revisão complementa [propostas.md](propostas.md),
> [novas_propostas.md](novas_propostas.md) e
> [melhorias_propostas_eco.md](melhorias_propostas_eco.md). As recomendações são
> hipóteses para implementar e medir; não houve implementação de gameplay,
> execução de bots externos ou partidas durante esta pesquisa.

## Resultado da comparação

Os ganhos mais acessíveis são **micro com os behaviors que já temos no Ares,
scouting depois da abertura e respostas concretas a rush**. Reparo, detecção
móvel e reforços coordenados vêm em seguida. Não há motivo demonstrado para
trocar nossa arquitetura ou adicionar outro framework.

O que os projetos externos fazem serve de referência de implementação, não de
prova de força competitiva. Não foi auditado todo o runtime de cada bot. Quando
a evidência é apenas o README, isso está indicado.

## O que já existe aqui

Esta lista evita propor como novidade o que avançou desde as pesquisas de setembro.

| Capacidade | Evidência local | O que ainda falta para esta pesquisa |
| --- | --- | --- |
| Ataque, assemble, engage, retreat, regroup e busca de estruturas | [MainAttackMission](../../bot/ego/planners/offense/missions/main_attack.py) | Melhor execução de combate e entrada coordenada de reforços |
| BIO e MECH, composição adaptada ao inimigo e produção de emergência | [styles](../../bot/ego/planners/economy/knowledge/styles.py), [composition](../../bot/ego/planners/economy/policies/composition.py) | Aberturas específicas por matchup e reação que compre bunker/reparo |
| Memória e estimativa adaptativa do exército desconhecido | [Awareness](../../bot/awareness/model.py), [enemy_army](../../bot/awareness/enemy_army.py) | Observações recorrentes para corrigir a estimativa durante a partida |
| Leitura de abertura e suspeita/busca de proxy | [OpeningBelief](../../bot/awareness/opening/belief.py), [IntelPlanner](../../bot/ego/planners/intel/planner.py) | Converter diagnóstico em resposta militar/econômica específica |
| Campo, topologia e staging consumindo influência | [staging](../../bot/ego/planners/map_control/policies/staging.py), [topology](../../bot/attention/topology.py) | Usar distância por rotas e valor regional em mais decisões |
| Scan, reserva de energia, turrets e sensor towers | [detection](../../bot/ego/planners/intel/policies/detection.py), [sensor_towers](../../bot/ego/planners/intel/policies/sensor_towers.py) | Detecção móvel acompanhando o exército |
| Stim, decisão de siege e Medivac seguindo o grupo | [combat](../../bot/body/behaviors/combat.py), [attack](../../bot/body/behaviors/attack.py) | Kite, foco local, esquiva de efeitos e proteção aérea do suporte |
| Harness, logs e preparação para adversário externo | [harness](../../harness/), [guia local](../../tools/aiarena_local/README.md) | Medir as mudanças em cenários e contra bots; preparação não comprova partida executada |

## Projetos e implementações consultados

Bots completos e frameworks aparecem separados na coluna de tipo. PiG joga
Protoss nas builds descritas; seus padrões de scouting e micro são transferíveis,
mas suas builds não são aberturas Terran.

| Projeto / revisão | Tipo | Implementação verificada | Como aproveitar |
| --- | --- | --- | --- |
| [PiG Bot](https://github.com/Vers-AI/SC2_PiGBot/tree/aa77634f6b6ea0fe2846488441bb78b55bdde91a) | Bot Python/Ares | [Micro ranged](https://github.com/Vers-AI/SC2_PiGBot/blob/aa77634f6b6ea0fe2846488441bb78b55bdde91a/bot/combat/unit_micro.py), [score de alvo](https://github.com/Vers-AI/SC2_PiGBot/blob/aa77634f6b6ea0fe2846488441bb78b55bdde91a/bot/combat/target_scoring.py), [scouting por informação envelhecida](https://github.com/Vers-AI/SC2_PiGBot/blob/aa77634f6b6ea0fe2846488441bb78b55bdde91a/bot/belief/scout_voi.py) | Referência mais direta para compor nossos behaviors e priorizar observações |
| [MicroMachine](https://github.com/RaphaelRoyerRivard/MicroMachine/tree/eb893161371dab975a0a7e600f9e250ac03ec1ef) | Bot Terran C++ | [Estações de reparo](https://github.com/RaphaelRoyerRivard/MicroMachine/blob/eb893161371dab975a0a7e600f9e250ac03ec1ef/src/RepairStationManager.cpp): validade da base, reserva persistente e escolha por ocupação/distância | Recuperar unidades mecânicas sem mandar todas para uma única base |
| [Ketroc](https://github.com/Ketroc/KetrocBot-for-Starcraft-II/tree/cc797b5ee845b92e818097ce07f8ff6ca438694b) | Bot Terran Java | [SCV repairer](https://github.com/Ketroc/KetrocBot-for-Starcraft-II/blob/cc797b5ee845b92e818097ce07f8ff6ca438694b/src/main/java/com/ketroc/micro/ScvRepairer.java), [Raven Matrix](https://github.com/Ketroc/KetrocBot-for-Starcraft-II/blob/cc797b5ee845b92e818097ce07f8ff6ca438694b/src/main/java/com/ketroc/micro/RavenMatrixer.java), [Hellion harasser](https://github.com/Ketroc/KetrocBot-for-Starcraft-II/blob/cc797b5ee845b92e818097ce07f8ff6ca438694b/src/main/java/com/ketroc/micro/HellionHarasser.java) | Estudar ciclos de suporte, reparo com término e operações pequenas de harass |
| [Sajuuk](https://github.com/Guillaume-Docquier/Sajuuk-SC2/tree/390bb8b77d05ded0385971055f377e5efacc8f15) | Bot C# | [Ameaça regional](https://github.com/Guillaume-Docquier/Sajuuk-SC2/blob/390bb8b77d05ded0385971055f377e5efacc8f15/Sajuuk/GameSense/RegionsEvaluationsTracking/RegionsEvaluations/RegionsThreatEvaluator.cs), [manutenção de visão](https://github.com/Guillaume-Docquier/Sajuuk-SC2/blob/390bb8b77d05ded0385971055f377e5efacc8f15/Sajuuk/Managers/ScoutManagement/ScoutingTasks/MaintainVisibilityScoutingTask.cs) | Transformar topologia e memória em prioridades de cobertura e reação |
| [Sharpy](https://github.com/DrInfy/sharpy-sc2/tree/d9577a00ee47634b56ff7ee0740c6ed3043659a2) | Framework Python | [Step](https://github.com/DrInfy/sharpy-sc2/blob/d9577a00ee47634b56ff7ee0740c6ed3043659a2/sharpy/plans/build_step.py) com requisito/skip/skip_until e [micro de Medivac](https://github.com/DrInfy/sharpy-sc2/blob/d9577a00ee47634b56ff7ee0740c6ed3043659a2/sharpy/combat/terran/micro_medivacs.py) | Etapas condicionais e suporte procurando posição de baixa influência aérea |
| [Sharky](https://github.com/sharknice/Sharky/tree/e4c818ef81cf8dbf79ac716ea00ec4d3dbb850e7) | Framework C# com exemplos | [MicroManager](https://github.com/sharknice/Sharky/blob/e4c818ef81cf8dbf79ac716ea00ec4d3dbb850e7/Sharky/Managers/MicroManager.cs) ordena tarefas, reclama unidades e filtra comandos; [README](https://github.com/sharknice/Sharky/blob/e4c818ef81cf8dbf79ac716ea00ec4d3dbb850e7/README.md) descreve transições de builds | Referência para operações concorrentes e reação de build; nosso Engine já resolve ownership |
| [Ares `8730865`](https://github.com/AresSC2/ares-sc2/tree/87308658b0dfe1e59486c2b157ef552e9af0c7fd) | Framework já usado | [Behaviors individuais](../../ares-sc2/src/ares/behaviors/combat/individual/), [CombatSimManager](../../ares-sc2/src/ares/managers/combat_sim_manager.py), [PathManager](../../ares-sc2/src/ares/managers/path_manager.py) | Reutilização direta no Body; avaliação/simulação deve entrar como dado, mantendo planners sem efeitos |

## Propostas aproveitáveis

Os ids `OS1`–`OS10` identificam esta revisão. **P0** é a primeira leva,
**P1** depende da base dessa leva e **P2** é exploração posterior. Esforço é
relativo: baixo, médio ou alto; não é estimativa de prazo.

### OS1 — Micro ranged: kite, foco e esquiva (P0, médio)

**Referência:** o `micro_ranged_unit` do PiG monta `CombatManeuver` com segurança,
`StutterUnitBack` e `ShootTargetInRange`; o score considera distância, vida,
alcance, ameaça e valor do tipo. Esses behaviors também estão no nosso Ares.

**Aplicação:** começar por Marine/Marauder no
[combat.py](../../bot/body/behaviors/combat.py), compartilhado por ataque e defesa.
Filtrar alvos visíveis, detectados e atingíveis; atirar quando pronto, reposicionar
durante cooldown e manter o destino concedido pelo planner. Usar grid de efeitos
para esquiva: colocar `KeepUnitSafe` sobre toda influência de combate antes de
qualquer tiro pode fazer o exército evitar toda luta. Foco coletivo precisa de
reserva de dano por frame para reduzir overkill; isso é uma extensão proposta
aqui, não uma capacidade confirmada do score do PiG.

**Medir:** recursos perdidos em lutas equivalentes, tempo para eliminar alvos e
progresso até o objetivo. Incluir melee, ranged e splash; kite que só prolonga a
partida sem melhorar a troca não basta.

### OS2 — Sobrevivência no recuo e Medivac seguro (P0, baixo–médio)

**Referência:** Sharpy procura baixa influência aérea perto do centro do grupo
quando o Medivac não pode curar ou não tem alvo útil. Ares já oferece
`MedivacHeal`, `KeepUnitSafe` e pathing em grids separados.

**Aplicação:** em [attack.py](../../bot/body/behaviors/attack.py), curar aliados
e manter suporte fora da ameaça antiaérea. Em
[retreat.py](../../bot/body/behaviors/retreat.py), preservar a saída como prioridade,
com esquiva e, se medido como útil, tiros oportunistas que não atrasem a retirada.
Tanques continuam precisando de unsiege; não aplicar kite genérico a todos os tipos.

**Correção da pesquisa anterior:** `sense_danger=False` não significa ignorar
influência. No Ares fixado, ele pula a otimização que dispensaria a consulta e
chega a `map_data.pathfind(start, target, grid, ...)`. Nosso recuo já passa grids
ground/air. O problema verificável é a ausência de reação de combate e suporte
especializado; a segurança da rota deve ser medida. O fallback do Ares pode
devolver o alvo se não houver path, então também interessa registrar falhas.

**Medir:** perdas durante retreat, taxa de chegada ao rally e sobrevivência de
Medivacs. Esta correção atualiza a interpretação do achado A9 em
[novas_propostas.md](novas_propostas.md).

### OS3 — Scouting recorrente por relevância e idade (P0, médio)

**Referência:** PiG ordena destinos por tempo sem observação × relevância, com
bônus de composição e flag de ativação. Sajuuk possui tarefa de manter visão
de uma área, distribuindo cobertura entre scouts.

**Aplicação:** estender [IntelPlanner](../../bot/ego/planners/intel/planner.py) além
da única missão de abertura. Manter cobertura como desired state; criar episódios
finitos para verificar tech, expansão ou última região do exército. Um score
inicial pode combinar idade da observação, impacto esperado na próxima decisão,
distância de rota e risco. Reaper sobrevivente é candidato antes de sacrificar
SCVs; selecionar atores exige extensão explícita do contrato quando necessário.

**Cuidado ao adaptar:** no PiG, a atualização de `last_army_pos` consultada usa
exército em cache, e destinos podem ser marcados por proximidade de scouts.
Aqui, cache não deve contar como visão nova: atualizar idade apenas com evidência
de observação e registrar cobertura efetiva, coerente com nossa Awareness.

**Medir:** idade da última confirmação de bases/tech/exército, scouts perdidos e
quantas observações mudaram composição, postura ou alvo. Sensor towers não
substituem confirmação visual de tech e composição.

### OS4 — Resposta executável a rush/proxy (P0, médio–alto)

**Referência:** o [README do PiG](https://github.com/Vers-AI/SC2_PiGBot/blob/aa77634f6b6ea0fe2846488441bb78b55bdde91a/README.md)
declara reações a cheese e troca por scouting. A árvore do Ketroc contém
`ProxyBunkerDefense` e `ScvAttackerBunkerDefense`; sua lógica inteira não foi auditada.

**Aplicação:** aproveitar nossa `OpeningBelief` e os incidentes existentes.
Defense pede SCVs com limite e reserva econômica quando a resposta requer
workers; Economy traduz a necessidade em bunker/produção antecipada e posterga
investimentos quando necessário. Reparo e guarnição são executados pelo Body.
Não basta interromper a abertura e voltar à macro genérica. Ampliar planos e
comandos para esses pedidos, pois `Command` hoje não tem reparo nem guarnição.

**Medir:** bases e workers preservados nos primeiros minutos contra rush,
tempo de bunker operacional e custo dos falsos positivos contra macro. A ordem
de resposta deve depender do ataque confirmado e da confiança, não só de um
limiar de suspeita de proxy.

### OS5 — Reparo com orçamento e destino persistente (P1, médio)

**Referência:** MicroMachine distribui unidades entre estações válidas e prefere
bases sem ataque; mantém reserva até morte ou recuperação. O `ScvRepairer` do
Ketroc termina quando ator/alvo morre, alvo fica saudável ou falta recurso.

**Aplicação:** começar reparando bunker/CC crítico e Siege Tank em base segura,
com teto de SCVs e gasto que não bloqueie produção. Planner define necessidade
e alvo; Engine arbitra SCVs; Body executa reparo e libera trabalhadores para
Mining ao terminar. A manutenção pode ser desired state; só criar Mission para
um resgate com começo/fim identificáveis, conforme
[architecture.md](../architecture.md). Reparo exige novos contratos e dados sobre
alvos, não apenas uma chamada de ability isolada.

**Medir:** valor de unidades salvas, gasto de reparo, renda perdida por SCVs
retirados e tempo de retorno ao combate. Estação lotada ou sob ataque não deve
ser destino automático.

### OS6 — Reforços chegando em grupo (P1, médio–alto)

**Referência:** Sharky mostra tarefas habilitadas disputando unidades por
prioridade; é precedente para coordenar operações concorrentes. O protocolo de
reforço proposto aqui é nosso desenho, não uma feature verificada nessa leitura.

**Aplicação:** a ofensiva hoje pede todas as unidades elegíveis livres e novas
unidades podem seguir o alvo distante. Reunir reforços em staging e liberá-los
por lote/condição de encontro. Exige permitir elegibilidade por conjunto de tags
ou região em [Proposal](../../bot/ego/planners/contracts.py), ou desenhar operação
finita própria com prioridade explícita. O
[Engine](../../bot/body/engine.py) já é dono único; não duplicar claiming no Ares.

**Medir:** mortes de unidades isoladas no caminho, tempo do reforço até a luta e
fração do poder chegando junta. Timeout evita esperar indefinidamente por um
lote; Defense deve continuar podendo requisitar unidades urgentes.

### OS7 — Raven como detecção móvel, depois abilities (P1, médio–alto)

**Referência:** Ketroc separa controladores de Raven. `RavenMatrixer` calcula
tempo até ter energia e entrar em alcance, acompanha o alvo e encerra após cast.
Essa implementação também pode avançar em linha direta até o alvo: não é uma
política de aproximação segura para copiar integralmente.

**Aplicação:** primeiro tratar Raven como suporte/detector, com requisito de
produção, orçamento no Economy e acompanhamento protegido no Body. Evitar que
uma unidade sem DPS seja contada como poder ofensivo suficiente. Intel define
necessidade de cobertura; uma ability local posterior escolhe apenas alvos
válidos. Matrix e Auto Turret dependem de dados/abilities do cliente efetivo.

**Medir:** tempo com detecção útil na luta, scans economizados, Ravens perdidos
e unidades ocultas eliminadas. Não comprar spellcaster antes de ter execução
de suporte que o preserve.

### OS8 — Aberturas por matchup e transições justificadas (P1, médio)

**Referência:** Sharpy `Step` separa requisito, execução e condições de skip;
o README de Sharky descreve `Transition`/`CounterTransition` de builds.

**Aplicação:** começar com poucas variantes em
[terran_builds.yml](../../terran_builds.yml), uma abertura normal por matchup e
respostas específicas observáveis. Preservar o Build Runner do Ares e o
handoff para Economy. Styles hoje escolhem BIO/MECH; isso não é seleção completa
por plano adversário. Registrar motivo, pré-condições, etapa abandonada e
estruturas aproveitáveis. Não reinstalar Sharpy para obter sua abstração de etapa.

**Medir:** tempo até primeiro exército útil, stalls, supply block, gastos e
resultado por matchup. Validar o efeito da abertura separado de troca de estilo;
histórico persistente de adversário não é pré-requisito.

### OS9 — Ameaça regional usando distância de rota (P2, médio–alto)

**Referência:** Sajuuk calcula força inimiga normalizada × soma do valor próprio
normalizado dividido por distância de caminho + 1, ignorando regiões inalcançáveis.
Esse é o cálculo consultado em `RegionsThreatEvaluator`, não uma fórmula
universal de combate.

**Aplicação:** aproveitar [topology](../../bot/attention/topology.py) e
[passages](../../bot/attention/passages.py) para diferenciar inimigo próximo por rota
de inimigo próximo em linha reta. MapControl já usa influência e choke: o ganho
a testar é rota/valor em defesa antecipada, expansão e escolha de objetivo.
Awareness publica uma avaliação regional reutilizável; cada planner interpreta
seus custos. Cachear distâncias e recalcular avaliações na cadência necessária.

**Medir:** tempo de resposta a ataques entre bases, escolhas de expansão e perdas
em travessias de chokes, incluindo obstáculos/destructibles e rotas inalcançáveis.

### OS10 — Simulação local como sinal adicional (P2, alto)

**Referência:** o Ares já contém `CombatSimManager.can_win_fight`, com ajuste de
tempo/distância e categorias de resultado. O próprio arquivo fixado relata
erros de interação ground/air e limitações com spellcasters e micro.

**Aplicação:** prototipar em modo de observação: salvar previsão e resultado de
lutas sem alterar decisões. Comparar com nosso poder atual, que já incorpora
splash, armadura e counters em partes do modelo. Não transformar previsão do
simulador em verdade nem usar unidades sob fog como observação confirmada.
Adaptador na percepção integra o runtime Ares e produz resultado imutável;
planner recebe esse dado e mantém fallback, sem importar o bot mutável.

**Medir:** erros de previsão por composição, falsos positivos de vitória,
impacto nos tempos de frame e divergência entre clientes. Só habilitar decisões
após validar cenários ground/air, siege, cura e suporte.

## Ordem recomendada e validação

| Leva | Trabalho | Dependências / critério para avançar |
| --- | --- | --- |
| 1 | OS1 + OS2, em mudanças separadas | Behaviors Ares já disponíveis; demonstrar troca melhor e retirada preservada |
| 2 | OS3 | Contrato de scouts e visão real; demonstrar redução de informação velha |
| 3 | OS4 e reparo mínimo de OS5 | Pedidos de construção, trabalhadores e comandos; sobreviver a rush sem prejudicar macro equivalente |
| 4 | Restante de OS5, OS6, OS7 e OS8 | Ownership e contratos definidos; medir cada mecanismo isoladamente |
| 5 | OS9 e OS10 | Cenários/replays suficientes e orçamento de CPU medido |

Usar cenários de micro com unidades/upgrades fixos e partidas pareadas com mesmo
mapa, matchup, seed, configuração e versão do cliente. Seeds ajudam o harness,
mas não garantem determinismo de um bot externo. Guardar commit, SHA do Ares,
feature ativada, replay, resultado e métricas do mecanismo. Registrar crash,
timeout e partida não jogada separadamente de derrota.

O [harness atual](../../harness/matrix.yml) e o
[bootstrap local](../../tools/aiarena_local/README.md) já existem. Fixar mapa e
estilo nas comparações e repetir células; não inferir ganho de uma vitória.
Preparar métricas ausentes antes de usar esse critério como evidência. A
documentação local registra uma pendência de virtualização; o host não foi
reavaliado nesta pesquisa.

## Reuso de código e itens para depois

PiG, MicroMachine, Sajuuk e Sharpy têm licença MIT identificada nos commits
consultados; Ares também traz MIT no checkout local. Preservar licença e autoria
quando adaptar trechos e verificar separadamente dependências/vendored code.
O GitHub não identificou licença para Ketroc ou Sharky, e não foi encontrada
licença raiz nas árvores consultadas: tratá-los como fonte de ideias e esclarecer
a licença antes de incorporar código. Código público não significa permissão
de redistribuição.

Harass de Hellion é uma referência concreta do Ketroc: tipos de alvos,
trajeto entre bases e controlador especializado. Fica depois das levas acima,
porque precisa de orçamento que não enfraqueça Defense, rota segura e retirada.
Drops ainda adicionam transporte, carga, desembarque e resgate; os behaviors
de cargo do Ares ajudam a execução, mas não definem a missão.

Não há evidência nesta pesquisa para justificar importar um bot inteiro,
adotar aprendizado por reforço ou começar por Ghost/Battlecruiser. A direção
mais sustentada pelas fontes é implementar um mecanismo pequeno, observar seu
efeito e conservar nossa cadeia de decisão explicável.
