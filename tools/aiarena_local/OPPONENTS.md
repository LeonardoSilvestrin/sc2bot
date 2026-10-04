# Adversários de rush

Pacotes públicos da AI Arena baixados e cadastrados nesta máquina em **04/10/2026**.
Além do PhantomBot, os seletores **play**, **play full debug** e
**bench: bot da ladder (full debug)** incluem:

| Bot | Raça | Estratégia | Origem |
| --- | --- | --- | --- |
| SharpKnives | Protoss | Proxy gateways e zealots | [AI Arena, bot 92](https://aiarena.net/bots/92/) |
| SharpCannon | Protoss | Cannon rush | [AI Arena, bot 91](https://aiarena.net/bots/91/) |
| RustyMarines | Terran | All-in de marines em uma base; tem variantes | [AI Arena, bot 98](https://aiarena.net/bots/98/) |
| RoachRush | Zerg | Pool e roach warren cedo; produz roaches | [AI Arena, bot 81](https://aiarena.net/bots/81/) |

SharpKnives, SharpCannon e RustyMarines são house bots do Sharpy, com versão
`2024-08-08 / 6933621`; seus pacotes foram atualizados na Arena em 11/08/2024.
RoachRush é o pacote original do autor tweakimp, identificado pelo SHA256.
Os nomes e estratégias foram conferidos na API pública e no código dos pacotes.
SharpCannon escolhe entre variantes de rush/contain e pode transicionar para
stalkers; o sucesso do rush depende do mapa e da defesa do adversário.

## Jogar

Para testar pressão de zealots perto da sua base, escolha **SharpKnives**:

```powershell
.venv\Scripts\python.exe run.py --opponent SharpKnives --map PersephoneAIE_v4 --bot-log events --spatial-view --spatial-snapshot
```

Para repetir o cenário:

```powershell
.venv\Scripts\python.exe bench.py run --out bench\rush-zealots --opponent SharpKnives --maps PersephoneAIE_v4 --armies bio --games 3 --time-limit 600 --spatial-view --spatial-snapshot
```

Troque `SharpKnives` por qualquer nome da tabela. Docker Desktop deve estar
operacional. O [runner sem janela](README.md) também aceita esses nomes:

```powershell
.venv\Scripts\python.exe run_local_opponent.py --opponent RustyMarines --map PersephoneAIE_v4
```

## Runtime e registro

Os três bots Sharpy usam `runtime: python311` em `bots.local.json`;
RoachRush usa `runtime: python311-oldnumpy`.
`Dockerfile.opponent` mantém o controller oficial e adiciona um virtualenv
CPython 3.11 com NumPy 1.26.4 (Sharpy) ou 1.23.5 (RoachRush) e dependências
compatíveis. RoachRush ainda usa o alias `np.float`, removido no NumPy 1.24.
Os pacotes Sharpy já incluem extensões Linux para essa versão; o runtime padrão Python 3.12 não
consegue importá-las. A imagem é construída automaticamente quando ausente;
a receita e a imagem base determinam sua tag. O PhantomBot usa o runtime padrão.

ZIPs e metadados: `runtime/downloads/<nome>-20261004.zip` e `.json`.
Pacotes extraídos: `runtime/bots/<nome>/`. Cada partida copia seu pacote e os
dados para uma pasta própria; os scripts e estratégias originais foram preservados.
O launcher grava também a referência, ID da imagem e interpretador no manifest.

Para preparar outro computador, execute `--setup`, baixe o pacote público e
cadastre com o runtime compatível. Exemplo:

```powershell
New-Item -ItemType Directory -Force tools\aiarena_local\runtime\downloads
Invoke-WebRequest https://aiarena.net/bots/92/bot_zip -OutFile tools\aiarena_local\runtime\downloads\SharpKnives.zip
.venv\Scripts\python.exe run_local_opponent.py --register SharpKnives --source tools\aiarena_local\runtime\downloads\SharpKnives.zip --race P --type python --runtime python311
```

Use os IDs e raças da tabela para os outros bots; para RoachRush, passe
`--runtime python311-oldnumpy`. Os downloads e o registro
local são ignorados pelo Git. Para outra versão, use outro nome de cadastro e
atualize o seletor do VS Code.

SHA256 dos ZIPs usados nesta instalação:

| Bot | SHA256 |
| --- | --- |
| SharpKnives | `551590d04f97a65aa6a51c64435ab1594db307bb7d6f26d12a39a9e043554733` |
| SharpCannon | `4f4eba1c974926c2649a7af93f8345f62bb70553da1ecbd085c2ed8d28f7583b` |
| RustyMarines | `335a2535e1b185d813157f236288fcf2e1ef4e06c7bee857d6f7d53724ce6850` |
| RoachRush | `a7a09e7010d754b3f053d0d47625405afa401b203ead5fb4804cc8226f089b2a` |

## Validação

Imports dos quatro bots aprovados em Linux/amd64, no runtime Python 3.11.
Testes do launcher, runner e workflows: 24 aprovados; lint aprovado.

Quatro testes pelo launcher nativo, em `PersephoneAIE_v4`, bio, seed 1, limite
de 180 segundos de jogo: manifests `completed`, replay e log do adversário
presentes. Os quatro retornaram `Result.Tie` no limite solicitado; o bench
registra esse encerramento como `outcome: timeout`.

Artefatos com janela, relativos à raiz do projeto:

- `bench/rush-opponents-smoke-20261004-SharpKnives/`
- `bench/rush-opponents-smoke-20261004-SharpCannon/`
- `bench/rush-opponents-smoke-20261004-RustyMarines/`
- `bench/rush-opponents-smoke-20261004-RoachRush-fixed/`

O replay confirmou gateways proxy e primeiros zealots aos 2min00s no
SharpKnives, barracks proxy e primeiros marines aos 2min02s no RustyMarines,
e primeiros roaches aos 2min10s no RoachRush.

Partidas no Docker, mesmo mapa, limite de dez minutos de jogo:

| Bot | Resultado | Tempo | Pasta em `runs/` |
| --- | --- | --- | --- |
| SharpKnives | Empate no limite | 10min00s | `20261004T040246872725Z-BotBandido-vs-SharpKnives` |
| SharpCannon | Vitória do adversário | 8min30s | `20261004T040635039135Z-BotBandido-vs-SharpCannon` |
| RustyMarines | Vitória do adversário | 5min42s | `20261004T040932898543Z-BotBandido-vs-RustyMarines` |
| RoachRush | Vitória do adversário | 6min44s | `20261004T041314202976Z-BotBandido-vs-RoachRush` |

Todos os manifests terminaram em `completed`, com replay, logs dos dois bots
e limpeza dos contêineres concluída. O replay do SharpCannon confirmou dois
cannons iniciados perto da base inimiga aos 2min15s e 2min18s.
Resumo dos artefatos: `runtime/opponents-validation-20261004.json`.

O primeiro teste de RoachRush falhou com `np.float` ausente. O teste repetido
usando NumPy 1.23.5 passou, mantendo o código original do pacote.

```powershell
.venv\Scripts\python.exe -m pytest tests/test_ladder_launcher.py tools/aiarena_local/test_local_play.py tests/test_workflows.py -q
.venv\Scripts\python.exe -m ruff check tools/aiarena_local/local_play.py tools/aiarena_local/live_play.py tests/test_ladder_launcher.py tools/aiarena_local/test_local_play.py
```
