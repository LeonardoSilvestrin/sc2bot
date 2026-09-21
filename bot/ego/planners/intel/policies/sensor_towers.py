"""A persistent late-game sensor barrier, independent of Awareness.

Air ignores terrain, so the barrier is judged over the whole playable area:
every own base must be cut off from the enemy start by radar, either inside a
tower's radius or behind a chain of overlapping radii that runs from map edge
to map edge. The planner asks for the fewest new towers that close it,
standing on the 2x2 spots Ares solved at our bases (the main's included), and
counts the towers already standing, unfinished ones too. Among equally short
chains it leans toward the enemy, for earlier warning, and away from overlap.
"""

from __future__ import annotations

import heapq
import math
from functools import lru_cache

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.attention import AttentionState, BaseView
from bot.ego.planners import SensorTowerPlan, SensorTowerSite

MIN_BASES = 4
# A Sensor Tower's radar_range, as the game reports it.
RADAR_RADIUS = 22.0
# Slack for a tower landing off its spot: radii overlap each other, and reach
# a base or the map edge, by this much.
SLACK = 2.0
REACH = RADAR_RADIUS - SLACK
LINK = 2 * RADAR_RADIUS - SLACK
# Candidate spots per base: the farthest out in each angular sector.
SECTORS = 12
OVERLAP_WEIGHT = 0.01
FORWARD_WEIGHT = 0.05
SENSOR_TOWERS = frozenset({UnitTypeId.SENSORTOWER})
ENGINEERING_BAYS = frozenset({UnitTypeId.ENGINEERINGBAY})


def plan(attention: AttentionState) -> SensorTowerPlan:
    towers = _towers(attention)
    missing = sensor_tower_sites(attention)
    engineering_bay = bool(missing) and not any(
        structure.type_id in ENGINEERING_BAYS for structure in attention.own_structures
    )
    if not attention.bases:
        reason = "no_bases"
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
            ("towers", float(len(towers))),
            ("missing_towers", float(len(missing))),
        ),
    )


def sensor_tower_sites(attention: AttentionState) -> tuple[SensorTowerSite, ...]:
    """The towers still missing, the ones nearest our start first."""

    map_view = attention.map
    return _barrier(
        map_view.bounds,
        map_view.own_start,
        map_view.enemy_start,
        map_view.tower_sites
        if attention.available_tower_sites is None
        else attention.available_tower_sites,
        tuple(sorted(attention.bases, key=lambda base: base.base_id)),
        _towers(attention),
    )


def _towers(attention: AttentionState) -> tuple[Point2, ...]:
    return tuple(
        sorted(
            (
                structure.position
                for structure in attention.own_structures
                if structure.type_id in SENSOR_TOWERS
            ),
            key=lambda point: (point.x, point.y),
        )
    )


@lru_cache(maxsize=8)
def _barrier(
    bounds: tuple[float, float, float, float],
    own: Point2,
    enemy: Point2,
    tower_sites: tuple[tuple[Point2, tuple[Point2, ...]], ...],
    bases: tuple[BaseView, ...],
    towers: tuple[Point2, ...],
) -> tuple[SensorTowerSite, ...]:
    # A base a standing tower already watches needs no chain.
    exposed = [
        base.position
        for base in bases
        if all(base.position.distance_to(tower) > REACH for tower in towers)
    ]
    if not exposed:
        return ()
    spots = [
        SensorTowerSite(base.base_id, key, spot)
        for base in bases
        for key, spot in _spots(tower_sites, base.position)
    ]
    nodes = [*towers, *(site.target for site in spots)]
    span = max(enemy.distance_to(position) for position in exposed)
    cost = [0.0] * len(towers) + [
        1.0 + FORWARD_WEIGHT * site.target.distance_to(enemy) / span for site in spots
    ]
    chain = _chain(bounds, enemy, exposed, nodes, cost)
    wanted = [spots[index - len(towers)] for index in chain if index >= len(towers)]
    closed = [*towers, *(site.target for site in wanted)]
    for position in exposed:
        mine = [site for site in spots if site.target.distance_to(position) <= REACH]
        if not mine or _sealed(bounds, enemy, position, closed):
            continue
        # No chain closes this base: a tower of its own watches it.
        site = min(
            mine,
            key=lambda site: (site.target.distance_to(enemy), site.target.x, site.target.y),
        )
        wanted.append(site)
        closed.append(site.target)
    unique = {(site.target.x, site.target.y): site for site in wanted}
    return tuple(
        sorted(
            unique.values(),
            key=lambda site: (site.target.distance_to(own), site.target.x, site.target.y),
        )
    )


def _spots(
    tower_sites: tuple[tuple[Point2, tuple[Point2, ...]], ...], position: Point2
) -> list[tuple[Point2, Point2]]:
    if not tower_sites:
        return []
    key, spots = min(
        tower_sites, key=lambda item: (item[0].distance_to(position), item[0].x, item[0].y)
    )
    outermost: dict[int, Point2] = {}
    for spot in spots:
        angle = math.atan2(spot.y - position.y, spot.x - position.x)
        sector = int((angle + math.pi) / (2 * math.pi) * SECTORS) % SECTORS
        best = outermost.get(sector)
        if best is None or spot.distance_to(position) > best.distance_to(position):
            outermost[sector] = spot
    return [(key, outermost[sector]) for sector in sorted(outermost)]


def _chain(
    bounds: tuple[float, float, float, float],
    enemy: Point2,
    exposed: list[Point2],
    nodes: list[Point2],
    cost: list[float],
) -> list[int]:
    """Cheapest chain of nodes, edge to edge, that best cuts the exposed bases
    off from the enemy.

    A closed curve through the chain separates a base from the enemy exactly
    when it crosses their segment an odd number of times; the search carries
    that parity per base. Closing along the map edge crosses nothing, and a
    node's own radius may wrap around any base inside it. A base the chain
    leaves open is priced as a tower of its own, a little behind any chain.
    """

    alone = 1.0 + FORWARD_WEIGHT

    def crossed(start: Point2, end: Point2) -> int:
        return sum(
            1 << bit
            for bit, position in enumerate(exposed)
            if _crosses(start, end, enemy, position)
        )

    exits = [[crossed(node, edge) for edge in _edges(node, bounds)] for node in nodes]
    wraps = [
        [1 << bit for bit, position in enumerate(exposed) if node.distance_to(position) <= REACH]
        for node in nodes
    ]
    links: list[list[tuple[int, int, float]]] = [[] for _ in nodes]
    for i, first in enumerate(nodes):
        for j in range(i + 1, len(nodes)):
            gap = first.distance_to(nodes[j])
            if gap <= LINK:
                mask = crossed(first, nodes[j])
                overlap = OVERLAP_WEIGHT * (2 * RADAR_RADIUS - gap) / (2 * RADAR_RADIUS)
                links[i].append((j, mask, overlap))
                links[j].append((i, mask, overlap))

    # State: (node, parity, entry edge while the chain is that one node).
    best: dict[tuple[int, int, int], float] = {}
    previous: dict[tuple[int, int, int], tuple[int, int, int] | None] = {}
    heap: list[tuple[float, tuple[int, int, int]]] = []

    def push(state, value, parent) -> None:
        if value < best.get(state, math.inf):
            best[state] = value
            previous[state] = parent
            heapq.heappush(heap, (value, state))

    for node, masks in enumerate(exits):
        for edge, mask in enumerate(masks):
            push((node, mask, edge), cost[node], None)
    total = alone * len(exposed)
    closing: tuple[int, int, int] | None = None
    while heap:
        value, state = heapq.heappop(heap)
        if value >= total:
            break
        if value > best.get(state, math.inf):
            continue
        node, parity, entry = state
        for edge, mask in enumerate(exits[node]):
            if edge == entry and previous[state] is None:
                continue
            open_bases = len(exposed) - bin(parity ^ mask).count("1")
            if value + alone * open_bases < total:
                total, closing = value + alone * open_bases, state
        for bit in wraps[node]:
            push((node, parity ^ bit, entry), value, state)
        for neighbour, mask, overlap in links[node]:
            push((neighbour, parity ^ mask, -1), value + cost[neighbour] + overlap, state)
    chain: list[int] = []
    while closing is not None:
        if not chain or chain[-1] != closing[0]:
            chain.append(closing[0])
        closing = previous[closing]
    return chain[::-1]


def _sealed(
    bounds: tuple[float, float, float, float],
    enemy: Point2,
    position: Point2,
    towers: list[Point2],
) -> bool:
    """Whether some chain among ``towers`` already closes ``position``."""

    if any(tower.distance_to(position) <= REACH for tower in towers):
        return True
    return _chain(bounds, enemy, [position], towers, [0.0] * len(towers)) != []


def _edges(node: Point2, bounds: tuple[float, float, float, float]) -> list[Point2]:
    """Where this node's radius meets the map edge."""

    min_x, min_y, max_x, max_y = bounds
    return [
        edge
        for gap, edge in (
            (node.x - min_x, Point2((min_x, node.y))),
            (max_x - node.x, Point2((max_x, node.y))),
            (node.y - min_y, Point2((node.x, min_y))),
            (max_y - node.y, Point2((node.x, max_y))),
        )
        if gap <= REACH
    ]


def _crosses(start: Point2, end: Point2, first: Point2, second: Point2) -> bool:
    def side(a: Point2, b: Point2, c: Point2) -> float:
        return (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)

    return (side(first, second, start) > 0) != (side(first, second, end) > 0) and (
        side(start, end, first) > 0
    ) != (side(start, end, second) > 0)
