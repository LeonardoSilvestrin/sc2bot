# Bot development workspace

This directory contains versioned architecture documentation, research notes,
and ignored local artifacts. Runtime bot code must stay under `bot/`.

- `architecture/`: decisions and contracts that are part of the repository.
- `notebook/`: research notes (in Portuguese) on Ares features the bot does
  not use yet; open the matching file before starting on one of those fronts.
- `logs/`: local JSONL logs, ignored by Git. `poetry run python run.py
  --bot-log events` writes them; `scripts/log_viewer.html` reads them.
- `reports/`, `tmp/`: generated analysis and scratch files, ignored by Git.

The ladder entrypoint must always compose the bot with `NullBotLogger`
(`MyBot` defaults to it; `run.py` only opens a JSONL log for local runs).

## Architecture docs

Start at [overview.md](architecture/overview.md) for the causal pipeline and
the mission-planner roster, then follow whichever slice is relevant:

- [contracts.md](architecture/contracts.md) -- dependency rules, mission
  kinds/priorities, the full frame lifecycle, and the causal logging catalog.
  `bot/behavior/contracts.py` is the code-level counterpart for behaviors
  (the `ASSESS -> PLAN -> EXECUTE` protocols every behavior follows), and
  `bot/macro/contracts.py` for macro (`SpendPlanner`).
- [squads.md](architecture/squads.md) -- persistent squad identity, and how a
  defense borrows a squad and gives it back.
- [vision.md](architecture/vision.md) -- the shared active-vision service
  (requests, arbitration, the Scanner Sweep provider).
- [base-model.md](architecture/base-model.md) -- per-base threat/protection
  scoring behind `DefensePlanner`.
- [harass-and-defense-planners.md](architecture/harass-and-defense-planners.md)
  -- the vertical `behavior/` layout, the `harass/reaper/` and
  `harass/banshee/` behaviors, `DefensePlanner` and its defense roles, and the
  priority/utility/preemption-cost arbitration between them.
- [standing-behavior.md](architecture/standing-behavior.md) -- the default
  behavior (`StandingPlanner`/`CombatPosture`) that owns every combat unit
  no special mission has claimed.
- [map-control.md](architecture/map-control.md) -- the safe patrol mission.
- [macro-planner.md](architecture/macro-planner.md) -- `bot/macro`, the
  spend domain beside `bot/behavior` (`EconomicProposal`/`EconomyController`).
- [opening.md](architecture/opening.md) -- the Ares build-order openings, how
  one is picked each game, and how they hand off to `MacroPlanner`.
- [scout-pilot-migration.md](architecture/scout-pilot-migration.md) -- the
  original scout vertical slice this architecture grew from.

Several of these include Mermaid flowcharts/sequence diagrams of the bot's
decision-making; they render directly on GitHub and in most Markdown
previews.
