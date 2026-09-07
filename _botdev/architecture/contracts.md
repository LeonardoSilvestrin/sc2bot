# Module contracts

## Dependency rules

1. Attention contains only selected state observable in the current frame.
2. Ares memory units are excluded from Attention; persistent sightings belong to
   Awareness.
3. Awareness describes the world. Controller state, leases, cooldowns, and mission
   status never enter Awareness.
4. A planner reads Attention and Awareness and returns immutable proposals. A
   proposal cannot claim a unit or start itself.
5. `MissionController` alone admits/rejects proposals and changes mission status.
6. `UnitAllocator` alone mutates the bidirectional unit-to-mission leases.
7. Executors cannot import Ares or infrastructure. They issue requests via
   `MissionCommands` (`path_to`, `attack_move`, `release`) and every result contains
   a non-empty reason.
8. Only `infrastructure/ares` assigns Ares roles or registers Ares behaviors. Each
   command port hardcodes one role regardless of the calling mission's kind:
   `path_to` assigns `UnitRole.SCOUTING`, `attack_move` assigns
   `UnitRole.ATTACKING`, `release` restores `GATHERING`/`IDLE`.

## Mission kinds and priorities

`MissionKind` (`SCOUT`, `HARASS`, `DEFENSE`) is the shared vocabulary in `ego`; see
[harass-and-defense-planners.md](harass-and-defense-planners.md) for what each
concrete planner and executor does. Default priorities set the intended arbitration
order under `UnitAllocator`'s preemption margin (10): Intel 55, Harass 60 (never
preempts, `can_preempt=False`), Defense 95 (`can_preempt=True`, high enough to
preempt either of the others once their commitment window has elapsed). Each
planner's deduplication key follows `<kind>:<target_key>`.

## Frame lifecycle

```text
observe current Ares state
build AttentionSnapshot
update AwarenessSnapshot and freshness
collect planner proposals
log and admit/reject proposals
sync unit allocator
allocate or preempt by priority after the commitment window
step active missions
register Ares behaviors
apply mission result and release terminal leases
```

`PathUnitToTarget` and `Mining` are registered every frame because Ares executes and
clears registered behaviors in `_after_step`.

## Causal logging

Local event logs are JSONL files with one `{event, component, game_time, data}`
record per line. Transition events include a reason and their correlation keys
where applicable (`proposal_id`, `mission_id`, `deduplication_key`, or
`action_id`). The current catalog is:

- Application lifecycle: `game.started`, `game.ended`.
- Opening progress: `macro.build_order_progress`.
- Periodic/changed awareness: `awareness.updated` contains macro posture,
  relative strength, threat counts, enemy sightings, and the active-mission
  count.
- Periodic/changed world state: `attention.world_state` contains resources,
  supply, economy/harvester facts, and visible entity counts. It is emitted
  alongside `awareness.updated`; both share the same change signature and
  ten-second heartbeat. `attention.snapshot` is a retired legacy event that the
  standalone viewer can still read.
- Mission proposals: `proposal_created`, `proposal_admitted`,
  `proposal_rejected`.
- Mission lifecycle: `mission_queued`, `mission_started`, `mission_blocked`,
  `mission_completed`, `mission_failed`, `mission_cancelled`.
- Unit leases: `units_assigned`, `units_reassigned`, `units_released`.
- Economic proposals: `economic_proposal_created`,
  `economic_proposal_deferred`, `economic_proposal_rejected`.
- Economic actions: `economic_action_admitted`, `economic_action_pending`,
  `economic_action_dispatched`, `economic_action_confirmed`,
  `economic_action_failed`, `economic_action_timed_out`.
- Invalid economic feedback: `economic_feedback_rejected`.

Local runs opt in with `--bot-log events` and write under `_botdev/logs/`.
Ladder runs retain `NullBotLogger` and do not open files. The standalone
`scripts/log_viewer.html` keeps mission and economic histories separate from the
event timeline and derives its Awareness and Economy/Resources views exclusively
from the structured events above.

## Mission loss and cleanup

- After allocator synchronization, a started mission that has lost its entire
  assigned team fails with `all_assigned_units_lost`, before replacement allocation.
- Partial losses allow replenishment. Below the allocation minimum, the mission
  stays blocked with its surviving leases and does not step its executor. Once
  replenished, it resumes the same executor and retains its original start time.
- Total preemption fails the donor with `all_assigned_units_preempted`. The donor
  cannot restart if the recipient releases the units later in the same frame.
  Partial preemption updates the donor's assignments before it is reconsidered.
- Transferred units have their execution role reset through the command port using
  the new lease owner, before the recipient executor runs. Terminal cleanup restores
  surviving workers to GATHERING and other units to IDLE through the Ares adapter.
- Timeout remains cancellation, measured from admission, including blocked time.
  Executor construction and step exceptions fail with the exception type and message
  in `executor_error`. Terminal missions release leases and discard their executor.
