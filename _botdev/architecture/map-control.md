# Persistent map control

`bot/behavior/map_control/` keeps a small, timid share of the army on the map.
It is the roaming counterpart to [standing-behavior.md](standing-behavior.md):
the core army claims every combat unit by default, and this preempts its share
from it.

## Plan

`MapControlAssessor` measures the army: ready combat units
(`bot.domain.is_combat_unit`) at 70% health or more, as `combat_units` and as
`combat_supply`. `MapControlPlanner` (cadence 15 s) declares the standing
`map_control` squad once `combat_supply` reaches `minimum_force_supply` (6).

The patrol is sized in supply, not heads: `supply_budget = combat_supply *
force_ratio` (20%). `desired` is only a count cap (every combat unit), so the
budget is what binds. `desired_units` remains an optional fixed count for
experiments and replaces the budget.

The proposal asks for `CombatRole.MOBILE_CONTROL` through
`UnitRequirement.for_role`, never for unit types, and knows nothing about what
macro is producing. The allocator scores every owned unit against the role and
fills the budget with the best-suited ones. On a Bio army that means Marines
and Marauders, on a Mech army Cyclones and Hellions, and in between they
compete. See [capabilities.md](capabilities.md).

The proposal uses `MissionKind.MAP_CONTROL`, priority 40,
`MissionMode.STANDING`, dedup key `map_control:patrol`,
`squad_id="map_control"`, `minimum=0` and `can_preempt=True`. The core army
holds every combat unit nothing else does, so the patrol has to take its share
from it. It is declared even during danger because this is a persistent
responsibility, not a one-shot opportunity; the assessment only reports
`strategically_safe`.

Below the minimum force supply the planner proposes nothing, and silence does
not tear down a live standing mission (see [contracts.md](contracts.md)): a
patrol already running keeps its remaining members.

## Execute

`MapControlExecutor` is a small phase machine, each change logged as
`behavior.state_changed`:

| Phase | When | Does |
| --- | --- | --- |
| `WAITING` | no units assigned (e.g. all preempted by defense) | nothing; waits for its members |
| `RETREAT` | a retreat reason holds and the squad is not home yet | `safe_path_to` the nearest `SAFE` base (or the main) |
| `HOLDING_HOME` | a retreat reason holds and every member is within 7 of home | stays active there |
| `PATROL` | otherwise | `safe_path_to` the current waypoint |

Retreat reasons, checked in order: `strategic_danger` (macro posture
`DEFENSE`/`RECOVERY`, or any threatened base), `squad_health_low` (any member
at 60% health or less), `enemy_too_close` (a visible enemy unit that can attack
ground within 20 of any member).

The patrol cycles four deterministic points on the friendly side of the line
from the main to the map center: one side of a forward point at 78% of that
line, the center, the other side of the forward point, and a staging point at
48%. It moves to the next point only once every member is within
`arrival_radius` (5), and it never completes on its own.

Priority arbitration lets `DEFENSE` preempt it at any time. The squad
bookkeeping in [squads.md](squads.md) brings the same units back afterwards,
and while members are away the patrol's budget shrinks by their supply rather
than backfilling.
