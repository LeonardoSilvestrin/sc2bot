# Capabilities, roles and composition doctrine

Three concepts in three layers. They meet only through the units that exist.

```text
SHARED DOMAIN    bot/domain/               what a unit type can do
                 CombatCapabilities, UNIT_PROFILES, COMBAT_UNIT_TYPES,
                 CapabilityRequirement, suitability

MISSION ENGINE   bot/engine/missions/      how to use the units that exist
                 CombatRole (roles.py), UnitRequirement, UnitAllocator

MACRO            bot/macro/builds/         what each build actually produces
                 MacroGoalSet (units, structures, add-ons, milestones)
                 bot/macro/composition/ only supplies doctrine bounds

BEHAVIORS        bot/behavior/*            ask for a role, every combat unit,
                                           or a concrete unit; know no doctrine
```

> Doctrine decides what we produce. Mission allocation decides how to use
> what already exists.

```text
Behavior -> role / capability requirement -> UnitAllocator
         -> every unit the bot owns -> physical eligibility -> suitability -> assignment

Macro -> build plan -> MacroGoalSet -> what to produce
                          |
                          +-> CompositionDoctrine validates broad bounds
```

The two flows meet only because production changes which units exist.
`tests/test_behavior_architecture.py` fails if doctrine reaches a generic
behavior or the mission engine, or if the domain imports anything from `bot`.

## Shared domain (`bot/domain/`)

A leaf package with no policy: behaviors, the mission engine and macro can
all read it without depending on each other.

`CombatCapabilities` is one unit type's profile: seven scalars in 0..1
(`mobility`, `anti_ground`, `anti_air`, `range`, `siege`, `splash`,
`durability`) plus physical booleans (`attacks_ground`, `attacks_air`,
`is_flying`). The scalars are operational heuristics for ranking units against
each other, not damage models. `mobility` means repositioning while staying
effective, so a Siege Tank is slow there despite Marine move speed.

`UNIT_PROFILES` covers Marine, Marauder, Reaper, Hellion, Hellbat, Cyclone,
Siege Tank, Thor, both Viking modes and Banshee. Sieged Tank and Thor
high-impact mode share their base profile: a transient mode must not change
what a mission holds. `COMBAT_UNIT_TYPES` / `is_combat_unit` are the profiled
types that can attack something. A type without a profile (SCV, Medivac) is
not a combat unit: no capability requirement and no fallback owner takes it.

## Suitability

```text
coverage(u, r) = sum_i w_i * c_i(u) / sum_i w_i
floors(u, r)   = prod_(d, f) min(1, c_d(u) / f) ** 2
S(u, r)        = coverage * floors   if every hard constraint holds
               = 0                   otherwise
```

Only three things shape the score, and all of them belong to the requirement:

- **Weights**: how much a dimension matters. They are normalized, so every
  score is in 0..1.
- **Floors**: the job falls apart below this level. The penalty is quadratic,
  so a Tank's firepower cannot buy it a mobile-control score near a
  Hellion's.
- **Hard constraints**: the unit must attack something, plus
  `requires_anti_ground` / `requires_anti_air`. These are physical booleans,
  never traded against other capabilities.

There is no global cut-off. A poor fit scores low and is taken last. The
score is zero only when a hard constraint fails or a floored capability is
missing entirely. `score_unit_for_requirement` returns a `Suitability`
(`score`, `coverage`, `floor_factor`, `rejection`) and is cached. Rejections
are `no_capability_profile`, `cannot_attack`, `cannot_attack_ground`,
`cannot_attack_air` and `lacks_<capability>`.

## Roles (`bot/engine/missions/roles.py`)

A role is a job a generic mission needs done. It carries one
`CapabilityRequirement` and nothing else: no unit list and no build.

| Role | Weights (main) | Floors | Hard |
| --- | --- | --- | --- |
| `MOBILE_CONTROL` | mobility 1.0, anti_ground 0.6 | mobility 0.5, anti_ground 0.4 | anti-ground |
| `SIEGE_ANCHOR` | anti_ground, range, siege 1.0 | range 0.6, siege 0.5 | anti-ground |

| Unit | MOBILE_CONTROL | SIEGE_ANCHOR |
| --- | ---: | ---: |
| Cyclone | 0.64 | 0 (lacks_siege) |
| Hellion | 0.60 | 0 (lacks_siege) |
| Banshee | 0.59 | 0 (lacks_siege) |
| Marine | 0.47 | 0 (lacks_siege) |
| Marauder | 0.46 | 0 (lacks_siege) |
| Hellbat | 0.33 | 0 (lacks_siege) |
| Reaper | 0.28 | 0 (lacks_siege) |
| Siege Tank | 0.19 | 0.84 |
| Thor | 0.15 | 0.10 |
| Viking (fighter) | 0 (cannot_attack_ground) | 0 (cannot_attack_ground) |

`SIEGE_ANCHOR` has no consumer yet. There is no `MAIN_FORCE` role: Standing
asks for every combat unit, so a main-force score never decided anything.

## Requests

| Request | Used by | Candidates | Utility |
| --- | --- | --- | --- |
| `UnitRequirement.for_role(role, desired=, minimum=, supply_budget=)` | map control | every owned unit the role admits (`S > 0`) | `S` |
| `UnitRequirement.any_combat_unit(desired=, minimum=)` | standing | `COMBAT_UNIT_TYPES` | 1.0 |
| `UnitRequirement.combat(unit_types=, ...)` | Banshee/Reaper harass, scouting, defense | the named types | `desirability` / `type_desirability` |

A capability requirement has an empty `unit_types` and cannot carry
desirability tables. Unit-specific behaviors keep naming their unit on
purpose, because the behavior depends on that unit's particular traits.

## Allocation (`UnitAllocator`)

1. **Eligibility**: `matches`, which covers identity (for a capability
   requirement, the type's `Suitability.admitted`), health, readiness, worker
   exclusions and availability. Utility must be above 0.
2. **Ranking**: preferred squad members first, then utility in 0.05 bands
   (`UTILITY_RESOLUTION`, the heuristic's precision), then free before leased,
   then distance and health.
3. **Size**: `desired` caps the count. When `supply_budget` is set, a unit is
   taken only while the supply already taken is below the budget, so the last
   unit may overshoot. `_fill` takes units one at a time.
4. **Shrinking**: a capability mission keeps its best-suited units within the
   size.
5. **Upgrades (hysteresis)**: a full capability mission may swap its least
   suitable unit for a candidate it could preempt anyway, only when utility
   rises by at least `upgrade_margin` (0.15). A swap that would not fit even
   after removing the swapped-out unit is skipped. A swap that pushes supply
   past the budget is trimmed on the next allocation.

Ownership, priority, preemption margin and cost, commitment windows,
persistent missions and squads are unchanged. `SquadController` shrinks a home
mission's request while members are away, by their count and by their supply.

## Composition doctrine (`bot/macro/composition/`)

`CompositionDoctrine` is production intent only: core, support and specialized
unit types. It has no capability, role or preference vocabulary. Every
`MacroGoalSet` names its `doctrine`, and construction fails if an army goal
falls outside it.

It is a shared validation vocabulary, not the place to discover a concrete
build. Exact unit ratios and every production request live together in that
build's `bot/macro/builds/<build>/plan.py`.

| Doctrine | Core | Support | Specialized | Used by |
| --- | --- | --- | --- | --- |
| `BIO` | Marine, Marauder, Siege Tank | Medivac, Viking | Banshee | `bio_three_one_one`, `banshee_cloak` |
| `MECH` | Hellion, Cyclone, Siege Tank | Viking, Thor | Banshee | `battle_mech` |

## A BIO -> MECH transition

Macro switches to a goal set within `MECH` and starts producing Hellions,
Cyclones and Tanks. Nothing in the mission system changes:

- Surviving Marines are still combat units, so Standing holds them.
- Map control scores Marines, Hellions and Cyclones side by side. As Cyclones
  appear, upgrades swap them into the patrol, and the Marines go back to the
  main army.
- The army's composition shifts only because what gets built changed.

No transition doctrine exists or is needed. `BuildTransitionTests` in
`tests/test_capability_allocation.py` runs this scenario.

## Events

Component `engine.missions.controller`:

- `capability_composition_changed`: the mission's count by unit type moved.
  Carries `role`, `previous_composition`, `composition`, `new_unit_types`,
  `supply`, `supply_budget` and `candidates`: one line per profiled unit type
  owned, with `count`, `utility`, `suitability`, `coverage`, `floor_factor`,
  `rejection` and the raw `capabilities`.
- `capability_no_suitable_candidates`: no owned unit fits the role. Sent once
  until one does.
- `units_upgraded`: released/acquired tag, type and utility per swap. The
  swapped-out unit is also reported as `units_released`, reason
  `replaced_by_more_suitable_unit`.
- `standing_mission_updated` also carries `previous_supply_budget`.

## Remaining allocation debt

- **Count-based sizing**: `DefenseConfig` still uses unit lists,
  `type_desirability` and a `desired` count (`DefenseRole.for_unit_type` too).
  Only map control sizes by supply. Standing's count is "all of them", a
  cardinality rather than a force size.
- **Standalone utility**: utility is per unit, independent of the squad and of
  supply. The budget is filled greedily by the best individual scores, so a
  patrol can end up as a single unit type. `_fill` is the seam where
  `MarginalUtility(unit | squad, requirement)` plugs in.
- **No opportunity cost**: preemption compares priorities, not what the donor
  loses. A poor fit (a Tank at 0.19) can join a patrol when nothing better is
  free or preemptible.
- **Map control sizing changed**: the patrol is now 20% of total combat supply
  (at least 6 supply), not 20% of fitting units. With Tanks in the army the
  patrol is larger than before.
- **Scouting and Reapers**: scouting never preempts, so a scout request stays
  blocked while every Reaper sits in Standing.
