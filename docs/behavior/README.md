# Behaviors

A behavior governs units already on the map: who goes where and does what.
What the bot buys is not a behavior ([macro](../macro/macro-planner.md)). A
behavior may read what exists -- how many Banshees are alive, whether cloak is
researched -- but never proposes spend.

Source: `bot/behavior/` (`contracts.py`, `strategy_intent.py`, one folder per
behavior), `bot/engine/missions/planning.py`.

## The shape of a behavior

Every behavior is a folder answering the same four questions in the same
place:

```text
bot/behavior/<behavior>/
  model.py        the config and the types the three below share
  assessment.py   ASSESS   what is the situation, through this behavior's lens?
  planner.py      PLAN     what do we want, at what priority, with which units?
  executor.py     EXECUTE  how do we make it happen this frame?
```

Between PLAN and EXECUTE sits the mission engine, which the behavior does not
control: `MissionController` admits the proposal and `UnitAllocator` leases
the units ([engine/missions.md](../engine/missions.md)).

`contracts.py` fixes the vocabulary as small protocols, not base classes:

| Protocol | Contract |
| --- | --- |
| `BehaviorAssessment` | `log_fields() -> dict`: the handful of numbers worth logging. Data, never a decision. |
| `BehaviorAssessor` | `assess(attention, awareness) -> BehaviorAssessment`. Reads the world model only; never missions, leases or a private copy of Awareness. |
| `BehaviorPlanner` | `planner_id`; `propose(attention, awareness) -> tuple[MissionProposal, ...]`. Proposes, never commands. |
| `BehaviorExecutor` | `mission_id`; `async step(context) -> MissionResult`. Commands only the units its mission leases. |

The rules that keep this true, and their tests, are rules 4, 5, 8, 14 and 15
in [contracts.md](../contracts.md#rules).

## Roster

Six behaviors, wired by `compose_bot` in this order.

| Behavior | Planner -> executor | Kind | Priority | Mode | Deduplication key | Squad | Requirement | Preempts |
| --- | --- | --- | ---: | --- | --- | --- | --- | --- |
| [scouting](scouting.md) | `IntelPlanner` -> `ScoutExecutor` | `SCOUT` | 65 | FINITE | `scout:<target>` | -- | 1 Reaper (1 SCV when no Reaper is alive), health >= 0.70 | **no** |
| [harass/reaper](harass.md#reaper-raid) | `ReaperHarassPlanner` -> `ReaperHarassExecutor` | `HARASS` | 60 | FINITE | `harass:<target>` | -- | 1 Reaper, health >= 0.5 | yes |
| [harass/banshee](harass.md#banshee-raid) | `BansheeHarassPlanner` -> `BansheeHarassExecutor` | `AIR_HARASS` | 62 | STANDING | `air_harass:banshee_harass` | `banshee_harass` | every Banshee alive, minimum 0, health >= 0.5 | yes |
| [defense](defense.md) | `DefensePlanner` -> `DefendBaseExecutor` | `DEFENSE` | 85 / 95 | FINITE | `defense:<base_id>` | bound to a compatible squad | 1..6 of Marine, Marauder, Reaper, Siege Tank, Banshee, health >= 0.3, preference by attack type | yes |
| [map_control](map-control.md) | `MapControlPlanner` -> `MapControlExecutor` | `MAP_CONTROL` | 40 | STANDING | `map_control:patrol` | `map_control` | role `MOBILE_CONTROL`, 20% of combat supply, health >= 0.7, minimum 0 | yes |
| [standing](standing.md) | `StandingPlanner` -> `StandingExecutor` | `HOLD_RALLY` | 20 | STANDING | `hold_rally:main_army` | `main_army` | every combat unit, minimum 0 | yes |

Timing:

| Behavior | Cadence | Cadence consumed | Worker gate | Commitment | Timeout | Cooldown |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| scouting | 65 s | only when proposing | 16 | 5 s | 105 s | 18 s |
| harass/reaper | 45 s | only when proposing | 16 | 5 s | 60 s | 30 s |
| harass/banshee | 8 s | only when proposing | 12 | 5 s | never (standing) | 30 s |
| defense | 5 s | only with a threatened base | -- | 3 s | 120 s | 10 s |
| map_control | 15 s | only with >= 6 combat supply | -- | 1 s | never (standing) | 15 s |
| standing | 5 s | always | -- | 2 s | never (standing) | 5 s |

Two more requesters produce vision requests instead of missions: the scouting
vision requester and Defense's lost-attacker request
([engine/vision.md](../engine/vision.md)).

## Shared helpers

- **`BehaviorLog`** -- one behavior's slice of the log, a no-op without a
  logger (tests construct behaviors far more often than games do). Verbs:
  `assessed(assessment, decision=)`, `proposed(plan, **extra)`,
  `state_changed(state=, reason=, **extra)`, and `event(name, **data)` for
  anything else. The component is `behavior.<folder>`.
- **`ProposalCadence`** -- rate limit plus stable sequence numbers for
  `proposal_id`s. Planners that withhold do not mark it, so a withheld
  decision is re-evaluated next frame.
- **`choose_target`** -- hold a target until another candidate beats it by a
  margin ([engine/missions.md](../engine/missions.md#planning-helpers-planningpy)).
- **`BehaviorServices`** -- shared capabilities; today only `vision`. Planners
  receive it at construction, executors as `context.services`.
- **`StrategicIntent`** (`strategy_intent.py`) -- the one place a behavior
  learns about the build. `BuildStrategicIntent.allows(capability, world)`
  maps the chosen opening to tactical capabilities: `BansheeCloak` and
  `BattleMech` allow `banshee_harass`.

## Commands a behavior can issue

Only through `context.commands` (`MissionCommands`), only for its leased
units: `path_to`, `safe_path_to`, `attack_move`, `attack_unit`,
`use_ability`, `release`. What each does in Ares is in
[contracts.md](../contracts.md#command-port-what-each-command-leaves-behind-rule-9).

## Adding a behavior

1. Create `bot/behavior/<name>/` with the five files; put a validated config
   dataclass in `model.py`.
2. `assessment.py`: read Attention and Awareness only; give the assessment
   `log_fields()`.
3. `planner.py`: use `ProposalCadence`; build stable ids
   (`<planner_id>:...:<sequence>`), a deduplication key, a reason, and a
   requirement from `UnitRequirement.combat`, `for_role` or `any_combat_unit`.
   A generic job asks for a role; only a behavior whose identity is a unit
   names it.
4. `executor.py`: subclass `MissionExecutor`; implement `refresh` for a
   standing mission, `preemption_cost` if interrupting it is expensive.
5. Add a `MissionKind` if needed and register its factory in
   `bot/app/mission_registry.py` (a test requires every kind registered).
6. Construct the planner in `compose_bot` and add it to `mission_planners`.
7. Add the folder to `VERTICAL_BEHAVIORS`, `ASSESSORS` and `PLANNERS` in
   `tests/test_behavior_architecture.py`.
8. Document it: a page here, a row in the roster, its events in
   [logging.md](../logging.md), its priority in
   [contracts.md](../contracts.md#mission-kinds-and-priorities).
