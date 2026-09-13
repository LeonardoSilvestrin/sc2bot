# Attention

Attention is what the bot can observe in the current frame, as immutable
data. It holds no memory, no beliefs and no mission bookkeeping. It is built
by exactly one adapter, `AresWorldObserver`, which is also the only code
that reads Ares' mutable state for facts.

Source: `bot/world/attention/` (`facts/unit_facts.py`, `base_facts.py`,
`map_facts.py`, `economy_facts.py`, `world_facts.py`, `service.py`,
`snapshot.py`), `bot/adapters/ares/world_observer.py`.

```text
bot (AresBot, mediator) --AresWorldObserver.world_facts--> WorldFacts --AttentionService.build--> AttentionSnapshot(world)
```

Consumers import from `bot.world.attention`.

## `WorldFacts`

| Field | Meaning |
| --- | --- |
| `iteration`, `time` | frame index and game time in seconds |
| `minerals`, `vespene`, `supply_used`, `supply_cap` | the bank as Ares reports it this frame (may be momentarily negative while Ares simulates spend; consumers clamp) |
| `own_units`, `own_structures` | `UnitSnapshot`s of everything we own |
| `enemy_units`, `enemy_structures` | `UnitSnapshot`s of every enemy Ares reports, visible or remembered |
| `map` | `MapFacts` (below) |
| `economy` | `EconomyFacts` (below) |
| `dead_unit_tags` | tags the game reported dead since the previous observation, any owner |
| `bases` (property) | one `BaseSnapshot` per own townhall (below) |

### `bases`

A computed property, not a stored field: a lossless transform of
`own_structures` and `map.own_start`, so a hand-built `WorldFacts` in a test
gets it for free.

- One `BaseSnapshot(base_id, position, is_main, townhall)` per own structure
  whose type is in `TOWNHALL_TYPES` (sourced from Ares, so a lifted Command
  Center still counts).
- `base_id = "base:<townhall tag>"`; `is_main` is true within 3 tiles of
  `map.own_start`.
- With no townhall at all it returns a single placeholder, `base_id="own_base"`
  at `own_start`, `is_main=True`, `townhall=None`.

## `UnitSnapshot`

| Field | Source / meaning |
| --- | --- |
| `tag`, `unit_type`, `position`, `health_percentage`, `is_flying` | the Ares unit; `unit_type` is the exact current form (a sieged Tank is `SIEGETANKSIEGED`) |
| `is_worker` | type in Ares `WORKER_TYPES` |
| `can_attack_air`, `can_attack_ground` | the unit's weapons |
| `visible_now` | own units: always true. Enemy units: false when Ares reports it as memory (`is_memory`). Enemy structures: false when memory or a game snapshot in fog (`is_snapshot`). |
| `is_ready`, `is_carrying_resource`, `is_structure` | the Ares unit |
| `is_constructing` | an SCV currently constructing (`is_constructing_scv`) |
| `available_for_mission` | own units only: false when the unit's Ares role is anything other than `GATHERING` or `IDLE` (a mission executor, or Ares' builder selection, set it) |
| `supply_cost` | from Ares' static `UNIT_DATA` table |
| `energy` | current energy (read by the scan provider) |

`is_visible_combat_threat(against_ground=True, against_air=True)` is true for
a visible non-worker that can attack at least one requested domain. Most
threat checks in behaviors use it.

## `EconomyFacts`

What macro, the economy controller and a few behaviors read about production.

| Field | Meaning |
| --- | --- |
| `opening_name`, `opening_completed` | the build runner's `chosen_opening` and `build_completed` |
| `protected_minerals`, `protected_vespene` | cost of the opening's next steps (below) |
| `mineral_collection_rate`, `vespene_collection_rate` | from the game score |
| `workers`, `townhalls` | `CountFacts(existing, ready, pending)`; `total = ready + pending` |
| `ideal_harvesters`, `assigned_harvesters` | summed over townhalls and gas buildings |
| `supply_pending` | supply under construction, in supply (8 per depot when counted from structures) |
| `unit_counts`, `structure_counts` | `UnitTypeCount(unit_type, existing, ready, pending)` per type |
| `producers` | `ProducerFacts(unit_type, ready, idle, busy, pending, utilization_20s)` per production structure type |
| `tech_ready` | unit types Ares says the current tech allows; `None` means "not asked this frame" and never blocks production |
| `upgrades`, `upgrades_in_progress` | finished upgrades; progress 0..1 of tracked upgrades (only `BANSHEECLOAK` today) |

Lookups: `unit_count(type)`, `structure_count(type)`, `producer(type)`
(each returns an empty record when absent), `tech_ready_for(type)`,
`upgrade_ready(id)`, `upgrade_progress(id)`.

How the adapter fills them:

- **Counted type.** Units and structures are counted as what was trained or
  built, through python-sc2's `UNIT_UNIT_ALIAS`: a sieged Tank counts as a
  `SIEGETANK`, a lowered depot as a `SUPPLYDEPOT`, a lifted Barracks as a
  `BARRACKS`. `UnitSnapshot` keeps the exact form.
- **Pending.** The largest of: existing-but-not-ready, train orders in
  progress (decoded from order abilities), Ares' building counter, and
  `already_pending` / `structure_pending` / `unit_pending`.
- **Types covered.** Everything owned, everything pending, everything the
  build order mentions, and every unit any owned structure can train, so a
  producer's units appear with zero counts before the first one exists.
- **Producers.** For each structure type that can train: `ready`, `idle`
  (landed and without orders; a flying Barracks reads busy), `busy = ready -
  idle`, and `utilization_20s`, a time-weighted moving average of `busy /
  ready` with a 20-second window. A type with no ready structure reports 0 and
  resets its average.
- **Protected cost.** While the build runner is still running,
  `_protected_commitment_cost` prices its current step and the next one with
  the bot's own `calculate_cost`, capped at 600 minerals and 400 gas. Steps
  that only direct (scouting, add-on swaps) cost nothing. Once
  `build_completed` is true nothing is protected.

## `MapFacts`

| Field | Lifetime | Meaning |
| --- | --- | --- |
| `center`, `own_start`, `enemy_starts` | game | from `game_info` |
| `observations` | every frame | `MapObservation(key, position, visible_now)` for `enemy_main` (first enemy start) and `enemy_natural` (Ares' `get_enemy_nat`) |
| `routes` | every frame (static shape) | `MapRoute` `enemy_main`: the scouting lap (below) |
| `expansions` | every frame | one `MapObservation` per expansion slot, keyed `expansion:<index>` |
| `pathable_points`, `pathable_sample_spacing` | cached once available | the coarse ground lattice (below) |
| `pathable_visibility` | every frame | whether each lattice point is in vision, aligned with `pathable_points` |
| `chokes` | cached once available | `MapChoke(key, position, width)` from MapAnalyzer |
| `traffic_routes` | when ready townhalls change | ground paths from likely enemy origins to our bases |
| `regions`, `passages` | cached once available | the region graph (below) |

`observation(key)` and `route(key)` look entries up by key.

### Visibility of a base location

A location counts as visible when **any** cell of a 5x5 townhall footprint
centred on it is visible (visibility grid value 2), not only the centre cell:
a scout passing a base sees the Hatchery without seeing its centre. Used for
`observations` and `expansions`. Without a visibility grid (test doubles) it
falls back to `bot.is_visible`.

### The enemy main scouting route

`_map_routes` builds a lap of the enemy main's walkable perimeter from
MapAnalyzer's region for the enemy start:

1. Take the region's perimeter points, dropping those within 8 of the enemy
   ramp's top (so the lap enters from a cliff, not the ramp).
2. Sort by angle around the region centre and rotate the list to start at the
   point nearest the enemy natural.
3. Keep points at least 4 apart, each pulled 2 tiles toward the main.
4. Prepend the natural, append the first perimeter point again to close the
   lap.

Maps without map analysis data produce no route; scouting then falls back to
the natural ([behavior/scouting.md](../behavior/scouting.md)).

### The pathable lattice

`_sample_pathable_points` samples Ares' initial pathing grid every `spacing`
cells, starting at `spacing // 2`, keeping pathable cells as points at cell
centres (`x + 0.5`, `y + 0.5`). The spacing is `AresWorldObserver`'s
`spatial_sample_spacing` -- 2 in real games (`run.py`), 10 by default in tests.
Every spatial reading ([spatial-field.md](spatial-field.md),
[territory.md](territory.md)) is indexed by these points.

`pathable_visibility` reads the visibility grid once per frame at every
lattice point's cell, vectorised; the row/column indices are computed once
per lattice.

### Chokes

`MapChoke.width` is the distance between the choke's `side_a` and `side_b`
where MapAnalyzer measured them (plus one cell for ramps, whose sides are
their outermost cells), at least 1. Vision blockers and areas without sides
report `None`, which consumers must not read as narrow.

### The region graph

`_region_graph` runs once, when both the lattice and MapAnalyzer's regions
exist:

- **Membership.** Each lattice point takes the region `in_region_p` places it
  in. A point no region covers (a ramp, an unbuildable plate) takes the region
  of a point it reaches in one straight lattice step whose every cell is
  pathable, spreading breadth-first.
- **Regions.** `MapRegion(key="region:<label>", center, points, expansions)`,
  with the region's own centre or the mean of its points, and its expansion
  slots.
- **Passages.** Every MapAnalyzer choke bordering two kept regions becomes a
  `MapPassage` (`choke:<index>`, or `choke:<index>:<a>:<b>` when it borders
  more than two). Where no choke joins two regions, the straight pathable
  lattice steps between their points become one `border:<a>|<b>` passage at
  the mean crossing. A cliff breaks the step, so high and low ground only
  meet through a real passage.

The result is tens of regions and passages, never a per-tile graph (10
regions and 16 passages on the last recorded map).

### Traffic routes

`_ground_traffic_routes` asks MapAnalyzer's pathfinder for a ground path
(sensitivity 3, no smoothing) from every enemy start and the enemy natural to
every ready, landed own townhall (or our start location when none). Townhalls
are sorted by position first: the game does not list our structures in a stable
order, and with two or more bases that alone used to re-path every other frame.
The result is cached by the endpoint positions; a pathfinding exception keeps
the partial result and retries the same endpoints after 2 seconds.

### Versioning by identity

The adapter keeps returning the same tuple objects for static data until the
data changes. Readers that cache (the spatial field, territory) treat tuple
identity as an O(1) version token and fall back to equality only when
identity differs. An empty result is never cached, because map analysis may
not be ready on the first frames.

## Known gaps

- The adapter exposes Ares' memory flag but not how long ago a memory unit was
  last seen. A unit already in Ares memory when Awareness first sees it has an
  unknown sighting time; Awareness treats it as stale, never fresh
  ([awareness.md](awareness.md#confidence)).
- Only `BANSHEECLOAK` research progress is tracked; other upgrades are only
  known once finished.
