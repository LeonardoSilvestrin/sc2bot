# Territory

`AwarenessSnapshot.territory` (`bot/world/awareness/territory/`) is the
perceived state of the map's territory: who holds each place, where the two
sides meet, and how exposed each region is to enemy ground forces. It is
perception only. It says "the natural is `FRIENDLY`, the main has
`ground_security` 0.99", never "defend the third".

**Shadow mode.** Territory is computed, tested and logged, but no behavior,
macro or engine code reads it yet. `tests/test_territory.py`
(`ShadowModeTests`) fails if one starts to, so wiring a consumer is a
deliberate change: delete that guard when Strategy lands.

## Three independent dimensions

| Dimension | Question | Where |
| --- | --- | --- |
| Control | who dominates this place? | `TerritoryReading.control`, `dominance` |
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
| `TerritoryTopology` (sample regions, access graph, origins, lattice neighbours) | once per version of the above | `build_topology` |
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
site_raw(p)     = Σ_base   0.6 · weight · K(|p - b|, 14)

F_mil = S(friendly military_raw)              # our army only
F     = S(friendly military_raw + site_raw)   # our army and townhalls
E     = S(enemy military_raw + site_raw)      # enemy clusters and confirmed bases
```

- **Friendly military.** Our combat units, never workers, are grouped exactly
  like enemy clusters (single linkage, 7 tiles). A force's strength is its
  supply; its confidence is 1 and its uncertainty 0.
- **Friendly infrastructure.** Each held townhall, with weight 1.
- **Enemy military.** The existing `EnemyForceCluster`s, unchanged. A stale
  cluster keeps its strength, but its weight falls with `confidence` and its
  reach widens with `position_uncertainty`: it fades out smoothly instead of
  vanishing.
- **Enemy infrastructure.** Each confirmed enemy base, weighted by its
  `confidence`.

`confidence = (F + E·c_E) / (F + E)`: our side is always current, and `c_E` is
the locality- and strength-weighted confidence of the clusters reaching the
point (1.0 where none does).

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

- `0/0` gives dominance 0 and `UNCONTROLLED`, never `CONTESTED`.
- `0.001` against nothing gives dominance ≈ 1, but it is still
  `UNCONTROLLED`.
- Low confidence widens the contested band, so a mixed reading built on a
  stale cluster does not name a side.
- Each threshold moves 0.05 in favour of the class the place already had
  (hysteresis, the last stabilising layer). The first stabiliser is the
  estimate itself: smooth kernels, and clusters that fade instead of blink.

Every number lives in `TerritoryConfig`.

A **sample** reads at its lattice point. A **region** reads the mean `F`,
`E` and `F_mil` of its samples, classified the same way (a region too small
for a sample reads at its centre). A **passage** reads at its position.

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

The graph has one node per region and per passage. Per node `n`:

```text
hold(n)   = F_mil(n) · max(0, dominance(n))     # only an army blocks ground passage
pass(n)   = 1 - hold(n)
source(n) = max(E(n), 1.0 if n is an enemy start region)

leaving(n) = max(source(n), arrived(n) · pass(n))
arrived(m) = max over neighbours n of leaving(n)
access(n)  = max(source(n), arrived(n))         # a node's own hold never shields it
security   = 1 - access
```

This is the widest path under products of factors ≤ 1, so it settles in
Dijkstra order (`ground_access`). Nothing is hardcoded: the main is secure
only because every path to it crosses something we hold. With two routes, the
open one sets the access.

Bases make a region `FRIENDLY` but add nothing to `hold`. Without an army,
every region's ground security is 0.

## Example

The layout is `enemy main — third — natural — main` along one line, with our
townhalls in the third, natural and main, and a fresh 16-supply enemy army at
the enemy natural (`scratchpad` run of the real code, rounded):

| | army (24 supply) holding the natural | army forward at the third | no army |
| --- | --- | --- | --- |
| enemy main | ENEMY, security 0.00 | ENEMY, 0.00 | ENEMY, 0.00 |
| third | FRIENDLY (dom +0.41), 0.00 | FRIENDLY (dom +0.65), 0.00 | CONTESTED (dom +0.34), 0.00 |
| natural | FRIENDLY, **0.71** | FRIENDLY, **0.88** | FRIENDLY, 0.00 |
| main | FRIENDLY, **0.99** | FRIENDLY, **0.89** | FRIENDLY, 0.00 |
| frontline | one point just in front of the third | (lattice gap in this synthetic layout) | one point in front of the third |

The third stays exposed in every case: nothing we hold stands between it and
the enemy. Holding the natural makes the main safer than the natural itself,
and pushing the army forward protects both.

## Cost

- **Startup, once:** region graph in the adapter (one `in_region_p` per
  sample plus about 20 grid reads per lattice step), then `build_topology`,
  O(samples + regions + passages).
- **Every frame:** four identity checks and a cadence check, about 0.004 ms.
- **Every second:** friendly grouping O(units); influence
  O(samples · (forces + bases)); region means O(samples); passages
  O(passages · forces); frontline O(samples); access O((R + P) log(R + P)).
  About 6 ms for 300 samples, 30 regions, 40 passages and 12 forces.
- Nothing is O(samples²), and there is no pathfinding at runtime.
  `TerritoryAssessor.topology_rebuilds` counts rebuilds, and
  `tests/test_territory.py` asserts that unchanged topology is never rebuilt.

## Telemetry

`knowledge.territory` (`world.awareness.territory`) aggregates: samples and
regions counted per control, frontline size with up to six points, every held
base's region/control/access/security, and every expansion region's control,
dominance and security. It is logged when one of those regions changes control
or crosses a 0.2 security step, a base changes region, or the frontline
appears or disappears, plus a ten-second heartbeat. `territory.perf` reports
the update cost and counters on a ten-second heartbeat.

## Deliberately out of scope

- Air security, naval or transport topology. Access is ground only, and air
  units still count toward territorial control and hold.
- Static defense as a blocker (bunkers, fortresses, cannons count as nothing
  here, as in enemy clusters).
- Strategy, and every consumer: Map Control, the main army (`StandingPlanner`),
  Defense, Harass, Scouting, Macro, arbitration and allocation are unchanged.
- Travel time, combat simulation and exact region polygons.
