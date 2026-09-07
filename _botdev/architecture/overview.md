# Pilot architecture

The official architecture is a one-way causal flow:

```text
Game / Ares
    -> Attention (selected current observations)
    -> Awareness (memory and derived beliefs)
    -> Planners (independent arguments)
    -> MissionProposal
    -> Ego / MissionController (admission and arbitration)
    -> MissionBoard + UnitAllocator (commitments and leases)
    -> MissionExecutor
    -> infrastructure command port
    -> Ares Behaviors
```

## Ownership

- `attention` publishes immutable current facts. It contains no beliefs or mission
  bookkeeping.
- `awareness` owns persistent enemy sightings and typed freshness beliefs.
- `planners` propose useful work. They never allocate or command units.
- `ego` is the only domain allowed to admit proposals, change mission lifecycle,
  transfer leases, or release units.
- `executors` implement one admitted mission and use only explicit command ports.
- `infrastructure/ares` translates those ports into Ares roles and behaviors.
- `application` wires the frame together without containing strategic rules.

The first vertical slice scouts the enemy natural. Unknown information creates an
initial scout after the economy reaches 16 workers. A location observed previously
can be scouted again after 240 game-seconds when its observation is at least 90
seconds old. These values live in `IntelPlannerConfig`.

Five mission planners are wired into `BotRuntime` today, each with its concrete
executor under `bot/behavior/<kind>/`: `IntelPlanner` (scouting, above),
`HarassPlanner` (worker-line harass), `BansheeHarassPlanner` (cloaked Banshee
harass), `DefensePlanner` (base defense), and `MapControlPlanner` (safe map
presence). See
[harass-and-defense-planners.md](harass-and-defense-planners.md) for their
conditions, priorities, and the `attack_move` command port they share.
`MacroPlanner` produces `EconomicProposal`s instead of `MissionProposal`s and is
admitted by `bot/engine/economy`; see [macro-planner.md](macro-planner.md).
