# M6 — Intel

↑ [Marcos](README_MILESTONES.md)

**Objetivo:** informação de meio de jogo, em vez de só o scout inicial e o que o exército encontra.

**Critério de saída:** a fixar quando o marco começar. A direção sugere a idade das perguntas abertas (tech
desconhecido, terceira não vista) como medida.

**Depende de:** [M2](m2-medicao.md). O [M7](m7-economia.md) depende deste: a troca de abertura precisa da
informação.

## Itens

**Informação de meio de jogo** [P1.1, N4, A11] — depois do scout inicial, o bot só vê o que o exército encontra,
fora a busca de proxy, os scans contra cloak e as Sensor Towers. Direção: o Reaper da abertura como sensor, scan
quando uma pergunta envelhece (tech desconhecido há 90 s, terceira não vista), e um Marine de vigia nos caminhos de
ataque, como `HOLD` de `count=1`. Primeiro consumidor: a troca de abertura ([M7](m7-economia.md)).

**Scan contado antes de acontecer** [I11] (baixa) — o planner registra o scan ao planejá-lo e não lê o
`DetectionReport.scanned_by`; se o Body não escanear, a área conta como coberta.

## Pesquisa

- **OS3 — scouting recorrente por relevância e idade**
  ([bots-opensource](pesquisa/bots-opensource.md#os3--scouting-recorrente-por-relevância-e-idade-p0-médio)).
- **LL7 — informação sobre expansão e defesa deve continuar chegando**
  ([ladder-local](pesquisa/ladder-local.md#ll7--informação-sobre-expansão-e-defesa-deve-continuar-chegando)).
- **Cobertura de scouting** no [migration-map](pesquisa/migration-map.md#cobertura-de-scouting).
