"""Where a proxy would be, if there is one.

A proxy is built on our half of the map, close enough to reach us and far
enough from our units not to be seen: the pockets next to our main and our
natural, and the flat ground of the expansions on our side. `proxy_route`
orders those places outwards from our main, which is also the order a scout
walking home from the enemy base crosses them in reverse.

Everything here comes from the static map (`MapView` and its `MapTopology`).
Whether a proxy is suspected at all is Awareness' reading of the opening; this
policy only answers where to look.
"""

from __future__ import annotations

from sc2.position import Point2

from bot.attention import EXPANSION_GAP, MapView

# How many places one search visits: a scout that walks further than this is
# no longer scouting an opening.
PROXY_LIMIT = 6


def proxy_route(map_view: MapView, limit: int = PROXY_LIMIT) -> tuple[Point2, ...]:
    """The places on our half worth a look, nearest our main first."""

    topology = map_view.topology
    own, enemy = map_view.own_start, map_view.enemy_start
    candidates: list[Point2] = []
    for region_id in _neighbourhood(map_view):
        region = topology.region(region_id)
        if region is not None:
            candidates.append(region.center)
    candidates.extend(map_view.expansions)
    ours = {
        point
        for point in candidates
        # Our half, and outside what our own base already sees.
        if point.distance_to(own) < point.distance_to(enemy)
        and point.distance_to(own) > EXPANSION_GAP
    }
    return tuple(sorted(ours, key=lambda point: (point.distance_to(own), point.x, point.y))[:limit])


def _neighbourhood(map_view: MapView) -> tuple[str, ...]:
    """The regions around our main and our natural."""

    topology = map_view.topology
    home = [topology.own_start_region, topology.expansion_region(map_view.own_start)]
    natural = map_view.own_natural
    if natural is not None:
        home.append(topology.expansion_region(natural))
    around: list[str] = []
    for region_id in dict.fromkeys(region for region in home if region is not None):
        around.append(region_id)
        around.extend(neighbour for neighbour, _ in topology.neighbours(region_id))
    return tuple(dict.fromkeys(around))
