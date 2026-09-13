# Standing army (the default owner)

`bot/behavior/standing/` is the behavior every combat unit belongs to when no
more specific mission has claimed it. It keeps the core army parked where an
attack arrives first, and it is what guarantees that no combat unit is ever
ownerless.

Source: `bot/behavior/standing/` (`model.py`, `assessment.py`, `planner.py`,
`executor.py`), `bot/app/telemetry/standing.py`.

```text
behavior/standing/
  model.py        CombatPosture, StandingConfig, StandingAssessment, StandingPlan
  assessment.py   StandingAssessor, derive_combat_posture
  planner.py      StandingPlanner -- one STANDING HOLD_RALLY proposal
  executor.py     StandingExecutor -- keeps the core army on the anchor
```

| Squad | Share | Home mission | Priority |
| --- | --- | --- | --- |
| `main_army` | every combat unit no higher-priority mission holds | `HOLD_RALLY` | 20, the Mission Policy's fixed fallback |
| `map_control` | 20% of combat supply, filled from its own roster (Cyclone, Hellion, Marine, Marauder), preempted from `main_army` ([map-control.md](map-control.md)) | `MAP_CONTROL` | the policy's rank when viable (30..100); not proposed when worth nothing |

## Assess

`StandingAssessor` reads:

- held bases, ordered by distance from our start -- the lightweight stand-in
  for expansion order until construction timestamps exist;
- the ids of threatened bases;
- `pressure`: `threat.near_own_base_enemy_combat_units`;
- `combat_units`: ready units of `STANDING_ROSTER` at or above
  `minimum_unit_health` (0, so every ready one).

`derive_combat_posture` maps Awareness onto a `CombatPosture`. It is
descriptive only -- logged, moving nothing -- and reads no strategic caution:
what the bot wants is Strategy's intent, and how risky spending is stays
macro's concern.

| Posture | When |
| --- | --- |
| `TURTLE` | a base is threatened, or the army belief is stably `BEHIND` |
| `PRESSURE` | the army belief is stably `AHEAD` and no enemy combat unit is near our bases |
| `BALANCED` | otherwise |

The stable army belief is read as is, with no confidence threshold on top:
the belief already weighs its own doubt ([world/awareness.md](../world/awareness.md#economy-and-army-beliefs)),
and gating it again on confidence is what used to make the posture flap.

## Plan

`StandingPlanner.propose` runs every 5 s and always consumes its cadence. It
turns the assessment and Strategy's control objectives into a
`StandingPlan(anchor, anchor_reason, core_count, objective_id, supports)`.

**Where the army waits follows Strategy.** Among Strategy's `BASE`
objectives that some `PASSAGE` objective protects, the planner takes the most
important base, then that base's most important protecting passage (exact
ties by objective id). The anchor is `home_anchor_standoff` (4) inside the
passage toward the base, never past it; `anchor_reason` is
`holds_home_passage_objective`, `objective_id` the passage objective and
`supports` the base objective. Each choice is kept until a rival is more
important by `anchor_retarget_margin` (0.1). Importance never reads our own
hold, so the army arriving does not argue its anchor away.

With no such objective -- no region graph yet, or no passage Strategy wants
held -- the old heuristic is the fallback:

| Situation | Anchor | `anchor_reason` |
| --- | --- | --- |
| no townhall observed | our start | `fallback_no_held_base_yet` |
| one base | that base | `fallback_single_base_held` |
| two or more | 72% of the way from the second-farthest to the farthest base from our start | `fallback_between_previous_and_newest_base` |

`core_count = max(1, combat_units)`: every combat unit, not a share. It is a
cardinality rather than a force size, exact whatever each unit weighs.

Posture is computed and exposed (`StandingPlanner.last_posture`, logged in
`standing.updated`) but does **not** move the anchor.

The proposal:

| Field | Value |
| --- | --- |
| kind, priority, mode | `HOLD_RALLY`, 20 (the Mission Policy's fixed fallback; always viable), `STANDING` |
| `deduplication_key`, `target_key` | `hold_rally:main_army` |
| `squad_id` | `main_army` |
| `target` | the anchor |
| `reason` | `main_army_holds_latest_expansion_rally` |
| requirement | `UnitRequirement.combat(unit_types=STANDING_ROSTER, desired=core_count, minimum=0, minimum_health=0)` |
| `can_preempt`, `commitment_seconds` | yes, 2 s |
| `timeout_seconds`, `cooldown_seconds` | 3600 (never applied to standing), 5 |

Standing scores nothing: every type on its explicit `STANDING_ROSTER` at
utility 1.0 -- Marine, Marauder, Reaper, Hellion, Hellbat, Cyclone, Siege Tank,
Thor, Viking and Banshee, every mode of each. A surviving Marine, a new
Cyclone, a Thor or a Banshee between raids all rest here until something with
a real job takes them. SCVs and unarmed support (Medivacs) never do. A type a
build starts producing joins only by an explicit roster decision:
`tests/test_unit_requirements.py` fails while a registered build's army holds
a type that is neither on the roster nor declared support.

The planner logs `behavior.assessed` (decision `hold`) and
`behavior.proposed` only when the anchor, the core count or the posture
changes.

## Execute

`StandingExecutor` moves only units farther than `arrival_radius` (4) from
the anchor, always with `safe_path_to(..., keep_available=True)`, so a parked
unit keeps the `IDLE` Ares role and never looks busy to another planner.
`refresh` follows the replaced proposal's anchor. It never completes or
fails; with zero units it waits (`no_units_assigned`). Each anchor change is
logged as `behavior.state_changed` with state `ANCHORED` (`anchor_assigned`
or `anchor_changed`).

## Ownership invariant

> Every available combat unit has a behavioral owner.

A unit with no special mission belongs to Standing. When a raid or a defense
needs it, `MissionController` transfers the lease; when that mission ends the
unit is released and Standing reacquires it. This is what keeps two behaviors
from commanding the same unit.

Standing asks for every roster unit rather than a share, which is what makes
it the fallback. Whatever no higher-priority mission holds is picked up on the
next allocation: units from before map control has enough army to start,
units a temporary mission released, units a shrinking patrol gave back.
Every viable mission allowed to preempt (map control, defense, both raids)
outranks Standing by at least the allocator's margin, so it takes its share
and Standing can never take it back; a candidate the Mission Policy rejects
never becomes a mission, so whatever it wanted stays here. A unit produced
between two proposals waits at most one 5 s cadence for the updated count.

Specialized units are no exception. Banshees and Reapers rest here between
raids and are preempted back out by a viable raid like any other unit. One
gap remains: scouting never preempts, so a Reaper scout proposed while every
Reaper sits in Standing stays blocked ([scouting.md](scouting.md#known-gaps)).

`standing.unassigned_units_persisting` fires when a ready, available combat
unit has had no mission for 15 s; normally it should never fire.

## Persistence and preemption

As a `STANDING` mission, the home mission never times out and its proposal is
replaced in place every cadence tick. `SquadController` records `main_army`
membership and supplies preferred tags; when a defense binds the squad, the
home mission's request shrinks by the members away -- by count, and by supply
for a supply-sized request -- instead of filling their seats with unrelated
units, and it reacquires the same members afterwards
([engine/squads.md](../engine/squads.md)).

## Config (`StandingConfig`)

| Field | Default |
| --- | --- |
| `proposal_cadence` | 5 s |
| `minimum_unit_health` | 0.0 |
| `mission_timeout` | 3600 s |
| `cooldown_seconds` | 5 s |
| `commitment_seconds` | 2 s |
| `arrival_radius` | 4 |
| `home_anchor_standoff` | 4 |
| `anchor_retarget_margin` | 0.1 |
| `anchor_fraction_to_newest_base` | 0.72 (fallback anchor only) |

## Events

`standing.updated`, `standing.unassigned_units_persisting`,
`standing_mission_updated`, `behavior.assessed`, `behavior.proposed`,
`behavior.state_changed`, and the squad events. See
[logging.md](../logging.md).

## Known gaps

- Combat posture does not move the anchor.
- Expansion order is approximated by distance from our start.
- The army holds position with `safe_path_to`; it does not fight as a group
  or engage from the anchor.
