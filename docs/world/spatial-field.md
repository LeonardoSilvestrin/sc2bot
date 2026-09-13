# Spatial field

A coarse, continuous description of the map exposed by Awareness: at every
point of the pathable lattice, how close our bases are, where the enemy
credibly controls, where an enemy force may threaten, how well the location
is known, how much it looks like a choke, and how much ground traffic passes
by. Independent properties, never folded into one score:
what they are worth is the reading behavior's call (today, map control).

Source: `bot/world/awareness/spatial/` (`field.py`, `kernel.py`, `model.py`,
`performance.py`).

## The field

`SpatialField(samples, updated_at, sample_spacing)`, one `SpatialFieldSample`
per lattice point:

| Sample field | Range | Meaning |
| --- | --- | --- |
| `position` | -- | the lattice point |
| `friendly_value` | 0..1 | nearness to our bases |
| `friendly_control` | 0..1 or `None` | actual bounded friendly territorial influence projected from territory; `None` before projection |
| `enemy_control` | 0..1 | bounded credible enemy territorial influence, projected from the territory pass |
| `enemy_threat` | 0..1 | believed enemy force reaching the point |
| `choke_value` | 0..1 | nearness to narrow chokes |
| `route_value` | 0..1 | nearness to ground paths from enemy origins to our bases |
| `confidence` | 0..1 | how well the threat there is known; 0 where no believed force reaches |
| `knowledge_confidence` | 0..1 | how well the location is known from vision memory or credible enemy evidence |

Lookups: `candidates` (every sample), `at(position)` (nearest sample),
`near(position, radius)` (samples within the radius, nearest first).

Until the adapter has a lattice, the field holds a single sample at the map
centre.

## Shared kernel (`kernel.py`)

Two related kernels now express two different claims.

Before the separation, both threat and territory used this formula:

```text
K(d, sigma) = exp(-0.5 * d^2 / sigma^2)          spreads one source smoothly
S(x)        = 1 - exp(-max(0, x))                saturates a sum into [0, 1)

spread = sigma + force.radius + force.position_uncertainty
locality = K(|p - force.center|, spread)
raw += strength * force.confidence * locality / full_strength
```

That was the oversized-red-territory bug: losing vision raised
`position_uncertainty`, which widened the same Gaussian used for ownership.
Even while confidence fell, distant samples could gain enemy influence.

The formula remains correct for possible threat:

```text
force_influence(p, forces, sigma, full_strength, ground_only=False):
    for each force:
        strength = anti_ground_strength if ground_only else combat_strength
        spread   = sigma + force.radius + force.position_uncertainty
        locality = K(|p - force.center|, spread)
        raw      += strength * force.confidence * locality / full_strength
        evidence += strength * locality / full_strength          (as if seen this instant)
        if locality > 0.01:
            weight = locality * max(strength, 0.01)
            confidence accumulates weight * force.confidence
    confidence = weighted mean of force confidences, 0 where no force reaches
```

A stale force can therefore threaten a wider area while becoming weaker and
less certain. Territorial ownership instead uses:

```text
force_control_influence(p, forces, sigma, max_reach, full_strength):
    edge_distance = max(0, |p - force.center| - force.radius)
    edge_distance >= max_reach -> no influence
    locality = K(edge_distance, sigma)
    raw += strength * force.confidence * locality / full_strength
```

Position uncertainty is intentionally absent. Strength deepens control inside
the observed footprint and its bounded combat reach; no amount of strength
can extend control beyond `force.radius + max_reach`.

## Formulas (`model.py`)

Defaults from `SpatialModelConfig`:

```text
friendly_value = S( sum over own bases of  w * K(d, 18) )      w = 1.0 for the main, 1.15 for other bases
enemy_threat   = S( force_influence(p, enemy clusters, sigma 7, full 8).raw )
confidence     =    force_influence(p, enemy clusters, sigma 7, full 8).confidence
enemy_control  = territory sample's bounded enemy influence
friendly_control = territory sample's bounded friendly influence
knowledge_confidence = territory sample's observation/evidence confidence
choke_value    = S( sum over chokes of  narrowness * K(d, 5) )
                 narrowness = min(1, 5 / max(1, width)),  0.5 when the width is unmeasured
route_value    = S( sum over traffic routes of  K(distance to the route, 4.5) )
                 a route is reduced to points every 8 tiles of path length
```

A force of 8 supply standing on a point reads raw threat 1, saturated 0.63.
The control and knowledge projection is cached by spatial/territory snapshot
identity and rebuilt only when either snapshot changes; it does not add a
second per-frame lattice scan.

## Caching

The four components change at very different rates, so each has its own
cache and is only recomputed when its inputs change. Composing a new
`SpatialField` happens only when any component was rebuilt.

| Component | Rebuilt when |
| --- | --- |
| static (lattice points, choke values) | the lattice or chokes change version, the spacing changes, or -- with no lattice yet -- the map centre changes |
| friendly | the set of own bases (id, position, main flag) changes; the order they are listed in does not count |
| routes | the traffic routes change version |
| threat and confidence | the quantized cluster key changes (id, centre per 2 tiles, radius and uncertainty per 2 tiles, strength per 0.5 supply, confidence per 0.1), or 2 s have passed (`update_interval`) |

A static rebuild invalidates the other three, since they are indexed by the
samples. Versions are tuple identity first, equality as the fallback (see
[attention.md](attention.md#versioning-by-identity)).

`SpatialPerformance` records, per component, what the cache check cost and
what the rebuild cost, plus rebuild counters; `spatial.perf` logs it every
10 s.

## Who reads it

| Reader | Uses |
| --- | --- |
| `MapControlPlanner` | scores every sample to pick the patrol anchor ([behavior/map-control.md](../behavior/map-control.md)) |
| `MapControlExecutor` | `near(anchor, 1.5 steps)` for the patrol loop |
| `TerritoryAssessor` | sample positions and spacing as its lattice |
| `AwarenessService` | projects the cadenced territory control/knowledge readings onto the strategy-facing samples |
| `SpatialDebugView` | sample positions and spacing for the grid view |

## Cost

On Ley Lines (spacing 2, 2935 samples, about 11 frames per game second):

- A frame where every cache holds costs about 0.01 ms; the first frame builds
  everything (about 320 ms, most of it the static component).
- A route rebuild costs 60-130 ms (samples times route points), a friendly or
  threat rebuild about 4 ms, composing the field about 4 ms more.
- Friendly and routes rebuild only when a townhall is added, finishes or is
  lost (3 times each in a 600 s game); threat on its cadence or a quantized
  change, about 0.8 times per second. The model averages about 0.75 ms per
  frame.
- Projecting 3000 territory readings into strategy-facing spatial samples
  costs about 6.0 ms on the development machine, only when either cached
  snapshot changes (normally once per territory second), never every frame.

Earlier games rebuilt friendly and routes on about every other frame from the
second townhall on (thousands of times, around 100 s of CPU in a 350 s game).
The game lists our structures in a different order between frames, and both
the friendly key and the traffic-route endpoints were ordered tuples, so the
same bases read as a new version. Both are now order-independent.

## Known gaps

- The field is ground only; flying units path over nothing it describes.
- Threat counts every armed enemy cluster regardless of which domain it can
  attack; readers that care (the raids) use the clusters directly.
- Euclidean/travel estimates do not prove connected ground reachability; all
  candidates are pathable lattice samples, and movement still delegates to
  Ares' safe ground path.
