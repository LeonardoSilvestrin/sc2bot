"""Intel: one SCV looks at the enemy main early in the game.

Once the mineral line reaches `SCOUT_AT_WORKERS`, Intel asks for one SCV and
sends it through the enemy main: the start location first, then a lap along
the edge of the main's region, one waypoint per angular sector, beginning on
the side it arrives from. A waypoint counts as seen the first time it is in
vision. The scout goes back to mining once every waypoint was seen or
`LAP_TIMEOUT` after it set out; a dead scout is not replaced, and a mineral
line that has not grown by `START_BY` sends no scout at all.

Priority is the share of the route still unseen. Workers are a pool of their
own in the Engine, so it only orders the log.
"""

from __future__ import annotations

import math

from ares.consts import UnitRole
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.attention import AttentionState, MapView
from bot.ego.planners import Command, Proposal

OWNER = "intel"
SCOUT_TYPES = frozenset({UnitTypeId.SCV})
# Right after the opening's first Barracks.
SCOUT_AT_WORKERS = 16
# Past this, a first look at the main is no longer early-game information.
START_BY = 240.0
# A scout that cannot finish the lap by then (a wall, a chase) goes home.
LAP_TIMEOUT = 90.0
LAP_SECTORS = 8


class Intel:
    def __init__(self) -> None:
        self.route: tuple[Point2, ...] = ()
        self.seen: set[int] = set()
        self.set_out: float | None = None
        # Why scouting is over; None while it is not.
        self.finished: str | None = None

    def plan(self, attention: AttentionState) -> tuple[Proposal, ...]:
        if self.finished is not None:
            return ()
        if not self.route:
            self.route = scouting_route(attention.map)
        now = attention.time
        # The scout behavior gives whoever the Engine granted the SCOUTING role.
        scouting = any(
            unit.type_id in SCOUT_TYPES and unit.role == UnitRole.SCOUTING.name
            for unit in attention.own_units
        )
        self.seen.update(
            index for index, point in enumerate(self.route) if attention.is_visible(point)
        )
        if len(self.seen) == len(self.route):
            return self._finish("route_seen")
        if self.set_out is None and scouting:
            self.set_out = now
        if self.set_out is None:
            if now >= START_BY:
                return self._finish("too_late")
            if attention.workers < SCOUT_AT_WORKERS:
                return ()
        elif not scouting:
            return self._finish("scout_lost")
        elif now - self.set_out >= LAP_TIMEOUT:
            return self._finish("lap_timed_out")
        waypoint = min(set(range(len(self.route))) - self.seen)
        return (
            Proposal(
                proposal_id=OWNER,
                owner=OWNER,
                priority=(len(self.route) - len(self.seen)) / len(self.route),
                command=Command.SCOUT,
                target=self.route[waypoint],
                reason="scout_enemy_start" if waypoint == 0 else "lap_enemy_main",
                count=1,
                unit_types=SCOUT_TYPES,
                inputs=(
                    ("workers", float(attention.workers)),
                    ("waypoint", float(waypoint)),
                    ("seen", float(len(self.seen))),
                    ("waypoints", float(len(self.route))),
                    ("scouting_for", 0.0 if self.set_out is None else now - self.set_out),
                ),
            ),
        )

    def _finish(self, reason: str) -> tuple[Proposal, ...]:
        self.finished = reason
        return ()


def scouting_route(map_view: MapView) -> tuple[Point2, ...]:
    """The enemy start, then the farthest sample of its region per sector,
    counter-clockwise from the direction of our own start."""

    start = map_view.enemy_start
    topology = map_view.topology
    region = (
        None
        if topology.enemy_start_region is None
        else topology.region(topology.enemy_start_region)
    )
    if region is None:
        return (start,)
    arrival = math.atan2(map_view.own_start.y - start.y, map_view.own_start.x - start.x)
    edge: dict[int, Point2] = {}
    for index in region.sample_indices:
        point = map_view.lattice[index]
        angle = (math.atan2(point.y - start.y, point.x - start.x) - arrival) % math.tau
        sector = int(angle / math.tau * LAP_SECTORS) % LAP_SECTORS
        best = edge.get(sector)
        if best is None or (point.distance_to(start), point.x, point.y) > (
            best.distance_to(start),
            best.x,
            best.y,
        ):
            edge[sector] = point
    return (start, *(edge[sector] for sector in sorted(edge)))
