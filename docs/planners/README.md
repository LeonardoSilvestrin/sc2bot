# Planners

Um documento por planner do Ego, e um para cada vizinho deles que não é planner (Strategy e Economy): o que
ele decide, como decide e o que ainda falta. Todos descrevem o código do HEAD. O que está em andamento fica em [staging/](../dev/staging/README.md), e as regras gerais
(papéis, contratos, missões, eventos) ficam em [architecture.md](../architecture.md).

| Documento | Pergunta que responde | Pede unidades ao Engine? |
| --- | --- | --- |
| [Strategy](strategy.md) | Como está a partida, e o que o bot quer agora? (não é planner: é o contexto que todos leem) | Não |
| [Defense](defense.md) | Quem está atacando uma base nossa, e quanto exército mandar? | Sim, prioridade > 0 |
| [Offense](offense.md) | Atacar agora? E, durante o ataque, avançar, lutar ou recuar? | Sim, prioridade 0 |
| [MapControl](map-control.md) | Onde espera o exército que ninguém está usando? | Sim, prioridade −1 |
| [Intel](intel.md) | O que precisamos ver, e com o quê (scout, scan, torre)? | Só um SCV |
| [Economy](economy.md) | O que comprar: workers, bases, gás, produção e qual exército? (não é planner: decide o que passa a existir, em `bot/ego/economy/`) | Não (plano direto) |
| [StructureControl](structure-control.md) | O que nossas estruturas fazem sozinhas (depots, tirar estrutura do caminho)? | Não (plano direto) |

Cada documento tem as mesmas seções: **Resumo**, **Entradas e saídas**, **Como decide**, **Estado entre
frames**, **Parâmetros**, **No log**, **Limitações conhecidas** e **Código**.

## O frame, em ordem

Todo frame passa pelas camadas na mesma ordem ([main.py](../../bot/main.py), `play_frame`). Nenhum planner
chama outro: o que um passa para o outro vai pelo frame.

```text
Attention ──▶ Awareness ──▶ Strategy ──▶ StrategicIntent (postura + avaliação)
 (o que vejo)  (o que acredito)              │  lida por todos os planners
                                             ▼
   Defense ─┐   MapControl ──anchor──▶ Offense ─┐   Intel ─┐    Economy   StructureControl
            │        │                          │          │       │              │
            └────────┴──── Proposals ───────────┴──────────┘       │              │
                               ▼                                   │  planos diretos
                            Engine ──▶ Grants ──▶ Behaviors ◀──────┴──────────────┘
                               │                     │
                               └── feedback ─────────┘  (lido pelos planners no frame seguinte)
```

- **Proposal**: um pedido de unidades ("quero poder 12 em Marines, que atire no ar, no ponto P, com
  ATTACK"). Não nomeia unidades.
- **Engine** ([engine.py](../../bot/body/engine.py)): ordena as propostas por prioridade e dá cada unidade
  de exército a no máximo uma. Entre as candidatas, primeiro as que a proposta já tinha, depois as mais
  próximas. Devolve um **Grant** por proposta, com `status` `FULL`, `PARTIAL` ou `REJECTED`.
- **Feedback**: os grants de um frame são lidos pelos planners no frame seguinte. Não há laço dentro do
  frame.
- **Plano direto**: Economy, StructureControl e a parte de detecção do Intel não pedem unidades. Eles
  entregam um plano que os behaviors executam (pelo Ares, na maior parte).

## Quem pede o quê

| Quem | Pede | Prioridade | Comando |
| --- | --- | --- | --- |
| Defense | poder suficiente para cada incidente, separado em ar e terra | `ameaça · (0,5 + 0,5·defense)`, entre 0 e 1 | `ATTACK` |
| Offense | todas as unidades livres | 0 | `ATTACK` ou `RETREAT` |
| MapControl | todas as unidades livres (o que sobrou) | −1 | `HOLD` |
| Intel | 1 SCV (só workers; não disputa exército) | 0,5 a 1,0, pela fase do scout | `SCOUT` |

Na prática: a Defense pega o que o incidente precisa, a Offense pega o resto quando há ataque, e o
MapControl fica com o que ninguém pediu.

## A postura em cada planner

A Strategy escolhe uma postura e todos leem a mesma. O que ela significa em cada domínio é decisão do
planner (a tabela vem do código de cada um):

| Postura | Economy | Offense | MapControl | Intel | Defense |
| --- | --- | --- | --- | --- | --- |
| DEFEND | tudo em exército: sem upgrades, add-ons nem expansão; em emergência interrompe a abertura e liga o SURVIVE | não abre; cancela o ataque **na hora** | anchor na base mais ameaçada | nenhum scout sai; Orbitais guardam scan | margem 2,0 |
| RECOVER | sem expansão; upgrades e add-ons seguem | não abre; cancela **com retirada** | `advance` 0 (só cobre as bases) | foco em economia | margem 1,5 |
| DEVELOP | expande quando satura | não abre; ataque em curso segue até o próximo reagrupamento | `advance` 0,7 | foco em economia | margem 1,5 |
| PRESSURE | expande quando satura; teto de produção 5 por base | abre ataque | `advance` 0,8 | Orbitais guardam scan | margem 1,5 |
| COMMIT | sem expansão; teto 5 por base | abre ataque sem esperar o cooldown | `advance` 0,8 | Orbitais guardam scan | margem 1,5 |

## Termos que aparecem em todos

- **Poder** (em Marines): `sqrt(dps · alvos · vida)` de uma unidade, dividido pelo de um Marine. Um Marine
  vale 1; um Siege Tank em siege com vida cheia vale cerca de 4,3. Somar poderes é a lei quadrática de
  Lanchester: dobrar o número de unidades dobra o poder somado.
- **Postura**: o que o bot quer agora (DEFEND, RECOVER, DEVELOP, PRESSURE, COMMIT). Ver
  [strategy.md](strategy.md).
- **Incidente**: um grupo de inimigos ao alcance de alguma base nossa, montado pela Awareness. Ver
  [defense.md](defense.md).
- **Anchor**: o ponto onde o exército livre espera e onde a ofensiva se reúne. Ver
  [map-control.md](map-control.md).
- **Missão**: uma operação com começo e fim (um ataque, a defesa de um incidente, o scout inicial). Tem
  fases próprias e termina `COMPLETED`, `FAILED` ou `CANCELLED`. Planner sem operação episódica não tem
  missão (MapControl, Economy, StructureControl).
- **Desired state**: uma condição que o planner mantém continuamente (o anchor, a barreira de radar, os
  depots). Se deixa de valer, é pedida de novo, sem abrir missão.
