# Harass and Defense planners

This slice keeps each planner and executor together under `bot/behavior/` and
adds the second and third mission planners after
[scout-pilot-migration.md](scout-pilot-migration.md)'s `IntelPlanner`.

## Directory layout

```text
bot/behavior/
  scouting/               -> IntelPlanner / ScoutExecutor / config
  harass/                 -> HarassPlanner / WorkerLineHarassExecutor / config
  defense/                -> DefensePlanner / DefendBaseExecutor / config
  map_control/            -> MapControlPlanner / PatrolMapExecutor / config
  macro/                  -> MacroPlanner / economic goals and config

bot/engine/missions/      -> controller, board, allocator, models, execution contracts
bot/app/mission_registry.py -> concrete executor wiring
```

Each executor is named after the concrete action it performs, not its planner, per
the project's rule against generic `<Kind>Executor` classes. Each behavior package
re-exports its public planner, executor, and configuration names.

`MissionKind` gained `HARASS` and `DEFENSE` in `bot/engine/missions/models.py`; it
stays the shared vocabulary in the mission engine, alongside
`MissionProposal`/`Mission`/`MissionController`.
`BotRuntime` now holds a tuple of mission planners and concatenates their proposals
every frame instead of calling a single planner by name, so wiring in a future
planner does not require touching the admission call site.

## New command port

Neither harass nor defense can be expressed with `path_to` alone: both need the
assigned units to fight, not just arrive. `MissionCommands` exposes `attack_move`
for positional pressure and `attack_unit` for focused fire. The Reaper-specific
adapter translates focused fire into `ReaperGrenade` plus aggressive
`StutterUnitForward`, and assigns `UnitRole.HARASSING`.

## HarassPlanner

Proposes one `MissionProposal` (`MissionKind.HARASS`) to attack-move a Reaper into
the enemy natural's worker line. Conditions, all read from existing Attention/
Awareness facts -- no new fact was invented for this planner:

- `awareness.enemy.location("enemy_natural").last_observed_at` is not `None` --
  harass only follows up on a location `IntelPlanner` (or a future scout) has
  already found; it never guesses a target.
- The economy has reached `minimum_workers` (16, matching `IntelPlannerConfig`) and
  a configured harass unit (Reaper by default) is healthy, ready, and available
  for a new mission.

Priority 60, `can_preempt=False` (harass is opportunistic and never steals a live
scout or defender), dedup key `harass:<target_key>`. Its executor attack-moves into
the target, focuses the visible worker with the lowest health, and tolerates local
defenders. At critical health it latches into retreat, follows a safe climber path
to the own main, and completes only after reaching safety.

## DefensePlanner

**Updated by [base-model.md](base-model.md):** proposes one `MissionProposal`
(`MissionKind.DEFENSE`) per currently threatened base, reading
`awareness.bases` (`BaseAwareness`, one `BaseAssessment` per base the bot
holds) instead of scanning all enemy units against a single `own_base`
anchor. See that doc for `BaseSnapshot`/`BaseAssessment`, why protection
never fully suppresses a proposal, and the dedup key change
(`defense:own_base` fixed -> `defense:{base.base_id}` per base). The
conditions that gate a proposal at all are unchanged: a currently visible,
non-worker, attack-capable enemy unit within `proximity_radius` (25, same
default as the old `detection_radius`) of the base.

Priority is now `critical_priority` (95, undefended base) or
`threatened_priority` (85, base has some protection already), both with
`can_preempt=True` -- still the highest of the pilot's planners on purpose,
so it can preempt a live Intel or Harass mission for the same unit once the
`UnitAllocator`'s preemption margin (10) and the donor's commitment window
allow it (see `tests/test_mission_arbitration.py` for the full preemption
sequence).

Its executor, `DefendBaseExecutor`, is unchanged by the base-model slice:
attack-moves every assigned unit toward the threat closest to where the
mission was admitted and completes with `threat_cleared_near_own_base` once
no matching enemy remains within `engagement_radius` of that point.

## Deliberately not built in this slice

- Splitting defense per base/expansion is now done, see
  [base-model.md](base-model.md); harass is still a single worker-line target.
- Worker-rush detection (an enemy worker alone is not treated as a threat).
- Changing `MacroPlanner`: it stays outside the `MissionProposal` model, as recorded
  in [macro-planner.md](macro-planner.md).

## Deferred decisions

- Whether Defense should eventually pull SCVs or request reinforcements instead of
  only reacting with existing combat units.
- Whether Harass should chain multiple targets (natural, then main) instead of a
  single fixed `target_key`.
- Whether a defended-but-currently-unseen base should be inferred from historical
  sightings when choosing between several harass targets.
