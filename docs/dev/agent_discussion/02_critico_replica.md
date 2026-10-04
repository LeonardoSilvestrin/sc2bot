# Réplica do crítico

Escrita sobre o HEAD `c7c336d`. Cada ponto da abertura do defensor foi conferido no código, no `ares-sc2/`, nos
`result.json`/`stdout.txt`/`game.jsonl` dos benches e no `git diff 9457a4a e647f7d`, com scripts read-only.
Nenhuma partida foi lançada. Arquivos que a outra sessão modificou foram lidos com `git show HEAD:`.

## 0. Correções da minha abertura

Começo pelo que errei, porque o erro principal era meu.

- **"O harness esconde uma derrota" — retiro.** As duas execuções rodaram em paralelo. O `004` de `comp-base`
  terminou às 23:21:48 de relógio, aos 1.312 s de jogo, e o de `comp-eficacia` às 23:21:43, aos 1.249 s. São
  cinco segundos de diferença no relógio e tempos de jogo diferentes. Depois disso, todo lançamento morreu em
  cerca de 11 s, com `0x40010004` e `0xC000026B`. Era a sessão sendo encerrada.
  - Aos 1.248 s, `comp-eficacia/004` tinha 200/200, 7 bases, 123 estruturas e 0 inimigos à vista. Ninguém perde
    um jogo assim.
  - O `Result.Defeat` do `game.ended` é o cliente saindo da partida. O `crash` do harness estava **certo**, e o
    meu "4–1" estava errado: são 4V e 1 jogo interrompido.
- **Placar da planta atual.** São 9V 4D 2T em 15 jogos decididos (Wilson 0,36–0,80), e não 9V 6D em 17.
  - O `004` deixa de ser "o jogo perdido".
  - O que medi nele continua sendo comportamento real dos 1.249 s jogados: 32 % do tempo em DEFEND, gatilhos com
    cobertura de 20 a 49, e o Marine subindo para 0,72 contra Lurker.
- **Testes.** São 602, não 486. Eu contei as funções `def test_`, sem as parametrizações.
- **"Nenhuma partida contra bot de ladder."** No HEAD isso é verdade: o `PHANTOMBOT.md` diz "Nenhuma partida
  contra o PhantomBot foi jogada". O working tree da outra sessão já registra uma: **derrota aos 10min50s** em
  Persephone. Volto a esse dado no ponto 6.

## 1. Os pontos em que divergimos

**(a) "4V com COMMIT nos 4, e DEFEND caindo de 42–45 % para 4–10 %."**
Veredito: **procede em parte.**

- Os números conferem. No meu script: `army_position` máximo de 0,68 a 0,75, COMMIT nos 4 jogos e DEFEND de 4 a
  10 %. Contra a minha tese da derrota escondida (que retirei acima), a dele fica de pé.
- Para o `t0` ser comparado com justiça, recortei os primeiros 1.250 s. O DEFEND do `t0` fica em 39 % e 35 %, e
  a diferença continua grande. **Concedo que o comportamento mudou.**
- O que não procede é atribuir essa queda ao observador:
  - `strategy.py` é idêntico entre `9457a4a` e `e647f7d`.
  - O `model.py` não mexeu em `full_pressure` nem em `_base_threat`.
  - O DEFEND lê `threat_level`, ou seja, a pressão de contatos (`model.py:488`), e não lê o filtro.
  - Logo, a queda do DEFEND é **trajetória**: um inimigo que gasta o exército em lutas que agora o bot procura.
    Isso é plausível, mas não é mecanismo. O alarme continua o mesmo, como mostram os 3,6 de pressão contra 49 de
    cobertura aos 1.152 s, ou o ENGAGE cancelado com +0,40 em `comp-eficacia/001`.
- **Impacto nas prioridades:** nenhum. O DEFEND por déficit continua necessário.

**(b) "9 dos 10 crashes por execução são interrupção, não falha do bot."**
Veredito: **procede**, e com a correção acima são 10 de 10.

- O "a décima merece investigação" fica fechado: é a mesma interrupção, no mesmo instante de relógio nas duas
  execuções, e não algo da célula.
- A consequência continua sendo minha: **a planta atual tem zero partidas contra Protoss e contra Terran.** Os
  números de 2.2 são de 4 células, todas Zerg, todas Torches, seed 1. O teste exato de Fisher, de 4/4 contra 0/2,
  dá p = 1/15 ≈ 0,067.
- Resta um bug pequeno: o JSONL grava `Result.Defeat` para um cliente que foi morto. Isso me enganou e vai
  enganar o próximo leitor.

**(c) `KeyError: 0`: Ares ou as torres?**
Veredito: **os dois, e eu considero o assunto fechado no código.**

- O bug é do Ares:
  - O `_prepare_units` dele (`ares main.py:194-292`) **não filtra blips**. Não há nenhum `is_blip` em
    `ares-sc2/src`.
  - O python-sc2 desvia os blips para `self.blips` (`bot_ai_internal.py:766-767`).
  - No Ares, toda unidade de aliança 4 vira inimigo com `UnitTypeId(unit_type)` (`main.py:267-281`). O
    `_should_add_unit` só filtra Adept Shade (`:876-885`).
  - Unidade real nunca tem `unit_type` 0. Um blip vira `NOTAUNIT`, e o `game_data.units[0]` levanta exatamente
    o `KeyError: 0` do traceback (`grid_manager.py:223 → 405 → 724 → 810`). O `frame.py:191-192` do próprio bot
    descreve esse arquivamento.
- O gatilho é do bot. Na última amostra antes de cada crash havia blips:
  - em `t0/004`, 19 blips aos 1.101 s, e o crash veio aos 1.106 s;
  - em `t0/005`, 2 blips aos 832 s, e o crash veio aos 834 s.
- Sem Sensor Tower não existe blip. As torres não têm nenhum consumidor.
- A única peça que não verifiquei é qual campo do blip abre a guarda de `grid_manager.py:403` (pronto,
  camuflado ou enterrado). Ela explica por que só Terran derruba o bot: há 451 e 177 menções a Ghost e 1.216 e
  747 a Widow Mine nos dois logs.
- **Impacto nas prioridades:** isto sobe para o 1º lugar, e a correção cabe em uma linha.
- A proposta 6 do defensor, usar `radar_blips` como medição, **piora** a situação enquanto o Ares não filtrar
  blips.

**(d) "t0 → comp-base → comp-eficacia é uma progressão monotônica."**
Veredito: **não procede como evidência causal.**

- A tabela escolhe as células. Ela deixa de fora a RandomBuild, em que:
  - o `t0`, com o prior antigo, **venceu** aos 1.303 s;
  - `comp-eficacia/004`, com o observador, nunca se achou à frente (`army_position` máximo de 0,00, nenhum
    COMMIT, 32 % em DEFEND) até ser interrompido aos 1.249 s.
- `comp-base` contra `comp-eficacia` isola a composição, e não o observador.
- O próprio autor escreve que "trajetórias divergem cedo" (`architecture.md:812`).
- A crença de fato mudou, e eu concedo isso. Mas "o observador fez o bot vencer" não sai de n = 2 contra n = 4.

**(e) Frame de 6,5 a 9,6 ms; disciplina de bench.**

- **Desempenho: procede.** Os meus números são mediana de 6,5 a 9,8 ms e p95 de 13,6 a 20,6 ms, com o `004`
  incluído. Retiro o "custo por frame" do meu item 9. Nunca foi uma acusação central.
- **Disciplina: procede em parte.** A infraestrutura é boa, e concedo `record.py`, fingerprint, Wilson e as tags
  de rollback. A prática é outra história:
  - Os cinco "Medido e revertido" são todos da era de 17/09 (`6d`, `6e3`, `7jk`, `all4/5`, `7`).
  - Desde as posturas, nada foi medido e revertido.
  - As duas maiores mudanças entraram sem bench, o que o defensor admite no W4.
  - Uma disciplina que se desliga quando a mudança é a teoria preferida do autor não é disciplina; é
    instrumento.

## 2. Os demais argumentos do defensor

1. **Pipeline acíclico e posse única (2.1). Procede.** Concedo que é a melhor parte do projeto. Uma ressalva: o
   "feedback lido no frame seguinte" não fecha a malha onde ela mais importa. A `DefendAreaMission` recebe o
   `feedback` e não o lê (`defend_area.py:78`), e nenhuma missão lê o `GrantStatus` (C6).
2. **O observador como teoria de controle real (2.2). Procede em parte.** A mecânica está correta: `g` no estado,
   morte como entrada e projeção na restrição. Os defeitos são de modelo, e estão no mesmo log que o defensor
   citou:
   - **Bases.** Em `comp-eficacia/003`, entre 580 e 760 s, o filtro acredita em **4,5 a 5,4 bases inimigas
     enquanto conhece 1 a 3**, e as conhecidas caem de 3 para 1 enquanto o bot as destrói. Isso é o piso
     `max(conhecidas, prior por tempo)` (`enemy_army.py:202-203`).
   - **Cobertura inconsistente.** A cobertura é medida contra as bases **conhecidas** (de 0,33 a 0,5), mas a
     renda é prevista para as bases **acreditadas**.
   - **`g` não identificável.** Com a renda vindo de um prior, `g` e `B·W` não se separam. O `g` caindo de
     0,0080 para 0,0060 não é "aprender a renda"; é o filtro absorvendo o erro estrutural das bases.
   - **σ sem validação.** O σ cai de 33,7 para 4,6 em 140 s por pseudo-medições de uma memória de 180 s. É o
     mesmo sintoma que deu NEES de 34,9. Os replays de `comp-eficacia/000-003` estão no disco, e o
     `replay_truth` não foi rodado.
3. **Composição contínua (2.3). Não procede na prática.**
   - Em 2.690 frames de `efficacy`, nenhum tipo foi acrescentado fora da doutrina, e o desvio mediano ficou entre
     0,02 e 0,05.
   - O Siege Tank nosso que um Infestor dominou virou "produção Zerg" e foi respondido com 67 % de Tanks. O
     INFESTOR aparece 0 vezes nos logs, porque o poder dele é 0 no python-sc2.
   - A continuidade acaba no `min_share` (`composition.py:129`).
   - O defensor não respondeu à cegueira a BC, Oracle e casters (`units.py:126-130`, `model.py:407,433`), e ela
     fica de pé.
4. **Usa o Ares (2.4). Procede na macro.** Não procede no micro (`ShootTargetInRange`, `StutterUnitBack` e
   `KeepUnitSafe` estão parados no Ares), e o bug de blip do Ares não foi corrigido em lugar nenhum.
5. **Observabilidade (2.6). Procede.** A telemetria achou bugs. Mas o Tank dominado e o DEFEND com 49 de
   cobertura estavam no mesmo JSONL havia dias, e ninguém leu. O instrumento só vale o leitor que tem.
6. **"O gargalo do PhantomBot é o Body" (A1 dele).** Uso o dado dele. É a única partida contra um bot de
   verdade, e terminou em **derrota aos 10min50s**. É antes do instante em que, contra o CheatInsane, o bot
   sequer chega ao supply máximo (589–774 s) e muito antes de qualquer vitória (≥ 1.000 s). Kalman e Lanchester
   não chegaram a jogar.
   - Há também um log "live" do HEAD (`logs/game-20261004T032327451475Z`) que para aos 332 s, com 2,6 de poder
     de exército e dois RECOVER por `army_setback`. Está incompleto e não conto como placar; só registro.
7. **Fraquezas admitidas (W1–W8). Convergência.** O W3 do defensor reconhece que a ameaça ignora o `cover`, o
   W4 que as duas maiores mudanças entraram sem bench, o W5 o crash e o W6 os sinais sem consumidor. Nesses
   quatro pontos não há divergência; há prioridade.
8. **"Crença robusta antes de histerese foi seguida" (A4 dele). Procede em parte.** O estimador foi corrigido
   primeiro, concedo. Mas a economia continua sendo um relé por postura (`investment.py:147-155`), contra a regra
   4 do próprio autor. E o `004` trocou de postura 37 vezes em 1.249 s, com o mesmo gate de DEFEND sobre a
   pressão bruta.

## 3. Prioridades revisadas

| # | Ação | Custo | Por que mudou |
| --- | --- | --- | --- |
| 1 | **Ladder sem crash:** `if unit.is_blip: continue` no `_prepare_units` do Ares (ou num wrapper no bot), `try/except` em `play_frame` e `super().on_step`, e pausar as Sensor Towers até alguma decisão as ler | Horas | Subiu: o `KeyError: 0` agora tem causa no código e é derrota certa contra Terran |
| 2 | **Medir o que foi interrompido:** células Terran e Protoss, RandomBuild, 3 seeds, 2 mapas, PhantomBot N vezes, e `replay_truth` sobre os replays que já existem. O harness passa a marcar "cliente morto" em vez de aceitar o `Result.Defeat` do JSONL | Horas, mais uma noite | Desceu de 1º para 2º: o harness estava certo; o que falta é amostra, e o defensor concorda |
| 3 | **DEFEND por déficit:** ameaça líquida pelo `balance` e pelo `GrantStatus`. Nunca cancelar IMEDIATAMENTE um ENGAGE quando a casa cobre o incidente | 1 dia | Igual. O mecanismo aparece com 49 de cobertura, e o rótulo do jogo não importa |
| 4 | **Micro pelo Ares** (OS1/OS2) | 2–4 dias | Igual ao defensor. A derrota aos 10:50 para o PhantomBot reforça |
| 5 | **Um modelo de poder só**, com casters, e tag que já foi nossa nunca conta como produção | 1 dia | Igual. Sem contestação |
| 6 | **I1 + reforços agrupados** | 1–2 dias | Igual |
| 7 | **Observador:** bases como estado medido pelos townhalls conhecidos, e não como piso; cobertura sobre as bases acreditadas; nenhum parâmetro mexido antes do NEES pelos replays | 1 dia | Novo: o log de `003` mostra 5 bases acreditadas contra 1–3 conhecidas |
| 8 | **Congelar a composição** na doutrina com counters medidos | Horas | Igual |
| 9 | **Apagar sinais sem consumidor** (`risk`, `economy_position` e o ramo de cancelamento da Defense), e ligar a `aggression` a Bunker, reparo e worker pull ou apagá-la | Horas a 2 dias | Sem o argumento de custo por frame, que retirei |
| 10 | **Docs:** ScoutMission, `architecture.md:740` e `:833`, README | Horas | Igual |

**Contra a proposta 6 do defensor** (`radar_blips` como medição do observador): só depois do item 1. Hoje, cada
blip é um crash em potencial e um gasto de gás na janela em que o gás limita.
