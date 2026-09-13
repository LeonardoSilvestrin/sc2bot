# Map control

`bot/behavior/map_control/` keeps a small, timid share of the army on the
map, patrolling a spot chosen from the spatial field. It is the roaming
counterpart to the [standing army](standing.md): the core army claims every
combat unit by default, and map control preempts its share from it.

Source: `bot/behavior/map_control/` (`model.py`, `assessment.py`,
`planner.py`, `executor.py`).

## Assess

`MapControlAssessor` measures the army that could roam:

| Field | Meaning |
| --- | --- |
| `combat_units` | ready combat units (`bot.domain.is_combat_unit`) at 70% health or more |
| `combat_supply` | their total supply |
| `started` | game time past `start_after` (0) |
| `strategically_safe` | no threatened base and macro posture not `DEFENSE`/`RECOVERY` -- reported, never gated on |

## Plan

```text
propose, every frame:
  before start_after                 -> ()
  cadence (15 s) not ready           -> ()
  assess
  combat_supply < 6                  -> ()   cadence not consumed; forget the last plan
  mark cadence
  anchor = best spatial sample (below)
  plan   = anchor + size
  log behavior.assessed / behavior.proposed if the plan changed
  -> one STANDING proposal
```

**Size.** The patrol is sized in supply, not heads, because units do not
weigh the same (a Cyclone is three Marines of supply):

```text
supply_budget = round(combat_supply * 0.2, 2)
desired       = max(1, combat_units)            a count cap only; the budget binds
```

A fixed `desired_units` in the config replaces the budget, for experiments.

**Requirement.** `UnitRequirement.for_role(CombatRole.MOBILE_CONTROL,
desired, minimum=0, minimum_health=0.7, supply_budget)`: never unit types.
The allocator scores every owned unit against the role and fills the budget
with the best-suited ones -- Marines and Marauders in a Bio army, Hellions and
Cyclones in a Mech army, and a mix while production shifts, swapped for better
fits as they appear ([engine/capabilities.md](../engine/capabilities.md)).

**Proposal.**

| Field | Value |
| --- | --- |
| kind, priority, mode | `MAP_CONTROL`, 40, `STANDING` |
| `deduplication_key`, `target_key` | `map_control:patrol` |
| `squad_id` | `map_control` |
| `target` | the anchor |
| `reason` | `persistent_map_control_share_available` |
| `can_preempt`, `commitment_seconds` | yes, 1 s |
| `timeout_seconds`, `cooldown_seconds` | 3600 (never applied to standing), 15 |

The squad is declared even under danger: it is a persistent responsibility,
and the executor pulls it home. Below 6 combat supply the planner proposes
nothing, and silence does not tear down a live standing mission -- a patrol
already running keeps its remaining members.

## Choosing the anchor

The planner reads `awareness.spatial` ([world/spatial-field.md](../world/spatial-field.md))
and owns every weight; Awareness owns none.

```text
candidates = spatial samples at least 6 tiles from every own base
             (every sample if that leaves none; the map centre if the field is empty)

frontier pool = candidates with friendly support in [0.10, 0.80],
                enemy_control < 0.55 and enemy_threat < 0.75
                (safe fallback pool when the coarse lattice misses the band)

friendly_support = projected friendly_control (or friendly_value before projection)
support_band = max(0, 1 - |friendly_support - 0.45| / 0.35)
frontier      = 1 when local lattice neighbours straddle support 0.45,
                otherwise support_band
unknown_risk  = 1 - knowledge_confidence

score = 0.45 support_band + 0.65 frontier + 0.25 advancement
        + 0.35 choke + 0.55 route
        - 1.00 enemy_control - 0.80 enemy_threat
        - 0.25 unknown_risk - 0.15 travel_cost
```

This makes friendly influence supportability rather than a reward for hiding
deeper at home. The preferred point is on the current support contour, moves
away from the nearest held base, improves route/choke control, and remains
within bounded danger. Known-safe frontier beats moderately unknown frontier;
moderately unknown space remains explorable; unknown is never treated as
known safe. `travel_cost` is bounded Euclidean distance from the old anchor
(or nearest base initially), used only as a locality penalty.

Neighbour detection builds one coordinate index for the lattice and checks
only the eight adjacent cells per sample. Candidate construction is therefore
`O(samples)`, followed by an `O(samples log samples)` ranking, once per 15 s
proposal cadence; it does not perform an all-pairs spatial scan.

**Hysteresis.** Once an anchor exists, the planner looks up the sample
nearest to it. If that sample is within 1.5 lattice steps of the anchor and
still a valid frontier candidate, the anchor only moves when the best is **both**
at least 1.5 lattice steps away **and** scores at least 0.12 more. Distances
are in lattice steps so the rule keeps its meaning when the spacing changes.
Because the last plan is forgotten whenever combat supply drops under 6, the
hysteresis starts over after such a gap. Enemy control/threat above the pool
limits or a materially advanced friendly frontier invalidates the current
anchor immediately; hysteresis cannot preserve an obsolete or dangerous one.

Every selection cycle logs `map_control.spatial_candidates` with the top five
candidates and the selected one, including score, frontier, advancement,
support band, enemy control/threat, knowledge, choke/route, travel cost,
selected flag and reason. `map_control.anchor_changed` records both anchors,
scores, switch margin and reason whenever the anchor changes.

A changed anchor replaces the live mission's proposal in place; the executor
picks it up through `refresh` and restarts its patrol loop.

## Execute

`MapControlExecutor` is a small phase machine; every change is logged as
`behavior.state_changed`.

| Phase | When | Does |
| --- | --- | --- |
| `WAITING` | no units assigned (e.g. all preempted by defense) | nothing (`waiting_for_squad_members`) |
| `RETREAT` | a retreat reason holds and some member is farther than 7 from the retreat target | `safe_path_to` the retreat target |
| `HOLDING_HOME` | a retreat reason holds and every member is within 7 of it | stays |
| `PATROL` | otherwise | walks the patrol loop |

Retreat reasons, checked in order:

1. `strategic_danger` -- macro posture `DEFENSE` or `RECOVERY`, or any
   threatened base (anywhere).
2. `squad_health_low` -- any member at 60% health or less.
3. `enemy_too_close` -- a visible enemy able to attack ground within 20 of
   any member.

The retreat target is the `SAFE` base nearest to the first member, or our
start when no base is `SAFE`.

**Patrol loop.** The route is the anchor followed by every spatial sample
within 1.5 lattice steps of it, sorted by angle around the anchor, so the
squad circles the anchor instead of zig-zagging. The route is rebuilt when the
anchor, the spacing or the sample count changes. The squad moves to the next
waypoint once every member is within 5 of the current one, always through
`safe_path_to` (Ares role `MAP_CONTROL`, so patrol units read as busy). It
never completes on its own.

## Arbitration

At priority 40 map control preempts its share from the standing army (20).
`DEFENSE` preempts it at any time after its 1 s commitment window. The squad
bookkeeping ([engine/squads.md](../engine/squads.md)) brings the same units
back afterwards, and while members are away the patrol's budget shrinks by
their supply rather than backfilling.

## Config (`MapControlConfig`)

| Group | Field | Default |
| --- | --- | --- |
| Proposal | `start_after` | 0 s |
| | `proposal_cadence` | 15 s |
| | `priority` | 40 |
| | `mission_timeout`, `failure_cooldown` | 3600 s, 15 s |
| | `commitment_seconds` | 1 s |
| Size | `role` | `MOBILE_CONTROL` |
| | `force_ratio` | 0.2 of combat supply |
| | `minimum_force_supply` | 6 |
| | `desired_units` | `None` (a fixed count replaces the budget) |
| | `minimum_unit_health` | 0.7 |
| Anchor | support/frontier/advancement weights | 0.45, 0.65, 0.25 |
| | choke/route weights | 0.35, 0.55 |
| | enemy control/threat weights | 1.00, 0.80 |
| | unknown/travel weights | 0.25, 0.15 |
| | frontier support target/width/min/max | 0.45, 0.35, 0.10, 0.80 |
| | maximum enemy control/threat | 0.55, 0.75 |
| | `base_exclusion_radius` | 6 |
| | `retarget_score_improvement` | 0.12 |
| | `retarget_min_sample_steps` | 1.5 |
| | `logged_candidate_count` | 5 |
| Tactics | `patrol_radius_sample_steps` | 1.5 |
| | `danger_radius` | 20 |
| | `arrival_radius` | 5 |
| | `retreat_arrival_radius` | 7 |
| | `retreat_health` | 0.6 |

## Known gaps

- With the lattice at spacing 2, 1.5 steps is 3 tiles: the patrol circles the
  anchor's eight neighbouring samples, a small loop.
- Any threatened base sends the whole patrol home, even when the attack is on
  the other side of the map.
- The retreat target is chosen from `SAFE` bases, and `SAFE` only means no
  visible threat right now.
- Reachability is pathable-sample plus bounded Euclidean travel cost, not a
  cached all-pairs path distance. `MoveToSafeTarget` still validates the
  actual route on Ares' ground danger grid.
