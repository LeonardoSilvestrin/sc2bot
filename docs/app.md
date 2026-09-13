# Application shell

`bot/app` wires the game's objects together and runs them; it holds no game
rules. This document covers how a game is started, what gets built, and the
observers that report on it.

Source: `run.py`, `bot/main.py`, `bot/app/composition.py`,
`bot/app/runtime.py`, `bot/app/frame.py`, `bot/app/opening.py`,
`bot/app/mission_registry.py`, `bot/app/telemetry/`, `bot/app/debug/`.

## Starting a game

`run.py` parses local flags, builds `MyBot`, and either joins a ladder game
(`--LadderServer` present) or starts a local one against `Computer(random
race, VeryHard, Macro)` on a random map from `MAPS_PATH`.

| Flag | Default | Effect |
| --- | --- | --- |
| `--bot-log off\|events` | `off` | `events` opens `logs/game-<timestamp>/game.jsonl` |
| `--spatial-view` | off | draws the territory debug view in game ([below](#in-game-debug-view)) |
| `--spatial-view-spacing UNITS` | 4 | gap between drawn markers, rounded to whole grid steps; presentation only |
| `--spatial-snapshot` | off | writes SVG snapshots, and opens the JSONL log too |
| `--spatial-snapshot-interval SECONDS` | 30 | game time between snapshots |

`DEFAULT_SPATIAL_SPACING = 2` in `run.py` is the spacing of the pathable
lattice the bot reasons over (spatial field, territory, map control anchors).
It changes how the bot plays, and it applies to ladder games too, because
`run.py` builds the same `MyBot` for both. `MyBot`, `BotRuntime` and
`compose_bot` default to 10 when constructed directly (tests). On the last
recorded map, spacing 2 meant 3094 samples.

Ladder safety: the JSONL logger and the SVG exporter are only created when
`--LadderServer` is absent; otherwise the bot gets `NullBotLogger` and both
debug outputs stay disabled.

VS Code launchers (`.vscode/launch.json`, checked by `tests/test_run.py`):

| Launcher | Arguments |
| --- | --- |
| `play` | `--bot-log off` |
| `play_log` | `--bot-log events` |
| `play_logs_imap` | `--bot-log events --spatial-view` |
| `play_logs_SVG` | `--bot-log events --spatial-snapshot` |
| `play_full_debug` | `--bot-log events --spatial-view --spatial-snapshot` |
| `log_view` | runs `logs/open_viewer.py` |
| `open WT` | runs `_botdev/agent.ps1` for an agent worktree |

## Composition root

`compose_bot(logger=..., **optional configs)` in `composition.py` is the only
place that knows which concrete objects a game runs with. Plain constructors,
no container. It returns `BotComposition(opening, frame, missions,
macro_planner)`.

What it builds, in order:

| Group | Objects |
| --- | --- |
| Read side | `AresWorldObserver(spatial_sample_spacing)`, `AwarenessService(location_stale_after=IntelConfig.location_stale_after, spatial_model_config, logger)` |
| Shared services | `VisionService(ScanProvider)`, wrapped in `BehaviorServices(vision=...)` |
| Behavior domain | `IntelPlanner`, `ScoutingVisionRequester`, `BansheeHarassPlanner`, `ReaperHarassPlanner`, `DefensePlanner(services)`, `MapControlPlanner`, `StandingPlanner` |
| Mission engine | `MissionController(executor_factories=build_executor_factories(...))`, which builds its own `UnitAllocator`, `MissionBoard`, `SquadController` |
| Macro domain | `MacroPlanner(config, follow_opening=macro_config is None)`, `EconomyController`, `MacroDiagnostics` |
| Frame | `FrameProcessor(...)` with `FrameTelemetry`, `SpatialDebugView`, `SpatialSnapshotExporter` |
| Start of game | `OpeningSelector(rng)` |

Every behavior config (`IntelConfig`, `ScoutingVisionConfig`,
`BansheeHarassConfig`, `ReaperHarassConfig`, `DefenseConfig`,
`MapControlConfig`, `StandingConfig`), the vision configs,
`MacroPlannerConfig`, `SpatialModelConfig`, the debug configs and the RNG can
be passed in; `BotRuntime` forwards the same keyword arguments. A pinned
`macro_config` never follows the opening (tests use this).

`AwarenessService` is built with its other defaults (territory, beliefs,
enemy heuristics); `compose_bot` does not expose those yet.

### Executor registry

`mission_registry.build_executor_factories` maps each `MissionKind` to a
factory `(mission, now) -> MissionExecutor`, each bound to the same config
object its planner uses, so tuning a behavior in one place tunes both halves.

| Kind | Executor |
| --- | --- |
| `SCOUT` | `ScoutExecutor` |
| `HARASS` | `ReaperHarassExecutor` |
| `AIR_HARASS` | `BansheeHarassExecutor` |
| `DEFENSE` | `DefendBaseExecutor` |
| `MAP_CONTROL` | `MapControlExecutor` |
| `HOLD_RALLY`, `POSITION` | `StandingExecutor` |

`DEFAULT_EXECUTOR_FACTORIES` is the default-config binding tests use.

## Runtime and frame

`BotRuntime` marks the start and end of the game and hands each frame to
`FrameProcessor.process`, whose step order is in
[frame-lifecycle.md](frame-lifecycle.md). `FrameProcessor` also constructs the
per-frame Ares adapters (`AresVisionCommands`, `AresMissionCommands`,
`AresEconomyCommands`) around the live `bot`.

## Opening selection

`terran_builds.yml` sets `UseData: false`, which makes Ares always resolve its
build cycle to `Cycle[0]`. `OpeningSelector.choose_and_announce` (in
`on_start`, before the build runner takes a step) re-picks uniformly at random
from the same cycle -- the opponent id's entry if present (or `test_123` when
`Debug` is on in `config.yml`), otherwise the enemy race's -- calls
`build_order_runner.switch_opening`, and posts `[Build] <opening>` in chat,
followed by a short description when one is registered (`BioThreeOneOne`,
`BansheeCloak`; `BattleMech` has none). See [macro/builds.md](macro/builds.md).

## Telemetry

`FrameTelemetry.report` runs six reporters at the end of every frame. They
read snapshots (and, for standing, the live mission board and squads) and log
through change gates. The event contents are in [logging.md](logging.md).

| Reporter | Reads | Events | Gate |
| --- | --- | --- | --- |
| `BuildOrderTelemetry` | `bot.build_order_runner` | `macro.build_order_progress` | change only |
| `EnemyTelemetry` | `awareness.enemy` | `knowledge.enemy_intel`; `knowledge.enemy_model` | change only; change + 10 s |
| `BeliefTelemetry` | `awareness.economy`, `awareness.army` | `awareness.world_belief` | change + 10 s |
| `TerritoryTelemetry` | `awareness.territory` | `knowledge.territory` | change + 10 s |
| `WorldSnapshotTelemetry` | attention, awareness, mission snapshots | `knowledge.updated`, `observation.updated` | change + 10 s |
| `StandingTelemetry` | mission board, allocator, squads, `StandingPlanner.last_posture` | `standing.updated`, `standing.unassigned_units_persisting` | change + 10 s; warning after 15 s |

## In-game debug view

`SpatialDebugView` (enabled by `--spatial-view`) queues python-sc2 debug
drawings from the latest `AwarenessSnapshot` every frame. It derives nothing.

| `SpatialDebugConfig` | `run.py` sets | Draws |
| --- | --- | --- |
| `enabled` | from `--spatial-view` | -- |
| `show_territory` | default on | a sphere per territory sample, coloured by control (green friendly, yellow contested, red enemy, grey uncontrolled) |
| `show_grid` | on | the plain sample grid in blue, only when territory samples are not drawn |
| `show_frontline` | default on | a magenta sphere per frontline point |
| `show_security` | default on | a `MAIN`/`BASE` label per own base with its region's control and ground security |
| `draw_spacing` | `--spatial-view-spacing` | thins the markers to a coarser regular grid (`thin_samples`); the bot still reasons over every sample |

A screen panel shows sample counts per control, the number drawn, and the
frontline size.

## SVG snapshots

`SpatialSnapshotExporter` (enabled by `--spatial-snapshot`) renders a
deterministic SVG of the same snapshot every `interval_seconds` of game time
into `logs/game-<timestamp>/spatial/`:

- `territory-SSSS.svg` (or `territory-SSSS-mmm.svg` off whole seconds), and
  `latest.svg` rewritten each time;
- a restarted game clock (a new game in the same process) resets the cadence.

What one snapshot shows, bottom to top:

| Layer | Drawn as |
| --- | --- |
| Expansion slots | small grey rings |
| Possible enemy threat | translucent orange dots from the spatial threat field |
| Territory samples | dots coloured by actual control; radius grows with presence, opacity with dominance; red means enemy control, not uncertainty |
| Passages | cyan rings joined to their two region centres, labelled `H <hold>` |
| Regions | rings coloured by control at the centre, labelled with the region key |
| Frontline | white dots |
| Own bases | green squares: `MAIN`/`BASE [region] <control> \| Sec <security> Acc <access>` |
| Confirmed enemy bases | red diamonds, `EN BASE <key>` |
| Own forces | green rings sized by supply, `OWN <supply>` (the friendly clusters territory used) |
| Enemy forces | red bounded-control radius, dashed orange possible-presence radius, a supply ring, and labels for strength, confidence, uncertainty and both radii |
| Side panel | game time, sample counts per control, frontline, regions, passages, force counts, one line per base |

Each write logs `debug.spatial_snapshot_written`; any exception is caught and
logged as `debug.spatial_snapshot_failed`, never raised into the game. The
log viewer's Decision Timeline shows the nearest snapshot to the selected
time.
