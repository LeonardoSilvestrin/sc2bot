# Missions

The mission engine turns behavior proposals into commitments: it admits them,
leases units to them, runs their executors, and cleans up when they end. It is
deliberately generic -- it never names a mission kind or a behavior (rule 6
in [contracts.md](../contracts.md)).

Source: `bot/engine/missions/` (`models.py`, `controller.py`,
`allocator.py`, `board.py`, `execution.py`, `planning.py`, `roles.py`,
`capability_log.py`), `bot/ports/mission_commands.py`,
`bot/adapters/ares/mission_commands.py`.

## Vocabulary

### `MissionProposal`

A planner's argument for work; not yet a commitment. Immutable.

| Field | Default | Meaning |
| --- | --- | --- |
| `proposal_id` | required | unique per proposal; a repeated id is ignored |
| `deduplication_key` | required | "the same work": one live mission per key |
| `planner` | required | planner id; also scopes standing reconciliation |
| `kind` | required | `MissionKind`, looked up in the executor registry |
| `priority` | required | 0..100 |
| `target_key`, `target` | required | a name and a map point |
| `reason` | required | why this is worth doing |
| `requirement` | required | `UnitRequirement` (below) |
| `created_at` | required | game time |
| `evidence_last_observed_at`, `evidence_age`, `evidence_stale_after` | `None` | what the proposal was based on, for the log |
| `timeout_seconds` | 70 | FINITE missions are cancelled after this long from admission |
| `cooldown_seconds` | 65 | after a mission with this key finishes, new proposals for it are rejected this long |
| `can_preempt` | `False` | may take units leased by lower-priority missions |
| `commitment_seconds` | 5 | once this mission leases a unit, nobody may preempt it for this long |
| `mode` | `FINITE` | `FINITE` or `STANDING` |
| `squad_id` | `None` | makes this mission a squad's home ([squads.md](squads.md)) |

Identifiers and reason must be non-blank, priority within 0..100, timeout
positive, cooldown and commitment not negative.

### `UnitRequirement`

Which units qualify, what each is worth to the mission, and how many.

| Field | Default | Meaning |
| --- | --- | --- |
| `unit_types` | required | eligible types, for an identity requirement; empty for a capability requirement |
| `desired` | required | at most this many units (> 0) |
| `minimum` | required | fewer than this and the mission cannot run (0..desired) |
| `flying` | `None` | require flying or ground |
| `minimum_health` | 0.0 | health fraction |
| `require_ready` | `True` | |
| `exclude_resource_carriers`, `exclude_constructors` | `False` | never pull a worker mid-return or mid-build |
| `require_available` | `True` | `UnitSnapshot.available_for_mission` (ignored for preemption) |
| `desirability` | 1.0 | baseline utility of a matching unit |
| `type_desirability` | `()` | per-type utility overrides, `(type, value)` pairs |
| `capability` | `None` | a `CapabilityRequirement`; utility becomes suitability |
| `supply_budget` | `None` | stop acquiring once held supply reaches this |

- `utility_for(unit)`: suitability for a capability requirement, otherwise
  the type override or `desirability`. Zero means never requested.
- `matches_identity(unit)`: flying constraint, then admitted suitability
  (capability) or membership in `unit_types`. Used to keep an existing lease.
- `matches(unit)`: identity, health, readiness, worker exclusions,
  availability.

Three constructors are what planners use:

| Constructor | For | Candidates | Utility |
| --- | --- | --- | --- |
| `UnitRequirement.combat(unit_types=, desired=, minimum=, ...)` | behaviors whose identity is a unit (raids, scout, defense) | the named types | `desirability` / `type_desirability` |
| `UnitRequirement.for_role(role, desired=, minimum=, supply_budget=)` | generic jobs (map control) | every owned unit the role admits | suitability |
| `UnitRequirement.any_combat_unit(desired=, minimum=)` | the fallback owner (standing) | `COMBAT_UNIT_TYPES` | 1.0 |

All three exclude resource carriers and constructors. Capabilities and roles
are in [capabilities.md](capabilities.md).

### Kinds, modes and status

- `MissionKind`: `SCOUT`, `HARASS`, `AIR_HARASS`, `DEFENSE`, `MAP_CONTROL`,
  `HOLD_RALLY`, `POSITION`. Priorities per kind: [contracts.md](../contracts.md#mission-kinds-and-priorities).
- `MissionMode.FINITE`: admitted once, runs to completion, failure or
  cancellation; a second proposal for the same key while it is live is
  rejected.
- `MissionMode.STANDING`: a responsibility re-declared every cadence. A new
  proposal for a live standing key replaces the mission's proposal in place
  (same `mission_id`, leases and executor). Standing missions never time out.
- `MissionStatus`: `PROPOSED -> QUEUED -> ACTIVE / BLOCKED -> COMPLETED /
  FAILED / CANCELLED`.

`Mission` holds the proposal, `admitted_at`, `status`, `assigned_unit_tags`,
`started_at`, `finished_at`, `last_reason`. Ids run `mission-0001`,
`mission-0002`, ... `MissionBoard` is the catalog of every mission, live and
finished; `MissionSnapshot` is its immutable view for telemetry.

## `MissionController.tick`

```text
1  allocator.sync(own units); squads.sync(own units)
2  for each live mission that started, had units and now holds none, with minimum > 0:
       FAILED all_assigned_units_lost                  (checked before replacement allocation)
3  for each proposal: _consider (below)
4  _reconcile_standing_missions
5  for each live mission, sorted by (-priority, admitted_at):
       cancellation check (below)
       squads.bind_compatible_squad (DEFENSE only)
       requirement = squads.effective_requirement (a home squad shrinks while members are away;
                     None when nothing is left to ask for -> keep current leases, satisfied)
       allocation  = allocator.allocate(...)
       apply transfers, releases and upgrades; log units_*
       squads.allocation_changed; capability composition log
       not satisfied: FAILED all_assigned_units_lost if started with zero units, else BLOCKED
       satisfied: advance the executor
```

### Admitting one proposal (`_consider`)

```mermaid
flowchart TD
    In(["proposal"]) --> Seen{"proposal_id seen before?"}
    Seen -->|yes| Ignore["ignore (idempotency)"]
    Seen -->|no| Created["log proposal_created"] --> Live{"a live mission holds<br/>this deduplication_key?"}
    Live -->|yes, both STANDING| Update["_update_standing: replace the proposal in place;<br/>standing_mission_updated if requirement,<br/>priority, target_key or target changed"]
    Live -->|yes, otherwise| RejectLive["proposal_rejected:<br/>matching_mission_already_live"]
    Live -->|no| Cooldown{"now < cooldown_until[key]?"}
    Cooldown -->|yes| RejectCooldown["proposal_rejected:<br/>mission_cooldown_active"]
    Cooldown -->|no| Supported{"kind has an executor factory?"}
    Supported -->|no| RejectKind["proposal_rejected:<br/>unsupported_mission_kind"]
    Supported -->|yes| Admit["proposal_admitted, mission_queued;<br/>registered as a squad home if squad_id is set"]
```

A rejected proposal simply does not become a mission; the planner proposes
again on its own cadence if the reason still holds. The cooldown starts only
when a mission **finishes**, never on a rejection.

### Standing reconciliation

If a planner proposed at least one STANDING proposal this tick, any live
standing mission of that planner whose key is not among them is cancelled
with `standing_proposal_omitted`. A planner that proposed nothing standing
this tick -- its cadence was not ready, or it withheld -- leaves its standing
missions alone: silence is not omission. Today every standing planner
declares one fixed key, so this rule never fires in practice; it exists for a
planner that holds several standing slots and drops one.

### Cancellation

Checked for each live mission before allocation:

| Reason | When |
| --- | --- |
| `objective_satisfied_before_mission_started` | the mission has not started, and `awareness.enemy.location(target_key)` was observed after admission. Applies to any mission whose `target_key` is a location key (`enemy_main`, `enemy_natural`) -- the scout, or a raid launched at a fallback location. |
| `mission_timeout` | `now - admitted_at >= timeout_seconds`, counting blocked time. Never for STANDING. |

### Advancing the executor

- First satisfied allocation: the registered factory builds the executor
  (`factory(mission, now)`); `started_at` is set; `mission_started`. A factory
  exception fails the mission with `executor_error:<Type>:<message>`.
- Every step: `executor.refresh(mission)` if the executor has it (so a
  standing mission picks up a changed target), then
  `executor.step(MissionContext(attention, awareness, assigned_units,
  commands, services))`. An exception fails the mission the same way.
- `COMPLETED` or `FAILED` results finish the mission; `ACTIVE` keeps it.
- A blocked mission keeps its surviving leases and does not step; once
  replenished it resumes the same executor with its original start time.

### Finishing

`_finish` releases every lease through the command port (workers back to
`GATHERING`, others to `IDLE`), logs `units_released`, clears tags, sets
status, `finished_at` and `last_reason`, discards the executor, tells the
squads, and starts the key's cooldown (`now + cooldown_seconds`).

Failure and cancellation reasons in one place:

| Outcome | Reason |
| --- | --- |
| FAILED | `all_assigned_units_lost` (started, then lost every unit; minimum > 0) |
| FAILED | `all_assigned_units_preempted` (a donor left with zero units; minimum > 0) |
| FAILED | `executor_error:<Type>:<message>` |
| FAILED / COMPLETED | the executor's own reason |
| CANCELLED | `mission_timeout`, `objective_satisfied_before_mission_started`, `standing_proposal_omitted` |

A requirement with `minimum=0` -- every squad-backed standing mission -- is
exempt from both loss failures: holding zero units is idle, not failed.

## `UnitAllocator`

Exclusive unit leases with deterministic, hysteretic preemption. Candidates
are every unit the bot owns; the requirement decides who is eligible, utility
who is taken first, and `desired` plus `supply_budget` how many.

A `UnitLease` records `mission_id`, `priority`, `protected_until` (lease time
plus the mission's `commitment_seconds`) and `preemption_cost`. `sync` drops
leases of units that no longer exist.

### `allocate(...)`

```text
1  keep:     current leases whose unit still matches the requirement's identity, filled up to the size
             (a capability requirement keeps its best-suited units); the rest are released
2  free:     unleased units with matches(unit) and utility > 0
3  preemptible (only if can_preempt):
             units leased by another mission where
                 priority >= lease.priority + margin (10) + lease.preemption_cost
             and now >= lease.protected_until
             and matches(unit, ignoring availability) and utility > 0
4  if kept + free + preemptible < minimum:  not satisfied; keep what is held
5  rank candidates:  squad-preferred first
                     -> higher utility, in bands of 0.05
                     -> free before leased
                     -> distance to the mission target minus 10 x health fraction
                     -> tag
6  fill:     take ranked candidates one at a time while count < desired
             and (no budget or held supply < budget); the last unit may overshoot the budget
7  upgrade (capability requirements already full):
             swap the least suitable held unit for a preemptible candidate whose utility is higher
             by at least 0.15; stop when even without that unit there would be no room
8  write leases for newly acquired units (with this mission's priority, commitment window and
   preemption cost); refresh the preemption cost on units already held
9  satisfied = held >= minimum
```

Notes:

- Preemption is not gated on the recipient being below its minimum: a
  mission at its minimum still preempts toward `desired` when the margin and
  commitment window allow.
- The 0.05 utility band is the heuristic's precision: a Marine and a Marauder
  that fit a role almost equally are chosen by distance, not by the third
  decimal.
- Upgrades only take units the mission could preempt anyway, whose donor ranks
  lower and allocates later the same tick, so the swapped-out unit is picked up
  instead of left ownerless.

```mermaid
flowchart TD
    Tick(["per live mission, by -priority"]) --> Keep["keep leases still matching identity,<br/>up to the size; release the excess"]
    Keep --> Pool["candidates: free available units, plus leased units<br/>when priority >= owner + 10 + owner's preemption cost<br/>and the owner's commitment window passed (utility > 0)"]
    Pool --> Enough{"held + candidates >= minimum?"}
    Enough -->|no| Blocked["not satisfied: BLOCKED<br/>(FAILED if started with zero units)"]
    Enough -->|yes| Rank["rank: squad-preferred, utility band,<br/>free before leased, distance - 10 x health"]
    Rank --> Fill["fill up to desired / supply budget"]
    Fill --> Transfer["transfer preempted units;<br/>the donor shrinks, or fails with zero units and minimum > 0"]
    Transfer --> Done["satisfied"]
```

### Worked example

The standing army (20) holds ten units. Map control (40) is declared with a
supply budget: after the standing mission's 2 s commitment window it
preempts its share (40 >= 20 + 10). A base is attacked: defense (95) preempts
from map control after map control's 1 s window (95 >= 40 + 10), and from a
Banshee raid mid-strike (95 >= 62 + 10 + 5). A Reaper raid (60) cannot take
the scouting Reaper (65), and scouting cannot take anything. When defense
completes, its units are released and the standing and map-control missions,
which prefer their squad members, take them back on the next allocation.

## Executor contract (`execution.py`)

```python
class MissionExecutor(ABC):
    async def step(self, context: MissionContext) -> MissionResult: ...
    def refresh(self, mission: Mission) -> None: ...        # default: no-op
    def preemption_cost(self) -> float: ...                 # default: 0.0
```

- `MissionContext`: `attention`, `awareness`, `assigned_units` (this
  mission's leased units only), `commands` (`MissionCommands`), `services`
  (`BehaviorServices` or `None`).
- `MissionResult(outcome, reason)`: `ACTIVE`, `COMPLETED` or `FAILED`, with a
  non-empty reason.
- `refresh` lets a standing mission's executor follow its replaced proposal.
- `preemption_cost` is the running executor's tactical answer to "what does
  taking my units cost right now"; it is clamped to >= 0 (an exception reads
  as 0) and added to the preemption margin on its leases. The Banshee raid
  returns 5 while infiltrating or striking.
- `MissionExecutorFactory = Callable[[Mission, float], MissionExecutor]`,
  registered per kind in `bot/app/mission_registry.py` ([app.md](../app.md#executor-registry)).

### Commands

`MissionCommands` (`bot/ports/mission_commands.py`): `path_to`,
`safe_path_to` (`search_radius`, `keep_available`), `attack_move`,
`attack_unit`, `use_ability`, `release`. `AresMissionCommands` checks the
lease on every call and raises `UnauthorizedUnitCommand` otherwise; what each
command registers in Ares is in [contracts.md](../contracts.md#command-port-what-each-command-leaves-behind-rule-9).
When units are transferred, the controller resets their role through the
port using the new owner, before the recipient's executor runs.

## Planning helpers (`planning.py`)

- **`ProposalCadence`** rate-limits a planner and hands out sequence numbers
  for stable proposal ids: `ready(now, cadence)` is true once `cadence`
  seconds passed since the last `mark(now)`; `next_sequence()` increments.
  Planners that withhold do not `mark`, so the next frame re-evaluates.
- **`choose_target(candidates, current_key, margin)`** returns a
  `TargetChoice(target, change, previous_key)`. It keeps the held target while
  it is still a candidate and nothing beats it by more than `margin`; drops it
  without any margin when it is no longer a candidate; ties go to the earlier
  candidate. `TargetChange`: `NONE`, `SELECTED`, `KEPT`, `RETARGETED`,
  `REPLACED`, `LOST`. Used by both raids.

## Capability allocation log (`capability_log.py`)

For capability-based missions only, after each allocation:

- `capability_composition_changed` when the mission's count by unit type
  changes, with the role, both compositions, new types, held supply, budget,
  and one line per profiled unit type owned (`count`, `utility`,
  `suitability`, `coverage`, `floor_factor`, `rejection`, raw capabilities).
- `capability_no_suitable_candidates` once when no owned unit fits the role,
  until one does.

## Known gaps

- Sizing is per unit, not per squad: the budget is filled greedily by the best
  individual scores, so a patrol can end up one unit type. `_fill` is the seam
  for a marginal utility given the units already taken.
- Preemption compares priorities, not what the donor loses.
- A FINITE mission cannot accept an in-place update (a live Reaper raid keeps
  its target).
- Emergency priority 100 has no special path around commitment windows.
