# Bot development workspace

This directory contains versioned architecture documentation and ignored local
artifacts. Runtime bot code must stay under `bot/`.

- `architecture/`: decisions and contracts that are part of the repository.
- `logs/`: local JSONL logs, ignored by Git.
- `reports/`: generated analysis, ignored by Git.

The ladder entrypoint must always compose the bot with `NullBotLogger`.
