# Persistent squads

`Squad` answers **who is together**; `Mission` answers **what they are doing
now**. The pilot lives in `bot/engine/squads/` and integrates with the existing
Planner -> MissionController -> UnitAllocator -> Executor flow without becoming
a second owner: `UnitAllocator` still holds every lease, and `SquadController`
never issues a command.

Each squad has a stable ID, role, member tags, a home mission key/ID, current
mission, and preemption return state (`Squad`, exposed as `SquadSnapshot`).

## Registry

A squad is created the first time `MissionController` admits a proposal whose
`squad_id` is set -- its *home* mission. Three planners declare one today:

| Squad | Role | Home mission key | Planner |
| --- | --- | --- | --- |
| `main_army` | `MAIN_ARMY` | `hold_rally:main_army` | `StandingPlanner` |
| `map_control` | `MAP_CONTROL` | `map_control:patrol` | `MapControlPlanner` |
| `banshee_harass` | `BANSHEE_HARASS` | `air_harass:enemy_natural` | `BansheeHarassPlanner` |

An unknown `squad_id` gets the `MAIN_ARMY` role. A squad keeps one home key for
life; admitting a different home key for the same squad raises.
`MissionProposal.squad_id` is optional, so unit-based missions (the scout, the
Reaper raid) are unaffected.

Home proposals are `MissionMode.STANDING` with stable deduplication keys, so the
mission ID survives every cadence tick and neither leases nor membership churn.

## Membership

Membership changes only after allocator results or observed unit death:

- When the **home** mission's allocation changes, membership becomes its
  assigned tags plus the members currently away on one of this squad's
  temporary missions. A tag that joins a home squad leaves every other squad.
- A **temporary** mission never redefines membership.
- `sync` drops dead members (`squad_membership_changed`, reason
  `members_lost`).

## Temporary missions: defense

A defense proposal does not name a squad. It asks for capability/composition
through `UnitRequirement`, and `SquadController.bind_compatible_squad` picks a
squad for it without exposing that choice to `DefensePlanner`. Only `DEFENSE`
missions are bound. A candidate squad must have a live home mission, must not
already be on another temporary mission, and must have at least
`requirement.minimum` members matching the requirement (availability ignored).
The squad with the most matching members (capped at `desired`) wins, then the
smallest summed distance to the target, then the squad ID.

Binding only turns that squad's members into *preferred* tags; the allocator
still applies priority, commitment window, utility and preemption cost. While
members are away, `effective_requirement` lowers the home mission's `desired`
by that many -- down to not allocating at all -- instead of filling their seats
with unrelated units. When the defense finishes, the squad returns home
(`squad_returned_home`) and the home mission preferentially reacquires the same
members.

Binding checks eligibility, not utility: a squad whose members are all worth
0.0 to this defense (Banshees against an air-only attack) can still be bound
and logged as preempted while the allocator pulls other units instead.

## Banshee harass

The Banshee option is gated through the small `StrategicIntent` interface
(`bot/behavior/strategy_intent.py`). The default implementation enables it for
the `BansheeCloak` opening; existence of a Banshee proves the build has reached
the executable part of that intent. Its standing executor survives repeated
attack -> retreat/recover -> attack cycles and waits with zero assigned units
during defense preemption.

## Events

Component `engine.squads.controller`: `squad_created`,
`squad_membership_changed`, `squad_mission_changed`, `squad_preempted`,
`squad_returned_home`. `standing.updated` also carries a snapshot of every
squad's members and current/home mission.
