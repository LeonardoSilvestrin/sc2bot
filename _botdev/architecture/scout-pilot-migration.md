# Scout pilot migration

## Sources deliberately mined

The research source was branch `ares` at commit `2eab783`. The destination and
official architecture is branch `recomeço`.

The pilot reimplemented these useful ideas rather than copying their code:

- planner proposal and admitted commitment are different objects;
- unit ownership has both `unit_tag -> mission_id` and
  `mission_id -> unit_tags` views;
- selection is deterministic and prefers health and proximity;
- a short commitment window plus a priority margin prevents allocation thrashing;
- enemy observations carry time, age, confidence, and a typed stale threshold;
- worker scouts require a healthy, ready, non-carrying, non-constructing worker;
- an objective completes only after a real observation newer than mission start;
- timeouts, cooldowns, lifecycle results, and all decisions have explicit reasons;
- mission state is exposed through immutable `MissionSnapshot` objects.

## Deliberately not migrated

- The old monolithic `Ego`: it mixed planning, allocation, scheduling, execution,
  memory, and logging.
- The global key/value `MemoryStore`: the pilot uses typed enemy location knowledge.
- `PrioritizationIntel`: priority 55 is explicit until several real planners need
  arbitration inputs.
- The giant `DefensePlanner`, synthetic threats, bunker logic, SCV pulls, and repair
  orchestration: none are required to prove the scout flow.
- `MacroOrchestratorPlanner`, desired composition, and spending heuristics: economy
  proposals need a separate future vertical slice.
- `ResourceReserve`: it was declarative but had no effective enforcement in the old
  runtime.
- Generic task factories, pick-policy protocols, event buses, service locators, and
  lease heartbeats: each adds machinery without helping this single mission.
- Multi-target scout routes, scans, Reaper scouting, rush-specific cadence, retreat
  micro, and probabilistic inference: useful candidates, but outside this pilot.

## End-to-end behavior

1. Attention selects the enemy natural and records whether it is visible now.
2. Awareness remembers its last real observation and computes age/confidence.
3. `IntelPlanner` emits a reasoned `MissionProposal` when it is unknown or stale.
4. `MissionController` logs the proposal, rejects duplicates/cooldown conflicts, or
   admits it as a distinct `Mission`.
5. `UnitAllocator` leases one eligible SCV and can later support priority-based
   preemption without allowing missions to steal tags directly.
6. `ScoutExecutor` carries out the admitted mission through `MissionCommands`.
7. The Ares adapter assigns `UnitRole.SCOUTING` and registers
   `PathUnitToTarget` every frame.
8. When `bot.is_visible(enemy_natural)` becomes true, Awareness records a newer
   observation.
9. The mission completes for `target_observed_after_mission_started`, releases the
   lease, restores `UnitRole.GATHERING`, and the baseline Ares `Mining` behavior
   resumes worker control.

The opening's independent `worker_scout` step was removed so this flow has one
authority and one causal record.

## Deferred decisions

- Whether future scout profiles should target main, ramp, natural, or a route.
- Whether a scout should return home before completion or release immediately to
  Ares mining.
- How emergency priority 100 should bypass or shorten commitment protection.
- The future economy contract: `SpendProposal`, real resource reservations, and an
  `EconomyController` remain intentionally unimplemented.
