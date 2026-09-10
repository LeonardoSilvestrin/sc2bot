# Persistent squads

`Squad` answers **who is together**; `Mission` answers **what they are doing
now**. The pilot lives in `bot/engine/squads/` and integrates with the existing
Planner -> MissionController -> UnitAllocator -> Executor flow.

Each squad has a stable ID, role, member tags, a home mission key/ID, current
mission, and preemption return state. The initial registry contains squads only
when their home proposals become relevant:

- `main_army` / `MAIN_ARMY`
- `map_control` / `MAP_CONTROL`
- `banshee_harass` / `BANSHEE_HARASS`

`MissionProposal.squad_id` is optional, preserving all unit-based missions.
Home proposals set it explicitly. A temporary defense does not: it asks for
capability/composition through `UnitRequirement`, and `SquadController` binds a
compatible squad without exposing that choice to `DefensePlanner`.

Membership changes only after allocator results or observed unit death. Stable
deduplication keys plus `MissionMode.STANDING` preserve mission IDs and avoid
lease/squad churn between cadence ticks.

The Banshee option is gated through the small `StrategicIntent` interface. The
default implementation enables it for the `BansheeCloak` opening; existence of
a Banshee proves the build has reached the executable part of that intent. Its
standing executor survives repeated attack -> retreat/recover -> attack cycles
and waits with zero assigned units during defense preemption.
