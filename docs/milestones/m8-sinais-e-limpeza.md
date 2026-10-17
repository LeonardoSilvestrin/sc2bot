# M8 — Sinais, topologia e limpeza

↑ [Marcos](README_MILESTONES.md)

**Objetivo:** todo sinal calculado tem leitor, nada degrada em silêncio, e o código não carrega nomes, dados e
fallbacks mortos.

**Critério de saída:** todo campo do `StrategicIntent` com leitor fora dos logs; a degradação da topologia
aparece no log e num teste. A limpeza não tem critério: vai de uma vez, quando der.

**Depende de:** nada; nenhum item muda decisão de jogo. O anchor `legacy` espera o bench do
[M2](m2-medicao.md).

## Strategy e sinais sem leitor

**Ligar ou apagar** [D10, C5, N3.3, A4] — `risk` e `economy_position` só vão para o log; `greed` e `tech` da
`OpeningBelief` não têm leitor (`aggression` e `proxy` já têm: rush e Intel). Todo campo do `StrategicIntent`
deveria ter um leitor fora dos logs.

**Campo calculado inteiro todo frame** [C1, A5] — o MapControl lê o campo só nos seus candidatos, mas o
`InfluenceField` inteiro é recalculado todo frame.

## MapControl e topologia

**Anchor `legacy`** [F1] — o rally antigo continua como terceira fonte do anchor quando o staging não acha
candidatas. Depois que o staging for medido num bench, sai ou vira um caso raro com alerta.

**Topologia que degrada em silêncio** [F2] — sem o MapAnalyzer, as regiões viram componentes caminháveis, o
MapControl cai no `legacy` e a rota do scout vira só o start, sem erro. Direção: uma razão de degradação em
`map.topology_built` e um teste que falhe quando o MapAnalyzer não responde num mapa do pool.

## Limpeza

Não mudam decisão; de uma vez, quando der. Só o `core_army` foi reconferido em 17/10.

- **Nomes legados:** o MapControl ainda propõe com id e owner `core_army` [L1], que o viewer e o overlay conhecem;
  renomear pede `SCHEMA_VERSION` novo. Eventos `behavior.*` escritos por planners [L2].
- **Dados e arquivos mortos:** counters de unidades que nenhum estilo constrói [L5]; o `[template]_builds.yml` do
  Ares e chaves sem efeito no `terran_builds.yml` [L6]; comentários que descrevem código que não existe [L4, L7].
- **Calculado só para o log:** leituras por base, agregados da Awareness e campos da Attention sem leitor [C2–C4],
  `MissionView`/`Frame` [C7], prioridade do scout [C9], plano de economia montado durante a abertura [C11],
  telemetria inteira rodando no ladder para um `NullLogger` [C12], helpers só chamados por testes [C13].
- **Fallbacks silenciosos:** rampa da main [F3], defaults da percepção numa exceção do mediator [F4], tipo fora do
  modelo de alcance [F6], defaults duplicados nos contratos [F8], `run.py` sem `MyBotRace` [F9], local da turret
  recalculado [F10].

## Pesquisa

- **Território e frente** e **Utilidade de missões** no
  [migration-map](pesquisa/migration-map.md#território-e-frente).
