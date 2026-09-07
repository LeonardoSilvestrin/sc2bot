# Safe map-control mission

`MapControlPlanner` creates one low-priority, persistent patrol after 180 game
seconds. Its default squad is three healthy Marines, with a minimum of two, and
it only starts when at least three additional eligible Marines remain in reserve.
It does not start during `DEFENSE`/`RECOVERY`, while a base is threatened, or
while an enemy combat unit is visible.

The proposal uses `MissionKind.MAP_CONTROL`, priority 40, and the single
deduplication key `map_control:patrol`. It cannot preempt another mission and its
one-second commitment window lets Defense take the squad almost immediately.

`MapControlExecutor` cycles the squad through four points covering the friendly
side of the map and the center. Every unit receives `safe_path_to`, implemented
by the Ares adapter with `MoveToSafeTarget`, `get_ground_grid`, and a strict
influence threshold. The adapter assigns Ares' native `UnitRole.MAP_CONTROL`.
No attack or attack-move command is issued by this mission.

The whole squad retreats to the closest safe base when:

- a visible ground threat comes within 20 range of any member;
- any member drops to 60% health or less;
- macro posture becomes `DEFENSE`/`RECOVERY`; or
- any held base becomes threatened.

Once the retreat reaches a base, the mission completes and releases its leases.
This is deliberately survival-biased map presence, not an army attack or combat
micro controller. The influence grid also routes around known enemy pressure and
dangerous effects between waypoints.
