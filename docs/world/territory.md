# Territory

`AwarenessSnapshot.territory` is the perceived state of the map's territory:
who holds each place, how well we know it, where the two sides meet, and how
exposed each region is to enemy ground forces. It is perception only. It says
"the natural is `FRIENDLY`, the main has `ground_security` 0.91", never
"defend the third".

Source: `bot/world/awareness/territory/` (`assessor.py`, `influence.py`,
`topology.py`, `frontline.py`, `observation.py`, `model.py`, `config.py`),
region graph in `bot/adapters/ares/world_observer.py`.

`TerritorySnapshot` remains an Awareness/debug model: behavior, macro and
engine code do not couple to its region graph or types. `AwarenessService`
does project each sample's bounded enemy influence and knowledge confidence
onto `SpatialFieldSample`, where Map Control can consume those generic
signals. The existing architecture guard still prevents direct territory
dependencies outside the application/Awareness layers.

## Three independent dimensions

| Dimension | Question | Where |
| --- | --- | --- |
| Control | who dominates this place, and how sure are we? | `TerritoryReading.control`, `dominance`, `confidence` |
| Value | how much does this place matter? | `SpatialField` (`choke_value`, `route_value`) |
| Security | how reachable is it to enemy ground forces? | `RegionTerritory.ground_access` / `ground_security` |

A choke can be valuable and enemy-held; a region can be ours and worthless.
Territory never folds value into control.

## Snapshot

| `TerritorySnapshot` | Content |
| --- | --- |
| `samples` | a `TerritorySample(position, reading, region)` per lattice point |
| `regions` | a `RegionTerritory(key, center, expansions, reading, ground_access, layered_ground_access)` per region; `ground_security = 1 - ground_access` |
| `passages` | a `PassageTerritory(key, position, regions, reading)` per passage |
| `bases` | a `BaseTerritory(base_id, position, region)` per own base |
| `friendly_forces` | the `FriendlyForce` clusters used this update |
| `frontline` | points where friendly and enemy dominance meet |
| `confidence` | mean sample confidence: how much of the map we currently know |
| aggregate enemy metrics | remembered cluster count, oldest memory, largest uncertainty, control radius and possible-presence radius |
| `updated_at` | game time of the update |

Lookups: `region(key)`, `region_at(position)`, `at(position)`,
`count(control)`.

`TerritoryReading` fields: `friendly_influence` (F), `enemy_influence` (E),
`dominance`, `control`, `confidence`, `friendly_military`,
`friendly_ground_denial`, `enemy_ground_military`, `enemy_ground_presence`;
properties `presence` and `hold`.

## What is static, what is dynamic

| Data | Lifetime | Source |
| --- | --- | --- |
| lattice points and chokes | once, when Ares has them | `AresWorldObserver._map_topology` |
| regions and passages | once, when MapAnalyzer has them | `AresWorldObserver._region_graph` ([attention.md](attention.md#the-region-graph)) |
| `TerritoryTopology` (sample regions, access graph, enemy origins, lattice edges, nearest samples) | once per version of the above, plus spacing and enemy starts | `build_topology` |
| which samples are in vision | every frame | `MapFacts.pathable_visibility` |
| when each sample was last seen | recorded every frame | `ObservationMemory` |
| own units, enemy clusters, bases | every frame | Attention / Awareness |
| readings, frontline, ground access | every 1 s (`update_interval`); the previous snapshot in between | `TerritoryAssessor` |

A topology rebuild resets the observation memory and the hysteresis history.

## Influence sources

| Side | Military | Infrastructure |
| --- | --- | --- |
| Friendly | our armed non-worker units grouped exactly like enemy clusters (single linkage, 7 tiles); strength in supply (0.25 for zero-supply), confidence 1, uncertainty 0 | each held base, weight 1 |
| Enemy | the `EnemyForceCluster`s, with confidence; position uncertainty does **not** enter control | each confirmed enemy base, weighted by its confidence |

## The reading at a point (`influence.py`)

With `force_control_influence` and the kernel from [spatial-field.md](spatial-field.md#shared-kernel-kernelpy)
(`TerritoryConfig` defaults):

```text
site(p, b)    = 0.6 * K(|p - b|, 14)

control(p, force):
    edge_distance = max(0, |p - force.center| - force.radius)
    edge_distance >= 24 -> 0
    otherwise K(edge_distance, 12) * strength * confidence / 8

friendly_raw  = sum control(p, friendly forces) + sum over own bases of site(p, b)
F             = S(friendly_raw)
F_mil         = S(force_influence(p, friendly forces).raw)                    our army alone
F_ground      = S(force_influence(p, friendly forces, ground_only).raw)       what can fight ground units

enemy         = sum control(p, enemy clusters)
enemy_raw     = enemy.raw      + sum over confirmed enemy bases of site(p, b) * base confidence
evidence      = enemy.evidence + sum over confirmed enemy bases of site(p, b)
E             = S(enemy_raw)
E_ground_mil  = S(force_influence(p, enemy clusters, ground_only).raw)        enemy army that fights ground
E_ground_pres = S(ground_only enemy raw + enemy base sites * confidence)      what can originate ground access
```

The pre-fix control spread was `12 + radius + position_uncertainty`. Thus a
lost sighting could increase distant `enemy_raw` solely because uncertainty
grew. Control now ends exactly at the observed cluster radius plus 24 tiles;
uncertainty remains in `SpatialField.enemy_threat` only. Confidence decay
still reduces control continuously, and confidence 0 removes it.

Each component is clamped so the parts never exceed the whole (`F_ground <=
F_mil <= F`, `E_ground_mil <= E`, `E_ground_pres <= E`).

- `F_mil` counts every combat unit: a Viking is still military presence.
  `F_ground` counts only what can fight ground units, since only that denies
  a ground passage.
- A base makes a place ours but stops no one: bases add to F, never to
  `F_mil` or `F_ground`.
- Enemy forces that cannot attack ground add to E but not to
  `E_ground_pres`, so they do not originate ground access. Enemy bases do,
  because they can produce ground forces.

## Confidence

"How well do we know the enemy side of this reading?" Our side is always
known.

```text
observation(p) = 1 while p is in vision, fading linearly to 0 over 30 s after the last look; 0 if never seen
remembered(p)  = enemy_raw / (evidence + 0.25)
confidence(p)  = clamp(max(observation, remembered), 0, 1)
```

| Case | Confidence |
| --- | --- |
| a place in vision now, empty | 1.0 |
| an enemy area unscouted for minutes, nothing known there | 0.0 (still `UNCONTROLLED`) |
| looked at 15 s ago | 0.5 |
| a fresh 16-supply enemy army standing there, out of vision | about 0.89 |
| far out on that army's kernel tail | low: a tail vouches for little |
| an enemy base believed at 0.5, alone at its slot | about 0.35 |

- `0.25` (`undetected_presence`) is the raw enemy influence, about two supply,
  that could stand anywhere unseen. Remembered sources only vouch for a place
  where they clearly outweigh it.
- The better of the two clues is kept, never combined: two stale clues do not
  add up to a fresh one.
- A scout passing between two territory updates still counts, because
  visibility is recorded every frame.
- Regions and the whole snapshot report the **plain mean** of their samples'
  confidence, so unwatched space drags them down however empty it looks.

## Dominance and classification

```text
dominance = clamp((F - E) / (F + E + 1e-6), -1, 1)     -1 enemy .. 0 balanced or empty .. +1 ours
presence  = 1 - (1 - F)(1 - E)

presence < 0.2                    -> UNCONTROLLED
required  = 0.4 + 0.3 * (1 - confidence)
dominance >=  required            -> FRIENDLY
dominance <= -required            -> ENEMY
otherwise                         -> CONTESTED
```

- Hysteresis: each threshold moves 0.05 in favour of the class the place
  already had, and 0.05 against entering another class. It is the last
  stabilising layer.
- `0/0` gives dominance 0 and `UNCONTROLLED`, never `CONTESTED`; confidence
  says whether that is knowledge or ignorance.
- A tiny influence against nothing has dominance near 1 but stays
  `UNCONTROLLED`.
- Low confidence widens the contested band, so a mixed reading we cannot see
  does not name a side.

Where readings are taken:

- A **sample** reads at its lattice point.
- A **region** averages its samples' F, E and components and their
  confidences, then classifies the averages (with the region's own previous
  class). A region too small to hold a sample reads at its centre, with the
  observation of the sample nearest the centre.
- A **passage** reads at its position, with the observation of the nearest
  sample.

## Frontline (`frontline.py`)

For each pair of lattice axis neighbours (points at most 1.2 spacings apart,
computed once per topology) where neither sample is `UNCONTROLLED` and
dominance changes sign (`d_a > 0 >= d_b`), a frontline point lies at the
linear zero crossing:

```text
point = p_a + d_a / (d_a - d_b) * (p_b - p_a)
```

The crossing slides continuously as dominance changes. The edge of our
territory against empty map is a border, not a front.

## Ground access and security (`topology.py`, `assessor.py`)

The access graph has one node per region (indices `0..R-1`) and one per
passage, each passage joined to its two regions.

```text
source(n)  = E_ground_pres(n)
             raised to 1.0 for each enemy start region
             if no enemy start could be placed in the graph: every region is a source at 1.0

pass(n)    = 1 for a region            (only passages are barriers)
           = 1 - hold(n) for a passage, where

    each friendly force that can fight ground is assigned to the ONE passage where its
    ground-only influence is strongest; per passage:
        friendly = S(sum of the assigned forces' ground-only raw influence at the passage)
        hold     = friendly * clamp((friendly - E_ground_mil) / (friendly + E_ground_mil + 1e-6), 0, 1)

leaving(n) = max(source(n), arrived(n) * pass(n))
arrived(m) = max over neighbours n of leaving(n)
access(n)  = max(source(n), arrived(n))           a node's own hold never shields it
security   = 1 - access
```

This is the widest path under products of factors at most 1, so it settles in
Dijkstra order, `O((V + E) log V)` on tens of nodes. Nothing is hardcoded:
the main is secure only because every path to it crosses a passage we hold,
and with two routes in, the open one sets the access.

**Why one force counts at one passage.** A force's smooth influence reaches
several passages. Counting it at each would turn one army into several
consecutive walls. Forces assigned to different passages still compound.

**Why only passages block.** The first model let every region block too, so
one army parked in the natural read as three walls -- the passage in front,
the natural, the ramp -- and the main reached 0.99. That model is still
computed as `layered_ground_access` (every node's pass is `1 - reading.hold`,
where `hold = F_ground * clamp(ground dominance)`) and logged beside the
passage model, so games can decide between them. Delete it once they have.

`BaseTerritory.region` is found through the topology: the region of the
expansion slot within 3 tiles of the base, otherwise the region of the
nearest sample that has one.

## Behavior in typical layouts

Along a line `enemy main -- third -- natural -- main`, with our townhalls in
the third, natural and main and an enemy army at its natural:

- **Army holding the natural's passage:** natural and main are secure; the
  third stays exposed, because no passage we hold stands between it and the
  enemy.
- **Army forward at the third:** the natural's interior no longer counts as a
  wall behind the third, so natural and main share the one held passage.
- **No army:** every region is exposed; bases make regions `FRIENDLY` but
  hold nothing.
- **Same army, nothing in vision:** influences stay, but readings we cannot
  see lose confidence, and an uncertain mixed region stops naming a side.

`tests/test_territory.py` builds these scenes and asserts the relations.

## Cost

On the last recorded game (spacing 2, 3094 samples, 10 regions, 16
passages), `territory.perf` reported **32-65 ms per update**, once per game
second, with a single topology build. The per-sample influence loop is
Python and linear in `samples x (forces + bases)`, so it scales with the
lattice: an earlier estimate of about 7.6 ms was for 300 samples at spacing
10.

- Every frame: `ObservationMemory.record` walks the visibility of every
  sample (`O(samples)`), then a cadence check returns the cached snapshot.
- Every second: friendly grouping `O(units)`; influence `O(samples * (forces +
  bases))`; region means `O(samples)`; passage assignment `O(forces *
  passages)`; frontline `O(edges)`; two access walks.
- Nothing is `O(samples^2)`, and there is no pathfinding at runtime.
  `TerritoryAssessor.topology_rebuilds` counts rebuilds, and the tests assert
  that an unchanged topology is never rebuilt.

## Telemetry

`knowledge.territory` (component `world.awareness.territory`) aggregates:
samples and regions counted per control; the mean confidence; the frontline
size with up to six points; for every held base its region, control,
`ground_access`, `ground_security`, `layered_ground_security` and confidence;
for every region with an expansion slot its centre, control, dominance,
confidence and both securities; enemy-control and threat sample counts;
remembered-cluster count, oldest memory, and largest uncertainty/control/
possible-presence radii. It is logged when an expansion region changes
control or crosses a 0.2 security step, a base changes region, or the
frontline appears or disappears, plus a ten-second heartbeat. `territory.perf`
reports cost and counters every 10 s. See [logging.md](../logging.md).

## Deliberately out of scope

- Air security, naval or transport topology. Access is ground only.
- Unwatched space as a possible enemy ingress: low confidence is reported,
  but access does not assume anything hides there.
- Static defense as a blocker: Bunkers, fortresses and cannons count as
  nothing here.
- Visibility is read at each sample's own cell.
- Consumers do not read the territory region graph. Map Control receives only
  the generic per-sample `enemy_control` and `knowledge_confidence` projection.
- Travel time, combat simulation, exact region polygons, threshold tuning.
