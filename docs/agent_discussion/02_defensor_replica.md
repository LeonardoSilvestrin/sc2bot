# Réplica do defensor

Fonte: `docs/agent_discussion/01_critico_abertura.md`. Conferi cada acusação no HEAD (`c7c336d`; o
`harness/outcome.py` foi lido com `git show HEAD:`) e nos JSONL dos benches, com scripts read-only. Não
lancei partidas. Onde o crítico tem razão, concedo sem rodeio. **Várias acusações procedem, e uma delas
derruba um número da minha abertura.**

## 0. Correções à minha abertura

1. **O "4 de 4" estava certo só para as células Rush e Macro; a execução inteira foi 4V 1D.** O
   `comp-eficacia/004` (Zerg RandomBuild, bio) é uma **derrota**: o JSONL fecha com
   `game.ended {"result":"Result.Defeat"}` aos 1.248,9 s. O processo caiu depois do fim, dentro do
   `sc2/client.py:147 save_replay`. O `comp-base/004` repete o padrão: Defeat aos 1.312,3 s. Eu tinha chamado
   esses dois casos de "queda do cliente, a investigar". O certo é **derrota escondida pelo harness**.
2. **O `KeyError: 0` não é "um crash do Ares", e sim um crash do Ares disparado pelo nosso radar** (detalhe em
   A3). Eu o tratei como problema de terceiro.
3. **Retiro o elogio da seção 2.3 da abertura.** A composição contínua é matematicamente correta, mas
   **na prática não se afasta da doutrina** (detalhe em A5). A diferença 4V contra 2V entre `comp-eficacia` e
   `comp-base` não pode ser atribuída a ela.

## 1. Acusação por acusação

### A1. Não há evidência, e o harness esconde derrotas — **procede**

- **(a) Confirmado.** Em `git show HEAD:harness/outcome.py:61-62`, `exit_code ∉ (0, None)` vira `CRASH` antes
  de o `result` ser lido. Nos dois `004`, o `result.json` tem `"result": null`, e o traceback termina em
  `save_replay`. O `summary.json` diz `"defeat": 0` nas duas execuções.
- **(c) A aritmética do crítico está trocada, mas a substância vale.** Contei os `result.json` e os JSONL.
  Desde as posturas há 18 partidas com desfecho: **9V, 6D, 1T e 2 crashes**. As 6 derrotas incluem as 2
  escondidas. Contando crash como derrota, como no ladder, são 9/17, com Wilson de [0,31; 0,74]. É o
  intervalo do crítico, embora ele tenha escrito "9V 6D". Contra Zerg são 15 das 18 (8V 6D 1T), não 16 de
  17. Contra Terran só uma partida foi decidida (`t0/003`); as outras duas são os crashes. Contra Protoss,
  **nenhuma**. Falta ainda somar a derrota para o PhantomBot, que o crítico não contou.
- **O que muda:** a correção do harness passa à frente de tudo. Ela custa horas, e sem ela qualquer bench
  novo mente nas derrotas.

### A2 e (e). DEFEND ignora a cobertura e cancela ataques — **procede**

- **No código:** `threat = 1 − exp(−pressure/4)`. A `cover` é calculada em `awareness/model.py:475-481` e não
  entra na ameaça. Com o gate em 0,55, bastam ~3,2 Marines de pressão.
- **Nos logs (script sobre `strategy.posture_changed` e `awareness.updated`):**

  | Jogo | O que aconteceu |
  | --- | --- |
  | `comp-eficacia/004` | 11 entradas em DEFEND, com pressão de 3,2 a 4,7 contra cobertura de 4 a 49. Aos 966 s: 4,1 contra 49,4. Aos 1.152 s: 3,6 contra 49,1, cancelando um ENGAGE |
  | `004`, ataques encerrados | 5 terminaram por `home_threatened`, 4 deles no ASSEMBLE |
  | `comp-eficacia/001` | Aos 773 s, pressão 3,2 contra cobertura 4,0 cancelou um ENGAGE com `army_position` +0,42 |

- **Nuance que não muda o veredito:** no `004` o bot estava **atrás** em todos os cancelamentos
  (`army_position` de −0,08 a −0,37). Lá o defeito é duplo: o PRESSURE abriu ataques por `power_spike` estando
  atrás (33 dos 36 PRESSURE de `comp-eficacia` foram por `power_spike`), e o DEFEND falso os matou.
- **O que muda:** "DEFEND por ameaça líquida" sobe de 5º para 3º na minha lista. O defeito está medido e a
  correção é pequena.

### A3 e (b). `KeyError: 0` vindo das nossas Sensor Towers — **procede como hipótese forte**

- **A cadeia no código é como o crítico descreve:**
  1. `attention/frame.py:191-192` registra que o Ares guarda blips como inimigo NOTAUNIT com tag 0.
  2. `grid_manager.py:403` só deixa passar unidade não pronta se ela estiver camuflada ou enterrada.
  3. Daí `_handle_generic_unit` → `_type_data` com `unit_type` 0.
- **O dado que faltava (meu script sobre os 16 JSONL do `t0` e dos dois `comp`):**
  - Blips de radar existem em 14 jogos, até 60 ao mesmo tempo contra Zerg, sem nenhum crash.
  - `cloak_seen_at` só aparece em 2 jogos, `t0/004` (842 s) e `t0/005` (738 s). São exatamente os dois que
    caíram, aos 1.106 s e aos 834 s.
  - Nos dois, a última amostra antes do crash tem blips (19 e 2).
  - Correlação perfeita em 16 de 16 ainda não é prova. Falta ler o replay ou um teste com blip enterrado.
    Mas vou além do crítico: isso explica por que nunca caiu contra Zerg. O Lurker enterrado do Zerg não
    marca `is_burrowed`; o `cloak_seen_at` ficou `None` em todos os jogos contra Zerg.
- **Radar sem leitor:** procede. Nada lê `radar_blips` além da telemetria.
- **O que muda:** suspender as torres é a medida de minutos. O filtro de `unit_type == 0` antes do
  `GridManager`, com um teste de regressão, é a de horas. A guarda em `on_step` vem junto.

### A4. Cego a casters, BC e Oracle; Neural Parasite vira "produção de Tank" — **procede**

- **O poder sai de `max(ground_dps, air_dps)`** (`attention/units.py:126-130`). Casters e BC dão 0 (o
  próprio python-sc2 tem o TODO em `sc2/unit.py:221`). O filtro `power > 0` (`awareness/model.py:407,433`)
  os tira do visto e do produzido.
- **Conferi a tag** `4364959746` em `comp-eficacia/003`. Ela está nos nossos grants de 378 a 481 s (HOLD,
  depois ATTACK) e aparece como contato inimigo SIEGETANK aos 490 s. "INFESTOR" tem 0 ocorrências nos 5 logs.
  O "Tank inimigo" aparece em 203, 33 e 319 eventos `economy_planned`: os mesmos números do crítico.
- **O que muda:** "um modelo de poder só" (o `combat.yml` também na Attention, com valor para feitiço) e
  "tag que já foi nossa nunca é produção inimiga" entram como item novo e alto. Somado à ausência de
  qualquer partida decidida contra Protoss, é o maior ponto cego do bot.

### A5 e (d). A composição devolve a doutrina com ruído — **procede**

Meu script sobre 2.690 frames `efficacy` dos 5 jogos de `comp-eficacia`:

- Nenhum tipo fora do estilo entrou na composição.
- Nenhum `add` passou de 1 % dos recursos no mix.
- A distância de variação total à doutrina teve mediana de 0,022 a 0,052 nas vitórias e de 0,108 na derrota.
- O peso mediano da doutrina ficou entre 0,62 e 0,72 nas vitórias.
- No `004`, contra Roach, Lurker e Hydra, o Marine foi de 0,56 para 0,73–0,76. É o viés pró-Marine que o
  autor já tinha registrado.

Defendo ainda que a forma (côncava, contínua, ~1 ms) está certa. Mas o termo que faria o mix andar, alcance
ou supply, não existe. **Proponho modo shadow**: o mix é calculado e registrado, e quem decide é a
doutrina, até um termo físico mostrar efeito em bench. Isso é o que a regra do próprio autor ("reverter o
não medido") manda.

### A6. Não fecha o jogo — **procede**

| Métrica (`comp-eficacia`) | Valor |
| --- | --- |
| Supply ≥ 190 | entre 589 e 774 s |
| Banco de minerais no fim das vitórias | 13.623 a 16.626 |
| Bases ao final | 8 a 10 |

As causas são A2, I1 e o reforço que chega pingando. Concedo também a da expansão sem fim: com
`saturated_at = min(80, 16·bases)`, a partir de 5 bases o bot está sempre "saturado". Eu já tinha admitido
o I1; o banco de 14 mil é a prova de quanto ele custa.

### A7. Micro inexistente — **procede**

São 258 linhas (`attack`, `combat`, `hold`, `retreat`). Eu já tinha concedido. Mantenho o argumento
arquitetural: o conserto é local ao Body. Mas três revisões do autor pediram isso e não foi feito, e isso é
uma escolha de prioridade ruim, não dívida neutra.

### A8. Sinais sem consumidor — **procede**

`risk`, `economy_position`, `balance`, `radar_blips`, `aggression`/`greed`/`tech` e o feedback da
`DefendAreaMission` estão sem leitor. Dois casos merecem atenção:

- O `balance` é exatamente a leitura que corrigiria A2. Está calculado e não é lido.
- O anúncio do estilo no chat entrega informação ao adversário sem ganho nenhum.

Discordo só do remédio "apagar tudo": o `balance` deve ser **ligado**, não apagado.

### A9. O observador reintroduz um prior irrefutável — **procede em parte**

- **Procede:** as bases têm piso por tempo (`enemy_army.py:202-203`) que só cai com townhall morto à vista,
  e os workers só são limitados por baixo. A entrada `u` é, portanto, prior.
- **Procede:** a medição de cobertura usa o `seen`, que é memória com τ = 180 s (`awareness/model.py:311-312`).
  Esse sinal é autocorrelacionado e entra como ruído branco. É um risco real de filtro otimista. Em
  `comp-eficacia/003`, o σ foi de 36,8 para 4,5 em 120 s.
- **Procede:** o `power_drift` ×6 nunca foi medido de novo, e os replays estão no disco.
- **Não procede:** "reintroduz o prior irrefutável". O `A` agora **cai**: aos 720 s de `003` estava em 10,9,
  contra 78–100 do prior antigo, e o COMMIT abre. O piso migrou para as bases, onde pesa menos. Só o
  `replay_truth` diz se o otimismo é real.

### A10. Cortes e histerese contra os próprios princípios — **procede em parte**

- **Procede:** são 37 trocas de postura em 1.249 s no `004` (contei a mesma coisa), a economia é liga/desliga
  por postura e há limiares fixos espalhados.
- **Não procede:** "estilo sorteado é ruído". O sorteio usa como seed o hash do oponente (`main.py:252-256`),
  então é fixo por adversário no ladder, e os benches forçaram `--armies`.
- **Discordo de "duas camadas matemáticas ignorando o `propostas.md:49-50`".** O observador consertou um
  defeito de decisão medido (COMMIT nunca abria). A composição, concedo, foi a camada a mais.

### A11. Docs que contradizem o HEAD — **procede**

| Onde | Problema |
| --- | --- |
| `architecture.md:270-279`, `:512`, `:553`, `:561` | Descrevem uma `ScoutMission`/`scout.py` que não existe; só existe `early_scout.py` |
| `architecture.md:740` | Diz que nenhuma decisão consome topologia e campo, mas o staging consome |
| `README.md` no HEAD | Vende "catálogo validado de counters" (linha 14) e "política por domínio" (linha 67) |

Para um documento declarado normativo, é grave. O `:833` é uma medição histórica, e lá o nome antigo da
postura é tolerável.

### A12. Remendos sobre o Ares — **procede**

Conferi: 127 `tank_stuck`, 11 `blocker_selected` (9 %) e 64 `no_blocker`. A relocation quase nunca resolve.
Ou se ataca a causa (placement com corredores), ou ela sai.

## 2. O que sobra da minha defesa

1. **A arquitetura facilitou cada achado do crítico.** As fronteiras e a telemetria tornaram cada acusação
   verificável em minutos: o DEFEND, o Neural Parasite, os blips e a derrota escondida estão todos nos JSONL
   porque o bot registra `reason` e `inputs` por decisão.
2. **Cada conserto acima é local:** harness, um filtro antes do Ares, um termo de cobertura na ameaça, o
   modelo de poder na Attention e os behaviors do Body.
3. **O observador corrigiu um defeito real de decisão.** No `t0` não havia COMMIT; nos `comp`, há.
4. **O problema não é a planta, é a ordem das prioridades.** Matemática entrou enquanto I1, I3 e N8
   esperavam. Isso o crítico provou, e eu concedo.

## 3. Lista de melhorias revisada

| # | Melhoria | Custo | Mudou porque |
| --- | --- | --- | --- |
| 1 | **Harness honesto:** com `exit_code ≠ 0`, ler o `game.ended` do JSONL; resumir de novo todos os benches | Horas | (a): duas derrotas escondidas |
| 2 | **Sobreviver no ladder:** suspender as Sensor Towers já; filtrar `unit_type == 0` e `is_blip` antes do `GridManager`, com teste de regressão (blip enterrado); `try/except` em `play_frame` com fallback para só macro do Ares | Minutos + horas | (b): 2/2 crashes com radar e camuflado |
| 3 | **DEFEND por ameaça líquida:** ligar o `balance`/`cover`; a Strategy lê o déficit da Defense (C6); nunca cancelar IMEDIATO um ENGAGE com a casa coberta | 1 dia + bench | (e): 49 de cobertura contra 3,6 de pressão |
| 4 | **Um modelo de poder só** (`combat.yml` na Attention, valor de feitiço para casters, BC e Carrier); tag que já foi nossa nunca é produção inimiga | 1 dia | A4: Protoss e casters invisíveis |
| 5 | **Bench de verdade** com 1–4 prontos: 3 seeds × 3 raças × 2 mapas, **Protoss incluído**, mais 2 bots de ladder pelo `aiarena_local` e `replay_truth` para o NEES | Uma noite de máquina | Nenhuma partida decidida contra Protoss |
| 6 | **Micro com os behaviors do Ares** (`ShootTargetInRange`, `StutterUnitBack`, `KeepUnitSafe`, Medivac) | 2–4 dias | Sem mudança |
| 7 | **I1 + reforços agrupados + PRESSURE não abre atrás** (`power_spike` só com `army_position ≥ 0`) | 1–2 dias | A6, e o `004` |
| 8 | **Composição em shadow** até um termo físico (alcance ou supply) mostrar efeito; ligar ou apagar `risk`, `economy_position` e `aggression`/`greed`/`tech`; parar de anunciar o estilo no chat | Horas | (d), A8 |
| 9 | **Docs:** `architecture.md` sem a `ScoutMission`, `:740` corrigido, README do HEAD sem catálogo nem política por domínio; notas de estado no `gaps.md` | Horas | A11 |
| 10 | Observador com workers e bases como medição; lei de gasto contínua | Alto | Rebaixado: só depois de 1–5 |
