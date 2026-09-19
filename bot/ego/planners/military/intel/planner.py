"""IntelPlanner: whether to scout. How the scout goes is
`missions.scout.ScoutMission`.

A scouting operation opens once the mineral line reaches `SCOUT_AT_WORKERS`
and before `START_BY`. The planner asks a scout that has not set out yet to
cancel if the mineral line falls back below the mark (a new one opens once it
is back) or once `START_BY` passes. A scout that set out is never replaced:
whatever ends it, scouting is over.

A waypoint counts as seen the first time it is in vision, whether a scout is
out or not: the planner keeps the route and that memory from the first frame.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from sc2.position import Point2

from bot.attention import AttentionState, MapView
from bot.ego.missions import (
    CancelMode,
    MissionFeedback,
    MissionView,
)
from bot.ego.planners import Proposal

from .missions.scout import KIND, OWNER, ScoutMission

if TYPE_CHECKING:
    from bot.body.engine import EngineResult


# Right after the opening's first Barracks.
SCOUT_AT_WORKERS = 16
# Past this, a first look at the main is no longer early-game information.
START_BY = 240.0
LAP_SECTORS = 8
# A scout cancelled for this before setting out leaves scouting open.
_REOPENS = "workers_below_threshold"


class IntelPlanner:
    def __init__(self) -> None:
        self.route: tuple[Point2, ...] = ()
        # The route's waypoints seen so far, by index.
        self.seen: set[int] = set()
        self.mission: ScoutMission | None = None
        # Why scouting is over; None while it is not.
        self.finished: str | None = None
        self._opened = 0
        self._views: tuple[MissionView, ...] = ()

    def views(self) -> tuple[MissionView, ...]:
        """The missions this frame's `plan` governed, as they left it."""

        return self._views

    def plan(
        self, attention: AttentionState, feedback: EngineResult | None = None
    ) -> tuple[Proposal, ...]:
        """`feedback`: the last `EngineResult`, or None before the first."""

        self._views = ()
        if self.finished is not None:
            return ()
        if not self.route:
            self.route = scouting_route(attention.map)
        now = attention.time
        self.seen.update(
            index for index, point in enumerate(self.route) if attention.is_visible(point)
        )
        mission = self.mission
        if mission is None:
            if len(self.seen) == len(self.route):
                self.finished = "route_seen"
                return ()
            if now >= START_BY:
                self.finished = "too_late"
                return ()
            if attention.workers < SCOUT_AT_WORKERS:
                return ()
            self._opened += 1
            mission = ScoutMission(f"{OWNER}:{KIND}:{self._opened}", self.route, now)
            self.mission = mission
        else:
            mission.observe(attention)
            if mission.set_out is None and len(self.seen) < len(self.route):
                if now >= START_BY:
                    mission.request_cancel(CancelMode.IMMEDIATE, "too_late", now)
                elif attention.workers < SCOUT_AT_WORKERS:
                    mission.request_cancel(CancelMode.IMMEDIATE, _REOPENS, now)
        granted = MissionFeedback.of(feedback, mission.mission_id)
        proposals = mission.step(attention, frozenset(self.seen), granted)
        self._views = (mission.view(granted, proposals),)
        if not mission.active:
            self.mission = None
            if mission.reason != _REOPENS:
                self.finished = mission.reason
        return proposals



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
