# MapControl

> Onde espera o exército que ninguém está usando?

## Resumo

- O MapControl é o **dono residual** do exército: pede todas as unidades livres com prioridade −1 e as
  mantém (`HOLD`) num ponto, o **anchor**.
- Recebe o que a Defense e a Offense deixaram. Não é uma reserva estratégica.
- O anchor tem dois papéis:
  - é onde o exército livre espera e reage;
  - é o **rally** da Offense: onde o ataque se reúne e para onde recua.
- O anchor é escolhido por um score contínuo (`staging`): o ponto que responde mais rápido a todas as
  nossas bases, um pouco à frente delas, de preferência num choke, longe da influência inimiga.
- Não tem missão: o anchor é um desired state, mantido com histerese.
- Apesar do nome, ele ainda não faz "controle de mapa" no sentido do SC2 (visão, presença, negar
  expansões). Ele escolhe um ponto de espera.

## Entradas e saídas

| | |
| --- | --- |
| Lê | `attention` (nossas bases, `MapView` com a topologia de regiões e passagens), `awareness.influence` (o campo de influência), `awareness.most_threatened` e `intent.posture` |
| Entrega | `MapControlPlan`: `anchor`, `source`, `advance`, `reason`, `fallback`, a escolha do `staging` e uma `Proposal` (`HOLD` no anchor, id e owner `core_army`) |
| Quem usa o anchor | O `main.py` passa `anchor` à Offense como rally |

O id `core_army` é o nome de duas versões atrás (CoreArmy → ArmyFallback → MapControl). Ele foi mantido
porque os logs, o viewer e os benches o conhecem.

## Como decide

O anchor vem da primeira fonte que se aplica:

| Fonte (`source`) | Quando | Onde fica o anchor |
| --- | --- | --- |
| `threatened_base` | Postura DEFEND e alguma base ameaçada | Na posição da base mais ameaçada (o townhall) |
| `staging` | O caso normal | No melhor ponto pelo score abaixo |
| `legacy` | O `staging` não achou candidatos (`fallback` diz por quê) | Rampa da main com uma base só; senão 6 células à frente da base mais avançada, rumo ao start inimigo |

O `staging` é avaliado todo frame, mesmo quando outra fonte põe o anchor, e aparece no log.

### O score do staging

**Candidatos.** Os pontos do lattice das regiões com base nossa e das regiões vizinhas. A região do start
inimigo e as vizinhas dela ficam de fora, a não ser que tenham base nossa: o exército não espera na porta
do inimigo. O ponto de guarda de cada passagem que protege alguma base também é candidato, marcado com a
passagem. Ele fica 4 células (`setback`) da passagem, para o nosso lado.

**Distâncias por terra.** As distâncias usam a topologia: reta dentro de uma região e, entre regiões, de
passagem em passagem, só pelas passagens **abertas**. Uma mineral wall não é atalho. `D` é a distância entre
os dois starts e serve de escala. `E` é o start inimigo.

```text
score = −reaction + choke − exposure
```

- **`reaction`**: o quanto o ponto demora a responder às nossas bases.
  - Para cada base `b`: `r_b = d(p, b) − advance · max(0, d(E, b) − d(E, p))`. É a distância até a base,
    descontada do quanto o ponto está **à frente** dela no caminho do inimigo: o inimigo que vem para `b`
    encontra o exército antes. Atrás da base, conta só a distância.
  - Depois, a média quadrática sobre as bases: `reaction = sqrt(média_b (r_b / D)²)`. Ela fica entre a média
    (que abandonaria uma base afastada) e o pior caso (que arrastaria o exército até ela).
  - Efeito: uma passagem que todos os caminhos até as nossas bases cruzam é boa sem precisar pedir, e o
    ponto avança conforme o território cresce, uma base de cada vez.
- **`choke`**: um bônus no ponto de guarda de uma passagem estreita que protege bases:
  `0,15 · guardadas · exp(−largura / 6)`. `guardadas` é a fração das nossas bases que o start inimigo deixa
  de alcançar com aquela passagem fechada. Uma borda de região sem largura conhecida não ganha nada.
- **`exposure`**: uma penalidade por estar onde o inimigo pode estar. Vem do campo de influência da
  Awareness: `0,3 · threat · (1 − support) + 0,2 · max(0, −control)`. É a ameaça que não contestamos mais
  o quanto o ponto está do lado inimigo do campo. `support` sozinho não dá bônus, porque no anchor ele é o
  próprio exército do anchor e premiá-lo prenderia o exército onde já está.

### O `advance` por postura

O `advance` é o quanto o score valoriza ficar à frente das bases. É a leitura que o MapControl faz da
postura:

| Postura | `advance` | Efeito |
| --- | --- | --- |
| DEFEND, RECOVER | 0 | O ponto só cobre as bases (em DEFEND com base ameaçada, o anchor vai para ela) |
| DEVELOP | 0,7 | Fica à frente das bases, no caminho do inimigo |
| PRESSURE, COMMIT | 0,8 | Fica mais à frente |

### Histerese

- Uma base tomada ou perdida, ou uma troca de `advance`, faz escolher de novo, livremente.
- Fora isso, o ponto mantido só troca quando outro o supera por 0,04 de `D` (`staging_margin`). Na prática,
  só uma mudança do campo de influência move o anchor.
- Toda troca registra o motivo: `initial`, `held_invalid`, `bases_changed`, `posture_changed` ou
  `awareness`.

### Onde o anchor fica nos mapas reais

Medido offline nas topologias reais, com as bases na ordem de distância ao nosso start:

| Bases | Anchor |
| --- | --- |
| 1 | Rampa da main |
| 2 | Choke da natural (Torches, que não tem, fica na rampa) |
| 3 em diante | Sai do choke da natural e avança aos poucos, um hub por vez, para a frente do centro das bases |
| 7 | Entre 0,43 D (Pylon) e 0,63 D (Ley Lines) do start inimigo |

A política anterior (uma passagem só) ficava no choke da natural até a 7ª base e então saltava para perto
do inimigo. A comparação está em [architecture.md](../architecture.md#medições).

## Interação com os outros planners

- **Offense:** usa o anchor como rally. Em `ASSEMBLE` e `REGROUP` a missão não pede unidades, e é o
  MapControl quem junta o exército no anchor.
- **Defense:** pega as unidades de que precisa antes (prioridade maior). As que ela solta voltam ao anchor.
- **Unidades novas:** sem ataque em curso, vão para o anchor. Com ataque em curso, vão direto para o grupo
  da Offense, porque a proposta dela pede todas as livres.

## Estado entre frames

O `StagingPolicy` guarda:

- a tabela de distâncias por terra do mapa (refeita quando uma passagem abre);
- os candidatos do conjunto de bases atual (refeitos quando uma base entra ou sai);
- o ponto mantido, desde quando e o anterior.

As distâncias custam 2 a 4 ms por conjunto de bases. O campo é lido todo frame, com numpy, sobre 300 a 700
pontos.

## Parâmetros (`MapControlConfig`)

| Parâmetro | Valor | Efeito |
| --- | --- | --- |
| `advance` | 0,7 | Peso de ficar à frente das bases em DEVELOP |
| `pressure_advance` | 0,8 | O mesmo em PRESSURE e COMMIT |
| `choke_weight` | 0,15 | Bônus de um choke que guarda todas as bases |
| `width_scale` | 6 | Escala da largura: `exp(−largura / 6)` |
| `setback` | 4 | Distância do ponto de guarda até a passagem |
| `threat_weight` | 0,3 | Peso da ameaça não contestada |
| `control_weight` | 0,2 | Peso de estar do lado inimigo do campo |
| `staging_margin` | 0,04 de D | Vantagem que um ponto novo precisa para trocar |
| `rally_forward` | 6 | Distância à frente da base mais avançada no `legacy` |
| `top_candidates` | 5 | Quantas regiões aparecem no `top[]` do log |

Calibração, feita offline nas topologias reais em 19/09/2026:

- a média quadrática da distância pura, sem o desconto de `advance`, punha 2 bases na rampa da main em 4
  de 5 mapas;
- com `advance` 0,6, Persephone volta para a rampa com 2 bases (o choke da natural ganha só por 0,005 a
  0,017);
- com `advance` 0,8 em DEVELOP, o anchor de 7 bases passa do meio do mapa (Incorporeal 0,35 D, Torches
  0,39 D);
- `choke_weight` é estável entre 0,1 e 0,2; com 0,25, a rampa estreita da main ganha do choke da natural.

## No log

`planner.map_control_planned`, escrito quando o anchor (em grade de 3), a fonte, o motivo ou o ponto mantido
mudam, com heartbeat de 30 s:

- `anchor`, `source`, `reason` (`hold_<staging|rally>_<postura>`), `advance` e `fallback`;
- `staging.switch`: por que o ponto mantido mudou;
- `staging.top[]`: o melhor candidato de cada região, com `reaction`, `choke`, `threat`, `support`,
  `control`, `exposure` e `score`.

Com `--spatial-view` o anchor aparece no jogo; com `--spatial-snapshot`, nos SVGs.

## Limitações conhecidas

Medidas nos logs de `comp-eficacia` e na partida contra o PhantomBot (`logs/game-20261004T032327451475Z`):

- **O exército anda a cada troca de postura.** O anchor mudou de 14 a 39 vezes por jogo, e 7 a 27 dessas
  mudanças foram `posture_changed`: o `advance` é um degrau por postura (0 / 0,7 / 0,8).
- **Decisão pelo ruído do campo, presa pela histerese.** Contra o PhantomBot, aos 2:52 e com 2 bases, um
  pouco de ameaça na natural trouxe o anchor para a rampa da main. A diferença de score entre o choke da
  natural e a rampa é 0,009, e a margem é 0,04. O exército ficou 60 s longe da natural, até a terceira base.
  Recuar pode estar certo quando estamos atrás, mas aqui quem decidiu foi `exposure` ≈ 0,01, e não a razão
  de forças.
- **Em DEFEND, o exército espera no townhall**, não no choke nem na luta (I17 no [gaps.md](../dev/gaps.md)). No
  `comp-eficacia/004`, isso foi 32 % do tempo. O anchor também alterna entre bases com ameaça parecida, e
  entre a base ameaçada e o staging quando a postura entra e sai de DEFEND.
- **Um ponto só** para o exército todo, sem dividir.
- **Todas as bases pesam igual:** a main e a natural não valem mais que uma base nova.
- **Base em construção conta como base** (I4 no [gaps.md](../dev/gaps.md)): os candidatos são recalculados no
  frame em que o SCV põe o CC.
- **Distância reta dentro de uma região**, o que subestima regiões côncavas.
- A exclusão das regiões vizinhas ao start inimigo é uma regra fixa.
- O `pressure_advance` (0,8) nunca foi medido por conta própria.
- Para avaliar mudanças no `exposure` offline, falta logar o campo em todos os candidatos: hoje só o
  `top[]` (o melhor de cada região) traz `threat` e `support`.

## Código

- [bot/ego/planners/map_control/planner.py](../../bot/ego/planners/map_control/planner.py):
  `MapControlPlanner`, `MapControlConfig`, as fontes do anchor e o `advance` por postura.
- [bot/ego/planners/map_control/policies/staging.py](../../bot/ego/planners/map_control/policies/staging.py):
  `Ground` (distâncias por terra), `evaluate` (candidatos), `StagingPolicy` (score e histerese).
- [bot/attention/topology.py](../../bot/attention/topology.py) e
  [bot/awareness/field.py](../../bot/awareness/field.py): a topologia e o campo que ele lê.
