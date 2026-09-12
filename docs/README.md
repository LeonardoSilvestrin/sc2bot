# Bot documentation

How the bot is built, from the one-page picture down to the formulas. Every
document names the modules it describes, and every number in it comes from
the code. When a change moves one of those numbers, the doc moves with it in
the same change.

Last verified against the code at commit `6cc8130` (2026-09-12).

## How the docs are layered

```text
Level 1  overview.md                 what the bot is, the pipeline, the layers, the vocabulary
Level 2  contracts.md                the dependency rules and invariants, and which test holds each
         frame-lifecycle.md          one frame, step by step; every cadence and time window
         logging.md                  every event the bot writes, and the log viewer
         app.md                      composition, runtime, run.py flags, telemetry, debug views
Level 3  world/  engine/  behavior/  macro/  strategy.md
                                     one document per component: data, algorithm, config, events, gaps
         history/                    records of past migrations and audits, not kept current
```

Start at level 1, go down only where the work is.

## Index

| Document | Covers | Status of what it describes |
| --- | --- | --- |
| [overview.md](overview.md) | The causal pipeline, the packages, the two domains, design principles, glossary | -- |
| [contracts.md](contracts.md) | Package dependency rules, ownership, invariants and the tests that enforce them, mission priorities | -- |
| [frame-lifecycle.md](frame-lifecycle.md) | `on_start`/`on_step`/`on_end`, the order of every step inside a frame, cadences and stale windows | live |
| [logging.md](logging.md) | JSONL format, the full event catalog by component, the log viewer, recipes for reading a game | live |
| [app.md](app.md) | `compose_bot`, `BotRuntime`, `FrameProcessor`, opening selection, telemetry reporters, spatial debug view and SVG snapshots, `run.py` | live |
| **World (read side)** | | |
| [world/attention.md](world/attention.md) | `WorldFacts` and everything `AresWorldObserver` extracts from Ares, including map topology | live |
| [world/awareness.md](world/awareness.md) | `AwarenessService`: enemy memory, enemy bases and forces, economy/army beliefs, macro posture, confidence semantics | live |
| [world/base-security.md](world/base-security.md) | Per-base threat/protection reading behind Defense | live |
| [world/spatial-field.md](world/spatial-field.md) | The sampled spatial field (friendly, threat, choke, route values) and its caches | live |
| [world/territory.md](world/territory.md) | Control, frontline and ground security of the map | shadow |
| **Engine (arbitration)** | | |
| [engine/missions.md](engine/missions.md) | `MissionController`, `UnitAllocator`, proposals, lifecycle modes, preemption, executor contract, command port | live |
| [engine/capabilities.md](engine/capabilities.md) | Unit capability profiles, suitability math, roles, capability-based allocation | live |
| [engine/squads.md](engine/squads.md) | Persistent squad identity and temporary missions | live |
| [engine/vision.md](engine/vision.md) | The shared active-vision service and the Scanner Sweep provider | live |
| [engine/economy.md](engine/economy.md) | `EconomyController`: the virtual bank, admission, dispatch, confirmation, the Ares economy adapter | live |
| **Behavior (units on the map)** | | |
| [behavior/README.md](behavior/README.md) | The behavior contract, the roster of all six behaviors with their mission parameters, shared helpers | live |
| [behavior/standing.md](behavior/standing.md) | The default owner of every idle combat unit (`main_army`) | live |
| [behavior/map-control.md](behavior/map-control.md) | The roaming patrol and its spatial anchor | live |
| [behavior/defense.md](behavior/defense.md) | Per-base defense, defender preference, vision for lost attackers, the Tank siege pilot | live, roles pilot |
| [behavior/harass.md](behavior/harass.md) | Reaper and Banshee raids: target scoring, launch gates, tactical loops | live |
| [behavior/scouting.md](behavior/scouting.md) | The routed Reaper scout and the scouting vision requester | live |
| **Macro (what to buy)** | | |
| [macro/macro-planner.md](macro/macro-planner.md) | `MacroPlanner`: army demand, production capacity, supply, workers, gas, expansion, add-ons, priorities | live |
| [macro/builds.md](macro/builds.md) | The Ares openings in `terran_builds.yml`, how one is picked, and each build's goal set | live (BattleMech only) |
| **Strategy** | | |
| [strategy.md](strategy.md) | Objective scoring and hysteresis in `bot/strategy` | shadow, not wired |
| **History** | | |
| [history/scout-pilot-migration.md](history/scout-pilot-migration.md) | What the first vertical slice kept from the old `ares` branch and what it dropped | record |
| [history/awareness-hardening.md](history/awareness-hardening.md) | The September 2026 audit of confidence semantics (Portuguese) | record |

Status words:

- **live** -- runs every game and decides something.
- **shadow** -- computed and logged, but no decision reads it; a test fails if one starts to.
- **pilot** -- live, but deliberately narrow; the doc lists what was left out.
- **not wired** -- code and tests exist; the game never runs it.
- **record** -- describes a moment in the project's history.

## Reading paths

- **New to the codebase:** [overview](overview.md) -> [contracts](contracts.md) -> [frame-lifecycle](frame-lifecycle.md) -> [behavior/README](behavior/README.md).
- **Changing a behavior:** [behavior/README](behavior/README.md) -> that behavior's doc -> [engine/missions](engine/missions.md) (arbitration) -> [engine/capabilities](engine/capabilities.md) if it asks for a role.
- **Changing what the bot builds:** [macro/builds](macro/builds.md) -> [macro/macro-planner](macro/macro-planner.md) -> [engine/economy](engine/economy.md).
- **Changing what the bot believes:** [world/attention](world/attention.md) -> [world/awareness](world/awareness.md) -> the reading's own doc.
- **Understanding a game from its logs:** [logging](logging.md) (recipes at the end) -> [app](app.md) for the SVG snapshots.

## Related places

- `logs/` -- the log viewer and one folder per local game (see [logging.md](logging.md)).
- `_botdev/notebook/` -- research notes, in Portuguese, on Ares features the bot does not use yet.
- `tests/test_*_architecture.py`, `tests/test_territory.py`, `tests/test_frame_processor.py` -- the executable form of [contracts.md](contracts.md).
