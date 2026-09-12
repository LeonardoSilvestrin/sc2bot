# Awareness hardening

Esta auditoria trata Awareness como uma descrição do mundo: o que foi
observado, o que ainda é acreditado e quanto essa crença é confiável. Nenhuma
decisão, oportunidade ou preferência estratégica foi adicionada.

## Semântica de confidence

`confidence` sempre descreve a qualidade/atualidade da evidência e nunca o
valor do objeto medido. Valor e confiança permanecem separados: uma força ou
base antiga conserva o último valor conhecido, enquanto sua confiança decai.

- Uma observação visível agora tem confiança `1`.
- Uma observação antiga perde confiança conforme a regra específica do seu
  conceito.
- Ausência de uma fonte conhecida, sem observação do local, tem confiança `0`.
  Portanto `enemy_threat == 0` não significa ameaça conhecida como zero.
- Todo confidence produzido por Awareness pertence a `[0, 1]`.
- Confidence territorial mede quanto se sabe sobre o lado inimigo do ponto. O
  lado friendly é observado diretamente.
- Uma fonte inimiga lembrada só aumenta confidence onde sua influência é
  material. Fora desse alcance, o campo permanece desconhecido.

Antes do hardening, `force_influence()` devolvia confidence `1` quando nenhuma
força alcançava o ponto. Isso fazia um campo sem qualquer inimigo conhecido
parecer conhecido e seguro. Agora o mesmo caso devolve `0`.

## Unknown versus empty

`UNCONTROLLED` continua significando que nenhuma influência material domina o
ponto; não significa que o ponto foi recentemente inspecionado. Assim:

| Leitura | Controle | Confidence |
| --- | --- | --- |
| ponto visível, sem presença | `UNCONTROLLED` | `1` |
| ponto nunca visto, sem fontes | `UNCONTROLLED` | `0` |
| ponto não visível, fonte lembrada | derivado das influências | limitada pela fonte |
| fonte esquecida (`confidence == 0`) | não fornece influência atual | `0` sem outra evidência |

Uma lista vazia de slots de expansão também não sustenta uma estimativa segura
de zero bases. `EnemyEconomyKnowledge.bases.confidence` agora é `0` quando não
há slots observáveis, mesmo que o helper agregado de coverage mantenha seu
fallback histórico para compatibilidade.

## Aging da informação inimiga

As diferenças são intencionais:

- Localizações genéricas: decay linear até zero em 90 s por padrão.
- Status de base inimiga: decay linear desde a última inspeção do slot até
  zero em 120 s por padrão. `CONFIRMED` pode permanecer como último valor
  conhecido, mas sua influência é multiplicada pela confidence.
- Defensores de base: unidades móveis decaem em 30 s; estruturas, em 180 s.
  Uma leitura de nenhum defensor vale apenas tanto quanto a última inspeção do
  próprio slot.
- Forças inimigas: decay linear até zero em 30 s. Ao envelhecer, a força fica
  simultaneamente mais fraca como evidência e espacialmente mais incerta, até
  o limite de 30 tiles. Clusters com confidence zero não são escolhidos como
  `main_force` nem retornados por `near()`, embora o último valor conhecido
  possa permanecer exposto até Ares expirar a memória do tag.
- Crenças agregadas de exército/economia: evidência individual usa constantes
  exponenciais próprias e o estado agregado esquece em 90 s. Isso evita fazer
  uma força localizada e uma estimativa macro obedecerem à mesma fórmula sem
  justificativa.

Se o primeiro frame recebido já contém uma unidade marcada como memória, o
runtime não sabe quando ela foi vista. `EnemySighting.last_seen_known` registra
essa diferença. A unidade não recebe confiança fresca, não informa a crença
agregada e forma apenas um cluster com confidence zero. Se depois ficar
visível, o timestamp passa a ser conhecido normalmente.

## Invariantes de Territory

Os caminhos de derivação garantem:

- `friendly_influence`, `enemy_influence`, presença militar, presença ground e
  confidence em `[0, 1]`;
- `dominance` em `[-1, 1]`, inclusive para entradas adversas de helpers;
- presença desprezível continua `UNCONTROLLED`, independentemente de artefatos
  da divisão normalizada;
- classificação determinística, com hysteresis de `0.05` nos limiares já
  existentes;
- baixa confidence eleva o domínio necessário para nomear um lado;
- bases geram presença territorial, mas não ground hold;
- unidades friendly sem ataque ground geram presença militar geral, mas não
  ground denial;
- forças enemy sem ataque ground geram presença territorial geral, mas não se
  tornam origem de ground access;
- `ground_access` e `ground_security` ficam em `[0, 1]`, e entradas do helper
  topológico são limitadas antes da propagação;
- ausência de uma origem inimiga resolvida não fabrica segurança perfeita: as
  regiões assumem exposição total enquanto a topologia de origem é desconhecida.

`hold` agora usa domínio exclusivamente ground: friendly ground denial contra
enemy ground military. `enemy_ground_presence` é separado porque uma base
inimiga pode produzir uma força terrestre e portanto iniciar acesso, mas sua
infraestrutura não é uma unidade defendendo a passagem.

## Ground security

Ground access é a melhor rota de uma origem inimiga até cada região. Regiões
não bloqueiam a si mesmas; passagens são as barreiras. Uma rota alternativa
aberta limita a segurança da região de destino.

A influência suave de uma única força pode alcançar várias passagens. Antes,
cada amostra era multiplicada como se fosse uma linha defensiva independente.
Agora cada força friendly é atribuída à passagem ground que ela segura mais
fortemente; outras passagens alcançadas pela mesma força não voltam a cobrar o
mesmo bloqueio. Forças distintas em passagens sucessivas continuam compondo
barreiras distintas. A leitura `layered_ground_access` permanece como shadow
do modelo anterior, sem uso decisório.

Air security não foi criada.

## Estabilidade, cadence e cache

- Observações do lattice são registradas todo frame, inclusive em frames nos
  quais Territory reutiliza o snapshot.
- Influence, classificação, frontline e access são atualizados na cadence de
  Territory (1 s por padrão).
- Hysteresis existente reduz flips junto aos limiares de presença e domínio.
- Topologia estática é reconstruída somente quando pontos, regiões, passagens,
  origens, spacing ou o centro usado pelo placeholder mudam.
- O campo espacial mantém caches separados para topologia/chokes, bases,
  rotas e ameaça. Entradas iguais não recompõem o campo fora da cadence.
- O placeholder espacial e a topologia territorial agora acompanham uma
  mudança de `map.center` enquanto ainda não existem pontos pathable; antes,
  podiam conservar o centro de outro mapa.
- A atribuição de barreiras percorre `forças x passagens`; a propagação de
  acesso continua `O((V + E) log V)` sobre o pequeno grafo de regiões.

Não foi encontrada recomputação pesada adicional que justificasse mudar a
arquitetura ou introduzir dependências.

## Problemas fora da allowlist

O adapter expõe `UnitSnapshot.visible_now`, mas não a idade/timestamp da memória
de Ares. Evidência: `AresWorldObserver.world_facts()` converte `is_memory` em
`visible_now=False`, descartando `Unit.age`; se Awareness inicia enquanto o tag
já está na memória, não há como reconstruir seu último instante observado.

Arquivos que precisariam mudar para uma correção completa:

- `bot/adapters/ares/world_observer.py`
- `bot/world/attention/facts/unit_facts.py`

Correção recomendada: transportar no `UnitSnapshot` um
`last_observed_at: float | None` derivado do timestamp/idade da snapshot de
Ares, e fazer `EnemyKnowledge` consumir esse valor. Nesta branch foi aplicado
o fallback conservador dentro de Awareness: timestamp desconhecido nunca é
tratado como observação fresca.

`BaseSecurityLevel.SAFE` continua sendo telemetria instantânea de "nenhuma
ameaça visível perto da base", sem confidence. Consumidores não devem
interpretá-lo como prova de área observada/segura; a exposição topológica está
em `territory.*.ground_security`. Alterar esse contrato exigiria mudanças em
consumidores fora da allowlist e não foi feito aqui.

A suíte completa também revela uma inconsistência preexistente fora do escopo:
`tests/test_run.py::test_vscode_exposes_the_supported_launcher_modes` espera
seis launchers, mas `.vscode/launch.json` contém ainda `abrir worktree de
agente`. Nem o teste nem o arquivo de editor pertencem à allowlist desta tarefa.

O lint completo também encontra um `E501` preexistente em
`tests/test_build_config.py:66`. Esse teste não pertence à allowlist; o lint
restrito aos arquivos desta entrega passa sem ocorrências.
