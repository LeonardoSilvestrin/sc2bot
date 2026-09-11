# Standing behavior (the default owner)

`bot/behavior/standing/` is the behavior every combat unit belongs to when no
special mission has claimed it. It is a vertical slice like any other:

```text
behavior/standing/
  model.py        CombatPosture, StandingConfig, StandingAssessment, StandingPlan
  assessment.py   StandingAssessor, derive_combat_posture
  planner.py      StandingPlanner -- one STANDING HOLD_RALLY proposal
  executor.py     StandingExecutor -- keeps the core army on the anchor
```

| Squad | Share | Home mission | Priority |
| --- | --- | --- | ---: |
| `main_army` | every eligible unit no higher-priority mission holds | `HOLD_RALLY` | 20 |
| `map_control` | 20% of healthy Marines, preempted from `main_army` | `MAP_CONTROL` | 40 |

`StandingPlanner` emits one `MissionMode.STANDING` proposal for `main_army`
every 5 s (key `hold_rally:main_army`, `minimum=0`, `can_preempt=True`);
`MapControlPlanner` emits the matching standing proposal for `map_control`
(see [map-control.md](map-control.md)). Both carry a stable `squad_id`; neither
planner allocates units or sends Ares commands. There is no `position:reserve`
catch-all. The two are sized independently: the core asks for every eligible
combat unit, the patrol for a share of the Marines, which it preempts from the
core.

## Assess -> plan -> execute

`StandingAssessor` reads held bases (ordered by distance from
`map.own_start`, the current lightweight proxy for expansion order),
threatened bases, pressure near our bases, and how many eligible combat units
exist (ready units of `StandingConfig.unit_types`). `derive_combat_posture`
maps Awareness' `bases.threatened`, the stabilized army belief and
`macro_posture` onto a `CombatPosture` -- a different axis from `MacroPosture`,
which is about spending risk rather than where the army sits:

| Posture | When |
| --- | --- |
| `TURTLE` | a base is threatened, macro posture is `DEFENSE`/`RECOVERY`, or the army belief is stably `BEHIND` with confidence >= 0.35 |
| `PRESSURE` | the army belief is stably `AHEAD` with confidence >= 0.60 and no enemy combat unit is near our bases |
| `BALANCED` | otherwise |

`StandingPlanner` turns that assessment into a `StandingPlan`: the anchor,
its reason, and `core_count = max(1, eligible)` -- every eligible unit, not a
share (see the ownership invariant below). With at
least two bases the anchor is 72% of the segment from the previous base to the
newest/farthest expansion (`anchor_fraction_to_newest_base`); with one base it
is that base; with no observed town hall it falls back to `own_start`. Posture
is computed and logged (`StandingPlanner.last_posture`) but does not move the
anchor yet -- that is the obvious next step, and the plan shape is what makes
it a small change rather than a restructure. The planner logs
`behavior.assessed`/`behavior.proposed` only when the anchor, the core count or
the posture changes.

`StandingExecutor` moves only units outside `arrival_radius` (4), and always
through `safe_path_to` with `keep_available=True`, so a parked unit keeps the
`IDLE` role and never looks busy to another planner. It never completes or
fails; with zero units it simply waits. Each anchor change is logged as
`behavior.state_changed` (`ANCHORED`).

## Ownership invariant

> Every available combat unit has a behavioral owner.

A unit with no special mission belongs to Standing. When a raid or a defense
needs it, `MissionController` transfers the lease; when that mission ends the
unit is released and Standing reacquires it. This is what keeps two behaviors
from commanding the same unit.

Standing asks for every eligible unit rather than a share, which is what makes
it the fallback: whatever no higher-priority mission holds -- before
`MapControlPlanner` has enough Marines to start, or once a temporary mission
releases its units -- is picked up on the next allocation pass. Anything
allowed to preempt (map control, defense, harass) outranks Standing by at least
the allocator's margin, so it takes its share exactly as before, and Standing
can never take it back. A unit produced between two Standing proposals waits at
most one 5 s cadence for the updated count.

Two gaps remain. Banshees are deliberately absent from
`StandingConfig.unit_types`, so the harass squad does not have to preempt
Standing for every Banshee produced. And scouting never preempts, so a scout
proposed while every Reaper sits in Standing stays blocked rather than taking
one. `standing.unassigned_units_persisting` fires when an eligible unit has had
no owner for 15 seconds.

## Persistence and preemption

`MissionController` registers squad-backed home missions with
`SquadController`. `UnitAllocator` still owns every unit lease. The squad
layer only records membership and supplies preferred tags when the allocator
fills a mission. As a `STANDING` mission, the home mission never times out and
its proposal is updated in place every cadence tick.

A defense proposal declares a normal `UnitRequirement`. It does not name a
squad or unit. `SquadController` selects a compatible, currently unpreempted
squad from its members; the allocator then performs the actual priority,
utility and commitment-window checks. While members are away, the home
mission reduces its effective request instead of filling their seats with
unrelated replacements. When the temporary mission finishes, its leases are
released and the standing home mission preferentially reacquires the same
members. Details in [squads.md](squads.md).

Squad membership is durable identity, not a second lease table:

- `MissionController` alone changes mission lifecycle.
- `UnitAllocator` alone grants/transfers/releases exclusive unit leases.
- `SquadController` never executes micro and never calls Ares.
- Unit-based missions such as SCV scouting keep `squad_id=None`.

The relevant structured events are `standing.updated`,
`standing.unassigned_units_persisting`, `standing_mission_updated`,
`behavior.assessed`, `behavior.proposed`, `behavior.state_changed`,
`squad_created`, `squad_membership_changed`, `squad_mission_changed`,
`squad_preempted`, and `squad_returned_home`.
