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

| Squad | Approximate share | Home mission | Priority |
| --- | ---: | --- | ---: |
| `main_army` | 80% (`StandingConfig.core_fraction`) | `HOLD_RALLY` | 20 |
| `map_control` | the remaining roaming share | `MAP_CONTROL` | 40 |

`StandingPlanner` emits one `MissionMode.STANDING` proposal for `main_army`;
`MapControlPlanner` emits the matching standing proposal for `map_control`.
Both carry a stable `squad_id`; neither planner allocates units or sends Ares
commands. There is no `position:reserve` catch-all.

## Assess -> plan -> execute

`StandingAssessor` reads held bases (ordered by distance from
`map.own_start`, the current lightweight proxy for expansion order),
threatened bases, pressure near our bases, and how many eligible combat units
exist. `derive_combat_posture` maps Awareness' `bases.threatened`,
`relative_strength` and `macro_posture` onto TURTLE / BALANCED / PRESSURE --
a different axis from `MacroPosture`, which is about spending risk rather
than where the army sits.

`StandingPlanner` turns that assessment into a `StandingPlan`: the anchor,
its reason, and `core_count`. With at least two bases the anchor is 72% of
the segment from the previous base to the newest/farthest expansion
(`anchor_fraction_to_newest_base`); with one base it is that base; with no
observed town hall it falls back to `own_start`. Posture does not move the
anchor yet -- that is the obvious next step, and the plan shape is what makes
it a small change rather than a restructure.

`StandingExecutor` moves only units outside `arrival_radius`, and always with
`keep_available=True` so a parked unit never looks busy to another planner.

## Ownership invariant

> Every available combat unit has a behavioral owner.

A unit with no special mission belongs to Standing. When a raid or a defense
needs it, `MissionController` transfers the lease; when that mission ends the
unit is released and Standing reacquires it. This is what keeps two behaviors
from commanding the same unit.

Two gaps remain between the invariant and the code, both deliberate:
`core_fraction` is 0.8 rather than 1.0 (the remainder is left free for
`MapControlPlanner` to claim rather than preempt), and Banshees are absent
from `StandingConfig.unit_types` so the harass squad does not have to preempt
Standing for every Banshee produced. `standing.unassigned_units_persisting`
fires when an eligible unit has had no owner for 15 seconds.

## Persistence and preemption

`MissionController` registers squad-backed home missions with
`SquadController`. `UnitAllocator` still owns every unit lease. The squad
layer only records membership and supplies preferred tags when the allocator
fills a mission.

A defense proposal declares a normal `UnitRequirement`. It does not name a
squad or unit. `SquadController` selects a compatible, currently unpreempted
squad from its members; the allocator then performs the actual priority,
utility and commitment-window checks. While members are away, the home
mission reduces its effective request instead of filling their seats with
unrelated replacements. When the temporary mission finishes, its leases are
released and the standing home mission preferentially reacquires the same
members.

Squad membership is durable identity, not a second lease table:

- `MissionController` alone changes mission lifecycle.
- `UnitAllocator` alone grants/transfers/releases exclusive unit leases.
- `SquadController` never executes micro and never calls Ares.
- Unit-based missions such as SCV scouting keep `squad_id=None`.

The relevant structured events are `standing.updated`,
`standing.unassigned_units_persisting`, `behavior.assessed`,
`behavior.proposed`, `behavior.state_changed`, `squad_created`,
`squad_membership_changed`, `squad_mission_changed`, `squad_preempted`, and
`squad_returned_home`.
