# BotBandido contra PhantomBot

Adversário baixado e registrado nesta máquina em 03/10/2026:
[PhantomBot](https://aiarena.net/bots/510/), do autor Phantom, Zerg de macro,
versão **3.48.1**. Na consulta à API pública da AI Arena, tinha **1963 de Elo**
na competição aberta `Sc2 AI Arena 2026 Pre-Season 2`.

O pacote e os dados de aprendizado estão liberados publicamente pelo autor.
O cadastro local inclui o código da ladder e seu `data/params.json`.

## Estado desta máquina — 03/10/2026

A virtualização foi habilitada na **ASUS TUF GAMING B550M-PLUS**, com Ryzen 7
5700X. O diagnóstico confirmou `VirtualizationFirmwareEnabled = True` e
`HypervisorPresent = True`; o engine Linux/amd64 do Docker está funcionando.
Os dois bots passaram na validação de imports dentro dos contêineres.

Caso a virtualização esteja desativada em outra instalação:

1. Reinicie e pressione **Del** para entrar na BIOS.
2. Entre em **Advanced Mode**, usando **F7** se necessário.
3. Abra **Advanced > CPU Configuration > SVM Mode** e escolha **Enabled**.
4. Salve com **F10** e inicie o Windows.
5. Abra Docker Desktop e aguarde o engine de contêineres Linux iniciar.

Caminho conforme a [documentação da ASUS](https://www.asus.com/global/support/faq/1045141/).

## Executar com janela e debug

No VS Code, use **play** ou **play full debug** e selecione **PhantomBot**.
Para repetir partidas, use **bench: bot da ladder (full debug)**.

```powershell
.venv\Scripts\python.exe run.py --opponent PhantomBot --map PersephoneAIE_v4 --bot-log events --spatial-view --spatial-snapshot
.venv\Scripts\python.exe bench.py run --out bench\phantom-local --opponent PhantomBot --maps PersephoneAIE_v4 --armies bio --games 3 --time-limit 1200 --spatial-view --spatial-snapshot
```

O SC2 abre duas janelas nativas no build 75689: nosso ponto de vista e o do
PhantomBot. Nosso bot roda no depurador e o adversário no Docker. O bench
grava os mesmos resultados, replays, eventos e snapshots dos testes contra a
IA do jogo, com versão e hash do adversário para comparação. Docker Desktop
deve estar funcionando. Veja [detalhes dos modos e artefatos](README.md).

## Executar inteiramente no Docker

No PowerShell, na raiz do projeto:

```powershell
.venv\Scripts\python.exe run_local_opponent.py --doctor
.venv\Scripts\python.exe run_local_opponent.py --opponent PhantomBot --map PersephoneAIE_v4
```

A primeira execução baixa as imagens oficiais e constrói o ambiente Linux do
BotBandido. O runner captura o código atual do projeto em cada nova execução.
SC2 roda no contêiner, na versão 4.10 / build 75689. O pacote do PhantomBot
contém extensões compiladas para CPython 3.12/Linux e não roda diretamente no
Python do Windows.

Os resultados ficam em `tools/aiarena_local/runs/<data>-BotBandido-vs-PhantomBot/`:

- `results.json`: resultado da partida.
- `replays/`: replay.
- `logs/bot_controller1/BotBandido/stderr.log`: log do nosso bot.
- `logs/bot_controller2/PhantomBot/stderr.log`: log do adversário.
- `setup.log`: download e construção das imagens.

Esse runner captura os logs da entrada ladder; a telemetria JSONL do bench
não é ativada por ele.

## Estado da validação

Validados o ZIP, o cadastro, a cópia dos parâmetros públicos, o mapa, Docker
Compose, SC2 build 75689, o build Linux do BotBandido e os imports de ambos os
bots. A imagem oficial do adversário usa CPython 3.12.12/Linux amd64.

O snapshot inclui `harness/`, importado pela entrada atual do BotBandido. A
instalação de dependências no Docker usa quatro workers, timeout de 120 segundos
e até três retomadas de download para evitar os timeouts encontrados no primeiro
build. Os 11 testes do runner e o lint passaram.

**Partida completa validada** em `PersephoneAIE_v4`: vitória do PhantomBot
(`Player2Win`) aos **10min50s** de jogo, com 14575 game loops. Ambos os logs e
o replay de 704927 bytes foram gravados; o manifest terminou em `completed` e
os contêineres foram encerrados sem erros. Tempo médio por step: BotBandido
7,12 ms; PhantomBot 19,08 ms.

Artefatos:

`runs/20261004T023811744624Z-BotBandido-vs-PhantomBot/`

Replay: `replays/1_BotBandido_vs_PhantomBot.SC2Replay` dentro dessa pasta.
O snapshot do BotBandido usado na partida tem SHA256
`aa0578f05fb99db5e9ad466eb9ad76e651b25ba92c23b2fdc976dacb5ca3e3a7`.

## Validação do launcher com janela — 04/10/2026

- `play full debug`: partida completa em Persephone AIE, bio, **vitória do
  PhantomBot aos 10min21s**. Manifest `completed`, replay de 689334 bytes,
  5326 eventos JSONL e 28 snapshots SVG. Ao terminar, nenhum contêiner do
  launcher ou processo SC2 permaneceu aberto.
- Artefatos da partida: `runs/20261004T032327572075Z-live-vs-PhantomBot/`.
  O manifest aponta para `logs/game-20261004T032327451475Z/game.jsonl` na
  raiz do projeto.
- Bench curto: `bench/launcher-phantom-smoke3-20261004`, limite de 120 s,
  corretamente classificado como `timeout`, com replay, 155 eventos e 4 SVGs.
- Timeout real de 2 s: classificado como `crash`, com
  `wall_timed_out = true`; os clientes iniciados foram encerrados.
- 623 testes verificados e lint do bot, harness e launcher aprovados.
  O teste do viewer em navegador precisou rodar fora do sandbox para acessar
  a GPU do Windows.
- Leitura da partida completa validada com `sc2reader` em ambiente isolado:
  NEES 0,81 e 94% das amostras dentro de 2σ. Esses valores descrevem esta
  partida; a validação do launcher não calibrou o estimador.

## Origem e arquivos locais

- Código: <https://aiarena.net/bots/510/bot_zip>, atualização de 26/08/2026.
- Dados públicos: <https://aiarena.net/bots/510/bot_data>, baixados em 03/10/2026.
- Código extraído: `runtime/bots/PhantomBot/`.
- Cadastro: `bots.local.json`.
- ZIPs e metadados de origem: `runtime/downloads/PhantomBot-*.zip` e `.json`.
- SHA256 do código: `6d9528dbe262115f7c1ee3628f4dbe87648a872582e5ab7d27a2931568c01451`.
- SHA256 dos dados: `23497d4dd046ca13e92f920a152bf57b3da25c9762ae4020499021fff77ced94`.

Downloads, cadastro local e artefatos são ignorados pelo Git. Para cadastrar o
mesmo ZIP novamente em outra máquina, após o `--setup`:

```powershell
.venv\Scripts\python.exe run_local_opponent.py --register PhantomBot --source tools\aiarena_local\runtime\downloads\PhantomBot-20260826.zip --race Z --type python
```

Esse comando cadastra o código. Os dados públicos devem ser descompactados em
`runtime/bots/PhantomBot/data/`; essa etapa já foi feita nesta máquina.
