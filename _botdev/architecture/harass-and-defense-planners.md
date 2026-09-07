# Harass and Defense planners

This slice keeps each planner and executor together under `bot/behavior/` and
adds the second and third mission planners after
[scout-pilot-migration.md](scout-pilot-migration.md)'s `IntelPlanner`.

## Directory layout

```text
bot/behavior/
  scouting/               -> IntelPlanner / ScoutExecutor / config
  harass/                 -> HarassPlanner / BansheeHarassPlanner / executors / config
  defense/                -> DefensePlanner / DefendBaseExecutor / config
  map_control/            -> MapControlPlanner / PatrolMapExecutor / config
  macro/                  -> MacroPlanner / economic goals and config

bot/engine/missions/      -> controller, board, allocator, models, execution contracts
bot/app/mission_registry.py -> concrete executor wiring
```

Each executor is named after the concrete action it performs, not its planner, per
the project's rule against generic `<Kind>Executor` classes. Each behavior package
re-exports its public planner, executor, and configuration names.

`MissionKind` gained `HARASS`, `AIR_HARASS`, and `DEFENSE` in
`bot/engine/missions/models.py`; it stays the shared vocabulary in the mission
engine, alongside
`MissionProposal`/`Mission`/`MissionController`.
`BotRuntime` now holds a tuple of mission planners and concatenates their proposals
every frame instead of calling a single planner by name, so wiring in a future
planner does not require touching the admission call site.

## New command port

Neither harass nor defense can be expressed with `path_to` alone: both need the
assigned units to fight, not just arrive. `MissionCommands` gained `attack_move`,
implemented in `AresMissionCommands` with the `AMove` behavior (the attack-capable
counterpart of the `PathUnitToTarget` behavior the scout already uses) and assigning
`UnitRole.ATTACKING`, mirroring how `path_to` always assigns `UnitRole.SCOUTING`
regardless of the calling mission's kind.

`MissionCommands` later gained `use_ability` for `BansheeHarassPlanner` below --
an ability cast with no positional order attached, so unlike `attack_move` it
does not reassign a `UnitRole`.

## HarassPlanner

Proposes one `MissionProposal` (`MissionKind.HARASS`) to attack-move a Reaper into
the enemy natural's worker line. Conditions, all read from existing Attention/
Awareness facts -- no new fact was invented for this planner:

- `awareness.enemy.location("enemy_natural").last_observed_at` is not `None` --
  harass only follows up on a location `IntelPlanner` (or a future scout) has
  already found; it never guesses a target.
- `awareness.threat.visible_enemy_units == 0` -- conservative: it withholds harass
  the instant any enemy unit is visible anywhere, since this slice has no notion of
  "the target base specifically is undefended" versus "a threat is visible
  somewhere else."
- The economy has reached `minimum_workers` (16, matching `IntelPlannerConfig`) and
  a configured harass unit (Reaper by default) is alive.

Priority 60, `can_preempt=False` (harass is opportunistic and should never steal
units from another live mission), dedup key `harass:<target_key>`. Its executor,
`WorkerLineHarassExecutor`, attack-moves into the target and completes with
`harass_target_defended` the moment a non-worker, attack-capable enemy unit is
observed within `disengage_radius` of the target -- it disengages from a fight it
wasn't sent to win instead of trading the harasser away.

## BansheeHarassPlanner

Proposes one `MissionProposal` (`MissionKind.AIR_HARASS`) to attack-move a
Banshee into the enemy natural's worker line, for the `BansheeCloak` opening
(see [opening.md](opening.md)). Same shape as `HarassPlanner`, with one
condition swapped for the fact that a flying, cloaked harasser cannot be
threatened by a ground-only defender: it withholds on
`awareness.threat.visible_anti_air_units > 0` rather than "any enemy unit
visible anywhere." It never checks cloak research directly -- see the
executor below for why that's unnecessary. Priority 62, `can_preempt=False`,
dedup key `air_harass:<target_key>` (distinct from `HarassPlanner`'s
`harass:<target_key>`, so a Reaper harass and a Banshee harass can both be
live at once without colliding).

Its executor, `CloakedBansheeHarassExecutor`, attack-moves into the target
and casts `AbilityId.BEHAVIOR_CLOAKON_BANSHEE` (via the new
`MissionCommands.use_ability` port, `AresMissionCommands` wrapping Ares's
`UseAbility` behavior) every step rather than tracking on/off state locally:
`UseAbility` no-ops once the ability is not in `unit.abilities`, which is
true both before Cloaking Field research finishes and once already cloaked,
so re-issuing it is always safe and needs no bookkeeping. It completes with
`harass_target_defended` the moment a non-worker, **anti-air-capable**
enemy unit is observed within `disengage_radius` -- checking
`can_attack_air` instead of `WorkerLineHarassExecutor`'s `can_attack_ground`,
since that is the only kind of defender that can actually hit it.

Deliberately not built here either: no detector-awareness (a defender that
can only detect, not attack air -- e.g. a lone Observer -- does not trigger
disengage), and no energy-aware cloak scheduling (cloak is cast blindly every
step; it simply stops taking effect once energy runs out).

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
- Any retreat/repositioning micro beyond `AMove`'s built-in engage-on-the-way
  behavior.
- Unit-specific Ares roles such as `HARASSING_REAPER`; `attack_move` always assigns
  the generic `UnitRole.ATTACKING`, matching `path_to`'s existing
  one-port-one-role convention.
- Changing `MacroPlanner`: it stays outside the `MissionProposal` model, as recorded
  in [macro-planner.md](macro-planner.md).

## Deferred decisions

- Whether Defense should eventually pull SCVs or request reinforcements instead of
  only reacting with existing combat units.
- Whether Harass should chain multiple targets (natural, then main) instead of a
  single fixed `target_key`.
- Whether a defended-but-currently-unseen base should be inferable (e.g. from
  `EnemyAwareness.sightings`) so Harass does not have to treat every visible enemy,
  anywhere on the map, as a reason to hold back.
