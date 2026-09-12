# Spatial field

A coarse, continuous description of the map exposed by Awareness: at every
point of the pathable lattice, how close our bases are, how much believed
enemy force reaches it, how much it looks like a choke, and how much ground
traffic passes by. Four independent properties, never folded into one score:
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
| `enemy_threat` | 0..1 | believed enemy force reaching the point |
| `choke_value` | 0..1 | nearness to narrow chokes |
| `route_value` | 0..1 | nearness to ground paths from enemy origins to our bases |
| `confidence` | 0..1 | how well the threat there is known; 0 where no believed force reaches |

Lookups: `candidates` (every sample), `at(position)` (nearest sample),
`near(position, radius)` (samples within the radius, nearest first).

Until the adapter has a lattice, the field holds a single sample at the map
centre.

## Shared kernel (`kernel.py`)

Every spatial reading -- this field and [territory](territory.md) -- uses the
same math, so a force means the same thing to both:

```text
K(d, sigma) = exp(-0.5 * d^2 / sigma^2)          spreads one source smoothly
S(x)        = 1 - exp(-max(0, x))                saturates a sum into [0, 1)

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

A stale force reaches wider (its uncertainty grows) but weaker (its
confidence falls), and fades out smoothly instead of vanishing.

## Formulas (`model.py`)

Defaults from `SpatialModelConfig`:

```text
friendly_value = S( sum over own bases of  w * K(d, 18) )      w = 1.0 for the main, 1.15 for other bases
enemy_threat   = S( force_influence(p, enemy clusters, sigma 7, full 8).raw )
confidence     =    force_influence(p, enemy clusters, sigma 7, full 8).confidence
choke_value    = S( sum over chokes of  narrowness * K(d, 5) )
                 narrowness = min(1, 5 / max(1, width)),  0.5 when the width is unmeasured
route_value    = S( sum over traffic routes of  K(distance to the route, 4.5) )
                 a route is reduced to points every 8 tiles of path length
```

A force of 8 supply standing on a point reads raw threat 1, saturated 0.63.

## Caching

The four components change at very different rates, so each has its own
cache and is only recomputed when its inputs change. Composing a new
`SpatialField` happens only when any component was rebuilt.

| Component | Rebuilt when |
| --- | --- |
| static (lattice points, choke values) | the lattice or chokes change version, the spacing changes, or -- with no lattice yet -- the map centre changes |
| friendly | the set of own bases (id, position, main flag) changes |
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
| `SpatialDebugView` | sample positions and spacing for the grid view |

## Cost

On the last recorded game (spacing 2, 3094 samples):

- A frame where every cache holds costs about 0.01 ms.
- Late in that game `spatial.perf` showed 2281 route rebuilds and 2914
  friendly rebuilds by 530 s of game time, with a route rebuild costing about
  140 ms. At roughly 11 frames per second that is a rebuild on about every
  other frame: the traffic routes or the base set are producing a new version
  far more often than the map actually changes. Worth investigating in the
  adapter (`_ground_traffic_routes` signature) and in what changes the base
  key.

## Known gaps

- The field is ground only; flying units path over nothing it describes.
- Threat counts every armed enemy cluster regardless of which domain it can
  attack; readers that care (the raids) use the clusters directly.
