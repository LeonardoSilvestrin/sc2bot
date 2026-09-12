# Persistent squads

`Squad` answers **who is together**; `Mission` answers **what they are doing
now**. The squad layer integrates with the planner -> `MissionController` ->
`UnitAllocator` -> executor flow without becoming a second owner:
`UnitAllocator` still holds every lease, and `SquadController` never issues a
command.

Source: `bot/engine/squads/` (`models.py`, `controller.py`), called from
`bot/engine/missions/controller.py`.

## Model

`Squad` (exposed as the immutable `SquadSnapshot`):

| Field | Meaning |
| --- | --- |
| `squad_id` | stable id from the home proposal's `squad_id` |
| `role` | `SquadRole`: `MAIN_ARMY`, `MAP_CONTROL`, `BANSHEE_HARASS` |
| `home_mission_key` | the deduplication key of its home mission, fixed for life |
| `member_tags` | who belongs to the squad |
| `home_mission_id` | the live home mission, `None` while it has none |
| `current_mission_id`, `current_mission_key` | what the squad is doing now (home or temporary) |
| `preempted_from_mission_id` | the mission it was pulled from for a temporary mission |

## Registry

A squad is created the first time `MissionController` admits a proposal whose
`squad_id` is set -- its **home** mission. Three planners declare one:

| Squad | Role | Home mission key | Planner |
| --- | --- | --- | --- |
| `main_army` | `MAIN_ARMY` | `hold_rally:main_army` | `StandingPlanner` |
| `map_control` | `MAP_CONTROL` | `map_control:patrol` | `MapControlPlanner` |
| `banshee_harass` | `BANSHEE_HARASS` | `air_harass:banshee_harass` | `BansheeHarassPlanner` |

- An unknown `squad_id` gets the `MAIN_ARMY` role.
- A squad keeps one home key for life; admitting a different home key for the
  same squad raises.
- Home proposals are `STANDING` with stable keys, so the mission id survives
  every cadence tick and neither leases nor membership churn.
- Unit-based missions (the scout, the Reaper raid) leave `squad_id=None` and
  are unaffected.

## Membership

Membership changes only after allocator results or observed unit death:

- When the **home** mission's allocation changes, membership becomes its
  assigned tags plus the members currently away on a temporary mission bound
  to this squad. A tag that joins a home squad leaves every other squad.
- A **temporary** mission never redefines membership.
- `sync` drops dead members (`squad_membership_changed`, `members_lost`).

## Temporary missions: defense

A defense proposal does not name a squad. It asks for defenders through its
`UnitRequirement`, and `SquadController.bind_compatible_squad` picks a squad
for it without `DefensePlanner` knowing. Only `DEFENSE` missions are bound,
once, before their allocation.

A candidate squad must:

- have a live home mission;
- not already be on another temporary mission;
- have at least `requirement.minimum` members matching the requirement
  (availability ignored).

The squad with the most matching members (capped at `desired`) wins, then the
smallest summed distance to the target, then the squad id. The squad logs
`squad_preempted` and `squad_mission_changed`.

What binding changes:

- **Preferred tags.** The squad's members rank first for the defense mission
  in the allocator. Priority, commitment windows, utility and preemption cost
  still apply, so binding never forces a transfer.
- **The home mission shrinks.** While members are leased by the bound
  temporary mission, `effective_requirement` lowers the home mission's
  `desired` by that many and its `supply_budget` by their supply. When nothing
  is left to ask for, the home mission does not allocate at all instead of
  filling their seats with unrelated units.
- **Return home.** When the defense finishes, the squad's current mission goes
  back to its home (`squad_returned_home`), and the home mission, preferring
  its members, reacquires them on its next allocation.

Binding checks eligibility, not utility: a squad whose members are all worth
0.0 to this defense (Banshees against an air-only attack) can still be bound
and logged as preempted while the allocator pulls other units instead.

When a **home** mission finishes, the squad keeps its members and simply has
no home mission until its planner declares one again.

## Events

Component `engine.squads.controller`: `squad_created`,
`squad_membership_changed`, `squad_mission_changed`, `squad_preempted`,
`squad_returned_home` (fields in [logging.md](../logging.md#enginesquadscontroller)).
`standing.updated` also carries every squad's members and current/home
mission.

## Known gaps

- Only `DEFENSE` binds squads; no other temporary mission kind exists yet.
- Squads never move as a group: membership is identity and allocation
  preference, not formation or group micro.
