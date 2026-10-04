# BotBandido contra PhantomBot

Adversário baixado e registrado nesta máquina em 03/10/2026:
[PhantomBot](https://aiarena.net/bots/510/), do autor Phantom, Zerg de macro,
versão **3.48.1**. Na consulta à API pública da AI Arena, tinha **1963 de Elo**
na competição aberta `Sc2 AI Arena 2026 Pre-Season 2`.

O pacote e os dados de aprendizado estão liberados publicamente pelo autor.
O cadastro local inclui o código da ladder e seu `data/params.json`.

## O que falta nesta máquina

O diagnóstico confirmou `VirtualizationFirmwareEnabled = False` e
`HypervisorPresent = False`. Docker Desktop está instalado, mas seu engine
Linux não está disponível. A placa-mãe é **ASUS TUF GAMING B550M-PLUS**, com
Ryzen 7 5700X.

Depois de terminar os testes em andamento:

1. Reinicie e pressione **Del** para entrar na BIOS.
2. Entre em **Advanced Mode**, usando **F7** se necessário.
3. Abra **Advanced > CPU Configuration > SVM Mode** e escolha **Enabled**.
4. Salve com **F10** e inicie o Windows.
5. Abra Docker Desktop e aguarde o engine de contêineres Linux iniciar.

Caminho conforme a [documentação da ASUS](https://www.asus.com/global/support/faq/1045141/).

## Executar a partida

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

Validados o ZIP, o cadastro, a cópia dos parâmetros públicos, o mapa e a geração
dos arquivos da partida usando `--prepare-only`. A imagem oficial do adversário
usa CPython 3.12.12/Linux amd64, compatível com o formato das extensões do pacote.

**Nenhuma partida contra o PhantomBot foi jogada.** O build do BotBandido, os
imports do PhantomBot no contêiner e a execução do jogo ainda dependem do engine
Docker. A preparação existente tem estado `prepared` e resultado vazio:

`runs/20261004T011259516509Z-BotBandido-vs-PhantomBot/`

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
