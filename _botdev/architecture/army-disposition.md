# Standing army disposition

The squad pilot replaces absolute main/natural/third/forward/reserve slots with
two proportional, persistent responsibilities:

| Squad | Approximate share | Home mission | Priority |
| --- | ---: | --- | ---: |
| `main_army` | 80% | `HOLD_RALLY` | 20 |
| `map_control` | 20% of suitable map-control units | `MAP_CONTROL` | 40 |

`DispositionPlanner` emits one `MissionMode.STANDING` proposal for
`main_army`. `MapControlPlanner` emits the matching standing proposal for
`map_control`. Both carry a stable `squad_id`; neither planner allocates units
or sends Ares commands. There is no `position:reserve` catch-all.

## Rally anchor

The main-army target is deterministic. Held bases are ordered by distance from
`map.own_start`, which is the current lightweight proxy for expansion order.
With at least two bases, the anchor is 72% of the segment from the previous
base to the newest/farthest expansion. With one base it is that base, and with
no observed town hall it falls back to `own_start`. This intentionally avoids
pathfinding or formation optimization in the pilot.

## Persistence and preemption

`MissionController` registers squad-backed home missions with
`SquadController`. `UnitAllocator` still owns every unit lease. The squad layer
only records membership and supplies preferred tags when the allocator fills a
mission.

A defense proposal declares a normal `UnitRequirement`. It does not name a
squad or unit. `SquadController` selects a compatible, currently unpreempted
squad from its members; the allocator then performs the actual priority and
commitment-window checks. While members are away, the home mission reduces its
effective request instead of filling their seats with unrelated replacements.
When the temporary mission finishes, its leases are released and the standing
home mission preferentially reacquires the same members.

## Ownership invariant

Squad membership is durable identity, not a second lease table:

- `MissionController` alone changes mission lifecycle.
- `UnitAllocator` alone grants/transfers/releases exclusive unit leases.
- `SquadController` never executes micro and never calls Ares.
- Unit-based missions such as SCV scouting keep `squad_id=None` and retain the
  existing behavior.

The relevant structured events are `squad_created`,
`squad_membership_changed`, `squad_mission_changed`, `squad_preempted`, and
`squad_returned_home`.
