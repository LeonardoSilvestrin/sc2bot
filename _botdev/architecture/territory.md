# Territory

`AwarenessSnapshot.territory` (`bot/world/awareness/territory/`) is the
perceived state of the map's territory: who holds each place, how well we
know it, where the two sides meet, and how exposed each region is to enemy
ground forces. It is perception only. It says "the natural is `FRIENDLY`,
the main has `ground_security` 0.91", never "defend the third".

**Shadow mode.** Territory is computed, tested and logged, but no behavior,
macro or engine code reads it yet. `tests/test_territory.py`
(`ShadowModeTests`) fails if one starts to, so wiring a consumer is a
deliberate change: delete that guard when Strategy lands. The thresholds
below are first guesses, left untuned until shadow-mode logs show where they
are wrong.

## Three independent dimensions

| Dimension | Question | Where |
| --- | --- | --- |
| Control | who dominates this place, and how sure are we? | `TerritoryReading.control`, `dominance`, `confidence` |
| Value | how much does this place matter? | `SpatialField` (`choke_value`, `route_value`) |
| Security | how reachable is it to enemy ground forces? | `RegionTerritory.ground_access` / `ground_security` |

A choke can be valuable and enemy-held; a region can be ours and worthless.
Territory never folds value into control.

## What is static, what is dynamic

| Data | Lifetime | Source |
| --- | --- | --- |
| `pathable_points` (lattice, 10 tiles) and `chokes` | once, as soon as Ares has them | `AresWorldObserver._map_topology` |
| `regions` and `passages` (region graph) | once, as soon as MapAnalyzer has them | `AresWorldObserver._region_graph` |
| `traffic_routes` (A* from enemy origins to our bases) | whenever the set of ready townhalls changes | `AresWorldObserver._ground_traffic_routes` |
| `TerritoryTopology` (sample regions, access graph, origins, lattice neighbours, nearest samples) | once per version of the above | `build_topology` |
| `pathable_visibility` (which samples are in vision now) | every frame, one vectorised grid read | `AresWorldObserver._pathable_visibility` |
| when each sample was last seen | recorded every frame | `ObservationMemory` |
| units, enemy clusters, bases | every frame | Attention / Awareness |
| spatial threat and confidence | 2 s cadence, or at once on a meaningful cluster change | `SpatialFieldModel` |
| territory readings, frontline, ground access | 1 s cadence (`TerritoryConfig.update_interval`) | `TerritoryAssessor` |

Awareness itself never pathfinds. Its only pathing use is the traffic-route
A* the adapter runs when our bases change.

## Region graph (adapter, once)

`_region_graph` takes MapAnalyzer's regions over the coarse samples:

- Each sample belongs to the region `in_region_p` places it in. A sample on
  ground no region covers (a ramp, an unbuildable plate) takes the region of
  a sample it reaches in one straight, fully pathable lattice step.
- Each MapAnalyzer choke that borders two kept regions is a `MapPassage`
  (`choke:<index>`). Where no choke joins two regions, their straight
  pathable steps are one `border:<a>|<b>` passage at the mean crossing. A
  cliff breaks the step, so high and low ground only meet through a real
  passage.

The result is tens of regions and passages, never a per-tile graph.

## Influence

Every source uses the shared kernel in `spatial/kernel.py`:
`K(d, σ) = exp(-0.5·d²/σ²)` and `S(x) = 1 - exp(-x)`. Both sides spread their
forces through the same `force_influence`, which is also the spatial field's
threat.

```text
military_raw(p) = Σ_force  strength · confidence / 8 · K(|p - c|, 12 + radius + uncertainty)
site_raw(p)     = Σ_base   0.6 · confidence · K(|p - b|, 14)

F        = S(friendly military_raw + site_raw)   # our army and townhalls
F_mil    = S(friendly military_raw)              # our army alone
F_ground = S(friendly military_raw, anti-ground strength only)
E        = S(enemy military_raw + site_raw)      # enemy clusters and confirmed bases
```

- **Friendly military.** Our combat units, never workers, are grouped exactly
  like enemy clusters (single linkage, 7 tiles). A force's strength is its
  supply; its confidence is 1 and its uncertainty 0. `F_mil` counts every
  combat unit, since a Viking is still military presence. `F_ground` counts
  only what can fight ground units, since only that denies a ground passage.
- **Friendly infrastructure.** Each held townhall, with confidence 1.
- **Enemy military.** The existing `EnemyForceCluster`s, unchanged. A stale
  cluster keeps its strength, but its weight falls with `confidence` and its
  reach widens with `position_uncertainty`: it fades out smoothly instead of
  vanishing.
- **Enemy infrastructure.** Each confirmed enemy base, weighted by its
  `confidence`.

## Confidence

`confidence` answers "how well do we know the enemy side of this reading?"
Our own side is always known. Not seeing an enemy only counts as knowing
there is none where we have actually looked:

```text
observation(p) = 1 while p is in vision, fading linearly to 0 over 30 s after the last look
                 (0 if never seen)
remembered(p)  = E_raw(p) / (E_evidence(p) + 0.25)
                 E_raw:      enemy raw influence as still believed (each source × its confidence)
                 E_evidence: the same, were every source current
confidence(p)  = max(observation(p), remembered(p))
```

| Case | confidence |
| --- | --- |
| a place in vision now, empty | 1.0 |
| an enemy area unscouted for two minutes, nothing known there | **0.0** (still `UNCONTROLLED`) |
| looked at 15 s ago | 0.5 |
| a fresh 16-supply enemy army standing there, out of vision | 2 / 2.25 ≈ 0.89 |
| 30 tiles from that army | ≈ 0.26 (a kernel tail vouches for little) |
| an enemy base believed at 0.5, alone at its slot | 0.3 / 0.85 ≈ 0.35 |

- `0.25` (`undetected_presence`) is the raw enemy influence, about two supply,
  that could stand anywhere unseen. Remembered sources only vouch for a place
  where they clearly outweigh it.
- The observation window (`observation_stale_after`) matches the 30 s Ares
  remembers an unseen unit for.
- The better of the two clues is kept, never combined: two stale clues do not
  add up to a fresh one.
- A scout passing between two territory updates still counts, because
  visibility is recorded every frame.
- A region and the whole snapshot report the **plain mean** of their
  samples' confidence, so unwatched space drags them down however empty it
  looks.

## Dominance and classification

```text
dominance = (F - E) / (F + E + 1e-6)          # -1 enemy .. 0 balanced/empty .. +1 ours
presence  = 1 - (1 - F)(1 - E)

presence < 0.2                        -> UNCONTROLLED
required = 0.4 + 0.3 · (1 - confidence)
dominance >=  required                -> FRIENDLY
dominance <= -required                -> ENEMY
otherwise                             -> CONTESTED
```

- `0/0` gives dominance 0 and `UNCONTROLLED`, never `CONTESTED`, and its
  confidence says whether that is knowledge or ignorance.
- `0.001` against nothing gives dominance ≈ 1, but it is still
  `UNCONTROLLED`.
- Low confidence widens the contested band, so a mixed reading we cannot see
  does not name a side.
- Each threshold moves 0.05 in favour of the class the place already had
  (hysteresis, the last stabilising layer).

Every number lives in `TerritoryConfig`.

A **sample** reads at its lattice point. A **region** reads the mean
influences of its samples, classified the same way (a region too small for a
sample reads at its centre). A **passage** reads at its position; its
observation, like a small region's, comes from the nearest sample.

## Frontline

For each pair of lattice axis neighbours (static) where neither sample is
`UNCONTROLLED` and dominance changes sign (`d_a > 0 ≥ d_b`), a frontline point
lies at the linear zero crossing:

```text
point = p_a + d_a / (d_a - d_b) · (p_b - p_a)
```

For `F F C E E` with the contested sample at 0, the frontline is exactly that
sample. The crossing slides continuously as dominance changes. The edge of
our territory against empty map is a border, not a front.

## Ground access and security

The graph has one node per region and per passage:

```text
hold(n)   = F_ground(n) · max(0, dominance(n))    # a ground-capable army, never a base
pass(n)   = 1 - hold(n)   for a passage,  1 for a region
source(n) = max(E(n), 1.0 if n is an enemy start region)

leaving(n) = max(source(n), arrived(n) · pass(n))
arrived(m) = max over neighbours n of leaving(n)
access(n)  = max(source(n), arrived(n))         # a node's own hold never shields it
security   = 1 - access
```

This is the widest path under products of factors ≤ 1, so it settles in
Dijkstra order (`ground_access`). Nothing is hardcoded: the main is secure
only because every path to it crosses a passage we hold. With two routes, the
open one sets the access.

**Only passages are barriers.** A region says who holds it; a passage says
how blocked the way through is. The first model also let every region block.
One army parked in the natural then read as three consecutive walls:
passage in front, the natural itself, then the ramp. That is why the main
reached 0.99. That model is still computed as
`RegionTerritory.layered_ground_access`, logged next to the passage model so
matches can decide between them. Delete it once they have.

## Example

The layout is `enemy main — third — natural — main` along one line, with our
townhalls in the third, natural and main, a fresh 16-supply enemy army at the
enemy natural, and our three bases in vision (real code, rounded). Each cell
reads control, then `ground_security` in the passage model / layered model.

| | army (24 supply) holding the natural | army forward at the third | no army | holding the natural, nothing in vision |
| --- | --- | --- | --- | --- |
| enemy main | ENEMY, 0.00 / 0.00 (conf 0.86) | ENEMY, 0.00 / 0.00 | ENEMY, 0.00 | ENEMY, 0.00 (conf 0.86) |
| third | FRIENDLY, 0.00 / 0.00 | FRIENDLY, 0.00 / 0.00 | CONTESTED, 0.00 | **CONTESTED**, 0.00 (conf 0.37) |
| natural | FRIENDLY, **0.70** / 0.71 | FRIENDLY, **0.70** / 0.88 | FRIENDLY, 0.00 | FRIENDLY, 0.70 (conf **0.00**) |
| main | FRIENDLY, **0.91** / 0.99 | FRIENDLY, **0.70** / 0.89 | FRIENDLY, 0.00 | FRIENDLY, 0.91 (conf **0.00**) |

- The third stays exposed in every case: no passage we hold stands between it
  and the enemy.
- With the army forward, the passage model no longer credits the natural's
  interior as a wall behind the third, so natural and main share the one
  passage that is held.
- Without vision the same influences stay, but every reading we cannot see
  loses its confidence, and the uncertain third stops naming a side.

## Cost

- **Startup, once:** region graph in the adapter (one `in_region_p` per
  sample plus about 20 grid reads per lattice step), then `build_topology`,
  O(samples · (regions + passages)).
- **Every frame:** one vectorised visibility read in the adapter, the
  observation record, and four identity checks plus a cadence check:
  about 0.013 ms in Awareness.
- **Every second:** friendly grouping O(units); influence
  O(samples · (forces + bases)); region means O(samples); passages
  O(passages · forces); frontline O(samples); two access walks
  O((R + P) log(R + P)). About 7.6 ms for 300 samples, 30 regions,
  40 passages and 12 forces.
- Nothing is O(samples²), and there is no pathfinding at runtime.
  `TerritoryAssessor.topology_rebuilds` counts rebuilds, and
  `tests/test_territory.py` asserts that unchanged topology is never rebuilt.

## Telemetry

`knowledge.territory` (`world.awareness.territory`) aggregates:

- samples and regions counted per control;
- the map's mean confidence;
- frontline size with up to six points;
- for every held base and every expansion region: control, confidence,
  `ground_security` and `layered_ground_security` (expansion regions also
  log dominance).

It is logged when one of those regions changes control or crosses a 0.2
security step, a base changes region, or the frontline appears or
disappears, plus a ten-second heartbeat. `territory.perf` reports the update
cost and counters on a ten-second heartbeat.

## Deliberately out of scope

- Air security, naval or transport topology. Access is ground only. An enemy
  source still counts all enemy influence, air units included, which
  overstates access.
- Unwatched space as a possible enemy ingress. Low confidence is reported,
  but ground access does not yet assume anything hides there.
- Static defense as a blocker: bunkers, fortresses and cannons count as
  nothing here, as in enemy clusters.
- `SpatialFieldSample.confidence` keeps its older meaning (1.0 where no
  cluster reaches). Map Control only logs it.
- Visibility is read at each sample's own cell.
- Strategy, and every consumer: Map Control, the main army
  (`StandingPlanner`), Defense, Harass, Scouting, Macro, arbitration and
  allocation are unchanged.
- Travel time, combat simulation, exact region polygons, threshold tuning.
