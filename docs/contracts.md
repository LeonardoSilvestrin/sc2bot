# Contracts

The rules that keep the layers in [overview.md](overview.md) apart, who owns
each decision, and the tests that fail when a rule erodes. Mission-level
detail (admission, allocation, loss and cleanup) is in
[engine/missions.md](engine/missions.md); the per-frame order is in
[frame-lifecycle.md](frame-lifecycle.md).

## Package dependencies

Allowed imports, top to bottom. Anything not listed is not allowed.

```text
bot.ports             nothing from bot (type-only imports of engine models)
bot.world.attention   nothing from bot
bot.world.awareness   world.attention, ports.logging
bot.strategy          the standard library; its boundary modules
                      (awareness_adapter, spatial/policy) also world.awareness
bot.engine.services   world.attention, ports
bot.engine.missions   world, engine.services, engine.squads, ports
bot.engine.squads     engine.missions (models, allocator), world.attention, ports
bot.engine.economy    world.attention, ports
bot.behavior          engine.missions, engine.services, world, ports,
                      strategy contracts (MissionSignals, ControlMatch,
                      StrategicActivity, StrategicContext, ControlObjective,
                      ControlTargetKind, SpatialStrategySnapshot)
bot.macro             engine.economy, world, ports
bot.adapters.ares     ares, sc2, world.attention facts, engine models the ports carry
bot.app               everything: the composition root
```

```mermaid
flowchart TD
    app["bot.app"] --> behavior["bot.behavior"]
    app --> macro["bot.macro"]
    app --> adapters["bot.adapters"]
    behavior --> missions["bot.engine.missions"]
    behavior --> services["bot.engine.services"]
    macro --> economy["bot.engine.economy"]
    missions --> squads["bot.engine.squads"]
    missions --> services
    behavior --> awareness["bot.world.awareness"]
    macro --> awareness
    missions --> awareness
    awareness --> attention["bot.world.attention"]
    economy --> attention
    services --> attention
    adapters --> attention
    app --> strategy["bot.strategy"]
    behavior -->|contracts only| strategy
    strategy -->|boundary modules| awareness
```

## Rules

Each rule names what enforces it. "Review" means no test does yet.

| # | Rule | Enforced by |
| --- | --- | --- |
| 1 | **Attention is one frame of facts.** It holds only state observable now, as immutable dataclasses, never an Ares object. `AresWorldObserver` is the only code that reads Ares to build facts. | review |
| 2 | **Enemy memory follows Ares.** Each enemy unit carries Ares' own visible/memory flag (`UnitSnapshot.visible_now`); a scouted structure in fog arrives as a game snapshot and is flagged the same way. `EnemyKnowledge` keeps a sighting only while Ares still reports the tag. Force clusters inherit that lifetime. Only `EnemyRoster` keeps units longer -- until the game reports them dead -- and only for counting. | `test_enemy_knowledge.py`, `test_awareness_belief.py` |
| 3 | **Awareness describes.** No controller state, lease, cooldown or mission status enters it, and it decides nothing: no Awareness type has an intent, desired, objective, priority or posture field, and `bot.world` never imports Strategy, macro, behavior or the app. Macro's posture is macro's, delivered as `MacroContext` by `bot.app`. Stable belief changes leave as `AwarenessSnapshot.belief_changes`, which `FrameProcessor` logs. Its only direct log output is the cost heartbeat (`spatial.perf`, `territory.perf`) through the injected logger port. | review |
| 4 | **An assessment is a reading.** A behavior's `assessment.py` reads Attention and Awareness only -- never `bot.engine` or `bot.app` -- and its result carries no `mission_id`, `assigned_units`, `status` or `owner`. | `test_behavior_architecture.py` (`AssessmentIndependenceTests`) |
| 5 | **A planner proposes.** It returns immutable proposals and never claims a unit or starts a mission. It may ask a shared service for an outcome (rule 12). | `test_behavior_architecture.py` (`BehaviorShapeTests`) |
| 6 | **`MissionController` alone admits.** It admits and rejects proposals and changes mission status. It never names a `MissionKind` or a behavior: it looks each kind up in the executor table `bot/app/mission_registry.py` hands it, and every kind is registered. | `test_behavior_architecture.py` (`MissionControllerGenericityTests`) |
| 7 | **`UnitAllocator` alone leases.** It is the only writer of the unit-to-mission leases. `SquadController` records membership and preferred tags; it is not a second owner and never commands. | `test_allocator.py`, `test_squad_controller.py` |
| 8 | **Executors command only what they lease.** Commands go through `MissionCommands`; `AresMissionCommands` raises `UnauthorizedUnitCommand` for a unit the calling mission does not lease. Executors may use `context.services`. Every `MissionResult` has a non-empty reason. | `test_ares_commands.py`; `MissionResult` raises |
| 9 | **Only the Ares adapters touch Ares.** They assign Ares roles and register Ares behaviors; each command sets its own role whatever mission calls it (table below). | review |
| 10 | **Behavior and macro stay apart.** `bot.behavior` never imports `bot.macro` or `bot.engine.economy`. `bot.macro` never imports `ares`, `bot.adapters`, `bot.app`, `bot.behavior`, `bot.engine.missions` or `bot.engine.squads`. Neither engine imports `bot.macro`; `bot.engine.economy` never imports missions or squads. The generic spend folders (`production/`, `construction/`, `expansion/`) name no army unit; each registered build owns `builds/<name>/plan.py`. | `test_macro_architecture.py` |
| 11 | **`EconomyController` alone spends.** It admits, reserves and dispatches through `EconomyCommands`. The SCV that lays a structure is picked by the Ares behavior; Ares marks it `UnitRole.BUILDING`, which Attention reports as unavailable for missions. That is builder selection, never a lease. | `test_economy_controller.py` |
| 12 | **Shared capabilities are services.** They live in `bot/engine/services` and reach behaviors as `BehaviorServices` (planners at construction, executors as `context.services`). A behavior asks for an outcome -- vision at a position, with urgency and TTL -- and never names the provider. `bot.engine` never imports `bot.behavior`. | `test_behavior_architecture.py`, `test_vision_consumers.py` |
| 13 | **Doctrine is macro's.** `CompositionDoctrine` appears only under `bot/macro`; the mission engine never mentions doctrine, and `UnitRequirement` has no doctrine, preference-list or capability field. | `test_behavior_architecture.py` (`ConcreteUnitRequirementTests`) |
| 14 | **Behaviors request the concrete units they can use.** Every planner builds its requirement with `UnitRequirement.combat(unit_types=...)` from its own roster: Standing's explicit `STANDING_ROSTER`, Map Control's `PATROL_UNIT_TYPES`, each raid its own unit, Defense its defender set. Per-type preference is local (`type_desirability`) and may only price requested types. No global capability sheet, role or suitability exists, and the mission engine names no unit type. A type a registered build produces is on Standing's roster or explicitly declared unarmed support. | `test_behavior_architecture.py` (`ConcreteUnitRequirementTests`), `test_unit_requirements.py` |
| 15 | **Every behavior is a vertical folder** holding exactly `__init__.py`, `model.py`, `assessment.py`, `planner.py`, `executor.py`. | `test_behavior_architecture.py` (`BehaviorShapeTests`) |
| 16 | **Territory types stay out of macro and the mission engine.** No module under `bot/macro` or `bot/engine` mentions `.territory` or a `*Territory*` name. Strategy's `spatial/policy.py` derives control objectives from regions and passages; behaviors may read the topology for tactics (Defense holds the passage into an attacked base's region); Awareness projects generic sample control/knowledge onto `SpatialField`; `bot/app` may read the full snapshot for telemetry/debug. | `test_territory.py` (`ConsumerTests`) |
| 17 | **Strategy is pure and consumed only through its contracts.** Its core (`model`, `config`, `scoring`, `hysteresis`, `director`, `intent`, `mission_policy`) imports only itself and the standard library; only `awareness_adapter.py` and `spatial/policy.py` read Awareness; nothing in it reaches behavior, engine, macro, app or adapters, or performs I/O. Only `bot/app/strategy_runtime.py` drives the director; behaviors import only the context and signal contracts and never read the objective; only `bot/app/mission_ranking.py` prices candidates; the engine never names a strategic concept. | `test_strategy_architecture.py`, `test_decision_pipeline_architecture.py` |
| 18 | **Observers change nothing.** Telemetry and the debug view/SVG exporter read snapshots, derive no world state, and never stop a match: the exporter catches every exception and logs it. | review; `test_spatial_snapshot.py` |
| 19 | **The ladder writes nothing.** `MyBot` defaults to `NullBotLogger`; `run.py` opens a JSONL log and the SVG exporter only for local games, and never enables the debug view or snapshots when `--LadderServer` is present. | `test_run.py`, `test_contracts.py` |
| 20 | **The frame order is fixed.** Vision needs are collected before they are resolved, leases are synced before macro reads the frame, diagnostics run after both domains. | `test_frame_processor.py` |

### Command port: what each command leaves behind (rule 9)

| `MissionCommands` method | Ares behavior registered | Role assigned |
| --- | --- | --- |
| `path_to` | `CombatManeuver(KeepUnitSafe, PathUnitToTarget)`, danger distance 24; climber grid for Reapers, ground grid otherwise | `SCOUTING`; a worker is also removed from its mineral line |
| `safe_path_to` | `MoveToSafeTarget`, danger distance 24, search radius 14 by default; climber grid for Reapers | `MAP_CONTROL`, or `IDLE` with `keep_available=True` |
| `attack_move` | `AMove` | `ATTACKING` |
| `attack_unit` | `CombatManeuver(ReaperGrenade (Reapers only), StutterUnitForward)` | `HARASSING` |
| `use_ability` | `UseAbility` | unchanged |
| `release` | -- | `GATHERING` for workers, `IDLE` otherwise |

Attention reports every own unit whose Ares role is neither `GATHERING` nor
`IDLE` as `available_for_mission=False`. That is why a parked standing unit
keeps `IDLE`: it must stay visible to planners that gate on availability.

Ares clears registered behaviors after each step, so `Mining`, `DepotToggle`
and every mission command are registered again every frame.

## Mission kinds and priorities

`MissionKind` is the shared vocabulary: `SCOUT`, `HARASS`, `AIR_HARASS`,
`DEFENSE`, `MAP_CONTROL`, `HOLD_RALLY`, `POSITION`. `POSITION` has no planner
today; it is registered to the standing executor for compatible callers.

No planner sets a priority. Each drafts its proposal at `UNRANKED_PRIORITY`
and describes the work as `MissionSignals`; the Mission Policy evaluates every
candidate under the current `StrategicIntent`
([strategy.md](strategy.md#mission-policy)) and only then does anything reach
`MissionController`:

| Outcome | Priority | Reaches `MissionController` |
| --- | ---: | --- |
| fallback owner (`StandingPlanner`) | 20 | yes |
| viable: final utility > 0, after the emergency floor | `30 + round(70 * utility)`, 30..100 | yes |
| rejected: final utility <= 0 | none | no; logged as `mission.evaluated` with `viable: false` |

| Kind | Planner | Mode | `can_preempt` |
| --- | --- | --- | --- |
| `HOLD_RALLY` | `StandingPlanner` | STANDING | yes |
| `MAP_CONTROL` | `MapControlPlanner` | STANDING | yes |
| `HARASS` | `ReaperHarassPlanner` | FINITE | yes |
| `AIR_HARASS` | `BansheeHarassPlanner` | STANDING | yes |
| `SCOUT` | `IntelPlanner` | FINITE | **no** |
| `DEFENSE` | `DefensePlanner` | FINITE | yes |

- Every viable mission clears the standing army by at least `UnitAllocator`'s
  preemption margin (10), so it can take units from it. A rejected candidate
  is never admitted and so can neither lease nor preempt.
- A standing responsibility whose re-declared candidate is rejected is
  withdrawn: the app names its planner in `declared_planners`, so the
  controller cancels the live mission (`standing_proposal_omitted`) and its
  units return to the standing army.
- Between two viable missions the policy's utility decides the order;
  preemption still needs the 10-point margin plus the owner's preemption
  cost, so near-equal missions do not trade units.
- Every kind except `SCOUT` can preempt, because the standing army holds most
  idle combat units: without preemption no opportunistic mission could get a
  unit at all.
- `SCOUT` never preempts: information is worth a spare unit, not an
  interrupted raid. The known cost is that a scout proposed while every Reaper
  sits in the standing army stays blocked.
- An urgent defense keeps a floor regardless of intent (utility >= 0.95 at
  urgency 1), so it stays viable and far above any raid even when Strategy
  wants no defense.

The full parameter set of every planner is in
[behavior/README.md](behavior/README.md#roster).
