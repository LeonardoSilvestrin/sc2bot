# Partidas locais AI Arena

Infraestrutura separada de `bench.py`, `harness/`, `run.py` e do ambiente `.venv`.
O wrapper usa o Compose e os controllers oficiais de
[aiarena/local-play-bootstrap](https://github.com/aiarena/local-play-bootstrap),
fixados no commit `6de4228a79d61bb045a0f179573c07984355f53f`.
As três imagens `v0.8.0` também estão fixadas por digest em `local_play.py`.
`RUN_TYPE = "local"`, URL da ladder vazia, uma partida por execução: não há
cadastro, upload, token nem participação na ladder oficial.

## Situação desta máquina — 19/09/2026

**Configuração preparada; smoke test de jogo ainda bloqueado pelo host.**

- Windows 11 Pro x64, Ryzen 7 5700X.
- Instalados Docker Desktop **4.91.0**, CLI **29.8.0**, Compose **5.5.1**,
  Microsoft WSL **2.7.13.0**, kernel **6.18.33.2-2**.
- O script administrativo verificou/habilitou `VirtualMachinePlatform` sem
  reiniciar o Windows. Log: `runtime/windows-prerequisites.log`.
- `VirtualizationFirmwareEnabled = False`, `HypervisorPresent = False`;
  `wsl --status` informa que WSL2 não pode iniciar sem virtualização.
- Habilitar **SVM/AMD-V** na BIOS/UEFI e reiniciar o computador é o próximo
  passo necessário. Não houve reinicialização automática.
- SC2 nativo encontrado em `C:\Program Files (x86)\StarCraft II`, com
  `Base75689` e `Base97563`. Essa instalação foi preservada.
- O bootstrap executará **SC2 4.10 / Base75689 Linux**, incluído na imagem
  oficial. O executável Windows não é montado no contêiner.
- Os bots oficiais `basic_bot` e `loser_bot` já estão disponíveis. **Não falta
  um ZIP de adversário.** Faltam o engine operacional e a validação real do jogo.

Após habilitar SVM e reiniciar, abra Docker Desktop, aguarde o engine Linux e
execute os comandos abaixo na raiz do projeto (Python 3.11/3.12; wrapper só
usa a biblioteca padrão). Se houver falha de build/import ou partida, os logs
indicarão o ponto: a imagem derivada do BotBandido ainda não pôde ser construída
nem executada nesta máquina.

## Preparação e partida

```powershell
python run_local_opponent.py --setup
python run_local_opponent.py --doctor
python run_local_opponent.py --opponent loser_bot --map PersephoneAIE_v4
```

`--setup` é repetível: baixa a revisão fixa do bootstrap quando ausente e copia
mapas AIE do SC2 detectado. Também aceita `--maps-from "C:\pasta\mapas"`.
Não instala software de sistema automaticamente. Em outro Windows, instale
Docker Desktop com backend WSL2; `install-wsl.ps1` pode ser executado em
PowerShell administrador para preparar o WSL, sem reinicialização automática.

O primeiro jogo baixa as imagens e constrói a imagem de nosso bot; isso pode
demorar. `setup.log` acompanha essas etapas. O wrapper valida o executável
`/root/StarCraftII/Versions/Base75689/SC2_x64` e rejeita uma imagem em que o
controller selecionaria outro build. O runtime oficial consultado usa Python
3.12.12; o Dockerfile mantém o controller oficial e instala as dependências de
nosso `poetry.lock` em um virtualenv Linux próprio. A imagem do adversário
continua sendo a oficial, com suas dependências originais.

Smoke test curto (100 segundos de jogo, resultado normalmente `Tie`):

```powershell
python run_local_opponent.py --opponent loser_bot --map PersephoneAIE_v4 --max-game-time 2240 --max-real-time 180
```

Teste só da infraestrutura com os dois bots oficiais:

```powershell
python run_local_opponent.py --bot basic_bot --opponent loser_bot --map AcropolisAIE --max-game-time 2240 --max-real-time 180
```

`--max-game-time` usa game loops, aproximadamente 22,4 por segundo.
O padrão é 80640 loops; o limite de tempo real padrão é 7200 segundos.
Os limites por frame e strikes são os do bootstrap oficial.
`--prepare-only` gera entradas e snapshots sem iniciar o Docker; **não é smoke
test**. A saída 0 de uma execução real exige vitória/derrota/empate, frames
jogados, replay não vazio e arquivos de log dos dois bots. Crash, timeout de
bot, erro de inicialização ou ausência de artefatos retorna 2.

## Cadastro de adversários

```powershell
python run_local_opponent.py --list-bots
python run_local_opponent.py --register MeuAdversario --source "C:\Downloads\bot.zip" --race Z --type python
python run_local_opponent.py --opponent MeuAdversario --map PersephoneAIE_v4
```

O download deve ser o pacote executável disponibilizado pelo autor na AI Arena.
Também é possível passar uma pasta descompactada em `--source`.
O cadastro base está em `bots.json`; os downloads são copiados para
`runtime/bots/<nome>` e registrados em `bots.local.json` (ignorado pelo Git).
Para outra versão, use outro nome de cadastro. A raça aceita `T`, `Z`, `P`, `R`.

O tipo determina a convenção oficial de entrada:

| Tipo | Arquivo na raiz do pacote |
| --- | --- |
| `python` | `run.py` |
| `cpplinux` | `<nome>` |
| `dotnetcore` | `<nome>.dll` |
| `java` | `<nome>.jar` |
| `nodejs` | `<nome>.js` |
| `cppwin32` | `<nome>.exe` (exige Wine no runtime; não validado aqui) |

Prefira o pacote Linux de competição. Um executável Windows ou dependências
Python compiladas no Windows não substituem os binários Linux necessários.
`BotBandido` é registrado com `source: project`: cada execução captura o código
atual, configurações, Ares e lockfile. Não exige ZIP nem altera o pacote da ladder.

## Localizações e artefatos

Todos os caminhos abaixo são relativos a `tools/aiarena_local/`:

| Conteúdo | Caminho |
| --- | --- |
| Bootstrap oficial, sem edições | `bootstrap/` |
| Bots de teste oficiais | `bootstrap/bots/basic_bot/`, `bootstrap/bots/loser_bot/` |
| Adversários registrados | `runtime/bots/<nome>/` |
| Snapshots de nosso código | `runtime/snapshots/<sha256>/BotBandido/` |
| Mapas | `runtime/maps/` |
| Origem e SHA256 dos mapas | `runtime/maps-manifest.json` |
| Execução | `runs/<data-UTC>-<nosso-bot>-vs-<adversário>/` |

Há oito mapas: `AcropolisAIE` do bootstrap e `IncorporealAIE_v4`,
`LeyLinesAIE_v3`, `MagannathaAIE_v2`, `PersephoneAIE_v4`, `PylonAIE_v4`,
`TorchesAIE_v4`, `UltraloveAIE_v2` copiados da instalação existente.
SC2 75689 e mapas AIE seguem a
[recomendação oficial da AI Arena](https://aiarena.net/wiki/bot-development/#sc2-version-considerations).
Novos mapas podem ser obtidos na [página oficial de mapas](https://aiarena.net/wiki/maps/).

Dentro de cada execução:

- `results.json`: resultado original do controller, sem conversão para o bench.
- `replays/*.SC2Replay`: replay gravado pelo controller.
- `logs/bot_controller1/<nosso-bot>/stderr.log`: stdout e stderr combinados do bot 1.
- `logs/bot_controller2/<adversário>/stderr.log`: stdout e stderr combinados do bot 2.
- `logs/proxy_controller/`, `logs/sc2_controller/`, `logs/bot_controller*/`:
  logs dos controllers, conforme o layout oficial.
- `compose.log`: saída dos quatro serviços, capturada antes do encerramento.
- `setup.log`, `cleanup.log`: preparação das imagens e remoção dos contêineres.
- `manifest.json`: estado (`prepared`, `running`, `completed`, `failed`), mapa,
  SHA do código atual, registros dos bots, build verificado e IDs/digests das
  imagens quando disponíveis; em caso de falha, o erro observado.
- `matches`, `config.toml`, `compose.override.json`: entradas exatas da execução.
- `bots/` e `maps/`: cópias usadas pela partida; `bots/<nome>/data/` preserva
  dados produzidos. Cada partida começa com uma cópia nova do cadastro; dados
  de aprendizado não são carregados automaticamente de partidas anteriores.

O código do bot continua com o logging normal da entrada ladder. O wrapper
captura stdout/stderr; não ativa o logging JSONL/overlays do bench.
Snapshots e mapas são preservados por execução; o comando pode ser repetido,
mas não promete resultados idênticos para bots com aleatoriedade interna.
Cada partida usa seu próprio projeto Compose, sem publicar portas do host.
O encerramento remove apenas os contêineres/rede daquele projeto, preservando
artefatos e imagens em cache.

## Validação realizada e pendência

Validados: `docker compose config` com os quatro serviços e caminhos Windows
com espaços; três imagens oficiais existentes no registry, Linux/amd64;
Python 3.12.12/entrypoint oficial; `poetry.lock` atualizado em relação ao
`pyproject.toml`; lint; 11 testes dos contratos de entrada, isolamento de
arquivos, registro de ZIP e detecção de falhas/artefatos ausentes.

```powershell
.venv\Scripts\python.exe -m pytest tools/aiarena_local/test_local_play.py -q
.venv\Scripts\python.exe -m ruff check run_local_opponent.py tools/aiarena_local/local_play.py tools/aiarena_local/test_local_play.py
```

Tentativa real do comando em
`runs/20260920T015118743465Z-BotBandido-vs-loser_bot/manifest.json`:
`failed`, `docker info` expirou aguardando o engine. **Nenhuma partida foi
jogada, nenhum replay foi gerado e o build Linux ainda não foi executado.**
`results.json` permanece com lista vazia; não há resultado de jogo inventado.
Após habilitar SVM e reiniciar, o smoke test acima ainda precisa passar para
considerar a tarefa concluída. Consulte também `host-report.json`.

Referências adicionais: [instalação Docker no Windows](https://docs.docker.com/desktop/setup/install/windows-install/),
[instalação WSL](https://learn.microsoft.com/en-us/windows/wsl/install),
[controller oficial v0](https://github.com/aiarena/sc2-ai-match-controller/tree/v0).
