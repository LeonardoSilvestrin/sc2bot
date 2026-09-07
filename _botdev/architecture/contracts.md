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
   `MissionCommands` and every result contains a non-empty reason.
8. Only `infrastructure/ares` assigns Ares roles or registers Ares behaviors.

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

Proposal and mission transitions are structured events. Each event includes a
reason plus proposal/planner/mission identifiers where applicable:

- `proposal_created`, `proposal_admitted`, `proposal_rejected`
- `mission_queued`, `mission_started`, `mission_blocked`
- `units_assigned`, `units_reassigned`, `units_released`
- `mission_completed`, `mission_failed`, `mission_cancelled`

Local runs opt in with `--bot-log events`. Ladder runs retain `NullBotLogger` and do
not open files.

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
