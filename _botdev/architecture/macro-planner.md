# Macro planner: economic vertical slice

This is the economic counterpart to the scout vertical slice, filling in the
work described as deferred in
[scout-pilot-migration.md](scout-pilot-migration.md): "The future economy
contract: `SpendProposal`, real resource reservations, and an
`EconomyController` remain intentionally unimplemented." It now covers both
halves: `MacroPlanner` argues for economic actions, and `EconomyController`
admits, reserves against, and executes them (see "Integration" below).

## Contracts

`bot/contracts/economy.py` adds:

- `EconomicActionKind` — `PRODUCE_WORKER`, `PRODUCE_SUPPLY`, `EXPAND`.
- `ResourceCost` — a declared `minerals`/`vespene`/`supply` cost. Building one
  never deducts or reserves anything; `affordable_with(...)` only compares
  against a bank the caller supplies.
- `EconomicProposal` — a planner's argument for one economic action. It is
  deliberately not a `MissionProposal`: it carries no `UnitRequirement` and no
  map `target`, because declaring an economic intent does not move or command
  a unit by itself. It does carry `priority`, `reason`, and `cost`, matching
  the `MissionProposal` convention of an explicit, non-empty reason.

## Planner

`bot/planners/macro.py` adds `MacroPlanner` (`MacroPlannerConfig` for
thresholds). `propose(attention, awareness)` is a pure function of its inputs
— no cadence state, no sequence counters — so it is trivially deterministic:
the same snapshot always yields the same tuple of proposals in the same order
(`PRODUCE_SUPPLY`, then `PRODUCE_WORKER`, then `EXPAND`).

### Decision rules

Townhall count is read from `WorldFacts.own_structures` (ready `CommandCenter`,
`OrbitalCommand`, `PlanetaryFortress`), floored at 1 so a snapshot without a
tracked townhall does not divide the ideal worker count to zero.
`ideal_workers = min(townhalls * workers_per_townhall, max_workers)`.

- **Worker production**: proposed when `workers < ideal_workers` and the
  worker cost is affordable (bank and remaining supply). Otherwise silent —
  including when resources are insufficient, since proposing an action the
  bot cannot currently take is not useful information.
- **Supply block prevention**: proposed when supply is not already at the
  absolute cap and `supply_cap - supply_used <= supply_buffer`, and the
  supply cost is affordable. This is the highest-priority rule by default,
  since a supply block stalls all other production.
- **Expansion**: proposed only once the current bases are saturated
  (`workers >= ideal_workers`), no enemy unit is currently visible
  (`AwarenessSnapshot.threat.visible_enemy_units == 0`), and the expansion
  cost is affordable. This is the one rule that reads `AwarenessSnapshot`
  directly, so expansion is withheld under visible threat even with a full
  bank.

All three rules gate on affordability using the proposal's own declared
`ResourceCost`. No reservation, deduction, or command happens anywhere in this
slice — `MacroPlanner` only ever returns proposals.

## Deliberately not built in this slice

- Expansion location selection beyond what Ares's own `ExpansionController`
  already resolves (see below) — this planner itself still declares no
  target; it only argues *that* an expansion is warranted.
- Production-queue/idle-structure awareness. `UnitSnapshot` has no "currently
  training" or order-queue signal yet, so this slice proposes based on counts
  and resources only, not on whether a townhall is currently idle (Ares's own
  macro behaviors, described below, do check idle state at execution time).

## Integration: `EconomyController`

`bot/ego/economy_controller.py` admits `EconomicProposal`s the way
`MissionController` admits `MissionProposal`s, sized down for the fact that
economic actions are single-frame and self-gating rather than multi-frame
unit commitments — no unit lease or executor lifecycle is needed.

- `bot/application/runtime.py` calls `MacroPlanner().propose(attention,
  awareness)` from the same frame step that collects `IntelPlanner`
  proposals, gated on `build_order_runner.build_completed` being true.
- `EconomyController.tick(...)` processes proposals by priority, reserving
  minerals/vespene against a running remainder seeded from the current bank
  so two proposals admitted in the same frame cannot both spend the same
  resources. Admitted proposals log `economy.proposal_admitted`; proposals
  that lose the in-tick reservation race log `economy.proposal_rejected`
  (`reason="insufficient_reserved_resources"`). Logging is transition-based
  (mirroring `MissionController._block`), so a proposal admitted across many
  consecutive frames logs once, not every tick; when a kind stops being
  proposed, `economy.action_resolved` is logged once.
- Execution goes through `EconomyCommands` (`bot/contracts/commands.py`),
  implemented by `AresEconomyCommands`
  (`bot/infrastructure/ares/commands.py`), which registers Ares's own macro
  behaviors: `BuildWorkers` for `PRODUCE_WORKER`, `AutoSupply` for
  `PRODUCE_SUPPLY` (at `WorldFacts.map.own_start`), and `ExpansionController`
  for `EXPAND` (`to_count` = current ready townhalls, via
  `ready_townhall_count`, plus one). These Ares behaviors own worker
  selection, structure placement, and expansion-site selection themselves;
  `MacroPlanner` only argues that the action is warranted and affordable.
