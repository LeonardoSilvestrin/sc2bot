# Bot development workspace

Local working space for developing the bot. Runtime code lives under `bot/`,
the architecture documentation under `docs/` (start at
[docs/README.md](../docs/README.md)), and game logs with their viewer under
`logs/`.

- `notebook/`: research notes (in Portuguese) on Ares features the bot does
  not use yet; open the matching file before starting on one of those fronts.
- `agent.ps1`: opens or resets an agent worktree (`.\_botdev\agent.ps1
  claude`); the `open WT` VS Code launcher runs it.
- `reports/`, `tmp/`: generated analysis and scratch files, ignored by Git.

Game logs live in the top-level `logs/` directory, next to the viewer that
reads them. `poetry run python run.py --bot-log events` writes
`logs/game-<timestamp>/game.jsonl` (ignored by Git), which `logs/viewer.html`
reads; `--spatial-snapshot` additionally writes periodic SVGs under that
game's `spatial/` directory. `python logs/open_viewer.py` opens the viewer.
See [docs/logging.md](../docs/logging.md).

The ladder entrypoint must always compose the bot with `NullBotLogger`
(`MyBot` defaults to it; `run.py` only opens a JSONL log for local runs).
