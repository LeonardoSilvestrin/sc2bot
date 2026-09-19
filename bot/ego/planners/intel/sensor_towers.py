"""A persistent late-game sensor barrier, independent of Awareness.

The towers stand across the enemy's approach: one at each laterally outermost
base -- lateral to the line from our start to the enemy's -- and one midway
between those two. The main keeps none.
"""

from __future__ import annotations

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.attention import AttentionState, BaseView
from bot.ego.planners import SensorTowerPlan, SensorTowerSite

MIN_BASES = 4
TOWER_OFFSET = 9.0
SITE_COVER_RADIUS = 12.0
MIDDLE_SITE = "middle"
SENSOR_TOWERS = frozenset({UnitTypeId.SENSORTOWER})
ENGINEERING_BAYS = frozenset({UnitTypeId.ENGINEERINGBAY})


def plan(attention: AttentionState) -> SensorTowerPlan:
    sites = sensor_tower_sites(attention)
    towers = [
        structure.position
        for structure in attention.own_structures
        if structure.type_id in SENSOR_TOWERS
    ]
    missing = tuple(
        site
        for site in sites
        if not any(
            site.target.distance_to(tower) <= SITE_COVER_RADIUS for tower in towers
        )
    )
    engineering_bay = bool(missing) and not any(
        structure.type_id in ENGINEERING_BAYS for structure in attention.own_structures
    )
    if not sites:
        reason = "no_barrier_bases"
    elif not missing:
        reason = "sensor_network_covered"
    else:
        reason = "engineering_bay_needed" if engineering_bay else "sensor_tower_needed"
    return SensorTowerPlan(
        sites=missing,
        engineering_bay=engineering_bay,
        reason=reason,
        inputs=(
            ("bases", float(len(attention.bases))),
            ("sites", float(len(sites))),
            ("missing_towers", float(len(missing))),
        ),
    )


def sensor_tower_sites(attention: AttentionState) -> tuple[SensorTowerSite, ...]:
    """The middle site first, then the flank sites by id."""

    map_view = attention.map
    own, enemy = map_view.own_start, map_view.enemy_start
    candidates = [base for base in attention.bases if not base.is_main]
    if not candidates:
        return ()

    def lateral(base: BaseView) -> float:
        dx, dy = base.position.x - own.x, base.position.y - own.y
        return (enemy.x - own.x) * dy - (enemy.y - own.y) * dx

    ordered = sorted(candidates, key=lambda base: (lateral(base), base.base_id))
    ends = {base.base_id: base for base in (ordered[0], ordered[-1])}
    flanks = [_flank(ends[base_id], attention) for base_id in sorted(ends)]
    if len(flanks) < 2:
        return tuple(flanks)
    first, second = flanks
    middle = Point2(
        (
            (first.target.x + second.target.x) / 2,
            (first.target.y + second.target.y) / 2,
        )
    )
    main_anchor = min(
        map_view.expansions,
        key=lambda point: (point.distance_to(own), point.x, point.y),
        default=None,
    )
    anchor = min(
        (point for point in map_view.expansions if point != main_anchor),
        key=lambda point: (point.distance_to(middle), point.x, point.y),
        default=middle,
    )
    return (SensorTowerSite(MIDDLE_SITE, anchor, middle), first, second)


def _flank(base: BaseView, attention: AttentionState) -> SensorTowerSite:
    own = attention.map.own_start
    outward = Point2(
        (
            base.position.x + (base.position.x - own.x),
            base.position.y + (base.position.y - own.y),
        )
    )
    target = base.position.towards(outward, TOWER_OFFSET)
    min_x, min_y, max_x, max_y = attention.map.bounds
    target = Point2(
        (
            min(max(target.x, min_x + 1.0), max_x - 1.0),
            min(max(target.y, min_y + 1.0), max_y - 1.0),
        )
    )
    return SensorTowerSite(base.base_id, base.position, target)
