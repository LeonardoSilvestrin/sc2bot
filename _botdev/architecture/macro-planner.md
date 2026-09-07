# Macro planner: first economic vertical slice

This is the first slice of the macroeconomic planning described as deferred work
in [scout-pilot-migration.md](scout-pilot-migration.md): "The future economy
contract: `SpendProposal`, real resource reservations, and an
`EconomyController` remain intentionally unimplemented." This slice implements
the planning half only. Admission, reservation, and execution stay
unimplemented on purpose.

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

- Any connection to `bot/application/runtime.py`, `MissionController`, or a
  new `EconomyController`. Nothing admits, arbitrates, or executes these
  proposals yet.
- Real resource reservation semantics (declared out of scope in
  [scout-pilot-migration.md](scout-pilot-migration.md) for the same reason the
  old `ResourceReserve` was dropped: declarative reservations with no
  effective enforcement add machinery without behavior).
- Expansion location selection. `EconomicProposal` has no target; picking
  *where* to expand is a future planner concern once map facts expose
  expansion sites.
- Build-order/tech interaction. This planner does not know about the
  `BuildOrderRunner` opening from [opening.md](opening.md); it is only meant
  to take over once `build_order_runner.build_completed` is true.
- Production-queue/idle-structure awareness. `UnitSnapshot` has no "currently
  training" or order-queue signal yet, so this slice proposes based on counts
  and resources only, not on whether a townhall is currently idle.

## Future integration point (not implemented here)

A future task must, without changing this planner's contract:

1. Call `MacroPlanner().propose(attention, awareness)` from the same frame
   step in `bot/application/runtime.py` that currently collects
   `IntelPlanner` proposals, once the opening's `build_completed` flag is
   true.
2. Introduce whatever admits `EconomicProposal`s — an `EconomyController`
   analogous to `MissionController`, or an extension of it — that decides
   real spending order, applies real resource reservation, and logs
   `proposal_admitted`/`proposal_rejected` for these proposals the same way
   `MissionController` does for scouting.
3. Add the execution side: something that turns an admitted `PRODUCE_WORKER`
   into a real train command, `PRODUCE_SUPPLY` into a depot placement, and
   `EXPAND` into a chosen expansion location plus a build command — all
   through explicit command ports, per the dependency rules in
   [contracts.md](contracts.md).
4. Decide expansion-site selection, which base to train workers from, and
   where to place supply — none of which this slice needs, since it never
   executes anything.
