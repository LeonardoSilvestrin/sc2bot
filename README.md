# sc2bot

Bot Terran de StarCraft II em Python, construído sobre o
[ares-sc2](https://github.com/AresSC2/ares-sc2) (que por sua vez usa o
[python-sc2](https://github.com/BurnySc2/python-sc2)). O objetivo é um bot que
jogue a partida inteira com decisões explicáveis: cada ação pode ser rastreada
até o que foi observado, o que se inferiu e por que se decidiu.

## O que o bot faz hoje

Uma única abertura (`BioThreeOneOne`: Reaper expand, 3 Barracks, Factory e
Starport) para todos os adversários; depois dela:

- **Economia:** workers, gás e expansões pelos macro behaviors do Ares, com
  composição fixa Marine/Marauder/Siege Tank/Medivac, upgrades de infantaria e
  veículos, Orbital Command e MULE. O gás cobre os geysers das bases que o bot
  segura, a expansão continua enquanto houver lugar no mapa, o teto de
  produção cresce com as bases e as Barracks sem add-on recebem Reactor. Numa
  emergência antes do fim da abertura, o plano dinâmico assume e a abertura é
  interrompida.
- **Defesa:** ataques a qualquer base viram um incidente com um único
  orçamento de poder, dividido entre as partes aérea e terrestre; os supply
  depots sobem quando inimigos terrestres se aproximam.
- **Ofensiva:** reúne, avança, luta ou recua conforme a força local, reagrupa,
  procura bases quando não sabe onde o inimigo está e destrói estruturas
  (inclusive voando).
- **Informação:** um SCV explora a main inimiga no início; o exército inimigo
  não visto é estimado, não tratado como zero.
- **Detecção:** depois de ver um inimigo camuflado ou enterrado, guarda
  energia para scan, escaneia os escondidos perto do exército e põe uma
  Missile Turret em cada base.
- **Micro:** Stim no ataque e no rally, Medivacs acompanhando o grupo, Siege
  Tanks decidindo o siege.

### Limitações conhecidas

- Uma abertura e uma composição para todos os matchups; nenhuma reação
  específica a rush (bunker, reparo, workers lutando).
- Com o exército morto, o bot pode acumular milhares de minerais com supply
  livre. Teto de produção, Reactors, gás e bases a mais deram destino ao banco
  sem que ele caísse nas partidas medidas; a causa continua em aberto.
- Sem combat simulation: o poder de uma unidade é `sqrt(dps · alvos · vida)`.
  O splash já conta (um Siege Tank em siege vale 4,3 Marines em vez de 2,7),
  o alcance não: um tanque que atira de 13 células vale o mesmo que um Marine
  que precisa chegar a 5.
- Sem Raven, scouting recorrente, stutter-step, foco de fogo ou harass.

O andamento e as evidências de cada item estão em
[docs/propostas_status.md](docs/propostas_status.md).

## Arquitetura

Cada frame atravessa quatro camadas, sempre na mesma ordem
([bot/main.py](bot/main.py)):

```text
Attention  → o que foi visto neste frame (estado imutável)
Awareness  → memória e inferências: contatos, ameaça por base, incidentes, estimativa do inimigo
Ego        → estratégia (objetivo e preferências) e planners (o que fazer, sem nomear unidades)
Body       → Engine (quem recebe cada tarefa) e behaviors (como executar, via Ares)
```

O Planner decide **o quê**, o Engine decide **quem**, o Behavior decide
**como**. Só `observe`, os behaviors e os logs tocam o bot; o resto é testável
sem o jogo. Fórmulas, eventos de log e parâmetros estão em
[docs/architecture.md](docs/architecture.md).

| Documento | Conteúdo |
| --- | --- |
| [docs/architecture.md](docs/architecture.md) | Camadas, matemática, catálogo de eventos e comandos |
| [docs/propostas.md](docs/propostas.md) | Análise e roadmap (pesquisa, não checklist) |
| [docs/propostas_corrigidas.txt](docs/propostas_corrigidas.txt) | Corrigenda que prevalece sobre o roadmap |
| [docs/propostas_status.md](docs/propostas_status.md) | O que foi feito, com evidência, e o que falta |
| [docs/migration-map.md](docs/migration-map.md) | Histórico: da branch `matematização` à base atual |

## Instalação

Pré-requisitos: Python 3.11 ou 3.12, [Poetry](https://python-poetry.org/),
Git, StarCraft II e os [mapas da AI Arena](https://aiarena.net/wiki/maps/)
copiados para a raiz da pasta de mapas (no Windows,
`C:\Program Files (x86)\StarCraft II\Maps`).

```bash
git clone --recursive <url-do-repositório>
cd sc2bot
poetry install
```

Sem o submódulo do Ares (`Directory .../ares-sc2 ... does not seem to be a
Python package`):

```bash
git submodule update --init --recursive
```

Em Linux ou com instalação não padrão, ajuste `MAPS_PATH` em `run.py`. Com o
StarCraft II via Lutris, defina `SC2PF=WineLinux`, `SC2PATH` (pasta do jogo) e
`WINE` (binário do Wine do Lutris). Para atualizar o Ares:
`python scripts/update_ares.py`.

## Uso

Partida local contra a IA VeryHard Macro, num mapa instalado e numa raça
sorteados (`run.py`; nome e raça do bot em `config.yml`):

```text
.venv\Scripts\python.exe run.py
.venv\Scripts\python.exe run.py --bot-log events
.venv\Scripts\python.exe run.py --bot-log events --spatial-view --spatial-snapshot
```

- `--bot-log events` grava o log JSONL em `logs/game-<hora>/game.jsonl`.
- `--spatial-view` desenha o campo de influência no jogo; `--spatial-snapshot`
  grava SVGs do campo.
- `.venv\Scripts\python.exe logs\open_viewer.py` abre o viewer do log
  (linha do tempo das decisões e inspetor por camada).

Testes e lint (o CI roda os dois antes de gerar qualquer artefato):

```text
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m ruff check bot tests harness run.py bench.py
```

## Avaliação

O harness joga uma matriz fixa de partidas contra a IA do jogo, cada uma num
processo com timeout, e grava por partida um `result.json` com resultado
(`victory`, `defeat`, `tie`, `timeout`, `crash`, `no_result`, `not_played`),
commit, SHA do Ares, fingerprint da configuração, replay e log. Os resultados
ficam em `bench/` (fora do git). Uma partida que o bot nunca chegou a jogar —
o cliente falha no `on_start`, o python-sc2 resigna e o jogo reporta derrota
com o relógio em zero — é `not_played`: fica fora da taxa de vitória e é
jogada de novo na execução seguinte.

```text
.venv\Scripts\python.exe bench.py run --out bench\<rótulo> --maps PersephoneAIE_v4 --races Zerg Terran Protoss --time-limit 1200
.venv\Scripts\python.exe bench.py summarize bench\<rótulo>
.venv\Scripts\python.exe bench.py compare bench\<base> bench\<desafiante>
```

`compare` só aceita execuções da mesma matriz. Mesmo seed e mesmas decisões
reproduzem a mesma partida nesta máquina — não quando o cliente do SC2 falha.
Com uma partida por combinação, uma diferença isolada não é evidência de ganho
(o resumo mostra o intervalo de Wilson).

Referência atual: Persephone AIE, IA VeryHard Macro, Zerg/Terran/Protoss,
seeds 1-3, 1.200 s. A linha de base de nove partidas (`fe3cea0`) fez 8/9; com a
luta local corrigida e mais gás (`455209e`), 9/9 e duração média de 837 s para
758 s. Uma partida por célula: os intervalos de Wilson se cobrem e o placar não
separa as mudanças — o que as sustenta são as medidas de mecanismo em
[docs/propostas_status.md](docs/propostas_status.md).

## Entrega

- **Ladder (AI Arena):** a AI Arena roda em Linux e o Ares depende de Cython,
  então o zip precisa ser gerado em Linux (`scripts/create_ladder_zip.py`,
  Docker ou WSL). O workflow `ladder_zip.yml` faz isso a cada push na `main`,
  depois de `pytest` e `ruff`, e publica o artefato `ladder-zip.zip` na aba
  Actions. O upload automático fica desligado; para ligar, defina
  `AutoUploadToAiarena: True` em `config.yml` e crie os secrets
  `UPLOAD_API_TOKEN` e `UPLOAD_BOT_ID` no repositório.
- **Executável para jogar contra humanos (SC2AIApp):** no Windows,
  `poetry run python scripts/create_pyinstaller_exe.py` gera o `.exe`, o
  `ladderbots.json` e os arquivos de build; sem Windows, rode manualmente o
  workflow `Build Windows Executable`. A pasta do bot em `SC2AIApp/Bots` deve
  ter exatamente o nome do `ladderbots.json`.

`config.yml` ainda usa os valores do template (`MyBotName`); ajuste antes de
publicar.
